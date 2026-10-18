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
  mkdirSync(join(root, 'data'));
  mkdirSync(join(root, 'scripts'));
  copyFileSync('scripts/pi-web-run-jmfederico.sh', join(root, 'scripts/run.sh'));
  const script = (name, body) => writeFileSync(join(bin, name), `#!/bin/bash\n${body}\n`, { mode: 0o755 });
  for (const name of ['pi-web-sessiond', 'pi-web-server']) {
    writeFileSync(join(bin, name), `#!${process.execPath}
console.log([process.env.PI_WEB_DATA_DIR, process.env.PI_WEB_SESSIOND_SOCKET, process.env.PI_WEB_RUN_DIR].join('\\n'));
setInterval(() => {}, 1000);
`, { mode: 0o755 });
  }
  script('curl', '/bin/sleep 0.05; printf 200; exit 0');
  script('ss', 'exit 0');
  const env = { ...process.env, PATH: `${bin}:${process.env.PATH}` };
  for (const key of Object.keys(env)) if (key.startsWith('PI_WEB_')) delete env[key];
  const run = (action, port, overrides = {}) => {
    const settings = Object.entries(overrides).filter(([key]) => key.startsWith('PI_WEB_'));
    if (port !== undefined) settings.push(['PI_WEB_PORT', port]);
    if (settings.length) writeFileSync(join(root, 'data/pi-web.conf'), settings.map(([key, value]) => `${key}='${value.replaceAll("'", "'\\''")}'`).join('\n') + '\n');
    return spawnSync('bash', [join(root, 'scripts/run.sh'), action], {
      env: { ...env, ...overrides }, encoding: 'utf8', timeout: 10000,
    });
  };
  const pids = [];
  return { root, run, pids, cleanup() {
    for (const pid of pids) { try { process.kill(pid, 'SIGKILL'); } catch {} }
    rmSync(root, { recursive: true, force: true });
  } };
}

test('unsupported update options and service arguments are rejected', () => {
  const f = fixture();
  try {
    copyFileSync('scripts/install.sh', join(f.root, 'scripts/install.sh'));
    for (const args of [['update', '--restart'], ['update', '--no-restart'], ['start', '--port', '8425'], ['stop', '--port=8425'], ['status', '8425']]) {
      const result = spawnSync('bash', [join(f.root, 'scripts/run.sh'), ...args], { encoding: 'utf8' });
      assert.equal(result.status, 2, result.stderr);
      assert.equal(existsSync(join(f.root, 'data/pi-web/8024/server.pid')), false);
    }
  } finally { f.cleanup(); }
});

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

test('stop reads the same config as start', () => {
  const f = fixture();
  try {
    assert.equal(f.run('start', '8425').status, 0);
    const dir = join(f.root, 'data/pi-web/8425');
    for (const service of ['sessiond', 'server']) f.pids.push(Number(readFileSync(join(dir, `${service}.pid`), 'utf8')));
    mkdirSync(join(f.root, 'data/pi-web/notes'));
    writeFileSync(join(f.root, 'data/pi-web/legacy.log'), '');
    const result = f.run('stop');
    assert.equal(result.status, 0, result.stderr);
    assert.doesNotMatch(result.stdout, /唯一实例/);
    for (const service of ['sessiond', 'server']) assert.equal(existsSync(join(dir, `${service}.pid`)), false);
  } finally { f.cleanup(); }
});

