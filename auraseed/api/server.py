import os
import sys
import json
import shutil
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Optional, Dict, Any

from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest
from auraseed.grid.detector import detect_grid


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class AuraSeedApiHandler(BaseHTTPRequestHandler):
    """
    Zero-dependency HTTP/REST API request handler for AuraSeed mvenv operations.
    """
    server_version = "AuraSeed-API/0.2.0"

    @property
    def manager(self) -> MvenvManager:
        return self.server.mvenv_manager  # type: ignore

    def _send_json(self, status_code: int, data: Any):
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(self, status_code: int, message: str):
        self._send_json(status_code, {"error": message, "status": "error", "code": status_code})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization")
        self.end_headers()

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        # Health probe
        if path == "/health" or path == "":
            grid_info = detect_grid()
            self._send_json(200, {
                "status": "ok",
                "service": "auraseed",
                "version": "0.2.0",
                "is_grid_connected": grid_info.is_on_grid if grid_info else False,
                "node_id": grid_info.node_id if grid_info else None,
                "mvenv_root": str(self.manager.root_path),
                "mvenv_count": len(self.manager.list_venvs())
            })
            return

        # List all mvenvs
        if path == "/api/v1/mvenv":
            records = [r.to_dict() for r in self.manager.list_venvs()]
            self._send_json(200, {"mvenvs": records, "total": len(records)})
            return

        # Discovery of host runtimes
        if path == "/api/v1/discovery":
            manager = self.manager._discover_best_interpreter()
            discovered = [
                {
                    "id": manager.id,
                    "name": manager.name,
                    "executable": str(manager.executable),
                    "version": manager.version,
                    "source_type": manager.source_type
                }
            ]
            self._send_json(200, {"interpreters": discovered})
            return

        # Single mvenv inspection: /api/v1/mvenv/{name}
        if path.startswith("/api/v1/mvenv/"):
            parts = path[len("/api/v1/mvenv/"):].split("/")
            name = parts[0]

            if len(parts) == 1:
                rec = self.manager.get_venv(name)
                if not rec:
                    self._send_error(404, f"Managed environment '{name}' not found.")
                    return
                self._send_json(200, rec.to_dict())
                return

            # Verification: /api/v1/mvenv/{name}/verify
            if len(parts) == 2 and parts[1] == "verify":
                res = self.manager.verify_venv(name)
                self._send_json(200 if res.get("valid") else 400, res)
                return

            # Download bundle: /api/v1/mvenv/{name}/bundle
            if len(parts) == 2 and parts[1] == "bundle":
                rec = self.manager.get_venv(name)
                if not rec:
                    self._send_error(404, f"Managed environment '{name}' not found.")
                    return
                try:
                    bundle_file = self.manager.export_bundle(name)
                    file_size = os.path.getsize(bundle_file)
                    self.send_response(200)
                    self.send_header("Content-Type", "application/gzip")
                    self.send_header("Content-Disposition", f'attachment; filename="{bundle_file.name}"')
                    self.send_header("Content-Length", str(file_size))
                    self.end_headers()
                    with open(bundle_file, "rb") as f:
                        shutil.copyfileobj(f, self.wfile)
                    return
                except Exception as ex:
                    self._send_error(500, f"Failed to export bundle: {ex}")
                    return

        self._send_error(404, f"Endpoint not found: {path}")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""

        # Create new mvenv: POST /api/v1/mvenv
        if path == "/api/v1/mvenv":
            try:
                data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception:
                self._send_error(400, "Invalid JSON body.")
                return

            name = data.get("name")
            if not name:
                self._send_error(400, "Missing required field 'name'.")
                return

            req = MvenvCreateRequest(
                name=name,
                base_python=data.get("base_python") or data.get("basePython"),
                packages=data.get("packages"),
                requirements_file=data.get("requirements_file") or data.get("requirementsFile"),
                sovereign=data.get("sovereign", True),
                force=data.get("force", False),
                target_dir=data.get("target_dir") or data.get("targetDir"),
                tags=data.get("tags")
            )

            try:
                rec = self.manager.create_venv(req)
                self._send_json(201, rec.to_dict())
            except Exception as ex:
                self._send_error(500, f"Failed to create mvenv: {ex}")
            return

        # Upload / import bundle: POST /api/v1/mvenv/bundle
        if path == "/api/v1/mvenv/bundle":
            target_name = self.headers.get("X-Mvenv-Name")
            temp_bundle = self.manager.root_path / f"temp_{os.getpid()}_{urllib.parse.quote_plus(target_name or 'bundle')}.tar.gz"
            try:
                with open(temp_bundle, "wb") as f:
                    f.write(body_bytes)
                rec = self.manager.import_bundle(temp_bundle, target_name=target_name, force=True)
                if temp_bundle.exists():
                    os.remove(temp_bundle)
                self._send_json(201, rec.to_dict())
            except Exception as ex:
                if temp_bundle.exists():
                    try: os.remove(temp_bundle)
                    except OSError: pass
                self._send_error(500, f"Failed to import bundle: {ex}")
            return

        # Install packages: POST /api/v1/mvenv/{name}/install
        if path.startswith("/api/v1/mvenv/") and path.endswith("/install"):
            parts = path[len("/api/v1/mvenv/"):].split("/")
            name = parts[0]

            try:
                data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception:
                self._send_error(400, "Invalid JSON body.")
                return

            packages = data.get("packages", [])
            requirements = data.get("requirements")
            upgrade = data.get("upgrade", False)

            try:
                if requirements:
                    rec = self.manager.install_requirements(name, requirements)
                else:
                    rec = self.manager.install_packages(name, packages, upgrade=upgrade)
                self._send_json(200, rec.to_dict())
            except Exception as ex:
                self._send_error(500, f"Failed to install packages: {ex}")
            return

        self._send_error(404, f"Endpoint not found: {path}")

    def do_DELETE(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        # Delete mvenv: DELETE /api/v1/mvenv/{name}
        if path.startswith("/api/v1/mvenv/"):
            name = path[len("/api/v1/mvenv/"):].split("/")[0]
            deleted = self.manager.delete_venv(name)
            if deleted:
                self._send_json(200, {"success": True, "message": f"Mvenv '{name}' deleted."})
            else:
                self._send_error(404, f"Mvenv '{name}' not found.")
            return

        self._send_error(404, f"Endpoint not found: {path}")

    def log_message(self, format, *args):
        # Quiet log unless DEBUG is enabled
        if os.environ.get("AURASEED_DEBUG") == "1":
            super().log_message(format, *args)


try:
    from auragrid import auragrid_service, auragrid_method
except ImportError:
    def auragrid_service(name: str = "", description: str = ""):
        def deco(cls):
            cls._service_name = name
            cls._service_description = description
            return cls
        return deco

    def auragrid_method(name: str = ""):
        def deco(fn):
            fn._method_name = name
            return fn
        return deco


@auragrid_service(name="AuraSeed", description="Managed virtual environment (mvenv) creation, isolation, and pruning")
class AuraSeedMasService:
    """AuraGrid MAS for managing virtual environments natively without standalone HTTP server."""

    def __init__(self, manager: Optional[MvenvManager] = None) -> None:
        self.manager = manager or MvenvManager()

    @auragrid_method(name="ListMenvs")
    def list_mvenvs(self) -> dict:
        return {"mvenvs": self.manager.list_all(), "count": len(self.manager.list_all())}

    @auragrid_method(name="GetHealth")
    def get_health(self) -> dict:
        return {"status": "Healthy", "service": "AuraSeed", "root_path": str(self.manager.root_path)}

    @auragrid_method(name="PruneStale")
    def prune_stale(self, hours: float = 24.0) -> dict:
        pruned = self.manager.prune_stale(hours)
        return {"pruned": pruned, "count": len(pruned)}


def create_api_server(host: str = "0.0.0.0", port: int = 7099, manager: Optional[MvenvManager] = None) -> ThreadedHTTPServer:
    m = manager or MvenvManager()
    server = ThreadedHTTPServer((host, port), AuraSeedApiHandler)
    server.mvenv_manager = m  # type: ignore
    return server


def run_api_server(host: str = "0.0.0.0", port: int = 7099, manager: Optional[MvenvManager] = None):
    server = create_api_server(host, port, manager)
    print(f"[AuraSeed API] Listening on http://{host}:{port}/")
    print(f"[AuraSeed API] Mvenv root: {server.mvenv_manager.root_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AuraSeed API] Shutting down.")
    finally:
        server.server_close()
