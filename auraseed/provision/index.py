import subprocess
import platform
from pathlib import Path
from typing import List, Optional
from auraseed.provision.base import BaseProvisioner

class PrivateIndexProvisioner(BaseProvisioner):
    """
    Enterprise mirror --index-url installer.
    """
    def __init__(self, index_url: str, trusted_host: Optional[str] = None, cert: Optional[str] = None):
        self.index_url = index_url
        self.trusted_host = trusted_host
        self.cert = cert

    def install_packages(self, venv_path: Path, packages: List[str]) -> None:
        is_windows = platform.system().lower() == "windows"
        pip_exe = venv_path / "Scripts" / "pip.exe" if is_windows else venv_path / "bin" / "pip"
        
        cmd = [str(pip_exe), "install", f"--index-url={self.index_url}"]
        if self.trusted_host:
            cmd.extend(["--trusted-host", self.trusted_host])
        if self.cert:
            cmd.extend(["--cert", self.cert])
        cmd.extend(packages)
        subprocess.run(cmd, check=True, capture_output=True, text=True)
