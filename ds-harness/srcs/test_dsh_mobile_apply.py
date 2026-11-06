"""Mobile owns both plugin presentation and host view-tab fitting."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from patches import dsh_mobile_apply as p
from patches import dsh_mobile_legacy as legacy
from patches import ds_bot_apply as bot


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

    def setUp(self):
        MobilePatchTests.setUp(self)
        (self.mobile / 'package.json').write_text(json.dumps({'name': 'dsh-web-mobile', 'version': self.mobile_version}))
        (self.host / 'dsh-client-ui-conversation/package.json').write_text(json.dumps({
            'name': '@deepseek-ai/dsh-client-ui-conversation', 'version': '0.2.2-rc.1'}))
        self.plugin.write_text('Upstream ' + self.mobile_version + ' plugin stays unchanged')
        self.conversation.write_text(bot.COMPOSER_ANCHOR + '\n' + p.VIEW_LIMIT_OLD)

    def test_keeps_upstream_mobile_and_migrates_host_atomically(self):
        upstream = self.plugin.read_bytes()
        self.conversation.write_text(bot.patch_composer(self.conversation.read_text()))
        self.assertNotEqual(self.run_cli('--check').returncode, 0)
        p.publish(p.plan_changes(self.mobile, self.host), self.mobile / 'backups')
        self.assertEqual(self.plugin.read_bytes(), upstream)
        self.assertEqual(self.conversation.read_text(), bot.COMPOSER_ANCHOR + '\n' + p.VIEW_LIMIT_NEW)
        self.assertEqual(self.run_cli('--check').returncode, 0)
        self.assertTrue(all(old == new for _, old, new in p.plan_changes(self.mobile, self.host)))

    def test_retires_enter_when_adaptive_tabs_are_already_installed(self):
        upstream = self.plugin.read_bytes()
        self.conversation.write_text(bot.COMPOSER_REPLACEMENT + '\n' + p.VIEW_LIMIT_NEW)
        self.assertNotEqual(self.run_cli('--check').returncode, 0)
        p.publish(p.plan_changes(self.mobile, self.host), self.mobile / 'backups')
        self.assertEqual(self.conversation.read_text(), bot.COMPOSER_ANCHOR + '\n' + p.VIEW_LIMIT_NEW)
        self.assertEqual(self.plugin.read_bytes(), upstream)
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


class Mobile331Tests(CurrentMobileTests):
    mobile_version = '3.3.1'


if __name__ == '__main__':
    unittest.main()
