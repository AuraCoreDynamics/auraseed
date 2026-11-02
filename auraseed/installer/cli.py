"""
Unified CLI / GUI Application Installer Entrypoint.
Zero external runtime dependencies (Python standard library only).
"""
import sys
import os
import argparse
from pathlib import Path
from typing import List, Optional

from auraseed.installer.models import AppManifest
from auraseed.installer.engine import AppInstallerEngine


def run_installer_cli(args: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="auraseed install-app",
        description="AuraSeed Application Installer (CLI, Silent, and GUI modes)."
    )
    parser.add_argument(
        "manifest",
        nargs="?",
        default=".",
        help="Path to app.json or application directory containing app.json."
    )
    parser.add_argument(
        "--dest",
        type=str,
        default=None,
        help="Custom destination directory for the application installation."
    )
    parser.add_argument(
        "--port",
        type=int,
        default=None,
        help="Service port to bind for the application."
    )
    parser.add_argument(
        "-s", "--silent", "--unattended",
        action="store_true",
        dest="silent",
        help="Run silent, non-interactive installation with default/configured settings."
    )
    parser.add_argument(
        "--gui",
        action="store_true",
        help="Force launching the zero-dependency Tkinter GUI installer wizard."
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Force interactive CLI wizard in the terminal."
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Overwrite existing application installation directory if it exists."
    )
    parser.add_argument(
        "--no-shortcut",
        action="store_true",
        help="Skip creating a desktop shortcut."
    )

    parsed = parser.parse_args(args)

    manifest_path = Path(parsed.manifest).resolve()
    try:
        manifest = AppManifest.from_file(manifest_path)
    except Exception as e:
        print(f"[AuraSeed Installer] Error: Failed to load application manifest: {e}", file=sys.stderr)
        return 1

    dest_dir = Path(parsed.dest).resolve() if parsed.dest else None

    # Determine whether to launch GUI:
    # 1. Explicitly requested with --gui
    # 2. Not silent, not explicit --cli, and running in an interactive terminal / window with display available
    should_launch_gui = parsed.gui
    if not parsed.silent and not parsed.cli and not parsed.gui:
        # Check if GUI is feasible
        has_display = True
        if sys.platform != "win32":
            has_display = bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
        if has_display:
            try:
                import tkinter
                should_launch_gui = True
            except Exception:
                should_launch_gui = False

    if should_launch_gui:
        try:
            from auraseed.installer.gui import launch_gui
            launch_gui(manifest, dest_dir=dest_dir)
            return 0
        except Exception as e:
            print(f"[AuraSeed Installer] Could not launch GUI ({e}). Falling back to CLI mode.")

    # CLI mode (Silent or Interactive)
    engine = AppInstallerEngine(manifest, logger=print)
    target_dest = dest_dir or engine.resolve_default_dest()
    target_port = parsed.port or manifest.default_port or 8000
    create_shortcut = not parsed.no_shortcut and manifest.create_desktop_shortcut

    if not parsed.silent:
        print("=" * 60)
        print(f" {manifest.display_name} - Setup Wizard")
        print(f" Version: {manifest.version}")
        if manifest.description:
            print(f" Description: {manifest.description}")
        print("=" * 60)

        # Interactive prompts
        try:
            resp_dest = input(f"Install location [{target_dest}]: ").strip()
            if resp_dest:
                target_dest = Path(resp_dest).resolve()

            if manifest.default_port:
                resp_port = input(f"Service port [{target_port}]: ").strip()
                if resp_port.isdigit():
                    target_port = int(resp_port)

            resp_sc = input(f"Create desktop shortcut? (Y/n): ").strip().lower()
            create_shortcut = resp_sc in ("", "y", "yes")
        except (KeyboardInterrupt, EOFError):
            print("\nInstallation aborted by user.")
            return 1

    print(f"\n[AuraSeed Installer] Starting installation of {manifest.display_name}...")
    try:
        result = engine.install(
            dest_dir=target_dest,
            port=target_port,
            force=parsed.force,
            create_launchers=True,
            create_desktop_shortcut=create_shortcut
        )
        print("\n" + "=" * 60)
        print(f" [SUCCESS] {manifest.display_name} installed successfully!")
        print(f" Location: {result.get('install_dir')}")
        print(f" Service Port: {result.get('port')}")
        launchers = result.get("launchers", {})
        if launchers:
            print(" Launch scripts:")
            for kind, path in launchers.items():
                print(f"   - {kind.upper()}: {path}")
        print("=" * 60)
        return 0
    except Exception as e:
        print(f"\n[AuraSeed Installer] Error: Installation failed: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(run_installer_cli(sys.argv[1:]))

