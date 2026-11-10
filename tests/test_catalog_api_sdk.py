"""
Tests for AuraSeed Server-Side App Catalog, Client SDK, OpenAPI Specification, and MVenv Merging.
Zero external runtime dependencies.
"""
import os
import sys
import json
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from auraseed.catalog.server import ServerAppCatalog
from auraseed.catalog.sources import CatalogRegistry
from auraseed.catalog.local import LocalAppManager
from auraseed.client import AuraSeedClient
from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest
from auraseed.installer.models import AppManifest
from auraseed.api.server import create_api_server


class TestCatalogApiAndSdk(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.test_dir = tempfile.mkdtemp(prefix="auraseed_catalog_test_")
        cls.root_path = Path(cls.test_dir)
        cls.mvenv_dir = cls.root_path / "mvenvs"
        cls.catalog_dir = cls.root_path / "catalog"
        cls.apps_dir = cls.root_path / "apps"

        cls.mvenv_dir.mkdir(parents=True)
        cls.catalog_dir.mkdir(parents=True)
        cls.apps_dir.mkdir(parents=True)

        cls.mvenv_manager = MvenvManager(cls.mvenv_dir)
        cls.server_catalog = ServerAppCatalog(cls.catalog_dir)

        cls.server = create_api_server(
            host="127.0.0.1",
            port=0,
            manager=cls.mvenv_manager,
            catalog=cls.server_catalog
        )
        cls.port = cls.server.server_port
        cls.base_url = f"http://127.0.0.1:{cls.port}"

        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

        cls.client = AuraSeedClient(base_url=cls.base_url)

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        shutil.rmtree(cls.test_dir, ignore_errors=True)

    def test_openapi_endpoints_and_artifact(self):
        # 1. Test SDK get_openapi (JSON)
        spec_json = self.client.get_openapi(format="json")
        self.assertIsInstance(spec_json, dict)
        self.assertEqual(spec_json.get("openapi"), "3.0.3")
        self.assertEqual(spec_json.get("info", {}).get("title"), "AuraSeed Server API")
        self.assertIn("/api/v1/apps", spec_json.get("paths", {}))
        self.assertIn("/api/v1/mvenv/merge", spec_json.get("paths", {}))

        # 2. Test SDK get_openapi (YAML)
        spec_yaml = self.client.get_openapi(format="yaml")
        self.assertIsInstance(spec_yaml, str)
        self.assertIn("openapi: 3.0.3", spec_yaml)
        self.assertIn("/api/v1/apps", spec_yaml)

    def test_catalog_and_client_app_deployment_lifecycle(self):
        # 1. Create a mock application directory with app.json
        app_source = self.root_path / "demo_app"
        app_source.mkdir(parents=True, exist_ok=True)
        (app_source / "pyproject.toml").write_text("[project]\nname='demo_app'\nversion='1.0.0'\n", encoding="utf-8")
        manifest_data = {
            "name": "demo_app",
            "display_name": "Demo Application",
            "version": "1.0.0",
            "description": "A demo app for deployment testing",
            "entrypoint_command": "demo_app --port {port}",
            "default_port": 8800
        }
        (app_source / "app.json").write_text(json.dumps(manifest_data), encoding="utf-8")

        # 2. Initially catalog should be empty
        initial_apps = self.client.list_apps()
        self.assertEqual(len(initial_apps), 0)

        # 3. Deploy app via Client SDK directly pointing to source folder
        deployed = self.client.deploy_app(app_source)
        self.assertEqual(deployed.get("name"), "demo_app")
        self.assertEqual(deployed.get("display_name"), "Demo Application")
        self.assertEqual(deployed.get("default_port"), 8800)
        self.assertGreater(deployed.get("size_bytes", 0), 0)

        # 4. List apps via SDK and verify query filter
        all_apps = self.client.list_apps()
        self.assertEqual(len(all_apps), 1)
        self.assertEqual(all_apps[0]["name"], "demo_app")

        matched = self.client.list_apps(query="demo")
        self.assertEqual(len(matched), 1)

        empty_matched = self.client.list_apps(query="nonexistent_xyz")
        self.assertEqual(len(empty_matched), 0)

        # 5. Get app details
        details = self.client.get_app("demo_app")
        self.assertEqual(details["name"], "demo_app")
        self.assertEqual(details["version"], "1.0.0")

        # 6. Download app bundle
        download_target = self.root_path / "downloads" / "downloaded_app.zip"
        saved = self.client.download_app("demo_app", download_target)
        self.assertTrue(saved.exists())
        self.assertGreater(os.path.getsize(saved), 0)

        # 7. Delete app from catalog
        deleted = self.client.delete_app("demo_app")
        self.assertTrue(deleted)

        remaining = self.client.list_apps()
        self.assertEqual(len(remaining), 0)

    def test_mvenv_merge_via_sdk(self):
        # 1. Create two small mvenvs via Client SDK
        env1 = self.client.create_mvenv("merge-env-1", sovereign=False, base_python=sys.executable)
        self.assertEqual(env1["name"], "merge-env-1")

        env2 = self.client.create_mvenv("merge-env-2", sovereign=False, base_python=sys.executable)
        self.assertEqual(env2["name"], "merge-env-2")

        # 2. Merge them into a target environment
        merge_result = self.client.merge_mvenvs(
            sources=["merge-env-1", "merge-env-2"],
            target="merged-consolidated-env",
            delete_sources=True
        )
        self.assertTrue(merge_result.get("success"))
        self.assertEqual(merge_result.get("target", {}).get("name"), "merged-consolidated-env")
        self.assertIn("merge-env-1", merge_result.get("deleted_sources", []))
        self.assertIn("merge-env-2", merge_result.get("deleted_sources", []))

        # Verify source mvenvs are pruned to save disk space
        existing_names = [v["name"] for v in self.client.list_mvenvs()]
        self.assertIn("merged-consolidated-env", existing_names)
        self.assertNotIn("merge-env-1", existing_names)
        self.assertNotIn("merge-env-2", existing_names)

    def test_catalog_sources_registry(self):
        reg_file = self.root_path / "catalogs_custom.json"
        reg = CatalogRegistry(reg_file)

        initial = reg.list_catalogs()
        self.assertTrue(len(initial) >= 1)

        # Add a custom catalog
        added = reg.add_catalog("http://192.168.1.50:7099", label="Cluster Node 1")
        self.assertEqual(added["url"], "http://192.168.1.50:7099")
        self.assertEqual(added["label"], "Cluster Node 1")

        catalogs = reg.list_catalogs()
        urls = [c["url"] for c in catalogs]
        self.assertIn("http://192.168.1.50:7099", urls)

        # Remove catalog
        removed = reg.remove_catalog("http://192.168.1.50:7099")
        self.assertTrue(removed)

        urls_after = [c["url"] for c in reg.list_catalogs()]
        self.assertNotIn("http://192.168.1.50:7099", urls_after)

    def test_local_app_manager_discovery_and_relink(self):
        local_mgr = LocalAppManager(
            apps_dir=self.apps_dir,
            registry_file=self.root_path / "local_apps_registry.json"
        )

        # Create a mock installed app directory
        mock_app_dir = self.apps_dir / "my_local_tool"
        mock_app_dir.mkdir(parents=True, exist_ok=True)
        manifest = AppManifest(
            name="my_local_tool",
            display_name="My Local Tool",
            version="2.1.0",
            entrypoint_command="my_local_tool --port {port}"
        )
        manifest.to_file(mock_app_dir / "app.json")

        # Fake an embedded launcher
        launcher_bat = mock_app_dir / "run-my_local_tool.bat"
        launcher_bat.write_text("@echo off\r\necho running\r\n", encoding="utf-8")

        # Inspect local apps
        installed = local_mgr.list_installed_apps()
        names = [a["name"] for a in installed]
        self.assertIn("my_local_tool", names)

        app_info = local_mgr.get_installed_app("my_local_tool")
        self.assertIsNotNone(app_info)
        self.assertEqual(app_info["version"], "2.1.0")

        # Create a mock target mvenv for relinking
        mvenv_req = MvenvCreateRequest(name="local-target-env", base_python=sys.executable, sovereign=False)
        self.mvenv_manager.create_venv(mvenv_req)

        # Relink to target mvenv
        relinked = local_mgr.relink_app_mvenv("my_local_tool", "local-target-env", mvenv_manager=self.mvenv_manager)
        self.assertTrue(relinked)

        updated_app = local_mgr.get_installed_app("my_local_tool")
        self.assertEqual(updated_app["mvenv_name"], "local-target-env")

        # Uninstall app
        uninstalled = local_mgr.uninstall_app("my_local_tool")
        self.assertTrue(uninstalled)
        self.assertIsNone(local_mgr.get_installed_app("my_local_tool"))

    def test_cli_deploy_and_catalog(self):
        # Create a mock app for CLI deploy
        cli_app_dir = self.root_path / "cli_test_app"
        cli_app_dir.mkdir(parents=True, exist_ok=True)
        manifest = {
            "name": "cli_app",
            "display_name": "CLI Test App",
            "version": "1.0.0",
            "entrypoint_command": "cli_app"
        }
        (cli_app_dir / "app.json").write_text(json.dumps(manifest), encoding="utf-8")

        # 1. Deploy via CLI
        cmd_deploy = [
            sys.executable, "-m", "auraseed", "deploy",
            str(cli_app_dir),
            "--server", self.base_url,
            "--json"
        ]
        env_vars = os.environ.copy()
        env_vars["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent)

        import subprocess
        proc = subprocess.run(cmd_deploy, capture_output=True, text=True, env=env_vars)
        self.assertEqual(proc.returncode, 0, f"CLI deploy failed: {proc.stderr}")
        deploy_res = json.loads(proc.stdout)
        self.assertEqual(deploy_res.get("name"), "cli_app")

        # 2. Query via CLI catalog list
        cmd_list = [
            sys.executable, "-m", "auraseed", "catalog", "list",
            "--server", self.base_url,
            "--json"
        ]
        proc_list = subprocess.run(cmd_list, capture_output=True, text=True, env=env_vars)
        self.assertEqual(proc_list.returncode, 0)
        apps_list = json.loads(proc_list.stdout)
        names = [a["name"] for a in apps_list]
        self.assertIn("cli_app", names)


if __name__ == "__main__":
    unittest.main()
