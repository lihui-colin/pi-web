"""Strict standalone host batching transform and isolated real-class execution."""
import test_support
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from patches.service import dsh_terminal_host_batching_apply as p
from patches.service import dsh_terminal_apply as terminal
from patches.common import publish

FIXTURE = Path(__file__).parent / 'fixtures/dsh_terminal_host_rc1.js'


class HostBatchingPatchTests(unittest.TestCase):
    def test_exact_class_and_idempotence(self):
        original = FIXTURE.read_text()
        fixed = p.patch(original)
        self.assertEqual(fixed, p.patch(fixed))
        self.assertEqual(p.patch('// unrelated\n' + original), '// unrelated\n' + fixed)
        for bad in (original.replace('await this.output(data);', 'this.output(data);'),
                    fixed.replace('>= 65536', '>= 65535'),
                    fixed.replace('this.hostOutputBatcher.flush();', '', 1),
                    original + original, fixed + original, fixed + fixed,
                    fixed.replace(p.HELPER, '', 1),
                    original + '\n// hostOutputBatcher'):
            with self.subTest(candidate=bad[:70]), self.assertRaises(ValueError):
                p.patch(bad)

    def test_old_terminal_patch_compatible_in_both_orders_and_repeat(self):
        original = FIXTURE.read_text()
        batch_first = terminal.patch_host(p.patch(original))
        terminal_first = p.patch(terminal.patch_host(original))
        self.assertEqual(batch_first, terminal_first)
        self.assertEqual(p.patch(batch_first), batch_first)
        self.assertEqual(terminal.patch_host(batch_first), batch_first)
        self.assertIn(terminal.HOST_WRITE, batch_first)
        self.assertIn(terminal.PROTOCOL_SERIALIZE, batch_first)

    def test_version_guards_readonly_plan_shared_publish_and_cli(self):
        with tempfile.TemporaryDirectory() as root:
            host = Path(root)
            package = host / 'dsh-api-terminal-controller'
            (package / 'lib').mkdir(parents=True)
            target = package / 'lib/index.js'
            manifest = package / 'package.json'
            original = FIXTURE.read_text()
            target.write_text(original)
            def version(value, name='@deepseek-ai/dsh-api-terminal-controller'):
                manifest.write_text(json.dumps({'name':name,'version':value}))
            version('0.2.2-rc.1')
            changes = p.plan_changes(host)
            self.assertEqual(target.read_text(), original)
            self.assertEqual(len(changes), 1)
            cli = [ 'python3', '-B', str(Path(p.__file__)), '--host-dir', str(host), '--check' ]
            result = subprocess.run(cli, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Required patches missing', result.stderr)
            publish(changes, backup_root=host / 'backups')
            self.assertEqual(target.read_text(), p.patch(original))
            result = subprocess.run(cli, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(p.plan_changes(host)[0][1], p.plan_changes(host)[0][2])
            version('0.2.2-alpha.2')
            self.assertEqual(p.plan_changes(host), [])
            for value, name in [('0.2.2-rc.2','@deepseek-ai/dsh-api-terminal-controller'), ('0.2.2-rc.1','unknown')]:
                version(value, name)
                with self.assertRaises(ValueError):
                    p.plan_changes(host)

    def test_transformed_real_class(self):
        result = subprocess.run(['node', '--test', str(Path(__file__).with_name('test_dsh_terminal_host_batching.cjs'))], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
