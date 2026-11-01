#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
CONFIG="$ROOT/data/paseo.conf"

# Never overwrite existing user configuration, including symbolic links.
if [[ -e "$CONFIG" || -L "$CONFIG" ]]; then
  exit 0
fi

printf '首次安装：请配置 Paseo 访问地址。\n'
while true; do
  printf 'IP 地址 [10.30.0.25]：' >&2
  if ! IFS= read -r ip; then
    printf '\n未收到 IP 地址，配置未创建。请在终端重新运行安装脚本。\n' >&2
    exit 1
  fi
  ip="$(node -p 'process.argv[1].trim()' -- "$ip")"
  ip="${ip:-10.30.0.25}"
  if node -e 'process.exit(require("node:net").isIP(process.argv[1]) ? 0 : 1)' -- "$ip"; then
    break
  fi
  printf '请输入有效的 IPv4 或 IPv6 地址。\n' >&2
done
while true; do
  printf '端口号 [25227]：' >&2
  if ! IFS= read -r port; then
    printf '\n未收到端口号，配置未创建。请在终端重新运行安装脚本。\n' >&2
    exit 1
  fi
  port="$(node -p 'process.argv[1].trim()' -- "$port")"
  port="${port:-25227}"
  if [[ "$port" =~ ^[0-9]{1,5}$ ]] && (( 10#$port >= 1 && 10#$port <= 65535 && 10#$port != 25226 )); then
    break
  fi
  printf '端口须为 1–65535 的整数，且不能占用后端端口 25226。\n' >&2
done

mkdir -p -- "$ROOT/data"
node - "$CONFIG" "$ip" "$port" <<'JS'
const fs = require('node:fs');
const [file, ip, port] = process.argv.slice(2);
try {
  fs.writeFileSync(file, JSON.stringify({ ip, port: Number(port) }, null, 2) + '\n', { mode: 0o600, flag: 'wx' });
  console.log(`已创建访问配置：${file}`);
} catch (error) {
  if (error.code !== 'EEXIST') throw error;
  console.log('访问配置已由其他进程创建，保留现有文件。');
}
JS
