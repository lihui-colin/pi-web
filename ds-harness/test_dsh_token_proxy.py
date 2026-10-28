"""HTTP regressions for dsh's transparent page authentication exchange."""

import http.client
import socket
import threading
import unittest
from collections import deque
from contextlib import contextmanager
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from dsh_token_proxy import TokenProxy


COOKIE = "dsh-auth-test=browser-session; Path=/; HttpOnly; SameSite=Strict"
PAGE = b"<!doctype html><title>DeepSeek Harness</title>"


@contextmanager
def proxy_fixture(responses):
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
            ("127.0.0.1", 0), upstream.server_address, "launch-token", "dsh.test:25228"
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
    def request(self, responses, target="/", headers=None, method="GET", body=None):
        with proxy_fixture(responses) as (address, requests, replies, errors):
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
        with proxy_fixture([(101, handshake, b"\x81\x02ok")]) as (address, requests, replies, errors):
            with socket.create_connection(address, timeout=2) as client:
                frame = b"\x81\x80abcd"
                client.sendall(
                    b"GET /api/remote.mux HTTP/1.1\r\nHost: browser.test\r\n"
                    b"Connection: Upgrade\r\nUpgrade: websocket\r\n"
                    b"Cookie: dsh-auth-test=browser-session\r\n"
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


if __name__ == "__main__":
    unittest.main()