for (const password of ['', 'test password $literal']) {
  test(`server receives configured host, port and ${password ? 'nonempty' : 'empty'} password`, () => {
    const f = fixture();
    try {
      const realNohup = spawnSync('sh', ['-c', 'command -v nohup'], { encoding: 'utf8' }).stdout.trim();
      assert.ok(realNohup);
      writeFileSync(join(f.root, 'bin/nohup'), `#!/bin/bash
printf '%s\\n' "$@" >> "$PI_WEB_RUN_DIR/launcher-args.log"
exec "$TEST_REAL_NOHUP" "$@"
`, { mode: 0o755 });
      writeFileSync(join(f.root, 'bin/pi-web-server'), `#!${process.execPath}
console.log(JSON.stringify([process.env.PI_WEB_HOST, process.env.PI_WEB_PORT, process.env.PI_WEB_PASSWORD]));
setInterval(() => {}, 1000);
`, { mode: 0o755 });
      const result = f.run('start', '8425', { PI_WEB_HOST: '127.0.0.2', PI_WEB_PASSWORD: password, TEST_REAL_NOHUP: realNohup });
      const dir = join(f.root, 'data/pi-web/8425');
      for (const service of ['server', 'sessiond']) {
        const pidfile = join(dir, `${service}.pid`);
        if (existsSync(pidfile)) f.pids.push(Number(readFileSync(pidfile, 'utf8')));
      }
      assert.equal(result.status, 0, result.stderr);
      assert.deepEqual(JSON.parse(readFileSync(join(dir, 'server.log'), 'utf8')), ['127.0.0.2', '8425', password]);
      const launcherArgs = readFileSync(join(dir, 'launcher-args.log'), 'utf8');
      assert.doesNotMatch(launcherArgs, /PI_WEB_PASSWORD=/);
      if (password) assert.equal(launcherArgs.includes(password), false);
    } finally { f.cleanup(); }
  });
}

for (const [name, ports, port, overrides, target] of [
  ['multiple instances', ['8024', '8425'], undefined, {}, '8024'],
  ['configured port', ['8425'], '8024', {}, '8024'],
  ['unconfigured sole instance', ['8425'], undefined, {}, '8024'],
  ['run directory override', ['8425'], undefined, { PI_WEB_RUN_DIR: 'custom' }, 'custom'],
  ['no instances', [], undefined, {}, '8024'],
]) {
  test(`stop preserves target selection with ${name}`, () => {
    const f = fixture();
    try {
      for (const instance of ports) {
        const dir = join(f.root, 'data/pi-web', instance);
        mkdirSync(dir, { recursive: true });
        writeFileSync(join(dir, 'server.pid'), '999999999');
      }
      const env = { ...overrides };
      if (env.PI_WEB_RUN_DIR) {
        env.PI_WEB_RUN_DIR = join(f.root, 'custom');
        mkdirSync(env.PI_WEB_RUN_DIR);
        writeFileSync(join(env.PI_WEB_RUN_DIR, 'server.pid'), '999999999');
      }
      const result = f.run('stop', port, env);
      assert.equal(result.status, 0, result.stderr);
      assert.doesNotMatch(result.stdout, /唯一实例/);
      for (const instance of ports) assert.equal(existsSync(join(f.root, 'data/pi-web', instance, 'server.pid')), instance !== target);
      if (env.PI_WEB_RUN_DIR) assert.equal(existsSync(join(env.PI_WEB_RUN_DIR, 'server.pid')), false);
    } finally { f.cleanup(); }
  });
}

for (const missing of [true, false]) {
  test(`stop recovers live processes with ${missing ? 'missing' : 'stale'} PID files`, () => {
    const f = fixture();
    try {
      assert.equal(f.run('start', '8425').status, 0);
      const dir = join(f.root, 'data/pi-web/8425');
      for (const service of ['server', 'sessiond']) {
        const pidfile = join(dir, `${service}.pid`);
        f.pids.push(Number(readFileSync(pidfile, 'utf8')));
        if (missing) rmSync(pidfile);
        else writeFileSync(pidfile, String(process.pid));
      }
      const result = f.run('stop', '8425');
      assert.equal(result.status, 0, result.stderr);
      assert.match(result.stdout, /遗留进程/);
      for (const pid of f.pids) {
        const stat = spawnSync('ps', ['-o', 'stat=', '-p', String(pid)], { encoding: 'utf8' });
        assert.ok(stat.status !== 0 || stat.stdout.trim().startsWith('Z'), `PID ${pid} is still alive`);
      }
      for (const service of ['server', 'sessiond']) assert.equal(existsSync(join(dir, `${service}.pid`)), false);
      assert.equal(f.run('start', '8425').status, 0);
      for (const service of ['server', 'sessiond']) f.pids.push(Number(readFileSync(join(dir, `${service}.pid`), 'utf8')));
    } finally { f.cleanup(); }
  });
}

