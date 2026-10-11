import sys
import argparse
import platform
import subprocess
from pathlib import Path

from auraseed.discovery.manager import DiscoveryManager
from auraseed.discovery.os.windows import WindowsDiscoverer
from auraseed.discovery.os.linux import LinuxDiscoverer
from auraseed.discovery.os.macos import MacOSDiscoverer
from auraseed.discovery.adapters.arcpro import ArcProDiscoverer
from auraseed.discovery.adapters.qgis import QgisDiscoverer

from auraseed.governance.rules import LatestVersionStrategy, VersionSpecStrategy, InteractiveSelectionStrategy
from auraseed.seed.sovereign import SovereignVenvEngine
from auraseed.seed.isolation import HostIsolationEngine
from auraseed.seed.artifacts import write_seed_manifest, generate_launchers
from auraseed.models import SeedManifest

def register_platform_strategies(manager: DiscoveryManager, adapter: str):
    sys_plat = platform.system().lower()
    if sys_plat == "windows" and adapter in ("all", "windows_registry"):
        manager.register_strategy(WindowsDiscoverer())
    elif sys_plat == "linux" and adapter in ("all", "linux_system"):
        manager.register_strategy(LinuxDiscoverer())
    elif sys_plat == "darwin" and adapter in ("all", "macos_system"):
        manager.register_strategy(MacOSDiscoverer())
        
    if adapter in ("all", "arcpro") and sys_plat == "windows":
        manager.register_strategy(ArcProDiscoverer())
    if adapter in ("all", "qgis"):
        manager.register_strategy(QgisDiscoverer())

def main() -> int:
    parser = argparse.ArgumentParser(description="AuraSeed: Zero-privilege Python runtime discovery and environment seeding engine.")
    parser.add_argument("--strategy", choices=["interactive", "latest", "spec"], default="interactive", help="Selection strategy for discovery.")
    parser.add_argument("--spec", type=str, help="Version specifier (e.g. >=3.10) if strategy is 'spec'.")
    parser.add_argument("--dest", type=str, help="Destination folder for the sovereign venv. Defaults to ~/.auraseed/venvs/<env_name>")
    parser.add_argument("--adapter", type=str, default="all", help="Which discovery adapter to prioritize.")
    parser.add_argument("--relaunch", type=str, help="Optional path to a Python script to relaunch in the new environment.")
    
    args = parser.parse_args()

    # 1. Discovery
    manager = DiscoveryManager()
    register_platform_strategies(manager, args.adapter)
    
    print("[AuraSeed] Discovering Python environments...")
    results = manager.run_discovery()
    env_list = list(results.values())
    
    if not env_list:
        print("[AuraSeed] Error: No Python environments found.")
        return 1

    # 2. Selection
    if args.strategy == "interactive":
        strategy = InteractiveSelectionStrategy()
    elif args.strategy == "latest":
        strategy = LatestVersionStrategy()
    elif args.strategy == "spec":
        if not args.spec:
            print("[AuraSeed] Error: --spec is required when using the 'spec' strategy.")
            return 1
        strategy = VersionSpecStrategy(args.spec)
    else:
        strategy = InteractiveSelectionStrategy()
        
    selected_env = strategy.select(env_list)
    if not selected_env:
        print("[AuraSeed] No environment selected. Exiting.")
        return 1
        
    print(f"[AuraSeed] Selected: {selected_env.name} ({selected_env.executable})")

    # 3. Seeding
    # Fallback default destination in ~/.auraseed/venvs/<normalized_name>
    safe_name = "".join([c if c.isalnum() else "_" for c in selected_env.name]).lower().strip("_")
    dest_path = Path(args.dest) if args.dest else Path.home() / ".auraseed" / "venvs" / safe_name
    
    if dest_path.exists():
        print(f"[AuraSeed] Destination {dest_path} already exists. Assuming environment is seeded.")
    else:
        print(f"[AuraSeed] Seeding sovereign environment at {dest_path}...")
        sovereign = SovereignVenvEngine()
        sovereign.create_venv(selected_env, dest_path)
        
        print("[AuraSeed] Executing Host Isolation...")
        isolation = HostIsolationEngine()
        isolation.isolate(selected_env, dest_path)
        
        manifest = SeedManifest(
            target_env_id=selected_env.id,
            version=selected_env.version,
            source_type=selected_env.source_type,
            is_default=True
        )
        write_seed_manifest(dest_path, manifest)
        generate_launchers(dest_path)

    # 4. OS Registry
    print("[AuraSeed] Registering environment...")
    env_name = dest_path.name
    sys_plat = platform.system().lower()
    try:
        if sys_plat == "windows":
            from auraseed.registry.win import WindowsRegistryAdapter
            reg = WindowsRegistryAdapter()
            reg.register_environment(env_name, str(dest_path))
        elif sys_plat == "linux":
            from auraseed.registry.linux import LinuxRegistryAdapter
            reg = LinuxRegistryAdapter()
            reg.register_environment(env_name, str(dest_path))
        elif sys_plat == "darwin":
            from auraseed.registry.mac import MacRegistryAdapter
            reg = MacRegistryAdapter()
            reg.register_environment(env_name, str(dest_path))
    except Exception as e:
        print(f"[AuraSeed] Warning: Failed to register environment with OS ({e})")
        
    print(f"\n[AuraSeed] Complete! Venv located at: {dest_path}")

    # 5. Relaunch
    if args.relaunch:
        relaunch_script = Path(args.relaunch)
        if not relaunch_script.exists():
            print(f"[AuraSeed] Error: Relaunch script not found at {relaunch_script}")
            return 1
            
        print(f"[AuraSeed] Relaunching plugin script: {relaunch_script}")
        is_win = platform.system().lower() == "windows"
        venv_python = dest_path / "Scripts" / "python.exe" if is_win else dest_path / "bin" / "python"
        
        cmd = [str(venv_python), str(relaunch_script)]
        try:
            subprocess.run(cmd, check=True)
        except subprocess.CalledProcessError as e:
            print(f"[AuraSeed] Plugin script failed with exit code {e.returncode}")
            return e.returncode

    return 0

if __name__ == "__main__":
    sys.exit(main())
