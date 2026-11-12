from typing import Dict, List, Optional, Tuple

from auraseed.discovery.base import BaseDiscoverer
from auraseed.discovery.cache import DiscoveryCache
from auraseed.discovery.prober import RuntimeCapabilityProber, is_windows_store_stub
from auraseed.governance.rules import CapabilityScoreStrategy
from auraseed.models import DiscoveredEnvironment


class DiscoveryManager:
    """
    Master Discovery Engine & Strategy Registry.
    Aggregates deduplicated results across multiple installed versions and
    optionally probes and caches runtime capabilities.
    """

    def __init__(self) -> None:
        self._strategies: List[BaseDiscoverer] = []

    def register_strategy(self, strategy: BaseDiscoverer) -> None:
        """
        Registers a new discovery strategy.
        """
        self._strategies.append(strategy)

    def run_discovery(
        self,
        probe_capabilities: bool = False,
        use_cache: bool = False,
        required_modules: Optional[List[str]] = None,
        required_packages: Optional[List[str]] = None,
        prober: Optional[RuntimeCapabilityProber] = None,
        cache: Optional[DiscoveryCache] = None,
    ) -> Dict[str, DiscoveredEnvironment]:
        """
        Runs all registered strategies, filters 0-byte WindowsApps stubs, and
        optionally probes/caches runtime capabilities.
        """
        results: Dict[str, DiscoveredEnvironment] = {}
        active_prober = prober or (RuntimeCapabilityProber() if probe_capabilities else None)
        active_cache = cache or (DiscoveryCache() if (probe_capabilities and use_cache) else None)

        for strategy in self._strategies:
            for env in strategy.discover():
                if is_windows_store_stub(env.executable):
                    continue
                if probe_capabilities and active_prober is not None:
                    cached = None
                    if use_cache and active_cache is not None:
                        cached = active_cache.get(
                            env.executable,
                            required_modules=required_modules,
                            required_packages=required_packages,
                        )
                    if cached is not None:
                        env.capabilities = cached.capabilities
                        if (not env.version or env.version in ("unknown", "3.x")) and cached.version:
                            env.version = cached.version
                    else:
                        active_prober.probe(
                            env,
                            required_modules=required_modules,
                            required_packages=required_packages,
                        )
                        if use_cache and active_cache is not None and not required_modules and not required_packages:
                            active_cache.put(env)
                results[env.id] = env
        return results

    def select_best(
        self,
        min_version: Tuple[int, int] = (3, 10),
        require_ssl: bool = True,
        require_sqlite3: bool = True,
        prefer_packages: Optional[List[str]] = None,
        probe_capabilities: bool = True,
        use_cache: bool = True,
        cache: Optional[DiscoveryCache] = None,
    ) -> Optional[DiscoveredEnvironment]:
        """
        Discovers, probes, and deterministically selects the highest-scoring runtime.
        """
        discovered = self.run_discovery(
            probe_capabilities=probe_capabilities,
            use_cache=use_cache,
            required_packages=prefer_packages,
            cache=cache,
        )
        strategy = CapabilityScoreStrategy(
            min_version=min_version,
            require_ssl=require_ssl,
            require_sqlite3=require_sqlite3,
            prefer_packages=prefer_packages,
        )
        return strategy.select(list(discovered.values()))
