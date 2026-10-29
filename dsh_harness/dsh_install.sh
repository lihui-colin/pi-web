#!/usr/bin/env bash
# 安装当前团队使用的 DSH 与插件，全部使用执行时的最新发布版本。
# 适用于 Linux/macOS；需要 Node.js >=24、OpenSSL、npm、curl 和 sh。
# 当前机器参考：Node.js v26.7.0；不负责自动安装 Node.js。
# 用法：bash dsh_harness/dsh_install.sh [--dry-run] [--cert-only] [--config 配置文件]
# HTTPS 地址与证书路径默认读取 ../ds-harness/dsh.conf。
# 可设置 DSH_HOME 指定数据目录，默认 $HOME/.dsh。
# 不启动/停止服务，不迁移用户数据，不写入 API Key。
set -euo pipefail

dry_run=false
cert_only=false
script_dir="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
config_file="$script_dir/../ds-harness/dsh.conf"
tls_dir=''
tls_hosts=()
while (( $# )); do
    case "$1" in
        --dry-run) dry_run=true; shift ;;
        --cert-only) cert_only=true; shift ;;
        --tls-host|--tls-dir|--config)
            option="$1"
            if (( $# < 2 )) || [[ -z "$2" || "$2" == --* ]]; then
                printf '%s 需要一个值。\n' "$option" >&2; exit 2
            fi
            case "$option" in
                --tls-host) tls_hosts+=("$2") ;;
                --tls-dir) tls_dir="$2" ;;
                --config) config_file="$2" ;;
            esac
            shift 2 ;;
        -h|--help)
            printf '%s\n' \
                '用法：bash dsh_harness/dsh_install.sh [--dry-run] [--cert-only] [--config 文件] [--tls-host IP或域名] [--tls-dir 目录]' \
                '前置：Node.js >=24、OpenSSL；完整安装还需 npm、curl、sh，npm 全局目录需要当前用户可写。' \
                '安装/更新 DSH、pnpm、5 个额外插件，以及官方 magpie。' \
                '全部使用执行时的最新版本，启用当前 web profile 的 12 个 bundle。' \
                '自动读取 DSH 配置的 server_ip、tls_cert、tls_key；--config 可指定配置文件。' \
                '默认配置为脚本上级 ds-harness/dsh.conf，证书相对路径以配置目录为基准。' \
                '--tls-host 可重复添加额外 SAN；--tls-dir 可覆盖证书目录，需同步调整服务配置。' \
                '已有证书会校验并保留；--cert-only 只处理证书，--dry-run 不写入文件。' \
                '局域网客户端需信任生成的 ca.pem；只导入根证书，不复制 CA 私钥。' \
                'DSH_HOME 可指定目标数据目录，默认 ~/.dsh。' \
                '请在新机器或目标 DSH 已停机时安装；本脚本不启停服务。' \
                '用户数据、模型配置、API Key、magpie 账号需要单独恢复。'
            exit 0 ;;
        *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
    esac
done

required_bins=(node openssl)
if ! "$cert_only"; then required_bins+=(npm curl sh); fi
for bin in "${required_bins[@]}"; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        printf '缺少命令：%s。请先安装前置依赖。\n' "$bin" >&2
        exit 1
    fi
done
node -e 'if (Number(process.versions.node.split(".")[0]) < 24) { console.error("需要 Node.js >=24"); process.exit(1); }'
export DSH_HOME="${DSH_HOME:-${HOME:?}/.dsh}"
DSH_HOME="$(node -e 'const p=require("node:path"),o=require("node:os"); let s=process.env.DSH_HOME; if(s==="~")s=o.homedir(); else if(s.startsWith("~/"))s=p.join(o.homedir(),s.slice(2)); console.log(p.resolve(s));')"
export DSH_HOME
# magpie 官方安装器默认把 CLI 放在 ~/.local/bin。
export PATH="${HOME:?}/.local/bin:$PATH"
profile_dir="$DSH_HOME/profiles/web"

