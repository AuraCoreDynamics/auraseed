import sys
import json
import argparse
import platform
import subprocess
from pathlib import Path
from typing import List, Optional

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

from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest
from auraseed.api.server import run_api_server
from auraseed.grid.mas_runner import run_as_mas
from auraseed.grid.peer_transfer import P2PVenvClient



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


def handle_mvenv_cli(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="auraseed mvenv", description="Manage and catalog sovereign virtual environments.")
    subparsers = parser.add_subparsers(dest="mvenv_cmd", help="Subcommand to execute")

    # list
    p_list = subparsers.add_parser("list", help="List all managed virtual environments")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")
    p_list.add_argument("--root", type=str, help="Custom mvenv root directory")

    # create
    p_create = subparsers.add_parser("create", help="Create a new managed virtual environment")
    p_create.add_argument("name", help="Name of the mvenv")
    p_create.add_argument("--packages", nargs="+", help="Pip packages to install")
    p_create.add_argument("-r", "--requirements", help="Path to requirements.txt")
    p_create.add_argument("--base", help="Path to base Python executable")
    p_create.add_argument("--no-sovereign", action="store_true", help="Disable host isolation")
    p_create.add_argument("--force", action="store_true", help="Overwrite if directory exists")
    p_create.add_argument("--dest", help="Explicit target directory")
    p_create.add_argument("--root", type=str, help="Custom mvenv root directory")
    p_create.add_argument("--json", action="store_true", help="Output as JSON")

    # info
    p_info = subparsers.add_parser("info", help="Get details of a managed virtual environment")
    p_info.add_argument("name", help="Name of the mvenv")
    p_info.add_argument("--root", type=str, help="Custom mvenv root directory")
    p_info.add_argument("--json", action="store_true", help="Output as JSON")

    # install
    p_install = subparsers.add_parser("install", help="Install packages into an mvenv")
    p_install.add_argument("name", help="Name of the mvenv")
    p_install.add_argument("packages", nargs="*", help="Packages to install")
    p_install.add_argument("-r", "--requirements", help="Path to requirements.txt")
    p_install.add_argument("--upgrade", action="store_true", help="Upgrade packages")
    p_install.add_argument("--root", type=str, help="Custom mvenv root directory")
    p_install.add_argument("--json", action="store_true", help="Output as JSON")

    # delete
    p_delete = subparsers.add_parser("delete", help="Delete a managed virtual environment")
    p_delete.add_argument("name", help="Name of the mvenv")
    p_delete.add_argument("--root", type=str, help="Custom mvenv root directory")

    # verify
    p_verify = subparsers.add_parser("verify", help="Verify executable and health of an mvenv")
    p_verify.add_argument("name", help="Name of the mvenv")
    p_verify.add_argument("--root", type=str, help="Custom mvenv root directory")
    p_verify.add_argument("--json", action="store_true", help="Output as JSON")

    # export
    p_export = subparsers.add_parser("export", help="Export an mvenv as a portable tar.gz bundle")
    p_export.add_argument("name", help="Name of the mvenv")
    p_export.add_argument("--out", help="Output bundle path")
    p_export.add_argument("--root", type=str, help="Custom mvenv root directory")

    # import
    p_import = subparsers.add_parser("import", help="Import an mvenv bundle into the catalog")
    p_import.add_argument("bundle", help="Path to tar.gz bundle")
    p_import.add_argument("--name", help="Target name for the imported mvenv")
    p_import.add_argument("--force", action="store_true", help="Overwrite if target exists")
    p_import.add_argument("--root", type=str, help="Custom mvenv root directory")
    p_import.add_argument("--json", action="store_true", help="Output as JSON")

    parsed = parser.parse_args(args)
    if not parsed.mvenv_cmd:
        parser.print_help()
        return 1

    root_path = Path(parsed.root) if getattr(parsed, "root", None) else None
    mgr = MvenvManager(root_path)

    if parsed.mvenv_cmd == "list":
        records = mgr.list_venvs()
        if getattr(parsed, "json", False):
            print(json.dumps([r.to_dict() for r in records], indent=2))
        else:
            print(f"Cataloged Managed Virtual Environments ({len(records)} in {mgr.root_path}):")
            for r in records:
                sov = " [sovereign]" if r.is_sovereign else ""
                print(f"  - {r.name:<20} Python {r.python_version:<8} ({len(r.packages)} pkgs){sov}")
                print(f"    Path: {r.python_path}")
        return 0

    if parsed.mvenv_cmd == "create":
        req = MvenvCreateRequest(
            name=parsed.name,
            base_python=parsed.base,
            packages=parsed.packages,
            requirements_file=parsed.requirements,
            sovereign=not parsed.no_sovereign,
            force=parsed.force,
            target_dir=parsed.dest
        )
        try:
            rec = mgr.create_venv(req)
            if getattr(parsed, "json", False):
                print(json.dumps(rec.to_dict(), indent=2))
            else:
                print(f"Created mvenv '{rec.name}' at: {rec.path}")
                print(f"Python: {rec.python_path} ({rec.python_version})")
                if rec.packages:
                    print(f"Packages: {', '.join(rec.packages)}")
            return 0
        except Exception as e:
            print(f"Error creating mvenv: {e}", file=sys.stderr)
            return 1

    if parsed.mvenv_cmd == "info":
        rec = mgr.get_venv(parsed.name)
        if not rec:
            print(f"Mvenv '{parsed.name}' not found.", file=sys.stderr)
            return 1
        if getattr(parsed, "json", False):
            print(json.dumps(rec.to_dict(), indent=2))
        else:
            print(f"Managed Venv: {rec.name}")
            print(f"  Path:             {rec.path}")
            print(f"  Python Path:      {rec.python_path}")
            print(f"  Python Version:   {rec.python_version}")
            print(f"  Sovereign:        {rec.is_sovereign}")
            print(f"  Disk Size:        {rec.size_bytes / (1024*1024):.1f} MB")
            print(f"  Packages ({len(rec.packages)}):")
            for pkg in rec.packages:
                print(f"    - {pkg}")
        return 0

    if parsed.mvenv_cmd == "install":
        try:
            if parsed.requirements:
                rec = mgr.install_requirements(parsed.name, parsed.requirements)
            else:
                rec = mgr.install_packages(parsed.name, parsed.packages or [], upgrade=parsed.upgrade)
            if getattr(parsed, "json", False):
                print(json.dumps(rec.to_dict(), indent=2))
            else:
                print(f"Updated packages for '{parsed.name}': {len(rec.packages)} installed.")
            return 0
        except Exception as e:
            print(f"Error installing packages: {e}", file=sys.stderr)
            return 1

    if parsed.mvenv_cmd == "delete":
        deleted = mgr.delete_venv(parsed.name)
        if deleted:
            print(f"Deleted mvenv '{parsed.name}'.")
            return 0
        else:
            print(f"Mvenv '{parsed.name}' not found.", file=sys.stderr)
            return 1

    if parsed.mvenv_cmd == "verify":
        res = mgr.verify_venv(parsed.name)
        if getattr(parsed, "json", False):
            print(json.dumps(res, indent=2))
        else:
            if res.get("valid"):
                print(f"[OK] Mvenv '{parsed.name}' is valid.")
                print(f"  Executable: {res.get('python_path')}")
                print(f"  Version:    {res.get('python_version')}")
            else:
                print(f"[FAIL] Mvenv '{parsed.name}' failed verification: {res.get('error')}", file=sys.stderr)
        return 0 if res.get("valid") else 1

    if parsed.mvenv_cmd == "export":
        try:
            out_path = Path(parsed.out) if parsed.out else None
            bundle = mgr.export_bundle(parsed.name, out_path)
            print(f"Exported bundle: {bundle}")
            return 0
        except Exception as e:
            print(f"Error exporting bundle: {e}", file=sys.stderr)
            return 1

    if parsed.mvenv_cmd == "import":
        try:
            bundle_file = Path(parsed.bundle)
            rec = mgr.import_bundle(bundle_file, target_name=parsed.name, force=parsed.force)
            if getattr(parsed, "json", False):
                print(json.dumps(rec.to_dict(), indent=2))
            else:
                print(f"Successfully imported mvenv '{rec.name}' from bundle.")
                print(f"  Location: {rec.path}")
                print(f"  Python:   {rec.python_path} ({rec.python_version})")
            return 0
        except Exception as e:
            print(f"Error importing bundle: {e}", file=sys.stderr)
            return 1

    return 0


