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


class LauncherTests(unittest.TestCase):
    def test_start_reuse_proxy_recovery_and_stop(self):
        with tempfile.TemporaryDirectory(prefix="dsh-launcher-") as temporary:
            root = Path(temporary)
            for name in ("dsh_web_run.sh", "dsh_token_proxy.py"):
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
            config.write_text(f"port={port}\nserver_ip=127.0.0.1\ndsh_token=''\n")
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
                self.assertEqual(run("start"), 0, (root / "launcher.log").read_text())
                original = pids()
                self.assertEqual(len(original), 3)
                self.assertIn("dsh_token='test-launch-token'", config.read_text())
                self.assertEqual(config.stat().st_mode & 0o077, 0)
                self.assertNotIn("test-launch-token", (root / "dsh-web.log").read_text())
                self.assertEqual(run("start"), 0)
                self.assertEqual(pids(), original)

                backend = Path(f'/proc/{original["dsh-web"]}/cmdline').read_bytes().split(b"\0")
                backend_port = backend[backend.index(b"--port") + 1]
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
                self.assertEqual(proxy[proxy.index(b"--upstream-port") + 1], backend_port)
                self.assertEqual(run("stop"), 0)
                self.assertFalse(pids())
                self.assertIn("dsh_token=''", config.read_text())
                self.assertEqual(run("stop"), 0)
            finally:
                run("stop")


if __name__ == "__main__":
    unittest.main()
