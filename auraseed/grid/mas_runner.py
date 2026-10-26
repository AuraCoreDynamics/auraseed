import os
import sys
import time
import signal
from pathlib import Path
from typing import Optional

from auraseed.mvenv.manager import MvenvManager
from auraseed.grid.detector import detect_grid


def run_as_mas(host: str = "0.0.0.0", port: int = 7099, mvenv_root: Optional[str] = None):
    """
    Executes AuraSeed as an AuraGrid Managed Application Service (MAS).
    """
    from auraseed.api.server import create_api_server
    grid_ctx = detect_grid()
    node_id = grid_ctx.node_id if grid_ctx else os.environ.get("AURAGRID_NODE_ID", "standalone-node")
    actual_root = Path(mvenv_root) if mvenv_root else (Path(grid_ctx.mvenv_root) if grid_ctx and grid_ctx.mvenv_root else None)

    manager = MvenvManager(actual_root)
    server = create_api_server(host=host, port=port, manager=manager)

    print(f"[AuraSeed MAS] Service online on node '{node_id}'")
    print(f"[AuraSeed MAS] Listening on http://{host}:{port}")
    print(f"[AuraSeed MAS] Managing mvenv root: {manager.root_path}")
    sys.stdout.flush()

    def handle_exit(signum, frame):
        print("\n[AuraSeed MAS] Received shutdown signal. Closing server...")
        server.shutdown()
        server.server_close()
        sys.exit(0)

    signal.signal(signal.SIGINT, handle_exit)
    signal.signal(signal.SIGTERM, handle_exit)

    try:
        server.serve_forever()
    except Exception as ex:
        print(f"[AuraSeed MAS] Fatal service error: {ex}", file=sys.stderr)
        sys.exit(1)
