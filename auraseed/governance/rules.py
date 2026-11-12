import abc
from typing import List, Optional, Tuple
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
                if not (env_tuple >= parse_semver(spec[2:])):
                    return False
            elif spec.startswith("<="):
                if not (env_tuple <= parse_semver(spec[2:])):
                    return False
            elif spec.startswith(">"):
                if not (env_tuple > parse_semver(spec[1:])):
                    return False
            elif spec.startswith("<"):
                if not (env_tuple < parse_semver(spec[1:])):
                    return False
        return True

    def select(self, environments: List[DiscoveredEnvironment]) -> Optional[DiscoveredEnvironment]:
        matching = [e for e in environments if self._matches(e.version)]
        if not matching:
            return None
        return max(matching, key=lambda e: parse_semver(e.version))


class CapabilityScoreStrategy(VersionSelectionStrategy):
    """
    Selects the highest-scoring healthy interpreter satisfying minimum version
    and capability constraints (SSL, SQLite3, and preferred preinstalled packages).
    """

    def __init__(
        self,
        min_version: Tuple[int, int] = (3, 10),
        require_ssl: bool = True,
        require_sqlite3: bool = True,
        prefer_packages: Optional[List[str]] = None,
    ) -> None:
        self.min_version = min_version
        self.require_ssl = require_ssl
        self.require_sqlite3 = require_sqlite3
        self.prefer_packages = [p.strip().lower() for p in (prefer_packages or []) if p and p.strip()]

    def _is_eligible(self, env: DiscoveredEnvironment) -> bool:
        ver = parse_semver(env.version)
        if len(ver) >= 2 and ver[:2] < self.min_version:
            return False
        caps = env.capabilities
        if caps is not None:
            if self.require_ssl and not caps.has_ssl:
                return False
            if self.require_sqlite3 and not caps.has_sqlite3:
                return False
        return True

    def _rank_key(self, env: DiscoveredEnvironment) -> tuple:
        caps = env.capabilities
        ver = parse_semver(env.version)
        if caps is None:
            return (0, 0.0, 0, ver, str(env.executable))
        pre_lower = {p.lower() for p in caps.preinstalled_packages}
        pref_hits = sum(1 for p in self.prefer_packages if p in pre_lower)
        return (1, float(caps.composite_score), pref_hits, ver, str(env.executable))

    def select(self, environments: List[DiscoveredEnvironment]) -> Optional[DiscoveredEnvironment]:
        eligible = [e for e in environments if self._is_eligible(e)]
        if not eligible:
            return None
        return max(eligible, key=self._rank_key)


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
