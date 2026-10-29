#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
config_file="$script_dir/dsh.conf"
token_capture_file="$script_dir/.dsh-web-token-captured"
proxy_script="$script_dir/dsh_token_proxy.py"

fail() { printf '%s\n' "$*" >&2; return 1; }

service_pid() {
    local service="$1" pid cmdline
    [[ -f "$script_dir/$service.pid" ]] || return 1
    pid="$(<"$script_dir/$service.pid")"
    [[ "$pid" =~ ^[0-9]+$ && -r "/proc/$pid/cmdline" ]] || return 1
    cmdline="$(tr '\0' ' ' <"/proc/$pid/cmdline")" || return 1
    case "$service" in
        magpie-serve) [[ "$cmdline" =~ (^|[[:space:]/])magpie[[:space:]]+serve([[:space:]]|$) ]] || return 1 ;;
        dsh-web) [[ "$cmdline" =~ (^|[[:space:]/])dsh[[:space:]]+web([[:space:]]|$) ]] || return 1 ;;
        dsh-token-proxy) [[ "$cmdline" == *"$proxy_script"* ]] || return 1 ;;
        *) return 1 ;;
    esac
    printf '%s\n' "$pid"
}

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
    local token="$1" temporary
    [[ -z "$token" || "$token" =~ ^[A-Za-z0-9_-]+$ ]] || return 1
    temporary="$(mktemp "$script_dir/.dsh.conf.XXXXXX")" || return 1
    # mktemp creates a private file; replace atomically without touching other settings.
    if awk '!/^[[:space:]]*dsh_token[[:space:]]*=/' "$config_file" >"$temporary" &&
        printf "dsh_token='%s'\n" "$token" >>"$temporary" && mv -f "$temporary" "$config_file"; then
        return 0
    fi
    rm -f "$temporary"
    fail '无法更新配置文件中的 dsh token。'
}

capture_dsh_output() {
    local line token_pattern='[?&]token=([A-Za-z0-9_-]+)'
    while IFS= read -r line || [[ -n "$line" ]]; do
        if [[ "$line" == *"dsh web: http"* && "$line" =~ $token_pattern ]]; then
            if write_token "${BASH_REMATCH[1]}"; then
                : >"$token_capture_file"
            fi
        fi
        printf '%s\n' "$line" | sed -E 's/([?&]token=)[A-Za-z0-9_-]+/\1[REDACTED]/g'
    done >>"$script_dir/dsh-web.log"
}

start_service() {
    local service="$1" pid attempt
    shift
    if pid="$(service_pid "$service")"; then
        printf '%s 已在运行，PID: %s\n' "$service" "$pid"
        return
    fi
    if [[ "$service" == dsh-web ]]; then
        rm -f "$token_capture_file"
        nohup "$@" > >(capture_dsh_output) 2>&1 </dev/null &
    else
        nohup "$@" >>"$script_dir/$service.log" 2>&1 </dev/null &
    fi
    pid=$!
    printf '%s\n' "$pid" >"$script_dir/$service.pid"
    sleep 1
    for attempt in {1..30}; do
        if ! service_pid "$service" >/dev/null; then
            rm -f "$script_dir/$service.pid"
            fail "$service 未能保持运行，请查看 $script_dir/$service.log"
            return 1
        fi
        if [[ "$service" != dsh-web || -f "$token_capture_file" ]]; then
            [[ "$service" != dsh-web ]] || rm -f "$token_capture_file"
            printf '%s 已后台启动，PID: %s\n' "$service" "$pid"
            return
        fi
        sleep 1
    done
    fail "dsh 已启动但未捕获 token，请查看 $script_dir/dsh-web.log"
}

stop_service() {
    local service="$1" pid attempt
    if ! pid="$(service_pid "$service")"; then
        rm -f "$script_dir/$service.pid"
        printf '%s 未运行。\n' "$service"
        return
    fi
    kill -TERM "$pid" || return 1
    for attempt in {1..10}; do
        if ! service_pid "$service" >/dev/null; then
            rm -f "$script_dir/$service.pid"
            printf '%s 已停止。\n' "$service"
            return
        fi
        sleep 1
    done
    fail "$service 仍在运行（PID: $pid），未强制终止。"
}

