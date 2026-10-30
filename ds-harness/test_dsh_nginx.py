"""Isolated integration tests for the generated Nginx HTTPS proxy."""

import http.client
import os
import shutil
import signal
import socket
import ssl
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from collections import deque
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from unittest import mock

from dsh_nginx import cookie_name, parent_death_guard, render_config, require_local_nginx
from test_support import create_test_certificate, local_nginx

PAGE = b"<!doctype html><title>DeepSeek Harness</title>"
WAIT = 5
PUBLIC_HOST = "dsh.test:25228"
COOKIE_NAME = cookie_name(PUBLIC_HOST)
COOKIE_PAIR = COOKIE_NAME + "=browser-session"
COOKIE = COOKIE_PAIR + "; Path=/; HttpOnly; SameSite=Strict"
NGINX = local_nginx()


class NginxBinaryTests(unittest.TestCase):
    def test_privileged_binary_is_rejected_before_execution(self):
        with tempfile.TemporaryDirectory(prefix="dsh-nginx-privileged-") as temporary:
            root = Path(temporary)
            binary = root / 'data/.local/nginx/sbin/nginx'
            binary.parent.mkdir(parents=True)
            binary.write_text('#!/bin/sh\nexit 99\n')
            with mock.patch('dsh_nginx.__file__', str(root / 'dsh_nginx.py')), \
                    mock.patch('dsh_nginx.subprocess.run') as execute:
                for mode in (0o4755, 0o2755):
                    with self.subTest(mode=oct(mode)):
                        binary.chmod(mode)
                        with self.assertRaisesRegex(ValueError, 'set-ID'):
                            require_local_nginx()
                binary.chmod(0o755)
                with mock.patch('dsh_nginx.os.getxattr', return_value=b'file-capability'):
                    with self.assertRaisesRegex(ValueError, 'file capabilities'):
                        require_local_nginx()
                execute.assert_not_called()

    def test_local_binary_cannot_escape_installation_through_symlinks(self):
        for component in ("data", "data/.local", "data/.local/nginx",
                          "data/.local/nginx/sbin", "data/.local/nginx/sbin/nginx"):
            with self.subTest(component=component), tempfile.TemporaryDirectory(prefix="dsh-nginx-link-") as temporary:
                root = Path(temporary) / "project"
                root.mkdir()
                shutil.copy2(Path(__file__).with_name("dsh_nginx.py"), root / "dsh_nginx.py")
                outside = Path(temporary) / "outside"
                binary = outside / ".local/nginx/sbin/nginx"
                binary.parent.mkdir(parents=True)
                marker = outside / "executed"
                binary.write_text(f"#!{sys.executable}\nfrom pathlib import Path\n"
                                  f"Path({str(marker)!r}).touch()\nprint('nginx/1.30.0')\n")
                binary.chmod(0o700)
                link = root / component
                link.parent.mkdir(parents=True, exist_ok=True)
                target = outside.joinpath(*Path(component).parts[1:])
                link.symlink_to(target, target_is_directory=target.is_dir())
                result = subprocess.run(
                    [sys.executable, "-B", "-c", "from dsh_nginx import require_local_nginx; require_local_nginx()"],
                    cwd=root, text=True, capture_output=True, timeout=10,
                )
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("outside its installation directory", result.stderr)
                self.assertIn("dsh_nginx_install.sh", result.stderr)
                self.assertFalse(marker.exists(), "an external binary must not even run its version check")

    def test_symlink_to_binary_inside_installation_remains_local(self):
        with tempfile.TemporaryDirectory(prefix="dsh-nginx-local-link-") as temporary:
            root = Path(temporary)
            shutil.copy2(Path(__file__).with_name("dsh_nginx.py"), root / "dsh_nginx.py")
            binary = root / "data/.local/nginx/sbin/nginx-versioned"
            binary.parent.mkdir(parents=True)
            binary.write_text("#!/bin/sh\nprintf 'nginx/1.30.0' >&2\n")
            binary.chmod(0o700)
            binary.with_name("nginx").symlink_to(binary.name)
            result = subprocess.run(
                [sys.executable, "-B", "-c", "from dsh_nginx import require_local_nginx; print(require_local_nginx())"],
                cwd=root, text=True, capture_output=True, timeout=10,
            )
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual(result.stdout.strip(), str(binary))

    def test_direct_entry_rejects_unusable_local_binary_without_path_fallback(self):
        with tempfile.TemporaryDirectory(prefix="dsh-nginx-binary-") as temporary:
            root = Path(temporary)
            script = root / "dsh_nginx.py"
            shutil.copy2(Path(__file__).with_name("dsh_nginx.py"), script)
            binaries = root / "bin"
            binaries.mkdir()
            fallback = binaries / "nginx"
            fallback.write_text("#!/bin/sh\nprintf 'PATH nginx must not run' >&2\nexit 99\n")
            fallback.chmod(0o755)
            environment = {**os.environ, "PATH": f"{binaries}:{os.environ['PATH']}"}
            local = root / "data/.local/nginx/sbin/nginx"
            local.parent.mkdir(parents=True)
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            command = [
                sys.executable, str(script), "--listen-host", "127.0.0.1", "--listen-port", str(port),
                "--upstream-host", "127.0.0.1", "--upstream-port", str(port),
                "--public-host", f"127.0.0.1:{port}", "--config", str(root / "absent.conf"),
                "--tls-cert", str(root / "absent.pem"), "--tls-key", str(root / "absent.key"),
            ]
            # Nonexistent runtime inputs ensure all binary failures precede config/TLS reads.
            for label, contents, mode in [
                ("missing", None, 0),
                ("not executable", "#!/bin/sh\nexit 0\n", 0o600),
                ("invalid executable", "not an executable\n", 0o700),
                ("old version", "#!/bin/sh\nprintf 'nginx/1.22.1' >&2\n", 0o700),
                ("failed version", "#!/bin/sh\nprintf 'nginx/1.30.0' >&2\nexit 1\n", 0o700),
                ("invalid version", "#!/bin/sh\nprintf 'not nginx' >&2\n", 0o700),
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
                    self.assertNotIn("absent.conf", result.stderr)
                    self.assertFalse((root / "log").exists())


@unittest.skipUnless(sys.platform.startswith("linux"), "Linux parent-death signals")
class SupervisorTests(unittest.TestCase):
    def test_child_exits_if_parent_changed_before_signal_registration(self):
        with mock.patch("dsh_nginx.os.getpid", return_value=-1):
            guard = parent_death_guard()
        result = subprocess.run([sys.executable, "-c", "print('must not execute')"],
                                preexec_fn=guard, capture_output=True, timeout=WAIT)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(result.stdout, b"")

    @unittest.skipUnless(NGINX, "install the project-local Nginx")
    def test_supervisor_death_releases_master_workers_and_listener(self):
        def identity(pid):
            try:
                fields = Path(f"/proc/{pid}/stat").read_text().rsplit(")", 1)[1].split()
                return fields[19] if fields[0] != "Z" else None
            except FileNotFoundError:
                return None

        with tempfile.TemporaryDirectory(prefix="dsh-supervisor-death-") as temporary:
            root = Path(temporary)
            cert, key = create_test_certificate(root)
            config = root / "dsh.conf"
            config.write_text("dsh_token='test-supervisor-token'\n")
            with socket.socket() as reservation:
                reservation.bind(("127.0.0.1", 0))
                port = reservation.getsockname()[1]
            runtime = root / "log" / f".nginx-{port}"
            command = [sys.executable, "-B", str(Path(__file__).with_name("dsh_nginx.py")),
                       "--listen-host", "127.0.0.1", "--listen-port", str(port),
                       "--upstream-host", "127.0.0.1", "--upstream-port", "1",
                       "--public-host", f"localhost:{port}", "--config", str(config),
                       "--tls-cert", str(cert), "--tls-key", str(key)]
            # Reuse the same port after each termination to exercise recovery too.
            for termination in (signal.SIGKILL, signal.SIGTERM):
                with self.subTest(signal=termination), (root / "diagnostics").open("w") as diagnostics:
                    process = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=diagnostics)
                    owned = {}
                    try:
                        deadline = time.monotonic() + WAIT
                        while True:
                            self.assertIsNone(process.poll(), "supervisor failed before readiness")
                            try:
                                pid = int((runtime / "nginx.pid").read_text().strip())
                                if str(runtime).encode() not in Path(f"/proc/{pid}/cmdline").read_bytes():
                                    raise OSError("waiting for test-owned Nginx master")
                                owned[pid] = identity(pid)
                                with socket.create_connection(("127.0.0.1", port), timeout=.2) as raw:
                                    with ssl.create_default_context(cafile=str(cert)).wrap_socket(
                                            raw, server_hostname="localhost"):
                                        pass
                                break
                            except (OSError, ValueError):
                                if time.monotonic() >= deadline:
                                    self.fail("isolated Nginx did not become ready")
                                time.sleep(.02)
                        workers = Path(f"/proc/{pid}/task/{pid}/children").read_text().split()
                        self.assertTrue(workers, "test must observe a real Nginx worker")
                        owned = {value: identity(value) for value in [pid, *map(int, workers)]}
                        self.assertTrue(all(owned.values()))
                        process.send_signal(termination)
                        process.wait(timeout=WAIT)
                        deadline = time.monotonic() + WAIT
                        while any(identity(pid) == stamp for pid, stamp in owned.items()):
                            if time.monotonic() >= deadline:
                                self.fail("Nginx survived its supervisor")
                            time.sleep(.02)
                        with socket.socket() as probe:
                            probe.settimeout(.2)
                            self.assertNotEqual(probe.connect_ex(("127.0.0.1", port)), 0)
                    finally:
                        if process.poll() is None:
                            process.terminate()
                            process.wait(timeout=WAIT)
                        # Only test-owned processes with their original birth identity.
                        for pid, stamp in owned.items():
                            if stamp is not None and identity(pid) == stamp:
                                try:
                                    os.kill(pid, signal.SIGTERM)
                                except ProcessLookupError:
                                    pass


