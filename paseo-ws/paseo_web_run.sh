#!/usr/bin/env bash
set -Eeuo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
DATA="$ROOT/data"
export PASEO_HOME="$DATA/.paseo"
PASEO="$ROOT/runtime/bin/paseo"

usage() {
  printf '用法：%s start [--proxy|--no-proxy]\n      %s {stop|status|set-password|reload-proxy|migrate-home}\n' "$0" "$0"
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
  stop|status|set-password|reload-proxy|migrate-home)
    [[ $# -eq 1 ]] || { usage >&2; exit 2; }
    ;;
  *) usage >&2; exit 2 ;;
esac

if [[ ! -x "$PASEO" ]]; then
  printf '尚未安装 Paseo，请先运行：bash %q\n' "$ROOT/install.sh" >&2
  exit 1
fi

NGINX="$ROOT/runtime/nginx/sbin/nginx"
NGINX_CONF="$DATA/nginx.conf"
NGINX_RUN="$DATA/nginx"
if [[ "$ACTION" == migrate-home ]]; then
  exec python3 "$ROOT/paseo-migrate-home.py" launch "$ROOT"
fi

mkdir -p "$NGINX_RUN"
# The detached migration worker passes its locked descriptor to lifecycle commands.
if [[ -n "${PASEO_MAINTENANCE_HOME:-}" && "$(readlink /proc/self/fd/9)" == "$DATA/service.lock" ]]; then
  [[ "$PASEO_MAINTENANCE_HOME" == "$DATA" || "$PASEO_MAINTENANCE_HOME" == "$DATA/.paseo" ]] || {
    printf '无效的维护进程锁或数据目录。\n' >&2; exit 1;
  }
  export PASEO_HOME="$PASEO_MAINTENANCE_HOME"
else
  # Older daemon launches may have inherited this marker without its lock descriptor.
  unset PASEO_MAINTENANCE_HOME
  exec 9>"$DATA/service.lock"
fi
flock -x 9

if [[ -z "${PASEO_MAINTENANCE_HOME:-}" && -f "$DATA/config.json" ]]; then
  case "$ACTION" in
    status|stop) export PASEO_HOME="$DATA" ;;
    start|set-password)
      printf '旧数据尚未迁移，请在无运行任务时执行：%s migrate-home\n' "$0" >&2
      exit 1 ;;
  esac
fi

nginx_running() {
  [[ -f "$NGINX_RUN/nginx.pid" ]] || return 1
  local pid
  read -r pid < "$NGINX_RUN/nginx.pid"
  [[ "$pid" =~ ^[0-9]+$ ]] && kill -0 "$pid" 2>/dev/null
}
nginx_cmd() {
  "$NGINX" -p "$NGINX_RUN/" -c "$NGINX_CONF" -e "$NGINX_RUN/error.log" "$@" 9>&-
}
if [[ -z "${PASEO_MAINTENANCE_HOME:-}" && -f "$DATA/home-migration.json" &&
      ( "$ACTION" == start || "$ACTION" == set-password ) ]]; then
  node - "$DATA/home-migration.json" <<'NODE'
const fs = require('node:fs');
const { phase } = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
if (!['complete', 'rolled-back'].includes(phase)) {
  console.error('数据迁移未完成，请先检查 data/home-migration.json 和迁移日志。');
  process.exit(1);
}
NODE
fi

# Maintenance context is local to this script, never part of the daemon environment.
unset PASEO_MAINTENANCE_HOME
case "$1" in
  start)
    ENDPOINT="$(node "$ROOT/paseo-config.cjs" endpoint "$DATA" "$MODE")"
    mapfile -t ENDPOINT_FIELDS <<< "$ENDPOINT"
    URL="${ENDPOINT_FIELDS[1]}"
    CA_CERT="${ENDPOINT_FIELDS[2]}"
    if [[ "$MODE" == proxy ]]; then
      node "$ROOT/paseo-config.cjs" proxy "$DATA"
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
    if [[ "$PASEO_HOME" == "$DATA/.paseo" ]]; then
      node "$ROOT/paseo-config.cjs" prepare "$DATA" "$MODE" "$STATE"
    fi
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
    node "$ROOT/paseo-config.cjs" proxy "$DATA"
    nginx_cmd -t
    nginx_running || { printf 'Nginx 未运行。\n' >&2; exit 1; }
    nginx_cmd -s reload
    ;;
  set-password) "$PASEO" daemon set-password --home "$PASEO_HOME" 9>&- ;;
esac
