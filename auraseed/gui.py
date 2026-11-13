"""
AuraSeed Sovereign Runtime & MVenv Manager - Composable Tkinter UI.
Zero external runtime dependencies (Python standard library only).
"""
import logging
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

try:
    import tkinter as tk
    from tkinter import messagebox, simpledialog, ttk
    HAS_TK = True
except ImportError:
    HAS_TK = False

from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest

_LOG = logging.getLogger(__name__)


class MvenvManagerPanel(ttk.Frame):
    """
    Reusable Tkinter panel for inspecting, creating, verifying, deleting,
    and merging AuraSeed Managed Virtual Environments (mvenvs).
    Can be run standalone via launch_gui() or composed into external tools such as AuraSprout.
    """

    def __init__(
        self,
        master: Any = None,
        mvenv_manager: Optional[MvenvManager] = None,
        repoint_callback: Optional[Callable[[List[str], str], List[str]]] = None,
        on_mvenv_changed: Optional[Callable[[], None]] = None,
        status_callback: Optional[Callable[[str, Optional[int]], None]] = None,
    ) -> None:
        if not HAS_TK:
            raise RuntimeError("Tkinter is not available in the current Python environment.")
        super().__init__(master, padding=8)
        self.mvenv_mgr = mvenv_manager or MvenvManager()
        self.repoint_callback = repoint_callback
        self.on_mvenv_changed = on_mvenv_changed
        self.status_callback = status_callback
        self._local_mvenvs: List[Dict[str, Any]] = []

        self._build_ui()
        self.refresh_mvenvs()

    def _safe_after(self, delay: int, callback: Callable[[], None]) -> None:
        try:
            if self.winfo_exists():
                self.after(delay, callback)
        except Exception as exc:
            _LOG.debug("Skipping UI callback after widget disposal: %s", exc)

    def _emit_status(self, text: str, progress: Optional[int] = None) -> None:
        if self.status_callback is not None:
            self.status_callback(text, progress)

    def _notify_changed(self) -> None:
        if self.on_mvenv_changed is not None:
            self.on_mvenv_changed()

    def _build_ui(self) -> None:
        top_bar = ttk.Frame(self)
        top_bar.pack(fill=tk.X, pady=(0, 8))

        ttk.Button(top_bar, text="Refresh", command=self.refresh_mvenvs).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(top_bar, text="Create MVenv...", command=self._create_new_mvenv_dialog).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(top_bar, text="Verify Environment", command=self._verify_selected_mvenv).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(top_bar, text="Delete MVenv", command=self._delete_selected_mvenv).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(
            top_bar,
            text="Merge MVenvs (Reclaim Disk Space)...",
            command=self._open_merge_mvenvs_dialog,
        ).pack(side=tk.RIGHT)

        paned = ttk.PanedWindow(self, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=3)

        cols = ("name", "py_ver", "size", "sovereign", "pkgs")
        self.mvenv_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        self.mvenv_tree.heading("name", text="MVenv Name")
        self.mvenv_tree.heading("py_ver", text="Python")
        self.mvenv_tree.heading("size", text="Disk Size")
        self.mvenv_tree.heading("sovereign", text="Sovereign")
        self.mvenv_tree.heading("pkgs", text="Packages")

        self.mvenv_tree.column("name", width=160)
        self.mvenv_tree.column("py_ver", width=90)
        self.mvenv_tree.column("size", width=80)
        self.mvenv_tree.column("sovereign", width=70)
        self.mvenv_tree.column("pkgs", width=70)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.mvenv_tree.yview)
        self.mvenv_tree.configure(yscrollcommand=tree_scroll.set)
        self.mvenv_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.mvenv_tree.bind("<<TreeviewSelect>>", self._on_mvenv_selected)

        pkg_frame = ttk.LabelFrame(paned, text="Installed Packages", padding=8)
        paned.add(pkg_frame, weight=2)

        self.pkg_listbox = tk.Listbox(pkg_frame, font=("Consolas", 9))
        pkg_scroll = ttk.Scrollbar(pkg_frame, command=self.pkg_listbox.yview)
        self.pkg_listbox.configure(yscrollcommand=pkg_scroll.set)
        self.pkg_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pkg_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def refresh_mvenvs(self) -> None:
        records = self.mvenv_mgr.list_venvs()
        self._local_mvenvs = [r.to_dict() for r in records]
        self.mvenv_tree.delete(*self.mvenv_tree.get_children())
        for r in records:
            size_mb = f"{r.size_bytes / (1024 * 1024):.1f} MB"
            sov_str = "Yes" if r.is_sovereign else "No"
            self.mvenv_tree.insert(
                "",
                tk.END,
                iid=r.name,
                values=(r.name, r.python_version, size_mb, sov_str, len(r.packages)),
            )

    def _on_mvenv_selected(self, event: Any) -> None:
        del event
        sel = self.mvenv_tree.selection()
        if not sel:
            return
        name = sel[0]
        rec = next((r for r in self._local_mvenvs if r["name"] == name), None)
        self.pkg_listbox.delete(0, tk.END)
        if rec:
            for p in sorted(rec.get("packages", [])):
                self.pkg_listbox.insert(tk.END, p)

    def _create_new_mvenv_dialog(self) -> None:
        parent_win = self.winfo_toplevel()
        name = simpledialog.askstring("New MVenv", "Enter name for new managed virtual environment:", parent=parent_win)
        if not name or not name.strip():
            return

        cleaned_name = name.strip()
        self._emit_status(f"Creating sovereign mvenv '{cleaned_name}'...", 25)

        def worker() -> None:
            try:
                req = MvenvCreateRequest(name=cleaned_name, sovereign=True)
                self.mvenv_mgr.create_venv(req)
                self._emit_status(f"MVenv '{cleaned_name}' created successfully.", 100)
                self._safe_after(0, self.refresh_mvenvs)
                self._safe_after(0, self._notify_changed)
            except Exception as e:
                self._emit_status(f"Failed to create mvenv: {e}", 0)
                err_msg = str(e)
                self._safe_after(0, lambda: messagebox.showerror("Creation Error", err_msg, parent=parent_win))

        threading.Thread(target=worker, daemon=True).start()

    def _verify_selected_mvenv(self) -> None:
        sel = self.mvenv_tree.selection()
        if not sel:
            return
        name = sel[0]
        parent_win = self.winfo_toplevel()
        res = self.mvenv_mgr.verify_venv(name)
        if res.get("valid"):
            messagebox.showinfo(
                "Verification Passed",
                f"MVenv '{name}' is healthy!\nPython: {res.get('python_path')}\nVersion: {res.get('python_version')}",
                parent=parent_win,
            )
        else:
            messagebox.showerror(
                "Verification Failed",
                f"MVenv '{name}' failed check:\n{res.get('error')}",
                parent=parent_win,
            )

    def _delete_selected_mvenv(self) -> None:
        sel = self.mvenv_tree.selection()
        if not sel:
            return
        name = sel[0]
        parent_win = self.winfo_toplevel()
        if messagebox.askyesno("Delete MVenv", f"Are you sure you want to delete mvenv '{name}'?", parent=parent_win):
            self.mvenv_mgr.delete_venv(name)
            self.refresh_mvenvs()
            self._notify_changed()
            self._emit_status(f"Deleted mvenv '{name}'.", 100)

    def _open_merge_mvenvs_dialog(self) -> None:
        parent_win = self.winfo_toplevel()
        venvs = self.mvenv_mgr.list_venvs()
        if len(venvs) < 2:
            messagebox.showinfo(
                "Merge MVenvs",
                "At least two managed virtual environments are required to perform a merge.",
                parent=parent_win,
            )
            return

        diag = tk.Toplevel(parent_win)
        diag.title("Merge MVenvs - Consolidate & Save Disk Space")
        diag.geometry("520x460")
        diag.transient(parent_win)
        diag.grab_set()

        f = ttk.Frame(diag, padding=12)
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            f,
            text="Select 2 or more MVenvs to consolidate dependencies into a single shared environment:",
            wraplength=480,
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor=tk.W, pady=(0, 8))

        list_frame = ttk.Frame(f)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        mvenv_listbox = tk.Listbox(list_frame, selectmode=tk.MULTIPLE, font=("Segoe UI", 9), height=7)
        scroll = ttk.Scrollbar(list_frame, command=mvenv_listbox.yview)
        mvenv_listbox.configure(yscrollcommand=scroll.set)
        mvenv_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for v in venvs:
            size_mb = f"{v.size_bytes / (1024 * 1024):.1f} MB"
            mvenv_listbox.insert(tk.END, f"{v.name}  ({size_mb}, {len(v.packages)} pkgs)")

        name_frame = ttk.Frame(f)
        name_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(name_frame, text="Target Merged MVenv Name:").pack(side=tk.LEFT, padx=(0, 8))
        target_name_var = tk.StringVar(value="shared-apps")
        ttk.Entry(name_frame, textvariable=target_name_var, width=22).pack(side=tk.LEFT)

        delete_sources_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(
            f,
            text="Delete source MVenvs after merge to reclaim disk space",
            variable=delete_sources_var,
        ).pack(anchor=tk.W, pady=2)

        relink_apps_var = tk.BooleanVar(value=self.repoint_callback is not None)
        chk_relink = ttk.Checkbutton(
            f,
            text="Notify host app callback to re-link applications to merged MVenv",
            variable=relink_apps_var,
        )
        if self.repoint_callback is None:
            chk_relink.configure(state="disabled")
        chk_relink.pack(anchor=tk.W, pady=2)

        def execute_merge() -> None:
            indices = mvenv_listbox.curselection()
            if len(indices) < 2:
                messagebox.showerror("Selection Error", "Please select at least 2 source environments to merge.", parent=diag)
                return

            sources = [venvs[i].name for i in indices]
            target_name = target_name_var.get().strip()
            if not target_name:
                messagebox.showerror("Input Error", "Please specify a target MVenv name.", parent=diag)
                return

            delete_sources = delete_sources_var.get()
            relink_apps = relink_apps_var.get() and self.repoint_callback is not None

            diag.destroy()
            self._emit_status(f"Merging {len(sources)} MVenvs into '{target_name}'...", 30)

            def worker() -> None:
                try:
                    res = self.mvenv_mgr.merge_venvs(
                        source_names=sources,
                        target_name=target_name,
                        delete_sources=delete_sources,
                        repoint_apps=relink_apps,
                        repoint_callback=self.repoint_callback,
                    )
                    saved_mb = f"{res.get('reclaimed_bytes', 0) / (1024 * 1024):.1f} MB"
                    msg = (
                        f"Merge complete!\n\n"
                        f"Target MVenv: {target_name}\n"
                        f"Merged Sources: {', '.join(res.get('merged_sources', []))}\n"
                        f"Packages Installed: {res.get('packages_installed', 0)}\n"
                        f"Repointed Apps: {', '.join(res.get('repointed_apps', [])) or 'None'}\n"
                        f"Reclaimed Disk Space: {saved_mb}"
                    )
                    self._emit_status(f"Merge complete. Saved {saved_mb} of disk space!", 100)
                    self._safe_after(0, self.refresh_mvenvs)
                    self._safe_after(0, self._notify_changed)
                    self._safe_after(0, lambda: messagebox.showinfo("Merge & Reclaim Success", msg, parent=parent_win))
                except Exception as e:
                    self._emit_status(f"Merge failed: {e}", 0)
                    err_msg = str(e)
                    self._safe_after(0, lambda: messagebox.showerror("Merge Error", err_msg, parent=parent_win))

            threading.Thread(target=worker, daemon=True).start()

        btn_row = ttk.Frame(f)
        btn_row.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(btn_row, text="Merge & Reclaim Space Now", command=execute_merge).pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="Cancel", command=diag.destroy).pack(side=tk.RIGHT, padx=6)


