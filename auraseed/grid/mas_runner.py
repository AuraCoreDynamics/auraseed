import os
import signal
import sys
from pathlib import Path
from typing import Optional

from auraseed.grid.detector import detect_grid
from auraseed.mvenv.manager import MvenvManager


def run_as_mas(
    host: Optional[str] = None,
    port: Optional[int] = None,
    mvenv_root: Optional[str] = None,
) -> None:
    """
    Executes AuraSeed as an AuraGrid Managed Application Service (MAS).
    """
    from auraseed.api.server import create_api_server

    bind_host = host or os.environ.get("AURASEED_BIND_HOST", "127.0.0.1")
    bind_port = int(port if port is not None else os.environ.get("AURASEED_PORT", "7099"))

    grid_ctx = detect_grid()
    node_id = grid_ctx.node_id if grid_ctx else os.environ.get("AURAGRID_NODE_ID", "standalone-node")
    actual_root = (
        Path(mvenv_root)
        if mvenv_root
        else (Path(grid_ctx.mvenv_root) if grid_ctx and grid_ctx.mvenv_root else None)
    )

    manager = MvenvManager(actual_root)
    server = create_api_server(host=bind_host, port=bind_port, manager=manager)
    actual_port = server.server_port

    print(f"[AuraSeed MAS] Service online on node '{node_id}'")
    print(f"[AuraSeed MAS] Listening on http://{bind_host}:{actual_port}")
    print(f"[AuraSeed MAS] Managing mvenv root: {manager.root_path}")
    sys.stdout.flush()

    def handle_exit(signum, frame):
        print(f"\n[AuraSeed MAS] Received shutdown signal ({signum}). Closing server...")
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
