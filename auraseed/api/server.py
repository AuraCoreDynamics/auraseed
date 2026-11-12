"""
AuraSeed HTTP/REST API Server.
Zero external runtime dependencies (Python standard library only).
Complies with the independent, version-controlled OpenAPI specification.
"""
import json
import logging
import os
import shutil
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from socketserver import ThreadingMixIn
from typing import Any, Callable, Dict, List, Optional

from auraseed import __version__
from auraseed.api.mcp import AuraSeedMcpServer
from auraseed.grid.detector import detect_grid
from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest

_LOG = logging.getLogger(__name__)


def _allowed_loopback_origin(origin: Optional[str], host_header: Optional[str]) -> Optional[str]:
    if not origin:
        return None
    parsed = urllib.parse.urlparse(origin)
    hostname = (parsed.hostname or "").lower()
    if hostname in ("127.0.0.1", "localhost", "::1") and parsed.scheme in ("http", "https"):
        return origin
    if host_header and parsed.netloc == host_header:
        return origin
    return None


class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True
    mvenv_manager: MvenvManager
    mcp_server: AuraSeedMcpServer
    repoint_callback: Optional[Callable[[List[str], str], List[str]]] = None


class AuraSeedApiHandler(BaseHTTPRequestHandler):
    """
    Zero-dependency HTTP/REST API request handler for AuraSeed discovery and mvenv operations.
    """
    server_version = f"AuraSeed-API/{__version__}"

    @property
    def manager(self) -> MvenvManager:
        srv = self.server
        if not isinstance(srv, ThreadedHTTPServer):
            raise RuntimeError("Invalid server instance for AuraSeedApiHandler")
        return srv.mvenv_manager

    @property
    def repoint_callback(self) -> Optional[Callable[[List[str], str], List[str]]]:
        return getattr(self.server, "repoint_callback", None)

    def _send_cors_headers(self) -> None:
        origin = _allowed_loopback_origin(self.headers.get("Origin"), self.headers.get("Host"))
        if origin:
            self.send_header("Access-Control-Allow-Origin", origin)
            self.send_header("Vary", "Origin")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, Authorization, X-Mvenv-Name")

    def _send_json(self, status_code: int, data: Any) -> None:
        payload = json.dumps(data, indent=2).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(payload)))
        self._send_cors_headers()
        self.end_headers()
        self.wfile.write(payload)

    def _send_error(self, status_code: int, message: str) -> None:
        self._send_json(status_code, {"error": message, "status": "error", "code": status_code})

    def do_OPTIONS(self) -> None:
        self.send_response(204)
        self._send_cors_headers()
        self.end_headers()

    def do_GET(self) -> None:
        parsed = urllib.parse.urlparse(self.path)
        path = parsed.path.rstrip("/")
        query = urllib.parse.parse_qs(parsed.query)

        # Health probe
        if path == "/health" or path == "":
            grid_info = detect_grid()
            self._send_json(200, {
                "status": "ok",
                "service": "auraseed",
                "version": __version__,
                "is_grid_connected": grid_info.is_on_grid if grid_info else False,
                "node_id": grid_info.node_id if grid_info else None,
                "mvenv_root": str(self.manager.root_path),
                "mvenv_count": len(self.manager.list_venvs()),
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
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(payload)
                return
            self._send_error(404, "openapi.json artifact not found.")
            return

        if path in ("/openapi.yaml", "/api/v1/openapi.yaml"):
            spec_file = Path(__file__).resolve().parent.parent / "openapi.yaml"
            if spec_file.exists():
                payload = spec_file.read_bytes()
                self.send_response(200)
                self.send_header("Content-Type", "text/yaml; charset=utf-8")
                self.send_header("Content-Length", str(len(payload)))
                self._send_cors_headers()
                self.end_headers()
                self.wfile.write(payload)
                return
            self._send_error(404, "openapi.yaml artifact not found.")
            return

        # Discovery of host runtimes
        if path == "/api/v1/discovery":
            adapter = query.get("adapter", ["all"])[0]
            probe = query.get("probe", ["false"])[0].lower() in ("1", "true", "yes")
            use_cache_vals = query.get("cache") or query.get("use_cache") or ["true"]
            use_cache = use_cache_vals[0].lower() not in ("0", "false", "no")
            try:
                envs = self.manager.discover_interpreters(
                    adapter=adapter,
                    probe_capabilities=probe,
                    use_cache=use_cache,
                )
            except Exception as exc:
                _LOG.warning("Discovery failed for adapter %s, falling back to best interpreter: %s", adapter, exc)
                envs = [self.manager._discover_best_interpreter()]
            discovered: List[Dict[str, Any]] = []
            for e in envs:
                item: Dict[str, Any] = {
                    "id": e.id,
                    "name": e.name,
                    "executable": str(e.executable),
                    "version": e.version,
                    "source_type": e.source_type,
                }
                if e.capabilities is not None:
                    item["capabilities"] = e.capabilities.to_dict()
                discovered.append(item)
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

        self._send_error(404, f"Endpoint not found: {path}")

    def do_POST(self) -> None:
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
                    self._send_cors_headers()
                    self.end_headers()
                    return
                self._send_json(200, responses)
                return

            resp = mcp_srv.handle_message(msg)
            if resp is None:
                self.send_response(202)
                self._send_cors_headers()
                self.end_headers()
                return
            self._send_json(200, resp)
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
                    repoint_apps=repoint_apps,
                    repoint_callback=self.repoint_callback,
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
                    try:
                        os.remove(temp_bundle)
                    except OSError as cleanup_ex:
                        _LOG.warning("Failed to remove temporary bundle %s: %s", temp_bundle, cleanup_ex)
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

    def do_DELETE(self) -> None:
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

    def log_message(self, format: str, *args: Any) -> None:
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
        venvs = self.manager.list_venvs()
        return {"mvenvs": [r.to_dict() for r in venvs], "count": len(venvs)}

    @auragrid_method(name="GetHealth")
    def get_health(self) -> dict:
        return {"status": "Healthy", "service": "AuraSeed", "root_path": str(self.manager.root_path)}

    @auragrid_method(name="PruneStale")
    def prune_stale(self, hours: float = 24.0) -> dict:
        pruned = self.manager.prune_stale(hours) if hasattr(self.manager, "prune_stale") else []
        return {"pruned": pruned, "count": len(pruned)}


def create_api_server(
    host: Optional[str] = None,
    port: Optional[int] = None,
    manager: Optional[MvenvManager] = None,
    repoint_callback: Optional[Callable[[List[str], str], List[str]]] = None,
) -> ThreadedHTTPServer:
    bind_host = host or os.environ.get("AURASEED_BIND_HOST", "127.0.0.1")
    bind_port = int(port if port is not None else os.environ.get("AURASEED_PORT", "7099"))
    m = manager or MvenvManager()
    server = ThreadedHTTPServer((bind_host, bind_port), AuraSeedApiHandler)
    server.mvenv_manager = m
    server.mcp_server = AuraSeedMcpServer(m)
    server.repoint_callback = repoint_callback
    return server


def run_api_server(
    host: Optional[str] = None,
    port: Optional[int] = None,
    manager: Optional[MvenvManager] = None,
    repoint_callback: Optional[Callable[[List[str], str], List[str]]] = None,
) -> None:
    server = create_api_server(host=host, port=port, manager=manager, repoint_callback=repoint_callback)
    bind_host, actual_port = server.server_address[:2]
    print(f"[AuraSeed API] Listening on http://{bind_host}:{actual_port}/")
    print(f"[AuraSeed API] Mvenv root: {server.mvenv_manager.root_path}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n[AuraSeed API] Shutting down.")
    finally:
        server.server_close()
