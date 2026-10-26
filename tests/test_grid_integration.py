import os
import sys
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

from auraseed.grid.detector import detect_grid
from auraseed.grid.peer_transfer import P2PVenvClient
from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest
from auraseed.api.server import create_api_server


class TestGridIntegration(unittest.TestCase):
    def test_detect_grid_from_env(self):
        old_node = os.environ.get("AURAGRID_NODE_ID")
        old_port = os.environ.get("AURAGRID_MANAGEMENT_PORT")

        try:
            os.environ["AURAGRID_NODE_ID"] = "test-node-99"
            os.environ["AURAGRID_MANAGEMENT_PORT"] = "7077"

            ctx = detect_grid()
            self.assertIsNotNone(ctx)
            self.assertTrue(ctx.is_on_grid)
            self.assertEqual(ctx.node_id, "test-node-99")
            self.assertEqual(ctx.management_port, 7077)
        finally:
            if old_node is not None:
                os.environ["AURAGRID_NODE_ID"] = old_node
            else:
                os.environ.pop("AURAGRID_NODE_ID", None)

            if old_port is not None:
                os.environ["AURAGRID_MANAGEMENT_PORT"] = old_port
            else:
                os.environ.pop("AURAGRID_MANAGEMENT_PORT", None)

    def test_p2p_bundle_transfer(self):

        # Set up peer node with an mvenv
        peer_dir = tempfile.mkdtemp(prefix="auraseed_peer_node_")
        local_dir = tempfile.mkdtemp(prefix="auraseed_local_node_")
        try:
            peer_mgr = MvenvManager(Path(peer_dir))
            # Create an mvenv on the peer node
            peer_mgr.create_venv(MvenvCreateRequest(
                name="shared-data-science",
                base_python=sys.executable,
                sovereign=False,
                force=True
            ))

            # Run peer server on dynamic port
            peer_server = create_api_server(host="127.0.0.1", port=0, manager=peer_mgr)
            peer_port = peer_server.server_port
            thread = threading.Thread(target=peer_server.serve_forever, daemon=True)
            thread.start()

            try:
                # Local node has no local install/compiler, pulls bundle from peer node
                local_mgr = MvenvManager(Path(local_dir))
                client = P2PVenvClient(local_mgr)

                peer_url = f"http://127.0.0.1:{peer_port}"
                rec = client.fetch_bundle_from_peer(peer_url, "shared-data-science")

                self.assertEqual(rec.name, "shared-data-science")
                self.assertTrue(Path(rec.path).exists())
                self.assertTrue(Path(rec.python_path).exists())

                # Local catalog now lists the transferred environment
                local_venvs = local_mgr.list_venvs()
                self.assertEqual(len(local_venvs), 1)
                self.assertEqual(local_venvs[0].name, "shared-data-science")
            finally:
                peer_server.shutdown()
                peer_server.server_close()
        finally:
            shutil.rmtree(peer_dir, ignore_errors=True)
            shutil.rmtree(local_dir, ignore_errors=True)


if __name__ == "__main__":
    unittest.main()
