#!/usr/bin/env python3
"""Generate a private Nginx configuration and supervise its foreground master.

Nginx owns all HTTP, HTTPS, WebSocket and streaming I/O. Python only prepares the
configuration and forwards termination signals; it never handles browser traffic.
"""

import argparse
import base64
import hashlib
import ipaddress
import os
import re
import signal
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit


def require_local_nginx():
    prefix = Path(__file__).resolve().parent / ".local/nginx"
    nginx = prefix / "sbin/nginx"
    install = "run dsh_nginx_install.sh to install the project-local Nginx"
    if not nginx.is_file() or not os.access(nginx, os.X_OK):
        raise ValueError(f"project-local Nginx is missing or not executable: {nginx}; {install}")
    resolved = nginx.resolve()
    if not resolved.is_relative_to(prefix):
        raise ValueError(f"project-local Nginx resolves outside its installation directory: {nginx}; {install}")
    nginx = resolved
    try:
        version = subprocess.run([str(nginx), "-v"], capture_output=True, text=True)
    except OSError as error:
        raise ValueError(f"cannot execute project-local Nginx: {nginx}; {install}: {error}") from error
    match = re.search(r"nginx/(\d+)\.(\d+)\.(\d+)", version.stdout + version.stderr)
    if version.returncode or not match or tuple(map(int, match.groups())) < (1, 24, 0):
        raise ValueError(f"project-local Nginx 1.24 or newer is required: {nginx}; {install}")
    return str(nginx)


def read_token(config_path):
    match = re.search(r"(?m)^dsh_token='([A-Za-z0-9_-]+)'\s*$", Path(config_path).read_text())
    if not match:
        raise ValueError("configuration does not contain a valid dsh_token")
    return match.group(1)


def quote(value):
    value = str(value)
    if any(character in value for character in "\x00\r\n"):
        raise ValueError("configuration values cannot contain newlines or NUL")
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"').replace("$", "\\$") + '"'


