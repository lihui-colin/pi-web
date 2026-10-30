#!/usr/bin/env bash
# 安装当前团队使用的 DSH 与插件，DSH/第三方插件使用 latest，官方 Codex 插件与 DSH 同版。
# 适用于 Linux/macOS；需要 Node.js >=24、npm、curl 和 sh。
# 用法：bash ds-harness/dsh_install.sh [--dry-run] [--upgrade]
# HTTPS 证书由同目录 dsh_cert.sh 单独生成。
# 可设置 DSH_HOME 指定数据目录，默认 $HOME/.dsh。
# 不启动/停止服务，不迁移用户数据，不写入 API Key。
set -euo pipefail

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
                '默认补装缺失程序和插件；--upgrade 更新 DSH、pnpm、Magpie 和插件。' \
                '缺少 Nginx 时通过 Debian/Ubuntu apt 或 macOS Homebrew 安装；已有 Nginx 只检查版本 >=1.24 和 HTTP SSL 模块。' \
                'DSH/第三方插件使用 latest，官方 Codex 插件与 DSH 同版，启用 14 个 bundle。' \
                'HTTPS 证书请单独运行 bash ds-harness/dsh_cert.sh 创建；本安装器不读取 dsh.conf。' \
                'DSH_HOME 可指定目标数据目录，默认 ~/.dsh。' \
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
export DSH_HOME="${DSH_HOME:-${HOME:?}/.dsh}"
DSH_HOME="$(node -e 'const p=require("node:path"),o=require("node:os"); let s=process.env.DSH_HOME; if(s==="~")s=o.homedir(); else if(s.startsWith("~/"))s=p.join(o.homedir(),s.slice(2)); console.log(p.resolve(s));')"
# magpie 使用 ~/.local/bin；发行版 Nginx 通常位于 /usr/sbin。
export PATH="${HOME:?}/.local/bin:$PATH:/usr/sbin:/sbin"
profile_dir="$DSH_HOME/profiles/web"

run() {
    printf '+'
    printf ' %q' "$@"
    printf '\n'
    if ! "$dry_run"; then
        "$@"
    fi
}

