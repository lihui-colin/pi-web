#!/usr/bin/env bash
# 安装当前团队使用的 DSH 与插件，DSH、pnpm 与插件按 srcs/install-versions.json 固定版本安装。
# 适用于 Linux/macOS；需要 Node.js >=24、npm、curl 和 sh。
# 用法：bash ds-harness/dsh_install.sh [--dry-run] [--upgrade]
# HTTPS 证书由dsh_cert.sh 单独生成。
# 数据固定放在脚本同级 data/.dsh，共享 agent 配置放在 data/.agents。
# 不启动/停止服务，不迁移 DSH 会话数据，不写入 API Key。
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"

dry_run=false
upgrade=false
while (( $# )); do
    case "$1" in
        --dry-run) dry_run=true; shift ;;
        --upgrade) upgrade=true; shift ;;
        -h|--help)
            printf '%s\n' \
                '用法：bash ds-harness/dsh_install.sh [--dry-run] [--upgrade]' \
                '前置：Node.js >=24、npm、curl、sh，npm 全局目录需要当前用户可写。' \
                '默认按固定版本安装；--upgrade 查询最新版本、更新版本清单并升级 DSH、pnpm、Magpie 和插件。' \
                'Nginx 及静态依赖安装到本目录 data/.local/nginx；首次构建需要 cc、make、perl、tar、Python 3。' \
                'Linux 缺少 xdg-open 时安装系统包 xdg-utils（非 root 使用 sudo）；macOS 使用系统 open。' \
                '不使用系统 Nginx；已有本地 Nginx 只检查版本 >=1.24 和 HTTP SSL 模块。' \
                'DSH、pnpm 与插件使用 srcs/install-versions.json 的固定版本；保留已有额外插件启用状态，新 profile 默认启用九个。' \
                '安装结束时创建 data/dsh.conf：已有配置保留，否则从控制台输入 IP 和端口。' \
                'HTTPS 证书请单独运行 bash ds-harness/dsh_cert.sh 创建。' \
                '数据固定放在脚本同级 data/.dsh，共享 agent 配置放在 data/.agents。' \
                'Magpie 安装最多尝试 3 次；支持 MAGPIE_PROXY 代理及 MAGPIE_MIRROR 镜像前缀。' \
                '请在新机器或目标 DSH 已停机时安装；本脚本不启停服务。' \
                '用户数据、模型配置、API Key、magpie 账号需要单独恢复。'
            exit 0 ;;
        *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
    esac
done

for bin in node npm curl sh; do
    if ! command -v "$bin" >/dev/null 2>&1; then
        printf '缺少命令：%s。请先安装前置依赖。\n' "$bin" >&2
        exit 1
    fi
done
node -e 'if (Number(process.versions.node.split(".")[0]) < 24) { console.error("需要 Node.js >=24"); process.exit(1); }'

if ! "$dry_run"; then
    command -v python3 >/dev/null 2>&1 || { printf '缺少命令：python3（用于 DSH 兼容补丁）。\n' >&2; exit 1; }
    bash "$script_dir/dsh_patches_install.sh" --validate-tools
fi
if "$upgrade" && ! "$dry_run"; then
    node "$script_dir/srcs/update-install-versions.mjs" "$script_dir/srcs/install-versions.json"
    export DSH_UPGRADE_PINS_RESOLVED=1
elif "$upgrade"; then
    printf '%s\n' '预览：实际 --upgrade 会查询最新版本并更新清单；以下命令使用当前清单，不联网或写入。'
fi
export DSH_HOME="$script_dir/data/.dsh"
export DSH_AGENTS_HOME="$script_dir/data/.agents"
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

ensure_xdg_open() {
    [[ "$(uname -s)" == Linux ]] || return 0
    if command -v xdg-open >/dev/null 2>&1; then
        printf '%s\n' '已存在 xdg-open，跳过安装。'
        return 0
    fi
    local -a privilege=() package_command=()
    if (( EUID != 0 )); then
        if ! command -v sudo >/dev/null 2>&1; then
            printf '%s\n' '缺少 xdg-open；请由管理员安装 xdg-utils 后重试（当前无 sudo）。' >&2
            return 1
        fi
        privilege=(sudo)
    fi
    if command -v apt-get >/dev/null 2>&1; then
        package_command=(apt-get install -y --no-install-recommends xdg-utils)
    elif command -v dnf >/dev/null 2>&1; then
        package_command=(dnf install -y xdg-utils)
    elif command -v yum >/dev/null 2>&1; then
        package_command=(yum install -y xdg-utils)
    else
        printf '%s\n' '缺少 xdg-open；请使用系统包管理器安装 xdg-utils 后重试。' >&2
        return 1
    fi
    run "${privilege[@]}" "${package_command[@]}"
    if ! "$dry_run" && ! command -v xdg-open >/dev/null 2>&1; then
        printf '%s\n' 'xdg-utils 安装后仍找不到 xdg-open，请检查 PATH。' >&2
        return 1
    fi
}

ensure_xdg_open

