import unittest
import tempfile
import shutil
from pathlib import Path

from auraseed.provision.config_manager import (
    generate_pip_ini,
    generate_condarc,
    backup_file
)


class TestConfigManager(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.test_dir, ignore_errors=True))

    def test_generate_pip_ini(self):
        cfg = {
            "index_url": "https://artifactory.local/api/pypi/simple",
            "extra_index_urls": ["https://pypi.org/simple"],
            "trusted_hosts": ["artifactory.local"],
            "proxy": "http://proxy.local:8080"
        }
        res = generate_pip_ini(cfg)
        self.assertIn("[global]", res)
        self.assertIn("index-url = https://artifactory.local/api/pypi/simple", res)
        self.assertIn("extra-index-url = https://pypi.org/simple", res)
        self.assertIn("trusted-host = artifactory.local", res)
        self.assertIn("proxy = http://proxy.local:8080", res)

    def test_generate_condarc(self):
        cfg = {
            "channels": ["conda-forge", "defaults"],
            "default_channels": ["https://conda.anaconda.org/conda-forge"],
            "proxy_servers": {
                "http": "http://proxy.local:8080",
                "https": "http://proxy.local:8080"
            },
            "ssl_verify": False
        }
        res = generate_condarc(cfg)
        self.assertIn("channels:", res)
        self.assertIn("  - conda-forge", res)
        self.assertIn("default_channels:", res)
        self.assertIn("proxy_servers:", res)
        self.assertIn("  http: http://proxy.local:8080", res)
        self.assertIn("ssl_verify: false", res)

    def test_backup_file(self):
        dummy_file = Path(self.test_dir) / "dummy.txt"
        dummy_file.write_text("old content", encoding="utf-8")
        backup = backup_file(dummy_file)
        self.assertTrue(backup.exists())
        self.assertIn("dummy.txt.bak_", backup.name)
        self.assertEqual(backup.read_text(encoding="utf-8"), "old content")


if __name__ == "__main__":
    unittest.main()

