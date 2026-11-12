import logging
import os
from pathlib import Path
from typing import Optional

from auraseed.registry.base import BaseOSRegistryAdapter
from auraseed.registry.manager import RegistryManager

_LOG = logging.getLogger(__name__)


def _safe_env_name(env_name: str) -> str:
    cleaned = "".join(c if c.isalnum() or c in "-_" else "_" for c in (env_name or "")).strip("_")
    if not cleaned:
        raise ValueError(f"Invalid environment name: {env_name!r}")
    return cleaned


class LinuxRegistryAdapter(BaseOSRegistryAdapter):
    """
    Linux ~/.config/auraseed/environments.json writer and ~/.local/bin symlinker.
    """

    def __init__(
        self,
        config_dir: Optional[Path] = None,
        bin_dir: Optional[Path] = None,
    ) -> None:
        xdg = os.environ.get("XDG_CONFIG_HOME")
        self.config_dir = Path(config_dir) if config_dir else (
            (Path(xdg) / "auraseed") if xdg else (Path.home() / ".config" / "auraseed")
        )
        self.bin_dir = Path(bin_dir) if bin_dir else (Path.home() / ".local" / "bin")
        self._registry = RegistryManager(self.config_dir)

    def register_environment(self, env_name: str, env_path: str) -> None:
        safe_name = _safe_env_name(env_name)
        resolved_env = str(Path(env_path).resolve())
        manifest = self._registry.read_manifest()
        envs = manifest.setdefault("environments", {})
        if not isinstance(envs, dict):
            envs = {}
            manifest["environments"] = envs
        envs[safe_name] = {
            "path": resolved_env,
            "platform": "linux",
        }
        self._registry.write_manifest(manifest)

        py_target = Path(resolved_env) / "bin" / "python"
        if not py_target.exists():
            py_target = Path(resolved_env) / "bin" / "python3"
        if py_target.exists():
            try:
                self.bin_dir.mkdir(parents=True, exist_ok=True)
                shim_path = self.bin_dir / f"auraseed-{safe_name}"
                shim_content = f'#!/bin/sh\nexec "{py_target}" "$@"\n'
                shim_path.write_text(shim_content, encoding="utf-8")
                os.chmod(shim_path, 0o755)
            except OSError as exc:
                _LOG.warning("Could not create launcher shim in %s: %s", self.bin_dir, exc)

    def unregister_environment(self, env_name: str) -> None:
        safe_name = _safe_env_name(env_name)
        manifest = self._registry.read_manifest()
        envs = manifest.get("environments", {})
        if isinstance(envs, dict) and safe_name in envs:
            del envs[safe_name]
            self._registry.write_manifest(manifest)

        link_path = self.bin_dir / f"auraseed-{safe_name}"
        if link_path.is_symlink() or link_path.exists():
            try:
                link_path.unlink()
            except OSError as exc:
                _LOG.warning("Could not remove symlink %s: %s", link_path, exc)
