const {sourceFile, fixtureFile} = require('./support.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

test('access initialization handles piped input and never replaces existing files', t => {
  const cases = [
    ['\n\n', { ip: '10.30.0.25', port: 25227 }],
    ['  ::1  \n 31415 \n', { ip: '::1', port: 31415 }],
    ['invalid\n127.0.0.1\n25226\n65536\n1e3\n31415\n', { ip: '127.0.0.1', port: 31415 }],
    ['', null], ['127.0.0.1\n', null],
  ];
  for (const [input, expected] of cases) {
    const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-access-'));
    t.after(() => fs.rmSync(root, { recursive: true, force: true }));
    const data = path.join(root, 'data');
    const run = text => spawnSync(process.execPath, [sourceFile('paseo-config.cjs'), 'access', data], {
      input: text, encoding: 'utf8', timeout: 5000,
    });
    const file = path.join(data, 'paseo.conf');
    const result = run(input);
    assert.equal(result.status, expected ? 0 : 1, result.stderr);
    if (!expected) {
      assert.match(result.stderr, /配置未创建/);
      assert.ok(!fs.existsSync(file));
      continue;
    }
    assert.deepEqual(JSON.parse(fs.readFileSync(file)), { ...expected, networkProxy: '' });
    assert.equal(fs.statSync(file).mode & 0o777, 0o600);
    fs.writeFileSync(file, 'existing configuration');
    assert.equal(run('').status, 0);
    assert.equal(fs.readFileSync(file, 'utf8'), 'existing configuration');
    fs.unlinkSync(file);
    fs.symlinkSync(path.join(root, 'missing-target'), file);
    assert.equal(run('').status, 0);
    assert.ok(fs.lstatSync(file).isSymbolicLink());
    assert.ok(!fs.existsSync(path.join(root, 'missing-target')));
  }
});

test('installer creates both configurations and preserves custom configuration on reinstall', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-install-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, 'srcs'), { recursive: true });
  for (const file of ['install.sh', 'paseo-config.cjs', 'config.json.example']) {
    fs.copyFileSync(sourceFile(file), fixtureFile(root, file));
  }
  fs.mkdirSync(path.join(root, 'bin'));
  fs.symlinkSync(process.execPath, path.join(root, 'bin/node'));
  fs.writeFileSync(path.join(root, 'bin/npm'), '#!/usr/bin/env bash\nprintf "%s\\n" "$@" > "$PASEO_INSTALL_TEST_NPM_ARGS"\n', {mode: 0o755});
  // Keep network/package installation out of this configuration lifecycle test.
  fs.writeFileSync(path.join(root, 'srcs/node-runtime.sh'), 'paseo_select_node() { export PATH="$ROOT/bin:$PATH"; }\n');
  fs.writeFileSync(path.join(root, 'srcs/paseo_nginx_install.sh'), 'exit 0\n');
  fs.writeFileSync(fixtureFile(root, 'patch-web-ui.cjs'), '');
  fs.writeFileSync(fixtureFile(root, 'patch-workspace-git-startup.cjs'), '');
  fs.writeFileSync(fixtureFile(root, 'patch-dsh-catalog.cjs'), '');
  const run = input => spawnSync('bash', [path.join(root, 'install.sh')], {
    input, encoding: 'utf8', timeout: 10000,
    env: { ...process.env, PASEO_RUNTIME_PREFIX: path.join(root, 'runtime'), PASEO_UPSTREAM_ONLY: '0', PASEO_VERSION: '99.0.0', PASEO_INSTALL_TEST_NPM_ARGS: path.join(root, 'npm-args') },
  });
  let result = run('10.30.0.25\n25027\n');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.readFileSync(path.join(root, 'npm-args'), 'utf8').trim().split('\n').at(-1), '@getpaseo/cli@0.16.0-beta.1');
  const accessFile = path.join(root, 'data/paseo.conf');
  assert.deepEqual(JSON.parse(fs.readFileSync(accessFile)), {ip: '10.30.0.25', port: 25027, networkProxy: ''});
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
