#!/usr/bin/env bash
#
# PI WEB (jmfederico) 手动运行管理脚本
#
# 适用于无 systemd user 总线（容器 / WSL / 精简服务器）的环境，按官方
# “manual run” 方式分别启动 session daemon 和 web/API 服务。
#
# 用法:
#   ./scripts/pi-web-run-jmfederico.sh start                # 后台启动（sessiond + server）
#   ./scripts/pi-web-run-jmfederico.sh start --port 8080    # 指定端口启动
#   ./scripts/pi-web-run-jmfederico.sh stop                 # 停止
#   ./scripts/pi-web-run-jmfederico.sh update [更新选项]    # 升级 pi 和 pi-web
#   ./scripts/pi-web-run-jmfederico.sh status               # 查看状态
#   ./scripts/pi-web-run-jmfederico.sh logs                 # 跟随服务日志
#
# 可配置参数:
#   --port <port>    监听端口（优先级高于 PI_WEB_PORT 环境变量，默认 8024）
#
# 可配置环境变量:
#   PI_WEB_HOST      绑定地址，默认 0.0.0.0
#   PI_WEB_PORT      监听端口，默认 8024
#   PI_WEB_PASSWORD  设置后（若支持）开启访问保护

if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi
set -euo pipefail

port_explicit="${PI_WEB_PORT:+1}"
PI_WEB_HOST="${PI_WEB_HOST:-0.0.0.0}"
PI_WEB_PORT="${PI_WEB_PORT:-8024}"
PI_WEB_PASSWORD="${PI_WEB_PASSWORD:-}"

usage() {
    cat <<'EOF'
PI WEB (jmfederico) 手动运行管理脚本

用法:
  ./scripts/pi-web-run-jmfederico.sh start                # 后台启动（sessiond + server）
  ./scripts/pi-web-run-jmfederico.sh start --port 8080    # 指定端口启动
  ./scripts/pi-web-run-jmfederico.sh stop                 # 停止
  ./scripts/pi-web-run-jmfederico.sh update [更新选项]    # 升级 pi 和 pi-web
  ./scripts/pi-web-run-jmfederico.sh status [--port N]    # 查看状态
  ./scripts/pi-web-run-jmfederico.sh logs                 # 跟随服务日志
  ./scripts/pi-web-run-jmfederico.sh --help               # 显示本帮助

参数:
  --port <port>    监听端口（优先级高于 PI_WEB_PORT 环境变量，默认 8024）
  -h, --help       显示本帮助并退出
  stop 未指定端口或运行目录时，自动选择 data/pi-web 下唯一的端口实例。

更新选项:
  --pi-only        只升级 Pi Coding Agent
  --web-only       只升级 @jmfederico/pi-web
  --update-relay   同步升级全局 relay skill
  --dry-run        只显示将执行的升级操作
  更新不启停服务；更新完成后需要手动执行 stop、start 才能使用新版本。

环境变量:
  PI_WEB_HOST      绑定地址，默认 0.0.0.0
  PI_WEB_PORT      监听端口，默认 8024
  PI_WEB_PASSWORD  设置后（若支持）开启访问保护
  PI_WEB_DATA_DIR  状态目录，默认 data/pi-web/<port>/state
  PI_WEB_RUN_DIR   日志和 PID 目录，默认 data/pi-web/<port>
  PI_WEB_SESSIOND_SOCKET  默认 <状态目录>/sessiond.sock
  PI_WEB_UPSTREAM_URL  官方上游 Git URL 覆盖
  PI_WEB_INSTALL_ROOT  安装目录父路径
  PI_WEB_TEST_MAX_WORKERS / PI_WEB_TEST_TIMEOUT_MS  构建测试限制
  update 将 Pi Agent 更新到 latest，并将官方 main 最新提交写入 patches/base-commit。
EOF
}

# ---------- 参数解析 ----------
ACTION=""
ACTION_ARGS=()
while [[ $# -gt 0 ]]; do
    case "$1" in
        -h|--help)
            usage
            exit 0
        ;;
        --port)
            [[ $# -ge 2 ]] || { echo "错误：--port 需要端口号参数" >&2; exit 2; }
            port_explicit=1
            PI_WEB_PORT="$2"
            shift 2
        ;;
        --port=*)
            port_explicit=1
            PI_WEB_PORT="${1#*=}"
            shift
        ;;
        start|stop|update|status|logs)
            ACTION="$1"
            shift
        ;;
        *)
            ACTION_ARGS+=("$1")
            shift
        ;;
    esac
done
[[ -n "$ACTION" ]] || ACTION="${ACTION_ARGS[0]:-run}"

