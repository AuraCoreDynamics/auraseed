import sys
import shutil
import platform
import subprocess
from pathlib import Path
from auraseed.models import DiscoveredEnvironment

class SovereignVenvEngine:
    """
    Builds a virtual environment structure using low-level target interpreter
    subprocess calls or resilient fallback scaffold for embedded/conda distributions.
    """
    def create_venv(self, target_env: DiscoveredEnvironment, destination_path: Path) -> None:
        """
        Executes standard venv creation or constructs environment scaffold.
        """
        if not target_env.executable.exists():
            raise FileNotFoundError(f"Target executable not found: {target_env.executable}")

        destination_path = destination_path.resolve()
        destination_path.mkdir(parents=True, exist_ok=True)

        is_win = platform.system().lower() == "windows"
        scripts_dir = destination_path / "Scripts" if is_win else destination_path / "bin"
        lib_dir = destination_path / "Lib" / "site-packages" if is_win else destination_path / "lib" / "python3" / "site-packages"

        # Try standard python -m venv first
        venv_created = False
        try:
            cmd = [
                str(target_env.executable),
                "-m",
                "venv",
                "--system-site-packages",
                "--without-pip",
                str(destination_path)
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
            if res.returncode == 0:
                venv_created = True
        except Exception:
            venv_created = False

        if not venv_created:
            # Fallback scaffold for Conda, embedded, or thick-client runtimes where venv module is absent
            scripts_dir.mkdir(parents=True, exist_ok=True)
            lib_dir.mkdir(parents=True, exist_ok=True)
            (destination_path / "Include").mkdir(parents=True, exist_ok=True)

            target_exe_dest = scripts_dir / target_env.executable.name
            if not target_exe_dest.exists():
                shutil.copy2(target_env.executable, target_exe_dest)

            # Write basic pyvenv.cfg
            cfg_path = destination_path / "pyvenv.cfg"
            cfg_content = (
                f"home = {target_env.executable.parent}\n"
                f"include-system-site-packages = true\n"
                f"version = {target_env.version}\n"
                f"executable = {target_env.executable}\n"
            )
            cfg_path.write_text(cfg_content, encoding="utf-8")
