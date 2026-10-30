#!/usr/bin/env bash
# 按 dsh.conf 的 server_ip 生成 HTTPS 证书，保存在 data/tls/<地址>/。
# 不安装程序，不修改配置，不启停服务，不覆盖已有证书。
set -euo pipefail
umask 077
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
config_file="$script_dir/data/dsh.conf"
tls_dir=''
tls_hosts=()
dry_run=false
while (( $# )); do
    case "$1" in
        --dry-run) dry_run=true; shift ;;
        --config|--tls-dir|--tls-host)
            option="$1"
            if (( $# < 2 )) || [[ -z "$2" || "$2" == --* ]]; then
                printf '%s 需要一个值。\n' "$option" >&2; exit 2
            fi
            case "$option" in
                --config) config_file="$2" ;;
                --tls-dir) tls_dir="$2" ;;
                --tls-host) tls_hosts+=("$2") ;;
            esac
            shift 2 ;;
        -h|--help)
            printf '%s\n' \
                '用法：bash ds-harness/dsh_cert.sh [--dry-run] [--config 文件] [--tls-dir 根目录] [--tls-host 额外IP或域名]' \
                '需要 Node.js >=24 和 OpenSSL。默认读取脚本目录下 data/dsh.conf 的 server_ip。' \
                '默认配置的证书保存在脚本目录下 data/tls/<server_ip>/；自定义 --config 则保存在配置目录下 tls/<server_ip>/。' \
                'IPv6 目录名中的冒号替换为下划线。' \
                '--tls-dir 指定保存根目录，仍会追加地址子目录；--tls-host 可重复添加 SAN。' \
                '只读取 server_ip；启动脚本从同目录 data/tls/<地址>/ 自动加载，不使用旧 tls_cert/tls_key。' \
                '已有证书校验后保留；--dry-run 不写入文件。' \
                'Linux/macOS 使用 Node 内置 SQLite 按输出目录互斥，最多等待 60 秒；不要删除锁文件。' \
                '中断后重试会校验并恢复 .dsh-cert-pending；需要支持硬链接和 SQLite 锁的本地文件系统。' \
                '将 ca.crt 导入访问设备并信任，切勿分发任何私钥。'
            exit 0 ;;
        *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
    esac
done
for bin in node openssl; do
    command -v "$bin" >/dev/null 2>&1 || { printf '缺少命令：%s\n' "$bin" >&2; exit 1; }
