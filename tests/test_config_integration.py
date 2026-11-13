import tempfile
import os
import unittest
from pathlib import Path
from auraseed.provision.config_manager import apply_user_configs

class TestConfigIntegration(unittest.TestCase):
    def test_apply_and_backup(self):
        with tempfile.TemporaryDirectory() as td:
            appdata = Path(td) / "AppData" / "Roaming"
            userprofile = Path(td) / "User"
            appdata.mkdir(parents=True)
            userprofile.mkdir(parents=True)

            orig_appdata = os.environ.get("APPDATA")
            orig_userprofile = os.environ.get("USERPROFILE")
            try:
                os.environ["APPDATA"] = str(appdata)
                os.environ["USERPROFILE"] = str(userprofile)

                test_cfg = Path(td) / "test_bootstrap.json"
                test_cfg.write_text(
                    '{\n'
                    '  "pip": {\n'
                    '    "index_url": "https://nexus.corp.net/repository/pypi/simple",\n'
                    '    "trusted_hosts": ["nexus.corp.net"],\n'
                    '    "proxy": "http://proxy.corp.net:3128"\n'
                    '  },\n'
                    '  "conda": {\n'
                    '    "channels": ["https://conda.corp.net/main", "conda-forge"],\n'
                    '    "proxy_servers": {\n'
                    '      "http": "http://proxy.corp.net:3128",\n'
                    '      "https": "http://proxy.corp.net:3128"\n'
                    '    },\n'
                    '    "ssl_verify": false\n'
                    '  }\n'
                    '}\n',
                    encoding="utf-8"
                )

                # 1. First run: create files
                res1 = apply_user_configs(test_cfg, auto_yes=True)
                self.assertTrue(res1["pip"]["created"])
                pip_file = appdata / "pip" / "pip.ini"
                condarc = Path.home() / ".condarc"  # Path.home() uses USERPROFILE on Windows

                self.assertTrue(pip_file.exists())
                self.assertTrue(condarc.exists())
                self.assertIn("index-url = https://nexus.corp.net", pip_file.read_text(encoding="utf-8"))
                self.assertIn("proxy = http://proxy.corp.net:3128", pip_file.read_text(encoding="utf-8"))
                self.assertIn("https://conda.corp.net/main", condarc.read_text(encoding="utf-8"))

                # 2. Second run: update with backup
                res2 = apply_user_configs(test_cfg, auto_yes=True)
                self.assertTrue(res2["pip"]["updated"])
                backup_pip = Path(res2["pip"]["backup"])
                self.assertTrue(backup_pip.exists())
                self.assertIn(".bak_", backup_pip.name)
            finally:
                if orig_appdata:
                    os.environ["APPDATA"] = orig_appdata
                if orig_userprofile:
                    os.environ["USERPROFILE"] = orig_userprofile

if __name__ == "__main__":
    unittest.main()

