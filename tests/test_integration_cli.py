import os
import sys
import shutil
import unittest
import subprocess
from pathlib import Path

class TestCLIIntegration(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path("C:/temp")
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.cli_venv = self.temp_root / "test_cli_sovereign_venv"
        self.relaunch_script = self.temp_root / "test_relaunch_script.py"

        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        for p in (self.cli_venv, self.relaunch_script):
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
            elif p.is_file():
                try:
                    p.unlink()
                except OSError:
                    pass

    def test_cli_qgis_seeding_and_relaunch(self):
        # Create a small relaunch script
        output_marker = self.temp_root / "relaunch_output.txt"
        if output_marker.exists():
            output_marker.unlink()

        self.relaunch_script.write_text(
            f'from pathlib import Path\nPath(r"{output_marker}").write_text("RELAUNCH_SUCCESS", encoding="utf-8")\n',
            encoding="utf-8"
        )

        cmd = [
            sys.executable,
            "-m",
            "auraseed",
            "--adapter",
            "qgis",
            "--strategy",
            "latest",
            "--dest",
            str(self.cli_venv),
            "--force",
            "--no-register",
            "--relaunch",
            str(self.relaunch_script)
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
        self.assertEqual(res.returncode, 0, f"CLI command failed: {res.stderr}\nStdout: {res.stdout}")
        self.assertTrue(output_marker.exists(), "Relaunch script should have created the output marker.")
        self.assertEqual(output_marker.read_text(encoding="utf-8"), "RELAUNCH_SUCCESS")

        # Clean marker
        output_marker.unlink()

        # Test auraseed-run.cmd launcher
        launcher = self.cli_venv / "Scripts" / "auraseed-run.cmd"
        self.assertTrue(launcher.exists(), "auraseed-run.cmd launcher must be generated.")

        cmd = [
            str(launcher),
            "-c",
            "from qgis.core import Qgis, QgsApplication; app = QgsApplication([], False); app.initQgis(); print('LAUNCHER_SUCCESS: QGIS_INITIALIZED', Qgis.QGIS_VERSION); app.exitQgis()"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, f"Launcher command failed: {res.stderr}\nStdout: {res.stdout}")
        self.assertIn("LAUNCHER_SUCCESS: QGIS_INITIALIZED", res.stdout)

if __name__ == "__main__":
    unittest.main()
