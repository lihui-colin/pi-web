#!/usr/bin/env bash
set -Eeuo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if [[ $# != 1 ]]; then
  printf '用法：%s start|stop|status\n' "$0" >&2
  exit 2
fi
case "$1" in
  start|stop|status) exec python3 "$ROOT/srcs/ocra.py" "$1" ;;
  *) printf '用法：%s start|stop|status\n' "$0" >&2; exit 2 ;;
esac