class AuraSeedMvenvGUI:
    """
    Standalone Tkinter window wrapping MvenvManagerPanel.
    """

    def __init__(
        self,
        root: Optional[Any] = None,
        mvenv_manager: Optional[MvenvManager] = None,
        repoint_callback: Optional[Callable[[List[str], str], List[str]]] = None,
    ) -> None:
        if not HAS_TK:
            raise RuntimeError("Tkinter is not available in the current Python environment.")

        self.root = root or tk.Tk()
        self.root.title("AuraSeed - Sovereign MVenv Manager")
        self.root.geometry("920x600")
        self.root.minsize(720, 460)
        try:
            ico_path = Path(__file__).resolve().parent / "assets" / "auraseed.ico"
            if ico_path.exists():
                self.root.iconbitmap(str(ico_path))
        except Exception as exc:
            _LOG.debug("Window iconbitmap skipped: %s", exc)

        self.style = ttk.Style(self.root)
        try:
            if "vista" in self.style.theme_names():
                self.style.theme_use("vista")
            elif "clam" in self.style.theme_names():
                self.style.theme_use("clam")
        except Exception as exc:
            _LOG.debug("Using default ttk theme: %s", exc)

        header = ttk.Frame(self.root, padding=(16, 12, 16, 8))
        header.pack(fill=tk.X)

        ttk.Label(header, text="AuraSeed", font=("Segoe UI", 16, "bold")).pack(side=tk.LEFT)
        ttk.Label(header, text="  Sovereign Runtime & MVenv Manager", font=("Segoe UI", 10)).pack(
            side=tk.LEFT, pady=(4, 0)
        )

        status_bar = ttk.Frame(self.root, relief=tk.SUNKEN, padding=(8, 4))
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self.status_var = tk.StringVar(value="Ready")
        ttk.Label(status_bar, textvariable=self.status_var, font=("Segoe UI", 9)).pack(side=tk.LEFT)
        self.progress_bar = ttk.Progressbar(status_bar, orient=tk.HORIZONTAL, mode="determinate", length=180)
        self.progress_bar.pack(side=tk.RIGHT, padx=4)

        self.panel = MvenvManagerPanel(
            self.root,
            mvenv_manager=mvenv_manager,
            repoint_callback=repoint_callback,
            status_callback=self.set_status,
        )
        self.panel.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

    def set_status(self, text: str, progress: Optional[int] = None) -> None:
        def _update() -> None:
            self.status_var.set(text)
            if progress is not None:
                self.progress_bar["value"] = progress
            elif text == "Ready":
                self.progress_bar["value"] = 0

        try:
            if self.root and self.root.winfo_exists():
                self.root.after(0, _update)
        except Exception as exc:
            _LOG.debug("Skipping status update on destroyed window: %s", exc)


def launch_mvenv_gui(mvenv_manager: Optional[MvenvManager] = None) -> int:
    if not HAS_TK:
        print("[AuraSeed GUI] Error: Tkinter is not available in this Python environment.", file=sys.stderr)
        return 1
    root = tk.Tk()
    AuraSeedMvenvGUI(root=root, mvenv_manager=mvenv_manager)
    root.mainloop()
    return 0


def launch_gui() -> int:
    return launch_mvenv_gui()
