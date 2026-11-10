"""
AuraSeed HTTP/REST API Server.
Zero external runtime dependencies (Python standard library only).
Complies with the independent, version-controlled OpenAPI specification.
"""
import os
import sys
import json
import base64
import shutil
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from socketserver import ThreadingMixIn
from pathlib import Path
from typing import Optional, Dict, Any

from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest
from auraseed.grid.detector import detect_grid
from auraseed.catalog.server import ServerAppCatalog
from auraseed.api.mcp import AuraSeedMcpServer


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True


class AuraSeedApiHandler(BaseHTTPRequestHandler):
    """
    Zero-dependency HTTP/REST API request handler for AuraSeed mvenv and app catalog operations.
    """
    server_version = "AuraSeed-API/1.0.0"

    @property
    def manager(self) -> MvenvManager:
        return self.server.mvenv_manager  # type: ignore

    @property
    def catalog(self) -> ServerAppCatalog:
        return self.server.catalog_manager  # type: ignore

    def _send_json(self, status_code: int, data: Any):
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-App-Filename, X-App-Manifest, X-Mvenv-Name")
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(self, status_code: int, message: str):
        self._send_json(status_code, {"error": message, "status": "error", "code": status_code})

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-App-Filename, X-App-Manifest, X-Mvenv-Name")
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
                "version": "1.0.0",
                "is_grid_connected": grid_info.is_on_grid if grid_info else False,
                "node_id": grid_info.node_id if grid_info else None,
                "mvenv_root": str(self.manager.root_path),
                "mvenv_count": len(self.manager.list_venvs()),
                "app_count": len(self.catalog.list_apps())
            })
            return

        # Independent OpenAPI specification artifacts
        if path in ("/openapi.json", "/api/v1/openapi.json"):
            spec_file = Path(__file__).resolve().parent.parent / "openapi.json"
            if spec_file.exists():
                payload = spec_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(payload)
                return
            else:
                self._send_error(404, "openapi.json artifact not found.")
                return

        if path in ("/openapi.yaml", "/api/v1/openapi.yaml"):
            spec_file = Path(__file__).resolve().parent.parent / "openapi.yaml"
            if spec_file.exists():
                payload = spec_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/yaml; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                self.wfile.write(payload)
                return
            else:
                self._send_error(404, "openapi.yaml artifact not found.")
                return

        # Discovery of host runtimes
        if path == "/api/v1/discovery":
            adapter = query.get("adapter", ["all"])[0]
            try:
                envs = self.manager.discover_interpreters(adapter=adapter)
            except Exception:
                envs = [self.manager._discover_best_interpreter()]
            discovered = [
                {
                    "id": e.id,
                    "name": e.name,
                    "executable": str(e.executable),
                    "version": e.version,
                    "source_type": e.source_type
                }
                for e in envs
            ]
            self._send_json(200, {"interpreters": discovered})
            return

        # List all mvenvs
        if path == "/api/v1/mvenv":
            records = [r.to_dict() for r in self.manager.list_venvs()]
            self._send_json(200, {"mvenvs": records, "total": len(records)})
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

        # List Catalog Apps: /api/v1/apps
        if path == "/api/v1/apps":
            q_filter = query.get("q", [None])[0]
            apps = self.catalog.list_apps(query=q_filter)
            self._send_json(200, {"apps": apps, "total": len(apps)})
            return

        # Catalog App details or download: /api/v1/apps/{name}
        if path.startswith("/api/v1/apps/"):
            parts = path[len("/api/v1/apps/"):].split("/")
            name = parts[0]

            if len(parts) == 1:
                app_meta = self.catalog.get_app(name)
                if not app_meta:
                    self._send_error(404, f"Application '{name}' not found in catalog.")
                    return
                self._send_json(200, app_meta)
                return

            if len(parts) == 2 and parts[1] == "download":
                bundle_path = self.catalog.get_bundle_path(name)
                if not bundle_path or not bundle_path.exists():
                    self._send_error(404, f"Application package bundle for '{name}' not found.")
                    return

                file_size = os.path.getsize(bundle_path)
                content_type = "application/zip" if bundle_path.suffix == ".zip" else "application/gzip"
                self.send_response(200)
                self.send_header("Content-Type", content_type)
                self.send_header("Content-Disposition", f'attachment; filename="{bundle_path.name}"')
                self.send_header("Content-Length", str(file_size))
                self.end_headers()
                with open(bundle_path, "rb") as f:
                    shutil.copyfileobj(f, self.wfile)
                return

        self._send_error(404, f"Endpoint not found: {path}")

    def do_POST(self):
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")

        content_length = int(self.headers.get("Content-Length", 0))
        body_bytes = self.rfile.read(content_length) if content_length > 0 else b""

        # Streamable HTTP MCP endpoint: POST /mcp
        if path in ("/mcp", "/api/v1/mcp"):
            try:
                msg = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception as e:
                self._send_json(400, {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32700, "message": f"Parse error: {e}"}
                })
                return

            mcp_srv = getattr(self.server, "mcp_server", None) or AuraSeedMcpServer(self.manager)
            if isinstance(msg, list):
                responses = []
                for item in msg:
                    r = mcp_srv.handle_message(item)
                    if r is not None:
                        responses.append(r)
                if not responses:
                    self.send_response(202)
                    self.send_header("Access-Control-Allow-Origin", "*")
                    self.end_headers()
                    return
                self._send_json(200, responses)
                return

            resp = mcp_srv.handle_message(msg)
            if resp is None:
                self.send_response(202)
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                return
            self._send_json(200, resp)
            return

        # Deploy Application Package: POST /api/v1/apps
        if path == "/api/v1/apps":
            filename = self.headers.get("X-App-Filename")
            manifest_header = self.headers.get("X-App-Manifest")
            manifest_override = None
            if manifest_header:
                try:
                    manifest_override = json.loads(manifest_header)
                except Exception:
                    pass

            # Check if JSON payload with base64 bundle
            content_type = self.headers.get("Content-Type", "")
            if "application/json" in content_type:
                try:
                    data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
                except Exception:
                    self._send_error(400, "Invalid JSON payload.")
                    return

                if "bundle_base64" in data:
                    try:
                        bundle_bytes = base64.b64decode(data["bundle_base64"])
                    except Exception:
                        self._send_error(400, "Invalid base64 payload in bundle_base64.")
                        return
                    filename = data.get("filename") or filename
                    manifest_override = data.get("manifest") or manifest_override
                else:
                    self._send_error(400, "JSON deployment must provide bundle_base64.")
                    return
            else:
                bundle_bytes = body_bytes

            if not bundle_bytes:
                self._send_error(400, "Application package payload is empty.")
                return

            try:
                record = self.catalog.publish_bundle(
                    bundle_source=bundle_bytes,
                    filename=filename,
                    manifest_override=manifest_override
                )
                self._send_json(201, record)
            except Exception as ex:
                self._send_error(400, f"Failed to publish application: {ex}")
            return

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
                tags=data.get("tags"),
                python_spec=data.get("python_spec") or data.get("pythonSpec"),
                adapter=data.get("adapter", "all")
            )

            try:
                rec = self.manager.create_venv(req)
                self._send_json(201, rec.to_dict())
            except Exception as ex:
                self._send_error(500, f"Failed to create mvenv: {ex}")
            return

        # Merge mvenvs: POST /api/v1/mvenv/merge
        if path == "/api/v1/mvenv/merge":
            try:
                data = json.loads(body_bytes.decode("utf-8")) if body_bytes else {}
            except Exception:
                self._send_error(400, "Invalid JSON body.")
                return

            sources = data.get("sources", [])
            target = data.get("target")
            if not sources or not target:
                self._send_error(400, "Missing required fields 'sources' or 'target'.")
                return

            delete_sources = bool(data.get("delete_sources", False))
            repoint_apps = bool(data.get("repoint_apps", True))

            try:
                res = self.manager.merge_venvs(
                    source_names=sources,
                    target_name=target,
                    delete_sources=delete_sources,
                    repoint_apps=repoint_apps
                )
                self._send_json(200, res)
            except Exception as ex:
                self._send_error(400, f"Failed to merge mvenvs: {ex}")
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

        # Delete catalog app: DELETE /api/v1/apps/{name}
        if path.startswith("/api/v1/apps/"):
            name = path[len("/api/v1/apps/"):].split("/")[0]
            deleted = self.catalog.delete_app(name)
            if deleted:
                self._send_json(200, {"success": True, "message": f"Application '{name}' deleted from catalog."})
            else:
                self._send_error(404, f"Application '{name}' not found in catalog.")
            return

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
        return {"mvenvs": [r.to_dict() for r in self.manager.list_venvs()], "count": len(self.manager.list_venvs())}

    @auragrid_method(name="GetHealth")
    def get_health(self) -> dict:
        return {"status": "Healthy", "service": "AuraSeed", "root_path": str(self.manager.root_path)}

    @auragrid_method(name="PruneStale")
    def prune_stale(self, hours: float = 24.0) -> dict:
        pruned = self.manager.prune_stale(hours) if hasattr(self.manager, "prune_stale") else []
        return {"pruned": pruned, "count": len(pruned)}


def create_api_server(
    host: str = "0.0.0.0",
    port: int = 7099,
    manager: Optional[MvenvManager] = None,
    catalog: Optional[ServerAppCatalog] = None
) -> ThreadedHTTPServer:
    m = manager or MvenvManager()
    c = catalog or ServerAppCatalog(root_dir=m.root_path / "catalog")
    server = ThreadedHTTPServer((host, port), AuraSeedApiHandler)
    server.mvenv_manager = m  # type: ignore
    server.catalog_manager = c  # type: ignore
    server.mcp_server = AuraSeedMcpServer(m)  # type: ignore
    return server


def run_api_server(
    host: str = "0.0.0.0",
    port: int = 7099,
    manager: Optional[MvenvManager] = None,
    catalog: Optional[ServerAppCatalog] = None
):
    server = create_api_server(host, port, manager, catalog)
    print(f"[AuraSeed API] Listening on http://{host}:{port}/")
    print(f"[AuraSeed API] Mvenv root: {server.mvenv_manager.root_path}")
    print(f"[AuraSeed API] Catalog root: {server.catalog_manager.root_dir}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AuraSeed API] Shutting down.")
    finally:
        server.server_close()
