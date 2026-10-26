import os
import sys
import glob
import shutil
import zipfile
import unittest
import subprocess
from pathlib import Path
from auraseed.discovery.adapters.arcpro import ArcProDiscoverer
from auraseed.seed.sovereign import SovereignVenvEngine
from auraseed.seed.isolation import HostIsolationEngine
from auraseed.seed.artifacts import write_seed_manifest, generate_launchers
from auraseed.models import SeedManifest

class TestArcProIntegrationAndSovereignty(unittest.TestCase):
    def setUp(self):
        self.temp_root = Path("C:/temp")
        self.temp_root.mkdir(parents=True, exist_ok=True)
        self.disposable_src = self.temp_root / "disposable_esri_src"
        self.disposable_venv = self.temp_root / "disposable_esri_venv"
        self.wheel_path = self.temp_root / "arcgis-2.4.3-py3-none-any.whl"

        self._cleanup()

    def tearDown(self):
        self._cleanup()

    def _cleanup(self):
        for p in (self.disposable_src, self.disposable_venv):
            if p.exists():
                shutil.rmtree(p, ignore_errors=True)

    def _ensure_arcgis_wheels(self):
        packages = [
            "arcgis", "cachetools", "requests_oauthlib", "requests_toolbelt",
            "oauthlib", "ujson", "puremagic", "geomet", "pylerc"
        ]
        for pkg in packages:
            matches = list(self.temp_root.glob(f"{pkg}*.whl"))
            if not matches:
                cmd = [
                    sys.executable,
                    "-m",
                    "pip",
                    "download",
                    pkg,
                    "-d",
                    str(self.temp_root)
                ]
                subprocess.run(cmd, check=True, capture_output=True, timeout=60)

    def _setup_disposable_esri_runtime(self):
        """
        Creates an authentic ArcGIS Pro Conda runtime structure:
        - bin/Python/envs/arcgispro-py3
        - Library/bin with native DLLs
        - Lib/site-packages with official arcgis package and dependencies
        - conda-meta
        """
        self.disposable_src.mkdir(parents=True, exist_ok=True)
        pro_envs = self.disposable_src / "bin" / "Python" / "envs" / "arcgispro-py3"
        pro_envs.mkdir(parents=True, exist_ok=True)

        sp = pro_envs / "Lib" / "site-packages"
        sp.mkdir(parents=True, exist_ok=True)
        lib_bin = pro_envs / "Library" / "bin"
        lib_bin.mkdir(parents=True, exist_ok=True)
        (pro_envs / "conda-meta").mkdir(parents=True, exist_ok=True)

        # 1. Base Python files from active interpreter
        sys_exe = Path(sys.executable)
        sys_dir = sys_exe.parent
        shutil.copy2(sys_exe, pro_envs / "python.exe")
        for dll in sys_dir.glob("*.dll"):
            shutil.copy2(dll, pro_envs / dll.name)
            shutil.copy2(dll, lib_bin / dll.name)
        if (sys_dir / "DLLs").exists():
            shutil.copytree(sys_dir / "DLLs", pro_envs / "DLLs", dirs_exist_ok=True)
        if (sys_dir / "Lib").exists():
            shutil.copytree(sys_dir / "Lib", pro_envs / "Lib", dirs_exist_ok=True)

        # 2. Extract downloaded wheels into site-packages
        self._ensure_arcgis_wheels()
        for whl in self.temp_root.glob("*.whl"):
            with zipfile.ZipFile(whl, "r") as zf:
                for member in zf.namelist():
                    if ".data/platlib/" in member:
                        idx = member.index(".data/platlib/") + len(".data/platlib/")
                        rel = member[idx:]
                        target_file = sp / rel
                    elif ".dist-info/" in member:
                        target_file = sp / member
                    elif ".data" in member:
                        continue
                    else:
                        target_file = sp / member
                    
                    target_file.parent.mkdir(parents=True, exist_ok=True)
                    if not member.endswith("/"):
                        with zf.open(member) as source, open(target_file, "wb") as target:
                            shutil.copyfileobj(source, target)

        # 3. Copy pre-installed networking/cryptography dependencies from user/conda site-packages
        dep_sources = [
            Path(os.environ.get("APPDATA", "")) / "Python" / f"Python{sys.version_info.major}{sys.version_info.minor}" / "site-packages",
            Path(r"C:\projects\portabella\conda\Lib\site-packages"),
            Path(r"C:\Program Files\QGIS 3.40.8\apps\Python312\Lib\site-packages"),
        ]
        for src_sp in dep_sources:
            if src_sp.exists():
                try:
                    for item in src_sp.iterdir():
                        if item.name.startswith(".") or item.name == "__pycache__":
                            continue
                        dst_item = sp / item.name
                        if not dst_item.exists():
                            if item.is_dir():
                                shutil.copytree(item, dst_item, dirs_exist_ok=True)
                            else:
                                shutil.copy2(item, dst_item)
                except Exception:
                    pass

        # 4. Create arcpy module
        arcpy_dir = sp / "arcpy"
        arcpy_dir.mkdir(parents=True, exist_ok=True)
        (arcpy_dir / "__init__.py").write_text(
            '__version__ = "3.3.0"\n'
            'class SpatialReference:\n'
            '    def __init__(self, wkid):\n'
            '        self.factoryCode = wkid\n'
            'def CheckOutExtension(name): return "CheckedOut"\n',
            encoding="utf-8"
        )

        # 5. Add mock ArcGIS native C-extension DLL
        (lib_bin / "arcgisscripting.dll").write_text("MZ_ESRI_NATIVE_DLL_DATA", encoding="utf-8")

    def test_esri_arcpro_discovery_and_sovereign_survival(self):
        r"""
        1. Set up authentic ArcGIS Pro environment.
        2. Discover via ArcProDiscoverer.
        3. Seed sovereign venv in C:\temp\disposable_esri_venv.
        4. Completely DELETE disposable source application.
        5. Verify that sovereign venv survives, executes, and imports arcgis & arcpy!
        """
        self._setup_disposable_esri_runtime()

        # 1. Discovery (using explicit search_paths into disposable Conda/ESRI runtime)
        discoverer = ArcProDiscoverer(search_paths=[self.disposable_src])
        envs = [e for e in discoverer.discover() if "disposable_esri_src" in str(e.executable).lower()]
        self.assertEqual(len(envs), 1, "Expected ArcProDiscoverer to locate disposable ESRI runtime.")
        target_env = envs[0]
        self.assertEqual(target_env.source_type, "arcpro_adapter")
        self.assertTrue(target_env.metadata.get("is_conda"))
        self.assertIn("arcgis", target_env.metadata["target_modules"])

        # 2. Seeding
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

        # Verify sovereign structure
        self.assertTrue((self.disposable_venv / "pyvenv.cfg").exists())
        self.assertTrue((self.disposable_venv / "base").exists())
        self.assertTrue((self.disposable_venv / "seed-manifest.json").exists())

        # 3. COMPLETELY DELETE SOURCE APPLICATION
        shutil.rmtree(self.disposable_src)
        self.assertFalse(self.disposable_src.exists(), "Source ESRI application MUST be deleted.")

        # 4. VERIFY SOVEREIGN SURVIVAL
        venv_py = self.disposable_venv / "Scripts" / "python.exe"
        self.assertTrue(venv_py.exists(), "Sovereign venv python.exe must exist.")

        cmd = [
            str(venv_py),
            "-c",
            "import sys; print('SURVIVAL_EXE:', sys.executable); import arcgis; print('ARCGIS_VERSION:', getattr(arcgis, '__version__', 'loaded')); import arcpy; print('ARCPY_SR:', arcpy.SpatialReference(4326).factoryCode)"
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
        self.assertEqual(res.returncode, 0, f"Sovereign venv execution failed after ESRI host deletion: {res.stderr}\nStdout: {res.stdout}")
        self.assertIn("ARCGIS_VERSION:", res.stdout)
        self.assertIn("ARCPY_SR: 4326", res.stdout)

if __name__ == "__main__":
    unittest.main()
