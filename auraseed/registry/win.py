import winreg
from auraseed.registry.base import BaseOSRegistryAdapter

class WindowsRegistryAdapter(BaseOSRegistryAdapter):
    """
    Windows PEP 514 (HKCU\\Software\\Python\\PythonCore) and HKCU\\Environment writer.
    """
    def register_environment(self, env_name: str, env_path: str) -> None:
        try:
            key_path = rf"Software\Python\PythonCore\AuraSeed\Environments\{env_name}"
            key = winreg.CreateKey(winreg.HKEY_CURRENT_USER, key_path)
            
            install_path_key = winreg.CreateKey(key, "InstallPath")
            winreg.SetValue(install_path_key, "", winreg.REG_SZ, env_path)
            winreg.CloseKey(install_path_key)
            winreg.CloseKey(key)

            env_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS)
            winreg.SetValueEx(env_key, f"AURASEED_ENV_{env_name.upper()}", 0, winreg.REG_SZ, env_path)
            winreg.CloseKey(env_key)
        except OSError:
            pass

    def unregister_environment(self, env_name: str) -> None:
        try:
            key_path = rf"Software\Python\PythonCore\AuraSeed\Environments\{env_name}"
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path + r"\InstallPath")
            except OSError:
                pass
            try:
                winreg.DeleteKey(winreg.HKEY_CURRENT_USER, key_path)
            except OSError:
                pass

            try:
                with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment", 0, winreg.KEY_ALL_ACCESS) as env_key:
                    winreg.DeleteValue(env_key, f"AURASEED_ENV_{env_name.upper()}")
            except OSError:
                pass
        except OSError:
            pass