test('stop escalates to KILL when a service ignores TERM', () => {
  const f = fixture();
  try {
    writeFileSync(join(f.root, 'bin/pi-web-server'), `#!${process.execPath}
process.on('SIGTERM', () => console.log('TERM ignored'));
console.log('ready');
setInterval(() => {}, 1000);
`, { mode: 0o755 });
    const started = f.run('start', '8425');
    const dir = join(f.root, 'data/pi-web/8425');
    for (const service of ['server', 'sessiond']) {
      const pidfile = join(dir, `${service}.pid`);
      if (existsSync(pidfile)) f.pids.push(Number(readFileSync(pidfile, 'utf8')));
    }
    assert.equal(started.status, 0, started.stderr);
    assert.match(readFileSync(join(dir, 'server.log'), 'utf8'), /ready/);
    const stopped = f.run('stop');
    assert.equal(stopped.status, 0, stopped.stderr);
    assert.match(readFileSync(join(dir, 'server.log'), 'utf8'), /TERM ignored/);
    for (const service of ['server', 'sessiond']) assert.equal(existsSync(join(dir, `${service}.pid`)), false);
    assert.equal(f.run('status').status, 1);
  } finally { f.cleanup(); }
});

for (const action of ['stop', 'restart']) {
test(`${action} failure preserves PID files and returns an error`, () => {
  const f = fixture();
  try {
    assert.equal(f.run('start', '8425').status, 0);
    const dir = join(f.root, 'data/pi-web/8425');
    for (const service of ['server', 'sessiond']) f.pids.push(Number(readFileSync(join(dir, `${service}.pid`), 'utf8')));
    const shellEnv = join(f.root, 'deny-signals.sh');
    writeFileSync(shellEnv, 'kill() { if [[ "$1" == -0 ]]; then builtin kill "$@"; else return 1; fi; }\n');
    const result = f.run(action, '8425', { BASH_ENV: shellEnv });
    assert.doesNotMatch(result.stdout, /启动 pi-web/);
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /无法停止.*保留 PID 文件/);
    for (const service of ['server', 'sessiond']) assert.equal(existsSync(join(dir, `${service}.pid`)), true);
    for (const pid of f.pids) process.kill(pid, 0);
  } finally { f.cleanup(); }
});

}

