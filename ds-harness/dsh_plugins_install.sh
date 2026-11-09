#!/usr/bin/env bash
# 安装 web profile 的十一个额外插件；已有 profile 保留启用/禁用状态。
set -euo pipefail
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
dry_run=false
upgrade=false
expected_version=''
while (( $# )); do
    case "$1" in
        --dry-run) dry_run=true; shift ;;
        --upgrade) upgrade=true; shift ;;
        --expected-dsh-version)
            [[ $# -ge 2 && -n "$2" ]] || { printf '缺少预期 DSH 版本。\n' >&2; exit 2; }
            expected_version="$2"; shift 2 ;;
        -h|--help)
            printf '%s\n' \
                '用法：bash ds-harness/dsh_plugins_install.sh [--dry-run] [--upgrade]' \
                '默认按固定版本安装十一个插件；--upgrade 查询最新版本、更新清单并升级。' \
                '版本和来源统一固定于 srcs/install-versions.json；mobile 固定 GitHub 提交。' \
                'codex-quota 链接本服务 srcs/plugins/codex-quota；已有 web profile 保留启用/禁用状态。' \
                '新 profile 启用九个，dsh-ide-git 和 Git panel 仅安装。' \
                '数据固定放在服务目录下 data/.dsh；不配置内置 bundle，不启停服务。' \
                '--expected-dsh-version 仅供父安装器 dry-run 传入固定版本。'
            exit 0 ;;
        *) printf '未知参数：%s\n' "$1" >&2; exit 2 ;;
    esac
done
if [[ -n "$expected_version" ]] && ! "$dry_run"; then
    printf '%s\n' '--expected-dsh-version 仅可用于 --dry-run。' >&2
    exit 2
fi
command -v node >/dev/null 2>&1 || { printf '缺少命令：node。\n' >&2; exit 1; }

if ! "$dry_run"; then
    command -v python3 >/dev/null 2>&1 || { printf '缺少命令：python3（用于 DSH 兼容补丁）。\n' >&2; exit 1; }
    # Validate every local tool and helper before downloading or changing the profile.
    bash "$script_dir/dsh_patches_install.sh" --validate-tools
fi
if "$upgrade" && ! "$dry_run" && [[ "${DSH_UPGRADE_PINS_RESOLVED:-}" != 1 ]]; then
    node "$script_dir/srcs/update-install-versions.mjs" "$script_dir/srcs/install-versions.json"
elif "$upgrade" && "$dry_run"; then
    printf '%s\n' '预览：实际 --upgrade 会查询最新版本并更新清单；以下使用当前清单，不联网或写入。'
fi
export DSH_HOME="$script_dir/data/.dsh"
export DSH_AGENTS_HOME="$script_dir/data/.agents"
profile_dir="$DSH_HOME/profiles/web"
if [[ -n "$expected_version" ]]; then
    dsh_version="$expected_version"
elif command -v dsh >/dev/null 2>&1; then
    dsh_version="$(dsh --version)"
    if [[ ! "$dsh_version" =~ ^[0-9]+\.[0-9]+\.[0-9]+(-[0-9A-Za-z.-]+)?(\+[0-9A-Za-z.-]+)?$ ]]; then
        printf '无法识别 DSH 版本：%s，停止安装插件。\n' "$dsh_version" >&2
        exit 1
    fi
elif "$dry_run"; then
    dsh_version="$(node -p 'require(process.argv[1]).dsh' "$script_dir/srcs/install-versions.json")"
else
    printf '缺少命令：dsh。请先运行 dsh_install.sh。\n' >&2
    exit 1
