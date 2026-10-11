import abc
from pathlib import Path
from typing import List

class BaseProvisioner(abc.ABC):
    """
    Abstract interface for package installation in seeded environments.
    """
    @abc.abstractmethod
    def install_packages(self, venv_path: Path, packages: List[str]) -> None:
        """
        Executes package installation logic (emits standard pip execution arguments).
        """
        pass
