import os
import shutil
import platform
from pathlib import Path
from auraseed.models import DiscoveredEnvironment

class HostIsolationEngine:
    """
    Hard-links/copies site-packages, copies binary DLLs, and severs pyvenv.cfg parent dependencies.
    """
    def isolate(self, target_env: DiscoveredEnvironment, venv_path: Path) -> None:
        """
        Executes a three-step isolation routine.
        """
        self._binding_phase(target_env, venv_path)
        self._sever_phase(venv_path)
        self._dll_anchoring_phase(target_env, venv_path)

    def _binding_phase(self, target_env: DiscoveredEnvironment, venv_path: Path) -> None:
        target_modules = target_env.metadata.get("target_modules", [])
        if not target_modules:
            return
            
        venv_site_packages = self._get_venv_site_packages(venv_path)
        
        for host_sp in target_env.site_packages:
            for module_name in target_modules:
                module_path = host_sp / module_name
                if module_path.exists():
                    dest_path = venv_site_packages / module_name
                    if module_path.is_dir():
                        self._copy_or_link_dir(module_path, dest_path)
                    else:
                        self._copy_or_link_file(module_path, dest_path)

    def _copy_or_link_file(self, src: Path, dst: Path) -> None:
        if dst.exists():
            return
        try:
            os.link(src, dst)
        except Exception:
            shutil.copy2(src, dst)

    def _copy_or_link_dir(self, src: Path, dst: Path) -> None:
        if dst.exists():
            return
        try:
            shutil.copytree(src, dst, copy_function=os.link)
        except Exception:
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    def _sever_phase(self, venv_path: Path) -> None:
        pyvenv_cfg = venv_path / "pyvenv.cfg"
        if pyvenv_cfg.exists():
            with open(pyvenv_cfg, "r", encoding="utf-8") as f:
                lines = f.readlines()
            
            with open(pyvenv_cfg, "w", encoding="utf-8") as f:
                for line in lines:
                    if line.startswith("include-system-site-packages"):
                        f.write("include-system-site-packages = false\n")
                    else:
                        f.write(line)
                        
        venv_site_packages = self._get_venv_site_packages(venv_path)
        if venv_site_packages.exists():
            for pth_file in venv_site_packages.glob("*.pth"):
                try:
                    pth_file.unlink()
                except OSError:
                    pass

    def _dll_anchoring_phase(self, target_env: DiscoveredEnvironment, venv_path: Path) -> None:
        bin_dir = target_env.metadata.get("parent_bin_dir")
        if not bin_dir:
            return
        bin_path = Path(bin_dir)
        if not bin_path.exists():
            return
            
        is_windows = platform.system().lower() == "windows"
        dest_dir = venv_path / "Scripts" if is_windows else venv_path / "lib"
        if not dest_dir.exists():
            dest_dir.mkdir(parents=True, exist_ok=True)
        
        exts = [".dll"] if is_windows else [".so", ".dylib"]
        for ext in exts:
            for dll_file in bin_path.glob(f"*{ext}"):
                dest_file = dest_dir / dll_file.name
                if not dest_file.exists():
                    shutil.copy2(dll_file, dest_file)

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
