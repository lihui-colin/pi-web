import asyncio
import base64
import json
import os
from pathlib import Path
import struct
import tempfile
import threading
import time
import unittest
import uuid

from websockets.asyncio.client import connect
from websockets.asyncio.server import serve
from websockets.exceptions import ConnectionClosed, InvalidStatus

from server import Service, VoiceError, decode
from settings import config
from manage import identity, running, stop


def frame(pcm=None, final=False, **changes):
    value = dict(task_id='2d3b557a-7d8c-4df4-bd12-7187dc22bfbb', source='mic',
                 time_start=1792215200, seg_duration=15, seg_overlap=2,
                 context='', language='auto', is_final=final,
                 data=base64.b64encode(struct.pack('<1600f', *([.1]*1600)) if pcm is None else pcm).decode())
    value.update(changes)
    return json.dumps(value)


class Backend:
    def __init__(self):
        self.calls = []
        self.gate = threading.Event()
        self.gate.set()
        self.entered = threading.Event()
        self.cleared = 0
        self.text = '测试。'

    def process(self, data, offset, final, identity):
        self.calls.append((len(data), offset, final, identity))
        self.entered.set()
        self.gate.wait(10)
        return dict(task_id=identity[0], text=self.text, is_final=final)

    def clear(self):
        self.cleared += 1


