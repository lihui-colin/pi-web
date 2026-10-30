"""Isolated installer tests: no network, real builds, or service changes."""
import hashlib
import io
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).resolve().with_name('dsh_install.sh')
NGINX_SCRIPT = SCRIPT.with_name('dsh_nginx_install.sh')
NAMES = ['@deepseek-ai/dsh-subagent-codex', 'ds-bot', 'dsh-web-mobile', 'dshmarket', 'dsh-ide-git', 'dsh-sidebar-enhancement', 'dsh-sidebar-plus']


NGINX_STUB = f'''#!{sys.executable}
import os, sys
assert sys.argv[1:] == ['-V'], sys.argv
print('nginx version: nginx/' + os.environ.get('TEST_NGINX_VERSION', '1.24.0'), file=sys.stderr)
print('configure arguments: ' + os.environ.get('TEST_NGINX_SSL', '--with-http_ssl_module'), file=sys.stderr)
sys.exit(int(os.environ.get('TEST_NGINX_EXIT', '0')))
'''


def copy_installers(root):
    project = root / 'project'
    project.mkdir()
    for source in (SCRIPT, NGINX_SCRIPT):
        shutil.copy2(source, project / source.name)
    return project


def write_executable(path, content):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)
    path.chmod(0o755)


class InstallPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.project = copy_installers(self.root)
        self.script = self.project / SCRIPT.name
        bins = self.root / 'bin'
        bins.mkdir()
        for name in ['dsh', 'pnpm', 'magpie']:
            command = bins / name
            command.write_text('#!/bin/sh\necho 0.2.1-rc.2\n')
            command.chmod(0o755)
        write_executable(self.project / 'data/.local/nginx/sbin/nginx', NGINX_STUB)
        for name in ('nginx', 'npm', 'curl', 'sudo', 'apt-get', 'brew', 'systemctl', 'service'):
            write_executable(bins / name, '#!/bin/sh\necho "unexpected command: $0" >&2\nexit 97\n')
        self.config = self.project / 'data/dsh.conf'
        self.profile = self.project / 'data/.dsh/profiles/web'
        self.profile.mkdir(parents=True)
        (self.profile / 'package.json').write_text(json.dumps({'dependencies': {n: '0.2.1-rc.2' for n in NAMES}}))
        for name in NAMES:
            package = self.profile / 'node_modules' / name / 'package.json'
            package.parent.mkdir(parents=True)
            package.write_text(json.dumps({'name': name, 'version': '0.2.1-rc.2'}))
        self.env = dict(os.environ, HOME=str(self.root), DSH_HOME=str(self.root / 'data'), PATH=f'{bins}:{os.environ["PATH"]}')

    def run_plan(self, *args):
        result = subprocess.run(['bash', str(self.script), '--dry-run', *args], cwd=self.root, env=self.env, text=True, capture_output=True, timeout=15)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse((self.root / 'tls').exists())
        return result.stdout

    def test_existing_install_skipped(self):
        output = self.run_plan()
        self.assertIn('目标数据目录：' + str(self.project / 'data/.dsh'), output)
        self.assertFalse((self.root / 'data').exists())
        self.assertIn('复用项目 Nginx：' + str(self.project / 'data/.local/nginx/sbin/nginx'), output)
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
        self.assertIn('复用项目 Nginx：', output)
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


    def install(self, answers=''):
        return subprocess.run(['bash', str(self.script)], cwd=self.root, env=self.env,
                              input=answers, text=True, capture_output=True, timeout=15)

    def test_install_creates_config_without_certificates(self):
        result = self.install('10.30.0.25\n25228\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_text(), "server_ip='10.30.0.25'\nport=25228\ndsh_token=''\n")
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertFalse(list(self.root.rglob('*.pem')))
        self.assertFalse(list(self.root.rglob('*.crt')))

    def test_first_input_accepts_surrounding_whitespace_and_crlf(self):
        result = self.install(' \t10.30.0.25 \t\r\n \t12345 \t\r\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_text(), "server_ip='10.30.0.25'\nport=12345\ndsh_token=''\n")
        self.assertNotIn('格式无效', result.stderr)
        self.assertNotIn('端口必须', result.stderr)

    def test_leading_blank_lines_do_not_report_invalid_ip(self):
        result = self.install('\n \t\r\n127.0.0.1\n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("server_ip='127.0.0.1'\nport=25228\n", self.config.read_text())
        self.assertNotIn('格式无效', result.stderr)

    def test_invalid_answers_are_retried_and_ipv6_default_port_supported(self):
        result = self.install('https://host\n::1\n0\n65536\nabc\n\n')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("server_ip='::1'\nport=25228\n", self.config.read_text())
        self.assertIn('IP 格式无效', result.stderr)
        self.assertEqual(result.stderr.count('端口必须'), 3)

    def test_existing_config_is_preserved_without_input(self):
        original = "server_ip=127.0.0.1\nport=12345\ndsh_token='keep'\n"
        self.config.write_text(original)
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_text(), original)
        self.assertNotIn('请输入', result.stderr)

    def test_legacy_config_is_copied_without_overwrite_or_input(self):
        legacy = self.project / 'dsh.conf'
        original = "server_ip=127.0.0.1\nport=12345\n"
        legacy.write_text(original)
        result = self.install()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.config.read_text(), original)
        self.assertEqual(legacy.read_text(), original)
        self.assertEqual(self.config.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('请输入', result.stderr)

    def test_missing_input_does_not_create_partial_config(self):
        for answers in ('', '127.0.0.1\n'):
            with self.subTest(answers=answers):
                result = self.install(answers)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(self.config.exists())

    def test_dry_run_never_prompts_or_creates_config(self):
        output = self.run_plan()
        self.assertFalse(self.config.exists())
        self.assertIn('不在预览时读取输入', output)

    def test_certificate_options_rejected(self):
        for option in ['--cert-only', '--config', '--tls-dir', '--tls-host']:
            with self.subTest(option=option):
                result = subprocess.run(['bash', str(self.script), option], cwd=self.root, env=self.env, text=True, capture_output=True, timeout=15)
                self.assertEqual(result.returncode, 2)
                self.assertIn('未知参数', result.stderr)


class NginxInstallTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.project = copy_installers(self.root)
        self.script = self.project / NGINX_SCRIPT.name
        self.local = self.project / 'data/.local'
        self.prefix = self.local / 'nginx'
        self.bins = self.root / 'bin'
        self.bins.mkdir()
        self.archives = self.root / 'archives'
        self.archives.mkdir()
        self.env = dict(os.environ, HOME=str(self.root), TMPDIR=str(self.root),
                        CASE_ROOT=str(self.root), PATH=str(self.bins),
                        PYTHONDONTWRITEBYTECODE='1', DSH_NGINX_BUILD_JOBS='4',
                        TEST_DOWNLOAD='', TEST_FAIL_PHASE='', TEST_CONCURRENT='',
                        TEST_NO_BINARY='', TEST_NGINX_VERSION='1.99.0',
                        TEST_NGINX_SSL='--with-http_ssl_module', TEST_NGINX_EXIT='0')
        for name in ('BASH_ENV', 'ENV'):
            self.env.pop(name, None)
        # Only these real tools are reachable; tar, SHA verification and rename stay real.
        for name in ('bash', 'sh', 'dirname', 'mkdir', 'mktemp', 'mv', 'rm', 'rmdir', 'cp', 'tar', 'gzip'):
            executable = shutil.which(name)
            self.assertIsNotNone(executable, f'missing test prerequisite: {name}')
            (self.bins / name).symlink_to(executable)
        (self.bins / 'python3').symlink_to(sys.executable)
        forbidden = r'''import json, os, sys
from pathlib import Path
root = Path(os.environ['CASE_ROOT'])
with (root / 'calls.jsonl').open('a') as log:
    log.write(json.dumps({'command': Path(sys.argv[0]).name, 'args': sys.argv[1:]}) + '\n')
sys.exit('unexpected external command: ' + sys.argv[0])
'''
        for name in ('nginx', 'cc', 'perl', 'sudo', 'apt-get', 'brew', 'systemctl', 'service'):
            self.fake_command(name, forbidden)
        self.fake_command('curl', r'''import json, os, shutil, sys
from pathlib import Path
from urllib.parse import urlparse
root = Path(os.environ['CASE_ROOT'])
args = sys.argv[1:]
with (root / 'calls.jsonl').open('a') as log:
    log.write(json.dumps({'command': 'curl', 'args': args}) + '\n')
assert args[-2] == '-o', args
archive = root / 'archives' / Path(urlparse(args[-3]).path).name
assert archive.is_file(), archive
output = Path(args[-1])
assert output.parent.resolve().is_relative_to(root / 'project/data/.local'), output
if os.environ['TEST_DOWNLOAD'] == 'fail':
    output.write_bytes(b'incomplete download')
    sys.exit(22)
if os.environ['TEST_DOWNLOAD'] == 'corrupt':
    output.write_bytes(b'not the pinned archive')
else:
    shutil.copyfile(archive, output)
''')
        self.fake_command('make', r'''import json, os, shutil, sys
from pathlib import Path
root = Path(os.environ['CASE_ROOT'])
args = sys.argv[1:]
prefix = Path('.fixture-prefix').read_text()
assert Path(prefix) == root / 'project/data/.local/nginx', prefix
assert not Path(prefix).exists(), 'published before staging completed'
def record(event):
    with (root / 'calls.jsonl').open('a') as log:
        log.write(json.dumps(event) + '\n')
record({'command': 'make', 'args': args})
if args[0] != 'install':
    assert len(args) == 2 and args[0] == '-j' and int(args[1]) > 0, args
    if os.environ['TEST_FAIL_PHASE'] == 'build':
        Path('partial-object').write_text('partial compilation')
        sys.exit(42)
    sys.exit(0)
assert len(args) == 2 and args[1].startswith('DESTDIR='), args
destdir = Path(args[1].split('=', 1)[1])
assert destdir.parent == Path.cwd().parent, destdir
staged = destdir / prefix.lstrip('/')
(staged / 'sbin').mkdir(parents=True)
if not os.environ['TEST_NO_BINARY']:
    shutil.copy2(root / 'nginx-fixture', staged / 'sbin/nginx')
if os.environ['TEST_FAIL_PHASE'] == 'install':
    sys.exit(43)
(staged / 'conf').mkdir()
(staged / 'conf/nginx.conf').write_text('fixture configuration\n')
(staged / 'html').mkdir()
(staged / 'html/index.html').write_text('fixture welcome page\n')
(staged / 'logs').mkdir()
(staged / 'logs/error.log').write_text('fixture log\n')
record({'command': 'stage', 'path': str(staged), 'inode': staged.stat().st_ino,
        'device': staged.stat().st_dev})
if os.environ['TEST_CONCURRENT']:
    Path(prefix).mkdir()
    (Path(prefix) / 'other-installer').write_text('keep this installation')
''')
        write_executable(self.root / 'nginx-fixture', NGINX_STUB)
        configure = f'#!{sys.executable}\n' + r'''import json, os, sys
from pathlib import Path
root = Path(os.environ['CASE_ROOT'])
args = sys.argv[1:]
with (root / 'calls.jsonl').open('a') as log:
    log.write(json.dumps({'command': 'configure', 'args': args}) + '\n')
options = dict(arg.split('=', 1) for arg in args if '=' in arg)
prefix = Path(options['--prefix'])
assert prefix == root / 'project/data/.local/nginx', prefix
assert not prefix.exists(), 'published before configure'
assert '--with-http_ssl_module' in args, args
assert '--without-http_auth_basic_module' in args, args
assert options['--with-openssl-opt'] == 'no-tests no-module', args
for option, license_file in (('--with-openssl', 'LICENSE.txt'),
                             ('--with-pcre', 'LICENCE.md'), ('--with-zlib', 'LICENSE')):
    dependency = Path(options[option])
    assert dependency.parent == Path.cwd().parent, dependency
    assert (dependency / license_file).is_file(), dependency
if os.environ['TEST_FAIL_PHASE'] == 'configure':
    sys.exit(41)
Path('.fixture-prefix').write_text(str(prefix))
'''
        source = self.script.read_text()
        pins = re.findall(r"^    '([^|']+)\|([^|']+)\|([0-9a-f]{64})'$", source, re.M)
        self.assertEqual(len(pins), 4, 'expected four pinned source archives')
        versions = {'nginx': '1.99.0', 'openssl': '9.8.7', 'pcre2': '99.88', 'zlib': '9.8.7'}
        license_names = {'nginx': 'LICENSE', 'openssl': 'LICENSE.txt', 'pcre2': 'LICENCE.md', 'zlib': 'LICENSE'}
        self.sources = []
        self.licenses = {}
        for old_name, old_url, old_digest in pins:
            kind, old_version = old_name.split('-', 1)
            version = versions[kind]
            name = f'{kind}-{version}'
            url = old_url.replace(old_version, version)
            self.licenses[kind] = f'{kind} fixture license\n'.encode()
            files = {license_names[kind]: self.licenses[kind]}
            if kind == 'nginx':
                files['configure'] = configure.encode()
            archive = self.archives / f'{name}.tar.gz'
            with tarfile.open(archive, 'w:gz') as tar:
                for filename, content in files.items():
                    member = tarfile.TarInfo(f'{name}/{filename}')
                    member.size = len(content)
                    member.mode = 0o755 if filename == 'configure' else 0o644
                    tar.addfile(member, io.BytesIO(content))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            # Rewrite only the temporary copy; keep its extraction and publication code intact.
            source = source.replace(old_version, version).replace(old_digest, digest)
            self.sources.append(f'{name}|{url}|{digest}')
        self.assertEqual({line.split('-', 1)[0] for line in self.sources}, set(versions))
        self.script.write_text(source)

    def fake_command(self, name, body):
        write_executable(self.bins / name, f'#!{sys.executable}\n' + body)

    def calls(self, command=None):
        log = self.root / 'calls.jsonl'
        calls = [json.loads(line) for line in log.read_text().splitlines()] if log.exists() else []
        return [call for call in calls if call['command'] == command] if command else calls

    def snapshot(self, root=None):
        root = self.root if root is None else root
        result = {}
        for path in root.rglob('*'):
            stat = path.lstat()
            data = os.readlink(path) if path.is_symlink() else path.read_bytes() if path.is_file() else None
            result[str(path.relative_to(root))] = (stat.st_mode, stat.st_mtime_ns, data)
        return result

    def run_nginx(self, *args, **overrides):
        self.assertTrue(self.script.resolve().is_relative_to(self.root))
        result = subprocess.run([str(self.bins / 'bash'), str(self.script), *args],
                                cwd=self.root, env=dict(self.env, **overrides),
                                text=True, capture_output=True, timeout=15)
        self.assertEqual(list(self.local.glob('.nginx-build.*')), [], 'private build directory leaked')
        return result

    def assert_not_published(self, result):
        self.assertNotEqual(result.returncode, 0, result.stdout)
        self.assertFalse(self.prefix.exists(), 'failed installation was published')
        self.assertFalse(self.prefix.is_symlink())

    def assert_complete_install(self):
        self.assertTrue(os.access(self.prefix / 'sbin/nginx', os.X_OK))
        self.assertEqual(sorted(path.name for path in self.prefix.iterdir()), ['licenses', 'sbin'])
        self.assertFalse((self.local / 'downloads').exists())
        for name, content in self.licenses.items():
            self.assertEqual((self.prefix / 'licenses' / name).read_bytes(), content)
        stage, = self.calls('stage')
        self.assertEqual((self.prefix.stat().st_dev, self.prefix.stat().st_ino),
                         (stage['device'], stage['inode']), 'installation was not renamed from staging')
        self.assertFalse(Path(stage['path']).exists())

    def test_dry_run_has_zero_writes_and_ignores_path_nginx(self):
        before = self.snapshot()
        result = self.run_nginx('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('将从官方源码构建 Nginx 1.99.0', result.stdout)
        self.assertIn(str(self.prefix), result.stdout)
        self.assertFalse(self.local.exists())
        self.assertEqual(self.calls(), [])
        self.assertEqual(self.snapshot(), before)

    def test_existing_local_nginx_is_reused_without_changes(self):
        write_executable(self.prefix / 'sbin/nginx', NGINX_STUB)
        before = self.snapshot()
        for args in ((), ('--dry-run',)):
            with self.subTest(args=args):
                result = self.run_nginx(*args)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn('复用项目 Nginx：' + str(self.prefix / 'sbin/nginx'), result.stdout)
                self.assertEqual(self.calls(), [])
                self.assertEqual(self.snapshot(), before)

    def seed_existing_install(self):
        write_executable(self.prefix / 'sbin/nginx', NGINX_STUB)
        (self.prefix / 'licenses').mkdir()
        for name, content in self.licenses.items():
            (self.prefix / 'licenses' / name).write_bytes(content)
        for name in ('conf', 'html', 'logs'):
            (self.prefix / name).mkdir()
            (self.prefix / name / 'default-file').write_text('default installer output')
        (self.prefix / 'sources.txt').write_text('\n'.join(self.sources) + '\n')
        cache = self.local / 'downloads'
        cache.mkdir()
        for archive in self.archives.iterdir():
            shutil.copy2(archive, cache / archive.name)
            for suffix in ('.asc', '.sha256'):
                (cache / (archive.name + suffix)).write_text('fixture source verification')
        for name in ('arut.key', 'pluknet.key'):
            (cache / name).write_text('fixture signing key')
        return cache

    def test_existing_install_prunes_known_outputs_and_keeps_unknown_files(self):
        cache = self.seed_existing_install()
        (self.prefix / 'custom').mkdir()
        (self.prefix / 'custom/keep.txt').write_text('custom installation data')
        (self.local / 'keep.txt').write_text('other local data')
        (cache / 'unrelated.tar.gz').write_text('other download')
        binary = (self.prefix / 'sbin/nginx').read_bytes()
        result = self.run_nginx()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('复用项目 Nginx：', result.stdout)
        self.assertEqual(sorted(path.name for path in self.prefix.iterdir()), ['custom', 'licenses', 'sbin'])
        self.assertEqual((self.prefix / 'sbin/nginx').read_bytes(), binary)
        for name, content in self.licenses.items():
            self.assertEqual((self.prefix / 'licenses' / name).read_bytes(), content)
        self.assertEqual((self.prefix / 'custom/keep.txt').read_text(), 'custom installation data')
        self.assertEqual((self.local / 'keep.txt').read_text(), 'other local data')
        self.assertEqual([path.name for path in cache.iterdir()], ['unrelated.tar.gz'])
        self.assertEqual((cache / 'unrelated.tar.gz').read_text(), 'other download')
        self.assertEqual(self.calls(), [])

    def test_existing_install_dry_run_preserves_outputs_and_cache(self):
        self.seed_existing_install()
        before = self.snapshot()
        result = self.run_nginx('--dry-run')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('将清理默认 conf/html/logs', result.stdout)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls(), [])

    def test_cleanup_unlinks_outputs_without_following_external_symlinks(self):
        write_executable(self.prefix / 'sbin/nginx', NGINX_STUB)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'keep.txt').write_text('outside installation')
        before = self.snapshot(outside)
        for name in ('conf', 'html'):
            (self.prefix / name).symlink_to(outside)
        (self.prefix / 'logs').mkdir()
        (self.prefix / 'logs/external').symlink_to(outside)
        (self.prefix / 'sources.txt').symlink_to(outside / 'keep.txt')
        cache = self.local / 'downloads'
        cache.mkdir()
        archive = self.sources[0].split('|', 1)[0] + '.tar.gz'
        for name in (archive, archive + '.asc', archive + '.sha256', 'arut.key', 'pluknet.key'):
            (cache / name).symlink_to(outside / 'keep.txt')
        result = self.run_nginx()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.snapshot(outside), before)
        self.assertEqual([path.name for path in self.prefix.iterdir()], ['sbin'])
        self.assertFalse(cache.exists())
        self.assertEqual(self.calls(), [])

    def test_existing_install_unlinks_download_directory_symlink(self):
        write_executable(self.prefix / 'sbin/nginx', NGINX_STUB)
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'arut.key').write_text('external key')
        (outside / 'keep.txt').write_text('external data')
        before = self.snapshot(outside)
        cache = self.local / 'downloads'
        cache.symlink_to(outside)
        result = self.run_nginx()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(cache.exists())
        self.assertFalse(cache.is_symlink())
        self.assertEqual(self.snapshot(outside), before)
        self.assertEqual(self.calls(), [])

    def test_new_install_rejects_download_directory_symlink_before_writes(self):
        outside = self.root / 'outside'
        outside.mkdir()
        (outside / 'keep.txt').write_text('external data')
        self.local.mkdir(parents=True)
        (self.local / 'downloads').symlink_to(outside)
        before = self.snapshot()
        result = self.run_nginx()
        self.assert_not_published(result)
        self.assertIn('下载缓存目录不能是符号链接', result.stderr)
        self.assertEqual(self.snapshot(), before)
        self.assertEqual(self.calls(), [])

    def test_existing_incompatible_nginx_is_preserved(self):
        self.seed_existing_install()
        before = self.snapshot()
        cases = [({'TEST_NGINX_VERSION': '1.22.1'}, '需要 Nginx >=1.24'),
                 ({'TEST_NGINX_SSL': ''}, '缺少 HTTP SSL 模块'),
                 ({'TEST_NGINX_VERSION': 'unknown'}, '无法识别本地 Nginx 版本'),
                 ({'TEST_NGINX_EXIT': '7'}, 'nginx version:')]
        for overrides, message in cases:
            with self.subTest(overrides=overrides):
                result = self.run_nginx(**overrides)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn(message, result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertEqual(self.snapshot(), before)

    def test_external_symlinks_are_rejected_without_changes(self):
        outside = self.root / 'outside'
        write_executable(outside / 'nginx/sbin/nginx', NGINX_STUB)
        write_executable(self.root / 'outside-data/.local/nginx/sbin/nginx', NGINX_STUB)
        links = [(self.project / 'data', self.root / 'outside-data'),
                 (self.local, outside),
                 (self.prefix, outside / 'nginx'),
                 (self.prefix / 'sbin', outside / 'nginx/sbin'),
                 (self.prefix / 'sbin/nginx', outside / 'nginx/sbin/nginx')]
        for link, target in links:
            with self.subTest(link=str(link.relative_to(self.project))):
                link.parent.mkdir(parents=True, exist_ok=True)
                self.assertTrue(link.parent.resolve().is_relative_to(self.project))
                link.symlink_to(target)
                try:
                    before = self.snapshot()
                    result = self.run_nginx()
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn('符号链接', result.stderr)
                    self.assertEqual(self.calls(), [])
                    self.assertEqual(self.snapshot(), before)
                finally:
                    # The path itself is a fixture link beneath this temporary project.
                    self.assertTrue(link.absolute().is_relative_to(self.project))
                    link.unlink()

    def test_incomplete_local_directory_is_preserved(self):
        (self.prefix / 'sbin').mkdir(parents=True)
        marker = self.prefix / 'unfinished'
        marker.write_text('leave existing files alone')
        for has_binary in (False, True):
            with self.subTest(non_executable_file=has_binary):
                if has_binary:
                    (self.prefix / 'sbin/nginx').write_text(NGINX_STUB)
                before = self.snapshot()
                result = self.run_nginx()
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('目录不完整', result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertEqual(self.snapshot(), before)

    def test_download_failure_does_not_cache_partial_archive_or_publish(self):
        result = self.run_nginx(TEST_DOWNLOAD='fail')
        self.assertEqual(result.returncode, 22, result.stderr)
        self.assert_not_published(result)
        self.assertEqual(len(self.calls('curl')), 1)
        self.assertEqual(list((self.local / 'downloads').iterdir()), [])
        self.assertEqual(self.calls('configure'), [])

    def test_downloaded_checksum_mismatch_stops_before_build(self):
        result = self.run_nginx(TEST_DOWNLOAD='corrupt')
        self.assert_not_published(result)
        self.assertIn('SHA-256 校验失败', result.stderr)
        self.assertEqual(len(self.calls('curl')), 1)
        self.assertEqual(self.calls('configure'), [])
        self.assertEqual(self.calls('make'), [])

    def test_cached_checksum_mismatch_is_rejected_without_downloading(self):
        cache = self.local / 'downloads'
        cache.mkdir(parents=True)
        archive = cache / (self.sources[0].split('|', 1)[0] + '.tar.gz')
        archive.write_bytes(b'corrupt cached source')
        result = self.run_nginx()
        self.assert_not_published(result)
        self.assertIn('SHA-256 校验失败', result.stderr)
        self.assertEqual(self.calls(), [])
        self.assertEqual(archive.read_bytes(), b'corrupt cached source')

    def test_valid_cached_sources_are_reused(self):
        cache = self.local / 'downloads'
        cache.mkdir(parents=True)
        for archive in self.archives.iterdir():
            shutil.copy2(archive, cache / archive.name)
        result = self.run_nginx()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(self.calls('curl'), [])
        self.assertEqual(self.calls('make')[0]['args'], ['-j', '4'])
        self.assert_complete_install()

    def test_configure_build_and_install_failures_never_publish(self):
        for phase, status in (('configure', 41), ('build', 42), ('install', 43)):
            with self.subTest(phase=phase):
                result = self.run_nginx(TEST_FAIL_PHASE=phase)
                self.assertEqual(result.returncode, status, result.stderr)
                self.assert_not_published(result)
                self.assertEqual(len(list((self.local / 'downloads').glob('*.tar.gz'))), 4)

    def test_staged_binary_is_validated_before_publication(self):
        for overrides in ({'TEST_NO_BINARY': '1'}, {'TEST_NGINX_VERSION': '1.22.1'},
                          {'TEST_NGINX_SSL': ''}, {'TEST_NGINX_EXIT': '7'}):
            with self.subTest(overrides=overrides):
                result = self.run_nginx(**overrides)
                self.assert_not_published(result)
                self.assertNotIn('Nginx 已安装：', result.stdout)

    def test_success_publishes_complete_install_atomically_and_cleans_build(self):
        result = self.run_nginx(DSH_NGINX_BUILD_JOBS='2')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('Nginx 已安装：' + str(self.prefix / 'sbin/nginx'), result.stdout)
        self.assert_complete_install()
        self.assertEqual([call['command'] for call in self.calls()],
                         ['curl'] * 4 + ['configure', 'make', 'make', 'stage'])
        self.assertEqual(self.calls('make')[0]['args'], ['-j', '2'])

    def test_concurrent_installation_is_preserved(self):
        result = self.run_nginx(TEST_CONCURRENT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('安装目录已由另一进程创建', result.stderr)
        self.assertEqual([path.name for path in self.prefix.iterdir()], ['other-installer'])
        self.assertEqual((self.prefix / 'other-installer').read_text(), 'keep this installation')
        self.assertNotIn('Nginx 已安装：', result.stdout)

    def test_invalid_build_jobs_are_rejected_before_writes(self):
        before = self.snapshot()
        for jobs in ('0', '-1', 'abc', '1 2'):
            with self.subTest(jobs=jobs):
                result = self.run_nginx(DSH_NGINX_BUILD_JOBS=jobs)
                self.assertEqual(result.returncode, 2, result.stderr)
                self.assertIn('必须是正整数', result.stderr)
                self.assertEqual(self.calls(), [])
                self.assertEqual(self.snapshot(), before)


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
                                    cwd=root, env=env, text=True, capture_output=True, timeout=15)
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
