import { spawnSync } from 'node:child_process';
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync, existsSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { test } from 'node:test';
import assert from 'node:assert/strict';

function fixture() {
  const root = mkdtempSync(join(tmpdir(), 'pi-web instances '));
  const bin = join(root, 'bin');
  mkdirSync(bin);
  mkdirSync(join(root, 'scripts'));
  copyFileSync('scripts/pi-web-run-jmfederico.sh', join(root, 'scripts/run.sh'));
  const script = (name, body) => writeFileSync(join(bin, name), `#!/bin/bash\n${body}\n`, { mode: 0o755 });
  for (const name of ['pi-web-sessiond', 'pi-web-server']) {
    script(name, 'printf "%s\\n" "$PI_WEB_DATA_DIR" "$PI_WEB_SESSIOND_SOCKET" "$PI_WEB_RUN_DIR"\nexec /bin/sleep 120');
  }
  script('curl', '/bin/sleep 0.05; exit 0');
  script('ss', 'exit 0');
  const env = { ...process.env, PATH: `${bin}:${process.env.PATH}` };
  for (const key of Object.keys(env)) if (key.startsWith('PI_WEB_')) delete env[key];
  const run = (action, port, overrides = {}) => spawnSync('bash', [join(root, 'scripts/run.sh'), action, '--port', port], {
    env: { ...env, ...overrides }, encoding: 'utf8', timeout: 10000,
  });
  const pids = [];
  return { root, run, pids, cleanup() {
    for (const pid of pids) { try { process.kill(pid, 'SIGKILL'); } catch {} }
    rmSync(root, { recursive: true, force: true });
  } };
}

test('two ports have independent state, socket and processes; stopping one preserves the other', () => {
  const f = fixture();
  try {
    for (const port of ['8424', '8425']) {
      const result = f.run('start', port);
      assert.equal(result.status, 0, result.stderr);
      const dir = join(f.root, 'data/pi-web', port);
      for (const service of ['sessiond', 'server']) {
        f.pids.push(Number(readFileSync(join(dir, `${service}.pid`), 'utf8')));
        assert.deepEqual(readFileSync(join(dir, `${service}.log`), 'utf8').trim().split('\n'), [join(dir, 'state'), join(dir, 'state/sessiond.sock'), dir]);
      }
    }
    assert.equal(new Set(f.pids).size, 4);
    assert.equal(f.run('stop', '8424').status, 0);
    assert.equal(existsSync(join(f.root, 'data/pi-web/8424/server.pid')), false);
    for (const pid of f.pids.slice(2)) process.kill(pid, 0);
    assert.equal(f.run('status', '8425').status, 0);
  } finally { f.cleanup(); }
});

test('explicit directory and socket overrides reach both processes', () => {
  const f = fixture();
  const overrides = { PI_WEB_DATA_DIR: join(f.root, 'custom-state'), PI_WEB_RUN_DIR: join(f.root, 'custom-run'), PI_WEB_SESSIOND_SOCKET: join(f.root, 'custom.sock') };
  try {
    const result = f.run('start', '8424', overrides);
    assert.equal(result.status, 0, result.stderr);
    for (const service of ['sessiond', 'server']) {
      f.pids.push(Number(readFileSync(join(overrides.PI_WEB_RUN_DIR, `${service}.pid`), 'utf8')));
      assert.deepEqual(readFileSync(join(overrides.PI_WEB_RUN_DIR, `${service}.log`), 'utf8').trim().split('\n'), [overrides.PI_WEB_DATA_DIR, overrides.PI_WEB_SESSIOND_SOCKET, overrides.PI_WEB_RUN_DIR]);
    }
  } finally { f.cleanup(); }
});

test('port paths are validated and leading zeros select the same instance', () => {
  const f = fixture();
  try {
    for (const port of ['../bad', '0', '65536', 'nope']) assert.equal(f.run('start', port).status, 2);
    const r = f.run('start', '08424');
    assert.equal(r.status, 0, r.stderr);
    for (const service of ['sessiond', 'server']) f.pids.push(Number(readFileSync(join(f.root, 'data/pi-web/8424', `${service}.pid`), 'utf8')));
    assert.equal(existsSync(join(f.root, 'data/pi-web/08424')), false);
  } finally { f.cleanup(); }
});
