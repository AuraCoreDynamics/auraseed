import unittest
from auraseed.mvenv.models import MvenvRecord, MvenvBundleMetadata, MvenvProvenance


class TestMvenvModels(unittest.TestCase):
    def test_record_serialization(self):
        rec = MvenvRecord(
            name="test-env",
            path="/tmp/test-env",
            python_path="/tmp/test-env/bin/python",
            pip_path="/tmp/test-env/bin/pip",
            python_version="3.12.3",
            base_interpreter="/usr/bin/python3",
            created_at="2026-10-26T12:00:00Z",
            updated_at="2026-10-26T12:00:00Z",
            packages=["mcp", "fastmcp"],
            size_bytes=1048576,
            is_sovereign=True,
            bundle_hash="abc123hash",
            metadata={"tag": "worker"}
        )

        d = rec.to_dict()
        self.assertEqual(d["name"], "test-env")
        self.assertEqual(d["python_version"], "3.12.3")
        self.assertTrue(d["is_sovereign"])

        # Deserialization from dictionary
        restored = MvenvRecord.from_dict(d)
        self.assertEqual(restored.name, "test-env")
        self.assertEqual(restored.python_path, "/tmp/test-env/bin/python")
        self.assertEqual(restored.packages, ["mcp", "fastmcp"])
        self.assertEqual(restored.bundle_hash, "abc123hash")

    def test_record_camel_case_compatibility(self):
        # Test compatibility with AuraGrid .mvenv.json format
        auragrid_data = {
            "name": "grid-env",
            "pythonVersion": "3.11.0",
            "pythonPath": "C:\\mvenvs\\grid-env\\Scripts\\python.exe",
            "pipPath": "C:\\mvenvs\\grid-env\\Scripts\\pip.exe",
            "baseInterpreter": "C:\\Python311\\python.exe",
            "createdAt": "2026-10-26T00:00:00Z",
            "updatedAt": "2026-10-26T01:00:00Z",
            "packages": ["fastmcp"],
            "sizeBytes": 2048,
            "isSovereign": True
        }

        rec = MvenvRecord.from_dict(auragrid_data)
        self.assertEqual(rec.name, "grid-env")
        self.assertEqual(rec.python_version, "3.11.0")
        self.assertEqual(rec.python_path, "C:\\mvenvs\\grid-env\\Scripts\\python.exe")
        self.assertTrue(rec.is_sovereign)
        self.assertEqual(rec.packages, ["fastmcp"])

    def test_bundle_metadata(self):
        meta = MvenvBundleMetadata(
            name="bundle-env",
            bundle_id="b12345",
            bundle_hash="sha256hash",
            created_at="2026-10-26T12:00:00Z",
            python_version="3.12.0",
            platform="linux",
            arch="x86_64",
            packages=["requests"]
        )

        d = meta.to_dict()
        restored = MvenvBundleMetadata.from_dict(d)
        self.assertEqual(restored.bundle_id, "b12345")
        self.assertEqual(restored.platform, "linux")

    def test_provenance_model_serialization(self):
        prov = MvenvProvenance(
            mvenv_name="prov-env",
            mvenv_path="/tmp/prov-env",
            python_path="/tmp/prov-env/bin/python",
            python_version="3.12.3",
            sovereign=True,
            package_count=2,
            packages=[
                {"name": "auraseed", "version": "1.1.1", "editable": True},
                {"name": "requests", "version": "2.32.0", "editable": False},
            ],
            provenance_digest="sha256:" + ("a" * 64),
            generated_at="2026-11-24T12:00:00+00:00",
        )
        d = prov.to_dict()
        self.assertEqual(d["mvenv_name"], "prov-env")
        self.assertEqual(d["package_count"], 2)
        self.assertTrue(d["packages"][0]["editable"])

        restored = MvenvProvenance.from_dict(d)
        self.assertEqual(restored.mvenv_name, "prov-env")
        self.assertEqual(restored.provenance_digest, "sha256:" + ("a" * 64))
        self.assertEqual(len(restored.packages), 2)


if __name__ == "__main__":
    unittest.main()
