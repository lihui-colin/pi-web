#!/usr/bin/env bash
# 按 dsh.conf 的 server_ip 生成 HTTPS 证书，保存在 tls/<地址>/。
# 不安装程序，不修改配置，不启停服务，不覆盖已有证书。
set -euo pipefail
umask 077
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
config_file="$script_dir/dsh.conf"
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
                '需要 Node.js >=24 和 OpenSSL。默认读取同目录 dsh.conf 的 server_ip。' \
                '证书保存在配置目录的 tls/<server_ip>/；IPv6 目录名中的冒号替换为下划线。' \
                '--tls-dir 指定保存根目录，仍会追加地址子目录；--tls-host 可重复添加 SAN。' \
                '只读取 server_ip；启动脚本从同目录 tls/<地址>/ 自动加载，不使用旧 tls_cert/tls_key。' \
                '已有证书校验后保留；--dry-run 不写入文件。' \
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
if (!fs.existsSync(config)) throw new Error(`缺少 DSH 配置：${config}。请先从 dsh.conf.example 复制并填写 server_ip。`);
const values = {};
for (const line of fs.readFileSync(config, 'utf8').split(/\r?\n/)) {
  const m = line.match(/^\s*(server_ip)\s*=\s*(.*?)\s*$/);
  if (!m) continue;
  const raw = m[2];
  const quoted = raw.match(/^(['"])(.*?)\1\s*(?:#.*)?$/);
  values[m[1]] = quoted ? quoted[2] : raw.replace(/\s+#.*$/, '').trim();
}
if (!values.server_ip) throw new Error('DSH 配置缺少 server_ip');
const hosts = [...new Set([values.server_ip, ...extraHosts])];
const san = hosts.map(host => {
  if (net.isIP(host)) return `IP:${host}`;
  if (host.length <= 253 && host.split('.').every(label => /^[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?$/.test(label))) return `DNS:${host}`;
  throw new Error(`无效的 IP 或域名：${host}，请勿包含协议、端口或路径`);
});
const base = path.dirname(config);
// Always namespace output by the address, even if legacy tls_cert/tls_key point elsewhere.
const addressDir = values.server_ip.toLowerCase().replaceAll(':', '_');
const outputDir = path.join(dirOverride ? path.resolve(dirOverride) : path.join(base, 'tls'), addressDir);
const cert = path.join(outputDir, 'fullchain.pem');
const key = path.join(outputDir, 'privkey.pem');
const caDir = path.dirname(cert);
const ca = path.join(caDir, 'ca.pem');
const caKey = path.join(caDir, 'ca-key.pem');
const caCrt = path.join(caDir, 'ca.crt');
if (new Set([cert, key, ca, caKey, caCrt]).size !== 5) throw new Error('证书、服务器私钥、CA 和 CA 私钥路径不能相同');
const openssl = args => execFileSync('openssl', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
function validatePair(certPath, keyPath) {
  const x = new crypto.X509Certificate(fs.readFileSync(certPath));
  const actual = crypto.createPublicKey(crypto.createPrivateKey(fs.readFileSync(keyPath))).export({ type: 'spki', format: 'der' });
  if (!x.publicKey.export({ type: 'spki', format: 'der' }).equals(actual)) throw new Error(`证书和私钥不匹配：${certPath}`);
  openssl(['x509', '-in', certPath, '-noout', '-checkend', '86400']);
  return x;
}
// Export only the public root certificate; preserve the server certificate and keys.
function exportRootCertificate() {
  if (!fs.existsSync(ca)) {
    console.log('未找到本地 ca.pem，未导出 ca.crt；外部签发证书请使用签发方提供的根证书。');
    return;
  }
  const root = new crypto.X509Certificate(fs.readFileSync(ca));
  if (!root.ca) throw new Error('ca.pem 不是 CA 证书，拒绝导出');
  openssl(['verify', '-CAfile', ca, cert]);
  if (fs.existsSync(caCrt)) {
    const existing = new crypto.X509Certificate(fs.readFileSync(caCrt));
    if (!existing.raw.equals(root.raw)) throw new Error('已有 ca.crt 与 ca.pem 不一致，请备份并检查后再处理');
  } else if (preview !== 'true') {
    fs.writeFileSync(caCrt, root.toString(), { flag: 'wx', mode: 0o644 });
  }
  console.log(`${preview === 'true' ? '预览：根证书导出路径' : '设备导入并信任的根证书'}：${caCrt}`);
}
console.log(`DSH 配置：${config}\n证书 SAN：${san.join(', ')}\nHTTPS 证书：${cert}\n服务器私钥：${key}`);
console.log('dsh_web_run.sh 启动时按 server_ip 从同目录 tls/<地址>/ 自动加载证书，不需要配置 tls_cert/tls_key。');
if (dirOverride && path.resolve(dirOverride) !== path.join(base, 'tls')) {
  console.log(`自定义输出目录仅用于导出；使用启动脚本前，请将 ${outputDir} 中的证书和私钥部署到 ${path.join(base, 'tls', addressDir)}。`);
}
if (fs.existsSync(cert) !== fs.existsSync(key)) throw new Error('已有证书/私钥不完整，停止处理；请先检查备份');
if (fs.existsSync(cert)) {
  const x = validatePair(cert, key);
  for (const host of hosts) {
    const match = net.isIP(host) ? x.checkIP(host) : x.checkHost(host, { subject: 'never' });
    if (!match) throw new Error(`已有证书未覆盖 ${host}；请备份后配置新的证书路径`);
  }
  console.log('已有证书有效、地址和私钥匹配，保留原文件。');
  exportRootCertificate();
  process.exit(0);
}
if (fs.existsSync(ca) !== fs.existsSync(caKey)) throw new Error('已有 CA 文件不完整，停止处理');
if (fs.existsSync(ca)) {
  const x = validatePair(ca, caKey);
  if (!x.ca) throw new Error('ca.pem 不是 CA 证书');
  // 服务器证书有效期为 365 天，CA 必须至少覆盖这一时间。
  openssl(['x509', '-in', ca, '-noout', '-checkend', String(366 * 86400)]);
}
if (preview === 'true') {
  console.log(`预览：将生成/复用本地 CA ${ca}，签发有效期 365 天的 HTTPS 证书并导出 ${caCrt}，不写入文件。`);
  process.exit(0);
}
for (const dir of new Set([caDir, path.dirname(key)])) fs.mkdirSync(dir, { recursive: true, mode: 0o700 });
const temp = fs.mkdtempSync(path.join(caDir, '.generate-'));
try {
  const tempCa = path.join(temp, 'ca.pem'), tempCaKey = path.join(temp, 'ca-key.pem');
  const reqConfig = path.join(temp, 'openssl.cnf');
  fs.writeFileSync(reqConfig, '[req]\ndistinguished_name=dn\n[dn]\n[v3_ca]\nbasicConstraints=critical,CA:TRUE\nkeyUsage=critical,keyCertSign,cRLSign\nsubjectKeyIdentifier=hash\nauthorityKeyIdentifier=keyid:always\n');
  if (!fs.existsSync(ca)) {
    openssl(['req', '-x509', '-newkey', 'rsa:3072', '-nodes', '-sha256', '-days', '3650',
      '-config', reqConfig, '-extensions', 'v3_ca', '-subj', `/CN=DSH Local HTTPS CA ${values.server_ip}`,
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
  if (!fs.existsSync(ca)) {
    fs.copyFileSync(tempCaKey, caKey, fs.constants.COPYFILE_EXCL);
    fs.copyFileSync(tempCa, ca, fs.constants.COPYFILE_EXCL);
  }
  fs.copyFileSync(tempKey, key, fs.constants.COPYFILE_EXCL);
  fs.writeFileSync(cert, fs.readFileSync(tempCert, 'utf8') + fs.readFileSync(signer, 'utf8'), { flag: 'wx', mode: 0o644 });
  fs.chmodSync(key, 0o600);
  fs.chmodSync(caKey, 0o600);
  exportRootCertificate();
  console.log(`HTTPS 证书已生成。请在访问设备上导入并信任根证书：${caCrt}`);
  console.log('不要分发 ca-key.pem 或 privkey.pem；iOS 安装描述文件后还需启用根证书完全信任。');
} finally {
  if (path.dirname(temp) !== caDir || !path.basename(temp).startsWith('.generate-')) throw new Error('拒绝清理意外的临时路径');
  fs.rmSync(temp, { recursive: true, force: true });
}
TLS_NODE
