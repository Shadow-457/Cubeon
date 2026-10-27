"""
Modpack install - Modrinth `.mrpack` and CurseForge packs.

WHY THIS IS MOSTLY ORCHESTRATION

A modpack is just "a Minecraft version + a mod loader + a fixed set of mods +
some config files", which is exactly the three things this launcher already
knows how to do (versions.install_version, mod_loaders.install_mod_loader,
the per-(version,loader) mod profiles in mods.py). So installing a pack here
is orchestration, not new machinery: read the manifest, install the version,
install the loader, drop the listed mods into the matching profile, copy the
pack's config overrides into the shared game folder.

TWO INPUT FORMATS, ONE INSTALLER

`.mrpack` (Modrinth) is the native format: an open ZIP spec with a plain-JSON
index and direct download URLs. It is installed directly.

CurseForge packs are plain zips whose manifest.json lists mods only as
(projectID, fileID) pairs - no URLs, no hashes. They matter because most of the
classic packs people ask for by name (RLCraft, SkyFactory, DawnCraft, ...) are
CurseForge exclusives that will never appear on Modrinth. They are handled by
CONVERTING them to a `.mrpack` in a temp file and reusing the one hardened
installer below, so there is exactly one code path doing the risky work.

Resolving those numeric ids has two modes, and BOTH must keep working:
  - with a CurseForge API key (optional, from console.curseforge.com): the
    batch metadata endpoint gives real filenames and SHA-1s.
  - with no key - the default for every user, so this is the common case: CF's
    own keyless download-redirect endpoint turns each (projectID, fileID) into
    a downloadable URL. No key, no token shipped in the app (Cubeon's
    never-ship-a-token rule), and no hash to verify against.
Never route the keyless case through a key-only endpoint: requests refuses a
None API-key header before it even sends, which is how "install RLCraft" once
failed with a raw InvalidHeader before a single byte was fetched.

HOW IT MAPS ONTO THE EXISTING PROFILE MODEL

Cubeon owns one private game folder (~/.cubeon_minecraft) and isolates
*mods*, per (version, loader), under mod_profiles/ - profiles now hold links
into the visible global mods store (one physical, human-named jar per mod).
A modpack install therefore:
  - installs the pack's Minecraft version + loader (so it appears on Play),
  - writes every `mods/*.jar` the pack lists into that profile - the exact
    folder sync_mods_to_game() copies into the game at launch,
  - writes the pack's `resourcepacks/` and `shaderpacks/` entries into that
    same profile (cubeon/content.py's per-instance content folders, staged
    into the game at launch like the mods),
  - copies the rest of `overrides/` (configs, options.txt, ...) into the game
    folder, where the game reads them regardless of instance.

A pack brings its own Minecraft version, so it does NOT have to match whatever
is selected on the Play tab - version-locked packs (RLCraft is 1.12.2-only)
must stay installable regardless of what the user currently has selected.

WHY THE PACKS ARE PER-INSTANCE NOW (they used to be shared): with one shared
resourcepacks/ folder, installing a second modpack mixed its packs and shaders
into the first one's permanently - one folder cannot describe two instances -
and two packs shipping a file at the same relative path silently overwrote each
other. Mods never had that problem because they are staged from the profile at
launch, so packs now use the identical store + profile-link + launch-sync
pattern. Configs still live in the shared game folder: that keeps a pack's
world/saves sitting next to everything else, and splitting configs per instance
is a much larger change with its own trade-offs.

SECURITY

A pack manifest is untrusted input that names URLs to download and paths to
write. So: download URLs are restricted to an HTTPS host allowlist, every write
path is checked for zip-slip / traversal before it touches disk, and file
hashes are verified whenever the manifest provides them.
"""
import hashlib
import json
import logging
import os
import re
import shutil
import tempfile
import threading
import time
import zipfile
from urllib.parse import urlparse

# Lazy: `requests` costs ~97ms to import and every module that pulls it in
# eagerly puts that on the startup path, even for a session that never
# touches the network. Call sites are unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
requests = LazyModule("requests")

log = logging.getLogger(__name__)

from .paths import (APP_NAME, MINECRAFT_DIR, PROFILES_DIR, MOD_META_SUFFIX,
                   modrinth_headers, user_agent)
from .versions import install_version, get_installed_versions
from .mod_loaders import install_mod_loader, find_installed_loader_version, MOD_CAPABLE_LOADERS
from .mods import (get_profile_dir, modrinth_search_index, rank_search_hits,
                   record_mod_source, profile_key, profile_key_for,
                   unique_profile_key, create_instance_version,
                   profile_dir_for_key, read_instance_meta, write_instance_meta,
                   is_protected_mod)
# Bundled resource packs/shaders belong to the INSTANCE, like the bundled mods
# do - so they are routed into the pack's own profile rather than the shared
# game folder (see _dest_is_content). Reuses content.py's profile layout so a
# pack-installed pack and a Mods-tab-installed one land in the same place.
from .content import CONTENT_TYPES, profile_dir as content_profile_dir
from . import local_cache
from . import global_mod_cache
from . import net

MODRINTH_API = "https://api.modrinth.com/v2"

# Pack FILES come from Modrinth, GitHub or GitLab depending on the pack (see
# _host_allowed), so this deliberately uses the generic agent rather than the
# Modrinth-specific one - a single identifying string for every host.
_DL_HEADERS = {"User-Agent": user_agent("modpack download")}


# Manifest key -> Cubeon loader id. These are the only loader dependencies the
# `.mrpack` spec defines; "minecraft" (handled separately) is the game version.
LOADER_DEP_KEYS = {
    "fabric-loader": "fabric",
    "quilt-loader": "quilt",
    "forge": "forge",
    "neoforge": "neoforge",
}

# Where a `.mrpack` is allowed to pull files from. This is Modrinth's own
# mandated allowlist for the format - matching hosts (and their subdomains)
# over HTTPS only. Anything else is refused rather than downloaded, so a
# malicious pack can't point the launcher at an arbitrary binary.
ALLOWED_DOWNLOAD_DOMAINS = (
    "modrinth.com",          # cdn.modrinth.com
    "github.com",
    "githubusercontent.com",  # raw./objects. - release assets, raw files
    "gitlab.com",
    "forgecdn.net",          # CurseForge's official CDN (mediafilez., edge.)
    "curseforge.com",        # CF's keyless download-redirect endpoint
)

# A single pack pulling more than this many files, or a single override bigger
# than this, is treated as malformed/hostile rather than processed blindly.
MAX_FILES = 5000
MAX_OVERRIDE_BYTES = 512 * 1024 * 1024  # 512 MB - generous, but not unbounded

# Recorded in each installed pack's profile so the tab can list what's there
# and Play can jump straight to the launchable version id.
MODPACK_META_FILENAME = "_modpack.json"


class ModpackError(Exception):
    """Anything wrong with a pack file or its install - carries a message
    already phrased for the user (no stack-trace jargon)."""


# ---------------------------------------------------------------------------
# In-flight registry: a pack install is NOT a single write
# ---------------------------------------------------------------------------
# The install starts by putting the base Minecraft version and its loader on
# disk, THEN downloads the pack's mods into the shared (mc_version, loader)
# profile, and only writes _modpack.json at the very end. For that whole
# window the version folders already look complete to any disk scan, so the
# Play tab (whose button is derived from exactly such a scan) used to offer
# PLAY - and a click then launched the game against a profile that was still
# being written: the 2026-10-18 report "it's not fully installed, still it
# says the Play button while it's installing mods, and that breaks stuff".
#
# This registry is the honest signal instead of a UI flag, because it must be
# true no matter WHICH surface started the install (Modpacks tab, Settings >
# Import, tests/CLI) and because several UI paths read it (button paint, click
# guard, prefetch, doctor). Keyed by mc_version: the base version's folder is
# being (re)written for every loader, so two pack installs for one base version
# must not overlap. Each record also remembers the exact version id / profile
# it is writing, so the Play button can lock the pack's OWN instance instead of
# every instance that happens to share a Minecraft version number.
_ACTIVE_INSTALLS: dict[str, dict] = {}   # mc_version -> claim record
_ACTIVE_INSTALLS_LOCK = threading.Lock()
_INSTALL_LISTENERS: list = []            # no-arg callbacks, fired on change

# A claim is touched on every progress/status callback. If an install thread
# dies in a way that skips its `finally` (a hard interpreter teardown, a
# frozen worker), the stale claim must not disable Play forever.
_CLAIM_IDLE_TIMEOUT = 15 * 60  # seconds without any install progress


def _prune_stale_claims_locked(now: float | None = None) -> None:
    now = time.time() if now is None else now
    for key, rec in list(_ACTIVE_INSTALLS.items()):
        touched = rec.get("touched") or rec.get("started") or 0
        if now - touched > _CLAIM_IDLE_TIMEOUT:
            _ACTIVE_INSTALLS.pop(key, None)


def active_pack_installs() -> dict[str, str]:
    """mc_version -> pack name for every pack install writing disk right now.

    Cheap, in-memory, never raises. The UI reads this to keep a half-installed
    instance from being offered as playable.
    """
    with _ACTIVE_INSTALLS_LOCK:
        _prune_stale_claims_locked()
        return {mc: rec.get("name") or "modpack"
                for mc, rec in _ACTIVE_INSTALLS.items() if rec.get("count")}


def pack_install_for(mc_version: str) -> "str | None":
    """The pack currently installing `mc_version`, or None.

    This is the BASE-VERSION view. UI code that guards one instance must use
    ``pack_install_for_instance`` instead - a 26.2 pack install is not writing
    a 26.3 instance, and must not disable its Play button.
    """
    if not mc_version:
        return None
    with _ACTIVE_INSTALLS_LOCK:
        _prune_stale_claims_locked()
        rec = _ACTIVE_INSTALLS.get(str(mc_version))
        return (rec.get("name") or "modpack") if rec and rec.get("count") else None


def pack_install_for_instance(version_id: str) -> "str | None":
    """The pack currently writing THIS exact instance, or None.

    A claim matches when it already recorded this launch id, when the selected
    version's instance sidecar names the same pack, or when that sidecar points
    at the profile the install owns. A bare vanilla instance with no sidecar is
    deliberately NOT matched: the pack writes a separate clone/profile, so
    locking it would be the 2026-10-26 report ("installing 26.2 blocked my real
    26.3 instance"). Never raises.
    """
    if not version_id:
        return None
    with _ACTIVE_INSTALLS_LOCK:
        _prune_stale_claims_locked()
        claims = [dict(rec) for rec in _ACTIVE_INSTALLS.values()
                  if rec.get("count")]
    if not claims:
        return None
    for rec in claims:
        if rec.get("version_id") == version_id:
            return rec.get("name") or "modpack"
    try:
        sidecar = read_instance_meta(version_id) or {}
    except Exception:
        sidecar = {}
    sidecar_name = str(sidecar.get("name") or "").strip().lower()
    sidecar_profile = sidecar.get("profile")
    for rec in claims:
        rec_name = str(rec.get("name") or "").strip().lower()
        if sidecar_name and rec_name and sidecar_name == rec_name:
            return rec.get("name") or "modpack"
        if sidecar_profile and rec.get("profile") == sidecar_profile:
            return rec.get("name") or "modpack"
    return None


def add_pack_install_listener(callback) -> None:
    """Register a no-arg callback fired when a pack install starts or ends.

    The Play button uses it to repaint the instant the claim changes - without
    it a disabled "installing" button could outlive a cancelled install (or a
    freshly finished one would keep saying it until some unrelated repaint).
    Callbacks run on the installing thread; the UI's repaint helper is
    thread-safe by design.
    """
    if callback and callback not in _INSTALL_LISTENERS:
        _INSTALL_LISTENERS.append(callback)


def _mark_pack_install(mc_version: str, name: str, *, exclusive: bool = False,
                       profile: str | None = None,
                       version_id: str | None = None) -> None:
    with _ACTIVE_INSTALLS_LOCK:
        _prune_stale_claims_locked()
        if exclusive and str(mc_version) in _ACTIVE_INSTALLS:
            raise ModpackError("Another modpack is already installing for this Minecraft version. Wait for it to finish.")
        rec = _ACTIVE_INSTALLS.setdefault(str(mc_version), {
            "name": "", "count": 0, "started": time.time(), "touched": 0.0,
            "profile": None, "version_id": None,
        })
        rec["count"] += 1
        rec["name"] = name or rec["name"] or "modpack"
        rec["touched"] = time.time()
        if profile:
            rec["profile"] = profile
        if version_id:
            rec["version_id"] = version_id
    _notify_install_listeners()


