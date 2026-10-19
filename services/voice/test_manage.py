import contextlib
import hashlib
import io
import json
from pathlib import Path
import socket
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import Mock, patch

import assets
import manage


class ManagerTests(unittest.TestCase):
    def test_start_status_stop_and_idempotence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'venv/bin').mkdir(parents=True)
            (root / 'venv/bin/python').symlink_to(sys.executable)
            with socket.socket() as sock:
                sock.bind(('127.0.0.1', 0))
                port = sock.getsockname()[1]
            settings = dict(host='127.0.0.1', port=port, threads=1, max_seconds=120, final_timeout_seconds=30)
            (root / 'config.json').write_text(json.dumps(settings))
            (root / 'server.py').write_text('''import json, os
from pathlib import Path
from http.server import HTTPServer, BaseHTTPRequestHandler
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(json.dumps(dict(ready=True, pid=os.getpid())).encode())
    def log_message(self, *args): pass
settings = json.loads((Path(__file__).parent / 'config.json').read_text())
HTTPServer((settings['host'], settings['port']), Handler).serve_forever()
''')
            with patch.object(manage, 'HERE', root), contextlib.redirect_stdout(io.StringIO()):
                child = None
                try:
                    child = manage.start(root)
                    record = manage.running(root)
                    self.assertIsNotNone(record)
                    self.assertEqual(manage.health(settings)['pid'], record['pid'])
                    manage.start(root)
                    self.assertEqual(manage.running(root), record)
                finally:
                    manage.stop(root, manage.running(root))
                    if child is not None:
                        child.wait(timeout=5)
                self.assertIsNone(manage.running(root))
                self.assertFalse((root / 'pid.json').exists())

    def test_failed_start_is_cleaned_up(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'venv/bin').mkdir(parents=True)
            (root / 'venv/bin/python').symlink_to(sys.executable)
            (root / 'config.json').write_text(json.dumps(dict(host='127.0.0.1', port=6016, threads=1, max_seconds=120, final_timeout_seconds=30)))
            (root / 'server.py').write_text('raise SystemExit(1)')
            with patch.object(manage, 'HERE', root), contextlib.redirect_stdout(io.StringIO()):
                with self.assertRaisesRegex(RuntimeError, 'Startup failed'):
                    manage.start(root)
            self.assertIsNone(manage.running(root))


class AssetTests(unittest.TestCase):
    def test_integrity_check(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'asset'
            item = dict(size=3, sha256=hashlib.sha256(b'abc').hexdigest())
            self.assertFalse(assets.checked(path, item))
            path.write_bytes(b'abc')
            self.assertTrue(assets.checked(path, item))
            path.write_bytes(b'abd')
            self.assertFalse(assets.checked(path, item))

    def test_install_extracts_only_verified_members_and_preserves_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'downloads').mkdir()
            (root / 'upstream').mkdir()
            archive = root / 'downloads/test.tar.bz2'
            with tarfile.open(archive, 'w:bz2') as tar:
                info = tarfile.TarInfo('package/model')
                info.size = 3
                tar.addfile(info, io.BytesIO(b'abc'))
                info = tarfile.TarInfo('../../escape')
                info.size = 4
                tar.addfile(info, io.BytesIO(b'evil'))
            item = dict(path='models/model', size=3, sha256=hashlib.sha256(b'abc').hexdigest())
            manifest = dict(archives=[dict(name=archive.name, size=archive.stat().st_size,
                sha256=hashlib.sha256(archive.read_bytes()).hexdigest(), files={'package/model': item})])
            (root / 'config.json').write_text('preserve me')
            with patch.object(assets, 'MANIFEST', manifest), patch.object(assets, 'source'), patch.object(assets.subprocess, 'run'):
                assets.install(root)
                self.assertEqual((root / 'models/model').read_bytes(), b'abc')
                self.assertEqual((root / 'config.json').read_text(), 'preserve me')
                self.assertFalse((root / 'escape').exists())
                (root / 'models/model').write_bytes(b'bad')
                with self.assertRaisesRegex(ValueError, 'corrupt asset'):
                    assets.verify(root)


