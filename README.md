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
- **Sovereign Environments**: Creates virtual environments that sever dynamic dependencies on the host runtime. If the host Python is uninstalled, your AuraSeed environment survives.
- **Cross-Platform Registry**: Automatically registers seeded environments in user-space (e.g., PEP 514 on Windows) for instant IDE discovery.
- **Thick-Client Adapters**: Built-in logic to discover embedded Python runtimes inside applications like ArcGIS Pro and QGIS.

## Documentation
- [Architecture Guide](docs/architecture.md): Deep dive into Operational Sovereignty and Host Isolation.
- [Integration Guide](docs/integration_guide.md): How to embed AuraSeed into your own CI/CD pipelines or parent applications.
