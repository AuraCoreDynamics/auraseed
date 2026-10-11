import subprocess
import platform
from pathlib import Path
from typing import List
from auraseed.provision.base import BaseProvisioner

class WheelhouseProvisioner(BaseProvisioner):
    """
    Offline --no-index provisioner for air-gapped systems.
    """
    def __init__(self, wheelhouse_path: Path):
        self.wheelhouse_path = wheelhouse_path

    def install_packages(self, venv_path: Path, packages: List[str]) -> None:
        is_windows = platform.system().lower() == "windows"
        pip_exe = venv_path / "Scripts" / "pip.exe" if is_windows else venv_path / "bin" / "pip"
        
        cmd = [str(pip_exe), "install", "--no-index", f"--find-links={self.wheelhouse_path}"] + packages
        subprocess.run(cmd, check=True, capture_output=True, text=True)
