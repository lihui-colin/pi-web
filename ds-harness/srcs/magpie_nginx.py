"""Render Magpie's private, cookie-authenticating TLS reverse proxy."""

import ipaddress
import re
from urllib.parse import urlsplit

from dsh_nginx import cookie_name, quote, render_proxy_config
from dsh_runtime import read_magpie_key as read_key


def validate_key(key):
    if not isinstance(key, str) or not re.fullmatch(r"[A-Za-z0-9.\-_~]{16,}", key):
        raise ValueError("Magpie key must contain at least 16 URL-safe characters")
    return key


def render_config(listen, upstream, key, public_host, tls_cert, tls_key, runtime_dir):
    validate_key(key)
    for host, port in (listen, upstream):
        if not isinstance(port, int) or isinstance(port, bool) or not 1 <= port <= 65535:
            raise ValueError("ports must be integers between 1 and 65535")
        if "%" in host:
            raise ValueError("scoped addresses are not supported")
        ipaddress.ip_address(host)
    if not ipaddress.ip_address(upstream[0]).is_loopback:
        raise ValueError("Magpie upstream must be a loopback IP address")
    if not re.fullmatch(r"[A-Za-z0-9.\-:\[\]]+", public_host) or public_host.endswith(":"):
        raise ValueError("public host must be a hostname or IP with an optional port")
    cookie_name(public_host)  # Reuse the existing canonical hostname/IP validation.
    if urlsplit("http://" + public_host).port == 0:
        raise ValueError("public host port must be between 1 and 65535")
    return render_proxy_config(
        listen, upstream, tls_cert, tls_key, runtime_dir, service="magpie",
        server_config=f'''        proxy_set_header Host {quote(public_host)};
        proxy_set_header X-Forwarded-Host {quote(public_host)};
        proxy_set_header X-Forwarded-Proto https;
        proxy_set_header Cookie {quote(f'magpie_web_{upstream[1]}={key}')};
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection $magpie_upgrade_connection;
        # Preserve browser Origin and Sec-Fetch-Site for CrossOriginProtection.
        proxy_hide_header Set-Cookie;
        location / {{
            proxy_pass http://magpie_backend;
        }}
''',
    )