start() {
    [[ -f "$config_file" ]] || { fail '请先复制 dsh.conf.example 为 dsh.conf 并填写配置。'; return 1; }
    source "$config_file"
    [[ "${port:-}" =~ ^[0-9]{1,5}$ ]] || { fail 'port 必须是 1–65535 之间的整数。'; return 1; }
    port=$((10#$port))
    (( port >= 1 && port <= 65535 )) || { fail 'port 必须是 1–65535 之间的整数。'; return 1; }
    [[ -n "${server_ip:-}" ]] || { fail 'server_ip 不能为空。'; return 1; }
    local host_ip command_name upstream_port='' pid
    local base_path="/dsh-${port}/" public_url="https://${server_ip}:${port}/dsh-${port}/"
    local tls_cert="${tls_cert:-tls/fullchain.pem}" tls_key="${tls_key:-tls/privkey.pem}"
    [[ "$tls_cert" == /* ]] || tls_cert="$script_dir/$tls_cert"
    [[ "$tls_key" == /* ]] || tls_key="$script_dir/$tls_key"
    read -r host_ip _ <<<"$(hostname -I)"
    [[ -n "$host_ip" ]] || { fail '无法获取本机绑定地址。'; return 1; }
    for command_name in magpie dsh python3; do
        command -v "$command_name" >/dev/null || { fail "找不到 $command_name 命令。"; return 1; }
    done
    [[ -f "$proxy_script" ]] || { fail "找不到 $proxy_script"; return 1; }
    # Validate HTTPS before starting any services; never fall back to plaintext.
    python3 - "$tls_cert" "$tls_key" <<'PY'
import ssl, sys
try:
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(*sys.argv[1:])
except (OSError, ValueError) as error:
    sys.exit(f"无法加载 HTTPS 证书或私钥，请检查 dsh.conf 的 tls_cert / tls_key：{error}")
PY

    # Reuse a running backend's actual port when starting a missing proxy.
    if pid="$(service_pid dsh-web)"; then
        upstream_port="$(process_option "$pid" --port)" || { fail '无法读取运行中 dsh 的端口。'; return 1; }
        if [[ "$(process_option "$pid" --public-url)" != "$public_url" ]]; then
            fail "运行中 DSH 的访问地址与 $public_url 不一致；请在任务完成后安排 stop/start，当前进程保持运行。"
            return 1
        fi
        [[ "$upstream_port" =~ ^[0-9]+$ ]] || { fail '无法读取运行中 dsh 的端口。'; return 1; }
    else
        if service_pid dsh-token-proxy >/dev/null; then
            fail 'dsh 已退出但代理仍在运行，请先 stop 再 start。'
            return 1
        fi
        upstream_port="$(python3 -c 'import socket; s=socket.socket(); s.bind(("127.0.0.1", 0)); print(s.getsockname()[1]); s.close()')"
    fi
    if pid="$(service_pid dsh-token-proxy)" && [[ "$(process_option "$pid" --base-path)" != "$base_path" ]]; then
        fail "运行中代理尚未使用 $base_path；请安排代理维护，当前进程保持运行。"
        return 1
    fi
    start_service magpie-serve magpie serve
    start_service dsh-web dsh web --port "$upstream_port" --host 127.0.0.1 \
        --trusted-host "${server_ip}:${port}" --trusted-host "127.0.0.1:${upstream_port}" \
        --public-url "$public_url" --no-open
    start_service dsh-token-proxy python3 "$proxy_script" \
        --listen-host "$host_ip" --listen-port "$port" \
        --upstream-host 127.0.0.1 --upstream-port "$upstream_port" \
        --public-host "${server_ip}:${port}" --base-path "$base_path" --config "$config_file" \
        --tls-cert "$tls_cert" --tls-key "$tls_key"
    printf '访问地址：%s\n' "$public_url"
}

stop() {
    local service result=0
    for service in dsh-token-proxy dsh-web magpie-serve; do
        stop_service "$service" || result=1
    done
    if [[ -f "$config_file" ]] && ! service_pid dsh-web >/dev/null; then
        write_token '' || result=1
        rm -f "$token_capture_file"
    fi
    return "$result"
}

main() {
    if (( $# > 1 )) || [[ "${1:-start}" != start && "${1:-start}" != stop ]]; then
        printf '用法：%s [start|stop]\n' "$0" >&2
        return 2
    fi
    "${1:-start}"
}

if [[ "${BASH_SOURCE[0]}" == "$0" ]]; then
    main "$@"
fi
