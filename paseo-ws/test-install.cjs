const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

test('installer creates both configurations and preserves custom configuration on reinstall', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-install-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  for (const file of ['install.sh', 'init-access-config.sh', 'paseo-config.cjs', 'config.json.example']) {
    fs.copyFileSync(path.join(__dirname, file), path.join(root, file));
  }
  fs.mkdirSync(path.join(root, 'bin'));
  fs.symlinkSync(process.execPath, path.join(root, 'bin/node'));
  fs.writeFileSync(path.join(root, 'bin/npm'), '#!/usr/bin/env bash\nexit 0\n', {mode: 0o755});
  // Keep network/package installation out of this configuration lifecycle test.
  fs.writeFileSync(path.join(root, 'node-runtime.sh'), 'paseo_select_node() { export PATH="$ROOT/bin:$PATH"; }\n');
  fs.writeFileSync(path.join(root, 'paseo_nginx_install.sh'), 'exit 0\n');
  fs.writeFileSync(path.join(root, 'patch-web-ui.cjs'), '');
  fs.writeFileSync(path.join(root, 'patch-dsh-catalog.cjs'), '');
  const run = input => spawnSync('bash', [path.join(root, 'install.sh')], {
    input, encoding: 'utf8', timeout: 10000,
  });
  let result = run('10.30.0.25\n25027\n');
  assert.equal(result.status, 0, result.stderr);
  const accessFile = path.join(root, 'data/paseo.conf');
  assert.deepEqual(JSON.parse(fs.readFileSync(accessFile)), {ip: '10.30.0.25', port: 25027});
  const file = path.join(root, 'data/.paseo/config.json');
  assert.equal(JSON.parse(fs.readFileSync(file)).daemon.relay.enabled, false);
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  const custom = '{"version":1,"daemon":{"auth":{"password":"preserve"}},"agents":{"providers":{"pi":{"enabled":true}}}}\n';
  fs.writeFileSync(file, custom);
  const before = fs.readFileSync(accessFile, 'utf8');
  result = run('');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.readFileSync(file, 'utf8'), custom);
  assert.equal(fs.readFileSync(accessFile, 'utf8'), before);
});
