"""
Thread- and process-safe atomic discovery cache keyed by binary mtime_ns and size.
"""
import json
import logging
import os
import threading
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from auraseed.discovery.prober import sanitize_candidate_path
from auraseed.models import DiscoveredEnvironment, RuntimeCapabilityReport

_LOG = logging.getLogger(__name__)


class DiscoveryCache:
    """
    Persists probed DiscoveredEnvironment records in ~/.auraseed/discovery_cache.json
    keyed by "{exe_path}|{st_mtime_ns}|{st_size}" with atomic replace semantics.
    """

    def __init__(self, cache_path: Optional[Path] = None) -> None:
        self.cache_path = Path(cache_path) if cache_path else (Path.home() / ".auraseed" / "discovery_cache.json")
        self._lock = threading.Lock()

    @staticmethod
    def build_key(executable: Path) -> Optional[str]:
        exe = sanitize_candidate_path(executable)
        if exe is None or not exe.exists() or not exe.is_file():
            return None
        try:
            st = exe.stat()
            return f"{exe}|{st.st_mtime_ns}|{st.st_size}"
        except OSError as exc:
            _LOG.debug("Failed to stat executable %s: %s", exe, exc)
            return None

    def _read_unlocked(self) -> Dict[str, Any]:
        if not self.cache_path.exists():
            return {"version": 1, "entries": {}}
        try:
            data = json.loads(self.cache_path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and isinstance(data.get("entries"), dict):
                return data
        except (OSError, json.JSONDecodeError, ValueError) as exc:
            _LOG.warning("Resetting unreadable discovery cache %s: %s", self.cache_path, exc)
        return {"version": 1, "entries": {}}

    def _write_unlocked(self, payload: Dict[str, Any]) -> None:
        self.cache_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = self.cache_path.with_name(f"{self.cache_path.name}.tmp_{uuid.uuid4().hex}")
        try:
            with open(tmp_path, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, indent=2)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(tmp_path, self.cache_path)
        finally:
            if tmp_path.exists():
                try:
                    tmp_path.unlink()
                except OSError as exc:
                    _LOG.debug("Temporary cache cleanup skipped for %s: %s", tmp_path, exc)

    @staticmethod
    def _serialize_env(env: DiscoveredEnvironment) -> Dict[str, Any]:
        return {
            "id": env.id,
            "name": env.name,
            "executable": str(env.executable),
            "version": env.version,
            "source_type": env.source_type,
            "site_packages": [str(p) for p in env.site_packages],
            "metadata": dict(env.metadata or {}),
            "capabilities": env.capabilities.to_dict() if env.capabilities else None,
        }

    @staticmethod
    def _deserialize_env(data: Dict[str, Any]) -> DiscoveredEnvironment:
        caps_raw = data.get("capabilities")
        caps = RuntimeCapabilityReport.from_dict(caps_raw) if isinstance(caps_raw, dict) else None
        return DiscoveredEnvironment(
            id=str(data.get("id", "")),
            name=str(data.get("name", "")),
            executable=Path(str(data.get("executable", ""))),
            version=str(data.get("version", "unknown")),
            source_type=str(data.get("source_type", "unknown")),
            site_packages=[Path(str(p)) for p in data.get("site_packages", [])],
            metadata=dict(data.get("metadata") or {}),
            capabilities=caps,
        )

    def get(
        self,
        executable: Path,
        required_modules: Optional[List[str]] = None,
        required_packages: Optional[List[str]] = None,
    ) -> Optional[DiscoveredEnvironment]:
        if required_modules or required_packages:
            return None
        key = self.build_key(executable)
        if not key:
            return None
        with self._lock:
            store = self._read_unlocked()
            entry = store["entries"].get(key)
            if not isinstance(entry, dict) or entry.get("capabilities") is None:
                return None
            return self._deserialize_env(entry)

    def put(self, env: DiscoveredEnvironment) -> Optional[str]:
        if env.capabilities is None:
            return None
        key = self.build_key(env.executable)
        if not key:
            return None
        with self._lock:
            store = self._read_unlocked()
            exe_prefix = f"{Path(env.executable).resolve()}|"
            stale_keys = [k for k in list(store["entries"].keys()) if k.startswith(exe_prefix) and k != key]
            for stale_key in stale_keys:
                del store["entries"][stale_key]
            store["entries"][key] = self._serialize_env(env)
            self._write_unlocked(store)
        return key

    def prune_stale(self) -> int:
        removed = 0
        with self._lock:
            store = self._read_unlocked()
            valid_entries: Dict[str, Any] = {}
            for key, entry in store["entries"].items():
                exe_part = key.split("|", 1)[0]
                if self.build_key(Path(exe_part)) == key:
                    valid_entries[key] = entry
                else:
                    removed += 1
            if removed > 0:
                store["entries"] = valid_entries
                self._write_unlocked(store)
        return removed

    def clear(self) -> None:
        with self._lock:
            self._write_unlocked({"version": 1, "entries": {}})
