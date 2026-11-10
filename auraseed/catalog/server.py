"""
Server-Side Application Catalog Engine for AuraSeed.
Zero external runtime dependencies (Python standard library only).
"""
import io
import os
import json
import shutil
import zipfile
import tarfile
import hashlib
from pathlib import Path
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional, Union

from auraseed.installer.models import AppManifest


class ServerAppCatalog:
    """
    Server-side storage and metadata manager for published AuraSeed application packages.
    """

    def __init__(self, root_dir: Optional[Path] = None):
        if root_dir:
            self.root_dir = Path(root_dir).resolve()
        else:
            local_appdata = os.environ.get("LOCALAPPDATA")
            if local_appdata and os.name == "nt":
                base = Path(local_appdata) / "AuraSeed"
            else:
                base = Path.home() / ".auraseed"
            self.root_dir = (base / "server_catalog").resolve()

        self.packages_dir = self.root_dir / "packages"
        self.metadata_dir = self.root_dir / "apps"
        self.index_file = self.root_dir / "index.json"

        self.packages_dir.mkdir(parents=True, exist_ok=True)
        self.metadata_dir.mkdir(parents=True, exist_ok=True)
        if not self.index_file.exists():
            self._save_index({})

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _load_index(self) -> Dict[str, Any]:
        if not self.index_file.exists():
            return {}
        try:
            return json.loads(self.index_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_index(self, data: Dict[str, Any]) -> None:
        self.index_file.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def list_apps(self, query: Optional[str] = None) -> List[Dict[str, Any]]:
        """
        Lists all published applications in the catalog, optionally filtered by a search query.
        """
        index = self._load_index()
        apps: List[Dict[str, Any]] = []

        for name, meta in sorted(index.items(), key=lambda x: x[0]):
            if query:
                q = query.lower()
                name_match = q in meta.get("name", "").lower()
                display_match = q in meta.get("display_name", "").lower()
                desc_match = q in meta.get("description", "").lower()
                if not (name_match or display_match or desc_match):
                    continue
            apps.append(meta)

        return apps

    def get_app(self, name: str) -> Optional[Dict[str, Any]]:
        """
        Retrieves metadata for a specific application in the catalog.
        """
        meta_file = self.metadata_dir / f"{name}.json"
        if meta_file.exists():
            try:
                return json.loads(meta_file.read_text(encoding="utf-8"))
            except Exception:
                pass
        index = self._load_index()
        return index.get(name)

    def get_bundle_path(self, name: str) -> Optional[Path]:
        """
        Returns the absolute Path to the application package bundle file on disk.
        """
        app_meta = self.get_app(name)
        if not app_meta:
            return None

        filename = app_meta.get("bundle_filename")
        if filename:
            p = self.packages_dir / filename
            if p.exists():
                return p

        # Fallback search by prefix
        candidates = list(self.packages_dir.glob(f"{name}-*.*")) + list(self.packages_dir.glob(f"{name}.*"))
        if candidates:
            return candidates[0]

        return None

    def publish_bundle(
        self,
        bundle_source: Union[Path, bytes, io.BytesIO],
        filename: Optional[str] = None,
        manifest_override: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Inspects, stores, and catalogs a deployed application package (.zip or .tar.gz bundle).
        """
        # 1. Resolve raw bytes and checksum
        if isinstance(bundle_source, Path):
            bundle_path = Path(bundle_source).resolve()
            if not bundle_path.exists():
                raise FileNotFoundError(f"Bundle file not found: {bundle_path}")
            bundle_bytes = bundle_path.read_bytes()
            if not filename:
                filename = bundle_path.name
        elif isinstance(bundle_source, bytes):
            bundle_bytes = bundle_source
            if not filename:
                filename = "bundle.zip"
        elif hasattr(bundle_source, "read"):
            bundle_bytes = bundle_source.read()
            if not filename:
                filename = "bundle.zip"
        else:
            raise TypeError("bundle_source must be a Path, bytes, or file-like object")

        if not bundle_bytes:
            raise ValueError("Application bundle payload is empty.")

        sha256 = hashlib.sha256(bundle_bytes).hexdigest()
        size_bytes = len(bundle_bytes)

        # 2. Inspect bundle archive to locate app.json / manifest
        manifest_dict = dict(manifest_override or {})
        is_zip = zipfile.is_zipfile(io.BytesIO(bundle_bytes))
        is_tar = False

        if is_zip:
            with zipfile.ZipFile(io.BytesIO(bundle_bytes), "r") as zf:
                # Find app.json candidates
                manifest_names = ["app.json", "auraseed-app.json", "manifest.json"]
                chosen_member = None
                for n in zf.namelist():
                    norm = n.replace("\\", "/")
                    parts = norm.split("/")
                    if parts[-1] in manifest_names and (len(parts) <= 2 or parts[0].endswith("-installer")):
                        chosen_member = n
                        break

                if chosen_member:
                    try:
                        raw_data = zf.read(chosen_member).decode("utf-8")
                        found_manifest = json.loads(raw_data)
                        # Let manifest_override take precedence over bundled values
                        for k, v in found_manifest.items():
                            if k not in manifest_dict:
                                manifest_dict[k] = v
                    except Exception:
                        pass
        else:
            # Check tarfile
            try:
                with tarfile.open(fileobj=io.BytesIO(bundle_bytes), mode="r:*") as tf:
                    is_tar = True
                    manifest_names = ["app.json", "auraseed-app.json", "manifest.json"]
                    for member in tf.getmembers():
                        norm = member.name.replace("\\", "/")
                        parts = norm.split("/")
                        if parts[-1] in manifest_names and (len(parts) <= 2 or parts[0].endswith("-installer")):
                            f = tf.extractfile(member)
                            if f:
                                raw_data = f.read().decode("utf-8")
                                found_manifest = json.loads(raw_data)
                                for k, v in found_manifest.items():
                                    if k not in manifest_dict:
                                        manifest_dict[k] = v
                                break
            except Exception:
                is_tar = False

        app_name = manifest_dict.get("name")
        if not app_name:
            if filename and ("." in filename):
                app_name = filename.split(".")[0].split("-")[0]
            else:
                app_name = f"app_{sha256[:8]}"
            manifest_dict["name"] = app_name

        display_name = manifest_dict.get("display_name") or app_name.replace("-", " ").title()
        version = manifest_dict.get("version", "1.0.0")
        description = manifest_dict.get("description", "")
        entrypoint_command = manifest_dict.get("entrypoint_command", f"{app_name} --port {{port}}")
        default_port = manifest_dict.get("default_port")

        ext = ".zip" if is_zip else (".tar.gz" if (is_tar or (filename and filename.endswith(".tar.gz"))) else ".zip")
        final_filename = f"{app_name}-{version}{ext}"
        saved_bundle_path = self.packages_dir / final_filename

        # 3. Save package bundle file
        saved_bundle_path.write_bytes(bundle_bytes)

        # 4. Construct catalog record
        now_iso = self._now_iso()
        existing = self.get_app(app_name)
        created_at = existing.get("created_at", now_iso) if existing else now_iso

        catalog_entry: Dict[str, Any] = {
            "name": app_name,
            "display_name": display_name,
            "version": version,
            "description": description,
            "entrypoint_command": entrypoint_command,
            "default_port": default_port,
            "size_bytes": size_bytes,
            "bundle_filename": final_filename,
            "bundle_sha256": sha256,
            "download_url": f"/api/v1/apps/{app_name}/download",
            "created_at": created_at,
            "updated_at": now_iso,
            "subprojects": manifest_dict.get("subprojects", []),
            "pip_install_args": manifest_dict.get("pip_install_args", []),
            "artifacts": manifest_dict.get("artifacts", []),
            "hooks": manifest_dict.get("hooks", {}),
            "metadata": manifest_dict.get("metadata", {}),
            "manifest": manifest_dict
        }

        # 5. Persist to apps/<name>.json and index.json
        meta_file = self.metadata_dir / f"{app_name}.json"
        meta_file.write_text(json.dumps(catalog_entry, indent=2), encoding="utf-8")

        index = self._load_index()
        index[app_name] = catalog_entry
        self._save_index(index)

        return catalog_entry

    def delete_app(self, name: str) -> bool:
        """
        Deletes an application, removing its package bundle file and catalog records.
        """
        meta = self.get_app(name)
        if not meta:
            return False

        # Remove bundle file
        bundle_path = self.get_bundle_path(name)
        if bundle_path and bundle_path.exists():
            try:
                bundle_path.unlink()
            except OSError:
                pass

        # Remove metadata file
        meta_file = self.metadata_dir / f"{name}.json"
        if meta_file.exists():
            try:
                meta_file.unlink()
            except OSError:
                pass

        # Update index
        index = self._load_index()
        if name in index:
            del index[name]
            self._save_index(index)

        return True
