#!/usr/bin/env python3
"""Launcher helpers: process ownership, token capture, migration and startup checks."""

import ctypes, errno, fcntl, hashlib, ipaddress, json, os, platform, re, secrets, shlex, shutil, signal, socket, ssl, stat, subprocess, sys, time, uuid
from pathlib import Path
from urllib.parse import urlsplit, parse_qs, unquote_plus

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
    return re.sub(r"([?&])([^&\s=]+)=([^&\s\"']+)", replace, line)


def snapshot(pid):
    proc = Path('/proc') / str(pid)
    try:
        stat = (proc / 'stat').read_text().rsplit(')', 1)[1].split()
        if stat[0] == 'Z':
            raise ProcessLookupError()
        return dict(pid=pid, start=stat[19], boot=Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
                    uid=proc.stat().st_uid, argv=(proc / 'cmdline').read_bytes().split(b'\0')[:-1])
    except FileNotFoundError:
        if not proc.exists():
            raise ProcessLookupError() from None
        raise

def current(recover=True):
    pid = int(pidfile.read_text().strip())
    if pid <= 1:
        raise ValueError('unsafe PID')
    try:
        return snapshot(pid)
    except ProcessLookupError:
        if recover and service == 'dsh-web':
            return recover_replacement()
        raise


def recover_replacement():
    # Market self-restart inherits our launch markers but cannot update our PID
    # file. Only an exact replacement of the recorded invocation may be adopted.
    # Keep the old identity until the replacement is verified, including while
    # the detached restart helper is waiting to spawn it.
    with state_lock():
        try:
            return current(recover=False)
        except ProcessLookupError:
            pass
        try:
            state = json.loads(statefile.read_text())
        except FileNotFoundError:
            raise ProcessLookupError() from None
        previous = state['identity']
        members = launch_members(state)
        candidates = [now for now in members
                      if settled_command(now, Path(previous['argv'][0]).resolve(), previous['argv'])]
        if members and not candidates:
            raise ValueError('self-restart still pending; use stop to terminate the launch')
        if len(candidates) > 1:
            raise ValueError('multiple replacement processes; refusing ambiguous adoption')
        if not candidates:
            raise ProcessLookupError()
        now = candidates[0]
        # Recheck before publishing. Never grant the environment-permission
        # fallback to an unverified replacement.
        if snapshot(now['pid']) != now:
            raise ValueError('replacement identity changed')
        replacement = {**state, 'launch_start': state.get('launch_start', previous['start']),
                       'identity': {**now, 'argv': [os.fsdecode(x) for x in now['argv']]}}
        atomic(statefile, json.dumps(replacement))
        atomic(pidfile, str(now['pid']) + '\n')
        print(f"dsh-web: 已登记自重启后的进程 PID {now['pid']}", file=sys.stderr)
        return now

def launch_members(state):
    previous = state['identity']
    if (state['root'] != str(root) or state['service'] != service or
            not state['launch'] or previous['uid'] != os.geteuid() or
            previous['boot'] != Path('/proc/sys/kernel/random/boot_id').read_text().strip()):
        raise ValueError('invalid launch origin')
    markers = {('DSH_LAUNCH_ID=' + state['launch']).encode(),
               ('DSH_LAUNCH_ROOT=' + str(root)).encode()}
    members = []
    for proc in Path('/proc').iterdir():
        if not proc.name.isdecimal():
            continue
        try:
            now = snapshot(int(proc.name))
            if (now['uid'] != previous['uid'] or
                    int(now['start']) < int(state.get('launch_start', previous['start']))):
                continue
            try:
                environment = set((proc / 'environ').read_bytes().split(b'\0'))
            except PermissionError:
                if now['pid'] == previous['pid']:
                    owned(now)  # Exact registered identity is the only fallback.
                    members.append(now)
                elif [os.fsdecode(x) for x in now['argv']] == previous['argv']:
                    raise ValueError('cannot verify possible replacement environment')
                continue
            if markers <= environment:
                members.append(now)
        except (FileNotFoundError, ProcessLookupError):
            continue
    return members


