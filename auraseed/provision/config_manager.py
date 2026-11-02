"""
Zero-dependency Pip and Conda User Configuration Manager.
Reads repository and proxy settings from bootstrap.json and configures user files:
  - pip: %APPDATA%/pip/pip.ini (Windows) or ~/.config/pip/pip.conf (Linux/macOS)
  - conda: ~/.condarc
"""
import os
import sys
import json
import shutil
import platform
from pathlib import Path
from datetime import datetime
from typing import Dict, Any, Optional, List


def get_pip_config_path() -> Path:
    sys_plat = platform.system().lower()
    if sys_plat == "windows":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "pip" / "pip.ini"
        return Path.home() / "pip" / "pip.ini"
    elif sys_plat == "darwin":
        return Path.home() / "Library" / "Application Support" / "pip" / "pip.conf"
    else:
        # Linux / XDG
        xdg_config = os.environ.get("XDG_CONFIG_HOME")
        if xdg_config:
            return Path(xdg_config) / "pip" / "pip.conf"
        return Path.home() / ".config" / "pip" / "pip.conf"


def get_conda_config_path() -> Path:
    return Path.home() / ".condarc"


def generate_pip_ini(pip_cfg: Dict[str, Any]) -> str:
    lines = ["[global]"]
    index_url = pip_cfg.get("index_url", "").strip()
    if index_url:
        lines.append(f"index-url = {index_url}")

    extra_urls = pip_cfg.get("extra_index_urls", [])
    if extra_urls:
        if isinstance(extra_urls, list):
            for u in extra_urls:
                if u.strip():
                    lines.append(f"extra-index-url = {u.strip()}")
        elif isinstance(extra_urls, str) and extra_urls.strip():
            lines.append(f"extra-index-url = {extra_urls.strip()}")

    trusted_hosts = pip_cfg.get("trusted_hosts", [])
    if trusted_hosts:
        if isinstance(trusted_hosts, list):
            for h in trusted_hosts:
                if h.strip():
                    lines.append(f"trusted-host = {h.strip()}")
        elif isinstance(trusted_hosts, str) and trusted_hosts.strip():
            lines.append(f"trusted-host = {trusted_hosts.strip()}")

    proxy = pip_cfg.get("proxy", "").strip()
    if proxy:
        lines.append(f"proxy = {proxy}")

    lines.append("")
    return "\n".join(lines)


def generate_condarc(conda_cfg: Dict[str, Any]) -> str:
    lines = []
    channels = conda_cfg.get("channels", [])
    if channels and isinstance(channels, list):
        lines.append("channels:")
        for ch in channels:
            if ch.strip():
                lines.append(f"  - {ch.strip()}")

    default_channels = conda_cfg.get("default_channels", [])
    if default_channels and isinstance(default_channels, list):
        lines.append("default_channels:")
        for ch in default_channels:
            if ch.strip():
                lines.append(f"  - {ch.strip()}")

    proxy_servers = conda_cfg.get("proxy_servers", {})
    if isinstance(proxy_servers, dict):
        p_lines = []
        for proto in ("http", "https"):
            val = proxy_servers.get(proto, "").strip()
            if val:
                p_lines.append(f"  {proto}: {val}")
        if p_lines:
            lines.append("proxy_servers:")
            lines.extend(p_lines)

    ssl_verify = conda_cfg.get("ssl_verify")
    if ssl_verify is not None:
        if isinstance(ssl_verify, bool):
            lines.append(f"ssl_verify: {'true' if ssl_verify else 'false'}")
        elif isinstance(ssl_verify, str) and ssl_verify.strip():
            lines.append(f"ssl_verify: {ssl_verify.strip()}")

    lines.append("")
    return "\n".join(lines)


def prompt_user_update(filepath: Path) -> bool:
    """
    Asks the user interactively if they want to update an existing configuration file.
    Defaults to Yes if running non-interactively or in unattended environment.
    """
    if not sys.stdin.isatty():
        # Non-interactive fallback
        return True
    
    try:
        reply = input(f"[AuraSeed] Configuration file '{filepath}' already exists. Overwrite/update? [Y/n]: ").strip().lower()
        if reply in ("", "y", "yes"):
            return True
        return False
    except (EOFError, KeyboardInterrupt):
        return False


