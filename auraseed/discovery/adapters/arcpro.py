import os
import sys
import platform
import subprocess
from pathlib import Path
from typing import Iterator, List, Optional, Set
from auraseed.models import DiscoveredEnvironment
from auraseed.discovery.base import BaseDiscoverer

class ArcProDiscoverer(BaseDiscoverer):
    """
    Adapter for ArcGIS Pro Conda/Python environments.
    Probes %LOCALAPPDATA%\\ESRI\\conda\\envs\\*, %PROGRAMFILES%\\ArcGIS\\Pro\\bin\\Python\\envs\\*,
    registry keys, environment variables, and custom search paths.
    """
    def __init__(self, search_paths: Optional[List[Path]] = None):
        self.search_paths = [Path(p) for p in (search_paths or [])]

    @property
    def source_type(self) -> str:
        return "arcpro_adapter"

    def discover(self) -> Iterator[DiscoveredEnvironment]:
        seen_roots: Set[str] = set()
        system = platform.system().lower()

        if system == "windows":
            yield from self._discover_windows(seen_roots)
        elif system == "linux":
            yield from self._discover_posix(seen_roots)
        elif system == "darwin":
            yield from self._discover_posix(seen_roots)

    def _discover_windows(self, seen_roots: Set[str]) -> Iterator[DiscoveredEnvironment]:
        candidates: List[Path] = []

        # 0. Custom search paths supplied explicitly or via environment variable
        for p in self.search_paths:
            if not p.exists():
                continue
            if (p / "python.exe").exists():
                candidates.append(p)
            elif (p / "bin" / "Python" / "envs").exists():
                candidates.extend([c for c in (p / "bin" / "Python" / "envs").iterdir() if c.is_dir()])
            elif (p / "conda" / "envs").exists():
                candidates.extend([c for c in (p / "conda" / "envs").iterdir() if c.is_dir()])
            else:
                candidates.append(p)
                try:
                    candidates.extend([c for c in p.iterdir() if c.is_dir()])
                except OSError:
                    pass

        extra_env = os.environ.get("AURASEED_EXTRA_SEARCH_PATHS")
        if extra_env:
            for piece in extra_env.split(os.pathsep):
                piece_p = Path(piece.strip())
                if piece_p.exists():
                    candidates.append(piece_p)

        # 1. Environment variables
        for env_var in ("ARCGISHOME", "ESRI_CONDA_ENVS", "ARCGIS_PRO_PYTHON"):
            val = os.environ.get(env_var)
            if val:
                p = Path(val)
                if p.is_file() and p.name.lower() == "python.exe":
                    candidates.append(p.parent)
                elif p.is_dir():
                    candidates.append(p)
                    # check sub-envs
                    envs_sub = p / "envs"
                    if envs_sub.exists():
                        candidates.extend([c for c in envs_sub.iterdir() if c.is_dir()])

        # 2. Well-known standard paths
        program_files = os.environ.get("ProgramFiles", r"C:\Program Files")
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        program_data = os.environ.get("ProgramData", r"C:\ProgramData")

        standard_env_dirs = [
            Path(program_files) / "ArcGIS" / "Pro" / "bin" / "Python" / "envs",
            Path(program_data) / "ESRI" / "conda" / "envs",
        ]
        if local_app_data:
            standard_env_dirs.append(Path(local_app_data) / "ESRI" / "conda" / "envs")

        # User home conda envs
        home_conda = Path.home() / ".conda" / "envs"
        if home_conda.exists():
            standard_env_dirs.append(home_conda)

        for env_root in standard_env_dirs:
            if not env_root.exists():
                continue
            if (env_root / "python.exe").exists():
                candidates.append(env_root)
            else:
                try:
                    for child in env_root.iterdir():
                        if not child.is_dir():
                            continue
                        lower_name = child.name.lower()
                        if "arcgis" in lower_name or "arcpro" in lower_name or "esri" in lower_name:
                            candidates.append(child)
                            # check if it contains a conda envs folder
                            sub_envs = child / "conda" / "envs"
                            if sub_envs.exists():
                                candidates.extend([c for c in sub_envs.iterdir() if c.is_dir()])
                            sub_pro_envs = child / "bin" / "Python" / "envs"
                            if sub_pro_envs.exists():
                                candidates.extend([c for c in sub_pro_envs.iterdir() if c.is_dir()])
                        elif (child / "python.exe").exists() and (child / "Lib" / "site-packages").exists():
                            # Check if it has arcgis / arcpy or conda-meta
                            sp = child / "Lib" / "site-packages"
                            if (sp / "arcgis").exists() or (sp / "arcpy").exists():
                                candidates.append(child)
                except (PermissionError, OSError):
                    continue

        # 3. Windows Registry
        try:
            import winreg
            reg_keys = [
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\ESRI\ArcGISPro"),
                (winreg.HKEY_CURRENT_USER, r"SOFTWARE\ESRI\ArcGISPro"),
                (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\ESRI\ArcGISPro"),
            ]
            for hive, key_path in reg_keys:
                try:
                    with winreg.OpenKey(hive, key_path) as key:
                        try:
                            install_dir, _ = winreg.QueryValueEx(key, "InstallDir")
                            if install_dir:
                                pro_envs = Path(install_dir) / "bin" / "Python" / "envs"
                                if pro_envs.exists():
                                    candidates.extend([c for c in pro_envs.iterdir() if c.is_dir()])
                        except OSError:
                            pass
                except OSError:
                    pass
        except ImportError:
            pass

        # Inspect candidates
        seen_exes: Set[str] = set()
        for env_dir in candidates:
            resolved_dir = str(env_dir.resolve()).lower()
            if resolved_dir in seen_roots:
                continue
            seen_roots.add(resolved_dir)

            env = self._inspect_arcpro_env(env_dir)
            if env:
                exe_str = str(env.executable.resolve()).lower()
                if exe_str not in seen_exes:
                    seen_exes.add(exe_str)
                    yield env

    def _inspect_arcpro_env(self, env_dir: Path) -> DiscoveredEnvironment | None:
        if not env_dir.exists():
            return None

        python_exe = env_dir / "python.exe"
        if not python_exe.exists():
            # Check if env_dir is pro root
            sub_exe = env_dir / "bin" / "Python" / "envs" / "arcgispro-py3" / "python.exe"
            if sub_exe.exists():
                python_exe = sub_exe
                env_dir = sub_exe.parent
            else:
                return None

        site_packages = env_dir / "Lib" / "site-packages"
        is_arcpro = False
        lower_path = str(env_dir).lower()
        if "arcgis" in lower_path or "esri" in lower_path or "arcpro" in lower_path:
            is_arcpro = True
        elif site_packages.exists() and ((site_packages / "arcgis").exists() or (site_packages / "arcpy").exists()):
            is_arcpro = True

        if not is_arcpro:
            return None

        # Determine version
        version = "3.11.0"
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

        # Find native binary / library directories
        bin_dirs: List[Path] = []
        for b in (env_dir / "Library" / "bin", env_dir / "bin", env_dir / "DLLs", env_dir / "Scripts"):
            if b.exists():
                bin_dirs.append(b)

        # Pro parent bin if available
        pro_parent = env_dir.parent.parent.parent  # e.g., ArcGIS/Pro
        if (pro_parent / "bin").exists():
            bin_dirs.append(pro_parent / "bin")

        parent_bin = (env_dir / "Library" / "bin") if (env_dir / "Library" / "bin").exists() else env_dir

        is_conda = (env_dir / "conda-meta").exists()

        metadata = {
            "arcpro_env": str(env_dir.resolve()),
            "parent_bin_dir": str(parent_bin.resolve()),
            "bin_dirs": [str(b.resolve()) for b in bin_dirs],
            "target_modules": ["arcgis", "arcpy", "arcgisscripting"],
            "is_conda": is_conda,
        }

        sp_list = [site_packages.resolve()] if site_packages.exists() else []

        return DiscoveredEnvironment(
            id=str(python_exe.resolve()),
            name=f"ArcGIS Pro ({env_dir.name})",
            executable=python_exe.resolve(),
            version=version,
            source_type=self.source_type,
            site_packages=sp_list,
            metadata=metadata
        )

    def _discover_posix(self, seen_roots: Set[str]) -> Iterator[DiscoveredEnvironment]:
        # ArcGIS Pro is Windows-native, but Conda environments with arcgis API can exist on Posix
        conda_envs = Path.home() / ".conda" / "envs"
        if conda_envs.exists():
            for child in conda_envs.iterdir():
                if child.is_dir() and "arcgis" in child.name.lower():
                    py_exe = child / "bin" / "python"
                    if py_exe.exists() and str(py_exe) not in seen_roots:
                        seen_roots.add(str(py_exe))
                        sp = child / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
                        yield DiscoveredEnvironment(
                            id=str(py_exe),
                            name=f"ArcGIS Environment ({child.name})",
                            executable=py_exe,
                            version="3.x",
                            source_type=self.source_type,
                            site_packages=[sp] if sp.exists() else [],
                            metadata={"is_conda": True, "target_modules": ["arcgis"]}
                        )
