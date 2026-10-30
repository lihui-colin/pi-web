#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_file="$script_dir/data/dsh.conf"
# Preserve operability until the installer copies a legacy configuration.
if [[ ! -e "$config_file" && -f "$script_dir/dsh.conf" ]]; then
    config_file="$script_dir/dsh.conf"
fi
log_dir="$script_dir/log"
token_capture_file="$log_dir/.dsh-web-token-captured"
proxy_script="$script_dir/dsh_nginx.py"

fail() { printf '%s\n' "$*" >&2; return 1; }

# Keep shell orchestration separate from process and configuration checks.
process_state() {
    python3 -B "$script_dir/dsh_runtime.py" "$script_dir" "$log_dir" "$config_file" "$@"
}

prepare_runtime() { process_state prepare dsh-web; }

service_pid() { process_state check "$1"; }

# Read a named option without splitting arguments containing spaces.
process_option() {
    local pid="$1" option="$2" index
    local -a arguments
    mapfile -d '' -t arguments <"/proc/$pid/cmdline" || return 1
    for ((index=0; index<${#arguments[@]}-1; index++)); do
        if [[ "${arguments[index]}" == "$option" ]]; then
            printf '%s\n' "${arguments[index+1]}"
            return 0
        fi
    done
    return 1
}

write_token() {
    process_state write-token dsh-web "$1"
}

capture_dsh_output() {
    process_state capture dsh-web "$@" >>"$log_dir/dsh-web.log"
}

start_service() {
    local service="$1" pid attempt status launch executable advertised='' local_url=''
    shift
    if pid="$(service_pid "$service")"; then
        printf '%s 已在运行，PID: %s\n' "$service" "$pid"
    else
        status=$?
        [[ "$status" == 1 ]] || return "$status"
        executable="$(command -v "$1")" || return 1
        executable="$(python3 -c 'import os, sys; print(os.path.abspath(sys.argv[1]))' "$executable")" || return 1
        set -- "$executable" "${@:2}"
        launch="$(python3 -c 'import uuid; print(uuid.uuid4().hex)')"
        # The former process is gone; do not let early output observe its identity.
        rm -f "$log_dir/$service.identity"
        if [[ "$service" == dsh-web ]]; then
            write_token '' || return 1
            rm -f "$token_capture_file"
            local -a command=("$@")
            for ((attempt=0; attempt<${#command[@]}-1; attempt++)); do
                case "${command[attempt]}" in
                    --public-url) advertised="${command[attempt+1]}" ;;
                    --port) local_url="http://127.0.0.1:${command[attempt+1]}/" ;;
                esac
            done
            DSH_LAUNCH_ID="$launch" DSH_LAUNCH_ROOT="$script_dir" nohup "$@" 9>&- \
                > >(exec 9>&-; capture_dsh_output "$launch" "$advertised" "$local_url") 2>&1 </dev/null &
        else
            DSH_LAUNCH_ID="$launch" DSH_LAUNCH_ROOT="$script_dir" nohup "$@" 9>&- >>"$log_dir/$service.log" 2>&1 </dev/null &
        fi
        pid=$!
        printf '%s\n' "$pid" >"$log_dir/$service.pid"
        process_state record "$service" "$pid" "$launch" "$executable" "${@:2}" || return 1
        [[ "$service" == dsh-web ]] || sleep 1
    fi
    for ((attempt=0; attempt<${DSH_READY_ATTEMPTS:-30}; attempt++)); do
        service_pid "$service" >/dev/null || { fail "$service 未能保持运行，请查看 $log_dir/$service.log"; return 1; }
        if [[ "$service" != dsh-web ]] || process_state ready dsh-web; then
            printf '%s 已后台启动，PID: %s\n' "$service" "$pid"
            return 0
        fi
        sleep "${DSH_READY_INTERVAL:-1}"
    done
    fail "dsh 已启动但 token 尚未就绪，请重试 start 等待同一后端；查看 $log_dir/dsh-web.log"
}

stop_service() {
    local service="$1" pid attempt status
    if pid="$(service_pid "$service")"; then
        process_state signal "$service" || return 1
    else
        status=$?
        [[ "$status" == 1 ]] || return "$status"
    fi
    for attempt in {1..10}; do
        if service_pid "$service" >/dev/null; then
            sleep 1
        else
            status=$?
            [[ "$status" == 1 ]] || return "$status"
            rm -f "$log_dir/$service.pid" "$log_dir/$service.identity"
            printf '%s 已停止。\n' "$service"
            return 0
        fi
    done
    fail "$service 仍在运行（PID: $pid），未强制终止。"
}

start() {
    command -v python3 >/dev/null || { fail '找不到 python3 命令。'; return 1; }
    [[ -f "$proxy_script" ]] || { fail "找不到 $proxy_script"; return 1; }
    # Share the direct supervisor's local binary and version checks before launch.
    process_state check-nginx dsh-web || return 1
    [[ -f "$config_file" ]] || { fail '请先运行 dsh_install.sh 创建 data/dsh.conf，或复制示例配置到该位置。'; return 1; }
    local listen_host=''
    source "$config_file"
    # Keep state beside the launcher even when a DSH session inherits old roots.
    export DSH_HOME="$script_dir/data/.dsh"
    export DSH_AGENTS_HOME="$script_dir/data/.agents"
    [[ "${port:-}" =~ ^[0-9]{1,5}$ ]] || { fail 'port 必须是 1–65535 之间的整数。'; return 1; }
    port=$((10#$port))
    (( port >= 1 && port <= 65535 )) || { fail 'port 必须是 1–65535 之间的整数。'; return 1; }
    [[ -n "${server_ip:-}" ]] || { fail 'server_ip 不能为空。'; return 1; }
    local command_name upstream_port='' pid status
    local public_host="$server_ip"
    [[ "$server_ip" != *:* ]] || public_host="[$server_ip]"
    local public_url="https://${public_host}:${port}/" cookie_prefix="dsh${port}_"
    local tls_dir tls_cert tls_key
    # Validate the address and HTTPS together before starting any service.
    local address_selection
    address_selection="$(process_state config dsh-web "$server_ip" "$script_dir/data/tls" "$listen_host")" || return 1
    listen_host="${address_selection%%$'\n'*}"
    tls_dir="${address_selection#*$'\n'}"
    tls_cert="$tls_dir/fullchain.pem"
    tls_key="$tls_dir/privkey.pem"
    for command_name in magpie dsh; do
        command -v "$command_name" >/dev/null || { fail "找不到 $command_name 命令。"; return 1; }
    done
    prepare_runtime || return 1
    # Reject ambiguous live legacy state before starting or changing any service.
    for command_name in magpie-serve dsh-web dsh-token-proxy; do
        if service_pid "$command_name" >/dev/null; then :; else
            [[ "$?" == 1 ]] || return 1
        fi
    done
    # Reuse a running backend's actual port when starting a missing proxy.
    if pid="$(service_pid dsh-web)"; then
        upstream_port="$(process_option "$pid" --port)" || { fail '无法读取运行中 dsh 的端口。'; return 1; }
        if [[ "$(process_option "$pid" --public-url)" != "$public_url" ]]; then
            fail "运行中 DSH 的访问地址与 $public_url 不一致；请在任务完成后安排 stop/start，当前进程保持运行。"
            return 1
        fi
        [[ "$upstream_port" =~ ^[0-9]+$ ]] || { fail '无法读取运行中 dsh 的端口。'; return 1; }
    else
        status=$?
        [[ "$status" == 1 ]] || return "$status"
        if service_pid dsh-token-proxy >/dev/null; then
            fail 'dsh 已退出但代理仍在运行，请先 stop 再 start。'
            return 1
        else
            status=$?
            [[ "$status" == 1 ]] || return "$status"
        fi
        upstream_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
    fi
    if pid="$(service_pid dsh-token-proxy)"; then
        if [[ "$(process_option "$pid" --cookie-prefix || true)" != "$cookie_prefix" ||
              "$(process_option "$pid" --listen-host || true)" != "$listen_host" ]]; then
            fail "运行中代理的监听地址或 Cookie 前缀与配置不一致；请安排代理维护，当前进程保持运行。"
            return 1
        fi
    else
        status=$?
        [[ "$status" == 1 ]] || return "$status"
    fi
    start_service magpie-serve magpie serve || return 1
    start_service dsh-web dsh web --port "$upstream_port" --host 127.0.0.1 \
        --trusted-host "${public_host}:${port}" --trusted-host "127.0.0.1:${upstream_port}" \
        --public-url "$public_url" --no-open || return 1
    start_service dsh-token-proxy python3 "$proxy_script" \
        --listen-host "$listen_host" --listen-port "$port" \
        --upstream-host 127.0.0.1 --upstream-port "$upstream_port" \
        --public-host "${public_host}:${port}" --cookie-prefix "$cookie_prefix" --config "$config_file" \
        --tls-cert "$tls_cert" --tls-key "$tls_key" || return 1
    printf '访问地址：%s\n' "$public_url"
}

stop() {
    local service result=0 status
    prepare_runtime || return 1
    for service in dsh-token-proxy dsh-web magpie-serve; do
        stop_service "$service" || result=1
    done
    if [[ "$result" == 0 && -f "$config_file" ]]; then
        if service_pid dsh-web >/dev/null; then
            result=1
        else
            status=$?
            [[ "$status" == 1 ]] || return "$status"
            write_token '' || return 1
            rm -f "$token_capture_file"
        fi
    fi
    return "$result"
}

main() (
    if (( $# > 1 )) || [[ "${1:-start}" != start && "${1:-start}" != stop ]]; then
        printf '用法：%s [start|stop]\n' "$0" >&2
        return 2
    fi
    command -v flock >/dev/null || { fail '找不到 flock 命令（util-linux）。'; return 1; }
    umask 077
    [[ ! -L "$log_dir" ]] || { fail '运行目录不能是符号链接。'; return 1; }
    mkdir -p -m 700 "$log_dir"
    chmod 700 "$log_dir"
    [[ ! -L "$log_dir/.launcher.lock" ]] || { fail '启停锁不能是符号链接。'; return 1; }
    exec 9>>"$log_dir/.launcher.lock"
    flock -n 9 || { fail '已有启停操作正在进行，请待其完成后重试。'; return 1; }
    process_state preflight dsh-web || return $?
    "${1:-start}"
)

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
