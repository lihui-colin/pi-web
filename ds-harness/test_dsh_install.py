"""Installer planning tests: no network, global installs, or service changes."""
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('dsh_install.sh')
NAMES = ['@deepseek-ai/dsh-subagent-codex', 'ds-bot', 'dsh-web-mobile', 'dshmarket', 'dsh-ide-git', 'dsh-sidebar-enhancement', 'dsh-sidebar-plus']


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
        nginx = bins / 'nginx'
        nginx.write_text('#!/bin/sh\necho "nginx version: nginx/1.24.0"\necho "configure arguments: --with-http_ssl_module"\n')
        nginx.chmod(0o755)
        self.config = self.root / 'dsh.conf'
        self.profile = self.root / 'data/profiles/web'
        self.profile.mkdir(parents=True)
        (self.profile / 'package.json').write_text(json.dumps({'dependencies': {n: '0.2.1-rc.2' for n in NAMES}}))
        for name in NAMES:
            package = self.profile / 'node_modules' / name / 'package.json'
            package.parent.mkdir(parents=True)
            package.write_text(json.dumps({'name': name, 'version': '0.2.1-rc.2'}))
        self.env = dict(os.environ, HOME=str(self.root), DSH_HOME=str(self.root / 'data'), PATH=f'{bins}:{os.environ["PATH"]}')

    def run_plan(self, *args):
        result = subprocess.run(['bash', str(SCRIPT), '--dry-run', *args], env=self.env, text=True, capture_output=True)
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
        self.assertIn('dsh-sidebar-enhancement@latest dsh-sidebar-plus@latest', output)
        self.assertNotIn('dsh-file-transfer', output)

    def test_removed_plugin_not_reinstalled(self):
        manifest = self.profile / 'package.json'
        pkg = json.loads(manifest.read_text())
        pkg['dependencies']['dsh-file-transfer'] = 'github:flyhigao/dsh-file-transfer'
        manifest.write_text(json.dumps(pkg))
        output = self.run_plan()
        self.assertNotIn('+ dsh plugin', output)
        self.assertNotIn('dsh-file-transfer', output)


    def test_install_without_config_does_not_create_certificates(self):
        self.assertFalse(self.config.exists())
        result = subprocess.run(['bash', str(SCRIPT)], env=self.env, text=True, capture_output=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.config.exists())
        self.assertFalse((self.root / 'tls').exists())
        self.assertNotIn('openssl', result.stdout)
        self.assertFalse(list(self.root.rglob('*.pem')))
        self.assertFalse(list(self.root.rglob('*.crt')))

    def test_certificate_options_rejected(self):
        for option in ['--cert-only', '--config', '--tls-dir', '--tls-host']:
            with self.subTest(option=option):
                result = subprocess.run(['bash', str(SCRIPT), option], env=self.env, text=True, capture_output=True)
                self.assertEqual(result.returncode, 2)
                self.assertIn('未知参数', result.stderr)


