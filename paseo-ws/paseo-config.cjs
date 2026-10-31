#!/usr/bin/env node
const fs = require('node:fs');
const path = require('node:path');
const net = require('node:net');

function endpoint(home, mode) {
  const config = JSON.parse(fs.readFileSync(path.join(home, 'paseo.conf'), 'utf8'));
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

function prepare(home, mode, state) {
  const target = endpoint(home, mode);
  if (state.localDaemon === 'running' && state.listen !== target.listen) {
    throw new Error('服务正在使用其他监听设置，请先 stop，再按目标设置 start。');
  }
  if (!['running', 'stopped'].includes(state.localDaemon)) {
    throw new Error(`无法确认服务已停止：${state.localDaemon}，请检查 status。`);
  }
  const file = path.join(home, 'config.json');
  if (fs.lstatSync(file).isSymbolicLink()) throw new Error('config.json 必须是独立文件，不能链接至 paseo.conf。');
  const config = JSON.parse(fs.readFileSync(file, 'utf8'));
  config.daemon ??= {};
  config.daemon.listen = target.listen;
  config.daemon.hostnames = [...new Set([...(config.daemon.hostnames ?? []), target.ip])];
  config.features ??= {};
  config.features.webUi ??= {};
  config.features.webUi.enabled = true;
  writeJson(file, config);
}

function renderProxy(home) {
  const target = endpoint(home, 'proxy');
  // The template contains Nginx variables; only replace these explicit placeholders.
  const values = {
    PASEO_DATA: path.resolve(home), PASEO_LISTEN: target.proxyListen,
    PASEO_IP: target.ip, PASEO_TLS_NAME: target.tlsName,
  };
  return fs.readFileSync(path.join(__dirname, 'nginx.conf.template'), 'utf8')
    .replace(/@(PASEO_[A-Z_]+)@/g, (_, name) => values[name]);
}

if (require.main === module) {
  try {
    const [action, home, mode = 'proxy', rawState] = process.argv.slice(2);
    if (action === 'endpoint') {
      const value = endpoint(home, mode);
      console.log([value.listen, value.url, path.join(home, 'tls', value.tlsName, 'fullchain.pem')].join('\n'));
    } else if (action === 'prepare') {
      prepare(home, mode, JSON.parse(rawState));
    } else if (action === 'proxy') {
      fs.writeFileSync(path.join(home, 'nginx.conf'), renderProxy(home), { mode: 0o600 });
    } else throw new Error('未知配置操作。');
  } catch (error) {
    console.error(error.message);
    process.exitCode = 1;
  }
}

module.exports = { endpoint, prepare, renderProxy };
