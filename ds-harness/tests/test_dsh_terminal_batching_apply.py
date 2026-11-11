"""Standalone batching candidate guards; never touches the installed runtime."""
import test_support
import json
import shutil
from pathlib import Path
import tempfile
import subprocess
import unittest
from patches.service import dsh_terminal_batching_apply as p


class TerminalBatchingPatchTests(unittest.TestCase):
    def original(self):
        consumer = (Path(__file__).parent / 'fixtures/dsh_terminal_consume_rc1.js').read_text()
        return p.ANCHOR + '\n' + consumer + p.END + '\n}\n};'

    def test_exact_consumer_idempotence_and_other_patches_preserved(self):
        source = '// existing unrelated patch\n' + self.original()
        result = p.patch(source)
        self.assertEqual(result, p.patch(result))
        self.assertTrue(result.startswith('// existing unrelated patch\n'))
        self.assertIn(p.CONSUME, result)
        self.assertIn(p.HELPER, result)
        with self.assertRaises(ValueError):
            p.patch(source.replace('let sequence = 0;', 'let sequence = 99;'))
        with self.assertRaises(ValueError):
            p.patch(result.replace('const maxRecords = 4096;', 'const maxRecords = 1;'))

    def test_rc1_only_plan_is_read_only(self):
        with tempfile.TemporaryDirectory() as root:
            package = Path(root) / 'dsh-api-terminal-controller'
            (package / 'lib').mkdir(parents=True)
            manifest = package / 'package.json'
            manifest.write_text(json.dumps({'name':'@deepseek-ai/dsh-api-terminal-controller','version':'0.2.2-rc.1'}))
            target = package / 'lib/client.js'
            target.write_text(self.original())
            before = target.read_text()
            changes = p.plan_changes(Path(root))
            self.assertEqual(target.read_text(), before)
            self.assertEqual(len(changes), 1)
            self.assertNotEqual(changes[0][1], changes[0][2])
            manifest.write_text(json.dumps({'name':'@deepseek-ai/dsh-api-terminal-controller','version':'0.2.2-alpha.2'}))
            self.assertEqual(p.plan_changes(Path(root)), [])
            for name, version in (('@deepseek-ai/dsh-api-terminal-controller', '0.2.2-rc.2'), ('unknown', '0.2.2-rc.1')):
                manifest.write_text(json.dumps({'name': name, 'version': version}))
                with self.assertRaises(ValueError):
                    p.plan_changes(Path(root))
            self.assertEqual(target.read_text(), before)

    def test_duplicate_and_mixed_consumer_rejected(self):
        original = self.original()
        fixed = p.patch(original)
        for value in (original + original, fixed + fixed, original + fixed, fixed + original):
            with self.subTest(value=value), self.assertRaises(ValueError):
                p.patch(value)

    def test_production_copy_without_tests_migrates_exact_legacy_helper(self):
        legacy = (Path(__file__).parent / 'fixtures/dsh_terminal_batching_v1.js').read_text()
        deployed = legacy + p.ANCHOR + '\n' + p.CONSUME + p.END + '\n}\n};'
        with tempfile.TemporaryDirectory() as root:
            patches = Path(root) / 'patches'
            service = patches / 'service'
            service.mkdir(parents=True)
            shutil.copy2(Path(p.__file__).parents[1] / 'common.py', patches / 'common.py')
            for name in ('dsh_terminal_batching.js', 'dsh_terminal_batching_apply.py'):
                shutil.copy2(Path(p.__file__).parent / name, service / name)
            result = subprocess.run(['python3', '-B', '-c',
                'import sys; sys.path.insert(0, sys.argv[1]); '
                'from patches.service import dsh_terminal_batching_apply as p; '
                'sys.stdout.write(p.patch(sys.stdin.read()))', root],
                input=deployed, capture_output=True, text=True, cwd=root, timeout=30)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout, p.patch(deployed))

    def test_exact_transformed_consumer_behavior(self):
        result = subprocess.run(['node', '--test', str(Path(__file__).with_name('test_dsh_terminal_batching.cjs'))],
                                capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