done
node -e 'if (Number(process.versions.node.split(".")[0]) < 24) { console.error("需要 Node.js >=24"); process.exit(1); }'
# 只解析需要的配置键，不 source 配置文件。
node --input-type=module - "$config_file" "$tls_dir" "$dry_run" "${tls_hosts[@]}" <<'TLS_NODE'
import fs from 'node:fs';
import path from 'node:path';
import net from 'node:net';
import crypto from 'node:crypto';
import { execFileSync } from 'node:child_process';
const [configArg, dirOverride, preview, ...extraHosts] = process.argv.slice(2);
const config = path.resolve(configArg);
if (!fs.existsSync(config)) throw new Error(`缺少 DSH 配置：${config}。请先从脚本目录下 dsh.conf.example 复制到 ${config} 并填写 server_ip（默认配置为 data/dsh.conf）。`);
let serverIp;
for (const line of fs.readFileSync(config, 'utf8').split(/\r?\n/)) {
  const m = line.match(/^\s*(server_ip)\s*=\s*(.*?)\s*$/);
  if (!m) continue;
  const raw = m[2];
  const quoted = raw.match(/^(['"])(.*?)\1\s*(?:#.*)?$/);
  serverIp = quoted ? quoted[2] : raw.replace(/\s+#.*$/, '').trim();
}
if (!serverIp) throw new Error('DSH 配置缺少 server_ip');
const hosts = [...new Set([serverIp, ...extraHosts])];
const san = hosts.map(host => {
  if (net.isIP(host)) return `IP:${host}`;
  if (host.length <= 253 && host.split('.').every(label => /^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/.test(label))) return `DNS:${host}`;
  throw new Error(`无效的 IP 或域名：${host}，请勿包含协议、端口或路径`);
});
const base = path.dirname(config);
// Always namespace output by the address, even if legacy tls_cert/tls_key point elsewhere.
const addressDir = serverIp.toLowerCase().replaceAll(':', '_');
const outputDir = path.join(dirOverride ? path.resolve(dirOverride) : path.join(base, 'tls'), addressDir);
const cert = path.join(outputDir, 'fullchain.pem');
const key = path.join(outputDir, 'privkey.pem');
const ca = path.join(outputDir, 'ca.pem');
const caKey = path.join(outputDir, 'ca-key.pem');
const caCrt = path.join(outputDir, 'ca.crt');
const openssl = args => execFileSync('openssl', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
function validatePair(certPath, keyPath) {
  const x = new crypto.X509Certificate(fs.readFileSync(certPath));
  if (!x.checkPrivateKey(crypto.createPrivateKey(fs.readFileSync(keyPath)))) throw new Error(`证书和私钥不匹配：${certPath}`);
  openssl(['x509', '-in', certPath, '-noout', '-checkend', '86400']);
  return x;
}
// A committed directory is the recovery marker. Staging and published files share
// inodes: publication is atomic/no-clobber, and recovery never adopts unknown files.
const pending = path.join(outputDir, '.dsh-cert-pending');
const names = ['ca-key.pem', 'ca.pem', 'privkey.pem', 'fullchain.pem', 'ca.crt'];
const exists = file => fs.lstatSync(file, { throwIfNoEntry: false }) !== undefined;
function regular(file) {
  const stat = fs.lstatSync(file);
  if (!stat.isFile()) throw new Error(`拒绝非普通文件：${file}`);
  return stat;
}
function digest(file) {
  regular(file);
  return crypto.createHash('sha256').update(fs.readFileSync(file)).digest('hex');
}
function syncFile(file) {
  const fd = fs.openSync(file, 'r');
  try { fs.fsyncSync(fd); } finally { fs.closeSync(fd); }
}
// Read-only semantic checks shared by existing files and the prospective result
// of recovery. Paths may combine staged publications with existing dependencies.
function validateCertificates(paths) {
  for (const file of Object.values(paths)) {
    if (exists(file)) regular(file);
  }
  const certPath = paths['fullchain.pem'], keyPath = paths['privkey.pem'];
  const caPath = paths['ca.pem'], exportPath = paths['ca.crt'];
  const x = validatePair(certPath, keyPath);
  for (const host of hosts) {
    const match = net.isIP(host) ? x.checkIP(host) : x.checkHost(host, { subject: 'never' });
    if (!match) throw new Error(`已有证书未覆盖 ${host}；请备份后配置新的证书路径`);
  }
  if (!exists(caPath)) return;
  const root = new crypto.X509Certificate(fs.readFileSync(caPath));
  if (!root.ca) throw new Error('ca.pem 不是 CA 证书，拒绝导出');
  openssl(['verify', '-CAfile', caPath, certPath]);
  if (exists(exportPath)) {
    const existing = new crypto.X509Certificate(fs.readFileSync(exportPath));
    if (!existing.raw.equals(root.raw)) throw new Error('已有 ca.crt 与 ca.pem 不一致，请备份并检查后再处理');
  }
}
const certificatePaths = Object.fromEntries(names.map(name => [name, path.join(outputDir, name)]));
function recoverPublication() {
  if (!exists(pending)) return;
  if (!fs.lstatSync(pending).isDirectory()) throw new Error('发布事务目录无效，请检查备份');
  const manifestPath = path.join(pending, 'manifest.json');
  regular(manifestPath);
  const m = JSON.parse(fs.readFileSync(manifestPath, 'utf8'));
  if (m.version !== 1 || !Array.isArray(m.files) || !m.files.length ||
      new Set(m.files.map(e => e.name)).size !== m.files.length ||
      m.files.some(e => !names.includes(e.name) || typeof e.publish !== 'boolean' ||
        !/^[a-f0-9]{64}$/.test(e.sha256)) || !m.files.some(e => e.publish)) {
    throw new Error('发布事务 manifest 无效，请检查备份');
  }
  const expected = new Set(['manifest.json', ...m.files.map(e => e.name)]);
  if (fs.readdirSync(pending).some(name => !expected.has(name))) {
    throw new Error('发布事务含未知文件，停止处理并保留目录');
  }
  const missing = [];
  // Validate the entire transaction before publishing anything, including reused CA.
  for (const e of m.files) {
    const staged = path.join(pending, e.name), target = path.join(outputDir, e.name);
    if (digest(staged) !== e.sha256) throw new Error(`发布事务文件校验失败：${e.name}`);
    if (exists(target)) {
      const a = regular(target), b = regular(staged);
      if (digest(target) !== e.sha256 || (e.publish && (a.dev !== b.dev || a.ino !== b.ino))) {
        throw new Error(`发布目标不是事务拥有的文件或已变更：${e.name}，拒绝覆盖`);
      }
    } else if (!e.publish) throw new Error(`发布依赖文件已丢失：${e.name}`);
    else missing.push(e.name);
  }
  const paths = { ...certificatePaths };
  for (const e of m.files) {
    if (e.publish) paths[e.name] = path.join(pending, e.name);
  }
  validateCertificates(paths);
  if (preview === 'true') {
    console.log('预览：存在可恢复发布事务；重试时将继续发布，不写入文件。');
    return;
  }
  for (const name of missing) {
    // EEXIST is an error even if an external writer races the validation above.
    fs.linkSync(path.join(pending, name), path.join(outputDir, name));
  }
  syncFile(outputDir);
  // Never partially remove the active recovery marker. A killed cleanup can leave
  // an inert private staging directory, but cannot make final files unrecoverable.
  const retired = path.join(outputDir, `.generate-${crypto.randomUUID()}`);
  fs.renameSync(pending, retired);
  syncFile(outputDir);
  fs.rmSync(retired, { recursive: true });
  console.log('证书发布事务已完成。');
}
function publishTransaction(files, dependencies = []) {
  const temp = fs.mkdtempSync(path.join(outputDir, '.generate-'));
  try {
    const entries = [];
    for (const name of [...Object.keys(files), ...dependencies]) {
      const publish = Object.hasOwn(files, name);
      const target = path.join(outputDir, name);
      if (publish && exists(target)) throw new Error(`已有文件，拒绝覆盖：${target}`);
      if (!publish) regular(target);
      const staged = path.join(temp, name);
      fs.writeFileSync(staged, publish ? files[name] : fs.readFileSync(target),
        { flag: 'wx', mode: name.includes('key') ? 0o600 : 0o644 });
      syncFile(staged);
      entries.push({ name, publish, sha256: digest(staged) });
    }
    fs.writeFileSync(path.join(temp, 'manifest.json'), JSON.stringify({ version: 1, files: entries }), { flag: 'wx', mode: 0o600 });
    syncFile(path.join(temp, 'manifest.json'));
    syncFile(temp);
    fs.renameSync(temp, pending);
    syncFile(outputDir);
    recoverPublication();
  } finally {
    // After commit temp no longer exists. Keep pending intact on any failure.
    fs.rmSync(temp, { recursive: true, force: true });
  }
}
// Export only the public root certificate; preserve the server certificate and keys.
function exportRootCertificate() {
  if (!fs.existsSync(ca)) {
    console.log('未找到本地 ca.pem，未导出 ca.crt；外部签发证书请使用签发方提供的根证书。');
    return;
  }
  const root = new crypto.X509Certificate(fs.readFileSync(ca));
  if (!fs.existsSync(caCrt) && preview !== 'true') {
    publishTransaction({ 'ca.crt': root.toString() }, ['ca.pem', 'fullchain.pem', 'privkey.pem']);
  }
  console.log(`${preview === 'true' ? '预览：根证书导出路径' : '设备导入并信任的根证书'}：${caCrt}`);
}
console.log(`DSH 配置：${config}\n证书 SAN：${san.join(', ')}\nHTTPS 证书：${cert}\n服务器私钥：${key}`);
console.log('dsh_web_run.sh 启动时按 server_ip 从同目录 data/tls/<地址>/ 自动加载证书，不需要配置 tls_cert/tls_key。');
if (dirOverride && path.resolve(dirOverride) !== path.join(base, 'tls')) {
  console.log(`自定义输出目录仅用于导出；使用启动脚本前，请将 ${outputDir} 中的证书和私钥部署到 ${path.join(base, 'tls', addressDir)}。`);
}
function processCertificates() {
if (exists(pending)) {
  recoverPublication();
  if (preview === 'true') return;
}
// lstat also catches dangling symlinks; never treat them as missing user files.
for (const name of names) {
  const file = path.join(outputDir, name);
  if (exists(file)) regular(file);
}
if (fs.existsSync(cert) !== fs.existsSync(key)) throw new Error('已有证书/私钥不完整，停止处理；请先检查备份');
if (fs.existsSync(cert)) {
  validateCertificates(certificatePaths);
  console.log('已有证书有效、地址和私钥匹配，保留原文件。');
  exportRootCertificate();
  return;
}
if (fs.existsSync(ca) !== fs.existsSync(caKey)) throw new Error('已有 CA 文件不完整，停止处理');
if (fs.existsSync(ca)) {
  const x = validatePair(ca, caKey);
  if (!x.ca) throw new Error('ca.pem 不是 CA 证书');
  // 服务器证书有效期为 365 天，CA 必须至少覆盖这一时间。
  openssl(['x509', '-in', ca, '-noout', '-checkend', String(366 * 86400)]);
}
if (exists(caCrt)) {
  if (!exists(ca) || !new crypto.X509Certificate(fs.readFileSync(caCrt)).raw.equals(new crypto.X509Certificate(fs.readFileSync(ca)).raw)) {
    throw new Error('已有 ca.crt 与 ca.pem 不一致或 CA 不完整，拒绝覆盖');
  }
}
if (preview === 'true') {
  console.log(`预览：将生成/复用本地 CA ${ca}，签发有效期 365 天的 HTTPS 证书并导出 ${caCrt}，不写入文件。`);
  return;
}
fs.mkdirSync(outputDir, { recursive: true, mode: 0o700 });
const temp = fs.mkdtempSync(path.join(outputDir, '.generate-'));
try {
  const tempCa = path.join(temp, 'ca.pem'), tempCaKey = path.join(temp, 'ca-key.pem');
  const reqConfig = path.join(temp, 'openssl.cnf');
  fs.writeFileSync(reqConfig, '[req]\ndistinguished_name=dn\n[dn]\n[v3_ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n');
  if (!fs.existsSync(ca)) {
    openssl(['req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-sha256', '-days', '3650',
      '-config', reqConfig, '-extensions', 'v3_ca', '-subj', `/CN=DSH Local HTTPS CA ${serverIp}`,
      '-keyout', tempCaKey, '-out', tempCa]);
    fs.chmodSync(tempCaKey, 0o600);
  }
  const signer = fs.existsSync(ca) ? ca : tempCa;
  const signerKey = fs.existsSync(caKey) ? caKey : tempCaKey;
  const tempKey = path.join(temp, 'privkey.pem'), csr = path.join(temp, 'server.csr');
  const tempCert = path.join(temp, 'server.pem'), ext = path.join(temp, 'server.ext');
  openssl(['req', '-new', '-newkey', 'rsa:2048', '-nodes', '-sha256', '-config', reqConfig, '-subj', '/CN=DSH HTTPS', '-keyout', tempKey, '-out', csr]);
  fs.chmodSync(tempKey, 0o600);
  fs.writeFileSync(ext, `basicConstraints=critical,CA:FALSE\nkeyUsage=critical,digitalSignature,keyEncipherment\nextendedKeyUsage=serverAuth\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid,issuer\nsubjectAltName=${san.join(',')}\n`);
  openssl(['x509', '-req', '-in', csr, '-CA', signer, '-CAkey', signerKey,
    '-set_serial', `0x${crypto.randomBytes(16).toString('hex')}`, '-days', '365', '-sha256', '-extfile', ext, '-out', tempCert]);
  openssl(['verify', '-CAfile', signer, tempCert]);
  validatePair(tempCert, tempKey);
  const files = {};
  const dependencies = [];
  for (const [name, source] of [['ca-key.pem', signerKey], ['ca.pem', signer]]) {
    if (exists(path.join(outputDir, name))) dependencies.push(name);
    else files[name] = fs.readFileSync(source);
  }
  files['privkey.pem'] = fs.readFileSync(tempKey);
  files['fullchain.pem'] = fs.readFileSync(tempCert, 'utf8') + fs.readFileSync(signer, 'utf8');
  if (exists(caCrt)) dependencies.push('ca.crt');
  else files['ca.crt'] = new crypto.X509Certificate(fs.readFileSync(signer)).toString();
  publishTransaction(files, dependencies);
  exportRootCertificate();
  console.log(`HTTPS 证书已生成。请在访问设备上导入并信任根证书：${caCrt}`);
  console.log('不要分发 ca-key.pem 或 privkey.pem；iOS 安装描述文件后还需启用根证书完全信任。');
} finally {
  fs.rmSync(temp, { recursive: true, force: true });
}
}

if (preview === 'true') {
  // Read-only observation: never create a directory, database or journal for preview.
  processCertificates();
} else {
  // SQLite's OS-backed locks work on Linux and macOS without a flock executable.
  // Keep this file permanently: unlinking it could let callers lock different inodes.
  // No rows are written; BEGIN IMMEDIATE serializes ALL checks and publication.
  // close() rolls back on errors; process death (including SIGKILL) releases the lock
  // in the kernel, so a leftover database is not a stale lock. Use a local filesystem
  // with working SQLite file locks, and do not move the directory while in use.
  const { DatabaseSync } = await import('node:sqlite');
  fs.mkdirSync(outputDir, { recursive: true, mode: 0o700 });
  const lock = new DatabaseSync(path.join(outputDir, '.dsh-cert-lock.sqlite'));
  try {
    try {
      lock.exec('PRAGMA busy_timeout=60000; BEGIN IMMEDIATE');
    } catch (cause) {
      throw new Error(`无法取得证书目录锁（最多等待 60 秒）：${outputDir}；请稍后重试，不要删除锁文件`, { cause });
    }
    processCertificates();
  } finally {
    lock.close();
  }
}
TLS_NODE
