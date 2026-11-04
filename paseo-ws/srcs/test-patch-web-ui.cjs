const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const baseline = require('./patch-web-ui.baseline.json');
const { checkCompatibility } = require('./patch-web-ui.cjs');

test('matching version and commit produce no warnings', () => {
  const warnings = [];
  checkCompatibility({ version: baseline.version, gitHead: baseline.commit }, text => warnings.push(text));
  assert.deepEqual(warnings, []);
});

test('different commits and versions produce warnings with expected and actual values', () => {
  const warnings = [];
  const actualCommit = '1'.repeat(40);
  checkCompatibility({ version: '99.0.0', gitHead: actualCommit }, text => warnings.push(text));
  assert.equal(warnings.length, 2);
  assert.ok(warnings.every(text => text.startsWith('[WARN]')));
  assert.ok(warnings[0].includes('99.0.0') && warnings[0].includes(baseline.version));
  assert.ok(warnings[1].includes(actualCommit) && warnings[1].includes(baseline.commit));
});

test('missing commit metadata warns even when version matches', () => {
  const warnings = [];
  checkCompatibility({ version: baseline.version }, text => warnings.push(text));
  assert.equal(warnings.length, 1);
  assert.match(warnings[0], /无法核对 commit ID/);
  assert.ok(warnings[0].includes(baseline.commit));
});

test('CLI warns before patching and preserves structural failure checks', t => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-patch-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  fs.mkdirSync(path.join(root, 'srcs'), { recursive: true });
  for (const file of ['patch-web-ui.cjs', 'patch-web-ui.baseline.json']) {
    fs.copyFileSync(path.join(__dirname, ['install.sh', 'paseo_web_run.sh'].includes(file) ? '..' : '.', file), path.join(root, ['install.sh', 'paseo_web_run.sh'].includes(file) ? '.' : 'srcs', file));
  }
  const server = path.join(root, 'runtime/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/server');
  const web = path.join(server, 'dist/server/web-ui');
  const assets = path.join(web, '_expo/static/js/web');
  fs.mkdirSync(assets, { recursive: true });
  fs.writeFileSync(path.join(server, 'package.json'), JSON.stringify({ version: baseline.version }));
  const html = '<head></head><script src="/_expo/static/js/web/index-123.js"></script>';
  fs.writeFileSync(path.join(web, 'index.html'), html);
  fs.writeFileSync(path.join(assets, 'index-123.js'), 'upstream structure changed');
  const result = spawnSync(process.execPath, [path.join(root, 'srcs/patch-web-ui.cjs')], { encoding: 'utf8' });
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /\[WARN\].*无法核对 commit ID/);
  assert.match(result.stderr, /Upstream bootstrap structure changed/);
  assert.equal(fs.readFileSync(path.join(web, 'index.html'), 'utf8'), html);
  assert.deepEqual(fs.readdirSync(assets), ['index-123.js']);
});
