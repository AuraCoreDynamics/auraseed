import os
from pathlib import Path
from typing import Iterator, Set
from auraseed.models import DiscoveredEnvironment
from auraseed.discovery.base import BaseDiscoverer

class WindowsDiscoverer(BaseDiscoverer):
    """
    Probes HKCU and HKLM under Software\\Python\\PythonCore per PEP 514 specs.
    Scans System and User %PATH% entries.
    Probes default installation paths.
    """
    @property
    def source_type(self) -> str:
        return "windows_registry"

    def discover(self) -> Iterator[DiscoveredEnvironment]:
        seen_paths: Set[str] = set()

        # 1. Minimal PEP 514
        try:
            import winreg
            hives = [winreg.HKEY_CURRENT_USER, winreg.HKEY_LOCAL_MACHINE]
            for hive in hives:
                try:
                    key = winreg.OpenKey(hive, r"Software\Python\PythonCore")
                    for i in range(winreg.QueryInfoKey(key)[0]):
                        version_key_name = winreg.EnumKey(key, i)
                        try:
                            version_key = winreg.OpenKey(key, version_key_name)
                            install_path_key = winreg.OpenKey(version_key, "InstallPath")
                            install_path = winreg.QueryValue(install_path_key, None)
                            executable = Path(install_path) / "python.exe"
                            if executable.exists() and str(executable).lower() not in seen_paths:
                                seen_paths.add(str(executable).lower())
                                yield DiscoveredEnvironment(
                                    id=str(executable),
                                    name=f"Python {version_key_name} (Registry)",
                                    executable=executable,
                                    version=version_key_name,
                                    source_type=self.source_type,
                                    site_packages=[Path(install_path) / "Lib" / "site-packages"],
                                    metadata={"hive": "HKCU" if hive == winreg.HKEY_CURRENT_USER else "HKLM"}
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
            env_paths.append(Path(p) / "python.exe")
            
        local_app_data = os.environ.get("LOCALAPPDATA", "")
        if local_app_data:
            programs_python = Path(local_app_data) / "Programs" / "Python"
            if programs_python.exists():
                for d in programs_python.iterdir():
                    if d.is_dir() and d.name.lower().startswith("python"):
                        env_paths.append(d / "python.exe")

        for exe in env_paths:
            if exe.exists() and exe.is_file():
                exe_str = str(exe).lower()
                if exe_str not in seen_paths:
                    seen_paths.add(exe_str)
                    yield DiscoveredEnvironment(
                        id=str(exe),
                        name="Python (Path/Env)",
                        executable=exe,
                        version="unknown",
                        source_type=self.source_type,
                        site_packages=[exe.parent / "Lib" / "site-packages"],
                        metadata={"source": "env_path"}
                    )
