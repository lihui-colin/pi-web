import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]


class InstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for name in ('install.sh', 'ocra.conf.example'):
            shutil.copy2(ROOT / name, self.root / name)
        shutil.copytree(ROOT / 'srcs', self.root / 'srcs')
        self.bin = self.root / 'mock-bin'
        self.bin.mkdir()
        self.release = {'tag_name': 'v1.4.261', 'assets': [
            {'name': f'orca-server-linux-{arch}.tar.gz', 'digest': 'sha256:' + 'a' * 64}
            for arch in ('x64', 'arm64')]}
        self.mock_release()
        self.env = dict(os.environ, PATH=str(self.bin) + ':' + os.environ['PATH'],
                        XDG_CONFIG_HOME=str(self.root / 'config'))

    def mock_release(self):
        cli = self.bin / 'curl'
        cli.write_text('#!/usr/bin/env python3\nprint(' + repr(json.dumps(self.release)) + ')\n')
        cli.chmod(0o700)

    def installed(self, version):
        cli = self.root / f'data/releases/{version}/bin/orca-ide'
        cli.parent.mkdir(parents=True)
        cli.write_text('#!/bin/sh\necho ' + version + '\n')
        cli.chmod(0o700)
        (self.root / 'data/orca-server').symlink_to(cli.parents[1])

    def run_install(self, answer=''):
        return subprocess.run(['bash', str(self.root / 'install.sh')], input=answer,
                              env=self.env, capture_output=True, text=True, timeout=10)

    def test_latest_skips_and_initializes_config(self):
        self.installed('1.4.261')
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('跳过安装', result.stdout)
        profile = json.loads((self.root / 'config/orca/orca-data.json').read_text())
        self.assertEqual(profile['settings']['agentDefaultSurface'], 'chat')
        self.assertTrue(profile['settings']['nativeChatProviders']['codex'])
        self.assertEqual((self.root / 'data/ocra.conf').read_bytes(),
                         (self.root / 'ocra.conf.example').read_bytes())

    def test_existing_version_requires_confirmation(self):
        self.installed('1.4.258')
        config = self.root / 'data/ocra.conf'
        config.write_text('{"ip":"10.30.0.25","port":25225,"custom":"keep"}')
        before = config.read_bytes()
        for answer in ('', '\n', 'n\n'):
            result = self.run_install(answer)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn('是否更新', result.stdout)
            self.assertIn('跳过更新', result.stdout)
            self.assertEqual(config.read_bytes(), before)
            self.assertIn('1.4.258', str((self.root / 'data/orca-server').resolve()))

    def test_missing_digest_fails_and_creates_data(self):
        self.release['assets'][0]['digest'] = ''
        self.release['assets'][1]['digest'] = ''
        self.mock_release()
        result = self.run_install()
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('SHA256', result.stderr)
        self.assertTrue((self.root / 'data/ocra.conf').is_file())
        self.assertFalse((self.root / 'data/orca-server').exists())

    def test_confirmed_update_uses_cached_release(self):
        self.installed('1.4.258')
        import platform
        arch = 'x64' if platform.machine() == 'x86_64' else 'arm64'
        cli = self.root / f'data/releases/1.4.261-linux-{arch}/bin/orca-ide'
        cli.parent.mkdir(parents=True)
        cli.write_text('#!/bin/sh\necho 1.4.261\n')
        cli.chmod(0o700)
        result = self.run_install('yes\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.root / 'data/orca-server').resolve(), cli.parents[1])

    def test_latest_install_preserves_official_bundle(self):
        self.installed('1.4.261')
        target = self.root / 'data/orca-server/orcad/orcad-server.js'
        target.parent.mkdir()
        original = b'official bundle must remain unchanged'
        target.write_bytes(original)
        result = self.run_install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(target.read_bytes(), original)
