#!/usr/bin/env python3
"""Configure native Chat in Orca's profile without altering release artifacts."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import sys
from ocra import write_json
import time


def chat_settings(settings):
    return {**settings, 'agentDefaultSurface': 'chat',
            'nativeChatProviders': {**(settings.get('nativeChatProviders') or {}), 'codex': True}}


def require_stopped(root):
    for name in ('orcad.lock', 'orca-runtime.json'):
        path = root / name
        if not path.exists():
            continue
        try:
            pid = json.loads(path.read_text())['pid']
            if type(pid) is not int or pid <= 0:
                raise ValueError('invalid PID')
            os.kill(pid, 0)
        except ProcessLookupError:
            continue
        except (ValueError, KeyError, PermissionError) as error:
            raise RuntimeError(f'无法确认 Orca 是否停止：{path}') from error
        raise RuntimeError('Orca 正在运行，未修改 profile；请在任务完成后停止服务，再执行安装。')


def backup_path(backups, name):
    backups.mkdir(mode=0o700, parents=True, exist_ok=True)
    return backups / f'{name}.{time.time_ns()}.bak'


def configure(root, backups):
    index = root / 'orca-profile-index.json'
    if index.exists():
        profile_id = json.loads(index.read_text())['activeProfileId']
        if not isinstance(profile_id, str) or profile_id in ('', '.', '..') or '/' in profile_id or '\\' in profile_id:
            raise ValueError('无效的 activeProfileId')
        directory = root / 'profiles' / profile_id
    else:
        directory = root
        if (root / 'profiles').exists():
            raise RuntimeError('已有 profiles 但缺少 profile 索引，拒绝猜测配置位置。')
    database = directory / 'profile-state.db'
    if database.exists():
        with sqlite3.connect(f'{database.as_uri()}?mode=ro', uri=True) as check:
            row = check.execute("SELECT payload, content_hash FROM profile_state_documents WHERE domain='settings'").fetchone()
            if not row:
                raise RuntimeError('profile 缺少 settings 文档')
            if hashlib.sha256(row[0].encode()).hexdigest() != row[1]:
                raise RuntimeError('settings 内容哈希不匹配，未修改 profile')
            settings = json.loads(row[0])
            if chat_settings(settings) == settings:
                print('Profile 已配置默认 Chat 和 Codex 原生 Chat。')
                return
        require_stopped(root)
        with sqlite3.connect(database, timeout=5) as connection:
            destination = backup_path(backups, database.name)
            with sqlite3.connect(destination) as saved:
                connection.backup(saved)
            connection.execute('BEGIN IMMEDIATE')
            payload, digest = connection.execute("SELECT payload,content_hash FROM profile_state_documents WHERE domain='settings'").fetchone()
            if hashlib.sha256(payload.encode()).hexdigest() != digest:
                raise RuntimeError('settings 内容哈希不匹配')
            updated = json.dumps(chat_settings(json.loads(payload)), ensure_ascii=False, separators=(',', ':'))
            revision = int(connection.execute("SELECT value FROM profile_state_meta WHERE key='revision'").fetchone()[0]) + 1
            connection.execute("UPDATE profile_state_documents SET payload=?,revision=?,updated_at=?,content_hash=? WHERE domain='settings'",
                               (updated, revision, int(time.time()*1000), hashlib.sha256(updated.encode()).hexdigest()))
            connection.execute("UPDATE profile_state_meta SET value=? WHERE key='revision'", (str(revision),))
    else:
        if database.with_suffix('.db.authority').exists():
            raise RuntimeError('SQLite profile 缺少数据库，拒绝改写为 JSON 配置。')
        path = directory / 'orca-data.json'
        document = json.loads(path.read_text()) if path.exists() else {}
        settings = document.get('settings', {})
        if chat_settings(settings) == settings and 'chatUiLaunchTipAudience' in document:
            print('Profile 已配置默认 Chat 和 Codex 原生 Chat。')
            return
        require_stopped(root)
        directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if path.exists():
            destination = backup_path(backups, path.name)
            shutil.copy2(path, destination)
            destination.chmod(0o600)
        # Without this marker Orca migrates legacy Chat preferences over the new fields.
        document.setdefault('chatUiLaunchTipAudience',
                            {'version': 1, 'membership': 'excluded', 'basis': 'new-profile'})
        document['settings'] = chat_settings(settings)
        write_json(path, document)
    print('已配置默认 Chat 和 Codex 原生 Chat；已有配置修改前已备份。')


if __name__ == '__main__':
    os.umask(0o077)
    try:
        configure((Path(os.environ.get('XDG_CONFIG_HOME', str(Path.home() / '.config'))) / 'orca').resolve(),
                  Path(sys.argv[1]).resolve())
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error, RuntimeError) as error:
        print(f'配置 profile 失败：{error}', file=sys.stderr)
        sys.exit(1)
