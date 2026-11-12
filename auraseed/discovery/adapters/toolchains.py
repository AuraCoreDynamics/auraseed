"""
Modern Python toolchain discovery adapter (uv, pixi, pyenv-win, hatch, pdm, scoop, winget, VS Shared).
"""
import logging
import os
import re
from pathlib import Path
from typing import Iterator, List, Optional, Set, Tuple

from auraseed.discovery.base import BaseDiscoverer
from auraseed.discovery.prober import is_windows_store_stub, sanitize_candidate_path
from auraseed.models import DiscoveredEnvironment

_LOG = logging.getLogger(__name__)
_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


def _extract_version_hint(text: str) -> str:
    match = _VERSION_RE.search(text or "")
    if not match:
        return "unknown"
    ver = match.group(1)
    if ver.count(".") == 1:
        return f"{ver}.0"
    return ver


def _find_python_binaries(root: Path, max_depth: int = 4) -> List[Path]:
    """
    Finds python / python3 executables under root up to max_depth levels.
    """
    found: List[Path] = []
    if not root.exists() or not root.is_dir():
        return found

    root_depth = len(root.parts)
    try:
        for dirpath, dirnames, filenames in os.walk(root):
            cur = Path(dirpath)
            if len(cur.parts) - root_depth > max_depth:
                dirnames[:] = []
                continue
            for fname in filenames:
                if fname.lower() in ("python.exe", "python3.exe", "python", "python3"):
                    candidate = cur / fname
                    if candidate.is_file() and not is_windows_store_stub(candidate):
                        found.append(candidate)
    except OSError as exc:
        _LOG.debug("Skipping unreadable toolchain directory %s: %s", root, exc)
    return found


class ToolchainDiscoverer(BaseDiscoverer):
    """
    Discovers Python runtimes managed by uv, pixi, pyenv/pyenv-win, hatch, pdm,
    scoop, winget, and Visual Studio Shared Python installations.
    """

    def __init__(self, search_roots: Optional[List[Path]] = None) -> None:
        self.search_roots = [Path(p) for p in search_roots] if search_roots is not None else None

    @property
    def source_type(self) -> str:
        return "toolchains"

    def _candidate_roots(self) -> List[Tuple[str, Path]]:
        if self.search_roots is not None:
            pairs: List[Tuple[str, Path]] = []
            for base in self.search_roots:
                clean = sanitize_candidate_path(base)
                if clean is None or not clean.exists():
                    continue
                pairs.extend([
                    ("uv", clean / "uv" / "python"),
                    ("uv", clean / "uv"),
                    ("pixi", clean / ".pixi" / "envs"),
                    ("pixi", clean / "pixi" / "envs"),
                    ("pyenv", clean / ".pyenv" / "pyenv-win" / "versions"),
                    ("pyenv", clean / "pyenv-win" / "versions"),
                    ("pyenv", clean / ".pyenv" / "versions"),
                    ("hatch", clean / "hatch" / "env" / "virtual"),
                    ("pdm", clean / "pdm" / "venvs"),
                    ("scoop", clean / "scoop" / "apps"),
                    ("winget", clean / "Microsoft" / "WinGet" / "Packages"),
                    ("vs_shared", clean / "Microsoft Visual Studio" / "Shared"),
                    ("custom_root", clean),
                ])
            return pairs

        home = Path.home()
        appdata = os.environ.get("APPDATA", "")
        localappdata = os.environ.get("LOCALAPPDATA", "")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")

        candidates: List[Tuple[str, Path]] = [
            ("uv", home / ".local" / "share" / "uv" / "python"),
            ("pixi", home / ".pixi" / "envs"),
            ("pyenv", home / ".pyenv" / "pyenv-win" / "versions"),
            ("pyenv", home / ".pyenv" / "versions"),
            ("hatch", home / ".local" / "share" / "hatch" / "env" / "virtual"),
            ("pdm", home / ".local" / "share" / "pdm" / "venvs"),
            ("scoop", home / "scoop" / "apps"),
        ]
        if appdata:
            candidates.append(("uv", Path(appdata) / "uv" / "python"))
        if localappdata:
            candidates.extend([
                ("uv", Path(localappdata) / "uv" / "python"),
                ("hatch", Path(localappdata) / "hatch" / "env" / "virtual"),
                ("pdm", Path(localappdata) / "pdm" / "venvs"),
                ("winget", Path(localappdata) / "Microsoft" / "WinGet" / "Packages"),
                ("winget", Path(localappdata) / "Microsoft" / "WinGet" / "Links"),
            ])
        for vs_base in (Path(pf86), Path(pf)):
            vs_shared = vs_base / "Microsoft Visual Studio" / "Shared"
            if vs_shared.exists():
                for child in vs_shared.glob("Python*"):
                    candidates.append(("vs_shared", child))
        return candidates

    def _infer_toolchain_tag(self, exe: Path, fallback_tag: str) -> str:
        lower = str(exe).lower().replace("\\", "/")
        for tag in ("uv", "pixi", "pyenv", "hatch", "pdm", "scoop", "winget"):
            if f"/{tag}" in lower or f"{tag}-" in lower or f".{tag}/" in lower:
                return tag
        if "microsoft visual studio/shared" in lower:
            return "vs_shared"
        return fallback_tag

    def discover(self) -> Iterator[DiscoveredEnvironment]:
        seen_exes: Set[str] = set()
        for default_tag, root in self._candidate_roots():
            clean_root = sanitize_candidate_path(root)
            if clean_root is None or not clean_root.exists():
                continue

            for exe in _find_python_binaries(clean_root):
                clean_exe = sanitize_candidate_path(exe)
                if clean_exe is None:
                    continue
                exe_key = str(clean_exe).lower()
                if exe_key in seen_exes:
                    continue
                seen_exes.add(exe_key)

                toolchain = self._infer_toolchain_tag(clean_exe, default_tag)
                version_hint = _extract_version_hint(str(clean_exe))
                parent = clean_exe.parent
                env_root = parent.parent if parent.name.lower() in ("bin", "scripts") else parent

                site_packages: List[Path] = []
                win_sp = env_root / "Lib" / "site-packages"
                if win_sp.exists():
                    site_packages.append(win_sp)
                lib_dir = env_root / "lib"
                if lib_dir.exists():
                    for py_sub in lib_dir.glob("python*"):
                        sp = py_sub / "site-packages"
                        if sp.exists():
                            site_packages.append(sp)

                bin_dirs = [parent]
                if (env_root / "DLLs").exists():
                    bin_dirs.append(env_root / "DLLs")

                yield DiscoveredEnvironment(
                    id=str(clean_exe),
                    name=f"Python ({toolchain}: {env_root.name})",
                    executable=clean_exe,
                    version=version_hint,
                    source_type=self.source_type,
                    site_packages=site_packages,
                    metadata={
                        "toolchain": toolchain,
                        "env_root": str(env_root),
                        "parent_bin_dir": str(parent),
                        "bin_dirs": [str(b) for b in bin_dirs],
                    },
                )
