# AuraSeed

**Zero-privilege Python runtime discovery and environment seeding engine.**

AuraSeed is a zero-dependency, cross-platform Python library and CLI tool designed to auto-discover existing Python runtimes on a host system and seed sovereign, isolated virtual environments without requiring administrative privileges.

## The Bootstrapping Solution
AuraSeed is written in Python, creating a chicken-and-egg problem: how do you run a Python-based discovery engine if you don't know where Python is? 

We solve this using **Native OS Bootstrappers**:
- `auraseed.bat` and `auraseed.ps1` (Windows)
- `auraseed.sh` (Linux/macOS)

These native shell scripts perform a fast, rudimentary "Level 0" scan (checking `%PATH%`, system registries, and common installation directories) to locate a base Python executable capable of launching the full AuraSeed engine.

## Quick Start

You do not need to install AuraSeed via pip. Simply clone the repository and invoke the bootstrapper for your OS:

### Windows (PowerShell)
```powershell
.\auraseed.ps1 --help
```

### macOS / Linux
```bash
./auraseed.sh --help
```

## Features
- **Zero Dependencies**: Relies entirely on the Python standard library.
- **First-Class MVenvs**: Full lifecycle cataloging, verification, and management of Managed Virtual Environments (`mvenvs`).
- **Sovereign Isolation**: Creates virtual environments that sever dynamic dependencies on the host runtime. If the host Python is uninstalled, your AuraSeed environment survives.
- **HTTP/REST API & Mesh Integration**: Exposes a zero-dependency REST service for IDEs, coding agents, and cluster orchestrators. When hosted on AuraGrid, it is automatically projected as Model Context Protocol (MCP) tools out of the box.
- **P2P Environment Transfer**: Enables heterogeneous cluster nodes without local compilers to pull pre-compiled, sovereign mvenv bundles from peers.

- **AuraGrid MAS Integration**: Detects active grid contexts and acts as an autonomous Managed Application Service under AuraGrid's `MasOrchestrator`.
- **Cross-Platform Registry**: Automatically registers seeded environments in user-space (e.g., PEP 514 on Windows) for instant IDE discovery.
- **Thick-Client Adapters**: Built-in logic to discover embedded Python runtimes inside applications like ArcGIS Pro and QGIS.

## MVenv Management CLI

AuraSeed provides commands to discover, create, execute in, and catalog managed environments (all supporting `--json` for structured agent/MCP consumption):

```bash
# Discover host base interpreters and existing mvenvs (including OS registry)
python -m auraseed discover --json
python -m auraseed mvenv discover --adapter all --json

# List all cataloged mvenvs
python -m auraseed mvenv list
python -m auraseed mvenv list --json

# Create a sovereign mvenv (auto-discovery, version spec, adapter, or explicit base)
python -m auraseed mvenv create data-science --packages numpy pandas mcp
python -m auraseed mvenv create py312-env --spec ">=3.11" --adapter all --json

# Inspect mvenv details, activation commands, and verification
python -m auraseed mvenv info data-science --json
python -m auraseed mvenv activate data-science --json
python -m auraseed mvenv verify data-science --json

# Execute Python or arbitrary commands isolated inside an mvenv
python -m auraseed mvenv python data-science --json -- -c "import sys; print(sys.executable)"
python -m auraseed mvenv run data-science --json -- pytest -q

# Install additional packages
python -m auraseed mvenv install data-science fastmcp scikit-learn

# Export / import portable bundles
python -m auraseed mvenv export data-science --out data-science.tar.gz
python -m auraseed mvenv import data-science.tar.gz --name data-science
```

## Agent Skill (`skills/auraseed-mvenv`)

An agent skill is included at [`skills/auraseed-mvenv/SKILL.md`](skills/auraseed-mvenv/SKILL.md) (auto-registered via [`.agents/skills.json`](.agents/skills.json)). It guides AI coding agents through discovering, creating, verifying, and running workloads in `mvenv`s via the CLI in alignment with AuraSeed's `MCP -> CLI -> Python API` architecture.

## Running the API & MCP Server

Run AuraSeed as a standalone daemon or background MAS service:

```bash
# Start REST API server (also serves Streamable HTTP MCP at POST /mcp) on port 7099
python -m auraseed serve --port 7099

# Run as stdio MCP server (delegates tool calls through the AuraSeed CLI)
python -m auraseed serve --mcp

# Run as an AuraGrid Managed Application Service
python -m auraseed serve --port 7099 --mas
```