def stop_launch():
    # Stop the entire marked launch, including detached plugin restart helpers.
    # Rescan after TERM: a helper can race with shutdown and spawn a new host.
    # Never discard the registration while any verified launch member survives.
    with state_lock():
        try:
            state = json.loads(statefile.read_text())
        except FileNotFoundError:
            try:
                current(recover=False)
            except (FileNotFoundError, ProcessLookupError):
                return
            raise
        try:
            owned(current(recover=False))
        except (FileNotFoundError, ProcessLookupError):
            pass
        deadline = time.monotonic() + 10
        quiet = False
        while True:
            members = launch_members(state)
            if not members:
                if quiet:
                    return
                # /proc enumeration can overlap a helper exiting just after it
                # spawns its replacement. Require a second empty observation.
                quiet = True
                time.sleep(.1)
                continue
            quiet = False
            for now in sorted(members, key=lambda item: item['pid'] == state['identity']['pid']):
                fd = None
                try:
                    fd = open_pidfd(now['pid'])
                    if snapshot(now['pid']) != now:
                        raise ValueError('launch member identity changed')
                    # Revalidate environment/ownership after pinning the PID.
                    if now not in launch_members(state):
                        raise ValueError('launch member ownership changed')
                    send_pidfd(fd, signal.SIGTERM)
                except ProcessLookupError:
                    pass
                finally:
                    if fd is not None:
                        os.close(fd)
            if time.monotonic() >= deadline:
                raise ValueError('launch processes still running; registration preserved')
            time.sleep(.1)


def owned(now, require_environment=False):
    state = json.loads(statefile.read_text())
    if not (state['root'] == str(root) and state['service'] == service):
        raise ValueError("state verification failed")
    if not (state['identity'] == {**now, 'argv': [os.fsdecode(x) for x in now['argv']]}):
        raise ValueError("state verification failed")
    try:
        env = (Path('/proc') / str(now['pid']) / 'environ').read_bytes().split(b'\0')
    except FileNotFoundError:
        snapshot(now['pid'])  # Translate an exited process; never ignore missing state.
        raise
    except PermissionError:
        # Existing private state identifies this exact process using boot ID,
        # start time, UID and argv. /proc environ may have stricter ptrace access
        # than signalling. Initial registration must still verify launch markers.
        if require_environment or now['uid'] != os.geteuid():
            raise
        return state
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


