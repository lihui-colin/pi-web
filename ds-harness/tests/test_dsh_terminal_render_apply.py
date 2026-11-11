"""Strict direct-render candidate tests, without modifying installed packages."""
import test_support
from pathlib import Path
import json
import subprocess
import tempfile
import unittest
from patches.service import dsh_terminal_render_apply as p
from patches.service import dsh_terminal_apply as legacy
from patches.service import dsh_terminal_batching_apply as batching


class TerminalRenderTests(unittest.TestCase):
    def original(self):
        return (Path(__file__).parent / 'fixtures/dsh_terminal_screen_rc1.js').read_text()

    def test_idempotence_and_mixed_rejection(self):
        original = self.original()
        direct = p.patch(original)
        self.assertEqual(p.patch(direct), direct)
        for source in (original + original, direct + direct, direct.replace('let alive = true', 'let alive = false'),
                       direct.replace('renderSink.dispose();', 'renderSink.unknown();'), original.replace('lastRevision.current = 0;', 'lastRevision.current = 1;')):
            with self.subTest(source=source[:50]), self.assertRaises(ValueError):
                p.patch(source)

    def test_exact_legacy_ui_skips_sink_and_mixed_legacy_rejects(self):
        enhanced = legacy.patch_frontend(self.original())
        self.assertEqual(p.patch(enhanced), enhanced)
        for source in (enhanced.replace('const redraw =', 'const unknown ='), enhanced + p.HELPER):
            with self.assertRaises(ValueError):
                p.patch(source)

    def test_plan_versions_and_entry_fingerprint(self):
        with tempfile.TemporaryDirectory() as root:
            package = Path(root) / 'dsh-client-ui-sidebar-terminal'
            (package / 'lib').mkdir(parents=True)
            manifest = package / 'package.json'
            manifest.write_text(json.dumps({'name': '@deepseek-ai/dsh-client-ui-sidebar-terminal', 'version': '0.2.2-rc.1'}))
            (package / 'lib/client.terminal.js').write_text(self.original())
            (package / 'lib/client.js').write_text('// entry\n//# sourceMappingURL=client.js.map\n')
            changes = p.plan_changes(Path(root))
            self.assertEqual(len(changes), 2)
            self.assertIn('dshBindTerminalRenderSink', changes[0][2])
            self.assertNotEqual(changes[1][1], changes[1][2])
            manifest.write_text(json.dumps({'name': '@deepseek-ai/dsh-client-ui-sidebar-terminal', 'version': '0.2.2-alpha.2'}))
            self.assertEqual(p.plan_changes(Path(root)), [])
            manifest.write_text(json.dumps({'name': '@deepseek-ai/dsh-client-ui-sidebar-terminal', 'version': '0.2.2-rc.2'}))
            with self.assertRaises(ValueError):
                p.plan_changes(Path(root))

    def test_deployed_batching_migrates_only_exact_known_helper(self):
        original = (Path(__file__).parent / 'fixtures/dsh_terminal_model_rc1.js').read_text()
        start = original.index(batching.START)
        end = original.index(batching.END, start)
        legacy = (Path(__file__).parent / 'fixtures/dsh_terminal_batching_v1.js').read_text()
        deployed = legacy + original[:start] + batching.CONSUME + original[end:]
        upgraded = batching.patch(deployed)
        self.assertEqual(upgraded, batching.patch(original))
        self.assertEqual(upgraded, batching.patch(upgraded))
        for mixed in (deployed.replace('const maxRecords = 4096;', 'const maxRecords = 8;'),
                      deployed + batching.HELPER,
                      deployed.replace(batching.ANCHOR, '\n' + batching.ANCHOR),
                      deployed.replace(batching.ANCHOR, '// unknown helper tail\n' + batching.ANCHOR),
                      upgraded.replace(batching.ANCHOR, '\n' + batching.ANCHOR)):
            with self.assertRaises(ValueError):
                batching.patch(mixed)

    def test_transformed_model_and_ui(self):
        result = subprocess.run(['node', '--test', str(Path(__file__).with_name('test_dsh_terminal_render.cjs'))], capture_output=True, text=True, timeout=30)
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
