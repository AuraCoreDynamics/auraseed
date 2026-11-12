"""
Headless / UI test for AuraSeed Sovereign MVenv Manager GUI and composable MvenvManagerPanel.
"""
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

try:
    import tkinter as tk
    HAS_TK = True
except ImportError:
    HAS_TK = False

from auraseed.gui import AuraSeedMvenvGUI, MvenvManagerPanel
from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest


@unittest.skipUnless(HAS_TK, "Tkinter not available")
class TestAuraSeedGuiHub(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="auraseed_gui_test_")
        self.mvenv_dir = Path(self.test_dir) / "mvenvs"
        self.mvenv_dir.mkdir(parents=True)
        self.mvenv_manager = MvenvManager(self.mvenv_dir)

        self.root = tk.Tk()
        self.root.withdraw()

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception as exc:
            del exc
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_mvenv_gui_and_composable_panel(self):
        repointed_calls = []

        def fake_repoint(sources, target):
            repointed_calls.append((list(sources), target))
            return ["sample-app"]

        gui = AuraSeedMvenvGUI(
            root=self.root,
            mvenv_manager=self.mvenv_manager,
            repoint_callback=fake_repoint,
        )
        self.assertIsInstance(gui.panel, MvenvManagerPanel)

        gui.set_status("Test status message", 50)
        self.root.update()
        self.assertEqual(gui.status_var.get(), "Test status message")
        self.assertEqual(gui.progress_bar["value"], 50)

        # Create a small non-sovereign mvenv and verify it renders in the composable panel
        self.mvenv_manager.create_venv(
            MvenvCreateRequest(
                name="gui-test-env",
                base_python=sys.executable,
                sovereign=False,
                force=True,
            )
        )
        gui.panel.refresh_mvenvs()
        self.root.update()
        children = gui.panel.mvenv_tree.get_children()
        self.assertIn("gui-test-env", children)

        # Verify panel can be embedded inside an arbitrary host frame (e.g. AuraSprout)
        host_frame = tk.Frame(self.root)
        embedded_panel = MvenvManagerPanel(
            host_frame,
            mvenv_manager=self.mvenv_manager,
            repoint_callback=fake_repoint,
        )
        embedded_panel.pack(fill=tk.BOTH, expand=True)
        self.root.update()
        self.assertIn("gui-test-env", embedded_panel.mvenv_tree.get_children())


if __name__ == "__main__":
    unittest.main()