### REST API Endpoints & OpenAPI Specification
The server API adheres to an independent, version-controlled OpenAPI 3.0 specification ([`openapi.yaml`](file:///C:/dev/auraseed/auraseed/openapi.yaml) and [`openapi.json`](file:///C:/dev/auraseed/auraseed/openapi.json)) served live from the daemon:
- `POST /mcp` — Streamable HTTP Model Context Protocol (MCP) JSON-RPC 2.0 endpoint
- `GET /health` — Service health probe, runtime info, and catalog counts
- `GET /api/v1/openapi.json` — Version-controlled OpenAPI specification (JSON)
- `GET /api/v1/openapi.yaml` — Version-controlled OpenAPI specification (YAML)
- `GET /api/v1/apps` — List all published catalog applications
- `GET /api/v1/apps/{name}` — Retrieve metadata for an application in the catalog
- `POST /api/v1/apps` — Deploy/publish an application package (.zip or .tar.gz bundle)
- `GET /api/v1/apps/{name}/download` — Download binary installer bundle
- `DELETE /api/v1/apps/{name}` — Remove an application from the catalog
- `GET /api/v1/mvenv` — List all cataloged virtual environments
- `GET /api/v1/mvenv/{name}` — Retrieve metadata for a specific environment
- `POST /api/v1/mvenv` — Create and catalog a new environment
- `POST /api/v1/mvenv/{name}/install` — Install packages into an environment
- `GET /api/v1/mvenv/{name}/verify` — Verify executable health
- `POST /api/v1/mvenv/merge` — Merge multiple mvenvs into a single environment to reclaim disk space
- `GET /api/v1/mvenv/{name}/bundle` — Download `.tar.gz` bundle for P2P distribution
- `POST /api/v1/mvenv/bundle` — Upload and import a `.tar.gz` bundle
- `DELETE /api/v1/mvenv/{name}` — Remove an environment
- `GET /api/v1/discovery` — Scan and discover host Python installations

## Desktop GUI: App & Environment Hub

Launch the zero-dependency Tkinter desktop management hub to manage apps, catalogs, and virtual environments with a native visual interface:

```bash
python -m auraseed gui
```

- **Catalog Browser**: Browse and search applications from one or more attached AuraSeed servers. Install with 1-click in either isolated sovereign mode or shared mvenv mode.
- **Installed Apps Manager**: Launch installed apps, inspect locations, switch/re-link mvenvs, or uninstall.
- **MVenv Manager & Disk Saver**: Inspect local environments and packages, create new mvenvs, verify health, and **merge multiple environments** into a consolidated mvenv to reclaim hundreds of megabytes or gigabytes of disk space.
- **Multi-Catalog Connectivity**: Attach, detach, and switch between multiple local, staging, or production catalog servers.

## Application Packaging & Deployment CLI

Package your local Python application and deploy it to any AuraSeed-compliant OpenAPI server:

```bash
# Package application into a standalone installer bundle (.zip)
python -m auraseed package-app ./my-app --out ./dist --zip

# Package and deploy directly to an AuraSeed server
python -m auraseed deploy ./my-app --server http://localhost:7099

# Query apps on a remote or local catalog
python -m auraseed catalog list --server http://localhost:7099

# Download an application installer package from the catalog
python -m auraseed catalog download my-app --out ./my-app-bundle.zip

# Manage attached catalog endpoints
python -m auraseed catalog sources
python -m auraseed catalog attach http://192.168.1.50:7099 --label "Team Staging"
```

## MVenv Merging (Consolidating & Saving Disk Space)

When running multiple apps, create or consolidate them into a shared mvenv to avoid duplicate Python runtimes, DLLs, and large packages:

```bash
# Merge multiple environments into a consolidated mvenv and prune sources
python -m auraseed mvenv merge app1-env app2-env data-env --target shared-apps --delete-sources
```

Installed applications using any of the source environments are automatically re-pointed to launch with the merged target environment.

## Python Client SDK

A zero-external-dependency SDK using Python standard library `urllib` is included:

```python
from auraseed.client import AuraSeedClient

client = AuraSeedClient(base_url="http://localhost:7099")

# 1. Inspect server health & OpenAPI spec
health = client.get_health()
spec = client.get_openapi(format="json")

# 2. Deploy an application directory (auto-packages into bundle)
deployed = client.deploy_app("./projects/bijou")
print(f"Deployed {deployed['name']} v{deployed['version']}")

# 3. List and download applications
apps = client.list_apps(query="bijou")
bundle_file = client.download_app("bijou", "./bijou-bundle.zip")

# 4. Consolidate and merge virtual environments
result = client.merge_mvenvs(
    sources=["bijou-env", "analysis-env"],
    target="shared-runtime",
    delete_sources=True
)
print(f"Reclaimed {result['reclaimed_bytes'] / (1024*1024):.1f} MB!")
```

## P2P Virtual Environment Distribution

Worker nodes without local Python toolchains can pull pre-built sovereign environments from peer nodes:

```bash
# Pull an environment from a build peer
python -m auraseed p2p pull http://10.0.0.5:7099 data-science

# Push a locally compiled environment to a peer
python -m auraseed p2p push http://10.0.0.12:7099 data-science
```

## Documentation
- [Architecture Guide](docs/architecture.md): Deep dive into Operational Sovereignty and Host Isolation.
- [Integration Guide](docs/integration_guide.md): How to embed AuraSeed into your own CI/CD pipelines or parent applications.

