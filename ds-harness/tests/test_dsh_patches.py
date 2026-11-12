"""Exercise all real planners and their shared-file publication together."""
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
from patches.service import dsh_context_details_apply as context_details
from patches.service import dsh_sidebar_render_apply as sidebar
from patches.service import dsh_terminal_batching_apply as batching
from patches.service import dsh_terminal_host_batching_apply as host_batching
from patches.service import dsh_terminal_render_apply as rendering
from patches.service import dsh_terminal_webgl_apply as webgl


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

        bot_source = (Path(__file__).parent / 'fixtures/ds_bot_031.js').read_text()
        package(self.profile / 'node_modules/ds-bot', 'ds-bot', '0.3.1', {'client.js': bot_source})
        focus_guard = (Path(__file__).parent / 'fixtures/mobile_focus_guard_3_3_5.cjs').read_text()
        package(self.profile / 'node_modules/dsh-web-mobile', 'dsh-web-mobile', '3.3.5',
                {'lib/client.js': mobile.COMPOSER_FILE_BUTTON + focus_guard})
        package(self.profile / 'node_modules/@xbzbing/dsh-git-panel', '@xbzbing/dsh-git-panel',
                '1.11.2', {'lib/client.js': git.PILL})
        conversation = '\n'.join([
            *[before for before, _ in bot.HISTORY_CONVERSATION_REPLACEMENTS],
            bot.COMPOSER_ANCHOR, mobile.VIEW_LIMIT_OLD, metadata.ANCHOR, metadata.OLD,
            metadata.TRAILING, metadata.REGISTER_ANCHOR,
            (Path(__file__).parent / "fixtures/context_meter_rc1.js").read_text(), context_details.DECLARE,
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
                '0.2.2-rc.1', {
                    'lib/client.terminal.js': (Path(__file__).parent / 'fixtures/dsh_terminal_screen_rc1.js').read_text() + '\n' + webgl.ANCHOR,
                    'lib/client.js': '// Client entry\n//# sourceMappingURL=client.js.map\n',
                })
        package(self.host / 'dsh-api-terminal-controller', '@deepseek-ai/dsh-api-terminal-controller',
                '0.2.2-rc.1', {
                    'lib/client.js': (Path(__file__).parent / 'fixtures/dsh_terminal_model_rc1.js').read_text(),
                    'lib/index.js': (Path(__file__).parent / 'fixtures/dsh_terminal_host_rc1.js').read_text(),
                })
        package(self.host / 'dsh-client-resources', '@deepseek-ai/dsh-client-resources',
                '0.2.2-rc.1', {'lib/client.js': resources.OLD})
        package(self.host / 'dsh-client-ui-sidebar-files', '@deepseek-ai/dsh-client-ui-sidebar-files',
                '0.2.2-rc.1', {'lib/client.js': '\n'.join((Path(__file__).parent / 'fixtures' / name).read_text()
                    for name in ('sidebar_navigator_rc1.css', 'sidebar_navigator_ref_rc1.js'))})
        for name, version in (('headless', '6.0.0'), ('addon-serialize', '0.14.0')):
            package(self.host.parent / '@xterm' / name, '@xterm/' + name, version, {})

        script = self.root / 'srcs/patches'
        shutil.copytree(test_support.SRC_DIR / 'patches', script)
        entry = self.root / 'dsh_patches_install.sh'
        shutil.copy2(test_support.source_file(entry.name), entry)
        self.command = ['bash', str(entry),
                        '--profile-dir', str(self.profile), '--host-dir', str(self.host)]

    def cli(self, *args):
        return subprocess.run([*self.command, *args], cwd='/', capture_output=True, text=True, timeout=15)

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
        mobile_source = (self.profile / 'node_modules/dsh-web-mobile/lib/client.js').read_text()
        self.assertIn(mobile.TERMINAL_FOCUS_HELPER, mobile_source)
        self.assertNotIn(mobile.TERMINAL_BLUR_OLD, mobile_source)
        self.assertIn(metadata.REGISTER_TRIGGER, conversation)
        self.assertNotIn(bot.COMPOSER_REPLACEMENT, conversation)
        self.assertNotIn('conversation.chat.before', conversation)
        sidebar_css = (self.host / 'dsh-client-ui-sidebar-files/lib/client.js').read_text()
        self.assertNotIn(':has(', sidebar_css)
        for _, scoped in sidebar.REPLACEMENTS:
            self.assertIn(scoped, sidebar_css)
        terminal_source = (self.host / 'dsh-client-ui-sidebar-terminal/lib/client.terminal.js').read_text()
        self.assertNotEqual(terminal_source, self.sources[self.host / 'dsh-client-ui-sidebar-terminal/lib/client.terminal.js'])
        self.assertIn(webgl.HELPER, terminal_source)
        self.assertNotIn(rendering.HELPER, terminal_source)  # Keep legacy clipboard/tools semantics.
        self.assertIn('DSH terminal lazy chunk SHA256:', (self.host / 'dsh-client-ui-sidebar-terminal/lib/client.js').read_text())
        self.assertIn(host_batching.HELPER, (self.host / 'dsh-api-terminal-controller/lib/index.js').read_text())
        controller = (self.host / 'dsh-api-terminal-controller/lib/client.js').read_text()
        self.assertIn(batching.CONSUME, controller)
        self.assertIn(batching.HELPER, controller)
        self.assertIn(terminal.FORCE_SIGNATURE_NEW, controller)
        self.assertEqual(self.cli('--check').returncode, 0)
        before = self.snapshot()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('已安装，跳过：', result.stdout)
        self.assertNotIn('已应用补丁：', result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertFalse((self.root / 'log').exists())
        self.assertEqual(len(list(self.backups.iterdir())), 1)

    def test_partial_install_only_writes_and_backs_up_missing_targets(self):
        common.publish(apply.plan_changes(self.profile, self.host), self.backups)
        target = self.host / 'dsh-client-resources/lib/client.js'
        target.write_text(resources.OLD)
        before = self.snapshot()
        result = self.cli()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(f'已应用补丁：{target}', result.stdout)
        self.assertIn('已安装，跳过：', result.stdout)
        self.assertEqual(target.read_text(), resources.NEW)
        after = self.snapshot()
        for path in self.sources:
            if path != target:
                self.assertEqual(after[path], before[path])
        backups = list((self.root / 'log/patch-backups').iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(json.loads((backups[0] / 'manifest.json').read_text()), [str(target)])

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
