"""
Mod loaders - Forge, NeoForge, Fabric, Quilt via mll's unified mod_loader
module (8.0+), so all four loaders install through the same code path.
"""
import inspect
import os
import re
import shutil

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
        if (mc_version in vid.split("-")
            or (loader_id == "neoforge" and re.fullmatch(r"neoforge-\d+\.\d+\.\d+", vid)
                and vid.split("-", 1)[1].rsplit(".", 1)[0] in
                (mc_version, mc_version.removeprefix("1."))))
        and pattern.search(vid.lower())
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


def loader_java(mc_version: str, loader_id: str = "") -> str:
    """The Java a loader INSTALLER runs under, or a readable error.

    Every mll loader (fabric/quilt/forge/neoforge) installs by downloading an
    installer jar and EXECUTING it. mll 8.0 silently falls back to the bare
    command "java" when the caller doesn't pass one, so on a Windows machine
    with no Java on PATH - which is most end users, since Cubeon ships no JRE
    - installing Fabric died with exactly:

        FileNotFoundError: [WinError 2] The system cannot find the file specified

    surfaced raw under the download button (the 2026-09-24 user report). So the
    Java is resolved HERE with the same logic that starts the game (Settings
    path -> system java -> JAVA_HOME -> every JVM on the machine, lowest
    sufficient major) and is verified to EXIST *and* to be new enough before
    the installer ever sees it - see the too-old comment below the resolution.
    """
    # Imported lazily: launch.py pulls in mods/csl/skins, and those import this
    # module. Same pattern as the config read in modpacks._curseforge_api_key.
    from .config import load_config
    from .launch import find_java_for_version, required_java_major, java_major_version
    try:
        configured = (load_config() or {}).get("java_path") or None
    except Exception:
        configured = None
    try:
        java = find_java_for_version(mc_version, configured)
    except Exception:
        java = None

    try:
        required = required_java_major(mc_version)
    except Exception:
        required = 17

    # An installer is EXECUTED, so it dies on a too-old JVM with a raw
    # UnsupportedClassVersionError rather than a Minecraft error. Existence is
    # therefore not enough: find_java_for_version deliberately falls back to a
    # too-old Java (so LAUNCH can surface Minecraft's own clearer error), and
    # that fallback used to sail through this os.path.isfile() check and get
    # handed straight to the loader. An unprobeable binary (major is None -
    # a path we can't run, e.g. a stub) is still accepted, as before.
    too_old = None
    if java and (os.path.isfile(java) or shutil.which(java)):
        try:
            probed = java_major_version(java)
        except Exception:
            probed = None
        if probed is None or probed >= required:
            return java
        too_old = probed

    # Nothing usable: find_java_for_version has nothing to fall back to, so say
    # it plainly. Mention JAVA_HOME because it - along with Settings and PATH -
    # is now one of the three places a Java is picked up from, and it is the one
    # an affected user most likely has set and was being ignored.
    label = SUPPORTED_LOADERS.get(loader_id, "mod loader")
    detail = (f" Only Java {too_old} was found, which is too old for "
              f"{mc_version}.") if too_old is not None else ""
    raise RuntimeError(
        f"Java {required}+ wasn't found, so the {label} installer can't run. "
        f"Install a Java {required} runtime (Temurin/Adoptium is fine), set the "
        f"path in Settings, or point JAVA_HOME at it, then try again.{detail}")


def install_mod_loader(loader_id: str, mc_version: str, progress_cb, status_cb, max_cb) -> str:
    """Installs the given loader (fabric/quilt/forge/neoforge) for mc_version
    and returns the resulting launchable version id. For 'vanilla' this is
    just install_version(). Uses the id the library reports and confirms it
    with a before/after diff, since the exact resulting id format varies per
    loader."""
    if loader_id == "vanilla" or loader_id not in SUPPORTED_LOADERS:
        install_version(mc_version, progress_cb, status_cb, max_cb)
        return mc_version

    before = {v["id"] for v in get_installed_versions()}

    callback = {"setStatus": status_cb, "setProgress": progress_cb, "setMax": max_cb}
    loader = mll.mod_loader.get_mod_loader(loader_id)
    # Resolve Java BEFORE the download starts: failing here is instant and the
    # message is actionable, versus a half-finished install and a bare WinError.
    java = loader_java(mc_version, loader_id)

    # mll >= 8: install(mc, dir, *, loader_version=None, callback=None,
    # java=None) and it RETURNS the installed version id. `java` is passed
    # explicitly (see loader_java) and the loader version is pinned to the
    # newest stable one so the result is predictable; the signature check keeps
    # this working if the library's shape ever changes again.
    kwargs = {"callback": callback, "java": java}
    try:
        if "loader_version" in inspect.signature(loader.install).parameters:
            kwargs["loader_version"] = loader.get_latest_loader_version(mc_version)
    except Exception:
        pass  # no version list (or an older API): let the library choose
    reported = loader.install(mc_version, MINECRAFT_DIR, **kwargs)

    after = get_installed_versions()
    by_id = {v["id"]: v for v in after}
    new_ids = [v["id"] for v in after if v["id"] not in before]
    # The library's own answer first - it knows the exact id format; the
    # before/after diff is the fallback for shapes it didn't report.
    candidates = ([reported] if isinstance(reported, str) and reported else []) + new_ids
    for vid in candidates:
        if vid not in by_id:
            continue
        if by_id[vid].get("incomplete"):
            # A loader install is tiny (one json), so an incomplete one
            # means the net died mid-write. Don't return a version id the
            # UI will mark installed - the scan already flagged it, so
            # surface that instead. (The base MC version install this
            # builds on is verified separately by install_version.)
            raise RuntimeError(
                f"The {loader_id} install didn't finish (network "
                "interrupted). Try again once you're back online.")
        return vid
    for vid in new_ids:
        return vid
    # Nothing new appeared (e.g. already installed) - best-effort match.
    for v in after:
        if loader_id in v["id"].lower() and mc_version in v["id"]:
            return v["id"]
    return mc_version


def install_fabric(mc_version: str, progress_cb, status_cb, max_cb) -> str:
    """Kept for backward compat - installs Fabric specifically."""
    return install_mod_loader("fabric", mc_version, progress_cb, status_cb, max_cb)
