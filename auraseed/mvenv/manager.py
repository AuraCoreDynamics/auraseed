import os
import sys
import shutil
import tarfile
import hashlib
import platform
import subprocess
from pathlib import Path
from typing import Dict, Any, List, Optional
from datetime import datetime, timezone

from auraseed.models import DiscoveredEnvironment
from auraseed.discovery.manager import DiscoveryManager
from auraseed.discovery.os.windows import WindowsDiscoverer
from auraseed.discovery.os.linux import LinuxDiscoverer
from auraseed.discovery.os.macos import MacOSDiscoverer
from auraseed.governance.rules import LatestVersionStrategy
from auraseed.seed.sovereign import SovereignVenvEngine
from auraseed.seed.isolation import HostIsolationEngine
from auraseed.mvenv.models import MvenvRecord, MvenvCreateRequest, MvenvBundleMetadata
from auraseed.mvenv.catalog import MvenvCatalog


class MvenvManager:
    """
    First-class Managed Virtual Environment (mvenv) Engine and Catalog Manager.
    Works standalone or as an integrated service within AuraGrid.
    """

    def __init__(self, root_path: Optional[Path] = None):
        self.root_path = self._resolve_root_path(root_path)
        self.catalog = MvenvCatalog(self.root_path)

    @staticmethod
    def _resolve_root_path(explicit_path: Optional[Path]) -> Path:
        if explicit_path:
            p = Path(explicit_path).resolve()
            p.mkdir(parents=True, exist_ok=True)
            return p

        # 1. Environment variable overrides
        for env_var in ("AURASEED_MVENV_ROOT", "AURAGRID_MVENV_ROOT", "AURA_MVENV_ROOT"):
            val = os.environ.get(env_var)
            if val and val.strip():
                p = Path(val.strip()).resolve()
                p.mkdir(parents=True, exist_ok=True)
                return p

        # 2. Check for active AuraGrid data directory
        grid_dir = os.environ.get("AURAGRID_DATA_DIR")
        if grid_dir and os.path.isdir(grid_dir):
            p = Path(grid_dir) / "mvenvs"
            p.mkdir(parents=True, exist_ok=True)
            return p

        # 3. OS default paths
        is_win = platform.system().lower() == "windows"
        if is_win:
            local_appdata = os.environ.get("LOCALAPPDATA")
            if local_appdata and os.path.exists(Path(local_appdata) / "AuraGrid"):
                p = Path(local_appdata) / "AuraGrid" / "mvenvs"
                p.mkdir(parents=True, exist_ok=True)
                return p
            p = Path.home() / ".auraseed" / "mvenvs"
        else:
            if os.path.exists("/var/lib/auragrid"):
                p = Path("/var/lib/auragrid/mvenvs")
                try:
                    p.mkdir(parents=True, exist_ok=True)
                    return p
                except OSError:
                    pass
            p = Path.home() / ".auraseed" / "mvenvs"

        p.mkdir(parents=True, exist_ok=True)
        return p

    def list_venvs(self) -> List[MvenvRecord]:
        return self.catalog.list_records()

    def get_venv(self, name: str) -> Optional[MvenvRecord]:
        return self.catalog.get_record(name)

    def _discover_best_interpreter(self) -> DiscoveredEnvironment:
        """
        Discovers the best host interpreter using AuraSeed's discovery engine.
        """
        manager = DiscoveryManager()
        sys_plat = platform.system().lower()
        if sys_plat == "windows":
            manager.register_strategy(WindowsDiscoverer())
        elif sys_plat == "linux":
            manager.register_strategy(LinuxDiscoverer())
        elif sys_plat == "darwin":
            manager.register_strategy(MacOSDiscoverer())

        results = manager.run_discovery()
        env_list = list(results.values())

        if env_list:
            strategy = LatestVersionStrategy()
            selected = strategy.select(env_list)
            if selected:
                return selected

        # Fallback to current running Python
        cur_exe = Path(sys.executable).resolve()
        ver_str = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        return DiscoveredEnvironment(
            id="current_python",
            name="Current Python",
            executable=cur_exe,
            version=ver_str,
            source_type="system_fallback",
            site_packages=[]
        )

    def create_venv(self, req: MvenvCreateRequest) -> MvenvRecord:
        """
        Creates, seeds, and catalogs a managed virtual environment.
        """
        safe_name = "".join([c if c.isalnum() or c in "-_" else "_" for c in req.name]).strip("_")
        if not safe_name:
            raise ValueError(f"Invalid mvenv name: {req.name}")

        dest_dir = Path(req.target_dir) if req.target_dir else self.root_path / safe_name
        dest_dir = dest_dir.resolve()

        if dest_dir.exists():
            if not req.force:
                existing = self.catalog.get_record(safe_name)
                if existing:
                    return existing
                raise FileExistsError(f"Environment directory already exists: {dest_dir}")
            else:
                shutil.rmtree(dest_dir, ignore_errors=True)

        dest_dir.mkdir(parents=True, exist_ok=True)

        # 1. Resolve base interpreter
        if req.base_python and Path(req.base_python).exists():
            base_exe = Path(req.base_python).resolve()
            ver_cmd = [str(base_exe), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"]
            try:
                ver_res = subprocess.run(ver_cmd, capture_output=True, text=True, timeout=10)
                ver_str = ver_res.stdout.strip() or "3.x"
            except Exception:
                ver_str = "3.x"

            target_env = DiscoveredEnvironment(
                id=f"custom_{base_exe.stem}",
                name=f"Custom ({base_exe.name})",
                executable=base_exe,
                version=ver_str,
                source_type="custom_path",
                site_packages=[]
            )
        else:
            target_env = self._discover_best_interpreter()

        # 2. Seed venv scaffold
        seeder = SovereignVenvEngine()
        seeder.create_venv(target_env, dest_dir)

        # 3. Sovereign isolation (if requested)
        if req.sovereign:
            try:
                isolation = HostIsolationEngine()
                isolation.isolate(target_env, dest_dir)
            except Exception as e:
                # If isolation throws on unusual distribution, continue with scaffold
                pass

        # 4. Resolve python and pip in newly created environment
        python_exe = MvenvCatalog._find_python_exe(dest_dir)
        if not python_exe or not python_exe.exists():
            raise RuntimeError(f"Failed to locate python binary inside new mvenv: {dest_dir}")

        # Ensure pip is installed
        pip_exe = MvenvCatalog._find_pip_exe(dest_dir)
        if not pip_exe or not pip_exe.exists():
            try:
                subprocess.run([str(python_exe), "-m", "ensurepip", "--default-pip"],
                               capture_output=True, timeout=60)
                pip_exe = MvenvCatalog._find_pip_exe(dest_dir)
            except Exception:
                pass

        # 5. Install packages if requested
        installed_packages: List[str] = []
        if req.packages:
            self._run_pip_install(python_exe, pip_exe, req.packages)
            installed_packages.extend(req.packages)

        if req.requirements_file and os.path.exists(req.requirements_file):
            self._run_pip_requirements(python_exe, pip_exe, req.requirements_file)

        # Gathers installed packages
        actual_packages = self._query_installed_packages(python_exe)
        for p in actual_packages:
            if p not in installed_packages:
                installed_packages.append(p)

        # Determine exact Python version
        py_version = self._query_python_version(python_exe) or target_env.version

        now_iso = datetime.now(timezone.utc).isoformat()
        record = MvenvRecord(
            name=safe_name,
            path=str(dest_dir),
            python_path=str(python_exe),
            pip_path=str(pip_exe) if pip_exe else "",
            python_version=py_version,
            base_interpreter=str(target_env.executable),
            created_at=now_iso,
            updated_at=now_iso,
            packages=installed_packages,
            size_bytes=MvenvCatalog._calculate_dir_size(dest_dir),
            is_sovereign=req.sovereign,
            metadata=dict(req.tags or {})
        )

        self.catalog.save_record(record)
        return record

    def install_packages(self, name: str, packages: List[str], upgrade: bool = False) -> MvenvRecord:
        """
        Installs additional pip packages into a managed virtual environment.
        """
        rec = self.get_venv(name)
        if not rec:
            raise KeyError(f"Managed venv '{name}' not found.")

        python_exe = Path(rec.python_path)
        pip_exe = Path(rec.pip_path) if rec.pip_path else None
        self._run_pip_install(python_exe, pip_exe, packages, upgrade=upgrade)

        updated_pkgs = list(set(rec.packages + packages))
        rec.packages = updated_pkgs
        rec.updated_at = datetime.now(timezone.utc).isoformat()
        rec.size_bytes = MvenvCatalog._calculate_dir_size(Path(rec.path))

        self.catalog.save_record(rec)
        return rec

    def install_requirements(self, name: str, requirements_path: str) -> MvenvRecord:
        """
        Installs packages from a requirements.txt file.
        """
        rec = self.get_venv(name)
        if not rec:
            raise KeyError(f"Managed venv '{name}' not found.")

        python_exe = Path(rec.python_path)
        pip_exe = Path(rec.pip_path) if rec.pip_path else None
        self._run_pip_requirements(python_exe, pip_exe, requirements_path)

        actual_packages = self._query_installed_packages(python_exe)
        rec.packages = actual_packages
        rec.updated_at = datetime.now(timezone.utc).isoformat()
        rec.size_bytes = MvenvCatalog._calculate_dir_size(Path(rec.path))

        self.catalog.save_record(rec)
        return rec

    def delete_venv(self, name: str) -> bool:
        """
        Deletes a managed virtual environment from disk and unregisters it.
        """
        rec = self.get_venv(name)
        if not rec:
            return False

        env_dir = Path(rec.path)
        if env_dir.exists():
            shutil.rmtree(env_dir, ignore_errors=True)

        self.catalog.remove_record(name)
        return True

    def export_bundle(self, name: str, output_path: Optional[Path] = None) -> Path:
        """
        Exports an mvenv into an autonomous, portable .tar.gz bundle.
        """
        rec = self.get_venv(name)
        if not rec:
            raise KeyError(f"Managed venv '{name}' not found.")

        env_dir = Path(rec.path)
        bundle_id = hashlib.sha256(f"{name}_{rec.created_at}".encode("utf-8")).hexdigest()[:16]

        if not output_path:
            output_dir = self.root_path / ".bundles"
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f"{name}-{rec.python_version}-{bundle_id}.tar.gz"
        else:
            output_path = Path(output_path).resolve()
            output_path.parent.mkdir(parents=True, exist_ok=True)

        meta = MvenvBundleMetadata(
            name=rec.name,
            bundle_id=bundle_id,
            bundle_hash="",
            created_at=datetime.now(timezone.utc).isoformat(),
            python_version=rec.python_version,
            platform=platform.system().lower(),
            arch=platform.machine().lower(),
            packages=rec.packages,
            is_sovereign=rec.is_sovereign,
            metadata=rec.metadata
        )

        # Write manifest into venv before bundling
        manifest_path = env_dir / "bundle.manifest.json"
        manifest_path.write_text(meta.to_dict().__repr__(), encoding="utf-8")

        with tarfile.open(output_path, "w:gz") as tar:
            tar.add(env_dir, arcname=name)

        # Compute SHA-256
        sha256 = hashlib.sha256()
        with open(output_path, "rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        digest = sha256.hexdigest()

        rec.bundle_hash = digest
        self.catalog.save_record(rec)
        return output_path

    def import_bundle(self, bundle_path: Path, target_name: Optional[str] = None, force: bool = False) -> MvenvRecord:
        """
        Imports and unpackages an mvenv bundle into the local catalog.
        """
        bundle_path = Path(bundle_path).resolve()
        if not bundle_path.exists():
            raise FileNotFoundError(f"Bundle file not found: {bundle_path}")

        # Compute SHA-256 of bundle
        sha256 = hashlib.sha256()
        with open(bundle_path, "rb") as f:
            while chunk := f.read(65536):
                sha256.update(chunk)
        bundle_hash = sha256.hexdigest()

        temp_extract = self.root_path / f".tmp_extract_{os.getpid()}_{hashlib.sha256(bundle_path.name.encode()).hexdigest()[:8]}"
        temp_extract.mkdir(parents=True, exist_ok=True)

        try:
            with tarfile.open(bundle_path, "r:gz") as tar:
                members = tar.getmembers()
                if not members:
                    raise ValueError("Empty tar bundle.")
                extracted_root_name = members[0].name.split("/")[0].split("\\")[0]
                name = target_name or extracted_root_name
                dest_dir = self.root_path / name

                if dest_dir.exists():
                    if not force:
                        raise FileExistsError(f"Target mvenv directory already exists: {dest_dir}")
                    shutil.rmtree(dest_dir, ignore_errors=True)

                tar.extractall(path=temp_extract)

            extracted_item = temp_extract / extracted_root_name
            if extracted_item.exists() and extracted_item.is_dir():
                shutil.move(str(extracted_item), str(dest_dir))
            else:
                shutil.move(str(temp_extract), str(dest_dir))
        finally:
            if temp_extract.exists():
                shutil.rmtree(temp_extract, ignore_errors=True)

        # Re-resolve paths in unpacked environment
        python_exe = MvenvCatalog._find_python_exe(dest_dir)
        pip_exe = MvenvCatalog._find_pip_exe(dest_dir)

        py_version = self._query_python_version(python_exe) if python_exe else "unknown"
        now_iso = datetime.now(timezone.utc).isoformat()

        rec = MvenvRecord(
            name=name,
            path=str(dest_dir),
            python_path=str(python_exe) if python_exe else "",
            pip_path=str(pip_exe) if pip_exe else "",
            python_version=py_version,
            base_interpreter="",
            created_at=now_iso,
            updated_at=now_iso,
            packages=self._query_installed_packages(python_exe) if python_exe else [],
            size_bytes=MvenvCatalog._calculate_dir_size(dest_dir),
            is_sovereign=True,
            bundle_hash=bundle_hash
        )

        self.catalog.save_record(rec)
        return rec

    def verify_venv(self, name: str) -> Dict[str, Any]:
        """
        Executes diagnostic verification of a managed environment.
        """
        rec = self.get_venv(name)
        if not rec:
            return {"valid": False, "error": f"Mvenv '{name}' not found"}

        py_exe = Path(rec.python_path)
        if not py_exe.exists():
            return {"valid": False, "error": f"Python executable missing at {py_exe}"}

        try:
            res = subprocess.run([str(py_exe), "-c", "import sys; print(sys.version)"],
                                 capture_output=True, text=True, timeout=10)
            if res.returncode != 0:
                return {"valid": False, "error": f"Python returned error: {res.stderr}"}

            return {
                "valid": True,
                "name": rec.name,
                "python_path": str(py_exe),
                "python_version": res.stdout.strip(),
                "is_sovereign": rec.is_sovereign,
                "size_bytes": rec.size_bytes,
                "package_count": len(rec.packages)
            }
        except Exception as e:
            return {"valid": False, "error": str(e)}

    @staticmethod
    def _run_pip_install(python_exe: Path, pip_exe: Optional[Path], packages: List[str], upgrade: bool = False):
        if not packages:
            return
        cmd = [str(python_exe), "-m", "pip", "install"]
        if upgrade:
            cmd.append("--upgrade")
        cmd.extend(packages)
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=180)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"pip install failed for {packages}: {e.stderr or e.stdout}")

    @staticmethod
    def _run_pip_requirements(python_exe: Path, pip_exe: Optional[Path], req_file: str):
        cmd = [str(python_exe), "-m", "pip", "install", "-r", str(req_file)]
        try:
            subprocess.run(cmd, check=True, capture_output=True, text=True, timeout=300)
        except subprocess.CalledProcessError as e:
            raise RuntimeError(f"pip install -r failed for {req_file}: {e.stderr or e.stdout}")

    @staticmethod
    def _query_installed_packages(python_exe: Optional[Path]) -> List[str]:
        if not python_exe or not python_exe.exists():
            return []
        try:
            cmd = [str(python_exe), "-m", "pip", "list", "--format=freeze"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if res.returncode == 0:
                lines = res.stdout.strip().splitlines()
                return [line.strip() for line in lines if line.strip() and not line.startswith("-e")]
        except Exception:
            pass
        return []

    @staticmethod
    def _query_python_version(python_exe: Optional[Path]) -> Optional[str]:
        if not python_exe or not python_exe.exists():
            return None
        try:
            cmd = [str(python_exe), "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}')"]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.strip()
        except Exception:
            pass
        return None
