"""
Client SDK for AuraSeed Application Deployment and MVenv Management.
Zero external runtime dependencies (Python standard library only).
"""
import io
import os
import json
import shutil
import tempfile
import urllib.parse
import urllib.request
import urllib.error
from pathlib import Path
from typing import Dict, Any, List, Optional, Union

from auraseed.installer.models import AppManifest


class AuraSeedClient:
    """
    Standard Python client for connecting to an AuraSeed-compliant server.
    Conforms to the independent OpenAPI specification.
    """

    def __init__(self, base_url: str = "http://localhost:7099", timeout: int = 30):
        url = base_url.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            url = f"http://{url}"
        self.base_url = url.rstrip("/")
        self.timeout = timeout

    def _url(self, path: str) -> str:
        if not path.startswith("/"):
            path = "/" + path
        return f"{self.base_url}{path}"

    def _request(
        self,
        method: str,
        path: str,
        body: Optional[Union[bytes, Dict[str, Any]]] = None,
        headers: Optional[Dict[str, str]] = None,
        query: Optional[Dict[str, str]] = None
    ) -> Any:
        url = self._url(path)
        if query:
            qs = urllib.parse.urlencode({k: v for k, v in query.items() if v is not None})
            if qs:
                url = f"{url}?{qs}"

        req_headers = headers.copy() if headers else {}
        data = None

        if body is not None:
            if isinstance(body, (dict, list)):
                data = json.dumps(body).encode("utf-8")
                if "Content-Type" not in req_headers:
                    req_headers["Content-Type"] = "application/json"
            elif isinstance(body, bytes):
                data = body
                if "Content-Type" not in req_headers:
                    req_headers["Content-Type"] = "application/octet-stream"
            else:
                data = str(body).encode("utf-8")

        req = urllib.request.Request(url, data=data, headers=req_headers, method=method)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                resp_bytes = resp.read()
                content_type = resp.headers.get("Content-Type", "")
                if "application/json" in content_type:
                    return json.loads(resp_bytes.decode("utf-8"))
                return resp_bytes
        except urllib.error.HTTPError as e:
            err_body = e.read()
            msg = f"HTTP {e.code}: {e.reason}"
            try:
                err_json = json.loads(err_body.decode("utf-8"))
                if "error" in err_json:
                    msg = f"{msg} - {err_json['error']}"
            except Exception:
                pass
            raise RuntimeError(msg) from e
        except urllib.error.URLError as e:
            raise ConnectionError(f"Failed to connect to AuraSeed server at {self.base_url}: {e.reason}") from e

    # System & Health
    def get_health(self) -> Dict[str, Any]:
        """Checks server health and connectivity status."""
        return self._request("GET", "/health")

    def get_openapi(self, format: str = "json") -> Union[Dict[str, Any], str]:
        """Retrieves the OpenAPI specification directly from the server."""
        if format.lower() == "yaml":
            raw = self._request("GET", "/api/v1/openapi.yaml")
            return raw.decode("utf-8") if isinstance(raw, bytes) else raw
        return self._request("GET", "/api/v1/openapi.json")

    def discover_runtimes(self) -> List[Dict[str, Any]]:
        """Queries the server for host Python interpreters."""
        data = self._request("GET", "/api/v1/discovery")
        return data.get("interpreters", [])

    # Catalog & Application Deployment
    def list_apps(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        """Lists cataloged applications available on the server."""
        params = {"q": query} if query else None
        data = self._request("GET", "/api/v1/apps", query=params)
        return data.get("apps", [])

    def get_app(self, name: str) -> Dict[str, Any]:
        """Retrieves metadata for a specific application."""
        return self._request("GET", f"/api/v1/apps/{name}")

    def download_app(self, name: str, dest_path: Union[str, Path]) -> Path:
        """Downloads an application installer bundle from the catalog."""
        dest = Path(dest_path).resolve()
        data = self._request("GET", f"/api/v1/apps/{name}/download")
        if dest.is_dir():
            dest = dest / f"{name}-bundle.zip"
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return dest

    def deploy_app(
        self,
        app_source_or_bundle: Union[str, Path, bytes],
        filename: Optional[str] = None,
        manifest_override: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Packages and deploys an application to the server catalog.
        Accepts:
          - A directory containing an app.json manifest (packaged automatically into a zip bundle)
          - An existing .zip or .tar.gz bundle path
          - Raw package bundle bytes
        """
        headers = {}
        temp_dir = None

        try:
            if isinstance(app_source_or_bundle, (str, Path)):
                p = Path(app_source_or_bundle).resolve()
                if p.is_dir():
                    # Directory: Package up with AppBundlePackager
                    from auraseed.installer.packager import AppBundlePackager
                    temp_dir = tempfile.mkdtemp(prefix="auraseed_pack_")
                    packager = AppBundlePackager(p)
                    zip_bundle = packager.package(Path(temp_dir), create_zip=True)
                    payload_bytes = zip_bundle.read_bytes()
                    chosen_filename = zip_bundle.name
                    headers["Content-Type"] = "application/zip"
                else:
                    payload_bytes = p.read_bytes()
                    chosen_filename = p.name
                    if p.name.endswith(".zip"):
                        headers["Content-Type"] = "application/zip"
                    else:
                        headers["Content-Type"] = "application/gzip"
            elif isinstance(app_source_or_bundle, bytes):
                payload_bytes = app_source_or_bundle
                chosen_filename = filename or "bundle.zip"
                headers["Content-Type"] = "application/zip"
            else:
                raise TypeError("app_source_or_bundle must be a directory Path, bundle file Path, or bytes")

            headers["X-App-Filename"] = chosen_filename
            if manifest_override:
                headers["X-App-Manifest"] = json.dumps(manifest_override)

            return self._request("POST", "/api/v1/apps", body=payload_bytes, headers=headers)
        finally:
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir, ignore_errors=True)

    def delete_app(self, name: str) -> bool:
        """Deletes an application from the server catalog."""
        try:
            resp = self._request("DELETE", f"/api/v1/apps/{name}")
            return bool(resp.get("success", True))
        except RuntimeError:
            return False

    # Managed Virtual Environments (mvenvs)
    def list_mvenvs(self) -> List[Dict[str, Any]]:
        """Lists all managed virtual environments on the server node."""
        data = self._request("GET", "/api/v1/mvenv")
        return data.get("mvenvs", [])

    def get_mvenv(self, name: str) -> Dict[str, Any]:
        """Retrieves details of a specific mvenv."""
        return self._request("GET", f"/api/v1/mvenv/{name}")

    def create_mvenv(
        self,
        name: str,
        packages: Optional[List[str]] = None,
        requirements_file: Optional[str] = None,
        base_python: Optional[str] = None,
        sovereign: bool = True,
        force: bool = False,
        target_dir: Optional[str] = None,
        tags: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Creates a managed virtual environment on the server node."""
        body = {
            "name": name,
            "packages": packages or [],
            "requirements_file": requirements_file,
            "base_python": base_python,
            "sovereign": sovereign,
            "force": force,
            "target_dir": target_dir,
            "tags": tags or {}
        }
        return self._request("POST", "/api/v1/mvenv", body=body)

    def verify_mvenv(self, name: str) -> Dict[str, Any]:
        """Verifies health and executables of an mvenv."""
        return self._request("GET", f"/api/v1/mvenv/{name}/verify")

    def install_packages(
        self,
        name: str,
        packages: Optional[List[str]] = None,
        requirements: Optional[str] = None,
        upgrade: bool = False
    ) -> Dict[str, Any]:
        """Installs packages into an mvenv."""
        body = {
            "packages": packages or [],
            "requirements": requirements,
            "upgrade": upgrade
        }
        return self._request("POST", f"/api/v1/mvenv/{name}/install", body=body)

    def delete_mvenv(self, name: str) -> bool:
        """Deletes an mvenv from the server node."""
        try:
            resp = self._request("DELETE", f"/api/v1/mvenv/{name}")
            return bool(resp.get("success", True))
        except RuntimeError:
            return False

    def merge_mvenvs(
        self,
        sources: List[str],
        target: str,
        delete_sources: bool = False,
        repoint_apps: bool = True
    ) -> Dict[str, Any]:
        """
        Merges multiple source mvenvs into a single target mvenv to reclaim disk space.
        """
        body = {
            "sources": sources,
            "target": target,
            "delete_sources": delete_sources,
            "repoint_apps": repoint_apps
        }
        return self._request("POST", "/api/v1/mvenv/merge", body=body)
