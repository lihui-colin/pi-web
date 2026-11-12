"""Verify optional GPU renderer guards, cleanup and real-xterm fallback."""
import test_support
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from patches.service import dsh_terminal_webgl_apply as p
from patches.plugins.mobile import dsh_mobile_apply as mobile
from patches.service.dsh_terminal_assets import refresh_terminal_entry, MARKER


class WebglPatchTests(unittest.TestCase):
    def original(self):
        return '\n'.join((p.ANCHOR, p.OPEN, p.CLEANUP))

    def test_idempotence_and_partial_unknown_rejection(self):
        original = self.original()
        fixed = p.patch(original)
        self.assertEqual(p.patch(fixed), fixed)
        for invalid in (original + original, fixed + fixed, original + fixed,
                        fixed.replace("mark('webgl');", "mark('unknown');"),
                        original.replace(p.OPEN, p.REPLACEMENTS[1][1])):
            with self.assertRaises(ValueError):
                p.patch(invalid)

    def test_exact_deployed_helper_upgrade(self):
        old_runtime = (Path(__file__).parent / 'fixtures/dsh_terminal_webgl_v1.js').read_text().strip() + '\n'
        fixed = p.patch(self.original())
        deployed = fixed.replace(p.HELPER, p.ADDON + old_runtime, 1)
        self.assertNotEqual(deployed, fixed)
        self.assertEqual(p.patch(deployed), fixed)
        for invalid in (deployed.replace("mark('webgl');", "mark('unknown');"),
                        deployed + p.HELPER, deployed.replace(p.OPEN, '')):
            with self.assertRaises(ValueError):
                p.patch(invalid)

    def test_package_versions_and_alpha_skip(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            package = root / 'dsh-client-ui-sidebar-terminal'
            package.mkdir()
            manifest = package / 'package.json'
            manifest.write_text(json.dumps({'name': '@deepseek-ai/dsh-client-ui-sidebar-terminal', 'version': '0.2.2-alpha.2'}))
            self.assertEqual(p.plan_changes(root), [])
            manifest.write_text(json.dumps({'name': '@deepseek-ai/dsh-client-ui-sidebar-terminal', 'version': '0.2.2-rc.2'}))
            with self.assertRaises(ValueError):
                p.plan_changes(root)
            manifest.write_text(json.dumps({'name': '@deepseek-ai/dsh-client-ui-sidebar-terminal', 'version': '0.2.2-rc.1'}))
            (package / 'lib').mkdir()
            target = package / 'lib/client.terminal.js'
            target.write_text(self.original())
            (package / 'lib/client.js').write_text('// client entry\n//# sourceMappingURL=client.js.map\n')
            changes = p.plan_changes(root)
            self.assertEqual(len(changes), 2)
            self.assertIn(MARKER, changes[1][2])
            self.assertNotEqual(changes[0][1], changes[0][2])
            self.assertEqual(target.read_text(), self.original())

    def test_lazy_revision_changes_entry_and_preserves_map_trailer(self):
        for entry in ('// entry', '// entry\n//# sourceMappingURL=client.js.map\n'):
            first = refresh_terminal_entry(entry, 'frontend α')
            self.assertEqual(refresh_terminal_entry(first, 'frontend α'), first)
            second = refresh_terminal_entry(first, 'frontend β')
            self.assertNotEqual(first, second)
            self.assertEqual(second.count(MARKER), 1)
            if 'sourceMappingURL' in entry:
                self.assertTrue(second.endswith('//# sourceMappingURL=client.js.map\n'))
            for invalid in (first + first, first.replace(MARKER, MARKER + 'unknown')):
                with self.assertRaises(ValueError):
                    refresh_terminal_entry(invalid, 'frontend')

    def test_renderer_lifecycle(self):
        result = subprocess.run(['node', '--test', str(Path(__file__).with_name('test_dsh_terminal_webgl.cjs'))], capture_output=True, text=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(os.environ.get('DSH_TEST_PLAYWRIGHT') and os.environ.get('DSH_TEST_FRONTEND'), 'Set browser module and pristine DSH_TEST_FRONTEND')
    def test_mobile_touch_focus_with_original_plugin_guard(self):
        source = Path(os.environ['DSH_TEST_FRONTEND']).read_text()
        guard = (Path(__file__).parent / 'fixtures/mobile_focus_guard_3_3_5.cjs').read_text()
        result = subprocess.run(['node', str(Path(__file__).with_name('test_dsh_terminal_touch_browser.cjs'))],
                                input=json.dumps({'bundle': p.patch(source), 'guard': mobile.patch_terminal_focus_guard(guard)}), capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    @unittest.skipUnless(os.environ.get('DSH_TEST_PLAYWRIGHT') and os.environ.get('DSH_TEST_FRONTEND'), 'Set browser module and pristine DSH_TEST_FRONTEND')
    def test_real_xterm_gpu_and_dom_fallback(self):
        source = Path(os.environ['DSH_TEST_FRONTEND']).read_text()
        result = subprocess.run(['node', str(Path(__file__).with_name('test_dsh_terminal_webgl_browser.cjs'))],
                                input=json.dumps({'bundle': p.patch(source)}), capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
