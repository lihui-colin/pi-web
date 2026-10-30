"""Shared test fixtures; never use deployment certificates."""

from pathlib import Path
import os
import shutil
import subprocess
import unittest


def local_nginx():
    prefix = Path(__file__).resolve().parent / "data/.local/nginx"
    binary = prefix / "sbin/nginx"
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return None
    binary = binary.resolve()
    return binary if binary.is_relative_to(prefix) else None


def copy_test_nginx(directory):
    source = local_nginx()
    if source is None:
        raise unittest.SkipTest("run dsh_nginx_install.sh to install the project-local Nginx")
    destination = Path(directory) / "data/.local/nginx/sbin/nginx"
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)
    return destination


def create_test_certificate(directory):
    cert, key = Path(directory) / "cert.pem", Path(directory) / "key.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost",
        "-keyout", str(key), "-out", str(cert),
    ], check=True, capture_output=True, timeout=15)
    return cert, key


def copy_test_launcher(directory):
    for name in ('dsh_web_run.sh', 'dsh_runtime.py'):
        shutil.copy2(Path(__file__).with_name(name), Path(directory) / name)
    return Path(directory) / 'dsh_web_run.sh'
