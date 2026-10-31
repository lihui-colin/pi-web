#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
PREFIX="$ROOT/runtime"

for dependency in node npm; do
  if ! command -v "$dependency" >/dev/null 2>&1; then
    printf '缺少 %s，请先安装 Node.js（含 npm）。\n' "$dependency" >&2
    exit 1
  fi
done

# 仅安装环境，不修改服务配置，不启动或停止服务。
bash "$ROOT/paseo_nginx_install.sh"
mkdir -p -- "$PREFIX"
npm install --global --prefix "$PREFIX" --cache "$ROOT/.npm-cache" --engine-strict '@getpaseo/cli'
node "$ROOT/patch-web-ui.cjs"

printf '\n安装完成。运行环境：%s\n' "$PREFIX"
printf '启动：bash %q start\n' "$ROOT/paseo_web_run.sh"
printf '停止：bash %q stop\n' "$ROOT/paseo_web_run.sh"
printf '请确保至少一种代理 CLI 已安装并完成认证。\n'
