import argparse
import json
import os
import platform
import subprocess
import sys
from pathlib import Path
from typing import List, Optional

from auraseed.api.mcp import AuraSeedMcpServer
from auraseed.api.server import run_api_server
from auraseed.discovery.adapters.arcpro import ArcProDiscoverer
from auraseed.discovery.adapters.embedded import EmbeddedAppDiscoverer
from auraseed.discovery.adapters.qgis import QgisDiscoverer
from auraseed.discovery.adapters.toolchains import ToolchainDiscoverer
from auraseed.discovery.manager import DiscoveryManager
from auraseed.discovery.os.linux import LinuxDiscoverer
from auraseed.discovery.os.macos import MacOSDiscoverer
from auraseed.discovery.os.windows import WindowsDiscoverer
from auraseed.governance.rules import (
    InteractiveSelectionStrategy,
    LatestVersionStrategy,
    VersionSpecStrategy,
    parse_semver,
)
from auraseed.grid.mas_runner import run_as_mas
from auraseed.models import DiscoveredEnvironment, SeedManifest
from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest
from auraseed.seed.artifacts import generate_launchers, write_seed_manifest
from auraseed.seed.isolation import HostIsolationEngine
from auraseed.seed.sovereign import SovereignVenvEngine


def _split_exec_args(raw_args: List[str]):
    """
    Splits `mvenv run` / `mvenv python` CLI arguments into AuraSeed option tokens
    and downstream child command arguments, supporting both `--` delimiter and
    natural flag placement around the mvenv name.
    """
    if "--" in raw_args:
        idx = raw_args.index("--")
        return raw_args[:idx], raw_args[idx + 1:]

    pre: List[str] = []
    value_flags = {"--cwd", "--timeout", "--root"}
    bool_flags = {"--json", "-h", "--help"}
    saw_name = False
    i = 0
    while i < len(raw_args):
        tok = raw_args[i]
        if tok in value_flags:
            pre.append(tok)
            if i + 1 < len(raw_args):
                pre.append(raw_args[i + 1])
                i += 2
            else:
                i += 1
            continue
        if any(tok.startswith(f + "=") for f in value_flags) or tok in bool_flags:
            pre.append(tok)
            i += 1
            continue
        if not tok.startswith("-") and not saw_name:
            pre.append(tok)
            saw_name = True
            i += 1
            continue
        if not saw_name and tok.startswith("-"):
            pre.append(tok)
            i += 1
            continue
        return pre, raw_args[i:]
    return pre, []


def _parse_csv_flags(raw_values: Optional[List[str]]) -> Optional[List[str]]:
    if not raw_values:
        return None
    items: List[str] = []
    for raw in raw_values:
        for part in raw.split(","):
            cleaned = part.strip()
            if cleaned and cleaned not in items:
                items.append(cleaned)
    return items or None


def _discovered_env_to_dict(env: DiscoveredEnvironment) -> dict:
    payload = {
        "id": env.id,
        "name": env.name,
        "executable": str(env.executable),
        "version": env.version,
        "source_type": env.source_type,
        "site_packages": [str(p) for p in (env.site_packages or [])],
        "metadata": env.metadata or {},
    }
    if env.capabilities is not None:
        payload["capabilities"] = env.capabilities.to_dict()
    return payload


def _print_discovery_payload(
    mgr: MvenvManager,
    adapter: str = "all",
    interpreters_only: bool = False,
    mvenvs_only: bool = False,
    include_registry: bool = True,
    as_json: bool = False,
    interpreters_focus: bool = False,
    probe: bool = False,
    use_cache: bool = True,
    required_modules: Optional[List[str]] = None,
    required_packages: Optional[List[str]] = None,
) -> int:
    interpreters = []
    mvenvs = []

    if not mvenvs_only:
        envs = mgr.discover_interpreters(
            adapter=adapter,
            probe_capabilities=probe,
            use_cache=use_cache,
            required_modules=required_modules,
            required_packages=required_packages,
        )
        if probe:
            envs.sort(
                key=lambda e: (
                    float(e.capabilities.composite_score) if e.capabilities else 0.0,
                    parse_semver(e.version),
                ),
                reverse=True,
            )
        interpreters = [_discovered_env_to_dict(e) for e in envs]

    if not interpreters_only:
        venvs = mgr.discover_venvs(include_registry=include_registry)
        mvenvs = [v.to_dict() for v in venvs]

    if as_json:
        payload = {
            "root_path": str(mgr.root_path),
            "adapter": adapter,
            "interpreters": interpreters,
            "mvenvs": mvenvs,
        }
        print(json.dumps(payload, indent=2))
        return 0

    if not interpreters_only and not (interpreters_focus and not mvenvs):
        print(f"Discovered Managed Virtual Environments ({len(mvenvs)}):")
        for r in mvenvs:
            sov = " [sovereign]" if r.get("is_sovereign") else ""
            print(f"  - {r['name']:<20} Python {r.get('python_version', 'unknown'):<8} ({len(r.get('packages', []))} pkgs){sov}")
            print(f"    Root:   {r.get('path')}")
            print(f"    Python: {r.get('python_path')}")

    if not mvenvs_only:
        if not interpreters_only:
            print()
        print(f"Discovered Base Python Interpreters ({len(interpreters)}, adapter={adapter}):")
        for e in interpreters:
            caps = e.get("capabilities")
            score_suffix = f", score={caps['composite_score']:.4f}" if caps else ""
            print(f"  - {e['name']} (Python {e['version']}, source={e['source_type']}{score_suffix})")
            print(f"    Executable: {e['executable']}")

    return 0


