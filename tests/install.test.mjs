import { execFileSync, spawnSync } from 'node:child_process';
import { chmodSync, existsSync, copyFileSync, mkdtempSync, mkdirSync, readFileSync, realpathSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';
import { afterEach, test } from 'node:test';
import assert from 'node:assert/strict';

const repo = resolve(dirname(fileURLToPath(import.meta.url)), '..');
const roots = [];
const npm = execFileSync('sh', ['-c', 'command -v npm'], { encoding: 'utf8' }).trim();
afterEach(() => {
  for (const root of roots.splice(0)) rmSync(root, { recursive: true, force: true });
});
function git(cwd, ...args) {
  return execFileSync('git', ['-c', 'core.hooksPath=/dev/null', '-c', 'commit.gpgsign=false', '-c', 'user.name=Test', '-c', 'user.email=test@example.invalid', ...args], { cwd, encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] }).trim();
}
function fixture({ conflict = false, failure = '', agent = true, agentVersion = 'latest', maxWorkers = '4', testTimeout = '30000' } = {}) {
  const root = mkdtempSync(join(tmpdir(), 'pi-web patch test '));
  roots.push(root);
  const upstream = join(root, 'upstream');
  const source = join(root, 'patch-source');
  const origin = join(root, 'origin.git');
  const bin = join(root, 'bin');
  const releases = join(root, 'releases');
  const log = join(root, 'calls.log');
  const prefix = join(root, 'global');
  for (const dir of [upstream, source, bin]) mkdirSync(dir);
  writeFileSync(log, '');
  git(upstream, 'init', '-b', 'main');
  const original = Array.from({ length: 20 }, (_, i) => `line ${i}`).join('\n') + '\n';
  writeFileSync(join(upstream, 'app.txt'), original);
  writeFileSync(join(upstream, 'package.json'), JSON.stringify({
    name: '@jmfederico/pi-web', version: '1.0.0',
    bin: { 'pi-web': 'dist/cli.js', 'pi-web-server': 'dist/server/index.js', 'pi-web-sessiond': 'dist/server/sessiond.js' },
    scripts: { prepare: 'exit 99', prepack: 'exit 99', postinstall: 'exit 99' },
  }));
  git(upstream, 'add', '.');
  git(upstream, 'commit', '-m', 'upstream base');
  const baseCommit = git(upstream, 'rev-parse', 'HEAD');
  writeFileSync(join(upstream, 'app.txt'), original.replace('line 0\n', 'custom layout\n'));
  const patch = git(upstream, 'diff', '--binary', '--full-index', 'HEAD') + '\n';
  git(upstream, 'restore', 'app.txt');
  writeFileSync(join(upstream, 'app.txt'), original.replace(conflict ? 'line 0\n' : 'line 19\n', 'new upstream\n'));
  git(upstream, 'commit', '-am', 'upstream update');
  git(root, 'init', '--bare', origin);
  git(source, 'init', '-b', 'terminal-patch');
  mkdirSync(join(source, 'patches'));
  writeFileSync(join(source, 'patches', '0001-layout.patch'), patch);
  writeFileSync(join(source, 'patches', 'base-commit'), (conflict ? git(upstream, 'rev-parse', 'HEAD') : baseCommit) + '\n');
  mkdirSync(join(source, 'scripts'));
  for (const file of ['install.sh', 'sync.sh', 'pi-web-run-jmfederico.sh']) copyFileSync(join(repo, 'scripts', file), join(source, 'scripts', file));
  git(source, 'add', '.');
  git(source, 'commit', '-m', 'patch-only root');
  git(source, 'remote', 'add', 'origin', origin);
  writeFileSync(join(bin, 'npm'), `#!/bin/sh
printf 'npm %s\n' "$*" >> "$TEST_LOG"
if [ "$TEST_FAILURE" = "$*" ]; then exit 7; fi
if [ "$1" = ls ]; then exit 1; fi
case "$*" in
  'install -g --ignore-scripts @earendil-works/pi-coding-agent@'*)
    printf '#!/bin/sh\\necho 0.85.1\\n' > "$TEST_BIN/pi"
    chmod +x "$TEST_BIN/pi"
    exit 0 ;;
esac
if [ "$*" = 'run build' ]; then
  mkdir -p dist/server
  for entry in dist/cli.js dist/server/index.js dist/server/sessiond.js; do
    printf '#!/usr/bin/env node\\nconsole.log("patched");\\n' > "$entry"
    chmod +x "$entry"
  done
  printf 'built %s\\n' "$PWD" >> "$TEST_LOG"
fi
if [ "$1" = install ] || [ "$1" = prefix ]; then
  exec "$REAL_NODE" "$REAL_NPM" "$@" --prefix "$TEST_PREFIX" --offline
fi
`);
  writeFileSync(join(bin, 'node'), `#!/bin/sh
if [ "$1" = '-e' ]; then exec "$REAL_NODE" "$@"; fi
if [ "$1" = '--version' ]; then echo v22.19.0; exit 0; fi
if [ "$1" = '--no-experimental-webstorage' ]; then exit 0; fi
printf 'node %s\n' "$*" >> "$TEST_LOG"
test -f dist/cli.js || exit 8
printf 'installed %s\n' "$PWD" >> "$TEST_LOG"
`);
  if (agent) writeFileSync(join(bin, 'pi'), '#!/bin/sh\necho 0.85.1\n');
  for (const file of ['node', 'npm', ...(agent ? ['pi'] : [])]) chmodSync(join(bin, file), 0o755);
  const run = (script = 'install.sh', args = [], runFailure = failure) => spawnSync('sh', [join(source, 'scripts', script), ...args], {
    cwd: root, encoding: 'utf8', env: { ...process.env, PATH: `${bin}:/usr/bin:/bin`, TEST_BIN: bin, PI_VERSION: agentVersion, PI_WEB_UPSTREAM_URL: upstream, PI_WEB_INSTALL_ROOT: releases, PI_WEB_TEST_MAX_WORKERS: maxWorkers, PI_WEB_TEST_TIMEOUT_MS: testTimeout, TEST_LOG: log, TEST_FAILURE: runFailure, TEST_PREFIX: prefix, REAL_NODE: process.execPath, REAL_NPM: realpathSync(npm) },
  });
  return { source, upstream, origin, log, releases, prefix, run, baseCommit };
}

