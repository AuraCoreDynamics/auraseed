"""
Tests for AuraSeed v1.1.0 Toolchain/Embedded Discoverers, Runtime Capability Prober,
Atomic Discovery Cache, Path Sanitization, and Hardened MVenv Packaging/Merging.
"""
import io
import json
import os
import shutil
import sys
import tarfile
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

from auraseed.discovery.adapters.embedded import EmbeddedAppDiscoverer
from auraseed.discovery.adapters.toolchains import ToolchainDiscoverer
from auraseed.discovery.cache import DiscoveryCache
from auraseed.discovery.manager import DiscoveryManager
from auraseed.discovery.prober import (
    RuntimeCapabilityProber,
    is_windows_store_stub,
    sanitize_candidate_path,
)
from auraseed.models import DiscoveredEnvironment
from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest


class TestToolchainsProberAndCache(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = Path(tempfile.mkdtemp(prefix="auraseed_probe_test_"))

    def tearDown(self) -> None:
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _make_fake_python(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"fake-python-binary")
        return path

    def test_toolchain_discoverer_finds_uv_and_pyenv_layouts(self) -> None:
        # Layout 1: uv, pyenv-win / pyenv, and pixi under injectable search_roots
        tc_root = self.temp_dir / "toolchains"
        if sys.platform == "win32":
            uv_exe = self._make_fake_python(tc_root / "uv" / "python" / "cpython-3.12.4-windows-x86_64" / "python.exe")
            pyenv_exe = self._make_fake_python(tc_root / "pyenv-win" / "versions" / "3.11.9" / "python.exe")
            pixi_exe = self._make_fake_python(tc_root / ".pixi" / "envs" / "ml" / "python.exe")
        else:
            uv_exe = self._make_fake_python(tc_root / "uv" / "python" / "cpython-3.12.4-linux-x86_64" / "bin" / "python3")
            pyenv_exe = self._make_fake_python(tc_root / ".pyenv" / "versions" / "3.11.9" / "bin" / "python")
            pixi_exe = self._make_fake_python(tc_root / ".pixi" / "envs" / "ml" / "bin" / "python")

        discoverer = ToolchainDiscoverer(search_roots=[tc_root])
        envs = list(discoverer.discover())
        exe_paths = {Path(e.executable).resolve() for e in envs}
        tools_found = {e.metadata.get("toolchain") for e in envs}

        self.assertIn(uv_exe.resolve(), exe_paths)
        self.assertIn(pyenv_exe.resolve(), exe_paths)
        self.assertIn(pixi_exe.resolve(), exe_paths)
        self.assertTrue({"uv", "pyenv", "pixi"}.issubset(tools_found))

        # Verify EmbeddedAppDiscoverer finds injectable Blender layout too
        emb_root = self.temp_dir / "embedded"
        if sys.platform == "win32":
            blender_exe = self._make_fake_python(
                emb_root / "Blender 4.2" / "4.2" / "python" / "bin" / "python.exe"
            )
        else:
            blender_exe = self._make_fake_python(
                emb_root / "blender-4.2" / "4.2" / "python" / "bin" / "python3"
            )
        emb = EmbeddedAppDiscoverer(search_roots=[emb_root])
        emb_envs = list(emb.discover())
        self.assertTrue(any(Path(e.executable).resolve() == blender_exe.resolve() for e in emb_envs))

    def test_capability_prober_scores_and_caches_interpreter(self) -> None:
        cache_path = self.temp_dir / "discovery_cache.json"
        cache = DiscoveryCache(cache_path)
        prober = RuntimeCapabilityProber(timeout=5.0)

        target_exe = Path(sys.executable).resolve()
        env = DiscoveredEnvironment(
            id=str(target_exe),
            name="Current Test Python",
            executable=target_exe,
            version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
            source_type="test",
            site_packages=[],
            metadata={},
        )

        # Helper static strategy yielding the single real Python
        class _StaticStrategy:
            @property
            def source_type(self) -> str:
                return "test"

            def discover(self):
                yield DiscoveredEnvironment(
                    id=str(target_exe),
                    name="Current Test Python",
                    executable=target_exe,
                    version=env.version,
                    source_type="test",
                    site_packages=[],
                    metadata={},
                )

        mgr = DiscoveryManager()
        mgr.register_strategy(_StaticStrategy())

        # First call must spawn a live subprocess probe (-I)
        first = mgr.run_discovery(
            probe_capabilities=True,
            use_cache=True,
            prober=prober,
            cache=cache,
        )
        self.assertEqual(len(first), 1)
        first_env = next(iter(first.values()))
        self.assertIsNotNone(first_env.capabilities)
        self.assertTrue(first_env.capabilities.has_ssl)
        self.assertTrue(first_env.capabilities.has_sqlite3)
        self.assertTrue(len(first_env.capabilities.abi_tags) >= 1)
        self.assertGreater(first_env.capabilities.composite_score, 0.0)
        self.assertTrue(cache_path.exists())

        # Second call with same exe mtime/size must hit cache without calling subprocess probe
        with mock.patch("auraseed.discovery.prober.subprocess.run") as spy_run:
            second = mgr.run_discovery(
                probe_capabilities=True,
                use_cache=True,
                prober=prober,
                cache=cache,
            )
            spy_run.assert_not_called()

        second_env = next(iter(second.values()))
        self.assertIsNotNone(second_env.capabilities)
        self.assertEqual(
            second_env.capabilities.composite_score,
            first_env.capabilities.composite_score,
        )

    def test_cache_invalidation_on_mtime_change(self) -> None:
        cache_path = self.temp_dir / "cache_mtime.json"
        cache = DiscoveryCache(cache_path)
        fake_py = self._make_fake_python(self.temp_dir / "fake_runtime" / "python.exe")

        class _FakeStrategy:
            @property
            def source_type(self) -> str:
                return "fake"

            def discover(self):
                yield DiscoveredEnvironment(
                    id=str(fake_py.resolve()),
                    name="Fake Python",
                    executable=fake_py.resolve(),
                    version="3.12.1",
                    source_type="fake",
                    site_packages=[],
                    metadata={},
                )

        def fake_subprocess_run(*args, **kwargs):
            del args, kwargs
            proc = mock.Mock()
            proc.returncode = 0
            proc.stdout = json.dumps(
                {
                    "version": "3.12.1",
                    "version_tuple": [3, 12, 1],
                    "architecture": "amd64",
                    "abi_tags": ["cp312-win_amd64"],
                    "modules": {
                        "ssl": True,
                        "sqlite3": True,
                        "ctypes": True,
                        "tkinter": False,
                        "venv": True,
                        "pip": True,
                    },
                    "matched_extra_modules": [],
                    "preinstalled_packages": ["numpy"],
                }
            )
            return proc

        mgr = DiscoveryManager()
        mgr.register_strategy(_FakeStrategy())
        prober = RuntimeCapabilityProber()

        with mock.patch("auraseed.discovery.prober.subprocess.run", side_effect=fake_subprocess_run) as run_mock:
            mgr.run_discovery(probe_capabilities=True, use_cache=True, prober=prober, cache=cache)
            self.assertEqual(run_mock.call_count, 1)

            # Cached hit -> still 1 call
            mgr.run_discovery(probe_capabilities=True, use_cache=True, prober=prober, cache=cache)
            self.assertEqual(run_mock.call_count, 1)

            # Modify binary size / mtime -> invalidates cache entry and re-probes
            time.sleep(0.02)
            fake_py.write_bytes(b"fake-python-binary-v2-updated")
            st = fake_py.stat()
            os.utime(fake_py, ns=(st.st_atime_ns, st.st_mtime_ns + 5_000_000))

            mgr.run_discovery(probe_capabilities=True, use_cache=True, prober=prober, cache=cache)
            self.assertEqual(run_mock.call_count, 2)

    def test_sanitization_windowsapps_stub_and_bundle_security(self) -> None:
        # Traversal path rejected
        self.assertIsNone(sanitize_candidate_path("../../etc/passwd"))
        self.assertIsNone(sanitize_candidate_path("bad\x00path"))

        # 0-byte WindowsApps stub detected
        stub = self.temp_dir / "WindowsApps" / "python.exe"
        stub.parent.mkdir(parents=True, exist_ok=True)
        stub.write_bytes(b"")
        self.assertTrue(is_windows_store_stub(stub))

        # Tar-Slip protection on MvenvManager.import_bundle
        mvenv_root = self.temp_dir / "mvenvs"
        mgr = MvenvManager(mvenv_root)
        malicious_tar = self.temp_dir / "evil.tar.gz"
        with tarfile.open(malicious_tar, "w:gz") as tf:
            info = tarfile.TarInfo(name="../../evil.txt")
            data = b"pwned"
            info.size = len(data)
            tf.addfile(info, io.BytesIO(data))

        with self.assertRaises(ValueError):
            mgr.import_bundle(malicious_tar, target_name="evil-env")

        # Symlink member protection on MvenvManager.import_bundle
        sym_tar = self.temp_dir / "symlink.tar.gz"
        with tarfile.open(sym_tar, "w:gz") as tf:
            info = tarfile.TarInfo(name="evil_link")
            info.type = tarfile.SYMTYPE
            info.linkname = "/etc/passwd"
            tf.addfile(info)

        with self.assertRaises(ValueError):
            mgr.import_bundle(sym_tar, target_name="sym-env")

        # repoint_callback invocation on merge_venvs
        e1 = mgr.create_venv(MvenvCreateRequest(name="src-a", base_python=sys.executable, sovereign=False))
        e2 = mgr.create_venv(MvenvCreateRequest(name="src-b", base_python=sys.executable, sovereign=False))
        self.assertEqual(e1.name, "src-a")
        self.assertEqual(e2.name, "src-b")

        captured = []
        res = mgr.merge_venvs(
            source_names=["src-a", "src-b"],
            target_name="merged-target",
            delete_sources=True,
            repoint_apps=True,
            repoint_callback=lambda srcs, tgt: captured.append((srcs, tgt)) or ["demo-app"],
        )
        self.assertTrue(res["success"])
        self.assertEqual(res["repointed_apps"], ["demo-app"])
        self.assertEqual(captured, [(["src-a", "src-b"], "merged-target")])


if __name__ == "__main__":
    unittest.main()
