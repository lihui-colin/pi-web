#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)"
usage() {
  printf '用法：%s set <HTTP/HTTPS代理URL>\n      %s delete\n' "$0" "$0"
}
case "${1:-}" in
  set) [[ $# -eq 2 && -n "$2" ]] || { usage >&2; exit 2; } ;;
  delete) [[ $# -eq 1 ]] || { usage >&2; exit 2; } ;;
  -h|--help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

source "$ROOT/srcs/node-runtime.sh"
paseo_select_node
[[ -f "$ROOT/data/paseo.conf" ]] || { printf '缺少 data/paseo.conf，请先安装并配置访问地址。\n' >&2; exit 1; }
# Share the service lock so start cannot read a partially updated configuration.
exec 9>"$ROOT/data/service.lock"
flock -x 9
if [[ "$1" == set ]]; then
  node "$ROOT/srcs/paseo-config.cjs" set-network-proxy "$ROOT/data" "$2"
  printf '已设置 paseo.conf 中的 networkProxy。\n'
else
  node "$ROOT/srcs/paseo-config.cjs" delete-network-proxy "$ROOT/data"
  printf '已删除 paseo.conf 中的 networkProxy；后续启动仍会继承启动环境中的代理变量。\n'
fi
printf '未重启服务。配置在后端下次启动时生效；如服务正在运行，请在允许中断会话时先 stop 再 start。\n'
