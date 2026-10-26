import os
import sys
import shutil
import unittest
import subprocess
from pathlib import Path
from auraseed.discovery.os.windows import WindowsDiscoverer
from auraseed.seed.sovereign import SovereignVenvEngine
from auraseed.seed.isolation import HostIsolationEngine
from auraseed.seed.artifacts import write_seed_manifest, generate_launchers
from auraseed.models import SeedManifest

class TestWindowsIntegrationAndSovereignty(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path("C:/temp")
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.disposable_src = self.temp_root / "disposable_win_src"
        self.disposable_venv = self.temp_root / "disposable_win_venv"
        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        for p in (self.disposable_src, self.disposable_venv):
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)

    def test_windows_operational_sovereignty_survives_deletion(self):
        r"""
        1. Set up a disposable standalone Python runtime in C:\temp\disposable_win_src.
        2. Discover it with WindowsDiscoverer.
        3. Seed sovereign venv in C:\temp\disposable_win_venv.
        4. Completely DELETE disposable source Python installation.
        5. Verify that sovereign venv survives, executes, and computes successfully!
        """
        # 1. Setup disposable standalone Python runtime
        self.disposable_src.mkdir(parents=True, exist_ok=True)
        sys_exe = Path(sys.executable)
        sys_dir = sys_exe.parent

        shutil.copy2(sys_exe, self.disposable_src / "python.exe")
        for dll in sys_dir.glob("*.dll"):
            shutil.copy2(dll, self.disposable_src / dll.name)
        if (sys_dir / "DLLs").exists():
            shutil.copytree(sys_dir / "DLLs", self.disposable_src / "DLLs", dirs_exist_ok=True)
        if (sys_dir / "Lib").exists():
            shutil.copytree(sys_dir / "Lib", self.disposable_src / "Lib", dirs_exist_ok=True)
        for zip_f in sys_dir.glob("python*.zip"):
            shutil.copy2(zip_f, self.disposable_src / zip_f.name)

        # 2. Discover disposable runtime
        old_path = os.environ.get("PATH", "")
        try:
            os.environ["PATH"] = f"{self.disposable_src};{old_path}"
            discoverer = WindowsDiscoverer()
            envs = [e for e in discoverer.discover() if "disposable_win_src" in str(e.executable).lower()]
            self.assertGreater(len(envs), 0, "Disposable Python runtime must be discovered via WindowsDiscoverer.")
            target_env = envs[0]

            # 3. Seed sovereign venv
            sovereign = SovereignVenvEngine()
            sovereign.create_venv(target_env, self.disposable_venv)

            isolation = HostIsolationEngine()
            isolation.isolate(target_env, self.disposable_venv)

            manifest = SeedManifest(
                target_env_id=target_env.id,
                version=target_env.version,
                source_type=target_env.source_type,
                is_default=True
            )
            write_seed_manifest(self.disposable_venv, manifest)
            generate_launchers(self.disposable_venv)

            # 4. COMPLETELY DELETE SOURCE APPLICATION
            shutil.rmtree(self.disposable_src)
            self.assertFalse(self.disposable_src.exists(), "Disposable Python source MUST be deleted.")

            # 5. VERIFY SOVEREIGN SURVIVAL
            venv_py = self.disposable_venv / "Scripts" / "python.exe"
            self.assertTrue(venv_py.exists(), "Sovereign venv python.exe must exist.")

            cmd = [
                str(venv_py),
                "-c",
                "import sys, math, json, os; print('SURVIVAL_WIN_EXE:', sys.executable); print('MATH_PI:', math.pi)"
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            self.assertEqual(res.returncode, 0, f"Sovereign venv execution failed after Python host deletion: {res.stderr}\nStdout: {res.stdout}")
            self.assertIn("MATH_PI: 3.14", res.stdout)
        finally:
            os.environ["PATH"] = old_path

if __name__ == "__main__":
    unittest.main()
