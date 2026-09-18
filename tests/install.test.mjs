import { execFileSync, spawnSync } from 'node:child_process';
import { chmodSync, copyFileSync, mkdtempSync, mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, test } from 'node:test';
import assert from 'node:assert/strict';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const roots = [];
afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});
function git(cwd, ...args) {
  return execFileSync('git', ['-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', ...args], { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}
function fixture({ conflict = false, failure = '' } = {}) {
  const root = mkdtempSync(join(tmpdir(), 'pi-web patch test '));
  roots.push(root);
  const upstream = join(root, 'upstream');
  const source = join(root, 'patch-source');
  const origin = join(root, 'origin.git');
  const bin = join(root, 'bin');
  const releases = join(root, 'releases');
  const log = join(root, 'calls.log');
  for (const dir of [upstream, source, bin]) mkdirSync(dir);
  writeFileSync(log, '');
  git(upstream, 'init', '-b', 'main');
  const original = Array.from({ length: 20 }, (_, i) => `line ${i}`).join('\n') + '\n';
  writeFileSync(join(upstream, 'app.txt'), original);
  git(upstream, 'add', '.');
  git(upstream, 'commit', '-m', 'upstream base');
  writeFileSync(join(upstream, 'app.txt'), original.replace('line 0\n', 'custom layout\n'));
  const patch = git(upstream, 'diff', '--binary', '--full-index', 'HEAD') + '\n';
  git(upstream, 'restore', 'app.txt');
  writeFileSync(join(upstream, 'app.txt'), original.replace(conflict ? 'line 0\n' : 'line 19\n', 'new upstream\n'));
  git(upstream, 'commit', '-am', 'upstream update');
  git(root, 'init', '--bare', origin);
  git(source, 'init', '-b', 'terminal-patch');
  mkdirSync(join(source, 'patches'));
  writeFileSync(join(source, 'patches', '0001-layout.patch'), patch);
  for (const file of ['install.sh', 'sync.sh']) copyFileSync(join(repo, file), join(source, file));
  git(source, 'add', '.');
  git(source, 'commit', '-m', 'patch-only root');
  git(source, 'remote', 'add', 'origin', origin);
  writeFileSync(join(bin, 'npm'), `#!/bin/sh
printf 'npm %s\n' "$*" >> "$TEST_LOG"
if [ "$TEST_FAILURE" = "$*" ]; then exit 7; fi
if [ "$*" = 'run build' ]; then mkdir -p dist; printf 'built' > dist/cli.js; fi
`);
  writeFileSync(join(bin, 'node'), `#!/bin/sh
if [ "$1" = '--no-experimental-webstorage' ]; then exit 0; fi
printf 'node %s\n' "$*" >> "$TEST_LOG"
test -f dist/cli.js || exit 8
printf 'installed %s\n' "$PWD" >> "$TEST_LOG"
`);
  for (const file of ['node', 'npm']) chmodSync(join(bin, file), 0o755);
  const run = (script = 'install.sh') => spawnSync('sh', [join(source, script), ...(script === 'install.sh' ? ['--port', '8510'] : [])], {
    cwd: root, encoding: 'utf8', env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, PI_WEB_UPSTREAM_URL: upstream, PI_WEB_INSTALL_ROOT: releases, TEST_LOG: log, TEST_FAILURE: failure },
  });
  return { source, upstream, origin, log, releases, run };
}

test('syncs pure main locally and remotely, applies patches, then validates and installs', () => {
  const f = fixture();
  const patchHead = git(f.source, 'rev-parse', 'HEAD');
  const result = f.run();
  assert.equal(result.status, 0, result.stderr);
  const calls = readFileSync(f.log, 'utf8').trim().split('\n');
  assert.deepEqual(calls.slice(0, 5), [
    'npm install -g @earendil-works/pi-coding-agent@latest',
    'npm ci --include=dev', 'npm test', 'npm run build',
    'node dist/cli.js install --port 8510',
  ]);
  const installed = calls[5].slice('installed '.length);
  assert.ok(installed.startsWith(f.releases));
  assert.match(readFileSync(join(installed, '.npmrc'), 'utf8'), /allow-scripts=node-pty,esbuild/);
  const app = readFileSync(join(installed, 'app.txt'), 'utf8');
  assert.ok(app.includes('custom layout') && app.includes('new upstream'));
  const upstreamHead = git(f.upstream, 'rev-parse', 'HEAD');
  assert.equal(git(f.source, 'rev-parse', 'main'), upstreamHead);
  assert.equal(git(f.origin, 'rev-parse', 'main'), upstreamHead);
  assert.equal(git(f.source, 'rev-parse', 'HEAD'), patchHead);
  assert.equal(git(f.source, 'status', '--porcelain'), '');
  assert.equal(git(f.source, 'rev-list', '--count', 'terminal-patch'), '1');
  assert.ok(!git(f.source, 'ls-tree', '--name-only', 'terminal-patch').includes('app.txt'));
  assert.equal(f.run().status, 0);
  const installs = readFileSync(f.log, 'utf8').split('\n').filter(line => line.startsWith('installed '));
  assert.equal(new Set(installs).size, 2);
  assert.equal(readFileSync(join(installed, 'app.txt'), 'utf8'), app);
});

test('sync-only prepares a patch release without updating Agent or installing services', () => {
  const f = fixture();
  const result = f.run('sync.sh');
  assert.equal(result.status, 0, result.stderr);
  assert.ok(readFileSync(join(result.stdout.trim(), 'app.txt'), 'utf8').includes('custom layout'));
  assert.equal(readFileSync(f.log, 'utf8'), '');
});

test('conflicts stop installation while main stays pure upstream', () => {
  const f = fixture({ conflict: true });
  const result = f.run();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Patch conflict/);
  assert.match(result.stderr, /retained directory/);
  assert.equal(readFileSync(f.log, 'utf8').trim(), 'npm install -g @earendil-works/pi-coding-agent@latest');
  assert.equal(git(f.source, 'rev-parse', 'main'), git(f.upstream, 'rev-parse', 'HEAD'));
});