function prepareLocalMain(f) {
  git(f.source, 'fetch', f.upstream, 'main:main');
}

test('installs the cached pinned commit even when local main is newer', () => {
  const f = fixture();
  prepareLocalMain(f);
  git(f.source, 'remote', 'set-url', 'origin', '/nonexistent-origin');
  const patchHead = git(f.source, 'rev-parse', 'HEAD');
  const result = f.run();
  assert.equal(result.status, 0, result.stderr);
  const calls = readFileSync(f.log, 'utf8').trim().split('\n');
  assert.deepEqual(calls.slice(0, 3), ['npm ci --include=dev', 'npm test -- --maxWorkers=4 --testTimeout=30000', 'npm run build']);
  assert.equal(calls.length, 6);
  const installed = calls[3].slice('built '.length);
  assert.ok(installed.startsWith(f.releases));
  assert.equal(calls[4], `npm install --global --ignore-scripts --install-links=false --legacy-peer-deps ${installed}`);
  for (const [bin, entry] of [['pi-web', 'cli.js'], ['pi-web-server', 'server/index.js'], ['pi-web-sessiond', 'server/sessiond.js']]) {
    const command = join(f.prefix, 'bin', bin);
    assert.equal(realpathSync(command), join(installed, 'dist', entry));
    assert.equal(execFileSync(process.execPath, [command], { encoding: 'utf8' }).trim(), 'patched');
  }
  assert.match(readFileSync(join(installed, '.npmrc'), 'utf8'), /allow-scripts=node-pty,esbuild/);
  assert.equal(git(installed, 'rev-parse', 'HEAD'), f.baseCommit);
  const app = readFileSync(join(installed, 'app.txt'), 'utf8');
  assert.ok(app.includes('custom layout') && !app.includes('new upstream'));
  const upstreamHead = git(f.upstream, 'rev-parse', 'HEAD');
  assert.equal(git(f.source, 'rev-parse', 'main'), upstreamHead);
  assert.equal(git(f.origin, 'for-each-ref', '--format=%(refname)', 'refs/heads/main'), '');
  assert.equal(git(f.source, 'rev-parse', 'HEAD'), patchHead);
  assert.equal(git(f.source, 'status', '--porcelain'), '');
  assert.equal(git(f.source, 'rev-list', '--count', 'terminal-patch'), '1');
  assert.ok(!git(f.source, 'ls-tree', '--name-only', 'terminal-patch').includes('app.txt'));
  assert.equal(f.run().status, 0);
  const installs = readFileSync(f.log, 'utf8').split('\n').filter(line => line.startsWith('built '));
  assert.equal(new Set(installs).size, 2);
  assert.equal(realpathSync(join(f.prefix, 'bin', 'pi-web')), join(installs[1].slice('built '.length), 'dist/cli.js'));
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
  prepareLocalMain(f);
  const result = f.run();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Patch conflict/);
  assert.match(result.stderr, /retained directory/);
  assert.equal(readFileSync(f.log, 'utf8'), '');
  assert.equal(git(f.source, 'rev-parse', 'main'), git(f.upstream, 'rev-parse', 'HEAD'));
});

