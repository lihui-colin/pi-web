"""Shared test fixtures; never use deployment certificates."""

from pathlib import Path
import os
import sys
import shutil
import subprocess
import unittest


SRC_DIR = Path(__file__).resolve().parents[1] / "srcs"
sys.path.insert(0, str(SRC_DIR))

ENTRY_SCRIPTS = frozenset((
    'dsh_install.sh', 'dsh_web_run.sh', 'dsh_proxy.sh',
    'dsh_plugins_install.sh', 'dsh_patches_install.sh', 'dsh_nginx_install.sh', 'dsh_cert.sh',
))


def local_nginx():
    prefix = Path(__file__).resolve().parents[1] / "data/.local/nginx"
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
        shutil.copy2(source_file(name), fixture_file(directory, name))
    return Path(directory) / 'dsh_web_run.sh'


def source_file(name):
    return (SRC_DIR.parent if name in ENTRY_SCRIPTS else SRC_DIR) / name

def fixture_file(root, name):
    target = Path(root) / (name if name in ENTRY_SCRIPTS else 'srcs/' + name)
    target.parent.mkdir(parents=True, exist_ok=True)
    return target


def copy_patch_tools(root):
    """Use the real coordinator with isolated planners in installer tests."""
    from patches.apply import PATCHES
    shutil.copy2(source_file('dsh_patches_install.sh'), fixture_file(root, 'dsh_patches_install.sh'))
    for name in ('patches/apply.py', 'patches/common.py'):
        shutil.copy2(source_file(name), fixture_file(root, name))
    markers = ('PATCH_BUNDLE', 'MOBILE_PATCH', 'GIT_PANEL_PATCH', 'TERMINAL_PATCH',
               'FILE_RESOURCES_PATCH', 'COMPOSER_METADATA_PATCH', 'CONTEXT_DETAILS_PATCH')
    for (module, _, _), marker in zip(PATCHES, markers, strict=True):
        fixture_file(root, 'patches/' + module.replace('.', '/') + '.py').write_text(
            'import os\n'
            'def plan_changes(**options):\n'
            f'    print("{marker}_APPLIED")\n'
            '    status = int(os.environ.get("FAKE_PATCH_FAIL", "0"))\n'
            '    if status: raise SystemExit(status)\n'
            '    return []\n'
        )
