from typing import Iterator
from auraseed.models import DiscoveredEnvironment
from auraseed.discovery.base import BaseDiscoverer

class ArcProDiscoverer(BaseDiscoverer):
    """
    Adapter for ArcGIS Pro Conda/Python environments.
    Probes %LOCALAPPDATA%\\ESRI\\conda\\envs\\* and %PROGRAMFILES%\\ArcGIS\\Pro\\bin\\Python\\envs\\*.
    """
    @property
    def source_type(self) -> str:
        return "arcpro_adapter"

    def discover(self) -> Iterator[DiscoveredEnvironment]:
        yield from []
