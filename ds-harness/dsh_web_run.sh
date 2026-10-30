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

prepare_runtime() {
    python3 -B - "$script_dir" <<'PY'
import sys
from pathlib import Path
root = Path(sys.argv[1]).resolve()
logs = root / 'log'
if logs.is_symlink():
    sys.exit(f'运行目录不能是符号链接：{logs}')
logs.mkdir(mode=0o700, exist_ok=True)
logs.chmod(0o700)
names = [f'{service}.{suffix}' for service in ('magpie-serve', 'dsh-web', 'dsh-token-proxy')
         for suffix in ('log', 'pid', 'identity')]
names += ['.dsh-web-token-captured']
sources = [root / name for name in names] + sorted(root.glob('.nginx-[0-9]*')) + sorted(root.glob('.dsh.conf.*'))
pending = []
for source in sources:
    if source.is_symlink() and source.readlink() == Path('log') / source.name:
        continue  # A running old Nginx still uses its original absolute paths.
    if not source.exists() and not source.is_symlink():
        continue
    target = logs / source.name
    if source.is_symlink() or target.exists() or target.is_symlink():
        sys.exit(f'运行文件迁移冲突，保留原文件：{source} -> {target}')
    pending.append((source, target))
for source, target in pending:
    # All paths are direct children of the resolved project/runtime directories.
    if not (source.parent == root and target.parent == logs):
        raise ValueError("state verification failed")
    directory = source.is_dir()
    source.rename(target)  # Open log descriptors continue writing to the same inode.
    if directory:
        source.symlink_to(Path('log') / source.name, target_is_directory=True)
PY
}

# PID files remain numeric for old tooling. Only a matching private identity record
# authorizes reuse/signalling; a live legacy PID requires explicit maintenance.
process_state() {
    python3 -B /dev/fd/3 "$script_dir" "$log_dir" "$config_file" "$@" 3<<'PYTHON'
import ctypes, errno, fcntl, hashlib, ipaddress, json, os, platform, re, shlex, shutil, signal, sys, time, uuid
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote_plus
root, logs, config = map(Path, sys.argv[1:4])
operation, service, *args = sys.argv[4:]
pidfile = logs / (service + '.pid')
statefile = logs / (service + '.identity')
readyfile = logs / '.dsh-web-token-captured'

def atomic(path, value):
    temporary = path.with_name(path.name + '.' + uuid.uuid4().hex)
    try:
        with temporary.open('x') as stream:
            os.chmod(temporary, 0o600)
            stream.write(value)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)

def state_lock():
    stream = (logs / '.process-state.lock').open('a')
    fcntl.flock(stream, fcntl.LOCK_EX)
    return stream

def save_token(token):
    if token and not re.fullmatch(r'[A-Za-z0-9_-]+', token):
        raise ValueError('invalid token')
    text = re.sub(r'^\s*dsh_token\s*=.*\n?', '', config.read_text(), flags=re.M)
    atomic(config, text.rstrip('\n') + "\ndsh_token='" + token + "'\n")


def redact_tokens(line):
    def replace(match):
        return (match[1] + match[2] + '=[REDACTED]' if unquote_plus(match[2]) == 'token'
                else match[0])
    return re.sub(r'([?&])([^&\s=]+)=([^&\s]+)', replace, line)


def snapshot(pid):
    proc = Path('/proc') / str(pid)
    stat = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
    if stat[0] == 'Z':
        raise ProcessLookupError()
    return dict(pid=pid, start=stat[19], boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                uid=proc.stat().st_uid, argv=(proc / 'cmdline').read_bytes().split(b'\0')[:-1])

def current():
    pid = int(pidfile.read_text().strip())
    if pid <= 1:
        raise ValueError('unsafe PID')
    return snapshot(pid)

def owned(now):
    state = json.loads(statefile.read_text())
    env = (Path('/proc') / str(now['pid']) / 'environ').read_bytes().split(b'\0')
    if not (state['root'] == str(root) and state['service'] == service):
        raise ValueError("state verification failed")
    if not (state['identity'] == {**now, 'argv': [os.fsdecode(x) for x in now['argv']]}):
        raise ValueError("state verification failed")
    if not (('DSH_LAUNCH_ID=' + state['launch']).encode() in env):
        raise ValueError("state verification failed")
    if not (('DSH_LAUNCH_ROOT=' + str(root)).encode() in env):
        raise ValueError("state verification failed")
    return state