run() {
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    if ! "$dry_run"; then
        "$@"
    fi
}

# 先校验配置/证书，再安装软件，避免因配置错误先更新运行环境。
# 只解析需要的键，不 source 配置，避免执行配置中的 shell 内容。
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
  const m = line.match(/^\s*(server_ip|tls_cert|tls_key)\s*=\s*(.*?)\s*$/);
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
const cert = dirOverride ? path.resolve(dirOverride, 'fullchain.pem') : path.resolve(base, values.tls_cert || 'tls/fullchain.pem');
const key = dirOverride ? path.resolve(dirOverride, 'privkey.pem') : path.resolve(base, values.tls_key || 'tls/privkey.pem');
const caDir = path.dirname(cert);
const ca = path.join(caDir, 'ca.pem');
const caKey = path.join(caDir, 'ca-key.pem');
if (new Set([cert, key, ca, caKey]).size !== 4) throw new Error('证书、服务器私钥、CA 和 CA 私钥路径不能相同');
const openssl = args => execFileSync('openssl', args, { encoding: 'utf8', stdio: ['ignore', 'pipe', 'pipe'] });
function validatePair(certPath, keyPath) {
  const x = new crypto.X509Certificate(fs.readFileSync(certPath));
  const actual = crypto.createPublicKey(crypto.createPrivateKey(fs.readFileSync(keyPath))).export({ type: 'spki', format: 'der' });
  if (!x.publicKey.export({ type: 'spki', format: 'der' }).equals(actual)) throw new Error(`证书和私钥不匹配：${certPath}`);
  openssl(['x509', '-in', certPath, '-noout', '-checkend', '86400']);
  return x;
}
console.log(`DSH 配置：${config}\n证书 SAN：${san.join(', ')}\nHTTPS 证书：${cert}\n服务器私钥：${key}`);
if (fs.existsSync(cert) !== fs.existsSync(key)) throw new Error('已有证书/私钥不完整，停止处理；请先检查备份');
if (fs.existsSync(cert)) {
  const x = validatePair(cert, key);
  for (const host of hosts) {
    const match = net.isIP(host) ? x.checkIP(host) : x.checkHost(host, { subject: 'never' });
    if (!match) throw new Error(`已有证书未覆盖 ${host}；请备份后配置新的证书路径`);
  }
  console.log('已有证书有效、地址和私钥匹配，保留原文件。');
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
  console.log(`预览：将生成/复用本地 CA ${ca}，签发有效期 365 天的 HTTPS 证书，不写入文件。`);
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
      '-config', reqConfig, '-extensions', 'v3_ca', '-subj', '/CN=DSH Local HTTPS CA',
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
  console.log(`HTTPS 证书已生成。请在访问设备上导入并信任根证书：${ca}`);
  console.log('不要分发 ca-key.pem 或 privkey.pem；iOS 安装描述文件后还需启用根证书完全信任。');
} finally {
  if (path.dirname(temp) !== caDir || !path.basename(temp).startsWith('.generate-')) throw new Error('拒绝清理意外的临时路径');
  fs.rmSync(temp, { recursive: true, force: true });
}
TLS_NODE
if "$cert_only"; then exit 0; fi

printf '目标数据目录：%s\n' "$DSH_HOME"
printf '%s\n' '将安装执行时的最新版本；不会启动或重启服务。'
run npm install --global '@deepseek-ai/dsh@latest' 'pnpm@latest'
if ! "$dry_run"; then
    for bin in dsh pnpm; do
        if ! command -v "$bin" >/dev/null 2>&1; then
            printf '找不到 %s，请将 npm 全局 bin 目录加入 PATH 后重试。\n' "$bin" >&2
            exit 1
        fi
    done
fi

