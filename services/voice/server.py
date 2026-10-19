"""Bounded, single-admission CapsWriter-compatible microphone service."""
import argparse
import asyncio
import base64
import binascii
import contextlib
import os
import json
import math
from pathlib import Path
import signal
import time
import uuid

import numpy as np
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed
from settings import config

RATE = 16000
BYTE_RATE = RATE * 4
FRAME_LIMIT = 16384


class VoiceError(Exception):
    pass


def decode(raw, identity):
    try:
        if not isinstance(raw, str) or len(raw.encode()) > FRAME_LIMIT:
            raise ValueError()
        msg = json.loads(raw)
        if not isinstance(msg, dict) or set(msg) != {
            'task_id', 'source', 'data', 'is_final', 'time_start',
            'seg_duration', 'seg_overlap', 'context', 'language'
        }:
            raise ValueError()
        if str(uuid.UUID(msg['task_id'])) != msg['task_id']:
            raise ValueError()
        if type(msg['time_start']) not in (int, float) or not math.isfinite(msg['time_start']) or msg['time_start'] <= 0:
            raise ValueError()
        current = (msg['task_id'], msg['time_start'])
        if identity is not None and current != identity:
            raise ValueError()
        if (msg['source'] != 'mic' or msg['context'] != '' or msg['language'] != 'auto'
                or msg['seg_duration'] != 15 or msg['seg_overlap'] != 2
                or type(msg['is_final']) is not bool or not isinstance(msg['data'], str)):
            raise ValueError()
        data = base64.b64decode(msg['data'], validate=True)
        if base64.b64encode(data).decode() != msg['data']:
            raise ValueError()
        if len(data) > 6400 or len(data) % 4 or (not data and not msg['is_final']):
            raise ValueError()
        samples = np.frombuffer(data, dtype='<f4')
        if not np.all(np.isfinite(samples)) or np.any(np.abs(samples) > 1):
            raise ValueError()
        return current, data, msg['is_final']
    except (ValueError, TypeError, KeyError, AttributeError, binascii.Error, OverflowError, RecursionError):
        raise VoiceError('AUDIO_INVALID') from None


class Service:
    def __init__(self, backend, settings):
        self.backend = backend
        self.settings = settings
        self.busy = False
        self.last_success = None
        self.last_error = None

    def health(self):
        return dict(ready=True, pid=os.getpid(), busy=self.busy, last_success=self.last_success,
                    last_error=self.last_error, model='paraformer-int8', protocol=1)

    async def http(self, connection, request):
        if request.headers.get_all('Origin'):
            return connection.respond(403, 'Browser connections are not supported\n')
        if request.path == '/healthz':
            response = connection.respond(200, json.dumps(self.health()) + '\n')
            response.headers['Content-Type'] = 'application/json'
            return response
        if request.path != '/':
            return connection.respond(404, 'Not found\n')

    async def error(self, ws, code):
        self.last_error = {'code': code, 'time': time.time()}
        with contextlib.suppress(ConnectionClosed, TimeoutError):
            async with asyncio.timeout(2):
                await ws.send(json.dumps({'error': code}))
        await ws.close(1013 if code == 'ASR_BUSY' else 1008, code)

    async def handle(self, ws):
        if self.busy:
            await self.error(ws, 'ASR_BUSY')
            return
        self.busy = True
        queue = asyncio.Queue(maxsize=19)
        identity = None
        total = 0
        finished = False
        last_frame = time.monotonic()
        started = last_frame
        final_at = None
        inference = None
        tasks = []

        async def receive():
            nonlocal identity, total, finished, last_frame, final_at
            async for raw in ws:
                if finished:
                    raise VoiceError('AUDIO_INVALID')
                identity, data, final = decode(raw, identity)
                total += len(data)
                if total > self.settings['max_seconds'] * BYTE_RATE:
                    raise VoiceError('AUDIO_TOO_LONG')
                last_frame = time.monotonic()
                if final:
                    finished = True
                    final_at = last_frame
                    if not total:
                        raise VoiceError('NO_SPEECH')
                try:
                    queue.put_nowait((data, final))
                except asyncio.QueueFull:
                    raise VoiceError('QUEUE_OVERFLOW') from None

        async def process():
            nonlocal inference
            buffer = bytearray()
            offset = 0
            while True:
                data, final = await queue.get()
                buffer.extend(data)
                if not final and len(buffer) < 19 * BYTE_RATE:
                    continue
                chunk = bytes(buffer if final else buffer[:17 * BYTE_RATE])
                if not final:
                    del buffer[:15 * BYTE_RATE]
                inference = asyncio.create_task(asyncio.to_thread(
                    self.backend.process, chunk, offset, final, identity))
                result = await asyncio.shield(inference)
                inference = None
                text = result.get('text')
                if not isinstance(text, str) or len(text.encode()) > 32768:
                    raise VoiceError('ASR_FAILED')
                if final and not text.strip():
                    raise VoiceError('NO_SPEECH')
                await ws.send(json.dumps(result, ensure_ascii=False))
                if final:
                    self.last_success = {'time': time.time(), 'audio_seconds': total / BYTE_RATE}
                    return
                offset += 15

        async def watchdog():
            while True:
                now = time.monotonic()
                if final_at is not None:
                    expired = now - final_at > self.settings['final_timeout_seconds']
                else:
                    expired = now - last_frame > 5 or now - started > self.settings['max_seconds'] + 5
                if expired:
                    raise VoiceError('ASR_TIMEOUT')
                await asyncio.sleep(0.1)

        try:
            tasks = [asyncio.create_task(fn()) for fn in (receive, process, watchdog)]
            done, _ = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
            for task in done:
                task.result()
        except VoiceError as exc:
            await self.error(ws, str(exc))
        except ConnectionClosed:
            pass
        except Exception:
            # Never log exception messages: upstream exceptions may contain text.
            await self.error(ws, 'ASR_FAILED')
        finally:
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await ws.close()
            # Cancelling to_thread cannot stop native inference. Keep admission
            # occupied until it actually exits, including disconnects/timeouts.
            if inference is not None:
                with contextlib.suppress(Exception):
                    await asyncio.shield(inference)
            self.backend.clear()
            self.busy = False


async def run(root):
    from assets import verify
    from backend import Backend
    settings = config(root / 'config.json')
    verify(root)
    backend = Backend(root, settings['threads'])
    service = Service(backend, settings)
    stop = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, stop.set)
    async with serve(service.handle, settings['host'], settings['port'],
                     subprotocols=['binary'], process_request=service.http,
                     max_size=FRAME_LIMIT, max_queue=1, compression=None,
                     open_timeout=5, close_timeout=1, write_limit=16384):
        print(json.dumps({'event': 'ready', 'port': settings['port']}), flush=True)
        await stop.wait()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    args = parser.parse_args()
    try:
        asyncio.run(run(args.root.resolve()))
    except Exception as exc:
        print(json.dumps({'event': 'startup_failed', 'kind': type(exc).__name__, 'message': str(exc)}), flush=True)
        raise SystemExit(1)
