const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function fixture(t, withOfficialConfig = true) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-service-'));
  t.after(() => {
    // Stop only the native fixture whose executable belongs to this temporary directory.
    try {
      const pid = Number(fs.readFileSync(path.join(root, 'data/nginx/nginx.pid')));
      if (fs.readlinkSync(`/proc/${pid}/exe`) === path.join(root, 'runtime/nginx/sbin/nginx')) process.kill(pid, 'SIGQUIT');
    } catch {}
    fs.rmSync(root, { recursive: true, force: true });
  });
  const data = path.join(root, 'data');
  fs.mkdirSync(path.join(data, '.paseo'), { recursive: true });
  fs.writeFileSync(path.join(data, 'paseo.conf'), '{"ip":"127.0.0.1","port":31415}');
  const tls = path.join(data, 'tls', '127.0.0.1');
  fs.mkdirSync(tls, { recursive: true });
  // Nginx is mocked here; certificate format validation belongs to nginx -t.
  for (const file of ['fullchain.pem', 'privkey.pem']) fs.writeFileSync(path.join(tls, file), 'test fixture');
  if (withOfficialConfig) fs.copyFileSync(path.join(__dirname, 'config.json.example'), path.join(data, '.paseo/config.json'));
  for (const file of ['paseo_nginx.py', 'paseo_web_run.sh', 'node-runtime.sh', 'paseo-config.cjs', 'nginx.conf.template', 'config.json.example']) {
    fs.copyFileSync(path.join(__dirname, file), path.join(root, file));
  }
  const mock = `#!${process.execPath}
const fs = require('node:fs'), path = require('node:path');
const root = process.env.PASEO_TEST_ROOT, args = process.argv.slice(2);
const command = path.basename(process.argv[1]);
fs.appendFileSync(root+'/calls', JSON.stringify({command,args})+'\\n');
const stateFile = root+'/state.json', pidFile = root+'/data/nginx/nginx.pid';
if (command === 'paseo') {
  const home = args[args.indexOf('--home')+1];
  if (home !== root+'/data/.paseo') process.exit(99);
  try { if (fs.readlinkSync('/proc/self/fd/9') === root+'/data/service.lock') process.exit(98); } catch {}
  if (args[1] === 'status') console.log(fs.existsSync(stateFile) ? fs.readFileSync(stateFile,'utf8') : '{"localDaemon":"stopped"}');
  if (args[1] === 'start') fs.writeFileSync(stateFile, JSON.stringify({localDaemon:'running', listen:JSON.parse(fs.readFileSync(home+'/config.json')).daemon.listen}));
  if (args[1] === 'stop') fs.rmSync(stateFile, {force:true});

}
`;
  for (const file of ['runtime/bin/paseo', 'bin/curl']) {
    const target = path.join(root, file);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, mock, { mode: 0o755 });
  }
  const nginx = path.join(root, 'runtime/nginx/sbin/nginx');
  fs.mkdirSync(path.dirname(nginx), { recursive: true });
  const compile = spawnSync('cc', [path.join(__dirname, 'test-nginx-fixture.c'), '-o', nginx], { encoding: 'utf8' });
  assert.equal(compile.status, 0, compile.stderr);
  return {
    root, data,
    run(...args) {
      return spawnSync('bash', [path.join(root, 'paseo_web_run.sh'), ...args], {
        encoding: 'utf8', timeout: 5000,
        env: { ...process.env, PASEO_TEST_ROOT: root, PATH: `${root}/bin:${process.env.PATH}` },
      });
    },
    calls() { return fs.readFileSync(path.join(root, 'calls'), 'utf8').trim().split('\n').map(JSON.parse); },
  };
}

test('HTTPS start rejects missing or empty TLS files before calling services', t => {
  for (const file of ['fullchain.pem', 'privkey.pem']) {
    for (const missing of [true, false]) {
      const service = fixture(t);
      const target = path.join(service.data, 'tls', '127.0.0.1', file);
      if (missing) fs.unlinkSync(target);
      else fs.writeFileSync(target, '');
      const result = service.run('start');
      assert.equal(result.status, 1, result.stderr);
      assert.match(result.stderr, /启动已取消/);
      assert.ok(result.stderr.includes(path.join(path.dirname(service.root), 'ds-harness/data/tls/127.0.0.1/')));
      assert.ok(result.stderr.includes(path.join(service.data, 'tls', '127.0.0.1')));
      assert.ok(!fs.existsSync(path.join(service.root, 'calls')));
      assert.ok(!fs.existsSync(path.join(service.data, 'nginx.conf')));
    }
  }
});

