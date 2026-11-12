"""Zero-privilege standalone lifecycle management (clean install & full user cleanup) for AuraSeed.

Pure Python standard library only. Handles:
- Removing legacy AuraSeed apps (`~/.auraseed/apps/<name>`, `%LOCALAPPDATA%/AuraSeed/apps/<name>`),
  catalog entries, launchers, shortcuts, associated mvenvs, and OS registry/env keys.
- Performing a full user-account cleanup of AuraSeed (all mvenvs, data directories,
  OS registry trees, HKCU user environment variables, PATH entries, shortcuts, and optional package removal).
- Installing AuraSeed standalone into an isolated user-space virtual environment with
  launchers and optional OS registration.
"""

from __future__ import annotations

import json
import os
import platform
import shutil
import subprocess
import sys
import venv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple


_VALID_NAME_CHARS = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_.-")


def _validate_name(name: str, label: str = "name") -> str:
    cleaned = (name or "").strip()
    if (
        not cleaned
        or cleaned in (".", "..")
        or ".." in cleaned
        or "/" in cleaned
        or "\\" in cleaned
        or "\x00" in cleaned
        or any(ch not in _VALID_NAME_CHARS for ch in cleaned)
    ):
        raise ValueError(f"Invalid {label}: {name!r}")
    return cleaned


def _norm_dir(p: Path) -> str:
    return os.path.normcase(os.path.normpath(str(p.resolve())))


def _default_local_app_data(home: Path) -> Path:
    env_val = os.environ.get("LOCALAPPDATA")
    if env_val and env_val.strip():
        return Path(env_val.strip()).resolve()
    return (home / "AppData" / "Local").resolve()


def _default_roaming_app_data(home: Path) -> Path:
    env_val = os.environ.get("APPDATA")
    if env_val and env_val.strip():
        return Path(env_val.strip()).resolve()
    return (home / "AppData" / "Roaming").resolve()


def _win_delete_registry_tree(subkey: str) -> List[str]:
    """Recursively delete an HKCU registry key and its subkeys using stdlib `winreg`."""
    if platform.system().lower() != "windows":
        return []
    import winreg

    deleted: List[str] = []

    def _recurse(path: str) -> None:
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, path, 0, winreg.KEY_READ | winreg.KEY_WRITE)
        except OSError:
            return

        subkeys: List[str] = []
        try:
            idx = 0
            while True:
                try:
                    subkeys.append(winreg.EnumKey(key, idx))
                    idx += 1
                except OSError:
                    break
        finally:
            winreg.CloseKey(key)

        for child in subkeys:
            _recurse(f"{path}\\{child}")

        try:
            winreg.DeleteKey(winreg.HKEY_CURRENT_USER, path)
            deleted.append(f"HKCU\\{path}")
        except OSError:
            pass

    _recurse(subkey)
    return deleted


def _win_read_registry_value(subkey: str, value_name: str) -> Optional[str]:
    if platform.system().lower() != "windows":
        return None
    import winreg

    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_READ) as key:
            val, _ = winreg.QueryValueEx(key, value_name)
            return str(val) if val is not None else None
    except OSError:
        return None


