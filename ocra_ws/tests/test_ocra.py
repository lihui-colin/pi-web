import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import tempfile
import textwrap
import unittest


ROOT = Path(__file__).resolve().parents[1]


class LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="ocra test ")
        self.root = Path(self.tmp.name)
        for name in ("ocra_web_run.sh", "ocra.conf.example"):
            shutil.copy2(ROOT / name, self.root / name)
        (self.root / "srcs").mkdir()
        shutil.copy2(ROOT / "srcs/ocra.py", self.root / "srcs/ocra.py")
        self.data = self.root / "data"
        self.data.mkdir()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        self.config = {"ip": "10.30.0.25", "port": self.port, "custom": "preserved"}
        self.write_config()
        self.cli = self.data / "orca-server/bin/orca-ide"
        self.cli.parent.mkdir(parents=True)
        self.cli.write_text(textwrap.dedent('''\
            #!/usr/bin/env python3
            import json, os, pathlib, signal, socket, sys, time
            root = pathlib.Path(__file__).resolve().parents[2]
            info = root / 'fake-runtime.json'
            args = sys.argv[1:]
            assert 'ORCA_ENVIRONMENT' not in os.environ
            assert 'ORCA_PAIRING_CODE' not in os.environ
            if args[0] == 'serve':
                port = int(args[args.index('--port') + 1])
                sock = socket.socket()
                sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                sock.bind(('0.0.0.0', port))
                sock.listen()
                info.write_text(json.dumps({'pid': os.getpid(), 'port': port}))
                signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
                while True: time.sleep(0.05)
            elif args[0] == 'status':
                runtime = json.loads(info.read_text())
                print(json.dumps({'ok': True, 'result': {'app': {'pid': runtime['pid']}, 'runtime': {'state': 'ready'}}}))
            elif args[0] == 'pair':
                raise RuntimeError('startup must not request pairing')
        '''))
        self.cli.chmod(0o700)

    def write_config(self):
        (self.data / "ocra.conf").write_text(json.dumps(self.config))

    def run_script(self, action):
        env = os.environ.copy()
        env.update(ORCA_ENVIRONMENT="remote-test", ORCA_PAIRING_CODE="unused")
        return subprocess.run(["bash", str(self.root / "ocra_web_run.sh"), action], cwd="/tmp",
                              text=True, capture_output=True, timeout=20, env=env)

    def tearDown(self):
        self.run_script("stop")
        self.tmp.cleanup()

    def test_start_status_repeat_stop_preserves_config(self):
        result = self.run_script("start")
        self.assertEqual(result.returncode, 0, result.stderr)
        saved = json.loads((self.data / "ocra.conf").read_text())
        self.assertEqual(saved, self.config)
        state = (self.data / "server.json").read_text()
        self.assertEqual(self.run_script("status").returncode, 0)
        self.assertEqual(self.run_script("start").returncode, 0)
        self.assertEqual((self.data / "server.json").read_text(), state)
        self.assertEqual(json.loads((self.data / "ocra.conf").read_text()), self.config)
        self.assertNotIn("orca://pair", (self.data / "server.log").read_text())
        # stop reads recorded parameters even when the configuration is invalid.
        (self.data / "ocra.conf").write_text("invalid json")
        stopped = self.run_script("stop")
        self.assertEqual(stopped.returncode, 0, stopped.stderr)
        self.assertFalse((self.data / "server.json").exists())

    def test_occupied_port_is_not_adopted_or_stopped(self):
        with socket.socket() as sock:
            sock.bind(("0.0.0.0", self.port))
            sock.listen()
            result = self.run_script("start")
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("已被占用", result.stderr)
            self.assertFalse((self.data / "server.json").exists())
            self.assertEqual(self.run_script("stop").returncode, 0)
            self.assertEqual(sock.getsockname()[1], self.port)

    def test_time_wait_does_not_block_start(self):
        with socket.socket() as listener:
            listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            listener.bind(("127.0.0.1", self.port))
            listener.listen()
            with socket.create_connection(("127.0.0.1", self.port), timeout=2) as client:
                accepted, _ = listener.accept()
                accepted.close()
                self.assertEqual(client.recv(1), b"")
        result = self.run_script("start")
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_start_does_not_refresh_legacy_pairing_config(self):
        self.config["pairingUrl"] = "legacy-value"
        self.write_config()
        before = (self.data / "ocra.conf").read_bytes()
        for _ in range(2):
            result = self.run_script("start")
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((self.data / "ocra.conf").read_bytes(), before)

    def test_recycled_pid_is_not_signalled(self):
        (self.data / "server.json").write_text(json.dumps({"pid": os.getpid(), "startTime": "not-current"}))
        self.assertEqual(self.run_script("stop").returncode, 0)
        self.assertFalse((self.data / "server.json").exists())

    def test_invalid_port_is_rejected(self):
        self.config["port"] = True
        self.write_config()
        result = self.run_script("start")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("port", result.stderr)


if __name__ == "__main__":
    unittest.main()