def _update_pack_install(mc_version: str, name: str | None = None, *,
                         profile: str | None = None,
                         version_id: str | None = None) -> None:
    """Record the exact instance/profile a running claim is writing.

    Called once the install body knows them (after the loader folder exists),
    so ``pack_install_for_instance`` can match the pack's own clone while the
    mods are still downloading.
    """
    with _ACTIVE_INSTALLS_LOCK:
        rec = _ACTIVE_INSTALLS.get(str(mc_version))
        if rec is None:
            return
        rec["touched"] = time.time()
        if name:
            rec["name"] = name
        if profile:
            rec["profile"] = profile
        if version_id:
            rec["version_id"] = version_id
    # No listener notification: the claim's start/end edges are what the Play
    # button repaints on, and this is still the same running install.


def _touch_pack_install(mc_version: str) -> None:
    with _ACTIVE_INSTALLS_LOCK:
        rec = _ACTIVE_INSTALLS.get(str(mc_version))
        if rec is not None:
            rec["touched"] = time.time()


def _unmark_pack_install(mc_version: str) -> None:
    with _ACTIVE_INSTALLS_LOCK:
        rec = _ACTIVE_INSTALLS.get(str(mc_version))
        if rec is None:
            return
        rec["count"] -= 1
        if rec["count"] <= 0:
            _ACTIVE_INSTALLS.pop(str(mc_version), None)
    _notify_install_listeners()


def _notify_install_listeners() -> None:
    for callback in list(_INSTALL_LISTENERS):
        try:
            callback()
        except Exception:
            log.debug("pack install listener failed", exc_info=True)


# ---------------------------------------------------------------------------
# Manifest parsing
# ---------------------------------------------------------------------------

def _read_index(zf: zipfile.ZipFile) -> dict:
    try:
        raw = zf.read("modrinth.index.json")
    except KeyError:
        raise ModpackError(
            "This doesn't look like a Modrinth modpack - its "
            "modrinth.index.json is missing. (CurseForge packs are handled "
            "separately - install them from a CurseForge search result, which "
            "converts the pack automatically.)"
        )
    try:
        index = json.loads(raw)
    except (json.JSONDecodeError, UnicodeDecodeError):
        raise ModpackError("The modpack's manifest is corrupted and couldn't be read.")
    if index.get("game") not in (None, "minecraft"):
        raise ModpackError(f"Unsupported pack game: {index.get('game')!r}.")
    if index.get("formatVersion") not in (None, 1):
        raise ModpackError(
            f"This pack uses modpack format {index.get('formatVersion')!r}, which "
            "this version of Cubeon doesn't understand yet (only format 1 is "
            "supported). Check for a Cubeon update, or ask the pack author for "
            "a format-1 build."
        )
    return index


# The `.mrpack` spec's dependency keys reserved for a game version rather
# than a loader - anything else in `dependencies` that ISN'T in
# LOADER_DEP_KEYS and isn't one of these is an unrecognized loader, not
# silently "no loader" (see parse_dependencies()).
_NON_LOADER_DEP_KEYS = {"minecraft"}


def parse_dependencies(index: dict) -> tuple[str, str, str | None]:
    """(mc_version, loader_id, loader_version) from a manifest's dependencies.
    loader_id is 'vanilla' for a pack that lists no loader (rare, but valid).

    Refuses rather than guessing when `dependencies` names a loader this
    launcher doesn't recognize (LOADER_DEP_KEYS is a fixed, hand-maintained
    map; Modrinth adding a new loader key in the future - or a pack simply
    using a spelling this launcher doesn't know - used to fall straight
    through to "vanilla" with no error at all. That's worse than a crash:
    the pack's mods need that loader, so they'd silently never load and the
    failure would show up as "why don't my mods work" with no clue why."""
    deps = index.get("dependencies") or {}
    mc_version = deps.get("minecraft")
    if not mc_version:
        raise ModpackError("The modpack doesn't say which Minecraft version it needs.")

    loader_id, loader_version = "vanilla", None
    for key, cubeon_loader in LOADER_DEP_KEYS.items():
        if key in deps:
            loader_id = cubeon_loader
            loader_version = deps.get(key)
            break
    else:
        unrecognized = [k for k in deps if k not in _NON_LOADER_DEP_KEYS and k not in LOADER_DEP_KEYS]
        if unrecognized:
            raise ModpackError(
                f"This pack needs a mod loader ({', '.join(sorted(unrecognized))}) "
                "that this version of Cubeon doesn't support yet. Check for a "
                "Cubeon update."
            )
    return mc_version, loader_id, loader_version


def summarize(index: dict) -> dict:
    """A quick, install-free description of a pack - name/version/loader/mod
    count - for confirmation UI before committing to the download."""
    mc_version, loader_id, loader_version = parse_dependencies(index)
    files = index.get("files") or []
    mod_files = [f for f in files if _wanted_on_client(f) and _dest_is_mod(f.get("path", ""))]
    return {
        "name": index.get("name") or "Modpack",
        "pack_version": index.get("versionId"),
        "summary": index.get("summary"),
        "mc_version": mc_version,
        "loader": loader_id,
        "loader_version": loader_version,
        "mod_count": len(mod_files),
    }


# ---------------------------------------------------------------------------
# Path / URL safety
# ---------------------------------------------------------------------------

def _safe_relpath(base_dir: str, rel_path: str) -> str:
    """Resolve rel_path under base_dir, refusing anything that escapes it
    (absolute paths, `..`, symlink-y tricks). Returns the absolute dest path.
    Raises ModpackError on a traversal attempt - a hostile pack shouldn't be
    able to write outside the folder we chose for it."""
    rel = rel_path.replace("\\", "/").lstrip("/")
    dest = os.path.normpath(os.path.join(base_dir, rel))
    base_abs = os.path.abspath(base_dir)
    dest_abs = os.path.abspath(dest)
    if dest_abs != base_abs and not dest_abs.startswith(base_abs + os.sep):
        raise ModpackError(f"Refusing to write outside the install folder: {rel_path!r}")
    return dest_abs


def _host_allowed(url: str) -> bool:
    try:
        parts = urlparse(url)
    except ValueError:
        return False
    if parts.scheme != "https" or not parts.hostname:
        return False
    host = parts.hostname.lower()
    return any(host == d or host.endswith("." + d) for d in ALLOWED_DOWNLOAD_DOMAINS)


def _dest_is_mod(rel_path: str) -> bool:
    p = rel_path.replace("\\", "/").lstrip("/").lower()
    return p.startswith("mods/") and p.endswith(".jar")


# A pack's bundled resource packs / shaders are per-INSTANCE (see
# cubeon/content.py), so they are routed into the pack's own profile like its
# mods are. Before this they went into the shared game folder, which is how two
# installed modpacks ended up permanently mixed - and how one pack's overrides
# silently overwrote the other's when both shipped the same relative path.
_CONTENT_PREFIXES = {cfg["subdir"] + "/": key for key, cfg in CONTENT_TYPES.items()}


def _content_type_for(rel_path: str) -> str | None:
    """The content type a pack-relative path belongs to, or None if it isn't
    a resource pack/shader (configs, options.txt, ... stay where they are)."""
    p = rel_path.replace("\\", "/").lstrip("/").lower()
    for prefix, content_type in _CONTENT_PREFIXES.items():
        if p.startswith(prefix):
            return content_type
    return None


def _content_profile_dest(rel_path: str, mc_version: str, loader: str,
                          version_id: str | None = None) -> str | None:
    """Where a bundled pack/shader lands for this instance, or None when the
    path isn't content. Keeps the pack's own filename (the folder inside a
    profile is already the content type, so the prefix is dropped)."""
    content_type = _content_type_for(rel_path)
    if not content_type or not mc_version or not loader:
        return None
    relative = rel_path.replace("\\", "/")
    root = content_profile_dir(content_type, mc_version, loader, version_id)
    _safe_relpath(root, relative)
    name = relative.split("/", 1)[1]
    if not name:
        return None
    return _safe_relpath(root, name)


def _legacy_profile_is_empty(mc_version: str, loader: str) -> bool:
    """True when the shared (mc_version, loader) profile has nothing in it.

    An empty profile is safe to reuse for a pack: there is no hand-built mod
    set to merge into or overwrite. A profile with any jar (or content folder)
    is someone's instance and gets a private clone instead.
    """
    path = os.path.join(PROFILES_DIR, profile_key(mc_version, loader))
    try:
        for name in os.listdir(path):
            if name in ("resourcepacks", "shaderpacks", "mods"):
                # An empty folder (Cubeon creates these on demand) is not
                # someone's content; only actual packs/mods count.
                try:
                    if os.listdir(os.path.join(path, name)):
                        return False
                except OSError:
                    return False
            if name.endswith((".jar", ".jar.disabled")):
                # Cubeon's own managed client mods (CustomSkinLoader, Friends)
                # are injected into every profile at install/launch. They do
                # not make a profile "someone's hand-built instance", so a
                # pack may still adopt it instead of cloning.
                if is_protected_mod(filename=name):
                    continue
                return False
    except OSError:
        return True
    return True


def _find_installed_pack(name: str, mc_version: str, loader: str) -> dict | None:
    """The existing install of this pack, if any (an update/reinstall).

    Matching on name + game version + loader keeps a pack update in the same
    isolated instance instead of creating a second copy every time. The
    pack's own version is deliberately NOT part of the key.
    """
    try:
        installed = list_installed_modpacks()
    except Exception:
        return None
    for meta in installed:
        if (str(meta.get("name") or "").strip().lower()
                == str(name or "").strip().lower()
                and str(meta.get("mc_version")) == str(mc_version)
                and meta.get("loader") == loader):
            return meta
    # A failed/cancelled reinstall drops _modpack.json, but its ownership
    # sidecar remains. Retry that profile instead of allocating pack-2.
    try:
        for version_id in sorted(os.listdir(os.path.join(MINECRAFT_DIR, "versions"))):
            meta = read_instance_meta(version_id) or {}
            if (str(meta.get("name") or "").strip().lower()
                    == str(name or "").strip().lower()
                    and meta.get("mc_version") == mc_version
                    and meta.get("loader") == loader and meta.get("profile")
                    and ("pack_version" in meta or meta.get("pack"))):
                return {**meta, "version_id": version_id}
    except OSError:
        pass
    return None


def _wanted_on_client(file_entry: dict) -> bool:
    """Skip files the pack marks as not for the client (server-only mods)."""
    env = file_entry.get("env") or {}
    return env.get("client", "required") != "unsupported"


# ---------------------------------------------------------------------------
# Download primitive (hash-verified, allowlisted)
# ---------------------------------------------------------------------------

def _stream_download(dest_path: str, urls: list[str], hashes: dict | None, progress_cb=None) -> None:
    """Stream the first allowlisted URL into dest_path, verifying the manifest
    hash as we go. Tries alternate mirrors if the first fails. Each URL gets
    retry/backoff and Range resume from cubeon.net, and the global download
    gate caps how many files of a pack fetch at once."""
    hashes = hashes or {}
    algo, expected = None, None
    for a in ("sha512", "sha1"):
        if hashes.get(a):
            algo, expected = a, hashes[a].lower()
            break

    candidates = [u for u in urls if _host_allowed(u)]
    if not candidates:
        raise ModpackError(
            "A file in this pack is hosted somewhere Cubeon won't download from "
            "(only Modrinth/GitHub/GitLab are trusted)."
        )

    os.makedirs(os.path.dirname(dest_path), exist_ok=True)

    # The size is known from a HEAD probe before a single byte is written:
    # refuse early on a nearly-full drive instead of dying halfway. A probe
    # that fails is NOT fatal - the download itself still gets to try.
    for url in candidates[:2]:
        try:
            probe = requests.head(url, headers=_DL_HEADERS, timeout=10,
                                  allow_redirects=True)
            total = int(probe.headers.get("content-length", 0))
            if total:
                from .paths import ensure_disk_space
                ensure_disk_space(os.path.dirname(dest_path), total, "mod download")
                break
        except (requests.RequestException, RuntimeError, ValueError) as ex:
            log.debug("size probe for %s skipped: %s", url, ex.__class__.__name__)

    last_err = None
    for url in candidates:
        expected_pair = (algo, expected) if algo and expected else None
        try:
            net.download_to(dest_path, url, headers=_DL_HEADERS, timeout=30,
                            expected_hash=expected_pair, progress_cb=progress_cb)
            return
        except net.DownloadError as ex:
            last_err = ex
            continue
    raise ModpackError(f"Couldn't download a pack file: {last_err}")


