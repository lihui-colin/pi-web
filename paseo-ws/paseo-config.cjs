#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');

async function initializeAccess(data) {
  const file = path.join(data, 'paseo.conf');
  if (fs.lstatSync(file, { throwIfNoEntry: false })) return;
  const reader = require('node:readline').createInterface({ input: process.stdin, crlfDelay: Infinity });
  const lines = reader[Symbol.asyncIterator]();
  const config = {};
  const fields = [
    ['ip', 'IP 地址', '10.30.0.25', value => net.isIP(value), '请输入有效的 IPv4 或 IPv6 地址。'],
    ['port', '端口号', '25227', value => /^\d{1,5}$/.test(value) && +value > 0 && +value <= 65535 && +value !== 25226,
      '端口须为 1–65535 的整数，且不能占用后端端口 25226。'],
  ];
  console.log('首次安装：请配置 Paseo 访问地址。');
  try {
    for (const [key, label, fallback, valid, error] of fields) {
      while (true) {
        process.stderr.write(`${label} [${fallback}]：`);
        const line = await lines.next();
        if (line.done) throw new Error(`未收到${label}，配置未创建。请在终端重新运行安装脚本。`);
        const value = line.value.trim() || fallback;
        if (valid(value)) {
          config[key] = key === 'port' ? Number(value) : value;
          break;
        }
        console.error(error);
      }
    }
    fs.mkdirSync(data, { recursive: true, mode: 0o700 });
    try {
      fs.writeFileSync(file, JSON.stringify(config, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
      console.log(`已创建访问配置：${file}`);
    } catch (error) {
      if (error.code !== 'EEXIST') throw error;
      console.log('访问配置已由其他进程创建，保留现有文件。');
    }
  } finally {
    reader.close();
  }
}

function endpoint(data, mode) {
  const config = JSON.parse(fs.readFileSync(path.join(data, 'paseo.conf'), 'utf8'));
  const { ip, port } = config;
  if (Object.keys(config).some(key => !['ip', 'port'].includes(key)) ||
      typeof ip !== 'string' || !net.isIP(ip) ||
      !Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('paseo.conf 只能包含 ip（IP 地址）和 port（1–65535 的整数）。');
  }
  if (!['proxy', 'direct'].includes(mode)) throw new Error('未知监听模式。');
  if (mode === 'proxy' && port === 25226) throw new Error('HTTPS 端口不能与后端端口 25226 相同。');
  const ipv6 = net.isIP(ip) === 6;
  return {
    ip, port,
    listen: mode === 'proxy' ? '127.0.0.1:25226' : `${ipv6 ? '[::]' : '0.0.0.0'}:${port}`,
    proxyListen: `${ipv6 ? '[::]' : '0.0.0.0'}:${port}`,
    url: `${mode === 'proxy' ? 'https' : 'http'}://${ipv6 ? `[${ip}]` : ip}:${port}`,
    tlsName: ip.toLowerCase().replaceAll(':', '_'),
  };
}

function writeJson(file, value) {
  const temp = `${file}.tmp`;
  try {
    fs.writeFileSync(temp, JSON.stringify(value, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
    fs.renameSync(temp, file);
  } catch (error) {
    // Leave an existing temporary file intact if this invocation did not create it.
    if (error.code !== 'EEXIST' && fs.existsSync(temp)) fs.unlinkSync(temp);
    throw error;
  }
}

function configFileExists(file) {
  const stat = fs.lstatSync(file, { throwIfNoEntry: false });
  if (stat && !stat.isFile()) throw new Error('config.json 必须是独立文件，不能链接至 paseo.conf。');
  return Boolean(stat);
}

function initialize(data) {
  const file = path.join(data, '.paseo', 'config.json');
  if (configFileExists(file)) return;
  const defaults = JSON.parse(fs.readFileSync(path.join(__dirname, 'config.json.example'), 'utf8'));
  fs.mkdirSync(path.dirname(file), { recursive: true, mode: 0o700 });
  try {
    fs.writeFileSync(file, JSON.stringify(defaults, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
  } catch (error) {
    if (error.code !== 'EEXIST') throw error;
    // Another initializer won the race; validate its path without overwriting it.
    if (!configFileExists(file)) throw error;
  }
}

function prepareLogs(data, config) {
  const home = path.resolve(data, '.paseo');
  const logs = path.resolve(data, '..', 'log');
  const target = path.join(logs, 'daemon.log');
  const legacy = path.join(home, 'daemon.log');
  fs.mkdirSync(logs, { recursive: true, mode: 0o700 });
  const existing = fs.lstatSync(legacy, { throwIfNoEntry: false });
  if (existing?.isSymbolicLink()) {
    if (path.resolve(home, fs.readlinkSync(legacy)) !== target) {
      throw new Error('daemon.log 链接指向其他位置，请检查后重试。');
    }
  } else {
    if (existing) {
      if (!existing.isFile()) throw new Error('daemon.log 必须是普通文件或指向日志目录的链接。');
      // Both paths are inside this instance; preserve the old log in a unique archive.
      const archive = fs.mkdtempSync(path.join(logs, 'legacy-'));
      fs.renameSync(legacy, path.join(archive, 'daemon.log'));
    }
    // Upstream worker lifecycle messages still use PASEO_HOME/daemon.log.
    fs.symlinkSync(path.relative(home, target), legacy);
  }
  config.log ??= {};
  config.log.file ??= {};
  config.log.file.path = path.relative(home, target);
}

function prepare(data, mode, state) {
  const target = endpoint(data, mode);
  if (state.localDaemon === 'running' && state.listen !== target.listen) {
    throw new Error('服务正在使用其他监听设置，请先 stop，再按目标设置 start。');
  }
  if (!['running', 'stopped'].includes(state.localDaemon)) {
    throw new Error(`无法确认服务已停止：${state.localDaemon}，请检查 status。`);
  }
  const file = path.join(data, '.paseo', 'config.json');
  if (state.localDaemon === 'stopped') initialize(data);
  configFileExists(file);
  const config = JSON.parse(fs.readFileSync(file, 'utf8'));
  if (state.localDaemon === 'stopped') prepareLogs(data, config);
  config.daemon ??= {};
  config.daemon.listen = target.listen;
  config.daemon.hostnames = [...new Set([...(config.daemon.hostnames ?? []), target.ip])];
  config.features ??= {};
  config.features.webUi ??= {};
  config.features.webUi.enabled = true;
  writeJson(file, config);
}

function renderProxy(data) {
  const target = endpoint(data, 'proxy');
  // The template contains Nginx variables; only replace these explicit placeholders.
  const values = {
    PASEO_DATA: path.resolve(data), PASEO_LOG: path.resolve(data, '..', 'log'),
    PASEO_LISTEN: target.proxyListen,
    PASEO_IP: target.ip, PASEO_TLS_NAME: target.tlsName,
  };
  return fs.readFileSync(path.join(__dirname, 'nginx.conf.template'), 'utf8')
    .replace(/@(PASEO_[A-Z_]+)@/g, (_, name) => values[name]);
}

async function main() {
  const [action, data, mode = 'proxy', rawState] = process.argv.slice(2);
  if (action === 'endpoint') {
    const value = endpoint(data, mode);
    console.log([value.listen, value.url, path.join(data, 'tls', value.tlsName, 'fullchain.pem')].join('\n'));
  } else if (action === 'access') {
    await initializeAccess(data);
  } else if (action === 'init') {
    initialize(data);
  } else if (action === 'prepare') {
    prepare(data, mode, JSON.parse(rawState));
  } else if (action === 'proxy') {
    fs.writeFileSync(path.join(data, 'nginx.conf'), renderProxy(data), { mode: 0o600 });
  } else throw new Error('未知配置操作。');
}

if (require.main === module) main().catch(error => {
  console.error(error.message);
  process.exitCode = 1;
});

module.exports = { endpoint, initialize, prepare, renderProxy };
