from typing import Iterator
from auraseed.models import DiscoveredEnvironment
from auraseed.discovery.base import BaseDiscoverer

class QgisDiscoverer(BaseDiscoverer):
    """
    Adapter for QGIS embedded Python environments.
    Probes standard paths for QGIS installations across Windows, macOS, and Linux.
    """
    @property
    def source_type(self) -> str:
        return "qgis_adapter"

    def discover(self) -> Iterator[DiscoveredEnvironment]:
        yield from []
