"""Shared test fixtures; never use deployment certificates."""

from pathlib import Path
import subprocess


def create_test_certificate(directory):
    cert, key = Path(directory) / "cert.pem", Path(directory) / "key.pem"
    subprocess.run([
        "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
        "-subj", "/CN=localhost", "-addext", "subjectAltName=IP:127.0.0.1,DNS:localhost",
        "-keyout", str(key), "-out", str(cert),
    ], check=True, capture_output=True, timeout=15)
    return cert, key
