#!/usr/bin/env bash
#
# PI WEB (jmfederico) 手动运行管理脚本
#
# 适用于无 systemd user 总线（容器 / WSL / 精简服务器）的环境，按官方
# “manual run” 方式分别启动 session daemon 和 web/API 服务。
#
# 用法:
#   ./scripts/pi-web-run-jmfederico.sh start                # 后台启动（sessiond + server）
#   ./scripts/pi-web-run-jmfederico.sh stop                 # 停止
#   ./scripts/pi-web-run-jmfederico.sh restart              # 先停止，再启动
#   ./scripts/pi-web-run-jmfederico.sh update [更新选项]    # 升级 pi 和 pi-web
#   ./scripts/pi-web-run-jmfederico.sh status               # 查看状态
#   ./scripts/pi-web-run-jmfederico.sh logs                 # 跟随服务日志
#
# 服务配置从仓库 data/pi-web.conf 读取（参见 pi-web.conf.example）：
#   PI_WEB_HOST      绑定地址，默认 0.0.0.0
#   PI_WEB_PORT      监听端口，默认 8024
#   PI_WEB_PASSWORD  设置后（若支持）开启访问保护

if [ -z "${BASH_VERSION:-}" ]; then
    exec bash "$0" "$@"
fi
set -euo pipefail

script_file="$(readlink -f "${BASH_SOURCE[0]}")"
project_root="$(cd "$(dirname "$script_file")/.." && pwd)"
config_file="$project_root/data/pi-web.conf"
# Service settings come only from the local config, not the calling shell.
unset PI_WEB_PORT PI_WEB_HOST PI_WEB_PASSWORD PI_WEB_DATA_DIR PI_WEB_RUN_DIR PI_WEB_VOICE_INPUT_ENABLED \
    PI_WEB_SESSIOND_SOCKET PI_WEB_SESSIOND_PORT PI_WEB_SESSIOND_URL
if [[ -f "$config_file" ]]; then
    set -a
    source "$config_file"
    set +a
fi
PI_WEB_HOST="${PI_WEB_HOST:-0.0.0.0}"
PI_WEB_PORT="${PI_WEB_PORT:-8024}"
PI_WEB_PASSWORD="${PI_WEB_PASSWORD:-}"
export PI_WEB_VOICE_INPUT_ENABLED="${PI_WEB_VOICE_INPUT_ENABLED-false}"

usage() {
    cat <<'EOF'
PI WEB (jmfederico) 手动运行管理脚本

用法:
  ./scripts/pi-web-run-jmfederico.sh start                # 后台启动（sessiond + server）
  ./scripts/pi-web-run-jmfederico.sh stop                 # 停止
  ./scripts/pi-web-run-jmfederico.sh restart              # 先停止，再启动
  ./scripts/pi-web-run-jmfederico.sh update [更新选项]    # 升级 pi 和 pi-web
  ./scripts/pi-web-run-jmfederico.sh status               # 查看状态
  ./scripts/pi-web-run-jmfederico.sh logs                 # 跟随服务日志
  ./scripts/pi-web-run-jmfederico.sh --help               # 显示本帮助

参数:
  -h, --help       显示本帮助并退出
  本地配置：仓库 data/pi-web.conf，示例 PI_WEB_PORT=8080（不提交 Git）。

更新选项:
  --pi-only        只升级 Pi Coding Agent
  --web-only       只升级 @jmfederico/pi-web
  --update-relay   同步升级全局 relay skill
  --dry-run        只显示将执行的升级操作
  更新不启停服务；更新完成后需要手动执行 restart 才能使用新版本。

配置文件字段（未填写时使用默认值）:
  PI_WEB_HOST      绑定地址，默认 0.0.0.0
  PI_WEB_PORT      监听端口，默认 8024
  PI_WEB_PASSWORD  设置后（若支持）开启访问保护
  PI_WEB_VOICE_INPUT_ENABLED  语音输入入口开关，true/false，默认 false
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
        --port|--port=*)
            echo "错误：不再支持 --port，请在 $config_file 中设置 PI_WEB_PORT" >&2
            exit 2
        ;;
        start|stop|restart|update|status|logs)
            if [[ -n "$ACTION" ]]; then
                echo "错误：一次只能执行一个命令（已指定 $ACTION，又收到 $1）" >&2
                exit 2
            fi
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

