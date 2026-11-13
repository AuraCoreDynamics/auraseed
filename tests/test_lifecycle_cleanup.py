"""Tests for AuraSeed lifecycle cleanup and OS registry/environment sanitization."""

from __future__ import annotations

import json
import platform
import uuid
from pathlib import Path

from auraseed.lifecycle import (
    _win_delete_registry_tree,
    cleanup_auraseed_user,
    cleanup_legacy_app,
)
from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest


def _seed_legacy_app_layout(home: Path, local_app_data: Path, desktop: Path, app_name: str = "bijou") -> None:
    app_dir = home / ".auraseed" / "apps" / app_name
    app_dir.mkdir(parents=True, exist_ok=True)
    (app_dir / "install_receipt.json").write_text('{"app_name": "bijou"}', encoding="utf-8")

    catalog_file = home / ".auraseed" / "apps" / ".catalog.json"
    catalog_file.write_text(
        json.dumps(
            {
                app_name: {"name": app_name, "install_path": str(app_dir)},
                "other-app": {"name": "other-app"},
                "apps": {app_name: {"version": "0.1.0"}},
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    local_seed = local_app_data / "AuraSeed"
    (local_seed / "apps" / app_name).mkdir(parents=True, exist_ok=True)
    (local_seed / "apps" / app_name / "marker.txt").write_text("x", encoding="utf-8")
    (local_seed / "installed_apps.json").write_text(
        json.dumps({app_name: {"version": "0.1.0"}, "other-app": {"version": "1.0.0"}}),
        encoding="utf-8",
    )

    desktop.mkdir(parents=True, exist_ok=True)
    (desktop / f"{app_name}.cmd").write_text("@echo off\r\n", encoding="utf-8")


def test_cleanup_legacy_app_preserves_other_apps(tmp_path: Path) -> None:
    home = tmp_path / "home"
    local_app_data = tmp_path / "local"
    desktop = tmp_path / "Desktop"
    _seed_legacy_app_layout(home, local_app_data, desktop, app_name="bijou")

    report = cleanup_legacy_app(
        "bijou",
        home_dir=home,
        local_app_data=local_app_data,
        desktop_dir=desktop,
        remove_mvenv=True,
        clean_os_registry=False,
    )
    assert report["found"] is True
    assert not (home / ".auraseed" / "apps" / "bijou").exists()
    assert not (local_app_data / "AuraSeed" / "apps" / "bijou").exists()
    assert not (desktop / "bijou.cmd").exists()

    cat_after = json.loads((home / ".auraseed" / "apps" / ".catalog.json").read_text(encoding="utf-8"))
    assert "bijou" not in cat_after
    assert "apps" not in cat_after
    assert "other-app" in cat_after

    inst_after = json.loads((local_app_data / "AuraSeed" / "installed_apps.json").read_text(encoding="utf-8"))
    assert "bijou" not in inst_after
    assert "other-app" in inst_after


def test_cleanup_auraseed_user_full_sanitization(tmp_path: Path, monkeypatch) -> None:
    home = tmp_path / "home"
    local_app_data = tmp_path / "local"
    xdg_cfg = tmp_path / "cfg"
    xdg_data = tmp_path / "data"
    desktop = tmp_path / "Desktop"
    posix_bin = tmp_path / "bin"
    posix_bin.mkdir(parents=True, exist_ok=True)

    _seed_legacy_app_layout(home, local_app_data, desktop, app_name="bijou")
    (home / ".auraseed" / "venvs" / "py314").mkdir(parents=True, exist_ok=True)
    (xdg_cfg / "auraseed").mkdir(parents=True, exist_ok=True)
    (xdg_cfg / "auraseed" / "environments.json").write_text('{"environments": {}}', encoding="utf-8")
    (xdg_data / "auraseed").mkdir(parents=True, exist_ok=True)
    (posix_bin / "auraseed-bijou").write_text("#!/bin/sh\n", encoding="utf-8")
    (posix_bin / "auraseed").write_text("#!/bin/sh\n", encoding="utf-8")

    # Create a real lightweight mvenv inside fake home so MvenvManager cleanup is exercised
    import sys

    mvenv_mgr = MvenvManager(home / ".auraseed" / "mvenvs")
    mvenv_mgr.create_venv(MvenvCreateRequest(name="bijou", base_python=sys.executable, sovereign=False))
    assert mvenv_mgr.get_venv("bijou") is not None

    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("USERPROFILE", str(home))

    win_test_root = None
    win_test_env = None
    if platform.system().lower() == "windows":
        import winreg

        uid = uuid.uuid4().hex[:10]
        win_test_root = rf"Software\AuraCore\AuraSeedTest_{uid}"
        win_test_env = rf"Software\AuraCore\AuraSeedTestEnv_{uid}"
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, f"{win_test_root}\\Environments\\bijou\\InstallPath") as k:
            winreg.SetValue(k, "", winreg.REG_SZ, str(home / ".auraseed" / "apps" / "bijou"))
        with winreg.CreateKey(winreg.HKEY_CURRENT_USER, win_test_env) as ek:
            winreg.SetValueEx(ek, "AURASEED_HOME", 0, winreg.REG_SZ, str(local_app_data / "AuraSeed"))
            winreg.SetValueEx(
                ek,
                "Path",
                0,
                winreg.REG_EXPAND_SZ,
                rf"C:\Windows\System32;{tmp_path / 'standalone' / 'bin'}",
            )
        # Write standalone receipt referencing standalone/bin so PATH stripping is verified
        (local_app_data / "AuraSeed" / "standalone_install.json").write_text(
            json.dumps(
                {
                    "install_dir": str(tmp_path / "standalone"),
                    "bin_dir": str(tmp_path / "standalone" / "bin"),
                }
            ),
            encoding="utf-8",
        )
        (tmp_path / "standalone" / "bin").mkdir(parents=True, exist_ok=True)

    try:
        report = cleanup_auraseed_user(
            remove_package=False,
            home_dir=home,
            local_app_data=local_app_data,
            xdg_config_home=xdg_cfg,
            xdg_data_home=xdg_data,
            desktop_dir=desktop,
            posix_bin_dir=posix_bin,
            clean_os_registry=(platform.system().lower() == "windows"),
            registry_root_key=win_test_root or r"Software\Python\PythonCore\AuraSeed",
            auracore_key=(f"{win_test_root}\\App" if win_test_root else r"Software\AuraCore\AuraSeed"),
            uninstall_key=(f"{win_test_root}\\Uninstall" if win_test_root else r"Software\Microsoft\Windows\CurrentVersion\Uninstall\AuraSeed"),
            env_reg_subkey=win_test_env or "Environment",
        )

        assert not (home / ".auraseed").exists()
        assert not (local_app_data / "AuraSeed").exists()
        assert not (xdg_cfg / "auraseed").exists()
        assert not (xdg_data / "auraseed").exists()
        assert not (desktop / "bijou.cmd").exists()
        assert not (posix_bin / "auraseed").exists()
        assert "bijou" in report["removed_apps"]

        if platform.system().lower() == "windows" and win_test_env and win_test_root:
            import winreg

            assert any(win_test_root in k for k in report["cleaned_registry"])
            assert "AURASEED_HOME" in report["cleaned_env_vars"]
            assert report["path_cleaned"] is True
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, win_test_env, 0, winreg.KEY_READ) as ek:
                path_val, _ = winreg.QueryValueEx(ek, "Path")
                assert path_val == r"C:\Windows\System32"
    finally:
        if win_test_root:
            _win_delete_registry_tree(win_test_root)
        if win_test_env:
            _win_delete_registry_tree(win_test_env)


def test_register_start_menu_launcher_and_refresh_cache(tmp_path: Path) -> None:
    from auraseed.lifecycle import register_start_menu_launcher

    sm_root = tmp_path / "StartMenu" / "Programs"
    target = tmp_path / "bin" / ("demo.bat" if platform.system().lower() == "windows" else "demo")
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text("@echo off\r\necho ok\r\n", encoding="utf-8")

    res = register_start_menu_launcher(
        app_name="demo-app",
        target_path=target,
        display_name="Demo App",
        arguments="--port 8123",
        working_dir=tmp_path,
        description="Demo App Launcher",
        subfolder="AuraSeed",
        start_menu_dir=sm_root,
        refresh_cache=True,
    )
    sc_path = Path(res["shortcut_path"])
    assert sc_path.exists()
    assert res["cache_refresh"]["refreshed"] is True
    if platform.system().lower() == "windows":
        assert sc_path.parent == (sm_root / "AuraSeed").resolve()
        assert sc_path.suffix.lower() in (".lnk", ".cmd")


