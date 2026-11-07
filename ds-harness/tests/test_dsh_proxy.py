from test_support import source_file, fixture_file
import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest

SCRIPT = source_file("dsh_proxy.sh")


class ProxyClearTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.conf = self.root / "dsh.conf"
        self.proxy = self.root / "proxy.env"
        self.providers = self.root / "providers.json"
        self.settings = self.root / "settings.json"
        self.conf.write_text("port=25228\noutbound_proxy='http://old:7890'\nno_proxy='localhost'\n")
        self.proxy.write_text("HTTP_PROXY='http://old:7890'\n")
        self.original_providers = {"providers": [
            {"id": "codex", "proxy": "http://old:7890", "model": "keep"},
            {"id": "other", "proxy": "http://other:7890", "enabled": True},
        ], "extra": "keep"}
        self.providers.write_text(json.dumps(self.original_providers))
        self.settings.write_text(json.dumps({"proxy": "http://old:7890", "theme": "dark"}))
        self.env = dict(os.environ, DSH_CONF_FILE=str(self.conf),
                        DSH_PROXY_ENV_FILE=str(self.proxy),
                        MAGPIE_PROVIDERS_FILE=str(self.providers))

    def clear(self, *args):
        return subprocess.run(["bash", str(SCRIPT), "clear", *args],
                              env=self.env, capture_output=True, text=True)

    def test_clear_all_and_repeat_preserves_unrelated_settings(self):
        for _ in range(2):
            result = self.clear()
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertFalse(self.proxy.exists())
            self.assertEqual(self.conf.read_text(), "port=25228\n")
            expected = self.original_providers.copy()
            expected["providers"] = [
                {key: value for key, value in item.items() if key != "proxy"}
                for item in self.original_providers["providers"]]
            self.assertEqual(json.loads(self.providers.read_text()), expected)
            self.assertEqual(json.loads(self.settings.read_text()), {"theme": "dark"})

    def test_set_still_updates_only_codex(self):
        result = subprocess.run(
            ["bash", str(SCRIPT), "set", "http://new:7890"],
            env=self.env, capture_output=True, text=True)
        self.assertEqual(result.returncode, 0, result.stderr)
        providers = json.loads(self.providers.read_text())["providers"]
        self.assertEqual(providers[0]["proxy"], "http://new:7890")
        self.assertEqual(providers[1], self.original_providers["providers"][1])

    def test_env_only_preserves_magpie(self):
        before = [p.read_bytes() for p in (self.providers, self.settings)]
        result = self.clear("--env-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.proxy.exists())
        self.assertEqual(self.conf.read_text(), "port=25228\n")
        self.assertEqual([p.read_bytes() for p in (self.providers, self.settings)], before)

    def test_missing_files_are_not_created(self):
        for path in (self.conf, self.proxy, self.providers, self.settings):
            path.unlink()
        result = self.clear()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_conf_does_not_block_magpie_cleanup(self):
        self.conf.unlink()
        result = self.clear()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn("proxy", json.loads(self.settings.read_text()))

    def test_magpie_symlinks_are_rejected(self):
        for path in (self.providers, self.settings):
            with self.subTest(path=path.name):
                original = path.read_bytes()
                target = self.root / "external.json"
                target.write_bytes(original)
                path.unlink()
                path.symlink_to(target)
                result = self.clear()
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(target.read_bytes(), original)
                path.unlink()
                path.write_bytes(original)


if __name__ == "__main__":
    unittest.main()
