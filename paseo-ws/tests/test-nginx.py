"""Signal race/fallback checks; all signal syscalls are mocked."""
import errno
from pathlib import Path
import signal
import tempfile
import unittest
from unittest.mock import patch
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'srcs'))
from paseo_nginx import Nginx


class IdentityTests(unittest.TestCase):
    def test_adopts_only_exact_current_or_legacy_instance_command(self):
        with tempfile.TemporaryDirectory(prefix='paseo-identity-') as root:
            nginx = Nginx(root)
            nginx.run.mkdir(parents=True)
            nginx.exe.parent.mkdir(parents=True)
            nginx.exe.write_text('fixture')
            (nginx.run / 'nginx.pid').write_text('12345')
            stat = nginx.exe.stat()
            current = {'pid': 12345, 'start': '100', 'boot': 'boot',
                       'exe': [stat.st_dev, stat.st_ino]}
            for log in [nginx.args[-1], str(nginx.run / 'error.log')]:
                args = nginx.args.copy()
                args[-1] = log
                snapshot = {**current, 'command': 'nginx: master process ' + ' '.join(args)}
                with patch.object(nginx, 'snapshot', return_value=snapshot):
                    self.assertEqual(nginx.verified(), snapshot)
                    self.assertEqual(nginx.verified(), snapshot)
                nginx.identity.unlink()
            for index, value in [(-1, str(nginx.run / 'other.log')),
                                 (4, str(nginx.data / 'other.conf')),
                                 (2, str(nginx.data / 'other') + '/')]:
                args = nginx.args.copy()
                args[index] = value
                snapshot = {**current, 'command': 'nginx: master process ' + ' '.join(args)}
                with patch.object(nginx, 'snapshot', return_value=snapshot):
                    with self.assertRaisesRegex(RuntimeError, 'does not identify'):
                        nginx.verified()
                self.assertFalse(nginx.identity.exists())
            snapshot = {**current, 'exe': [0, 0],
                        'command': 'nginx: master process ' + ' '.join(nginx.args)}
            with patch.object(nginx, 'snapshot', return_value=snapshot):
                with self.assertRaisesRegex(RuntimeError, 'does not identify'):
                    nginx.verified()


class SignalTests(unittest.TestCase):
    def setUp(self):
        self.nginx = Nginx(Path(__file__).parent)
        self.current = {'pid': 12345, 'start': '100', 'boot': 'boot'}

    def test_pidfd_is_opened_before_recheck_and_used_for_signal(self):
        events = []
        with patch('os.pidfd_open', create=True, side_effect=lambda pid: events.append('open') or 42), \
             patch.object(self.nginx, 'snapshot', side_effect=lambda pid: events.append('check') or self.current), \
             patch('signal.pidfd_send_signal', create=True, side_effect=lambda *args: events.append('signal')) as send, \
             patch('os.close') as close, patch('os.kill') as kill:
            self.nginx.send(self.current, signal.SIGQUIT)
            self.assertEqual(events, ['open', 'check', 'signal'])
            send.assert_called_once_with(42, signal.SIGQUIT)
            close.assert_called_once_with(42)
            kill.assert_not_called()

    def test_reused_pid_after_open_is_never_signaled(self):
        with patch('os.pidfd_open', create=True, return_value=42), \
             patch.object(self.nginx, 'snapshot', return_value={**self.current, 'start': '101'}), \
             patch('signal.pidfd_send_signal', create=True) as send, \
             patch('os.close') as close, patch('os.kill') as kill:
            with self.assertRaisesRegex(RuntimeError, 'identity changed'):
                self.nginx.send(self.current, signal.SIGQUIT)
            send.assert_not_called()
            kill.assert_not_called()
            close.assert_called_once_with(42)

    def test_unsupported_kernel_fallback_rechecks_identity(self):
        with patch('os.pidfd_open', create=True, side_effect=OSError(errno.ENOSYS, 'unsupported')), \
             patch('signal.pidfd_send_signal', create=True) as send, \
             patch.object(self.nginx, 'snapshot', return_value=self.current) as snapshot, \
             patch('os.kill') as kill:
            self.nginx.send(self.current, signal.SIGHUP)
            snapshot.assert_called_once_with(self.current['pid'])
            kill.assert_called_once_with(self.current['pid'], signal.SIGHUP)
            send.assert_not_called()

    def test_permission_failure_does_not_fall_back_to_kill(self):
        with patch('os.pidfd_open', create=True, side_effect=PermissionError(errno.EPERM, 'denied')), \
             patch('signal.pidfd_send_signal', create=True) as send, patch('os.kill') as kill:
            with self.assertRaises(PermissionError):
                self.nginx.send(self.current, signal.SIGQUIT)
            send.assert_not_called()
            kill.assert_not_called()


if __name__ == '__main__':
    unittest.main()
