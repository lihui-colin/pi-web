const { sourceFile, fixtureFile } = require('./support.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const baseline = require('../srcs/patches/service/patch-web-ui.baseline.json');

function fixture(t, option = 'includeForge: true') {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-git-patch-'));
  t.after(() => {
    assert.ok(root.startsWith(path.join(os.tmpdir(), 'paseo-git-patch-')));
    fs.rmSync(root, { recursive: true, force: true });
  });
  for (const name of ['patch-workspace-git-startup.cjs', 'patch-utils.cjs', 'patch-web-ui.baseline.json']) {
    fs.copyFileSync(sourceFile(name), fixtureFile(root, name));
  }
  const server = path.join(root, 'runtime/lib/node_modules/@getpaseo/cli/node_modules/@getpaseo/server');
  const file = path.join(server, 'dist/server/server/workspace-git-service.js');
  fs.mkdirSync(path.dirname(file), { recursive: true });
  fs.writeFileSync(path.join(server, 'package.json'), JSON.stringify({ version: baseline.version, gitHead: baseline.commit }));
  const original = `class Service {
    refresh() { return { includeForge: true }; }
    scheduleInitialWorkspaceRefresh(target) { return { reason: "initial", ${option} }; }
    scheduleWorkspaceObservationSetup(target) {}
}`;
  fs.writeFileSync(file, original);
  const run = () => spawnSync(process.execPath, [fixtureFile(root, 'patch-workspace-git-startup.cjs')], { encoding: 'utf8', env: { ...process.env, PASEO_RUNTIME_PREFIX: path.join(root, 'runtime') } });
  return { file, original, run };
}

test('initial refresh skips forge without changing later refreshes and remains idempotent', t => {
  const { file, original, run } = fixture(t);
  assert.equal(run().status, 0);
  const patched = original.replace('reason: "initial", includeForge: true', 'reason: "initial", includeForge: false');
  assert.equal(fs.readFileSync(file, 'utf8'), patched);
  assert.equal(run().status, 0);
  assert.equal(fs.readFileSync(file, 'utf8'), patched);
});

test('unknown or ambiguous initial forge options never modify the source', t => {
  for (const option of ['includeForge: unknown', 'includeForge: true, includeForge: true', 'includeForge: true, includeForge: false', '']) {
    const { file, original, run } = fixture(t, option);
    assert.notEqual(run().status, 0);
    assert.equal(fs.readFileSync(file, 'utf8'), original);
  }
});
