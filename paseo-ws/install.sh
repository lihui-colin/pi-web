#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PREFIX="$ROOT/runtime"

source "$ROOT/srcs/node-runtime.sh"
if ! paseo_select_node; then
  # An explicit invalid override is a configuration error, not permission to ignore it.
  if [[ ${PASEO_NODE_BIN+x} ]]; then exit 1; fi
  printf '未找到独立 Node.js，正在为 Paseo 安装官方 Node.js 24 LTS…\n'
  bash "$ROOT/srcs/install-node.sh"
  paseo_select_node
fi
printf '使用 Node.js %s：%s\n' "$(node --version)" "$(command -v node)"
bash "$ROOT/srcs/init-access-config.sh"
node "$ROOT/srcs/paseo-config.cjs" init "$ROOT/data"

# 仅安装环境，不启动或停止服务；已有配置保持不变。
bash "$ROOT/srcs/paseo_nginx_install.sh"
mkdir -p -- "$PREFIX"
npm install --global --prefix "$PREFIX" --cache "$ROOT/.npm-cache" --engine-strict '@getpaseo/cli'
node "$ROOT/srcs/patches/service/patch-web-ui.cjs"
node "$ROOT/srcs/patches/service/patch-workspace-git-startup.cjs"
node "$ROOT/srcs/patches/plugins/dsh/patch-dsh-catalog.cjs"

printf '\n安装完成。运行环境：%s\n' "$PREFIX"
printf '启动：bash %q start\n' "$ROOT/paseo_web_run.sh"
printf '停止：bash %q stop\n' "$ROOT/paseo_web_run.sh"
printf '请确保至少一种代理 CLI 已安装并完成认证。\n'