# 保留官方安装器的平台选择和 SHA-256 校验；重试覆盖其内部二进制下载。
install_magpie() (
    local installer_dir attempt
    installer_dir="$(mktemp -d)" || exit 1
    trap 'rm -rf -- "$installer_dir"' EXIT
    local curl_args=(-fsSL --connect-timeout 15 --max-time 120)
    if [[ -n "${MAGPIE_PROXY:-}" ]]; then
        curl_args+=(--proxy "$MAGPIE_PROXY")
    fi
    for attempt in 1 2 3; do
        printf 'Magpie 安装尝试 %s/3。\n' "$attempt"
        # 不使用管道：只有完整下载成功后才执行，失败的下载不能当作脚本运行。
        if curl "${curl_args[@]}" https://usemagpie.ai/install.sh -o "$installer_dir/install.sh" &&
            sh "$installer_dir/install.sh"; then
            exit 0
        fi
        if (( attempt < 3 )); then
            printf 'Magpie 安装失败，3 秒后重试。\n' >&2
            sleep 3
        fi
    done
    printf '%s\n' \
        'Magpie 安装失败，停止后续插件安装。' \
        '若官网或 GitHub 连接失败，请先恢复 DNS/网络，或设置 MAGPIE_PROXY（服务器可访问的代理地址）后重跑。' \
        'MAGPIE_MIRROR 仅用于 GitHub 二进制下载；安装脚本、版本信息和校验值仍需访问 usemagpie.ai。' \
        '这两个变量由官方安装器支持；镜像下载仍使用官方 SHA-256 校验。' >&2
    exit 1
)

# 本地依赖安装器不使用 PATH 中的系统 Nginx。
if "$dry_run"; then
    bash "$script_dir/dsh_nginx_install.sh" --dry-run
else
    bash "$script_dir/dsh_nginx_install.sh"
fi

printf '目标数据目录：%s\n' "$DSH_HOME"
printf '%s\n' 'DSH、pnpm 与插件使用 srcs/install-versions.json 的固定版本；不会启动或重启服务。'
version_pins="$(node --input-type=module - "$script_dir/srcs/install-versions.json" <<'PINS_NODE'
import fs from 'node:fs';
const pins = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
for (const name of ['dsh', 'pnpm']) {
  if (!/^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$/.test(pins[name])) throw new Error(`Invalid pinned version: ${name}`);
}
console.log(pins.dsh, pins.pnpm);
PINS_NODE
)"
read -r dsh_pin pnpm_pin <<< "$version_pins"
npm_packages=()
dsh_will_install=false
for bin in dsh pnpm; do
    target_version="$pnpm_pin"
    if [[ "$bin" == dsh ]]; then target_version="$dsh_pin"; fi
    current_version=''
    if command -v "$bin" >/dev/null 2>&1; then current_version="$("$bin" --version)"; fi
    if [[ "$current_version" != "$target_version" ]]; then
        package="$bin"
        if [[ "$bin" == dsh ]]; then
            package='@deepseek-ai/dsh'
            dsh_will_install=true
        fi
        npm_packages+=("$package@$target_version")
    else
        printf '已存在 %s，跳过安装。\n' "$bin"
    fi
