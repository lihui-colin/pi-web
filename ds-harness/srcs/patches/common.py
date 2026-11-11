"""Shared validation and atomic publication for DSH bundle patches."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


COMPONENT_ROOT = Path(__file__).resolve().parents[2]


def replace_once(text, old, new):
    if new in text:
        if text.count(new) != 1 or old in text.replace(new, '', 1):
            raise ValueError('Duplicate or mixed patch anchors; inspect upstream before applying')
        return text
    if text.count(old) != 1:
        raise ValueError('Unrecognized bundle; inspect upstream before applying')
    return text.replace(old, new, 1)

def apply_replacements(text, replacements):
    """Apply ordered, independently idempotent replacements with exact guards."""
    for old, new in replacements:
        text = replace_once(text, old, new)
    return text


def undo_replacements(text, replacements, *, error='Incomplete terminal patch; inspect before applying'):
    """Reverse only a complete, unambiguous set of installed replacements."""
    for old, new in reversed(replacements):
        if text.count(new) != 1:
            raise ValueError(error)
        text = text.replace(new, old, 1)
    return text


def vendor_addon(path, digest, export, *, error=None):
    """Verify an upstream UMD bundle and embed it without source-map requests."""
    path = Path(path)
    data = path.read_bytes()
    if hashlib.sha256(data).hexdigest() != digest:
        raise ValueError(error or f'Unexpected terminal addon contents: {path.name}')
    source = '\n'.join(line for line in data.decode().splitlines() if not line.startswith('//# sourceMappingURL='))
    return (f'const DshTerminal{export} = (() => {{\nconst module = {{exports: {{}}}}, exports = module.exports;\n'
            + source + f'\nreturn module.exports.{export};\n}})();\n')


def publish(changes, backup_root=None):
    """Stage every file, keep originals, and roll back completed replacements on failure."""
    pending = [(path.resolve(), original, fixed) for path, original, fixed in changes if original != fixed]
    if not pending:
        return
    if any(path.read_text() != original for path, original, _ in changes):
        raise ValueError('Target changed during validation; rerun without overwriting it')
    backup_root = backup_root or COMPONENT_ROOT / 'log/patch-backups'
    backup_root.mkdir(parents=True, exist_ok=True)
    backup = Path(tempfile.mkdtemp(prefix='ds-bot-', dir=backup_root))
    staged = []
    replaced = []
    try:
        for index, (path, original, fixed) in enumerate(pending):
            saved = backup / str(index)
            shutil.copy2(path, saved)
            # Staging next to the target guarantees same-filesystem atomic replacement.
            stage_dir = Path(tempfile.mkdtemp(prefix='.ds-bot-patch-', dir=path.parent))
            staged.append((path, saved, stage_dir))
            stage = stage_dir / 'client'
            stage.write_text(fixed)
            shutil.copymode(path, stage)
            with stage.open('rb') as handle:
                os.fsync(handle.fileno())
        (backup / 'manifest.json').write_text(json.dumps([str(path) for path, _, _ in pending], indent=2))
        if any(path.read_text() != original for path, original, _ in changes):
            raise ValueError('Target changed while staging; no replacements made')
        for path, saved, stage_dir in staged:
            os.replace(stage_dir / 'client', path)
            replaced.append((path, saved, stage_dir))
    except Exception as error:
        failures = []
        for path, saved, stage_dir in reversed(replaced):
            try:
                shutil.copy2(saved, stage_dir / 'restore')
                os.replace(stage_dir / 'restore', path)
            except OSError:
                failures.append(str(path))
        detail = f'; rollback failed for {failures}' if failures else '; completed replacements rolled back'
        raise RuntimeError(f'Patch publication failed{detail}. Originals: {backup}') from error
    finally:
        for path, _, stage_dir in staged:
            # Only remove directories created above, alongside their verified target.
            if stage_dir.parent == path.parent and stage_dir.name.startswith('.ds-bot-patch-'):
                shutil.rmtree(stage_dir)
    print(f'Original files saved in {backup}')


def host_directory(host=None):
    if host is not None:
        return Path(host)
    executable = shutil.which('dsh')
    if executable is None:
        raise ValueError('dsh executable not found')
    return Path(executable).resolve().parents[1] / 'node_modules/@deepseek-ai'


def verify_package(directory, name, versions):
    manifest = json.loads((Path(directory) / 'package.json').read_text())
    if manifest.get('name') != name or manifest.get('version') not in versions:
        raise ValueError(f'Unsupported package {manifest.get("name")}@{manifest.get("version")}; expected {name} at {versions}. Review upstream before applying.')
    return manifest['version']


def read_change(path, transform, *, read_text=Path.read_text):
    original = read_text(path)
    return path, original, transform(original)


def reviewed_host_package(host, name, versions=('0.2.2-rc.1', '0.2.2-alpha.2'), *, skip=('0.2.2-alpha.2',)):
    """Resolve and verify a core package before reading its version-specific code."""
    package = host_directory(host) / name
    version = verify_package(package, '@deepseek-ai/' + name, versions)
    return None if version in skip else package


def plan_host_patch(host, name, transform, *, filename='lib/client.js', read_text=Path.read_text, **review):
    """Plan one core bundle, preserving known-version skips and injected reads."""
    package = reviewed_host_package(host, name, **review)
    return [] if package is None else [read_change(package / filename, transform, read_text=read_text)]


def check_or_publish(changes, check, message):
    if check:
        pending = [str(path) for path, before, after in changes if before != after]
        if pending:
            raise SystemExit(message + ': ' + ', '.join(pending))
    else:
        publish(changes)


def patch_cli(planner, description, directories, message):
    """Keep standalone patch commands consistent with the shared publisher."""
    parser = argparse.ArgumentParser(description=description)
    parser.add_argument('--check', action='store_true', help='Validate without writing')
    for parameter, flag in directories.items():
        parser.add_argument(flag, dest=parameter, type=Path)
    options = vars(parser.parse_args())
    check = options.pop('check')
    check_or_publish(planner(**options), check, 'Required patches missing')
    print(message + '; no service restarted.')
