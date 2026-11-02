"""
Application Bundle Packager for AuraSeed.
Wraps an application, its manifest, dependencies, and AuraSeed Level-0 bootstrappers
into a standalone distributable installer folder or zip archive.
Zero external runtime dependencies (Python standard library only).
"""
import os
import shutil
import zipfile
from pathlib import Path
from typing import Optional

from auraseed.installer.models import AppManifest


class AppBundlePackager:
    def __init__(self, app_dir: Path, auraseed_root: Optional[Path] = None):
        self.app_dir = Path(app_dir).resolve()
        self.manifest = AppManifest.from_file(self.app_dir)
        if auraseed_root:
            self.auraseed_root = Path(auraseed_root).resolve()
        else:
            # Locate auraseed root (where auraseed.ps1 and bootstrap.json reside)
            self.auraseed_root = Path(__file__).resolve().parent.parent.parent

    def package(self, output_dir: Path, create_zip: bool = False) -> Path:
        """
        Creates the standalone installer bundle.
        """
        out_path = Path(output_dir).resolve()
        bundle_dir = out_path / f"{self.manifest.name}-installer" if create_zip else out_path

        if bundle_dir.exists():
            shutil.rmtree(bundle_dir, ignore_errors=True)
        bundle_dir.mkdir(parents=True, exist_ok=True)

        # 1. Copy application source payload into payload/
        payload_dir = bundle_dir / "payload"
        payload_dir.mkdir(parents=True, exist_ok=True)
        self._copy_tree_clean(self.app_dir, payload_dir)

        # 2. Copy auraseed runtime into bundle
        auraseed_pkg_src = self.auraseed_root / "auraseed"
        auraseed_pkg_dst = bundle_dir / "auraseed"
        self._copy_tree_clean(auraseed_pkg_src, auraseed_pkg_dst)

        # 3. Copy bootstrap.json
        bootstrap_json = self.auraseed_root / "bootstrap.json"
        if bootstrap_json.exists():
            shutil.copy2(bootstrap_json, bundle_dir / "bootstrap.json")

        # 4. Generate app.json in bundle root pointing source_path to payload
        manifest_copy = AppManifest.from_dict(self.manifest.__dict__)
        manifest_copy.source_path = "payload"
        # Update relative subproject paths to payload/<subproject>
        subprojects_in_bundle = []
        for sp in manifest_copy.subprojects:
            subprojects_in_bundle.append(f"payload/{sp}")
        manifest_copy.subprojects = subprojects_in_bundle
        manifest_copy.to_file(bundle_dir / "app.json")

        # 5. Generate Level-0 Installer Bootstrappers
        self._generate_bootstrappers(bundle_dir)

        if create_zip:
            zip_target = out_path / f"{self.manifest.name}-installer.zip"
            if zip_target.exists():
                zip_target.unlink()
            with zipfile.ZipFile(zip_target, "w", zipfile.ZIP_DEFLATED) as zf:
                for root, _, files in os.walk(bundle_dir):
                    for file in files:
                        full_path = Path(root) / file
                        rel_path = full_path.relative_to(bundle_dir)
                        zf.write(full_path, rel_path)
            shutil.rmtree(bundle_dir, ignore_errors=True)
            return zip_target

        return bundle_dir

    def _copy_tree_clean(self, src: Path, dst: Path):
        ignore_patterns = shutil.ignore_patterns(
            "__pycache__", "*.pyc", ".git", ".github", ".venv", "venv",
            ".bootstrapped_python", "*.egg-info", "dist", "build", ".pytest_cache"
        )
        shutil.copytree(src, dst, dirs_exist_ok=True, ignore=ignore_patterns)

    def _generate_bootstrappers(self, bundle_dir: Path):
        # install.bat
        install_bat = bundle_dir / "install.bat"
        bat_content = (
            "@echo off\r\n"
            "setlocal\r\n"
            "if exist \"%~dp0install.ps1\" (\r\n"
            "    powershell -NoProfile -ExecutionPolicy Bypass -File \"%~dp0install.ps1\" %*\r\n"
            "    exit /b %ERRORLEVEL%\r\n"
            ")\r\n"
            "echo [AuraSeed] Error: install.ps1 not found.\r\n"
            "pause\r\n"
            "exit /b 1\r\n"
        )
        install_bat.write_text(bat_content, encoding="utf-8")

        # install.ps1
        # Read the robust auraseed.ps1 and adjust entrypoint to run `install-app`
        auraseed_ps1 = self.auraseed_root / "auraseed.ps1"
        if auraseed_ps1.exists():
            base_ps1 = auraseed_ps1.read_text(encoding="utf-8")
            # Replace default module execution `& $FoundPython -m auraseed $args` with `install-app`
            replaced = base_ps1.replace(
                "& $FoundPython -m auraseed $args",
                "& $FoundPython -m auraseed install-app \"$PSScriptRoot\\app.json\" $args"
            )
            (bundle_dir / "install.ps1").write_text(replaced, encoding="utf-8")

        # install.sh
        auraseed_sh = self.auraseed_root / "auraseed.sh"
        if auraseed_sh.exists():
            base_sh = auraseed_sh.read_text(encoding="utf-8")
            replaced = base_sh.replace(
                'exec "$FOUND_PYTHON" -m auraseed "$@"',
                'exec "$FOUND_PYTHON" -m auraseed install-app "$SCRIPT_DIR/app.json" "$@"'
            )
            sh_target = bundle_dir / "install.sh"
            sh_target.write_text(replaced, encoding="utf-8")
            sh_target.chmod(0o755)

