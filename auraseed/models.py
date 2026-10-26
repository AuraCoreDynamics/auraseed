import dataclasses
from pathlib import Path
from typing import Dict, Any, List, Optional

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
