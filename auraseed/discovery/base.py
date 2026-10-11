import abc
from typing import Iterator
from auraseed.models import DiscoveredEnvironment

class BaseDiscoverer(abc.ABC):
    """
    Abstract strategy interface for Python runtime discovery.
    """
    
    @property
    @abc.abstractmethod
    def source_type(self) -> str:
        """
        Returns the category identifier for this discoverer (e.g., 'windows_registry', 'arcpro').
        """
        pass

    @abc.abstractmethod
    def discover(self) -> Iterator[DiscoveredEnvironment]:
        """
        Yields DiscoveredEnvironment instances for each valid Python runtime found.
        """
        pass
