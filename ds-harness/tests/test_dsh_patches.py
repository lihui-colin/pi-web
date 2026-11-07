"""Exercise all six real planners and their shared-file publication together."""
import test_support
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

from patches import apply, common
from patches.plugins.ds_bot import ds_bot_apply as bot
from patches.plugins.mobile import dsh_mobile_apply as mobile
from patches.plugins.git_panel import dsh_git_panel_apply as git
from patches.service import dsh_terminal_apply as terminal
from patches.service import dsh_file_resources_apply as resources
from patches.service import dsh_composer_metadata_apply as metadata


class PatchSetTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.profile = self.root / 'profile'
        self.host = self.root / 'node_modules/@deepseek-ai'
        self.backups = self.root / 'backups'
        self.sources = {}

        def package(directory, name, version, files):
            files = {'package.json': json.dumps({'name': name, 'version': version}), **files}
            for name, source in files.items():
                path = directory / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(source)
                self.sources[path] = source

        bot_source = '\n'.join([
            bot.MOBILE_GRID, bot.MOBILE_TRACK, bot.MOBILE_GROUP_OLD, bot.MOBILE_META_CSS,
            bot.MOBILE_RAIL_CSS, bot.MOBILE_COMPOSER, bot.WIDTH_HANDLES, bot.WIDTH_BODY,
            bot.WIDTH_COMPOSER, bot.ALIGN_ANCHOR,
            *[before for before, _ in bot.MESSAGE_ACTION_REPLACEMENTS],
        ]).replace('import_react17', 'import_react19')
        package(self.profile / 'node_modules/ds-bot', 'ds-bot', '0.2.7', {'client.js': bot_source})
        package(self.profile / 'node_modules/dsh-web-mobile', 'dsh-web-mobile', '3.3.1',
                {'lib/client.js': mobile.COMPOSER_FILE_BUTTON})
        package(self.profile / 'node_modules/@xbzbing/dsh-git-panel', '@xbzbing/dsh-git-panel',
                '1.11.2', {'lib/client.js': git.PILL})
        conversation = '\n'.join([
            *[before for before, _ in bot.HISTORY_CONVERSATION_REPLACEMENTS],
            bot.COMPOSER_ANCHOR, mobile.VIEW_LIMIT_OLD, metadata.ANCHOR, metadata.OLD,
            metadata.TRAILING, metadata.REGISTER_ANCHOR,
            *['"details.running": ' + json.dumps(label, ensure_ascii=False) + ','
              for label in metadata.TRANSLATIONS],
        ])
        # Begin with the retired history/Enter hooks, so migration and additions overlap.
        conversation = bot.patch_composer(bot.patch_history(conversation, bot.HISTORY_CONVERSATION_REPLACEMENTS))
        package(self.host / 'dsh-client-ui-conversation', '@deepseek-ai/dsh-client-ui-conversation',
                '0.2.2-rc.1', {'lib/client.js': conversation})
        chat = '\n'.join(before for before, _ in bot.HISTORY_CHAT_REPLACEMENTS)
        package(self.host / 'dsh-client-ui-chat', '@deepseek-ai/dsh-client-ui-chat',
                '0.2.2-rc.1', {'lib/client.js': bot.patch_history(chat, bot.HISTORY_CHAT_REPLACEMENTS)})
        package(self.host / 'dsh-client-ui-sidebar-terminal', '@deepseek-ai/dsh-client-ui-sidebar-terminal',
                '0.2.2-rc.1', {'lib/client.terminal.js': '\n'.join([
                    terminal.SCREEN_REF, terminal.SETUP, terminal.CLEANUP, terminal.FONT_FIT,
                    terminal.WRITE, terminal.VISIBLE, terminal.PHASE, terminal.RUNTIME_ANCHOR,
                    terminal.CLIP_HELPER, terminal.CLIP_SETUP, terminal.CLIP_CLEANUP, terminal.PROPOSED,
                ])})
        package(self.host / 'dsh-api-terminal-controller', '@deepseek-ai/dsh-api-terminal-controller',
                '0.2.2-rc.1', {
                    'lib/client.js': terminal.FORCE_SIGNATURE + '\n' + terminal.FORCE_CHECK,
                    'lib/index.js': '\n'.join([terminal.SNAPSHOT_ANCHOR, terminal.SERIALIZE,
                                              terminal.HOST_SETUP, terminal.HOST_WRITE, terminal.HOST_DISPOSE]),
                })
        package(self.host / 'dsh-client-resources', '@deepseek-ai/dsh-client-resources',
                '0.2.2-rc.1', {'lib/client.js': resources.OLD})
        for name, version in (('headless', '6.0.0'), ('addon-serialize', '0.14.0')):
            package(self.host.parent / '@xterm' / name, '@xterm/' + name, version, {})

        script = self.root / 'srcs/patches'
        shutil.copytree(test_support.SRC_DIR / 'patches', script)
        self.command = [sys.executable, '-B', str(script / 'apply.py'),
                        '--profile-dir', str(self.profile), '--host-dir', str(self.host)]

    def cli(self, *args):
        return subprocess.run([*self.command, *args], capture_output=True, text=True, timeout=15)

    def snapshot(self):
        return {path: (path.read_bytes(), path.stat().st_mtime_ns) for path in self.sources}

    def test_shared_file_migrations_publish_once_and_are_idempotent(self):
        before = self.snapshot()
        self.assertNotEqual(self.cli('--check').returncode, 0)
        changes = apply.plan_changes(self.profile, self.host)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(len(changes), len({path for path, _, _ in changes}))
        common.publish(changes, self.backups)
        conversation = (self.host / 'dsh-client-ui-conversation/lib/client.js').read_text()
        self.assertIn(mobile.VIEW_LIMIT_NEW, conversation)
        self.assertIn(metadata.REGISTER_TRIGGER, conversation)
        self.assertNotIn(bot.COMPOSER_REPLACEMENT, conversation)
        self.assertNotIn('conversation.chat.before', conversation)
        self.assertEqual(self.cli('--check').returncode, 0)
        before = self.snapshot()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / 'log').exists())
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_final_planner_failure_does_not_write_earlier_targets(self):
        conversation = self.host / 'dsh-client-ui-conversation/lib/client.js'
        conversation.write_text(conversation.read_text().replace(metadata.ANCHOR, 'unknown upstream'))
        before = self.snapshot()
        result = self.cli()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('dsh_composer_metadata_apply', result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / 'log').exists())

    def test_write_failure_rolls_back_complete_patch_set(self):
        changes = apply.plan_changes(self.profile, self.host)
        before = self.snapshot()
        original_replace = common.os.replace
        last = changes[-1][0]

        def fail_last(source, target):
            if target == last and Path(source).name == 'client':
                raise OSError('simulated write failure')
            return original_replace(source, target)

        with patch.object(common.os, 'replace', side_effect=fail_last):
            with self.assertRaisesRegex(RuntimeError, 'rolled back'):
                common.publish(changes, self.backups)
        self.assertEqual({path: path.read_text() for path in self.sources}, self.sources)
        self.assertEqual({path: value[0] for path, value in self.snapshot().items()},
                         {path: value[0] for path, value in before.items()})


if __name__ == '__main__':
    unittest.main()
