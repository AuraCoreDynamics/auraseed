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
    seed_version: str
    created_at: str
    selected_interpreter: SelectedInterpreterContext
    known_host_alternatives: List[HostAlternativeContext]
    is_default_selection: bool
    isolation_status: IsolationStatus

@dataclasses.dataclass
class VersionAuditReport:
    """
    Report detailing drift in discovered Python environments for an adapter.
    """
    adapter_name: str
    new_versions: List[DiscoveredEnvironment]
    removed_version_ids: List[str]
    recommend_reseed: bool
