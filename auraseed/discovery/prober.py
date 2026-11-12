"""
Zero-dependency Python runtime capability prober and path sanitizer.
"""
import importlib.util
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from auraseed.models import DiscoveredEnvironment, RuntimeCapabilityReport


BORROWABLE_HEAVY_PACKAGES: Tuple[str, ...] = (
    "numpy",
    "scipy",
    "pandas",
    "pyarrow",
    "torch",
    "osgeo",
)

_PROBE_SCRIPT = """
import importlib.util
import json
import platform
import sys
import sysconfig

req = json.loads(sys.argv[1]) if len(sys.argv) > 1 else {}
extra_modules = req.get("modules", [])
heavy_packages = req.get("packages", [])

def has_mod(name):
    try:
        return importlib.util.find_spec(name) is not None
    except Exception:
        return False

modules = {
    "ssl": has_mod("ssl"),
    "sqlite3": has_mod("sqlite3"),
    "ctypes": has_mod("ctypes"),
    "tkinter": has_mod("tkinter"),
    "venv": has_mod("venv"),
    "pip": has_mod("pip"),
}
matched_extra_modules = [m for m in extra_modules if has_mod(m)]
preinstalled = [p for p in heavy_packages if has_mod(p)]

ver = sys.version_info
py_tag = f"cp{ver[0]}{ver[1]}"
impl_tag = getattr(sys.implementation, "cache_tag", None) or py_tag
plat_tag = sysconfig.get_platform().replace("-", "_").replace(".", "_")
abi_tags = list(dict.fromkeys([f"{py_tag}-{impl_tag}-{plat_tag}", py_tag, plat_tag]))

payload = {
    "version": f"{ver[0]}.{ver[1]}.{ver[2]}",
    "version_tuple": [int(ver[0]), int(ver[1]), int(ver[2])],
    "architecture": (platform.machine() or "unknown").lower(),
    "abi_tags": abi_tags,
    "modules": modules,
    "matched_extra_modules": matched_extra_modules,
    "preinstalled_packages": preinstalled,
}
print(json.dumps(payload))
""".strip()


def sanitize_candidate_path(raw_path: str | Path) -> Optional[Path]:
    """
    Normalizes candidate paths from environment variables or discovery inputs
    and rejects null-byte or ungrounded traversal segments.
    """
    text = str(raw_path).strip().strip('"').strip("'")
    if not text or "\x00" in text:
        return None
    normalized = os.path.normpath(text)
    if ".." in Path(normalized).parts:
        return None
    try:
        return Path(normalized).resolve()
    except OSError:
        return None


def iter_env_search_paths(var_names: Iterable[str]) -> List[Path]:
    """
    Parses path-list environment variables with traversal validation.
    """
    out: List[Path] = []
    seen: set[str] = set()
    for var in var_names:
        raw = os.environ.get(var, "")
        if not raw:
            continue
        for piece in raw.split(os.pathsep):
            clean = sanitize_candidate_path(piece)
            if clean is not None and clean.exists():
                key = str(clean).lower()
                if key not in seen:
                    seen.add(key)
                    out.append(clean)
    return out


def is_windows_store_stub(executable: Path) -> bool:
    """
    Detects 0-byte Microsoft Store execution aliases under WindowsApps.
    """
    exe_str = str(executable).lower()
    if "windowsapps" not in exe_str:
        return False
    try:
        return executable.exists() and executable.stat().st_size == 0
    except OSError:
        return True


def _parse_version_tuple(version_str: str) -> Tuple[int, int, int]:
    parts: List[int] = []
    for seg in (version_str or "").split("."):
        digits = ""
        for ch in seg:
            if ch.isdigit():
                digits += ch
            else:
                break
        if not digits:
            break
        parts.append(int(digits))
        if len(parts) >= 3:
            break
    while len(parts) < 3:
        parts.append(0)
    return (parts[0], parts[1], parts[2])


