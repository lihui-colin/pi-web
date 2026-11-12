"""Validate the versioned native-composer patch without changing real installs."""
import test_support  # Configure the service source import path.
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from patches.service import dsh_composer_metadata_apply as patcher


class ComposerMetadataTests(unittest.TestCase):
    def test_version_gate_cli_and_idempotence(self):
        source = patcher.ANCHOR + '\n' + patcher.OLD + '\n' + patcher.TRAILING + '\n' + patcher.REGISTER_ANCHOR
        for running in patcher.TRANSLATIONS:
            source += '\n"details.running": ' + json.dumps(running, ensure_ascii=False) + ','
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            package = root / 'dsh-client-ui-conversation'
            (package / 'lib').mkdir(parents=True)
            manifest = package / 'package.json'
            def version(value):
                manifest.write_text(json.dumps({'name':'@deepseek-ai/dsh-client-ui-conversation','version':value}))
            version('0.2.2-rc.1')
            file = package / 'lib/client.js'
            file.write_text(source)
            command = ['python3','-B',patcher.__file__,'--host-dir',str(root)]
            self.assertNotEqual(subprocess.run(command + ['--check'],capture_output=True).returncode,0)
            patcher.publish(patcher.plan_changes(root), root / 'backups')
            self.assertEqual(subprocess.run(command + ['--check'],capture_output=True).returncode,0)
            self.assertEqual(patcher.patch(file.read_text()),file.read_text())
            stamp = file.stat().st_mtime_ns
            patcher.publish(patcher.plan_changes(root), root / 'backups')
            self.assertEqual(file.stat().st_mtime_ns,stamp)
            current = file.read_text()
            self.assertIn(patcher.REGISTER_TRIGGER, current)
            self.assertNotIn(patcher.TRAILING_NEW, current)
            previous = current.replace(patcher.REGISTER_TRIGGER, '').replace(patcher.TRAILING, patcher.TRAILING_NEW)
            self.assertEqual(patcher.patch(previous), current)
            for name in ('composer_metadata_v1.js', 'composer_metadata_v2.js'):
                legacy = (Path(__file__).parent / 'fixtures' / name).read_text()
                previous = (current.replace(patcher.HELPER, legacy)
                            .replace(patcher.WRAPPER, patcher.LEGACY_WRAPPER)
                            .replace(patcher.NEW, patcher.DOCK))
                self.assertEqual(patcher.patch(previous), current)
                for broken in (
                    previous.replace('const dshSessionInfoCss', 'const unknownCss'),
                    previous.replace('}, props.sessionId);', '}, unknownKey);'),
                    previous.replace(patcher.LEGACY_WRAPPER, patcher.WRAPPER),
                    previous + patcher.LEGACY_WRAPPER,
                    previous + legacy,
                    current.replace(patcher.WRAPPER, patcher.LEGACY_WRAPPER),
                ):
                    with self.assertRaises(ValueError):
                        patcher.patch(broken)
            version('0.2.3')
            with self.assertRaises(ValueError): patcher.plan_changes(root)
            version('0.2.2-alpha.2')
            self.assertEqual(patcher.plan_changes(root),[])
            self.assertEqual(file.stat().st_mtime_ns,stamp)

    def test_missing_and_mixed_anchors_are_rejected(self):
        for source in ('unknown', patcher.ANCHOR * 2):
            with self.assertRaises(ValueError): patcher.patch(source)

    @unittest.skipUnless(all(os.environ.get(name) for name in
        ('DSH_TEST_PLAYWRIGHT', 'DSH_TEST_FRONTEND_ASSETS')),
        'Set browser dependencies and native frontend assets for lifecycle regression')
    def test_native_browser_lifecycle(self):
        from patches.service import dsh_context_details_apply as context_patcher
        with tempfile.TemporaryDirectory() as temp:
            config = Path(temp) / 'lifecycle.json'
            meter = context_patcher.patch(
                (Path(__file__).parent / 'fixtures/context_meter_rc1.js').read_text()
                + '\n' + context_patcher.DECLARE).removesuffix('\n' + context_patcher.DECLARE_NEW)
            config.write_text(json.dumps({'wrapper': patcher.WRAPPER, 'meter': meter}))
            result = subprocess.run(['node', str(Path(__file__).with_name('test_dsh_composer_metadata_lifecycle.cjs')), str(config)],
                                    capture_output=True, text=True, timeout=90)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            print(result.stdout.strip())

    @unittest.skipUnless(all(os.environ.get(name) for name in
        ('DSH_TEST_PLAYWRIGHT','DSH_TEST_REACT_UMD','DSH_TEST_REACT_DOM_UMD')),
        'Set browser test dependencies to exercise the real React helper')
    def test_browser_interaction(self):
        result = subprocess.run(['node',str(Path(__file__).with_suffix('.cjs')), patcher.REGISTER_TRIGGER],
                                capture_output=True,text=True,timeout=60)
        self.assertEqual(result.returncode,0,result.stdout+result.stderr)


if __name__ == '__main__': unittest.main()
