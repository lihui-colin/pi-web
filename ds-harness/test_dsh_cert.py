"""Standalone HTTPS certificate tests using temporary directories only."""
from pathlib import Path
import os
import json
import hashlib
import shutil
import signal
import ssl
import subprocess
import sys
import tempfile
import time
import unittest

SCRIPT = Path(__file__).with_name('dsh_cert.sh')


class CertificateTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.config = self.root / 'dsh.conf'
        self.config.write_text("server_ip='127.0.0.1' # test address\n")

    def run_cert(self, *args, success=True):
        original_config = self.config.read_bytes()
        result = subprocess.run(['bash', str(SCRIPT), '--config', str(self.config), *args],
                                text=True, capture_output=True, timeout=90)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_bytes(), original_config)
        return result

    def snapshot(self, directory):
        return {p.name: p.read_bytes() for p in directory.iterdir()}

    def gated_openssl(self):
        """Pause actual OpenSSL generation, so competing processes overlap reliably."""
        bins = self.root / 'bin'
        bins.mkdir()
        wrapper = bins / 'openssl'
        wrapper.write_text(f'''#!{sys.executable}
import os, pathlib, sys, time
root = pathlib.Path({str(self.root)!r})
if sys.argv[1] == 'req' and '-x509' in sys.argv:
    (root / ('entered-' + str(os.getpid()))).write_text(str(os.getppid()))
    deadline = time.monotonic() + 30
    while not (root / 'release').exists():
        if time.monotonic() > deadline:
            sys.exit(94)
        time.sleep(0.02)
    if os.environ.get('FAIL_GENERATION'):
        sys.exit(93)
os.execv({shutil.which('openssl')!r}, ['openssl', *sys.argv[1:]])
''')
        wrapper.chmod(0o755)
        return dict(os.environ, PATH=f'{bins}:{os.environ["PATH"]}')

    def start_cert(self, name, env, *args):
        log = self.root / f'{name}.log'
        stream = log.open('w')
        self.addCleanup(stream.close)
        proc = subprocess.Popen(['bash', str(SCRIPT), '--config', str(self.config), *args],
                                env=env, stdout=stream, stderr=subprocess.STDOUT,
                                start_new_session=True)

        def cleanup():
            if proc.poll() is None:
                os.killpg(proc.pid, signal.SIGKILL)
            proc.wait(timeout=10)

        self.addCleanup(cleanup)
        return proc, log

    def wait_until(self, predicate):
        deadline = time.monotonic() + 15
        while not predicate():
            if time.monotonic() > deadline:
                self.fail('Timed out waiting for certificate subprocess')
            time.sleep(0.02)

    def assert_valid_certificates(self, tls):
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(
            str(tls / 'fullchain.pem'), str(tls / 'privkey.pem'))
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(
            str(tls / 'ca.pem'), str(tls / 'ca-key.pem'))
        self.assertEqual((tls / 'ca.crt').read_bytes(), (tls / 'ca.pem').read_bytes())
        result = subprocess.run(['openssl', 'verify', '-CAfile', str(tls / 'ca.crt'),
                                 str(tls / 'fullchain.pem')],
                                text=True, capture_output=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)

    def publication_fault(self, phase):
        """Instrument Node's fs only in test subprocesses; use real OpenSSL."""
        hook = self.root / 'fault.mjs'
        hook.write_text("""
import fs from 'node:fs';
import path from 'node:path';
const phase = process.env.CERT_TEST_PHASE;
const signal = process.env.CERT_TEST_SIGNAL;
const write = fs.writeFileSync;
function stop(at) {
  if (phase !== at) return;
  write(signal, String(process.pid));
  Atomics.wait(new Int32Array(new SharedArrayBuffer(4)), 0, 0);
}
const rename = fs.renameSync;
fs.renameSync = function(a, b) {
  const result = rename(a, b);
  if (path.basename(b) === '.dsh-cert-pending') stop('commit');
  if (path.basename(a) === '.dsh-cert-pending') stop('retire');
  return result;
};
const link = fs.linkSync;
fs.linkSync = function(a, b) {
  if (phase === 'race' && path.basename(b) === 'privkey.pem') write(b, 'external user key');
  const result = link(a, b);
  stop(path.basename(b));
  return result;
};
const rm = fs.rmSync;
fs.rmSync = function(p, options) {
  if (fs.existsSync(path.join(p, 'manifest.json'))) {
    fs.unlinkSync(path.join(p, 'manifest.json'));
    stop('cleanup');
  }
  return rm(p, options);
};
""")
        marker = self.root / 'fault-ready'
        marker.unlink(missing_ok=True)
        return dict(os.environ, NODE_OPTIONS=f'--import={hook}',
                    CERT_TEST_PHASE=phase, CERT_TEST_SIGNAL=str(marker)), marker

    def test_sigkill_recovery_at_every_publication_boundary(self):
        for phase in ['commit', 'ca-key.pem', 'ca.pem', 'privkey.pem',
                      'fullchain.pem', 'ca.crt', 'retire', 'cleanup']:
            with self.subTest(phase=phase):
                target = self.root / phase
                args = ('--tls-dir', str(target))
                env, marker = self.publication_fault(phase)
                proc, log = self.start_cert('fault-' + phase, env, *args)
                self.wait_until(marker.exists)
                tls = target / '127.0.0.1'
                lock_inode = (tls / '.dsh-cert-lock.sqlite').stat().st_ino
                pending = tls / '.dsh-cert-pending'
                intended = ({p.name: p.read_bytes() for p in pending.iterdir()
                             if p.name != 'manifest.json'} if pending.exists() else {})
                published = {p.name: (p.read_bytes(), p.stat().st_ino)
                             for p in tls.glob('*.pem')}
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
                # Preview must not repair, remove, or even create journal files.
                def tree():
                    return {str(p.relative_to(tls)): (p.stat().st_ino, p.read_bytes())
                            for p in tls.rglob('*') if p.is_file()}
                before = tree()
                self.run_cert(*args, '--dry-run')
                self.assertEqual(tree(), before)
                # Competing retries must use the same stable lock and finish once.
                waiters = [self.start_cert(f'retry-{phase}-{i}', os.environ, *args)
                           for i in range(2)]
                for waiter, output in waiters:
                    self.assertEqual(waiter.wait(timeout=60), 0, output.read_text())
                self.assert_valid_certificates(tls)
                for name, data in intended.items():
                    self.assertEqual((tls / name).read_bytes(), data)
                self.assertFalse((tls / '.dsh-cert-pending').exists())
                self.assertEqual((tls / '.dsh-cert-lock.sqlite').stat().st_ino, lock_inode)
                for name, (data, inode) in published.items():
                    self.assertEqual((tls / name).read_bytes(), data)
                    self.assertEqual((tls / name).stat().st_ino, inode)

    def test_recovery_refuses_changed_or_unknown_files(self):
        for kind in ['unknown', 'same-bytes', 'staged', 'manifest', 'symlink', 'extra']:
            with self.subTest(kind=kind):
                args = ('--tls-dir', str(self.root / kind))
                env, marker = self.publication_fault('ca-key.pem')
                proc, _ = self.start_cert('corrupt-' + kind, env, *args)
                self.wait_until(marker.exists)
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
                tls = self.root / kind / '127.0.0.1'
                pending = tls / '.dsh-cert-pending'
                if kind == 'unknown':
                    (tls / 'privkey.pem').write_text('user private key')
                elif kind == 'same-bytes':
                    key = tls / 'ca-key.pem'
                    data = key.read_bytes()
                    key.unlink()
                    key.write_bytes(data)
                elif kind == 'staged':
                    (pending / 'privkey.pem').write_text('corrupt staged key')
                elif kind == 'manifest':
                    manifest = pending / 'manifest.json'
                    data = json.loads(manifest.read_text())
                    data['files'][0]['name'] = '../escape'
                    manifest.write_text(json.dumps(data))
                elif kind == 'extra':
                    (pending / 'unknown').write_text('keep me')
                else:
                    (tls / 'privkey.pem').symlink_to(self.root / 'missing')
                before = {p.name: p.read_bytes() for p in tls.glob('*.pem') if not p.is_symlink()}
                self.run_cert(*args, success=False)
                self.assertEqual(before, {p.name: p.read_bytes() for p in tls.glob('*.pem') if not p.is_symlink()})
                self.assertTrue(pending.is_dir())
                self.assertFalse((tls / 'ca.pem').exists())

    def certificate_tree(self, tls):
        return {str(p.relative_to(tls)): (p.stat().st_ino, p.stat().st_mode,
                                        p.read_bytes() if p.is_file() else None)
                for p in tls.rglob('*')}

    def assert_recovery_semantic_failure(self, tls, args, message):
        before = self.certificate_tree(tls)
        for flags in [('--dry-run',), ()]:
            result = self.run_cert(*args, *flags, success=False)
            self.assertIn(message, result.stderr)
            after = self.certificate_tree(tls)
            if flags:
                self.assertEqual(after, before)
            else:
                # A real retry rolls back SQLite's crash journal while taking
                # the stable lock; certificate/staging files must stay intact.
                journal = '.dsh-cert-lock.sqlite-journal'
                self.assertEqual({k: v for k, v in after.items() if k != journal},
                                 {k: v for k, v in before.items() if k != journal})
            self.assertTrue((tls / '.dsh-cert-pending').is_dir())

    def test_pending_san_mismatch_fails_before_publication(self):
        for kind in ['new', 'partial', 'reuse', 'export']:
            with self.subTest(kind=kind):
                target = self.root / kind
                args = ('--tls-dir', str(target))
                tls = target / '127.0.0.1'
                if kind in ['reuse', 'export']:
                    self.run_cert(*args)
                    for name in (['fullchain.pem', 'privkey.pem'] if kind == 'reuse'
                                 else ['ca.crt']):
                        (tls / name).unlink()
                env, marker = self.publication_fault('ca.pem' if kind == 'partial' else 'commit')
                proc, _ = self.start_cert('san-' + kind, env, *args)
                self.wait_until(marker.exists)
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
                self.assert_recovery_semantic_failure(
                    tls, (*args, '--tls-host', 'extra.example.test'),
                    '已有证书未覆盖 extra.example.test')
                # The failed attempts must still allow recovery with matching SAN.
                self.run_cert(*args, '--dry-run')
                self.run_cert(*args)
                self.assert_valid_certificates(tls)

    def test_pending_semantics_are_checked_even_with_valid_digests(self):
        other = self.root / 'other'
        self.run_cert('--tls-dir', str(other))
        other_ca = (other / '127.0.0.1/ca.pem').read_bytes()
        for kind, message in [('key', '证书和私钥不匹配'),
                              ('expiry', 'checkend'), ('chain', 'verify'),
                              ('export', 'ca.crt 与 ca.pem 不一致')]:
            with self.subTest(kind=kind):
                target = self.root / kind
                args = ('--tls-dir', str(target))
                env, marker = self.publication_fault('commit')
                proc, _ = self.start_cert('semantic-' + kind, env, *args)
                self.wait_until(marker.exists)
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
                tls = target / '127.0.0.1'
                pending = tls / '.dsh-cert-pending'
                if kind == 'key':
                    (pending / 'privkey.pem').write_bytes((pending / 'ca-key.pem').read_bytes())
                elif kind == 'expiry':
                    expired = subprocess.run(
                        ['openssl', 'x509', '-in', str(pending / 'fullchain.pem'),
                         '-signkey', str(pending / 'privkey.pem'), '-days', '-1'],
                        capture_output=True, check=True, timeout=10).stdout
                    (pending / 'fullchain.pem').write_bytes(expired)
                elif kind == 'chain':
                    (pending / 'ca.pem').write_bytes(other_ca)
                    (pending / 'ca.crt').write_bytes(other_ca)
                else:
                    (pending / 'ca.crt').write_bytes(other_ca)
                # Deliberately keep integrity valid to isolate semantic validation.
                manifest = pending / 'manifest.json'
                data = json.loads(manifest.read_text())
                for entry in data['files']:
                    entry['sha256'] = hashlib.sha256((pending / entry['name']).read_bytes()).hexdigest()
                manifest.write_text(json.dumps(data))
                self.assert_recovery_semantic_failure(tls, args, message)

    def test_unknown_incomplete_files_are_never_adopted(self):
        for name in ['ca-key.pem', 'ca.pem', 'ca.crt', 'privkey.pem', 'fullchain.pem']:
            with self.subTest(name=name):
                root = self.root / name
                tls = root / '127.0.0.1'
                tls.mkdir(parents=True)
                (tls / name).write_text('unknown user file')
                (tls / '.generate-unknown').mkdir()
                (tls / '.generate-unknown/keep').write_text('unknown staging')
                self.run_cert('--tls-dir', str(root), success=False)
                self.assertEqual((tls / name).read_text(), 'unknown user file')
                self.assertEqual((tls / '.generate-unknown/keep').read_text(), 'unknown staging')
                self.assertEqual([p.name for p in tls.glob('*.pem')],
                                 [name] if name.endswith('.pem') else [])

    def test_reused_ca_survives_recovery_and_changed_dependency_is_rejected(self):
        for changed in [False, True]:
            with self.subTest(changed=changed):
                target = self.root / f'reuse-{changed}'
                args = ('--tls-dir', str(target))
                self.run_cert(*args)
                tls = target / '127.0.0.1'
                original = {name: ((tls / name).read_bytes(), (tls / name).stat().st_ino)
                            for name in ['ca.pem', 'ca-key.pem', 'ca.crt']}
                (tls / 'fullchain.pem').unlink()
                (tls / 'privkey.pem').unlink()
                env, marker = self.publication_fault('privkey.pem')
                proc, _ = self.start_cert(f'reuse-{changed}', env, *args)
                self.wait_until(marker.exists)
                os.killpg(proc.pid, signal.SIGKILL)
                proc.wait(timeout=10)
                if changed:
                    (tls / 'ca-key.pem').write_text('replacement user key')
                    self.run_cert(*args, success=False)
                    self.assertEqual((tls / 'ca-key.pem').read_text(), 'replacement user key')
                    self.assertFalse((tls / 'fullchain.pem').exists())
                else:
                    self.run_cert(*args)
                    self.assert_valid_certificates(tls)
                    for name, (data, inode) in original.items():
                        self.assertEqual((tls / name).read_bytes(), data)
                        self.assertEqual((tls / name).stat().st_ino, inode)

    def test_external_file_appearing_during_publication_is_not_skipped(self):
        env, _ = self.publication_fault('race')
        proc, log = self.start_cert('race', env)
        self.assertNotEqual(proc.wait(timeout=60), 0, log.read_text())
        tls = self.root / 'tls/127.0.0.1'
        self.assertEqual((tls / 'privkey.pem').read_text(), 'external user key')
        self.assertFalse((tls / 'fullchain.pem').exists())
        self.assertTrue((tls / '.dsh-cert-pending').is_dir())
        self.run_cert(success=False)
        self.assertEqual((tls / 'privkey.pem').read_text(), 'external user key')

    def test_root_export_is_recoverable(self):
        self.run_cert()
        tls = self.root / 'tls/127.0.0.1'
        original = self.snapshot(tls)
        (tls / 'ca.crt').unlink()
        env, marker = self.publication_fault('ca.crt')
        proc, _ = self.start_cert('export', env)
        self.wait_until(marker.exists)
        os.killpg(proc.pid, signal.SIGKILL)
        proc.wait(timeout=10)
        self.run_cert()
        self.assertEqual(self.snapshot(tls), original)

    def test_concurrent_first_generation_serializes_directory_aliases(self):
        env = self.gated_openssl()
        first = self.start_cert('first', env)
        self.wait_until(lambda: list(self.root.glob('entered-*')))
        tls = self.root / 'tls/127.0.0.1'
        alias = self.root / 'tls-alias'
        alias.symlink_to(tls.parent, target_is_directory=True)
        others = [self.start_cert(f'other-{i}', env, '--tls-dir', str(alias)) for i in range(3)]
        for _, log in others:
            self.wait_until(lambda: 'HTTPS 证书：' in log.read_text())
        time.sleep(0.3)
        self.assertTrue(all(proc.poll() is None for proc, _ in [first, *others]))
        self.assertEqual(len(list(self.root.glob('entered-*'))), 1)
        (self.root / 'release').touch()
        outputs = []
        for proc, log in [first, *others]:
            self.assertEqual(proc.wait(timeout=60), 0, log.read_text())
            outputs.append(log.read_text())
        self.assertEqual(sum('HTTPS 证书已生成' in output for output in outputs), 1)
        self.assertEqual(sum('已有证书有效' in output for output in outputs), 3)
        self.assert_valid_certificates(tls)
        self.assertFalse(list(tls.glob('.generate-*')))
        original = self.snapshot(tls)
        self.run_cert()
        self.assertEqual(original, self.snapshot(tls))
        self.run_cert('--dry-run')
        self.assertEqual(original, self.snapshot(tls))

    def test_generation_failure_releases_lock_for_waiter(self):
        env = self.gated_openssl()
        first, first_log = self.start_cert('failing', dict(env, FAIL_GENERATION='1'))
        self.wait_until(lambda: list(self.root.glob('entered-*')))
        second, second_log = self.start_cert('waiting', env)
        self.wait_until(lambda: 'HTTPS 证书：' in second_log.read_text())
        (self.root / 'release').touch()
        self.assertNotEqual(first.wait(timeout=60), 0, first_log.read_text())
        self.assertEqual(second.wait(timeout=60), 0, second_log.read_text())
        self.assert_valid_certificates(self.root / 'tls/127.0.0.1')
        self.assertFalse(list((self.root / 'tls/127.0.0.1').glob('.generate-*')))

    def test_sigkill_leaves_no_stale_lock(self):
        env = self.gated_openssl()
        first, _ = self.start_cert('killed', env)
        self.wait_until(lambda: list(self.root.glob('entered-*')))
        second, log = self.start_cert('survivor', env)
        self.wait_until(lambda: 'HTTPS 证书：' in log.read_text())
        os.killpg(first.pid, signal.SIGKILL)
        first.wait(timeout=10)
        (self.root / 'release').touch()
        self.assertEqual(second.wait(timeout=60), 0, log.read_text())
        self.assert_valid_certificates(self.root / 'tls/127.0.0.1')

    def test_different_output_directories_do_not_share_lock(self):
        env = self.gated_openssl()
        first, _ = self.start_cert('blocked', env)
        self.wait_until(lambda: list(self.root.glob('entered-*')))
        self.run_cert('--tls-dir', str(self.root / 'independent'))
        self.assertIsNone(first.poll())
        self.assert_valid_certificates(self.root / 'independent/127.0.0.1')
        (self.root / 'release').touch()
        self.assertEqual(first.wait(timeout=60), 0)

    def test_default_config_and_certificates_use_data_directory(self):
        script = self.root / 'dsh_cert.sh'
        script.write_bytes(SCRIPT.read_bytes())
        config = self.root / 'data/dsh.conf'
        config.parent.mkdir()
        config.write_text('server_ip=localhost\n')
        original_config = config.read_bytes()
        default_tls = self.root / 'data/tls/localhost'
        output = self.root / 'exported certificates'
        for args, target in [([], default_tls),
                             (['--config', str(config), '--dry-run'], default_tls),
                             (['--tls-dir', str(output), '--dry-run'], output / 'localhost')]:
            with self.subTest(args=args):
                result = subprocess.run(['bash', str(script), *args], cwd=config.parent,
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertIn(f'DSH 配置：{config}', result.stdout)
                self.assertIn(f'HTTPS 证书：{target / "fullchain.pem"}', result.stdout)
                self.assertIn(str(default_tls), result.stdout)
                self.assertEqual(config.read_bytes(), original_config)
        self.assertTrue((default_tls / 'fullchain.pem').is_file())
        self.assertFalse((self.root / 'data/tls/127.0.0.1').exists())
        self.assertFalse((self.root / 'tls').exists())
        self.assertFalse(output.exists())

    def test_missing_default_config_reports_data_path(self):
        script = self.root / 'dsh_cert.sh'
        script.write_bytes(SCRIPT.read_bytes())
        result = subprocess.run(['bash', str(script), '--dry-run'],
                                text=True, capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn(f'缺少 DSH 配置：{self.root / "data/dsh.conf"}', result.stderr)
        self.assertFalse((self.root / 'data/tls').exists())
        self.assertFalse((self.root / 'tls').exists())

    def test_generate_backfill_and_preview_preserve_certificates(self):
        self.run_cert('--dry-run')
        self.assertFalse((self.root / 'tls').exists())
        self.run_cert('--tls-host', 'localhost')
        tls = self.root / 'tls/127.0.0.1'
        crt = tls / 'ca.crt'
        original = self.snapshot(tls)
        self.assertEqual(crt.read_bytes(), (tls / 'ca.pem').read_bytes())
        self.assertNotIn(b'PRIVATE KEY', crt.read_bytes())
        for name in ['privkey.pem', 'ca-key.pem']:
            self.assertEqual((tls / name).stat().st_mode & 0o777, 0o600)
        self.assertEqual(tls.stat().st_mode & 0o777, 0o700)
        self.assertFalse(list(tls.glob('.generate-*')))
        details = ssl._ssl._test_decode_cert(str(tls / 'fullchain.pem'))
        self.assertIn(('IP Address', '127.0.0.1'), details['subjectAltName'])
        self.assertIn(('DNS', 'localhost'), details['subjectAltName'])
        ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER).load_cert_chain(str(tls / 'fullchain.pem'), str(tls / 'privkey.pem'))
        verify = subprocess.run(['openssl', 'verify', '-CAfile', str(crt), str(tls / 'fullchain.pem')],
                                text=True, capture_output=True)
        self.assertEqual(verify.returncode, 0, verify.stderr)
        crt.unlink()
        self.run_cert('--dry-run')
        self.assertFalse(crt.exists())
        self.run_cert()
        self.assertEqual(original, self.snapshot(tls))
        crt.write_bytes((tls / 'fullchain.pem').read_bytes())
        mismatched = crt.read_bytes()
        result = self.run_cert(success=False)
        self.assertIn('ca.crt 与 ca.pem 不一致', result.stderr)
        self.assertEqual(crt.read_bytes(), mismatched)

    def test_addresses_get_separate_directories_and_legacy_paths_untouched(self):
        legacy = self.root / 'tls'
        legacy.mkdir()
        (legacy / 'fullchain.pem').write_text('legacy certificate')
        (legacy / 'privkey.pem').write_text('legacy key')
        self.config.write_text('server_ip=127.0.0.1\ntls_cert=tls/fullchain.pem\ntls_key=tls/privkey.pem\n')
        self.run_cert()
        first = self.snapshot(legacy / '127.0.0.1')
        self.config.write_text('server_ip=10.30.0.25\ntls_cert=tls/fullchain.pem\ntls_key=tls/privkey.pem\n')
        result = self.run_cert()
        second = legacy / '10.30.0.25'
        self.assertTrue((second / 'ca.crt').is_file())
        self.assertEqual(first, self.snapshot(legacy / '127.0.0.1'))
        self.assertEqual((legacy / 'fullchain.pem').read_text(), 'legacy certificate')
        self.assertEqual((legacy / 'privkey.pem').read_text(), 'legacy key')
        self.assertIn(str(second / 'fullchain.pem'), result.stdout)
        self.assertNotEqual(first['ca.crt'], (second / 'ca.crt').read_bytes())

    def test_custom_root_still_appends_address_and_reports_deployment_path(self):
        output = self.root / "cert root's folder"
        result = self.run_cert('--tls-dir', str(output))
        target = output / '127.0.0.1'
        self.assertTrue((target / 'fullchain.pem').is_file())
        self.assertIn(str(target / 'fullchain.pem'), result.stdout)
        self.assertIn(str(self.root / 'tls/127.0.0.1'), result.stdout)
        self.assertIn('自定义输出目录仅用于导出', result.stdout)
        self.assertNotIn('\ntls_cert=', result.stdout)
        self.assertFalse((self.root / 'tls').exists())

    def test_ipv6_and_dns_directory_names(self):
        self.config.write_text('server_ip=::1\n')
        self.run_cert()
        cert = self.root / 'tls/__1/fullchain.pem'
        self.assertTrue(cert.is_file())
        decoded = ssl._ssl._test_decode_cert(str(cert))
        self.assertTrue(any(kind == 'IP Address' and ':' in value for kind, value in decoded['subjectAltName']))
        self.config.write_text('server_ip=dsh.example.test\n')
        output = self.run_cert('--dry-run').stdout
        self.assertIn(str(self.root / 'tls/dsh.example.test/fullchain.pem'), output)
        self.assertFalse((self.root / 'tls/dsh.example.test').exists())

    def test_invalid_address_and_incomplete_pair_fail_without_overwrite(self):
        self.config.write_text('server_ip=../../outside\n')
        self.run_cert(success=False)
        self.assertFalse((self.root / 'tls').exists())
        self.config.write_text('server_ip=127.0.0.1\n')
        tls = self.root / 'tls/127.0.0.1'
        tls.mkdir(parents=True)
        key = tls / 'privkey.pem'
        key.write_text('existing key')
        self.run_cert(success=False)
        self.assertEqual(key.read_text(), 'existing key')
        self.assertFalse((tls / 'fullchain.pem').exists())


if __name__ == '__main__':
    unittest.main()
