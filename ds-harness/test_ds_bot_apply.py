"""Exercise the standalone patch against isolated current-version package trees."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from patches import ds_bot_apply as p
from patches import dsh_mobile_apply as mobile


class CompletePatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bot = self.root / 'bot'
        self.host = self.root / 'host'
        for directory, name, version in [
            (self.bot, 'ds-bot', '0.2.6'),
            (self.host / 'dsh-client-ui-chat', '@deepseek-ai/dsh-client-ui-chat', '0.2.2-alpha.2'),
            (self.host / 'dsh-client-ui-conversation', '@deepseek-ai/dsh-client-ui-conversation', '0.2.2-alpha.2'),
        ]:
            directory.mkdir(parents=True)
            (directory / 'package.json').write_text(json.dumps({'name': name, 'version': version}))
        sources = {
            self.bot / 'client.js': '\n'.join([a for a, _ in p.HISTORY_BOT_REPLACEMENTS] + [
                p.MOBILE_GRID, p.MOBILE_TRACK, p.MOBILE_GROUP_OLD, p.MOBILE_META_CSS,
                p.MOBILE_RAIL_CSS, p.MOBILE_COMPOSER, p.WIDTH_HANDLES, p.WIDTH_BODY, p.WIDTH_COMPOSER,
                p.ALIGN_ANCHOR] + [a for a, _ in p.MESSAGE_ACTION_REPLACEMENTS]),
            self.bot / 'src/host/tools.js': p.PROMPT_OLD,
            self.host / 'dsh-client-ui-chat/lib/client.js': '\n'.join(a for a, _ in p.HISTORY_CHAT_REPLACEMENTS),
            self.host / 'dsh-client-ui-conversation/lib/client.js': '\n'.join(
                [a for a, _ in p.HISTORY_CONVERSATION_REPLACEMENTS] + [p.COMPOSER_ANCHOR, mobile.VIEW_LIMIT_OLD]),
        }
        for path, source in sources.items():
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(source)
        self.sources = sources
        # Copy only the one script: no imports from retired patch modules may be needed.
        self.script = self.root / 'patches/ds_bot_apply.py'
        self.script.parent.mkdir()
        shutil.copy2(p.__file__, self.script)

    def run_cli(self, *args, status=0):
        result = subprocess.run([sys.executable, '-B', str(self.script), '--bot-dir', str(self.bot),
                                 '--host-dir', str(self.host), *args], capture_output=True, text=True)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return result

    def test_standalone_applies_every_fix_and_is_idempotent(self):
        self.run_cli('--check', status=1)
        self.assertEqual({path: path.read_text() for path in self.sources}, self.sources)
        self.run_cli()
        self.run_cli('--check')
        self.assertIn(p.MOBILE_COMPOSER_CSS, (self.bot / 'client.js').read_text())
        self.assertIn(p.HISTORY_INSERT, (self.bot / 'client.js').read_text())
        self.assertIn(p.WIDTH_BODY_FIXED, (self.bot / 'client.js').read_text())
        self.assertIn(p.ALIGN_CSS, (self.bot / 'client.js').read_text())
        self.assertIn(p.DIRECT_BUTTONS, (self.bot / 'client.js').read_text())
        conversation = (self.host / 'dsh-client-ui-conversation/lib/client.js').read_text()
        self.assertIn(p.COMPOSER_REPLACEMENT, conversation)
        self.assertIn(mobile.VIEW_LIMIT_OLD, conversation)
        self.assertNotIn(mobile.VIEW_LIMIT_NEW, conversation)
        before = {path: path.stat().st_mtime_ns for path in self.sources}
        self.run_cli()
        self.assertEqual(before, {path: path.stat().st_mtime_ns for path in self.sources})

    def test_missing_composer_fix_is_detected_and_repaired(self):
        self.run_cli()
        target = self.host / 'dsh-client-ui-conversation/lib/client.js'
        target.write_text(target.read_text().replace(p.COMPOSER_REPLACEMENT, p.COMPOSER_ANCHOR))
        self.run_cli('--check', status=1)
        self.run_cli()
        self.run_cli('--check')

    def test_existing_install_gets_width_controls(self):
        self.run_cli()
        target = self.bot / 'client.js'
        target.write_text(target.read_text().replace(p.WIDTH_HANDLES_FIXED, p.WIDTH_HANDLES)
                          .replace(p.WIDTH_BODY_FIXED, p.WIDTH_BODY)
                          .replace(p.WIDTH_COMPOSER_FIXED, p.WIDTH_COMPOSER))
        self.run_cli('--check', status=1)
        self.run_cli()
        self.run_cli('--check')
        self.assertIn(p.WIDTH_HANDLES_FIXED, target.read_text())

    def test_bad_last_target_prevents_all_writes(self):
        target = self.host / 'dsh-client-ui-conversation/lib/client.js'
        target.write_text('unknown layout')
        before = {path: path.read_bytes() for path in self.sources}
        self.run_cli(status=1)
        self.assertEqual(before, {path: path.read_bytes() for path in self.sources})
        self.assertFalse((self.root / 'log').exists())

    def test_old_and_unknown_versions_are_rejected_without_writes(self):
        manifest = self.bot / 'package.json'
        for version in ['0.2.4', '0.2.5', '0.2.7']:
            manifest.write_text(json.dumps({'name': 'ds-bot', 'version': version}))
            self.run_cli(status=1)
            self.assertEqual(self.sources, {path: path.read_text() for path in self.sources})
        manifest.write_text(json.dumps({'name': 'ds-bot', 'version': '0.2.6'}))
        host_manifest = self.host / 'dsh-client-ui-conversation/package.json'
        host_manifest.write_text(json.dumps({'name': '@deepseek-ai/dsh-client-ui-conversation', 'version': '0.2.1'}))
        self.run_cli(status=1)
        self.assertEqual(self.sources, {path: path.read_text() for path in self.sources})


if __name__ == '__main__':
    unittest.main()
