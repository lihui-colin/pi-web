"""Mobile owns both plugin presentation and host view-tab fitting."""
import test_support  # Configure the service source import path.
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from patches.plugins.mobile import dsh_mobile_apply as p
from patches.plugins.mobile import dsh_mobile_legacy as legacy
from patches.plugins.ds_bot import ds_bot_apply as bot


class MobilePatchTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        self.mobile, self.host = root / 'mobile', root / 'host'
        for directory, name, version in (
            (self.mobile, 'dsh-web-mobile', '3.2.1'),
            (self.host / 'dsh-client-ui-conversation', '@deepseek-ai/dsh-client-ui-conversation', '0.2.2-alpha.2'),
        ):
            (directory / 'lib').mkdir(parents=True)
            (directory / 'package.json').write_text(json.dumps({'name': name, 'version': version}))
        self.plugin = self.mobile / 'lib/client.js'
        self.conversation = self.host / 'dsh-client-ui-conversation/lib/client.js'
        selectors = ['html [data-mobile-nav="frame"] [data-conversation-header-leading] ' + label
                     for label in ('button[aria-label*="sidebar" i]', 'button[aria-label*="侧边栏"]')]
        self.plugin.write_text('\n'.join([
            legacy.OLD, legacy.RIGHT_ICON_OLD, "'files': '文件浏览'", "'files': 'Files'", legacy.DRAWER_LOG_OLD,
            'exports.LAYOUT_CSS = `' + legacy.ANCHOR, legacy.TAB_ANCHOR, legacy.ROW_ANCHOR, *selectors, '}`;',
        ]))
        self.conversation.write_text(p.VIEW_LIMIT_OLD)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-B', p.__file__, '--mobile-dir', str(self.mobile),
                               '--host-dir', str(self.host), *args], capture_output=True, text=True)

    def test_applies_both_targets_and_checks_host_independently(self):
        # Use the shared publisher with a temporary backup location.
        changes = p.plan_changes(self.mobile, self.host)
        p.publish(changes, self.mobile / 'backups')
        self.assertIn(legacy.NEW, self.plugin.read_text())
        self.assertEqual(self.conversation.read_text(), p.VIEW_LIMIT_NEW)
        self.assertEqual(self.run_cli('--check').returncode, 0)
        self.assertTrue(all(old == new for _, old, new in p.plan_changes(self.mobile, self.host)))
        self.conversation.write_text(p.VIEW_LIMIT_OLD)
        result = self.run_cli('--check')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(str(self.conversation), result.stderr)

    def test_invalid_host_prevents_plugin_write(self):
        original = self.plugin.read_bytes()
        for version, source in [('0.2.3', p.VIEW_LIMIT_OLD), ('0.2.2-alpha.2', 'unknown layout')]:
            self.conversation.parent.parent.joinpath('package.json').write_text(json.dumps({
                'name': '@deepseek-ai/dsh-client-ui-conversation', 'version': version}))
            self.conversation.write_text(source)
            self.assertNotEqual(self.run_cli().returncode, 0)
            self.assertEqual(self.plugin.read_bytes(), original)

    def test_native_fallback_without_mobile_layout(self):
        # Native paths must never enter the DOM measurement branch.
        script = r"""
const assert = require('node:assert/strict');
const effect = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
for (const [matches, enabled] of [[false, false], [false, true], [true, false]]) {
  let limit, cleanup, markerCallback, mediaCallback;
  const query = { matches, addEventListener: (_, fn) => mediaCallback = fn,
    removeEventListener: (_, fn) => assert.equal(fn, mediaCallback) };
  const frame = {};
  const row = { clientWidth: 374, closest: () => enabled ? frame : null,
    querySelector: () => { throw Error('Mobile measurement used outside mobile layout'); } };
  const react = { useLayoutEffect: fn => cleanup = fn() };
  const document = { querySelector: () => ({parentElement: frame}) };
  class ResizeObserver { observe() {} disconnect() {} }
  class MutationObserver { constructor(fn) { markerCallback = fn; } observe() {} disconnect() {} }
  const window = { matchMedia: () => query };
  const tabRow = {current: row}, hasEntryActions = true, showTabs = true, tabs = [], unpinned = [];
  const setVisibleViewLimit = n => limit = n;
  eval(effect);
  assert.equal(limit, 2);
  row.clientWidth = 820;
  markerCallback();
  assert.equal(limit, 6);
  row.clientWidth = 390;
  mediaCallback();
  assert.equal(limit, 2);
  cleanup();
}
"""
        result = subprocess.run(['node', '-e', script], input=json.dumps(p.VIEW_LIMIT_NEW),
                                capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_migrates_legacy_phone_limit(self):
        legacy = p.VIEW_LIMIT_OLD.replace(p.VIEW_LIMIT_UPSTREAM, p.VIEW_LIMIT_LEGACY)
        self.assertEqual(p.patch_view_tabs(legacy), p.VIEW_LIMIT_NEW)
        self.assertEqual(p.patch_view_tabs(p.VIEW_LIMIT_UNSCOPED), p.VIEW_LIMIT_NEW)
        self.assertEqual(p.patch_view_tabs(p.VIEW_LIMIT_NEW), p.VIEW_LIMIT_NEW)


class CurrentMobileTests(unittest.TestCase):
    run_cli = MobilePatchTests.run_cli
    mobile_version = '3.3.0'
    focus_guard = ''
    patched_guard = ''

    def setUp(self):
        MobilePatchTests.setUp(self)
        (self.mobile / 'package.json').write_text(json.dumps({'name': 'dsh-web-mobile', 'version': self.mobile_version}))
        (self.host / 'dsh-client-ui-conversation/package.json').write_text(json.dumps({
            'name': '@deepseek-ai/dsh-client-ui-conversation', 'version': '0.2.2-rc.1'}))
        self.plugin.write_text(p.COMPOSER_FILE_BUTTON + self.focus_guard)
        self.conversation.write_text(bot.COMPOSER_ANCHOR + '\n' + p.VIEW_LIMIT_OLD)

    def test_removes_file_button_and_migrates_host_atomically(self):
        self.conversation.write_text(bot.patch_composer(self.conversation.read_text()))
        self.assertNotEqual(self.run_cli('--check').returncode, 0)
        p.publish(p.plan_changes(self.mobile, self.host), self.mobile / 'backups')
        self.assertEqual(self.plugin.read_text(), p.COMPOSER_FILE_BUTTON_REMOVED + self.patched_guard)
        self.assertEqual(self.conversation.read_text(), bot.COMPOSER_ANCHOR + '\n' + p.VIEW_LIMIT_NEW)
        self.assertEqual(self.run_cli('--check').returncode, 0)
        self.assertTrue(all(old == new for _, old, new in p.plan_changes(self.mobile, self.host)))

    def test_retires_enter_when_adaptive_tabs_are_already_installed(self):
        self.conversation.write_text(bot.COMPOSER_REPLACEMENT + '\n' + p.VIEW_LIMIT_NEW)
        self.assertNotEqual(self.run_cli('--check').returncode, 0)
        p.publish(p.plan_changes(self.mobile, self.host), self.mobile / 'backups')
        self.assertEqual(self.conversation.read_text(), bot.COMPOSER_ANCHOR + '\n' + p.VIEW_LIMIT_NEW)
        self.assertEqual(self.plugin.read_text(), p.COMPOSER_FILE_BUTTON_REMOVED + self.patched_guard)
        self.assertEqual(self.run_cli('--check').returncode, 0)

    def test_unknown_source_and_mixed_version_do_not_write(self):
        for version, source in [('0.2.2-alpha.2', self.conversation.read_text()),
                                ('0.2.2-rc.1', 'unknown editor'),
                                ('0.2.2-rc.1', bot.COMPOSER_ANCHOR + '\nunknown tabs')]:
            (self.host / 'dsh-client-ui-conversation/package.json').write_text(json.dumps({
                'name': '@deepseek-ai/dsh-client-ui-conversation', 'version': version}))
            self.conversation.write_text(source)
            originals = [self.plugin.read_bytes(), self.conversation.read_bytes()]
            self.assertNotEqual(self.run_cli().returncode, 0)
            self.assertEqual([self.plugin.read_bytes(), self.conversation.read_bytes()], originals)

    def test_absent_button_is_skipped(self):
        self.plugin.write_text('plugin without the extra button' + self.focus_guard)
        changes = p.plan_changes(self.mobile, self.host)
        self.assertEqual(changes[0][2], 'plugin without the extra button' + self.patched_guard)

    def test_terminal_focus_guard_version_scope(self):
        source = p.COMPOSER_FILE_BUTTON_REMOVED + '\nunknown focus guard'
        self.plugin.write_text(source)
        if self.mobile_version == '3.3.5':
            with self.assertRaises(ValueError):
                p.plan_changes(self.mobile, self.host)
        else:
            changes = p.plan_changes(self.mobile, self.host)
            self.assertEqual(changes[0][2], source)

    def test_unknown_or_mixed_button_registration_is_rejected(self):
        for source in ('unknown mobile-nav-file-upload registration', p.COMPOSER_FILE_BUTTON * 2,
                       p.COMPOSER_FILE_BUTTON + p.COMPOSER_FILE_BUTTON_REMOVED):
            self.plugin.write_text(source)
            originals = [self.plugin.read_bytes(), self.conversation.read_bytes()]
            self.assertNotEqual(self.run_cli().returncode, 0)
            self.assertEqual([self.plugin.read_bytes(), self.conversation.read_bytes()], originals)


class Mobile331Tests(CurrentMobileTests):
    mobile_version = '3.3.1'


class Mobile335Tests(CurrentMobileTests):
    mobile_version = '3.3.5'
    focus_guard = (Path(__file__).parent / 'fixtures/mobile_focus_guard_3_3_5.cjs').read_text()
    patched_guard = p.patch_terminal_focus_guard(focus_guard)

    def test_existing_button_removal_migrates_guard_without_writing_during_plan(self):
        self.plugin.write_text(p.COMPOSER_FILE_BUTTON_REMOVED + self.focus_guard)
        originals = [self.plugin.read_bytes(), self.conversation.read_bytes()]
        changes = p.plan_changes(self.mobile, self.host)
        self.assertEqual([self.plugin.read_bytes(), self.conversation.read_bytes()], originals)
        self.assertEqual(changes[0][2], p.COMPOSER_FILE_BUTTON_REMOVED + self.patched_guard)
        p.publish(changes, self.mobile / 'backups')
        self.assertTrue(all(old == new for _, old, new in p.plan_changes(self.mobile, self.host)))
        self.assertEqual(p.patch_terminal_focus_guard(self.patched_guard), self.patched_guard)

    def test_partial_guard_is_rejected_before_any_publication(self):
        replacements = p.TERMINAL_FOCUS_REPLACEMENTS
        for mask in range(1, (1 << len(replacements)) - 1):
            with self.subTest(mask=mask):
                partial = self.focus_guard
                for index, (old, new) in enumerate(replacements):
                    if mask & (1 << index):
                        partial = partial.replace(old, new, 1)
                self.plugin.write_text(p.COMPOSER_FILE_BUTTON + partial)
                originals = [self.plugin.read_bytes(), self.conversation.read_bytes()]
                result = self.run_cli()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Incomplete mobile terminal focus patch', result.stderr)
                self.assertEqual([self.plugin.read_bytes(), self.conversation.read_bytes()], originals)

    def test_unknown_duplicate_and_mixed_guard_are_rejected(self):
        sources = (
            self.focus_guard.replace('sinceGestureMs > GESTURE_WINDOW_MS', 'sinceGestureMs >= GESTURE_WINDOW_MS'),
            self.patched_guard.replace("element.closest('.xterm')", "element.closest('.unknown')"),
            self.focus_guard + self.focus_guard,
            self.patched_guard + self.patched_guard,
            self.patched_guard + p.TERMINAL_FOCUS_HELPER,
            self.focus_guard + self.patched_guard,
            'function dshSameInputSurface() { /* unknown helper revision */ }',
        )
        for source in sources:
            with self.subTest(source=source[:90]):
                with self.assertRaises(ValueError):
                    p.patch_terminal_focus_guard(source)


if __name__ == '__main__':
    unittest.main()
