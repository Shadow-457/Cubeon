"""
Mod loaders - Forge, NeoForge, Fabric, Quilt via mll's unified mod_loader
module (8.0+), so all four loaders install through the same code path.
"""
import re

# minecraft_launcher_lib costs ~116ms to import (it pulls in requests);
# nothing here needs it until the user actually installs/launches, so it
# is imported on first use. `mll.<anything>` is unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
mll = LazyModule("minecraft_launcher_lib")

from .paths import MINECRAFT_DIR
from .versions import get_installed_versions, install_version
from . import local_cache

SUPPORTED_LOADERS = {
    "vanilla": "Vanilla",
    "fabric": "Fabric",
    "quilt": "Quilt",
    "forge": "Forge",
    "neoforge": "NeoForge",
}

# Loader ids that actually load mods. Vanilla (or anything not in this set)
# never does - this is the single source of truth other modules should
# check against instead of re-deriving their own loader whitelist.
MOD_CAPABLE_LOADERS = ("fabric", "quilt", "forge", "neoforge")


def is_loader_supported(loader_id: str, mc_version: str) -> bool:
    if loader_id == "vanilla":
        return True
    cached = local_cache.get("loader_support", {"loader": loader_id, "version": mc_version}, max_age=604800)
    if cached is not None:
        return bool(cached)
    try:
        loader = mll.mod_loader.get_mod_loader(loader_id)
        supported = loader.is_minecraft_version_supported(mc_version)
        return local_cache.set("loader_support", {"loader": loader_id, "version": mc_version}, bool(supported))
    except Exception:
        return False


def is_fabric_supported(mc_version: str) -> bool:
    return is_loader_supported("fabric", mc_version)


def find_installed_loader_version(installed_ids, loader_id: str, mc_version: str) -> str | None:
    """Given the set of installed version ids, returns the one that matches
    mc_version and was installed with loader_id, or None. Matches the loader
    name as a whole word/segment (not a bare substring) so e.g. "forge"
    doesn't false-match an id containing "neoforge".

    Ordering matters and used to be absent. `installed_ids` is a set, so
    iterating it yields an arbitrary order that varies between runs (string
    hashing is randomized per process). With more than one candidate - say a
    real `fabric-loader-0.19.3-1.21.11` alongside an imported TLauncher pack
    named `...Boosted FPS Fabric-1.21.11-1.6.7` - the launcher would pick a
    *different* one on different runs, so the same Play click launched the real
    profile sometimes and a third-party pack other times.

    So candidates are now sorted deterministically, preferring the loader's own
    canonical profile (`<loader>-loader-<...>`, which is what this launcher
    installs) over an imported pack that merely mentions the loader in its name.
    """
    if loader_id == "vanilla":
        return mc_version if mc_version in installed_ids else None

    pattern = re.compile(rf"(?<![a-z]){re.escape(loader_id)}(?![a-z])")
    candidates = [
        vid for vid in installed_ids
        if mc_version in vid and pattern.search(vid.lower())
    ]
    if not candidates:
        return None

    def rank(vid: str):
        low = vid.lower()
        # 0 = the profile shape mll/this launcher creates, e.g.
        # "fabric-loader-0.19.3-1.21.11" or "neoforge-21.1.99". 1 = anything
        # else that happens to contain the loader name.
        canonical = 0 if low.startswith(f"{loader_id}-") else 1
        # Prefer an id that is *only* the loader and versions over one carrying
        # a pack's display name, then break remaining ties alphabetically so the
        # result is stable across runs.
        return (canonical, len(vid), vid)

    return min(candidates, key=rank)


def install_mod_loader(loader_id: str, mc_version: str, progress_cb, status_cb, max_cb) -> str:
    """Installs the given loader (fabric/quilt/forge/neoforge) for mc_version
    and returns the resulting launchable version id. For 'vanilla' this is
    just install_version(). Works by diffing installed versions before/after
    since the exact resulting id format varies per loader."""
    if loader_id == "vanilla" or loader_id not in SUPPORTED_LOADERS:
        install_version(mc_version, progress_cb, status_cb, max_cb)
        return mc_version

    before = {v["id"] for v in get_installed_versions()}

    callback = {"setStatus": status_cb, "setProgress": progress_cb, "setMax": max_cb}
    loader = mll.mod_loader.get_mod_loader(loader_id)
    loader.install(mc_version, MINECRAFT_DIR, callback=callback)

    after = get_installed_versions()
    new_ids = [v["id"] for v in after if v["id"] not in before]
    for vid in new_ids:
        if mc_version in vid:
            return vid
    if new_ids:
        return new_ids[0]
    # Nothing new appeared (e.g. already installed) - best-effort match.
    for v in after:
        if loader_id in v["id"].lower() and mc_version in v["id"]:
            return v["id"]
    return mc_version


def install_fabric(mc_version: str, progress_cb, status_cb, max_cb) -> str:
    """Kept for backward compat - installs Fabric specifically."""
    return install_mod_loader("fabric", mc_version, progress_cb, status_cb, max_cb)
