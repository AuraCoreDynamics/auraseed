from typing import List
from auraseed.models import VersionAuditReport, DiscoveredEnvironment
from auraseed.discovery.manager import DiscoveryManager

def audit_host_updates(adapter_name: str, discovery_manager: DiscoveryManager, known_version_ids: List[str]) -> VersionAuditReport:
    """
    Re-runs discovery for a specified adapter and compares against previously recorded versions.
    Returns a VersionAuditReport detailing drift.
    """
    results = discovery_manager.run_discovery()
    adapter_results = [env for env in results.values() if env.source_type == adapter_name]
    
    current_ids = {env.id for env in adapter_results}
    known_ids_set = set(known_version_ids)
    
    new_versions = [env for env in adapter_results if env.id not in known_ids_set]
    removed_version_ids = list(known_ids_set - current_ids)
    
    recommend_reseed = len(new_versions) > 0

    return VersionAuditReport(
        adapter_name=adapter_name,
        new_versions=new_versions,
        removed_version_ids=removed_version_ids,
        recommend_reseed=recommend_reseed
    )