test('installation respects test worker and timeout overrides', () => {
  const f = fixture({ maxWorkers: '2', testTimeout: '60000' });
  prepareLocalMain(f);
  const result = f.run();
  assert.equal(result.status, 0, result.stderr);
  assert.ok(readFileSync(f.log, 'utf8').includes('npm test -- --maxWorkers=2 --testTimeout=60000'));
});

for (const failure of ['ci --include=dev', 'test -- --maxWorkers=4 --testTimeout=30000', 'run build']) {
  test(`does not install services after ${failure} fails`, () => {
    const f = fixture({ failure });
    prepareLocalMain(f);
    const result = f.run();
    assert.notEqual(result.status, 0);
    const calls = readFileSync(f.log, 'utf8');
    assert.equal(calls.trim().split('\n').at(-1), `npm ${failure}`);
    assert.ok(!calls.includes('node dist/cli.js install'));
    assert.ok(!calls.includes('npm install --global'));
  });
}

test('sync fetches the pinned commit without requiring main or origin', () => {
  const f = fixture();
  git(f.source, 'remote', 'remove', 'origin');
  const result = f.run('sync.sh');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(git(result.stdout.trim(), 'rev-parse', 'HEAD'), f.baseCommit);
  assert.equal(git(f.source, 'for-each-ref', '--format=%(refname)', 'refs/heads/main'), '');
  assert.equal(git(f.origin, 'for-each-ref', '--format=%(refname)'), '');
  // --local must also work when the baseline is only cached, with no local main.
  rmSync(f.upstream, { recursive: true });
  const local = f.run('sync.sh', ['--local']);
  assert.equal(local.status, 0, local.stderr);
  assert.equal(git(local.stdout.trim(), 'rev-parse', 'HEAD'), f.baseCommit);
});

test('sync preserves divergent local and origin main and a dirty main worktree', () => {
  const f = fixture();
  prepareLocalMain(f);
  const mainWorktree = join(f.source, '..', 'main checkout');
  git(f.source, 'worktree', 'add', mainWorktree, 'main');
  writeFileSync(join(mainWorktree, 'local.txt'), 'keep me');
  git(mainWorktree, 'add', 'local.txt');
  git(mainWorktree, 'commit', '-m', 'local work');
  git(mainWorktree, 'push', 'origin', 'main');
  const oldHead = git(mainWorktree, 'rev-parse', 'HEAD');
  writeFileSync(join(mainWorktree, 'app.txt'), 'unfinished work');
  git(mainWorktree, 'add', 'app.txt');
  writeFileSync(join(mainWorktree, 'notes.txt'), 'local notes');
  const oldStatus = git(mainWorktree, 'status', '--porcelain');
  const result = f.run('sync.sh');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(git(result.stdout.trim(), 'rev-parse', 'HEAD'), f.baseCommit);
  assert.equal(git(mainWorktree, 'rev-parse', 'HEAD'), oldHead);
  assert.equal(git(f.origin, 'rev-parse', 'main'), oldHead);
  assert.equal(git(mainWorktree, 'status', '--porcelain'), oldStatus);
  assert.equal(readFileSync(join(mainWorktree, 'app.txt'), 'utf8'), 'unfinished work');
  assert.equal(readFileSync(join(mainWorktree, 'notes.txt'), 'utf8'), 'local notes');
});

