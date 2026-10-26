import os
import sys
import shutil
import tempfile
import unittest
from pathlib import Path

from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest


class TestMvenvManager(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.mkdtemp(prefix="auraseed_test_mvenv_")
        self.manager = MvenvManager(Path(self.temp_dir))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_create_and_catalog_venv(self):
        # Create an mvenv using the current interpreter
        req = MvenvCreateRequest(
            name="unit-test-env",
            base_python=sys.executable,
            sovereign=False,  # faster test without full DLL copies
            force=True
        )

        record = self.manager.create_venv(req)
        self.assertEqual(record.name, "unit-test-env")
        self.assertTrue(Path(record.path).exists())
        self.assertTrue(Path(record.python_path).exists())

        # Verify .mvenv.json was written
        meta_file = Path(record.path) / ".mvenv.json"
        self.assertTrue(meta_file.exists())

        # Verify catalog lookup
        fetched = self.manager.get_venv("unit-test-env")
        self.assertIsNotNone(fetched)
        self.assertEqual(fetched.name, "unit-test-env")

        # Verify list
        venvs = self.manager.list_venvs()
        self.assertEqual(len(venvs), 1)
        self.assertEqual(venvs[0].name, "unit-test-env")

    def test_verify_venv(self):
        req = MvenvCreateRequest(
            name="verify-env",
            base_python=sys.executable,
            sovereign=False,
            force=True
        )
        self.manager.create_venv(req)

        verify_res = self.manager.verify_venv("verify-env")
        self.assertTrue(verify_res.get("valid"))
        self.assertIn("python_version", verify_res)

    def test_export_and_import_bundle(self):
        req = MvenvCreateRequest(
            name="export-env",
            base_python=sys.executable,
            sovereign=False,
            force=True
        )
        self.manager.create_venv(req)

        # Export bundle
        bundle_file = self.manager.export_bundle("export-env")
        self.assertTrue(bundle_file.exists())
        self.assertTrue(bundle_file.name.endswith(".tar.gz"))

        # Import bundle under a new name
        imported_rec = self.manager.import_bundle(bundle_file, target_name="imported-env", force=True)
        self.assertEqual(imported_rec.name, "imported-env")
        self.assertTrue(Path(imported_rec.path).exists())
        self.assertTrue(Path(imported_rec.python_path).exists())

        # Verify both exist in catalog
        all_venvs = self.manager.list_venvs()
        names = [v.name for v in all_venvs]
        self.assertIn("export-env", names)
        self.assertIn("imported-env", names)

    def test_delete_venv(self):
        req = MvenvCreateRequest(
            name="del-env",
            base_python=sys.executable,
            sovereign=False,
            force=True
        )
        rec = self.manager.create_venv(req)
        env_dir = Path(rec.path)
        self.assertTrue(env_dir.exists())

        # Delete
        success = self.manager.delete_venv("del-env")
        self.assertTrue(success)
        self.assertFalse(env_dir.exists())
        self.assertIsNone(self.manager.get_venv("del-env"))


if __name__ == "__main__":
    unittest.main()
