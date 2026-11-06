"""
Mod loaders - Forge, NeoForge, Fabric, Quilt via mll's unified mod_loader
module (8.0+), so all four loaders install through the same code path.
"""
import inspect
import os
from .storage import runtime_dir
import re
import shutil
from contextlib import nullcontext

# minecraft_launcher_lib costs ~116ms to import (it pulls in requests);
# nothing here needs it until the user actually installs/launches, so it
# is imported on first use. `mll.<anything>` is unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
mll = LazyModule("minecraft_launcher_lib")

from .paths import MINECRAFT_DIR
from .versions import (get_installed_versions, install_version,
                       _InstallCancelBridge, _PatchedMllDownloads,
                       _DownloadCancelled, _active_install)
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


def get_loader_minecraft_versions(loader_id: str) -> list[str]:
    """One supported-version list per loader, fetched off the UI thread."""
    if loader_id not in MOD_CAPABLE_LOADERS:
        raise ValueError("Unknown mod loader")
    cached = local_cache.get("loader_versions", {"loader": loader_id}, max_age=3600)
    if isinstance(cached, list):
        return list(cached)
    versions = mll.mod_loader.get_mod_loader(loader_id).get_minecraft_versions(False)
    result = [version for version in versions if isinstance(version, str)]
    local_cache.set("loader_versions", {"loader": loader_id}, result)
    return result


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


def loader_java(mc_version: str, loader_id: str = "", *, progress_cb=None,
                status_cb=None, cancel_check=None) -> str:
    """Prepare a runnable, compatible Java before executing a loader installer.

    Use installed Java when possible, otherwise download a verified managed
    runtime. Forge 1.8.9 needs exact Java 8; modern loaders use the game's
    minimum major. Progress and cancellation share the installer's controls.
    """
    # Imported lazily: launch.py pulls in mods/csl/skins, and those import this
    # module. Same pattern as the config read in modpacks._curseforge_api_key.
    from .config import load_config
    from .jre import ensure_java_for_version
    java_version_id = mc_version + "-forge" if loader_id == "forge" and mc_version == "1.8.9" else mc_version
    try:
        configured = (load_config() or {}).get("java_path") or None
    except Exception:
        configured = None
    return ensure_java_for_version(java_version_id, configured, progress_cb=progress_cb,
                                   status_cb=status_cb, cancel_check=cancel_check)


def install_mod_loader(loader_id: str, mc_version: str, progress_cb, status_cb, max_cb,
                       cancel_event=None, *, loader_version: str | None = None) -> str:
    """Installs the given loader (fabric/quilt/forge/neoforge) for mc_version
    and returns the resulting launchable version id. For 'vanilla' this is
    just install_version(). Uses the id the library reports and confirms it
    with a before/after diff, since the exact resulting id format varies per
    loader."""
    if loader_id == "vanilla" or loader_id not in SUPPORTED_LOADERS:
        install_version(mc_version, progress_cb, status_cb, max_cb,
                        cancel_event=cancel_event)
        return mc_version

    before = {v["id"] for v in get_installed_versions()}

    # Cover both legacy modules and mll 8's mod_loader adapters. Upstream
    # STARTUPINFO alone still creates a console for some Windows child paths.
    from .winproc import patch_mll
    patch_mll()

    bridge = _InstallCancelBridge(cancel_event) if cancel_event is not None else None

    def checked(cb):
        def call(*args):
            if bridge is not None:
                bridge.note_thread()
                if bridge.should_stop():
                    raise _DownloadCancelled()
            return cb(*args)
        return call

    callback = {"setStatus": checked(status_cb), "setProgress": checked(progress_cb),
                "setMax": checked(max_cb)}
    callback["setStatus"]("Preparing mod loader")
    loader = mll.mod_loader.get_mod_loader(loader_id)
    # Include adapters loaded lazily by get_mod_loader too.
    patch_mll()
    # Resolve Java BEFORE the download starts: failing here is instant and the
    # message is actionable, versus a half-finished install and a bare WinError.
    def check_cancel():
        if bridge is not None:
            bridge.note_thread()
            if bridge.should_stop():
                raise _DownloadCancelled()

    def java_progress(done, total):
        callback["setProgress"](done / (total or 1))

    callback["setMax"](1)
    java = loader_java(mc_version, loader_id, progress_cb=java_progress,
                       status_cb=callback["setStatus"], cancel_check=check_cancel)

    # mll >= 8: install(mc, dir, *, loader_version=None, callback=None,
    # java=None) and it RETURNS the installed version id. `java` is passed
    # explicitly (see loader_java) and the loader version is pinned to the
    # newest stable one so the result is predictable; the signature check keeps
    # this working if the library's shape ever changes again.
    kwargs = {"callback": callback, "java": java}
    try:
        if "loader_version" in inspect.signature(loader.install).parameters:
            kwargs["loader_version"] = loader_version or loader.get_latest_loader_version(mc_version)
    except Exception:
        if loader_version:
            raise
        pass  # no version list (or an older API): let the library choose
    if loader_version and "loader_version" not in kwargs:
        raise RuntimeError("This installer cannot install the loader build required by the modpack.")
    expected_id = None
    if kwargs.get("loader_version") and hasattr(loader, "get_installed_version"):
        expected_id = loader.get_installed_version(mc_version, kwargs["loader_version"])
    expected_folder = (os.path.join(runtime_dir(MINECRAFT_DIR), "versions", expected_id)
                       if expected_id else None)
    folder_existed = bool(expected_folder and os.path.exists(expected_folder))
    owns_attempt = False
    try:
        with (_active_install(expected_id) if expected_id else nullcontext()):
            owns_attempt = True
            with _PatchedMllDownloads(bridge, explicit_java=True):
                reported = loader.install(mc_version, runtime_dir(MINECRAFT_DIR), **kwargs)
            callback["setStatus"]("Checking mod loader files")
    except Exception:
        # Own only the new loader folder, never the verified base or an
        # existing profile that may contain worlds and user-installed mods.
        if owns_attempt and expected_folder and not folder_existed:
            shutil.rmtree(expected_folder, ignore_errors=True)
        raise
    finally:
        if bridge is not None:
            bridge.release()

    after = get_installed_versions()
    by_id = {v["id"]: v for v in after}
    new_ids = [v["id"] for v in after if v["id"] not in before]
    # The library's own answer first - it knows the exact id format; the
    # before/after diff is the fallback for shapes it didn't report.
    candidates = ([reported] if isinstance(reported, str) and reported else []) + new_ids
    for vid in candidates:
        if vid not in by_id:
            continue
        if loader_version and expected_id and vid != expected_id:
            continue
        if vid != expected_id and find_installed_loader_version(
                {vid}, loader_id, mc_version) != vid:
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
    # Nothing new appeared (e.g. already installed) - best-effort match.
    complete_ids = {v["id"] for v in after if not v.get("incomplete")}
    existing = (expected_id if expected_id in complete_ids else None) if loader_version else find_installed_loader_version(
        complete_ids, loader_id, mc_version)
    if existing:
        return existing
    raise RuntimeError(f"The {SUPPORTED_LOADERS[loader_id]} installer did not create "
                       "a complete instance. Try installing it again.")


def install_fabric(mc_version: str, progress_cb, status_cb, max_cb) -> str:
    """Kept for backward compat - installs Fabric specifically."""
    return install_mod_loader("fabric", mc_version, progress_cb, status_cb, max_cb)
