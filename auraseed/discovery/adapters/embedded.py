"""
Thick-client embedded Python discovery adapter (OSGeo4W, Blender, FreeCAD).
"""
import logging
import os
import re
from pathlib import Path
from typing import Iterator, List, Optional, Set, Tuple

from auraseed.discovery.base import BaseDiscoverer
from auraseed.discovery.prober import sanitize_candidate_path
from auraseed.models import DiscoveredEnvironment

_LOG = logging.getLogger(__name__)
_VERSION_RE = re.compile(r"(\d+\.\d+(?:\.\d+)?)")


def _is_python_binary(path: Path) -> bool:
    if not path.is_file():
        return False
    name = path.name.lower()
    if name.endswith((".dll", ".pdb", ".lib", ".so", ".dylib", ".a", ".py", ".pyc")):
        return False
    if os.name == "nt":
        return name in ("python.exe", "python3.exe") or (
            name.startswith("python3.") and name.endswith(".exe")
        )
    return name in ("python", "python3", "python.exe", "python3.exe") or (
        name.startswith("python3.") and not name.endswith("-config")
    )


def _version_hint_from_path(p: Path) -> str:
    m = _VERSION_RE.search(str(p))
    if not m:
        return "unknown"
    v = m.group(1)
    return f"{v}.0" if v.count(".") == 1 else v


class EmbeddedAppDiscoverer(BaseDiscoverer):
    """
    Discovers Python runtimes embedded inside thick desktop applications
    such as OSGeo4W, Blender, and FreeCAD.
    """

    def __init__(self, search_roots: Optional[List[Path]] = None) -> None:
        self.search_roots = [Path(p) for p in search_roots] if search_roots is not None else None

    @property
    def source_type(self) -> str:
        return "embedded_apps"

    def _collect_candidates(self) -> List[Tuple[str, Path, List[str]]]:
        candidates: List[Tuple[str, Path, List[str]]] = []

        if self.search_roots is not None:
            roots = [r for r in (sanitize_candidate_path(p) for p in self.search_roots) if r and r.exists()]
            for root in roots:
                # OSGeo4W patterns
                for rel in (
                    "OSGeo4W/bin/python3.exe",
                    "OSGeo4W/bin/python.exe",
                    "bin/python3.exe",
                    "bin/python.exe",
                ):
                    p = root / rel
                    if p.exists() and ("osgeo" in str(p).lower()):
                        candidates.append(("OSGeo4W", p, ["osgeo", "gdal"]))

                # Blender patterns
                for pattern in (
                    "Blender*/*/python/bin/python.exe",
                    "Blender*/*/python/bin/python3*",
                    "Blender.app/Contents/Resources/*/python/bin/python3*",
                    "*/*/python/bin/python*",
                ):
                    for p in root.glob(pattern):
                        if _is_python_binary(p) and "blender" in str(p).lower():
                            candidates.append(("Blender", p, ["bpy"]))

                # FreeCAD patterns
                for pattern in (
                    "FreeCAD*/bin/python.exe",
                    "FreeCAD*/bin/python3*",
                    "FreeCAD.app/Contents/Resources/bin/python*",
                ):
                    for p in root.glob(pattern):
                        if _is_python_binary(p) and "freecad" in str(p).lower():
                            candidates.append(("FreeCAD", p, ["FreeCAD", "Part"]))
            return candidates

        pf = Path(os.environ.get("ProgramFiles", r"C:\Program Files"))
        pf86 = Path(os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)"))

        # OSGeo4W
        for osgeo_dir in (Path("C:/OSGeo4W"), Path("C:/OSGeo4W64")):
            for py_name in ("python3.exe", "python.exe"):
                p = osgeo_dir / "bin" / py_name
                if p.exists():
                    candidates.append(("OSGeo4W", p, ["osgeo", "gdal"]))

        # Blender
        blender_dirs = [
            pf / "Blender Foundation",
            Path("/usr/share/blender"),
            Path("/Applications"),
        ]
        for bdir in blender_dirs:
            if not bdir.exists():
                continue
            try:
                for p in bdir.glob("Blender*/*/python/bin/python*"):
                    if _is_python_binary(p):
                        candidates.append(("Blender", p, ["bpy"]))
                for p in bdir.glob("Blender.app/Contents/Resources/*/python/bin/python*"):
                    if _is_python_binary(p):
                        candidates.append(("Blender", p, ["bpy"]))
            except OSError as exc:
                _LOG.debug("Skipping Blender scan under %s: %s", bdir, exc)

        # FreeCAD
        for base in (pf, pf86, Path("/Applications"), Path("/usr/lib/freecad")):
            if not base.exists():
                continue
            try:
                for pattern in (
                    "FreeCAD*/bin/python.exe",
                    "FreeCAD*/bin/python3*",
                    "FreeCAD.app/Contents/Resources/bin/python*",
                ):
                    for p in base.glob(pattern):
                        if _is_python_binary(p):
                            candidates.append(("FreeCAD", p, ["FreeCAD", "Part"]))
            except OSError as exc:
                _LOG.debug("Skipping FreeCAD scan under %s: %s", base, exc)

        return candidates

    def discover(self) -> Iterator[DiscoveredEnvironment]:
        seen_exes: Set[str] = set()
        for app_name, raw_exe, target_modules in self._collect_candidates():
            clean_exe = sanitize_candidate_path(raw_exe)
            if clean_exe is None or not clean_exe.exists() or not clean_exe.is_file():
                continue
            exe_key = str(clean_exe).lower()
            if exe_key in seen_exes:
                continue
            seen_exes.add(exe_key)

            parent = clean_exe.parent
            env_root = parent.parent if parent.name.lower() in ("bin", "scripts") else parent
            site_packages: List[Path] = []
            for cand_sp in (
                env_root / "Lib" / "site-packages",
                env_root / "lib" / "site-packages",
                parent / "Lib" / "site-packages",
            ):
                if cand_sp.exists():
                    site_packages.append(cand_sp)

            yield DiscoveredEnvironment(
                id=str(clean_exe),
                name=f"{app_name} ({env_root.name})",
                executable=clean_exe,
                version=_version_hint_from_path(clean_exe),
                source_type=self.source_type,
                site_packages=site_packages,
                metadata={
                    "embedded_app": app_name.lower(),
                    "target_modules": target_modules,
                    "parent_bin_dir": str(parent),
                    "bin_dirs": [str(parent)],
                },
            )
