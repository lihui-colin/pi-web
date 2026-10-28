#!/usr/bin/env python3
"""Forward dsh HTTP/WebSocket traffic and finish page login without browser redirects."""

import argparse
import http.client
import re
import select
import socket
import sys
from contextlib import closing
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qsl, urlsplit, urlunsplit

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "trailers", "transfer-encoding", "upgrade",
}


def filtered_headers(headers, *, websocket=False):
    blocked = HOP_BY_HOP | {
        token.strip().lower()
        for name, value in headers if name.lower() == "connection"
        for token in value.split(",")
    }
    if websocket:
        blocked -= {"connection", "upgrade"}
    return [(name, value) for name, value in headers if name.lower() not in blocked]


def append_token(method, target, headers, token):
    url = urlsplit(target)
    has_cookie = any(
        part.strip().startswith("dsh-auth-") and "=" in part
        for name, value in headers if name.lower() == "cookie"
        for part in value.split(";")
    )
    if (
        method != "GET" or url.path not in {"/", "/index.html", "/connect"}
        or any(name == "token" for name, _ in parse_qsl(url.query, keep_blank_values=True))
        or (url.path != "/connect" and has_cookie)
    ):
        return target
    query = f"{url.query}&token={token}" if url.query else f"token={token}"
    return urlunsplit(url._replace(query=query))


class TokenProxy(ThreadingHTTPServer):
    def __init__(self, listen, upstream, token, public_host):
        if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
            raise ValueError("dsh token is missing or invalid")
        self.upstream, self.token, self.public_host = upstream, token, public_host
        super().__init__(listen, ProxyHandler)


class ProxyHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    # Leave early WebSocket frames on the socket for the relay after header parsing.
    rbufsize = 0
    timeout = 60

    def log_message(self, *_args):
        pass  # Request URLs can contain launch tokens.

    def proxy(self):
        self.close_connection = True
        self.responded = False
        try:
            websocket = self.headers.get("Upgrade", "").lower() == "websocket"
            headers = {
                name.lower(): value
                for name, value in filtered_headers(self.headers.items(), websocket=websocket)
            }
            headers.update({
                "host": self.server.public_host,
                "x-forwarded-host": self.server.public_host,
                "x-forwarded-proto": "http",
            })
            if websocket:
                self.proxy_websocket(headers)
            else:
                self.proxy_http(headers)
        except (ValueError, http.client.HTTPException, OSError):
            if not self.responded:
                self.send_error(502, "Upstream request failed")

    do_GET = do_HEAD = do_POST = do_PUT = do_PATCH = do_DELETE = do_OPTIONS = proxy

    def proxy_websocket(self, headers):
        with socket.create_connection(self.server.upstream, timeout=30) as upstream:
            request = f"{self.command} {self.path} HTTP/1.1\r\n"
            request += "".join(f"{name}: {value}\r\n" for name, value in headers.items())
            upstream.sendall((request + "\r\n").encode("iso-8859-1"))
            self.responded = True
            while True:
                ready, _, _ = select.select([self.connection, upstream], [], [], 300)
                if not ready:
                    return
                for source in ready:
                    data = source.recv(65536)
                    if not data:
                        return
                    (upstream if source is self.connection else self.connection).sendall(data)

    def proxy_http(self, headers):
        length = self.headers.get("Content-Length", "0")
        if self.headers.get("Transfer-Encoding") or not length.isascii() or not length.isdigit():
            self.send_error(400, "A valid Content-Length is required for request bodies")
            return
        body = bytearray()
        while len(body) < int(length):
            chunk = self.rfile.read(min(65536, int(length) - len(body)))
            if not chunk:
                raise ValueError("truncated request body")
            body.extend(chunk)

        target = append_token(self.command, self.path, self.headers.items(), self.server.token)
        bootstrap = target != self.path and urlsplit(self.path).path == "/"
        session_cookies = []
        for attempt in range(2):
            with closing(http.client.HTTPConnection(*self.server.upstream, timeout=30)) as upstream:
                upstream.request(self.command, target, body=body or None, headers=headers)
                response = upstream.getresponse()
                cookies = [
                    value for name, value in response.getheaders()
                    if name.lower() == "set-cookie" and value.startswith("dsh-auth-")
                    and "=" in value.split(";", 1)[0]
                ]
                if (
                    attempt == 0 and bootstrap and response.status == 303
                    and response.getheader("Location") == "./" and cookies
                ):
                    # Cross-site redirects cannot send Strict cookies. Complete our
                    # token exchange upstream, then return the page and cookie together.
                    session_cookies = cookies
                    jar = SimpleCookie(headers.get("cookie", ""))
                    for cookie in cookies:
                        jar.load(cookie)
                    headers["cookie"] = "; ".join(m.OutputString(attrs=[]) for m in jar.values())
                    target = "/"
                    continue

                self.responded = True
                self.send_response_only(response.status, response.reason)
                for name, value in filtered_headers(response.getheaders()):
                    if not (session_cookies and name.lower() == "cache-control"):
                        self.send_header(name, value)
                for cookie in session_cookies:
                    self.send_header("Set-Cookie", cookie)
                if session_cookies:
                    self.send_header("Cache-Control", "no-store")
                # HTTPResponse decodes chunks; closing frames responses without a length.
                self.send_header("Connection", "close")
                self.end_headers()
                while chunk := response.read1(65536):
                    self.wfile.write(chunk)
                return


def read_token(config_path):
    match = re.search(r"(?m)^dsh_token='([A-Za-z0-9_-]+)'\s*$", Path(config_path).read_text())
    if not match:
        raise ValueError(f"no dsh_token in {config_path}")
    return match.group(1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for endpoint in ("listen", "upstream"):
        parser.add_argument(f"--{endpoint}-host", required=True)
        parser.add_argument(f"--{endpoint}-port", required=True, type=int)
    parser.add_argument("--public-host", required=True)
    parser.add_argument("--config", required=True)
    args = parser.parse_args()
    if not all(1 <= port <= 65535 for port in (args.listen_port, args.upstream_port)):
        parser.error("ports must be between 1 and 65535")
    try:
        with TokenProxy(
            (args.listen_host, args.listen_port), (args.upstream_host, args.upstream_port),
            read_token(args.config), args.public_host,
        ) as server:
            server.serve_forever()
    except (OSError, ValueError) as error:
        print(f"dsh token proxy: {error}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