def handle_serve_cli(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="auraseed serve", description="Run the AuraSeed API and MCP server.")
    parser.add_argument("--host", default="127.0.0.1", help="Host interface to bind")
    parser.add_argument("--port", type=int, default=7099, help="HTTP port to listen on")
    parser.add_argument("--root", help="Custom mvenv root directory")
    parser.add_argument("--mcp", action="store_true", help="Run MCP stdio server instead of HTTP")
    parser.add_argument("--mas", action="store_true", help="Run as an AuraGrid Managed Application Service")

    parsed = parser.parse_args(args)
    root_path = Path(parsed.root) if parsed.root else None
    mgr = MvenvManager(root_path)

    if parsed.mcp:
        server = AuraSeedMcpServer(mgr)
        server.run_stdio()
        return 0

    if parsed.mas:
        run_as_mas(host=parsed.host, port=parsed.port, mvenv_root=parsed.root)
        return 0

    run_api_server(host=parsed.host, port=parsed.port, manager=mgr)
    return 0


def handle_p2p_cli(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="auraseed p2p", description="P2P venv transfer between nodes.")
    parser.add_argument("action", choices=["pull", "push"], help="Pull or push bundle")
    parser.add_argument("peer_url", help="Peer node URL (e.g. http://10.0.0.5:7099)")
    parser.add_argument("name", help="Mvenv name")
    parser.add_argument("--root", help="Custom mvenv root directory")

    parsed = parser.parse_args(args)
    root_path = Path(parsed.root) if parsed.root else None
    mgr = MvenvManager(root_path)
    client = P2PVenvClient(mgr)

    if parsed.action == "pull":
        print(f"[AuraSeed P2P] Pulling '{parsed.name}' from {parsed.peer_url}...")
        rec = client.fetch_bundle_from_peer(parsed.peer_url, parsed.name, force=True)
        print(f"[AuraSeed P2P] Successfully imported '{rec.name}' ({rec.python_version}).")
        return 0
    elif parsed.action == "push":
        print(f"[AuraSeed P2P] Pushing '{parsed.name}' to {parsed.peer_url}...")
        resp = client.push_bundle_to_peer(parsed.peer_url, parsed.name)
        print(f"[AuraSeed P2P] Peer response: {json.dumps(resp, indent=2)}")
        return 0

    return 1


