"""
Local Client-Side Application Manager for AuraSeed.
Zero external runtime dependencies (Python standard library only).
"""
import os
import sys
import json
import shutil
import zipfile
import tarfile
import tempfile
import platform
import subprocess
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Callable

from auraseed.installer.models import AppManifest
from auraseed.installer.engine import AppInstallerEngine
from auraseed.mvenv.manager import MvenvManager


class LocalAppManager:
    """
    Manages client-side installed applications provisioned by AuraSeed.
    """

    def __init__(self, apps_dir: Optional[Path] = None, registry_file: Optional[Path] = None):
        if apps_dir:
            self.apps_dir = Path(apps_dir).resolve()
        else:
            sys_plat = platform.system().lower()
            if sys_plat == "windows":
                local_appdata = os.environ.get("LOCALAPPDATA")
                if local_appdata:
                    base = Path(local_appdata) / "AuraSeed" / "apps"
                else:
                    base = Path.home() / ".auraseed" / "apps"
            elif sys_plat == "darwin":
                base = Path.home() / "Library" / "Application Support" / "auraseed" / "apps"
            else:
                base = Path.home() / ".local" / "share" / "auraseed" / "apps"
            self.apps_dir = base.resolve()

        self.apps_dir.mkdir(parents=True, exist_ok=True)

        if registry_file:
            self.registry_file = Path(registry_file).resolve()
        else:
            local_appdata = os.environ.get("LOCALAPPDATA")
            if local_appdata and os.name == "nt":
                base_dir = Path(local_appdata) / "AuraSeed"
            else:
                base_dir = Path.home() / ".auraseed"
            self.registry_file = (base_dir / "installed_apps.json").resolve()

        self.registry_file.parent.mkdir(parents=True, exist_ok=True)
        if not self.registry_file.exists():
            self._save_registry({})

    def _load_registry(self) -> Dict[str, Any]:
        if not self.registry_file.exists():
            return {}
        try:
            return json.loads(self.registry_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_registry(self, data: Dict[str, Any]) -> None:
        self.registry_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _calculate_dir_size(self, path: Path) -> int:
        total = 0
        try:
            for root, _, files in os.walk(path):
                for f in files:
                    try:
                        total += os.path.getsize(os.path.join(root, f))
                    except OSError:
                        pass
        except OSError:
            pass
        return total

    def list_installed_apps(self) -> List[Dict[str, Any]]:
        """
        Discovers all locally installed applications.
        """
        registry = self._load_registry()
        apps: Dict[str, Dict[str, Any]] = {}

        # 1. Inspect registered apps
        for name, entry in list(registry.items()):
            install_dir = Path(entry.get("install_dir", ""))
            if install_dir.exists() and install_dir.is_dir():
                app_info = self._inspect_app_dir(install_dir, fallback_entry=entry)
                if app_info:
                    apps[app_info["name"]] = app_info
            else:
                # Stale registry entry
                del registry[name]
        self._save_registry(registry)

        # 2. Inspect apps_dir children directly
        if self.apps_dir.exists():
            for child in self.apps_dir.iterdir():
                if child.is_dir() and not child.name.startswith("."):
                    if child.name not in apps:
                        app_info = self._inspect_app_dir(child)
                        if app_info:
                            apps[app_info["name"]] = app_info

        return sorted(list(apps.values()), key=lambda x: x["name"])

    def _inspect_app_dir(self, app_dir: Path, fallback_entry: Optional[Dict[str, Any]] = None) -> Optional[Dict[str, Any]]:
        manifest_path = app_dir / "app.json"
        auraseed_app_meta = app_dir / ".auraseed_app.json"

        meta: Dict[str, Any] = {}
        if auraseed_app_meta.exists():
            try:
                meta = json.loads(auraseed_app_meta.read_text(encoding="utf-8"))
            except Exception:
                pass

        manifest_data: Dict[str, Any] = {}
        if manifest_path.exists():
            try:
                manifest_data = json.loads(manifest_path.read_text(encoding="utf-8"))
            except Exception:
                pass
        elif fallback_entry:
            manifest_data = fallback_entry

        app_name = manifest_data.get("name") or meta.get("name") or app_dir.name
        display_name = manifest_data.get("display_name") or meta.get("display_name") or app_name.replace("-", " ").title()
        version = manifest_data.get("version") or meta.get("version") or "1.0.0"
        description = manifest_data.get("description") or meta.get("description") or ""
        port = manifest_data.get("default_port") or meta.get("port") or 8000

        # Detect launchers
        launchers: Dict[str, str] = {}
        for ext in ("bat", "ps1", "sh"):
            cand = app_dir / f"run-{app_name}.{ext}"
            if cand.exists():
                launchers[ext] = str(cand)

        # Detect bound mvenv
        mvenv_name = meta.get("mvenv_name")
        mvenv_path = meta.get("mvenv_path")
        python_path = meta.get("python_path")

        if not mvenv_name:
            # Check if private embedded venv exists in app_dir
            is_win = platform.system().lower() == "windows"
            py_cand = (app_dir / "Scripts" / "python.exe") if is_win else (app_dir / "bin" / "python")
            if py_cand.exists():
                mvenv_name = f"{app_name}-private"
                mvenv_path = str(app_dir)
                python_path = str(py_cand)
            else:
                mvenv_name = "unknown"

        return {
            "name": app_name,
            "display_name": display_name,
            "version": version,
            "description": description,
            "install_dir": str(app_dir),
            "mvenv_name": mvenv_name,
            "mvenv_path": mvenv_path or str(app_dir),
            "python_path": python_path or "",
            "port": port,
            "launchers": launchers,
            "size_bytes": self._calculate_dir_size(app_dir),
            "installed_at": meta.get("installed_at") or datetime.now(timezone.utc).isoformat()
        }

    def get_installed_app(self, name: str) -> Optional[Dict[str, Any]]:
        for app in self.list_installed_apps():
            if app["name"] == name:
                return app
        return None

    def install_from_bundle(
        self,
        bundle_path: Path,
        dest_dir: Optional[Path] = None,
        port: Optional[int] = None,
        mvenv_name: Optional[str] = None,
        use_shared_mvenv: bool = False,
        create_shortcut: bool = True,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Unpacks and executes full installation of an application bundle (.zip or .tar.gz).
        """
        bundle_path = Path(bundle_path).resolve()
        if not bundle_path.exists():
            raise FileNotFoundError(f"Bundle file not found: {bundle_path}")

        temp_stage = Path(tempfile.mkdtemp(prefix="auraseed_install_stage_"))

        try:
            if progress_callback:
                progress_callback(5, "Unpacking installer bundle...")

            if zipfile.is_zipfile(bundle_path):
                with zipfile.ZipFile(bundle_path, "r") as zf:
                    zf.extractall(temp_stage)
            else:
                with tarfile.open(bundle_path, "r:*") as tf:
                    tf.extractall(temp_stage)

            # Locate app.json
            manifest_file = temp_stage / "app.json"
            if not manifest_file.exists():
                # Check nested subdirectory if archive root had a directory
                for c in temp_stage.iterdir():
                    if c.is_dir() and (c / "app.json").exists():
                        manifest_file = c / "app.json"
                        break

            if not manifest_file.exists():
                raise FileNotFoundError("Application bundle did not contain a valid app.json manifest.")

            manifest = AppManifest.from_file(manifest_file)
            engine = AppInstallerEngine(manifest)

            target_dest = dest_dir or (self.apps_dir / manifest.name)

            install_result = engine.install(
                dest_dir=target_dest,
                port=port,
                force=True,
                create_desktop_shortcut=create_shortcut,
                progress_callback=progress_callback,
                target_mvenv_name=mvenv_name,
                use_shared_mvenv=use_shared_mvenv
            )

            # Register app
            registry = self._load_registry()
            app_info = self._inspect_app_dir(Path(target_dest))
            if app_info:
                registry[manifest.name] = app_info
                self._save_registry(registry)

            return install_result
        finally:
            if temp_stage.exists():
                shutil.rmtree(temp_stage, ignore_errors=True)

    def uninstall_app(self, name: str, remove_mvenv_if_private: bool = True) -> bool:
        """
        Uninstalls an application from local system.
        """
        app = self.get_installed_app(name)
        if not app:
            return False

        install_dir = Path(app["install_dir"])
        mvenv_name = app.get("mvenv_name")

        # 1. Remove app directory
        if install_dir.exists():
            shutil.rmtree(install_dir, ignore_errors=True)

        # 2. If it had a private dedicated mvenv not sharing, clean up
        if remove_mvenv_if_private and mvenv_name and mvenv_name.endswith("-private"):
            # Embedded inside app_dir already deleted
            pass
        elif remove_mvenv_if_private and mvenv_name and mvenv_name == name:
            # Standalone mvenv with same name
            try:
                mgr = MvenvManager()
                mgr.delete_venv(name)
            except Exception:
                pass

        # 3. Clean registry
        registry = self._load_registry()
        if name in registry:
            del registry[name]
            self._save_registry(registry)

        return True

    def launch_app(self, name: str) -> subprocess.Popen:
        """
        Launches the installed application process using its native launcher script.
        """
        app = self.get_installed_app(name)
        if not app:
            raise KeyError(f"Installed app '{name}' not found.")

        launchers = app.get("launchers", {})
        is_win = platform.system().lower() == "windows"

        launcher_path = None
        if is_win:
            launcher_path = launchers.get("bat") or launchers.get("ps1")
        else:
            launcher_path = launchers.get("sh")

        if not launcher_path or not Path(launcher_path).exists():
            raise FileNotFoundError(f"Launcher script not found for application: {name}")

        launcher_p = Path(launcher_path)
        app_dir = Path(app["install_dir"])

        if is_win and launcher_p.suffix == ".ps1":
            cmd = ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(launcher_p)]
        elif is_win:
            cmd = [str(launcher_p)]
        else:
            cmd = ["/bin/sh", str(launcher_p)]

        proc = subprocess.Popen(
            cmd,
            cwd=str(app_dir),
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        return proc

    def relink_app_mvenv(self, name: str, new_mvenv_name: str, mvenv_manager: Optional[MvenvManager] = None) -> bool:
        """
        Re-points an installed application's launchers to use a different (e.g. shared or merged) mvenv.
        """
        app = self.get_installed_app(name)
        if not app:
            return False

        mgr = mvenv_manager or MvenvManager()
        target_mvenv = mgr.get_venv(new_mvenv_name)
        if not target_mvenv:
            raise KeyError(f"Target mvenv '{new_mvenv_name}' not found.")

        app_dir = Path(app["install_dir"])
        python_exe = Path(target_mvenv.python_path)

        manifest_path = app_dir / "app.json"
        if manifest_path.exists():
            manifest = AppManifest.from_file(manifest_path)
        else:
            manifest = AppManifest(name=name, display_name=app["display_name"])

        engine = AppInstallerEngine(manifest)
        launchers = engine._generate_launchers(app_dir, python_exe, app.get("port", 8000), mvenv_root=Path(target_mvenv.path))

        # Update .auraseed_app.json
        meta_file = app_dir / ".auraseed_app.json"
        meta = {
            "name": name,
            "display_name": app["display_name"],
            "version": app["version"],
            "mvenv_name": new_mvenv_name,
            "mvenv_path": target_mvenv.path,
            "python_path": target_mvenv.python_path,
            "port": app.get("port", 8000),
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")

        # Update registry
        registry = self._load_registry()
        app["mvenv_name"] = new_mvenv_name
        app["mvenv_path"] = target_mvenv.path
        app["python_path"] = target_mvenv.python_path
        app["launchers"] = launchers
        registry[name] = app
        self._save_registry(registry)

        return True