def _download_to(dest_path: str, urls: list[str], hashes: dict | None, progress_cb=None,
                  use_global_cache: bool = False) -> None:
    """As _stream_download, but for mod jars (use_global_cache=True) checks/
    populates the global mods store first, so a mod already on disk for some
    other pack/profile is linked in instead of re-downloaded."""
    if not use_global_cache:
        _stream_download(dest_path, urls, hashes, progress_cb)
        return

    def fetch_fn(tmp_path):
        _stream_download(tmp_path, urls, hashes, progress_cb)

    global_mod_cache.get_or_fetch(dest_path, fetch_fn, hashes)


# ---------------------------------------------------------------------------
# Install
# ---------------------------------------------------------------------------

def _noop(*_a, **_k):
    pass


def _extract_overrides(zf: zipfile.ZipFile, profile_dir: str, status_cb,
                       mc_version: str = "", loader: str = "",
                       version_id: str | None = None,
                       written: "set[str] | None" = None) -> int:
    """Copy the pack's override files into place: anything under mods/ goes to
    the profile (so sync_mods_to_game picks it up), bundled resource
    packs/shaders go to the profile's content folders (so they follow THIS
    instance), and everything else (config/, options.txt, ...) into the shared
    game dir. Returns how many override mod jars were written; pass `written`
    to also collect their basenames."""
    override_mods = 0
    for info in zf.infolist():
        if info.is_dir():
            continue
        name = info.filename.replace("\\", "/")
        for prefix in ("overrides/", "client-overrides/"):
            if name.startswith(prefix):
                rel = name[len(prefix):]
                break
        else:
            continue  # not an override entry (manifest, server-overrides/, ...)
        if not rel:
            continue
        if info.file_size > MAX_OVERRIDE_BYTES:
            raise ModpackError(f"An override file is implausibly large ({rel}); refusing it.")

        if _dest_is_mod(rel):
            dest = _safe_relpath(profile_dir, os.path.basename(rel))
            override_mods += 1
            if written is not None:
                written.add(os.path.basename(rel))
        else:
            # A bundled pack/shader belongs to this instance; everything else
            # (configs, options.txt, ...) keeps its existing shared location.
            dest = _content_profile_dest(rel, mc_version, loader, version_id) \
                or _safe_relpath(MINECRAFT_DIR, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".override-", dir=os.path.dirname(dest)) as tmpdir:
            payload = os.path.join(tmpdir, "payload")
            with zf.open(info) as src, open(payload, "wb") as out:
                shutil.copyfileobj(src, out)
            if _dest_is_mod(rel):
                staged = os.path.join(tmpdir, os.path.basename(dest))
                global_mod_cache.put_file(payload, staged)
                os.replace(staged, dest)
            else:
                os.replace(payload, dest)
    if override_mods:
        status_cb(f"Copied {override_mods} bundled mod(s) and pack config")
    return override_mods


def _modrinth_project_id(urls) -> "str | None":
    """The Modrinth project id buried in a CDN URL, or None.

    Manifests list download URLs like
      https://cdn.modrinth.com/data/AANobbMI/versions/.../sodium.jar
    where 'AANobbMI' is the project id - the ONLY identifier a Modrinth
    manifest leaves for the sidecar. CurseForge-converted packs use their own
    CDN, which has no /data/ segment, and correctly yield None."""
    for url in urls or []:
        try:
            path = urlparse(url).path
        except Exception:
            continue
        if "/data/" in path:
            segment = path.split("/data/", 1)[1].split("/", 1)[0]
            if segment:
                return segment
    return None


def _install_from_zip_body(zip_path: str, *, progress_cb=None, status_cb=None, max_cb=None,
                           icon_url: str | None = None) -> dict:
    progress_cb = progress_cb or _noop
    status_cb = status_cb or _noop
    max_cb = max_cb or _noop

    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile:
        raise ModpackError("That file isn't a valid modpack (couldn't open the .mrpack archive).")

    with zf:
        index = _read_index(zf)
        info = summarize(index)
        mc_version = info["mc_version"]
        loader_id = info["loader"]

        files = index.get("files") or []
        if len(files) > MAX_FILES:
            raise ModpackError("This pack lists an implausible number of files; refusing it.")

        # A previous install of THIS pack (an update/reinstall) keeps its own
        # instance/profile instead of spawning another copy or merging into
        # whatever now occupies the legacy profile.
        existing = _find_installed_pack(info["name"], mc_version, loader_id)

        # 0) Decide which mod profile this pack owns BEFORE the long install.
        #
        # Installs made before instance isolation share one profile per
        # (mc_version, loader). Reusing that profile for a pack is only safe
        # when it is EMPTY (nothing to merge into) or already belongs to this
        # same pack. Otherwise the pack gets a cloned version folder and a
        # private profile, so installing Fabulously Optimized next to a
        # hand-built Fabric instance can never overwrite its 54 mods.
        #
        # The clone itself has to wait until the loader is installed (it
        # copies that version folder), but the profile KEY is known now - and
        # knowing it now is what lets the stale marker be dropped before the
        # first progress line.
        legacy_key = profile_key(mc_version, loader_id)
        profile = ""
        version_id = None
        rebuild_note = ""
        if existing:
            existing_vid = existing.get("version_id")
            existing_profile = existing.get("profile")
            version_dir = os.path.join(MINECRAFT_DIR, "versions", str(existing_vid or ""))
            if isinstance(existing_profile, str) and existing_profile:
                profile = existing_profile
            if existing_vid and os.path.isdir(version_dir):
                version_id = existing_vid
                profile = profile or profile_key_for(mc_version, loader_id, version_id)
            elif profile:
                # The tracking record survived but its version folder did not.
                # Re-clone the loader install and point it back at the same
                # profile, so the pack updates in place.
                rebuild_note = "Rebuilding the pack's isolated instance"
            else:
                profile = legacy_key

        if not profile:
            if _legacy_profile_is_empty(mc_version, loader_id):
                profile = legacy_key
            else:
                profile = unique_profile_key(mc_version, loader_id, info["name"])
                rebuild_note = "Keeping this pack separate from your other mods"

        # A pack that stays on the legacy profile launches through the loader's
        # canonical version id (no clone needed). That id is only known after
        # the loader install, so it is filled in there.

        # This install is about to overwrite the profile this pack lives in.
        # If the pack was already installed (a repair/reinstall of the same
        # version+loader, or a different pack sharing that profile), its
        # _modpack.json marker is still sitting there and would keep listing it
        # as "Installed" - with a working Play button - for the whole duration
        # of the rebuild, even though the version and mods on disk are being
        # replaced underneath it. Drop the stale marker BEFORE any of the long
        # download steps so the pack stops showing as installed the moment its
        # rebuild begins; it's re-written at the end of THIS install (step 6),
        # so a success puts it back and a failure correctly leaves it gone
        # instead of presenting a half-finished pack as ready to play.
        if version_id:
            marker_dir = get_profile_dir(mc_version, loader_id, version_id)
        elif profile == legacy_key:
            marker_dir = get_profile_dir(mc_version, loader_id)
        else:
            marker_dir = profile_dir_for_key(profile)
        # Remember exactly which jars the PREVIOUS install of this pack owned,
        # so a reinstall can remove ones the new pack version dropped instead
        # of letting old and new builds pile up (the "30 mods then 70 mods"
        # report: every reinstall only ever added).
        old_pack_jars = []
        if marker_dir:
            try:
                with open(os.path.join(marker_dir, MODPACK_META_FILENAME),
                          "r", encoding="utf-8") as fh:
                    _old_meta = json.load(fh)
                if isinstance(_old_meta, dict):
                    old_pack_jars = [str(n) for n in (_old_meta.get("jars") or [])
                                     if isinstance(n, str)]
            except (OSError, json.JSONDecodeError):
                old_pack_jars = []
            try:
                os.remove(os.path.join(marker_dir, MODPACK_META_FILENAME))
            except OSError:
                pass

        # 1) Minecraft version
        status_cb(f"Installing Minecraft {mc_version}")
        from .config import launch_java_path
        # Snapshot the versions folder so the sidecar can record which build
        # inputs THIS install created. The Instances sheet hides those, so a
        # pack shows up as one instance instead of "vanilla + loader + pack".
        versions_dir = os.path.join(MINECRAFT_DIR, "versions")
        try:
            versions_before = set(os.listdir(versions_dir))
        except OSError:
            versions_before = set()
        install_version(mc_version, progress_cb, status_cb, max_cb,
                        explicit_java=bool(launch_java_path()))

        # 2) Mod loader (returns the launchable version id, e.g.
        #    fabric-loader-0.15.x-1.20.1). Vanilla packs skip straight through.
        if loader_id in MOD_CAPABLE_LOADERS:
            status_cb(f"Installing {loader_id.title()} loader")
            loader_version_id = install_mod_loader(loader_id, mc_version, progress_cb,
                                                   status_cb, max_cb,
                                                   loader_version=info.get("loader_version") if info.get("loader_version") != "*" else None)
        else:
            loader_version_id = mc_version

        # 2c) Now that the loader exists, clone its version folder for an
        # isolated pack (or rebuild a missing one). A pack that stays on the
        # legacy profile just launches through the loader's canonical id.
        if version_id is None and profile == legacy_key:
            version_id = loader_version_id
        elif version_id is None:
            if rebuild_note:
                status_cb(rebuild_note)
            version_id = create_instance_version(
                mc_version, loader_id, loader_version_id, profile,
                name=info["name"], pack={"name": info["name"],
                                         "pack_version": info["pack_version"]})

        # A pack update can change the required loader build. Refresh only
        # its launch JSON, retaining its id, profile and user content.
        if version_id != loader_version_id:
            source_json = os.path.join(MINECRAFT_DIR, "versions", loader_version_id, loader_version_id + ".json")
            target_json = os.path.join(MINECRAFT_DIR, "versions", version_id, version_id + ".json")
            with open(source_json, encoding="utf-8") as source:
                launch_profile = json.load(source)
            launch_profile["id"] = version_id
            from .atomicio import write_json
            write_json(target_json, launch_profile)

        # Record the ownership in the version folder. This is what every
        # launch/UI lookup uses to find the pack's private profile; without it
        # the same (mc_version, loader) pair would resolve to the shared one.
        previous_meta = read_instance_meta(version_id) or {}
        built_from = [str(src) for src in (previous_meta.get("built_from") or [])
                      if isinstance(src, str) and src]
        for candidate in (mc_version, loader_version_id):
            if (candidate and candidate != version_id
                    and candidate not in versions_before
                    and candidate not in built_from):
                built_from.append(candidate)
        instance_meta = {
            "profile": profile,
            "name": info["name"],
            "mc_version": mc_version,
            "loader": loader_id,
            "pack_version": info["pack_version"],
            "loader_version": info.get("loader_version"),
        }
        source = previous_meta.get("source_version_id")
        if not source and loader_version_id != version_id:
            source = loader_version_id
        if source and source != version_id:
            instance_meta["source_version_id"] = source
        if built_from:
            instance_meta["built_from"] = built_from
        write_instance_meta(version_id, instance_meta)
        profile_dir = get_profile_dir(mc_version, loader_id, version_id)

        # The claim now knows the exact instance it is writing, so the Play
        # button can lock this clone (and only this clone) for the rest of the
        # download.
        _update_pack_install(mc_version, info["name"],
                             profile=profile, version_id=version_id)

        # A reinstall must REPLACE the pack's mod set, not add to it. The
        # actual removal happens after the new jars are in (see step 6): doing
        # it here destroyed a working pack's mods when a later download failed
        # or the user cancelled.

        def _profile_jars() -> set:
            try:
                return {name for name in os.listdir(profile_dir)
                        if name.endswith((".jar", ".jar.disabled"))}
            except OSError:
                return set()

        # 3) The pack's declared mod files, into the matching profile folder.
        client_files = [f for f in files if _wanted_on_client(f)]
        mod_files = [f for f in client_files if _dest_is_mod(f.get("path", ""))]
        other_files = [f for f in client_files if not _dest_is_mod(f.get("path", ""))]

        total = len(mod_files) + len(other_files)
        max_cb(max(total, 1))
        n = 0

        # 3a) Mod jars fetch IN PARALLEL, not one-at-a-time. The old serial
        # loop meant the 4-slot net.DOWNLOAD_GATE was decorative: a single
        # thread can only ever hold one slot, so a 300-mod pack paid the full
        # latency of 300 sequential transfers. A bounded pool (sized to the
        # same cap) uses all four slots while still keeping Modrinth's CDN and
        # the user's router happy. Worker threads only touch the network and
        # the content-addressed store (which is now lock-guarded); every UI
        # callback and the manifest bookkeeping run back here, on this thread.
        if mod_files:
            from concurrent.futures import ThreadPoolExecutor, as_completed
            fetched = []

            def _fetch_one(entry):
                path = entry.get("path", "")
                dest = _safe_relpath(profile_dir, os.path.basename(path))
                urls = entry.get("downloads") or []
                _download_to(dest, urls, entry.get("hashes"), use_global_cache=True)
                return (os.path.basename(dest),
                        _modrinth_project_id(urls),
                        urls[0] if urls else None)

            with ThreadPoolExecutor(max_workers=net.MAX_CONCURRENT_DOWNLOADS) as pool:
                futures = [pool.submit(_fetch_one, f) for f in mod_files]
                for fut in as_completed(futures):
                    try:
                        fetched.append(fut.result())
                        n += 1
                        status_cb(f"Downloading mods... {n}/{len(mod_files)}")
                        progress_cb(n)
                    except Exception:
                        # Any abort - a failed download OR a caller cancelling
                        # from its status/progress callback - must cancel the
                        # still-queued fetches. Left alone, the pool's
                        # shutdown(wait=True) would happily grind through the
                        # rest of the pack before the cancel could take effect.
                        for pending in futures:
                            pending.cancel()
                        raise

            # Record what each jar IS, after the downloads settle. A manifest
            # entry has no slug, but the Modrinth CDN URL carries the project
            # id, and that's enough for the Mods tab to show the mod as
            # installed and - more importantly - for a later install of a newer
            # build to REPLACE this one instead of sitting next to it. Without
            # this, every pack mod was anonymous: the browse view offered
            # "Download" for mods the pack had already installed, and taking
            # that offer left the profile with two builds of the same mod for
            # the game to pick between. Done serially to avoid racing writes to
            # the profile's metadata file.
            for filename, project_id, url in fetched:
                record_mod_source(profile_dir, filename,
                                  project_id=project_id, url=url)

        # 4) Declared non-mod files (resourcepacks/shaders and the odd config).
        #    A declared pack/shader belongs to THIS instance (see
        #    _content_profile_dest); anything else keeps the shared game dir.
        for f in other_files:
            n += 1
            path = f.get("path", "")
            status_cb("Downloading pack resources...")
            dest = _content_profile_dest(path, mc_version, loader_id, version_id) \
                or _safe_relpath(MINECRAFT_DIR, path)
            _download_to(dest, f.get("downloads") or [], f.get("hashes"))
            progress_cb(n)

        # 5) Overrides (bundled configs + any non-Modrinth-hosted jars).
        status_cb("Applying pack config")
        override_jars: set[str] = set()
        _extract_overrides(
            zf, profile_dir, status_cb, mc_version, loader_id, version_id,
            written=override_jars)

        # 6) Remember which jars belong to the pack itself (manifest downloads
        #    plus bundled override jars). This is the list a future reinstall
        #    prunes; Cubeon's own injected client mods are added AFTER this
        #    snapshot, so they are never mistaken for pack content. The marker
        #    is written at the very end, once the real jar count is known.
        pack_jars = {os.path.basename(f.get("path", "")) for f in mod_files}
        pack_jars |= override_jars
        pack_jars = {name for name in pack_jars if name}

        # Now that the NEW set is safely on disk, remove the jars the PREVIOUS
        # install recorded as pack-owned and this pack version no longer ships.
        # Only "old minus new" is deleted, so same-named jars are not churned;
        # a jar the user added by hand was never in that list, so it survives.
        # (Installs made before this field existed have no list and simply keep
        # their files once; the next install writes the list and future
        # updates prune.)
        for _old_name in old_pack_jars:
            if (os.path.basename(_old_name) != _old_name
                    or _old_name in pack_jars):
                continue
            try:
                os.remove(os.path.join(profile_dir, _old_name))
            except OSError:
                pass

        # 7) Cubeon's own client mods into THIS pack's profile, using the
        #    PACK's loader. Injection used to happen only at launch, where it
        #    read the Play tab's loader selector - launching a Forge pack with
        #    the selector left on vanilla/fabric sent CustomSkinLoader (a
        #    fabric build!) and the Friends jar into a profile the pack never
        #    synced from, so skins and the Friends button silently vanished.
        #    Doing it here at install time, with the loader the pack actually
        #    declared, is what makes injection deterministic.
        try:
            from . import csl as _csl
            _csl.ensure_ready(mc_version, loader_id, status_cb=status_cb,
                              version_id=version_id)
        except Exception:
            pass  # best-effort: a skins problem must never fail the install
        try:
            from .mods import get_profile_dir as _get_profile_dir
            from . import cubeonfriends as _friends_mod
            _friends_ok = _friends_mod.ensure_installed(
                mc_version, loader_id,
                _get_profile_dir(mc_version, loader_id, version_id))
            if loader_id not in ("fabric", "quilt"):
                # The Friends mod is Fabric-only (see mod/brackets.json).
                # Saying so beats a silently missing game-menu button.
                status_cb("Friends button needs Fabric/Quilt - not available in this pack")
            elif not _friends_ok:
                # Fabric/Quilt pack but no jar was built for this bracket -
                # the in-game button will be missing. Say so instead of silence.
                status_cb("Cubeon Friends mod not built for Minecraft "
                          f"{mc_version} - the in-game button will be missing")
        except Exception:
            pass

        # 8) Record the pack so the tab can list it and Play can select it.
        #    mod_count is the REAL number of jars in the profile (the same
        #    number the Play tab and instances.mod_count() report), not just
        #    the manifest's file list - the 30-vs-70 report was one install
        #    showing two different counts from two different definitions.
        all_jars = _profile_jars()
        meta = {
            "name": info["name"],
            "pack_version": info["pack_version"],
            "summary": info["summary"],
            "mc_version": mc_version,
            "loader": loader_id,
            "version_id": version_id,
            "profile": profile,
            "mod_count": len(all_jars),
            "jars": sorted(pack_jars),
        }
        # The browse hit's thumbnail, kept so "Installed packs" can show real
        # art instead of a placeholder. Absent for a pack imported from disk.
        if icon_url:
            meta["icon_url"] = icon_url
        try:
            with open(os.path.join(profile_dir, MODPACK_META_FILENAME),
                      "w", encoding="utf-8") as fh:
                json.dump(meta, fh)
        except OSError:
            pass

        # Self-check: an install that produced zero mods AND zero override
        # files produced nothing playable. Warn loudly instead of reporting
        # a success the Play tab can't make good on. (Config/resourcepack-only
        # packs are legitimate, so this is a warning, not a failure.)
        try:
            _has_jars = any(fn.endswith((".jar", ".jar.disabled"))
                            for fn in os.listdir(profile_dir))
            if not mod_files and not _has_jars:
                status_cb("WARNING: this pack declared no client mods and "
                          "bundled no override mods - nothing to install "
                          "except its config")
        except OSError:
            pass

        status_cb(f"Installed {info['name']}")
        return meta