test('only changing base-commit advances the release to a newer upstream commit', () => {
  const f = fixture();
  const first = f.run('sync.sh');
  assert.equal(first.status, 0, first.stderr);
  const latest = git(f.upstream, 'rev-parse', 'HEAD');
  writeFileSync(join(f.source, 'patches/base-commit'), latest + '\n');
  const next = f.run('sync.sh');
  assert.equal(next.status, 0, next.stderr);
  assert.equal(git(next.stdout.trim(), 'rev-parse', 'HEAD'), latest);
  assert.equal(git(first.stdout.trim(), 'rev-parse', 'HEAD'), f.baseCommit);
  assert.match(readFileSync(join(next.stdout.trim(), 'app.txt'), 'utf8'), /new upstream/);
});

test('missing local pinned commit asks for synchronization without remote writes', () => {
  const f = fixture();
  const result = f.run();
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /Pinned commit .* is missing locally/);
  assert.equal(readFileSync(f.log, 'utf8'), '');
  assert.equal(git(f.origin, 'for-each-ref', '--format=%(refname)'), '');
});

for (const pin of [null, '', 'main', '60a29ac', 'a'.repeat(39), 'g'.repeat(40), 'a'.repeat(40) + '\nmain']) {
  test(`rejects missing or invalid base-commit: ${JSON.stringify(pin)}`, () => {
    const f = fixture();
    const file = join(f.source, 'patches/base-commit');
    if (pin === null) rmSync(file);
    else writeFileSync(file, pin);
    const result = f.run('sync.sh');
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /Missing patch baseline|must contain a full/);
    assert.equal(readFileSync(f.log, 'utf8'), '');
  });
}

test('unavailable pinned commit fails instead of falling back to main', () => {
  const f = fixture();
  prepareLocalMain(f);
  writeFileSync(join(f.source, 'patches/base-commit'), 'a'.repeat(40) + '\n');
  for (const args of [[], ['--local']]) {
    const result = f.run('sync.sh', args);
    assert.notEqual(result.status, 0);
    assert.equal(result.stdout, '');
  }
});

test('rejects a non-commit object as the patch baseline', () => {
  const f = fixture();
  prepareLocalMain(f);
  writeFileSync(join(f.source, 'patches/base-commit'), git(f.upstream, 'rev-parse', 'HEAD:app.txt') + '\n');
  const result = f.run('sync.sh', ['--local']);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /is not a commit/);
});

test('installation rejects former service options before doing any work', () => {
  const f = fixture();
  const result = f.run('install.sh', ['--port', '8510']);
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /service options are no longer accepted/);
  assert.equal(readFileSync(f.log, 'utf8'), '');
});


test('failed rebuild preserves the previously installed global command', () => {
  const f = fixture();
  prepareLocalMain(f);
  const installed = f.run();
  assert.equal(installed.status, 0, installed.stderr);
  const command = join(f.prefix, 'bin', 'pi-web');
  const oldTarget = realpathSync(command);
  const failed = f.run('install.sh', [], 'run build');
  assert.notEqual(failed.status, 0);
  assert.equal(realpathSync(command), oldTarget);
  assert.equal(execFileSync(process.execPath, [command], { encoding: 'utf8' }).trim(), 'patched');
});