def handle_discover_cli(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="auraseed discover",
        description="Discover host Python interpreters and existing AuraSeed managed virtual environments."
    )
    parser.add_argument(
        "--adapter",
        default="all",
        help="Interpreter discovery adapter filter (all, windows_registry, linux_system, macos_system, toolchains, embedded_apps, arcpro, qgis)",
    )
    parser.add_argument("--interpreters-only", action="store_true", help="Only scan host base interpreters")
    parser.add_argument("--mvenvs-only", action="store_true", help="Only scan managed virtual environments")
    parser.add_argument("--no-registry", action="store_true", help="Skip global OS registry manifests and default ~/.auraseed directories")
    parser.add_argument("--probe", action="store_true", help="Probe runtime capabilities, ABI tags, and composite scores")
    parser.add_argument("--no-cache", action="store_true", help="Bypass persistent ~/.auraseed/discovery_cache.json when probing")
    parser.add_argument(
        "--require-module",
        action="append",
        help="Required importable stdlib/site module(s), comma-separated (e.g. ssl,sqlite3)",
    )
    parser.add_argument(
        "--require-package",
        action="append",
        help="Preferred preinstalled package(s), comma-separated (e.g. numpy,osgeo)",
    )
    parser.add_argument("--root", type=str, help="Custom mvenv root directory")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    parsed = parser.parse_args(args)
    root_path = Path(parsed.root) if parsed.root else None
    mgr = MvenvManager(root_path)
    return _print_discovery_payload(
        mgr=mgr,
        adapter=parsed.adapter,
        interpreters_only=parsed.interpreters_only,
        mvenvs_only=parsed.mvenvs_only,
        include_registry=not parsed.no_registry,
        as_json=parsed.json,
        probe=bool(parsed.probe),
        use_cache=not parsed.no_cache,
        required_modules=_parse_csv_flags(parsed.require_module),
        required_packages=_parse_csv_flags(parsed.require_package),
    )


def register_platform_strategies(manager: DiscoveryManager, adapter: str) -> None:
    sys_plat = platform.system().lower()
    norm_adapter = (adapter or "all").strip().lower()
    if sys_plat == "windows" and norm_adapter in ("all", "windows_registry"):
        manager.register_strategy(WindowsDiscoverer())
    elif sys_plat == "linux" and norm_adapter in ("all", "linux_system"):
        manager.register_strategy(LinuxDiscoverer())
    elif sys_plat == "darwin" and norm_adapter in ("all", "macos_system"):
        manager.register_strategy(MacOSDiscoverer())

    if norm_adapter in ("all", "toolchains", "toolchain_adapter"):
        manager.register_strategy(ToolchainDiscoverer())
    if norm_adapter in ("all", "embedded_apps", "embedded"):
        manager.register_strategy(EmbeddedAppDiscoverer())

    if norm_adapter in ("all", "arcpro") and sys_plat == "windows":
        manager.register_strategy(ArcProDiscoverer())
    if norm_adapter in ("all", "qgis"):
        manager.register_strategy(QgisDiscoverer())


