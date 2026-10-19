"""Verified, explicit installation; runtime never downloads assets."""
import hashlib
import json
import platform
from pathlib import Path
import shutil
import subprocess
import tarfile

HERE = Path(__file__).resolve().parent
MANIFEST = json.loads((HERE / 'assets.json').read_text())


def checked(path, item):
    if not path.is_file() or path.stat().st_size != item['size']:
        return False
    with path.open('rb') as stream:
        digest = hashlib.sha256()
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
        return digest.hexdigest() == item['sha256']


def source(root):
    repo = root / 'upstream'
    def git(*args):
        return subprocess.check_output(['git', '-C', str(repo), *args], text=True).strip()
    if git('rev-parse', 'HEAD') != MANIFEST['commit'] or git('status', '--porcelain', '--untracked-files=normal'):
        raise ValueError('CapsWriter source differs from pinned commit')


def verify(root):
    source(root)
    for archive in MANIFEST['archives']:
        for item in archive['files'].values():
            if not checked(root / item['path'], item):
                raise ValueError('Missing or corrupt asset: ' + item['path'])


def install(root):
    if platform.system() != 'Linux' or platform.machine() != 'x86_64':
        raise ValueError('Supported platform: Linux x86_64')
    root.mkdir(parents=True, exist_ok=True)
    repo = root / 'upstream'
    if not repo.exists():
        subprocess.run(['git', 'init', str(repo)], check=True)
        subprocess.run(['git', '-C', str(repo), 'fetch', '--depth=1', MANIFEST['upstream'], MANIFEST['commit']], check=True)
        subprocess.run(['git', '-C', str(repo), 'checkout', '--detach', 'FETCH_HEAD'], check=True)
    source(root)
    subprocess.run(['uv', 'venv', '--python', '3.12.3', '--allow-existing', str(root / 'venv')], check=True)
    subprocess.run(['uv', 'pip', 'sync', '--python', str(root / 'venv/bin/python'),
                    '--require-hashes', str(HERE / 'requirements.lock')], check=True)
    downloads = root / 'downloads'
    downloads.mkdir(exist_ok=True)
    for archive in MANIFEST['archives']:
        if all(checked(root / i['path'], i) for i in archive['files'].values()):
            continue
        path = downloads / archive['name']
        if not checked(path, archive):
            partial = path.with_suffix('.part')
            subprocess.run(['curl', '--fail', '--location', '--retry', '3', '--output', str(partial), archive['url']], check=True)
            if not checked(partial, archive):
                raise ValueError('Download checksum mismatch: ' + archive['name'])
            partial.replace(path)
        remaining = dict(archive['files'])
        with tarfile.open(path, 'r|bz2') as tar:
            # Stream only explicitly listed regular files, never archive paths.
            for info in tar:
                item = remaining.pop(info.name, None)
                if item is None:
                    continue
                if not info.isfile() or info.size != item['size']:
                    raise ValueError('Unexpected archive member')
                dest = root / item['path']
                dest.parent.mkdir(parents=True, exist_ok=True)
                partial = dest.with_suffix('.part')
                with tar.extractfile(info) as src, partial.open('wb') as out:
                    shutil.copyfileobj(src, out)
                if not checked(partial, item):
                    raise ValueError('Extracted file checksum mismatch')
                partial.replace(dest)
                if not remaining:
                    break
        if remaining:
            raise ValueError('Missing archive members')
    if not (root / 'config.json').exists():
        shutil.copyfile(HERE / 'config.example.json', root / 'config.json')
    verify(root)