class NginxInstallTests(unittest.TestCase):
    def setUp(self):
        import sys
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bins = self.root / 'bin'
        self.bins.mkdir()
        self.policy = self.root / 'policy-rc.d'
        self.installed = self.root / 'nginx-installed'
        self.env = dict(os.environ, CASE_ROOT=str(self.root), PATH=f'{self.bins}:{os.environ["PATH"]}',
                        TEST_OS='Linux', TEST_DISABLED='', TEST_DRY_RUN='false',
                        TEST_VERSION='1.24.0', TEST_SSL='--with-http_ssl_module')
        def executable(name, body):
            path = self.bins / name
            path.write_text(f'#!{sys.executable}\n' + body)
            path.chmod(0o755)
        # Redirect the privileged script to a temporary policy; never touch /usr/sbin.
        executable('sh', '''import os, sys
assert sys.argv[1:] == ['-s', '--', '/usr/sbin/policy-rc.d']
os.execv('/bin/sh', ['/bin/sh', '-s', '--', os.environ['CASE_ROOT'] + '/policy-rc.d'])
''')
        executable('sudo', '''import os, sys
assert sys.argv[1:] == ['sh', '-s', '--', '/usr/sbin/policy-rc.d']
os.execvp(sys.argv[1], sys.argv[1:])
''')
        package_manager = '''import json, os, subprocess, sys
from pathlib import Path
root = Path(os.environ['CASE_ROOT'])
name = Path(sys.argv[0]).name
with (root / 'packages.jsonl').open('a') as log:
    log.write(json.dumps([name, *sys.argv[1:]]) + '\\n')
if name == 'apt-get':
    assert os.environ['NEEDRESTART_SUSPEND'] == '1'
    assert os.environ['DEBIAN_FRONTEND'] == 'noninteractive'
    for service in ('nginx', 'nginx.service'):
        assert subprocess.call([str(root / 'policy-rc.d'), service, 'start']) == 101
if os.environ.get('TEST_FAIL') == sys.argv[1]:
    sys.exit(41)
if sys.argv[1] == 'install' and not os.environ.get('TEST_NO_BINARY'):
    (root / 'nginx-installed').touch()
'''
        for name in ('apt-get', 'brew'):
            executable(name, package_manager)
        source = SCRIPT.read_text()
        functions = source[source.index('run() {'):source.index('# 保留官方安装器')]
        self.script = '''set -euo pipefail
dry_run="$TEST_DRY_RUN"
''' + functions + '''
uname() { printf '%s\\n' "$TEST_OS"; }
nginx() { printf 'nginx version: nginx/%s\\nconfigure arguments: %s\\n' "$TEST_VERSION" "$TEST_SSL"; }
command() {
    if [[ "$1" == -v ]]; then
        if [[ "$2" == nginx && ! -f "$CASE_ROOT/nginx-installed" ]]; then return 1; fi
        if [[ " $TEST_DISABLED " == *" $2 "* ]]; then return 1; fi
    fi
    builtin command "$@"
}
ensure_nginx
'''

    def run_nginx(self, **overrides):
        result = subprocess.run(['bash', '-c', self.script], env=dict(self.env, **overrides),
                                text=True, capture_output=True, timeout=15)
        calls = self.root / 'packages.jsonl'
        return result, [json.loads(line) for line in calls.read_text().splitlines()] if calls.exists() else []

    def test_apt_installs_missing_nginx_without_starting_services(self):
        result, calls = self.run_nginx()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [['apt-get', 'update'], ['apt-get', 'install', '-y', '--no-install-recommends', 'nginx']])
        self.assertTrue(self.installed.exists())
        self.assertFalse(self.policy.exists())
        self.assertFalse(list(self.root.glob('.dsh-policy-rc.d.*')))

    def test_dry_run_never_invokes_package_manager_or_creates_policy(self):
        result, calls = self.run_nginx(TEST_DRY_RUN='true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('apt-get update', result.stdout)
        self.assertIn('NEEDRESTART_SUSPEND=1', result.stdout)
        self.assertIn('apt-get install -y --no-install-recommends nginx', result.stdout)
        self.assertEqual(calls, [])
        self.assertFalse(self.installed.exists())
        self.assertFalse(self.policy.exists())

    def test_existing_nginx_is_reused_even_with_upgrade(self):
        self.installed.touch()
        result, calls = self.run_nginx(upgrade='true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [])

    def test_existing_policy_is_preserved(self):
        target = self.root / 'admin-policy'
        target.write_text('#!/bin/sh\nexit 101\n')
        target.chmod(0o755)
        self.policy.symlink_to(target)
        result, _ = self.run_nginx()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue(self.policy.is_symlink())
        self.assertEqual(target.read_text(), '#!/bin/sh\nexit 101\n')

    def test_permissive_existing_policy_stops_before_install(self):
        policies = [
            '#!/bin/sh\nexit 0\n',
            '#!/bin/sh\nif [ "$#" -gt 2 ]; then exit 0; fi\nexit 101\n',
            '#!/bin/sh\nif [ "$2" = "(start)" ]; then exit 0; fi\nexit 101\n',
        ]
        for policy in policies:
            with self.subTest(policy=policy):
                self.policy.write_text(policy)
                self.policy.chmod(0o755)
                result, calls = self.run_nginx()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('未禁止 Nginx 启停', result.stderr)
                self.assertEqual(calls, [])
                self.assertEqual(self.policy.read_text(), policy)

    def test_failed_package_operation_cleans_temporary_policy(self):
        for failure in ('update', 'install'):
            with self.subTest(failure=failure):
                result, _ = self.run_nginx(TEST_FAIL=failure)
                self.assertEqual(result.returncode, 41, result.stderr)
                self.assertFalse(self.policy.exists())
                self.assertFalse(list(self.root.glob('.dsh-policy-rc.d.*')))
                self.assertFalse(self.installed.exists())

    def test_existing_incompatible_nginx_is_not_upgraded(self):
        self.installed.touch()
        for version, flags, error in [('1.22.1', '--with-http_ssl_module', '需要 Nginx >=1.24'),
                                      ('1.24.0', '', '缺少 HTTP SSL 模块'),
                                      ('unknown', '--with-http_ssl_module', '无法识别 Nginx 版本')]:
            with self.subTest(version=version, flags=flags):
                result, calls = self.run_nginx(TEST_VERSION=version, TEST_SSL=flags)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(error, result.stderr)
                self.assertEqual(calls, [])

    def test_post_install_result_is_checked(self):
        result, _ = self.run_nginx(TEST_NO_BINARY='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('仍找不到 nginx', result.stderr)
        self.assertFalse(self.policy.exists())

    def test_homebrew_install_and_preview(self):
        result, calls = self.run_nginx(TEST_OS='Darwin', TEST_DRY_RUN='true')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('brew install nginx', result.stdout)
        self.assertEqual(calls, [])
        result, calls = self.run_nginx(TEST_OS='Darwin')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls, [['brew', 'install', 'nginx']])
        self.assertFalse(self.policy.exists())

    def test_missing_package_manager_or_unsupported_platform(self):
        for system, disabled in [('Linux', 'apt-get'), ('Darwin', 'brew'), ('Other', '')]:
            with self.subTest(system=system):
                result, calls = self.run_nginx(TEST_OS=system, TEST_DISABLED=disabled)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, [])


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
