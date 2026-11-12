# AuraSeed MVenv CLI & MCP Reference

## Architecture: MCP -> CLI -> Python API

AuraSeed separates responsibilities into three cleanly aligned layers:

1. **Python API (`auraseed.mvenv.manager.MvenvManager`, `auraseed.discovery.*`)**:
   Programmatic runtime discovery (`discover_interpreters`, `discover_venvs`), environment creation/isolation (`create_venv`), inspection (`list_venvs`, `get_venv`, `verify_venv`, `get_activation_info`), execution (`run_in_venv`), package management (`install_packages`, `install_requirements`), consolidation (`merge_venvs`), and P2P bundling (`export_bundle`, `import_bundle`).
2. **CLI (`python -m auraseed ...` / `auraseed.ps1` / `auraseed.bat` / `auraseed.sh`)**:
   Non-interactive `--json` subcommands backed directly by the Python API. Passing `--json` or `--mcp` sets quiet unattended config provisioning (`apply_user_configs(auto_yes=True, quiet=True)`) so stdout remains strict JSON or JSON-RPC.
3. **MCP Server (`auraseed.api.mcp.AuraSeedMcpServer`)**:
   Exposes MCP tools over **Stdio** (`python -m auraseed serve --mcp`) and **Streamable HTTP** (`POST /mcp` via `python -m auraseed serve --port 7099`). Each MCP tool executes the corresponding `python -m auraseed ... --json` CLI command in a subprocess, guaranteeing identical behavior between human operators, agent skills using the CLI, and MCP clients.

---

## CLI Command Reference

### Discovery

| Command | Key Flags | Purpose |
| :--- | :--- | :--- |
| `auraseed discover` | `--adapter`, `--probe`, `--no-cache`, `--require-module`, `--require-package`, `--interpreters-only`, `--mvenvs-only`, `--no-registry`, `--root`, `--json` | Discover host Python interpreters and existing mvenvs. |
| `auraseed mvenv discover` | `--adapter`, `--probe`, `--no-cache`, `--require-module`, `--require-package`, `--interpreters`, `--interpreters-only`, `--mvenvs-only`, `--no-registry`, `--root`, `--json` | Same discovery workflow under the `mvenv` namespace. |
| `auraseed mvenv list` | `--root`, `--json` | List mvenvs cataloged in the active `--root` (`AURASEED_MVENV_ROOT` or default). |

Valid `--adapter` values: `all`, `windows_registry`, `linux_system`, `macos_system`, `toolchains`, `embedded_apps`, `arcpro`, `qgis`.

### Creation & Packages

| Command | Key Flags | Purpose |
| :--- | :--- | :--- |
| `auraseed mvenv create <name>` | `--packages`, `-r/--requirements`, `--base`, `--spec`, `--adapter`, `--no-sovereign`, `--force`, `--dest`, `--root`, `--json` | Seed, isolate, generate launchers, and catalog a new mvenv. |
| `auraseed mvenv install <name>` | `<packages...>`, `-r/--requirements`, `--upgrade`, `--root`, `--json` | Install or upgrade packages in an existing mvenv. |
| `auraseed mvenv merge <src...>` | `--target`, `--delete-sources`, `--no-repoint`, `--root`, `--json` | Merge source mvenvs into a target environment and optionally prune sources. |

### Inspection, Execution & Lifecycle

| Command | Key Flags | Purpose |
| :--- | :--- | :--- |
| `auraseed mvenv info <name>` | `--root`, `--json` | Show path, Python executable, version, size, and installed packages. |
| `auraseed mvenv verify <name>` | `--root`, `--json` | Run executable health check on `<name>`. |
| `auraseed mvenv activate <name>` | `--shell {powershell,cmd,bash,all}`, `--root`, `--json` | Return activation scripts, launcher path, and shell commands. |
| `auraseed mvenv python <name> -- <args...>` | `--cwd`, `--timeout`, `--root`, `--json` | Run the mvenv's Python interpreter with isolated `VIRTUAL_ENV`/`PATH`. |
| `auraseed mvenv run <name> -- <cmd...>` | `--cwd`, `--timeout`, `--root`, `--json` | Run an executable or command resolved in the mvenv's `Scripts`/`bin`. |
| `auraseed mvenv export <name>` | `--out`, `--root`, `--json` | Export portable `.tar.gz` bundle. |
| `auraseed mvenv import <bundle>` | `--name`, `--force`, `--root`, `--json` | Import a `.tar.gz` mvenv bundle. |
| `auraseed mvenv delete <name>` | `--root`, `--json` | Remove an mvenv directory and catalog record. |
| `auraseed p2p {pull,push} <url> <name>` | `--root` | Transfer `.tar.gz` mvenv bundles with a peer AuraSeed HTTP server. |
| `auraseed install-self` | `--dest`, `--source`, `--wheelhouse`, `--base-python`, `--editable`, `--no-register`, `--add-to-path`, `--json` | Install AuraSeed standalone into an isolated user-space venv. |
| `auraseed cleanup app <name>` | `--keep-mvenv`, `--no-registry`, `--json` | Remove a legacy AuraSeed-deployed app and its OS registry/env keys. |
| `auraseed cleanup self` | `--yes`, `--remove-package`, `--purge-bootstrapped-python`, `--no-registry`, `--json` | Full user-account cleanup of AuraSeed data, mvenvs, registry, and env vars. |

---

## MCP Tool Mapping (MCP -> CLI)

| MCP Tool | Underlying CLI Invocation |
| :--- | :--- |
| `discover_environments` | `auraseed discover --adapter ... --json` |
| `list_mvenvs` | `auraseed mvenv list --json` |
| `get_mvenv_info` | `auraseed mvenv info <name> --json` |
| `get_mvenv_activation` | `auraseed mvenv activate <name> --shell ... --json` |
| `create_mvenv` | `auraseed mvenv create <name> ... --json` |
| `run_in_mvenv` | `auraseed mvenv python <name> --json -- ...` or `auraseed mvenv run <name> --json -- ...` |
| `install_mvenv_packages` | `auraseed mvenv install <name> ... --json` |
| `verify_mvenv` | `auraseed mvenv verify <name> --json` |
| `merge_mvenvs` | `auraseed mvenv merge <src...> --target <t> --json` |
| `delete_mvenv` | `auraseed mvenv delete <name> --json` |

---

## Attaching AuraSeed as an MCP Server

### Option 1: Stdio Transport (Local Agent / IDE)

In `~/.gemini/config/mcp_config.json`:

```json
{
  "mcpServers": {
    "auraseed": {
      "command": "C:/dev/auraseed/.bootstrapped_python/python.exe",
      "args": ["-m", "auraseed", "serve", "--mcp"],
      "env": {
        "PYTHONPATH": "C:/dev/auraseed"
      }
    }
  }
}
```

### Option 2: Streamable HTTP Transport

Start the HTTP daemon (`python -m auraseed serve --port 7099`), then configure:

```json
{
  "mcpServers": {
    "auraseed-http": {
      "url": "http://127.0.0.1:7099/mcp"
    }
  }
}
```
