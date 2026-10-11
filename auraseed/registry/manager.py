import json
from pathlib import Path
from typing import Dict, Any

class RegistryManager:
    """
    Global JSON Manifest Reader/Writer for ~/.auraseed/environments.json.
    """
    def __init__(self, registry_dir: Path):
        self.registry_dir = registry_dir
        self.manifest_path = self.registry_dir / "environments.json"

    def read_manifest(self) -> Dict[str, Any]:
        """
        Reads the tracking manifest.
        """
        if not self.manifest_path.exists():
            return {"version": "1.0", "environments": {}}
        
        with open(self.manifest_path, "r", encoding="utf-8") as f:
            return json.load(f)

    def write_manifest(self, data: Dict[str, Any]) -> None:
        """
        Writes to the tracking manifest.
        """
        self.registry_dir.mkdir(parents=True, exist_ok=True)
        with open(self.manifest_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
