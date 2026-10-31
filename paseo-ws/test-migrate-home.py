import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location('paseo_migration', ROOT / 'paseo-migrate-home.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class SimulatedService(module.Migration):
    def __init__(self, root):
        super().__init__(root)
        self.running_home = self.data
        self.agents = [{'id': 'agent-1', 'status': 'idle'}]
        self.calls = []
        self.fail_start = False
        self.fail_stop_new = False

    def query(self, home, *args):
        if args[0] == 'daemon':
            return {'localDaemon': 'running' if self.running_home == home else 'stopped',
                    'home': str(home), 'listen': '127.0.0.1:25226'}
        self.assert_all_agents_query(args)
        return self.agents

    @staticmethod
    def assert_all_agents_query(args):
        assert args == ('ls', '--all', '--global')

    def lifecycle(self, action, home, mode='proxy'):
        self.calls.append((action, home))
        if action == 'stop':
            if home == self.home and self.fail_stop_new:
                raise RuntimeError('simulated stop failure')
            self.running_home = None
        else:
            self.running_home = home
            if home == self.home:
                # The real manager prepares the official configuration before starting.
                subprocess.run(['node', str(ROOT / 'paseo-config.cjs'), 'prepare', str(self.data),
                                mode, '{"localDaemon":"stopped"}'], check=True)
                if self.fail_start:
                    raise RuntimeError('simulated health check failure')


class MigrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='paseo-home-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.data = self.root / 'data'
        self.data.mkdir(mode=0o700)
        for name in ('agents', 'models', 'runtime', 'tls', 'nginx'):
            (self.data / name).mkdir(mode=0o700)
            (self.data / name / 'sample').write_bytes(b'preserved content')
        (self.data / 'config.json').write_text(json.dumps({
            'version': 1, 'daemon': {'listen': '127.0.0.1:25226', 'relay': {'enabled': False}},
            'agents': {'providers': {'pi': {'enabled': True}}},
        }))
        (self.data / 'config.json').chmod(0o600)
        (self.data / 'server-id').write_bytes(b'original-server-id')
        (self.data / 'daemon-keypair.json').write_bytes(b'original-keypair')
        (self.data / 'daemon-keypair.json').chmod(0o600)
        (self.data / 'daemon.log').write_bytes(b'existing log')
        (self.data / 'paseo.conf').write_text('{"ip":"127.0.0.1","port":25227}')
        shutil.copy2(ROOT / 'paseo-config.cjs', self.root)
        self.service = SimulatedService(self.root)

    def run_migration(self):
        with self.service.lock():
            self.service.migrate()

    def test_success_preserves_identity_sessions_permissions_and_deployment_paths(self):
        before = (self.data / 'agents/sample').stat()
        self.run_migration()
        home = self.service.home
        self.assertEqual(self.service.running_home, home)
        self.assertFalse((self.data / 'config.json').exists())
        self.assertEqual((home / 'server-id').read_bytes(), b'original-server-id')
        self.assertEqual((home / 'agents/sample').stat().st_ino, before.st_ino)
        self.assertEqual((home / 'agents/sample').stat().st_mode, before.st_mode)
        self.assertEqual((home / 'daemon-keypair.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(home.stat().st_mode & 0o777, 0o700)
        self.assertTrue((home / 'models/sample').exists())
        self.assertTrue((home / 'runtime/sample').exists())
        self.assertTrue((self.data / 'tls/sample').exists())
        self.assertTrue((self.data / 'nginx/sample').exists())
        self.assertEqual(json.loads(self.service.journal.read_text())['phase'], 'complete')

    def test_nonempty_target_is_rejected_before_stopping(self):
        self.service.home.mkdir()
        (self.service.home / 'existing').write_text('do not overwrite')
        with self.assertRaisesRegex(RuntimeError, '拒绝覆盖'):
            self.run_migration()
        self.assertEqual(self.service.calls, [])
        self.assertTrue((self.data / 'config.json').exists())

    def test_active_initializing_or_unknown_sessions_do_not_stop_service(self):
        for status in ('running', 'initializing', None, 'unknown'):
            with self.subTest(status=status):
                self.service.agents = [{'id': 'agent-1', 'status': status}]
                with self.assertRaisesRegex(RuntimeError, '服务保持原状'):
                    self.run_migration()
                self.assertEqual(self.service.calls, [])
                self.assertFalse(self.service.home.exists())

    def test_unknown_daemon_status_is_rejected_without_stopping(self):
        with patch.object(self.service, 'query', return_value={'localDaemon': 'unknown'}):
            with self.assertRaisesRegex(RuntimeError, '无法确认旧服务状态'):
                self.run_migration()
        self.assertEqual(self.service.calls, [])

    def test_command_hosted_by_daemon_is_rejected_even_if_agent_looks_idle(self):
        with patch.object(self.service, 'query', side_effect=[
            {'localDaemon': 'running', 'pid': os.getpid()}, self.service.agents,
        ]):
            with self.assertRaisesRegex(RuntimeError, '独立终端'):
                self.run_migration()
        self.assertEqual(self.service.calls, [])

    def test_health_failure_restores_legacy_configuration_and_service(self):
        original = (self.data / 'config.json').read_bytes()
        self.service.fail_start = True
        with self.assertRaisesRegex(RuntimeError, 'health check failure'):
            self.run_migration()
        self.assertEqual(self.service.running_home, self.data)
        self.assertEqual((self.data / 'config.json').read_bytes(), original)
        self.assertTrue((self.data / 'agents/sample').exists())
        self.assertFalse(self.service.home.exists())
        self.assertEqual(json.loads(self.service.journal.read_text())['phase'], 'rolled-back')

    def test_partial_move_failure_restores_already_moved_files(self):
        rename = Path.rename

        def fail_model_move(source, target):
            if source == self.data / 'models':
                raise OSError('simulated move failure')
            return rename(source, target)

        with patch.object(Path, 'rename', fail_model_move):
            with self.assertRaisesRegex(OSError, 'move failure'):
                self.run_migration()
        self.assertEqual(self.service.running_home, self.data)
        self.assertTrue((self.data / 'agents/sample').exists())
        self.assertTrue((self.data / 'config.json').exists())
        self.assertFalse(self.service.home.exists())

    def test_unconfirmed_new_stop_preserves_files_for_recovery(self):
        self.service.fail_start = True
        self.service.fail_stop_new = True
        with self.assertRaisesRegex(RuntimeError, '自动恢复未完成'):
            self.run_migration()
        self.assertTrue((self.service.home / 'agents/sample').exists())
        self.assertFalse((self.data / 'config.json').exists())
        self.assertEqual(json.loads(self.service.journal.read_text())['phase'], 'recovery-required')

    def test_management_retains_legacy_status_stop_and_blocks_start(self):
        shutil.copy2(ROOT / 'paseo_web_run.sh', self.root)
        binary = self.root / 'runtime/bin/paseo'
        binary.parent.mkdir(parents=True)
        binary.write_text('#!/bin/sh\n[ -z "${PASEO_MAINTENANCE_HOME:-}" ] || exit 99\nprintf "%s\\n" "$@"\n')
        binary.chmod(0o755)
        inherited = {**os.environ, 'PASEO_MAINTENANCE_HOME': '/stale/daemon/home'}
        for action in ('status', 'stop'):
            result = subprocess.run(['bash', str(self.root / 'paseo_web_run.sh'), action],
                                    capture_output=True, text=True, env=inherited)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn(str(self.data), result.stdout.splitlines())
        for action in ('start', 'set-password'):
            result = subprocess.run(['bash', str(self.root / 'paseo_web_run.sh'), action],
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('migrate-home', result.stderr)
        (self.data / '.paseo').mkdir()
        (self.data / 'config.json').rename(self.data / '.paseo/config.json')
        result = subprocess.run(['bash', str(self.root / 'paseo_web_run.sh'), 'status'],
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn(str(self.data / '.paseo'), result.stdout.splitlines())
        # Exercise the actual lifecycle subprocess and its inherited lock, not the simulation.
        with self.service.lock():
            module.Migration.lifecycle(self.service, 'status', self.service.home)
        (self.data / 'home-migration.json').write_text('{"phase":"moving"}')
        result = subprocess.run(['bash', str(self.root / 'paseo_web_run.sh'), 'start'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('数据迁移未完成', result.stderr)

    def test_detached_worker_completes_through_manager_with_mock_services(self):
        for name in ('paseo_web_run.sh', 'paseo-migrate-home.py', 'nginx.conf.template'):
            shutil.copy2(ROOT / name, self.root)
        binary = self.root / 'runtime/bin/paseo'
        binary.parent.mkdir(parents=True)
        binary.write_text(f'#!{sys.executable}\n' + '''import json, os, sys
from pathlib import Path
root = Path(os.environ['PASEO_TEST_ROOT'])
args = sys.argv[1:]
home = args[args.index('--home') + 1]
file = root / 'mock-state.json'
state = json.loads(file.read_text())
if 'status' in args:
    print(json.dumps({'localDaemon': 'running' if state['home'] == home else 'stopped',
                      'home': home, 'listen': '127.0.0.1:25226'}))
elif 'ls' in args:
    print(json.dumps([{'id': 'agent-1', 'status': 'idle'}]))
elif 'stop' in args:
    file.write_text(json.dumps({'home': None}))
elif 'start' in args:
    assert not os.environ.get('PASEO_MAINTENANCE_HOME'), 'maintenance context leaked to daemon'
    file.write_text(json.dumps({'home': home}))
else:
    sys.exit(1)
''')
        binary.chmod(0o755)
        (self.root / 'mock-state.json').write_text(json.dumps({'home': str(self.data)}))
        nginx = self.root / 'runtime/nginx/sbin/nginx'
        nginx.parent.mkdir(parents=True)
        nginx.write_text(f'#!{sys.executable}\n' + '''import os, sys
from pathlib import Path
pid = Path(os.environ['PASEO_TEST_ROOT']) / 'data/nginx/nginx.pid'
if '-s' in sys.argv:
    pid.unlink(missing_ok=True)
elif '-t' not in sys.argv:
    pid.write_text(os.environ['PASEO_TEST_PID'])
''')
        nginx.chmod(0o755)
        fakebin = self.root / 'fakebin'
        fakebin.mkdir()
        curl = fakebin / 'curl'
        curl.write_text('#!/bin/sh\nexit 0\n')
        curl.chmod(0o755)
        env = {**os.environ, 'PATH': str(fakebin) + ':' + os.environ['PATH'],
               'PASEO_TEST_ROOT': str(self.root), 'PASEO_TEST_PID': str(os.getpid())}
        result = subprocess.run(['bash', str(self.root / 'paseo_web_run.sh'), 'migrate-home'],
                                capture_output=True, text=True, env=env, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('独立迁移进程', result.stdout)
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if self.service.journal.exists():
                state = json.loads(self.service.journal.read_text())
                if state['phase'] in ('complete', 'rolled-back', 'recovery-required'):
                    break
            time.sleep(0.05)
        else:
            self.fail((self.data / 'home-migration.log').read_text())
        self.assertEqual(state['phase'], 'complete', (self.data / 'home-migration.log').read_text())
        self.assertEqual(json.loads((self.root / 'mock-state.json').read_text())['home'], str(self.service.home))
        self.assertTrue((self.service.home / 'agents/sample').exists())
        self.assertTrue((self.data / 'tls/sample').exists())


if __name__ == '__main__':
    unittest.main()
