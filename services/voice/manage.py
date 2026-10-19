"""Linux process management, serialized across install/start/stop."""
import argparse
import contextlib
import fcntl
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time
import urllib.request

from assets import HERE, install, verify as verify_assets
from settings import config


def identity(pid):
    try:
        # comm may contain spaces or parentheses; fields after the last ')'.
        fields = Path(f'/proc/{pid}/stat').read_text().rsplit(')', 1)[1].split()
        return None if fields[0] == 'Z' else fields[19]
    except (FileNotFoundError, ProcessLookupError):
        return None


def running(root):
    try:
        record = json.loads((root / 'pid.json').read_text())
        if (type(record['pid']) is int and record['pid'] > 1
                and isinstance(record['start'], str) and record['start']
                and identity(record['pid']) == record['start']):
            return record
    except (FileNotFoundError, ValueError, KeyError, TypeError):
        pass
    return None


def health(settings):
    host = settings['host']
    if ':' in host:
        host = '[' + host + ']'
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    with opener.open(f'http://{host}:{settings["port"]}/healthz', timeout=1) as response:
        return json.load(response)


def stop(root, record):
    if record is None:
        print('stopped')
        return
    # pidfd prevents a PID reuse between checking identity and signalling.
    try:
        fd = os.pidfd_open(record['pid'])
    except ProcessLookupError:
        return
    try:
        if identity(record['pid']) != record['start']:
            return
        with contextlib.suppress(ProcessLookupError):
            signal.pidfd_send_signal(fd, signal.SIGTERM)
        deadline = time.monotonic() + 10
        while identity(record['pid']) == record['start'] and time.monotonic() < deadline:
            time.sleep(.1)
        if identity(record['pid']) == record['start']:
            with contextlib.suppress(ProcessLookupError):
                signal.pidfd_send_signal(fd, signal.SIGKILL)
        for _ in range(30):
            if identity(record['pid']) != record['start']:
                (root / 'pid.json').unlink(missing_ok=True)
                print('stopped')
                return
            time.sleep(.1)
        raise RuntimeError('Process did not exit; PID record preserved')
    finally:
        os.close(fd)


def start(root):
    record = running(root)
    settings = config(root / 'config.json')
    if record:
        state = health(settings)
        if state['pid'] != record['pid'] or not state['ready']:
            raise RuntimeError('Recorded process is not ready')
        print(json.dumps(state), flush=True)
        return
    logfile = root / 'service.log'
    if logfile.exists() and logfile.stat().st_size > 10 * 1024 * 1024:
        logfile.replace(root / 'service.log.1')
    with logfile.open('ab') as log:
        child = subprocess.Popen([str(root / 'venv/bin/python'), '-u', str(HERE / 'server.py'), '--root', str(root)],
                                 stdin=subprocess.DEVNULL, stdout=log, stderr=log, start_new_session=True)
    record = {'pid': child.pid, 'start': identity(child.pid)}
    (root / 'pid.json').write_text(json.dumps(record) + '\n')
    try:
        for _ in range(300):
            if child.poll() is not None:
                raise RuntimeError('Startup failed; see service.log')
            try:
                state = health(settings)
                if state['ready'] and state['pid'] == child.pid:
                    print(json.dumps(state), flush=True)
                    return child
            except (OSError, ValueError, KeyError):
                pass
            time.sleep(.1)
        raise RuntimeError('Startup timed out; see service.log')
    except BaseException:
        stop(root, record)
        child.wait(timeout=5)
        raise


def verify_service(root):
    record = running(root)
    if not record:
        raise RuntimeError('Start the voice service before verification')
    settings = config(root / 'config.json')
    before = health(settings)
    if before.get('pid') != record['pid'] or not before.get('ready'):
        raise RuntimeError('Health endpoint does not match the managed service')
    subprocess.run([str(root / 'venv/bin/python'), str(HERE / 'smoke.py'),
                    str(root / 'models/test/0.wav'), '--config', str(root / 'config.json'),
                    '--expect', '对我的研究感兴趣'], check=True)
    after = health(settings)
    if (running(root) != record or after.get('pid') != record['pid']
            or not after.get('ready') or not after.get('last_success')
            or after['last_success'] == before.get('last_success')):
        raise RuntimeError('Service did not confirm a new successful transcription')


def setup(root):
    """Install and verify before printing any enablement instructions."""
    child = None
    owned_record = None
    try:
        if running(root):
            # Never reinstall dependencies or restart an existing service.
            verify_assets(root)
            print('服务已运行，校验现有安装并执行转写测试。', flush=True)
        else:
            install(root)
            child = start(root)
            owned_record = running(root)
        verify_service(root)
    except BaseException:
        if child is not None:
            stop(root, owned_record)
            child.wait(timeout=5)
        raise
    print('语音服务真实转写测试通过，服务保持运行。', flush=True)
    print(f'可在 {HERE.parents[1] / "data/pi-web.conf"} 中设置 PI_WEB_VOICE_INPUT_ENABLED=true。')
    print('使用包含语音接入功能的 pi-web 版本，并通过 HTTPS 或 localhost 打开 Codex 输入框；远程机器需配置 PI_WEB_CAPSWRITER_URL。')
    print('脚本未修改该开关，也未重启 pi-web。')
    return child


def main():
    if not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal'):
        raise RuntimeError('Linux Python with pidfd support is required')
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['install', 'setup', 'start', 'stop', 'status', 'logs', 'verify'])
    parser.add_argument('--root', type=Path, default=HERE.parents[1] / 'data/voice')
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    with (root / 'manage.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = running(root)
        if args.action == 'setup':
            setup(root)
        elif args.action == 'install':
            if record:
                raise RuntimeError('Stop the voice service before installation')
            install(root)
            print('installed')
        elif args.action == 'start':
            start(root)
        elif args.action == 'stop':
            stop(root, record)
        elif args.action == 'status':
            if not record:
                print('stopped')
                return 1
            state = health(config(root / 'config.json'))
            if state['pid'] != record['pid']:
                raise RuntimeError('Health endpoint belongs to another process')
            print(json.dumps(state), flush=True)
        elif args.action == 'logs':
            subprocess.run(['tail', '-n', '100', str(root / 'service.log')], check=True)
        else:
            verify_service(root)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (ValueError, RuntimeError, OSError, subprocess.CalledProcessError) as exc:
        print(str(exc), file=sys.stderr)
        sys.exit(1)