for (const failure of ['install -g @earendil-works/pi-coding-agent@latest', 'ci --include=dev', 'test', 'run build']) {
  test(`does not install services after ${failure} fails`, () => {
    const f = fixture({ failure });
    const result = f.run();
    assert.notEqual(result.status, 0);
    const calls = readFileSync(f.log, 'utf8');
    assert.equal(calls.trim().split('\n').at(-1), `npm ${failure}`);
    assert.ok(!calls.includes('node dist/cli.js install'));
  });
}

test('refuses to overwrite divergent local main', () => {
  const f = fixture();
  git(f.source, 'fetch', f.upstream, 'main:main');
  git(f.source, 'switch', 'main');
  writeFileSync(join(f.source, 'local.txt'), 'keep me');
  git(f.source, 'add', 'local.txt');
  git(f.source, 'commit', '-m', 'local work');
  const oldMain = git(f.source, 'rev-parse', 'main');
  git(f.source, 'switch', 'terminal-patch');
  assert.notEqual(f.run('sync.sh').status, 0);
  assert.equal(git(f.source, 'rev-parse', 'main'), oldMain);
  assert.equal(readFileSync(f.log, 'utf8'), '');
});

test('refuses to overwrite divergent origin/main', () => {
  const f = fixture();
  assert.equal(f.run('sync.sh').status, 0);
  const remoteWork = join(f.source, '..', 'other-user');
  git(f.source, 'clone', '--branch', 'main', f.origin, remoteWork);
  writeFileSync(join(remoteWork, 'remote.txt'), 'keep remote work');
  git(remoteWork, 'add', '.');
  git(remoteWork, 'commit', '-m', 'remote work');
  git(remoteWork, 'push', 'origin', 'main');
  const oldMain = git(f.origin, 'rev-parse', 'main');
  assert.notEqual(f.run('sync.sh').status, 0);
  assert.equal(git(f.origin, 'rev-parse', 'main'), oldMain);
});
