#!/usr/bin/env python3
"""Isolated installer tests: only fake dsh and temporary profiles are modified."""
import json
import os
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent
PLUGINS = [
    '@deepseek-ai/dsh-subagent-codex', 'ds-bot', 'dsh-web-mobile',
    'dshmarket', 'dsh-ide-git', 'dsh-sidebar-enhancement', 'dsh-sidebar-plus',
    '@huanlin/dsh-plugin-input-history', '@xbzbing/dsh-git-panel',
]
VERSION = '0.2.1-rc.2'
FAKE_DSH = r'''import json, os, sys
from pathlib import Path
if sys.argv[1:] == ['--version']:
    print(os.environ.get('FAKE_VERSION', '0.2.1-rc.2'))
    sys.exit(0)
assert sys.argv[1:7] == ['plugin', '--profile', 'web', 'add', '-w', '--save-exact'], sys.argv
with open(os.environ['CALLS'], 'a') as f:
    f.write(json.dumps(sys.argv[1:]) + '\n')
dir = Path(os.environ['DSH_HOME']) / 'profiles/web'
dir.mkdir(parents=True, exist_ok=True)
manifest = dir / 'package.json'
pkg = json.loads(manifest.read_text()) if manifest.exists() else {
    'private': True, 'dsh': {'profile': {'bundles': ['@deepseek-ai/dsh-base', '@deepseek-ai/dsh-web-app']}}}
bundles = pkg.setdefault('dsh', {}).setdefault('profile', {}).setdefault('bundles', [])
for spec in sys.argv[7:]:
    name, version = spec.rsplit('@', 1)
    if version == 'latest': version = '1.2.3'
    pkg.setdefault('dependencies', {})[name] = version
    target = dir / 'node_modules' / name / 'package.json'
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps({'name': name, 'version': version}))
    # Deliberately emulate a manager enabling added plugins, even on partial failure.
    if name not in bundles: bundles.append(name)
manifest.write_text(json.dumps(pkg))
sys.exit(int(os.environ.get('FAKE_FAIL', '0')))
'''


class PluginInstallerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='dsh-plugin-test-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.bin = self.root / 'bin'
        self.bin.mkdir()
        for name in ('bash', 'sh', 'node', 'dirname', 'cp', 'date', 'python3'):
            executable = shutil.which(name)
            self.assertIsNotNone(executable, name)
            (self.bin / name).symlink_to(executable)
        for name in ('dsh_install.sh', 'dsh_plugins_install.sh'):
            shutil.copy2(ROOT / name, self.root / name)
        (self.root / 'patches').mkdir()
        (self.root / 'patches/ds_bot_apply.py').write_text(
            'import os, sys\nprint("PATCH_BUNDLE_APPLIED")\nsys.exit(int(os.environ.get("FAKE_PATCH_FAIL", "0")))\n')
        (self.root / 'dsh_nginx_install.sh').write_text('#!/bin/bash\nexit 0\n')
        self.fake('dsh', '#!' + shutil.which('python3') + '\n' + FAKE_DSH)
        for name in ('npm', 'curl'):
            self.fake(name, '#!/bin/bash\necho unexpected external command >&2\nexit 99\n')
        for name in ('pnpm', 'magpie'):
            self.fake(name, '#!/bin/bash\nexit 0\n')
        self.env = dict(os.environ, PATH=str(self.bin), HOME=str(self.root / 'home'),
                        CALLS=str(self.root / 'calls'))
        for name in ('FAKE_FAIL', 'FAKE_VERSION', 'FAKE_PATCH_FAIL'):
            self.env.pop(name, None)
        self.manifest = self.root / 'data/.dsh/profiles/web/package.json'

    def fake(self, name, content):
        path = self.bin / name
        path.write_text(content)
        path.chmod(0o755)

    def run_script(self, *args, parent=False, status=0):
        script = 'dsh_install.sh' if parent else 'dsh_plugins_install.sh'
        result = subprocess.run([str(self.bin / 'bash'), str(self.root / script), *args],
                                env=self.env, text=True, capture_output=True, timeout=20)
        self.assertEqual(result.returncode, status, result.stdout + result.stderr)
        return result.stdout

    def seed(self, bundles=None, installed=True):
        pkg = {'private': True, 'dependencies': {}, 'dsh': {'profile': {'other': {'keep': True}}}}
        if bundles is not None:
            pkg['dsh']['profile']['bundles'] = bundles
        for name in PLUGINS:
            version = VERSION if name == PLUGINS[0] else '1.0.0'
            pkg['dependencies'][name] = version
            if installed:
                target = self.manifest.parent / 'node_modules' / name / 'package.json'
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(json.dumps({'name': name, 'version': version}))
        self.manifest.parent.mkdir(parents=True, exist_ok=True)
        self.manifest.write_text(json.dumps(pkg))

    def package(self):
        return json.loads(self.manifest.read_text())

    def calls(self):
        path = self.root / 'calls'
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def snapshot(self):
        return {str(p.relative_to(self.root)): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in self.root.rglob('*') if p.is_file()}

    def test_new_profile_installs_nine_enables_eight(self):
        self.assertIn("PATCH_BUNDLE_APPLIED", self.run_script())
        pkg = self.package()
        self.assertEqual(set(pkg['dependencies']), set(PLUGINS))
        self.assertEqual(set(pkg['dsh']['profile']['bundles']) & set(PLUGINS),
                         set(PLUGINS) - {'dsh-ide-git'})
        self.assertIn('@deepseek-ai/dsh-base', pkg['dsh']['profile']['bundles'])
        self.assertEqual(self.calls()[0][6:],
                         [name + '@' + (VERSION if name == PLUGINS[0] else 'latest') for name in PLUGINS])

    def test_installed_is_idempotent_without_writes(self):
        self.seed(['custom', 'dsh-ide-git'])
        before = self.snapshot()
        self.assertIn("PATCH_BUNDLE_APPLIED", self.run_script())
        self.assertEqual(before, self.snapshot())
        self.assertEqual(self.calls(), [])

    def test_upgrade_preserves_enabled_disabled_and_other_config(self):
        bundles = ['@deepseek-ai/dsh-base', 'custom', 'ds-bot', 'dsh-ide-git']
        self.seed(bundles)
        self.assertIn('PATCH_BUNDLE_APPLIED', self.run_script('--upgrade'))
        self.assertEqual(self.package()['dsh']['profile']['bundles'], bundles)
        self.assertEqual(self.package()['dsh']['profile']['other'], {'keep': True})
        self.assertEqual(len(self.calls()[0][6:]), 9)

    def test_existing_profile_without_bundles_keeps_all_disabled(self):
        self.seed()
        self.run_script('--upgrade')
        self.assertNotIn('bundles', self.package()['dsh']['profile'])

    def test_missing_package_and_codex_version_are_repaired(self):
        self.seed(['custom'])
        missing = self.manifest.parent / 'node_modules' / PLUGINS[-1] / 'package.json'
        # Exact isolated test fixture path, never a real profile.
        missing.unlink()
        self.env['FAKE_VERSION'] = '0.2.2'
        self.run_script()
        self.assertEqual(self.calls()[0][6:], [PLUGINS[0] + '@0.2.2', PLUGINS[-1] + '@latest'])
        self.assertEqual(self.package()['dsh']['profile']['bundles'], ['custom'])

    def test_dry_run_no_writes_existing_or_upgrade(self):
        self.seed(['custom'])
        before = self.snapshot()
        self.run_script('--dry-run')
        self.run_script('--dry-run', '--upgrade')
        self.assertEqual(before, self.snapshot())

    def test_dry_run_without_dsh_in_child_and_parent(self):
        (self.bin / 'dsh').unlink()
        before = self.snapshot()
        for parent in (False, True):
            output = self.run_script('--dry-run', parent=parent)
            self.assertIn('安装后的', output)
            self.assertIn('@xbzbing/dsh-git-panel@latest', output)
        self.assertEqual(before, self.snapshot())

    def test_parent_dry_upgrade_uses_future_version(self):
        self.seed(['custom'])
        before = self.snapshot()
        output = self.run_script('--dry-run', '--upgrade', parent=True)
        self.assertIn('安装后的', output)
        self.assertNotIn(PLUGINS[0] + '@' + VERSION, output)
        self.assertEqual(before, self.snapshot())

    def test_failure_propagates_and_restores_bundles(self):
        self.seed(['custom', 'ds-bot'], installed=False)
        self.env['FAKE_FAIL'] = '37'
        self.assertNotIn('PATCH_BUNDLE_APPLIED', self.run_script(status=37))
        self.assertEqual(self.package()['dsh']['profile']['bundles'], ['custom', 'ds-bot'])

    def test_parent_failure_propagates_before_builtin_configuration(self):
        self.seed(['custom'], installed=False)
        self.env['FAKE_FAIL'] = '37'
        self.run_script(parent=True, status=37)
        self.assertEqual(self.package()['dsh']['profile']['bundles'], ['custom'])
        self.assertFalse((self.root / 'data/dsh.conf').exists())

    def test_parent_preserves_builtin_config_and_extra_selection(self):
        self.seed(['custom', '@deepseek-ai/dsh-experimental-auto-review', 'ds-bot'])
        (self.root / 'data/dsh.conf').write_text("server_ip='127.0.0.1'\nport=25228\n")
        self.run_script(parent=True)
        bundles = self.package()['dsh']['profile']['bundles']
        self.assertEqual(set(bundles) & set(PLUGINS), {'ds-bot'})
        self.assertIn('@deepseek-ai/dsh-experimental-auto-review', bundles)
        self.assertIn('@deepseek-ai/dsh-experimental-voice-input-bundle', bundles)
        self.assertEqual(self.package()['dsh']['profile']['other'], {'keep': True})

    def test_patch_failure_aborts_both_installers(self):
        self.seed(['custom'])
        self.env['FAKE_PATCH_FAIL'] = '29'
        for parent in (False, True):
            self.run_script(parent=parent, status=29)
        self.assertFalse((self.root / 'data/dsh.conf').exists())

    def test_invalid_version_and_bad_arguments_do_not_write(self):
        before = self.snapshot()
        self.env['FAKE_VERSION'] = 'invalid'
        self.run_script(status=1)
        self.run_script('--expected-dsh-version', '0.2.3', status=2)
        self.run_script('--expected-dsh-version', status=2)
        self.run_script('--unknown', status=2)
        self.assertEqual(before, self.snapshot())


if __name__ == '__main__':
    unittest.main()