function updateFixture({ running = false } = {}) {
  const root = mkdtempSync(join(tmpdir(), 'pi-web update test '));
  roots.push(root);
  const bin = join(root, 'bin');
  const log = join(root, 'calls.log');
  mkdirSync(bin);
  writeFileSync(log, '');
  mkdirSync(join(root, 'scripts'));
  copyFileSync(join(repo, 'scripts/install.sh'), join(root, 'scripts/install.sh'));
  copyFileSync(join(repo, 'scripts/pi-web-run-jmfederico.sh'), join(root, 'scripts/pi-web-run-jmfederico.sh'));
  const runDir = join(root, 'run');
  mkdirSync(runDir);
  if (running) writeFileSync(join(runDir, 'server.pid'), String(process.pid));
  writeFileSync(join(bin, 'npm'), `#!/bin/sh
printf 'npm %s\\n' "$*" >> "$TEST_LOG"
case "$*" in
  'ls -g --depth=0 --json '*) printf '{}'; exit 1 ;;
  'ls -g --depth=0 @agegr/pi-web') exit 1 ;;
esac
`);
  writeFileSync(join(bin, 'node'), `#!/bin/sh
if [ "$1" = --version ]; then echo v22.19.0; exit 0; fi
exec "$REAL_NODE" "$@"
`);
  writeFileSync(join(bin, 'pi'), '#!/bin/sh\necho 0.85.1\n');
  writeFileSync(join(bin, 'curl'), '#!/bin/sh\nexit 0\n', { mode: 0o755 });
  for (const name of ['pi-web-server', 'pi-web-sessiond']) {
    writeFileSync(join(bin, name), `#!/bin/sh\nprintf 'service start\\n' >> "$TEST_LOG"\nexit 1\n`, { mode: 0o755 });
  }
  for (const file of ['node', 'npm', 'pi']) chmodSync(join(bin, file), 0o755);
  const run = (...args) => spawnSync('bash', [join(root, 'scripts/pi-web-run-jmfederico.sh'), ...args], {
    encoding: 'utf8', env: { ...process.env, PATH: `${bin}:${process.env.PATH}`, TEST_LOG: log, REAL_NODE: process.execPath, PI_WEB_RUN_DIR: runDir },
  });
  return { run, log, runDir };
}

for (const running of [false, true]) {
  test(`update leaves services untouched: running=${running}`, () => {
    const f = updateFixture({ running });
    const result = f.run('update', '--pi-only');
    assert.equal(result.status, 0, result.stderr);
    const calls = readFileSync(f.log, 'utf8').trim().split('\n');
    assert.deepEqual(calls.filter(line => /^service (start|stop)$/.test(line)), []);
    assert.ok(calls.some(line => line.startsWith('npm install')));
    assert.equal(existsSync(join(f.runDir, 'server.pid')), running);
    if (running) assert.equal(readFileSync(join(f.runDir, 'server.pid'), 'utf8'), String(process.pid));
    assert.equal(existsSync(join(f.runDir, 'sessiond.pid')), false);
  });
}

for (const [option, pkg, excluded] of [
  ['--pi-only', '@earendil-works/pi-coding-agent', '@jmfederico/pi-web'],
]) {
  test(`update ${option} installs only the selected package even when not installed`, () => {
    const f = updateFixture();
    const result = f.run('update', option);
    assert.equal(result.status, 0, result.stderr);
    const installs = readFileSync(f.log, 'utf8').split('\n').filter(line => line.startsWith('npm install'));
    assert.equal(installs.length, 1);
    assert.ok(installs[0].includes(pkg + '@'));
    assert.ok(!installs[0].includes(excluded + '@'));
  });
}

test('update dry-run prints both updates without installing', () => {
  const f = updateFixture();
  const result = f.run('update', '--dry-run');
  assert.equal(result.status, 0, result.stderr);
  assert.match(result.stdout, /\[dry-run\] npm install -g --ignore-scripts @earendil-works\/pi-coding-agent@/);
  assert.match(result.stdout, /\[dry-run\] sh .*scripts\/sync.sh/);
  assert.match(result.stdout, /\[dry-run\] npm ci --include=dev/);
  assert.ok(!readFileSync(f.log, 'utf8').includes('npm install'));
});

test('install rejects update and update options without installing', () => {
  const f = fixture();
  for (const args of [['update'], ['update', '--web-only'], ['--pi-only'], ['install', '--dry-run']]) {
    assert.equal(f.run('install.sh', args).status, 2);
  }
  assert.equal(readFileSync(f.log, 'utf8'), '');
  assert.doesNotMatch(f.run('install.sh', ['--help']).stdout, /--pi-only|--web-only|--dry-run/);
});

test('unified entry rejects invalid arguments before executing npm', () => {
  const f = updateFixture();
  for (const args of [['invalid'], ['install', '--dry-run'], ['update', '--pi-only', '--web-only'], ['update', '--invalid'], ['update', '--restart'], ['update', '--no-restart']]) {
    assert.notEqual(f.run(...args).status, 0);
  }
  assert.equal(readFileSync(f.log, 'utf8'), '');
  for (const args of [['--help'], ['install', '--help'], ['update', '--help']]) {
    const result = f.run(...args);
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /pi-web-run-jmfederico.sh update/);
  }
});


