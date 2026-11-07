const {sourceFile, fixtureFile} = require('./support.cjs');
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { endpoint, initialize, prepare, renderProxy } = require('../srcs/paseo-config.cjs');

function fixture(t, config = { ip: '10.30.0.25', port: 25227 }, withOfficialConfig = true) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-config-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const home = path.join(root, 'data');
  fs.mkdirSync(home);
  fs.writeFileSync(path.join(home, 'paseo.conf'), JSON.stringify(config));
  if (!withOfficialConfig) return home;
  fs.mkdirSync(path.join(home, '.paseo'), { mode: 0o700 });
  fs.writeFileSync(path.join(home, '.paseo', 'config.json'), JSON.stringify({
    version: 1, daemon: { relay: { enabled: false } }, agents: { providers: { pi: { enabled: true } } },
  }));
  return home;
}

test('initialize creates private defaults and leaves existing configuration untouched', t => {
  const home = fixture(t, undefined, false);
  initialize(home);
  const file = path.join(home, '.paseo/config.json');
  assert.deepEqual(JSON.parse(fs.readFileSync(file)), JSON.parse(fs.readFileSync(sourceFile('config.json.example'))));
  assert.equal(fs.statSync(path.dirname(file)).mode & 0o777, 0o700);
  assert.equal(fs.statSync(file).mode & 0o777, 0o600);
  const custom = '{"daemon":{"auth":{"password":"keep-me"}},"agents":{"providers":{}}}\n';
  fs.writeFileSync(file, custom);
  initialize(home);
  assert.equal(fs.readFileSync(file, 'utf8'), custom);
  fs.writeFileSync(file, 'invalid existing config');
  initialize(home);
  assert.equal(fs.readFileSync(file, 'utf8'), 'invalid existing config');
});

test('prepare bootstraps a stopped instance but never invents running or unknown configuration', t => {
  for (const state of [{localDaemon: 'running', listen: '127.0.0.1:25226'}, {localDaemon: 'unknown'}]) {
    const home = fixture(t, undefined, false);
    assert.throws(() => prepare(home, 'proxy', state));
    assert.ok(!fs.existsSync(path.join(home, '.paseo/config.json')));
  }
  const home = fixture(t, {ip: '127.0.0.2', port: 31415}, false);
  prepare(home, 'direct', {localDaemon: 'stopped'});
  const config = JSON.parse(fs.readFileSync(path.join(home, '.paseo/config.json')));
  assert.equal(config.daemon.listen, '0.0.0.0:31415');
  assert.ok(config.daemon.hostnames.includes('127.0.0.2'));
  assert.equal(config.daemon.relay.enabled, false);
  assert.equal(config.features.webUi.enabled, true);
});

test('initialize rejects existing and dangling configuration symlinks without changing their targets', t => {
  for (const target of ['paseo.conf', 'missing.json']) {
    const home = fixture(t, undefined, false);
    const before = fs.readFileSync(path.join(home, 'paseo.conf'), 'utf8');
    fs.mkdirSync(path.join(home, '.paseo'));
    fs.symlinkSync(path.join(home, target), path.join(home, '.paseo/config.json'));
    assert.throws(() => initialize(home), /独立文件/);
    assert.equal(fs.readFileSync(path.join(home, 'paseo.conf'), 'utf8'), before);
    assert.ok(!fs.existsSync(path.join(home, 'missing.json')));
  }
});

test('IP and port control direct and proxy endpoints, including IPv6', t => {
  const home = fixture(t, { ip: '127.0.0.2', port: 31415 });
  assert.equal(endpoint(home, 'direct').listen, '0.0.0.0:31415');
  assert.equal(endpoint(home, 'direct').url, 'http://127.0.0.2:31415');
  assert.equal(endpoint(home, 'proxy').listen, '127.0.0.1:25226');
  fs.writeFileSync(path.join(home, 'paseo.conf'), JSON.stringify({ ip: '::1', port: 31415 }));
  assert.equal(endpoint(home, 'direct').listen, '[::]:31415');
  assert.equal(endpoint(home, 'proxy').url, 'https://[::1]:31415');
});

test('reject invalid addresses, ports, extra keys, and proxy port conflicts', t => {
  const home = fixture(t);
  for (const config of [
    { ip: 'bad;address', port: 1234 }, { ip: '127.0.0.1', port: '1234' },
    { ip: '127.0.0.1', port: 65536 }, { ip: '127.0.0.1', port: 0 },
    { ip: '127.0.0.1', port: 1234, daemon: {} }, { ip: '127.0.0.1', port: 25226 },
  ]) {
    fs.writeFileSync(path.join(home, 'paseo.conf'), JSON.stringify(config));
    assert.throws(() => endpoint(home, 'proxy'));
  }
});

