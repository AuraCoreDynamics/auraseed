import os
import sys
import platform
import subprocess
from pathlib import Path
from typing import Iterator, List, Optional, Set
from auraseed.models import DiscoveredEnvironment
from auraseed.discovery.base import BaseDiscoverer

class QgisDiscoverer(BaseDiscoverer):
    """
    Adapter for QGIS embedded Python environments.
    Probes standard paths, registry, and environment variables across Windows, macOS, and Linux.
    """
    def __init__(self, search_paths: Optional[List[Path]] = None):
        self.search_paths = [Path(p) for p in (search_paths or [])]

    @property
    def source_type(self) -> str:
        return "qgis_adapter"

    def discover(self) -> Iterator[DiscoveredEnvironment]:
        seen_roots: Set[str] = set()
        system = platform.system().lower()

        if system == "windows":
            yield from self._discover_windows(seen_roots)
        elif system == "linux":
            yield from self._discover_linux(seen_roots)
        elif system == "darwin":
            yield from self._discover_macos(seen_roots)

    def _discover_windows(self, seen_roots: Set[str]) -> Iterator[DiscoveredEnvironment]:
        candidates: List[Path] = []

        # 0. Custom search paths supplied explicitly or via environment variable
        for p in self.search_paths:
            if p.exists():
                candidates.append(p)

        extra_env = os.environ.get("AURASEED_EXTRA_SEARCH_PATHS")
        if extra_env:
            for piece in extra_env.split(os.pathsep):
                piece_p = Path(piece.strip())
                if piece_p.exists():
                    candidates.append(piece_p)

        # 1. Environment variables
        for env_var in ("QGIS_PREFIX_PATH", "OSGEO4W_ROOT"):
            val = os.environ.get(env_var)
            if val:
                p = Path(val)
                if (p / "bin").exists() or (p.parent / "bin").exists():
                    candidates.append(p if (p / "bin").exists() else p.parent)

        # 2. Well-known directories
        search_dirs = [
            Path("C:/Program Files"),
            Path("C:/Program Files (x86)"),
            Path("C:/OSGeo4W"),
            Path("C:/OSGeo4W64"),
        ]
        local_app_data = os.environ.get("LOCALAPPDATA")
        if local_app_data:
            search_dirs.append(Path(local_app_data) / "Programs")

        for sdir in search_dirs:
            if not sdir.exists():
                continue
            if sdir.name in ("OSGeo4W", "OSGeo4W64") and (sdir / "bin").exists():
                candidates.append(sdir)
            else:
                try:
                    for child in sdir.iterdir():
                        if not child.is_dir():
                            continue
                        lower_name = child.name.lower()
                        if "qgis" in lower_name or "osgeo4w" in lower_name:
                            candidates.append(child)
                except (PermissionError, OSError):
                    continue

        # 3. Windows Registry (Uninstall & OSGeo4W)
        try:
            import winreg
            uninstall_paths = [
                r"SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
                r"SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall",
            ]
            for hive in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
                for uninst in uninstall_paths:
                    try:
                        with winreg.OpenKey(hive, uninst) as key:
                            num_subkeys = winreg.QueryInfoKey(key)[0]
                            for i in range(num_subkeys):
                                try:
                                    subkey_name = winreg.EnumKey(key, i)
                                    with winreg.OpenKey(key, subkey_name) as subkey:
                                        try:
                                            disp_name, _ = winreg.QueryValueEx(subkey, "DisplayName")
                                            if "qgis" in str(disp_name).lower():
                                                loc, _ = winreg.QueryValueEx(subkey, "InstallLocation")
                                                if loc and Path(loc).exists():
                                                    candidates.append(Path(loc))
                                        except OSError:
                                            pass
                                except OSError:
                                    continue
                    except OSError:
                        pass
        except ImportError:
            pass

        # Evaluate each candidate root
        for root in candidates:
            resolved_root = str(root.resolve()).lower()
            if resolved_root in seen_roots:
                continue
            seen_roots.add(resolved_root)

            env = self._inspect_windows_qgis_root(root)
            if env:
                yield env

    def _inspect_windows_qgis_root(self, root: Path) -> DiscoveredEnvironment | None:
        if not root.exists():
            return None

        # Python executable search order:
        # 1. apps/Python3*/python.exe
        # 2. bin/python.exe
        # 3. python.exe
        python_exe = None
        version_hint = "3.12.0"
        py_apps = root / "apps"
        if py_apps.exists():
            for item in py_apps.iterdir():
                if item.is_dir() and item.name.lower().startswith("python"):
                    candidate_exe = item / "python.exe"
                    if candidate_exe.exists():
                        python_exe = candidate_exe
                        # Extract version hint from directory name (e.g. Python312 -> 3.12.0)
                        digits = "".join([c for c in item.name if c.isdigit()])
                        if len(digits) >= 2:
                            version_hint = f"3.{digits[1:]}.0" if digits.startswith("3") else f"{digits[0]}.{digits[1:]}.0"
                        break

        if not python_exe:
            if (root / "bin" / "python.exe").exists():
                python_exe = root / "bin" / "python.exe"
            elif (root / "python.exe").exists():
                python_exe = root / "python.exe"

        if not python_exe or not python_exe.exists():
            return None

        # Extract precise version if possible
        version = version_hint
        try:
            res = subprocess.run(
                [str(python_exe), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')"],
                capture_output=True,
                text=True,
                timeout=5
            )
            if res.returncode == 0 and res.stdout.strip():
                version = res.stdout.strip()
        except Exception:
            pass

        # Identify site-packages and QGIS module paths
        site_packages: List[Path] = []
        extra_paths: List[Path] = []
        py_parent = python_exe.parent
        if (py_parent / "Lib" / "site-packages").exists():
            site_packages.append(py_parent / "Lib" / "site-packages")
        elif (root / "Lib" / "site-packages").exists():
            site_packages.append(root / "Lib" / "site-packages")

        # QGIS python modules are located under apps/qgis*/python or python
        if py_apps.exists():
            for item in py_apps.iterdir():
                if item.is_dir() and "qgis" in item.name.lower():
                    qgis_py = item / "python"
                    if qgis_py.exists():
                        extra_paths.append(qgis_py)
                        site_packages.append(qgis_py)

        if (root / "python").exists() and (root / "python" / "qgis").exists():
            extra_paths.append(root / "python")
            site_packages.append(root / "python")

        # Native binary directories containing dependent DLLs
        bin_dirs: List[Path] = []
        if (root / "bin").exists():
            bin_dirs.append(root / "bin")
        if (py_parent / "DLLs").exists():
            bin_dirs.append(py_parent / "DLLs")
        if py_apps.exists():
            for item in py_apps.iterdir():
                if item.is_dir():
                    bin_dir = item / "bin"
                    if bin_dir.exists():
                        bin_dirs.append(bin_dir)

        # Assets: Qt plugins, QGIS providers, GDAL data, PROJ data
        qt_plugins_dir = None
        if (py_apps / "Qt5" / "plugins").exists():
            qt_plugins_dir = py_apps / "Qt5" / "plugins"
        elif (root / "apps" / "Qt5" / "plugins").exists():
            qt_plugins_dir = root / "apps" / "Qt5" / "plugins"
        elif (root / "qtplugins").exists():
            qt_plugins_dir = root / "qtplugins"

        qgis_plugins_dir = None
        if py_apps.exists():
            for item in py_apps.iterdir():
                if item.is_dir() and "qgis" in item.name.lower() and (item / "plugins").exists():
                    qgis_plugins_dir = item / "plugins"
                    break
        if not qgis_plugins_dir and (root / "plugins").exists():
            qgis_plugins_dir = root / "plugins"

        gdal_data_dir = None
        if (py_apps / "gdal" / "share" / "gdal").exists():
            gdal_data_dir = py_apps / "gdal" / "share" / "gdal"
        elif (root / "share" / "gdal").exists():
            gdal_data_dir = root / "share" / "gdal"

        proj_data_dir = None
        if (root / "share" / "proj").exists():
            proj_data_dir = root / "share" / "proj"
        elif (py_apps / "proj" / "share" / "proj").exists():
            proj_data_dir = py_apps / "proj" / "share" / "proj"

        qgis_prefix_path = None
        if py_apps.exists():
            for item in py_apps.iterdir():
                if item.is_dir() and "qgis" in item.name.lower():
                    qgis_prefix_path = item
                    break
        if not qgis_prefix_path and (root / "bin").exists():
            qgis_prefix_path = root

        metadata = {
            "qgis_root": str(root.resolve()),
            "parent_bin_dir": str((root / "bin").resolve()) if (root / "bin").exists() else str(py_parent.resolve()),
            "bin_dirs": [str(b.resolve()) for b in bin_dirs],
            "target_modules": ["qgis", "PyQt5", "osgeo", "osgeo_utils"],
            "extra_paths": [str(p.resolve()) for p in extra_paths],
            "qt_plugins_dir": str(qt_plugins_dir.resolve()) if qt_plugins_dir else None,
            "qgis_plugins_dir": str(qgis_plugins_dir.resolve()) if qgis_plugins_dir else None,
            "gdal_data_dir": str(gdal_data_dir.resolve()) if gdal_data_dir else None,
            "proj_data_dir": str(proj_data_dir.resolve()) if proj_data_dir else None,
            "qgis_prefix_path": str(qgis_prefix_path.resolve()) if qgis_prefix_path else None,
        }

        return DiscoveredEnvironment(
            id=str(python_exe.resolve()),
            name=f"QGIS ({root.name})",
            executable=python_exe.resolve(),
            version=version,
            source_type=self.source_type,
            site_packages=site_packages,
            metadata=metadata
        )

    def _discover_linux(self, seen_roots: Set[str]) -> Iterator[DiscoveredEnvironment]:
        qgis_bin = Path("/usr/bin/qgis")
        if qgis_bin.exists():
            py_bin = Path("/usr/bin/python3")
            if py_bin.exists() and str(py_bin) not in seen_roots:
                seen_roots.add(str(py_bin))
                yield DiscoveredEnvironment(
                    id=str(py_bin),
                    name="QGIS (System Linux)",
                    executable=py_bin,
                    version="3.x",
                    source_type=self.source_type,
                    site_packages=[Path("/usr/share/qgis/python"), Path("/usr/lib/python3/dist-packages")],
                    metadata={"target_modules": ["qgis", "PyQt5"]}
                )

    def _discover_macos(self, seen_roots: Set[str]) -> Iterator[DiscoveredEnvironment]:
        app_dirs = [Path("/Applications"), Path.home() / "Applications"]
        for ad in app_dirs:
            if not ad.exists():
                continue
            for app in ad.glob("QGIS*.app"):
                py_bin = app / "Contents" / "MacOS" / "bin" / "python3"
                if py_bin.exists() and str(py_bin) not in seen_roots:
                    seen_roots.add(str(py_bin))
                    yield DiscoveredEnvironment(
                        id=str(py_bin),
                        name=f"QGIS ({app.stem})",
                        executable=py_bin,
                        version="3.x",
                        source_type=self.source_type,
                        site_packages=[app / "Contents" / "Resources" / "python"],
                        metadata={"target_modules": ["qgis", "PyQt5"]}
                    )
