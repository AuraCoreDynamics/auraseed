# AuraSeed Architecture

## Operational Sovereignty

A standard Python virtual environment (`python -m venv --system-site-packages`) maintains dynamic references back to its host runtime via `pyvenv.cfg` and `.pth` path lookups. If the parent host application is updated, mutated, corrupted, or uninstalled, dependent virtual environments break immediately.

AuraSeed introduces **Operational Sovereignty**:
The host runtime is utilized only as a source interpreter and C-extension payload pool during the initial seed phase.

Post-seeding, AuraSeed severs dynamic dependencies on the parent host by:
1. Hard-linking or copying critical `site-packages`.
2. Migrating native C-extensions (`.pyd`/`.so`) and dependent binary shared libraries (`.dll`/`.so`/`.dylib`) into user space.
3. Modifying `pyvenv.cfg` and purging dynamic `.pth` linkers.

**Guarantee**: Upgrades, deletions, or corruptions of the host application (e.g., updating ArcGIS Pro from 3.2 to 3.3 or completely uninstalling QGIS) MUST NOT impact or break existing AuraSeed virtual environments.

## The Bootstrapping Paradigm

To resolve the chicken-and-egg problem of requiring Python to discover Python, AuraSeed utilizes a two-tier architectural bootstrap:

1. **Native OS Discovery (Level 0)**:
   - Extremely lightweight, fast shell scripts (`.bat`, `.ps1`, `.sh`).
   - Uses native system commands (`where`, `Get-Command`, `command -v`) to find an initial, valid Python interpreter.
   - Bootstraps the execution into the AuraSeed Python engine.

2. **Engine Discovery (Level 1)**:
   - Uses the robust, object-oriented `BaseDiscoverer` strategy pattern in Python.
   - Discovers environments dynamically across the host system, including embedded thick-client runtimes like ArcGIS Pro or QGIS.

## Zero External Runtime Dependencies

AuraSeed Core MUST rely strictly on the Python Standard Library (`venv`, `subprocess`, `winreg`, `pathlib`, `json`, `urllib`, `shutil`, `importlib`). 
Any provisioner requiring third-party libraries (e.g., `requests`, `keyring`, `cryptography`) MUST be isolated into a secondary plugin repository (`auraseed-plugins`).
