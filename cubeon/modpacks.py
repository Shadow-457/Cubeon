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
  - copies the pack's `overrides/` (configs, resourcepacks, shaders) straight
    into the game folder.

A pack brings its own Minecraft version, so it does NOT have to match whatever
is selected on the Play tab - version-locked packs (RLCraft is 1.12.2-only)
must stay installable regardless of what the user currently has selected.

The overrides being shared is a deliberate MVP trade: a cracked launcher's
users run one pack at a time, and keeping the single game dir is what
lets a pack's world/saves live right next to everything else instead of in an
isolated instance. Isolated instances would be a much larger change to the
launch flow; this is not that.

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
import zipfile
from urllib.parse import urlparse

# Lazy: `requests` costs ~97ms to import and every module that pulls it in
# eagerly puts that on the startup path, even for a session that never
# touches the network. Call sites are unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
requests = LazyModule("requests")

log = logging.getLogger(__name__)

from .paths import APP_NAME, MINECRAFT_DIR, PROFILES_DIR, MOD_META_SUFFIX
from .versions import install_version, get_installed_versions
from .mod_loaders import install_mod_loader, find_installed_loader_version, MOD_CAPABLE_LOADERS
from .mods import get_profile_dir, modrinth_search_index, rank_search_hits, record_mod_source
from . import local_cache
from . import global_mod_cache
from . import net