test('a busy port does not start sessiond or write PID files', () => {
  const f = fixture();
  try {
    writeFileSync(join(f.root, 'bin/ss'), '#!/bin/sh\necho "LISTEN 0 511 0.0.0.0:8425 0.0.0.0:*"\n', { mode: 0o755 });
    const result = f.run('start', '8425');
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /端口 8425 已被占用/);
    for (const service of ['server', 'sessiond']) assert.equal(existsSync(join(f.root, 'data/pi-web/8425', `${service}.pid`)), false);
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

// A background service must survive cleanup of its launching process group.
test('Linux services run in separate sessions with detached stdin', { skip: process.platform !== 'linux' }, () => {
  const f = fixture();
  try {
    const result = f.run('start', '8424');
    assert.equal(result.status, 0, result.stderr);
    for (const service of ['sessiond', 'server']) {
      const pid = Number(readFileSync(join(f.root, 'data/pi-web/8424', `${service}.pid`), 'utf8'));
      f.pids.push(pid);
      const session = spawnSync('ps', ['-o', 'sid=', '-p', String(pid)], { encoding: 'utf8' });
      assert.equal(Number(session.stdout.trim()), pid);
      const stdin = spawnSync('readlink', [`/proc/${pid}/fd/0`], { encoding: 'utf8' });
      assert.equal(stdin.stdout.trim(), '/dev/null');
    }
  } finally { f.cleanup(); }
});

test('service environment cannot override config or defaults', () => {
  const f = fixture();
  try {
    const env = { ...process.env, PI_WEB_PORT: '9999', PI_WEB_HOST: 'bad-host', PI_WEB_RUN_DIR: '/bad-path' };
    const run = () => spawnSync('bash', [join(f.root, 'scripts/run.sh'), 'status'], { env, encoding: 'utf8' });
    // Start owned processes to expose the selected host and port in status output.
    for (const port of ['8024', '8425']) {
      const dir = join(f.root, 'data/pi-web', port);
      assert.equal(f.run('start', port).status, 0);
      for (const service of ['server', 'sessiond']) f.pids.push(Number(readFileSync(join(dir, `${service}.pid`), 'utf8')));
    }
    writeFileSync(join(f.root, 'data/pi-web.conf'), 'PI_WEB_PORT=8425\nPI_WEB_HOST=127.0.0.1\n');
    assert.match(run().stdout, /http:\/\/127\.0\.0\.1:8425/);
    rmSync(join(f.root, 'data/pi-web.conf'));
    assert.match(run().stdout, /http:\/\/0\.0\.0\.0:8024/);
  } finally { f.cleanup(); }
});

test('invalid configured port is rejected before starting services', () => {
  const f = fixture();
  try {
    writeFileSync(join(f.root, 'data/pi-web.conf'), 'PI_WEB_PORT=65536\n');
    assert.equal(f.run('start').status, 2);
    assert.equal(existsSync(join(f.root, 'data/pi-web')), false);
  } finally { f.cleanup(); }
});

for (const running of [false, true]) {
  test(`restart stops before starting with configured port (running=${running})`, () => {
    const f = fixture();
    try {
      const dir = join(f.root, 'data/pi-web/8425');
      if (running) {
        assert.equal(f.run('start', '8425').status, 0);
        for (const service of ['sessiond', 'server']) f.pids.push(Number(readFileSync(join(dir, `${service}.pid`), 'utf8')));
      }
      const result = f.run('restart', '8425');
      assert.equal(result.status, 0, result.stderr);
      const previous = [...f.pids];
      for (const service of ['sessiond', 'server']) {
        const pid = Number(readFileSync(join(dir, `${service}.pid`), 'utf8'));
        f.pids.push(pid);
        assert.ok(!previous.includes(pid));
        process.kill(pid, 0);
      }
      if (running) {
        assert.ok(result.stdout.lastIndexOf('已停止') < result.stdout.indexOf('启动 pi-web'));
        for (const pid of previous) {
          const stat = spawnSync('ps', ['-o', 'stat=', '-p', String(pid)], { encoding: 'utf8' });
          assert.ok(stat.status !== 0 || stat.stdout.trim().startsWith('Z'));
        }
      }
      assert.match(f.run('status').stdout, /:8425/);
    } finally { f.cleanup(); }
  });
}

for (const failure of ['server', 'sessiond', 'http']) {
  test(`start reports failure when ${failure} is unavailable`, () => {
    const f = fixture();
    try {
      writeFileSync(join(f.root, 'bin/sleep'), '#!/bin/sh\n/bin/sleep 0.02\n', { mode: 0o755 });
      if (failure === 'http') writeFileSync(join(f.root, 'bin/curl'), '#!/bin/sh\nprintf 503\n', { mode: 0o755 });
      else writeFileSync(join(f.root, `bin/pi-web-${failure}`), '#!/bin/sh\nexit 7\n', { mode: 0o755 });
      const result = f.run('start', '8425');
      for (const service of ['server', 'sessiond']) {
        const file = join(f.root, 'data/pi-web/8425', `${service}.pid`);
        if (existsSync(file)) f.pids.push(Number(readFileSync(file, 'utf8')));
      }
      assert.notEqual(result.status, 0);
      assert.match(result.stderr, /服务未就绪/);
    } finally { f.cleanup(); }
  });
}

test('start replaces stale PID files without accepting or killing unrelated processes', () => {
  const f = fixture();
  try {
    const dir = join(f.root, 'data/pi-web/8425');
    mkdirSync(dir, { recursive: true });
    for (const service of ['server', 'sessiond']) writeFileSync(join(dir, `${service}.pid`), String(process.pid));
    const result = f.run('start', '8425');
    for (const service of ['server', 'sessiond']) f.pids.push(Number(readFileSync(join(dir, `${service}.pid`), 'utf8')));
    assert.equal(result.status, 0, result.stderr);
    for (const pid of f.pids) assert.notEqual(pid, process.pid);
    process.kill(process.pid, 0);
    assert.match(result.stdout, /启动 pi-web-server/);
    assert.match(result.stdout, /启动 pi-web-sessiond/);
  } finally { f.cleanup(); }
});

for (const missing of [true, false]) {
  test(`start recovers running services with ${missing ? 'missing' : 'stale'} PID files`, () => {
    const f = fixture();
    try {
      assert.equal(f.run('start', '8425').status, 0);
      const dir = join(f.root, 'data/pi-web/8425');
      for (const service of ['server', 'sessiond']) {
        const file = join(dir, `${service}.pid`);
        f.pids.push(Number(readFileSync(file, 'utf8')));
        if (missing) rmSync(file);
        else writeFileSync(file, String(process.pid));
      }
      // The existing server still owns its port even though its PID file was lost.
      writeFileSync(join(f.root, 'bin/ss'), '#!/bin/sh\necho "LISTEN 0 511 0.0.0.0:8425 0.0.0.0:*"\n', { mode: 0o755 });
      const result = f.run('start', '8425');
      assert.equal(result.status, 0, result.stderr);
      assert.doesNotMatch(result.stdout, /启动 pi-web/);
      for (const [index, service] of ['server', 'sessiond'].entries()) {
        assert.equal(Number(readFileSync(join(dir, `${service}.pid`), 'utf8')), f.pids[index]);
        process.kill(f.pids[index], 0);
      }
    } finally { f.cleanup(); }
  });
}

test('multiple service actions are rejected without stopping running services', () => {
  const f = fixture();
  try {
    assert.equal(f.run('start', '8425').status, 0);
    const dir = join(f.root, 'data/pi-web/8425');
    for (const service of ['server', 'sessiond']) f.pids.push(Number(readFileSync(join(dir, `${service}.pid`), 'utf8')));
    for (const args of [['status', 'stop'], ['start', 'restart'], ['update', 'stop']]) {
      const result = spawnSync('bash', [join(f.root, 'scripts/run.sh'), ...args], { encoding: 'utf8' });
      assert.equal(result.status, 2, result.stderr);
      for (const pid of f.pids) process.kill(pid, 0);
    }
  } finally { f.cleanup(); }
});

for (const [host, target] of [['127.0.0.2', '127.0.0.2'], ['0.0.0.0', '127.0.0.1'], ['::', '[::1]'], ['::1', '[::1]'], ['[::1]', '[::1]']]) {
  test(`startup and status probe the configured host ${host}`, () => {
    const f = fixture();
    try {
      writeFileSync(join(f.root, 'bin/curl'), `#!/bin/bash\n[[ "\${@: -1}" == 'http://${target}:8425/' ]] || exit 1\nprintf 200\n`, { mode: 0o755 });
      const result = f.run('start', '8425', { PI_WEB_HOST: host });
      for (const service of ['server', 'sessiond']) {
        const file = join(f.root, 'data/pi-web/8425', `${service}.pid`);
        if (existsSync(file)) f.pids.push(Number(readFileSync(file, 'utf8')));
      }
      assert.equal(result.status, 0, result.stderr);
      const status = f.run('status');
      assert.equal(status.status, 0);
      assert.doesNotMatch(status.stdout, /探测失败/);
    } finally { f.cleanup(); }
  });
}
