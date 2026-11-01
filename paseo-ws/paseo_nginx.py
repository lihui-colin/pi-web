#!/usr/bin/env python3
"""Paseo Linux nginx lifecycle; caller holds data/service.lock throughout."""
import errno
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import tempfile
import time


class Nginx:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.data = self.root / 'data'
        self.run = self.data / 'nginx'
        self.exe = self.root / 'runtime/nginx/sbin/nginx'
        self.conf = self.data / 'nginx.conf'
        self.identity = self.run / 'master.json'
        self.args = [str(self.exe), '-p', str(self.run) + '/', '-c', str(self.conf),
                     '-e', str(self.root / 'log/nginx/error.log')]

    def snapshot(self, pid):
        proc = Path('/proc') / str(pid)
        stat = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        if stat[0] in ('Z', 'X'):
            raise ProcessLookupError(pid)
        exe = (proc / 'exe').stat()
        return {'pid': pid, 'boot': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                'start': stat[19], 'exe': [exe.st_dev, exe.st_ino],
                'command': (proc / 'cmdline').read_bytes().rstrip(bytes([0])).decode()}

    def verified(self):
        try:
            raw = (self.run / 'nginx.pid').read_text().strip()
        except FileNotFoundError:
            return None
        if not raw.isdecimal() or int(raw) <= 1:
            raise RuntimeError('Invalid nginx PID file; refusing to signal or start.')
        pid = int(raw)
        try:
            current = self.snapshot(pid)
        except (FileNotFoundError, ProcessLookupError):
            return None
        expected = self.exe.stat()
        if (current['exe'] != [expected.st_dev, expected.st_ino] or
                current['command'] != 'nginx: master process ' + ' '.join(self.args)):
            raise RuntimeError('Nginx PID does not identify this instance master; refusing to signal or start.')
        try:
            saved = json.loads(self.identity.read_text())
        except FileNotFoundError:
            if self.snapshot(pid) != current:
                raise RuntimeError('Nginx identity changed during adoption.')
            self.save_identity(current)
        else:
            if saved != current:
                raise RuntimeError('Nginx boot/start identity changed; refusing to signal or start.')
        return current

    def save_identity(self, value):
        fd, temp = tempfile.mkstemp(prefix='.master-', dir=self.run)
        try:
            with os.fdopen(fd, 'w') as stream:
                json.dump(value, stream)
            os.replace(temp, self.identity)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def send(self, current, sig):
        pid = current['pid']
        fd = None
        try:
            if hasattr(os, 'pidfd_open') and hasattr(signal, 'pidfd_send_signal'):
                try:
                    fd = os.pidfd_open(pid)
                except OSError as error:
                    if error.errno not in (errno.ENOSYS, errno.EINVAL):
                        raise
            # Check after pidfd_open so a reused PID cannot redirect this signal.
            if self.snapshot(pid) != current:
                raise RuntimeError('Nginx identity changed before signal.')
            if fd is not None:
                signal.pidfd_send_signal(fd, sig)
            else:
                # Older Linux/Python: recheck narrows but cannot eliminate the kill race.
                os.kill(pid, sig)
        finally:
            if fd is not None:
                os.close(fd)

    def publish(self):
        rendered = subprocess.check_output([
            'node', '-e', 'process.stdout.write(require(process.argv[1]).renderProxy(process.argv[2]))',
            str(self.root / 'paseo-config.cjs'), str(self.data)])
        fd, temp = tempfile.mkstemp(prefix='.nginx-candidate-', suffix='.conf', dir=self.data)
        try:
            with os.fdopen(fd, 'wb') as stream:
                stream.write(rendered)
            args = self.args.copy()
            args[args.index('-c') + 1] = temp
            subprocess.run(args + ['-t'], check=True, close_fds=True)
            os.replace(temp, self.conf)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)

    def start(self):
        if self.verified() is not None:
            return
        self.identity.unlink(missing_ok=True)
        subprocess.run(self.args, check=True, close_fds=True)
        for _ in range(50):
            if self.verified() is not None:
                return
            time.sleep(.1)
        raise RuntimeError('Nginx did not create a verified master.')

    def quit(self):
        current = self.verified()
        if current is None:
            return
        self.send(current, signal.SIGQUIT)
        for _ in range(50):
            try:
                observed = self.snapshot(current['pid'])
                if any(observed[key] != current[key] for key in ('boot', 'start', 'exe')):
                    break
            except (FileNotFoundError, ProcessLookupError):
                break
            time.sleep(.2)
        else:
            raise RuntimeError('Nginx is still exiting; retry stop later.')
        self.identity.unlink(missing_ok=True)


def main():
    action, root = sys.argv[1:]
    nginx = Nginx(root)
    if action == 'running':
        return 0 if nginx.verified() else 1
    if action == 'publish':
        nginx.verified()  # Reject a live foreign PID before changing configuration or backend state.
        nginx.publish()
    elif action == 'start':
        nginx.start()
    elif action == 'quit':
        nginx.quit()
    elif action == 'reload':
        current = nginx.verified()
        if current is None:
            raise RuntimeError('Nginx is not running.')
        nginx.publish()
        nginx.send(current, signal.SIGHUP)
    else:
        raise RuntimeError('Unknown nginx action: ' + action)
    return 0


if __name__ == '__main__':
    try:
        sys.exit(main())
    except (OSError, ValueError, RuntimeError, subprocess.CalledProcessError) as error:
        print(str(error), file=sys.stderr)
        sys.exit(2)
