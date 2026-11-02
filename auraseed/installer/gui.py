"""
Zero-dependency Tkinter GUI Wizard for AuraSeed App Installer.
Zero external runtime dependencies (Python standard library only).
"""
import sys
import os
import threading
import webbrowser
import subprocess
from pathlib import Path
from typing import Optional

try:
    import tkinter as tk
    from tkinter import ttk, filedialog, messagebox
    HAS_TK = True
except ImportError:
    HAS_TK = False

from auraseed.installer.models import AppManifest
from auraseed.installer.engine import AppInstallerEngine


class AppInstallerGUI:
    def __init__(self, manifest: AppManifest, default_dest: Optional[Path] = None):
        if not HAS_TK:
            raise RuntimeError("Tkinter is not available in the current Python environment.")

        self.manifest = manifest
        self.engine = AppInstallerEngine(manifest, logger=self._log)
        self.target_dest = default_dest or self.engine.resolve_default_dest()
        self.install_result = None

        self.root = tk.Tk()
        self.root.title(f"{manifest.display_name} Setup")
        self.root.geometry("640x480")
        self.root.minsize(580, 420)

        # Apply clean theme
        style = ttk.Style(self.root)
        try:
            if "vista" in style.theme_names():
                style.theme_use("vista")
            elif "clam" in style.theme_names():
                style.theme_use("clam")
        except Exception:
            pass

        self._build_ui()

    def _build_ui(self):
        # 1. Header Frame
        header = ttk.Frame(self.root, padding=16)
        header.pack(fill=tk.X)

        title_lbl = ttk.Label(header, text=self.manifest.display_name, font=("Segoe UI", 14, "bold"))
        title_lbl.pack(anchor=tk.W)

        desc_text = f"Version {self.manifest.version}\n{self.manifest.description}"
        desc_lbl = ttk.Label(header, text=desc_text, font=("Segoe UI", 9))
        desc_lbl.pack(anchor=tk.W, pady=(4, 0))

        sep = ttk.Separator(self.root, orient=tk.HORIZONTAL)
        sep.pack(fill=tk.X, padx=16, pady=4)

        # 2. Container for Wizard Pages
        self.page_container = ttk.Frame(self.root, padding=16)
        self.page_container.pack(fill=tk.BOTH, expand=True)

        self._show_options_page()

    def _show_options_page(self):
        for widget in self.page_container.winfo_children():
            widget.destroy()

        # Destination selector
        dest_label = ttk.Label(self.page_container, text="Installation Location:", font=("Segoe UI", 9, "bold"))
        dest_label.pack(anchor=tk.W, pady=(8, 2))

        dest_frame = ttk.Frame(self.page_container)
        dest_frame.pack(fill=tk.X, pady=(0, 12))

        self.dest_var = tk.StringVar(value=str(self.target_dest))
        self.dest_entry = ttk.Entry(dest_frame, textvariable=self.dest_var)
        self.dest_entry.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 8))

        browse_btn = ttk.Button(dest_frame, text="Browse...", command=self._browse_dir)
        browse_btn.pack(side=tk.RIGHT)

        # Port configuration
        port_label = ttk.Label(self.page_container, text="Service Port:", font=("Segoe UI", 9, "bold"))
        port_label.pack(anchor=tk.W, pady=(4, 2))

        default_port = self.manifest.default_port or 8000
        self.port_var = tk.IntVar(value=default_port)
        port_spin = ttk.Spinbox(self.page_container, from_=1024, to=65535, textvariable=self.port_var, width=10)
        port_spin.pack(anchor=tk.W, pady=(0, 12))

        # Checkbox: Desktop shortcut
        self.shortcut_var = tk.BooleanVar(value=self.manifest.create_desktop_shortcut)
        shortcut_chk = ttk.Checkbutton(self.page_container, text="Create Desktop Shortcut", variable=self.shortcut_var)
        shortcut_chk.pack(anchor=tk.W, pady=(0, 8))

        # Bottom Buttons
        btn_frame = ttk.Frame(self.root, padding=16)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        cancel_btn = ttk.Button(btn_frame, text="Cancel", command=self.root.destroy)
        cancel_btn.pack(side=tk.RIGHT, padx=(8, 0))

        install_btn = ttk.Button(btn_frame, text="Install Now", style="Accent.TButton", command=self._start_install)
        install_btn.pack(side=tk.RIGHT)

    def _browse_dir(self):
        selected = filedialog.askdirectory(initialdir=self.dest_var.get(), title="Select Installation Folder")
        if selected:
            self.dest_var.set(selected)

    def _start_install(self):
        target_path = Path(self.dest_var.get()).resolve()
        port = self.port_var.get()
        create_shortcut = self.shortcut_var.get()

        # Switch to Progress Page
        for widget in self.page_container.winfo_children():
            widget.destroy()

        self.status_lbl = ttk.Label(self.page_container, text="Preparing installation...", font=("Segoe UI", 10))
        self.status_lbl.pack(anchor=tk.W, pady=(8, 4))

        self.progress_bar = ttk.Progressbar(self.page_container, orient=tk.HORIZONTAL, mode="determinate")
        self.progress_bar.pack(fill=tk.X, pady=(0, 12))

        # Log Console
        log_frame = ttk.Frame(self.page_container)
        log_frame.pack(fill=tk.BOTH, expand=True)

        self.log_text = tk.Text(log_frame, wrap=tk.WORD, font=("Consolas", 8), height=12)
        scrollbar = ttk.Scrollbar(log_frame, command=self.log_text.yview)
        self.log_text.configure(yscrollcommand=scrollbar.set)
        self.log_text.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        scrollbar.pack(side=tk.RIGHT, fill=tk.Y)

        # Worker thread
        def run_thread():
            try:
                res = self.engine.install(
                    dest_dir=target_path,
                    port=port,
                    force=True,
                    create_launchers=True,
                    create_desktop_shortcut=create_shortcut,
                    progress_callback=self._update_progress_from_thread
                )
                self.install_result = res
                self.root.after(100, self._show_complete_page)
            except Exception as e:
                self.root.after(100, lambda: self._show_error(str(e)))

        t = threading.Thread(target=run_thread, daemon=True)
        t.start()

    def _update_progress_from_thread(self, pct: int, msg: str):
        def ui_update():
            self.progress_bar["value"] = pct
            self.status_lbl.config(text=msg)
            self._log(msg)
        self.root.after(10, ui_update)

    def _log(self, text: str):
        if hasattr(self, "log_text"):
            self.log_text.insert(tk.END, text + "\n")
            self.log_text.see(tk.END)
        else:
            print(text)

    def _show_error(self, err_msg: str):
        self.status_lbl.config(text="Installation Failed.")
        self._log(f"\nERROR: {err_msg}")
        messagebox.showerror("Installation Error", f"An error occurred during installation:\n\n{err_msg}")

    def _show_complete_page(self):
        for widget in self.page_container.winfo_children():
            widget.destroy()

        success_lbl = ttk.Label(self.page_container, text="Installation Complete!", font=("Segoe UI", 12, "bold"))
        success_lbl.pack(anchor=tk.W, pady=(12, 6))

        info_text = (
            f"{self.manifest.display_name} has been successfully installed and configured.\n\n"
            f"Directory: {self.install_result.get('install_dir')}\n"
            f"Service Port: {self.install_result.get('port')}\n"
        )
        info_lbl = ttk.Label(self.page_container, text=info_text, font=("Segoe UI", 9))
        info_lbl.pack(anchor=tk.W, pady=(0, 16))

        # Bottom Buttons
        btn_frame = ttk.Frame(self.root, padding=16)
        btn_frame.pack(fill=tk.X, side=tk.BOTTOM)

        finish_btn = ttk.Button(btn_frame, text="Finish", command=self.root.destroy)
        finish_btn.pack(side=tk.RIGHT, padx=(8, 0))

        launch_btn = ttk.Button(btn_frame, text=f"Launch {self.manifest.name.capitalize()}", command=self._launch_app)
        launch_btn.pack(side=tk.RIGHT)

    def _launch_app(self):
        if not self.install_result:
            return
        launchers = self.install_result.get("launchers", {})
        port = self.install_result.get("port", 8000)

        # Open web browser if service port defined
        if port:
            try:
                webbrowser.open(f"http://localhost:{port}/")
            except Exception:
                pass

        # Execute launcher process in background
        bat = launchers.get("bat")
        sh = launchers.get("sh")
        target_launcher = bat if platform.system().lower() == "windows" else sh
        if target_launcher and Path(target_launcher).exists():
            subprocess.Popen([str(target_launcher)], shell=True)

        self.root.destroy()

    def run(self):
        self.root.mainloop()


def launch_gui(manifest: AppManifest, dest_dir: Optional[Path] = None):
    app = AppInstallerGUI(manifest, default_dest=dest_dir)
    app.run()

