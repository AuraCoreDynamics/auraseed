import logging
import os
import sys
import shutil
import tarfile
import hashlib
import platform
import subprocess
from pathlib import Path
from typing import Callable, Dict, Any, List, Optional
from datetime import datetime, timezone

from auraseed.models import DiscoveredEnvironment
from auraseed.discovery.manager import DiscoveryManager
from auraseed.discovery.os.windows import WindowsDiscoverer
from auraseed.discovery.os.linux import LinuxDiscoverer
from auraseed.discovery.os.macos import MacOSDiscoverer
from auraseed.discovery.adapters.arcpro import ArcProDiscoverer
from auraseed.discovery.adapters.qgis import QgisDiscoverer
from auraseed.discovery.adapters.toolchains import ToolchainDiscoverer
from auraseed.discovery.adapters.embedded import EmbeddedAppDiscoverer
from auraseed.governance.rules import CapabilityScoreStrategy, LatestVersionStrategy, VersionSpecStrategy
from auraseed.seed.sovereign import SovereignVenvEngine
from auraseed.seed.isolation import HostIsolationEngine
from auraseed.seed.artifacts import generate_launchers
from auraseed.registry.manager import RegistryManager
from auraseed.mvenv.models import MvenvRecord, MvenvCreateRequest, MvenvBundleMetadata
from auraseed.mvenv.catalog import MvenvCatalog

