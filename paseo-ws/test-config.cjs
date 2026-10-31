const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { endpoint, prepare, renderProxy } = require('./paseo-config.cjs');

function fixture(t, config = { ip: '10.30.0.25', port: 25227 }) {
  const home = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-config-'));
  t.after(() => fs.rmSync(home, { recursive: true, force: true }));
  fs.writeFileSync(path.join(home, 'paseo.conf'), JSON.stringify(config));
  fs.writeFileSync(path.join(home, 'config.json'), JSON.stringify({
    version: 1, daemon: { relay: { enabled: false } }, agents: { providers: { pi: { enabled: true } } },
  }));
  return home;
}

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

test('prepare preserves provider settings and the two-field user configuration', t => {
  const home = fixture(t);
  const before = fs.readFileSync(path.join(home, 'paseo.conf'), 'utf8');
  prepare(home, 'proxy', { localDaemon: 'stopped' });
  const official = JSON.parse(fs.readFileSync(path.join(home, 'config.json'), 'utf8'));
  assert.equal(official.agents.providers.pi.enabled, true);
  assert.equal(official.daemon.relay.enabled, false);
  assert.equal(official.daemon.listen, '127.0.0.1:25226');
  assert.equal(official.features.webUi.enabled, true);
  assert.equal(fs.readFileSync(path.join(home, 'paseo.conf'), 'utf8'), before);
  assert.equal(fs.statSync(path.join(home, 'config.json')).mode & 0o777, 0o600);
});

test('running mode mismatch and unknown state cannot rewrite official configuration', t => {
  const home = fixture(t);
  const before = fs.readFileSync(path.join(home, 'config.json'), 'utf8');
  assert.throws(() => prepare(home, 'proxy', { localDaemon: 'running', listen: '0.0.0.0:25227' }));
  assert.throws(() => prepare(home, 'proxy', { localDaemon: 'unknown' }));
  assert.equal(fs.readFileSync(path.join(home, 'config.json'), 'utf8'), before);
});

test('proxy configuration uses local certificates, configured port, and intact Nginx variables', t => {
  const home = fixture(t, { ip: '127.0.0.2', port: 31415 });
  const text = renderProxy(home);
  assert.ok(text.includes('listen 0.0.0.0:31415 ssl;'));
  assert.ok(text.includes('server_name 127.0.0.2;'));
  assert.ok(text.includes(`${home}/tls/127.0.0.2/fullchain.pem`));
  assert.ok(text.includes('$http_upgrade'));
  assert.ok(!text.includes('@PASEO_'));
});
