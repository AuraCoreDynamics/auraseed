# AuraSeed

**Zero-privilege Python runtime discovery, capability probing, and sovereign environment (`mvenv`) seeding engine.**

AuraSeed (`v1.1.1`) is a zero-dependency (`dependencies = []`), cross-platform Python library and CLI tool focused strictly on:
- Auto-discovering existing Python runtimes across Windows Registry (PEP 514), Linux/macOS system locations, modern toolchain managers (`uv`, `pixi`, `pyenv`/`pyenv-win`, `hatch`, `pdm`, `scoop`, `winget`, Visual Studio Shared), and embedded application runtimes (`ArcGIS Pro`, `QGIS`, `OSGeo4W`, `Blender`, `FreeCAD`).
- Isolated capability probing (`python -I -c ...`) and atomic mtime/size-keyed discovery caching with multi-criteria scoring.
- Creating and managing sovereign, relocatable virtual environments (`mvenv`s) without administrative privileges.
- Exposing local/grid MVenv REST + MCP endpoints (`/api/v1/mvenv*`, `/api/v1/discovery`, `/mcp`) and the composable Tkinter `MvenvManagerPanel`.

> **Note:** Application packaging, catalog management, and application deployment have moved to [`aurasprout`](../aurasprout), which consumes `auraseed` as a runtime dependency while `auraseed` remains completely decoupled.

## Quick Start

```powershell
# Windows (PowerShell)
.\auraseed.ps1 --help
```

```bash
# macOS / Linux
./auraseed.sh --help
```

## Runtime Discovery & Capability Probing CLI

```bash
# Discover host base interpreters and existing mvenvs
python -m auraseed discover --json

# Run deep isolated capability probing (-I) and score candidates
python -m auraseed discover --json --probe

# Require specific modules or pre-installed packages when scoring
python -m auraseed discover --json --probe --require-module ssl --require-package numpy

# Discover via a specific adapter subset (including toolchains / embedded_apps)
python -m auraseed mvenv discover --adapter toolchains --probe --json
```

## MVenv Management CLI

```bash
# List all cataloged mvenvs
python -m auraseed mvenv list --json

# Create a sovereign mvenv (auto-discovery + capability score or version spec)
python -m auraseed mvenv create data-science --packages numpy pandas
python -m auraseed mvenv create py312-env --spec ">=3.11" --adapter all --json

# Inspect mvenv details, activation commands, and verification
python -m auraseed mvenv info data-science --json
python -m auraseed mvenv activate data-science --json
python -m auraseed mvenv verify data-science --json

# Execute Python or arbitrary commands isolated inside an mvenv
python -m auraseed mvenv python data-science --json -- -c "import sys; print(sys.executable)"
python -m auraseed mvenv run data-science --json -- pytest -q

# Merge multiple mvenvs to consolidate shared dependencies
python -m auraseed mvenv merge env-a env-b --target shared-env --delete-sources

# Export / import portable bundles (Tar-Slip & symlink validated)
python -m auraseed mvenv export data-science --out data-science.tar.gz
python -m auraseed mvenv import data-science.tar.gz --name data-science

# Peer-to-peer mvenv transfer with another AuraSeed HTTP node
python -m auraseed p2p push http://127.0.0.1:7099 data-science
python -m auraseed p2p pull http://127.0.0.1:7099 data-science

# Standalone lifecycle & full user cleanup (apps, mvenvs, registry, HKCU env, PATH)
python -m auraseed install-self --add-to-path --json
python -m auraseed cleanup app <legacy_app_name> --json
python -m auraseed cleanup self --yes --json
```

### Key Environment Variables
- `AURASEED_MVENV_ROOT` / `AURAGRID_MVENV_ROOT`: Override the active mvenv catalog root (discovery cache defaults to `<root>/.discovery_cache.json` when using a custom root, or `~/.auraseed/discovery_cache.json`).
- `AURASEED_DISCOVERY_CACHE`: Explicit path override for the interpreter discovery cache file.
- `AURASEED_BIND_HOST` / `AURASEED_PORT` / `AURASEED_URL`: Server bind host/port (defaults `127.0.0.1:7099`) and `AuraSeedClient` target URL.
- `AURASEED_HOME` / `AURASEED_STANDALONE_DIR`: Standalone installation paths set on Windows user environment.
- `AURASEED_BOOTSTRAP_CONFIG` / `AURASEED_DEBUG`: Unattended `bootstrap.json` override and HTTP request debug logging (`=1`).

## Agent Skill (`skills/auraseed-mvenv`)

An agent skill is included at [`skills/auraseed-mvenv/SKILL.md`](skills/auraseed-mvenv/SKILL.md) (auto-registered via [`.agents/skills.json`](.agents/skills.json)) for mvenv discovery, creation, verification, and execution.

## Running the MVenv API & MCP Server

```bash
# Start REST API server (binds 127.0.0.1:7099 by default; configure via AURASEED_BIND_HOST / AURASEED_PORT)
python -m auraseed serve --port 7099

# Run as stdio MCP server (delegates tool calls through the AuraSeed CLI)
python -m auraseed serve --mcp

# Run as an AuraGrid Managed Application Service
python -m auraseed serve --port 7099 --mas
```

### REST API Endpoints & OpenAPI Specification
The server API adheres to [`openapi.yaml`](auraseed/openapi.yaml) and [`openapi.json`](auraseed/openapi.json):
- `POST /mcp` — Streamable HTTP Model Context Protocol (MCP) JSON-RPC 2.0 endpoint
- `GET /health` — Service health probe, runtime info, and mvenv counts
- `GET /api/v1/openapi.json` / `/api/v1/openapi.yaml` — OpenAPI 3.0.3 specification
- `GET /api/v1/discovery` — Discover host Python runtimes (`?probe=true`, `?cache=true` / `?use_cache=true`, `?adapter=all`)
- `GET /api/v1/mvenv` — List all cataloged virtual environments
- `GET /api/v1/mvenv/{name}` — Retrieve metadata for a specific environment
- `POST /api/v1/mvenv` — Create and catalog a new environment
- `POST /api/v1/mvenv/{name}/install` — Install packages into an environment
- `GET /api/v1/mvenv/{name}/verify` — Verify executable health
- `POST /api/v1/mvenv/merge` — Merge multiple mvenvs (`repoint_callback` supported in-process)
- `GET /api/v1/mvenv/{name}/bundle` — Download `.tar.gz` bundle for P2P distribution
- `POST /api/v1/mvenv/bundle` — Upload and import a `.tar.gz` bundle
- `DELETE /api/v1/mvenv/{name}` — Remove an environment

## Desktop MVenv Manager & Composable Panel

Launch the standalone Tkinter MVenv Manager:

```bash
python -m auraseed gui
```

Embed `MvenvManagerPanel` in external tools (e.g., AuraSprout):

```python
from auraseed.gui import MvenvManagerPanel

panel = MvenvManagerPanel(parent_frame, repoint_callback=my_repoint_fn)
```

## Documentation
- [Architecture Guide](docs/architecture.md): Deep dive into Operational Sovereignty and Host Isolation.
- [Integration Guide](docs/integration_guide.md): How to embed AuraSeed into your own CI/CD pipelines or parent applications.