test('first start initializes missing official configuration in both modes', t => {
  for (const mode of ['--proxy', '--no-proxy']) {
    const service = fixture(t, false);
    const result = service.run('start', mode);
    assert.equal(result.status, 0, result.stderr);
    const config = JSON.parse(fs.readFileSync(path.join(service.data, '.paseo/config.json')));
    assert.equal(config.daemon.listen, mode === '--proxy' ? '127.0.0.1:25226' : '0.0.0.0:31415');
    assert.ok(config.daemon.hostnames.includes('127.0.0.1'));
    assert.equal(config.features.webUi.enabled, true);
    assert.equal(config.daemon.relay.enabled, false);
  }
});

test('HTTPS lifecycle uses the official home, local certificates and proxy reload', t => {
  const service = fixture(t);
  for (const args of [['start'], ['status'], ['set-password'], ['reload-proxy'], ['stop']]) {
    const result = service.run(...args);
    assert.equal(result.status, 0, result.stderr);
  }
  const calls = service.calls();
  const curl = calls.find(call => call.command === 'curl');
  assert.ok(curl.args.includes(`${service.data}/tls/127.0.0.1/fullchain.pem`));
  assert.ok(curl.args.includes('https://127.0.0.1:31415/api/health'));
  assert.equal(fs.readFileSync(path.join(service.root, 'signals'), 'utf8'), 'reload\nquit\n');
  assert.ok(!calls.some(call => call.command === 'nginx' && call.args.includes('-s')));
  for (const call of calls.filter(call => call.command === 'nginx')) {
    assert.equal(call.args[call.args.indexOf('-p') + 1], `${service.data}/nginx/`);
    assert.equal(call.args[call.args.indexOf('-e') + 1], `${service.root}/log/nginx/error.log`);
  }
  const config = JSON.parse(fs.readFileSync(path.join(service.data, '.paseo/config.json')));
  assert.equal(path.resolve(service.data, '.paseo', config.log.file.path), `${service.root}/log/daemon.log`);
  assert.ok(!fs.existsSync(path.join(service.root, 'state.json')));
});

test('HTTP mode skips Nginx and uses the configured direct listener', t => {
  const service = fixture(t);
  for (const file of ['fullchain.pem', 'privkey.pem']) {
    fs.unlinkSync(path.join(service.data, 'tls', '127.0.0.1', file));
  }
  const result = service.run('start', '--no-proxy');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(JSON.parse(fs.readFileSync(path.join(service.root, 'state.json'))).listen, '0.0.0.0:31415');
  assert.ok(!service.calls().some(call => call.command === 'nginx'));
  const curl = service.calls().find(call => call.command === 'curl');
  assert.ok(curl.args.includes('http://127.0.0.1:31415/api/health'));
  assert.ok(!curl.args.includes('--cacert'));
});

test('mode mismatch cannot start or stop a running backend', t => {
  const service = fixture(t);
  fs.writeFileSync(path.join(service.root, 'state.json'), '{"localDaemon":"running","listen":"0.0.0.0:31415"}');
  const result = service.run('start');
  assert.notEqual(result.status, 0);
  assert.match(result.stderr, /先 stop/);
  assert.ok(!service.calls().some(call => call.command === 'paseo' && ['start', 'stop'].includes(call.args[1])));
});


test('unrelated live PID is rejected without signaling or starting services', t => {
  const service = fixture(t);
  fs.mkdirSync(path.join(service.data, 'nginx'), { recursive: true });
  fs.writeFileSync(path.join(service.data, 'nginx/nginx.pid'), String(process.pid));
  for (const args of [['status'], ['stop'], ['reload-proxy'], ['start'], ['start', '--no-proxy']]) {
    const result = service.run(...args);
    assert.notEqual(result.status, 0, result.stdout);
    assert.match(result.stderr, /does not identify this instance master/);
  }
  assert.ok(!fs.existsSync(path.join(service.data, 'nginx/master.json')));
  assert.ok(!service.calls().some(call => call.command === 'nginx' || ['start', 'stop'].includes(call.args[1])));
});