def _win_cleanup_hkcu_env(
    prefixes: Tuple[str, ...] = ("AURASEED_",),
    exact_names: Iterable[str] = (),
    path_dirs_to_remove: Iterable[Path] = (),
    env_subkey: str = "Environment",
) -> Tuple[List[str], bool]:
    """Delete matching user environment variables and clean PATH entries in HKCU\\Environment."""
    if platform.system().lower() != "windows":
        return [], False
    import winreg

    removed_vars: List[str] = []
    path_modified = False
    exact_upper = {n.upper() for n in exact_names}
    remove_norms = {_norm_dir(Path(p)) for p in path_dirs_to_remove}

    try:
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            env_subkey,
            0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        )
    except OSError:
        return removed_vars, path_modified

    try:
        values: List[Tuple[str, Any, int]] = []
        idx = 0
        while True:
            try:
                name, val, vtype = winreg.EnumValue(key, idx)
                values.append((name, val, vtype))
                idx += 1
            except OSError:
                break

        for name, val, vtype in values:
            upper_name = name.upper()
            if upper_name in exact_upper or any(upper_name.startswith(p) for p in prefixes):
                try:
                    winreg.DeleteValue(key, name)
                    removed_vars.append(name)
                except OSError:
                    pass
                continue

            if upper_name == "PATH" and remove_norms and isinstance(val, str):
                parts = [seg for seg in val.split(";") if seg.strip()]
                kept: List[str] = []
                for seg in parts:
                    try:
                        norm_seg = os.path.normcase(os.path.normpath(seg.strip()))
                    except OSError:
                        norm_seg = seg.strip().lower()
                    if norm_seg in remove_norms:
                        path_modified = True
                    else:
                        kept.append(seg)
                if path_modified:
                    new_path = ";".join(kept)
                    if new_path:
                        winreg.SetValueEx(key, name, 0, vtype, new_path)
                    else:
                        winreg.DeleteValue(key, name)
    finally:
        winreg.CloseKey(key)

    return removed_vars, path_modified


def _win_add_path_dir(bin_dir: Path, env_subkey: str = "Environment") -> bool:
    if platform.system().lower() != "windows":
        return False
    import winreg

    resolved_str = str(bin_dir.resolve())
    norm_target = _norm_dir(bin_dir)
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            env_subkey,
            0,
            winreg.KEY_READ | winreg.KEY_SET_VALUE,
        ) as key:
            try:
                cur_val, cur_type = winreg.QueryValueEx(key, "Path")
            except OSError:
                cur_val, cur_type = "", winreg.REG_EXPAND_SZ
            parts = [s for s in str(cur_val).split(";") if s.strip()]
            if any(os.path.normcase(os.path.normpath(s.strip())) == norm_target for s in parts):
                return False
            parts.append(resolved_str)
            reg_type = cur_type if cur_type in (winreg.REG_SZ, winreg.REG_EXPAND_SZ) else winreg.REG_EXPAND_SZ
            winreg.SetValueEx(key, "Path", 0, reg_type, ";".join(parts))
            return True
    except OSError:
        return False


