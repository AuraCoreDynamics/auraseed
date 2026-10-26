from dataclasses import dataclass, field, asdict
from typing import Dict, Any, List, Optional
from pathlib import Path


@dataclass
class MvenvRecord:
    """
    Catalog record representing a managed virtual environment (mvenv).
    """
    name: str
    path: str
    python_path: str
    pip_path: str
    python_version: str
    base_interpreter: str
    created_at: str
    updated_at: str
    packages: List[str] = field(default_factory=list)
    size_bytes: int = 0
    is_sovereign: bool = True
    bundle_hash: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MvenvRecord":
        return cls(
            name=data.get("name", ""),
            path=data.get("path", ""),
            python_path=data.get("python_path") or data.get("pythonPath", ""),
            pip_path=data.get("pip_path") or data.get("pipPath", ""),
            python_version=data.get("python_version") or data.get("pythonVersion", ""),
            base_interpreter=data.get("base_interpreter") or data.get("baseInterpreter", ""),
            created_at=data.get("created_at") or data.get("createdAt", ""),
            updated_at=data.get("updated_at") or data.get("updatedAt", ""),
            packages=list(data.get("packages", [])),
            size_bytes=int(data.get("size_bytes") or data.get("sizeBytes", 0)),
            is_sovereign=bool(data.get("is_sovereign") if "is_sovereign" in data else data.get("isSovereign", True)),
            bundle_hash=data.get("bundle_hash") or data.get("bundleHash"),
            metadata=dict(data.get("metadata", {}))
        )


@dataclass
class MvenvCreateRequest:
    """
    Options for creating a new managed virtual environment.
    """
    name: str
    base_python: Optional[str] = None
    packages: Optional[List[str]] = None
    requirements_file: Optional[str] = None
    sovereign: bool = True
    force: bool = False
    target_dir: Optional[str] = None
    tags: Optional[Dict[str, Any]] = None


@dataclass
class MvenvBundleMetadata:
    """
    Header metadata bundled inside an exported mvenv .tar.gz archive.
    """
    name: str
    bundle_id: str
    bundle_hash: str
    created_at: str
    python_version: str
    platform: str
    arch: str
    packages: List[str] = field(default_factory=list)
    is_sovereign: bool = True
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "MvenvBundleMetadata":
        return cls(
            name=data.get("name", ""),
            bundle_id=data.get("bundle_id") or data.get("bundleId", ""),
            bundle_hash=data.get("bundle_hash") or data.get("bundleHash", ""),
            created_at=data.get("created_at") or data.get("createdAt", ""),
            python_version=data.get("python_version") or data.get("pythonVersion", ""),
            platform=data.get("platform", ""),
            arch=data.get("arch", ""),
            packages=list(data.get("packages", [])),
            is_sovereign=bool(data.get("is_sovereign") if "is_sovereign" in data else data.get("isSovereign", True)),
            metadata=dict(data.get("metadata", {}))
        )
