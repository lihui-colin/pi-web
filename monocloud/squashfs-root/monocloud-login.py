#!/usr/bin/env python3
"""Command-line login for the MonoCloud 1.0.3 desktop client."""

import argparse
import getpass
import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

PRIMARY_BASE = "https://api.bluecloudworks.com/"
FALLBACK_BASE = "https://ac.applecross.link/"
CLIENT_ID = "019f193d-f543-7151-adb3-cdbea9e8f14d"
CLIENT_SECRET = "hxHXGxyhUNrvQ1eXGvjOFVzrdfaHkM8T7Y2Z1vt3"
CLIENT_VERSION = "1.0.3"


def config_dir():
    override = os.environ.get("XDG_CONFIG_HOME")
    if override:
        return override
    home_root = os.path.join(os.path.expanduser("~"), ".config")
    fallback = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "config"
    )
    try:
        os.makedirs(home_root, mode=0o700, exist_ok=True)
        probe = os.path.join(home_root, ".Monocloud.write-test")
        with open(probe, "w", encoding="utf-8") as fh:
            fh.write("")
        os.remove(probe)
        return home_root
    except OSError:
        return fallback


def config_path():
    return os.path.join(config_dir(), ".Monocloud.json")


def load_config():
    path = config_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        return {}
    except (OSError, json.JSONDecodeError) as exc:
        print(f"monocloud: cannot read {path}: {exc}", file=sys.stderr)
        return {}
    return data if isinstance(data, dict) else {}


def save_config(data):
    path = config_path()
    os.makedirs(os.path.dirname(path), mode=0o700, exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)
        fh.write("\n")
        fh.flush()
        os.fsync(fh.fileno())
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    os.chmod(path, 0o600)
    return path


def prompt(label):
    try:
        return input(label).strip()
    except EOFError:
        print("\nmonocloud: email is required", file=sys.stderr)
        raise SystemExit(2)


def prompt_secret(label):
    try:
        return getpass.getpass(label)
    except EOFError:
        print("\nmonocloud: password is required", file=sys.stderr)
        raise SystemExit(2)


def post_token(base, email, password, sub_user):
    path = "oauth/sub-user/token" if sub_user else "oauth/token"
    url = urllib.parse.urljoin(base, path)
    body = urllib.parse.urlencode(
        {
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "username": email,
            "password": password,
        }
    ).encode()
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
            "X-Client-Version": CLIENT_VERSION,
            "User-Agent": f"MonoCloud/{CLIENT_VERSION}",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            raw = response.read()
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            payload = json.loads(raw.decode() or "{}")
        except json.JSONDecodeError:
            payload = {}
        message = payload.get("message") or payload.get("error") or exc.reason
        raise SystemExit(f"monocloud: login failed: {message}") from exc
    except urllib.error.URLError as exc:
        raise ConnectionError(exc.reason) from exc
    try:
        payload = json.loads(raw.decode() or "{}")
    except json.JSONDecodeError as exc:
        raise SystemExit("monocloud: login failed: server returned invalid JSON") from exc
    token = payload.get("access_token") or payload.get("token")
    if not token:
        raise SystemExit("monocloud: login failed: response did not include a token")
    return token


def login(email, password, sub_user):
    bases = []
    saved = load_config().get("apiBaseUrl")
    if isinstance(saved, str) and saved.startswith("https://"):
        bases.append(saved if saved.endswith("/") else saved + "/")
    for base in (PRIMARY_BASE, FALLBACK_BASE):
        if base not in bases:
            bases.append(base)
    last_error = None
    for base in bases:
        try:
            token = post_token(base, email, password, sub_user)
        except ConnectionError as exc:
            last_error = exc
            continue
        config = load_config()
        config.update(
            {
                "email": email,
                "token": token,
                "authenticated": True,
                "remember": True,
                "subUser": bool(sub_user),
                "apiBaseUrl": base,
            }
        )
        path = save_config(config)
        kind = "sub-user" if sub_user else "main account"
        print(f"Signed in as {email} ({kind})")
        print(f"Session saved to {path}")
        return
    raise SystemExit(f"monocloud: cannot reach the login server: {last_error}")


def logout():
    path = config_path()
    config = load_config()
    if not config:
        print("Not signed in")
        return
    email = config.get("email") or ""
    config["token"] = ""
    config["authenticated"] = False
    save_config(config)
    if email:
        print(f"Signed out {email}")
    else:
        print("Signed out")


def whoami():
    config = load_config()
    if not config.get("token"):
        print("Not signed in")
        raise SystemExit(1)
    email = config.get("email") or "(unknown)"
    kind = "sub-user" if config.get("subUser") else "main account"
    print(f"{email} ({kind})")
    print(f"Session file: {config_path()}")


def main():
    parser = argparse.ArgumentParser(prog="monocloud login")
    parser.add_argument("action", nargs="?", choices=("login", "logout", "whoami"), default="login")
    parser.add_argument("--email", help="account email; prompted when omitted")
    parser.add_argument(
        "--password",
        help="account password; prompted when omitted (preferred, so it is not stored in the shell history)",
    )
    parser.add_argument("--sub-user", action="store_true", help="sign in as a sub-user")
    args = parser.parse_args()
    if args.action == "logout":
        logout()
        return
    if args.action == "whoami":
        whoami()
        return
    email = (args.email or "").strip() or prompt("Email: ")
    password = args.password if args.password is not None else prompt_secret("Password: ")
    if not email or not password:
        print("monocloud: email and password are required", file=sys.stderr)
        raise SystemExit(2)
    login(email, password, args.sub_user)


if __name__ == "__main__":
    main()
