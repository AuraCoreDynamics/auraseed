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
        launcher_path = venv_path / "Scripts" / "auraseed-run.cmd"
        content = f"@echo off\r\ncall \"{venv_path / 'Scripts' / 'activate.bat'}\"\r\n%*\r\n"
        with open(launcher_path, "w", encoding="utf-8") as f:
            f.write(content)
    else:
        launcher_path = venv_path / "bin" / "auraseed-run.sh"
        content = f"#!/bin/sh\n. \"{venv_path / 'bin' / 'activate'}\"\nexec \"$@\"\n"
        with open(launcher_path, "w", encoding="utf-8") as f:
            f.write(content)
        launcher_path.chmod(0o755)