def _peek_pack_identity(zip_path: str) -> tuple[str, str]:
    """(mc_version, name) from a pack archive, or ("", "") if unreadable.

    Reads only modrinth.index.json - the same file the install reads first -
    so the in-flight claim can be raised BEFORE any byte lands in the game
    folder. A malformed archive yields ("", "") and the install body raises
    its own readable ModpackError instead of a claim leak.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            info = summarize(_read_index(zf))
        return (str(info.get("mc_version") or ""),
                str(info.get("name") or ""))
    except Exception:
        return "", ""


def _peek_pack_claim_target(zip_path: str) -> dict | None:
    """Everything the in-flight claim needs to scope itself to one instance.

    Reads the manifest and, for a reinstall, the existing pack record. A fresh
    install has no version id yet (the clone is created after the loader is
    installed); the body calls ``_update_pack_install`` once it knows it.
    """
    try:
        with zipfile.ZipFile(zip_path) as zf:
            info = summarize(_read_index(zf))
    except Exception:
        return None
    mc_version = str(info.get("mc_version") or "")
    if not mc_version:
        return None
    name = str(info.get("name") or "")
    loader = info.get("loader") or "vanilla"
    try:
        existing = _find_installed_pack(name, mc_version, loader) or {}
    except Exception:
        existing = {}
    return {
        "mc_version": mc_version,
        "name": name,
        "loader": loader,
        "profile": existing.get("profile"),
        "version_id": existing.get("version_id"),
    }


def _install_from_zip(zip_path: str, *, progress_cb=None, status_cb=None, max_cb=None,
                      icon_url: str | None = None) -> dict:
    """`_install_from_zip_body` with the in-flight claim around it.

    The claim must cover the WHOLE body (base version, loader, every mod) and
    must never survive an exception or a cancel - otherwise the instance would
    stay unplayable for the rest of the session. That is why it lives here as
    a wrapper instead of a try/finally indenting the long install body.

    The claim is EXCLUSIVE per base Minecraft version. Two pack installs for
    one base version would both rewrite ``versions/<mc>`` and its loader
    folder, which is exactly how a user ended up with two half-installs and
    two different mod counts. A second click now fails immediately with a
    readable message instead of racing the first.
    """
    target = _peek_pack_claim_target(zip_path)
    if not target:
        # Unreadable archive: let the body raise its own user-facing error.
        return _install_from_zip_body(zip_path, progress_cb=progress_cb,
                                      status_cb=status_cb, max_cb=max_cb,
                                      icon_url=icon_url)

    mc_version = target["mc_version"]
    name = target["name"]
    _mark_pack_install(mc_version, name, exclusive=True,
                       profile=target.get("profile"),
                       version_id=target.get("version_id"))

    def _touch():
        _touch_pack_install(mc_version)

    def _status(text):
        _touch()
        if status_cb:
            status_cb(text)

    def _progress(value):
        _touch()
        if progress_cb:
            progress_cb(value)

    def _maximum(value):
        _touch()
        if max_cb:
            max_cb(value)

    try:
        return _install_from_zip_body(zip_path, progress_cb=_progress,
                                      status_cb=_status, max_cb=_maximum,
                                      icon_url=icon_url)
    finally:
        _unmark_pack_install(mc_version)


def install_modpack_from_file(path: str, *, progress_cb=None, status_cb=None, max_cb=None) -> dict:
    """Install a pack the user already has on disk - either a Modrinth
    `.mrpack` or a CurseForge pack `.zip`. Returns the pack meta (incl. the
    launchable `version_id`).

    The format is decided by what's actually inside the archive, not by its
    extension: a `.mrpack` IS a zip, plenty of browsers hand back
    "rlcraft.zip", and users rename things. Accepting a CF zip here matters
    because it's the one import route that needs no third-party metadata
    service at all - if CF search/cfwidget is down or a pack simply isn't
    listed, downloading it from the website and importing it still works."""
    status_cb = status_cb or _noop
    if not os.path.isfile(path):
        raise ModpackError("Couldn't find that modpack file.")
    try:
        with zipfile.ZipFile(path) as zf:
            names = set(zf.namelist())
    except zipfile.BadZipFile:
        raise ModpackError(
            "That file isn't a modpack - it isn't a readable archive. Modpacks "
            "are Modrinth .mrpack files or CurseForge pack .zip files."
        )

    if "modrinth.index.json" in names:
        return _install_from_zip(path, progress_cb=progress_cb,
                                 status_cb=status_cb, max_cb=max_cb)

    if "manifest.json" in names:
        status_cb("Converting CurseForge pack...")
        fd, tmp_mrpack = tempfile.mkstemp(suffix=".mrpack")
        os.close(fd)
        try:
            _cf_manifest_to_mrpack(path, tmp_mrpack, status_cb=status_cb)
            return _install_from_zip(tmp_mrpack, progress_cb=progress_cb,
                                     status_cb=status_cb, max_cb=max_cb)
        finally:
            try:
                os.remove(tmp_mrpack)
            except OSError:
                pass

    raise ModpackError(
        "That archive isn't a modpack: it has neither a Modrinth "
        "modrinth.index.json nor a CurseForge manifest.json."
    )


def _archive_progress_status(prefix: str, status_cb):
    """A `progress_cb` that shows byte progress for the pack ARCHIVE itself.

    The archive is downloaded before anything else happens, and it is the one
    phase whose size is unknown to the caller (tens of MB for a big pack), so
    a bare "Downloading modpack..." left the user staring at an indeterminate
    bar for the whole transfer. Reports whole-percent only: cubeon.net already
    throttles to >= 33 ms / >= 1%, and status_cb repaints the status line and
    the bar on every call (modpacks_tab), so duplicate percents would be
    wasted repaints.
    """
    seen = {"pct": -1}

    def report(done, total):
        if not total:
            return
        pct = int(done * 100 / total)
        if pct == seen["pct"]:
            return
        seen["pct"] = pct
        status_cb(f"{prefix} {pct}%")

    return report


def install_modpack_from_url(url: str, *, progress_cb=None, status_cb=None, max_cb=None,
                             icon_url: str | None = None) -> dict:
    """Download a `.mrpack` (from a browse result) and install it. The pack
    archive itself must come from the same trusted host allowlist as its
    files. `icon_url` is the browse hit's thumbnail, recorded in the pack meta
    so the installed list can show it."""
    status_cb = status_cb or _noop
    if not _host_allowed(url):
        raise ModpackError("That modpack download isn't from a trusted host.")
    status_cb("Downloading modpack...")
    fd, tmp = tempfile.mkstemp(suffix=".mrpack")
    os.close(fd)
    try:
        _download_to(tmp, [url], None,
                     _archive_progress_status("Downloading modpack...", status_cb))
        return _install_from_zip(tmp, progress_cb=progress_cb, status_cb=status_cb,
                                 max_cb=max_cb, icon_url=icon_url)
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


# ---------------------------------------------------------------------------
# Keyless (no API key) CurseForge pack installation.
#
# With no key the batch-metadata endpoint is off-limits, so a pack's mods can't
# be resolved to real filenames/hashes. They don't need to be: a CF manifest
# already carries the (projectID, fileID) pairs, and CF's own keyless download
# redirect turns each pair into a downloadable URL that passes the host
# allowlist. So the keyless path builds the same mrpack file entries as the
# keyed one, just without a manifest hash to verify against (the transfer is
# still HTTPS to an allowlisted host, and every write path is still checked).
# ---------------------------------------------------------------------------


def _cf_files_keyless(entries: list[dict]) -> list[dict]:
    """mrpack `files` entries built straight from the manifest's numeric ids, via
    CF's keyless download redirect. No API key, no metadata lookup, and - unlike
    the keyed path - no hash to verify, since only the API knows the real SHA-1."""
    mr_files = []
    for e in entries:
        pid, fid = e["projectID"], e["fileID"]
        url = _cf_download_url(pid, fid)
        if not _host_allowed(url):
            continue
        size = e.get("fileSize")
        mr_files.append({
            # The real jar name lives behind the redirect, so the fileID is used
            # as a stable unique filename. Loaders key off jar *contents* (mod
            # metadata), not the filename, so this is cosmetic only.
            "path": f"mods/{fid}.jar",
            "hashes": {},
            "env": {"client": "required", "server": "required"},
            "downloads": [url],
            "fileSize": size if isinstance(size, (int, float)) else 0,
        })
    return mr_files


def _cf_batch_files(entries: list[dict]) -> list[dict]:
    """Resolve (projectID, fileID) pairs to full file metadata via CurseForge's
    batch endpoint. Unknown/removed pairs are simply absent from the result."""
    key = _curseforge_api_key()
    if not key:
        # Guarded explicitly: requests refuses a None header value with an
        # InvalidHeader that surfaces as raw jargon, and the keyless path
        # (_cf_files_keyless) is what should have been used instead.
        raise ModpackError("No CurseForge API key configured.")
    resolved = []
    # POST /v1/mods/files takes {"fileIds": [<int>, ...]} - NOT a list of
    # {projectID, fileID} objects (that shape is what returned the 400 "Bad
    # Request"). File ids are globally unique on CurseForge, so the project id
    # isn't needed; the rows come back with `modId`, which the caller matches on.
    file_ids = []
    for e in entries:
        try:
            fid = int(e["fileID"])
        except (KeyError, TypeError, ValueError):
            continue
        if fid > 0 and fid not in file_ids:
            file_ids.append(fid)
    for i in range(0, len(file_ids), 50):
        resp = requests.post(
            f"{CURSEFORGE_API}/mods/files",
            json={"fileIds": file_ids[i:i + 50]},
            headers={"x-api-key": key,
                     "Accept": "application/json",
                     "Content-Type": "application/json",
                     "User-Agent": user_agent("curseforge")},
            timeout=30)
        if resp.status_code in (401, 403):
            raise ModpackError("CurseForge rejected the API key. Check it in Settings.")
        resp.raise_for_status()
        data = resp.json().get("data")
        if isinstance(data, list):
            resolved.extend(f for f in data if isinstance(f, dict))
    return resolved


def _cf_sha1(file_meta: dict) -> "str | None":
    for h in file_meta.get("hashes") or []:
        if isinstance(h, dict) and h.get("algo") == CF_HASH_SHA1:
            return h.get("value")
    return None


def _cf_manifest_to_mrpack(zip_path: str, dest_mrpack: str, *, status_cb) -> dict:
    """Convert a CurseForge pack zip (manifest.json + overrides/) into a
    standard `.mrpack` so the existing hardened installer can process it.
    Every mod file's real URL and SHA-1 come from CurseForge's own API - the
    manifest only carries numeric ids. Returns the parsed mrpack index dict."""
    with zipfile.ZipFile(zip_path) as zf:
        manifest = json.loads(zf.read("manifest.json").decode("utf-8"))
        if manifest.get("manifestType") not in (None, "minecraftModpack"):
            raise ModpackError("That CurseForge pack has an unexpected manifest type.")
        mc = manifest.get("minecraft") or {}
        mc_version = mc.get("version")
        if not mc_version:
            raise ModpackError("That CurseForge pack doesn't declare a Minecraft version.")
        entries = [f for f in (manifest.get("files") or [])
                   if isinstance(f, dict) and f.get("projectID") and f.get("fileID")]
        if curseforge_enabled():
            status_cb(f"Resolving {len(entries)} mods from CurseForge...")
            by_key = {}
            mr_files = []
            try:
                rows = _cf_batch_files(entries)
            except requests.RequestException as exc:
                # The metadata API being down or picky must not sink the whole
                # install: the keyless redirect can still fetch every file.
                logging.getLogger(__name__).warning(
                    "CurseForge batch lookup failed (%s); using keyless downloads", exc)
                status_cb("CurseForge lookup failed - using direct downloads instead...")
                rows = None
            if rows is None:
                mr_files = _cf_files_keyless(entries)
                rows = []
            for row in rows:
                by_key[(row.get("modId"), row.get("id"))] = row
            # Missing metadata rows are skipped (not fatal): the pack stays
            # installable minus a broken/removed file, matching the CF launcher's
            # own tolerance of removed files.
            for e in (entries if by_key or not mr_files else ()):
                meta = by_key.get((int(e["projectID"]), int(e["fileID"])))
                if not meta:
                    continue
                url = meta.get("downloadUrl") or _cf_download_url(e["projectID"], e["fileID"])
                if not _host_allowed(url):
                    continue
                sha1 = _cf_sha1(meta)
                mr_files.append({
                    "path": f"mods/{meta.get('fileName') or (str(meta.get('id')) + '.jar')}",
                    "hashes": {"sha1": sha1} if sha1 else {},
                    "env": {"client": "required", "server": "required"},
                    "downloads": [url],
                    "fileSize": meta.get("fileLength", 0)
                    if isinstance(meta.get("fileLength"), (int, float)) else 0,
                })
        else:
            # No API key: resolve the ids through CF's keyless download redirect
            # instead of the (key-only) batch metadata endpoint. Without this
            # branch a keyless install died in _cf_batch_files before a single
            # file was fetched, which is what made the classic CurseForge packs
            # (RLCraft, SkyFactory, ...) impossible to install.
            status_cb(f"Preparing {len(entries)} mods from CurseForge...")
            mr_files = _cf_files_keyless(entries)
        if entries and not mr_files:
            raise ModpackError(
                "None of this pack's mods could be resolved from CurseForge. "
                "The pack may have been updated or its files withdrawn."
            )
        dependencies = {"minecraft": str(mc_version)}
        # CF spells loaders "forge-14.23.5.2859" / "fabric-0.14.9" / "quilt-..."
        # / "neoforge-21.1.1"; the mrpack spec wants its own dependency keys
        # (see LOADER_DEP_KEYS). Only forge/neoforge were translated before, so
        # a CF *Fabric* pack converted into a pack declaring no loader at all -
        # it installed as vanilla and none of its mods ever loaded. The loader
        # flagged `primary` wins when a manifest lists more than one.
        for loader in sorted((mc.get("modLoaders") or []),
                             key=lambda l: not (isinstance(l, dict) and l.get("primary"))):
            if not isinstance(loader, dict):
                continue
            name, _, ver = str(loader.get("id") or "").partition("-")
            dep_key = LOADER_TO_DEP_KEY.get(name.strip().lower())
            if dep_key and ver:
                dependencies[dep_key] = ver
                break
        index = {
            "formatVersion": 1,
            "game": "minecraft",
            "name": manifest.get("name") or "CurseForge pack",
            "versionId": manifest.get("version") or "1.0.0",
            "files": mr_files,
            "dependencies": dependencies,
        }
        with zipfile.ZipFile(dest_mrpack, "w", zipfile.ZIP_DEFLATED) as out:
            out.writestr("modrinth.index.json", json.dumps(index))
            # Repack the pack's overrides/ directory as the overrides zip the
            # installer expects. Members are re-added individually so no
            # dotted/absolute name inside the source zip can escape - the
            # installer's own traversal checks re-verify every path anyway.
            overrides_root = (manifest.get("overrides") or "overrides").strip("/") + "/"
            for info in zf.infolist():
                name = info.filename.replace("\\", "/")
                if name.startswith(overrides_root) and not info.is_dir():
                    rel = name[len(overrides_root):]
                    if rel and not rel.startswith("/") and ".." not in rel.split("/"):
                        out.writestr(f"overrides/{rel}", zf.read(info.filename))
        return index


def install_modpack_from_cf(project_id: str, file_id, *,
                            progress_cb=None, status_cb=None, max_cb=None,
                            icon_url: str | None = None) -> dict:
    """Download a CurseForge pack zip and install it through the mrpack
    pipeline. The zip comes from CurseForge's own CDN/redirect endpoints
    (both allowlisted), and every per-mod URL the conversion writes comes
    from CurseForge's API - nothing is taken on faith from the pack."""
    status_cb = status_cb or _noop
    status_cb("Downloading CurseForge modpack...")
    fd, tmp_zip = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
    fd, tmp_mrpack = tempfile.mkstemp(suffix=".mrpack")
    os.close(fd)
    try:
        _download_to(tmp_zip, [_cf_download_url(project_id, file_id)], None,
                     _archive_progress_status("Downloading CurseForge modpack...",
                                              status_cb))
        _cf_manifest_to_mrpack(tmp_zip, tmp_mrpack, status_cb=status_cb)
        return _install_from_zip(tmp_mrpack, progress_cb=progress_cb,
                                 status_cb=status_cb, max_cb=max_cb,
                                 icon_url=icon_url)
    finally:
        for tmp in (tmp_zip, tmp_mrpack):
            try:
                os.remove(tmp)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Export / authoring - turn an installed (version, loader) profile back into a
