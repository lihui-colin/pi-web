"""Magpie renderer validation and isolated real-Nginx TLS integration tests."""
import io
import os
import tempfile
import unittest
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import test_dsh_nginx as fixtures
from dsh_nginx import main
from magpie_nginx import read_key, render_config

KEY = "magpie-test-secret-._~1234"


class MagpieConfigTests(unittest.TestCase):
    def render(self, **overrides):
        args = dict(listen=("127.0.0.1", 34567), upstream=("127.0.0.1", 34568),
                    key=KEY, public_host="magpie.test:443", tls_cert="cert", tls_key="key",
                    runtime_dir="/tmp/magpie-test")
        args.update(overrides)
        return render_config(**args)

    def test_rejects_invalid_inputs(self):
        for overrides in (
            {"key": "short"}, {"key": "x" * 16 + ";"}, {"key": "x" * 16 + "\n"},
            {"upstream": ("10.0.0.1", 1234)}, {"upstream": ("localhost", 1234)},
            {"listen": ("127.0.0.1", 0)}, {"listen": ("127.0.0.1", 65536)},
            {"listen": ("127.0.0.1", "443;return")}, {"listen": ("::1%lo", 443)},
            *({"public_host": host} for host in ("evil;return", "host\n", "host/path",
                "host:", "host:0", "host:65536", "user@host", "host?x", "bad_host")),
        ):
            with self.subTest(overrides=overrides), self.assertRaises(ValueError):
                self.render(**overrides)
        self.assertIn("server [::1]:1234;", self.render(upstream=("::1", 1234), public_host="[::1]:443"))

    def test_stable_private_key_file(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "key"
            path.write_text(KEY + "\n")
            path.chmod(0o600)
            self.assertEqual(read_key(path), KEY)
            self.assertEqual(read_key(path), KEY)
            path.chmod(0o644)
            with self.assertRaisesRegex(ValueError, "private"):
                read_key(path)
            path.chmod(0o600)
            for value in ("short", KEY + "\n\n", KEY + " ", "é" * 20):
                path.write_text(value)
                with self.assertRaises(ValueError):
                    read_key(path)

    def test_supervisor_selects_magpie_redacts_key_and_cleans_private_config(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            key = root / "magpie.key"
            key.write_text(KEY)
            key.chmod(0o600)
            argv = ["dsh_nginx.py", "--listen-host", "127.0.0.1", "--listen-port", "34567",
                    "--upstream-host", "127.0.0.1", "--upstream-port", "34568",
                    "--public-host", "magpie.test", "--config", str(root / "dsh.conf"),
                    "--magpie-key-file", str(key), "--tls-cert", str(root / "cert"),
                    "--tls-key", str(root / "tls.key")]
            config = root / "log/.nginx-34567/nginx.conf"

            def check(*args, **kwargs):
                self.assertIn("magpie_web_34568=" + KEY, config.read_text())
                self.assertEqual(config.stat().st_mode & 0o777, 0o600)
                self.assertEqual(config.parent.stat().st_mode & 0o777, 0o700)
                return SimpleNamespace(returncode=1, stderr="failed " + KEY + "\n")

            errors = io.StringIO()
            original_umask = os.umask(0o077)
            try:
                with mock.patch("sys.argv", argv), mock.patch("sys.stderr", errors), \
                        mock.patch("dsh_nginx.require_local_nginx", return_value="/mock/nginx"), \
                        mock.patch("dsh_nginx.subprocess.run", side_effect=check):
                    self.assertEqual(main(), 1)
            finally:
                os.umask(original_umask)
            self.assertNotIn(KEY, errors.getvalue())
            self.assertIn("[REDACTED]", errors.getvalue())
            self.assertFalse(config.exists())
            self.assertEqual(key.read_text(), KEY)


@unittest.skipUnless(fixtures.NGINX, "install the project-local Nginx")
class MagpieProxyTests(unittest.TestCase):
    setUpClass = classmethod(fixtures.NginxProxyTests.setUpClass.__func__)
    connection = fixtures.NginxProxyTests.connection
    socket = fixtures.NginxProxyTests.socket
    request = fixtures.NginxProxyTests.request
    test_stream_first_chunk_arrives_before_tail_is_produced = fixtures.NginxProxyTests.test_stream_first_chunk_arrives_before_tail_is_produced
    test_upload_streams_before_completion_and_preserves_next_request = fixtures.NginxProxyTests.test_upload_streams_before_completion_and_preserves_next_request

    @contextmanager
    def fixture(self, responses=(), handle=None):
        def render(listen, upstream, _token, public_host, cert, key, runtime, _prefix):
            self.cookie = f"magpie_web_{upstream[1]}={KEY}"
            return render_config(listen, upstream, KEY, public_host, cert, key, runtime)
        with mock.patch.object(fixtures, "render_config", side_effect=render):
            with fixtures.NginxProxyTests.fixture(self, responses, handle) as fixture:
                yield fixture

    def test_root_without_cookie_authenticates_without_browser_secret(self):
        def handle(handler, record):
            self.assertEqual(handler.headers.get("Cookie"), self.cookie)
            self.assertIsNone(handler.headers.get("Authorization"))
            self.assertEqual(handler.headers["Host"], fixtures.PUBLIC_HOST)
            self.assertEqual(handler.headers["X-Forwarded-Host"], fixtures.PUBLIC_HOST)
            self.assertEqual(handler.headers["X-Forwarded-Proto"], "https")
            fixtures.reply(handler, headers=[("Set-Cookie", self.cookie), ("Set-Cookie", "other=value")],
                           body=b"<title>Magpie</title>")
        with self.fixture(handle=handle) as fixture:
            for path in ("/", "/api/status?x=keep"):
                status, headers, body = self.request(fixture, target=path)
                self.assertEqual(status, 200)
                self.assertNotIn("set-cookie", dict((k.lower(), v) for k, v in headers))
                self.assertNotIn(KEY, str(headers) + body.decode())
                self.assertEqual(fixture.requests[-1]["path"], path)
            self.assertFalse(list(fixture.runtime.rglob("*access*")))

    def test_backend_rejects_cross_origin_mutation(self):
        def handle(handler, record):
            self.assertEqual(handler.headers["Cookie"], self.cookie)
            self.assertEqual(handler.headers["Host"], fixtures.PUBLIC_HOST)
            allowed = (handler.headers.get("Origin") == "https://" + fixtures.PUBLIC_HOST
                       and handler.headers.get("Sec-Fetch-Site") == "same-origin")
            fixtures.reply(handler, 200 if allowed else 403)
        with self.fixture(handle=handle) as fixture:
            for origin, site, expected in (("https://" + fixtures.PUBLIC_HOST, "same-origin", 200),
                                           ("https://evil.test", "cross-site", 403)):
                status, _, _ = self.request(fixture, method="POST", target="/api/mutate", body=b"",
                    headers={"Origin": origin, "Sec-Fetch-Site": site})
                self.assertEqual(status, expected)
                self.assertEqual(fixture.requests[-1]["headers"]["Origin"], origin)
                self.assertEqual(fixture.requests[-1]["headers"]["Sec-Fetch-Site"], site)

    def test_websocket_upgrade_and_frame(self):
        frame = b"\x81\x80abcd"
        def handle(handler, record):
            self.assertEqual(handler.headers["Cookie"], self.cookie)
            self.assertEqual(handler.headers["Origin"], "https://" + fixtures.PUBLIC_HOST)
            fixtures.reply(handler, 101, [("Connection", "Upgrade"), ("Upgrade", "websocket"),
                                          ("Set-Cookie", self.cookie)], b"")
            self.assertEqual(handler.rfile.read(len(frame)), frame)
            handler.wfile.write(b"\x81\x02ok")
            handler.close_connection = True
        with self.fixture(handle=handle) as fixture:
            with self.socket(fixture.address) as client, client.makefile("rb") as stream:
                client.sendall(("GET /ws HTTP/1.1\r\nHost: browser.test\r\nConnection: Upgrade\r\n"
                                "Upgrade: websocket\r\nOrigin: https://" + fixtures.PUBLIC_HOST + "\r\n\r\n").encode())
                status, headers = fixtures.read_head(stream)
                self.assertEqual(status, 101)
                self.assertIsNone(headers.get("Set-Cookie"))
                client.sendall(frame)
                self.assertEqual(stream.read(), b"\x81\x02ok")


if __name__ == "__main__":
    unittest.main()