script_file="$(readlink -f "${BASH_SOURCE[0]}")"
project_root="$(cd "$(dirname "$script_file")/.." && pwd)"
# With no explicit target, stop the sole instance instead of assuming port 8024.
if [[ "$ACTION" == stop && -z "$port_explicit" && -z "${PI_WEB_RUN_DIR:-}" ]]; then
    instance_ports=()
    for candidate in "$project_root"/data/pi-web/*; do
        [[ -d "$candidate" ]] || continue
        candidate_port="${candidate##*/}"
        [[ "$candidate_port" =~ ^[1-9][0-9]{0,4}$ ]] || continue
        (( candidate_port <= 65535 )) || continue
        instance_ports+=("$candidate_port")
    done
    if [[ ${#instance_ports[@]} -eq 1 ]]; then
        PI_WEB_PORT="${instance_ports[0]}"
        echo "自动选择唯一实例: $PI_WEB_PORT"
    fi
fi
# 端口同时作为实例标识，避免不同 Web 服务共享 daemon 状态和 PID。
if [[ ! "$PI_WEB_PORT" =~ ^[0-9]{1,5}$ ]] || (( 10#$PI_WEB_PORT < 1 || 10#$PI_WEB_PORT > 65535 )); then
    echo "错误：--port 必须是 1–65535 的整数" >&2
    exit 2
fi
PI_WEB_PORT="$((10#$PI_WEB_PORT))"
instance_dir="$project_root/data/pi-web/$PI_WEB_PORT"
export PI_WEB_DATA_DIR="${PI_WEB_DATA_DIR:-$instance_dir/state}"
export PI_WEB_SESSIOND_SOCKET="${PI_WEB_SESSIOND_SOCKET:-$PI_WEB_DATA_DIR/sessiond.sock}"
export PI_WEB_RUN_DIR="${PI_WEB_RUN_DIR:-$instance_dir}"
log_dir="$PI_WEB_RUN_DIR"
server_log="$log_dir/server.log"
sessiond_log="$log_dir/sessiond.log"
server_pid="$log_dir/server.pid"
sessiond_pid="$log_dir/sessiond.pid"
run_script="$script_file"

require_bins() {
    command -v pi-web-server   >/dev/null 2>&1 || { echo "错误：未找到 pi-web-server" >&2; exit 1; }
    command -v pi-web-sessiond >/dev/null 2>&1 || { echo "错误：未找到 pi-web-sessiond" >&2; exit 1; }
}

check_port_free() {
    if command -v ss >/dev/null 2>&1; then
        if ss -tlnp 2>/dev/null | grep -q ":$PI_WEB_PORT "; then
            echo "错误：端口 $PI_WEB_PORT 已被占用" >&2
            exit 1
        fi
    fi
}

start() {
    require_bins
    mkdir -p "$log_dir"
    # nohup ignores SIGHUP, but does not detach the process group from an
    # automation runner. Start a separate session where setsid is available.
    local -a launcher=(nohup)
    if command -v setsid >/dev/null 2>&1; then
        launcher+=(setsid)
    fi

    # 会话守护进程
    if [[ ! -f "$sessiond_pid" ]] || ! kill -0 "$(cat "$sessiond_pid")" 2>/dev/null; then
        echo "启动 pi-web-sessiond ..."
        "${launcher[@]}" pi-web-sessiond </dev/null >"$sessiond_log" 2>&1 &
        echo $! > "$sessiond_pid"
    else
        echo "pi-web-sessiond 已在运行 (PID $(cat "$sessiond_pid"))"
    fi

    # Web/API 服务
    if [[ ! -f "$server_pid" ]] || ! kill -0 "$(cat "$server_pid")" 2>/dev/null; then
        check_port_free
        echo "启动 pi-web-server -> http://$PI_WEB_HOST:$PI_WEB_PORT"
        if [[ -n "$PI_WEB_PASSWORD" ]]; then
            PI_WEB_PASSWORD="$PI_WEB_PASSWORD" PI_WEB_PORT="$PI_WEB_PORT" PI_WEB_HOST="$PI_WEB_HOST" \
            "${launcher[@]}" pi-web-server </dev/null >"$server_log" 2>&1 &
        else
            PI_WEB_PORT="$PI_WEB_PORT" PI_WEB_HOST="$PI_WEB_HOST" \
            "${launcher[@]}" pi-web-server </dev/null >"$server_log" 2>&1 &
        fi
        echo $! > "$server_pid"
    else
        echo "pi-web-server 已在运行 (PID $(cat "$server_pid"))"
    fi

    # 等服务就绪（最多约 15 秒）
    for _ in $(seq 1 30); do
        if curl -s -o /dev/null --max-time 1 "http://127.0.0.1:$PI_WEB_PORT/" 2>/dev/null; then
            break
        fi
        sleep 0.5
    done
    status
}

stop_pid() {
    local name="$1" pidfile="$2"
    if [[ -f "$pidfile" ]]; then
        local pid; pid="$(cat "$pidfile")"
        if kill -0 "$pid" 2>/dev/null; then
            kill "$pid" 2>/dev/null || true
            sleep 1
            kill -9 "$pid" 2>/dev/null || true
            echo "已停止 $name (PID $pid)"
        fi
        rm -f "$pidfile"
    fi
}

stop() {
    stop_pid "pi-web-server"   "$server_pid"
    stop_pid "pi-web-sessiond" "$sessiond_pid"
}

status() {
    local any=0
    if [[ -f "$server_pid" ]] && kill -0 "$(cat "$server_pid")" 2>/dev/null; then
        echo "pi-web-server   运行中 (PID $(cat "$server_pid")) -> http://$PI_WEB_HOST:$PI_WEB_PORT"
        curl -s -o /dev/null -w "   HTTP 状态: %{http_code}\n" "http://127.0.0.1:$PI_WEB_PORT/" 2>/dev/null || echo "   探测失败"
        any=1
    else
        echo "pi-web-server   未在运行"
    fi
    if [[ -f "$sessiond_pid" ]] && kill -0 "$(cat "$sessiond_pid")" 2>/dev/null; then
        echo "pi-web-sessiond 运行中 (PID $(cat "$sessiond_pid"))"
        any=1
    else
        echo "pi-web-sessiond 未在运行"
    fi
    [[ $any -eq 1 ]]
}

logs() {
    local f="$server_log"
    [[ -f "$f" ]] || f="$sessiond_log"
    tail -f -n 50 "$f"
}

log()  { printf '\033[1;34m[update-jmf]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[update-jmf]\033[0m %s\n' "$*" >&2; }
err()  { printf '\033[1;31m[update-jmf]\033[0m %s\n' "$*" >&2; }

ver_ge() { [[ "$(printf '%s\n' "$1" "$2" | sort -V | tail -n1)" == "$1" ]]; }


run() {
    if [[ $DRY_RUN -eq 1 ]]; then
        log "[dry-run] $*"
        return 0
    fi
    "$@"
}

pkg_version() {
    local pkg="$1"
    { npm ls -g --depth=0 --json "$pkg" 2>/dev/null || true; } \
    | node -e '
            let s = "";
            process.stdin.on("data", d => s += d);
            process.stdin.on("end", () => {
              try {
                const j = JSON.parse(s || "{}");
                const deps = j.dependencies || {};
                const name = process.argv[1];
                process.stdout.write((deps[name] && deps[name].version) || "");
              } catch {
                process.stdout.write("");
              }
            });
    ' "$pkg"
}

cli_version() {
    local bin="$1"
    if ! command -v "$bin" >/dev/null 2>&1; then
        echo ""
        return 0
    fi
    case "$bin" in
        pi) pi --version 2>/dev/null | head -n1 | tr -d '[:space:]' ;;
        pi-web)
            pi-web version 2>/dev/null | awk '
                /@jmfederico\/pi-web:/ { print $NF; found=1 }
                END { if (!found) print "" }
            '
        ;;
        *) echo "" ;;
    esac
}

# ---------- 前置检查 ----------
check_node() {
    command -v node >/dev/null 2>&1 || { err "未找到 node，需要 Node.js >= 22.19.0"; exit 1; }
    command -v npm >/dev/null 2>&1 || { err "未找到 npm"; exit 1; }
    local ver; ver="$(node --version | sed 's/^v//')"
    if ! ver_ge "$ver" "22.19.0"; then
        err "Node.js 版本过低（v$ver），需要 >= 22.19.0"
        exit 1
    fi
    log "Node.js v$ver"
}

check_conflict() {
    if npm ls -g --depth=0 "@agegr/pi-web" >/dev/null 2>&1; then
        err "检测到全局 @agegr/pi-web，与 @jmfederico/pi-web 命令名冲突，不能共存。"
        err "请先卸载: npm uninstall -g @agegr/pi-web"
        exit 1
    fi
}

update_pi() {
    local before after
    before="$(pkg_version "$PI_PKG")"
    [[ -n "$before" ]] || before="$(cli_version pi)"
    [[ -n "$before" ]] || before="(未安装)"
    log "更新 $PI_PKG@$PI_VERSION （当前 $before）..."
    run npm install -g --ignore-scripts "${PI_PKG}@${PI_VERSION}"
    hash -r 2>/dev/null || true
    after="$(pkg_version "$PI_PKG")"
    [[ -n "$after" ]] || after="$(cli_version pi)"
    log "pi agent: $before -> ${after:-未知}"
}

update_web() {
    log "获取官方 pi-web main 最新提交、更新 patches/base-commit、应用补丁并测试构建..."
    if [[ $DRY_RUN -eq 1 ]]; then
        log "[dry-run] git fetch --no-tags ${PI_WEB_UPSTREAM_URL:-https://github.com/jmfederico/pi-web.git} refs/heads/main；将提交 ID 写入 patches/base-commit"
        log "[dry-run] sh $project_root/scripts/sync.sh --local (应用新基线补丁)"
        log "[dry-run] npm ci --include=dev; npm test -- --maxWorkers=${PI_WEB_TEST_MAX_WORKERS:-4} --testTimeout=${PI_WEB_TEST_TIMEOUT_MS:-30000}; npm run build; 链接补丁版全局命令"
        return 0
    fi
    local upstream_url="${PI_WEB_UPSTREAM_URL:-https://github.com/jmfederico/pi-web.git}"
    local latest_commit baseline_tmp
    git -C "$project_root" fetch --no-tags "$upstream_url" refs/heads/main
    latest_commit=$(git -C "$project_root" rev-parse --verify 'FETCH_HEAD^{commit}')
    [[ "$latest_commit" =~ ^[0-9a-f]{40}$ ]] || { err "上游返回无效 commit ID"; return 1; }
    baseline_tmp=$(mktemp "$project_root/patches/base-commit.XXXXXXXX")
    printf '%s\n' "$latest_commit" > "$baseline_tmp"
    mv "$baseline_tmp" "$project_root/patches/base-commit"
    log "patches/base-commit -> $latest_commit"
    source "$project_root/scripts/install.sh"
    install_local web-only
    hash -r 2>/dev/null || true
}

update_relay() {
    log "更新全局 relay skill（npx skills add jmfederico/pi-web --skill relay -a pi -g）..."
    run npx --yes skills add jmfederico/pi-web --skill relay -a pi -g
}

doctor() {
    log "===== 更新后状态 ====="
    if command -v pi >/dev/null 2>&1; then
        local pv; pv="$(pi --version 2>/dev/null || echo 未知)"
        if ver_ge "$pv" "0.84.0"; then
            log "  [OK] pi $pv"
        else
            warn "  [warn] pi $pv 低于 pi-web 要求的 >= 0.84.0"
        fi
    else
        err "  [X] pi 命令不可用"
    fi

    if command -v pi-web >/dev/null 2>&1; then
        log "  [OK] pi-web $(cli_version pi-web || echo '')"
        if [[ $DRY_RUN -eq 0 ]]; then
            pi-web version || true
        fi
    else
        err "  [X] pi-web 命令不可用"
    fi

    if [[ $DRY_RUN -eq 0 ]]; then
        status || true
    fi
}

update() (
    PI_PKG="@earendil-works/pi-coding-agent"
    PI_VERSION="latest"
    UPDATE_PI=1
    UPDATE_WEB=1
    UPDATE_RELAY=0
    DRY_RUN=0

    # ---------- 参数 ----------
    for arg in "${ACTION_ARGS[@]}"; do
        case "$arg" in
            --pi-only)       UPDATE_WEB=0 ;;
            --web-only)      UPDATE_PI=0 ;;
            --update-relay)  UPDATE_RELAY=1 ;;
            --dry-run)       DRY_RUN=1 ;;
            -h|--help)       usage; exit 0 ;;
            *)
                err "未知参数: $arg"
                usage >&2
                exit 2
            ;;
        esac
    done

    if [[ $UPDATE_PI -eq 0 && $UPDATE_WEB -eq 0 ]]; then
        err "--pi-only 与 --web-only 不能同时使用"
        exit 2
    fi

    # ---------- 主流程 ----------
    log "开始更新 jmfederico/pi-web 与 pi agent"
    [[ $DRY_RUN -eq 1 ]] && log "dry-run 模式：不会真正安装"
    check_node
    if [[ $UPDATE_WEB -eq 1 ]]; then
        command -v git >/dev/null 2>&1 || { err "未找到 git"; exit 1; }
        check_conflict
    fi

    if [[ $UPDATE_PI -eq 1 ]]; then
        update_pi
    fi
    if [[ $UPDATE_WEB -eq 1 ]]; then
        update_web
    fi
    if [[ $UPDATE_RELAY -eq 1 ]]; then
        update_relay
    fi

    doctor
    log "更新完成"
    log "管理命令: $run_script {start|stop|update|status|logs}"
    log "使用新版本请手动执行: $run_script stop --port $PI_WEB_PORT，然后 $run_script start --port $PI_WEB_PORT"
)

case "$ACTION" in
    start)   start ;;
    stop)    stop ;;
    update)  update ;;
    status)  status ;;
    logs)    logs ;;
    *)
        echo "用法: $0 {start|stop|update|status|logs} [--port <port>]" >&2
        exit 2
    ;;
esac
