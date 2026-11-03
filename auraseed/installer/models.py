"""
Application Manifest Data Models for AuraSeed App Installer.
Zero external runtime dependencies (Python standard library only).
"""
import json
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import List, Optional, Dict, Any


@dataclass
class AppManifest:
    """
    Specification for a Python application packaged and provisioned by AuraSeed.
    """
    name: str
    display_name: str
    version: str = "1.0.0"
    description: str = ""
    entrypoint_command: str = ""
    default_port: Optional[int] = None
    default_dest: Optional[str] = None
    source_path: str = "."
    pip_install_args: List[str] = field(default_factory=list)
    subprojects: List[str] = field(default_factory=list)
    post_install_commands: List[str] = field(default_factory=list)
    artifacts: List[str] = field(default_factory=list)
    hooks: Dict[str, str] = field(default_factory=dict)
    create_desktop_shortcut: bool = True
    create_launchers: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AppManifest":
        return cls(
            name=data.get("name", "app"),
            display_name=data.get("display_name") or data.get("name", "Application"),
            version=data.get("version", "1.0.0"),
            description=data.get("description", ""),
            entrypoint_command=data.get("entrypoint_command", ""),
            default_port=data.get("default_port"),
            default_dest=data.get("default_dest"),
            source_path=data.get("source_path", "."),
            pip_install_args=data.get("pip_install_args", []),
            subprojects=data.get("subprojects", []),
            post_install_commands=data.get("post_install_commands", []),
            artifacts=data.get("artifacts", []),
            hooks=data.get("hooks", {}),
            create_desktop_shortcut=bool(data.get("create_desktop_shortcut", True)),
            create_launchers=bool(data.get("create_launchers", True)),
            metadata=data.get("metadata", {})
        )

    @classmethod
    def from_file(cls, path: Path) -> "AppManifest":
        path = Path(path).resolve()
        if path.is_dir():
            # Check standard names
            candidates = ["app.json", "auraseed-app.json", "manifest.json"]
            for c in candidates:
                cand_path = path / c
                if cand_path.exists():
                    path = cand_path
                    break
            else:
                raise FileNotFoundError(f"No application manifest (app.json) found in directory: {path}")

        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        manifest = cls.from_dict(data)
        # Store manifest parent directory in metadata for resolving relative paths
        manifest.metadata["_manifest_dir"] = str(path.parent)
        return manifest

    def to_file(self, path: Path) -> None:
        path = Path(path).resolve()
        data = asdict(self)
        # Clean internal metadata keys
        if "metadata" in data and "_manifest_dir" in data["metadata"]:
            del data["metadata"]["_manifest_dir"]
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