def backup_file(filepath: Path) -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = filepath.with_name(f"{filepath.name}.bak_{timestamp}")
    shutil.copy2(filepath, backup_path)
    return backup_path


def apply_user_configs(config_file: Optional[Path] = None, auto_yes: bool = False) -> Dict[str, Any]:
    if config_file is None:
        config_path_str = os.environ.get("AURASEED_BOOTSTRAP_CONFIG")
        if config_path_str:
            config_file = Path(config_path_str)
        else:
            # Check repository root (two levels up from auraseed/provision/config_manager.py)
            repo_root = Path(__file__).resolve().parent.parent.parent
            config_file = repo_root / "bootstrap.json"
            if not config_file.exists():
                # Or current working directory
                cwd_config = Path.cwd() / "bootstrap.json"
                if cwd_config.exists():
                    config_file = cwd_config

    if not config_file.exists():
        return {"status": "skipped", "reason": f"Config not found at {config_file}"}

    with open(config_file, "r", encoding="utf-8") as f:
        data = json.load(f)

    results = {}

    # 1. Pip configuration
    pip_cfg = data.get("pip", {})
    has_pip_settings = any([
        pip_cfg.get("index_url"),
        pip_cfg.get("extra_index_urls"),
        pip_cfg.get("trusted_hosts"),
        pip_cfg.get("proxy")
    ])

    if has_pip_settings:
        pip_file = get_pip_config_path()
        content = generate_pip_ini(pip_cfg)
        if pip_file.exists():
            should_update = auto_yes or prompt_user_update(pip_file)
            if should_update:
                b_path = backup_file(pip_file)
                pip_file.parent.mkdir(parents=True, exist_ok=True)
                with open(pip_file, "w", encoding="utf-8") as f:
                    f.write(content)
                results["pip"] = {"updated": True, "path": str(pip_file), "backup": str(b_path)}
                print(f"[AuraSeed] Backed up existing pip config to {b_path} and updated {pip_file}")
            else:
                results["pip"] = {"updated": False, "path": str(pip_file), "skipped": True}
                print(f"[AuraSeed] Keeping existing pip config at {pip_file}")
        else:
            pip_file.parent.mkdir(parents=True, exist_ok=True)
            with open(pip_file, "w", encoding="utf-8") as f:
                f.write(content)
            results["pip"] = {"created": True, "path": str(pip_file)}
            print(f"[AuraSeed] Created user pip config at {pip_file}")

    # 2. Conda configuration (.condarc)
    conda_cfg = data.get("conda", {})
    has_conda_settings = any([
        conda_cfg.get("channels"),
        conda_cfg.get("default_channels"),
        conda_cfg.get("proxy_servers", {}).get("http") if isinstance(conda_cfg.get("proxy_servers"), dict) else False,
        conda_cfg.get("proxy_servers", {}).get("https") if isinstance(conda_cfg.get("proxy_servers"), dict) else False,
        "ssl_verify" in conda_cfg and conda_cfg.get("ssl_verify") is not True
    ])

    if has_conda_settings:
        conda_file = get_conda_config_path()
        content = generate_condarc(conda_cfg)
        if conda_file.exists():
            should_update = auto_yes or prompt_user_update(conda_file)
            if should_update:
                b_path = backup_file(conda_file)
                conda_file.parent.mkdir(parents=True, exist_ok=True)
                with open(conda_file, "w", encoding="utf-8") as f:
                    f.write(content)
                results["conda"] = {"updated": True, "path": str(conda_file), "backup": str(b_path)}
                print(f"[AuraSeed] Backed up existing conda config to {b_path} and updated {conda_file}")
            else:
                results["conda"] = {"updated": False, "path": str(conda_file), "skipped": True}
                print(f"[AuraSeed] Keeping existing conda config at {conda_file}")
        else:
            conda_file.parent.mkdir(parents=True, exist_ok=True)
            with open(conda_file, "w", encoding="utf-8") as f:
                f.write(content)
            results["conda"] = {"created": True, "path": str(conda_file)}
            print(f"[AuraSeed] Created user conda config at {conda_file}")

    return results


if __name__ == "__main__":
    apply_user_configs()

