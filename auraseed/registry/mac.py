from auraseed.registry.base import BaseOSRegistryAdapter

class MacOSRegistryAdapter(BaseOSRegistryAdapter):
    """
    macOS ~/.zshenv exporter and ~/.local/bin symlinker.
    """
    def register_environment(self, env_name: str, env_path: str) -> None:
        pass

    def unregister_environment(self, env_name: str) -> None:
        pass

