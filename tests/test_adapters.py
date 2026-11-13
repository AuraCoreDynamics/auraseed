import unittest
from pathlib import Path
from auraseed.discovery.adapters.qgis import QgisDiscoverer
from auraseed.discovery.adapters.arcpro import ArcProDiscoverer
from auraseed.discovery.os.windows import WindowsDiscoverer
from auraseed.discovery.manager import DiscoveryManager

class TestDiscoveryAdapters(unittest.TestCase):
    def test_qgis_discovery(self):
        discoverer = QgisDiscoverer()
        envs = list(discoverer.discover())
        if envs:
            qgis_env = envs[0]
            self.assertIn("QGIS", qgis_env.name)
            self.assertEqual(qgis_env.source_type, "qgis_adapter")
            self.assertTrue(qgis_env.executable.exists())
            self.assertIn("target_modules", qgis_env.metadata)
            self.assertIn("qgis", qgis_env.metadata["target_modules"])
        else:
            # When host system has no installed QGIS, test discovery algorithm on mock layout
            import tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                tmp = Path(tmpdir)
                py_dir = tmp / "apps" / "Python312"
                py_dir.mkdir(parents=True)
                (py_dir / "python.exe").write_text("", encoding="utf-8")
                (tmp / "apps" / "qgis-ltr" / "python").mkdir(parents=True)
                mock_disc = QgisDiscoverer(search_paths=[tmp])
                mock_envs = list(mock_disc.discover())
                self.assertGreater(len(mock_envs), 0, "Expected mock QGIS installation to be discovered.")
                qgis_env = mock_envs[0]
                self.assertIn("QGIS", qgis_env.name)
                self.assertEqual(qgis_env.source_type, "qgis_adapter")
                self.assertTrue(qgis_env.executable.exists())
                self.assertIn("target_modules", qgis_env.metadata)
                self.assertIn("qgis", qgis_env.metadata["target_modules"])

    def test_windows_discovery(self):
        import platform
        if platform.system().lower() != "windows":
            self.skipTest("Windows discovery only available on Windows")
        discoverer = WindowsDiscoverer()
        envs = list(discoverer.discover())
        self.assertGreater(len(envs), 0, "Expected at least one Windows Python environment to be discovered.")
        py_env = envs[0]
        self.assertEqual(py_env.source_type, "windows_registry")
        self.assertTrue(py_env.executable.exists())
        self.assertNotEqual(py_env.version, "unknown")

    def test_discovery_manager_aggregation(self):
        manager = DiscoveryManager()
        manager.register_strategy(WindowsDiscoverer())
        manager.register_strategy(QgisDiscoverer())
        envs = manager.run_discovery()
        self.assertGreater(len(envs), 0)
        # Verify deduplication by ID
        self.assertEqual(len(envs), len(set(envs.keys())))

    def test_arcpro_discovery_with_custom_path(self):
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            env_dir = tmp / "bin" / "Python" / "envs" / "test-arcgis-env"
            env_dir.mkdir(parents=True)
            (env_dir / "python.exe").write_text("", encoding="utf-8")
            (env_dir / "conda-meta").mkdir()
            discoverer = ArcProDiscoverer(search_paths=[tmp])
            envs = list(discoverer.discover())
            self.assertEqual(len(envs), 1)
            self.assertEqual(envs[0].source_type, "arcpro_adapter")
            self.assertTrue(envs[0].metadata.get("is_conda"))

if __name__ == "__main__":
    unittest.main()
