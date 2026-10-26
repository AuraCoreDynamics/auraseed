import os
import sys
import shutil
import unittest
import subprocess
from pathlib import Path
from auraseed.discovery.adapters.qgis import QgisDiscoverer
from auraseed.seed.sovereign import SovereignVenvEngine
from auraseed.seed.isolation import HostIsolationEngine
from auraseed.seed.artifacts import write_seed_manifest, generate_launchers
from auraseed.models import SeedManifest

class TestQgisIntegrationAndSovereignty(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path("C:/temp")
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.disposable_src = self.temp_root / "disposable_qgis_src"
        self.disposable_venv = self.temp_root / "disposable_qgis_venv"
        self.real_qgis_venv = self.temp_root / "int_test_qgis_real_venv"

        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        for p in (self.disposable_src, self.disposable_venv, self.real_qgis_venv):
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)

    def test_01_real_qgis_discovery_and_seeding(self):
        discoverer = QgisDiscoverer()
        envs = list(discoverer.discover())
        self.assertGreater(len(envs), 0, "Real QGIS installation must be discoverable.")

        qgis_env = envs[0]
        self.assertTrue(qgis_env.executable.exists())

        # Seed sovereign venv from real QGIS
        sovereign = SovereignVenvEngine()
        sovereign.create_venv(qgis_env, self.real_qgis_venv)

        isolation = HostIsolationEngine()
        isolation.isolate(qgis_env, self.real_qgis_venv)

        manifest = SeedManifest(
            target_env_id=qgis_env.id,
            version=qgis_env.version,
            source_type=qgis_env.source_type,
            is_default=True
        )
        write_seed_manifest(self.real_qgis_venv, manifest)
        generate_launchers(self.real_qgis_venv)

        # Verify sovereign structure
        self.assertTrue((self.real_qgis_venv / "pyvenv.cfg").exists())
        self.assertTrue((self.real_qgis_venv / "base").exists())
        self.assertTrue((self.real_qgis_venv / "seed-manifest.json").exists())

        # Verify execution and QGIS import
        venv_py = self.real_qgis_venv / "Scripts" / "python.exe"
        cmd = [
            str(venv_py),
            "-c",
            "import sys; print('VENV_EXE:', sys.executable); from qgis.core import Qgis, QgsApplication; app = QgsApplication([], False); app.initQgis(); print('QGIS_CORE_INITIALIZED:', Qgis.QGIS_VERSION); app.exitQgis()"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, f"Execution failed: {res.stderr}\nStdout: {res.stdout}")
        self.assertIn("QGIS_CORE_INITIALIZED:", res.stdout)

    def test_02_qgis_operational_sovereignty_survives_source_deletion(self):
        """
        Critical test: Verifies that when the source QGIS application directory
        is COMPLETELY DELETED, the seeded sovereign venv continues to survive and execute!
        """
        discoverer = QgisDiscoverer()
        host_envs = list(discoverer.discover())
        self.assertGreater(len(host_envs), 0, "Requires at least one QGIS environment to build mock.")
        host_qgis = host_envs[0]
        host_root = Path(host_qgis.metadata["qgis_root"])

        # 1. Create disposable source QGIS directory structure
        self.disposable_src.mkdir(parents=True, exist_ok=True)
        disp_apps = self.disposable_src / "apps"
        disp_bin = self.disposable_src / "bin"
        disp_py = disp_apps / "Python312"
        disp_qgis_py = disp_apps / "qgis-ltr" / "python"
        disp_qgis_bin = disp_apps / "qgis-ltr" / "bin"

        disp_py.mkdir(parents=True, exist_ok=True)
        disp_bin.mkdir(parents=True, exist_ok=True)
        disp_qgis_py.mkdir(parents=True, exist_ok=True)
        disp_qgis_bin.mkdir(parents=True, exist_ok=True)

        # Copy python executable and dlls to disposable QGIS
        shutil.copy2(host_qgis.executable, disp_py / "python.exe")
        for dll in host_qgis.executable.parent.glob("*.dll"):
            shutil.copy2(dll, disp_py / dll.name)
        if (host_qgis.executable.parent / "DLLs").exists():
            shutil.copytree(host_qgis.executable.parent / "DLLs", disp_py / "DLLs", dirs_exist_ok=True)
        if (host_qgis.executable.parent / "Lib").exists():
            shutil.copytree(host_qgis.executable.parent / "Lib", disp_py / "Lib", dirs_exist_ok=True)
        for zip_f in host_qgis.executable.parent.glob("python*.zip"):
            shutil.copy2(zip_f, disp_py / zip_f.name)

        # Copy bin dlls
        if (host_root / "bin").exists():
            for dll in (host_root / "bin").glob("*.dll"):
                shutil.copy2(dll, disp_bin / dll.name)
        if (host_root / "apps" / "qgis-ltr" / "bin").exists():
            for dll in (host_root / "apps" / "qgis-ltr" / "bin").glob("*.dll"):
                shutil.copy2(dll, disp_qgis_bin / dll.name)

        # Copy Qt5 DLLs and platform plugins
        disp_qt5_bin = disp_apps / "Qt5" / "bin"
        disp_qt5_bin.mkdir(parents=True, exist_ok=True)
        host_qt5_bin = host_root / "apps" / "Qt5" / "bin"
        if host_qt5_bin.exists():
            for dll in host_qt5_bin.glob("*.dll"):
                shutil.copy2(dll, disp_qt5_bin / dll.name)

        host_qt5_plugins = host_root / "apps" / "Qt5" / "plugins"
        disp_qt5_plugins = disp_apps / "Qt5" / "plugins"
        if (host_qt5_plugins / "platforms").exists():
            shutil.copytree(host_qt5_plugins / "platforms", disp_qt5_plugins / "platforms", dirs_exist_ok=True)

        host_qgis_plugins = host_root / "apps" / "qgis-ltr" / "plugins"
        disp_qgis_plugins = disp_apps / "qgis-ltr" / "plugins"
        if host_qgis_plugins.exists():
            shutil.copytree(host_qgis_plugins, disp_qgis_plugins, dirs_exist_ok=True)

        # Copy qgis and PyQt5 python packages
        host_qgis_py = host_root / "apps" / "qgis-ltr" / "python"
        if host_qgis_py.exists():
            shutil.copytree(host_qgis_py / "qgis", disp_qgis_py / "qgis", dirs_exist_ok=True)
            if (host_qgis_py / "PyQt5").exists():
                shutil.copytree(host_qgis_py / "PyQt5", disp_qgis_py / "PyQt5", dirs_exist_ok=True)

        host_sp = host_qgis.executable.parent / "Lib" / "site-packages"
        disp_sp = disp_py / "Lib" / "site-packages"
        disp_sp.mkdir(parents=True, exist_ok=True)
        if (host_sp / "PyQt5").exists():
            shutil.copytree(host_sp / "PyQt5", disp_sp / "PyQt5", dirs_exist_ok=True)

        # 2. Discover the disposable QGIS instance (via explicit search_paths)
        disp_discoverer = QgisDiscoverer(search_paths=[self.disposable_src])
        discovered = [e for e in disp_discoverer.discover() if "disposable_qgis_src" in str(e.executable).lower()]
        self.assertEqual(len(discovered), 1, "Disposable QGIS source must be discovered.")
        target_disp_env = discovered[0]

        # 3. Seed sovereign venv from the disposable source
        sovereign = SovereignVenvEngine()
        sovereign.create_venv(target_disp_env, self.disposable_venv)

        isolation = HostIsolationEngine()
        isolation.isolate(target_disp_env, self.disposable_venv)

        manifest = SeedManifest(
            target_env_id=target_disp_env.id,
            version=target_disp_env.version,
            source_type=target_disp_env.source_type,
            is_default=True
        )
        write_seed_manifest(self.disposable_venv, manifest)
        generate_launchers(self.disposable_venv)

        # 4. COMPLETELY DELETE THE SOURCE APPLICATION
        shutil.rmtree(self.disposable_src)
        self.assertFalse(self.disposable_src.exists(), "Disposable QGIS source MUST be completely deleted.")

        # 5. VERIFY SOVEREIGN VENV SURVIVAL
        venv_py = self.disposable_venv / "Scripts" / "python.exe"
        self.assertTrue(venv_py.exists())

        cmd = [
            str(venv_py),
            "-c",
            "import sys; print('SURVIVAL_EXE:', sys.executable); from qgis.core import Qgis, QgsApplication; app = QgsApplication([], False); app.initQgis(); print('SURVIVED_QGIS_CORE_INITIALIZED:', Qgis.QGIS_VERSION); app.exitQgis()"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, f"Sovereign venv failed after source deletion: {res.stderr}\nStdout: {res.stdout}")
        self.assertIn("SURVIVED_QGIS_CORE_INITIALIZED:", res.stdout)

if __name__ == "__main__":
    unittest.main()
