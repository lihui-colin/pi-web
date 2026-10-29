"""HTTP regressions for dsh's transparent page authentication exchange."""

import http.client
import socket
import ssl
import subprocess
import tempfile
import threading
import unittest
from collections import deque
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.cookiejar import CookieJar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.request import HTTPCookieProcessor, HTTPSHandler, ProxyHandler, build_opener

from dsh_token_proxy import TokenProxy


COOKIE = "dsh-auth-test=browser-session; Path=/; HttpOnly; SameSite=Strict"
PAGE = b"<!doctype html><title>DeepSeek Harness</title>"


def create_test_certificate(directory):
    cert, key = Path(directory) / "cert.pem", Path(directory) / "key.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost",
        "-keyout", str(key), "-out", str(cert),
    ], check=True, capture_output=True, timeout=15)
    return cert, key


@contextmanager
def proxy_fixture(responses, tls_context=None, cookie_prefix=""):
    replies = deque(responses)
    requests = []
    errors = []

    class Upstream(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_GET(self):
            requests.append((self.path, self.headers))
            request_body = self.rfile.read(int(self.headers.get("Content-Length", "0")))
            if not replies:
                errors.append("unexpected upstream request")
                self.send_error(500)
                return
            status, headers, body = replies.popleft()
            if body is None:
                body = request_body
            self.send_response(status)
            for name, value in headers:
                self.send_header(name, value)
            chunked = any(
                name.lower() == "transfer-encoding" and value == "chunked"
                for name, value in headers
            )
            if not chunked and status != 101:
                self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            if self.command == "HEAD":
                return
            if status == 101:
                self.wfile.write(body)
                self.wfile.write(self.rfile.read(6))
                self.close_connection = True
                return
            if chunked:
                if body:
                    self.wfile.write(f"{len(body):x}\r\n".encode() + body + b"\r\n")
                self.wfile.write(b"0\r\nx-checksum: test\r\n\r\n")
            else:
                self.wfile.write(body)

        do_POST = do_HEAD = do_GET

        def log_message(self, *_args):
            pass

    with ThreadingHTTPServer(("127.0.0.1", 0), Upstream) as upstream:
        with TokenProxy(
            ("127.0.0.1", 0), upstream.server_address, "launch-token", "dsh.test:25228",
            tls_context, cookie_prefix,
        ) as proxy:
            for server in (upstream, proxy):
                threading.Thread(
                    target=server.serve_forever,
                    kwargs={"poll_interval": 0.01},
                    daemon=True,
                ).start()
            try:
                yield proxy.server_address, requests, replies, errors
            finally:
                proxy.shutdown()
                upstream.shutdown()


class PageAuthenticationTests(unittest.TestCase):
    def test_namespaced_login_ignores_foreign_and_legacy_cookies(self):
        result, requests = self.request([
            (303, [("Location", "./"), ("Set-Cookie", COOKIE)], b""),
            (200, [], PAGE),
        ], cookie_prefix="dsh25228_", headers={"Cookie":
            "dsh25229_dsh-auth-test=other; dsh-auth-old=legacy; theme=dark"})
        self.assertEqual(result[0], 200)
        self.assertEqual(dict(result[1])["Set-Cookie"], "dsh25228_" + COOKIE)
        self.assertEqual(requests[0][0], "/?token=launch-token")
        self.assertIsNone(requests[0][1].get("Cookie"))
        self.assertEqual(requests[1][1]["Cookie"], "dsh-auth-test=browser-session")

    def test_namespaced_cookie_restored_before_login_and_stale_retry(self):
        headers = {"Cookie": "dsh25229_dsh-auth-test=other; dsh25228_dsh-auth-test=mine; dsh-auth-old=legacy"}
        _, requests = self.request([(200, [], PAGE)], headers=headers, cookie_prefix="dsh25228_")
        self.assertEqual(requests[0][0], "/")
        self.assertEqual(requests[0][1]["Cookie"], "dsh-auth-test=mine")
        result, requests = self.request([
            (401, [], b"expired"),
            (303, [("Location", "./"), ("Set-Cookie", COOKIE)], b""),
            (200, [], PAGE),
        ], headers=headers, cookie_prefix="dsh25228_")
        self.assertEqual(dict(result[1])["Set-Cookie"], "dsh25228_" + COOKIE)
        self.assertEqual([r[0] for r in requests], ["/", "/?token=launch-token", "/"])

    def test_namespaced_cookie_deletion_preserves_attributes(self):
        deletion = "dsh-auth-test=; Path=/; Max-Age=0; Expires=Thu, 01 Jan 1970 00:00:00 GMT; HttpOnly; SameSite=Strict"
        result, _ = self.request([(200, [("Set-Cookie", deletion)], b"")],
                                 target="/logout", cookie_prefix="dsh25228_")
        self.assertEqual(dict(result[1])["Set-Cookie"], "dsh25228_" + deletion)

    def test_root_plugin_routes_forward_once_with_instance_cookie(self):
        for operation in ("save", "create", "mkdir", "rename", "remove", "upload", "quick/load", "quick/save", "download"):
            target = "/sidebar-enhancer/" + operation
            method = "GET" if operation == "download" else "POST"
            payload = bytes(range(256)) * 1024
            result, requests = self.request([(200, [], None)], target=target, method=method,
                body=payload, cookie_prefix="dsh25228_",
                headers={"Cookie": "dsh25228_dsh-auth-test=mine; dsh25229_dsh-auth-test=other"})
            self.assertEqual((result[0], result[2]), (200, payload))
            self.assertEqual([r[0] for r in requests], [target])
            self.assertEqual(requests[0][1]["Cookie"], "dsh-auth-test=mine")

    def request(self, responses, target="/", headers=None, method="GET", body=None, cookie_prefix=""):
        with proxy_fixture(responses, cookie_prefix=cookie_prefix) as (address, requests, replies, errors):
            connection = http.client.HTTPConnection(*address, timeout=2)
            try:
                connection.request(method, target, body=body, headers=headers or {})
                response = connection.getresponse()
                body = response.read()
                result = response.status, response.getheaders(), body
            finally:
                connection.close()
            self.assertFalse(replies, "not all expected upstream responses were used")
            self.assertFalse(errors)
            return result, requests

    def test_download_keeps_binary_body_and_attachment_headers(self):
        target = "/sidebar-enhancer/download?sessionId=session-test&path=dir%2Farchive.zip"
        payload = bytes(range(256)) * 1000
        attachment = 'attachment; filename="archive.zip"'
        result, requests = self.request([
            (200, [("Content-Type", "application/zip"), ("Content-Disposition", attachment)], payload),
        ], target=target)
        self.assertEqual((result[0], result[2]), (200, payload))
        self.assertEqual(dict(result[1])["Content-Disposition"], attachment)
        self.assertEqual(requests[0][0], target)

    def test_post_and_static_asset_preserve_path_query_and_body(self):
        for method, target, body in (("POST", "/api/pluginInventory/list?q=x%2Fy", b'{"args":{}}'),
                                      ("GET", "/app.js?v=42", None)):
            result, requests = self.request([(200, [], None)], target=target, method=method, body=body)
            self.assertEqual(result[0], 200)
            self.assertEqual(requests[0][0], target)
            self.assertEqual(result[2], body or b"")

    def test_first_visit_returns_page_and_strict_cookie_without_redirect(self):
        result, requests = self.request(
            [
                (303, [("Location", "./"), ("Set-Cookie", COOKIE)], b""),
                (200, [("Cache-Control", "public, max-age=3600")], PAGE),
            ],
            headers={"Sec-Fetch-Site": "cross-site", "Cookie": "theme=dark"},
        )
        status, headers, body = result
        mapped = {name.lower(): value for name, value in headers}
        self.assertEqual((status, body), (200, PAGE))
        self.assertEqual(mapped["set-cookie"], COOKIE)
        self.assertEqual(mapped["cache-control"], "no-store")
        self.assertNotIn("location", mapped)
        self.assertEqual([path for path, _ in requests], ["/?token=launch-token", "/"])
        cookies = SimpleCookie(requests[1][1]["Cookie"])
        self.assertEqual({name: cookie.value for name, cookie in cookies.items()}, {
            "dsh-auth-test": "browser-session", "theme": "dark",
        })
        self.assertEqual(requests[1][1]["Host"], "dsh.test:25228")
        self.assertNotIn(b"launch-token", body)

    def test_bootstrap_preserves_chunked_page(self):
        result, _ = self.request(
            [
                (303, [("Location", "./"), ("Set-Cookie", COOKIE)], b""),
                (200, [("Transfer-Encoding", "chunked")], PAGE),
            ]
        )
        self.assertEqual((result[0], result[2]), (200, PAGE))

    def test_existing_browser_cookie_is_forwarded_without_exchange(self):
        result, requests = self.request(
            [(200, [], PAGE)], headers={"Cookie": "dsh-auth-test=browser-session"}
        )
        self.assertEqual((result[0], result[2]), (200, PAGE))
        self.assertEqual([path for path, _ in requests], ["/"])

    def test_stale_cookie_reauthenticates_page_once(self):
        for target in ("/", "/index.html"):
            with self.subTest(target=target):
                result, requests = self.request([
                    (401, [], b"authentication required"),
                    (303, [("Location", "./"), ("Set-Cookie", COOKIE)], b""),
                    (200, [], PAGE),
                ], target=target, headers={"Cookie": "dsh-auth-old=expired; theme=dark"})
                self.assertEqual((result[0], result[2]), (200, PAGE))
                self.assertEqual([path for path, _ in requests], [target, target + "?token=launch-token", "/"])
                self.assertEqual(requests[1][1]["Cookie"], "theme=dark")
                self.assertEqual(dict(result[1])["Set-Cookie"], COOKIE)

    def test_reauthentication_failure_is_not_retried_forever(self):
        result, requests = self.request([(401, [], b"expired"), (401, [], b"invalid token")],
                                        headers={"Cookie": "dsh-auth-old=expired"})
        self.assertEqual(result[0], 401)
        self.assertEqual(len(requests), 2)

    def test_api_and_explicit_invalid_token_are_not_reauthenticated(self):
        for target in ("/api/call", "/?token=invalid"):
            with self.subTest(target=target):
                result, requests = self.request([(401, [], b"unauthorized")], target=target,
                                                headers={"Cookie": "dsh-auth-old=expired"})
                self.assertEqual(result[0], 401)
                self.assertEqual(len(requests), 1)

    def test_explicit_token_keeps_upstream_redirect(self):
        result, requests = self.request(
            [(303, [("Location", "./"), ("Set-Cookie", COOKIE)], b"")],
            target="/?token=user-token",
        )
        self.assertEqual(result[0], 303)
        self.assertEqual([path for path, _ in requests], ["/?token=user-token"])

    def test_api_connect_keeps_upstream_redirect(self):
        result, requests = self.request(
            [(302, [("Location", "./api/remote.mux"), ("Set-Cookie", COOKIE)], b"")],
            target="/connect?interactions=none",
        )
        self.assertEqual(result[0], 302)
        self.assertEqual(
            [path for path, _ in requests], ["/connect?interactions=none&token=launch-token"]
        )

    def test_unexpected_redirect_is_not_followed(self):
        result, requests = self.request(
            [(303, [("Location", "http://other.test/"), ("Set-Cookie", COOKIE)], b"")]
        )
        self.assertEqual(result[0], 303)
        self.assertEqual(len(requests), 1)

    def test_redirect_without_session_cookie_is_not_followed(self):
        result, requests = self.request([(303, [("Location", "./")], b"")])
        self.assertEqual(result[0], 303)
        self.assertEqual(len(requests), 1)

    def test_followup_redirect_cannot_start_another_exchange(self):
        redirect = (303, [("Location", "./"), ("Set-Cookie", COOKIE)], b"")
        result, requests = self.request([redirect, redirect])
        self.assertEqual(result[0], 303)
        self.assertEqual(len(requests), 2)

    def test_static_resource_does_not_receive_token(self):
        result, requests = self.request([(200, [], b"const loaded = true;")], target="/app.js")
        self.assertEqual((result[0], result[2]), (200, b"const loaded = true;"))
        self.assertEqual([path for path, _ in requests], ["/app.js"])

    def test_post_body_is_forwarded_intact(self):
        payload = b'{"text":"hello"}' * 10000
        result, requests = self.request(
            [(200, [], None)], target="/api/call", method="POST", body=payload
        )
        self.assertEqual((result[0], result[2]), (200, payload))
        self.assertEqual(requests[0][0], "/api/call")

    def test_head_preserves_length_without_reading_body(self):
        result, _ = self.request([(200, [], PAGE)], target="/app.js", method="HEAD")
        self.assertEqual((result[0], result[2]), (200, b""))
        self.assertEqual(dict(result[1])["Content-Length"], str(len(PAGE)))

    def test_connection_scoped_headers_are_removed(self):
        result, requests = self.request(
            [(200, [("Connection", "X-Private"), ("X-Private", "hidden")], PAGE)],
            target="/app.js", headers={"Connection": "X-Private", "X-Private": "hidden"},
        )
        self.assertNotIn("x-private", {name.lower() for name, _ in result[1]})
        self.assertIsNone(requests[0][1].get("X-Private"))

    def test_websocket_handshake_and_early_frame_survive(self):
        handshake = [("Connection", "Upgrade"), ("Upgrade", "websocket")]
        with proxy_fixture([(101, handshake, b"\x81\x02ok")], cookie_prefix="dsh25228_") as (address, requests, replies, errors):
            with socket.create_connection(address, timeout=2) as client:
                frame = b"\x81\x80abcd"
                client.sendall(
                    b"GET /api/remote.mux HTTP/1.1\r\nHost: browser.test\r\n"
                    b"Connection: Upgrade\r\nUpgrade: websocket\r\n"
                    b"Cookie: dsh25228_dsh-auth-test=browser-session; dsh25229_dsh-auth-test=other\r\n"
                    b"Origin: http://dsh.test:25228\r\n\r\n" + frame
                )
                response = b""
                while chunk := client.recv(4096):
                    response += chunk
            head, _, body = response.partition(b"\r\n\r\n")
            self.assertTrue(head.startswith(b"HTTP/1.1 101"))
            self.assertIn(b"Upgrade: websocket", head)
            self.assertEqual(body, b"\x81\x02ok" + frame)
            self.assertEqual(requests[0][1]["Host"], "dsh.test:25228")
            self.assertEqual(requests[0][1]["Origin"], "http://dsh.test:25228")
            self.assertEqual(requests[0][1]["Cookie"], "dsh-auth-test=browser-session")
            self.assertFalse(replies or errors)


class HttpsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        directory = tempfile.TemporaryDirectory(prefix="dsh-tls-")
        cls.addClassCleanup(directory.cleanup)
        cert, key = create_test_certificate(directory.name)
        cls.server_context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        cls.server_context.load_cert_chain(cert, key)
        cls.client_context = ssl.create_default_context(cafile=str(cert))

    def test_two_root_instances_share_browser_jar_without_login_collision(self):
        def responses():
            return [(303, [("Location", "./"), ("Set-Cookie", COOKIE)], b""),
                    (200, [], PAGE), (200, [], b"ok")]
        with proxy_fixture(responses(), self.server_context, cookie_prefix="dsh25228_") as first, \
             proxy_fixture(responses(), self.server_context, cookie_prefix="dsh25229_") as second:
            jar = CookieJar()
            opener = build_opener(ProxyHandler({}), HTTPSHandler(context=self.client_context), HTTPCookieProcessor(jar))
            for address, *_ in (first, second):
                with opener.open(f"https://{address[0]}:{address[1]}/", timeout=2) as response:
                    self.assertEqual(response.read(), PAGE)
            self.assertEqual({cookie.name for cookie in jar},
                             {"dsh25228_dsh-auth-test", "dsh25229_dsh-auth-test"})
            self.assertTrue(all(cookie.path == "/" and cookie.secure for cookie in jar))
            for address, requests, remaining, errors in (first, second):
                with opener.open(f"https://{address[0]}:{address[1]}/api/test", timeout=2) as response:
                    self.assertEqual(response.read(), b"ok")
                self.assertIsNone(requests[0][1].get("Cookie"))
                self.assertEqual(requests[-1][1]["Cookie"], "dsh-auth-test=browser-session")
                self.assertFalse(remaining or errors)

    def test_https_bootstrap_and_api_cookies_are_secure(self):
        for target, replies in (
            ("/", [(303, [("Location", "./"), ("Set-Cookie", COOKIE)], b""), (200, [], PAGE)]),
            ("/connect", [(302, [("Location", "./api/remote.mux"), ("Set-Cookie", COOKIE)], b"")]),
        ):
            with self.subTest(target=target), proxy_fixture(replies, self.server_context) as fixture:
                address, requests, remaining, errors = fixture
                connection = http.client.HTTPSConnection(*address, context=self.client_context, timeout=2)
                try:
                    connection.request("GET", target, headers={
                        "Origin": "https://dsh.test:25228", "X-Forwarded-Proto": "http",
                    })
                    response = connection.getresponse()
                    self.assertEqual(response.status, 200 if target == "/" else 302)
                    self.assertEqual(response.getheader("Set-Cookie"), COOKIE + "; Secure")
                    self.assertEqual(response.read(), PAGE if target == "/" else b"")
                finally:
                    connection.close()
                self.assertEqual(requests[0][1]["Origin"], "https://dsh.test:25228")
                self.assertEqual(requests[0][1]["X-Forwarded-Proto"], "https")
                self.assertFalse(remaining or errors)

    def test_idle_tls_client_does_not_block_other_clients(self):
        with proxy_fixture([(200, [], PAGE)], self.server_context) as (address, *_):
            with socket.create_connection(address, timeout=2):
                connection = http.client.HTTPSConnection(*address, context=self.client_context, timeout=2)
                try:
                    connection.request("GET", "/app.js")
                    self.assertEqual(connection.getresponse().read(), PAGE)
                finally:
                    connection.close()

    def test_wss_forwards_frame_buffered_with_upgrade_headers(self):
        handshake = [("Connection", "Upgrade"), ("Upgrade", "websocket")]
        # The upstream waits for the client frame before replying. This catches relays
        # that wait on select() while the frame is already in the TLS decrypted buffer.
        with proxy_fixture([(101, handshake, b"")], self.server_context) as fixture:
            address, requests, replies, errors = fixture
            with socket.create_connection(address, timeout=2) as raw:
                with self.client_context.wrap_socket(raw, server_hostname="127.0.0.1") as client:
                    frame = b"\x81\x80abcd"
                    client.sendall(
                        b"GET /api/remote.mux HTTP/1.1\r\nHost: browser.test\r\n"
                        b"Connection: Upgrade\r\nUpgrade: websocket\r\n"
                        b"Cookie: dsh-auth-test=browser-session\r\n"
                        b"Origin: https://dsh.test:25228\r\n\r\n" + frame
                    )
                    response = b""
                    while chunk := client.recv(4096):
                        response += chunk
            head, _, body = response.partition(b"\r\n\r\n")
            self.assertTrue(head.startswith(b"HTTP/1.1 101"))
            self.assertEqual(body, frame)
            self.assertEqual(requests[0][0], "/api/remote.mux")
            self.assertEqual(requests[0][1]["X-Forwarded-Proto"], "https")
            self.assertEqual(requests[0][1]["Origin"], "https://dsh.test:25228")
            self.assertFalse(replies or errors)


if __name__ == "__main__":
    unittest.main()