def _remove_entry_from_json_registry(
    reg_dir: Path,
    app_names: Iterable[str],
    clear_all: bool = False,
) -> bool:
    env_file = reg_dir / "environments.json"
    if not env_file.exists():
        return False
    try:
        data = json.loads(env_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False

    if clear_all:
        data["environments"] = {}
        env_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
        return True

    envs = data.get("environments")
    if not isinstance(envs, dict):
        return False
    changed = False
    for candidate in list(envs.keys()):
        if candidate in set(app_names):
            del envs[candidate]
            changed = True
    if changed:
        env_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return changed


def _remove_app_from_catalog_json(catalog_path: Path, app_name: str) -> bool:
    if not catalog_path.exists():
        return False
    try:
        data = json.loads(catalog_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    if not isinstance(data, dict):
        return False

    changed = False
    if app_name in data:
        del data[app_name]
        changed = True
    apps_block = data.get("apps")
    if isinstance(apps_block, dict) and app_name in apps_block:
        del apps_block[app_name]
        if not apps_block:
            del data["apps"]
        changed = True

    if changed:
        if not data:
            catalog_path.unlink(missing_ok=True)
        else:
            tmp = catalog_path.with_name(f"{catalog_path.name}.tmp")
            tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
            os.replace(tmp, catalog_path)
    return changed


def _resolve_desktop_dirs(desktop_dir: Optional[Path] = None) -> List[Path]:
    if desktop_dir is not None:
        return [Path(desktop_dir)]
    home = Path.home()
    candidates: List[Path] = [home / "Desktop", home / "OneDrive" / "Desktop"]
    if platform.system().lower() == "windows":
        import winreg

        for subkey in (
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\Shell Folders",
        ):
            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey, 0, winreg.KEY_READ) as rk:
                    val, _ = winreg.QueryValueEx(rk, "Desktop")
                    expanded = os.path.expandvars(str(val or "").strip())
                    if expanded:
                        candidates.append(Path(expanded))
            except OSError:
                continue
    seen: set[str] = set()
    unique: List[Path] = []
    for cand in candidates:
        norm = _norm_dir(cand)
        if norm not in seen:
            seen.add(norm)
            unique.append(cand)
    return unique


def _cleanup_shortcuts_for_names(
    names: Iterable[str],
    desktop_dir: Optional[Path] = None,
    start_menu_dir: Optional[Path] = None,
    posix_bin_dir: Optional[Path] = None,
) -> List[str]:
    removed: List[str] = []
    name_set = {n.strip().lower() for n in names if n and n.strip()}
    if not name_set:
        return removed

    home = Path.home()
    candidates: List[Path] = []
    for d_dir in _resolve_desktop_dirs(desktop_dir):
        if d_dir.exists():
            for name in name_set:
                for ext in (".cmd", ".bat", ".lnk", ".desktop"):
                    candidates.append(d_dir / f"{name}{ext}")
                    candidates.append(d_dir / f"auraseed-{name}{ext}")

    if start_menu_dir is not None:
        sm_dir = Path(start_menu_dir)
    elif platform.system().lower() == "windows":
        sm_dir = _default_roaming_app_data(home) / "Microsoft" / "Windows" / "Start Menu" / "Programs"
    else:
        sm_dir = home / ".local" / "share" / "applications"

    if sm_dir.exists():
        for name in name_set:
            for ext in (".cmd", ".bat", ".lnk", ".desktop"):
                candidates.append(sm_dir / f"{name}{ext}")
                candidates.append(sm_dir / f"auraseed-{name}{ext}")
        seed_sm = sm_dir / "AuraSeed"
        if "auraseed" in name_set and seed_sm.exists() and seed_sm.is_dir():
            shutil.rmtree(seed_sm, ignore_errors=True)
            removed.append(str(seed_sm))

    bin_dir = Path(posix_bin_dir) if posix_bin_dir else (home / ".local" / "bin")
    if bin_dir.exists():
        for name in name_set:
            candidates.append(bin_dir / f"auraseed-{name}")
            if name == "auraseed":
                candidates.append(bin_dir / "auraseed")

    for cand in candidates:
        try:
            if cand.is_symlink() or cand.is_file():
                cand.unlink()
                removed.append(str(cand))
        except OSError:
            pass

    return removed


def cleanup_legacy_app(
    app_name: str,
    *,
    home_dir: Optional[Path] = None,
    local_app_data: Optional[Path] = None,
    desktop_dir: Optional[Path] = None,
    start_menu_dir: Optional[Path] = None,
    remove_mvenv: bool = True,
    clean_os_registry: bool = True,
    registry_base_key: str = r"Software\Python\PythonCore\AuraSeed",
    env_reg_subkey: str = "Environment",
) -> Dict[str, Any]:
    """Delete a legacy AuraSeed-installed application and all its user/OS state."""
    safe_name = _validate_name(app_name, "app_name")
    home = Path(home_dir).resolve() if home_dir else Path.home().resolve()
    local_root = Path(local_app_data).resolve() if local_app_data else _default_local_app_data(home)
    dot_auraseed = home / ".auraseed"
    local_auraseed = local_root / "AuraSeed"

    removed_paths: List[str] = []
    cleaned_catalogs: List[str] = []
    cleaned_registry: List[str] = []
    cleaned_env_vars: List[str] = []
    found = False

    # 1. Remove app install directories (~/.auraseed/apps/<app>, %LOCALAPPDATA%/AuraSeed/apps/<app>)
    for app_dir in (
        dot_auraseed / "apps" / safe_name,
        local_auraseed / "apps" / safe_name,
        local_auraseed / "catalog" / "apps" / safe_name,
    ):
        if app_dir.exists():
            shutil.rmtree(app_dir, ignore_errors=True)
            removed_paths.append(str(app_dir))
            found = True

    # 2. Clean catalog & installed_apps metadata files without recreating missing dirs
    for cat_file in (
        dot_auraseed / "apps" / ".catalog.json",
        local_auraseed / "installed_apps.json",
    ):
        if _remove_app_from_catalog_json(cat_file, safe_name):
            cleaned_catalogs.append(str(cat_file))
            found = True

    # 3. Clean matching mvenv if present & requested (never instantiate MvenvManager on empty root)
    if remove_mvenv:
        mvenvs_root = dot_auraseed / "mvenvs"
        if mvenvs_root.exists():
            from auraseed.mvenv.manager import MvenvManager

            mgr = MvenvManager(mvenvs_root)
            for candidate_mvenv in (safe_name, f"auraseed-{safe_name}"):
                if mgr.get_venv(candidate_mvenv) is not None and mgr.delete_venv(candidate_mvenv):
                    removed_paths.append(str(mvenvs_root / candidate_mvenv))
                    found = True
        for extra_venv in (dot_auraseed / "venvs" / safe_name, dot_auraseed / "venvs" / f"auraseed-{safe_name}"):
            if extra_venv.exists():
                shutil.rmtree(extra_venv, ignore_errors=True)
                removed_paths.append(str(extra_venv))
                found = True

    # 4. Clean JSON environment registries
    for reg_dir in (
        dot_auraseed,
        local_root / "auraseed",
        home / ".config" / "auraseed",
    ):
        if _remove_entry_from_json_registry(reg_dir, [safe_name, f"auraseed-{safe_name}"]):
            cleaned_catalogs.append(str(reg_dir / "environments.json"))
            found = True

    # 5. Clean shortcuts
    removed_paths.extend(
        _cleanup_shortcuts_for_names(
            [safe_name],
            desktop_dir=desktop_dir,
            start_menu_dir=start_menu_dir,
        )
    )

    # 6. Clean Windows Registry & HKCU\Environment
    if clean_os_registry and platform.system().lower() == "windows":
        for env_key in (safe_name, f"auraseed-{safe_name}"):
            cleaned_registry.extend(
                _win_delete_registry_tree(f"{registry_base_key}\\Environments\\{env_key}")
            )
        exact_vars = [
            f"AURASEED_ENV_{safe_name.upper()}",
            f"AURASEED_ENV_{safe_name.replace('-', '_').upper()}",
        ]
        vars_del, _ = _win_cleanup_hkcu_env(
            prefixes=(),
            exact_names=exact_vars,
            env_subkey=env_reg_subkey,
        )
        cleaned_env_vars.extend(vars_del)
        if cleaned_registry or cleaned_env_vars:
            found = True

    return {
        "app_name": safe_name,
        "found": found,
        "removed_paths": removed_paths,
        "cleaned_catalogs": cleaned_catalogs,
        "cleaned_registry": cleaned_registry,
        "cleaned_env_vars": cleaned_env_vars,
    }


def cleanup_auraseed_user(
    *,
    remove_package: bool = False,
    purge_bootstrapped_python: bool = False,
    home_dir: Optional[Path] = None,
    local_app_data: Optional[Path] = None,
    xdg_config_home: Optional[Path] = None,
    xdg_data_home: Optional[Path] = None,
    desktop_dir: Optional[Path] = None,
    start_menu_dir: Optional[Path] = None,
    posix_bin_dir: Optional[Path] = None,
    clean_os_registry: bool = True,
    registry_root_key: str = r"Software\Python\PythonCore\AuraSeed",
    auracore_key: str = r"Software\AuraCore\AuraSeed",
    uninstall_key: str = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AuraSeed",
    bootstrapped_key: str = r"Software\Python\PythonCore\AuraSeedBootstrapped",
    env_reg_subkey: str = "Environment",
    python_executable: Optional[str] = None,
) -> Dict[str, Any]:
    """Perform complete user-account removal of AuraSeed (apps, mvenvs, data, env vars, registry)."""
    home = Path(home_dir).resolve() if home_dir else Path.home().resolve()
    local_root = Path(local_app_data).resolve() if local_app_data else _default_local_app_data(home)
    dot_auraseed = home / ".auraseed"
    local_auraseed = local_root / "AuraSeed"
    cfg_auraseed = (
        Path(xdg_config_home).resolve() / "auraseed"
        if xdg_config_home
        else (home / ".config" / "auraseed").resolve()
    )
    data_auraseed = (
        Path(xdg_data_home).resolve() / "auraseed"
        if xdg_data_home
        else (home / ".local" / "share" / "auraseed").resolve()
    )

    removed_paths: List[str] = []
    removed_apps: List[str] = []
    removed_mvenvs: List[str] = []
    cleaned_registry: List[str] = []
    cleaned_env_vars: List[str] = []
    path_cleaned = False
    path_dirs_to_strip: List[Path] = []

    # 1. Discover any standalone install location recorded in receipts or HKCU
    standalone_dirs: List[Path] = []
    for receipt in (
        dot_auraseed / "standalone_install.json",
        local_auraseed / "standalone_install.json",
        data_auraseed / "standalone_install.json",
    ):
        if receipt.exists():
            try:
                rec_data = json.loads(receipt.read_text(encoding="utf-8"))
                inst_d = rec_data.get("install_dir")
                if inst_d:
                    standalone_dirs.append(Path(inst_d))
                bin_d = rec_data.get("bin_dir")
                if bin_d:
                    path_dirs_to_strip.append(Path(bin_d))
            except (OSError, json.JSONDecodeError):
                pass

    if clean_os_registry and platform.system().lower() == "windows":
        reg_inst = _win_read_registry_value(auracore_key, "InstallPath")
        if reg_inst:
            reg_inst_path = Path(reg_inst)
            standalone_dirs.append(reg_inst_path)
            path_dirs_to_strip.append(reg_inst_path / "bin")
            path_dirs_to_strip.append(reg_inst_path / "Scripts")

    # 2. Collect app names & clean legacy apps cleanly before tearing down directories
    app_names: set[str] = {"auraseed"}
    for apps_parent in (dot_auraseed / "apps", local_auraseed / "apps"):
        if apps_parent.exists() and apps_parent.is_dir():
            for child in list(apps_parent.iterdir()):
                if child.is_dir() and not child.name.startswith("."):
                    app_names.add(child.name)
                    cleanup_legacy_app(
                        child.name,
                        home_dir=home,
                        local_app_data=local_root,
                        desktop_dir=desktop_dir,
                        start_menu_dir=start_menu_dir,
                        remove_mvenv=True,
                        clean_os_registry=clean_os_registry,
                        registry_base_key=registry_root_key,
                        env_reg_subkey=env_reg_subkey,
                    )
                    removed_apps.append(child.name)

    # 3. Delete all cataloged mvenvs inside ~/.auraseed/mvenvs cleanly if present
    mvenvs_dir = dot_auraseed / "mvenvs"
    if mvenvs_dir.exists():
        from auraseed.mvenv.manager import MvenvManager

        mgr = MvenvManager(mvenvs_dir)
        for rec in list(mgr.list_venvs()):
            app_names.add(rec.name)
            if mgr.delete_venv(rec.name):
                removed_mvenvs.append(rec.name)

    # 4. Clean shortcuts and POSIX shims
    removed_paths.extend(
        _cleanup_shortcuts_for_names(
            app_names,
            desktop_dir=desktop_dir,
            start_menu_dir=start_menu_dir,
            posix_bin_dir=posix_bin_dir,
        )
    )

    # 5. Clean Windows Registry & HKCU\Environment
    if clean_os_registry and platform.system().lower() == "windows":
        for reg_path in (registry_root_key, auracore_key, uninstall_key):
            cleaned_registry.extend(_win_delete_registry_tree(reg_path))
        if purge_bootstrapped_python:
            cleaned_registry.extend(_win_delete_registry_tree(bootstrapped_key))

        vars_del, path_cleaned = _win_cleanup_hkcu_env(
            prefixes=("AURASEED_",),
            path_dirs_to_remove=path_dirs_to_strip,
            env_subkey=env_reg_subkey,
        )
        cleaned_env_vars.extend(vars_del)

    # 6. Remove AuraSeed directories last so nothing recreates them
    for target_dir in (
        *standalone_dirs,
        local_auraseed,
        local_root / "auraseed",
        dot_auraseed,
        cfg_auraseed,
        data_auraseed,
    ):
        try:
            if target_dir.exists():
                shutil.rmtree(target_dir, ignore_errors=True)
                removed_paths.append(str(target_dir))
        except OSError:
            pass

    # 7. Optionally remove installed `auraseed` Python package cleanly via pip
    package_removed = False
    package_output = ""
    if remove_package:
        py = python_executable or sys.executable
        res = subprocess.run(
            [str(py), "-m", "pip", "uninstall", "-y", "auraseed"],
            capture_output=True,
            text=True,
            shell=False,
            timeout=120,
        )
        package_removed = res.returncode == 0
        package_output = (res.stdout or "") + (res.stderr or "")

    return {
        "removed_apps": sorted(set(removed_apps)),
        "removed_mvenvs": sorted(set(removed_mvenvs)),
        "removed_paths": removed_paths,
        "cleaned_registry": cleaned_registry,
        "cleaned_env_vars": cleaned_env_vars,
        "path_cleaned": path_cleaned,
        "package_removed": package_removed,
        "package_output": package_output.strip(),
    }


def install_auraseed_standalone(
    *,
    dest_dir: Optional[Path] = None,
    source_path: Optional[Path] = None,
    wheelhouse_dir: Optional[Path] = None,
    base_python: Optional[str] = None,
    register_os: bool = True,
    add_to_path: bool = False,
    editable: bool = False,
    home_dir: Optional[Path] = None,
    local_app_data: Optional[Path] = None,
    registry_root_key: str = r"Software\Python\PythonCore\AuraSeed",
    auracore_key: str = r"Software\AuraCore\AuraSeed",
    uninstall_key: str = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AuraSeed",
    env_reg_subkey: str = "Environment",
) -> Dict[str, Any]:
    """Cleanroom standalone user-space installation of AuraSeed into an isolated venv."""
    home = Path(home_dir).resolve() if home_dir else Path.home().resolve()
    local_root = Path(local_app_data).resolve() if local_app_data else _default_local_app_data(home)
    is_win = platform.system().lower() == "windows"
    data_root = (local_root / "AuraSeed") if is_win else (home / ".local" / "share" / "auraseed")
    target_dir = Path(dest_dir).resolve() if dest_dir else (data_root / "standalone")
    target_dir.mkdir(parents=True, exist_ok=True)

    py_base = str(Path(base_python).resolve()) if base_python else sys.executable
    if not any((target_dir / marker).exists() for marker in ("pyvenv.cfg",)):
        if Path(py_base).resolve() == Path(sys.executable).resolve():
            venv.EnvBuilder(with_pip=True, system_site_packages=False).create(target_dir)
        else:
            subprocess.run(
                [py_base, "-m", "venv", str(target_dir)],
                check=True,
                capture_output=True,
                text=True,
                shell=False,
            )

    venv_py = (
        target_dir / "Scripts" / "python.exe"
        if is_win
        else target_dir / "bin" / "python"
    )
    if not venv_py.exists() and not is_win:
        venv_py = target_dir / "bin" / "python3"
    if not venv_py.exists():
        raise FileNotFoundError(f"Standalone venv python binary missing in {target_dir}")

    resolved_src = (
        Path(source_path).resolve()
        if source_path is not None
        else Path(__file__).resolve().parent.parent
    )
    pip_cmd: List[str] = [str(venv_py), "-m", "pip", "install"]
    if wheelhouse_dir is not None:
        pip_cmd.extend(["--no-index", "--find-links", str(Path(wheelhouse_dir).resolve()), "--no-build-isolation"])
    if editable and resolved_src.exists():
        pip_cmd.extend(["-e", str(resolved_src)])
    elif resolved_src.exists() and (resolved_src / "pyproject.toml").exists():
        pip_cmd.append(str(resolved_src))
    else:
        pip_cmd.append("auraseed")

    res = subprocess.run(pip_cmd, capture_output=True, text=True, shell=False, timeout=300)
    if res.returncode != 0:
        raise RuntimeError(f"Failed installing AuraSeed into standalone venv: {res.stderr or res.stdout}")

    bin_dir = target_dir / "bin"
    bin_dir.mkdir(parents=True, exist_ok=True)
    if is_win:
        (bin_dir / "auraseed.bat").write_text(
            "@echo off\r\n"
            f'set "AURASEED_HOME={data_root}"\r\n'
            f'"{venv_py}" -m auraseed %*\r\n',
            encoding="utf-8",
        )
        (bin_dir / "auraseed.ps1").write_text(
            f'$env:AURASEED_HOME = "{data_root}"\n'
            f'& "{venv_py}" -m auraseed @args\n',
            encoding="utf-8",
        )
    else:
        sh_path = bin_dir / "auraseed"
        sh_path.write_text(
            "#!/bin/sh\n"
            f'export AURASEED_HOME="{data_root}"\n'
            f'exec "{venv_py}" -m auraseed "$@"\n',
            encoding="utf-8",
        )
        os.chmod(sh_path, 0o755)

    receipt_path = data_root / "standalone_install.json"
    data_root.mkdir(parents=True, exist_ok=True)
    receipt = {
        "install_dir": str(target_dir),
        "bin_dir": str(bin_dir),
        "python_path": str(venv_py),
        "data_root": str(data_root),
        "installed_at": datetime.now(timezone.utc).isoformat(),
    }
    receipt_path.write_text(json.dumps(receipt, indent=2), encoding="utf-8")

    registered_keys: List[str] = []
    path_updated = False
    if register_os and is_win:
        import winreg

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{registry_root_key}\\Environments\\standalone") as env_k:
            with winreg.CreateKey(env_k, "InstallPath") as ip_k:
                winreg.SetValue(ip_k, "", winreg.REG_SZ, str(target_dir))
                winreg.SetValueEx(ip_k, "ExecutablePath", 0, winreg.REG_SZ, str(venv_py))
        registered_keys.append(f"HKCU\\{registry_root_key}\\Environments\\standalone")

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, auracore_key) as ac_k:
            winreg.SetValueEx(ac_k, "InstallPath", 0, winreg.REG_SZ, str(target_dir))
            winreg.SetValueEx(ac_k, "PythonExecutable", 0, winreg.REG_SZ, str(venv_py))
        registered_keys.append(f"HKCU\\{auracore_key}")

        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, uninstall_key) as un_k:
            winreg.SetValueEx(un_k, "DisplayName", 0, winreg.REG_SZ, "AuraSeed (User)")
            winreg.SetValueEx(un_k, "InstallLocation", 0, winreg.REG_SZ, str(target_dir))
            winreg.SetValueEx(
                un_k,
                "UninstallString",
                0,
                winreg.REG_SZ,
                f'"{venv_py}" -m auraseed cleanup self --yes',
            )
        registered_keys.append(f"HKCU\\{uninstall_key}")

        try:
            with winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                env_reg_subkey,
                0,
                winreg.KEY_READ | winreg.KEY_SET_VALUE,
            ) as hkcu_env:
                winreg.SetValueEx(hkcu_env, "AURASEED_HOME", 0, winreg.REG_SZ, str(data_root))
                winreg.SetValueEx(hkcu_env, "AURASEED_STANDALONE_DIR", 0, winreg.REG_SZ, str(target_dir))
        except OSError:
            pass
        if add_to_path:
            path_updated = _win_add_path_dir(bin_dir, env_subkey=env_reg_subkey)

    return {
        **receipt,
        "registered_keys": registered_keys,
        "path_updated": path_updated,
        "receipt_path": str(receipt_path),
    }

