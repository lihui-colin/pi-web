import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class ProfileTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.profile = self.root / 'config/orca'
        self.profile.mkdir(parents=True)
        self.backups = self.root / 'backups'
        self.env = dict(os.environ, XDG_CONFIG_HOME=str(self.root / 'config'))

    def run_configure(self):
        return subprocess.run(['python3', '-B', str(ROOT / 'srcs/configure-profile.py'), str(self.backups)],
                              env=self.env, capture_output=True, text=True, timeout=10)

    def database(self):
        (self.profile / 'orca-profile-index.json').write_text(json.dumps({'activeProfileId': 'personal'}))
        directory = self.profile / 'profiles/personal'
        directory.mkdir(parents=True)
        path = directory / 'profile-state.db'
        settings = {'custom': 'keep', 'nativeChatProviders': {'claude': False, 'codex': False}}
        payload = json.dumps(settings)
        with sqlite3.connect(path) as c:
            c.executescript('CREATE TABLE profile_state_meta(key TEXT PRIMARY KEY,value TEXT);'
                            'CREATE TABLE profile_state_documents(domain TEXT PRIMARY KEY,payload TEXT,'
                            'domain_version INTEGER,revision INTEGER,updated_at INTEGER,content_hash TEXT);')
            c.execute('INSERT INTO profile_state_meta VALUES (?,?)', ('revision', '7'))
            c.execute('INSERT INTO profile_state_documents VALUES (?,?,?,?,?,?)',
                      ('settings', payload, 1, 7, 1, hashlib.sha256(payload.encode()).hexdigest()))
            c.execute('INSERT INTO profile_state_documents VALUES (?,?,?,?,?,?)', ('repos', '[]', 1, 2, 1, 'unchanged'))
        return path

    def test_new_json_then_repeat_is_unchanged(self):
        self.assertEqual(self.run_configure().returncode, 0)
        path = self.profile / 'orca-data.json'
        self.assertEqual(json.loads(path.read_text())['settings'],
                         {'agentDefaultSurface': 'chat', 'nativeChatProviders': {'codex': True}})
        before = path.stat().st_mtime_ns
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertEqual(self.run_configure().returncode, 0)
        self.assertEqual(path.stat().st_mtime_ns, before)

    def test_sqlite_preserves_settings_hash_revision_and_backup(self):
        path = self.database()
        result = self.run_configure()
        self.assertEqual(result.returncode, 0, result.stderr)
        with sqlite3.connect(path) as c:
            payload, revision, digest = c.execute("SELECT payload,revision,content_hash FROM profile_state_documents WHERE domain='settings'").fetchone()
            settings = json.loads(payload)
            self.assertEqual(settings['custom'], 'keep')
            self.assertEqual(settings['nativeChatProviders'], {'claude': False, 'codex': True})
            self.assertEqual(settings['agentDefaultSurface'], 'chat')
            self.assertEqual(digest, hashlib.sha256(payload.encode()).hexdigest())
            self.assertEqual(revision, 8)
            self.assertEqual(c.execute("SELECT value FROM profile_state_meta WHERE key='revision'").fetchone()[0], '8')
            self.assertEqual(c.execute("SELECT content_hash FROM profile_state_documents WHERE domain='repos'").fetchone()[0], 'unchanged')
        backups = list(self.backups.iterdir())
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)
        with sqlite3.connect(backups[0]) as c:
            self.assertEqual(c.execute("SELECT value FROM profile_state_meta WHERE key='revision'").fetchone()[0], '7')
        (self.profile / 'orcad.lock').write_text(json.dumps({'pid': os.getpid()}))
        self.assertEqual(self.run_configure().returncode, 0)
        self.assertEqual(list(self.backups.iterdir()), backups)

    def test_running_service_rejects_write(self):
        path = self.database()
        before = path.read_bytes()
        (self.profile / 'orca-runtime.json').write_text(json.dumps({'pid': os.getpid()}))
        result = self.run_configure()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('正在运行', result.stderr)
        self.assertEqual(path.read_bytes(), before)
        self.assertFalse(self.backups.exists())

    def test_legacy_json_preserves_other_data_and_backups(self):
        path = self.profile / 'orca-data.json'
        original = {'repos': [{'id': 'keep'}], 'settings': {'custom': True}}
        path.write_text(json.dumps(original))
        self.assertEqual(self.run_configure().returncode, 0)
        saved = json.loads(path.read_text())
        self.assertEqual(saved['repos'], original['repos'])
        self.assertTrue(saved['settings']['custom'])
        self.assertEqual(json.loads(next(self.backups.iterdir()).read_text()), original)

    def test_corrupt_settings_hash_is_not_overwritten(self):
        path = self.database()
        with sqlite3.connect(path) as c:
            c.execute("UPDATE profile_state_documents SET content_hash='invalid' WHERE domain='settings'")
        before = path.read_bytes()
        result = self.run_configure()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('哈希', result.stderr)
        self.assertEqual(path.read_bytes(), before)

    def test_existing_json_chat_choice_gets_migration_marker(self):
        path = self.profile / 'orca-data.json'
        path.write_text(json.dumps({'settings': {'agentDefaultSurface': 'chat',
                                               'nativeChatProviders': {'codex': True}}}))
        self.assertEqual(self.run_configure().returncode, 0)
        self.assertIn('chatUiLaunchTipAudience', json.loads(path.read_text()))