class SetupTests(unittest.TestCase):
    def test_enable_hint_only_after_successful_transcription(self):
        root = Path('/test/voice')
        events = []
        output = io.StringIO()
        child = Mock()
        record = dict(pid=123, start='456')
        def verified(_):
            self.assertNotIn('PI_WEB_VOICE_INPUT_ENABLED=true', output.getvalue())
            events.append('verify')
        with patch.object(manage, 'running', side_effect=[None, record]), \
                patch.object(manage, 'install', side_effect=lambda _: events.append('install')), \
                patch.object(manage, 'start', side_effect=lambda _: events.append('start') or child), \
                patch.object(manage, 'verify_service', side_effect=verified), \
                contextlib.redirect_stdout(output):
            self.assertIs(manage.setup(root), child)
        self.assertEqual(events, ['install', 'start', 'verify'])
        self.assertIn('PI_WEB_VOICE_INPUT_ENABLED=true', output.getvalue())
        self.assertIn('HTTPS 或 localhost', output.getvalue())

    def test_failures_never_print_enable_hint(self):
        root = Path('/test/voice')
        record = dict(pid=123, start='456')
        for stage in ['install', 'start', 'verify_service']:
            with self.subTest(stage=stage), contextlib.ExitStack() as stack:
                output = stack.enter_context(contextlib.redirect_stdout(io.StringIO()))
                stack.enter_context(patch.object(manage, 'running', side_effect=[None, record]))
                methods = {name: stack.enter_context(patch.object(manage, name))
                           for name in ['install', 'start', 'verify_service', 'stop']}
                methods[stage].side_effect = RuntimeError('failed')
                with self.assertRaises(RuntimeError):
                    manage.setup(root)
                self.assertNotIn('PI_WEB_VOICE_INPUT_ENABLED=true', output.getvalue())
                if stage == 'verify_service':
                    methods['stop'].assert_called_once_with(root, record)
                    methods['start'].return_value.wait.assert_called_once_with(timeout=5)
                else:
                    methods['stop'].assert_not_called()

    def test_running_service_is_not_reinstalled_or_stopped_on_probe_failure(self):
        with patch.object(manage, 'running', return_value=dict(pid=123, start='456')), \
                patch.object(manage, 'verify_assets') as assets_check, \
                patch.object(manage, 'install') as install, \
                patch.object(manage, 'start') as start, \
                patch.object(manage, 'stop') as stop, \
                patch.object(manage, 'verify_service', side_effect=RuntimeError('busy')), \
                contextlib.redirect_stdout(io.StringIO()) as output:
            with self.assertRaises(RuntimeError):
                manage.setup(Path('/test/voice'))
            assets_check.assert_called_once()
            install.assert_not_called()
            start.assert_not_called()
            stop.assert_not_called()
            self.assertNotIn('PI_WEB_VOICE_INPUT_ENABLED=true', output.getvalue())

    def test_verify_requires_matching_pid_and_new_success(self):
        root = Path('/test/voice')
        record = dict(pid=123, start='456')
        before = dict(pid=123, ready=True, last_success={'time': 1})
        good = dict(pid=123, ready=True, last_success={'time': 2})
        for after, passes in [(good, True), (before, False),
                              (good | {'pid': 124}, False),
                              (good | {'last_success': None}, False)]:
            with self.subTest(after=after), \
                    patch.object(manage, 'running', return_value=record), \
                    patch.object(manage, 'config', return_value={}), \
                    patch.object(manage, 'health', side_effect=[before, after]), \
                    patch.object(manage.subprocess, 'run') as probe:
                if passes:
                    manage.verify_service(root)
                else:
                    with self.assertRaises(RuntimeError):
                        manage.verify_service(root)
                self.assertIn('--expect', probe.call_args.args[0])
        with patch.object(manage, 'running', return_value=record), \
                patch.object(manage, 'config', return_value={}), \
                patch.object(manage, 'health', return_value=good | {'pid': 124}), \
                patch.object(manage.subprocess, 'run') as probe:
            with self.assertRaises(RuntimeError):
                manage.verify_service(root)
            probe.assert_not_called()
