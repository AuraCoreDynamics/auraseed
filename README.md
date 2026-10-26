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

AuraSeed provides commands to create, manage, and catalog managed environments:

```bash
# List all cataloged mvenvs
python -m auraseed mvenv list
python -m auraseed mvenv list --json

# Create a sovereign mvenv with packages
python -m auraseed mvenv create data-science --packages numpy pandas mcp

# Inspect mvenv details and package listing
python -m auraseed mvenv info data-science

# Verify environment executables and health
python -m auraseed mvenv verify data-science

# Install additional packages
python -m auraseed mvenv install data-science fastmcp scikit-learn

# Export an environment as a portable tar.gz bundle
python -m auraseed mvenv export data-science --out data-science.tar.gz

# Import a bundle on another node
python -m auraseed mvenv import data-science.tar.gz --name data-science
```

## Running the API & MCP Server

Run AuraSeed as a standalone daemon or background MAS service:

```bash
# Start REST API server on port 7099
python -m auraseed serve --port 7099

# Run as stdio MCP server for AuraRouter / AuraCode
python -m auraseed serve --mcp

# Run as an AuraGrid Managed Application Service
python -m auraseed serve --port 7099 --mas
```

### REST API Endpoints
- `GET /health` — Service health probe and grid connectivity status
- `GET /api/v1/mvenv` — List all cataloged virtual environments
- `GET /api/v1/mvenv/{name}` — Retrieve metadata for a specific environment
- `POST /api/v1/mvenv` — Create and catalog a new environment
- `POST /api/v1/mvenv/{name}/install` — Install packages into an environment
- `GET /api/v1/mvenv/{name}/verify` — Verify executable health
- `GET /api/v1/mvenv/{name}/bundle` — Download `.tar.gz` bundle for P2P distribution
- `POST /api/v1/mvenv/bundle` — Upload and import a `.tar.gz` bundle
- `DELETE /api/v1/mvenv/{name}` — Remove an environment
- `GET /api/v1/discovery` — Scan and discover host Python installations

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