def handle_mvenv_cli(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="auraseed mvenv", description="Manage and catalog sovereign virtual environments.")
    subparsers = parser.add_subparsers(dest="mvenv_cmd", help="Subcommand to execute")

    # list
    p_list = subparsers.add_parser("list", help="List all managed virtual environments")
    p_list.add_argument("--json", action="store_true", help="Output as JSON")
    p_list.add_argument("--root", type=str, help="Custom mvenv root directory")

    # discover
    p_discover = subparsers.add_parser("discover", help="Discover host Python interpreters and managed virtual environments")
    p_discover.add_argument(
        "--adapter",
        default="all",
        help="Interpreter discovery adapter filter (all, windows_registry, linux_system, macos_system, toolchains, embedded_apps, arcpro, qgis)",
    )
    p_discover.add_argument("--interpreters", action="store_true", help="Include base host interpreters (text output focuses on interpreters when set alone)")
    p_discover.add_argument("--interpreters-only", action="store_true", help="Only scan base host Python interpreters")
    p_discover.add_argument("--mvenvs-only", action="store_true", help="Only scan managed virtual environments")
    p_discover.add_argument("--no-registry", action="store_true", help="Skip global OS registry manifests and default ~/.auraseed directories")
    p_discover.add_argument("--probe", action="store_true", help="Probe runtime capabilities, ABI tags, and composite scores")
    p_discover.add_argument("--no-cache", action="store_true", help="Bypass persistent ~/.auraseed/discovery_cache.json when probing")
    p_discover.add_argument("--require-module", action="append", help="Required importable module(s), comma-separated")
    p_discover.add_argument("--require-package", action="append", help="Preferred preinstalled package(s), comma-separated")
    p_discover.add_argument("--root", type=str, help="Custom mvenv root directory")
    p_discover.add_argument("--json", action="store_true", help="Output as JSON")

    # create
    p_create = subparsers.add_parser("create", help="Create a new managed virtual environment")
    p_create.add_argument("name", help="Name of the mvenv")
    p_create.add_argument("--packages", nargs="+", help="Pip packages to install")
    p_create.add_argument("-r", "--requirements", help="Path to requirements.txt")
    p_create.add_argument("--base", help="Path to base Python executable")
    p_create.add_argument("--spec", help="Version specifier constraint for discovered interpreter (e.g. '>=3.11', '==3.12.*')")
    p_create.add_argument("--adapter", default="all", help="Interpreter discovery adapter")
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

    # activate
    p_activate = subparsers.add_parser("activate", help="Print activation scripts, python path, and shell commands for an mvenv")
    p_activate.add_argument("name", help="Name or path of the mvenv")
    p_activate.add_argument("--shell", choices=["powershell", "cmd", "bash", "all"], default="all", help="Target shell format")
    p_activate.add_argument("--root", type=str, help="Custom mvenv root directory")
    p_activate.add_argument("--json", action="store_true", help="Output as JSON")

    # run
    p_run = subparsers.add_parser("run", help="Run an arbitrary command inside an mvenv with isolated VIRTUAL_ENV and PATH")
    p_run.add_argument("name", help="Name or path of the mvenv")
    p_run.add_argument("--cwd", type=str, help="Working directory for the command")
    p_run.add_argument("--timeout", type=int, default=300, help="Execution timeout in seconds")
    p_run.add_argument("--root", type=str, help="Custom mvenv root directory")
    p_run.add_argument("--json", action="store_true", help="Output structured JSON result")

    # python
    p_python = subparsers.add_parser("python", help="Run Python inside an mvenv (e.g. `-c ...`, `-m ...`, script.py)")
    p_python.add_argument("name", help="Name or path of the mvenv")
    p_python.add_argument("--cwd", type=str, help="Working directory for execution")
    p_python.add_argument("--timeout", type=int, default=300, help="Execution timeout in seconds")
    p_python.add_argument("--root", type=str, help="Custom mvenv root directory")
    p_python.add_argument("--json", action="store_true", help="Output structured JSON result")

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
    p_delete.add_argument("--json", action="store_true", help="Output as JSON")

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
    p_export.add_argument("--json", action="store_true", help="Output as JSON")

    # import
    p_import = subparsers.add_parser("import", help="Import an mvenv bundle into the catalog")
    p_import.add_argument("bundle", help="Path to tar.gz bundle")
    p_import.add_argument("--name", help="Target name for the imported mvenv")
    p_import.add_argument("--force", action="store_true", help="Overwrite if target exists")
    p_import.add_argument("--root", type=str, help="Custom mvenv root directory")
    p_import.add_argument("--json", action="store_true", help="Output as JSON")

    # merge
    p_merge = subparsers.add_parser("merge", help="Merge multiple mvenvs to consolidate packages and save disk space")
    p_merge.add_argument("sources", nargs="+", help="Source mvenv names to merge")
    p_merge.add_argument("--target", required=True, help="Target merged mvenv name")
    p_merge.add_argument("--delete-sources", action="store_true", help="Delete source mvenvs to reclaim disk space")
    p_merge.add_argument("--no-repoint", action="store_true", help="Do not run host app repoint hook")
    p_merge.add_argument("--root", type=str, help="Custom mvenv root directory")
    p_merge.add_argument("--json", action="store_true", help="Output as JSON")

    exec_tail: List[str] = []
    parse_target = args
    if args and args[0] in ("run", "python"):
        pre, exec_tail = _split_exec_args(args[1:])
        parse_target = [args[0]] + pre

    parsed = parser.parse_args(parse_target)
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

    if parsed.mvenv_cmd == "discover":
        interpreters_only = bool(parsed.interpreters_only or (parsed.interpreters and not parsed.mvenvs_only))
        return _print_discovery_payload(
            mgr=mgr,
            adapter=parsed.adapter,
            interpreters_only=interpreters_only if not parsed.json else bool(parsed.interpreters_only),
            mvenvs_only=bool(parsed.mvenvs_only),
            include_registry=not parsed.no_registry,
            as_json=bool(parsed.json),
            interpreters_focus=bool(parsed.interpreters),
            probe=bool(parsed.probe),
            use_cache=not parsed.no_cache,
            required_modules=_parse_csv_flags(parsed.require_module),
            required_packages=_parse_csv_flags(parsed.require_package),
        )

    if parsed.mvenv_cmd == "create":
        req = MvenvCreateRequest(
            name=parsed.name,
            base_python=parsed.base,
            packages=parsed.packages,
            requirements_file=parsed.requirements,
            sovereign=not parsed.no_sovereign,
            force=parsed.force,
            target_dir=parsed.dest,
            python_spec=parsed.spec,
            adapter=parsed.adapter
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
        try:
            rec = mgr._resolve_mvenv(parsed.name)
        except KeyError:
            rec = None
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
            print(f"  Disk Size:        {rec.size_bytes / (1024 * 1024):.1f} MB")
            print(f"  Packages ({len(rec.packages)}):")
            for pkg in rec.packages:
                print(f"    - {pkg}")
        return 0

    if parsed.mvenv_cmd == "activate":
        try:
            info = mgr.get_activation_info(parsed.name)
        except Exception as e:
            print(f"Error resolving mvenv activation: {e}", file=sys.stderr)
            return 1
        if getattr(parsed, "json", False):
            print(json.dumps(info, indent=2))
        else:
            print(f"Activation Details for '{info['name']}' ({info['venv_path']}):")
            print(f"  Python:   {info['python_path']}")
            if info.get("launcher"):
                print(f"  Launcher: {info['launcher']}")
            cmds = info.get("commands", {})
            if parsed.shell == "all":
                for sh_name, cmd_str in cmds.items():
                    print(f"  {sh_name:<14} {cmd_str}")
            else:
                print(f"  {parsed.shell}: {cmds.get(parsed.shell, '')}")
        return 0

    if parsed.mvenv_cmd in ("run", "python"):
        if not exec_tail:
            print(f"Error: no {'python arguments' if parsed.mvenv_cmd == 'python' else 'command'} provided.", file=sys.stderr)
            return 1
        try:
            if parsed.mvenv_cmd == "python":
                res = mgr.run_in_venv(
                    parsed.name,
                    python_args=exec_tail,
                    cwd=parsed.cwd,
                    timeout=parsed.timeout,
                )
            else:
                res = mgr.run_in_venv(
                    parsed.name,
                    command=exec_tail,
                    cwd=parsed.cwd,
                    timeout=parsed.timeout,
                )
            if getattr(parsed, "json", False):
                print(json.dumps(res, indent=2))
            else:
                if res.get("stdout"):
                    sys.stdout.write(res["stdout"])
                if res.get("stderr"):
                    sys.stderr.write(res["stderr"])
            return int(res.get("returncode", 0))
        except Exception as e:
            print(f"Error executing in mvenv '{parsed.name}': {e}", file=sys.stderr)
            return 1

    if parsed.mvenv_cmd == "install":
        if not parsed.requirements and not parsed.packages:
            print("Error specifying packages: provide package names or -r/--requirements.", file=sys.stderr)
            return 1
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
            if getattr(parsed, "json", False):
                print(json.dumps({"success": True, "name": parsed.name}, indent=2))
            else:
                print(f"Deleted mvenv '{parsed.name}'.")
            return 0
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
            if getattr(parsed, "json", False):
                print(json.dumps({"name": parsed.name, "bundle_path": str(bundle)}, indent=2))
            else:
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

    if parsed.mvenv_cmd == "merge":
        try:
            res = mgr.merge_venvs(
                source_names=parsed.sources,
                target_name=parsed.target,
                delete_sources=parsed.delete_sources,
                repoint_apps=not parsed.no_repoint,
            )
            if getattr(parsed, "json", False):
                print(json.dumps(res, indent=2))
            else:
                saved_mb = f"{res.get('reclaimed_bytes', 0) / (1024 * 1024):.1f} MB"
                print(f"Successfully merged {len(res.get('merged_sources', []))} mvenvs into '{parsed.target}'.")
                print(f"  Packages installed: {res.get('packages_installed', 0)}")
                if res.get("deleted_sources"):
                    print(f"  Pruned sources: {', '.join(res.get('deleted_sources'))} (reclaimed {saved_mb})")
                if res.get("repointed_apps"):
                    print(f"  Repointed apps: {', '.join(res.get('repointed_apps'))}")
            return 0
        except Exception as e:
            print(f"Error merging mvenvs: {e}", file=sys.stderr)
            return 1

    return 0


def handle_serve_cli(args: List[str]) -> int:
    parser = argparse.ArgumentParser(prog="auraseed serve", description="Run the AuraSeed API and MCP server.")
    parser.add_argument("--host", default=None, help="Host interface to bind (default: AURASEED_BIND_HOST or 127.0.0.1)")
    parser.add_argument("--port", type=int, default=None, help="HTTP port to listen on (default: AURASEED_PORT or 7099)")
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
    from auraseed.grid.peer_transfer import P2PVenvClient

    parser = argparse.ArgumentParser(prog="auraseed p2p", description="P2P venv transfer between nodes.")
    parser.add_argument("action", choices=["pull", "push"], help="Pull or push bundle")
    parser.add_argument("peer_url", help="Peer node URL")
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
    if parsed.action == "push":
        print(f"[AuraSeed P2P] Pushing '{parsed.name}' to {parsed.peer_url}...")
        resp = client.push_bundle_to_peer(parsed.peer_url, parsed.name)
        print(f"[AuraSeed P2P] Peer response: {json.dumps(resp, indent=2)}")
        return 0

    return 1


def handle_cleanup_cli(args: List[str]) -> int:
    from auraseed.lifecycle import cleanup_auraseed_user, cleanup_legacy_app

    parser = argparse.ArgumentParser(
        prog="auraseed cleanup",
        description="Clean up legacy AuraSeed apps or completely remove AuraSeed user/OS state.",
    )
    sub = parser.add_subparsers(dest="cleanup_cmd", required=True)

    p_app = sub.add_parser("app", help="Delete a legacy AuraSeed-installed application and its state")
    p_app.add_argument("name", help="Legacy application name (e.g. bijou)")
    p_app.add_argument("--keep-mvenv", action="store_true", help="Preserve any matching mvenv")
    p_app.add_argument("--no-registry", action="store_true", help="Skip OS registry/env cleanup")
    p_app.add_argument("--json", action="store_true", help="Output as JSON")

    p_self = sub.add_parser("self", help="Completely remove AuraSeed state, registry keys, env vars, and optional package")
    p_self.add_argument("--yes", "-y", action="store_true", help="Skip confirmation prompt")
    p_self.add_argument("--remove-package", action="store_true", help="Also pip-uninstall the auraseed Python package")
    p_self.add_argument("--purge-bootstrapped-python", action="store_true", help="Also delete AuraSeedBootstrapped registry entries")
    p_self.add_argument("--no-registry", action="store_true", help="Skip OS registry/env cleanup")
    p_self.add_argument("--json", action="store_true", help="Output as JSON")

    parsed = parser.parse_args(args)
    if parsed.cleanup_cmd == "app":
        report = cleanup_legacy_app(
            parsed.name,
            remove_mvenv=not parsed.keep_mvenv,
            clean_os_registry=not parsed.no_registry,
        )
        if parsed.json:
            print(json.dumps(report, indent=2))
        else:
            print(f"[AuraSeed] Cleaned app '{parsed.name}': {len(report['removed_paths'])} paths removed.")
        return 0

    if parsed.cleanup_cmd == "self":
        if not parsed.yes and sys.stdin.isatty():
            reply = input("[AuraSeed] Remove all AuraSeed apps, mvenvs, user dirs, env vars, and registry keys? [y/N]: ").strip().lower()
            if reply not in ("y", "yes"):
                print("[AuraSeed] Cleanup cancelled.")
                return 1
        report = cleanup_auraseed_user(
            remove_package=bool(parsed.remove_package),
            purge_bootstrapped_python=bool(parsed.purge_bootstrapped_python),
            clean_os_registry=not parsed.no_registry,
        )
        if parsed.json:
            print(json.dumps(report, indent=2))
        else:
            print(
                f"[AuraSeed] Full cleanup complete: apps={len(report['removed_apps'])}, "
                f"mvenvs={len(report['removed_mvenvs'])}, paths={len(report['removed_paths'])}, "
                f"registry={len(report['cleaned_registry'])}, package_removed={report['package_removed']}"
            )
        return 0

    return 1


def handle_install_self_cli(args: List[str]) -> int:
    from auraseed.lifecycle import install_auraseed_standalone

    parser = argparse.ArgumentParser(
        prog="auraseed install-self",
        description="Install AuraSeed standalone into an isolated user-space virtual environment.",
    )
    parser.add_argument("--dest", default=None, help="Target standalone installation directory")
    parser.add_argument("--source", default=None, help="Source directory to install from")
    parser.add_argument("--wheelhouse", default=None, help="Offline wheelhouse directory")
    parser.add_argument("--base-python", default=None, help="Base Python executable to seed from")
    parser.add_argument("--editable", action="store_true", help="Install in editable mode")
    parser.add_argument("--no-register", action="store_true", help="Skip HKCU registry and env var registration")
    parser.add_argument("--add-to-path", action="store_true", help="Add standalone bin directory to HKCU PATH")
    parser.add_argument("--json", action="store_true", help="Output as JSON")

    parsed = parser.parse_args(args)
    report = install_auraseed_standalone(
        dest_dir=Path(parsed.dest) if parsed.dest else None,
        source_path=Path(parsed.source) if parsed.source else None,
        wheelhouse_dir=Path(parsed.wheelhouse) if parsed.wheelhouse else None,
        base_python=parsed.base_python,
        register_os=not parsed.no_register,
        add_to_path=bool(parsed.add_to_path),
        editable=bool(parsed.editable),
    )
    if parsed.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"[AuraSeed] Installed standalone -> {report['install_dir']} (python={report['python_path']})")
    return 0


