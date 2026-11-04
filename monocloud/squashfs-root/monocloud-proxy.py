#!/usr/bin/env python3
"""Start the MonoCloud local proxy forwarder."""

import argparse
import json
import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request

APP_DIR = os.path.dirname(os.path.abspath(__file__))
ROOT_DIR = os.path.dirname(APP_DIR)
CORE = os.path.join(APP_DIR, "usr", "bin", "monocloud-core")
STATE_DIR = os.path.join(ROOT_DIR, "config")
RUNTIME_DIR = os.path.join(STATE_DIR, "runtime")
CONFIG_FILE = os.path.join(RUNTIME_DIR, "config.yaml")
PID_FILE = os.path.join(STATE_DIR, "proxy.pid")
LOG_FILE = os.path.join(STATE_DIR, "proxy.log")
DEFAULT_PORT = 7890
DEFAULT_BIND = "127.0.0.1"


def session_path():
    override = os.environ.get("XDG_CONFIG_HOME")
    if override:
        return os.path.join(override, ".Monocloud.json")
    home = os.path.join(os.path.expanduser("~"), ".config", ".Monocloud.json")
    if os.path.exists(home):
        return home
    return os.path.join(STATE_DIR, ".Monocloud.json")


def load_session():
    path = session_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        raise SystemExit("monocloud: not signed in. Run: monocloud login")
    if not isinstance(data, dict) or not data.get("token"):
        raise SystemExit("monocloud: not signed in. Run: monocloud login")
    return data


def api_get(session, path):
    url = session["apiBaseUrl"].rstrip("/") + "/" + path.lstrip("/")
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": "Bearer " + session["token"],
            "Accept": "application/json",
            "X-Client-Version": "1.0.3",
            "User-Agent": "MonoCloud/1.0.3",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read(200).decode("utf-8", "replace")
        raise SystemExit(f"monocloud: API {path} failed: HTTP {exc.code} {body}") from exc


def yaml_quote(value):
    return json.dumps(str(value), ensure_ascii=False)


def fetch_nodes(session):
    services = api_get(session, "api/service")
    if not services:
        raise SystemExit("monocloud: this account has no active service")
    service = services[0]
    plan_type = ((service.get("plan") or {}).get("type") or "shadowsocks").lower()
    service_id = service["id"]
    nodes = api_get(session, f"api/{plan_type}/{service_id}")
    enabled = [node for node in nodes if node.get("enable", 1)]
    if not enabled:
        raise SystemExit("monocloud: no enabled nodes")
    return service, enabled


def write_config(nodes, port, bind, selected):
    names = [node.get("alias") or node["hostname"] for node in nodes]
    if selected not in names:
        raise SystemExit(
            "monocloud: unknown node {!r}. Available: {}".format(selected, ", ".join(names))
        )
    ordered = [selected] + [name for name in names if name != selected]
    lines = [
        f"mixed-port: {port}",
        "allow-lan: {}".format("true" if bind != "127.0.0.1" else "false"),
        f"bind-address: {yaml_quote(bind)}",
        "mode: rule",
        "log-level: info",
        "ipv6: false",
        "find-process-mode: off",
        "proxies:",
    ]
    for node in nodes:
        name = node.get("alias") or node["hostname"]
        lines.extend(
            [
                f"  - name: {yaml_quote(name)}",
                "    type: ss",
                f"    server: {yaml_quote(node['hostname'])}",
                f"    port: {int(node['port'])}",
                f"    cipher: {yaml_quote(node.get('encryption') or 'chacha20-ietf-poly1305')}",
                f"    password: {yaml_quote(node['password'])}",
                "    udp: true",
            ]
        )
    lines.extend(
        [
            "proxy-groups:",
            "  - name: PROXY",
            "    type: select",
            "    proxies:",
        ]
    )
    for name in ordered:
        lines.append(f"      - {yaml_quote(name)}")
    lines.extend(["rules:", "  - MATCH,PROXY", ""])
    os.makedirs(RUNTIME_DIR, mode=0o700, exist_ok=True)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    os.chmod(tmp, 0o600)
    os.replace(tmp, CONFIG_FILE)
    os.chmod(CONFIG_FILE, 0o600)


def read_pid():
    try:
        with open(PID_FILE, "r", encoding="utf-8") as fh:
            return int(fh.read().strip())
    except (OSError, ValueError):
        return None


def running_pid():
    pid = read_pid()
    if not pid:
        return None
    try:
        os.kill(pid, 0)
    except OSError:
        return None
    return pid


def stop():
    pid = running_pid()
    if not pid:
        print("Proxy is not running")
        try:
            os.remove(PID_FILE)
        except OSError:
            pass
        return
    os.kill(pid, signal.SIGTERM)
    for _ in range(30):
        try:
            os.kill(pid, 0)
        except OSError:
            break
        time.sleep(0.1)
    else:
        os.kill(pid, signal.SIGKILL)
    try:
        os.remove(PID_FILE)
    except OSError:
        pass
    print(f"Stopped proxy pid {pid}")


def start(port, bind, node):
    session = load_session()
    service, nodes = fetch_nodes(session)
    names = [item.get("alias") or item["hostname"] for item in nodes]
    selected = node or names[0]
    write_config(nodes, port, bind, selected)
    test = subprocess.run(
        [CORE, "-t", "-f", CONFIG_FILE, "-d", RUNTIME_DIR],
        capture_output=True,
        text=True,
    )
    if test.returncode != 0:
        detail = (test.stderr or test.stdout or "").strip().splitlines()
        raise SystemExit("monocloud: config test failed: " + (detail[-1] if detail else "unknown error"))
    if running_pid():
        stop()
    log = open(LOG_FILE, "ab", buffering=0)
    proc = subprocess.Popen(
        [CORE, "-d", RUNTIME_DIR, "-f", CONFIG_FILE],
        stdout=log,
        stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL,
        start_new_session=True,
    )
    with open(PID_FILE, "w", encoding="utf-8") as fh:
        fh.write(str(proc.pid))
    time.sleep(0.6)
    if proc.poll() is not None:
        raise SystemExit(f"monocloud: proxy exited. See {LOG_FILE}")
    plan = (service.get("plan") or {}).get("name") or "service"
    print(f"Proxy listening on {bind}:{port} (HTTP and SOCKS5)")
    print(f"Plan: {plan}")
    print(f"Node: {selected}")
    print(f"Other nodes: {', '.join(name for name in names if name != selected)}")
    print(f"Log: {LOG_FILE}")


def status():
    pid = running_pid()
    if not pid:
        print("Proxy is not running")
        raise SystemExit(1)
    print(f"Proxy running pid {pid}")
    print(f"Config: {CONFIG_FILE}")
    print(f"Log: {LOG_FILE}")


def main():
    parser = argparse.ArgumentParser(prog="monocloud proxy")
    parser.add_argument("action", nargs="?", choices=("start", "stop", "status", "restart"), default="start")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT, help="local mixed proxy port (default 7890)")
    parser.add_argument("--bind", default=DEFAULT_BIND, help="listen address (default 127.0.0.1)")
    parser.add_argument("--node", help="node alias to use first, for example Relay-HK1")
    args = parser.parse_args()
    if not (1 <= args.port <= 65535):
        raise SystemExit("monocloud: port must be between 1 and 65535")
    if args.action == "stop":
        stop()
    elif args.action == "status":
        status()
    elif args.action == "restart":
        stop()
        start(args.port, args.bind, args.node)
    else:
        start(args.port, args.bind, args.node)


if __name__ == "__main__":
    main()
