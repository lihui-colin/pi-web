#!/usr/bin/env bash
# 安装 web profile 的十个额外插件；已有 profile 保留启用/禁用状态。
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
                '默认补装十个额外插件；--upgrade 重新安装，普通 npm 插件使用 latest，Codex 与实际 DSH 同版。' \
                'mobile 默认使用 GitHub，composer-plus 默认使用 1.22.0 压缩包；保留已指定的对应来源。' \
                '已有 web profile 保留启用/禁用状态；新 profile 启用八个，input-history 和 dsh-ide-git 仅安装。' \
                '数据固定放在服务目录下 data/.dsh；不配置内置 bundle，不启停服务。' \
                '--expected-dsh-version 仅供父安装器 dry-run 传入预期版本或占位符。'
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
    command -v python3 >/dev/null 2>&1 || { printf '缺少命令：python3（用于 DS Bot 兼容补丁）。\n' >&2; exit 1; }
    [[ -f "$script_dir/srcs/patches/plugins/ds_bot/ds_bot_apply.py" ]] || { printf '缺少 DS Bot 统一补丁文件。\n' >&2; exit 1; }
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
    dsh_version='<安装后的 DSH 版本>'
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
plugin_plan="$(node --input-type=module - "$profile_dir" "$dsh_version" "$upgrade" <<'PLAN_NODE'
import fs from 'node:fs';
import path from 'node:path';
const [dir, version, upgrade] = process.argv.slice(2);
const manifest = path.join(dir, 'package.json');
const pkg = fs.existsSync(manifest) ? JSON.parse(fs.readFileSync(manifest, 'utf8')) : {};
const names = ['@deepseek-ai/dsh-subagent-codex', 'ds-bot', 'dsh-web-mobile', 'dshmarket', 'dsh-ide-git', 'dsh-sidebar-enhancement', 'dsh-sidebar-plus', '@huanlin/dsh-plugin-input-history', '@xbzbing/dsh-git-panel', 'dsh-composer-plus'];
// Sources selected in the deployed web profile; keep these on a fresh install too.
const sources = {
  'dsh-web-mobile': 'github:mexiaosqwq/dsh-web-mobile',
  'dsh-composer-plus': 'https://registry.npmjs.org/dsh-composer-plus/-/dsh-composer-plus-1.22.0.tgz',
};
for (const name of names) {
  const installedPath = path.join(dir, 'node_modules', name, 'package.json');
  let installed;
  if (fs.existsSync(installedPath)) installed = JSON.parse(fs.readFileSync(installedPath, 'utf8'));
  const declared = pkg.dependencies?.[name] || pkg.devDependencies?.[name] || pkg.optionalDependencies?.[name];
  // Keep an explicitly selected mobile repository (including a pinned commit).
  // Replacing it with npm latest could restore the older mobile generation.
  const githubMobile = name === 'dsh-web-mobile' && typeof declared === 'string' && declared.startsWith('github:');
  const tarballComposer = name === 'dsh-composer-plus' && typeof declared === 'string' && declared.startsWith('https:');
  const source = githubMobile || tarballComposer ? declared : sources[name];
  const target = name === names[0] ? version : source || 'latest';
  if (upgrade !== 'true' && declared && installed?.name === name && installed.version &&
      (name !== names[0] || installed.version === version)) {
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
    printf '%s\n' '预览：已有 profile 保留额外插件启用状态；新 profile 安装十个、启用八个（不启用 input-history 和 dsh-ide-git）。未修改文件。'
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
    const defaults = ['@deepseek-ai/dsh-subagent-codex', 'ds-bot', 'dsh-web-mobile', 'dshmarket', 'dsh-sidebar-enhancement', 'dsh-sidebar-plus', '@xbzbing/dsh-git-panel', 'dsh-composer-plus'];
    pkg.dsh ??= {};
    pkg.dsh.profile ??= {};
    const existing = pkg.dsh.profile.bundles ?? [];
    if (!Array.isArray(existing)) throw new Error('现有 bundles 不是数组，停止修改');
    pkg.dsh.profile.bundles = [...new Set([...existing.filter(name => !['dsh-ide-git', '@huanlin/dsh-plugin-input-history'].includes(name)), ...defaults])];
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
# Always validate/migrate the reviewed version pair, even when downloads were skipped.
# Current Bot/mobile use upstream UI; migrate retired host hooks before fitting tabs.
# Terminal fixes stay paired. Unknown or mixed releases must fail explicitly.
run python3 -B "$script_dir/srcs/patches/plugins/ds_bot/ds_bot_apply.py"
run python3 -B "$script_dir/srcs/patches/plugins/mobile/dsh_mobile_apply.py"
run python3 -B "$script_dir/srcs/patches/plugins/git_panel/dsh_git_panel_apply.py"
run python3 -B "$script_dir/srcs/patches/service/dsh_terminal_apply.py"
run python3 -B "$script_dir/srcs/patches/service/dsh_file_resources_apply.py"
run python3 -B "$script_dir/srcs/patches/service/dsh_composer_metadata_apply.py"