test('networkProxy accepts HTTP proxies and rejects malformed values', t => {
  const home = fixture(t);
  for (const networkProxy of ['', 'http://127.0.0.1:7890', 'https://user:pass@[::1]:8443']) {
    fs.writeFileSync(path.join(home, 'paseo.conf'), JSON.stringify({ ip: '127.0.0.1', port: 31415, networkProxy }));
    assert.equal(endpoint(home, 'direct').listen, '0.0.0.0:31415');
  }
  for (const networkProxy of [null, true, 7890, 'localhost:7890', 'socks5://localhost:7890', 'http://localhost:99999', 'http://localhost/path', 'http://localhost?x=1', 'http://localhost#x', 'http://localhost\n', ' http://localhost']) {
    fs.writeFileSync(path.join(home, 'paseo.conf'), JSON.stringify({ ip: '127.0.0.1', port: 31415, networkProxy }));
    assert.throws(() => endpoint(home, 'proxy'), /networkProxy/);
  }
});

test('prepare preserves provider settings and the two-field user configuration', t => {
  const home = fixture(t);
  const before = fs.readFileSync(path.join(home, 'paseo.conf'), 'utf8');
  prepare(home, 'proxy', { localDaemon: 'stopped' });
  const official = JSON.parse(fs.readFileSync(path.join(home, '.paseo', 'config.json'), 'utf8'));
  assert.equal(official.agents.providers.pi.enabled, true);
  assert.equal(official.daemon.relay.enabled, false);
  assert.equal(official.daemon.listen, '127.0.0.1:25226');
  assert.equal(official.features.webUi.enabled, true);
  assert.equal(fs.readFileSync(path.join(home, 'paseo.conf'), 'utf8'), before);
  assert.equal(fs.statSync(path.join(home, '.paseo', 'config.json')).mode & 0o777, 0o600);
});

test('stopped instances preserve old logs and redirect lifecycle writes without changing rotation', t => {
  const home = fixture(t);
  const file = path.join(home, '.paseo/config.json');
  const config = JSON.parse(fs.readFileSync(file));
  config.log = { level: 'debug', file: { path: 'daemon.log', rotate: { maxFiles: 7 } } };
  fs.writeFileSync(file, JSON.stringify(config));
  const legacy = path.join(home, '.paseo/daemon.log');
  fs.writeFileSync(legacy, 'old log\n');
  const logs = path.resolve(home, '..', 'log');
  fs.mkdirSync(logs);
  const current = path.join(logs, 'daemon.log');
  fs.writeFileSync(current, 'new log\n');
  prepare(home, 'proxy', { localDaemon: 'running', listen: '127.0.0.1:25226' });
  assert.ok(!fs.lstatSync(legacy).isSymbolicLink());
  assert.equal(JSON.parse(fs.readFileSync(file)).log.file.path, 'daemon.log');
  prepare(home, 'proxy', { localDaemon: 'stopped' });
  const after = JSON.parse(fs.readFileSync(file));
  assert.equal(path.resolve(path.dirname(file), after.log.file.path), current);
  assert.equal(after.log.level, 'debug');
  assert.equal(after.log.file.rotate.maxFiles, 7);
  assert.ok(fs.lstatSync(legacy).isSymbolicLink());
  assert.equal(fs.readFileSync(current, 'utf8'), 'new log\n');
  const archives = fs.readdirSync(logs).filter(name => name.startsWith('legacy-'));
  assert.equal(archives.length, 1);
  assert.equal(fs.readFileSync(path.join(logs, archives[0], 'daemon.log'), 'utf8'), 'old log\n');
  fs.appendFileSync(legacy, 'exit record\n');
  assert.equal(fs.readFileSync(current, 'utf8'), 'new log\nexit record\n');
  prepare(home, 'proxy', { localDaemon: 'stopped' });
  assert.equal(fs.readdirSync(logs).filter(name => name.startsWith('legacy-')).length, 1);
});

test('running mode mismatch and unknown state cannot rewrite official configuration', t => {
  const home = fixture(t);
  const before = fs.readFileSync(path.join(home, '.paseo', 'config.json'), 'utf8');
  assert.throws(() => prepare(home, 'proxy', { localDaemon: 'running', listen: '0.0.0.0:25227' }));
  assert.throws(() => prepare(home, 'proxy', { localDaemon: 'unknown' }));
  assert.equal(fs.readFileSync(path.join(home, '.paseo', 'config.json'), 'utf8'), before);
});

test('proxy configuration uses local certificates, configured port, and intact Nginx variables', t => {
  const home = fixture(t, { ip: '127.0.0.2', port: 31415 });
  const text = renderProxy(home);
  assert.ok(text.includes('listen 0.0.0.0:31415 ssl;'));
  assert.ok(text.includes('server_name 127.0.0.2;'));
  assert.ok(text.includes(`${home}/tls/127.0.0.2/fullchain.pem`));
  assert.ok(text.includes('$http_upgrade'));
  assert.ok(text.includes('gzip on;'));
  assert.ok(text.includes('gzip_types application/javascript application/json text/css image/svg+xml;'));
  assert.ok(text.includes(`error_log ${path.resolve(home, '..', 'log')}/nginx/error.log warn;`));
  assert.ok(text.includes(`pid ${home}/nginx/nginx.pid;`));
  assert.ok(!text.includes('@PASEO_'));
});
