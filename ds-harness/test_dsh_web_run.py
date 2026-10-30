"""Exercise launcher lifecycle with temporary services, without touching live sessions."""

import os
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

from test_support import create_test_certificate


class LauncherTests(unittest.TestCase):
    def test_certificate_directory_follows_address_and_rejects_fallback(self):
        with tempfile.TemporaryDirectory(prefix='dsh-cert-selection-') as temporary:
            root = Path(temporary)
            script = root / 'dsh_web_run.sh'
            shutil.copy2(Path(__file__).with_name('dsh_web_run.sh'), script)
            shutil.copy2(Path(__file__).with_name('dsh_nginx.py'), root / 'dsh_nginx.py')
            seed = root / 'seed'
            seed.mkdir()
            cert, key = create_test_certificate(seed)
            config = root / 'dsh.conf'
            # Stub service management: exercise selection and TLS validation only.
            command = ['bash', '-c', 'source "$1"; service_pid() { return 1; }; '
                       'start_service() { printf "SERVICE %s\\n" "$*"; }; start', 'test', str(script)]
            for address, folder in [('127.0.0.1', '127.0.0.1'), ('10.30.0.25', '10.30.0.25'),
                                    ('DSH.Example.Test', 'dsh.example.test'), ('::1', '__1')]:
                with self.subTest(address=address):
                    directory = root / 'tls' / folder
                    directory.mkdir(parents=True)
                    shutil.copy2(cert, directory / 'fullchain.pem')
                    shutil.copy2(key, directory / 'privkey.pem')
                    config.write_text(f'port=25228\nserver_ip={address}\ntls_cert=stale.pem\ntls_key=stale.key\n')
                    result = subprocess.run(command, text=True, capture_output=True, timeout=10)
                    self.assertEqual(result.returncode, 0, result.stderr)
                    self.assertIn(f'--tls-cert {directory}/fullchain.pem', result.stdout)
                    self.assertIn(f'--tls-key {directory}/privkey.pem', result.stdout)
            # An unrelated IP directory and stale explicit paths must not be used.
            config.write_text(f'port=25228\nserver_ip=10.30.0.26\ntls_cert={cert}\ntls_key={key}\n')
            result = subprocess.run(command, text=True, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('tls/10.30.0.26/fullchain.pem', result.stderr)
            self.assertNotIn('SERVICE', result.stdout)
            config.write_text("port=25228\nserver_ip='../outside'\n")
            result = subprocess.run(command, text=True, capture_output=True, timeout=10)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('SERVICE', result.stdout)

    @unittest.skipUnless(shutil.which("nginx"), "nginx is required for launcher integration")
    def test_start_reuse_proxy_recovery_and_stop(self):
        with tempfile.TemporaryDirectory(prefix="dsh-launcher-") as temporary:
            root = Path(temporary)
            for name in ("dsh_web_run.sh", "dsh_nginx.py"):
                shutil.copy2(Path(__file__).with_name(name), root / name)
            binaries = root / "bin"
            binaries.mkdir()
            for name in ("dsh", "magpie"):
                command = binaries / name
                command.write_text(
                    f"#!{sys.executable}\n"
                    "import signal, sys\n"
                    "if sys.argv[0].endswith('/dsh'):\n"
                    "    print('dsh web: http://127.0.0.1/?token=test-launch-token', flush=True)\n"
                    "signal.pause()\n"
                )
                command.chmod(0o755)
            (binaries / "hostname").write_text("#!/bin/sh\nprintf '127.0.0.1\\n'\n")
            (binaries / "hostname").chmod(0o755)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            config = root / "dsh.conf"
            tls = root / 'tls/127.0.0.1'
            tls.mkdir(parents=True)
            generated_cert, generated_key = create_test_certificate(tls)
            cert, key = tls / 'fullchain.pem', tls / 'privkey.pem'
            generated_cert.rename(cert)
            generated_key.rename(key)
            config.write_text(
                f"port={port}\nserver_ip=127.0.0.1\ndsh_token=''\n"
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
                return {p.stem: int(p.read_text()) for p in root.glob("*.pid")}

            try:
                key.rename(key.with_suffix(".backup"))
                self.assertNotEqual(run("start"), 0)
                self.assertFalse(pids(), "missing TLS key must fail before starting services")
                key.with_suffix(".backup").rename(key)
                self.assertEqual(run("start"), 0, (root / "launcher.log").read_text())
                self.assertIn(
                    f"访问地址：https://127.0.0.1:{port}/",
                    (root / "launcher.log").read_text(),
                )
                original = pids()
                self.assertEqual(len(original), 3)
                nginx_runtime = root / f".nginx-{port}"
                nginx_config = nginx_runtime / "nginx.conf"
                self.assertEqual(nginx_runtime.stat().st_mode & 0o777, 0o700)
                self.assertEqual(nginx_config.stat().st_mode & 0o777, 0o600)
                self.assertIn("dsh_token='test-launch-token'", config.read_text())
                self.assertEqual(config.stat().st_mode & 0o077, 0)
                self.assertNotIn("test-launch-token", (root / "dsh-web.log").read_text())
                self.assertEqual(run("start"), 0)
                self.assertEqual(pids(), original)

                backend = Path(f'/proc/{original["dsh-web"]}/cmdline').read_bytes().split(b"\0")
                backend_port = backend[backend.index(b"--port") + 1]
                self.assertEqual(
                    backend[backend.index(b"--public-url") + 1],
                    f"https://127.0.0.1:{port}/".encode(),
                )
                # Changing the advertised URL must never silently reuse/restart a backend.
                original_config = config.read_text()
                config.write_text(original_config.replace('server_ip=127.0.0.1', 'server_ip=localhost'))
                self.assertNotEqual(run("start"), 0)
                self.assertEqual(pids(), original)
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


if __name__ == "__main__":
    unittest.main()
