import os
import json
import urllib.request
import urllib.error
from pathlib import Path
from typing import Optional, Dict, Any

from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvRecord


class P2PVenvClient:
    """
    P2P Virtual Environment Transfer Client.
    Allows worker nodes without local build tools or compilers to pull pre-compiled,
    sovereign mvenv bundles from peer nodes across the grid.
    """

    def __init__(self, manager: Optional[MvenvManager] = None):
        self.manager = manager or MvenvManager()

    def fetch_bundle_from_peer(self, peer_url: str, mvenv_name: str, force: bool = True) -> MvenvRecord:
        """
        Fetches an mvenv bundle from a peer node and registers it in the local catalog.
        """
        base_url = peer_url.rstrip("/")
        endpoint = f"{base_url}/api/v1/mvenv/{mvenv_name}/bundle"

        temp_bundle = self.manager.root_path / f"peer_fetch_{mvenv_name}.tar.gz"

        req = urllib.request.Request(endpoint, headers={"User-Agent": "AuraSeed-P2P/0.2.0"})
        try:
            with urllib.request.urlopen(req, timeout=300) as response:
                if getattr(response, "status", 200) != 200:
                    err_msg = response.read().decode("utf-8", errors="ignore")
                    raise RuntimeError(f"Peer returned HTTP {response.status}: {err_msg}")

                with open(temp_bundle, "wb") as out_f:
                    while chunk := response.read(65536):
                        out_f.write(chunk)

            rec = self.manager.import_bundle(temp_bundle, target_name=mvenv_name, force=force)
            return rec
        finally:
            if temp_bundle.exists():
                try: os.remove(temp_bundle)
                except OSError: pass

    def push_bundle_to_peer(self, peer_url: str, mvenv_name: str) -> Dict[str, Any]:
        """
        Exports a local mvenv and pushes it to a peer node's AuraSeed API.
        """
        rec = self.manager.get_venv(mvenv_name)
        if not rec:
            raise KeyError(f"Local mvenv '{mvenv_name}' not found.")

        bundle_path = self.manager.export_bundle(mvenv_name)
        base_url = peer_url.rstrip("/")
        endpoint = f"{base_url}/api/v1/mvenv/bundle"

        with open(bundle_path, "rb") as f:
            data = f.read()

        req = urllib.request.Request(
            endpoint,
            data=data,
            headers={
                "Content-Type": "application/gzip",
                "X-Mvenv-Name": mvenv_name,
                "Content-Length": str(len(data)),
                "User-Agent": "AuraSeed-P2P/0.2.0"
            },
            method="POST"
        )

        with urllib.request.urlopen(req, timeout=300) as response:
            resp_body = response.read().decode("utf-8")
            return json.loads(resp_body)
