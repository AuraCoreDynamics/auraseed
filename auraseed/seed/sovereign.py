import subprocess
from pathlib import Path
from auraseed.models import DiscoveredEnvironment

class SovereignVenvEngine:
    """
    Builds a venv using low-level target interpreter subprocess calls.
    """
    def create_venv(self, target_env: DiscoveredEnvironment, destination_path: Path) -> None:
        """
        Executes: [target_executable, "-m", "venv", "--system-site-packages", destination_path]
        """
        if not target_env.executable.exists():
            raise FileNotFoundError(f"Target executable not found: {target_env.executable}")

        cmd = [
            str(target_env.executable),
            "-m",
            "venv",
            "--system-site-packages",
            str(destination_path)
        ]
        subprocess.run(cmd, check=True, capture_output=True, text=True)