# 官方安装来源：https://github.com/yetone/magpie#quick-start
# 安装/更新程序，不运行 magpie serve，也不安装常驻服务。
printf '%s\n' '+ curl -fsSL https://usemagpie.ai/install.sh | sh'
if ! "$dry_run"; then
    curl -fsSL --connect-timeout 15 --max-time 120 https://usemagpie.ai/install.sh | sh
    if ! command -v magpie >/dev/null 2>&1; then
        printf 'magpie 安装后不在 PATH 中，请按官方安装器提示配置 PATH。\n' >&2
        exit 1
    fi
fi

# dsh plugin 会初始化 web profile，并更新包清单及锁文件。
# 先备份已有包清单；完整的会话、配置和密钥仍需另行备份。
if [[ -f "$profile_dir/package.json" ]]; then
    backup="$profile_dir/package.json.before-dsh-install.$(date +%Y%m%dT%H%M%S).$$"
    run cp -p -- "$profile_dir/package.json" "$backup"
fi
run dsh plugin --profile web add -w --save-exact \
    '@deepseek-ai/dsh-subagent-codex@latest' \
    'ds-bot@latest' \
    'dsh-web-mobile@latest' \
    'dshmarket@latest' \
    'dsh-ide-git@latest'

# 官方实验功能随 DSH 分发，不另行固定旧版依赖。
# 恢复本机 bundle 顺序，并保留目标 profile 中其他已有 bundle。
run node --input-type=module - "$profile_dir/package.json" <<'NODE'
import fs from 'node:fs';
const path = process.argv[2];
const pkg = JSON.parse(fs.readFileSync(path, 'utf8'));
const expected = [
  '@deepseek-ai/dsh-base',
  '@deepseek-ai/dsh-web-app',
  '@deepseek-ai/dsh-experimental-plugin-market-bundle',
  '@deepseek-ai/dsh-subagent-codex',
  '@deepseek-ai/dsh-experimental-terminal-bundle',
  '@deepseek-ai/dsh-experimental-tool-worktree',
  '@deepseek-ai/dsh-experimental-agent-team-profile',
  'dsh-web-mobile',
  'dshmarket',
  'ds-bot',
  '@deepseek-ai/dsh-experimental-voice-input-bundle',
  'dsh-ide-git',
];
pkg.dsh ??= {};
pkg.dsh.profile ??= {};
const existing = pkg.dsh.profile.bundles ?? [];
if (!Array.isArray(existing)) throw new Error('现有 bundles 不是数组，停止修改');
pkg.dsh.profile.bundles = [...new Set([...expected, ...existing])];
const temp = `${path}.dsh-install.${process.pid}.tmp`;
fs.writeFileSync(temp, `${JSON.stringify(pkg, null, 2)}\n`, { mode: fs.statSync(path).mode & 0o777 });
fs.renameSync(temp, path);
console.log('已配置 bundle：\n' + pkg.dsh.profile.bundles.join('\n'));
console.log('插件实际安装版本：\n' + JSON.stringify(pkg.dependencies, null, 2));
NODE

if "$dry_run"; then
    printf '%s\n' '预览完成：node 步骤将配置 12 个 bundle；未安装程序或修改文件。'
else
    run dsh --version
    run pnpm --version
    run magpie --version
    printf '%s\n' \
        '安装完成，未启动或重启任何服务。' \
        '请另外恢复 DSH 用户数据、模型配置、magpie 账号与密钥、共享 Skills 和项目文件。' \
        'magpie 支持 magpie backup / magpie restore 迁移加密备份。' \
        '配置完成后可运行 magpie serve，并使用项目 HTTPS 启动脚本启动 DSH。' \
        '直接启动 dsh web 时，请传 --tls-cert <配置的证书路径> --tls-key <配置的私钥路径>。' \
        '客户端需信任本地 CA；网页语音还需要麦克风权限及语音服务配置。' \
        '最新插件可能对 DSH/Node 版本有更高要求；以安装时兼容性检查为准。'
fi
