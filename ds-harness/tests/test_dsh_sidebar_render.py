"""Guard rc.1 explicit navigator parent state and compare browser semantics."""
import test_support
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

from patches.service import dsh_sidebar_render_apply as patcher


FIXTURE = Path(__file__).parent / 'fixtures/sidebar_navigator_rc1.css'
REF_FIXTURE = Path(__file__).parent / 'fixtures/sidebar_navigator_ref_rc1.js'


def source():
    return FIXTURE.read_text() + '\n' + REF_FIXTURE.read_text()


class SidebarRenderPatchTests(unittest.TestCase):
    def test_relational_css_removed_with_complete_idempotent_layout_ref(self):
        original = source()
        fixed = patcher.patch(original)
        self.assertNotIn(':has(', fixed)
        self.assertIn(patcher.HELPER, fixed)
        self.assertIn(patcher.REF_NEW, fixed)
        self.assertEqual(patcher.patch(fixed), fixed)
        for old, new in reversed(patcher.REPLACEMENTS):
            fixed = fixed.replace(new, old)
        self.assertEqual(fixed, original)

    def test_unknown_duplicate_and_mixed_targets_are_rejected(self):
        original = source()
        fixed = patcher.patch(original)
        invalid = [
            'unknown bundle',
            original.replace('.k-1LKG_fill)>', '.unknown)>'),
            original.replace('(width<768px)', '(width<800px)'),
            original.replace('}:has(', '}[data-unknown]:has(', 1),
            original + original,
            fixed + fixed,
            original + fixed,
            fixed.replace('const token = { fill: mode === "fill" };', 'const token = {};'),
            original.replace(':has(', ':where([data-files-content],[data-textpreview-content]):has('),
        ]
        for old, new in patcher.REPLACEMENTS:
            invalid.extend((original.replace(old, new), original + old, fixed + new))
        for candidate in invalid:
            with self.subTest(source=candidate), self.assertRaises(ValueError):
                patcher.patch(candidate)

    def test_standalone_check_publication_idempotence_and_version_guard(self):
        with tempfile.TemporaryDirectory() as temporary:
            host = Path(temporary)
            package = host / 'dsh-client-ui-sidebar-files'
            (package / 'lib').mkdir(parents=True)
            manifest = package / 'package.json'
            manifest.write_text(json.dumps({'name': '@deepseek-ai/dsh-client-ui-sidebar-files', 'version': '0.2.2-rc.1'}))
            client = package / 'lib/client.js'
            client.write_text(source())
            command = [os.sys.executable, '-B', patcher.__file__, '--host-dir', str(host), '--check']
            original = client.read_bytes()
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('Required patches missing', result.stderr)
            self.assertEqual(client.read_bytes(), original)
            patcher.publish(patcher.plan_changes(host), host / 'backups')
            result = subprocess.run(command, capture_output=True, text=True, timeout=15)
            self.assertEqual(result.returncode, 0, result.stderr)
            stamp = client.stat().st_mtime_ns
            patcher.publish(patcher.plan_changes(host), host / 'backups')
            self.assertEqual(stamp, client.stat().st_mtime_ns)
            self.assertEqual(len(list((host / 'backups').iterdir())), 1)
            for name, version in (
                ('@deepseek-ai/dsh-client-ui-sidebar-files', '0.2.2-rc.0'),
                ('@deepseek-ai/dsh-client-ui-sidebar-files', '0.2.2-rc.2'),
                ('@deepseek-ai/unknown', '0.2.2-rc.1'),
            ):
                manifest.write_text(json.dumps({'name': name, 'version': version}))
                with self.subTest(name=name, version=version), self.assertRaises(ValueError):
                    patcher.plan_changes(host)
                self.assertEqual(client.stat().st_mtime_ns, stamp)

    def test_alpha2_skips_without_reading_client(self):
        with tempfile.TemporaryDirectory() as temporary:
            package = Path(temporary) / 'dsh-client-ui-sidebar-files'
            package.mkdir()
            (package / 'package.json').write_text(json.dumps({
                'name': '@deepseek-ai/dsh-client-ui-sidebar-files', 'version': '0.2.2-alpha.2'}))
            self.assertEqual(patcher.plan_changes(Path(temporary)), [])

    def test_ref_lifecycle_aggregation_and_cleanup(self):
        result = subprocess.run(
            ['node', str(Path(__file__).parent / 'test_dsh_sidebar_render_lifecycle.cjs')],
            input=json.dumps({'source': patcher.patch(source()).split('\n', 1)[1]}),
            capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(os.environ.get('DSH_TEST_PLAYWRIGHT'), 'Set DSH_TEST_PLAYWRIGHT for browser CSS regression')
    def test_browser_navigator_visibility_and_specificity(self):
        original = source()
        result = subprocess.run(
            ['node', str(Path(__file__).with_suffix('.cjs'))],
            input=json.dumps({'original': FIXTURE.read_text(), 'fixed': patcher.patch(original).split('\n', 1)[0],
                              'helper': patcher.HELPER}),
            capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
