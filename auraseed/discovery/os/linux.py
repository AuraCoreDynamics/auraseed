import os
from pathlib import Path
from typing import Iterator, Set
from auraseed.models import DiscoveredEnvironment
from auraseed.discovery.base import BaseDiscoverer

class LinuxDiscoverer(BaseDiscoverer):
    """
    Scans /usr/bin, /usr/local/bin, ~/.local/bin.
    Scans ~/.pyenv/versions/* and ~/miniconda3/envs/*.
    """
    @property
    def source_type(self) -> str:
        return "linux_system"

    def discover(self) -> Iterator[DiscoveredEnvironment]:
        seen_paths: Set[str] = set()
        search_paths = []
        
        # 1. Environment Variables
        if "PYTHONHOME" in os.environ:
            search_paths.append(Path(os.environ["PYTHONHOME"]) / "bin" / "python3")
            search_paths.append(Path(os.environ["PYTHONHOME"]) / "bin" / "python")
            
        path_var = os.environ.get("PATH", "")
        for p in path_var.split(os.pathsep):
            search_paths.append(Path(p) / "python3")
            search_paths.append(Path(p) / "python")
            
        # 2. Common Linux Install paths
        common_dirs = [
            Path("/usr/bin"),
            Path("/usr/local/bin"),
            Path.home() / ".local" / "bin"
        ]
        for d in common_dirs:
            search_paths.append(d / "python3")
            search_paths.append(d / "python")

        # 3. Pyenv & Conda standard locations
        pyenv_root = Path.home() / ".pyenv" / "versions"
        if pyenv_root.exists():
            for d in pyenv_root.iterdir():
                if d.is_dir():
                    search_paths.append(d / "bin" / "python")
                    
        conda_roots = [Path.home() / "miniconda3", Path.home() / "anaconda3"]
        for c in conda_roots:
            if c.exists():
                search_paths.append(c / "bin" / "python")
                envs_dir = c / "envs"
                if envs_dir.exists():
                    for d in envs_dir.iterdir():
                        if d.is_dir():
                            search_paths.append(d / "bin" / "python")
                            
        for exe in search_paths:
            if exe.exists() and exe.is_file():
                exe_str = str(exe)
                if exe_str not in seen_paths:
                    seen_paths.add(exe_str)
                    
                    # Try to guess site packages
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
                        name="Python (Linux System/Env)",
                        executable=exe,
                        version="unknown",
                        source_type=self.source_type,
                        site_packages=site_packages,
                        metadata={"source": "system"}
                    )