def prepare_runtime(root):
    root = root.resolve()
    logs = root / 'log'
    if logs.is_symlink():
        sys.exit(f'运行目录不能是符号链接：{logs}')
    logs.mkdir(mode=0o700, exist_ok=True)
    logs.chmod(0o700)
    names = [f'{service}.{suffix}' for service in ('magpie-serve', 'magpie-web-proxy', 'dsh-web', 'dsh-token-proxy')
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


def read_magpie_key(path):
    fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    with os.fdopen(fd, encoding='ascii') as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.geteuid() or info.st_mode & 0o077:
            raise ValueError('Magpie Web key must be a private regular file owned by the current user')
        key = stream.read().removesuffix('\n')
    if not re.fullmatch(r'[A-Za-z0-9._~-]{16,}', key):
        raise ValueError('Invalid Magpie Web key')
    return key


def magpie_web_key():
    path = root / 'data/.magpie-web-key'
    try:
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    except FileExistsError:
        pass
    else:
        with os.fdopen(fd, 'w') as stream:
            stream.write(secrets.token_urlsafe(32) + '\n')
    return read_magpie_key(path)


def startup_config(address, tls_root, listen):
    try:
        ipaddress.ip_address(address)
    except ValueError:
        if not (len(address) <= 253 and all(re.fullmatch(r'[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?', label) for label in address.split('.'))):
            sys.exit('server_ip 必须是 IP 或域名，不得包含协议、端口或路径。')
    def bindable(value):
        ip = ipaddress.ip_address(value)
        try:
            with socket.socket(socket.AF_INET6 if ip.version == 6 else socket.AF_INET) as probe:
                # Probe address ownership, not the service port: a running proxy may own it.
                probe.bind((str(ip), 0))
            return True
        except OSError:
            return False

    if listen:
        try:
            ipaddress.ip_address(listen)
        except ValueError:
            sys.exit('listen_host 必须是 IPv4 或 IPv6 地址。')
        if not bindable(listen):
            sys.exit(f'listen_host 无法在本机绑定：{listen}；请配置本机 IP。')
    else:
        try:
            local_public = bindable(address)
        except ValueError:
            local_public = False
        if local_public:
            listen = address
        else:
            try:
                result = subprocess.run(['hostname', '-I'], capture_output=True, text=True,
                                        check=True, timeout=5)
                candidates = sorted({str(ipaddress.ip_address(value))
                                     for value in result.stdout.split() if bindable(value)})
            except (OSError, ValueError, subprocess.SubprocessError):
                candidates = []
            if len(candidates) != 1:
                sys.exit('无法唯一确定本机监听 IP；请显式配置 listen_host（域名/NAT/多网卡部署）。')
            listen = candidates[0]
            print(f'对外地址 {address} 不可用于本机绑定，自动选择 listen_host={listen}', file=sys.stderr)
    directory = Path(tls_root) / address.lower().replace(':', '_')
    cert, key = directory / 'fullchain.pem', directory / 'privkey.pem'
    try:
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(cert, key)
    except (OSError, ValueError) as error:
        sys.exit(f"无法加载地址目录中的 HTTPS 证书或私钥：{cert} / {key}。请先运行 dsh_cert.sh：{error}")
    print(listen)
    print(directory)


def record_process():
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
    try:
        owned(now, require_environment=True)
    except Exception:
        # Never leave an unverified registration available to the permission fallback.
        statefile.unlink(missing_ok=True)
        raise


def capture_output():
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
                    if not (owned(current(recover=False)) == state):
                        raise ValueError("state verification failed")
                    save_token(token)
                    atomic(readyfile, json.dumps(dict(state=state, token_sha256=hashlib.sha256(token.encode()).hexdigest())))
                captured = True
        print(redact_tokens(line), end='', flush=True)


def run_operation():
    try:
        if int(Path('/proc/self/stat').read_text().split()[0]) != os.getpid():
            raise ValueError('/proc PID namespace mismatch')
        if operation == 'preflight':
            fd = open_pidfd(os.getpid())
            try:
                send_pidfd(fd, 0)
            finally:
                os.close(fd)
        elif operation == 'prepare':
            prepare_runtime(root)
        elif operation == 'config':
            startup_config(*args)
        elif operation == 'magpie-key':
            print(magpie_web_key())
        elif operation == 'check-nginx':
            from dsh_nginx import require_local_nginx
            require_local_nginx()
        elif operation == 'stop-launch':
            stop_launch()
        elif operation == 'record':
            record_process()
        elif operation == 'capture':
            capture_output()
        elif operation == 'write-token':
            with state_lock():
                save_token(args[0])
        else:
            try:
                now = current()
            except (FileNotFoundError, ProcessLookupError):
                sys.exit(1)
            try:
                state = owned(now)
            except ProcessLookupError:
                sys.exit(1)
            if operation == 'signal':
                # Pin the process before the final check: PID reuse cannot redirect TERM.
                try:
                    fd = open_pidfd(now['pid'])
                except ProcessLookupError:
                    sys.exit(1)
                try:
                    with state_lock():
                        if not (owned(current(recover=False)) == state):
                            raise ValueError("state verification failed")
                        send_pidfd(fd, signal.SIGTERM)
                except ProcessLookupError:
                    sys.exit(1)
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
        elif operation == 'check-nginx':
            print(f'dsh nginx: {error}', file=sys.stderr)
        elif operation != 'ready' and isinstance(error, FileNotFoundError) and error.filename == str(statefile):
            print(f'{service}: PID 对应进程仍在运行，但缺少身份记录 {statefile}；'
                  '可能由旧版脚本启动，拒绝接管或停止。请在任务可中断时核验并迁移旧进程；'
                  '不要删除 PID 文件绕过检查。', file=sys.stderr)
        elif operation != 'ready':
            print(f'{service}: 无法验证进程身份，保留现场；请安排维护 ({type(error).__name__})', file=sys.stderr)
        sys.exit(2)


def main():
    global root, logs, config, operation, service, args, pidfile, statefile, readyfile
    root, logs, config = map(Path, sys.argv[1:4])
    operation, service, *args = sys.argv[4:]
    pidfile = logs / (service + '.pid')
    statefile = logs / (service + '.identity')
    readyfile = logs / '.dsh-web-token-captured'
    run_operation()


if __name__ == "__main__":
    main()