if [[ "$ACTION" != update && ${#ACTION_ARGS[@]} -gt 0 ]]; then
    echo "错误：不支持的参数 ${ACTION_ARGS[*]}；服务配置请填写 $config_file" >&2
    exit 2
fi

# 端口同时作为实例标识，避免不同 Web 服务共享 daemon 状态和 PID。
if [[ ! "$PI_WEB_PORT" =~ ^[0-9]{1,5}$ ]] || (( 10#$PI_WEB_PORT < 1 || 10#$PI_WEB_PORT > 65535 )); then
    echo "错误：端口必须是 1–65535 的整数" >&2
    exit 2
fi
case "$PI_WEB_VOICE_INPUT_ENABLED" in
    true|false) ;;
    *) echo "错误：PI_WEB_VOICE_INPUT_ENABLED 必须为 true 或 false" >&2; exit 2 ;;
esac
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

    # Check before creating either process, so a busy port cannot leave a new daemon behind.
    if ! service_running pi-web-server "$server_pid"; then
        check_port_free
    fi

    # 会话守护进程
    if ! service_running pi-web-sessiond "$sessiond_pid"; then
        echo "启动 pi-web-sessiond ..."
        "${launcher[@]}" pi-web-sessiond </dev/null >"$sessiond_log" 2>&1 &
        echo $! > "$sessiond_pid"
    else
        echo "pi-web-sessiond 已在运行 (PID $(cat "$sessiond_pid"))"
    fi

    # Web/API 服务
    if ! service_running pi-web-server "$server_pid"; then
        echo "启动 pi-web-server -> http://$PI_WEB_HOST:$PI_WEB_PORT"
        (
            export PI_WEB_PORT PI_WEB_HOST
            if [[ -n "$PI_WEB_PASSWORD" ]]; then export PI_WEB_PASSWORD; fi
            # Keep credentials out of launcher arguments and preserve the tracked PID.
            exec "${launcher[@]}" pi-web-server
        ) </dev/null >"$server_log" 2>&1 &
        echo $! > "$server_pid"
    else
        echo "pi-web-server 已在运行 (PID $(cat "$server_pid"))"
    fi

    # Require both owned processes and HTTP readiness; a surviving daemon alone
    # must not make a failed Web startup look successful.
    for _ in $(seq 1 30); do
        if service_running pi-web-server "$server_pid" && service_running pi-web-sessiond "$sessiond_pid" && http_ready; then
            status
            return 0
        fi
        sleep 0.5
    done
    status || true
    echo "错误：服务未就绪，请检查 $server_log 和 $sessiond_log" >&2
    return 1
}

probe_url() {
    local host="$PI_WEB_HOST"
    case "$host" in
        0.0.0.0|'') host=127.0.0.1 ;;
        ::|'[::]') host='[::1]' ;;
        *:*) [[ "$host" == \[*\] ]] || host="[$host]" ;;
    esac
    printf 'http://%s:%s/' "$host" "$PI_WEB_PORT"
}

http_ready() {
    local code
    code=$(curl --noproxy '*' -s -o /dev/null -w '%{http_code}' --max-time 1 "$(probe_url)" 2>/dev/null) || return 1
    [[ "$code" =~ ^[23][0-9][0-9]$ || "$code" == 401 || "$code" == 403 ]]
}

service_running() {
    local name="$1" pidfile="$2" pid candidate
    if [[ -f "$pidfile" ]]; then
        pid=$(cat "$pidfile")
        if [[ "$pid" =~ ^[1-9][0-9]*$ && "$pid" -gt 1 ]] && process_running "$pid"; then
            if [[ ! -d /proc ]] || is_instance_process "$pid" "$name"; then return 0; fi
        fi
    fi
    # Recover ownership before checking the port or launching a replacement.
    # A missing PID file does not mean that the daemon and its sessions stopped.
    for candidate in /proc/[0-9]*/cmdline; do
        pid="${candidate%/cmdline}"; pid="${pid##*/}"
        if is_instance_process "$pid" "$name" && process_running "$pid"; then
            mkdir -p "$(dirname "$pidfile")" || return 1
            printf '%s\n' "$pid" > "$pidfile" || return 1
            return 0
        fi
    done
    return 1
}

