"""
Headless / UI test for AuraSeed App & Environment Hub GUI.
"""
import unittest
import tempfile
import shutil
from pathlib import Path

try:
    import tkinter as tk
    HAS_TK = True
except ImportError:
    HAS_TK = False

from auraseed.gui import AuraSeedAppHubGUI
from auraseed.catalog.sources import CatalogRegistry
from auraseed.catalog.local import LocalAppManager
from auraseed.mvenv.manager import MvenvManager


@unittest.skipUnless(HAS_TK, "Tkinter not available")
class TestAuraSeedGuiHub(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="auraseed_gui_test_")
        self.root_p = Path(self.test_dir)
        self.apps_dir = self.root_p / "apps"
        self.apps_dir.mkdir(parents=True)

        self.root = tk.Tk()
        self.root.withdraw()  # keep window hidden during unit tests

    def tearDown(self):
        try:
            self.root.destroy()
        except Exception:
            pass
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_gui_instantiation_and_tabs(self):
        gui = AuraSeedAppHubGUI(root=self.root)

        # Verify tabs exist
        tabs = gui.notebook.tabs()
        self.assertEqual(len(tabs), 3)

        # Verify status updates
        gui.set_status("Test status message", 50)
        self.root.update()
        self.assertEqual(gui.status_var.get(), "Test status message")
        self.assertEqual(gui.progress_bar["value"], 50)

        # Verify catalog tree and filter
        gui._active_catalog_apps = [
            {"name": "alpha", "display_name": "Alpha Service", "version": "1.0.0", "description": "Alpha tool"},
            {"name": "beta", "display_name": "Beta Pipeline", "version": "2.0.0", "description": "Beta worker"}
        ]
        gui.catalog_search_var.set("alpha")
        children = gui.catalog_tree.get_children()
        self.assertIn("alpha", children)
        self.assertNotIn("beta", children)

        # Clear filter
        gui.catalog_search_var.set("")
        children_all = gui.catalog_tree.get_children()
        self.assertIn("alpha", children_all)
        self.assertIn("beta", children_all)


if __name__ == "__main__":
    unittest.main()
