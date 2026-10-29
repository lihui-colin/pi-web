"""Installer planning tests: no network, global installs, or service changes."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('dsh_install.sh')
NAMES = ['@deepseek-ai/dsh-subagent-codex', 'ds-bot', 'dsh-web-mobile', 'dshmarket', 'dsh-ide-git', 'dsh-sidebar-enhancement', 'dsh-sidebar-plus', 'dsh-file-transfer']


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
        self.assertIn('dsh-sidebar-enhancement@latest dsh-sidebar-plus@latest github:flyhigao/dsh-file-transfer', output)
        self.assertNotIn('dsh-file-transfer@latest', output)

    def test_missing_github_plugin_uses_repository_source(self):
        package = self.profile / 'node_modules/dsh-file-transfer/package.json'
        package.unlink()
        output = self.run_plan()
        command = next(line for line in output.splitlines() if line.startswith('+ dsh plugin'))
        self.assertTrue(command.endswith('github:flyhigao/dsh-file-transfer'), command)
        self.assertNotIn('dsh-file-transfer@latest', command)


class CertificateExportTests(unittest.TestCase):
    def test_generate_backfill_and_preview_preserve_certificates(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = root / 'dsh.conf'
            config.write_text('server_ip=127.0.0.1\n')
            command = ['bash', str(SCRIPT), '--cert-only', '--config', str(config)]
            def run(*args):
                result = subprocess.run([*command, *args], text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
            run()
            tls = root / 'tls'
            crt = tls / 'ca.crt'
            original = {p.name: p.read_bytes() for p in tls.iterdir()}
            self.assertEqual(crt.read_bytes(), (tls / 'ca.pem').read_bytes())
            self.assertNotIn(b'PRIVATE KEY', crt.read_bytes())
            crt.unlink()
            run('--dry-run')
            self.assertFalse(crt.exists())
            run()
            self.assertEqual(original, {p.name: p.read_bytes() for p in tls.iterdir()})
            # An existing unrelated certificate must not be overwritten.
            crt.write_bytes((tls / 'fullchain.pem').read_bytes())
            mismatched = crt.read_bytes()
            result = subprocess.run(command, text=True, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn('ca.crt 与 ca.pem 不一致', result.stderr)
            self.assertEqual(crt.read_bytes(), mismatched)


class MagpieRetryTests(unittest.TestCase):
    def run_install(self, download_failures=0, install_failures=0):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            bins = root / 'bin'
            bins.mkdir()
            curl = bins / 'curl'
            curl.write_text("""#!/bin/bash
printf '%s\\n' "$@" >> "$CASE_ROOT/curl-args"
n=0
if [[ -f "$CASE_ROOT/downloads" ]]; then n=$(cat "$CASE_ROOT/downloads"); fi
n=$((n + 1))
echo "$n" > "$CASE_ROOT/downloads"
while [[ "$1" != -o ]]; do shift; done
shift
cat > "$1" <<'INSTALLER'
#!/bin/sh
n=0
if [ -f "$CASE_ROOT/installs" ]; then n=$(cat "$CASE_ROOT/installs"); fi
n=$((n + 1))
echo "$n" > "$CASE_ROOT/installs"
[ "$n" -gt "$INSTALL_FAILURES" ]
INSTALLER
# Even a failed download leaves content: it must never be executed.
[[ "$n" -gt "$DOWNLOAD_FAILURES" ]]
""")
            curl.chmod(0o755)
            sleep = bins / 'sleep'
            sleep.write_text('#!/bin/sh\nexit 0\n')
            sleep.chmod(0o755)
            function = SCRIPT.read_text().split('install_magpie() (', 1)[1].split('\n)\n', 1)[0]
            env = dict(os.environ, CASE_ROOT=str(root), TMPDIR=str(root),
                       PATH=f'{bins}:{os.environ["PATH"]}',
                       DOWNLOAD_FAILURES=str(download_failures), INSTALL_FAILURES=str(install_failures),
                       MAGPIE_PROXY='http://localhost:7890')
            result = subprocess.run(['bash', '-c', 'set -euo pipefail\ninstall_magpie() (' + function + '\n)\ninstall_magpie'],
                                    env=env, text=True, capture_output=True)
            downloads = int((root / 'downloads').read_text())
            installs = int((root / 'installs').read_text()) if (root / 'installs').exists() else 0
            self.assertIn('--proxy\nhttp://localhost:7890\n', (root / 'curl-args').read_text())
            self.assertFalse(list(root.glob('tmp.*')), 'installer temp directory was not cleaned')
            return result, downloads, installs

    def test_internal_download_failure_retried(self):
        result, downloads, installs = self.run_install(install_failures=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((downloads, installs), (2, 2))

    def test_incomplete_installer_not_executed(self):
        result, downloads, installs = self.run_install(download_failures=1)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((downloads, installs), (2, 1))

    def test_persistent_failure_stops(self):
        result, downloads, installs = self.run_install(install_failures=3)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual((downloads, installs), (3, 3))
        self.assertIn('MAGPIE_PROXY', result.stderr)


if __name__ == '__main__':
    unittest.main()
