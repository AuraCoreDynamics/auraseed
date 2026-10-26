import os
import sys
import shutil
import platform
from pathlib import Path
from auraseed.models import DiscoveredEnvironment

class HostIsolationEngine:
    """
    Operational Sovereignty Engine:
    Migrates base runtime, anchors dependent DLLs, binds site-packages,
    configures dll directory loaders, and completely severs pyvenv.cfg from host runtime.
    """
    def isolate(self, target_env: DiscoveredEnvironment, venv_path: Path) -> None:
        """
        Executes complete operational sovereignty isolation routine.
        """
        venv_path = venv_path.resolve()
        self._base_runtime_phase(target_env, venv_path)
        self._binding_phase(target_env, venv_path)
        self._dll_anchoring_phase(target_env, venv_path)
        self._asset_migration_phase(target_env, venv_path)
        self._dll_loader_phase(target_env, venv_path)
        self._sever_phase(target_env, venv_path)

    def _base_runtime_phase(self, target_env: DiscoveredEnvironment, venv_path: Path) -> None:
        """
        Migrates python executables, shared libraries, and standard library to venv/base.
        """
        is_windows = platform.system().lower() == "windows"
        base_dir = venv_path / "base"
        base_dir.mkdir(parents=True, exist_ok=True)

        src_dir = target_env.executable.parent

        # 1. Copy python executables to base_dir
        for exe_name in ("python.exe", "pythonw.exe", "python.pdb", "python3.exe", "python312.exe"):
            src_exe = src_dir / exe_name
            dst_exe = base_dir / exe_name
            if src_exe.exists() and not dst_exe.exists():
                shutil.copy2(src_exe, dst_exe)

        # 2. Copy DLLs from interpreter directory to base_dir
        if is_windows:
            for dll in src_dir.glob("*.dll"):
                dst_dll = base_dir / dll.name
                if not dst_dll.exists():
                    shutil.copy2(dll, dst_dll)

            # Copy DLLs directory (contains C-extension .pyd files)
            src_dlls = src_dir / "DLLs"
            if src_dlls.exists() and src_dlls.is_dir():
                dst_dlls = base_dir / "DLLs"
                dst_dlls.mkdir(parents=True, exist_ok=True)
                for item in src_dlls.iterdir():
                    dst_item = dst_dlls / item.name
                    if not dst_item.exists():
                        if item.is_dir():
                            shutil.copytree(item, dst_item)
                        else:
                            shutil.copy2(item, dst_item)

            # Copy standard library zip files (e.g. python312.zip)
            for zip_file in src_dir.glob("python*.zip"):
                dst_zip = base_dir / zip_file.name
                if not dst_zip.exists():
                    shutil.copy2(zip_file, dst_zip)

            # Copy Lib standard library (excluding site-packages)
            src_lib = src_dir / "Lib"
            if src_lib.exists() and src_lib.is_dir():
                dst_lib = base_dir / "Lib"
                dst_lib.mkdir(parents=True, exist_ok=True)
                for item in src_lib.iterdir():
                    if item.name.lower() == "site-packages":
                        continue
                    dst_item = dst_lib / item.name
                    if not dst_item.exists():
                        if item.is_dir():
                            shutil.copytree(item, dst_item)
                        else:
                            shutil.copy2(item, dst_item)

            # Also ensure Scripts/python.exe exists in venv
            scripts_dir = venv_path / "Scripts"
            scripts_dir.mkdir(parents=True, exist_ok=True)
            if not (scripts_dir / "python.exe").exists():
                shutil.copy2(target_env.executable, scripts_dir / "python.exe")
            if (src_dir / "pythonw.exe").exists() and not (scripts_dir / "pythonw.exe").exists():
                shutil.copy2(src_dir / "pythonw.exe", scripts_dir / "pythonw.exe")

    def _binding_phase(self, target_env: DiscoveredEnvironment, venv_path: Path) -> None:
        """
        Binds required packages (target modules and site-packages) into venv site-packages.
        """
        venv_site_packages = self._get_venv_site_packages(venv_path)
        venv_site_packages.mkdir(parents=True, exist_ok=True)

        target_modules = target_env.metadata.get("target_modules", [])
        search_paths = list(target_env.site_packages)
        extra_paths = [Path(p) for p in target_env.metadata.get("extra_paths", [])]
        search_paths.extend(extra_paths)

        # 1. Target modules binding
        for host_sp in search_paths:
            if not host_sp.exists():
                continue
            for module_name in target_modules:
                module_path = host_sp / module_name
                if module_path.exists():
                    dest_path = venv_site_packages / module_name
                    if module_path.is_dir():
                        self._copy_dir_safely(module_path, dest_path)
                    else:
                        self._copy_file_safely(module_path, dest_path)

                # Look for matching dist-info or egg-info
                for info_dir in host_sp.glob(f"{module_name}*.dist-info"):
                    self._copy_dir_safely(info_dir, venv_site_packages / info_dir.name)
                for info_dir in host_sp.glob(f"{module_name}*.egg-info"):
                    self._copy_dir_safely(info_dir, venv_site_packages / info_dir.name)

        # 2. General site-packages migration (copy modules so sovereign environment has dependencies)
        for host_sp in target_env.site_packages:
            if not host_sp.exists():
                continue
            try:
                for item in host_sp.iterdir():
                    if item.name.startswith(".") or item.name == "__pycache__":
                        continue
                    dest_item = venv_site_packages / item.name
                    if not dest_item.exists():
                        if item.is_dir():
                            self._copy_dir_safely(item, dest_item)
                        else:
                            self._copy_file_safely(item, dest_item)
            except (PermissionError, OSError):
                pass

    def _copy_file_safely(self, src: Path, dst: Path) -> None:
        if dst.exists():
            return
        try:
            shutil.copy2(src, dst)
        except Exception:
            pass

    def _copy_dir_safely(self, src: Path, dst: Path) -> None:
        if dst.exists():
            return
        try:
            shutil.copytree(src, dst)
        except Exception:
            pass

    def _dll_anchoring_phase(self, target_env: DiscoveredEnvironment, venv_path: Path) -> None:
        """
        Anchors dependent binary DLLs / shared objects into venv/bin and core Python DLLs into base/Scripts.
        """
        is_windows = platform.system().lower() == "windows"
        bin_dir = venv_path / "bin"
        base_dir = venv_path / "base"
        scripts_dir = venv_path / "Scripts"
        bin_dir.mkdir(parents=True, exist_ok=True)

        source_bin_dirs = []
        for bd in target_env.metadata.get("bin_dirs", []):
            p = Path(bd)
            if p.exists() and p.is_dir():
                source_bin_dirs.append(p)

        parent_bin = target_env.metadata.get("parent_bin_dir")
        if parent_bin:
            p = Path(parent_bin)
            if p.exists() and p.is_dir() and p not in source_bin_dirs:
                source_bin_dirs.append(p)

        core_python_prefixes = ("python", "vcruntime", "msvcp", "api-ms-win", "ucrtbase")
        exts = [".dll"] if is_windows else [".so", ".dylib"]

        for sbd in source_bin_dirs:
            for ext in exts:
                try:
                    for bin_file in sbd.glob(f"*{ext}"):
                        name_lower = bin_file.name.lower()
                        # All application DLLs go into venv/bin (discovered via os.add_dll_directory)
                        dest_bin = bin_dir / bin_file.name
                        if not dest_bin.exists():
                            try:
                                shutil.copy2(bin_file, dest_bin)
                            except Exception:
                                pass

                        # Only core Python runtime DLLs need to reside alongside python.exe in base/Scripts
                        if name_lower.startswith(core_python_prefixes):
                            for target_dest in (base_dir, scripts_dir):
                                dest_core = target_dest / bin_file.name
                                if not dest_core.exists():
                                    try:
                                        shutil.copy2(bin_file, dest_core)
                                    except Exception:
                                        pass
                except (PermissionError, OSError):
                    pass

    def _asset_migration_phase(self, target_env: DiscoveredEnvironment, venv_path: Path) -> None:
        """
        Migrates runtime assets (Qt platform plugins, QGIS providers, GDAL/PROJ data)
        to guarantee functional operational sovereignty without host dependencies.
        """
        # 1. Qt plugins (critical: platforms/qwindows.dll for offscreen/window initialization)
        qt_plugins_src = target_env.metadata.get("qt_plugins_dir")
        if qt_plugins_src:
            src_p = Path(qt_plugins_src)
            if src_p.exists():
                dst_qt = venv_path / "qtplugins"
                platforms_src = src_p / "platforms"
                if platforms_src.exists():
                    self._copy_dir_safely(platforms_src, dst_qt / "platforms")
                for sub in ("styles", "imageformats", "iconengines"):
                    if (src_p / sub).exists():
                        self._copy_dir_safely(src_p / sub, dst_qt / sub)

        # 2. QGIS provider plugins (ogr, gdal, delimitedtext, etc.)
        qgis_plugins_src = target_env.metadata.get("qgis_plugins_dir")
        if qgis_plugins_src:
            src_p = Path(qgis_plugins_src)
            if src_p.exists():
                dst_qgis = venv_path / "qgis_plugins"
                dst_qgis.mkdir(parents=True, exist_ok=True)
                for dll in src_p.glob("*.dll"):
                    self._copy_file_safely(dll, dst_qgis / dll.name)

        # 3. GDAL data directory
        gdal_data_src = target_env.metadata.get("gdal_data_dir")
        if gdal_data_src:
            src_p = Path(gdal_data_src)
            if src_p.exists():
                dst_gdal = venv_path / "gdal_data"
                self._copy_dir_safely(src_p, dst_gdal)

        # 4. PROJ data directory (proj.db)
        proj_data_src = target_env.metadata.get("proj_data_dir")
        if proj_data_src:
            src_p = Path(proj_data_src)
            if src_p.exists():
                dst_proj = venv_path / "proj_data"
                dst_proj.mkdir(parents=True, exist_ok=True)
                for f in src_p.glob("*"):
                    if f.is_file():
                        self._copy_file_safely(f, dst_proj / f.name)

    def _dll_loader_phase(self, target_env: DiscoveredEnvironment, venv_path: Path) -> None:
        """
        Installs an automatic DLL loader on Windows so that Python 3.8+ registers
        the sovereign venv's bin and base directories via os.add_dll_directory(),
        and configures isolated asset environment variables (QT, QGIS, GDAL, PROJ).
        """
        is_windows = platform.system().lower() == "windows"
        if not is_windows:
            return

        venv_sp = self._get_venv_site_packages(venv_path)
        venv_sp.mkdir(parents=True, exist_ok=True)

        loader_py = venv_sp / "_auraseed_dll_loader.py"
        loader_code = (
            "import os, sys\n"
            "from pathlib import Path\n\n"
            "_root = Path(__file__).resolve().parent.parent.parent\n"
            "_candidates = [\n"
            "    _root / 'bin',\n"
            "    _root / 'base',\n"
            "    _root / 'base' / 'DLLs',\n"
            "    _root / 'Scripts',\n"
            "    _root / 'Lib' / 'site-packages'\n"
            "]\n"
            "for _p in _candidates:\n"
            "    if _p.exists():\n"
            "        try:\n"
            "            os.add_dll_directory(str(_p))\n"
            "        except Exception:\n"
            "            pass\n"
            "        _ps = str(_p)\n"
            "        _path = os.environ.get('PATH', '')\n"
            "        if _ps.lower() not in _path.lower():\n"
            "            os.environ['PATH'] = _ps + os.pathsep + _path\n\n"
            "# Assets & GIS Environment Configuration\n"
            "_qt = _root / 'qtplugins'\n"
            "if _qt.exists():\n"
            "    os.environ['QT_PLUGIN_PATH'] = str(_qt)\n"
            "    os.environ['QT_QPA_PLATFORM_PLUGIN_PATH'] = str(_qt / 'platforms')\n"
            "if 'QT_QPA_PLATFORM' not in os.environ:\n"
            "    os.environ['QT_QPA_PLATFORM'] = 'offscreen'\n\n"
            "_qgisp = _root / 'qgis_plugins'\n"
            "if _qgisp.exists():\n"
            "    os.environ['QGIS_PLUGIN_PATH'] = str(_qgisp)\n\n"
            "_gdald = _root / 'gdal_data'\n"
            "if _gdald.exists():\n"
            "    os.environ['GDAL_DATA'] = str(_gdald)\n\n"
            "_projd = _root / 'proj_data'\n"
            "if _projd.exists():\n"
            "    os.environ['PROJ_DATA'] = str(_projd)\n"
            "    os.environ['PROJ_LIB'] = str(_projd)\n"
        )
        loader_py.write_text(loader_code, encoding="utf-8")

        pth_file = venv_sp / "auraseed_dll_loader.pth"
        pth_file.write_text("import _auraseed_dll_loader\n", encoding="utf-8")

    def _sever_phase(self, target_env: DiscoveredEnvironment, venv_path: Path) -> None:
        """
        Rewrites pyvenv.cfg so home points to sovereign base_dir, and purges host .pth files.
        """
        base_dir = venv_path / "base"
        pyvenv_cfg = venv_path / "pyvenv.cfg"

        cfg_lines = []
        cfg_lines.append(f"home = {base_dir}")
        cfg_lines.append("include-system-site-packages = false")
        cfg_lines.append(f"version = {target_env.version}")
        cfg_lines.append(f"executable = {base_dir / 'python.exe'}")
        cfg_lines.append(f"command = {base_dir / 'python.exe'} -m venv {venv_path}")

        pyvenv_cfg.write_text("\n".join(cfg_lines) + "\n", encoding="utf-8")

        # Purge any host .pth files that could retain dynamic references to host or fail
        venv_site_packages = self._get_venv_site_packages(venv_path)
        if venv_site_packages.exists():
            for pth_file in venv_site_packages.glob("*.pth"):
                if pth_file.name == "auraseed_dll_loader.pth":
                    continue
                try:
                    pth_file.unlink()
                except OSError:
                    pass

    def _get_venv_site_packages(self, venv_path: Path) -> Path:
        is_windows = platform.system().lower() == "windows"
        if is_windows:
            return venv_path / "Lib" / "site-packages"
        else:
            lib_dir = venv_path / "lib"
            if lib_dir.exists():
                for py_dir in lib_dir.iterdir():
                    if py_dir.name.startswith("python") and py_dir.is_dir():
                        return py_dir / "site-packages"
            return lib_dir / "python3" / "site-packages"
