#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DATA="$ROOT/data"
LOG="$ROOT/log"
export PASEO_HOME="$DATA/.paseo"
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

source "$ROOT/node-runtime.sh"
paseo_select_node

if [[ ! -x "$PASEO" ]]; then
  printf '尚未安装 Paseo，请先运行：bash %q\n' "$ROOT/install.sh" >&2
  exit 1
fi

NGINX="$ROOT/runtime/nginx/sbin/nginx"
NGINX_RUN="$DATA/nginx"
mkdir -p "$NGINX_RUN" "$LOG/nginx"
exec 9>"$DATA/service.lock"
flock -x 9

daemon() {
  "$PASEO" daemon "$@" --home "$PASEO_HOME" 9>&-
}

nginx_control() {
  python3 "$ROOT/paseo_nginx.py" "$1" "$ROOT" 9>&-
}
nginx_running() {
  nginx_control running
}
case "$1" in
  start)
    ENDPOINT="$(node "$ROOT/paseo-config.cjs" endpoint "$DATA" "$MODE")"
    mapfile -t ENDPOINT_FIELDS <<< "$ENDPOINT"
    URL="${ENDPOINT_FIELDS[1]}"
    CA_CERT="${ENDPOINT_FIELDS[2]}"
    if [[ "$MODE" == proxy ]]; then
      TLS_DIR="${CA_CERT%/*}"
      TLS_KEY="$TLS_DIR/privkey.pem"
      if [[ ! -f "$CA_CERT" || ! -r "$CA_CERT" || ! -s "$CA_CERT" ||
            ! -f "$TLS_KEY" || ! -r "$TLS_KEY" || ! -s "$TLS_KEY" ]]; then
        printf 'Paseo HTTPS 证书缺失、为空或不可读，启动已取消。\n' >&2
        printf '请从 ds-harness/data 下对应的证书目录复制 fullchain.pem 和 privkey.pem：\n' >&2
        printf '  来源：%s/ds-harness/data/tls/%s/\n' "${ROOT%/*}" "${TLS_DIR##*/}" >&2
        printf '  目标：%s/\n' "$TLS_DIR" >&2
        printf '复制完成后重新执行 start。\n' >&2
        exit 1
      fi
      [[ -x "$NGINX" ]] || { printf '请先运行 install.sh 安装 Nginx。\n' >&2; exit 1; }
      mkdir -p "$NGINX_RUN"/{body,proxy,fastcgi,uwsgi,scgi}
      nginx_control publish
    else
      if nginx_running; then
        printf 'HTTPS 代理正在运行，请先 stop 再 start --no-proxy。\n' >&2
        exit 1
      else
        code=$?
        [[ "$code" -eq 1 ]] || exit "$code"
      fi
    fi
    # 读取实际运行状态，禁止隐式重启或改写运行中实例的监听设置。
    STATE="$(daemon status --json)"
    node "$ROOT/paseo-config.cjs" prepare "$DATA" "$MODE" "$STATE"
    NETWORK_PROXY="$(node "$ROOT/paseo-config.cjs" network-proxy "$DATA")"
    if [[ -n "$NETWORK_PROXY" ]]; then
      if [[ "$STATE" == *'"running"'* ]]; then
        printf '服务已运行：networkProxy 仅在后端重新启动时应用；请在允许中断会话时先 stop 再 start。\n' >&2
      fi
      # Scope proxy overrides to the daemon and its children, keeping local control traffic direct.
      (
        export HTTP_PROXY="$NETWORK_PROXY" HTTPS_PROXY="$NETWORK_PROXY"
        export http_proxy="$NETWORK_PROXY" https_proxy="$NETWORK_PROXY"
        export NO_PROXY="localhost,127.0.0.1,::1${NO_PROXY:+,$NO_PROXY}${no_proxy:+,$no_proxy}"
        export no_proxy="$NO_PROXY"
        daemon start
      )
    else
      daemon start
    fi
    CURL_ARGS=(--noproxy '*' --fail --silent --show-error --max-time 15)
    if [[ "$MODE" == proxy ]]; then
      nginx_control start
      CURL_ARGS+=(--cacert "$CA_CERT")
    fi
    curl "${CURL_ARGS[@]}" "$URL/api/health"
    printf '\nPaseo：%s/\n' "$URL"
    ;;
  stop)
    nginx_control quit
    daemon stop
    ;;
  status)
    daemon status
    if nginx_running; then
      printf 'nginx: running (HTTPS)\n'
    else
      code=$?
      [[ "$code" -eq 1 ]] || exit "$code"
      printf 'nginx: stopped\n'
    fi
    ;;
  reload-proxy)
    nginx_control reload
    ;;
  set-password) daemon set-password ;;
esac