for (const options of [[], ['--web-only']]) {
test(`update ${options.join(' ')} synchronizes upstream and installs patched global commands`, () => {
  const f = fixture();
  const result = f.run('pi-web-run-jmfederico.sh', ['update', ...options]);
  assert.equal(result.status, 0, result.stderr);
  assert.equal(git(f.origin, 'for-each-ref', '--format=%(refname)'), '');
  const calls = readFileSync(f.log, 'utf8');
  assert.equal(calls.includes('npm install -g --ignore-scripts @earendil-works/pi-coding-agent@'), options.length === 0);
  const installed = calls.split('\n').find(line => line.startsWith('built ')).slice(6);
  assert.equal(git(installed, 'rev-parse', 'HEAD'), git(f.upstream, 'rev-parse', 'main'));
  assert.equal(readFileSync(join(f.source, 'patches/base-commit'), 'utf8').trim(), git(f.upstream, 'rev-parse', 'main'));
  const app = readFileSync(join(installed, 'app.txt'), 'utf8');
  assert.ok(app.includes('custom layout') && app.includes('new upstream'));
  assert.equal(realpathSync(join(f.prefix, 'bin', 'pi-web')), join(installed, 'dist/cli.js'));
});

}

for (const agentVersion of ['latest', '0.85.1']) {
  test(`install bootstraps missing Agent at ${agentVersion} only once`, () => {
    const f = fixture({ agent: false, agentVersion });
    prepareLocalMain(f);
    for (let attempt = 0; attempt < 2; attempt++) {
      const result = f.run();
      assert.equal(result.status, 0, result.stderr);
    }
    const calls = readFileSync(f.log, 'utf8').split('\n');
    const agentInstall = `npm install -g --ignore-scripts @earendil-works/pi-coding-agent@${agentVersion}`;
    assert.equal(calls.filter(line => line === agentInstall).length, 1);
    assert.ok(calls.indexOf(agentInstall) > calls.indexOf('npm run build'));
    assert.ok(calls.indexOf(agentInstall) < calls.findIndex(line => line.startsWith('npm install --global')));
  });
}

test('Agent install failure stops before replacing pi-web', () => {
  const failure = 'install -g --ignore-scripts @earendil-works/pi-coding-agent@latest';
  const f = fixture({ agent: false, failure });
  prepareLocalMain(f);
  const result = f.run();
  assert.notEqual(result.status, 0);
  const calls = readFileSync(f.log, 'utf8');
  assert.ok(calls.includes(`npm ${failure}`));
  assert.ok(!calls.includes('npm install --global'));
});

test('update --web-only does not bootstrap a missing Agent', () => {
  const f = fixture({ agent: false });
  const result = f.run('pi-web-run-jmfederico.sh', ['update', '--web-only']);
  assert.equal(result.status, 0, result.stderr);
  assert.ok(!readFileSync(f.log, 'utf8').includes('npm install -g --ignore-scripts @earendil-works/pi-coding-agent@'));
});

test('update uses latest Agent even when install bootstrap version is pinned', () => {
  const f = fixture({ agentVersion: '0.85.1' });
  const result = f.run('pi-web-run-jmfederico.sh', ['update', '--pi-only']);
  assert.equal(result.status, 0, result.stderr);
  assert.match(readFileSync(f.log, 'utf8'), /npm install -g --ignore-scripts @earendil-works\/pi-coding-agent@latest/);
  assert.equal(readFileSync(join(f.source, 'patches/base-commit'), 'utf8').trim(), f.baseCommit);
});

test('update dry-run and failed upstream fetch preserve the baseline', () => {
  const f = fixture();
  const before = readFileSync(join(f.source, 'patches/base-commit'), 'utf8');
  assert.equal(f.run('pi-web-run-jmfederico.sh', ['update', '--web-only', '--dry-run']).status, 0);
  assert.equal(readFileSync(join(f.source, 'patches/base-commit'), 'utf8'), before);
  git(f.upstream, 'branch', '-m', 'unavailable-main');
  assert.notEqual(f.run('pi-web-run-jmfederico.sh', ['update', '--web-only']).status, 0);
  assert.equal(readFileSync(join(f.source, 'patches/base-commit'), 'utf8'), before);
  assert.ok(!readFileSync(f.log, 'utf8').includes('built '));
});
