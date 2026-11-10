"""
AuraSeed App & Environment Hub - Tkinter GUI.
Manages local client-side applications, attached catalogs, and mvenvs (including merging).
Zero external runtime dependencies (Python standard library only).
"""
import os
import sys
import json
import shutil
import platform
import threading
import subprocess
from pathlib import Path
from typing import Optional, Dict, Any, List

try:
    import tkinter as tk
    from tkinter import ttk, messagebox, filedialog, simpledialog
    HAS_TK = True
except ImportError:
    HAS_TK = False

from auraseed.catalog.server import ServerAppCatalog
from auraseed.catalog.sources import CatalogRegistry
from auraseed.catalog.local import LocalAppManager
from auraseed.client import AuraSeedClient
from auraseed.mvenv.manager import MvenvManager
from auraseed.mvenv.models import MvenvCreateRequest


class AuraSeedAppHubGUI:
    """
    Unified client-side desktop management GUI for AuraSeed applications,
    multiple attached catalogs, and virtual environments.
    """

    def __init__(self, root: Optional[Any] = None):
        if not HAS_TK:
            raise RuntimeError("Tkinter is not available in the current Python environment.")

        self.root = root or tk.Tk()
        self.root.title("AuraSeed - App & Environment Hub")
        self.root.geometry("960x640")
        self.root.minsize(800, 500)

        # Apply native styling
        self.style = ttk.Style(self.root)
        try:
            if "vista" in self.style.theme_names():
                self.style.theme_use("vista")
            elif "clam" in self.style.theme_names():
                self.style.theme_use("clam")
        except Exception:
            pass

        # Subsystems
        self.catalog_registry = CatalogRegistry()
        self.local_app_mgr = LocalAppManager()
        self.mvenv_mgr = MvenvManager()

        self._active_catalog_apps: List[Dict[str, Any]] = []
        self._installed_apps: List[Dict[str, Any]] = []
        self._local_mvenvs: List[Dict[str, Any]] = []

        self._build_ui()
        self.refresh_all()

    def _build_ui(self):
        # 1. Main Header
        header = ttk.Frame(self.root, padding=(16, 12, 16, 8))
        header.pack(fill=tk.X)

        title_lbl = ttk.Label(header, text="AuraSeed Hub", font=("Segoe UI", 16, "bold"))
        title_lbl.pack(side=tk.LEFT)

        subtitle_lbl = ttk.Label(header, text="  Application Catalog & Sovereign Runtime Manager", font=("Segoe UI", 10))
        subtitle_lbl.pack(side=tk.LEFT, pady=(4, 0))

        # 2. Notebook (Tabs)
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill=tk.BOTH, expand=True, padx=12, pady=(0, 8))

        # Tab 1: Catalog Browser
        self.tab_catalog = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_catalog, text="  Catalog Store  ")
        self._build_catalog_tab()

        # Tab 2: Local Applications
        self.tab_apps = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_apps, text="  Installed Apps  ")
        self._build_installed_apps_tab()

        # Tab 3: MVenv Manager & Space Reclaimer
        self.tab_mvenvs = ttk.Frame(self.notebook, padding=8)
        self.notebook.add(self.tab_mvenvs, text="  MVenvs & Disk Saver  ")
        self._build_mvenv_tab()

        # 3. Status Bar
        status_bar = ttk.Frame(self.root, relief=tk.SUNKEN, padding=(8, 4))
        status_bar.pack(fill=tk.X, side=tk.BOTTOM)

        self.status_var = tk.StringVar(value="Ready")
        self.status_lbl = ttk.Label(status_bar, textvariable=self.status_var, font=("Segoe UI", 9))
        self.status_lbl.pack(side=tk.LEFT)

        self.progress_bar = ttk.Progressbar(status_bar, orient=tk.HORIZONTAL, mode="determinate", length=180)
        self.progress_bar.pack(side=tk.RIGHT, padx=4)

    def safe_after(self, delay: int, callback):
        try:
            if self.root and self.root.winfo_exists():
                self.root.after(delay, callback)
        except Exception:
            pass

    def set_status(self, text: str, progress: Optional[int] = None):
        def _update():
            self.status_var.set(text)
            if progress is not None:
                self.progress_bar["value"] = progress
            elif text == "Ready":
                self.progress_bar["value"] = 0
        self.safe_after(0, _update)

    # -------------------------------------------------------------------------
    # TAB 1: Catalog Browser
    # -------------------------------------------------------------------------
    def _build_catalog_tab(self):
        top_bar = ttk.Frame(self.tab_catalog)
        top_bar.pack(fill=tk.X, pady=(0, 8))

        ttk.Label(top_bar, text="Attached Catalog:").pack(side=tk.LEFT, padx=(0, 6))

        self.catalog_combo_var = tk.StringVar()
        self.catalog_combo = ttk.Combobox(top_bar, textvariable=self.catalog_combo_var, state="readonly", width=36)
        self.catalog_combo.pack(side=tk.LEFT, padx=(0, 6))
        self.catalog_combo.bind("<<ComboboxSelected>>", lambda e: self.refresh_catalog_apps())

        manage_btn = ttk.Button(top_bar, text="Manage Catalogs...", command=self._open_manage_catalogs_dialog)
        manage_btn.pack(side=tk.LEFT, padx=(0, 8))

        refresh_btn = ttk.Button(top_bar, text="Refresh", command=self.refresh_catalog_apps)
        refresh_btn.pack(side=tk.LEFT, padx=(0, 8))

        ttk.Label(top_bar, text="Search:").pack(side=tk.LEFT, padx=(12, 4))
        self.catalog_search_var = tk.StringVar()
        self.catalog_search_entry = ttk.Entry(top_bar, textvariable=self.catalog_search_var, width=16)
        self.catalog_search_entry.pack(side=tk.LEFT, padx=(0, 4))
        self.catalog_search_var.trace_add("write", lambda *args: self._filter_catalog_tree())

        deploy_btn = ttk.Button(top_bar, text="Deploy App to Catalog...", command=self._deploy_app_to_active_catalog)
        deploy_btn.pack(side=tk.RIGHT)

        # Paned split
        paned = ttk.PanedWindow(self.tab_catalog, orient=tk.HORIZONTAL)
        paned.pack(fill=tk.BOTH, expand=True)

        # Treeview list
        tree_frame = ttk.Frame(paned)
        paned.add(tree_frame, weight=3)

        cols = ("name", "version", "desc", "size")
        self.catalog_tree = ttk.Treeview(tree_frame, columns=cols, show="headings", selectmode="browse")
        self.catalog_tree.heading("name", text="Application Name")
        self.catalog_tree.heading("version", text="Version")
        self.catalog_tree.heading("desc", text="Description")
        self.catalog_tree.heading("size", text="Size")
        self.catalog_tree.column("name", width=140)
        self.catalog_tree.column("version", width=70)
        self.catalog_tree.column("desc", width=220)
        self.catalog_tree.column("size", width=70)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.catalog_tree.yview)
        self.catalog_tree.configure(yscrollcommand=tree_scroll.set)
        self.catalog_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.catalog_tree.bind("<<TreeviewSelect>>", self._on_catalog_item_selected)

        # Details & Install side panel
        self.catalog_detail_frame = ttk.LabelFrame(paned, text="Application Details", padding=12)
        paned.add(self.catalog_detail_frame, weight=2)

        self.cat_name_lbl = ttk.Label(self.catalog_detail_frame, text="Select an application", font=("Segoe UI", 12, "bold"))
        self.cat_name_lbl.pack(anchor=tk.W, pady=(0, 4))

        self.cat_meta_lbl = ttk.Label(self.catalog_detail_frame, text="", font=("Segoe UI", 9))
        self.cat_meta_lbl.pack(anchor=tk.W, pady=(0, 8))

        self.cat_desc_text = tk.Text(self.catalog_detail_frame, wrap=tk.WORD, height=6, font=("Segoe UI", 9))
        self.cat_desc_text.pack(fill=tk.X, pady=(0, 12))
        self.cat_desc_text.configure(state="disabled")

        # Install options
        opts_frame = ttk.LabelFrame(self.catalog_detail_frame, text="Installation Options", padding=8)
        opts_frame.pack(fill=tk.X, pady=(0, 12))

        self.install_mode_var = tk.StringVar(value="shared")
        r_shared = ttk.Radiobutton(opts_frame, text="Shared MVenv (Consolidate & Save Disk)", value="shared", variable=self.install_mode_var)
        r_shared.pack(anchor=tk.W, pady=2)

        shared_name_frame = ttk.Frame(opts_frame)
        shared_name_frame.pack(fill=tk.X, padx=(20, 0), pady=(0, 4))
        ttk.Label(shared_name_frame, text="Target MVenv:").pack(side=tk.LEFT)
        self.shared_mvenv_entry = ttk.Entry(shared_name_frame, width=16)
        self.shared_mvenv_entry.insert(0, "shared-apps")
        self.shared_mvenv_entry.pack(side=tk.LEFT, padx=4)

        r_sovereign = ttk.Radiobutton(opts_frame, text="Isolated Sovereign MVenv (Full Autonomy)", value="sovereign", variable=self.install_mode_var)
        r_sovereign.pack(anchor=tk.W, pady=2)

        self.install_btn = ttk.Button(
            self.catalog_detail_frame,
            text="Install Application Now",
            command=self._install_selected_catalog_app,
            state="disabled"
        )
        self.install_btn.pack(fill=tk.X, pady=(8, 0))

    def _update_catalog_combo(self):
        catalogs = self.catalog_registry.list_catalogs()
        items = [f"{c['label']} ({c['url']})" for c in catalogs]
        self.catalog_combo["values"] = items
        default_url = self.catalog_registry.get_default_catalog()

        for i, c in enumerate(catalogs):
            if c["url"] == default_url:
                self.catalog_combo.current(i)
                return

        if items:
            self.catalog_combo.current(0)

    def _get_active_catalog_url(self) -> str:
        val = self.catalog_combo_var.get()
        if "(" in val and val.endswith(")"):
            return val.split("(")[-1].rstrip(")")
        return val or self.catalog_registry.get_default_catalog()

    def refresh_catalog_apps(self):
        url = self._get_active_catalog_url()
        self.set_status(f"Fetching applications from {url}...", 20)

        def worker():
            try:
                client = AuraSeedClient(base_url=url, timeout=5)
                apps = client.list_apps()
                self._active_catalog_apps = apps
                self.safe_after(0, lambda: self._populate_catalog_tree(apps))
                self.set_status(f"Loaded {len(apps)} applications from {url}.", 100)
                self.safe_after(2000, lambda: self.set_status("Ready"))
            except Exception as e:
                self._active_catalog_apps = []
                self.safe_after(0, lambda: self._populate_catalog_tree([]))
                self.set_status(f"Could not connect to {url}: {e}", 0)

        threading.Thread(target=worker, daemon=True).start()

    def _populate_catalog_tree(self, apps: List[Dict[str, Any]]):
        self.catalog_tree.delete(*self.catalog_tree.get_children())
        for a in apps:
            size_mb = f"{a.get('size_bytes', 0) / (1024*1024):.1f} MB"
            self.catalog_tree.insert(
                "",
                tk.END,
                iid=a["name"],
                values=(a.get("display_name") or a["name"], a.get("version", "1.0.0"), a.get("description", ""), size_mb)
            )

    def _filter_catalog_tree(self):
        query = self.catalog_search_var.get().lower()
        filtered = [
            a for a in self._active_catalog_apps
            if query in a["name"].lower() or query in a.get("display_name", "").lower() or query in a.get("description", "").lower()
        ]
        self._populate_catalog_tree(filtered)

    def _on_catalog_item_selected(self, event):
        sel = self.catalog_tree.selection()
        if not sel:
            self.install_btn.configure(state="disabled")
            return

        name = sel[0]
        app = next((a for a in self._active_catalog_apps if a["name"] == name), None)
        if not app:
            return

        self.cat_name_lbl.configure(text=app.get("display_name") or app["name"])
        size_mb = f"{app.get('size_bytes', 0) / (1024*1024):.1f} MB"
        self.cat_meta_lbl.configure(text=f"Version: {app.get('version', '1.0.0')}  |  Size: {size_mb}  |  Port: {app.get('default_port', 8000)}")

        self.cat_desc_text.configure(state="normal")
        self.cat_desc_text.delete("1.0", tk.END)
        self.cat_desc_text.insert(tk.END, app.get("description") or "No description provided.")
        self.cat_desc_text.configure(state="disabled")

        self.install_btn.configure(state="normal")

    def _install_selected_catalog_app(self):
        sel = self.catalog_tree.selection()
        if not sel:
            return
        app_name = sel[0]
        app_meta = next((a for a in self._active_catalog_apps if a["name"] == app_name), None)
        if not app_meta:
            return

        is_shared = self.install_mode_var.get() == "shared"
        target_mvenv = self.shared_mvenv_entry.get().strip() if is_shared else None
        catalog_url = self._get_active_catalog_url()

        self.install_btn.configure(state="disabled")
        self.set_status(f"Downloading {app_name} package from catalog...", 15)

        def worker():
            try:
                client = AuraSeedClient(base_url=catalog_url)
                temp_down = Path(tempfile.gettempdir()) / f"{app_name}_install_bundle.zip"
                client.download_app(app_name, temp_down)

                self.set_status(f"Installing {app_name}...", 50)
                self.local_app_mgr.install_from_bundle(
                    bundle_path=temp_down,
                    mvenv_name=target_mvenv,
                    use_shared_mvenv=is_shared,
                    progress_callback=lambda pct, msg: self.set_status(msg, pct)
                )

                if temp_down.exists():
                    try: temp_down.unlink()
                    except OSError: pass

                self.set_status(f"Installation of {app_name} completed successfully!", 100)
                self.safe_after(0, self.refresh_installed_apps)
                self.safe_after(0, self.refresh_mvenvs)
                self.safe_after(0, lambda: messagebox.showinfo("Install Complete", f"Successfully installed {app_name}!"))
            except Exception as e:
                self.set_status(f"Installation failed: {e}", 0)
                self.safe_after(0, lambda: messagebox.showerror("Installation Error", str(e)))
            finally:
                self.safe_after(0, lambda: self.install_btn.configure(state="normal"))

        threading.Thread(target=worker, daemon=True).start()

    def _deploy_app_to_active_catalog(self):
        target_url = self._get_active_catalog_url()
        path = filedialog.askdirectory(title="Select Application Source Directory (containing app.json)")
        if not path:
            return

        app_dir = Path(path)
        manifest_file = app_dir / "app.json"
        if not manifest_file.exists():
            messagebox.showerror("Invalid Directory", "The selected folder must contain an app.json manifest file.")
            return

        self.set_status(f"Packaging and deploying to {target_url}...", 30)

        def worker():
            try:
                client = AuraSeedClient(base_url=target_url)
                res = client.deploy_app(app_dir)
                self.set_status(f"Successfully deployed {res.get('name')} to catalog!", 100)
                self.safe_after(0, self.refresh_catalog_apps)
                self.safe_after(0, lambda: messagebox.showinfo("Deploy Success", f"Application '{res.get('name')}' version {res.get('version')} deployed!"))
            except Exception as e:
                self.set_status(f"Deployment failed: {e}", 0)
                self.safe_after(0, lambda: messagebox.showerror("Deployment Error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _open_manage_catalogs_dialog(self):
        diag = tk.Toplevel(self.root)
        diag.title("Manage Attached Catalogs")
        diag.geometry("520x340")
        diag.transient(self.root)
        diag.grab_set()

        frame = ttk.Frame(diag, padding=12)
        frame.pack(fill=tk.BOTH, expand=True)

        list_frame = ttk.Frame(frame)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        cat_listbox = tk.Listbox(list_frame, font=("Segoe UI", 9))
        cat_scroll = ttk.Scrollbar(list_frame, command=cat_listbox.yview)
        cat_listbox.configure(yscrollcommand=cat_scroll.set)
        cat_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        cat_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        def reload_cats():
            cat_listbox.delete(0, tk.END)
            for c in self.catalog_registry.list_catalogs():
                def_mark = " [Default]" if c.get("is_default") else ""
                cat_listbox.insert(tk.END, f"{c.get('label', '')} - {c['url']}{def_mark}")

        reload_cats()

        btn_row = ttk.Frame(frame)
        btn_row.pack(fill=tk.X)

        def add_cat():
            url = simpledialog.askstring("Add Catalog", "Enter AuraSeed Server URL (e.g. http://10.0.0.5:7099):", parent=diag)
            if url and url.strip():
                label = simpledialog.askstring("Catalog Label", "Enter friendly label (optional):", parent=diag)
                self.catalog_registry.add_catalog(url.strip(), label=label or url.strip())
                reload_cats()
                self._update_catalog_combo()

        def remove_cat():
            sel = cat_listbox.curselection()
            if not sel:
                return
            line = cat_listbox.get(sel[0])
            url_part = line.split(" - ")[-1].replace(" [Default]", "").strip()
            self.catalog_registry.remove_catalog(url_part)
            reload_cats()
            self._update_catalog_combo()

        ttk.Button(btn_row, text="Add Catalog...", command=add_cat).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="Remove Selected", command=remove_cat).pack(side=tk.LEFT, padx=(0, 6))
        ttk.Button(btn_row, text="Close", command=diag.destroy).pack(side=tk.RIGHT)

    # -------------------------------------------------------------------------
    # TAB 2: Installed Apps
    # -------------------------------------------------------------------------
    def _build_installed_apps_tab(self):
        top_bar = ttk.Frame(self.tab_apps)
        top_bar.pack(fill=tk.X, pady=(0, 8))

        refresh_btn = ttk.Button(top_bar, text="Refresh", command=self.refresh_installed_apps)
        refresh_btn.pack(side=tk.LEFT, padx=(0, 8))

        launch_btn = ttk.Button(top_bar, text="Launch Application", style="Accent.TButton", command=self._launch_selected_app)
        launch_btn.pack(side=tk.LEFT, padx=(0, 8))

        folder_btn = ttk.Button(top_bar, text="Open Folder", command=self._open_app_folder)
        folder_btn.pack(side=tk.LEFT, padx=(0, 8))

        relink_btn = ttk.Button(top_bar, text="Switch / Relink MVenv...", command=self._relink_selected_app)
        relink_btn.pack(side=tk.LEFT, padx=(0, 8))

        uninstall_btn = ttk.Button(top_bar, text="Uninstall App", command=self._uninstall_selected_app)
        uninstall_btn.pack(side=tk.RIGHT)

        cols = ("name", "version", "mvenv", "port", "path")
        self.installed_tree = ttk.Treeview(self.tab_apps, columns=cols, show="headings", selectmode="browse")
        self.installed_tree.heading("name", text="Application Name")
        self.installed_tree.heading("version", text="Version")
        self.installed_tree.heading("mvenv", text="Bound MVenv")
        self.installed_tree.heading("port", text="Port")
        self.installed_tree.heading("path", text="Installation Location")

        self.installed_tree.column("name", width=160)
        self.installed_tree.column("version", width=70)
        self.installed_tree.column("mvenv", width=140)
        self.installed_tree.column("port", width=60)
        self.installed_tree.column("path", width=340)

        tree_scroll = ttk.Scrollbar(self.tab_apps, orient=tk.VERTICAL, command=self.installed_tree.yview)
        self.installed_tree.configure(yscrollcommand=tree_scroll.set)
        self.installed_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def refresh_installed_apps(self):
        apps = self.local_app_mgr.list_installed_apps()
        self._installed_apps = apps
        self.installed_tree.delete(*self.installed_tree.get_children())
        for a in apps:
            self.installed_tree.insert(
                "",
                tk.END,
                iid=a["name"],
                values=(a.get("display_name") or a["name"], a.get("version", "1.0.0"), a.get("mvenv_name", "private"), a.get("port", ""), a.get("install_dir", ""))
            )

    def _launch_selected_app(self):
        sel = self.installed_tree.selection()
        if not sel:
            messagebox.showinfo("Select App", "Please select an installed application to launch.")
            return
        name = sel[0]
        try:
            self.local_app_mgr.launch_app(name)
            self.set_status(f"Launched application '{name}'", 100)
            self.safe_after(2000, lambda: self.set_status("Ready"))
        except Exception as e:
            messagebox.showerror("Launch Error", f"Could not launch application '{name}': {e}")

    def _open_app_folder(self):
        sel = self.installed_tree.selection()
        if not sel:
            return
        app = self.local_app_mgr.get_installed_app(sel[0])
        if not app:
            return
        p = Path(app["install_dir"])
        if p.exists():
            if platform.system().lower() == "windows":
                os.startfile(str(p))
            elif platform.system().lower() == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])

    def _relink_selected_app(self):
        sel = self.installed_tree.selection()
        if not sel:
            return
        app_name = sel[0]
        venvs = self.mvenv_mgr.list_venvs()
        if not venvs:
            messagebox.showinfo("No MVenvs", "No cataloged mvenvs available to relink to.")
            return

        diag = tk.Toplevel(self.root)
        diag.title(f"Relink MVenv for {app_name}")
        diag.geometry("400x260")
        diag.transient(self.root)
        diag.grab_set()

        f = ttk.Frame(diag, padding=12)
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(f, text=f"Choose target mvenv for '{app_name}':").pack(anchor=tk.W, pady=(0, 6))

        mvenv_combo = ttk.Combobox(f, values=[v.name for v in venvs], state="readonly")
        mvenv_combo.current(0)
        mvenv_combo.pack(fill=tk.X, pady=(0, 16))

        def execute_relink():
            target_venv = mvenv_combo.get()
            try:
                self.local_app_mgr.relink_app_mvenv(app_name, target_venv, mvenv_manager=self.mvenv_mgr)
                diag.destroy()
                self.refresh_installed_apps()
                messagebox.showinfo("Relink Complete", f"Repointed '{app_name}' to mvenv '{target_venv}'.")
            except Exception as e:
                messagebox.showerror("Relink Error", str(e))

        ttk.Button(f, text="Apply Relink", command=execute_relink).pack(side=tk.RIGHT)
        ttk.Button(f, text="Cancel", command=diag.destroy).pack(side=tk.RIGHT, padx=6)

    def _uninstall_selected_app(self):
        sel = self.installed_tree.selection()
        if not sel:
            return
        name = sel[0]
        if messagebox.askyesno("Confirm Uninstall", f"Are you sure you want to uninstall application '{name}'?"):
            self.local_app_mgr.uninstall_app(name)
            self.refresh_installed_apps()
            self.set_status(f"Uninstalled '{name}'.", 100)

    # -------------------------------------------------------------------------
    # TAB 3: MVenvs & Disk Optimization
    # -------------------------------------------------------------------------
    def _build_mvenv_tab(self):
        top_bar = ttk.Frame(self.tab_mvenvs)
        top_bar.pack(fill=tk.X, pady=(0, 8))

        refresh_btn = ttk.Button(top_bar, text="Refresh", command=self.refresh_mvenvs)
        refresh_btn.pack(side=tk.LEFT, padx=(0, 8))

        new_btn = ttk.Button(top_bar, text="Create MVenv...", command=self._create_new_mvenv_dialog)
        new_btn.pack(side=tk.LEFT, padx=(0, 8))

        verify_btn = ttk.Button(top_bar, text="Verify Environment", command=self._verify_selected_mvenv)
        verify_btn.pack(side=tk.LEFT, padx=(0, 8))

        delete_btn = ttk.Button(top_bar, text="Delete MVenv", command=self._delete_selected_mvenv)
        delete_btn.pack(side=tk.LEFT, padx=(0, 8))

        merge_btn = ttk.Button(top_bar, text="Merge MVenvs (Reclaim Disk Space)...", command=self._open_merge_mvenvs_dialog)
        merge_btn.pack(side=tk.RIGHT)

        # Paned layout
        paned = ttk.PanedWindow(self.tab_mvenvs, orient=tk.HORIZONTAL)
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

        self.mvenv_tree.column("name", width=140)
        self.mvenv_tree.column("py_ver", width=90)
        self.mvenv_tree.column("size", width=80)
        self.mvenv_tree.column("sovereign", width=70)
        self.mvenv_tree.column("pkgs", width=70)

        tree_scroll = ttk.Scrollbar(tree_frame, orient=tk.VERTICAL, command=self.mvenv_tree.yview)
        self.mvenv_tree.configure(yscrollcommand=tree_scroll.set)
        self.mvenv_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)

        self.mvenv_tree.bind("<<TreeviewSelect>>", self._on_mvenv_selected)

        # Packages detail panel
        pkg_frame = ttk.LabelFrame(paned, text="Installed Packages", padding=8)
        paned.add(pkg_frame, weight=2)

        self.pkg_listbox = tk.Listbox(pkg_frame, font=("Consolas", 9))
        pkg_scroll = ttk.Scrollbar(pkg_frame, command=self.pkg_listbox.yview)
        self.pkg_listbox.configure(yscrollcommand=pkg_scroll.set)
        self.pkg_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        pkg_scroll.pack(side=tk.RIGHT, fill=tk.Y)

    def refresh_mvenvs(self):
        records = self.mvenv_mgr.list_venvs()
        self._local_mvenvs = [r.to_dict() for r in records]
        self.mvenv_tree.delete(*self.mvenv_tree.get_children())
        for r in records:
            size_mb = f"{r.size_bytes / (1024*1024):.1f} MB"
            sov_str = "Yes" if r.is_sovereign else "No"
            self.mvenv_tree.insert(
                "",
                tk.END,
                iid=r.name,
                values=(r.name, r.python_version, size_mb, sov_str, len(r.packages))
            )

    def _on_mvenv_selected(self, event):
        sel = self.mvenv_tree.selection()
        if not sel:
            return
        name = sel[0]
        rec = next((r for r in self._local_mvenvs if r["name"] == name), None)
        self.pkg_listbox.delete(0, tk.END)
        if rec:
            for p in sorted(rec.get("packages", [])):
                self.pkg_listbox.insert(tk.END, p)

    def _create_new_mvenv_dialog(self):
        name = simpledialog.askstring("New MVenv", "Enter name for new managed virtual environment:", parent=self.root)
        if not name or not name.strip():
            return

        self.set_status(f"Creating sovereign mvenv '{name}'...", 25)

        def worker():
            try:
                req = MvenvCreateRequest(name=name.strip(), sovereign=True)
                self.mvenv_mgr.create_venv(req)
                self.set_status(f"MVenv '{name}' created successfully.", 100)
                self.safe_after(0, self.refresh_mvenvs)
            except Exception as e:
                self.set_status(f"Failed to create mvenv: {e}", 0)
                self.safe_after(0, lambda: messagebox.showerror("Creation Error", str(e)))

        threading.Thread(target=worker, daemon=True).start()

    def _verify_selected_mvenv(self):
        sel = self.mvenv_tree.selection()
        if not sel:
            return
        name = sel[0]
        res = self.mvenv_mgr.verify_venv(name)
        if res.get("valid"):
            messagebox.showinfo("Verification Passed", f"MVenv '{name}' is healthy!\nPython: {res.get('python_path')}\nVersion: {res.get('python_version')}")
        else:
            messagebox.showerror("Verification Failed", f"MVenv '{name}' failed check:\n{res.get('error')}")

    def _delete_selected_mvenv(self):
        sel = self.mvenv_tree.selection()
        if not sel:
            return
        name = sel[0]
        if messagebox.askyesno("Delete MVenv", f"Are you sure you want to delete mvenv '{name}'?"):
            self.mvenv_mgr.delete_venv(name)
            self.refresh_mvenvs()
            self.set_status(f"Deleted mvenv '{name}'.", 100)

    def _open_merge_mvenvs_dialog(self):
        venvs = self.mvenv_mgr.list_venvs()
        if len(venvs) < 2:
            messagebox.showinfo("Merge MVenvs", "At least two managed virtual environments are required to perform a merge.")
            return

        diag = tk.Toplevel(self.root)
        diag.title("Merge MVenvs - Consolidate & Save Disk Space")
        diag.geometry("520x460")
        diag.transient(self.root)
        diag.grab_set()

        f = ttk.Frame(diag, padding=12)
        f.pack(fill=tk.BOTH, expand=True)

        ttk.Label(
            f,
            text="Select 2 or more MVenvs to consolidate dependencies into a single shared environment:",
            wraplength=480,
            font=("Segoe UI", 9, "bold")
        ).pack(anchor=tk.W, pady=(0, 8))

        # Checkboxes listbox
        list_frame = ttk.Frame(f)
        list_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))

        mvenv_listbox = tk.Listbox(list_frame, selectmode=tk.MULTIPLE, font=("Segoe UI", 9), height=7)
        scroll = ttk.Scrollbar(list_frame, command=mvenv_listbox.yview)
        mvenv_listbox.configure(yscrollcommand=scroll.set)
        mvenv_listbox.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scroll.pack(side=tk.RIGHT, fill=tk.Y)

        for v in venvs:
            size_mb = f"{v.size_bytes / (1024*1024):.1f} MB"
            mvenv_listbox.insert(tk.END, f"{v.name}  ({size_mb}, {len(v.packages)} pkgs)")

        # Target environment name
        name_frame = ttk.Frame(f)
        name_frame.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(name_frame, text="Target Merged MVenv Name:").pack(side=tk.LEFT, padx=(0, 8))
        target_name_var = tk.StringVar(value="shared-apps")
        target_entry = ttk.Entry(name_frame, textvariable=target_name_var, width=22)
        target_entry.pack(side=tk.LEFT)

        # Options
        delete_sources_var = tk.BooleanVar(value=True)
        chk_delete = ttk.Checkbutton(f, text="Delete source MVenvs after merge to reclaim disk space", variable=delete_sources_var)
        chk_delete.pack(anchor=tk.W, pady=2)

        relink_apps_var = tk.BooleanVar(value=True)
        chk_relink = ttk.Checkbutton(f, text="Automatically re-link installed applications to merged MVenv", variable=relink_apps_var)
        chk_relink.pack(anchor=tk.W, pady=2)

        # Execute merge
        def execute_merge():
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
            relink_apps = relink_apps_var.get()

            diag.destroy()
            self.set_status(f"Merging {len(sources)} MVenvs into '{target_name}'...", 30)

            def worker():
                try:
                    res = self.mvenv_mgr.merge_venvs(
                        source_names=sources,
                        target_name=target_name,
                        delete_sources=delete_sources,
                        repoint_apps=relink_apps
                    )
                    saved_mb = f"{res.get('reclaimed_bytes', 0) / (1024*1024):.1f} MB"
                    msg = (
                        f"Merge complete!\n\n"
                        f"Target MVenv: {target_name}\n"
                        f"Merged Sources: {', '.join(res.get('merged_sources', []))}\n"
                        f"Packages Installed: {res.get('packages_installed', 0)}\n"
                        f"Repointed Apps: {', '.join(res.get('repointed_apps', [])) or 'None'}\n"
                        f"Reclaimed Disk Space: {saved_mb}"
                    )
                    self.set_status(f"Merge complete. Saved {saved_mb} of disk space!", 100)
                    self.safe_after(0, self.refresh_mvenvs)
                    self.safe_after(0, self.refresh_installed_apps)
                    self.safe_after(0, lambda: messagebox.showinfo("Merge & Reclaim Success", msg))
                except Exception as e:
                    self.set_status(f"Merge failed: {e}", 0)
                    self.safe_after(0, lambda: messagebox.showerror("Merge Error", str(e)))

            threading.Thread(target=worker, daemon=True).start()

        btn_row = ttk.Frame(f)
        btn_row.pack(fill=tk.X, pady=(12, 0))
        ttk.Button(btn_row, text="Merge & Reclaim Space Now", style="Accent.TButton", command=execute_merge).pack(side=tk.RIGHT)
        ttk.Button(btn_row, text="Cancel", command=diag.destroy).pack(side=tk.RIGHT, padx=6)

    def refresh_all(self):
        self._update_catalog_combo()
        self.refresh_catalog_apps()
        self.refresh_installed_apps()
        self.refresh_mvenvs()


def launch_gui():
    if not HAS_TK:
        print("[AuraSeed GUI] Error: Tkinter is not available in this Python environment.", file=sys.stderr)
        return 1
    root = tk.Tk()
    app = AuraSeedAppHubGUI(root)
    root.mainloop()
    return 0
