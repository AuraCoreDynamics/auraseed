import os
import sys
import subprocess
from pathlib import Path
from typing import Iterator, Set
from auraseed.models import DiscoveredEnvironment
from auraseed.discovery.base import BaseDiscoverer

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
                                exe_str = str(executable.resolve()).lower()
                                if executable.exists() and exe_str not in seen_paths:
                                    seen_paths.add(exe_str)
                                    site_packages = Path(install_path) / "Lib" / "site-packages"
                                    bin_dirs = [Path(install_path)]
                                    if (Path(install_path) / "DLLs").exists():
                                        bin_dirs.append(Path(install_path) / "DLLs")
                                    yield DiscoveredEnvironment(
                                        id=str(executable.resolve()),
                                        name=f"Python {version_key_name} (Registry)",
                                        executable=executable.resolve(),
                                        version=version_key_name,
                                        source_type=self.source_type,
                                        site_packages=[site_packages] if site_packages.exists() else [],
                                        metadata={
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
        if "PYTHONHOME" in os.environ:
            env_paths.append(Path(os.environ["PYTHONHOME"]) / "python.exe")

        path_var = os.environ.get("PATH", "")
        for p in path_var.split(os.pathsep):
            if p.strip():
                env_paths.append(Path(p.strip()) / "python.exe")

        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            programs_python = Path(local_app_data) / "Programs" / "Python"
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
                    # Skip WindowsApps 0-byte execution aliases if empty
                    if "windowsapps" in str(exe).lower():
                        try:
                            if exe.stat().st_size == 0:
                                continue
                        except OSError:
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