# Match both executable identity and this instance's run directory before recovering a PID.
is_instance_process() {
    local pid="$1" name="$2" arg entry matched=0
    [[ "$pid" =~ ^[1-9][0-9]*$ && "$pid" -gt 1 ]] || return 1
    [[ -r "/proc/$pid/cmdline" && -r "/proc/$pid/environ" ]] || return 1
    while IFS= read -r -d '' arg; do
        if [[ "${arg##*/}" == "$name" ]]; then matched=1; fi
    done < "/proc/$pid/cmdline"
    [[ $matched -eq 1 ]] || return 1
    while IFS= read -r -d '' entry; do
        [[ "$entry" == "PI_WEB_RUN_DIR=$log_dir" ]] && return 0
    done < "/proc/$pid/environ"
    return 1
}

process_running() {
    local pid="$1" stat rest
    kill -0 "$pid" 2>/dev/null || return 1
    # A zombie has exited and released its sockets; only its parent can reap it.
    if [[ -r "/proc/$pid/stat" ]]; then
        stat=$(cat "/proc/$pid/stat" 2>/dev/null) || return 1
        rest="${stat##*) }"
        [[ "${rest%% *}" == Z ]] && return 1
    fi
    return 0
}

stop_pid() {
    local name="$1" pidfile="$2" pid candidate attempt signal attempts recorded="" failed=0
    local -a pids=()
    if [[ -f "$pidfile" ]]; then
        recorded=$(cat "$pidfile")
        if [[ "$recorded" =~ ^[1-9][0-9]*$ && "$recorded" -gt 1 ]] && process_running "$recorded"; then
            if [[ ! -d /proc ]] || is_instance_process "$recorded" "$name"; then
                pids+=("$recorded")
            else
                echo "忽略不属于本实例的过期 PID: $recorded ($name)" >&2
            fi
        fi
    fi
    # PID files can disappear or contain the PID of an exited launcher.
    for candidate in /proc/[0-9]*/cmdline; do
        pid="${candidate%/cmdline}"; pid="${pid##*/}"
        [[ "$pid" == "$recorded" ]] && continue
        if is_instance_process "$pid" "$name" && process_running "$pid"; then
            pids+=("$pid")
            echo "找到本实例遗留进程: $name (PID $pid)"
        fi
    done
    for pid in "${pids[@]}"; do
        signal=TERM
        # Give graceful shutdown 3 seconds, then allow 2 seconds after KILL.
        for attempts in 30 20; do
            kill -s "$signal" "$pid" 2>/dev/null || true
            for ((attempt=0; attempt<attempts; attempt++)); do
                process_running "$pid" || break
                sleep 0.1
            done
            process_running "$pid" || break
            signal=KILL
        done
        if process_running "$pid"; then
            echo "错误：无法停止 $name (PID $pid)，保留 PID 文件" >&2
            printf '%s\n' "$pid" > "$pidfile"
            failed=1
        else
            echo "已停止 $name (PID $pid)"
        fi
    done
    [[ $failed -eq 0 ]] || return 1
    rm -f "$pidfile"
}

stop() {
    stop_pid "pi-web-server"   "$server_pid"
    stop_pid "pi-web-sessiond" "$sessiond_pid"
}

status() {
    local any=0
    if service_running pi-web-server "$server_pid"; then
        echo "pi-web-server   运行中 (PID $(cat "$server_pid")) -> http://$PI_WEB_HOST:$PI_WEB_PORT"
        curl --noproxy '*' --max-time 1 -s -o /dev/null -w "   HTTP 状态: %{http_code}\n" "$(probe_url)" 2>/dev/null || echo "   探测失败"
        any=1
    else
        echo "pi-web-server   未在运行"
    fi
    if service_running pi-web-sessiond "$sessiond_pid"; then
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
        try {
            const result = JSON.parse(require("node:fs").readFileSync(0, "utf8") || "{}");
            process.stdout.write(result.dependencies?.[process.argv[1]]?.version || "");
        } catch { /* Missing or invalid npm metadata: let the caller try the CLI. */ }
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
        log "[dry-run] sh $project_root/scripts/sync.sh (同步并应用新基线补丁)"
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
    log "管理命令: $run_script {start|stop|restart|update|status|logs}"
    log "使用新版本请手动执行: $run_script restart"
)

case "$ACTION" in
    start)   start ;;
    stop)    stop ;;
    restart) stop; start ;;
    update)  update ;;
    status)  status ;;
    logs)    logs ;;
    *)
        echo "用法: $0 {start|stop|restart|update|status|logs}" >&2
        exit 2
    ;;
esac
