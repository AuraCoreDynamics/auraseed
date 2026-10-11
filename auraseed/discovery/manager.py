from typing import List, Dict
from auraseed.models import DiscoveredEnvironment
from auraseed.discovery.base import BaseDiscoverer

class DiscoveryManager:
    """
    Master Discovery Engine & Strategy Registry.
    Aggregates deduplicated results across multiple installed versions.
    """
    def __init__(self) -> None:
        self._strategies: List[BaseDiscoverer] = []

    def register_strategy(self, strategy: BaseDiscoverer) -> None:
        """
        Registers a new discovery strategy.
        """
        self._strategies.append(strategy)

    def run_discovery(self) -> Dict[str, DiscoveredEnvironment]:
        """
        Runs all registered strategies and deduplicates results based on the DiscoveredEnvironment.id.
        """
        results: Dict[str, DiscoveredEnvironment] = {}
        for strategy in self._strategies:
            for env in strategy.discover():
                results[env.id] = env
        return results