class ProtocolTests(unittest.TestCase):
    def test_valid_and_empty_tail(self):
        ident, data, final = decode(frame(), None)
        self.assertEqual(len(data), 6400)
        self.assertFalse(final)
        self.assertEqual(decode(frame(b'', True), ident), (ident, b'', True))

    def test_invalid_inputs(self):
        bad = [b'{}', '[]', '{}', 'null', frame(b'\0'), frame(b''), frame(b'\0'*6404),
               frame(struct.pack('<f', float('nan'))), frame(struct.pack('<f', float('inf'))),
               frame(struct.pack('<f', 1.1)), frame(data='!'), frame(data='AB=='),
               frame(source='file'), frame(context='secret'), frame(language='en'),
               frame(is_final=1), frame(task_id='no'), frame(time_start=True),
               frame(time_start=float('inf')), frame(seg_overlap=5), frame(extra='x')]
        for raw in bad:
            with self.subTest(raw=raw[:80]):
                with self.assertRaisesRegex(VoiceError, 'AUDIO_INVALID'):
                    decode(raw, None)
        with self.assertRaises(VoiceError):
            decode(frame(), ('another-task', 1792215200))

    def test_config(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            good = dict(host='127.0.0.1', port=6016, threads=4, max_seconds=120, final_timeout_seconds=30)
            for changes in [dict(host='0.0.0.0'), dict(port=True), dict(threads=0), dict(max_seconds=121), dict(extra=1)]:
                path.write_text(json.dumps(good | changes))
                with self.assertRaises(ValueError):
                    config(path)
            path.write_text(json.dumps(good))
            self.assertEqual(config(path), good)

    def test_stale_pid_is_never_signalled(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            record = dict(pid=os.getpid(), start='wrong')
            (root / 'pid.json').write_text(json.dumps(record))
            self.assertIsNone(running(root))
            stop(root, record)
            self.assertIsNotNone(identity(os.getpid()))


class ServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.backend = Backend()
        self.service = Service(self.backend, dict(max_seconds=120, final_timeout_seconds=1))
        self.server = await serve(self.service.handle, '127.0.0.1', 0,
                                  subprotocols=['binary'], process_request=self.service.http,
                                  max_size=16384, max_queue=1, compression=None, close_timeout=.1)
        self.url = f'ws://127.0.0.1:{self.server.sockets[0].getsockname()[1]}/'

    async def asyncTearDown(self):
        self.backend.gate.set()
        self.server.close()
        await self.server.wait_closed()

    def client(self, **kwargs):
        return connect(self.url, subprotocols=['binary'], proxy=None, compression=None, **kwargs)

    async def until(self, predicate):
        async with asyncio.timeout(3):
            while not predicate():
                await asyncio.sleep(.01)

    async def test_final_and_cleanup(self):
        async with self.client() as ws:
            await ws.send(frame())
            await ws.send(frame(b'', True))
            result = json.loads(await ws.recv())
            self.assertEqual(result['text'], '测试。')
            self.assertTrue(result['is_final'])
            with self.assertRaises(ConnectionClosed):
                await ws.recv()
        await self.until(lambda: not self.service.busy)
        self.assertIsNotNone(self.service.last_success)
        self.assertEqual(self.backend.cleared, 1)

    async def test_global_busy(self):
        async with self.client():
            async with self.client() as second:
                self.assertEqual(json.loads(await second.recv()), {'error': 'ASR_BUSY'})
        await self.until(lambda: not self.service.busy)

    async def test_disconnect_retains_admission_until_native_work_finishes(self):
        self.backend.gate.clear()
        async with self.client() as ws:
            await ws.send(frame(final=True))
            await self.until(self.backend.entered.is_set)
        self.assertTrue(self.service.busy)
        async with self.client() as other:
            self.assertEqual(json.loads(await other.recv())['error'], 'ASR_BUSY')
        self.backend.gate.set()
        await self.until(lambda: not self.service.busy)
        self.assertIsNone(self.service.last_success)

    async def test_final_timeout_and_recovery(self):
        self.backend.gate.clear()
        async with self.client() as ws:
            await ws.send(frame(final=True))
            self.assertEqual(json.loads(await ws.recv())['error'], 'ASR_TIMEOUT')
        self.assertTrue(self.service.busy)
        self.backend.gate.set()
        await self.until(lambda: not self.service.busy)

    async def test_no_speech_invalid_and_limit(self):
        for raw, code in [(frame(b'', True), 'NO_SPEECH'), ('{}', 'AUDIO_INVALID')]:
            async with self.client() as ws:
                await ws.send(raw)
                self.assertEqual(json.loads(await ws.recv())['error'], code)
            await self.until(lambda: not self.service.busy)
        self.service.settings['max_seconds'] = .05
        async with self.client() as ws:
            await ws.send(frame())
            self.assertEqual(json.loads(await ws.recv())['error'], 'AUDIO_TOO_LONG')

    async def test_empty_recognition(self):
        self.backend.text = ''
        async with self.client() as ws:
            await ws.send(frame(final=True))
            self.assertEqual(json.loads(await ws.recv())['error'], 'NO_SPEECH')

    async def test_browser_origin_rejected(self):
        with self.assertRaises(InvalidStatus):
            async with self.client(origin='https://example.org'):
                pass

    async def test_segment_overlap_and_cumulative_results(self):
        async with self.client() as ws:
            for _ in range(190):
                await ws.send(frame())
                await asyncio.sleep(.001)
            result = json.loads(await ws.recv())
            self.assertFalse(result['is_final'])
            await ws.send(frame(b'', True))
            result = json.loads(await ws.recv())
            self.assertTrue(result['is_final'])
        self.assertEqual([(c[0], c[1], c[2]) for c in self.backend.calls],
                         [(17*64000, 0, False), (4*64000, 15, True)])

    async def test_queue_overflow_during_inference(self):
        self.backend.gate.clear()
        async with self.client() as ws:
            for _ in range(190):
                await ws.send(frame())
                await asyncio.sleep(.001)
            await self.until(self.backend.entered.is_set)
            for _ in range(20):
                await ws.send(frame())
                await asyncio.sleep(.001)
            self.assertEqual(json.loads(await ws.recv())['error'], 'QUEUE_OVERFLOW')
        self.assertTrue(self.service.busy)
        self.backend.gate.set()

    async def test_no_audio_timeout_releases_admission(self):
        async with self.client() as ws:
            self.assertEqual(json.loads(await ws.recv())['error'], 'ASR_TIMEOUT')
        await self.until(lambda: not self.service.busy)
        self.assertEqual(self.backend.calls, [])

    async def test_oversize_message_is_closed(self):
        async with self.client() as ws:
            await ws.send('x' * 16385)
            with self.assertRaises(ConnectionClosed) as closed:
                await ws.recv()
            self.assertEqual(closed.exception.rcvd.code, 1009)
        await self.until(lambda: not self.service.busy)

    async def test_inference_failure_is_sanitized(self):
        def fail(*args):
            raise RuntimeError('private transcript')
        self.backend.process = fail
        async with self.client() as ws:
            await ws.send(frame(final=True))
            self.assertEqual(json.loads(await ws.recv()), {'error': 'ASR_FAILED'})


if __name__ == '__main__':
    unittest.main()
