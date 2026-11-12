"""
Client SDK for AuraSeed Runtime Discovery and Managed Virtual Environment (mvenv) Management.
Zero external runtime dependencies (Python standard library only).
"""
import json
import os
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Dict, List, Optional, Union


class AuraSeedClient:
    """
    Standard Python client for connecting to an AuraSeed-compliant server.
    Conforms to the independent OpenAPI specification.
    """

    def __init__(self, base_url: Optional[str] = None, timeout: int = 30) -> None:
        raw_url = base_url if base_url is not None else os.environ.get("AURASEED_URL", "")
        url = raw_url.strip()
        if not url:
            raise ValueError(
                "AuraSeed server URL is required. Pass base_url or set the AURASEED_URL environment variable."
            )
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
        query: Optional[Dict[str, str]] = None,
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
            except (UnicodeDecodeError, json.JSONDecodeError, TypeError):
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

    def discover_runtimes(
        self,
        adapter: str = "all",
        probe: bool = False,
        use_cache: bool = True,
    ) -> List[Dict[str, Any]]:
        """Queries the server for host Python interpreters."""
        params: Dict[str, str] = {"adapter": adapter}
        if probe:
            params["probe"] = "true"
            params["cache"] = "true" if use_cache else "false"
        data = self._request("GET", "/api/v1/discovery", query=params)
        return data.get("interpreters", [])

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
        tags: Optional[Dict[str, Any]] = None,
        python_spec: Optional[str] = None,
        adapter: str = "all",
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
            "tags": tags or {},
            "python_spec": python_spec,
            "adapter": adapter,
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
        upgrade: bool = False,
    ) -> Dict[str, Any]:
        """Installs packages into an mvenv."""
        body = {
            "packages": packages or [],
            "requirements": requirements,
            "upgrade": upgrade,
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
        repoint_apps: bool = True,
    ) -> Dict[str, Any]:
        """
        Merges multiple source mvenvs into a single target mvenv to reclaim disk space.
        """
        body = {
            "sources": sources,
            "target": target,
            "delete_sources": delete_sources,
            "repoint_apps": repoint_apps,
        }
        return self._request("POST", "/api/v1/mvenv/merge", body=body)
