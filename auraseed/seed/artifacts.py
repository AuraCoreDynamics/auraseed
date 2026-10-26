import json
import dataclasses
import platform
from pathlib import Path
from auraseed.models import SeedManifest

def write_seed_manifest(venv_path: Path, manifest: SeedManifest) -> None:
    """
    Generates seed-manifest.json recording selection lineage, default status, and host alternatives.
    """
    manifest_path = venv_path / "seed-manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(dataclasses.asdict(manifest), f, indent=2)

def generate_launchers(venv_path: Path) -> None:
    """
    Generates static .cmd/.sh launcher wrappers (auraseed-run).
    """
    is_windows = platform.system().lower() == "windows"
    if is_windows:
        bin_dir = venv_path / "bin"
        base_dir = venv_path / "base"
        scripts_dir = venv_path / "Scripts"
        activate_bat = scripts_dir / "activate.bat"

        # Update activate.bat to include bin and base in PATH if not present
        if activate_bat.exists():
            try:
                act_content = activate_bat.read_text(encoding="utf-8", errors="ignore")
                path_addition = f'set "PATH={bin_dir};{base_dir};%PATH%"\r\n'
                if str(bin_dir) not in act_content:
                    activate_bat.write_text(path_addition + act_content, encoding="utf-8")
            except Exception:
                pass

        launcher_path = scripts_dir / "auraseed-run.cmd"
        content = (
            "@echo off\r\n"
            f"set \"PATH={bin_dir};{base_dir};{scripts_dir};%PATH%\"\r\n"
            f"if exist \"{activate_bat}\" call \"{activate_bat}\"\r\n"
            f"\"{scripts_dir / 'python.exe'}\" %*\r\n"
        )
        with open(launcher_path, "w", encoding="utf-8") as f:
            f.write(content)

        root_launcher = venv_path / "auraseed-run.cmd"
        root_content = (
            "@echo off\r\n"
            f"call \"{launcher_path}\" %*\r\n"
        )
        with open(root_launcher, "w", encoding="utf-8") as f:
            f.write(root_content)
    else:
        launcher_path = venv_path / "bin" / "auraseed-run.sh"
        content = f"#!/bin/sh\n. \"{venv_path / 'bin' / 'activate'}\"\nexec \"$@\"\n"
        with open(launcher_path, "w", encoding="utf-8") as f:
            f.write(content)
        launcher_path.chmod(0o755)
