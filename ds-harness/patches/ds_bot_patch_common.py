"""Strict bundle replacements and recoverable publication of reviewed patches."""
import json
import os
from pathlib import Path
import shutil
import tempfile


def replace_once(text, old, new):
    if new in text:
        if text.count(new) != 1 or old in text.replace(new, '', 1):
            raise ValueError('Duplicate or mixed patch anchors; inspect upstream before applying')
        return text
    if text.count(old) != 1:
        raise ValueError('Unrecognized bundle; inspect upstream before applying')
    return text.replace(old, new, 1)


def publish(changes, backup_root=None):
    """Stage every file, keep originals, and roll back completed replacements on failure."""
    pending = [(path.resolve(), original, fixed) for path, original, fixed in changes if original != fixed]
    if not pending:
        return
    if any(path.read_text() != original for path, original, _ in changes):
        raise ValueError('Target changed during validation; rerun without overwriting it')
    backup_root = backup_root or Path(__file__).resolve().parents[1] / 'log/patch-backups'
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
