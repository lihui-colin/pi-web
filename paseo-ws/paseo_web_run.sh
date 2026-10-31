#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
export PASEO_HOME="$ROOT/data"
PASEO="$ROOT/runtime/bin/paseo"

usage() {
  printf '用法：%s start [--proxy|--no-proxy]\n      %s {stop|status|set-password|reload-proxy}\n' "$0" "$0"
}
ACTION="${1:-}"
MODE=proxy
case "$ACTION" in
  -h|--help) usage; exit 0 ;;
  start)
    [[ $# -le 2 ]] || { usage >&2; exit 2; }
    case "${2:---proxy}" in
      --proxy) MODE=proxy ;;
      --no-proxy) MODE=direct ;;
      *) usage >&2; exit 2 ;;
    esac
    ;;
  stop|status|set-password|reload-proxy)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    ;;
  *) usage >&2; exit 2 ;;
esac

if [[ ! -x "$PASEO" ]]; then
  printf '尚未安装 Paseo，请先运行：bash %q\n' "$ROOT/install.sh" >&2
  exit 1
fi

NGINX="$ROOT/runtime/nginx/sbin/nginx"
NGINX_CONF="$PASEO_HOME/nginx.conf"
NGINX_RUN="$PASEO_HOME/nginx"
mkdir -p "$NGINX_RUN"
exec 9>"$PASEO_HOME/service.lock"
flock -x 9

nginx_running() {
  [[ -f "$NGINX_RUN/nginx.pid" ]] || return 1
  local pid
  read -r pid < "$NGINX_RUN/nginx.pid"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}
nginx_cmd() {
  "$NGINX" -p "$NGINX_RUN/" -c "$NGINX_CONF" -e "$NGINX_RUN/error.log" "$@" 9>&-
}
case "$1" in
  start)
    ENDPOINT="$(node "$ROOT/paseo-config.cjs" endpoint "$PASEO_HOME" "$MODE")"
    mapfile -t ENDPOINT_FIELDS <<< "$ENDPOINT"
    URL="${ENDPOINT_FIELDS[1]}"
    CA_CERT="${ENDPOINT_FIELDS[2]}"
    if [[ "$MODE" == proxy ]]; then
      node "$ROOT/paseo-config.cjs" proxy "$PASEO_HOME"
      [[ -x "$NGINX" ]] || { printf '请先运行 install.sh 安装 Nginx。\n' >&2; exit 1; }
      mkdir -p "$NGINX_RUN"/{body,proxy,fastcgi,uwsgi,scgi}
      nginx_cmd -t
    else
      if nginx_running; then
        printf 'HTTPS 代理正在运行，请先 stop 再 start --no-proxy。\n' >&2
        exit 1
      fi
    fi
    # 读取实际运行状态，禁止隐式重启或改写运行中实例的监听设置。
    STATE="$("$PASEO" daemon status --home "$PASEO_HOME" --json 9>&-)"
    node "$ROOT/paseo-config.cjs" prepare "$PASEO_HOME" "$MODE" "$STATE"
    "$PASEO" daemon start --home "$PASEO_HOME" 9>&-
    if [[ "$MODE" == proxy ]]; then
      if ! nginx_running; then nginx_cmd; fi
      curl --noproxy '*' --fail --silent --show-error --max-time 15 \
        --cacert "$CA_CERT" \
        "$URL/api/health"
      printf '\nPaseo HTTPS：%s/\n' "$URL"
    else
      curl --noproxy '*' --fail --silent --show-error --max-time 15 "$URL/api/health"
      printf '\nPaseo HTTP：%s/\n' "$URL"
    fi
    ;;
  stop)
    if nginx_running; then
      nginx_cmd -s quit
      for ((attempt=0; attempt<50; attempt++)); do
        nginx_running || break
        sleep 0.2
      done
      if nginx_running; then
        printf 'Nginx 仍在退出，请稍后重试 stop。\n' >&2
        exit 1
      fi
    fi
    "$PASEO" daemon stop --home "$PASEO_HOME" 9>&-
    ;;
  status)
    "$PASEO" daemon status --home "$PASEO_HOME" 9>&-
    if nginx_running; then printf 'nginx: running (HTTPS)\n'; else printf 'nginx: stopped\n'; fi
    ;;
  reload-proxy)
    node "$ROOT/paseo-config.cjs" proxy "$PASEO_HOME"
    nginx_cmd -t
    nginx_running || { printf 'Nginx 未运行。\n' >&2; exit 1; }
    nginx_cmd -s reload
    ;;
  set-password) "$PASEO" daemon set-password --home "$PASEO_HOME" 9>&- ;;
esac
