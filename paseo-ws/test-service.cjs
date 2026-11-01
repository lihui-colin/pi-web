const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('node:fs');
const os = require('node:os');
const path = require('node:path');
const { spawnSync } = require('node:child_process');

function fixture(t) {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'paseo-service-'));
  t.after(() => fs.rmSync(root, { recursive: true, force: true }));
  const data = path.join(root, 'data');
  fs.mkdirSync(path.join(data, '.paseo'), { recursive: true });
  fs.writeFileSync(path.join(data, 'paseo.conf'), '{"ip":"127.0.0.1","port":31415}');
  fs.copyFileSync(path.join(__dirname, 'config.json.example'), path.join(data, '.paseo/config.json'));
  for (const file of ['paseo_web_run.sh', 'node-runtime.sh', 'paseo-config.cjs', 'nginx.conf.template']) {
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
} else if (command === 'nginx') {
  if (args.includes('-s') && args.includes('quit')) fs.rmSync(pidFile,{force:true});
  else if (!args.includes('-s') && !args.includes('-t')) fs.writeFileSync(pidFile, process.env.PASEO_TEST_PID);
}
`;
  for (const file of ['runtime/bin/paseo', 'runtime/nginx/sbin/nginx', 'bin/curl']) {
    const target = path.join(root, file);
    fs.mkdirSync(path.dirname(target), { recursive: true });
    fs.writeFileSync(target, mock, { mode: 0o755 });
  }
  return {
    root, data,
    run(...args) {
      return spawnSync('bash', [path.join(root, 'paseo_web_run.sh'), ...args], {
        encoding: 'utf8', timeout: 5000,
        env: { ...process.env, PASEO_TEST_ROOT: root, PASEO_TEST_PID: String(process.pid), PATH: `${root}/bin:${process.env.PATH}` },
      });
    },
    calls() { return fs.readFileSync(path.join(root, 'calls'), 'utf8').trim().split('\n').map(JSON.parse); },
  };
}

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
  assert.ok(calls.some(call => call.command === 'nginx' && call.args.includes('reload')));
  assert.ok(!fs.existsSync(path.join(service.root, 'state.json')));
});

test('HTTP mode skips Nginx and uses the configured direct listener', t => {
  const service = fixture(t);
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
