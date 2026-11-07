"""Exercise resource dispatch with current and legacy mobile URL implementations."""
import test_support  # Configure the service source import path.
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

from patches.service import dsh_file_resources_apply as patcher


class FileResourcePatchTests(unittest.TestCase):
    def test_protocol_dispatch_with_legacy_url_and_current_url(self):
        script = r'''
const vm = require('node:vm'), assert = require('node:assert/strict');
const {old, fixed} = JSON.parse(require('node:fs').readFileSync(0, 'utf8'));
class LegacyURL extends URL {
  get hostname() { return this.protocol === 'dsh-resource:' ? '' : super.hostname; }
}
const addresses = [
  'dsh-resource://file/session/test/README.md',
  'DSH-RESOURCE://FILE/session/test/a%20b.md',
  'dsh-resource://changes-review/session/test/1/2',
  'dsh-resource://subagentchat/test',
];
const compile = (source, URL) => vm.runInNewContext(source + '\nprotocolOf', {URL});
const baseline = compile(old, URL), legacy = compile(old, LegacyURL);
const currentFixed = compile(fixed, URL), legacyFixed = compile(fixed, LegacyURL);
for (const address of addresses) {
  assert.equal(legacy(address), undefined); // reproduces provider lookup failure
  assert.equal(legacyFixed(address), baseline(address));
  assert.equal(currentFixed(address), baseline(address));
}
for (const address of ['bad', 'file:///tmp/a', 'https://file/a',
    'dsh-resource:///file/a', 'dsh-resource://', 'dsh-resource://file@/a']) {
  assert.equal(legacyFixed(address), undefined);
  assert.equal(currentFixed(address), baseline(address));
}
// The address and session/path authority are passed through, not rewritten.
const address = addresses[0], providers = new Map([['file', value => value]]);
assert.equal(providers.get(legacyFixed(address))(address), address);
'''
        result = subprocess.run(['node', '-e', script], input=json.dumps({
            'old': patcher.OLD, 'fixed': patcher.NEW}), text=True,
            capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_apply_check_idempotence_and_version_rejection(self):
        with tempfile.TemporaryDirectory() as temp:
            host = Path(temp)
            package = host / 'dsh-client-resources'
            (package / 'lib').mkdir(parents=True)
            manifest = package / 'package.json'
            manifest.write_text(json.dumps({'name': '@deepseek-ai/dsh-client-resources', 'version': '0.2.2-rc.1'}))
            client = package / 'lib/client.js'
            client.write_text(patcher.OLD)
            cli = ['python3', '-B', patcher.__file__, '--host-dir', str(host)]
            self.assertNotEqual(subprocess.run(cli + ['--check'], capture_output=True).returncode, 0)
            patcher.publish(patcher.plan_changes(host), host / 'backups')
            self.assertEqual(subprocess.run(cli + ['--check'], capture_output=True).returncode, 0)
            self.assertEqual(patcher.patch(client.read_text()), client.read_text())
            stamp = client.stat().st_mtime_ns
            patcher.publish(patcher.plan_changes(host), host / 'backups')
            self.assertEqual(stamp, client.stat().st_mtime_ns)
            manifest.write_text(json.dumps({'name': '@deepseek-ai/dsh-client-resources', 'version': '0.2.2-alpha.2'}))
            self.assertTrue(all(before == after for _, before, after in patcher.plan_changes(host)))
            for version in ('0.2.1', '0.2.3'):
                manifest.write_text(json.dumps({'name': '@deepseek-ai/dsh-client-resources', 'version': version}))
                with self.assertRaises(ValueError):
                    patcher.plan_changes(host)
                self.assertEqual(stamp, client.stat().st_mtime_ns)

    def test_unknown_and_mixed_sources_are_rejected(self):
        for source in ('unknown', patcher.OLD * 2, patcher.NEW + patcher.OLD):
            with self.assertRaises(ValueError):
                patcher.patch(source)


if __name__ == '__main__':
    unittest.main()
