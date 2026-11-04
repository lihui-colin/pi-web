#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
usage() {
  printf '用法：%s set <HTTP/HTTPS代理URL>\n      %s clear\n      %s show\n' "$0" "$0" "$0"
  printf '不带参数时默认 show；delete 是 clear 的兼容别名。\n'
}
COMMAND="${1:-show}"
case "$COMMAND" in
  set) [[ $# -eq 2 && -n "$2" ]] || { usage >&2; exit 2; } ;;
  clear|delete) [[ $# -eq 1 ]] || { usage >&2; exit 2; } ;;
  show) [[ $# -le 1 ]] || { usage >&2; exit 2; } ;;
  -h|--help|help) usage; exit 0 ;;
  *) usage >&2; exit 2 ;;
esac

source "$ROOT/srcs/node-runtime.sh"
paseo_select_node
[[ -f "$ROOT/data/paseo.conf" ]] || { printf '缺少 data/paseo.conf，请先安装并配置访问地址。\n' >&2; exit 1; }
if [[ "$COMMAND" == show ]]; then
  NETWORK_PROXY="$(node "$ROOT/srcs/paseo-config.cjs" network-proxy "$ROOT/data")"
  if [[ "$NETWORK_PROXY" == *'@'* ]]; then
    NETWORK_PROXY="${NETWORK_PROXY%%://*}://***@${NETWORK_PROXY##*@}"
  fi
  printf 'Paseo networkProxy：%s\n' "${NETWORK_PROXY:-未配置（跟随启动环境）}"
  exit 0
fi
# Share the service lock so start cannot read a partially updated configuration.
exec 9>"$ROOT/data/service.lock"
flock -x 9
if [[ "$COMMAND" == set ]]; then
  node "$ROOT/srcs/paseo-config.cjs" set-network-proxy "$ROOT/data" "$2"
  printf '已设置 paseo.conf 中的 networkProxy。\n'
else
  node "$ROOT/srcs/paseo-config.cjs" delete-network-proxy "$ROOT/data"
  printf '已删除 paseo.conf 中的 networkProxy；后续启动仍会继承启动环境中的代理变量。\n'
fi
printf '未重启服务。配置在后端下次启动时生效；如服务正在运行，请在允许中断会话时先 stop 再 start。\n'