def compute_composite_score(
    version_tuple: Tuple[int, int, int],
    report: RuntimeCapabilityReport,
    required_modules: Optional[List[str]] = None,
    required_packages: Optional[List[str]] = None,
    matched_required_modules: Optional[List[str]] = None,
) -> float:
    """
    Computes a deterministic high-precision capability score (>= 6 decimals).
    """
    major, minor, micro = version_tuple
    version_score = max(0.0, ((major * 100.0) + minor + (micro / 100.0) - 300.0)) / 20.0
    version_component = min(1.0, version_score) * 35.0

    stdlib_checks = (
        report.has_ssl,
        report.has_sqlite3,
        report.has_ctypes,
        report.has_tkinter,
        report.has_venv,
        report.has_pip,
    )
    stdlib_component = (sum(1 for ok in stdlib_checks if ok) / float(len(stdlib_checks))) * 30.0
    health_bonus = (8.0 if report.has_ssl else 0.0) + (7.0 if report.has_venv else 0.0)

    req_mods = [m for m in (required_modules or []) if m]
    if req_mods:
        matched_m = set(matched_required_modules or [])
        mod_component = (sum(1 for m in req_mods if m in matched_m) / float(len(req_mods))) * 10.0
    else:
        mod_component = 5.0

    req_pkgs = [p for p in (required_packages or []) if p]
    pre_lower = {p.lower() for p in report.preinstalled_packages}
    if req_pkgs:
        pkg_component = (sum(1 for p in req_pkgs if p.lower() in pre_lower) / float(len(req_pkgs))) * 10.0
    else:
        borrowable_hits = sum(1 for p in BORROWABLE_HEAVY_PACKAGES if p in pre_lower)
        pkg_component = (borrowable_hits / float(len(BORROWABLE_HEAVY_PACKAGES))) * 10.0

    total = version_component + stdlib_component + health_bonus + mod_component + pkg_component
    return round(total, 8)


class RuntimeCapabilityProber:
    """
    Probes discovered Python runtimes in isolated subprocess mode (-I) with strict timeout.
    """

    def __init__(self, timeout: float = 3.0) -> None:
        self.timeout = float(timeout)

    def probe(
        self,
        env: DiscoveredEnvironment,
        required_modules: Optional[List[str]] = None,
        required_packages: Optional[List[str]] = None,
    ) -> RuntimeCapabilityReport:
        exe = sanitize_candidate_path(env.executable)
        if exe is None or not exe.exists() or not exe.is_file() or is_windows_store_stub(exe):
            report = RuntimeCapabilityReport()
            env.capabilities = report
            return report

        req_modules = list(dict.fromkeys([m.strip() for m in (required_modules or []) if m and m.strip()]))
        check_packages = list(
            dict.fromkeys(
                list(BORROWABLE_HEAVY_PACKAGES)
                + [p.strip() for p in (required_packages or []) if p and p.strip()]
            )
        )
        req_payload = json.dumps({"modules": req_modules, "packages": check_packages})

        cmd = [str(exe), "-I", "-c", _PROBE_SCRIPT, req_payload]
        try:
            proc = subprocess.run(
                cmd,
                shell=False,
                capture_output=True,
                text=True,
                timeout=self.timeout,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                report = RuntimeCapabilityReport()
                env.capabilities = report
                return report
            data: Dict[str, Any] = json.loads(proc.stdout.strip().splitlines()[-1])
        except (OSError, subprocess.TimeoutExpired, json.JSONDecodeError, ValueError):
            report = RuntimeCapabilityReport()
            env.capabilities = report
            return report

        mods = data.get("modules", {}) if isinstance(data.get("modules"), dict) else {}
        ver_str = str(data.get("version") or env.version or "0.0.0")
        ver_tuple_raw = data.get("version_tuple")
        if isinstance(ver_tuple_raw, list) and len(ver_tuple_raw) >= 3:
            ver_tuple = (int(ver_tuple_raw[0]), int(ver_tuple_raw[1]), int(ver_tuple_raw[2]))
        else:
            ver_tuple = _parse_version_tuple(ver_str)

        if not env.version or env.version in ("unknown", "3.x") or env.version.endswith(".x"):
            env.version = ver_str

        report = RuntimeCapabilityReport(
            has_ssl=bool(mods.get("ssl", False)),
            has_sqlite3=bool(mods.get("sqlite3", False)),
            has_ctypes=bool(mods.get("ctypes", False)),
            has_tkinter=bool(mods.get("tkinter", False)),
            has_venv=bool(mods.get("venv", False)),
            has_pip=bool(mods.get("pip", False)),
            architecture=str(data.get("architecture") or "unknown"),
            abi_tags=[str(t) for t in data.get("abi_tags", [])],
            preinstalled_packages=[str(p) for p in data.get("preinstalled_packages", [])],
            composite_score=0.0,
        )
        report.composite_score = compute_composite_score(
            version_tuple=ver_tuple,
            report=report,
            required_modules=req_modules,
            required_packages=required_packages,
            matched_required_modules=[str(m) for m in data.get("matched_extra_modules", [])],
        )
        env.capabilities = report
        return report