def _handle_migrated_app_command(cmd: str) -> int:
    guidance = {
        "install-app": "aurasprout install",
        "install": "aurasprout install",
        "package-app": "aurasprout package",
        "bundle-app": "aurasprout package",
        "package": "aurasprout package",
        "deploy": "aurasprout deploy",
        "catalog": "aurasprout catalog",
    }
    target = guidance.get(cmd, "aurasprout")
    print(
        f"[AuraSeed] The '{cmd}' command has migrated to AuraSprout. "
        f"Use '{target}' instead (auraseed now focuses strictly on runtime discovery and mvenv management).",
        file=sys.stderr,
    )
    return 2


def main() -> int:
    if len(sys.argv) > 1:
        early_cmd = sys.argv[1].lower()
        if early_cmd == "cleanup":
            return handle_cleanup_cli(sys.argv[2:])
        if early_cmd in ("uninstall", "uninstall-self"):
            return handle_cleanup_cli(["self", *sys.argv[2:]])
        if early_cmd == "install-self":
            return handle_install_self_cli(sys.argv[2:])

    from auraseed.provision.config_manager import apply_user_configs
    quiet_mode = ("--json" in sys.argv or "--mcp" in sys.argv)
    apply_user_configs(auto_yes=quiet_mode, quiet=quiet_mode)
    if len(sys.argv) > 1:
        cmd = sys.argv[1].lower()
        if cmd == "discover":
            return handle_discover_cli(sys.argv[2:])
        if cmd in ("install-app", "install", "package-app", "bundle-app", "package", "deploy", "catalog"):
            return _handle_migrated_app_command(cmd)
        if cmd in ("gui", "hub", "mvenv-gui"):
            from auraseed.gui import launch_gui
            return launch_gui()
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
        from auraseed.models import IsolationStatus, SelectedInterpreterContext
        now_str = datetime.now(timezone.utc).isoformat()
        manifest = SeedManifest(
            seed_version="1.1.0",
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