def native_pidfd(name, *arguments):
    # Missing Python wrappers do not imply missing kernel support. Never use kill.
    if sys.platform != 'linux':
        raise OSError(errno.ENOSYS, 'pidfds require Linux')
    libc = ctypes.CDLL(None, use_errno=True)
    function = getattr(libc, name, None)
    if function is not None:
        function.argtypes = ([ctypes.c_int, ctypes.c_uint] if name == 'pidfd_open' else
                             [ctypes.c_int, ctypes.c_int, ctypes.c_void_p, ctypes.c_uint])
        function.restype = ctypes.c_int
        result = function(*arguments)
    else:
        # These syscall numbers are verified only for these Linux ABIs.
        if platform.machine() not in ('x86_64', 'aarch64') or ctypes.sizeof(ctypes.c_void_p) != 8:
            raise OSError(errno.ENOSYS, 'unsupported pidfd syscall architecture')
        syscall = libc.syscall
        syscall.restype = ctypes.c_long
        number = {'pidfd_open': 434, 'pidfd_send_signal': 424}[name]
        result = syscall(ctypes.c_long(number), *(ctypes.c_long(x or 0) for x in arguments))
    if result == -1:
        error = ctypes.get_errno()
        raise OSError(error, os.strerror(error))
    return result

def open_pidfd(pid):
    wrapper = getattr(os, 'pidfd_open', None)
    return wrapper(pid, 0) if wrapper is not None else native_pidfd('pidfd_open', pid, 0)

def send_pidfd(fd, sig):
    wrapper = getattr(signal, 'pidfd_send_signal', None)
    return wrapper(fd, sig, None, 0) if wrapper is not None else native_pidfd('pidfd_send_signal', fd, sig, None, 0)

def launch_command(executable, tail):
    path = Path(executable).resolve()
    with path.open('rb') as stream:
        header = stream.readline(256)
    if header.startswith(b'\x7fELF'):
        return path, [executable, *tail]
    if not header.startswith(b'#!'):
        raise ValueError('unsupported executable format')
    parts = os.fsdecode(header[2:]).strip().split(None, 1)
    interpreter = parts[0]
    options = parts[1:]
    if Path(interpreter).resolve() == Path('/usr/bin/env').resolve():
        if not options:
            raise ValueError('missing env interpreter')
        words = shlex.split(options[0][3:]) if options[0].startswith('-S ') else options
        if not words or words[0].startswith('-') or '=' in words[0]:
            raise ValueError('unsupported env shebang')
        interpreter = shutil.which(words[0])
        if interpreter is None:
            raise ValueError('missing shebang interpreter')
        options = words[1:]
    return Path(interpreter).resolve(), [interpreter, *options, executable, *tail]

def settled_command(now, expected_exe, expected_argv):
    argv = [os.fsdecode(x) for x in now['argv']]
    return (len(argv) == len(expected_argv) and
            Path(shutil.which(argv[0]) or argv[0]).resolve() == expected_exe and argv[1:] == expected_argv[1:] and
            (Path('/proc') / str(now['pid']) / 'exe').resolve(strict=True) == expected_exe)

def url_endpoint(value):
    url = urlsplit(value)
    if url.scheme not in ('http', 'https') or not url.hostname or url.username is not None or url.password is not None or url.fragment:
        raise ValueError('invalid startup URL')
    host = url.hostname.lower()
    try:
        host = str(ipaddress.ip_address(host))
    except ValueError:
        pass
    return (url.scheme, host, url.port if url.port is not None else
            (443 if url.scheme == 'https' else 80), url.path or '/')

def startup_token(value, endpoints):
    try:
        if url_endpoint(value) not in endpoints:
            return None
        query = parse_qs(urlsplit(value).query, keep_blank_values=True)
        tokens = query.get('token', [])
        if len(tokens) == 1 and re.fullmatch(r'[A-Za-z0-9_-]+', tokens[0]):
            return tokens[0]
    except ValueError:
        pass  # Malformed unrelated output must not terminate the log reader.
    return None

