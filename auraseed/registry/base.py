import abc

class BaseOSRegistryAdapter(abc.ABC):
    """
    Abstract interface for OS-specific environment registration.
    """
    @abc.abstractmethod
    def register_environment(self, env_name: str, env_path: str) -> None:
        """
        Registers the seeded environment natively in the host OS.
        """
        pass