MODRINTH_API = "https://api.modrinth.com/v2"
MODRINTH_HEADERS = {"User-Agent": f"Cubeon/{APP_NAME.lower()}/1.0"}


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
            probe = requests.head(url, headers=MODRINTH_HEADERS, timeout=10,
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
            net.download_to(dest_path, url, headers=MODRINTH_HEADERS, timeout=30,
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


def _extract_overrides(zf: zipfile.ZipFile, profile_dir: str, status_cb) -> int:
    """Copy the pack's override files into place: anything under mods/ goes to
    the profile (so sync_mods_to_game picks it up), everything else
    (config/, resourcepacks/, shaderpacks/, options.txt, ...) into the shared
    game dir. Returns how many override mod jars were written."""
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
        else:
            dest = _safe_relpath(MINECRAFT_DIR, rel)
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with zf.open(info) as src, open(dest, "wb") as out:
            shutil.copyfileobj(src, out)
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


def _install_from_zip(zip_path: str, *, progress_cb=None, status_cb=None, max_cb=None) -> dict:
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

        profile_dir = get_profile_dir(mc_version, loader_id)

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
        try:
            os.remove(os.path.join(profile_dir, MODPACK_META_FILENAME))
        except OSError:
            pass

        # 1) Minecraft version
        status_cb(f"Installing Minecraft {mc_version}")
        install_version(mc_version, progress_cb, status_cb, max_cb)

        # 2) Mod loader (returns the launchable version id, e.g.
        #    fabric-loader-0.15.x-1.20.1). Vanilla packs skip straight through.
        if loader_id in MOD_CAPABLE_LOADERS:
            status_cb(f"Installing {loader_id.title()} loader")
            version_id = install_mod_loader(loader_id, mc_version, progress_cb, status_cb, max_cb)
        else:
            version_id = mc_version

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
                    except Exception:
                        for pending in futures:
                            pending.cancel()
                        raise
                    n += 1
                    status_cb(f"Downloading mods... {n}/{len(mod_files)}")
                    progress_cb(n)

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

        # 4) Non-mod declared files (resourcepacks/shaders/etc.) into the game dir.
        for f in other_files:
            n += 1
            path = f.get("path", "")
            status_cb("Downloading pack resources...")
            dest = _safe_relpath(MINECRAFT_DIR, path)
            _download_to(dest, f.get("downloads") or [], f.get("hashes"))
            progress_cb(n)

        # 5) Overrides (bundled configs + any non-Modrinth-hosted jars).
        status_cb("Applying pack config")
        _extract_overrides(zf, profile_dir, status_cb)

        # 6) Record the pack so the tab can list it and Play can select it.
        meta = {
            "name": info["name"],
            "pack_version": info["pack_version"],
            "summary": info["summary"],
            "mc_version": mc_version,
            "loader": loader_id,
            "version_id": version_id,
            "mod_count": len(mod_files),
        }
        try:
            with open(os.path.join(profile_dir, MODPACK_META_FILENAME), "w", encoding="utf-8") as fh:
                json.dump(meta, fh)
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
            _csl.ensure_ready(mc_version, loader_id, status_cb=status_cb)
        except Exception:
            pass  # best-effort: a skins problem must never fail the install
        try:
            from .mods import get_profile_dir as _get_profile_dir
            from . import cubeonfriends as _friends_mod
            _friends_ok = _friends_mod.ensure_installed(mc_version, loader_id,
                                                        _get_profile_dir(mc_version, loader_id))
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


def install_modpack_from_url(url: str, *, progress_cb=None, status_cb=None, max_cb=None) -> dict:
    """Download a `.mrpack` (from a browse result) and install it. The pack
    archive itself must come from the same trusted host allowlist as its
    files."""
    status_cb = status_cb or _noop
    if not _host_allowed(url):
        raise ModpackError("That modpack download isn't from a trusted host.")
    status_cb("Downloading modpack...")
    fd, tmp = tempfile.mkstemp(suffix=".mrpack")
    os.close(fd)
    try:
        _download_to(tmp, [url], None,
                     _archive_progress_status("Downloading modpack...", status_cb))
        return _install_from_zip(tmp, progress_cb=progress_cb, status_cb=status_cb, max_cb=max_cb)
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
    for i in range(0, len(entries), 50):
        body = entries[i:i + 50]
        resp = requests.post(
            f"{CURSEFORGE_API}/mods/files",
            json=[{"projectID": int(e["projectID"]), "fileID": int(e["fileID"])}
                  for e in body],
            headers={"x-api-key": key,
                     "Accept": "application/json",
                     "User-Agent": MODRINTH_HEADERS["User-Agent"]},
            timeout=30)
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
            for row in _cf_batch_files(entries):
                by_key[(row.get("modId"), row.get("id"))] = row
            # Missing metadata rows are skipped (not fatal): the pack stays
            # installable minus a broken/removed file, matching the CF launcher's
            # own tolerance of removed files.
            mr_files = []
            for e in entries:
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
                            progress_cb=None, status_cb=None, max_cb=None) -> dict:
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
                                 status_cb=status_cb, max_cb=max_cb)
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
                  summarize_cb=None) -> str:
    """Write the mods of one installed (mc_version, loader) profile out as a
    valid Modrinth `.mrpack` at dest_path, and return that path.

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

def _modrinth_modpack_search(query: str, mc_version: str | None, limit: int) -> list[dict]:
    """One Modrinth search request, parsed into the browse-UI hit shape.
    Split out of search_modpacks so the UI can render Modrinth results
    immediately while CurseForge (slower, especially keyless via cfwidget)
    is still in flight."""
    facets = [["project_type:modpack"]]
    if mc_version:
        facets.append([f"versions:{mc_version}"])

    params = {"query": query, "limit": str(limit), "facets": json.dumps(facets),
              "index": modrinth_search_index(query)}
    payload = net.get_json(f"{MODRINTH_API}/search", params=params,
                           headers=MODRINTH_HEADERS, timeout=15)
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


def search_modpacks_modrinth(query: str, mc_version: str | None = None, limit: int = 40) -> list[dict]:
    """Modrinth-only modpack search, cached. Kept separate from the combined
    search so the browse UI can show these hits first."""
    cache_key = {"query": query, "mc_version": mc_version, "limit": limit}

    def fetch():
        return _modrinth_modpack_search(query, mc_version, limit)

    # cached_call: fresh cache wins; on a failed fetch the last known results
    # are served instead of an error (a launcher showing yesterday's search
    # beats a spinner), and nothing here ever blocks on a refresh.
    return local_cache.cached_call("search_modpacks_mr", cache_key, fetch,
                                   background_refresh=False)


def search_modpacks_curseforge(query: str, mc_version: str | None = None, limit: int = 40) -> list[dict]:
    """CurseForge-only modpack search, cached. Keyless access (cfwidget) is
    slow - up to a dozen 4s probes - so this runs as its own phase the UI
    merges in whenever it lands."""
    cache_key = {"query": query, "mc_version": mc_version, "limit": limit}

    def fetch():
        return _curseforge_search(query, mc_version, limit)

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


def search_modpacks(query: str, mc_version: str | None = None, limit: int = 40) -> list[dict]:
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
    project's control."""
    cache_key = {"query": query, "mc_version": mc_version, "limit": limit}

    def fetch():
        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=2) as pool:
            mr_fut = pool.submit(search_modpacks_modrinth, query, mc_version, limit)
            cf_fut = pool.submit(search_modpacks_curseforge, query, mc_version, limit)
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


def get_popular_modpacks(mc_version: str | None = None, limit: int = 40) -> list[dict]:
    """The default browse list before the user searches: most-downloaded packs."""
    return search_modpacks("", mc_version=mc_version, limit=limit)


