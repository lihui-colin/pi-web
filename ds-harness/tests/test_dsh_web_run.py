from test_support import source_file, fixture_file
"""Exercise launcher lifecycle with temporary services, without touching live sessions."""

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

from test_support import copy_test_launcher, copy_test_nginx, create_test_certificate, local_nginx

NGINX = local_nginx()


class LauncherTests(unittest.TestCase):
    def test_stop_attempts_every_service_and_reports_failures(self):
        services = ['magpie-web-proxy', 'dsh-token-proxy', 'dsh-web', 'magpie-serve']
        cases = [(service, 1, len(services)) for service in services]
        cases += [('', status, len(services)) for status in (0, 2, 1)]
        for failed, identity_status, count in cases:
            with self.subTest(failed=failed, identity=identity_status), tempfile.TemporaryDirectory() as temporary:
                root = Path(temporary)
                copy_test_launcher(root)
                config = root / 'data/dsh.conf'
                config.parent.mkdir(exist_ok=True)
                config.write_text('test configuration')
                capture = root / 'capture'
                capture.write_text('test captured state')
                wrapper = '''source "$1"
failed=$2 identity_status=$3
token_capture_file="$script_dir/capture"
prepare_runtime() { :; }
stop_service() { printf '%s\\n' "$1"; [[ "$1" != "$failed" ]]; }
service_pid() { return "$identity_status"; }
write_token() { printf 'clear-token\\n'; }
stop
'''
                result = subprocess.run(['bash', '-c', wrapper, 'test', str(root / 'dsh_web_run.sh'),
                                         failed, str(identity_status)], capture_output=True, text=True, timeout=5)
                success = not failed and identity_status == 1
                expected = services[:count] + (['clear-token'] if success else [])
                self.assertEqual(result.stdout.splitlines(), expected, result.stderr)
                self.assertEqual(result.returncode == 0, success, result.stderr)
                self.assertEqual(capture.exists(), not success)
                if failed:
                    self.assertIn('停止失败：' + failed, result.stderr)
                self.assertEqual(config.read_text(), 'test configuration')

    def test_main_serializes_operations_and_releases_lock_after_failure(self):
        for held, contender in [('start', 'start'), ('start', 'stop'), ('stop', 'start')]:
            with self.subTest(held=held, contender=contender), tempfile.TemporaryDirectory(
                    prefix='dsh-launcher-lock-') as temporary:
                root = Path(temporary)
                script = root / 'dsh_web_run.sh'
                copy_test_launcher(root)
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
            copy_test_launcher(root)
            # Isolate address validation from Nginx availability and socket permissions.
            (fixture_file(root, 'dsh_nginx.py')).write_text('def require_local_nginx(): pass\n')
            binaries = root / 'bin'
            binaries.mkdir()
            for name in ('dsh', 'magpie', 'hostname'):
                executable = binaries / name
                executable.write_text('#!/bin/sh\ntouch "$(dirname "$0")/called-' + name + '"\n'
                                      "printf '%s\\n' \"${TEST_HOST_IPS-127.0.0.2}\"\n")
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
                ('0:0:0:0:0:0:0:1', '127.0.0.1', '127.0.0.1'),
                ('::ffff:192.0.2.1', '127.0.0.1', '127.0.0.1'),
                ('::ffff:c000:201', '127.0.0.1', '127.0.0.1'),
                ('2001:db8::25', '', '127.0.0.2'),
                ('192.0.2.25', None, '127.0.0.2'),
                ('DSH.Example.Test', '127.0.0.1', '127.0.0.1'),
                ('dsh.example.test', '::1', '::1'),
                ('203.0.113.25', '127.0.0.1', '127.0.0.1'),
                ('dsh.example.test', None, '127.0.0.2'),
                ('dsh.example.test', '', '127.0.0.2'),
            ] + [('127.0.0.1', invalid, None) for invalid in
                 ('localhost', 'https://127.0.0.1', '127.0.0.1:25228', '[::1]', '999.0.0.1', '::gg', '127.0.0.1/8')]
            canonical_hosts = {
                '0:0:0:0:0:0:0:1': '[::1]',
                '::ffff:192.0.2.1': '[::ffff:c000:201]',
                '::ffff:c000:201': '[::ffff:c000:201]',
                '::1': '[::1]',
                '2001:db8::25': '[2001:db8::25]',
            }
            for address, listen, expected in cases:
                # Explicit scheme-default ports must remain exact-port grants.
                port = {'0:0:0:0:0:0:0:1': 443, '::ffff:192.0.2.1': 80}.get(address, 25228)
                with self.subTest(address=address, listen=listen):
                    tls = root / 'data/tls' / address.lower().replace(':', '_')
                    tls.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(cert, tls / 'fullchain.pem')
                    shutil.copy2(key, tls / 'privkey.pem')
                    config.write_text(f"port={port}\nserver_ip='{address}'\n" +
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
                        self.assertIn(f'--listen-host {expected} --listen-port {port}', proxy)
                        host = canonical_hosts.get(address, address.lower())
                        self.assertIn(f'--public-host {host}:{port}', proxy)
                        self.assertIn(f'访问地址：https://{host}:{port}/', result.stdout)
                        backend = next(line for line in result.stdout.splitlines()
                                       if line.startswith('SERVICE dsh-web '))
                        self.assertIn(f'--trusted-host {host}:{port} --trusted-host 127.0.0.1:12346', backend)
                        self.assertIn(f'--public-url https://{host}:{port}/ --no-open', backend)
                        self.assertIn(f'--tls-cert {tls}/fullchain.pem', proxy)
                        self.assertIn(f'--tls-key {tls}/privkey.pem', proxy)
                    self.assertFalse((binaries / 'called-dsh').exists())
                    self.assertFalse((binaries / 'called-magpie').exists())
                    self.assertFalse(list((root / 'log').glob('*.pid')))

            # Ambiguous/missing automatic candidates and explicit nonlocal IPs fail
            # before any service starts; explicit values never silently fall back.
            for listen, candidates, message in [
                ('', '127.0.0.2 127.0.0.3', '无法唯一确定'),
                ('', '', '无法唯一确定'),
                ('192.0.2.25', '127.0.0.2', '无法在本机绑定'),
            ]:
                with self.subTest(listen=listen, candidates=candidates):
                    config.write_text(f"port=25228\nserver_ip=dsh.example.test\nlisten_host='{listen}'\n")
                    result = subprocess.run(command, env={**environment, 'TEST_HOST_IPS': candidates},
                                            capture_output=True, text=True, timeout=10)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(message, result.stderr)
                    self.assertNotIn('SERVICE', result.stdout)

    def test_migration_preserves_open_logs_and_legacy_runtime_paths(self):
        with tempfile.TemporaryDirectory(prefix="dsh-runtime-migration-") as temporary:
            root = Path(temporary)
            script = root / "dsh_web_run.sh"
            copy_test_launcher(root)
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
            copy_test_launcher(root)
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
            for name in ("dsh_web_run.sh", "dsh_runtime.py", "dsh_nginx.py", "magpie_nginx.py"):
                shutil.copy2(source_file(name), fixture_file(root, name))
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
            copy_test_launcher(root)
            shutil.copy2(source_file('dsh_nginx.py'), fixture_file(root, 'dsh_nginx.py'))
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
                                      + ('listen_host=127.0.0.1\n' if address in ('DSH.Example.Test', '10.30.0.25') else '')
                                      + 'tls_cert=stale.pem\ntls_key=stale.key\n')
                    result = subprocess.run(command, text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f'--tls-cert {directory}/fullchain.pem', result.stdout)
                    self.assertIn(f'--tls-key {directory}/privkey.pem', result.stdout)
            # An unrelated IP directory and stale explicit paths must not be used.
            config.write_text(f'port=25228\nserver_ip=10.30.0.26\nlisten_host=127.0.0.1\ntls_cert={cert}\ntls_key={key}\n')
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
            for name in ("dsh_web_run.sh", "dsh_runtime.py", "dsh_nginx.py", "magpie_nginx.py"):
                shutil.copy2(source_file(name), fixture_file(root, name))
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
                with socket.socket(socket.AF_INET6 if ':' in address else socket.AF_INET) as magpie_reservation:
                    magpie_reservation.bind((address, 0))
                    magpie_port = magpie_reservation.getsockname()[1]
            config = root / "data/dsh.conf"
            config.parent.mkdir(exist_ok=True)
            tls = root / 'data/tls' / address.replace(':', '_')
            tls.mkdir(parents=True)
            generated_cert, generated_key = create_test_certificate(tls)
            cert, key = tls / 'fullchain.pem', tls / 'privkey.pem'
            generated_cert.rename(cert)
            generated_key.rename(key)
            config.write_text(
                f"port={port}\nserver_ip={address}\nmagpie_port={magpie_port}\ndsh_token=''\n"
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
                self.assertEqual(set(original), {'magpie-serve', 'magpie-web-proxy',
                                                 'dsh-web', 'dsh-token-proxy'})
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
                # A crashed backend leaves the proxy alive; stop must still clear
                # every component so a subsequent start can recover the instance.
                os.kill(recovered['dsh-web'], signal.SIGKILL)
                self.assertEqual(run("stop"), 0)
                self.assertFalse(pids())
                self.assertFalse(nginx_config.exists())
                self.assertIn("dsh_token=''", config.read_text())
                self.assertEqual(run("stop"), 0)
                self.assertEqual(run("start"), 0, (root / 'launcher.log').read_text())
                self.assertNotEqual(pids()['dsh-web'], recovered['dsh-web'])
                self.assertEqual(run("stop"), 0)
            finally:
                run("stop")

    def test_pidfd_preflight_failure_never_starts_services(self):
        with tempfile.TemporaryDirectory(prefix='dsh-pidfd-preflight-') as temporary:
            root = Path(temporary)
            script = root / 'dsh_web_run.sh'
            copy_test_launcher(root)
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
            copy_test_launcher(root)
            (fixture_file(root, 'dsh_nginx.py')).write_text('def require_local_nginx(): pass\n')
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
            # Discover each branch's probes, then inject failure at every one.
            cases = [(0, backend) for backend in (0, 1)]
            for probe, backend in cases:
                with self.subTest(probe=probe, backend=backend):
                    (root / 'counter').write_text('0')
                    body = '''source "$1"
service_pid() {
    local count
    read -r count < "$script_dir/counter" || true
    count=$((count + 1))
    printf '%s\n' "$count" > "$script_dir/counter"
    [[ "$count" != "$probe" ]] || return 2
    if [[ "$1" == dsh-web && "$backend" == 1 ]]; then echo 12345; return 0; fi
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
                    count = int((root / 'counter').read_text())
                    if probe == 0:
                        self.assertEqual(result.returncode, 0, result.stderr)
                        self.assertTrue((root / 'started').exists())
                        (root / 'started').unlink()
                        cases.extend((index, backend) for index in range(1, count + 1))
                    else:
                        self.assertNotEqual(result.returncode, 0, result.stderr)
                        self.assertFalse((root / 'started').exists())
                        self.assertEqual(count, probe)
                    self.assertEqual(config.read_text(), original)

    def test_stop_final_unknown_identity_preserves_ready_and_token(self):
        with tempfile.TemporaryDirectory(prefix='dsh-stop-probe-') as temporary:
            root = Path(temporary)
            script = root / 'dsh_web_run.sh'
            copy_test_launcher(root)
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


class MagpieWebTests(unittest.TestCase):
    """Private launcher copies and child processes; never start installed services."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix='dsh-magpie-web-')
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        copy_test_launcher(self.root)
        fixture_file(self.root, 'dsh_nginx.py').write_text('def require_local_nginx(): pass\n')
        tls = self.root / 'data/tls/127.0.0.1'
        tls.mkdir(parents=True)
        cert, key = create_test_certificate(tls)
        shutil.copy2(cert, tls / 'fullchain.pem')
        shutil.copy2(key, tls / 'privkey.pem')
        self.config = self.root / 'data/dsh.conf'
        bins = self.root / 'bin'
        bins.mkdir()
        for name in ('magpie', 'dsh'):
            executable = bins / name
            executable.write_text('#!/bin/sh\nexit 99\n')
            executable.chmod(0o755)
        self.env = {**os.environ, 'PATH': f'{bins}:{os.environ["PATH"]}'}

    def start(self, web_port=None, public_port='25228', live_pid=None, host_ip=None,
              magpie_port=None, proxy_pid=None):
        original = f"server_ip=127.0.0.1\nport={public_port}\ndsh_token='preserve'\n"
        for name, value in [('magpie_web_port', web_port), ('host_ip', host_ip),
                            ('magpie_port', magpie_port)]:
            if value is not None:
                original += f"{name}='{value}'\n"
        self.config.write_text(original)
        body = '''source "$1"
service_pid() {
    if [[ "$1" == magpie-serve && -n "$live_pid" ]]; then
        printf '%s\\n' "$live_pid"
    elif [[ "$1" == magpie-web-proxy && -n "$proxy_pid" ]]; then
        printf '%s\\n' "$proxy_pid"
    else
        return 1
    fi
}
start_service() {
    printf 'SERVICE %s\\n' "$*"
    if [[ "$1" == magpie-serve ]]; then
        printf '%s\\n' "$MAGPIE_WEB_KEY" > "$script_dir/observed-key"
        printf 'MAGPIE_URL %s\\n' "$MAGPIE_PUBLIC_URL"
    fi
}
stop_service() { printf 'STOP %s\\n' "$*"; return 99; }
live_pid=$2 proxy_pid=$3
main start
'''
        result = subprocess.run(['bash', '-c', body, 'test', str(self.root / 'dsh_web_run.sh'),
                                 str(live_pid) if live_pid is not None else '',
                                 str(proxy_pid) if proxy_pid is not None else ''],
                                env=self.env, capture_output=True, text=True, timeout=10)
        self.assertEqual(self.config.read_text(), original)
        self.assertNotIn('STOP ', result.stdout)
        self.assertFalse(list((self.root / 'log').glob('*.pid')))
        return result

    def assert_started(self, result, port, host='127.0.0.1', magpie_port=25226):
        self.assertEqual(result.returncode, 0, result.stderr)
        services = [line for line in result.stdout.splitlines() if line.startswith('SERVICE ')]
        self.assertEqual([line.split()[1] for line in services],
                         ['magpie-serve', 'magpie-web-proxy', 'dsh-web', 'dsh-token-proxy'])
        self.assertEqual(services[0], f'SERVICE magpie-serve magpie serve --web=127.0.0.1:{port}')
        public_host = f'[{host}]' if ':' in host else host
        url = f'https://{public_host}:{magpie_port}/'
        self.assertIn(url, result.stdout)
        self.assertIn(f'MAGPIE_URL {url}', result.stdout)
        self.assertIn('无需填写 token', result.stdout)
        key_file = self.root / 'data/.magpie-web-key'
        self.assertEqual(key_file.stat().st_mode & 0o777, 0o600)
        self.assertEqual((self.root / 'observed-key').read_text(), key_file.read_text())
        self.assertNotIn(key_file.read_text().strip(), result.stdout + result.stderr)
        proxy = services[1]
        for option in (f'--listen-host {host}', f'--listen-port {magpie_port}',
                       '--upstream-host 127.0.0.1', f'--upstream-port {port}',
                       f'--public-host {public_host}:{magpie_port}',
                       f'--config {self.config}',
                       f'--magpie-key-file {self.root}/data/.magpie-web-key',
                       f'--tls-cert {self.root}/data/tls/{host.replace(":", "_")}/fullchain.pem',
                       f'--tls-key {self.root}/data/tls/{host.replace(":", "_")}/privkey.pem'):
            self.assertIn(option, proxy)

    def test_default_custom_boundary_and_decimal_web_ports(self):
        for value, expected in [(None, 3430), ('4343', 4343), ('1', 1), ('65535', 65535),
                                ('03430', 3430), ('00008', 8)]:
            with self.subTest(port=value):
                self.assert_started(self.start(value), expected)

    def test_custom_https_host_and_public_port_keep_backend_on_loopback(self):
        tls = self.root / 'data/tls/127.0.0.2'
        shutil.copytree(self.root / 'data/tls/127.0.0.1', tls)
        self.assert_started(self.start('4343', host_ip='127.0.0.2', magpie_port='25443'),
                            4343, '127.0.0.2', 25443)

    def test_public_https_port_validation_and_collisions_precede_launch(self):
        for value in ('', '0', '-1', '65536', 'abc', '25 226', '25228', '3430', '03430'):
            with self.subTest(port=value):
                result = self.start(magpie_port=value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('magpie', result.stderr)
                self.assertNotIn('SERVICE ', result.stdout)
        result = self.start('25226')
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn('SERVICE ', result.stdout)

    def test_invalid_https_host_and_missing_host_certificate_precede_launch(self):
        for value in ('https://127.0.0.1', '../outside', '127.0.0.1:25226', '127.0.0.2'):
            with self.subTest(host=value):
                result = self.start(host_ip=value)
                self.assertNotEqual(result.returncode, 0)
                self.assertNotIn('SERVICE ', result.stdout)

    def test_invalid_web_ports_fail_before_any_service_starts(self):
        for value in ('', '0', '00000', '-1', '65536', '999999999999999999999999999999',
                      'abc', '0x10', '1.5', '+3430', ' 3430', '3430 ', '34 30'):
            with self.subTest(port=value):
                result = self.start(value)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('magpie_web_port', result.stderr)
                self.assertNotIn('SERVICE ', result.stdout)

    def test_public_port_collision_fails_before_any_service_starts(self):
        for web, public in [(None, '3430'), ('4343', '4343'), ('03430', '3430'),
                            ('3430', '03430')]:
            with self.subTest(web=web, public=public):
                result = self.start(web, public)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('magpie_web_port', result.stderr)
                self.assertNotIn('SERVICE ', result.stdout)

    def child(self, arguments):
        process = subprocess.Popen(
            [sys.executable, '-c', "import signal; print('ready', flush=True); signal.pause()",
             *arguments], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)

        def cleanup():
            if process.poll() is None:
                process.kill()
            process.communicate(timeout=5)

        self.addCleanup(cleanup)
        self.assertEqual(process.stdout.readline(), 'ready\n')
        return process

    def test_live_magpie_accepts_matching_web_option_in_both_forms(self):
        for arguments in (['--web=127.0.0.1:4343'], ['--web', '127.0.0.1:4343']):
            with self.subTest(arguments=arguments):
                process = self.child(arguments)
                self.assert_started(self.start('4343', live_pid=process.pid), 4343)
                self.assertIsNone(process.poll())

    def test_live_magpie_missing_or_mismatched_web_requires_maintenance(self):
        for arguments in ([], ['--web=127.0.0.1:3430'], ['--web', '127.0.0.1:3430'],
                          ['--web=0.0.0.0:4343'], ['--web=localhost:4343'],
                          ['--web='], ['--web'], ['--web-extra=127.0.0.1:4343']):
            with self.subTest(arguments=arguments):
                process = self.child(arguments)
                result = self.start('4343', live_pid=process.pid)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('Magpie', result.stderr)
                self.assertIn('stop', result.stderr)
                self.assertIn('start', result.stderr)
                self.assertNotIn('SERVICE ', result.stdout)
                self.assertIsNone(process.poll(), 'existing Magpie process must remain alive')

    def test_private_key_is_reused_across_starts(self):
        self.assert_started(self.start(), 3430)
        key_file = self.root / 'data/.magpie-web-key'
        original = key_file.read_bytes()
        self.assert_started(self.start(), 3430)
        self.assertEqual(key_file.read_bytes(), original)

    def test_live_https_proxy_matches_or_refuses_drift_without_stopping_child(self):
        expected = {'--listen-host': '127.0.0.1', '--listen-port': '25226',
                    '--upstream-host': '127.0.0.1', '--upstream-port': '3430',
                    '--public-host': '127.0.0.1:25226'}
        cases = [(None, None), ('--listen-host', '127.0.0.2'),
                 ('--listen-port', '25443'), ('--upstream-host', '127.0.0.2'),
                 ('--upstream-port', '4343'),
                 ('--public-host', 'localhost:25226')]
        for option, value in cases:
            with self.subTest(option=option):
                options = dict(expected)
                if option:
                    options[option] = value
                process = self.child([part for pair in options.items() for part in pair])
                result = self.start(proxy_pid=process.pid)
                if option is None:
                    self.assert_started(result, 3430)
                else:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('Magpie', result.stderr)
                    self.assertIn('stop/start', result.stderr)
                    self.assertNotIn('SERVICE ', result.stdout)
                self.assertIsNone(process.poll(), 'existing HTTPS proxy must remain alive')

    def test_process_option_preserves_equals_spaces_and_exact_option_names(self):
        for arguments, option, expected in [
                (['--web=127.0.0.1:3430'], '--web', '127.0.0.1:3430'),
                (['--web', '127.0.0.1:3430'], '--web', '127.0.0.1:3430'),
                (['--name=value with spaces=tail'], '--name', 'value with spaces=tail'),
                (['--name', 'value with spaces=tail'], '--name', 'value with spaces=tail'),
                (['--web-extra=wrong', '--web=right'], '--web', 'right'),
                (['--web-extra=wrong'], '--web', None),
                (['--web'], '--web', None)]:
            with self.subTest(arguments=arguments):
                process = self.child(arguments)
                result = subprocess.run(
                    ['bash', '-c', 'source "$1"; process_option "$2" "$3"', 'test',
                     str(self.root / 'dsh_web_run.sh'), str(process.pid), option],
                    capture_output=True, text=True, timeout=5)
                if expected is None:
                    self.assertNotEqual(result.returncode, 0)
                    self.assertEqual(result.stdout, '')
                else:
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertEqual(result.stdout, expected + '\n')


class ProcessHelperTests(unittest.TestCase):
    """Execute the runtime helpers/branches without relying on the /proc namespace."""

    def setUp(self):
        source = source_file('dsh_runtime.py').read_text()
        self.ns = {'__name__': 'test_runtime'}
        exec(compile(source, 'dsh_runtime.py', 'exec'), self.ns)

    def test_environment_denied_uses_exact_recorded_identity_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            statefile = root / 'identity'
            now = dict(pid=123, start='456', boot='boot', uid=os.geteuid(), argv=[b'/bin/sleep', b'60'])
            state = dict(root=str(root), service='test', launch='launch',
                         identity={**now, 'argv': ['/bin/sleep', '60']})
            statefile.write_text(json.dumps(state))
            self.ns.update(root=root, service='test', statefile=statefile)
            with mock.patch.object(Path, 'read_bytes', side_effect=PermissionError(errno.EACCES, 'denied')):
                self.assertEqual(self.ns['owned'](now), state)
                with self.assertRaises(PermissionError):
                    self.ns['owned'](now, require_environment=True)
                for key in ('pid', 'start', 'boot', 'uid', 'argv'):
                    with self.subTest(key=key), self.assertRaises(ValueError):
                        self.ns['owned']({**now, key: [] if key == 'argv' else 'wrong'})
                statefile.unlink()
                with self.assertRaises(FileNotFoundError):
                    self.ns['owned'](now)

    def test_exit_during_signal_is_already_stopped(self):
        from contextlib import nullcontext
        for phase in ('open', 'recheck', 'signal'):
            with self.subTest(phase=phase):
                current = mock.Mock(side_effect=[{'pid': 123}, ProcessLookupError()]
                                    if phase == 'recheck' else None, return_value={'pid': 123})
                opener = mock.Mock(side_effect=ProcessLookupError() if phase == 'open' else None,
                                   return_value=71)
                sender = mock.Mock(side_effect=ProcessLookupError() if phase == 'signal' else None)
                with mock.patch.dict(self.ns, operation='signal', current=current,
                                     owned=mock.Mock(return_value={'launch': 'test'}),
                                     open_pidfd=opener, send_pidfd=sender,
                                     state_lock=nullcontext), mock.patch.object(os, 'close') as close:
                    with self.assertRaises(SystemExit) as result:
                        self.ns['run_operation']()
                    self.assertEqual(result.exception.code, 1)
                    if phase == 'open':
                        close.assert_not_called()
                    else:
                        close.assert_called_once_with(71)
                    if phase != 'signal':
                        sender.assert_not_called()

    def test_stop_launch_timeout_preserves_registration(self):
        from contextlib import nullcontext
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'identity'
            now = {'pid': 123}
            state = {'identity': now, 'launch': 'test'}
            original = json.dumps(state)
            path.write_text(original)
            with mock.patch.dict(self.ns, statefile=path, current=mock.Mock(return_value=now),
                                 owned=mock.Mock(return_value=state), state_lock=nullcontext,
                                 launch_members=mock.Mock(return_value=[now]),
                                 snapshot=mock.Mock(return_value=now),
                                 open_pidfd=mock.Mock(return_value=71),
                                 send_pidfd=mock.Mock()), \
                 mock.patch.object(time, 'monotonic', side_effect=[0, 11]), \
                 mock.patch.object(os, 'close'):
                with self.assertRaisesRegex(ValueError, 'still running'):
                    self.ns['stop_launch']()
                self.assertEqual(path.read_text(), original)

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
                        self.ns['record_process']()
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
                    self.ns['capture_output']()
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
                        self.ns['capture_output']()
                        self.assertEqual(sleep.call_count, 3)
                        self.assertIn("dsh_token='valid'", config.read_text())
                        self.assertTrue(ready.exists())
                        self.assertIn('\ufffd', output.getvalue())
                        self.assertNotIn('secret', output.getvalue())
                    else:
                        with self.assertRaises(ValueError):
                            self.ns['capture_output']()
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
        copy_test_launcher(self.root)
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

    def launch_dsh(self):
        script = self.bins / 'dsh'
        script.write_text(f'#!{sys.executable}\nimport signal\n'
                          "print('dsh web: https://example.test/?token=test-token', flush=True)\n"
                          'signal.pause()\n')
        script.chmod(0o755)
        self.assertEqual(self.shell('start_service dsh-web dsh web --port 12345 '
                                    '--public-url https://example.test/'), 0,
                         (self.root / 'launcher.log').read_text())
        pid = int((self.logs / 'dsh-web.pid').read_text())
        self.children.append(pid)
        return pid

    def marked_child(self, code='import signal; signal.pause()', **overrides):
        state = json.loads((self.logs / 'dsh-web.identity').read_text())
        env = {**self.env, 'DSH_LAUNCH_ID': state['launch'],
               'DSH_LAUNCH_ROOT': str(self.root), **overrides}
        process = subprocess.Popen([sys.executable, '-c', code], env=env, start_new_session=True,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

        def cleanup():
            if process.poll() is None:
                process.kill()
            process.wait(timeout=5)

        self.addCleanup(cleanup)
        return process

    def test_stop_includes_all_detached_plugin_helpers_and_preserves_other_launches(self):
        self.launch_dsh()
        helpers = [self.marked_child() for _ in range(3)]
        other_launch = self.marked_child(DSH_LAUNCH_ID='another-launch')
        other_root = self.marked_child(DSH_LAUNCH_ROOT=str(self.root / 'other'))
        self.assertEqual(self.shell('stop'), 0, (self.root / 'launcher.log').read_text())
        for process in helpers:
            process.wait(timeout=3)
        self.assertIsNone(other_launch.poll())
        self.assertIsNone(other_root.poll())
        self.assertFalse((self.logs / 'dsh-web.identity').exists())
        self.assertIn("dsh_token=''", self.config.read_text())

    def test_stop_after_original_host_exits_kills_pending_restart(self):
        pid = self.launch_dsh()
        helper = self.marked_child()
        os.kill(pid, signal.SIGTERM)
        # The launcher must not call a missing original PID 'already stopped'
        # while detached plugin helpers still hold the inherited launch markers.
        deadline = time.monotonic() + 3
        while Path(f'/proc/{pid}/cmdline').exists() and Path(f'/proc/{pid}/cmdline').read_bytes():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
        self.assertEqual(self.shell('stop'), 0, (self.root / 'launcher.log').read_text())
        helper.wait(timeout=3)
        self.assertFalse((self.logs / 'dsh-web.pid').exists())

    def test_stop_rescans_child_spawned_during_shutdown(self):
        self.launch_dsh()
        marker = self.root / 'helper-ready'
        child_pid = self.root / 'late-child'
        helper = self.marked_child(f'''
import os, pathlib, signal, subprocess, sys
def restart(*args):
    child = subprocess.Popen([sys.executable, '-c', 'import signal; signal.pause()'], start_new_session=True)
    pathlib.Path({str(child_pid)!r}).write_text(str(child.pid))
    os._exit(0)
signal.signal(signal.SIGTERM, restart)
pathlib.Path({str(marker)!r}).touch()
signal.pause()
''')
        deadline = time.monotonic() + 3
        while not marker.exists():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
        self.assertEqual(self.shell('stop'), 0, (self.root / 'launcher.log').read_text())
        helper.wait(timeout=3)
        pid = int(child_pid.read_text())
        self.children.append(pid)
        stat = Path(f'/proc/{pid}/stat')
        self.assertTrue(not stat.exists() or stat.read_text().rsplit(')', 1)[1].split()[0] == 'Z')

    def test_exact_self_restart_replacement_is_registered_then_stopped(self):
        pid = self.launch_dsh()
        state = json.loads((self.logs / 'dsh-web.identity').read_text())
        os.kill(pid, signal.SIGTERM)
        deadline = time.monotonic() + 3
        while Path(f'/proc/{pid}/cmdline').exists() and Path(f'/proc/{pid}/cmdline').read_bytes():
            self.assertLess(time.monotonic(), deadline)
            time.sleep(.01)
        replacement = subprocess.Popen(state['identity']['argv'], start_new_session=True,
                                       env={**self.env, 'DSH_LAUNCH_ID': state['launch'],
                                            'DSH_LAUNCH_ROOT': str(self.root)},
                                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.children.append(replacement.pid)
        try:
            self.assertEqual(self.shell('service_pid dsh-web'), 0,
                             (self.root / 'launcher.log').read_text())
            self.assertEqual(int((self.logs / 'dsh-web.pid').read_text()), replacement.pid)
            self.assertEqual(self.shell('stop'), 0, (self.root / 'launcher.log').read_text())
            replacement.wait(timeout=3)
        finally:
            if replacement.poll() is None:
                replacement.kill()
            replacement.wait(timeout=3)

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

    def test_stop_with_environment_read_denied(self):
        self.launch()
        site = self.root / 'python-site'
        site.mkdir()
        (site / 'sitecustomize.py').write_text(
            "from pathlib import Path\n"
            "original = Path.read_bytes\n"
            "def read_bytes(path):\n"
            "    if str(path).startswith('/proc/') and path.name == 'environ':\n"
            "        raise PermissionError(13, 'denied')\n"
            "    return original(path)\n"
            "Path.read_bytes = read_bytes\n")
        self.env['PYTHONPATH'] = str(site)
        self.assertEqual(self.shell('stop'), 0, (self.root / 'launcher.log').read_text())
        self.assertFalse(list(self.logs.glob('*.pid')))
        self.assertIn("dsh_token=''", self.config.read_text())

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
                if legacy:
                    output = (self.root / 'launcher.log').read_text()
                    self.assertIn(f'缺少身份记录 {self.logs / "magpie-serve.identity"}', output)
                    self.assertIn('不要删除 PID 文件绕过检查', output)

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
