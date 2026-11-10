"""
Attached AuraSeed Catalogs Registry.
Zero external runtime dependencies (Python standard library only).
"""
import os
import json
from pathlib import Path
from typing import List, Dict, Any, Optional


class CatalogRegistry:
    """
    Manages client-side attached AuraSeed catalogs.
    Allows local nodes to discover, query, and install applications from multiple servers.
    """

    DEFAULT_CATALOG_URL = "http://localhost:7099"

    def __init__(self, config_path: Optional[Path] = None):
        if config_path:
            self.config_path = Path(config_path).resolve()
        else:
            local_appdata = os.environ.get("LOCALAPPDATA")
            if local_appdata and os.name == "nt":
                base = Path(local_appdata) / "AuraSeed"
            else:
                base = Path.home() / ".auraseed"
            self.config_path = (base / "catalogs.json").resolve()

        self.config_path.parent.mkdir(parents=True, exist_ok=True)
        if not self.config_path.exists():
            self._save_catalogs([
                {
                    "url": self.DEFAULT_CATALOG_URL,
                    "label": "Local AuraSeed Daemon",
                    "is_default": True
                }
            ])

    def _normalize_url(self, url: str) -> str:
        u = url.strip()
        if not (u.startswith("http://") or u.startswith("https://")):
            u = f"http://{u}"
        return u.rstrip("/")

    def list_catalogs(self) -> List[Dict[str, Any]]:
        if not self.config_path.exists():
            return []
        try:
            return json.loads(self.config_path.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _save_catalogs(self, catalogs: List[Dict[str, Any]]) -> None:
        self.config_path.write_text(json.dumps(catalogs, indent=2), encoding="utf-8")

    def add_catalog(self, url: str, label: Optional[str] = None, set_default: bool = False) -> Dict[str, Any]:
        norm_url = self._normalize_url(url)
        catalogs = self.list_catalogs()

        for c in catalogs:
            if self._normalize_url(c["url"]) == norm_url:
                if label:
                    c["label"] = label
                if set_default:
                    for other in catalogs:
                        other["is_default"] = False
                    c["is_default"] = True
                self._save_catalogs(catalogs)
                return c

        new_entry = {
            "url": norm_url,
            "label": label or norm_url,
            "is_default": bool(set_default or len(catalogs) == 0)
        }
        if set_default:
            for other in catalogs:
                other["is_default"] = False

        catalogs.append(new_entry)
        self._save_catalogs(catalogs)
        return new_entry

    def remove_catalog(self, url: str) -> bool:
        norm_url = self._normalize_url(url)
        catalogs = self.list_catalogs()
        initial_len = len(catalogs)
        remaining = [c for c in catalogs if self._normalize_url(c["url"]) != norm_url]

        if len(remaining) == initial_len:
            return False

        # If we removed default, set the first one as default
        if remaining and not any(c.get("is_default") for c in remaining):
            remaining[0]["is_default"] = True

        self._save_catalogs(remaining)
        return True

    def get_default_catalog(self) -> str:
        catalogs = self.list_catalogs()
        for c in catalogs:
            if c.get("is_default"):
                return c["url"]
        return self.DEFAULT_CATALOG_URL