test('failed candidate validation preserves original config and removes candidate', t => {
  for (const action of ['start', 'reload-proxy']) {
    const service = fixture(t);
    if (action === 'reload-proxy') assert.equal(service.run('start').status, 0);
    const conf = path.join(service.data, 'nginx.conf');
    fs.writeFileSync(conf, '# retained known-good configuration\n');
    const original = fs.readFileSync(conf);
    const inode = fs.statSync(conf).ino;
    fs.writeFileSync(path.join(service.root, 'reject-config'), 'reject');
    const result = service.run(action);
    assert.notEqual(result.status, 0);
    assert.deepEqual(fs.readFileSync(conf), original);
    assert.equal(fs.statSync(conf).ino, inode);
    assert.ok(!fs.readdirSync(service.data).some(name => name.startsWith('.nginx-candidate-')));
    const validation = service.calls().filter(call => call.command === 'nginx' && call.args.includes('-t')).at(-1);
    assert.notEqual(validation.args[validation.args.indexOf('-c') + 1], conf);
    assert.equal(fs.readFileSync(path.join(service.root, 'signals'), 'utf8'), '');
  }
});

test('stop adopts a verified master and succeeds despite missing certificates and invalid config', t => {
  const service = fixture(t);
  assert.equal(service.run('start').status, 0);
  fs.unlinkSync(path.join(service.data, 'nginx/master.json'));
  fs.unlinkSync(path.join(service.data, 'tls/127.0.0.1/fullchain.pem'));
  fs.writeFileSync(path.join(service.data, 'nginx.conf'), 'invalid nginx syntax');
  fs.writeFileSync(path.join(service.root, 'reject-config'), 'reject');
  const before = service.calls().length;
  const result = service.run('stop');
  assert.equal(result.status, 0, result.stderr);
  assert.equal(fs.readFileSync(path.join(service.root, 'signals'), 'utf8'), 'quit\n');
  assert.ok(!service.calls().slice(before).some(call => call.command === 'nginx'));
  assert.ok(!fs.existsSync(path.join(service.root, 'state.json')));
});

test('saved boot/start identity mismatch never signals the live master', t => {
  for (const field of ['boot', 'start']) {
    const service = fixture(t);
    assert.equal(service.run('start').status, 0);
    const identity = path.join(service.data, 'nginx/master.json');
    const original = fs.readFileSync(identity, 'utf8');
    const record = JSON.parse(original);
    record[field] = 'different';
    fs.writeFileSync(identity, JSON.stringify(record));
    const result = service.run('stop');
    assert.notEqual(result.status, 0);
    assert.match(result.stderr, /boot\/start identity changed/);
    assert.equal(fs.readFileSync(path.join(service.root, 'signals'), 'utf8'), '');
    fs.writeFileSync(identity, original);
    assert.equal(service.run('stop').status, 0);
  }
});

test('same executable with another instance command is not adopted', t => {
  const service = fixture(t);
  fs.mkdirSync(path.join(service.data, 'nginx'), { recursive: true });
  const executable = path.join(service.root, 'runtime/nginx/sbin/nginx');
  const result = spawnSync(executable, ['-p', `${service.data}/nginx/`, '-c', `${service.data}/other.conf`, '-e', `${service.root}/log/nginx/error.log`], {
    env: { ...process.env, PASEO_TEST_ROOT: service.root }, timeout: 5000,
  });
  assert.equal(result.status, 0);
  const stop = service.run('stop');
  assert.notEqual(stop.status, 0);
  assert.match(stop.stderr, /does not identify this instance master/);
  assert.equal(fs.readFileSync(path.join(service.root, 'signals'), 'utf8'), '');
});


test('successful reload atomically publishes the validated configuration', t => {
  const service = fixture(t);
  assert.equal(service.run('start').status, 0);
  const conf = path.join(service.data, 'nginx.conf');
  const original = fs.statSync(conf).ino;
  fs.writeFileSync(path.join(service.data, 'paseo.conf'), '{"ip":"127.0.0.1","port":31416}');
  const result = service.run('reload-proxy');
  assert.equal(result.status, 0, result.stderr);
  assert.notEqual(fs.statSync(conf).ino, original);
  assert.match(fs.readFileSync(conf, 'utf8'), /31416/);
  assert.equal(fs.readFileSync(path.join(service.root, 'signals'), 'utf8'), 'reload\n');
  assert.ok(!fs.readdirSync(service.data).some(name => name.startsWith('.nginx-candidate-')));
  assert.equal(service.run('stop').status, 0);
});
