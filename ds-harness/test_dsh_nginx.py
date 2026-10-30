"""Isolated integration tests for the generated Nginx HTTPS proxy."""

import http.client
import os
import shutil
import signal
import socket
import ssl
import subprocess
import tempfile
import threading
import time
import unittest
from collections import deque
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace

from dsh_nginx import cookie_name, render_config
from test_support import create_test_certificate

PAGE = b"<!doctype html><title>DeepSeek Harness</title>"
WAIT = 5
PUBLIC_HOST = "dsh.test:25228"
COOKIE_NAME = cookie_name(PUBLIC_HOST)
COOKIE_PAIR = COOKIE_NAME + "=browser-session"
COOKIE = COOKIE_PAIR + "; Path=/; HttpOnly; SameSite=Strict"
NGINX = shutil.which("nginx")


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


@unittest.skipUnless(NGINX, "nginx is not installed")
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
                                          replies=replies, errors=errors)
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