def cookie_name(public_host):
    """Match DSH's HTTP authority audience (the upstream listener remains HTTP)."""
    parsed = urlsplit("http://" + public_host)
    if not parsed.hostname or parsed.username or parsed.password or parsed.path or parsed.query or parsed.fragment:
        raise ValueError("public host must be a hostname or IP with an optional port")
    host = parsed.hostname.lower()
    if not host.isascii() or "%" in host:
        raise ValueError("public host must use a canonical IP or ASCII hostname")
    try:
        address = ipaddress.ip_address(host)
        host = f"[{address.compressed}]" if address.version == 6 else address.compressed
    except ValueError:
        labels = host.rstrip(".").split(".")
        if (not all(re.fullmatch(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?", label) for label in labels)
                or re.fullmatch(r"(?:[0-9]+|0x[0-9a-f]*)", labels[-1])):
            raise ValueError("public host must use a canonical IP or ASCII hostname") from None
    authority = host + (f":{parsed.port}" if parsed.port not in {None, 80} else "")
    digest = base64.urlsafe_b64encode(hashlib.sha256(authority.encode()).digest()).decode().rstrip("=")
    return "dsh-auth-" + digest


def endpoint(address):
    host, port = address
    host = str(ipaddress.ip_address(host))
    if not 1 <= int(port) <= 65535:
        raise ValueError("ports must be between 1 and 65535")
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def render_config(listen, upstream, token, public_host, tls_cert, tls_key, runtime_dir, cookie_prefix=""):
    if not re.fullmatch(r"[A-Za-z0-9_-]+", token):
        raise ValueError("dsh token is missing or invalid")
    if cookie_prefix and not re.fullmatch(r"dsh[0-9]+_", cookie_prefix):
        raise ValueError("cookie prefix must be dsh<port>_")
    name = cookie_name(public_host)
    runtime_dir = Path(runtime_dir).resolve()
    legacy_cookie = (
        f'        "~(?:^|;\\s*){cookie_prefix}{name}=([^;]+)" "{name}=$1";\n'
        if cookie_prefix else ""
    )

    def headers(cookie="$dsh_request_cookie", *, login=False):
        return f'''        proxy_set_header Host {quote(public_host)};
        proxy_set_header X-Forwarded-Host {quote(public_host)};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Cookie {cookie};
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $dsh_upgrade_connection;
''' + ('        proxy_set_header Content-Length "";\n' if login else "")

    # No HTTP/2 listener yet: auto-login requires an unambiguous, bodyless GET.
    # HTTP/2 may carry DATA without Content-Length, unlike the HTTP/1.1 gate below.
    return f'''worker_processes 2;
daemon off;
pid {quote(runtime_dir / 'nginx.pid')};
# Access logs stay disabled; the supervisor redacts tokens from error diagnostics.
error_log stderr warn;
events {{ worker_connections 1024; }}
http {{
    access_log off;
    client_body_temp_path {quote(runtime_dir / 'body')};
    proxy_temp_path {quote(runtime_dir / 'proxy')};
    fastcgi_temp_path {quote(runtime_dir / 'fastcgi')};
    uwsgi_temp_path {quote(runtime_dir / 'uwsgi')};
    scgi_temp_path {quote(runtime_dir / 'scgi')};
    map $http_upgrade $dsh_upgrade_connection {{ default upgrade; "" ""; }}
    map $http_cookie $dsh_request_cookie {{
        default "";
        "~(?:^|;\\s*){name}=([^;]+)" "{name}=$1";
{legacy_cookie}    }}
    map $args $dsh_explicit_token {{
        default 0;
        "~(^|&)(t|%74)(o|%6[fF])(k|%6[bB])(e|%65)(n|%6[eE])(=|&|$)" 1;
    }}
    map $request_uri $dsh_page_path {{
        default 0;
        "~^/(index[.]html)?([?]|$)" 1;
    }}
    map "$dsh_page_path:$request_method:$content_length:$http_transfer_encoding:$dsh_explicit_token:$http_upgrade" $dsh_auto_login {{
        default 0;
        "1:GET:::0:" 1;
        "1:GET:0::0:" 1;
    }}
    map "$request_method:$dsh_explicit_token:$args" $dsh_connect_uri {{
        default $request_uri;
        "~^GET:0:$" "/connect?token={token}";
        "~^GET:0:" "/connect?$args&token={token}";
    }}
    map $upstream_http_set_cookie $dsh_issued_cookie {{
        default "";
        "~,[ \\t]*[^;,=\\s]+=" "";
        "~^({name}=[^;,]+)(;|$)" $1;
    }}
    map $dsh_login_ok $dsh_cookie_to_browser {{
        default "";
        1 "$dsh_login_cookie; Secure";
    }}
    map "$upstream_http_location:$dsh_issued_cookie" $dsh_valid_login {{
        default 0;
        "~^\\./:{name}=" 1;
    }}
    upstream dsh_backend {{
        server {endpoint(upstream)};
        keepalive 32;
        keepalive_requests 1000;
        keepalive_timeout 4s;
    }}
    server {{
        listen {endpoint(listen)} ssl;
        server_name _;
        ssl_certificate {quote(Path(tls_cert).resolve())};
        ssl_certificate_key {quote(Path(tls_key).resolve())};
        ssl_protocols TLSv1.2 TLSv1.3;
        ssl_session_cache shared:DSH_TLS:10m;
        ssl_session_timeout 1h;
        ssl_session_tickets off;
        keepalive_timeout 65s;
        client_max_body_size 0;
        client_body_buffer_size 64k;
        client_header_timeout 15s;
        client_body_timeout 60s;
        proxy_http_version 1.1;
        proxy_buffering off;
        proxy_request_buffering off;
        proxy_connect_timeout 5s;
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_next_upstream off;
        proxy_redirect off;
        proxy_cookie_flags ~^dsh-auth- secure;
        recursive_error_pages on;
        set $dsh_launch_url "http://dsh_backend/?token={token}";
        set $dsh_root_url "http://dsh_backend/";

        location = / {{
            error_page 418 = @page;
            if ($dsh_auto_login) {{ return 418; }}
{headers()}            proxy_pass http://dsh_backend;
        }}
        location = /index.html {{
            error_page 418 = @page;
            if ($dsh_auto_login) {{ return 418; }}
{headers()}            proxy_pass http://dsh_backend;
        }}
        location @page {{
            error_page 419 = @login;
            error_page 401 = @login;
            if ($dsh_request_cookie = "") {{ return 419; }}
            proxy_intercept_errors on;
{headers()}            proxy_pass http://dsh_backend;
        }}
        location @login {{
            proxy_pass_request_body off;
            proxy_intercept_errors on;
            error_page 303 = @finish_login;
{headers('""', login=True)}            proxy_pass $dsh_launch_url;
        }}
        location @finish_login {{
            # Snapshot headers before a second upstream response replaces them.
            set $dsh_login_ok $dsh_valid_login;
            set $dsh_login_cookie $upstream_http_set_cookie;
            set $dsh_login_pair $dsh_issued_cookie;
            if ($dsh_login_ok = 0) {{ return 502; }}
            proxy_pass_request_body off;
            proxy_intercept_errors off;
            proxy_hide_header Cache-Control;
            add_header Cache-Control no-store always;
            add_header Set-Cookie $dsh_cookie_to_browser always;
{headers('$dsh_login_pair', login=True)}            proxy_pass $dsh_root_url;
        }}
        location = /connect {{
{headers()}            proxy_pass http://dsh_backend$dsh_connect_uri;
        }}
        location / {{
{headers()}            proxy_pass http://dsh_backend;
        }}
    }}
}}
'''


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for side in ("listen", "upstream"):
        parser.add_argument(f"--{side}-host", required=True)
        parser.add_argument(f"--{side}-port", required=True, type=int)
    parser.add_argument("--public-host", required=True)
    parser.add_argument("--cookie-prefix", default="")
    parser.add_argument("--config", required=True, type=Path)
    parser.add_argument("--tls-cert", required=True, type=Path)
    parser.add_argument("--tls-key", required=True, type=Path)
    args = parser.parse_args()
    runtime = args.config.resolve().parent / f".nginx-{args.listen_port}"
    try:
        nginx = require_local_nginx()
        # Launch token and runtime files are private, including temp directories.
        os.umask(0o077)
        runtime.mkdir(mode=0o700, exist_ok=True)
        runtime.chmod(0o700)
        config = runtime / "nginx.conf"
        launch_token = read_token(args.config)
        config.write_text(render_config(
            (args.listen_host, args.listen_port), (args.upstream_host, args.upstream_port),
            launch_token, args.public_host, args.tls_cert, args.tls_key, runtime,
            args.cookie_prefix,
        ))
        config.chmod(0o600)

        def diagnostic(line):
            line = line.replace(launch_token, "[REDACTED]")
            return re.sub(r"([?&]token=)[^&\s\"']+", r"\1[REDACTED]", line)

        command = [nginx, "-p", str(runtime) + "/", "-c", str(config), "-e", "stderr"]
        try:
            checked = subprocess.run(command + ["-t"], capture_output=True, text=True)
            if checked.returncode:
                print(diagnostic(checked.stderr), file=sys.stderr, end="")
                return 1
            child = subprocess.Popen(command, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE, text=True)
            for signum in (signal.SIGTERM, signal.SIGINT):
                signal.signal(signum, lambda *_: child.terminate())
            try:
                for line in child.stderr:
                    print(diagnostic(line), file=sys.stderr, end="", flush=True)
                return child.wait()
            finally:
                child.stderr.close()
                if child.poll() is None:
                    child.terminate()
                    child.wait()
        finally:
            # This exact file was generated above, inside the private instance directory.
            config.unlink(missing_ok=True)
    except (OSError, ValueError) as error:
        print(f"dsh nginx: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
