import dataclasses
from pathlib import Path
from typing import Dict, Any, List, Optional


@dataclasses.dataclass
class RuntimeCapabilityReport:
    """
    Capability, ABI, and borrowable-package introspection report for a Python runtime.
    """
    has_ssl: bool = False
    has_sqlite3: bool = False
    has_ctypes: bool = False
    has_tkinter: bool = False
    has_venv: bool = False
    has_pip: bool = False
    architecture: str = "unknown"
    abi_tags: List[str] = dataclasses.field(default_factory=list)
    preinstalled_packages: List[str] = dataclasses.field(default_factory=list)
    composite_score: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        return dataclasses.asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "RuntimeCapabilityReport":
        return cls(
            has_ssl=bool(data.get("has_ssl", False)),
            has_sqlite3=bool(data.get("has_sqlite3", False)),
            has_ctypes=bool(data.get("has_ctypes", False)),
            has_tkinter=bool(data.get("has_tkinter", False)),
            has_venv=bool(data.get("has_venv", False)),
            has_pip=bool(data.get("has_pip", False)),
            architecture=str(data.get("architecture", "unknown")),
            abi_tags=[str(x) for x in data.get("abi_tags", [])],
            preinstalled_packages=[str(x) for x in data.get("preinstalled_packages", [])],
            composite_score=float(data.get("composite_score", 0.0)),
        )


@dataclasses.dataclass
class DiscoveredEnvironment:
    """
    Unified metadata instance representing a discovered Python interpreter installation.
    """
    id: str
    name: str
    executable: Path
    version: str
    source_type: str
    site_packages: List[Path]
    metadata: Dict[str, Any] = dataclasses.field(default_factory=dict)
    capabilities: Optional[RuntimeCapabilityReport] = None


@dataclasses.dataclass
class SelectedInterpreterContext:
    """
    Lineage context of the interpreter selected during seeding.
    """
    executable: str
    version: str
    adapter: str
    selection_rule: str


@dataclasses.dataclass
class HostAlternativeContext:
    """
    Context representing a known host alternative.
    """
    executable: str
    version: str


@dataclasses.dataclass
class IsolationStatus:
    """
    Status of the environment isolation.
    """
    frozen: bool
    system_site_packages_severed: bool


@dataclasses.dataclass
class SeedManifest:
    """
    Manifest recording the selection lineage, default status, and host alternatives.
    """
    seed_version: str = "1.0.0"
    created_at: str = ""
    selected_interpreter: Optional[SelectedInterpreterContext] = None
    known_host_alternatives: List[HostAlternativeContext] = dataclasses.field(default_factory=list)
    is_default_selection: bool = True
    isolation_status: Optional[IsolationStatus] = None
    target_env_id: Optional[str] = None
    version: Optional[str] = None
    source_type: Optional[str] = None
    is_default: Optional[bool] = None


@dataclasses.dataclass
class VersionAuditReport:
    """
    Report detailing drift in discovered Python environments for an adapter.
    """
    adapter_name: str
    new_versions: List[DiscoveredEnvironment]
    removed_version_ids: List[str]
    recommend_reseed: bool