def main() -> int:
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "mvenv":
            return handle_mvenv_cli(sys.argv[2:])
        if cmd == "serve":
            return handle_serve_cli(sys.argv[2:])
        if cmd == "p2p":
            return handle_p2p_cli(sys.argv[2:])

    # Legacy Discovery / Seeding flow
    parser = argparse.ArgumentParser(description="AuraSeed: Zero-privilege Python runtime discovery and environment seeding engine.")
    parser.add_argument("--strategy", choices=["interactive", "latest", "spec"], default="interactive", help="Selection strategy for discovery.")
    parser.add_argument("--spec", type=str, help="Version specifier (e.g. >=3.10) if strategy is 'spec'.")
    parser.add_argument("--dest", type=str, help="Destination folder for the sovereign venv. Defaults to ~/.auraseed/venvs/<env_name>")
    parser.add_argument("--adapter", type=str, default="all", help="Which discovery adapter to prioritize.")
    parser.add_argument("--relaunch", type=str, help="Optional path to a Python script to relaunch in the new environment.")
    
    parser.add_argument("--force", action="store_true", help="Force re-seeding if destination folder already exists.")
    parser.add_argument("--no-register", action="store_true", help="Skip registering the environment in the OS registry.")
    
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
    safe_name = "".join([c if c.isalnum() else "_" for c in selected_env.name]).lower().strip("_")
    dest_path = Path(args.dest) if args.dest else Path.home() / ".auraseed" / "venvs" / safe_name
    
    if dest_path.exists() and not args.force:
        print(f"[AuraSeed] Destination {dest_path} already exists. Assuming environment is seeded.")
    else:
        if dest_path.exists() and args.force:
            import shutil
            shutil.rmtree(dest_path)

        print(f"[AuraSeed] Seeding sovereign environment at {dest_path}...")
        sovereign = SovereignVenvEngine()
        sovereign.create_venv(selected_env, dest_path)
        
        print("[AuraSeed] Executing Host Isolation...")
        isolation = HostIsolationEngine()
        isolation.isolate(selected_env, dest_path)
        
        from datetime import datetime, timezone
        from auraseed.models import SelectedInterpreterContext, IsolationStatus
        now_str = datetime.now(timezone.utc).isoformat()
        manifest = SeedManifest(
            seed_version="1.0.0",
            created_at=now_str,
            selected_interpreter=SelectedInterpreterContext(
                executable=str(selected_env.executable),
                version=selected_env.version,
                adapter=selected_env.source_type,
                selection_rule=args.strategy
            ),
            isolation_status=IsolationStatus(
                frozen=True,
                system_site_packages_severed=True
            ),
            is_default_selection=True,
            target_env_id=selected_env.id,
            version=selected_env.version,
            source_type=selected_env.source_type,
            is_default=True
        )
        write_seed_manifest(dest_path, manifest)
        generate_launchers(dest_path)

    # 4. OS Registry
    if not args.no_register:
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
    else:
        print("[AuraSeed] Skipping environment registration (--no-register active).")
        
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
