"""Standalone HTTPS certificate tests using temporary directories only."""
from pathlib import Path
import ssl
import subprocess
import tempfile
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
                                text=True, capture_output=True)
        if success:
            self.assertEqual(result.returncode, 0, result.stderr)
        else:
            self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.config.read_bytes(), original_config)
        return result

    def snapshot(self, directory):
        return {p.name: p.read_bytes() for p in directory.iterdir()}

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
