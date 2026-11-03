"""
Core Application Installer Engine for AuraSeed.
Zero external runtime dependencies (Python standard library only).
"""
import os
import sys
import shutil
import platform
import subprocess
from pathlib import Path
from typing import Optional, Callable, Dict, Any, List

from auraseed.installer.models import AppManifest
from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest
from auraseed.provision.config_manager import apply_user_configs


class AppInstallerEngine:
    def __init__(self, manifest: AppManifest, logger: Optional[Callable[[str], None]] = None):
        self.manifest = manifest
        self.logger = logger or print

    def log(self, message: str) -> None:
        self.logger(message)

    def resolve_default_dest(self) -> Path:
        if self.manifest.default_dest:
            p = Path(os.path.expandvars(os.path.expanduser(self.manifest.default_dest)))
            return p.resolve()

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

        return (base / self.manifest.name).resolve()

    def resolve_app_root(self) -> Path:
        manifest_dir = Path(self.manifest.metadata.get("_manifest_dir", ".")).resolve()
        app_source = Path(os.path.expandvars(os.path.expanduser(self.manifest.source_path)))
        if app_source.is_absolute():
            return app_source
        return (manifest_dir / app_source).resolve()

    def install(
        self,
        dest_dir: Optional[Path] = None,
        port: Optional[int] = None,
        force: bool = False,
        create_launchers: bool = True,
        create_desktop_shortcut: bool = True,
        progress_callback: Optional[Callable[[int, str], None]] = None
    ) -> Dict[str, Any]:
        """
        Executes the full installation lifecycle.
        """
        def update_progress(percent: int, msg: str):
            self.log(f"[{percent}%] {msg}")
            if progress_callback:
                progress_callback(percent, msg)

        update_progress(5, "Initializing installation environment...")

        # 1. Apply user pip/conda config if present in bootstrap.json
        try:
            apply_user_configs(auto_yes=True)
        except Exception as e:
            self.log(f"[AuraSeed Installer] Warning: Could not apply bootstrap config ({e})")

        # 2. Resolve destination
        target_dest = (dest_dir or self.resolve_default_dest()).resolve()
        target_port = port or self.manifest.default_port or 8000
        app_root = self.resolve_app_root()

        update_progress(10, f"Target directory: {target_dest}")

        # 3. Create or reuse managed sovereign virtual environment
        update_progress(20, "Creating sovereign virtual environment...")
        mvenv_mgr = MvenvManager(root_path=target_dest.parent)
        env_name = target_dest.name

        req = MvenvCreateRequest(
            name=env_name,
            target_dir=str(target_dest),
            sovereign=True,
            force=force
        )
        record = mvenv_mgr.create_venv(req)

        python_exe = Path(record.python_path).resolve()
        pip_exe = Path(record.pip_path).resolve() if record.pip_path else None

        if not python_exe.exists():
            raise RuntimeError(f"Python binary not found at: {python_exe}")

        update_progress(35, f"Virtual environment verified with Python at: {python_exe}")

        bundle_dir = Path(self.manifest.metadata.get("_manifest_dir", app_root)).resolve()

        # 3.5 Execute pre-install hook if defined
        update_progress(38, "Checking pre-install lifecycle hooks...")
        self._execute_python_hook("pre_install", python_exe, target_dest, target_port, app_root, bundle_dir)

        # 4. Install main application
        update_progress(40, f"Installing {self.manifest.display_name}...")
        is_windows = platform.system().lower() == "windows"
        env_vars = os.environ.copy()
        bin_dir = python_exe.parent
        env_vars["PATH"] = f"{bin_dir}{os.pathsep}{env_vars.get('PATH', '')}"

        pip_cmd = [str(python_exe), "-m", "pip", "install"]
        if self.manifest.pip_install_args:
            pip_cmd.extend(self.manifest.pip_install_args)
        else:
            pip_cmd.extend(["-e", str(app_root)])

        self.log(f"Running pip command: {' '.join(pip_cmd)}")
        res = subprocess.run(pip_cmd, capture_output=True, text=True, env=env_vars)
        if res.returncode != 0:
            raise RuntimeError(f"Failed to install application package: {res.stderr or res.stdout}")

        update_progress(60, f"Successfully installed {self.manifest.display_name}")

        # 5. Install subprojects
        manifest_dir = Path(self.manifest.metadata.get("_manifest_dir", app_root)).resolve()
        for i, subp in enumerate(self.manifest.subprojects, start=1):
            sub_path = Path(os.path.expandvars(os.path.expanduser(subp)))
            if not sub_path.is_absolute():
                sub_path = (manifest_dir / sub_path).resolve()
            if not sub_path.exists():
                self.log(f"Warning: Subproject path not found: {sub_path}")
                continue

            pct = 60 + int((i / max(1, len(self.manifest.subprojects))) * 20)
            update_progress(pct, f"Installing subproject: {sub_path.name}...")
            sub_cmd = [str(python_exe), "-m", "pip", "install", "-e", str(sub_path)]
            sub_res = subprocess.run(sub_cmd, capture_output=True, text=True, env=env_vars)
            if sub_res.returncode != 0:
                self.log(f"Warning: Subproject {sub_path.name} install warning: {sub_res.stderr or sub_res.stdout}")

        # 6. Execute post-install hooks & commands
        update_progress(82, "Executing post-install lifecycle hooks...")
        self._execute_python_hook("post_install", python_exe, target_dest, target_port, app_root, bundle_dir)

        if self.manifest.post_install_commands:
            update_progress(87, "Executing post-install shell commands...")
            for post_cmd in self.manifest.post_install_commands:
                formatted_cmd = post_cmd.format(
                    port=target_port,
                    python=str(python_exe),
                    dest=str(target_dest),
                    app_root=str(app_root),
                    bundle_dir=str(bundle_dir)
                )
                self.log(f"Running post-install: {formatted_cmd}")
                subprocess.run(formatted_cmd, shell=True, env=env_vars, capture_output=True)

        # 7. Generate Launchers & Shortcuts
        launchers = {}
        if create_launchers:
            update_progress(90, "Generating application launchers...")
            launchers = self._generate_launchers(target_dest, python_exe, target_port)

        if create_desktop_shortcut and is_windows:
            update_progress(95, "Creating desktop shortcut...")
            self._create_windows_desktop_shortcut(target_dest, launchers.get("bat") or launchers.get("cmd"))

        update_progress(100, f"Installation of {self.manifest.display_name} complete!")

        return {
            "success": True,
            "app_name": self.manifest.name,
            "display_name": self.manifest.display_name,
            "version": self.manifest.version,
            "install_dir": str(target_dest),
            "python_path": str(python_exe),
            "port": target_port,
            "launchers": launchers
        }

    def _generate_launchers(self, target_dest: Path, python_exe: Path, port: int) -> Dict[str, str]:
        """
        Creates ready-to-run launcher scripts in the installation directory.
        """
        app_name = self.manifest.name
        is_windows = platform.system().lower() == "windows"
        launchers = {}

        # Parse command or default to python -m <name>
        raw_cmd = self.manifest.entrypoint_command or f"{app_name} --port {{port}}"
        cmd_str = raw_cmd.format(port=port, dest=str(target_dest))

        if is_windows:
            scripts_dir = target_dest / "Scripts"
            activate_bat = scripts_dir / "activate.bat"

            bat_file = target_dest / f"run-{app_name}.bat"
            bat_content = (
                "@echo off\r\n"
                f"title {self.manifest.display_name}\r\n"
                f"cd /d \"{target_dest}\"\r\n"
                f"if exist \"{activate_bat}\" call \"{activate_bat}\"\r\n"
                f"{cmd_str}\r\n"
                "if %ERRORLEVEL% neq 0 pause\r\n"
            )
            bat_file.write_text(bat_content, encoding="utf-8")
            launchers["bat"] = str(bat_file)

            ps1_file = target_dest / f"run-{app_name}.ps1"
            activate_ps1 = scripts_dir / "Activate.ps1"
            ps1_content = (
                f"$host.ui.RawUI.WindowTitle = '{self.manifest.display_name}'\r\n"
                f"Set-Location '{target_dest}'\r\n"
                f"if (Test-Path '{activate_ps1}') {{ & '{activate_ps1}' }}\r\n"
                f"{cmd_str}\r\n"
            )
            ps1_file.write_text(ps1_content, encoding="utf-8")
            launchers["ps1"] = str(ps1_file)
        else:
            sh_file = target_dest / f"run-{app_name}.sh"
            activate_sh = target_dest / "bin" / "activate"
            sh_content = (
                "#!/usr/bin/env sh\n"
                f"cd \"{target_dest}\"\n"
                f"[ -f \"{activate_sh}\" ] && . \"{activate_sh}\"\n"
                f"exec {cmd_str}\n"
            )
            sh_file.write_text(sh_content, encoding="utf-8")
            sh_file.chmod(0o755)
            launchers["sh"] = str(sh_file)

        return launchers

    def _create_windows_desktop_shortcut(self, target_dest: Path, launcher_path: Optional[str]) -> None:
        if not launcher_path or not Path(launcher_path).exists():
            return
        try:
            desktop_dir = Path.home() / "Desktop"
            if not desktop_dir.exists():
                return
            shortcut_path = desktop_dir / f"{self.manifest.display_name}.lnk"
            vbs_script = (
                f'Set oWS = WScript.CreateObject("WScript.Shell")\n'
                f'sLinkFile = "{shortcut_path}"\n'
                f'Set oLink = oWS.CreateShortcut(sLinkFile)\n'
                f'oLink.TargetPath = "{launcher_path}"\n'
                f'oLink.WorkingDirectory = "{target_dest}"\n'
                f'oLink.Description = "{self.manifest.description}"\n'
                f'oLink.Save\n'
            )
            temp_vbs = Path(os.environ.get("TEMP", ".")) / "auraseed_create_shortcut.vbs"
            temp_vbs.write_text(vbs_script, encoding="utf-8")
            subprocess.run(["cscript.exe", "//Nologo", str(temp_vbs)], capture_output=True)
            if temp_vbs.exists():
                temp_vbs.unlink()
            self.log(f"Created Desktop shortcut: {shortcut_path}")
        except Exception as e:
            self.log(f"Could not create desktop shortcut: {e}")

    def _execute_python_hook(
        self,
        hook_name: str,
        python_exe: Path,
        target_dest: Path,
        target_port: int,
        app_root: Path,
        bundle_dir: Path
    ) -> None:
        """
        Executes a Python lifecycle hook script with injected installation context.
        """
        hook_target = None
        # Check explicit definition in manifest
        if self.manifest.hooks and hook_name in self.manifest.hooks:
            cand = Path(self.manifest.hooks[hook_name])
            if cand.is_absolute() and cand.exists():
                hook_target = cand
            elif (bundle_dir / cand).exists():
                hook_target = bundle_dir / cand
            elif (app_root / cand).exists():
                hook_target = app_root / cand
            elif (bundle_dir / "hooks" / cand.name).exists():
                hook_target = bundle_dir / "hooks" / cand.name
            else:
                self.log(f"Warning: Defined hook '{hook_name}' not found at: {cand}")
                return
        else:
            # Check standard fallback locations
            candidates = [
                bundle_dir / "hooks" / f"{hook_name}.py",
                app_root / "hooks" / f"{hook_name}.py",
                bundle_dir / f"{hook_name}.py",
                app_root / f"{hook_name}.py",
            ]
            for cand in candidates:
                if cand.exists():
                    hook_target = cand
                    break

        if not hook_target:
            return

        self.log(f"Executing lifecycle hook '{hook_name}' from: {hook_target}")
        env_vars = os.environ.copy()
        bin_dir = python_exe.parent
        env_vars["PATH"] = f"{bin_dir}{os.pathsep}{env_vars.get('PATH', '')}"
        env_vars["AURASEED_APP_NAME"] = self.manifest.name
        env_vars["AURASEED_DISPLAY_NAME"] = self.manifest.display_name
        env_vars["AURASEED_VERSION"] = self.manifest.version
        env_vars["AURASEED_INSTALL_DIR"] = str(target_dest)
        env_vars["AURASEED_APP_ROOT"] = str(app_root)
        env_vars["AURASEED_BUNDLE_DIR"] = str(bundle_dir)
        env_vars["AURASEED_ARTIFACTS_DIR"] = str(bundle_dir / "artifacts")
        env_vars["AURASEED_PYTHON"] = str(python_exe)
        env_vars["AURASEED_PORT"] = str(target_port)
        env_vars["AURASEED_HOOK"] = hook_name

        cmd = [
            str(python_exe),
            str(hook_target),
            "--install-dir", str(target_dest),
            "--bundle-dir", str(bundle_dir),
            "--port", str(target_port),
            "--hook", hook_name,
        ]

        proc = subprocess.Popen(
            cmd,
            env=env_vars,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(bundle_dir)
        )
        if proc.stdout:
            for line in proc.stdout:
                clean_line = line.rstrip()
                if clean_line:
                    self.log(f"[{hook_name}] {clean_line}")
            proc.stdout.close()
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"Lifecycle hook '{hook_name}' failed with returncode {proc.returncode}")


