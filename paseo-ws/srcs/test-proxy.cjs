const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

test('proxy configuration supports set, clear, show and legacy delete from any cwd', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-proxy-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, 'srcs'));
  fs.mkdirSync(path.join(root, 'data'));
  fs.copyFileSync(path.join(__dirname, '../paseo-proxy.sh'), path.join(root, 'paseo-proxy.sh'));
  fs.copyFileSync(path.join(__dirname, 'paseo-config.cjs'), path.join(root, 'srcs/paseo-config.cjs'));
  // Use the test runner's Node; no installed service or package manager is needed.
  fs.writeFileSync(path.join(root, 'srcs/node-runtime.sh'), 'paseo_select_node() { return 0; }\n');
  const file = path.join(root, 'data/paseo.conf');
  const base = { ip: '127.0.0.1', port: 25227 };
  fs.writeFileSync(file, JSON.stringify(base));
  const run = (...args) => spawnSync('bash', [path.join(root, 'paseo-proxy.sh'), ...args], {
    cwd: '/', encoding: 'utf8',
    env: { ...process.env, PATH: `${path.dirname(process.execPath)}:${process.env.PATH}` },
  });
  for (const args of [[], ['show']]) {
    const result = run(...args);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /未配置/);
  }
  assert.ok(!fs.existsSync(path.join(root, 'data/service.lock')), 'show does not write a lock file');
  for (const clear of ['clear', 'delete']) {
    const proxy = 'http://alice:secret@127.0.0.1:7890';
    assert.equal(run('set', proxy).status, 0);
    assert.deepEqual(JSON.parse(fs.readFileSync(file)), { ...base, networkProxy: proxy });
    const shown = run('show');
    assert.equal(shown.status, 0, shown.stderr);
    assert.match(shown.stdout, /http:\/\/\*\*\*@127\.0\.0\.1:7890/);
    assert.doesNotMatch(shown.stdout + shown.stderr, /alice|secret/);
    const before = fs.readFileSync(file, 'utf8');
    for (const args of [['set'], ['set', 'invalid'], ['clear', 'extra'], ['show', 'extra']]) {
      assert.notEqual(run(...args).status, 0);
      assert.equal(fs.readFileSync(file, 'utf8'), before);
    }
    assert.equal(run(clear).status, 0);
    assert.equal(run(clear).status, 0);
    assert.deepEqual(JSON.parse(fs.readFileSync(file)), base);
  }
  fs.unlinkSync(file);
  for (const help of ['help', '--help', '-h']) assert.equal(run(help).status, 0);
});
