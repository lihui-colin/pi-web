"""Exercise launcher lifecycle with temporary services, without touching live sessions."""

import ast
import io
import errno
import fcntl
import json
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock
from types import SimpleNamespace
from pathlib import Path

from test_support import copy_test_nginx, create_test_certificate, local_nginx

NGINX = local_nginx()


class LauncherTests(unittest.TestCase):
    def test_main_serializes_operations_and_releases_lock_after_failure(self):
        for held, contender in [('start', 'start'), ('start', 'stop'), ('stop', 'start')]:
            with self.subTest(held=held, contender=contender), tempfile.TemporaryDirectory(
                    prefix='dsh-launcher-lock-') as temporary:
                root = Path(temporary)
                script = root / 'dsh_web_run.sh'
                shutil.copy2(Path(__file__).with_name(script.name), script)
                barrier = root / 'release'
                os.mkfifo(barrier)
                # Keep both FIFO ends open so cleanup can always release a failed test.
                barrier_fd = os.open(barrier, os.O_RDWR | os.O_NONBLOCK)
                wrapper = '''source "$1"
operation() {
    printf '%s\n' "$1" >> "$script_dir/entered"
    if [[ "$3" == hold ]]; then
        printf 'ready\n' > "$script_dir/ready"
        read -r release < "$script_dir/release"
    fi
    return "$2"
}
start() { operation start "$status" "$mode"; }
stop() { operation stop "$status" "$mode"; }
action=$2 status=$3 mode=$4
main "$action"
'''
                command = ['bash', '-c', wrapper, 'test', str(script)]
                owner = subprocess.Popen(command + [held, '23', 'hold'],
                                         stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
                try:
                    deadline = time.monotonic() + 5
                    while not (root / 'ready').exists():
                        self.assertIsNone(owner.poll(), 'lock owner exited before barrier')
                        self.assertLess(time.monotonic(), deadline, 'lock owner never reached barrier')
                        time.sleep(0.01)
                    # A blocking flock would time out while the owner waits at the FIFO.
                    result = subprocess.run(command + [contender, '0', 'pass'],
                                            capture_output=True, text=True, timeout=2)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('已有启停操作正在进行', result.stderr)
                    self.assertEqual((root / 'entered').read_text().splitlines(), [held])
                    self.assertIsNone(owner.poll())
                    os.write(barrier_fd, b'release\n')
                    _, errors = owner.communicate(timeout=5)
                    self.assertEqual(owner.returncode, 23, errors)
                    result = subprocess.run(command + [contender, '0', 'pass'],
                                            capture_output=True, text=True, timeout=2)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual((root / 'entered').read_text().splitlines(), [held, contender])
                    # main's subshell must also release fd9 when its sourcing shell lives on.
                    result = subprocess.run(
                        ['bash', '-c', 'source "$1"; start() { return 0; }; '
                         'main start; flock -n "$log_dir/.launcher.lock" true', 'test', str(script)],
                        capture_output=True, text=True, timeout=2)
                    self.assertEqual(result.returncode, 0, result.stderr)
                finally:
                    os.write(barrier_fd, b'release\n')
                    os.close(barrier_fd)
                    if owner.poll() is None:
                        owner.kill()
                    owner.communicate(timeout=5)

    def test_listen_address_selection_and_validation(self):
        with tempfile.TemporaryDirectory(prefix='dsh-listen-selection-') as temporary:
            root = Path(temporary)
            script = root / 'dsh_web_run.sh'
            shutil.copy2(Path(__file__).with_name(script.name), script)
            # Isolate address validation from Nginx availability and socket permissions.
            (root / 'dsh_nginx.py').write_text('def require_local_nginx(): pass\n')
            binaries = root / 'bin'
            binaries.mkdir()
            for name in ('dsh', 'magpie', 'hostname'):
                executable = binaries / name
                executable.write_text('#!/bin/sh\ntouch "$(dirname "$0")/called-' + name + '"\n'
                                      "printf '192.0.2.10 10.0.0.2 2001:db8::10\\n'\n")
                executable.chmod(0o755)
            environment = {**os.environ, 'PATH': f"{binaries}:{os.environ['PATH']}"}
            cert, key = create_test_certificate(root)
            config = root / 'data/dsh.conf'
            # Pretend an existing backend has the expected URL, avoiding port allocation.
            command = ['bash', '-c', '''source "$1"
service_pid() { [[ "$1" == dsh-web ]] && printf '12345\n'; }
process_option() {
    case "$2" in
        --port) printf '12346\n' ;;
        --public-url) printf '%s\n' "$public_url" ;;
    esac
}
start_service() { printf 'SERVICE %s\n' "$*"; }
main start
''', 'test', str(script)]
            cases = [
                ('::1', None, '::1'),
                ('2001:db8::25', '', '2001:db8::25'),
                ('192.0.2.25', None, '192.0.2.25'),
                ('DSH.Example.Test', '127.0.0.1', '127.0.0.1'),
                ('dsh.example.test', '::1', '::1'),
                ('203.0.113.25', '127.0.0.1', '127.0.0.1'),
                ('dsh.example.test', None, None),
                ('dsh.example.test', '', None),
            ] + [('127.0.0.1', invalid, None) for invalid in
                 ('localhost', 'https://127.0.0.1', '127.0.0.1:25228', '[::1]', '999.0.0.1', '::gg', '127.0.0.1/8')]
            for address, listen, expected in cases:
                with self.subTest(address=address, listen=listen):
                    tls = root / 'data/tls' / address.lower().replace(':', '_')
                    tls.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(cert, tls / 'fullchain.pem')
                    shutil.copy2(key, tls / 'privkey.pem')
                    config.write_text(f"port=25228\nserver_ip='{address}'\n" +
                                      (f"listen_host='{listen}'\n" if listen is not None else ''))
                    result = subprocess.run(command, env=environment, capture_output=True,
                                            text=True, timeout=10)
                    if expected is None:
                        self.assertNotEqual(result.returncode, 0)
                        self.assertIn('listen_host 必须是 IPv4 或 IPv6', result.stderr)
                        self.assertNotIn('SERVICE', result.stdout)
                    else:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        proxy = next(line for line in result.stdout.splitlines()
                                     if line.startswith('SERVICE dsh-token-proxy '))
                        self.assertIn(f'--listen-host {expected} --listen-port 25228', proxy)
                        host = f'[{address}]' if ':' in address else address
                        self.assertIn(f'--public-host {host}:25228', proxy)
                        self.assertIn(f'访问地址：https://{host}:25228/', result.stdout)
                        self.assertIn(f'--tls-cert {tls}/fullchain.pem', proxy)
                    self.assertFalse(list(binaries.glob('called-*')))
                    self.assertFalse(list((root / 'log').glob('*.pid')))

    def test_migration_preserves_open_logs_and_legacy_runtime_paths(self):
        with tempfile.TemporaryDirectory(prefix="dsh-runtime-migration-") as temporary:
            root = Path(temporary)
            script = root / "dsh_web_run.sh"
            shutil.copy2(Path(__file__).with_name(script.name), script)
            runtime = root / ".nginx-25228"
            runtime.mkdir()
            (runtime / "nginx.conf").write_text("test config")
            (root / "dsh-web.pid").write_text("12345\n")
            command = ["bash", "-c", 'source "$1"; prepare_runtime', "test", str(script)]
            with (root / "dsh-web.log").open("w") as stream:
                stream.write("before\n")
                stream.flush()
                inode = os.fstat(stream.fileno()).st_ino
                result = subprocess.run(command, capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stderr)
                stream.write("after\n")
            logs = root / "log"
            self.assertEqual((logs / "dsh-web.log").read_text(), "before\nafter\n")
            self.assertEqual((logs / "dsh-web.log").stat().st_ino, inode)
            self.assertEqual((logs / "dsh-web.pid").read_text(), "12345\n")
            self.assertFalse((root / "dsh-web.log").exists())
            self.assertFalse((root / "dsh-web.pid").exists())
            self.assertTrue(runtime.is_symlink())
            self.assertEqual((runtime / "nginx.conf").read_text(), "test config")
            self.assertEqual(runtime.resolve(), logs / runtime.name)
            self.assertEqual(logs.stat().st_mode & 0o777, 0o700)
            # Repeated startup must not move or overwrite already migrated files.
            result = subprocess.run(command, capture_output=True, text=True, timeout=10)
            self.assertEqual(result.returncode, 0, result.stderr)

    def test_migration_conflict_keeps_both_files(self):
        with tempfile.TemporaryDirectory(prefix="dsh-runtime-conflict-") as temporary:
            root = Path(temporary)
            script = root / "dsh_web_run.sh"
            shutil.copy2(Path(__file__).with_name(script.name), script)
            (root / "log").mkdir()
            (root / "dsh-web.log").write_text("old")
            (root / "log/dsh-web.log").write_text("new")
            result = subprocess.run(
                ["bash", "-c", 'source "$1"; prepare_runtime', "test", str(script)],
                capture_output=True, text=True, timeout=10,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("迁移冲突", result.stderr)
            self.assertEqual((root / "dsh-web.log").read_text(), "old")
            self.assertEqual((root / "log/dsh-web.log").read_text(), "new")

    def test_local_binary_failure_precedes_config_and_service_start(self):
        with tempfile.TemporaryDirectory(prefix="dsh-launcher-binary-") as temporary:
            root = Path(temporary)
            script = root / "dsh_web_run.sh"
            for name in ("dsh_web_run.sh", "dsh_nginx.py"):
                shutil.copy2(Path(__file__).with_name(name), root / name)
            binaries = root / "bin"
            binaries.mkdir()
            fallback = binaries / "nginx"
            fallback.write_text("#!/bin/sh\nprintf 'PATH nginx must not run' >&2\nexit 99\n")
            fallback.chmod(0o755)
            environment = {**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"}
            local = root / "data/.local/nginx/sbin/nginx"
            local.parent.mkdir(parents=True)
            # No config or TLS inputs: the binary check must run before reading them.
            command = ["bash", "-c", 'source "$1"; '
                       'start_service() { printf "SERVICE %s\\n" "$*"; }; '
                       'if start; then exit 0; else exit 1; fi', "test", str(script)]
            for label, contents, mode in [
                ("missing", None, 0),
                ("not executable", "#!/bin/sh\nexit 0\n", 0o600),
                ("old version", "#!/bin/sh\nprintf 'nginx/1.22.1' >&2\n", 0o700),
                ("failed version", "#!/bin/sh\nprintf 'nginx/1.30.0' >&2\nexit 1\n", 0o700),
            ]:
                with self.subTest(binary=label):
                    if contents is not None:
                        local.write_text(contents)
                        local.chmod(mode)
                    result = subprocess.run(command, cwd=binaries, env=environment,
                                            text=True, capture_output=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(str(local), result.stderr)
                    self.assertIn("dsh_nginx_install.sh", result.stderr)
                    self.assertNotIn("PATH nginx must not run", result.stderr)
                    self.assertNotIn("SERVICE", result.stdout)
                    self.assertNotIn("dsh.conf.example", result.stderr)
                    self.assertFalse(list(root.glob("*.pid")))

    @unittest.skipUnless(NGINX, "run dsh_nginx_install.sh to install the project-local Nginx")
    def test_certificate_directory_follows_address_and_rejects_fallback(self):
        with tempfile.TemporaryDirectory(prefix='dsh-cert-selection-') as temporary:
            root = Path(temporary)
            script = root / 'dsh_web_run.sh'
            shutil.copy2(Path(__file__).with_name('dsh_web_run.sh'), script)
            shutil.copy2(Path(__file__).with_name('dsh_nginx.py'), root / 'dsh_nginx.py')
            copy_test_nginx(root)
            seed = root / 'seed'
            seed.mkdir()
            cert, key = create_test_certificate(seed)
            config = root / 'data/dsh.conf'
            config.parent.mkdir(exist_ok=True)
            # Stub service management: exercise selection and TLS validation only.
            command = ['bash', '-c', 'source "$1"; '
                       'service_pid() { [[ "$1" == dsh-web ]] && printf "12345\\n"; }; '
                       'process_option() { if [[ "$2" == --port ]]; then printf "12346\\n"; '
                       'else printf "%s\\n" "$public_url"; fi; }; '
                       'start_service() { printf "SERVICE %s\\n" "$*"; }; start', 'test', str(script)]
            for address, folder in [('127.0.0.1', '127.0.0.1'), ('10.30.0.25', '10.30.0.25'),
                                    ('DSH.Example.Test', 'dsh.example.test'), ('::1', '__1')]:
                with self.subTest(address=address):
                    directory = root / 'data/tls' / folder
                    directory.mkdir(parents=True)
                    shutil.copy2(cert, directory / 'fullchain.pem')
                    shutil.copy2(key, directory / 'privkey.pem')
                    config.write_text(f'port=25228\nserver_ip={address}\n'
                                      + ('listen_host=127.0.0.1\n' if address == 'DSH.Example.Test' else '')
                                      + 'tls_cert=stale.pem\ntls_key=stale.key\n')
                    result = subprocess.run(command, text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f'--tls-cert {directory}/fullchain.pem', result.stdout)
                    self.assertIn(f'--tls-key {directory}/privkey.pem', result.stdout)
            # An unrelated IP directory and stale explicit paths must not be used.
            config.write_text(f'port=25228\nserver_ip=10.30.0.26\ntls_cert={cert}\ntls_key={key}\n')
            result = subprocess.run(command, text=True, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn(str(root / 'data/tls/10.30.0.26/fullchain.pem'), result.stderr)
            self.assertNotIn('SERVICE', result.stdout)
            config.write_text("port=25228\nserver_ip='../outside'\n")
            result = subprocess.run(command, text=True, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('SERVICE', result.stdout)

    @unittest.skipUnless(NGINX, "run dsh_nginx_install.sh to install the project-local Nginx")
    def test_start_reuse_proxy_recovery_and_stop(self):
        self.exercise_lifecycle("127.0.0.1")

    @unittest.skipUnless(NGINX, "run dsh_nginx_install.sh to install the project-local Nginx")
    def test_ipv6_tls_lifecycle(self):
        try:
            with socket.socket(socket.AF_INET6) as probe:
                probe.bind(("::1", 0))
        except OSError as error:
            if error.errno in (errno.EAFNOSUPPORT, errno.EPROTONOSUPPORT, errno.EADDRNOTAVAIL, errno.ENODEV):
                self.skipTest(f"IPv6 loopback unavailable: {error}")
            raise  # Socket sandbox restrictions must be reported as failures.
        self.exercise_lifecycle("::1")

    def exercise_lifecycle(self, address):
        public_host = f"[{address}]" if ":" in address else address
        with tempfile.TemporaryDirectory(prefix="dsh-launcher-") as temporary:
            root = Path(temporary)
            for name in ("dsh_web_run.sh", "dsh_nginx.py"):
                shutil.copy2(Path(__file__).with_name(name), root / name)
            copy_test_nginx(root)
            binaries = root / "bin"
            binaries.mkdir()
            for name in ("dsh", "magpie"):
                command = binaries / name
                command.write_text(
                    f"#!{sys.executable}\n"
                    "import signal, sys\n"
                    "if sys.argv[0].endswith('/dsh'):\n"
                    "    print('dsh web: ' + sys.argv[sys.argv.index('--public-url') + 1] + '?token=test-launch-token', flush=True)\n"
                    "signal.pause()\n"
                )
                command.chmod(0o755)
            (binaries / "hostname").write_text(
                '#!/bin/sh\ntouch "$(dirname "$0")/hostname-called"\n'
                "printf '192.0.2.10 10.0.0.2 2001:db8::10\\n'\n"
            )
            (binaries / "hostname").chmod(0o755)
            (binaries / "nginx").write_text("#!/bin/sh\nprintf 'PATH nginx must not run' >&2\nexit 99\n")
            (binaries / "nginx").chmod(0o755)
            with socket.socket(socket.AF_INET6 if ":" in address else socket.AF_INET) as reservation:
                reservation.bind((address, 0))
                port = reservation.getsockname()[1]
            config = root / "data/dsh.conf"
            config.parent.mkdir(exist_ok=True)
            tls = root / 'data/tls' / address.replace(':', '_')
            tls.mkdir(parents=True)
            generated_cert, generated_key = create_test_certificate(tls)
            cert, key = tls / 'fullchain.pem', tls / 'privkey.pem'
            generated_cert.rename(cert)
            generated_key.rename(key)
            config.write_text(
                f"port={port}\nserver_ip={address}\ndsh_token=''\n"
                "tls_cert=tls/stale/cert.pem\ntls_key=tls/stale/key.pem\n"
            )
            environment = {**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"}

            def run(action):
                # Background log readers must not hold subprocess.run's capture pipe open.
                with (root / "launcher.log").open("ab") as log:
                    return subprocess.run(
                        ["bash", str(root / "dsh_web_run.sh"), action],
                        env=environment, stdout=log, stderr=log, timeout=40,
                    ).returncode

            def pids():
                return {p.stem: int(p.read_text()) for p in (root / "log").glob("*.pid")}

            try:
                key.rename(key.with_suffix(".backup"))
                self.assertNotEqual(run("start"), 0)
                self.assertFalse(pids(), "missing TLS key must fail before starting services")
                key.with_suffix(".backup").rename(key)
                self.assertEqual(run("start"), 0, (root / "launcher.log").read_text())
                self.assertIn(
                    f"访问地址：https://{public_host}:{port}/",
                    (root / "launcher.log").read_text(),
                )
                # The services and process-substitution log reader remain alive here.
                # A fresh descriptor must be able to acquire the launcher lock.
                with (root / "log/.launcher.lock").open("a") as lock:
                    fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                self.assertFalse((binaries / "hostname-called").exists())
                context = ssl.create_default_context(cafile=str(cert))
                # The shared test certificate covers localhost, even on IPv6 transport.
                with socket.create_connection((address, port), timeout=5) as raw:
                    with context.wrap_socket(raw, server_hostname="localhost") as client:
                        self.assertTrue(client.getpeercert())
                original = pids()
                self.assertEqual(len(original), 3)
                self.assertFalse(list(root.glob("*.pid")))
                self.assertFalse(list(root.glob(".nginx-*")))
                self.assertEqual((root / "log").stat().st_mode & 0o777, 0o700)
                nginx_runtime = root / "log" / f".nginx-{port}"
                nginx_config = nginx_runtime / "nginx.conf"
                self.assertEqual(nginx_runtime.stat().st_mode & 0o777, 0o700)
                self.assertEqual(nginx_config.stat().st_mode & 0o777, 0o600)
                for name in ("body", "proxy", "fastcgi", "uwsgi", "scgi"):
                    directory = nginx_runtime / name
                    self.assertTrue(directory.is_dir(), f"Nginx did not create {directory}")
                    self.assertEqual(directory.stat().st_uid, os.geteuid())
                    self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
                self.assertIn("dsh_token='test-launch-token'", config.read_text())
                self.assertEqual(config.stat().st_mode & 0o077, 0)
                self.assertNotIn("test-launch-token", (root / "log/dsh-web.log").read_text())
                # Emulate the old layout while services keep their open descriptors.
                for name in ("dsh-web.log", "dsh-web.pid"):
                    (root / "log" / name).rename(root / name)
                self.assertEqual(run("start"), 0)
                self.assertEqual(pids(), original)
                self.assertFalse((root / "dsh-web.pid").exists())
                self.assertFalse((root / "dsh-web.log").exists())

                backend_env = dict(item.split(b'=', 1) for item in
                                   Path(f'/proc/{original["dsh-web"]}/environ').read_bytes().split(b'\0') if item)
                self.assertEqual(backend_env[b'DSH_HOME'], str(root / 'data/.dsh').encode())
                self.assertEqual(backend_env[b'DSH_AGENTS_HOME'], str(root / 'data/.agents').encode())
                backend = Path(f'/proc/{original["dsh-web"]}/cmdline').read_bytes().split(b"\0")
                backend_port = backend[backend.index(b"--port") + 1]
                self.assertEqual(
                    backend[backend.index(b"--public-url") + 1],
                    f"https://{public_host}:{port}/".encode(),
                )
                # Changing the advertised URL must never silently reuse/restart a backend.
                original_config = config.read_text()
                config.write_text(original_config.replace(f'server_ip={address}', f'server_ip=localhost\nlisten_host={address}'))
                self.assertNotEqual(run("start"), 0)
                self.assertEqual(pids(), original)
                config.write_text(original_config + '\nlisten_host=0.0.0.0\n')
                self.assertNotEqual(run("start"), 0)
                self.assertEqual(pids(), original)
                self.assertIn('监听地址或 Cookie 前缀与配置不一致', (root / 'launcher.log').read_text())
                config.write_text(original_config)
                os.kill(original["dsh-token-proxy"], signal.SIGTERM)
                for _ in range(100):
                    process = Path(f'/proc/{original["dsh-token-proxy"]}/cmdline')
                    if not process.exists() or not process.read_bytes():
                        break
                    time.sleep(0.02)
                self.assertEqual(run("start"), 0)
                recovered = pids()
                self.assertEqual(recovered["dsh-web"], original["dsh-web"])
                proxy = Path(f'/proc/{recovered["dsh-token-proxy"]}/cmdline').read_bytes().split(b"\0")
                self.assertEqual(proxy[proxy.index(b"--cookie-prefix") + 1], f"dsh{port}_".encode())
                self.assertEqual(proxy[proxy.index(b"--upstream-port") + 1], backend_port)
                self.assertEqual(proxy[proxy.index(b"--tls-cert") + 1], str(cert).encode())
                self.assertEqual(proxy[proxy.index(b"--tls-key") + 1], str(key).encode())
                self.assertEqual(run("stop"), 0)
                self.assertFalse(pids())
                self.assertFalse(nginx_config.exists())
                self.assertIn("dsh_token=''", config.read_text())
                self.assertEqual(run("stop"), 0)
            finally:
                run("stop")

    def test_pidfd_preflight_failure_never_starts_services(self):
        with tempfile.TemporaryDirectory(prefix='dsh-pidfd-preflight-') as temporary:
            root = Path(temporary)
            script = root / 'dsh_web_run.sh'
            shutil.copy2(Path(__file__).with_name(script.name), script)
            marker = root / 'started'
            result = subprocess.run(
                ['bash', '-c', 'source "$1"; process_state() { return 2; }; '
                 'start() { touch "$script_dir/started"; }; main start', 'test', str(script)],
                capture_output=True, text=True, timeout=5)
            self.assertEqual(result.returncode, 2)
            self.assertFalse(marker.exists())

    def test_start_identity_errors_at_each_probe_fail_closed(self):
        with tempfile.TemporaryDirectory(prefix='dsh-start-probes-') as temporary:
            root = Path(temporary)
            script = root / 'dsh_web_run.sh'
            shutil.copy2(Path(__file__).with_name(script.name), script)
            (root / 'dsh_nginx.py').write_text('def require_local_nginx(): pass\n')
            tls = root / 'data/tls/127.0.0.1'
            tls.mkdir(parents=True)
            cert, key = create_test_certificate(tls)
            shutil.copy2(cert, tls / 'fullchain.pem')
            shutil.copy2(key, tls / 'privkey.pem')
            config = root / 'data/dsh.conf'
            original = "server_ip=127.0.0.1\nport=25228\ndsh_token='preserve'\n"
            config.write_text(original)
            bins = root / 'bin'
            bins.mkdir()
            for name in ('magpie', 'dsh'):
                path = bins / name
                path.write_text('#!/bin/sh\nexit 99\n')
                path.chmod(0o755)
            for probe, backend in ((1, 0), (2, 0), (3, 0), (4, 0), (5, 0), (5, 1)):
                with self.subTest(probe=probe, backend=backend):
                    (root / 'counter').write_text('0')
                    body = '''source "$1"
service_pid() {
    local count
    read -r count < "$script_dir/counter" || true
    count=$((count + 1))
    printf '%s\n' "$count" > "$script_dir/counter"
    [[ "$count" != "$probe" ]] || return 2
    if [[ "$count" == 4 && "$backend" == 1 ]]; then echo 12345; return 0; fi
    return 1
}
process_option() { case "$2" in --port) echo 12346;; --public-url) echo "$public_url";; esac; }
start_service() { touch "$script_dir/started"; }
probe=$2 backend=$3
start
'''
                    result = subprocess.run(['bash', '-c', body, 'test', str(script),
                                             str(probe), str(backend)],
                                            env={**os.environ, 'PATH': f'{bins}:{os.environ["PATH"]}'},
                                            capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0, result.stderr)
                    self.assertFalse((root / 'started').exists())
                    self.assertEqual(config.read_text(), original)

    def test_stop_final_unknown_identity_preserves_ready_and_token(self):
        with tempfile.TemporaryDirectory(prefix='dsh-stop-probe-') as temporary:
            root = Path(temporary)
            script = root / 'dsh_web_run.sh'
            shutil.copy2(Path(__file__).with_name(script.name), script)
            (root / 'data').mkdir()
            config = root / 'data/dsh.conf'
            config.write_text("dsh_token='preserve'\n")
            (root / 'log').mkdir()
            ready = root / 'log/.dsh-web-token-captured'
            ready.write_text('preserve')
            result = subprocess.run(['bash', '-c', 'source "$1"; '
                                     'stop_service() { return 0; }; '
                                     'service_pid() { return 2; }; stop', 'test', str(script)],
                                    capture_output=True, timeout=10)
            self.assertEqual(result.returncode, 2)
            self.assertIn('preserve', config.read_text())
            self.assertEqual(ready.read_text(), 'preserve')


class ProcessHelperTests(unittest.TestCase):
    """Execute the embedded helpers/branches without relying on the /proc namespace."""

    def setUp(self):
        source = Path(__file__).with_name('dsh_web_run.sh').read_text()
        source = source.split("3<<'PYTHON'\n", 1)[1].split('\nPYTHON', 1)[0]
        self.tree = ast.parse(source)
        definitions = [node for node in self.tree.body
                       if isinstance(node, (ast.Import, ast.ImportFrom, ast.FunctionDef))]
        self.ns = {}
        exec(compile(ast.Module(body=definitions, type_ignores=[]), '<helpers>', 'exec'), self.ns)

    def branch(self, operation):
        outer = next(node for node in self.tree.body if isinstance(node, ast.Try))
        node = outer.body[1]
        while node.test.comparators[0].value != operation:
            node = node.orelse[0]
        return compile(ast.Module(body=node.body, type_ignores=[]), '<branch>', 'exec')

    def test_pidfd_missing_python_wrappers_uses_libc(self):
        libc = mock.Mock()
        libc.pidfd_open.return_value = 71
        libc.pidfd_send_signal.return_value = 0
        with mock.patch.dict(self.ns, os=SimpleNamespace(), signal=SimpleNamespace()), \
             mock.patch.object(self.ns['ctypes'], 'CDLL', return_value=libc):
            self.assertEqual(self.ns['open_pidfd'](123), 71)
            self.ns['send_pidfd'](71, signal.SIGTERM)
        libc.pidfd_open.assert_called_once_with(123, 0)
        libc.pidfd_send_signal.assert_called_once_with(71, signal.SIGTERM, None, 0)

    def test_pidfd_syscall_numbers_and_unknown_architecture(self):
        libc = mock.Mock(spec=['syscall'])
        libc.syscall.return_value = 73
        for arch in ('x86_64', 'aarch64'):
            with self.subTest(arch=arch), \
                 mock.patch.object(self.ns['ctypes'], 'CDLL', return_value=libc), \
                 mock.patch.object(self.ns['platform'], 'machine', return_value=arch):
                self.ns['native_pidfd']('pidfd_open', 123, 0)
                self.assertEqual([x.value for x in libc.syscall.call_args.args], [434, 123, 0])
                self.ns['native_pidfd']('pidfd_send_signal', 73, 15, None, 0)
                self.assertEqual([x.value for x in libc.syscall.call_args.args], [424, 73, 15, 0, 0])
        with mock.patch.object(self.ns['ctypes'], 'CDLL', return_value=libc), \
             mock.patch.object(self.ns['platform'], 'machine', return_value='riscv64'):
            with self.assertRaises(OSError) as error:
                self.ns['native_pidfd']('pidfd_open', 123, 0)
            self.assertEqual(error.exception.errno, errno.ENOSYS)

    def test_pidfd_standard_library_preferred_and_errors_never_fall_back(self):
        for name, module, helper, args in (
                ('pidfd_open', os, 'open_pidfd', (123,)),
                ('pidfd_send_signal', signal, 'send_pidfd', (71, 15))):
            with self.subTest(name=name), \
                 mock.patch.object(module, name, create=True) as wrapper, \
                 mock.patch.dict(self.ns, native_pidfd=mock.Mock()):
                wrapper.return_value = 71
                self.ns[helper](*args)
                wrapper.side_effect = PermissionError(errno.EPERM, 'denied')
                with self.assertRaises(PermissionError):
                    self.ns[helper](*args)
                self.ns['native_pidfd'].assert_not_called()
        libc = mock.Mock()
        libc.pidfd_open.return_value = -1
        with mock.patch.object(self.ns['ctypes'], 'CDLL', return_value=libc), \
             mock.patch.object(self.ns['ctypes'], 'get_errno', return_value=errno.EPERM):
            with self.assertRaises(PermissionError):
                self.ns['native_pidfd']('pidfd_open', 123, 0)
            libc.syscall.assert_not_called()

    def test_normalized_startup_urls_and_rejections(self):
        endpoint = self.ns['url_endpoint']
        token = self.ns['startup_token']
        for advertised, emitted in (
                ('https://DSH.Example.Test:25228/', 'https://dsh.example.test:25228/'),
                ('https://example.test:443/', 'https://example.test/'),
                ('https://[2001:0db8:0:0:0:0:0:1]:25228/', 'https://[2001:db8::1]:25228/')):
            with self.subTest(advertised=advertised):
                self.assertEqual(token(emitted + '?token=valid', {endpoint(advertised)}), 'valid')
        endpoints = {endpoint('https://example.test/')}
        for value in ('https://[broken/?token=x', 'https://example.test:bad/?token=x',
                      'https://user@example.test/?token=x', 'https://example.test/?token=x#frag',
                      'https://example.test/?token=x&token=y', 'https://example.test/?token=',
                      'http://example.test/?token=x', 'https://example.test:444/?token=x',
                      'https://example.test/other?token=x'):
            self.assertIsNone(token(value, endpoints), value)

    def test_nohup_transition_waits_for_validated_interpreter_or_elf(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            script = root / 'script'
            script.write_text(f'#!{sys.executable}\n')
            binary = root / 'binary'
            binary.write_bytes(b'\x7fELF')
            for executable, final_argv, actual_exe in (
                    (script, [sys.executable, str(script), 'arg'], Path(sys.executable).resolve()),
                    (binary, [str(binary), 'arg'], binary)):
                with self.subTest(executable=executable):
                    (root / 'identity').unlink(missing_ok=True)
                    self.ns.update(args=['123', 'launch', str(executable), 'arg'],
                                   root=root, service='test', statefile=root / 'identity')
                    transition = dict(pid=123, argv=[b'nohup', os.fsencode(executable), b'arg'])
                    settled = dict(pid=123, argv=[os.fsencode(x) for x in final_argv])
                    snapshots = mock.Mock(side_effect=[transition, transition, settled])
                    original_resolve = Path.resolve

                    def resolve(path, *args, **kwargs):
                        if str(path) == '/proc/123/exe':
                            return actual_exe
                        return original_resolve(path, *args, **kwargs)

                    with mock.patch.dict(self.ns, snapshot=snapshots, owned=mock.Mock()), \
                         mock.patch.object(Path, 'resolve', resolve), \
                         mock.patch.object(time, 'sleep', side_effect=lambda _: self.assertFalse(
                             (root / 'identity').exists())) as sleep:
                        exec(self.branch('record'), self.ns)
                    self.assertEqual(sleep.call_args_list, [mock.call(.02), mock.call(.02)])
                    self.assertEqual(json.loads((root / 'identity').read_text())['identity']['argv'], final_argv)
                    with mock.patch.object(Path, 'resolve', return_value=Path('/wrong/interpreter')):
                        self.assertFalse(self.ns['settled_command'](settled, actual_exe, final_argv))

    def test_env_shebang_resolves_actual_interpreter(self):
        with tempfile.TemporaryDirectory() as directory:
            script = Path(directory) / 'script'
            script.write_text('#!/usr/bin/env python3\n')
            interpreter, argv = self.ns['launch_command'](str(script), ['arg'])
            self.assertEqual(interpreter, Path(shutil.which('python3')).resolve())
            self.assertEqual(argv[1:], [str(script), 'arg'])
            script.write_text('#!/usr/bin/env -S python3 -u\n')
            interpreter, argv = self.ns['launch_command'](str(script), ['arg'])
            self.assertEqual(argv[1:], ['-u', str(script), 'arg'])

    def test_encoded_token_names_are_captured_without_logging_credentials(self):
        for parameter in ('token', '%74oken', '%74%6fken'):
            with self.subTest(parameter=parameter), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = root / 'config'
                config.write_text("dsh_token=''\n")
                ready = root / 'ready'
                stream = io.TextIOWrapper(io.BytesIO(
                    f'dsh web: https://example.test/?{parameter}=synthetic-secret\n'.encode()))
                output = io.StringIO()
                self.ns.update(args=['launch', 'https://example.test/', ''],
                               config=config, readyfile=ready, logs=root)
                with mock.patch.dict(self.ns, current=mock.Mock(return_value={}),
                                     owned=mock.Mock(return_value={'launch': 'launch'})), \
                     mock.patch.object(sys, 'stdin', stream), mock.patch.object(sys, 'stdout', output):
                    exec(self.branch('capture'), self.ns)
                stream.close()
                self.assertIn("dsh_token='synthetic-secret'", config.read_text())
                self.assertTrue(ready.exists())
                self.assertNotIn('synthetic-secret', output.getvalue())
                self.assertIn('[REDACTED]', output.getvalue())

    def test_capture_retries_transients_and_replaces_invalid_utf8(self):
        for final_launch in ('launch', 'wrong'):
            with self.subTest(final_launch=final_launch), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                config = root / 'config'
                config.write_text("dsh_token='old'\n")
                ready = root / 'ready'
                stream = io.TextIOWrapper(io.BytesIO(
                    b'bad utf8 \xff\ndsh web: https://[broken/?token=secret\n'
                    b'dsh web: https://example.test/?token=valid\n'))
                self.ns.update(args=['launch', 'https://example.test/', ''],
                               config=config, readyfile=ready, logs=root)
                state = {'launch': final_launch}
                current = mock.Mock(side_effect=[FileNotFoundError(), ProcessLookupError(), ValueError(),
                                                 *([{}] * 101)])
                output = io.StringIO()
                with mock.patch.dict(self.ns, current=current, owned=mock.Mock(return_value=state)), \
                     mock.patch.object(sys, 'stdin', stream), mock.patch.object(sys, 'stdout', output), \
                     mock.patch.object(time, 'sleep') as sleep:
                    if final_launch == 'launch':
                        exec(self.branch('capture'), self.ns)
                        self.assertEqual(sleep.call_count, 3)
                        self.assertIn("dsh_token='valid'", config.read_text())
                        self.assertTrue(ready.exists())
                        self.assertIn('\ufffd', output.getvalue())
                        self.assertNotIn('secret', output.getvalue())
                    else:
                        with self.assertRaises(ValueError):
                            exec(self.branch('capture'), self.ns)
                        self.assertEqual(sleep.call_count, 100)
                        self.assertEqual(config.read_text(), "dsh_token='old'\n")
                        self.assertFalse(ready.exists())
                stream.close()


class ProcessIdentityTests(unittest.TestCase):
    """Real child processes and private state only; no network or installed services."""

    def setUp(self):
        proc_pid = int(Path('/proc/self/stat').read_text().split()[0])
        if proc_pid != os.getpid():
            self.skipTest('/proc is outside the PID namespace; cannot verify real process identity')
        self.tmp = tempfile.TemporaryDirectory(prefix='dsh-identity-')
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.script = self.root / 'dsh_web_run.sh'
        shutil.copy2(Path(__file__).with_name(self.script.name), self.script)
        self.logs = self.root / 'log'
        self.logs.mkdir()
        (self.root / 'data').mkdir()
        self.config = self.root / 'data/dsh.conf'
        self.config.write_text("dsh_token='stale-token'\n")
        self.bins = self.root / 'bin'
        self.bins.mkdir()
        # An actual ELF binary invoked through a bare PATH name, like magpie.
        shutil.copy2(shutil.which('sleep'), self.bins / 'magpie')
        self.env = {**os.environ, 'PATH': f'{self.bins}:{os.environ["PATH"]}',
                    'PYTHONOPTIMIZE': '2', 'DSH_READY_ATTEMPTS': '2',
                    'DSH_READY_INTERVAL': '.02'}
        self.children = []
        self.addCleanup(self.cleanup_children)

    def cleanup_children(self):
        for pid in self.children:
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    def shell(self, body):
        # Persist output: capture's child must not inherit a subprocess pipe.
        with (self.root / 'launcher.log').open('ab') as output:
            result = subprocess.run(['bash', '-c', 'source "$1"; ' + body,
                                     'test', str(self.script)], env=self.env,
                                    stdout=output, stderr=output, timeout=12)
        return result.returncode

    def launch(self, service='magpie-serve'):
        result = self.shell(f'start_service {service} magpie 60')
        pid = int((self.logs / f'{service}.pid').read_text())
        self.children.append(pid)
        self.assertEqual(result, 0, (self.root / 'launcher.log').read_text())
        return pid

    def test_clear_token_waits_for_pending_capture_transaction(self):
        marker = self.root / 'clear-started'
        with (self.logs / '.process-state.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            process = subprocess.Popen(
                ['bash', '-c', 'source "$1"; printf started >"$2"; write_token ""',
                 'test', str(self.script), str(marker)], env=self.env,
                stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            try:
                try:
                    deadline = time.monotonic() + 5
                    while not marker.exists():
                        self.assertIsNone(process.poll())
                        self.assertLess(time.monotonic(), deadline)
                        time.sleep(.01)
                    with self.assertRaises(subprocess.TimeoutExpired):
                        process.wait(timeout=.2)
                    # A previously admitted capture finishes while holding the lock.
                    self.config.write_text("dsh_token='late-capture'\n")
                finally:
                    fcntl.flock(lock, fcntl.LOCK_UN)
                _, error = process.communicate(timeout=5)
                self.assertEqual(process.returncode, 0, error)
                self.assertEqual(self.config.read_text().strip(), "dsh_token=''")
            finally:
                if process.poll() is None:
                    process.terminate()
                    process.wait(timeout=5)
                if process.stderr is not None:
                    process.stderr.close()

    def test_native_absolute_argv_reuse_and_pidfd_stop(self):
        pid = self.launch()
        self.assertEqual(Path(f'/proc/{pid}/cmdline').read_bytes().split(b'\0')[0],
                         str(self.bins / 'magpie').encode())
        self.assertEqual(self.shell('start_service magpie-serve magpie 60'), 0)
        self.assertEqual(int((self.logs / 'magpie-serve.pid').read_text()), pid)
        self.assertEqual(self.shell('stop_service magpie-serve'), 0)
        self.assertFalse((self.logs / 'magpie-serve.identity').exists())

    def test_pidfd_stop_without_python_wrappers(self):
        # Lead's main namespace exercises the real libc path with a private child.
        site = self.root / 'python-site'
        site.mkdir()
        (site / 'sitecustomize.py').write_text(
            "import os, signal\n"
            "for module, name in ((os, 'pidfd_open'), (signal, 'pidfd_send_signal')):\n"
            "    if hasattr(module, name): delattr(module, name)\n")
        self.env['PYTHONPATH'] = str(site)
        self.launch()
        self.assertEqual(self.shell('stop_service magpie-serve'), 0,
                         (self.root / 'launcher.log').read_text())
        self.assertFalse((self.logs / 'magpie-serve.identity').exists())

    def test_identity_mutations_fail_closed_even_with_python_optimization(self):
        pid = self.launch()
        path = self.logs / 'magpie-serve.identity'
        original = json.loads(path.read_text())
        for field in ('start', 'boot', 'uid', 'argv', 'root', 'launch', 'service'):
            with self.subTest(field=field):
                state = json.loads(json.dumps(original))
                target = state['identity'] if field in state['identity'] else state
                target[field] = 'wrong'
                path.write_text(json.dumps(state))
                for operation in ('service_pid magpie-serve', 'stop_service magpie-serve',
                                  'start_service magpie-serve magpie 60'):
                    self.assertEqual(self.shell(operation), 2)
                self.assertEqual(json.loads(path.read_text()), state)
                os.kill(pid, 0)
        path.write_text(json.dumps(original))
        self.assertEqual(self.shell('stop_service magpie-serve'), 0)

    def test_wrong_pid_and_live_legacy_state_are_not_adopted(self):
        self.launch()
        unrelated = subprocess.Popen(['sleep', '60'])
        self.addCleanup(unrelated.wait)
        self.addCleanup(unrelated.kill)
        pidfile = self.logs / 'magpie-serve.pid'
        pidfile.write_text(str(unrelated.pid))
        for legacy in (False, True):
            with self.subTest(legacy=legacy):
                if legacy:
                    (self.logs / 'magpie-serve.identity').unlink()
                for command in ('stop', 'start_service magpie-serve magpie 60'):
                    self.assertNotEqual(self.shell(command), 0)
                self.assertIsNone(unrelated.poll())
                self.assertEqual(pidfile.read_text(), str(unrelated.pid))
                self.assertIn('stale-token', self.config.read_text())

    def test_slow_token_retry_exact_url_and_persistent_ready(self):
        script = self.bins / 'dsh'
        script.write_text(f'''#!{sys.executable}
import pathlib, signal, time
root = pathlib.Path(__file__).parent.parent
print('unrelated https://example.test/?token=wrong', flush=True)
print('dsh web: https://wrong.test/?token=wrong', flush=True)
while not (root / 'release').exists(): time.sleep(.01)
print('dsh web: https://example.test/?token=first-token', flush=True)
while not (root / 'later').exists(): time.sleep(.01)
print('dsh web: https://example.test/?token=later-token', flush=True)
print('unrelated ?token=secret-later', flush=True)
(root / 'printed').touch()
signal.pause()
''')
        script.chmod(0o755)
        command = 'start_service dsh-web dsh web --port 12345 --public-url https://example.test/'
        self.assertNotEqual(self.shell(command), 0)
        pidfile = self.logs / 'dsh-web.pid'
        pid = int(pidfile.read_text())
        self.children.append(pid)
        self.assertIn("dsh_token=''", self.config.read_text())
        self.assertFalse((self.logs / '.dsh-web-token-captured').exists())
        (self.root / 'release').touch()
        self.env['DSH_READY_ATTEMPTS'] = '100'
        self.assertEqual(self.shell(command), 0)
        self.assertEqual(int(pidfile.read_text()), pid)
        (self.root / 'later').touch()
        deadline = time.monotonic() + 3
        while not (self.root / 'printed').exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.02)
        self.assertEqual(self.shell(command), 0)
        self.assertIn("dsh_token='first-token'", self.config.read_text())
        self.assertNotIn('later-token', self.config.read_text())
        ready = self.logs / '.dsh-web-token-captured'
        original = ready.read_text()
        for field in ('state', 'token_sha256'):
            state = json.loads(original)
            state[field] = 'wrong'
            ready.write_text(json.dumps(state))
            self.assertEqual(self.shell('process_state ready dsh-web'), 2)
        ready.write_text(original)
        self.config.write_text("dsh_token='changed'\n")
        self.assertEqual(self.shell('process_state ready dsh-web'), 2)
        self.assertEqual(self.shell('stop'), 0)
        self.assertFalse(ready.exists())
        log = (self.logs / 'dsh-web.log').read_text()
        for token in ('first-token', 'later-token', 'secret-later', 'token=wrong'):
            self.assertNotIn(token, log)



if __name__ == "__main__":
    unittest.main()
