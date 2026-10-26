import os
import json
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Optional, Dict, Any


@dataclass
class GridContext:
    """
    Context indicating that AuraSeed is operating within an AuraGrid node.
    """
    is_on_grid: bool
    node_id: Optional[str] = None
    management_port: Optional[int] = None
    proxy_port: Optional[int] = None
    cell_id: Optional[str] = None
    mvenv_root: Optional[str] = None
    config_source: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def detect_grid() -> Optional[GridContext]:
    """
    Determines if AuraSeed is executing within an active AuraGrid node or environment.
    """
    # 1. Environment variables
    node_id = os.environ.get("AURAGRID_NODE_ID") or os.environ.get("AURA_NODE_ID")
    mgmt_port = os.environ.get("AURAGRID_MANAGEMENT_PORT") or os.environ.get("AURA_MANAGEMENT_PORT")
    proxy_port = os.environ.get("AURAGRID_PROXY_PORT") or os.environ.get("AURA_PROXY_PORT")
    cell_id = os.environ.get("AURAGRID_CELL_ID") or os.environ.get("AURA_CELL_ID")
    mvenv_root = os.environ.get("AURAGRID_MVENV_ROOT") or os.environ.get("AURA_MVENV_ROOT")

    if node_id:
        return GridContext(
            is_on_grid=True,
            node_id=node_id,
            management_port=int(mgmt_port) if mgmt_port and mgmt_port.isdigit() else 7077,
            proxy_port=int(proxy_port) if proxy_port and proxy_port.isdigit() else 8088,
            cell_id=cell_id or "default-cell",
            mvenv_root=mvenv_root,
            config_source="environment_variables"
        )

    # 2. Check nearby appsettings.json
    candidates = [
        Path.cwd() / "appsettings.json",
        Path.cwd() / "config" / "appsettings.json",
        Path.cwd().parent / "config" / "appsettings.json",
        Path.home() / ".auragrid" / "config" / "appsettings.json"
    ]

    for candidate in candidates:
        if candidate.exists():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
                if "AuraGrid" in data:
                    ag = data["AuraGrid"]
                    pw = ag.get("ProxyWorker", {})
                    wm = ag.get("WebManagement", {})
                    py = ag.get("PythonEnvironment", {})
                    listen = wm.get("ListenPrefix", "")
                    port = 7077
                    if ":" in listen:
                        try:
                            port = int(listen.split(":")[-1].split("/")[0])
                        except ValueError:
                            pass

                    return GridContext(
                        is_on_grid=True,
                        node_id=pw.get("NodeId", "unknown-grid-node"),
                        management_port=port,
                        proxy_port=ag.get("ServiceProxy", {}).get("ProxyPort", 8088),
                        cell_id=ag.get("Region", {}).get("CellId", "default-cell"),
                        mvenv_root=py.get("MvenvRootPath"),
                        config_source=str(candidate)
                    )
            except Exception:
                pass

    return None
