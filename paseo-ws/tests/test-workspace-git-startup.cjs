const { sourceFile, fixtureFile } = require('./support.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');
const baseline = require('../srcs/patches/service/patch-web-ui.baseline.json');
const { patchSource } = require('../srcs/patches/service/patch-workspace-git-startup.cjs');
const vm = require('node:vm');
const initialMethod = `    scheduleInitialWorkspaceRefresh(target) {
        queueMicrotask(() => {
            if (!this.isActiveObservedWorkspaceTarget(target) || target.latestSnapshot) {
                return;
            }
            void this.refreshWorkspaceTarget(target, {
                origin: "demand",
                force: false,
                refreshStructure: true,
                refreshWorktree: true,
                includeForge: true,
                reason: "initial",
                queueIfBusy: false,
                movedRemoteRefs: new Set(),
            });
        });
    }`;
const sourceFor = option => `class Service {
    refresh() { return { includeForge: true }; }
${initialMethod.replace('includeForge: true', option)}
    scheduleWorkspaceObservationSetup(target) {}
}`;

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
  const original = sourceFor(option);
  fs.writeFileSync(file, original);
  const run = () => spawnSync(process.execPath, [fixtureFile(root, 'patch-workspace-git-startup.cjs')], { encoding: 'utf8', env: { ...process.env, PASEO_RUNTIME_PREFIX: path.join(root, 'runtime') } });
  return { file, original, run };
}

