---
name: auraseed-mvenv
description: >-
  Discover, create, activate, and execute Python workloads in sovereign managed
  virtual environments (mvenvs) using the AuraSeed CLI. Use when an agent needs
  to find available Python interpreters or existing mvenvs, provision isolated
  environments with packages, or run Python code and tools inside an mvenv via
  the CLI.
---

# AuraSeed MVenv Skill

Use the AuraSeed CLI (`--json`) to discover host Python runtimes and existing `mvenv`s, create new isolated environments, and execute commands inside them. Under the hood, AuraSeed follows a layered **MCP -> CLI -> Python API** architecture; when invoking commands directly in a shell, always target the CLI with `--json` for structured output and quiet non-interactive execution.

## 1. Invoking the AuraSeed CLI

Run commands from the AuraSeed repository root (`C:\dev\auraseed` or your clone path) using either the OS bootstrapper or a known valid interpreter:

- **Windows (PowerShell)**:
  `.\auraseed.ps1 <command> [args]` or `.\.bootstrapped_python\python.exe -m auraseed <command> [args]`
- **Windows (CMD)**:
  `auraseed.bat <command> [args]`
- **Linux / macOS**:
  `./auraseed.sh <command> [args]` or `PYTHONPATH=. python3 -m auraseed <command> [args]`

> **Note**: On Windows, do not rely on bare `python` if it points to a 0-byte Windows Store alias. Use `.\auraseed.ps1` or an explicit interpreter path (such as `.bootstrapped_python\python.exe`). Pass `--json` so stdout emits only clean JSON.

## 2. Discover Runtimes and Existing MVenvs

Scan both base Python interpreters and existing `mvenv`s before creating a new environment:

```bash
# Discover both existing mvenvs (catalog + OS registry) and host Python interpreters
python -m auraseed discover --probe --json

# Discover via the mvenv namespace, optionally filtering by adapter
# (all, windows_registry, linux_system, macos_system, toolchains, embedded_apps, arcpro, qgis)
python -m auraseed mvenv discover --adapter all --probe --json

# Fast listing of cataloged mvenvs in the active root only
python -m auraseed mvenv list --json

# Inspect full metadata and installed packages for a specific mvenv
python -m auraseed mvenv info <name> --json
```

Use `--root <dir>` (or `AURASEED_MVENV_ROOT`) when isolating `mvenv`s to a project-specific or temporary directory.

## 3. Create an MVenv

Provision a sovereign managed virtual environment (severs host dependencies by default; add `--no-sovereign` when a standard lightweight venv is preferred):

```bash
# Create with auto-discovered latest Python and pip packages
python -m auraseed mvenv create <name> --packages requests pytest --json

# Select a discovered interpreter matching a version constraint
python -m auraseed mvenv create <name> --spec ">=3.11,<3.15" --packages httpx --json

# Seed from a specialized host adapter (e.g., arcpro or qgis)
python -m auraseed mvenv create <name> --adapter arcpro --json

# Seed from an explicit base interpreter and requirements file into a custom path
python -m auraseed mvenv create <name> --base "/path/to/python" -r requirements.txt --dest "/path/to/env" --json
```

## 4. Use an Existing MVenv

### Run Python or Commands Inside the MVenv (Recommended)

Execute code or installed CLI tools inside `<name>` with `VIRTUAL_ENV` and `PATH` automatically isolated, without mutating the parent shell:

```bash
# Run inline Python or a script file inside the mvenv
python -m auraseed mvenv python <name> --json -- -c "import sys; print(sys.executable)"
python -m auraseed mvenv python <name> -- ./my_script.py --flag

# Run any command (pytest, ruff, module CLIs, etc.) resolved against the mvenv's Scripts/bin
python -m auraseed mvenv run <name> --cwd ./project --json -- pytest -q
```

### Activate, Install, Merge, or Remove

```bash
# Get direct python/pip paths, launcher scripts, and shell activation snippets (powershell, cmd, bash)
python -m auraseed mvenv activate <name> --json

# Install or upgrade packages in an existing mvenv
python -m auraseed mvenv install <name> numpy pandas --upgrade --json
python -m auraseed mvenv install <name> -r requirements.txt --json

# Merge multiple mvenvs into one shared environment to reclaim disk space
python -m auraseed mvenv merge env-a env-b --target shared-env --delete-sources --json

# Delete an mvenv
python -m auraseed mvenv delete <name> --json
```

## 5. Verify Success

After creating or modifying an `mvenv`, verify its executable health and prefix isolation:

1. Check binary and catalog health:
   ```bash
   python -m auraseed mvenv verify <name> --json
   ```
   Confirm `"valid": true` in the JSON output.
2. Confirm execution resolves inside the `mvenv` directory:
   ```bash
   python -m auraseed mvenv python <name> --json -- -c "import sys; print(sys.prefix)"
   ```
   Confirm `"returncode": 0` and `"stdout"` prints the `mvenv` path.

## Additional Reference

For complete flag documentation, `--mcp` stdio/HTTP configuration, and the MCP tool catalog that wraps these CLI commands, read [CLI & MCP Reference](./references/cli-and-mcp-reference.md).
