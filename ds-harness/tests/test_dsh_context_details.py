"""Check the native context-panel extension and its quota integration."""
import test_support
import os
from pathlib import Path
import subprocess
import tempfile
import unittest
from patches.service import dsh_context_details_apply as patcher

FIXTURE = Path(__file__).parent / 'fixtures/context_meter_rc1.js'

class ContextDetailsTests(unittest.TestCase):
    def test_native_context_extension_is_idempotent_and_rejects_drift(self):
        source = FIXTURE.read_text() + '\n' + patcher.DECLARE
        fixed = patcher.patch(source)
        self.assertEqual(patcher.patch(fixed), fixed)
        self.assertIn('renderSlot?.("conversation.context.details"', fixed)
        self.assertIn('"data-dsh-session-info-owner": dshSessionInfoOwner', fixed)
        legacy = (fixed.replace(patcher.SIGNATURE_NEW, patcher.SIGNATURE_LEGACY)
                  .replace(patcher.PANEL_NEW, patcher.PANEL)
                  .replace(patcher.VISIBILITY_NEW, patcher.VISIBILITY)
                  .replace(patcher.PORTAL_NEW, patcher.PORTAL))
        self.assertEqual(patcher.patch(legacy), fixed)
        for broken in (
            legacy.replace(patcher.PANEL_END_NEW, patcher.PANEL_END),
            legacy.replace(patcher.DECLARE_NEW, patcher.DECLARE),
            legacy + patcher.SIGNATURE_LEGACY,
            fixed.replace(patcher.PANEL_NEW, patcher.PANEL),
            fixed + patcher.PANEL_NEW,
            fixed.replace(patcher.VISIBILITY_NEW, patcher.VISIBILITY),
            fixed.replace(patcher.PORTAL_NEW, patcher.PORTAL),
        ):
            with self.assertRaises(ValueError):
                patcher.patch(broken)
        with self.assertRaises(ValueError):
            patcher.patch(source.replace(patcher.PANEL_END, 'unknown upstream'))

    @unittest.skipUnless(all(os.environ.get(name) for name in
        ('DSH_TEST_PLAYWRIGHT','DSH_TEST_REACT_UMD','DSH_TEST_REACT_DOM_UMD')),
        'Set browser test dependencies')
    def test_quota_inside_native_context_panel(self):
        with tempfile.TemporaryDirectory() as temp:
            script = Path(temp) / 'context.js'
            text = patcher.patch(FIXTURE.read_text() + '\n' + patcher.DECLARE)
            script.write_text(text.removesuffix('\n' + patcher.DECLARE_NEW))
            result = subprocess.run(['node', str(Path(__file__).with_name('test_codex_quota_browser.cjs')), str(script)],
                                    capture_output=True,text=True,timeout=60)
            self.assertEqual(result.returncode,0,result.stdout+result.stderr)

if __name__ == '__main__':
    unittest.main()
