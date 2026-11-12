# AuraSeed Integration Guide

## Embedding AuraSeed into Parent Applications

AuraSeed is designed to be embedded in automation pipelines, CI/CD routines, and custom thick-client installers. Because AuraSeed operates entirely in user-space and has zero dependencies, integrating it is trivial.

### Step 1: Bootstrapping

Do not invoke `python -m auraseed` directly unless you are absolutely certain of the Python environment's origin. Instead, always use the OS-native bootstrappers provided in the root of the repository:
- `auraseed.bat` (Legacy Windows CMD)
- `auraseed.ps1` (Modern Windows PowerShell)
- `auraseed.sh` (macOS / Linux)

Example CI/CD execution:
```bash
# Clone the seed engine
git clone https://github.com/AuraCoreDynamics/auraseed.git

# Execute the native bootstrapper
./auraseed/auraseed.sh --adapter arcpro --dest ~/.auraseed/venvs/arcpro-sovereign
```

### Step 2: Interpreting the Registry

AuraSeed automatically exposes the generated virtual environments to the host OS.
If you are developing a downstream application (like an IDE plugin or a pipeline runner), you can discover AuraSeed environments from the host OS registry or `mvenv` catalog:

- **Windows**: `HKCU\Software\Python\PythonCore\AuraSeed\Environments\<name>` (PEP 514) and `HKCU\Environment\AURASEED_ENV_<NAME>`
- **Linux**: `~/.config/auraseed/environments.json`
- **macOS**: `~/.config/auraseed/environments.json` (and `MvenvManager.discover_venvs` also scans `~/Library/Application Support/auraseed/environments.json`)

For `mvenv`-managed environments, `MvenvManager` stores `.catalog.json` inside the active mvenv root (`AURASEED_MVENV_ROOT`, `%LOCALAPPDATA%\AuraGrid\mvenvs`, or `~/.auraseed/mvenvs`) and caches probed host interpreters in `<root>/.discovery_cache.json` (or `~/.auraseed/discovery_cache.json` / `AURASEED_DISCOVERY_CACHE`).

### Step 3: Triggering an Audit

Downstream applications should periodically run the audit API to detect drift in the host system. If a user updates their embedded Python (e.g. updating QGIS to a new major version), AuraSeed will not automatically break your isolated environment, but you may want to prompt the user to re-seed to get the latest features.

```python
from auraseed.governance.audit import audit_host_updates
from auraseed.discovery.manager import DiscoveryManager

manager = DiscoveryManager()
# ... register strategies ...

report = audit_host_updates(
    adapter_name="qgis_adapter",
    discovery_manager=manager,
    known_version_ids=["...old_ids..."]
)

if report.recommend_reseed:
    print(f"Found new versions! {report.new_versions}")
```