# 只补装缺失的 Nginx；已有实例不随 --upgrade 更新。
ensure_nginx() {
    local details major minor
    local -a privileged=()
    if ! command -v nginx >/dev/null 2>&1; then
        case "$(uname -s)" in
            Linux)
                command -v apt-get >/dev/null 2>&1 || {
                    printf '%s\n' '缺少 Nginx；自动安装支持 Debian/Ubuntu apt 和 macOS Homebrew，请先安装 Nginx >=1.24（含 HTTP SSL 模块）。' >&2
                    return 1
                }
                if (( EUID != 0 )); then privileged=(sudo); fi
                if "$dry_run"; then
                    printf '%s\n' '将临时禁止 Nginx 包自动启停服务，并跳过 needrestart 钩子。'
                    run "${privileged[@]}" apt-get update
                    run "${privileged[@]}" env DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1 apt-get install -y --no-install-recommends nginx
                    return
                fi
                if (( ${#privileged[@]} )) && ! command -v sudo >/dev/null 2>&1; then
                    printf '%s\n' '安装 Nginx 需要 root 或 sudo；请由管理员安装后重跑。' >&2
                    return 1
                fi
                run "${privileged[@]}" sh -s -- /usr/sbin/policy-rc.d <<'NGINX_APT'
set -eu
policy="$1"
temporary=
cleanup() {
    if [ -n "$temporary" ]; then
        # Only unlink the exact policy inode published by this invocation.
        if [ "$policy" -ef "$temporary" ]; then rm -- "$policy"; fi
        rm -f -- "$temporary"
    fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
if [ ! -e "$policy" ] && [ ! -L "$policy" ]; then
    temporary="$(mktemp "${policy%/*}/.dsh-policy-rc.d.XXXXXX")"
    printf '#!/bin/sh\nexit 101\n' >"$temporary"
    chmod 755 "$temporary"
    # Atomic no-clobber publication; an existing policy is never replaced.
    ln -T -- "$temporary" "$policy"
fi
for service in nginx nginx.service; do
    for action in start stop restart reload upgrade try-restart force-reload '(start)' '(restart)' '(try-restart)'; do
        for level in '' 1 2 3 4 5 S; do
            set -- "$service" "$action"
            if [ -n "$level" ]; then set -- "$@" "$level"; fi
            result=0
            "$policy" "$@" >/dev/null 2>&1 || result=$?
            if [ "$result" -ne 101 ]; then
                printf '%s\n' '现有 policy-rc.d 未禁止 Nginx 启停，自动安装已停止；请由管理员处理该策略或预装 Nginx。' >&2
                exit 1
            fi
        done
    done
done
export DEBIAN_FRONTEND=noninteractive NEEDRESTART_SUSPEND=1
apt-get update
apt-get install -y --no-install-recommends nginx
NGINX_APT
                ;;
            Darwin)
                command -v brew >/dev/null 2>&1 || {
                    printf '%s\n' '缺少 Homebrew，请先安装 Homebrew 或 Nginx >=1.24。' >&2
                    return 1
                }
                run brew install nginx
                if "$dry_run"; then return; fi
                ;;
            *)
                printf '%s\n' '当前平台不支持自动安装 Nginx，请先安装 Nginx >=1.24。' >&2
                return 1 ;;
        esac
    fi
    command -v nginx >/dev/null 2>&1 || {
        printf '%s\n' '安装后仍找不到 nginx，请检查安装结果及 PATH。' >&2
        return 1
    }
    details="$(nginx -V 2>&1)" || return 1
    if [[ ! "$details" =~ nginx/([0-9]+)\.([0-9]+)\.[0-9]+ ]]; then
        printf '%s\n' '无法识别 Nginx 版本，停止安装。' >&2
        return 1
    fi
    major="${BASH_REMATCH[1]}"; minor="${BASH_REMATCH[2]}"
    if ! (( major > 1 || (major == 1 && minor >= 24) )); then
        printf '%s\n' '需要 Nginx >=1.24；现有版本未自动升级，请安排升级后重跑。' >&2
        return 1
    fi
    if [[ "$details" != *--with-http_ssl_module* ]]; then
        printf '%s\n' 'Nginx 缺少 HTTP SSL 模块，请安装支持 HTTPS 的构建。' >&2
        return 1
    fi
    printf '%s\n' 'Nginx 版本及 HTTP SSL 模块检查通过，复用现有安装。'
}

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

ensure_nginx

printf '目标数据目录：%s\n' "$DSH_HOME"
printf '%s\n' 'DSH/第三方插件使用 latest，官方 Codex 插件与 DSH 同版；不会启动或重启服务。'
npm_packages=()
dsh_will_install=false
for bin in dsh pnpm; do
    if "$upgrade" || ! command -v "$bin" >/dev/null 2>&1; then
        package="$bin"
        if [[ "$bin" == dsh ]]; then
            package='@deepseek-ai/dsh'
            dsh_will_install=true
        fi
        npm_packages+=("$package@latest")
    else
        printf '已存在 %s，跳过安装。\n' "$bin"
    fi
done
if (( ${#npm_packages[@]} )); then
    run npm install --global "${npm_packages[@]}"
fi
if ! "$dry_run"; then
    for bin in dsh pnpm; do
        if ! command -v "$bin" >/dev/null 2>&1; then
            printf '找不到 %s，请将 npm 全局 bin 目录加入 PATH 后重试。\n' "$bin" >&2
            exit 1
        fi
    done
fi

# 官方插件的 latest 标签可能滞后于运行时；使用实际安装的 DSH 版本。
# dry-run 不执行安装，不能把当前机器的旧版本当作安装后的版本。
if "$dry_run" && "$dsh_will_install"; then
    dsh_version='<安装后的 DSH 版本>'
else
    dsh_version="$(dsh --version)"
    if [[ ! "$dsh_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]; then
        printf '无法识别 DSH 版本：%s，停止安装插件。\n' "$dsh_version" >&2
        exit 1
    fi
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

# 同时检查 profile 声明和实际包文件，避免把未完成的安装当作已安装。
# 官方 Codex 插件版本不匹配时仍需对齐；由上游执行最终兼容性检查。
plugin_plan="$(node --input-type=module - "$profile_dir" "$dsh_version" "$upgrade" <<'PLAN_NODE'
import fs from 'node:fs';
import path from 'node:path';
const [dir, version, upgrade] = process.argv.slice(2);
const manifest = path.join(dir, 'package.json');
const pkg = fs.existsSync(manifest) ? JSON.parse(fs.readFileSync(manifest, 'utf8')) : {};
const names = ['@deepseek-ai/dsh-subagent-codex', 'ds-bot', 'dsh-web-mobile', 'dshmarket', 'dsh-ide-git', 'dsh-sidebar-enhancement', 'dsh-sidebar-plus'];
for (const name of names) {
  const target = name === names[0] ? version : 'latest';
  const installedPath = path.join(dir, 'node_modules', name, 'package.json');
  let installed;
  if (fs.existsSync(installedPath)) installed = JSON.parse(fs.readFileSync(installedPath, 'utf8'));
  const declared = pkg.dependencies?.[name] || pkg.devDependencies?.[name] || pkg.optionalDependencies?.[name];
  if (upgrade !== 'true' && declared && installed?.name === name && installed.version &&
      (name !== names[0] || installed.version === version)) {
    console.error(`已安装 ${name}@${installed.version}，跳过安装。`);
  } else {
    console.log(`${name}@${target}`);
  }
}
PLAN_NODE
)"
plugins=()
while IFS= read -r plugin; do
    if [[ -n "$plugin" ]]; then plugins+=("$plugin"); fi
done <<< "$plugin_plan"

# dsh plugin 会初始化 web profile，并更新包清单及锁文件。
# 先备份已有包清单；完整的会话、配置和密钥仍需另行备份。
if [[ -f "$profile_dir/package.json" ]]; then
    backup="$profile_dir/package.json.before-dsh-install.$(date +%Y%m%dT%H%M%S).$$"
    run cp -p -- "$profile_dir/package.json" "$backup"
fi
if (( ${#plugins[@]} )); then
    run dsh plugin --profile web add -w --save-exact "${plugins[@]}"
else
    printf '%s\n' '所需插件均已安装，跳过插件安装。'
fi

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
  'dsh-sidebar-enhancement',
  'dsh-sidebar-plus',
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
    printf '%s\n' '预览完成：node 步骤将配置 14 个 bundle；未安装程序或修改文件。'
else
    for bin in dsh pnpm magpie; do run "$bin" --version; done
    printf '%s\n' \
        '安装完成，未启动或重启任何服务。' \
        '请另外恢复 DSH 用户数据、模型配置、magpie 账号与密钥、共享 Skills 和项目文件。' \
        'magpie 支持 magpie backup / magpie restore 迁移加密备份。' \
        'HTTPS 证书请另行运行 bash ds-harness/dsh_cert.sh，启动时按 server_ip 自动选择 tls/<地址>/。' \
        '配置完成后可运行 magpie serve，并使用项目 HTTPS 启动脚本启动 DSH。' \
        '直接启动 dsh web 时，请传 --tls-cert <配置的证书路径> --tls-key <配置的私钥路径>。' \
        '客户端需信任本地 CA；网页语音还需要麦克风权限及语音服务配置。' \
        '最新插件可能对 DSH/Node 版本有更高要求；以安装时兼容性检查为准。'
fi
