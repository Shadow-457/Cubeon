"""Read-only collection counts used by Account badges, never by tab navigation."""
import os


def _names(directory):
    try:
        return os.listdir(directory)
    except OSError:
        return []


def _jars(directory):
    return sum(name.endswith((".jar", ".jar.disabled")) for name in _names(directory))


def collect_library():
    from .paths import PROFILES_DIR, RESOURCEPACKS_DIR, SHADERPACKS_DIR, SERVERS_DIR
    from .versions import get_installed_versions
    from .modpacks import list_installed_modpacks
    from .skins import list_custom_skins
    from .capes import list_custom_capes

    return {
        "versions": len(get_installed_versions()),
        "mods": sum(_jars(os.path.join(PROFILES_DIR, name)) for name in _names(PROFILES_DIR)
                    if "-" in name and os.path.isdir(os.path.join(PROFILES_DIR, name))),
        "packs": len(list_installed_modpacks()),
        "content": sum(name.endswith(".zip") for directory in (RESOURCEPACKS_DIR, SHADERPACKS_DIR)
                       for name in _names(directory)),
        "plugins": sum(_jars(os.path.join(SERVERS_DIR, name, "plugins")) for name in _names(SERVERS_DIR)),
        "skins": len(list_custom_skins()),
        "capes": len(list_custom_capes()),
    }
