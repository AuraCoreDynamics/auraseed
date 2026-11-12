import os
import subprocess
from pathlib import Path
from typing import Iterator, Set
from auraseed.models import DiscoveredEnvironment
from auraseed.discovery.base import BaseDiscoverer
from auraseed.discovery.prober import (
    is_windows_store_stub,
    iter_env_search_paths,
    sanitize_candidate_path,
)

class WindowsDiscoverer(BaseDiscoverer):
    """
    Probes HKCU and HKLM under Software\\Python\\PythonCore per PEP 514 specs.
    Scans System and User %PATH% entries.
    Probes default installation paths (C:\\Python*, %LOCALAPPDATA%\\Programs\\Python).
    """
    @property
    def source_type(self) -> str:
        return "windows_registry"

    def discover(self) -> Iterator[DiscoveredEnvironment]:
        seen_paths: Set[str] = set()

        # 1. PEP 514 Registry Scans (64-bit and 32-bit views)
        try:
            import winreg
            hives = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
            flags_list = [0]
            if hasattr(winreg, "KEY_WOW64_64KEY"):
                flags_list.append(winreg.KEY_WOW64_64KEY)
            if hasattr(winreg, "KEY_WOW64_32KEY"):
                flags_list.append(winreg.KEY_WOW64_32KEY)

            for hive in hives:
                for flags in flags_list:
                    access = winreg.KEY_READ | flags
                    try:
                        key = winreg.OpenKey(hive, r"Software\Python\PythonCore", 0, access)
                        num_subkeys = winreg.QueryInfoKey(key)[0]
                        for i in range(num_subkeys):
                            version_key_name = winreg.EnumKey(key, i)
                            try:
                                version_key = winreg.OpenKey(key, version_key_name, 0, access)
                                install_path_key = winreg.OpenKey(version_key, "InstallPath", 0, access)
                                install_path = winreg.QueryValue(install_path_key, None)
                                if not install_path:
                                    continue
                                executable = Path(install_path) / "python.exe"
                                if not executable.exists():
                                    continue
                                exe_str = str(executable.resolve()).lower()
                                if exe_str not in seen_paths:
                                    seen_paths.add(exe_str)
                                    # Determine semantic version (PEP 514 subkeys can be tags like AuraSeedBootstrapped or 3.12-64)
                                    resolved_version = version_key_name.split("-")[0].strip()
                                    if not resolved_version or not resolved_version[0].isdigit():
                                        for reg_val in ("Version", "SysVersion"):
                                            try:
                                                v, _ = winreg.QueryValueEx(version_key, reg_val)
                                                if v and str(v)[0].isdigit():
                                                    resolved_version = str(v).split("-")[0].strip()
                                                    break
                                            except OSError:
                                                pass
                                    if not resolved_version or not resolved_version[0].isdigit():
                                        try:
                                            ver_res = subprocess.run(
                                                [str(executable), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')"],
                                                capture_output=True,
                                                text=True,
                                                timeout=3
                                            )
                                            if ver_res.returncode == 0 and ver_res.stdout.strip():
                                                resolved_version = ver_res.stdout.strip()
                                        except Exception:
                                            pass

                                    site_packages = Path(install_path) / "Lib" / "site-packages"
                                    bin_dirs = [Path(install_path)]
                                    if (Path(install_path) / "DLLs").exists():
                                        bin_dirs.append(Path(install_path) / "DLLs")
                                    if (Path(install_path) / "Library" / "bin").exists():
                                        bin_dirs.append(Path(install_path) / "Library" / "bin")
                                    yield DiscoveredEnvironment(
                                        id=str(executable.resolve()),
                                        name=f"Python {resolved_version} ({version_key_name})" if resolved_version != version_key_name else f"Python {version_key_name} (Registry)",
                                        executable=executable.resolve(),
                                        version=resolved_version,
                                        source_type=self.source_type,
                                        site_packages=[site_packages] if site_packages.exists() else [],
                                        metadata={
                                            "registry_tag": version_key_name,
                                            "hive": "HKCU" if hive == winreg.HKEY_CURRENT_USER else "HKLM",
                                            "parent_bin_dir": str(Path(install_path).resolve()),
                                            "bin_dirs": [str(b.resolve()) for b in bin_dirs]
                                        }
                                    )
                            except OSError:
                                continue
                    except OSError:
                        continue
        except ImportError:
            pass

        # 2. Environmental Variables and Standard Fallbacks
        env_paths = []
        for py_home in iter_env_search_paths(("PYTHONHOME",)):
            env_paths.append(py_home / "python.exe")

        for p_dir in iter_env_search_paths(("PATH",)):
            env_paths.append(p_dir / "python.exe")

        local_app_data = os.environ.get("LOCALAPPDATA", "")
        local_app_path = sanitize_candidate_path(local_app_data) if local_app_data else None
        if local_app_path is not None:
            programs_python = local_app_path / "Programs" / "Python"
            if programs_python.exists():
                for d in programs_python.iterdir():
                    if d.is_dir() and d.name.lower().startswith("python"):
                        env_paths.append(d / "python.exe")

        # Standard C:\ root python installations
        try:
            for root_dir in Path("C:/").glob("Python*"):
                if root_dir.is_dir():
                    env_paths.append(root_dir / "python.exe")
            for prog_dir in Path("C:/Program Files").glob("Python*"):
                if prog_dir.is_dir():
                    env_paths.append(prog_dir / "python.exe")
        except (PermissionError, OSError):
            pass

        for exe in env_paths:
            try:
                if exe.exists() and exe.is_file():
                    if is_windows_store_stub(exe):
                        continue

                    exe_str = str(exe.resolve()).lower()
                    if exe_str not in seen_paths:
                        seen_paths.add(exe_str)

                        # Determine version
                        version = "unknown"
                        # Try parsing from directory name (e.g. Python314 -> 3.14.0)
                        digits = "".join([c for c in exe.parent.name if c.isdigit()])
                        if len(digits) >= 2:
                            version = f"3.{digits[1:]}.0" if digits.startswith("3") else f"{digits[0]}.{digits[1:]}.0"
                        else:
                            try:
                                res = subprocess.run(
                                    [str(exe), "-c", "import sys; print(f'{sys.version_info[0]}.{sys.version_info[1]}.{sys.version_info[2]}')"],
                                    capture_output=True,
                                    text=True,
                                    timeout=3
                                )
                                if res.returncode == 0 and res.stdout.strip():
                                    version = res.stdout.strip()
                            except Exception:
                                pass

                        site_packages = exe.parent / "Lib" / "site-packages"
                        bin_dirs = [exe.parent]
                        if (exe.parent / "DLLs").exists():
                            bin_dirs.append(exe.parent / "DLLs")
                        if (exe.parent / "Library" / "bin").exists():
                            bin_dirs.append(exe.parent / "Library" / "bin")

                        yield DiscoveredEnvironment(
                            id=str(exe.resolve()),
                            name=f"Python {version} ({exe.parent.name})",
                            executable=exe.resolve(),
                            version=version,
                            source_type=self.source_type,
                            site_packages=[site_packages] if site_packages.exists() else [],
                            metadata={
                                "source": "env_or_path",
                                "parent_bin_dir": str(exe.parent.resolve()),
                                "bin_dirs": [str(b.resolve()) for b in bin_dirs]
                            }
                        )
            except (PermissionError, OSError):
                continue
