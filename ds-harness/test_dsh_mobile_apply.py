"""Mobile owns both plugin presentation and host view-tab fitting."""
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from patches import dsh_mobile_apply as p


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
            p.OLD, p.RIGHT_ICON_OLD, "'files': '文件浏览'", "'files': 'Files'", p.DRAWER_LOG_OLD,
            'exports.LAYOUT_CSS = `' + p.ANCHOR, p.TAB_ANCHOR, p.ROW_ANCHOR, *selectors, '}`;',
        ]))
        self.conversation.write_text(p.VIEW_LIMIT_OLD)

    def run_cli(self, *args):
        return subprocess.run([sys.executable, '-B', p.__file__, '--mobile-dir', str(self.mobile),
                               '--host-dir', str(self.host), *args], capture_output=True, text=True)

    def test_applies_both_targets_and_checks_host_independently(self):
        # Use the shared publisher with a temporary backup location.
        changes = p.plan_changes(self.mobile, self.host)
        p.publish(changes, self.mobile / 'backups')
        self.assertIn(p.NEW, self.plugin.read_text())
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


if __name__ == '__main__':
    unittest.main()
