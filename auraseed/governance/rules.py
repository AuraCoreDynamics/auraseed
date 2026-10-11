import abc
from typing import List, Optional
from auraseed.models import DiscoveredEnvironment

class VersionSelectionStrategy(abc.ABC):
    """
    Abstract interface for version selection rules.
    """
    @abc.abstractmethod
    def select(self, environments: List[DiscoveredEnvironment]) -> Optional[DiscoveredEnvironment]:
        pass

def parse_semver(version: str) -> tuple:
    parts = []
    for p in version.split("."):
        try:
            parts.append(int(p))
        except ValueError:
            break
    return tuple(parts)

class LatestVersionStrategy(VersionSelectionStrategy):
    """
    Automatically selects the highest semantic version available.
    """
    def select(self, environments: List[DiscoveredEnvironment]) -> Optional[DiscoveredEnvironment]:
        if not environments:
            return None
        return max(environments, key=lambda e: parse_semver(e.version))

class VersionSpecStrategy(VersionSelectionStrategy):
    """
    Accepts a standard version specifier (e.g., ==3.11.*, >=3.10,<3.12).
    """
    def __init__(self, specifier: str):
        self.specifier = specifier

    def _matches(self, env_version: str) -> bool:
        specs = [s.strip() for s in self.specifier.split(",")]
        env_tuple = parse_semver(env_version)
        for spec in specs:
            if spec.startswith("=="):
                target = spec[2:]
                if target.endswith(".*"):
                    target_tuple = parse_semver(target[:-2])
                    if env_tuple[:len(target_tuple)] != target_tuple:
                        return False
                else:
                    if env_tuple != parse_semver(target):
                        return False
            elif spec.startswith(">="):
                if not (env_tuple >= parse_semver(spec[2:])): return False
            elif spec.startswith("<="):
                if not (env_tuple <= parse_semver(spec[2:])): return False
            elif spec.startswith(">"):
                if not (env_tuple > parse_semver(spec[1:])): return False
            elif spec.startswith("<"):
                if not (env_tuple < parse_semver(spec[1:])): return False
        return True

    def select(self, environments: List[DiscoveredEnvironment]) -> Optional[DiscoveredEnvironment]:
        matching = [e for e in environments if self._matches(e.version)]
        if not matching:
            return None
        return max(matching, key=lambda e: parse_semver(e.version))

class PinnedTargetStrategy(VersionSelectionStrategy):
    """
    Requires an exact match on a previously generated manifest hash or unique ID.
    """
    def __init__(self, target_id: str):
        self.target_id = target_id

    def select(self, environments: List[DiscoveredEnvironment]) -> Optional[DiscoveredEnvironment]:
        for env in environments:
            if env.id == self.target_id:
                return env
        return None

class InteractiveSelectionStrategy(VersionSelectionStrategy):
    """
    Prompts the user via stdout/stdin to select an environment from the discovered list.
    """
    def select(self, environments: List[DiscoveredEnvironment]) -> Optional[DiscoveredEnvironment]:
        if not environments:
            print("No Python environments discovered.")
            return None
            
        print("\nDiscovered Python Environments:")
        print("-" * 60)
        for idx, env in enumerate(environments):
            print(f"[{idx + 1}] {env.name} (Version: {env.version})")
            print(f"    Path: {env.executable}")
            print(f"    Source: {env.source_type}")
        print("-" * 60)
        
        while True:
            try:
                choice = input("Select an environment number (or 'q' to quit): ").strip()
                if choice.lower() == 'q':
                    return None
                    
                idx = int(choice) - 1
                if 0 <= idx < len(environments):
                    return environments[idx]
                else:
                    print(f"Invalid selection. Please choose a number between 1 and {len(environments)}.")
            except ValueError:
                print("Invalid input. Please enter a number.")
            except EOFError:
                return None

class VersionRulesEngine:
    """
    Configurable selection engine to resolve which discovered interpreter to utilize.
    """
    def __init__(self, strategy: VersionSelectionStrategy):
        self.strategy = strategy
        
    def resolve(self, environments: List[DiscoveredEnvironment]) -> Optional[DiscoveredEnvironment]:
        return self.strategy.select(environments)