_LOG = logging.getLogger(__name__)


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

    def _current_python_env(self) -> DiscoveredEnvironment:
        cur_exe = Path(sys.executable).resolve()
        ver_str = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
        bin_dirs = [cur_exe.parent]
        if (cur_exe.parent / "DLLs").exists():
            bin_dirs.append(cur_exe.parent / "DLLs")
        if (cur_exe.parent / "Library" / "bin").exists():
            bin_dirs.append(cur_exe.parent / "Library" / "bin")

        site_packages: List[Path] = []
        win_sp = cur_exe.parent / "Lib" / "site-packages"
        if win_sp.exists():
            site_packages.append(win_sp)
        posix_sp = cur_exe.parent.parent / "lib" / f"python{sys.version_info.major}.{sys.version_info.minor}" / "site-packages"
        if posix_sp.exists():
            site_packages.append(posix_sp)

        return DiscoveredEnvironment(
            id="current_python",
            name="Current Python",
            executable=cur_exe,
            version=ver_str,
            source_type="system_fallback",
            site_packages=site_packages,
            metadata={
                "parent_bin_dir": str(cur_exe.parent),
                "bin_dirs": [str(b) for b in bin_dirs]
            }
        )

    def _build_discovery_manager(self, adapter: str = "all") -> DiscoveryManager:
        manager = DiscoveryManager()
        sys_plat = platform.system().lower()
        norm_adapter = (adapter or "all").strip().lower()

        if sys_plat == "windows" and norm_adapter in ("all", "windows_registry", "system", "os"):
            manager.register_strategy(WindowsDiscoverer())
        elif sys_plat == "linux" and norm_adapter in ("all", "linux_system", "system", "os"):
            manager.register_strategy(LinuxDiscoverer())
        elif sys_plat == "darwin" and norm_adapter in ("all", "macos_system", "system", "os"):
            manager.register_strategy(MacOSDiscoverer())

        if norm_adapter in ("all", "toolchains", "toolchain_adapter"):
            manager.register_strategy(ToolchainDiscoverer())
        if norm_adapter in ("all", "embedded_apps", "embedded"):
            manager.register_strategy(EmbeddedAppDiscoverer())

        if sys_plat == "windows" and norm_adapter in ("all", "arcpro", "arcpro_adapter"):
            manager.register_strategy(ArcProDiscoverer())
        if norm_adapter in ("all", "qgis", "qgis_adapter"):
            manager.register_strategy(QgisDiscoverer())
        return manager

    def discover_interpreters(
        self,
        adapter: str = "all",
        probe_capabilities: bool = False,
        use_cache: bool = False,
        required_modules: Optional[List[str]] = None,
        required_packages: Optional[List[str]] = None,
    ) -> List[DiscoveredEnvironment]:
        """
        Discovers available host Python interpreters using AuraSeed's discovery engine.
        Supports adapter filters: all, windows_registry, linux_system, macos_system,
        toolchains, embedded_apps, arcpro, qgis.
        """
        norm_adapter = (adapter or "all").strip().lower()
        manager = self._build_discovery_manager(norm_adapter)

        results = manager.run_discovery(
            probe_capabilities=probe_capabilities,
            use_cache=use_cache,
            required_modules=required_modules,
            required_packages=required_packages,
        )
        env_list = list(results.values())

        for env_item in env_list:
            ver = (env_item.version or "").strip()
            if not ver or not ver[0].isdigit() or ver.endswith(".x"):
                probed = self._query_python_version(Path(env_item.executable))
                if probed:
                    env_item.version = probed

        if norm_adapter == "all":
            cur_fallback = self._current_python_env()
            seen_exes = {str(Path(e.executable).resolve()).lower() for e in env_list}
            if str(cur_fallback.executable.resolve()).lower() not in seen_exes:
                env_list.append(cur_fallback)

        return env_list

    def discover_venvs(self, include_registry: bool = True) -> List[MvenvRecord]:
        """
        Discovers managed virtual environments in the configured catalog root,
        and optionally scans OS AuraSeed registry manifests and default user venv folders.
        """
        records: List[MvenvRecord] = list(self.list_venvs())
        seen_paths = {str(Path(r.path).resolve()).lower() for r in records if r.path}

        if not include_registry:
            return records

        sys_plat = platform.system().lower()
        candidate_reg_dirs = [Path.home() / ".auraseed"]
        if sys_plat == "windows":
            local_appdata = os.environ.get("LOCALAPPDATA")
            if local_appdata:
                candidate_reg_dirs.append(Path(local_appdata) / "auraseed")
        elif sys_plat == "darwin":
            candidate_reg_dirs.append(Path.home() / "Library" / "Application Support" / "auraseed")
        else:
            xdg_cfg = os.environ.get("XDG_CONFIG_HOME")
            candidate_reg_dirs.append(Path(xdg_cfg) / "auraseed" if xdg_cfg else Path.home() / ".config" / "auraseed")

        for reg_dir in candidate_reg_dirs:
            try:
                manifest = RegistryManager(reg_dir).read_manifest()
                envs = manifest.get("environments", {})
                if not isinstance(envs, dict):
                    continue
                for env_name, val in envs.items():
                    if isinstance(val, str):
                        cand_dir = Path(val)
                    elif isinstance(val, dict):
                        if val.get("bootstrapped"):
                            continue
                        raw_path = val.get("path") or val.get("venv_path") or val.get("install_dir")
                        if not raw_path:
                            continue
                        cand_dir = Path(raw_path)
                    else:
                        continue

                    if not cand_dir.is_dir():
                        continue
                    if not ((cand_dir / ".mvenv.json").exists() or (cand_dir / "pyvenv.cfg").exists()):
                        continue
                    resolved_str = str(cand_dir.resolve()).lower()
                    if resolved_str in seen_paths:
                        continue
                    rec = self.catalog._load_record_from_dir(env_name, cand_dir.resolve())
                    if rec is not None:
                        records.append(rec)
                        seen_paths.add(resolved_str)
            except Exception:
                continue

        # Scan standard ~/.auraseed/{mvenvs,venvs} folders as well
        for extra_root in (Path.home() / ".auraseed" / "mvenvs", Path.home() / ".auraseed" / "venvs"):
            try:
                if not extra_root.exists() or extra_root.resolve() == self.root_path.resolve():
                    continue
                for child in sorted(extra_root.iterdir()):
                    if not child.is_dir() or child.name.startswith("."):
                        continue
                    if not ((child / ".mvenv.json").exists() or (child / "pyvenv.cfg").exists()):
                        continue
                    resolved_str = str(child.resolve()).lower()
                    if resolved_str in seen_paths:
                        continue
                    rec = self.catalog._load_record_from_dir(child.name, child.resolve())
                    if rec is not None:
                        records.append(rec)
                        seen_paths.add(resolved_str)
            except Exception:
                continue

        return records

    def _resolve_mvenv(self, name: str) -> MvenvRecord:
        rec = self.get_venv(name)
        if rec:
            return rec

        as_path = Path(name)
        if as_path.exists() and as_path.is_dir():
            loaded = self.catalog._load_record_from_dir(as_path.name, as_path.resolve())
            if loaded:
                return loaded

        for disc in self.discover_venvs(include_registry=True):
            if disc.name == name:
                return disc

        raise KeyError(f"Managed venv '{name}' not found.")

    def get_activation_info(self, name: str) -> Dict[str, Any]:
        """
        Returns activation script paths, binary locations, and shell commands to use an mvenv.
        """
        rec = self._resolve_mvenv(name)
        venv_dir = Path(rec.path)
        py_exe = Path(rec.python_path) if rec.python_path else MvenvCatalog._find_python_exe(venv_dir)
        pip_exe = Path(rec.pip_path) if rec.pip_path else MvenvCatalog._find_pip_exe(venv_dir)
        is_win = platform.system().lower() == "windows"
        scripts_dir = venv_dir / ("Scripts" if is_win else "bin")

        activate_ps1 = scripts_dir / "Activate.ps1"
        activate_bat = scripts_dir / "activate.bat"
        activate_sh = (venv_dir / "bin" / "activate") if not is_win else (scripts_dir / "activate")
        launcher = (venv_dir / "auraseed-run.cmd") if is_win else (venv_dir / "bin" / "auraseed-run.sh")

        if is_win:
            commands = {
                "powershell": f'& "{activate_ps1}"' if activate_ps1.exists() else f'$env:PATH = "{scripts_dir};$env:PATH"',
                "cmd": f'call "{activate_bat}"' if activate_bat.exists() else f'set "PATH={scripts_dir};%PATH%"',
                "bash": f'source "{activate_sh.as_posix()}"' if activate_sh.exists() else f'export PATH="{scripts_dir.as_posix()}:$PATH"',
                "direct_python": f'"{py_exe}"' if py_exe else "",
            }
        else:
            commands = {
                "bash": f'. "{activate_sh}"' if activate_sh.exists() else f'export PATH="{scripts_dir}:$PATH"',
                "powershell": f'& "{activate_ps1}"' if activate_ps1.exists() else f'$env:PATH = "{scripts_dir}:$env:PATH"',
                "direct_python": f'"{py_exe}"' if py_exe else "",
            }

        return {
            "name": rec.name,
            "venv_path": str(venv_dir),
            "python_path": str(py_exe) if py_exe else "",
            "pip_path": str(pip_exe) if pip_exe else "",
            "scripts_dir": str(scripts_dir),
            "activate_scripts": {
                "powershell": str(activate_ps1) if activate_ps1.exists() else None,
                "cmd": str(activate_bat) if activate_bat.exists() else None,
                "bash": str(activate_sh) if activate_sh.exists() else None,
            },
            "launcher": str(launcher) if launcher.exists() else None,
            "commands": commands,
        }

    def run_in_venv(
        self,
        name: str,
        command: Optional[List[str]] = None,
        python_args: Optional[List[str]] = None,
        cwd: Optional[str] = None,
        extra_env: Optional[Dict[str, str]] = None,
        timeout: Optional[int] = 300
    ) -> Dict[str, Any]:
        """
        Executes a command or Python script inside the managed virtual environment
        with VIRTUAL_ENV and PATH isolated to that environment.
        """
        rec = self._resolve_mvenv(name)
        venv_dir = Path(rec.path)
        py_exe = Path(rec.python_path) if rec.python_path else MvenvCatalog._find_python_exe(venv_dir)
        if not py_exe or not py_exe.exists():
            raise FileNotFoundError(f"Python executable not found for mvenv '{name}' at '{rec.python_path}'.")

        is_win = platform.system().lower() == "windows"
        scripts_dir = venv_dir / ("Scripts" if is_win else "bin")

        if command and python_args:
            raise ValueError("Provide either 'command' or 'python_args', not both.")

        if python_args is not None:
            exec_cmd = [str(py_exe)] + [str(a) for a in python_args]
        elif command:
            cmd_list = [str(c) for c in command]
            prog = cmd_list[0]
            prog_lower = prog.lower()
            if prog_lower in ("python", "python3", "python.exe", "python3.exe"):
                resolved_prog = str(py_exe)
            elif prog_lower in ("pip", "pip3", "pip.exe") and rec.pip_path and Path(rec.pip_path).exists():
                resolved_prog = str(rec.pip_path)
            else:
                resolved_prog = prog
                candidate_names = [prog, f"{prog}.exe", f"{prog}.cmd", f"{prog}.bat"] if is_win else [prog]
                for cname in candidate_names:
                    cand = scripts_dir / cname
                    if cand.exists() and cand.is_file():
                        resolved_prog = str(cand)
                        break
            exec_cmd = [resolved_prog] + cmd_list[1:]
        else:
            raise ValueError("No command or python arguments provided.")

        env = os.environ.copy()
        env["VIRTUAL_ENV"] = str(venv_dir)
        env.pop("PYTHONHOME", None)
        env.pop("__PYVENV_LAUNCHER__", None)

        path_additions: List[str] = []
        for d in (scripts_dir, venv_dir / "bin", venv_dir / "base"):
            if d.exists():
                path_additions.append(str(d))
        if path_additions:
            existing_path = env.get("PATH", "")
            env["PATH"] = os.pathsep.join(path_additions + ([existing_path] if existing_path else []))

        if extra_env:
            for k, v in extra_env.items():
                env[str(k)] = str(v)

        res = subprocess.run(
            exec_cmd,
            cwd=str(Path(cwd).resolve()) if cwd else None,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout
        )

        return {
            "name": rec.name,
            "command": exec_cmd,
            "returncode": res.returncode,
            "stdout": res.stdout,
            "stderr": res.stderr,
            "python_path": str(py_exe),
            "venv_path": str(venv_dir)
        }

    def _discover_best_interpreter(
        self,
        adapter: str = "all",
        python_spec: Optional[str] = None
    ) -> DiscoveredEnvironment:
        """
        Discovers the best host interpreter using AuraSeed's capability-aware
        discovery engine, optionally constrained by adapter and semantic version spec.
        """
        norm_adapter = (adapter or "all").strip().lower()
        manager = self._build_discovery_manager(norm_adapter)

        if python_spec:
            env_list = list(manager.run_discovery(probe_capabilities=True, use_cache=True).values())
            if not env_list:
                if norm_adapter != "all":
                    raise ValueError(f"No Python interpreters discovered for adapter '{adapter}'.")
                env_list = [self._current_python_env()]
            selected = VersionSpecStrategy(python_spec).select(env_list)
            if not selected:
                available = ", ".join(f"{e.name} ({e.version})" for e in env_list[:8])
                raise ValueError(
                    f"No discovered Python interpreter satisfies spec '{python_spec}' "
                    f"(adapter='{adapter}'; available: {available})."
                )
            return selected

        best = manager.select_best(probe_capabilities=True, use_cache=True)
        if best is not None:
            return best

        if norm_adapter != "all":
            env_list = self.discover_interpreters(adapter=norm_adapter, probe_capabilities=True, use_cache=True)
            if not env_list:
                raise ValueError(f"No Python interpreters discovered for adapter '{adapter}'.")
            return CapabilityScoreStrategy().select(env_list) or LatestVersionStrategy().select(env_list) or env_list[0]

        return self._current_python_env()

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
            target_env = self._discover_best_interpreter(
                adapter=getattr(req, "adapter", "all") or "all",
                python_spec=getattr(req, "python_spec", None)
            )

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

        # Generate convenient OS launchers (auraseed-run.cmd / auraseed-run.sh)
        try:
            generate_launchers(dest_dir)
        except Exception:
            pass

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

    def merge_venvs(
        self,
        source_names: List[str],
        target_name: str,
        delete_sources: bool = False,
        repoint_apps: bool = True,
        repoint_callback: Optional[Callable[[List[str], str], List[str]]] = None,
    ) -> Dict[str, Any]:
        """
        Merges multiple source managed virtual environments into a single target environment.
        Consolidates dependencies and reclaims disk space by repointing apps and pruning sources.
        """
        if not source_names:
            raise ValueError("At least one source mvenv must be specified for merging.")

        source_records: List[MvenvRecord] = []
        for s in source_names:
            rec = self.get_venv(s)
            if not rec:
                raise KeyError(f"Source mvenv '{s}' not found.")
            source_records.append(rec)

        # 1. Resolve or create target mvenv
        target_rec = self.get_venv(target_name)
        if not target_rec:
            # Create target using base interpreter of first source
            base_interp = source_records[0].base_interpreter or None
            req = MvenvCreateRequest(
                name=target_name,
                base_python=base_interp,
                sovereign=any(r.is_sovereign for r in source_records),
                force=False
            )
            target_rec = self.create_venv(req)

        # 2. Collect and install missing packages
        target_python = Path(target_rec.python_path)
        target_pip = Path(target_rec.pip_path) if target_rec.pip_path else None

        existing_pkgs = set(p.lower().split("==")[0].split(">=")[0].split("<=")[0] for p in target_rec.packages)
        all_source_pkgs: List[str] = []
        for r in source_records:
            for p in r.packages:
                if p not in all_source_pkgs:
                    all_source_pkgs.append(p)

        to_install: List[str] = []
        for pkg_spec in all_source_pkgs:
            base_name = pkg_spec.lower().split("==")[0].split(">=")[0].split("<=")[0]
            if base_name not in existing_pkgs:
                to_install.append(pkg_spec)

        if to_install:
            self._run_pip_install(target_python, target_pip, to_install)
            updated_pkgs = self._query_installed_packages(target_python)
            target_rec.packages = updated_pkgs
            target_rec.updated_at = datetime.now(timezone.utc).isoformat()
            target_rec.size_bytes = MvenvCatalog._calculate_dir_size(Path(target_rec.path))
            self.catalog.save_record(target_rec)

        # 3. Repoint installed applications via caller hook when supplied
        repointed_apps: List[str] = []
        if repoint_apps and repoint_callback is not None:
            repointed_apps = list(repoint_callback(list(source_names), target_name) or [])

        # 4. Calculate disk space to reclaim and prune sources
        reclaimed_bytes = 0
        deleted_sources: List[str] = []
        for r in source_records:
            if r.name != target_name:
                reclaimed_bytes += r.size_bytes
                if delete_sources:
                    self.delete_venv(r.name)
                    deleted_sources.append(r.name)

        return {
            "success": True,
            "target": target_rec.to_dict(),
            "merged_sources": [s for s in source_names if s != target_name],
            "deleted_sources": deleted_sources,
            "packages_installed": len(to_install),
            "repointed_apps": repointed_apps,
            "reclaimed_bytes": reclaimed_bytes if delete_sources else 0
        }

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

    @staticmethod
    def _validate_tar_members(members: List[tarfile.TarInfo], dest_root: Path) -> None:
        resolved_root = dest_root.resolve()
        for member in members:
            raw_name = (member.name or "").strip()
            if not raw_name or "\x00" in raw_name:
                raise ValueError(f"Invalid archive member name: {member.name!r}")
            posix_name = raw_name.replace("\\", "/")
            if posix_name.startswith("/") or (len(posix_name) >= 2 and posix_name[1] == ":"):
                raise ValueError(f"Absolute archive member path prohibited: {member.name!r}")
            parts = [part for part in posix_name.split("/") if part and part != "."]
            if ".." in parts:
                raise ValueError(f"Archive path traversal detected: {member.name!r}")
            if member.issym() or member.islnk() or member.isdev() or member.isfifo():
                raise ValueError(f"Unsafe special/link archive member prohibited: {member.name!r}")
            target_path = (resolved_root / posix_name).resolve()
            if os.path.commonpath([str(resolved_root), str(target_path)]) != str(resolved_root):
                raise ValueError(f"Archive member escapes target root: {member.name!r}")

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
                self._validate_tar_members(members, temp_extract)
                extracted_root_name = members[0].name.replace("\\", "/").split("/")[0]
                name = target_name or extracted_root_name
                if not name or ".." in Path(name).parts or "/" in name or "\\" in name:
                    raise ValueError(f"Invalid target mvenv name: {name!r}")
                dest_dir = (self.root_path / name).resolve()
                if os.path.commonpath([str(self.root_path.resolve()), str(dest_dir)]) != str(self.root_path.resolve()):
                    raise ValueError(f"Target destination escapes mvenv root: {dest_dir}")

                if dest_dir.exists():
                    if not force:
                        raise FileExistsError(f"Target mvenv directory already exists: {dest_dir}")
                    shutil.rmtree(dest_dir, ignore_errors=True)

                tar.extractall(path=temp_extract, filter="data")

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
        try:
            rec = self._resolve_mvenv(name)
        except KeyError:
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