# shareable `.mrpack`.
# ---------------------------------------------------------------------------

# Reverse of LOADER_DEP_KEYS: Cubeon loader id -> the manifest `dependencies`
# key the `.mrpack` spec expects for it. Used when writing a pack we author.
LOADER_TO_DEP_KEY = {cubeon: key for key, cubeon in LOADER_DEP_KEYS.items()}


def _hash_file(path: str) -> dict:
    """sha1 + sha512 of a file on disk, computed in a single read pass. These
    are the two hashes the `.mrpack` spec uses; we take them from the real jar
    we're shipping (not the sidecar) so the entry describes exactly that file."""
    sha1, sha512 = hashlib.sha1(), hashlib.sha512()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            sha1.update(chunk)
            sha512.update(chunk)
    return {"sha1": sha1.hexdigest(), "sha512": sha512.hexdigest()}


def _read_mod_sidecar(profile_dir: str, filename: str) -> dict:
    """The `.cubeon.json` metadata written next to an installed mod, if any.
    The sidecar name is keyed off the enabled filename, so strip a trailing
    `.disabled` first (a toggled-off mod shares its enabled sidecar)."""
    base = filename[:-len(".disabled")] if filename.endswith(".disabled") else filename
    path = os.path.join(profile_dir, base + MOD_META_SUFFIX)
    if not os.path.isfile(path):
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh) or {}
    except (OSError, json.JSONDecodeError):
        return {}


def _sidecar_download_url(meta: dict) -> str | None:
    """A direct download URL recorded in a mod's sidecar, or None. Accepts the
    few shapes the sidecar might carry it under (a bare `url`, a `downloads`
    list like the manifest's own, etc.) so a richer sidecar is used when it's
    there without requiring one."""
    for key in ("url", "download_url", "downloadUrl"):
        val = meta.get(key)
        if isinstance(val, str) and val:
            return val
    downloads = meta.get("downloads")
    if isinstance(downloads, list):
        for val in downloads:
            if isinstance(val, str) and val:
                return val
    return None