try:
    if int(Path('/proc/self/stat').read_text().split()[0]) != os.getpid():
        raise ValueError('/proc PID namespace mismatch')
    if operation == 'preflight':
        fd = open_pidfd(os.getpid())
        try:
            send_pidfd(fd, 0)
        finally:
            os.close(fd)
    elif operation == 'record':
        pid, launch, executable, *tail = args
        expected_exe, expected_argv = launch_command(executable, tail)
        # Wait for nohup/shebang exec, accepting only the exact requested argv.
        for attempt in range(100):
            now = snapshot(int(pid))
            argv = [os.fsdecode(x) for x in now['argv']]
            if settled_command(now, expected_exe, expected_argv):
                break
            time.sleep(.02)
        else:
            raise ValueError('launch argv did not settle')
        state = dict(root=str(root), service=service, launch=launch,
                     identity={**now, 'argv': argv})
        atomic(statefile, json.dumps(state))
        owned(now)
    elif operation == 'capture':
        launch, advertised, local = args
        captured = False
        endpoints = {url_endpoint(value) for value in (advertised, local) if value}
        sys.stdin.reconfigure(errors='replace')
        for line in sys.stdin:
            clean = re.sub(r'\x1b\[[0-9;]*m', '', line).strip()
            match = re.fullmatch(r'dsh web: (https?://[^\s]+)', clean)
            if match and not captured:
                token = startup_token(match[1], endpoints)
                if token is not None:
                    # Output may precede the parent's identity publication.
                    for attempt in range(100):
                        try:
                            state = owned(current())
                            if state['launch'] != launch:
                                raise ValueError('replaced launch')
                            break
                        except (FileNotFoundError, ProcessLookupError, ValueError):
                            time.sleep(.02)
                    else:
                        raise ValueError('missing launch identity')
                    with state_lock():
                        if not (owned(current()) == state):
                            raise ValueError("state verification failed")
                        save_token(token)
                        atomic(readyfile, json.dumps(dict(state=state, token_sha256=hashlib.sha256(token.encode()).hexdigest())))
                    captured = True
            print(redact_tokens(line), end='', flush=True)
    elif operation == 'write-token':
        with state_lock():
            save_token(args[0])
    else:
        try:
            now = current()
        except (FileNotFoundError, ProcessLookupError):
            sys.exit(1)
        state = owned(now)
        if operation == 'signal':
            # Pin the process before the final check: PID reuse cannot redirect TERM.
            fd = open_pidfd(now['pid'])
            try:
                with state_lock():
                    if not (owned(current()) == state):
                        raise ValueError("state verification failed")
                    send_pidfd(fd, signal.SIGTERM)
            finally:
                os.close(fd)
        elif operation == 'ready':
            ready = json.loads(readyfile.read_text())
            if not (ready['state'] == state):
                raise ValueError("state verification failed")
            token = re.search(r"^dsh_token='([A-Za-z0-9_-]+)'$", config.read_text(), re.M).group(1)
            if not (ready['token_sha256'] == hashlib.sha256(token.encode()).hexdigest()):
                raise ValueError("state verification failed")
        else:
            print(now['pid'])
except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError) as error:
    if operation == 'preflight':
        print(f'pidfd 检查失败，请检查 Linux 内核和系统调用权限 ({type(error).__name__})', file=sys.stderr)
    elif operation != 'ready':
        print(f'{service}: 无法验证进程身份，保留现场；请安排维护 ({type(error).__name__})', file=sys.stderr)
    sys.exit(2)
PYTHON
}

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
    python3 -B - "$script_dir" <<'PY' || return 1
import sys
sys.path.insert(0, sys.argv[1])
from dsh_nginx import require_local_nginx
try:
    require_local_nginx()
except (OSError, ValueError) as error:
    sys.exit(f"dsh nginx: {error}")
PY
    [[ -f "$config_file" ]] || { fail '请先运行 dsh_install.sh 创建 data/dsh.conf，或复制示例配置到该位置。'; return 1; }
    local listen_host=''
    source "$config_file"
    listen_host="${listen_host:-${server_ip:-}}"
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
    tls_dir="$(python3 - "$server_ip" "$script_dir/data/tls" "$listen_host" <<'PY'
import ipaddress, re, ssl, sys
from pathlib import Path
address = sys.argv[1]
try:
    ipaddress.ip_address(address)
except ValueError:
    if not (len(address) <= 253 and all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in address.split('.'))):
        sys.exit('server_ip 必须是 IP 或域名，不得包含协议、端口或路径。')
try:
    ipaddress.ip_address(sys.argv[3])
except ValueError:
    sys.exit('listen_host 必须是 IPv4 或 IPv6 地址；域名或 NAT 部署请显式填写本机监听 IP。')
directory = Path(sys.argv[2]) / address.lower().replace(':', '_')
cert, key = directory / 'fullchain.pem', directory / 'privkey.pem'
try:
    ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, key)
except (OSError, ValueError) as error:
    sys.exit(f"无法加载地址目录中的 HTTPS 证书或私钥：{cert} / {key}。请先运行 dsh_cert.sh：{error}")
print(directory)
PY
)" || return 1
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
