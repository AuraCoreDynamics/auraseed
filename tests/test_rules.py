import unittest
from pathlib import Path
from auraseed.models import DiscoveredEnvironment
from auraseed.governance.rules import LatestVersionStrategy, VersionSpecStrategy, parse_semver

class TestGovernanceRules(unittest.TestCase):
    def setUp(self):
        self.env1 = DiscoveredEnvironment(
            id="1", name="Env 1", executable=Path("/env1"), version="3.9.12", source_type="test", site_packages=[], metadata={}
        )
        self.env2 = DiscoveredEnvironment(
            id="2", name="Env 2", executable=Path("/env2"), version="3.11.8", source_type="test", site_packages=[], metadata={}
        )
        self.env3 = DiscoveredEnvironment(
            id="3", name="Env 3", executable=Path("/env3"), version="3.10.4", source_type="test", site_packages=[], metadata={}
        )
        self.envs = [self.env1, self.env2, self.env3]

    def test_parse_semver(self):
        self.assertEqual(parse_semver("3.11.8"), (3, 11, 8))

    def test_latest_version_strategy(self):
        strategy = LatestVersionStrategy()
        selected = strategy.select(self.envs)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.version, "3.11.8")

    def test_version_spec_strategy_exact(self):
        strategy = VersionSpecStrategy("==3.10.4")
        selected = strategy.select(self.envs)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.version, "3.10.4")
        
    def test_version_spec_strategy_range(self):
        strategy = VersionSpecStrategy(">=3.9,<3.11")
        selected = strategy.select(self.envs)
        self.assertIsNotNone(selected)
        self.assertEqual(selected.version, "3.10.4")

if __name__ == "__main__":
    unittest.main()
