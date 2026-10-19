"""Real PCM16 WAV probe. Text output requires explicit --show-text."""
import argparse
import asyncio
import base64
import json
from pathlib import Path
import time
import uuid
import wave

import numpy as np
from websockets.asyncio.client import connect
from settings import config


async def probe(path, settings, show=False, expect=None):
    with wave.open(str(path), 'rb') as wav:
        if (wav.getframerate(), wav.getnchannels(), wav.getsampwidth(), wav.getcomptype()) != (16000, 1, 2, 'NONE'):
            raise ValueError('Expected 16 kHz mono PCM16 WAV')
        if wav.getnframes() > 16000 * settings['max_seconds']:
            raise ValueError('Audio exceeds configured duration')
        pcm = (np.frombuffer(wav.readframes(wav.getnframes()), dtype='<i2').astype('<f4') / 32768).tobytes()
    host = settings['host']
    host = f'[{host}]' if ':' in host else host
    started = time.monotonic()
    stopped = None
    partials = 0
    message = dict(task_id=str(uuid.uuid4()), source='mic', time_start=time.time(),
                   seg_duration=15.0, seg_overlap=2.0, context='', language='auto')
    async with connect(f'ws://{host}:{settings["port"]}/', subprotocols=['binary'],
                       proxy=None, max_size=65536, compression=None) as ws:
        async def send():
            nonlocal stopped
            for offset in range(0, len(pcm), 6400):
                await ws.send(json.dumps(dict(message, data=base64.b64encode(pcm[offset:offset+6400]).decode(), is_final=False)))
                await asyncio.sleep(.1)
            stopped = time.monotonic()
            await ws.send(json.dumps(dict(message, data='', is_final=True)))
        sender = asyncio.create_task(send())
        try:
            async with asyncio.timeout(settings['max_seconds'] + settings['final_timeout_seconds'] + 5):
                async for raw in ws:
                    result = json.loads(raw)
                    if 'error' in result:
                        raise RuntimeError(result['error'])
                    if result.get('task_id') != message['task_id']:
                        raise RuntimeError('Unexpected task ID')
                    if result.get('is_final'):
                        if not result['text'].strip() or (expect and expect not in result['text']):
                            raise RuntimeError('Recognition did not match expected text')
                        stats = dict(audio_seconds=len(pcm)/64000, elapsed_seconds=round(time.monotonic()-started, 3),
                                     stop_to_final_seconds=round(time.monotonic()-stopped, 3) if stopped else None,
                                     partial_results=partials, characters=len(result['text']))
                        if show:
                            stats['text'] = result['text']
                        print(json.dumps(stats, ensure_ascii=False))
                        return stats
                    partials += 1
                raise RuntimeError('Connection closed without final result')
        finally:
            sender.cancel()
            await asyncio.gather(sender, return_exceptions=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('wav', type=Path)
    parser.add_argument('--config', type=Path, default=Path(__file__).resolve().parents[2] / 'data/voice/config.json')
    parser.add_argument('--show-text', action='store_true')
    parser.add_argument('--expect')
    args = parser.parse_args()
    asyncio.run(probe(args.wav, config(args.config), args.show_text, args.expect))
