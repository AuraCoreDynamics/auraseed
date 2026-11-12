from pathlib import Path
from typing import Iterator, Set
from auraseed.models import DiscoveredEnvironment
from auraseed.discovery.base import BaseDiscoverer
from auraseed.discovery.prober import iter_env_search_paths

class MacOSDiscoverer(BaseDiscoverer):
    """
    Scans Homebrew prefix paths.
    Scans /Library/Frameworks/Python.framework/Versions/* and /Applications/*.
    """
    @property
    def source_type(self) -> str:
        return "macos_system"

    def discover(self) -> Iterator[DiscoveredEnvironment]:
        seen_paths: Set[str] = set()
        search_paths = []
        
        # 1. Environment Variables
        for py_home in iter_env_search_paths(("PYTHONHOME",)):
            search_paths.append(py_home / "bin" / "python3")

        for p_dir in iter_env_search_paths(("PATH",)):
            search_paths.append(p_dir / "python3")
            search_paths.append(p_dir / "python")
            
        # 2. Homebrew and Frameworks
        common_dirs = [
            Path("/opt/homebrew/bin"),
            Path("/usr/local/bin"),
            Path("/usr/bin")
        ]
        for d in common_dirs:
            search_paths.append(d / "python3")
            search_paths.append(d / "python")
            
        frameworks_root = Path("/Library/Frameworks/Python.framework/Versions")
        if frameworks_root.exists():
            for version_dir in frameworks_root.iterdir():
                if version_dir.is_dir():
                    search_paths.append(version_dir / "bin" / "python3")
                    
        for exe in search_paths:
            if exe.exists() and exe.is_file():
                exe_str = str(exe)
                if exe_str not in seen_paths:
                    seen_paths.add(exe_str)
                    
                    lib_dir = exe.parent.parent / "lib"
                    site_packages = []
                    if lib_dir.exists():
                        for py_dir in lib_dir.iterdir():
                            if py_dir.is_dir() and py_dir.name.startswith("python"):
                                sp = py_dir / "site-packages"
                                if sp.exists():
                                    site_packages.append(sp)

                    yield DiscoveredEnvironment(
                        id=exe_str,
                        name="Python (macOS System/Env)",
                        executable=exe,
                        version="unknown",
                        source_type=self.source_type,
                        site_packages=site_packages,
                        metadata={"source": "system"}
                    )
