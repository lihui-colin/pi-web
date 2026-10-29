"""Installer planning tests: no network, global installs, or service changes."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('dsh_install.sh')
NAMES = ['@deepseek-ai/dsh-subagent-codex', 'ds-bot', 'dsh-web-mobile', 'dshmarket', 'dsh-ide-git']


class InstallPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        bins = self.root / 'bin'
        bins.mkdir()
        for name in ['dsh', 'pnpm', 'magpie']:
            command = bins / name
            command.write_text('#!/bin/sh\necho 0.2.1-rc.2\n')
            command.chmod(0o755)
        self.config = self.root / 'dsh.conf'
        self.config.write_text('server_ip=127.0.0.1\n')
        self.profile = self.root / 'data/profiles/web'
        self.profile.mkdir(parents=True)
        (self.profile / 'package.json').write_text(json.dumps({'dependencies': {n: '0.2.1-rc.2' for n in NAMES}}))
        for name in NAMES:
            package = self.profile / 'node_modules' / name / 'package.json'
            package.parent.mkdir(parents=True)
            package.write_text(json.dumps({'name': name, 'version': '0.2.1-rc.2'}))
        self.env = dict(os.environ, HOME=str(self.root), DSH_HOME=str(self.root / 'data'), PATH=f'{bins}:{os.environ["PATH"]}')

    def run_plan(self, *args):
        result = subprocess.run(['bash', str(SCRIPT), '--dry-run', '--config', str(self.config), *args], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'tls').exists())
        return result.stdout

    def test_existing_install_skipped(self):
        output = self.run_plan()
        self.assertNotIn('+ npm install', output)
        self.assertNotIn('+ curl', output)
        self.assertNotIn('+ dsh plugin', output)

    def test_missing_plugin_files_reinstalled(self):
        (self.profile / 'node_modules/ds-bot/package.json').unlink()
        output = self.run_plan()
        command = next(line for line in output.splitlines() if line.startswith('+ dsh plugin'))
        self.assertTrue(command.endswith('ds-bot@latest'), command)
        self.assertNotIn('dshmarket', command)

    def test_codex_version_aligned(self):
        package = self.profile / 'node_modules' / NAMES[0] / 'package.json'
        package.write_text(json.dumps({'name': NAMES[0], 'version': '0.0.1-rc.1'}))
        output = self.run_plan()
        self.assertIn('add -w --save-exact @deepseek-ai/dsh-subagent-codex@0.2.1-rc.2', output)

    def test_upgrade_installs_all(self):
        output = self.run_plan('--upgrade')
        self.assertIn('+ npm install', output)
        self.assertIn('+ curl', output)
        self.assertIn('ds-bot@latest dsh-web-mobile@latest dshmarket@latest dsh-ide-git@latest', output)


if __name__ == '__main__':
    unittest.main()
