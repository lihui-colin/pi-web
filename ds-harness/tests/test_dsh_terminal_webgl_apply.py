"""Verify safe retirement of the WebGL patch and restoration of native xterm."""
import test_support
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
from patches.service import dsh_terminal_webgl_apply as p
from patches.plugins.mobile import dsh_mobile_apply as mobile
from patches.service.dsh_terminal_assets import refresh_terminal_entry, MARKER


class WebglRemovalTests(unittest.TestCase):
    def original(self):
        return '\n'.join((p.ANCHOR, p.OPEN, '// unrelated terminal enhancements', p.CLEANUP))

    def retired(self, revision):
        # Synthetic helper keeps tests independent of the removed vendor bundle.
        helper = p.HELPER_PREFIX + f'// retired revision {revision}\n}})();\n'
        text = self.original().replace(p.ANCHOR, helper + p.ANCHOR)
        for original, installed in p.REPLACEMENTS:
            text = text.replace(original, installed)
        return helper, text

    def test_restores_exact_original_and_is_idempotent(self):
        self.assertEqual(p.patch(self.original()), self.original())
        for revision in (1, 2):
            helper, deployed = self.retired(revision)
            with patch.object(p, 'RETIRED_HELPERS', {hashlib.sha256(helper.encode()).hexdigest()}):
                restored = p.patch(deployed)
                self.assertEqual(restored, self.original())
                self.assertEqual(p.patch(restored), restored)

    def test_rejects_unknown_partial_or_mixed_deployments(self):
        helper, deployed = self.retired(2)
        with self.assertRaises(ValueError):
            p.patch(deployed)
        with patch.object(p, 'RETIRED_HELPERS', {hashlib.sha256(helper.encode()).hexdigest()}):
            for invalid in (deployed + deployed, deployed.replace(helper, ''),
                            deployed.replace(helper, helper + '// unknown change\n'),
                            deployed.replace(p.REPLACEMENTS[0][1], p.OPEN),
                            deployed.replace(p.REPLACEMENTS[1][1], p.CLEANUP),
                            deployed + '\ncreateDshTerminalWebgl(other, node);'):
                with self.subTest(invalid=invalid), self.assertRaises(ValueError):
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
            helper, deployed = self.retired(2)
            target = package / 'lib/client.terminal.js'
            target.write_text(deployed)
            (package / 'lib/client.js').write_text('// client entry\n//# sourceMappingURL=client.js.map\n')
            with patch.object(p, 'RETIRED_HELPERS', {hashlib.sha256(helper.encode()).hexdigest()}):
                changes = p.plan_changes(root)
            self.assertEqual(len(changes), 2)
            self.assertEqual(changes[0][2], self.original())
            self.assertIn(MARKER, changes[1][2])
            self.assertEqual(target.read_text(), deployed)

    def test_lazy_revision_changes_entry_and_preserves_map_trailer(self):
        for entry in ('// entry', '// entry\n//# sourceMappingURL=client.js.map\n'):
            first = refresh_terminal_entry(entry, 'frontend α')
            self.assertEqual(refresh_terminal_entry(first, 'frontend α'), first)
            second = refresh_terminal_entry(first, 'frontend β')
            self.assertNotEqual(first, second)
            self.assertEqual(second.count(MARKER), 1)
            self.assertEqual(second, refresh_terminal_entry(second, 'frontend β'))
            if 'sourceMappingURL' in entry:
                self.assertTrue(second.endswith('//# sourceMappingURL=client.js.map\n'))
            for invalid in (first + first, first.replace(MARKER, MARKER + 'unknown')):
                with self.assertRaises(ValueError):
                    refresh_terminal_entry(invalid, 'frontend')

    @unittest.skipUnless(os.environ.get('DSH_TEST_PLAYWRIGHT') and os.environ.get('DSH_TEST_FRONTEND'), 'Set browser module and DSH_TEST_FRONTEND')
    def test_mobile_touch_focus_with_native_renderer(self):
        source = Path(os.environ['DSH_TEST_FRONTEND']).read_text()
        guard = (Path(__file__).parent / 'fixtures/mobile_focus_guard_3_3_5.cjs').read_text()
        result = subprocess.run(['node', str(Path(__file__).with_name('test_dsh_terminal_touch_browser.cjs'))],
                                input=json.dumps({'bundle': p.patch(source), 'guard': mobile.patch_terminal_focus_guard(guard)}), capture_output=True, text=True, timeout=60)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == '__main__':
    unittest.main()
