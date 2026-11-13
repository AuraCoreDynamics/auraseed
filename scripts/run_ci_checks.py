#!/usr/bin/env python3
"""
Local CI verification script for AuraSeed.

Mirrors the exact checks performed by the GitHub Actions CI workflow:
  1. Ruff linting (ruff check .)
  2. Test suite execution (pytest tests/ -v)
  3. Package distribution build (python -m build)
  4. Twine validation (twine check dist/*)
"""

import sys
import subprocess
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


def run_step(name: str, cmd: list[str]) -> bool:
    print(f"\n{'=' * 60}")
    print(f"==> Step: {name}")
    print(f"==> Command: {' '.join(cmd)}")
    print(f"{'=' * 60}\n")
    res = subprocess.run(cmd, cwd=str(REPO_ROOT))
    if res.returncode != 0:
        print(f"\n[FAILED] Step '{name}' exited with code {res.returncode}")
        return False
    print(f"\n[PASSED] Step '{name}' succeeded.")
    return True


def main() -> int:
    steps = [
        ("Linting (Ruff)", [sys.executable, "-m", "ruff", "check", "."]),
        ("Unit Tests (Pytest)", [sys.executable, "-m", "pytest", "tests/", "-v"]),
        ("Package Build", [sys.executable, "-m", "build"]),
        ("Package Validation (Twine)", [sys.executable, "-m", "twine", "check", "dist/*"]),
    ]

    for name, cmd in steps:
        if not run_step(name, cmd):
            print("\n❌ CI pre-push verification failed. Fix errors above before pushing.")
            return 1

    print("\n✅ All CI checks passed successfully! Ready for push.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