fi
run() {
    printf '+'; printf ' %q' "$@"; printf '\n'
    if ! "$dry_run"; then "$@"; fi
}
# 包管理器运行前记录状态；已有 profile 缺少 bundles 也不自动启用插件。
bundle_state="$(node --input-type=module - "$profile_dir/package.json" <<'STATE_NODE'
import fs from 'node:fs';
const file = process.argv[2];
if (!fs.existsSync(file)) console.log('null');
else {
  const pkg = JSON.parse(fs.readFileSync(file, 'utf8'));
  const bundles = pkg.dsh?.profile?.bundles;
  if (bundles !== undefined && !Array.isArray(bundles)) throw new Error('现有 bundles 不是数组，停止修改');
  console.log(JSON.stringify({ bundles }));
}
STATE_NODE
)"
# 声明和实际文件均存在才算已安装；Codex 还必须与 DSH 同版。
plugin_plan="$(node --input-type=module - "$profile_dir" "$dsh_version" "$upgrade" "$script_dir/srcs/install-versions.json" <<'PLAN_NODE'
import fs from 'node:fs';
import path from 'node:path';
const [dir, version, upgrade, pinsFile] = process.argv.slice(2);
const pins = JSON.parse(fs.readFileSync(pinsFile, 'utf8'));
if (version !== pins.dsh) throw new Error(`DSH ${version} 与固定版本 ${pins.dsh} 不符，请先运行 dsh_install.sh`);
const manifest = path.join(dir, 'package.json');
const pkg = fs.existsSync(manifest) ? JSON.parse(fs.readFileSync(manifest, 'utf8')) : {};
const names = Object.keys(pins.plugins);
for (const name of names) {
  const installedPath = path.join(dir, 'node_modules', name, 'package.json');
  let installed;
  if (fs.existsSync(installedPath)) installed = JSON.parse(fs.readFileSync(installedPath, 'utf8'));
  const declared = pkg.dependencies?.[name] || pkg.devDependencies?.[name] || pkg.optionalDependencies?.[name];
  const pin = pins.plugins[name];
  const target = pin.source || pin.version;
  if (declared === target && installed?.name === name && installed.version === pin.version) {
    console.error(`已安装 ${name}@${installed.version}，跳过安装。`);
  } else console.log(`${name}@${target}`);
}
PLAN_NODE
)"
plugins=()
while IFS= read -r plugin; do
    if [[ -n "$plugin" ]]; then plugins+=("$plugin"); fi
done <<< "$plugin_plan"
status=0
if (( ${#plugins[@]} )); then
    if [[ -f "$profile_dir/package.json" ]]; then
        backup="$profile_dir/package.json.before-dsh-plugins-install.$(date +%Y%m%dT%H%M%S).$$"
        run cp -p -- "$profile_dir/package.json" "$backup"
    fi
    if run dsh plugin --profile web add -w --save-exact "${plugins[@]}"; then
        :
    else
        status=$?
    fi
else
    printf '%s\n' '所需插件均已安装，跳过插件安装。'
fi
if "$dry_run"; then
    printf '%s\n' '预览：已有 profile 保留额外插件启用状态；新 profile 安装十一个、启用九个（不启用 dsh-ide-git 和 Git panel）。未修改文件。'
else
    # 包管理器可能自动启用插件；安装失败时也恢复已有 profile 的 bundle 状态。
    node --input-type=module - "$profile_dir/package.json" "$bundle_state" "$status" <<'BUNDLES_NODE'
import fs from 'node:fs';
const [file, raw, status] = process.argv.slice(2);
const state = JSON.parse(raw);
if (!fs.existsSync(file)) {
  if (status === '0') throw new Error('插件安装未创建 profile');
} else {
  const pkg = JSON.parse(fs.readFileSync(file, 'utf8'));
  const before = JSON.stringify(pkg);
  if (state !== null) {
    if (state.bundles === undefined) {
      if (pkg.dsh?.profile) delete pkg.dsh.profile.bundles;
    } else {
      pkg.dsh ??= {};
      pkg.dsh.profile ??= {};
      pkg.dsh.profile.bundles = state.bundles;
    }
  } else if (status === '0') {
    const defaults = ['@deepseek-ai/dsh-subagent-codex', 'ds-bot', 'dsh-web-mobile', 'dshmarket', 'dsh-sidebar-enhancement', 'dsh-sidebar-plus', '@local/dsh-codex-quota', 'dsh-composer-plus', 'dsh-better-sidebar'];
    pkg.dsh ??= {};
    pkg.dsh.profile ??= {};
    const existing = pkg.dsh.profile.bundles ?? [];
    if (!Array.isArray(existing)) throw new Error('现有 bundles 不是数组，停止修改');
    pkg.dsh.profile.bundles = [...new Set([...existing.filter(name => !['dsh-ide-git', '@xbzbing/dsh-git-panel'].includes(name)), ...defaults])];
  }
  if (JSON.stringify(pkg) !== before) {
    const temp = `${file}.dsh-plugins-install.${process.pid}.tmp`;
    fs.writeFileSync(temp, `${JSON.stringify(pkg, null, 2)}\n`, { mode: fs.statSync(file).mode & 0o777 });
    fs.renameSync(temp, file);
  }
}
BUNDLES_NODE
fi
if (( status != 0 )); then exit "$status"; fi
# Validate the complete patch set before publishing any target file.
# Shared host files are composed in memory and backed up only once.
run bash "$script_dir/dsh_patches_install.sh"
