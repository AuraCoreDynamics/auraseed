import json
import os
import platform
from pathlib import Path
from typing import Dict, List, Optional
from datetime import datetime, timezone

from auraseed.mvenv.models import MvenvRecord


class MvenvCatalog:
    """
    Catalog store for managed virtual environments.
    Maintains a central index while honoring per-environment `.mvenv.json` metadata.
    """

    def __init__(self, root_dir: Path):
        self.root_dir = root_dir.resolve()
        self.catalog_file = self.root_dir / ".catalog.json"
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def _now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def get_record(self, name: str) -> Optional[MvenvRecord]:
        """
        Retrieves a record for the named mvenv, reading .mvenv.json if present.
        """
        env_dir = self.root_dir / name
        if not env_dir.is_dir():
            return None

        meta_file = env_dir / ".mvenv.json"
        if meta_file.exists():
            try:
                data = json.loads(meta_file.read_text(encoding="utf-8"))
                record = MvenvRecord.from_dict(data)
                record.path = str(env_dir)
                if not record.python_path:
                    record.python_path = str(self._find_python_exe(env_dir))
                if not record.pip_path:
                    record.pip_path = str(self._find_pip_exe(env_dir))
                return record
            except Exception:
                pass

        # Fallback to inspecting directory directly
        py_exe = self._find_python_exe(env_dir)
        if py_exe and py_exe.exists():
            pip_exe = self._find_pip_exe(env_dir)
            created_at = self._now_iso()
            return MvenvRecord(
                name=name,
                path=str(env_dir),
                python_path=str(py_exe),
                pip_path=str(pip_exe) if pip_exe else "",
                python_version="unknown",
                base_interpreter="",
                created_at=created_at,
                updated_at=created_at,
                packages=[],
                size_bytes=self._calculate_dir_size(env_dir),
                is_sovereign=False
            )

        return None

    def list_records(self) -> List[MvenvRecord]:
        """
        Scans root_dir and returns all discovered and cataloged mvenv records.
        """
        records: List[MvenvRecord] = []
        if not self.root_dir.exists():
            return records

        for child in sorted(self.root_dir.iterdir()):
            if child.is_dir() and not child.name.startswith("."):
                rec = self.get_record(child.name)
                if rec is not None:
                    records.append(rec)

        return records

    def save_record(self, record: MvenvRecord) -> None:
        """
        Saves metadata to both the environment's .mvenv.json and central .catalog.json.
        """
        env_dir = Path(record.path)
        if env_dir.exists():
            # AuraGrid-compatible .mvenv.json format
            auragrid_meta = {
                "name": record.name,
                "pythonVersion": record.python_version,
                "createdAt": record.created_at,
                "updatedAt": record.updated_at,
                "packages": record.packages,
                "isSovereign": record.is_sovereign,
                "baseInterpreter": record.base_interpreter,
                "sizeBytes": record.size_bytes,
                "bundleHash": record.bundle_hash,
                "metadata": record.metadata
            }
            meta_file = env_dir / ".mvenv.json"
            meta_file.write_text(json.dumps(auragrid_meta, indent=2), encoding="utf-8")

        # Update central index
        all_records = {r.name: r.to_dict() for r in self.list_records()}
        all_records[record.name] = record.to_dict()
        try:
            self.catalog_file.write_text(json.dumps(all_records, indent=2), encoding="utf-8")
        except Exception:
            pass

    def remove_record(self, name: str) -> bool:
        """
        Deregisters the record from the central catalog.
        """
        if self.catalog_file.exists():
            try:
                data = json.loads(self.catalog_file.read_text(encoding="utf-8"))
                if name in data:
                    del data[name]
                    self.catalog_file.write_text(json.dumps(data, indent=2), encoding="utf-8")
                    return True
            except Exception:
                pass
        return False

    @staticmethod
    def _find_python_exe(venv_dir: Path) -> Optional[Path]:
        is_win = platform.system().lower() == "windows"
        if is_win:
            candidates = [
                venv_dir / "Scripts" / "python.exe",
                venv_dir / "python.exe",
                venv_dir / "base" / "python.exe"
            ]
        else:
            candidates = [
                venv_dir / "bin" / "python",
                venv_dir / "bin" / "python3",
                venv_dir / "python",
                venv_dir / "base" / "python"
            ]

        for c in candidates:
            if c.exists():
                return c
        return None

    @staticmethod
    def _find_pip_exe(venv_dir: Path) -> Optional[Path]:
        is_win = platform.system().lower() == "windows"
        if is_win:
            candidates = [
                venv_dir / "Scripts" / "pip.exe",
                venv_dir / "pip.exe",
                venv_dir / "base" / "pip.exe"
            ]
        else:
            candidates = [
                venv_dir / "bin" / "pip",
                venv_dir / "bin" / "pip3"
            ]

        for c in candidates:
            if c.exists():
                return c
        return None

    @staticmethod
    def _calculate_dir_size(dir_path: Path) -> int:
        total = 0
        try:
            for root, _, files in os.walk(dir_path):
                for f in files:
                    fp = os.path.join(root, f)
                    try:
                        total += os.path.getsize(fp)
                    except OSError:
                        pass
        except Exception:
            pass
        return total