def reply(handler, status=200, headers=(), body=b"ok"):
    handler.send_response(status)
    for name, value in headers:
        handler.send_header(name, value)
    chunked = any(name.lower() == "transfer-encoding" and value == "chunked" for name, value in headers)
    if not chunked and status != 101:
        handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    if handler.command == "HEAD" or status in {204, 304}:
        return
    if chunked:
        if body:
            handler.wfile.write(f"{len(body):x}\r\n".encode() + body + b"\r\n")
        handler.wfile.write(b"0\r\nX-End: yes\r\n\r\n")
    else:
        handler.wfile.write(body)


def read_head(stream):
    line = stream.readline()
    if not line:
        raise EOFError("connection closed before response headers")
    return int(line.split()[1]), http.client.parse_headers(stream)


@unittest.skipUnless(NGINX, "run dsh_nginx_install.sh to install the project-local Nginx")
class NginxProxyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="dsh-nginx-cert-")
        cls.addClassCleanup(directory.cleanup)
        cls.cert, cls.key = create_test_certificate(directory.name)
        cls.client_context = ssl.create_default_context(cafile=str(cls.cert))

    @contextmanager
    def fixture(self, responses=(), handle=None):
        replies, requests, accepts, errors = deque(responses), [], [], []

        class Upstream(BaseHTTPRequestHandler):
            protocol_version = "HTTP/1.1"
            timeout = WAIT

            def do_GET(self):
                record = {"method": self.command, "path": self.path, "headers": self.headers}
                requests.append(record)
                try:
                    if handle:
                        handle(self, record)
                        return
                    record["body"] = self.rfile.read(int(self.headers.get("Content-Length", "0")))
                    if not replies:
                        raise AssertionError("unexpected additional upstream request")
                    status, headers, body = replies.popleft()
                    reply(self, status, headers, record["body"] if body is None else body)
                except Exception as error:
                    errors.append(error)
                    self.close_connection = True

            do_POST = do_HEAD = do_GET

            def handle(self):
                try:
                    super().handle()
                except ConnectionResetError:
                    # Nginx may discard an intercepted redirect body and close its socket.
                    pass

            def log_message(self, *_args):
                pass

        class RecordingServer(ThreadingHTTPServer):
            def get_request(self):
                connection, address = super().get_request()
                accepts.append(address)
                return connection, address

        with tempfile.TemporaryDirectory(prefix="dsh-nginx-test-") as directory:
            with RecordingServer(("127.0.0.1", 0), Upstream) as upstream:
                thread = threading.Thread(target=upstream.serve_forever,
                                          kwargs={"poll_interval": 0.01}, daemon=True)
                thread.start()
                with socket.socket() as reservation:
                    reservation.bind(("127.0.0.1", 0))
                    address = reservation.getsockname()
                config = Path(directory) / "nginx.conf"
                config.write_text(render_config(address, upstream.server_address, "launch-token",
                                                PUBLIC_HOST, self.cert, self.key, directory, "dsh25228_"))
                process = subprocess.Popen(
                    [NGINX, "-p", directory + "/", "-c", str(config), "-e", "stderr"],
                    stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, start_new_session=True,
                )
                try:
                    deadline = time.monotonic() + WAIT
                    while True:
                        if process.poll() is not None:
                            raise AssertionError("test nginx exited: " + process.stderr.read().decode())
                        try:
                            with socket.create_connection(address, timeout=0.1):
                                break
                        except OSError:
                            if time.monotonic() >= deadline:
                                raise AssertionError("test nginx never opened its local listener")
                            threading.Event().wait(0.01)
                    yield SimpleNamespace(address=address, requests=requests, accepts=accepts,
                                          replies=replies, errors=errors, runtime=Path(directory))
                finally:
                    process.terminate()
                    try:
                        process.wait(WAIT)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(WAIT)
                    process.stderr.close()
                    upstream.shutdown()
                    thread.join(WAIT)
        self.assertFalse(errors, f"upstream fixture failed: {errors!r}")
        self.assertFalse(replies, "not all expected upstream replies were used")

    def connection(self, address):
        return http.client.HTTPSConnection(*address, timeout=WAIT, context=self.client_context)

    @contextmanager
    def socket(self, address):
        with socket.create_connection(address, timeout=WAIT) as raw:
            with self.client_context.wrap_socket(raw, server_hostname="127.0.0.1") as client:
                yield client

    def request(self, fixture, method="GET", target="/", headers=None, body=None):
        connection = self.connection(fixture.address)
        try:
            connection.request(method, target, headers=headers or {}, body=body)
            response = connection.getresponse()
            return response.status, response.getheaders(), response.read()
        finally:
            connection.close()

    def test_every_http_temp_directory_is_created_inside_the_instance(self):
        with self.fixture() as fixture:
            # Check directories Nginx actually creates, even for unused HTTP modules.
            # Omitting fastcgi_temp_path can otherwise silently use /var/lib/nginx/fastcgi
            # on system builds, or the shared installation prefix on local builds.
            for name in ("body", "proxy", "fastcgi", "uwsgi", "scgi"):
                with self.subTest(directory=name):
                    directory = fixture.runtime / name
                    self.assertTrue(directory.is_dir(), f"Nginx did not create {directory}")
                    self.assertEqual(directory.stat().st_uid, os.geteuid())
                    self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
                    self.assertEqual(directory.resolve().parent, fixture.runtime.resolve())

    def test_bootstrap_and_stale_cookie_complete_without_browser_redirect(self):
        for path in ("/", "/index.html"):
            for stale in (False, True):
                with self.subTest(path=path, stale=stale):
                    responses = ([(401, [], b"expired" * 10000)] if stale else []) + [
                        (303, [("Location", "./"), ("Set-Cookie", COOKIE)], b"discard this redirect"),
                        (200, [("Cache-Control", "public, max-age=3600")], PAGE),
                    ]
                    with self.fixture(responses) as fixture:
                        status, headers, body = self.request(
                            fixture, target=path,
                            headers={"Cookie": COOKIE_NAME + "=expired"} if stale else {},
                        )
                        mapped = {name.lower(): value for name, value in headers}
                        self.assertEqual((status, body), (200, PAGE))
                        self.assertEqual(mapped["set-cookie"], COOKIE + "; Secure")
                        self.assertEqual(mapped["cache-control"], "no-store")
                        self.assertNotIn("location", mapped)
                        expected = ([path] if stale else []) + ["/?token=launch-token", "/"]
                        self.assertEqual([request["path"] for request in fixture.requests], expected)
                        self.assertIsNone(fixture.requests[-2]["headers"].get("Cookie"))
                        self.assertEqual(fixture.requests[-1]["headers"]["Cookie"], COOKIE_PAIR)
                        self.assertEqual(fixture.requests[-1]["headers"]["Host"], PUBLIC_HOST)
                        self.assertEqual(fixture.requests[-1]["headers"]["X-Forwarded-Proto"], "https")

    def test_native_expiry_attributes_survive_bootstrap(self):
        cookie = (COOKIE_PAIR + "; Max-Age=2592000; Path=/; "
                  "Expires=Fri, 29 Oct 2027 12:00:00 GMT; HttpOnly; SameSite=Strict")
        with self.fixture([
            (303, [("Location", "./"), ("Set-Cookie", cookie)], b""),
            (200, [], PAGE),
        ]) as fixture:
            status, headers, body = self.request(fixture)
            self.assertEqual((status, body), (200, PAGE))
            self.assertEqual(dict(headers)["Set-Cookie"], cookie + "; Secure")
            self.assertEqual(fixture.requests[-1]["headers"]["Cookie"], COOKIE_PAIR)

    def test_native_cookie_wins_and_legacy_input_is_normalized_for_api(self):
        foreign = cookie_name("other.test:25229") + "=foreign"
        for raw, expected in [
            ("dsh25228_" + COOKIE_NAME + "=old; " + COOKIE_PAIR, COOKIE_PAIR),
            ("dsh25228_" + COOKIE_PAIR + "; " + foreign, COOKIE_PAIR),
            (foreign + "; dsh25229_" + COOKIE_PAIR, None),
        ]:
            with self.subTest(raw=raw), self.fixture([(200, [], b"ok")]) as fixture:
                self.assertEqual(self.request(fixture, target="/api/test", headers={"Cookie": raw})[0], 200)
                self.assertEqual(fixture.requests[0]["headers"].get("Cookie"), expected)
                self.assertEqual(fixture.requests[0]["path"], "/api/test")

    def test_existing_native_page_cookie_is_forwarded_once(self):
        with self.fixture([(200, [], PAGE)]) as fixture:
            self.assertEqual(self.request(fixture, headers={"Cookie": COOKIE_PAIR})[2], PAGE)
            self.assertEqual([request["path"] for request in fixture.requests], ["/"])
            self.assertEqual(fixture.requests[0]["headers"]["Cookie"], COOKIE_PAIR)

    def test_explicit_tokens_writes_head_and_bodyful_get_are_not_reauthenticated(self):
        cases = [("GET", path, None) for path in (
            "/?token=invalid", "/?token=", "/?token", "/?t%6fken=invalid",
            "/?token=one&token=two", "/index.html?token=invalid", "/api/call",
            "/index.html/extra", "/index.htmlx", "/nested/index.html",
        )] + [("HEAD", "/", None), ("POST", "/", b"write"), ("GET", "/", b"body")]
        for method, path, payload in cases:
            with self.subTest(method=method, path=path), self.fixture([(401, [], b"unauthorized")]) as fixture:
                status, _, body = self.request(fixture, method, path, body=payload)
                self.assertEqual(status, 401)
                self.assertEqual(body, b"" if method == "HEAD" else b"unauthorized")
                self.assertEqual(len(fixture.requests), 1)
                self.assertEqual(fixture.requests[0]["path"], path)
                self.assertEqual(fixture.requests[0]["body"], payload or b"")

    def test_connect_only_adds_missing_token_and_preserves_redirect(self):
        for path, expected in [
            ("/connect", "/connect?token=launch-token"),
            ("/connect?interactions=none", "/connect?interactions=none&token=launch-token"),
            ("/connect?token=", "/connect?token="),
            ("/connect?t%6fken=explicit", "/connect?t%6fken=explicit"),
        ]:
            with self.subTest(path=path), self.fixture([
                (302, [("Location", "./api/remote.mux"), ("Set-Cookie", COOKIE)], b""),
            ]) as fixture:
                status, headers, _ = self.request(fixture, target=path)
                mapped = {name.lower(): value for name, value in headers}
                self.assertEqual(status, 302)
                self.assertEqual(mapped["location"], "./api/remote.mux")
                self.assertIn("secure", mapped["set-cookie"].lower())
                self.assertEqual(fixture.requests[0]["path"], expected)

    def test_invalid_login_redirects_and_multiple_cookies_fail_closed(self):
        for headers in [
            [("Location", "https://other.test/"), ("Set-Cookie", COOKIE)],
            [("Location", "./")],
            [("Location", "./"), ("Set-Cookie", "dsh-auth-foreign=wrong")],
            [("Location", "./"), ("Set-Cookie", COOKIE), ("Set-Cookie", "theme=light")],
        ]:
            with self.subTest(headers=headers), self.fixture([(303, headers, b"redirect")]) as fixture:
                status, output, _ = self.request(fixture)
                self.assertEqual(len(fixture.requests), 1, [request["path"] for request in fixture.requests])
                self.assertEqual(status, 502)
                self.assertNotIn("set-cookie", {name.lower() for name, _ in output})

    def test_followup_redirect_does_not_restart_login(self):
        with self.fixture([
            (303, [("Location", "./"), ("Set-Cookie", COOKIE)], b""),
            (303, [("Location", "./")], b"second redirect"),
        ]) as fixture:
            status, _, body = self.request(fixture)
            self.assertEqual((status, body), (303, b"second redirect"))
            self.assertEqual(len(fixture.requests), 2)

    def test_https_connection_and_upstream_are_reused_for_binary_chunked_and_head(self):
        payload = bytes(range(256)) * 1024
        with self.fixture([
            (200, [], None), (200, [("Transfer-Encoding", "chunked")], b"streamed"),
            (200, [], PAGE), (200, [], b"final"),
        ]) as fixture:
            connection = self.connection(fixture.address)
            try:
                connection.connect()
                original_socket = connection.sock
                for method, body, expected in [
                    ("POST", payload, payload), ("GET", None, b"streamed"),
                    ("HEAD", None, b""), ("GET", None, b"final"),
                ]:
                    connection.request(method, "/api/test", body=body)
                    response = connection.getresponse()
                    self.assertEqual(response.read(), expected)
                    self.assertFalse(response.will_close)
                    self.assertIs(connection.sock, original_socket)
            finally:
                connection.close()
            self.assertEqual(len(fixture.accepts), 1)

    def test_stream_first_chunk_arrives_before_tail_is_produced(self):
        release_tail = threading.Event()

        def handle(handler, _record):
            handler.send_response(200)
            handler.send_header("Transfer-Encoding", "chunked")
            handler.end_headers()
            handler.wfile.write(b"5\r\nfirst\r\n")
            self.assertTrue(release_tail.wait(WAIT), "client never received the first chunk")
            handler.wfile.write(b"4\r\nlast\r\n0\r\n\r\n")

        with self.fixture(handle=handle) as fixture:
            connection = self.connection(fixture.address)
            try:
                connection.request("GET", "/stream")
                response = connection.getresponse()
                self.assertEqual(response.read(5), b"first")
                release_tail.set()
                self.assertEqual(response.read(), b"last")
            finally:
                release_tail.set()
                connection.close()

    def test_upload_streams_before_completion_and_preserves_next_request(self):
        first_received = threading.Event()
        prefix, tail = b"a" * 1024, bytes(range(256)) * 1024
        received = []

        def handle(handler, _record):
            if handler.path == "/upload":
                length = int(handler.headers["Content-Length"])
                first = handler.rfile.read(len(prefix))
                self.assertEqual(first, prefix)
                first_received.set()
                received.append(first + handler.rfile.read(length - len(first)))
                reply(handler, body=b"uploaded")
            else:
                reply(handler, body=b"next")

        with self.fixture(handle=handle) as fixture:
            with self.socket(fixture.address) as client, client.makefile("rb") as stream:
                client.sendall(
                    b"POST /upload HTTP/1.1\r\nHost: browser.test\r\nContent-Length: "
                    + str(len(prefix) + len(tail)).encode() + b"\r\n\r\n" + prefix
                )
                self.assertTrue(first_received.wait(WAIT), "upload was buffered before forwarding")
                client.sendall(tail + b"GET /after HTTP/1.1\r\nHost: browser.test\r\nConnection: close\r\n\r\n")
                for expected in (b"uploaded", b"next"):
                    status, headers = read_head(stream)
                    self.assertEqual(status, 200)
                    self.assertEqual(stream.read(int(headers["Content-Length"])), expected)
                self.assertEqual(stream.read(), b"")
            self.assertEqual(received, [prefix + tail])
            self.assertEqual([request["path"] for request in fixture.requests], ["/upload", "/after"])

    def test_wss_headers_only_and_large_early_frame(self):
        for early in (False, True):
            with self.subTest(early=early):
                payload = bytes(range(256)) * 1024 if early else b""
                frame = (b"\x82\xff" + len(payload).to_bytes(8, "big") + b"\0" * 4 + payload
                         if early else b"\x81\x80abcd")
                received = []

                def handle(handler, _record):
                    # Nginx starts tunnelling only after the upstream accepts the upgrade.
                    reply(handler, 101, [("Connection", "Upgrade"), ("Upgrade", "websocket")], b"")
                    received.append(handler.rfile.read(len(frame)))
                    handler.wfile.write(b"\x81\x02ok")
                    handler.close_connection = True

                with self.fixture(handle=handle) as fixture:
                    with self.socket(fixture.address) as client, client.makefile("rb") as stream:
                        headers = (
                            "GET /api/remote.mux HTTP/1.1\r\nHost: browser.test\r\n"
                            "Connection: Upgrade\r\nUpgrade: websocket\r\n"
                            f"Cookie: dsh25228_{COOKIE_PAIR}\r\nOrigin: https://{PUBLIC_HOST}\r\n\r\n"
                        ).encode()
                        client.sendall(headers + (frame if early else b""))
                        status, _ = read_head(stream)
                        self.assertEqual(status, 101)
                        if not early:
                            client.sendall(frame)
                        self.assertEqual(stream.read(), b"\x81\x02ok")
                    self.assertEqual(received, [frame])
                    self.assertEqual(fixture.requests[0]["path"], "/api/remote.mux")
                    self.assertEqual(fixture.requests[0]["headers"]["Cookie"], COOKIE_PAIR)
                    self.assertEqual(fixture.requests[0]["headers"]["Origin"], "https://" + PUBLIC_HOST)

    def test_failed_post_is_not_replayed(self):
        attempts = []

        def handle(handler, _record):
            if handler.path == "/warm":
                reply(handler)
                return
            attempts.append(handler.rfile.read(int(handler.headers["Content-Length"])))
            handler.close_connection = True

        with self.fixture(handle=handle) as fixture:
            connection = self.connection(fixture.address)
            try:
                connection.request("GET", "/warm")
                self.assertEqual(connection.getresponse().read(), b"ok")
                connection.request("POST", "/api/write", body=b"change")
                response = connection.getresponse()
                self.assertEqual(response.status, 502)
                response.read()
            finally:
                connection.close()
            self.assertEqual(attempts, [b"change"])


if __name__ == "__main__":
    unittest.main()