def _loader_version_from_id(version_id: str | None, mc_version: str) -> str | None:
    """Best-effort pull of the loader's own version out of a launchable version
    id (e.g. 'fabric-loader-0.15.11-1.20.1' -> '0.15.11', '1.20.1-forge-47.2.0'
    -> '47.2.0'). Returns the first dotted-number token that isn't the MC
    version, or None if the id carries nothing that looks like one."""
    if not version_id:
        return None
    tokens = [t for t in re.findall(r"\d+(?:\.\d+)+", version_id) if t != mc_version]
    return tokens[0] if tokens else None


def export_mrpack(name: str, version: str, mc_version: str, loader: str,
                  mod_filenames: list[str], dest_path: str, description: str = "",
                  summarize_cb=None, profile: str | None = None) -> str:
    """Write the mods of one installed profile out as a valid Modrinth
    `.mrpack` at dest_path, and return that path.

    This is the mirror image of the install flow above: install reads a
    manifest and lays a profile down, export walks a profile and writes the
    manifest back out. Each selected mod becomes either
      - a `files` entry (path 'mods/<jar>', its download URL, sha1+sha512, and
        size) when its `.cubeon.json` sidecar records a trusted download URL,
        so the pack stays small and re-downloads from source; or
      - a jar bundled straight into `overrides/mods/<jar>` when there's no
        known URL, so a hand-added mod still travels with the pack.
    The hashes are always computed from the real jar on disk, so a `files`
    entry describes exactly the file the author has.

    `dependencies` records the MC version and, for a mod-capable loader, the
    matching `.mrpack` loader key (fabric-loader/quilt-loader/forge/neoforge)
    with the installed loader's version when it can be determined.

    Raises ModpackError (already phrased for the user) on the expected failure
    cases - no name/version, no such profile, or an unwritable destination - so
    the UI can surface the message without a crash. summarize_cb(text), if
    given, receives short human-readable progress lines."""
    summarize_cb = summarize_cb or _noop

    name = (name or "").strip()
    version = (version or "").strip()
    if not name:
        raise ModpackError("Give the modpack a name before exporting it.")
    if not version:
        raise ModpackError("Give the modpack a version (for example 1.0.0).")
    if not mc_version or not loader:
        raise ModpackError("Pick which installed version and loader to export.")

    # `profile` is the profile folder key when exporting an isolated instance.
    # Legacy callers omit it and keep exporting the shared
    # (mc_version, loader) profile.
    if profile:
        profile_dir = profile_dir_for_key(profile)
        if not profile_dir:
            raise ModpackError("That instance's mod profile is invalid.")
    else:
        profile_dir = get_profile_dir(mc_version, loader)
    if not os.path.isdir(profile_dir):
        raise ModpackError("That version and loader has no installed mods to export.")

    # dependencies: the game version, plus the loader under its manifest key.
    dependencies = {"minecraft": mc_version}
    dep_key = LOADER_TO_DEP_KEY.get(loader)
    if dep_key:
        installed_ids = {v["id"] for v in get_installed_versions()}
        version_id = find_installed_loader_version(installed_ids, loader, mc_version)
        # The installer re-resolves the loader build at install time and ignores
        # this value, so when the exact installed build can't be read back we
        # fall back to "*" (any) rather than block the export on it.
        dependencies[dep_key] = _loader_version_from_id(version_id, mc_version) or "*"

    files: list[dict] = []
    bundled: list[tuple[str, str]] = []  # (arcname jar, source path on disk)
    seen_paths: set[str] = set()

    for filename in mod_filenames:
        src = os.path.join(profile_dir, filename)
        if not os.path.isfile(src):
            continue  # deleted/renamed since the picker listed it - just skip
        jar_name = filename[:-len(".disabled")] if filename.endswith(".disabled") else filename
        rel = f"mods/{jar_name}"
        if rel in seen_paths:
            continue
        seen_paths.add(rel)

        meta = _read_mod_sidecar(profile_dir, filename)
        url = _sidecar_download_url(meta)
        if url and _host_allowed(url):
            summarize_cb(f"Linking {jar_name}")
            files.append({
                "path": rel,
                "hashes": _hash_file(src),
                "downloads": [url],
                "fileSize": os.path.getsize(src),
            })
        else:
            # No trusted URL to re-download from - carry the jar itself so the
            # pack is still complete for whoever installs it.
            summarize_cb(f"Bundling {jar_name}")
            bundled.append((jar_name, src))

    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": version,
        "name": name,
        "summary": description or "",
        "files": files,
        "dependencies": dependencies,
    }

    parent = os.path.dirname(dest_path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    summarize_cb("Writing modpack")
    try:
        with zipfile.ZipFile(dest_path, "w", zipfile.ZIP_DEFLATED) as zf:
            zf.writestr("modrinth.index.json", json.dumps(index, indent=2))
            for jar_name, src in bundled:
                zf.write(src, arcname=f"overrides/mods/{jar_name}")
    except OSError as ex:
        raise ModpackError(f"Couldn't write the modpack file: {ex}")

    summarize_cb(f"Exported {name} ({len(files) + len(bundled)} mods)")
    return dest_path


# ---------------------------------------------------------------------------
# Discovery via Modrinth's public API (project_type:modpack) - no auth.
# ---------------------------------------------------------------------------

def _modrinth_modpack_search(query: str, mc_version: str | None, limit: int,
                             offset: int = 0) -> list[dict]:
    """One Modrinth search request, parsed into the browse-UI hit shape.
    Split out of search_modpacks so the UI can render Modrinth results
    immediately while CurseForge (slower, especially keyless via cfwidget)
    is still in flight. `offset` pages through the result set."""
    facets = [["project_type:modpack"]]
    if mc_version:
        facets.append([f"versions:{mc_version}"])

    params = {"query": query, "limit": str(limit), "offset": str(offset),
              "facets": json.dumps(facets),
              "index": modrinth_search_index(query)}
    payload = net.get_json(f"{MODRINTH_API}/search", params=params,
                           headers=modrinth_headers(), timeout=15)
    hits = payload.get("hits") if isinstance(payload, dict) else None
    results = []
    for hit in hits if isinstance(hits, list) else []:
        if not isinstance(hit, dict) or not hit.get("project_id"):
            continue
        results.append({
            "source": "modrinth",
            "project_id": hit.get("project_id"),
            "slug": hit.get("slug"),
            "title": hit.get("title") or hit.get("slug") or "Untitled pack",
            "description": hit.get("description"),
            "icon_url": hit.get("icon_url"),
            "downloads": hit.get("downloads", 0) if isinstance(hit.get("downloads"), (int, float)) else 0,
            "author": hit.get("author"),
            "versions": hit.get("versions") if isinstance(hit.get("versions"), list) else [],
        })
    return results


def search_modpacks_modrinth(query: str, mc_version: str | None = None,
                             limit: int = 40, offset: int = 0) -> list[dict]:
    """Modrinth-only modpack search, cached. Kept separate from the combined
    search so the browse UI can show these hits first."""
    cache_key = {"query": query, "mc_version": mc_version, "limit": limit,
                 "offset": offset}

    def fetch():
        return _modrinth_modpack_search(query, mc_version, limit, offset)

    # cached_call: fresh cache wins; on a failed fetch the last known results
    # are served instead of an error (a launcher showing yesterday's search
    # beats a spinner), and nothing here ever blocks on a refresh.
    return local_cache.cached_call("search_modpacks_mr", cache_key, fetch,
                                   background_refresh=False)


def search_modpacks_curseforge(query: str, mc_version: str | None = None,
                               limit: int = 40, offset: int = 0) -> list[dict]:
    """CurseForge-only modpack search, cached. Keyless access (cfwidget) is
    slow - up to a dozen 4s probes - so this runs as its own phase the UI
    merges in whenever it lands. Only the keyed CurseForge API paginates;
    keyless cfwidget returns its small curated set for the first page and
    nothing for later offsets (so classics never repeat on every page).

    `keyed` is part of the cache key on purpose: pasting or removing a
    CurseForge key swaps the provider (curated classics <-> the real API), and
    without this the tab would keep serving the OTHER provider's cached page
    for up to a day."""
    cache_key = {"query": query, "mc_version": mc_version, "limit": limit,
                 "offset": offset, "keyed": bool(_curseforge_api_key())}

    def fetch():
        if offset and not curseforge_enabled():
            return []
        return _curseforge_search(query, mc_version, limit, offset)

    return local_cache.cached_call("search_modpacks_cf", cache_key, fetch,
                                   background_refresh=False)


def merge_modpack_hits(mr_hits: list[dict], cf_hits: list[dict], query: str) -> list[dict]:
    """Combined ranking for Modrinth + CurseForge hits, plus the exact-name
    CurseForge promotion: a CF pack whose title or slug contains the query IS
    the exact match the user means (typing "rlcraft" - the pack, not a
    Modrinth mod with "rlcraft" in its name), and Modrinth's relevance never
    saw these hits, so they're promoted to the front when they genuinely match."""
    results = list(mr_hits) + list(cf_hits)
    results = rank_search_hits(results, query)
    q = (query or "").strip().lower()
    if q:
        exact_cf = [h for h in results
                    if h.get("source") == "curseforge"
                    and (q in (h.get("title") or "").lower()
                         or q in (h.get("slug") or "").lower())]
        others = [h for h in results
                  if not (h.get("source") == "curseforge"
                          and (q in (h.get("title") or "").lower()
                               or q in (h.get("slug") or "").lower()))]
        results = exact_cf + others
    return results


def search_modpacks(query: str, mc_version: str | None = None, limit: int = 40,
                    offset: int = 0) -> list[dict]:
    """Search Modrinth for modpacks (optionally scoped to an MC version via
    the `versions:` facet - advisory on Modrinth's side, same caveat as
    get_modpack_file(); results still carry their own `versions` list so
    the caller can show a compatibility hint rather than trust the facet
    blindly). Returns simplified hit dicts for the browse UI.

    The Modrinth and CurseForge providers run IN PARALLEL: previously the CF
    fetch (which is the slow one, keyless cfwidget probes especially) only
    started after Modrinth finished, roughly doubling every uncached search.
    Tolerant of a malformed/unexpected API response shape (missing `hits`,
    a non-list `hits`, or a non-dict entry) - skips what it can't use
    instead of raising, since this hits a third-party endpoint outside this
    project's control. `offset` pages through both providers."""
    cache_key = {"query": query, "mc_version": mc_version, "limit": limit,
                 "offset": offset}

    def fetch():
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            mr_fut = pool.submit(search_modpacks_modrinth, query, mc_version, limit, offset)
            cf_fut = pool.submit(search_modpacks_curseforge, query, mc_version, limit, offset)
            try:
                mr = mr_fut.result()
            except Exception:
                mr = None  # Modrinth down - CF hits may still be worth showing
            try:
                cf = cf_fut.result()
            except Exception:
                cf = []
        if mr is None:
            if cf:
                mr = []
            else:
                raise RuntimeError("couldn't reach Modrinth or CurseForge")
        return merge_modpack_hits(mr, cf, query)

    return local_cache.cached_call("search_modpacks", cache_key, fetch,
                                   background_refresh=False)


def get_popular_modpacks(mc_version: str | None = None, limit: int = 40,
                         offset: int = 0) -> list[dict]:
    """The default browse list before the user searches: most-downloaded packs."""
    return search_modpacks("", mc_version=mc_version, limit=limit, offset=offset)


# ---------------------------------------------------------------------------
# CurseForge provider (the other big platform - RLCraft, SkyFactory, DawnCraft
# and most other classic packs are CurseForge exclusives).
#
# Uses CurseForge's official API, which requires an API key. **One key ships
# with Cubeon** (2026-10-18) so every user gets the full catalogue with nothing
# to configure: see _curseforge_api_key() for the lookup order. The per-user
# "paste your own key" dialog was REMOVED in the same pass, by the operator's
# decision - a launcher asking a player for an API key is a bug report, not a
# feature, and Cubeon is the one that should apply for it.
#
# CF packs are NOT `.mrpack` - they're plain zips with a manifest.json of
# (projectID, fileID) pairs. install_modpack_from_cf() downloads the zip,
# resolves every file's real URL/hash via the API, converts the pack into a
# standard .mrpack in a temp dir, and reuses the existing hardened install
# pipeline (_install_from_zip) - same allowlist/slip/hash checks.
# ---------------------------------------------------------------------------

CURSEFORGE_API = "https://api.curseforge.com/v1"
CF_GAME_ID_MINECRAFT = 432
CF_CLASS_ID_MODPACK = 4471
CF_HASH_SHA1 = 1  # hash algo id for SHA-1 in CurseForge's API


def _builtin_curseforge_api_key() -> str:
    """The key Cubeon SHIPS with, or "" when this build carries none.

    `cubeon/_cf_key.py` is generated at build time from the
    `CURSEFORGE_API_KEY` GitHub secret (see .github/workflows/build.yml) and is
    gitignored, so the key never enters the repository or its history - which
    matters, because this repo is public and a committed key is a revoked key.
    A source checkout without the file simply has no builtin key and falls back
    to the classic list, exactly like a build made without the secret.
    """
    try:
        from . import _cf_key
        key = getattr(_cf_key, "BUILTIN_KEY", "") or ""
        return key.strip() if isinstance(key, str) else ""
    except Exception:
        return ""


def _curseforge_api_key() -> "str | None":
    """The CurseForge API key to use, or None.

    Order, most specific first:
      1. the CURSEFORGE_API_KEY environment variable (testers, support: point a
         source checkout at a different key without touching the shipped one)
      2. the first line of ~/.cubeon_launcher/curseforge_api_key (a local
         override file, gitignored, no config edit needed)
      3. "curseforge_api_key" in ~/.cubeon_launcher/config.json (what
         set_curseforge_api_key writes)
      4. the key baked into this build at package time (cubeon/_cf_key.py)

    Every step is optional. With none of them the provider is dormant and the
    tab shows the curated classics instead - a missing key is a smaller
    catalogue, never an error.
    """
    key = os.environ.get("CURSEFORGE_API_KEY")
    if key:
        return key.strip()
    from .paths import CUBEON_HOME
    try:
        with open(os.path.join(CUBEON_HOME, "curseforge_api_key"),
                  "r", encoding="utf-8") as f:
            first = f.readline().strip()
        if first:
            return first
    except OSError:
        pass
    try:
        from .config import load_config
        key = (load_config() or {}).get("curseforge_api_key")
        if isinstance(key, str) and key.strip():
            return key.strip()
    except Exception:
        pass
    return _builtin_curseforge_api_key() or None


def curseforge_enabled() -> bool:
    """True when a CurseForge API key is configured - the provider's gate."""
    return bool(_curseforge_api_key())


def set_curseforge_api_key(key: str) -> bool:
    """Persist (or clear, with an empty key) a LOCAL CurseForge key override.

    No longer reachable from the UI (2026-10-18): the button that called it was
    removed, because Cubeon now ships one key for everybody (see
    _curseforge_api_key() step 4). This stays for support and for the tests -
    it is the only way to override the shipped key without restarting with an
    environment variable, and it still resolves ABOVE the builtin one.
    Returns True when the stored config is now readable back.
    """
    from .config import load_config, save_config
    try:
        cfg = dict(load_config() or {})
        cleaned = (key or "").strip()
        if cleaned:
            cfg["curseforge_api_key"] = cleaned
        else:
            cfg.pop("curseforge_api_key", None)
        save_config(cfg)
        # Verify the CONFIG, not the RESOLVED key: a build can carry its own
        # key (cubeon/_cf_key.py), so clearing a local override must not report
        # failure just because the shipped key is still there.
        stored = (load_config() or {}).get("curseforge_api_key") or ""
        return (stored.strip() if isinstance(stored, str) else "") == cleaned
    except Exception:
        return False


def _cf_request(path: str, params: "dict | None" = None, timeout: int = 10,
                key: "str | None" = None):
    """One CurseForge API GET. Raises requests exceptions like the Modrinth
    paths do - callers are already tolerant of third-party failures. `key` is
    only for validating a key the user just pasted (before it is stored)."""
    key = (key or _curseforge_api_key() or "").strip()
    if not key:
        raise ModpackError("No CurseForge API key configured.")
    headers = {
        "User-Agent": user_agent("curseforge"),
        "Accept": "application/json",
        "x-api-key": key,
    }
    return net.get_json(f"{CURSEFORGE_API}{path}", params=params,
                        headers=headers, timeout=timeout)


def check_curseforge_api_key(key: str) -> dict:
    """Try a pasted CurseForge key with one cheap, real API call.

    Returns {"ok": bool, "error": str, "count": int}. Validating before saving
    matters: a wrong key silently degrades to the curated-classics list, which
    looks like "the app is broken" rather than "that key is wrong".
    """
    cleaned = (key or "").strip()
    if not cleaned:
        return {"ok": False, "error": "Paste your key first.", "count": 0}
    try:
        payload = _cf_request("/mods/search", params={
            "gameId": str(CF_GAME_ID_MINECRAFT),
            "classId": str(CF_CLASS_ID_MODPACK),
            "index": "0",
            "pageSize": "5",
        }, key=cleaned)
    except Exception as ex:
        return {"ok": False, "error": f"{type(ex).__name__}: {ex}"[:140],
                "count": 0}
    data = payload.get("data") if isinstance(payload, dict) else None
    return {"ok": True, "error": "", "count": len(data) if isinstance(data, list) else 0}


def _cf_download_url(project_id, file_id) -> str:
    """The keyless download-redirect URL for a CF file - works even when the
    API omits downloadUrl (older files) and is the same endpoint the website
    itself hands to the browser before its CDN redirect."""
    return (f"https://www.curseforge.com/api/v1/mods/{project_id}"
            f"/files/{file_id}/download")


# ---------------------------------------------------------------------------
# Keyless CurseForge access via CFWidget (api.cfwidget.com) - no API key.
# CFWidget can't search, only resolve a project id or website path, so the
# keyless browse/search uses a curated list of the famous CurseForge packs
# plus slug-probing for whatever the user typed. With an API key the real
# search API is used instead and none of this runs.
# ---------------------------------------------------------------------------

CFWIDGET_API = "https://api.cfwidget.com"

# The classics people mean when they say "where is RLCraft". Paths resolve
# through cfwidget's website-path form; dead entries just yield nothing.
#
# Numeric PROJECT IDS are preferred over slugs: CurseForge renames a project's
# slug far more often than it reissues its id, so a slug list rots (that is
# exactly how 5 of the original 12 entries turned into 404s and the browse
# quietly fell to 7 packs). Verified live 2026-09-24 via
# `api.cfwidget.com/minecraft/cf/mods/<id>`.
CURATED_CF_PROJECTS = (
    "cf/mods/285109",    # RLCraft
    "cf/mods/296062",    # SkyFactory 4
    "cf/mods/715572",    # All the Mods 9
    "cf/mods/452013",    # Better MC [FABRIC]
    "cf/mods/936875",    # Craft to Exile 2
    "cf/mods/482878",    # Better MC [FORGE]
    "cf/mods/899572",    # All of Fabric 7
    "cf/mods/327085",    # FantasyCraft
    "cf/mods/287710",    # Ages of Time
    "modpacks/rlcraft",  # kept: a live slug is a free backstop for the ids
)


def _cfwidget_fetch(path: str) -> "dict | None":
    """One CFWidget project lookup (by numeric id or website path). Cached an
    hour - cfwidget rate-limits and is itself a cache of CurseForge. Returns
    None for unknown/queued/error responses rather than raising."""
    cached = local_cache.get("cfwidget", path, max_age=3600)
    if cached is not None:
        return cached
    try:
        # 4s, not 8: cfwidget is probed up to a dozen times per search (6-way
        # parallel) and is itself a cache - a slow probe is nearly always a
        # dead slug or rate-limit, and waiting longer just stalls the search.
        resp = requests.get(f"{CFWIDGET_API}/{path}", timeout=4,
                            headers=modrinth_headers())
        if resp.status_code != 200:
            return None
        data = resp.json()
    except Exception:
        return None
    # "in queue" responses have no files - treat as unknown this time.
    if not isinstance(data, dict) or "id" not in data or not isinstance(data.get("files"), list):
        return None
    return local_cache.set("cfwidget", path, data)


def _cfwidget_to_hit(widget: dict) -> "dict | None":
    """A CFWidget project payload → the search-hit dict shape the UI renders.

    Every field here used to be hardcoded empty/zero ("no icon, 0 downloads, no
    author"), which is why the CurseForge rows rendered as blank squares
    saying "0 downloads" while Modrinth rows next to them looked normal. The
    payload actually carries all of it:

      thumbnail          -> the pack's art (media.forgecdn.net)
      downloads          -> {"monthly": N, "total": N}  (NOT a scalar - reading
                            it as one is what printed 0 for RLCraft's 30M)
      members[0]         -> the author
      versions{ "1.12.2": [files] }  -> the Minecraft versions the pack covers
                            (the older flat `files` list is still accepted)
    """
    try:
        # No id => nothing can be routed or installed (a "None" project_id
        # would silently fall through to the Modrinth path and 404 there).
        if not widget.get("id"):
            return None
        page = ((widget.get("urls") or {}).get("curseforge") or "").rstrip("/")
        versions = []
        grouped = widget.get("versions")
        sources = []
        if isinstance(grouped, dict):
            for files in grouped.values():
                if isinstance(files, list):
                    sources.extend(files)
        elif isinstance(grouped, list):
            sources.extend(grouped)
        if not sources:
            sources = widget.get("files") or []
        for f in sources:
            if not isinstance(f, dict):
                continue
            for v in (f.get("versions") or []):
                # Loader tags ("Forge") also show up here; only real MC
                # versions are useful for the compatibility hint.
                if isinstance(v, str) and v[:1].isdigit() and v not in versions:
                    versions.append(v)
        downloads = widget.get("downloads")
        if isinstance(downloads, dict):
            downloads = downloads.get("total")
        members = widget.get("members") or []
        author = None
        if members and isinstance(members[0], dict):
            author = members[0].get("username") or members[0].get("title")
        thumbnail = widget.get("thumbnail")
        return {
            "source": "curseforge",
            "project_id": str(widget.get("id")),
            "slug": page.split("/")[-1] if page else None,
            "title": widget.get("title") or "Untitled pack",
            "description": widget.get("summary"),
            "icon_url": thumbnail if isinstance(thumbnail, str) and thumbnail else None,
            "downloads": downloads if isinstance(downloads, (int, float)) else 0,
            "author": author,
            "versions": versions,
        }
    except Exception:
        return None


def _cfwidget_search(query: str, limit: int) -> list[dict]:
    """Keyless CF search: slug-probe the query, plus scan the curated classics
    for a title/slug match (browse = just the curated list, downloads-ordered)."""
    from concurrent.futures import ThreadPoolExecutor
    q = (query or "").strip().lower()
    if q:
        # A typed name is probed as a website path first (so "rlcraft" finds
        # even a pack that isn't in the curated list), then the curated set.
        paths = [f"modpacks/{q.replace(' ', '-')}"] + list(CURATED_CF_PROJECTS)
    else:
        paths = list(CURATED_CF_PROJECTS)
    with ThreadPoolExecutor(max_workers=6) as pool:
        widgets = [w for w in pool.map(_cfwidget_fetch,
                                       [f"minecraft/{p}" for p in paths]) if w]
    hits, seen = [], set()
    for w in widgets:
        hit = _cfwidget_to_hit(w)
        if not hit or hit["project_id"] in seen:
            continue
        if q and q not in (hit["title"] or "").lower() \
                and q not in (hit["slug"] or ""):
            continue
        seen.add(hit["project_id"])
        hits.append(hit)
    hits.sort(key=lambda h: h["downloads"], reverse=True)
    return hits[:limit]


def _curseforge_search(query: str, mc_version: "str | None", limit: int,
                       offset: int = 0) -> list[dict]:
    """CF search hits in the same dict shape the Modrinth path returns, tagged
    source='curseforge'. Any failure (no key, network, schema drift) degrades
    to an empty list rather than breaking the Modrinth results. Keyless
    cfwidget can't paginate (it returns a small curated set), so offset only
    applies to the keyed CurseForge API path."""
    if not curseforge_enabled():
        return _cfwidget_search(query, limit)
    try:
        payload = _cf_request("/mods/search", params={
            "gameId": str(CF_GAME_ID_MINECRAFT),
            "classId": str(CF_CLASS_ID_MODPACK),
            "searchFilter": query or "",
            "sortField": "2",   # 2 = Popularity (downloads) - matches browse
            "sortOrder": "desc",
            "index": str(offset),
            "pageSize": str(min(limit, 50)),
        })
    except Exception:
        # A key CurseForge REFUSES for /mods/search must never leave the tab
        # emptier than having no key at all. Seen live 2026-10-18: a valid key
        # (single-project lookups return 200) answered 403 "API Key missing or
        # invalid" on exactly this endpoint, which silently turned the
        # CurseForge half of the tab into nothing. Fall back to the keyless
        # curated set - only on the first page, because cfwidget cannot
        # paginate and repeating the classics on page 2 would look broken.
        return _cfwidget_search(query, limit) if not offset else []
    data = payload.get("data") if isinstance(payload, dict) else None
    results = []
    for hit in data if isinstance(data, list) else []:
        if not isinstance(hit, dict) or not hit.get("id"):
            continue
        logo = hit.get("logo") or {}
        authors = hit.get("authors") or []
        # A hit has no single versions list; approximate from the latest
        # files' game versions so the UI's mismatch hint keeps working.
        versions = []
        for idx in hit.get("latestFilesIndexes") or []:
            v = idx.get("gameVersion") if isinstance(idx, dict) else None
            if v and v not in versions:
                versions.append(v)
        results.append({
            "source": "curseforge",
            "project_id": str(hit.get("id")),
            "slug": hit.get("slug"),
            "title": hit.get("name") or "Untitled pack",
            "description": hit.get("summary"),
            "icon_url": logo.get("thumbnailUrl") if isinstance(logo, dict) else None,
            "downloads": hit.get("downloadCount", 0) if isinstance(hit.get("downloadCount"), (int, float)) else 0,
            "author": (authors[0].get("name") if isinstance(authors, list)
                       and authors and isinstance(authors[0], dict) else None),
            "versions": versions,
        })
    return results


def _curseforge_get_modpack_file(project_id: str, mc_version: "str | None") -> "dict | None":
    """The newest installable pack file for a CF project, optionally scoped to
    an MC version. Same shape as get_modpack_file() plus file_id/source."""
    if not curseforge_enabled():
        return _cfwidget_get_modpack_file(project_id, mc_version)
    params = {"pageSize": "100"}
    if mc_version:
        params["gameVersion"] = mc_version
    payload = _cf_request(f"/mods/{project_id}/files", params=params)
    data = payload.get("data") if isinstance(payload, dict) else None
    files = [f for f in (data if isinstance(data, list) else [])
             if isinstance(f, dict) and f.get("id")]
    if mc_version:
        # The API filter can also match mod files inside the same project;
        # re-check locally and refuse rather than guess.
        files = [f for f in files
                 if mc_version in (f.get("gameVersions") or [])]
    files = [f for f in files
             if isinstance(f.get("fileName"), str)
             and f["fileName"].lower().endswith(".zip")]
    if not files:
        return None
    files.sort(key=lambda f: f.get("fileDate") or "", reverse=True)
    chosen = files[0]
    url = chosen.get("downloadUrl") or _cf_download_url(project_id, chosen["id"])
    if not _host_allowed(url):
        return None
    versions = chosen.get("gameVersions") or []
    loaders = [v for v in versions if isinstance(v, str) and
               v.lower() in ("forge", "neoforge", "fabric", "quilt")]
    return {
        "source": "curseforge",
        "project_id": str(project_id),
        "file_id": chosen["id"],
        "filename": chosen.get("fileName"),
        "url": url,
        "size_kb": round(chosen.get("fileLength", 0) / 1024, 1)
        if isinstance(chosen.get("fileLength"), (int, float)) else 0.0,
        "version_number": chosen.get("displayName") or str(chosen.get("id")),
        "game_versions": versions,
        "loaders": loaders,
    }


def _cfwidget_get_modpack_file(project_id: str, mc_version: "str | None") -> "dict | None":
    """Keyless pack-file pick from a CFWidget project payload: newest published
    zip (optionally version-scoped), same shape as _curseforge_get_modpack_file."""
    widget = _cfwidget_fetch(project_id) or _cfwidget_fetch(f"minecraft/modpacks/{project_id}")
    files = [f for f in (widget.get("files") or [] if isinstance(widget, dict) else [])
             if isinstance(f, dict) and f.get("id") and f.get("type") != "source"]
    if mc_version:
        files = [f for f in files if mc_version in (f.get("versions") or [])]
    if not files:
        return None
    files.sort(key=lambda f: f.get("uploaded_at") or "", reverse=True)
    chosen = files[0]
    url = _cf_download_url(project_id, chosen["id"])
    if not _host_allowed(url):
        return None
    return {
        "source": "curseforge",
        "project_id": str(project_id),
        "file_id": chosen["id"],
        "filename": chosen.get("name") or f"{chosen['id']}.zip",
        "url": url,
        "size_kb": round(chosen.get("filesize", 0) / 1024, 1)
        if isinstance(chosen.get("filesize"), (int, float)) else 0.0,
        "version_number": chosen.get("name") or str(chosen["id"]),
        "game_versions": chosen.get("versions") or [],
        "loaders": [],
    }


def get_modpack_file(project_id_or_slug: str, mc_version: str | None = None) -> dict | None:
    """Find a usable version of a modpack project and return its primary
    `.mrpack` file: {filename, url, version_number, game_versions, loaders}.

    `game_versions` is passed to Modrinth's API as a filter, but that filter
    is advisory, not guaranteed - a project can still return version entries
    that don't actually list mc_version (Modrinth's own docs note this can
    happen for older/loosely-tagged projects). The old code trusted
    versions[0] unconditionally, so on a mismatch it would happily hand back
    a `.mrpack` targeting a completely different, possibly-unsupported
    Minecraft/loader combination (that's how a Forge/NeoForge build number
    like "26.2" could end up fed into mll as if it were an MC version -
    parse_dependencies() reads the pack's own declared dependencies, and if
    those are wrong for what the user actually has installed, mll's install
    call blows up far from the actual mistake).

    Now: when mc_version is given, results are filtered to entries that
    actually declare it in their own game_versions list, sorted by
    date_published (not API order, which isn't documented as guaranteed) so
    the *newest matching* one wins - never just the newest overall. If
    nothing matches, returns None rather than silently falling back to an
    incompatible file.

    Defensive against API/schema drift on purpose - this hits a third-party
    endpoint whose response shape isn't under this project's control:
    - A non-list response (error body, null, etc.) is treated as "no
      versions" rather than crashing on iteration.
    - Each version entry is skipped (not fatal) if it's missing the fields
      this function needs, rather than raising into the caller.
    - The chosen file's URL is re-checked against the same host allowlist
      the rest of the installer enforces (_host_allowed) - a version
      response with an unexpected/malicious download host is refused here,
      before it ever reaches a Download button.

    Routing: Modrinth project ids are base32-style strings (base-32 alphabet,
    so they essentially always contain letters); CurseForge ids are purely
    numeric. A numeric id therefore unambiguously routes to the CurseForge
    provider - keyless (cfwidget) or API-keyed - that's how a merged search
    result from either platform resolves back to the right store.
    """
    if str(project_id_or_slug).isdigit():
        cache_key = {"cf_file": project_id_or_slug, "mc_version": mc_version}
        cached = local_cache.get("modpack_file", cache_key)
        if cached is not None:
            return cached
        try:
            result = _curseforge_get_modpack_file(str(project_id_or_slug), mc_version)
        except Exception:
            result = None
        return local_cache.set("modpack_file", cache_key, result)

    params = {}
    if mc_version:
        params["game_versions"] = json.dumps([mc_version])

    cache_key = {"project": project_id_or_slug, "mc_version": mc_version}
    cached = local_cache.get("modpack_file", cache_key)
    if cached is not None:
        return cached

    versions = net.get_json(f"{MODRINTH_API}/project/{project_id_or_slug}/version",
                            params=params, headers=modrinth_headers(), timeout=15)
    if not isinstance(versions, list) or not versions:
        return local_cache.set("modpack_file", cache_key, None)

    # Keep only entries that are shaped the way this function needs -
    # anything malformed is skipped rather than allowed to crash sorting
    # or comparison below.
    usable = [v for v in versions if isinstance(v, dict) and isinstance(v.get("files"), list)]
    if not usable:
        return local_cache.set("modpack_file", cache_key, None)

    if mc_version:
        usable = [v for v in usable if mc_version in (v.get("game_versions") or [])]
        if not usable:
            # The API's own filter should have excluded these, but don't
            # trust that - re-check locally and refuse rather than guess.
            return local_cache.set("modpack_file", cache_key, None)

    # Sort by date_published, newest first - explicit rather than assuming
    # the API always returns newest-first (that ordering isn't documented
    # as a stable contract). Entries with an unparseable/missing date sort
    # last rather than crashing the sort or winning by accident.
    def _pub_key(v):
        raw = v.get("date_published")
        return raw if isinstance(raw, str) else ""

    usable.sort(key=_pub_key, reverse=True)
    chosen = usable[0]

    files = chosen.get("files") or []
    primary = next((f for f in files if isinstance(f, dict) and f.get("primary")),
                    next((f for f in files if isinstance(f, dict)), None))
    if not primary:
        return local_cache.set("modpack_file", cache_key, None)

    url = primary.get("url")
    if not url or not _host_allowed(url):
        # Refuse rather than hand back a file the rest of the installer
        # would reject anyway (or, worse, a host it wouldn't have checked
        # if some future caller skips install_modpack_from_url's own
        # validation and downloads this url directly).
        return local_cache.set("modpack_file", cache_key, None)

    size = primary.get("size")
    size_kb = round(size / 1024, 1) if isinstance(size, (int, float)) else 0.0

    return local_cache.set("modpack_file", cache_key, {
        "filename": primary.get("filename"),
        "url": url,
        "size_kb": size_kb,
        "version_number": chosen.get("version_number"),
        "game_versions": chosen.get("game_versions") or [],
        "loaders": chosen.get("loaders") or [],
    })


def list_installed_modpacks() -> list[dict]:
    """Every profile that was created by installing a modpack, newest scan
    order. Used to show 'Installed packs' and let Play jump to one.

    De-duplicated by pack identity (name + Minecraft version + loader). A
    profile can end up with two markers for one pack - a legacy shared profile
    and an isolated clone from a later reinstall - and listing both is exactly
    the "it installed the pack twice, with different mod counts" report. The
    surviving entry is the one whose version folder still exists, then the
    newest marker.
    """
    packs: dict[tuple, dict] = {}
    if not os.path.isdir(PROFILES_DIR):
        return []
    for key in sorted(os.listdir(PROFILES_DIR)):
        meta_path = os.path.join(PROFILES_DIR, key, MODPACK_META_FILENAME)
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
            mtime = os.path.getmtime(meta_path)
        except (OSError, json.JSONDecodeError):
            continue
        if not isinstance(meta, dict):
            continue
        # Installs made before instance isolation have no recorded profile
        # key; the folder they sit in IS the key.
        meta.setdefault("profile", key)
        identity = (str(meta.get("name") or "").strip().lower(),
                    str(meta.get("mc_version") or ""),
                    str(meta.get("loader") or "vanilla"))

        def _rank(item):
            candidate, stamp = item
            vid = candidate.get("version_id")
            exists = bool(vid and os.path.isdir(
                os.path.join(MINECRAFT_DIR, "versions", str(vid))))
            return (exists, stamp)

        previous = packs.get(identity)
        if previous is None or _rank((meta, mtime)) > _rank(previous):
            packs[identity] = (meta, mtime)
    return [meta for meta, _mtime in packs.values()]


def forget_modpack_for_version(version_id: str) -> bool:
    """Removes the modpack-tracking record (`_modpack.json`) for whichever
    installed profile was created by installing this launchable version_id,
    if any. Returns True if a record was found and removed.

    This is NOT a mod/profile deletion - the mod jars, configs, and the
    profile folder itself are left alone (mod profiles are shared/reusable
    by design, same reasoning as versions.delete_version()'s docstring).
    Only the small JSON record that makes list_installed_modpacks() report
    this pack as "installed" is removed.

    Exists because deleting a version via versions.delete_version() removes
    `.minecraft/versions/<id>` but has no reason to know about modpacks at
    all - it operates purely on the versions folder. Without this, a
    modpack's meta file would sit in mod_profiles/ forever after its
    version was deleted, so "Installed packs" on the Modpacks tab kept
    listing packs the user had already deleted from the Play tab, with a
    Play button that led nowhere. Call this alongside delete_version(vid)
    from the UI, not as a replacement for it.
    """
    if not version_id or not os.path.isdir(PROFILES_DIR):
        return False
    found = False
    for key in os.listdir(PROFILES_DIR):
        meta_path = os.path.join(PROFILES_DIR, key, MODPACK_META_FILENAME)
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                meta = json.load(fh)
        except (OSError, json.JSONDecodeError):
            continue
        if meta.get("version_id") != version_id:
            continue
        try:
            os.remove(meta_path)
            found = True
        except OSError:
            pass
    return found