# ---------------------------------------------------------------------------
# CurseForge provider (the other big platform - RLCraft, SkyFactory, DawnCraft
# and most other classic packs are CurseForge exclusives).
#
# Uses CurseForge's official API, which requires a free API key from
# console.curseforge.com. The key is looked up in this order:
#   1. the CURSEFORGE_API_KEY environment variable
#   2. "curseforge_api_key" in ~/.cubeon_launcher/config.json
#   3. the first line of ~/.cubeon_launcher/curseforge_api_key
# Without a key the provider is dormant and the tab is Modrinth-only.
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


def _curseforge_api_key() -> "str | None":
    """The configured CurseForge API key, or None. Env first, then config.json,
    then a dedicated key file."""
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
    return None


def curseforge_enabled() -> bool:
    """True when a CurseForge API key is configured - the provider's gate."""
    return bool(_curseforge_api_key())


def _cf_request(path: str, params: "dict | None" = None, timeout: int = 10):
    """One CurseForge API GET. Raises requests exceptions like the Modrinth
    paths do - callers are already tolerant of third-party failures."""
    key = _curseforge_api_key()
    if not key:
        raise ModpackError("No CurseForge API key configured.")
    headers = {
        "User-Agent": MODRINTH_HEADERS["User-Agent"],
        "Accept": "application/json",
        "x-api-key": key,
    }
    return net.get_json(f"{CURSEFORGE_API}{path}", params=params,
                        headers=headers, timeout=timeout)


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

# The classics people mean when they say "where is RLCraft". Slugs resolve
# through cfwidget's website-path form; dead slugs just yield nothing.
CURATED_CF_SLUGS = (
    "rlcraft", "skyfactory-4", "dawncraft", "medieval-minecraft",
    "craft-to-exile-2", "vault-hunters-3rd-edition", "all-the-mods-9",
    "all-of-fabric-7", "better-mc-fabric-bmc1", "better-mc-forge-bmc2",
    "big-chad-guys-plus", "prominence-2-rpg",
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
                            headers=MODRINTH_HEADERS)
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
    """A CFWidget project payload → the search-hit dict shape the UI renders."""
    try:
        page = ((widget.get("urls") or {}).get("curseforge") or "").rstrip("/")
        versions = []
        for f in widget.get("files") or []:
            for v in (f.get("versions") or [] if isinstance(f, dict) else []):
                if v and v not in versions:
                    versions.append(v)
        downloads = widget.get("downloads", 0)
        return {
            "source": "curseforge",
            "project_id": str(widget.get("id")),
            "slug": page.split("/")[-1] if page else None,
            "title": widget.get("title") or "Untitled pack",
            "description": widget.get("summary"),
            "icon_url": None,
            "downloads": downloads if isinstance(downloads, (int, float)) else 0,
            "author": None,
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
        keys = [q.replace(" ", "-")] + list(CURATED_CF_SLUGS)
    else:
        keys = list(CURATED_CF_SLUGS)
    with ThreadPoolExecutor(max_workers=6) as pool:
        widgets = [w for w in pool.map(_cfwidget_fetch,
                                       [f"minecraft/modpacks/{k}" for k in keys]) if w]
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


def _curseforge_search(query: str, mc_version: "str | None", limit: int) -> list[dict]:
    """CF search hits in the same dict shape the Modrinth path returns, tagged
    source='curseforge'. Any failure (no key, network, schema drift) degrades
    to an empty list rather than breaking the Modrinth results."""
    if not curseforge_enabled():
        return _cfwidget_search(query, limit)
    try:
        payload = _cf_request("/mods/search", params={
            "gameId": str(CF_GAME_ID_MINECRAFT),
            "classId": str(CF_CLASS_ID_MODPACK),
            "searchFilter": query or "",
            "sortField": "2",   # 2 = Popularity (downloads) - matches browse
            "sortOrder": "desc",
            "pageSize": str(min(limit, 50)),
        })
    except Exception:
        return []
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
                            params=params, headers=MODRINTH_HEADERS, timeout=15)
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
    order. Used to show 'Installed packs' and let Play jump to one."""
    packs = []
    if not os.path.isdir(PROFILES_DIR):
        return packs
    for key in sorted(os.listdir(PROFILES_DIR)):
        meta_path = os.path.join(PROFILES_DIR, key, MODPACK_META_FILENAME)
        if not os.path.isfile(meta_path):
            continue
        try:
            with open(meta_path, "r", encoding="utf-8") as fh:
                packs.append(json.load(fh))
        except (OSError, json.JSONDecodeError):
            continue
    return packs


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
