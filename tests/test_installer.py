import unittest
import tempfile
import shutil
import json
import sys
from pathlib import Path

from auraseed.installer.models import AppManifest
from auraseed.installer.packager import AppBundlePackager
from auraseed.installer.engine import AppInstallerEngine


class TestInstallerSystem(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.addCleanup(lambda: shutil.rmtree(self.test_dir, ignore_errors=True))

    def test_manifest_serialization(self):
        manifest_data = {
            "name": "bijou",
            "display_name": "Bijou Causal Graph Engine",
            "version": "0.1.0",
            "description": "Multi-Echelon Impact & Causal Graph Engine",
            "entrypoint_command": "bijou --mode standalone --port {port}",
            "default_port": 8000,
            "subprojects": ["projects/bijou-pysdk", "projects/bijou-doc-ingest"]
        }
        manifest_file = Path(self.test_dir) / "app.json"
        manifest_file.write_text(json.dumps(manifest_data), encoding="utf-8")

        loaded = AppManifest.from_file(manifest_file)
        self.assertEqual(loaded.name, "bijou")
        self.assertEqual(loaded.display_name, "Bijou Causal Graph Engine")
        self.assertEqual(loaded.default_port, 8000)
        self.assertEqual(len(loaded.subprojects), 2)

    def test_launcher_generation(self):
        manifest = AppManifest(
            name="testapp",
            display_name="Test Application",
            entrypoint_command="testapp --port {port}",
            default_port=9000
        )
        engine = AppInstallerEngine(manifest)
        dest_dir = Path(self.test_dir) / "testapp_dest"
        dest_dir.mkdir(parents=True)
        fake_python = dest_dir / "Scripts" / "python.exe"
        fake_python.parent.mkdir(parents=True)
        fake_python.write_text("", encoding="utf-8")

        launchers = engine._generate_launchers(dest_dir, fake_python, 9000)
        self.assertTrue(len(launchers) > 0)
        if "bat" in launchers:
            bat_path = Path(launchers["bat"])
            self.assertTrue(bat_path.exists())
            content = bat_path.read_text(encoding="utf-8")
            self.assertIn("testapp --port 9000", content)

    def test_bundle_packager(self):
        # Create a mock application directory
        app_dir = Path(self.test_dir) / "mock_app"
        app_dir.mkdir()
        (app_dir / "pyproject.toml").write_text("[project]\nname='mock_app'\n", encoding="utf-8")
        manifest_data = {
            "name": "mock_app",
            "display_name": "Mock Application",
            "version": "1.0.0",
            "subprojects": ["sub1"]
        }
        (app_dir / "app.json").write_text(json.dumps(manifest_data), encoding="utf-8")
        (app_dir / "sub1").mkdir()
        (app_dir / "sub1" / "setup.py").write_text("", encoding="utf-8")

        packager = AppBundlePackager(app_dir=app_dir)
        out_dir = Path(self.test_dir) / "dist"
        bundle_path = packager.package(out_dir, create_zip=False)

        self.assertTrue(bundle_path.exists())
        self.assertTrue((bundle_path / "app.json").exists())
        self.assertTrue((bundle_path / "payload").exists())
        self.assertTrue((bundle_path / "auraseed").exists())
        self.assertTrue((bundle_path / "install.bat").exists())
        self.assertTrue((bundle_path / "install.ps1").exists())

        # Verify app.json inside bundle points source_path to payload
        bundled_manifest = AppManifest.from_file(bundle_path / "app.json")
        self.assertEqual(bundled_manifest.source_path, "payload")
        self.assertEqual(bundled_manifest.subprojects, ["payload/sub1"])

    def test_bundle_packager_with_artifacts_and_hooks(self):
        app_dir = Path(self.test_dir) / "app_with_artifacts"
        app_dir.mkdir()
        (app_dir / "pyproject.toml").write_text("[project]\nname='art_app'\n", encoding="utf-8")

        # Create extra artifacts
        configs_dir = app_dir / "configs"
        configs_dir.mkdir()
        (configs_dir / "net_prod.yaml").write_text("env: production\n", encoding="utf-8")
        (configs_dir / "net_dev.yaml").write_text("env: dev\n", encoding="utf-8")

        # Create hooks
        hooks_dir = app_dir / "hooks"
        hooks_dir.mkdir()
        (hooks_dir / "post_install.py").write_text("print('Hook executed')\n", encoding="utf-8")

        manifest_data = {
            "name": "art_app",
            "display_name": "Artifacts Application",
            "artifacts": ["configs/*.yaml"],
            "hooks": {
                "post_install": "hooks/post_install.py"
            }
        }
        (app_dir / "app.json").write_text(json.dumps(manifest_data), encoding="utf-8")

        packager = AppBundlePackager(app_dir=app_dir)
        out_dir = Path(self.test_dir) / "dist_art"
        bundle_path = packager.package(out_dir, create_zip=False)

        self.assertTrue((bundle_path / "artifacts" / "configs" / "net_prod.yaml").exists())
        self.assertTrue((bundle_path / "artifacts" / "configs" / "net_dev.yaml").exists())
        self.assertTrue((bundle_path / "hooks" / "post_install.py").exists())

    def test_lifecycle_hook_execution(self):
        manifest_data = {
            "name": "hook_app",
            "display_name": "Hook Application",
            "version": "1.2.3",
            "hooks": {
                "post_install": "hooks/post_install.py"
            }
        }
        manifest = AppManifest.from_dict(manifest_data)
        engine = AppInstallerEngine(manifest)

        bundle_dir = Path(self.test_dir) / "bundle"
        bundle_dir.mkdir()
        hooks_dir = bundle_dir / "hooks"
        hooks_dir.mkdir()

        witness_file = Path(self.test_dir) / "witness.json"
        hook_code = f"""import os, json, sys
data = {{
    "app_name": os.environ.get("AURASEED_APP_NAME"),
    "install_dir": os.environ.get("AURASEED_INSTALL_DIR"),
    "bundle_dir": os.environ.get("AURASEED_BUNDLE_DIR"),
    "hook": os.environ.get("AURASEED_HOOK"),
    "argv": sys.argv
}}
with open(r"{witness_file}", "w") as f:
    json.dump(data, f)
print("Witness written successfully")
"""
        (hooks_dir / "post_install.py").write_text(hook_code, encoding="utf-8")

        target_dest = Path(self.test_dir) / "installed_app"
        target_dest.mkdir()
        python_exe = Path(sys.executable)

        manifest.metadata["_manifest_dir"] = str(bundle_dir)
        engine._execute_python_hook(
            hook_name="post_install",
            python_exe=python_exe,
            target_dest=target_dest,
            target_port=8080,
            app_root=bundle_dir,
            bundle_dir=bundle_dir
        )

        self.assertTrue(witness_file.exists())
        witness_data = json.loads(witness_file.read_text(encoding="utf-8"))
        self.assertEqual(witness_data["app_name"], "hook_app")
        self.assertEqual(witness_data["install_dir"], str(target_dest))
        self.assertEqual(witness_data["bundle_dir"], str(bundle_dir))
        self.assertEqual(witness_data["hook"], "post_install")
        self.assertIn("--install-dir", witness_data["argv"])


if __name__ == "__main__":
    unittest.main()