done
if (( ${#npm_packages[@]} )); then
    run npm install --global --allow-scripts=pnpm,@deepseek-ai/dsh-subprocess-local,koffi,node-pty "${npm_packages[@]}"
fi
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
if ! "$upgrade" && command -v magpie >/dev/null 2>&1; then
    printf '%s\n' '已存在 magpie，跳过安装。'
else
    printf '%s\n' '+ curl 下载官方 Magpie 安装器后执行（最多尝试 3 次）'
    if ! "$dry_run"; then
        install_magpie
        if ! command -v magpie >/dev/null 2>&1; then
            printf 'magpie 安装后不在 PATH 中，请按官方安装器提示配置 PATH。\n' >&2
            exit 1
        fi
    fi
fi

# 额外插件由独立安装器维护；dry-run 不能把旧版本当作升级后的版本。
plugin_args=()
if "$dry_run"; then
    plugin_args+=(--dry-run)
    if "$dsh_will_install"; then
        plugin_args+=(--expected-dsh-version "$dsh_pin")
    fi
fi
if "$upgrade"; then plugin_args+=(--upgrade); fi
bash "$script_dir/dsh_plugins_install.sh" "${plugin_args[@]}"

# 官方实验功能随 DSH 分发，不另行固定旧版依赖。
# 补齐内置 bundle，并保留额外插件启用状态及其他已有 bundle 配置。
run node --input-type=module - "$profile_dir/package.json" <<'NODE'
import fs from 'node:fs';
import { dirname, join } from 'node:path';
const path = process.argv[2];
const pkg = JSON.parse(fs.readFileSync(path, 'utf8'));
const expected = [
  '@deepseek-ai/dsh-base',
  '@deepseek-ai/dsh-web-app',
  '@deepseek-ai/dsh-experimental-plugin-market-bundle',
  '@deepseek-ai/dsh-experimental-terminal-bundle',
  '@deepseek-ai/dsh-experimental-tool-worktree',
  '@deepseek-ai/dsh-experimental-agent-team-profile',
  '@deepseek-ai/dsh-experimental-voice-input-bundle',
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

// Stats is a shipped client plugin, not a bundle selected by dsh-web-app.
// Insert it into the user patch layer; preserve explicit existing choices.
const patchPath = join(dirname(path), 'cordis.patch.yml');
const patch = fs.existsSync(patchPath) ? fs.readFileSync(patchPath, 'utf8') : '';
const hasStats = /^\s*(?:-\s*)?(?:id:\s*['"]?ui-stats['"]?\s*(?:#.*)?$|name:\s*['"]?@deepseek-ai\/dsh-experimental-client-ui-stats['"]?\s*(?:#.*)?$)/m.test(patch);
if (!hasStats) {
  const content = patch.replace(/^\s*\[\]\s*(?:#.*)?$/m, '').trimEnd();
  const tempPatch = `${patchPath}.dsh-install.${process.pid}.tmp`;
  fs.writeFileSync(tempPatch, `${content}${content ? '\n' : ''}- insert:\n    - id: ui-stats\n      name: '@deepseek-ai/dsh-experimental-client-ui-stats'\n`, {
    mode: fs.existsSync(patchPath) ? fs.statSync(patchPath).mode & 0o777 : 0o600,
  });
  fs.renameSync(tempPatch, patchPath);
  console.log('已启用主聊天统计页签');
}
NODE

ensure_config() {
    local config="$script_dir/data/dsh.conf" address='' listen_port=''
    if [[ -f "$config" ]]; then
        printf '保留已有配置：%s\n' "$config"
        return
    fi
    if [[ -e "$config" || -L "$config" ]]; then
        printf '配置路径不是普通文件：%s\n' "$config" >&2
        return 1
    fi
    # Preserve old deployments without sourcing configuration as shell code.
    if [[ ! -f "$script_dir/dsh.conf" ]]; then
        while true; do
            printf '请输入浏览器访问的服务器 IP（IPv4 或 IPv6）：' >&2
            IFS= read -r address || { printf '\n未读取到 IP，未创建配置；请交互运行安装器。\n' >&2; return 1; }
            address="$(node -p 'process.argv[1].trim()' -- "$address")"
            [[ -n "$address" ]] || continue
            if node -e 'process.exit(require("node:net").isIP(process.argv[1]) ? 0 : 1)' -- "$address"; then break; fi
            printf 'IP 格式无效，请重新输入，不要包含协议或端口。\n' >&2
        done
        while true; do
            printf '请输入 HTTPS 端口 [25228]：' >&2
            IFS= read -r listen_port || { printf '\n未读取到端口，未创建配置。\n' >&2; return 1; }
            listen_port="$(node -p 'process.argv[1].trim()' -- "$listen_port")"
            listen_port="${listen_port:-25228}"
            if [[ "$listen_port" =~ ^[0-9]{1,5}$ ]] && (( 10#$listen_port >= 1 && 10#$listen_port <= 65535 )); then break; fi
            printf '端口必须是 1–65535 之间的整数，请重新输入。\n' >&2
        done
    fi
    node - "$config" "$script_dir/dsh.conf" "$address" "$listen_port" <<'CONFIG_WRITE'
const fs = require('node:fs'), path = require('node:path');
const [target, legacy, address, port] = process.argv.slice(2);
fs.mkdirSync(path.dirname(target), { recursive: true, mode: 0o700 });
const content = address
  ? `server_ip='${address}'\nport=${Number(port)}\nhost_ip='${address}'\nmagpie_port=25226\nmagpie_web_port=3430\ndsh_token=''\n`
  : fs.readFileSync(legacy);
fs.writeFileSync(target, content, { flag: 'wx', mode: 0o600 });
console.log(`${address ? '已创建配置' : '已保留旧配置副本'}：${target}`);
CONFIG_WRITE
}

if "$dry_run"; then
    printf '%s\n' '预览：安装结束后保留 data/dsh.conf；若不存在则复制旧配置或提示输入 IP 和端口，不在预览时读取输入。'
    printf '%s\n' '预览完成：node 步骤将补齐七个内置 bundle，额外插件由独立安装器维护；未安装程序或修改文件。'
else
    for bin in dsh pnpm magpie; do run "$bin" --version; done
    ensure_config
    printf '%s\n' \
        '安装完成，未启动或重启任何服务。' \
        '请另外恢复 DSH 用户数据、模型配置、magpie 账号与密钥、共享 Skills 和项目文件。' \
        'magpie 支持 magpie backup / magpie restore 迁移加密备份。' \
        'HTTPS 证书请另行运行 bash ds-harness/dsh_cert.sh，启动时按 server_ip 自动选择 data/tls/<地址>/。' \
        '配置完成后可运行 magpie serve，并使用项目 HTTPS 启动脚本启动 DSH。' \
        '直接启动 dsh web 时，请传 --tls-cert <配置的证书路径> --tls-key <配置的私钥路径>。' \
        '客户端需信任本地 CA；网页语音还需要麦克风权限及语音服务配置。' \
        '最新插件可能对 DSH/Node 版本有更高要求；以安装时兼容性检查为准。'
fi