test('initial refresh skips forge without changing later refreshes and remains idempotent', t => {
  const { file, original, run } = fixture(t);
  assert.equal(run().status, 0);
  const patched = patchSource(original);
  assert.notEqual(patched, original);
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

for (const legacy of [false, true]) test(`local snapshot precedes immediate Forge discovery (legacy=${legacy})`, async () => {
  const source = sourceFor(legacy ? 'includeForge: false' : 'includeForge: true');
  const patched = patchSource(source);
  assert.equal(patchSource(patched), patched);
  const Service = vm.runInNewContext('(' + patched + ')', { queueMicrotask, Set });
  const service = new Service(), target = {}, requests = [];
  let finishLocal;
  service.isActiveObservedWorkspaceTarget = () => true;
  service.refreshWorkspaceTarget = async (observed, request) => {
    requests.push(request);
    if (request.includeForge) {
      assert.ok(target.latestSnapshot, 'local state has already been published');
      return;
    }
    await new Promise(resolve => { finishLocal = resolve; });
    target.latestSnapshot = { git: {} };
  };
  service.scheduleInitialWorkspaceRefresh(target);
  await new Promise(setImmediate);
  assert.equal(requests.length, 1);
  assert.equal(requests[0].includeForge, false);
  finishLocal();
  await new Promise(setImmediate);
  assert.equal(requests.length, 2);
  assert.equal(requests[1].includeForge, true);
  assert.equal(requests[1].refreshStructure, false);
  assert.equal(requests[1].refreshWorktree, false);
  assert.equal(requests[1].queueIfBusy, true, 'bypass the recent local-refresh throttle');
});

for (const state of ['inactive', 'no-snapshot']) test(`Forge continuation skips ${state} targets`, async () => {
  const Service = vm.runInNewContext('(' + patchSource(sourceFor('includeForge: true')) + ')', { queueMicrotask, Set });
  const service = new Service(), target = {};
  let active = true, calls = 0;
  service.isActiveObservedWorkspaceTarget = () => active;
  service.refreshWorkspaceTarget = async () => {
    calls++;
    if (state === 'inactive') { target.latestSnapshot = {}; active = false; }
  };
  service.scheduleInitialWorkspaceRefresh(target);
  await new Promise(setImmediate);
  assert.equal(calls, 1);
});

test('installed upstream module upgrades idempotently and preserves other methods', async t => {
  const { serverRoot } = require('../srcs/patches/patch-utils.cjs');
  const file = path.join(serverRoot, 'dist/server/server/workspace-git-service.js');
  if (!fs.existsSync(file)) {
    assert.ok(!process.env.PASEO_RUNTIME_PREFIX, 'explicit runtime must contain the upstream Git module');
    return t.skip(`Paseo ${baseline.version} module not installed`);
  }
  const installed = JSON.parse(fs.readFileSync(path.join(serverRoot, 'package.json'), 'utf8'));
  if (installed.version !== baseline.version) {
    assert.ok(!process.env.PASEO_RUNTIME_PREFIX, `explicit runtime version ${installed.version} must match ${baseline.version}`);
    return t.skip(`Paseo ${baseline.version} module not installed`);
  }
  t.diagnostic(`Read-only upstream verification: ${installed.version} at ${file}`);
  const source = fs.readFileSync(file, 'utf8');
  const patched = patchSource(source);
  assert.equal(patchSource(patched), patched);
  const begin = '    scheduleInitialWorkspaceRefresh(target) {';
  const end = '\n    scheduleWorkspaceObservationSetup(target) {';
  assert.equal(patched.slice(0, patched.indexOf(begin)), source.slice(0, source.indexOf(begin)));
  assert.equal(patched.slice(patched.indexOf(end)), source.slice(source.indexOf(end)));
  const method = patched.slice(patched.indexOf(begin), patched.indexOf(end));
  assert.doesNotThrow(() => new vm.Script('(class Service {\n' + method + '\n})'));
  const pristine = source.slice(source.indexOf(begin), source.indexOf(end));
  // Compare the release module against the reviewed canonical method, including
  // installations carrying the earlier local-only version of this patch.
  const canonical = patchSource(sourceFor('includeForge: true'));
  assert.equal(method, canonical.slice(canonical.indexOf(begin), canonical.indexOf(end)));
  assert.ok(pristine.includes('includeForge: true') || pristine.includes('includeForge: false'));
  for (const changed of [
    source.replace(begin, '    unknownInitialWorkspaceRefresh(target) {'),
    source.replace(end, '\n    unknownWorkspaceObservationSetup(target) {'),
    source.replace(pristine, pristine.replace(/includeForge: (true|false),/, 'includeForge: unknown,')),
    source.replace(pristine, pristine.replace('reason: "initial"', 'reason: "unknown"')),
  ]) {
    assert.throws(() => patchSource(changed), /changed|anchor/, 'refuse drift in the actual release module');
  }

  // Execute the release's real admission/refresh pipeline. Only the shell/forge
  // boundaries are faked; throttle, request handling and snapshot publication
  // use the actual release methods instead of a mocked refreshWorkspaceTarget.
  const extract = name => {
    const match = patched.match(new RegExp(`\\n    (?:async )?${name}\\(`));
    assert.ok(match, `release method ${name} exists`);
    const tail = patched.slice(match.index + 1);
    const next = tail.indexOf('\n    }') + '\n    }'.length;
    assert.ok(next > '\n    }'.length);
    return tail.slice(0, next);
  };
  const methods = ['scheduleInitialWorkspaceRefresh', 'refreshWorkspaceTarget', 'requestWorkspaceSnapshot', 'runWorkspaceRefreshLoop', 'refreshSnapshot'].map(extract).join('\n');
  const ReleaseService = vm.runInNewContext('(class Service {\n' + methods + '\n})', {
    queueMicrotask, Set, createRunGitCommand: () => () => {}, buildNotGitSnapshot: () => ({ git: null }),
  });
  const service = new ReleaseService();
  const target = { cwd: '/fixture', refreshState: { status: 'idle' } };
  service.workspaceTargets = new Map([[target.cwd, target]]);
  service.pendingRefreshes = new Set();
  service.workspaceRefreshLimit = callback => callback();
  service.deps = { now: () => new Date() };
  service.logger = { warn: (...args) => assert.fail(JSON.stringify(args)) };
  service.isActiveObservedWorkspaceTarget = () => true;
  let local = 0, worktree = 0, forge = 0, throttles = 0, releaseForge;
  service.shouldThrottleNonForcedRefresh = () => ++throttles > 1;
  service.refreshGitSnapshot = async () => {
    local++;
    target.latestFacts = { isGit: true };
    target.latestGit = { isGit: true };
    return target.latestFacts;
  };
  service.refreshWorktreeSnapshot = async () => { worktree++; };
  service.refreshForgeSnapshot = async () => {
    forge++;
    assert.ok(target.latestSnapshot, 'local snapshot published before Forge starts');
    await new Promise(resolve => { releaseForge = resolve; });
  };
  service.combineSnapshot = () => ({ git: target.latestGit });
  service.rememberSnapshot = (observed, snapshot) => { observed.latestSnapshot = snapshot; };
  service.scheduleInitialWorkspaceRefresh(target);
  await new Promise(setImmediate);
  assert.equal(local, 1);
  assert.equal(worktree, 0, 'Forge continuation reuses warmed local Git state');
  assert.equal(forge, 1, 'Forge runs immediately despite the recent local refresh');
  assert.equal(throttles, 1, 'Forge continuation bypasses the upstream throttle');
  releaseForge();
  await new Promise(setImmediate);
  assert.equal(service.pendingRefreshes.size, 0);
  assert.equal(target.refreshState.status, 'idle');
});
