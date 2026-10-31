"""
Mod management: per-(version, loader) profile folders, Modrinth
search/download, and syncing the active profile's enabled jars into the
real MINECRAFT_DIR/mods folder the game actually reads at launch.

--- Why mods used to "sometimes work, sometimes just drop and do nothing" ---

Two real bugs, both about a loader/version value silently going missing
somewhere between "download/select a mod" and "the game reads mods/":

1. sync_mods_to_game() was being called from launch_game() without ever
   being told which loader was active (the caller just never passed it).
   Internally it treats a missing/None loader exactly like "vanilla" -
   which means every single launch WIPED MINECRAFT_DIR/mods and then
   returned immediately, without copying anything back in, regardless
   of what loader was actually selected. Any jars that appeared to be
   "working" were just leftovers from a previous manual copy that
   hadn't been wiped yet - hence "sometimes".

2. Downloading a mod from the in-app Modrinth browser saved the jar
   without passing mc_version/loader either, so it silently landed in
   the wrong profile folder (keyed by "None"/"unknown-vanilla") instead
   of the folder the currently selected version+loader actually reads
   from. So the mod would show as "Installed" in the browse view, and
   even show up under Installed if you happened to be on that profile,
   but sync_mods_to_game() (once fixed) would never find it under the
   real profile and it would never load in-game.

Fixed here by:
  - require_loader_and_version(): every public entry point below that
    reads/writes a profile now goes through this, so a missing/None
    value fails loudly (ValueError) instead of quietly resolving to
    the wrong folder.
  - The UI call sites (mods_tab.py, main.py's launch flow) now always
    pass the actual selected mc_version/loader through explicitly.
"""
import json
import os
import re
import shutil
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor, as_completed
from functools import lru_cache
from urllib.parse import urlsplit

# `requests` costs ~97ms to import; this module is on the startup path but
# only touches the network when the user browses/downloads. Lazy so the
# window appears sooner. Metadata GETs route through net.get_json (retry +
# backoff); `requests` stays only for its exception types here.
from .lazy import LazyModule
requests = LazyModule("requests")

from .paths import (
    APP_NAME, MINECRAFT_DIR, MODS_DIR, PROFILES_DIR,
    INSTANCE_META_FILENAME, MOD_META_SUFFIX, PROFILE_META_FILENAME,
    modrinth_headers,
)
from .mod_loaders import MOD_CAPABLE_LOADERS
from .atomicio import write_json
from . import local_cache
from . import global_mod_cache
from . import net

MODRINTH_API = "https://api.modrinth.com/v2"

# The jars sync_mods_to_game linked on the last run. Only these may be
# removed from the shared mods/ folder; anything else there is the user's own
# file and is moved to MINECRAFT_DIR/mods_user_backup instead of deleted.
_SYNC_MANIFEST = ".cubeon-synced.json"


def _read_synced_manifest() -> set[str]:
    """Filenames this launcher linked into MODS_DIR last time (empty on first
    run or an unreadable manifest)."""
    path = os.path.join(MODS_DIR, _SYNC_MANIFEST)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        return set()
    if isinstance(data, dict):
        data = data.get("files")
    if not isinstance(data, list):
        return set()
    return {name for name in data if isinstance(name, str)}


def _backup_user_jar(fname: str) -> None:
    """Move a jar Cubeon did not put in mods/ to mods_user_backup/.

    Never delete it: it may be the user's only copy. A same-named backup from
    an earlier run gets a numeric suffix rather than being overwritten.
    """
    backup_dir = os.path.join(MINECRAFT_DIR, "mods_user_backup")
    os.makedirs(backup_dir, exist_ok=True)
    dest = os.path.join(backup_dir, fname)
    if os.path.exists(dest):
        stem, ext = os.path.splitext(fname)
        n = 1
        while os.path.exists(dest):
            dest = os.path.join(backup_dir, f"{stem}.{n}{ext}")
            n += 1
    os.replace(os.path.join(MODS_DIR, fname), dest)




def modrinth_search_index(query: "str | None") -> str:
    """The `index` value to send Modrinth for a search request. With no
    query text (a plain browse - the default view before the user types
    anything) there's nothing for "relevance" to rank against, so sorting
    by that just returns Modrinth's arbitrary tie-break order. Downloads is
    what "browse" actually means in every mod-search UI users are used to
    (CurseForge, the Modrinth site itself, etc.), so use it whenever there's
    no query. Once the user types something, relevance has to stay in the
    driver's seat or a popular-but-unrelated project would outrank an exact
    name match - downloads is then only used as the client-side tiebreak in
    rank_search_hits() below, not as the primary Modrinth-side sort."""
    return "downloads" if not (query or "").strip() else "relevance"


def rank_search_hits(hits: list[dict], query: "str | None" = None) -> list[dict]:
    """Orders search hits for display.

    With NO query (plain browse), this is a straightforward most-downloaded-
    first sort - that's what "browse" means in every mod site users already
    know (CurseForge, Modrinth itself), and it's a no-op here since
    modrinth_search_index() already asked Modrinth to return results in
    that order for an empty query.

    WITH a query, this used to unconditionally re-sort every hit by raw
    downloads - which silently threw away Modrinth's actual relevance
    ranking. That's the bug behind "I can't find the mod I'm looking for":
    searching a specific mod's name could bury the exact match under any
    unrelated project that simply has more total downloads (e.g. search
    "sodium" and a mega-popular unrelated mod like JEI would outrank the
    actual Sodium result, just because 200M > 50M downloads). Relevance is
    what makes a *search* return what you typed; downloads should only
    break ties between hits Modrinth already considers comparably
    relevant, not override relevance outright.

    Fix: keep Modrinth's relevance order as the primary sort, and only use
    downloads to break ties *within* same-relevance bands, starting after a
    protected top slice. Modrinth doesn't expose a raw numeric relevance
    score in the hit payload, so bands are approximated with fixed-size
    windows over the order Modrinth returned - hits are re-sorted by
    downloads inside each band, but a hit never jumps out of its band and
    ahead of a hit Modrinth ranked clearly more relevant. The first
    TOP_PROTECTED hits are left exactly as Modrinth ordered them and never
    join a band: those top few are almost always the actual intended match
    for a specific-enough query, and are exactly what a small result set
    (e.g. searching one mod's exact name) consists of - banding a
    3-result search would let raw downloads override relevance entirely,
    the same bug this is fixing. Downloads-based reordering only kicks in
    from result #4 onward, where "which of these several plausible matches
    should I show first" is a much safer question to answer with downloads.
    """
    if not (query or "").strip():
        return sorted(hits, key=lambda h: h.get("downloads", 0) or 0, reverse=True)

    TOP_PROTECTED = 3
    band_size = 5
    protected, rest = hits[:TOP_PROTECTED], hits[TOP_PROTECTED:]
    ranked = list(protected)
    for start in range(0, len(rest), band_size):
        band = rest[start:start + band_size]
        band.sort(key=lambda h: h.get("downloads", 0) or 0, reverse=True)
        ranked.extend(band)
    return ranked


# Curated, well-known mods shown by default before the user searches
# anything - a mix of performance and quality-of-life picks that work well
# together and are safe defaults for almost any modpack.
RECOMMENDED_MOD_SLUGS = ["sodium", "iris", "lithium", "modmenu", "fabric-api", "customskinloader"]

# Curated categories shown as quick filters in the Mods tab. (id, label) -
# ids match Modrinth's own category slugs so they can be passed straight
# into the facets below.
MOD_CATEGORIES = [
    ("", "All"),
    ("performance", "Performance"),
    ("optimization", "Optimization"),
    ("worldgen", "World Gen"),
    ("technology", "Tech"),
    ("magic", "Magic"),
    ("adventure", "Adventure"),
    ("decoration", "Decoration"),
    ("utility", "Utility"),
    ("storage", "Storage"),
    ("food", "Food"),
    ("mobs", "Mobs"),
    ("equipment", "Equipment"),
    ("library", "Library"),
]


# ---------------------------------------------------------------------------
# Profile folders
# ---------------------------------------------------------------------------

def _sanitize(part: str) -> str:
    return re.sub(r"[^a-zA-Z0-9.+_]", "_", part) or "unknown"


def profile_key(mc_version: str | None, loader: str | None) -> str:
    return f"{_sanitize(mc_version or 'unknown')}-{_sanitize(loader or 'vanilla')}"


def _instance_meta_path(version_id: str | None) -> str | None:
    """Path of an instance's sidecar, or None for an unsafe/blank id.

    The id comes from config and version folders, so it is treated as a
    filename: separators and parent hops are refused instead of letting a
    crafted id read a JSON file outside versions/.
    """
    if not version_id or not isinstance(version_id, str):
        return None
    if version_id in (".", "..") or "/" in version_id or "\\" in version_id:
        return None
    if os.path.basename(version_id) != version_id:
        return None
    return os.path.join(MINECRAFT_DIR, "versions", version_id,
                        INSTANCE_META_FILENAME)


# Sidecar reads are tiny but numerous: list_mods() reads one `<jar>.cubeon.json`
# per installed jar on every repaint (300 jars = 300 opens + JSON parses), and
# the Play tab's instance rows re-read one `_cubeon_instance.json` per row. Both
# are immutable-between-writes, so memoize by (path, mtime_ns, size): any
# rewrite changes the key, so an entry can never serve stale data. Writers in
# this module additionally drop the entry (see _forget_sidecar) because two
# writes of the same size can land within one mtime tick on a coarse filesystem.
_SIDECAR_CACHE_LOCK = threading.Lock()
_SIDECAR_CACHE: dict[str, tuple[tuple[int, int], "dict | None"]] = {}
_SIDECAR_CACHE_MAX = 2048


def _forget_sidecar(path: str) -> None:
    with _SIDECAR_CACHE_LOCK:
        _SIDECAR_CACHE.pop(path, None)


def _read_sidecar_json(path: str) -> dict | None:
    """Read a sidecar JSON through the cache. Missing/unreadable -> None."""
    try:
        stat = os.stat(path)
    except OSError:
        _forget_sidecar(path)
        return None
    key = (stat.st_mtime_ns, stat.st_size)
    with _SIDECAR_CACHE_LOCK:
        cached = _SIDECAR_CACHE.get(path)
    if cached is not None and cached[0] == key:
        data = cached[1]
        return dict(data) if isinstance(data, dict) else data
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        # ValueError covers invalid UTF-8; a corrupt sidecar must degrade to
        # "unknown", which is what every caller already expects.
        data = None
    if not isinstance(data, dict):
        data = None
    with _SIDECAR_CACHE_LOCK:
        if len(_SIDECAR_CACHE) >= _SIDECAR_CACHE_MAX:
            _SIDECAR_CACHE.clear()   # bounded; the next reads refill it
        _SIDECAR_CACHE[path] = (key, data)
    return dict(data) if data is not None else None


def read_instance_meta(version_id: str | None) -> dict | None:
    """The per-instance record written inside a version folder, or None.

    Never raises: a missing/unreadable sidecar simply means "legacy shared
    profile", which is exactly how every install made before instance
    isolation behaved.
    """
    path = _instance_meta_path(version_id)
    if not path:
        return None
    return _read_sidecar_json(path)


def write_instance_meta(version_id: str | None, meta: dict) -> bool:
    """Atomically write a version folder's instance sidecar. Never raises."""
    path = _instance_meta_path(version_id)
    if not path:
        return False
    try:
        # Unique temp name + fsync: two writers (or a crash mid-write) must
        # never leave a truncated sidecar or overwrite each other's temp file.
        write_json(path, meta)
    except (OSError, TypeError, ValueError):
        return False
    _forget_sidecar(path)
    return True


def profile_key_for(mc_version: str | None, loader: str | None,
                    version_id: str | None = None) -> str:
    """The profile key an install actually uses.

    When the version folder carries an instance sidecar, its recorded
    `profile` key wins. Otherwise this is the legacy shared
    (mc_version, loader) key, so existing installs keep working unchanged.
    """
    meta = read_instance_meta(version_id) if version_id else None
    recorded = (meta or {}).get("profile")
    if isinstance(recorded, str) and recorded.strip():
        # A recorded key is a folder name, never a path.
        if (os.path.basename(recorded) == recorded
                and "/" not in recorded and "\\" not in recorded
                and recorded not in (".", "..")):
            return recorded
    return profile_key(mc_version, loader)


def resolve_profile_dir(mc_version: str | None, loader: str | None,
                        version_id: str | None = None) -> str:
    return os.path.join(PROFILES_DIR,
                        profile_key_for(mc_version, loader, version_id))


def get_profile_dir(mc_version: str | None, loader: str | None,
                    version_id: str | None = None) -> str:
    path = resolve_profile_dir(mc_version, loader, version_id)
    os.makedirs(path, exist_ok=True)
    meta_path = os.path.join(path, PROFILE_META_FILENAME)
    if not os.path.isfile(meta_path):
        write_json(meta_path, {"mc_version": mc_version, "loader": loader})
    return path


def profile_dir_for_key(key: str | None) -> str | None:
    """Absolute folder for a profile key (a folder name), or None."""
    if not key or not isinstance(key, str):
        return None
    if key in (".", "..") or os.path.basename(key) != key \
            or "/" in key or "\\" in key:
        return None
    return os.path.join(PROFILES_DIR, key)


def _profile_size_bytes(path: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(path):
        for name in files:
            try:
                total += os.path.getsize(os.path.join(root, name))
            except OSError:
                pass
    return total


def private_profile_for_deletion(version_id: str | None) -> tuple[str, int] | None:
    """(profile key, size in bytes) of an isolated instance's OWN profile.

    None when the instance uses the legacy shared (version, loader) profile -
    that folder is reused by other installs and must never be removed with one
    instance - when no other instance references the profile, or when the id
    is unsafe. So the UI can safely offer "also delete this instance's mods".
    Never raises.
    """
    if not version_id or not isinstance(version_id, str):
        return None
    meta = read_instance_meta(version_id) or {}
    key = meta.get("profile")
    if not isinstance(key, str) or not key:
        return None
    if key == profile_key(meta.get("mc_version"), meta.get("loader")):
        return None  # legacy shared profile
    path = profile_dir_for_key(key)
    if not path or not os.path.isdir(path):
        return None
    versions_dir = os.path.join(MINECRAFT_DIR, "versions")
    try:
        others = os.listdir(versions_dir)
    except OSError:
        others = []
    for other in others:
        if other == version_id:
            continue
        other_meta = read_instance_meta(other) or {}
        if other_meta.get("profile") == key:
            return None  # shared with another installed instance
    return key, _profile_size_bytes(path)


def delete_instance_profile(profile_key: str) -> None:
    """Remove one isolated instance's private profile folder.

    Only called after the user explicitly confirmed it. The key is checked to
    be a bare folder name and the resolved path must stay inside PROFILES_DIR.
    Raises ValueError with a readable message otherwise.
    """
    path = profile_dir_for_key(profile_key)
    if not path:
        raise ValueError("Refusing to delete that profile.")
    root = os.path.abspath(PROFILES_DIR)
    real = os.path.abspath(path)
    if real == root or not real.startswith(root + os.sep):
        raise ValueError("Refusing to delete a profile outside the profiles folder.")
    if not os.path.isdir(path):
        return
    try:
        shutil.rmtree(path)
    except OSError as ex:
        raise ValueError(f"Couldn't delete this instance's mods: {ex}") from ex


def _profile_has_content(path: str) -> bool:
    """Whether a profile already holds mods or content links."""
    try:
        for name in os.listdir(path):
            if name.endswith((".jar", ".jar.disabled")):
                return True
            if name in ("resourcepacks", "shaderpacks", "mods"):
                return True
        return False
    except OSError:
        return False


def _profile_slug(label: str | None) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", (label or "").lower()).strip("-")
    return (slug[:40].strip("-") or "pack")


def unique_profile_key(mc_version: str | None, loader: str | None,
                       label: str | None) -> str:
    """A profile key that no other instance is using.

    Starts from `<mc>-<loader>-<pack-slug>` so the folder is recognisable in
    the profile list, then adds -2, -3, ... rather than ever merging two
    packs into one folder.
    """
    base = f"{profile_key(mc_version, loader)}-{_profile_slug(label)}"
    candidate = base
    n = 2
    while os.path.isdir(os.path.join(PROFILES_DIR, candidate)):
        candidate = f"{base}-{n}"
        n += 1
    return candidate


def create_instance_version(mc_version: str, loader: str,
                            source_version_id: str, profile: str,
                            name: str | None = None,
                            pack: dict | None = None) -> str:
    """Clone a loader version folder into an isolated instance.

    A modpack must not overwrite a hand-built profile that happens to use the
    same (mc_version, loader). The launchable version folder is cloned (the
    client jar is hard-linked, the JSON rewritten with the new id) and a
    sidecar records the private profile key. Returns the new version id.

    The new id starts with the Minecraft version, so `extract_mc_version()`
    resolves it without the loader's own version confusing it.
    """
    versions_dir = os.path.join(MINECRAFT_DIR, "versions")
    source_dir = os.path.join(versions_dir, source_version_id)
    if not os.path.isdir(source_dir):
        raise ValueError(f"Can't isolate this install: {source_version_id} is missing.")

    slug = _profile_slug(name)
    base_id = f"{mc_version}-{loader}-{slug}"
    new_id = base_id
    n = 2
    while True:
        target = os.path.join(versions_dir, new_id)
        if not os.path.isdir(target):
            break
        existing = read_instance_meta(new_id) or {}
        if existing.get("profile") == profile:
            return new_id  # already cloned for this exact profile
        new_id = f"{base_id}-{n}"
        n += 1

    target = os.path.join(versions_dir, new_id)
    os.makedirs(target, exist_ok=False)

    # Find the source metadata even when the folder/json names differ (foreign
    # launchers). The canonical <id>.json is preferred.
    source_json = os.path.join(source_dir, f"{source_version_id}.json")
    if not os.path.isfile(source_json):
        candidates = sorted(f for f in os.listdir(source_dir)
                            if f.endswith(".json"))
        source_json = (os.path.join(source_dir, candidates[0])
                       if candidates else "")
    data = {}
    if source_json and os.path.isfile(source_json):
        try:
            with open(source_json, "r", encoding="utf-8") as fh:
                loaded = json.load(fh)
            if isinstance(loaded, dict):
                data = loaded
        except (OSError, json.JSONDecodeError):
            data = {}
    data["id"] = new_id
    json_name = f"{new_id}.json"
    with open(os.path.join(target, json_name), "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2)

    # Hard-link the client jar and any side files; a copy fallback covers a
    # different filesystem or a mount that refuses links.
    for entry in os.listdir(source_dir):
        if entry in (f"{source_version_id}.json", json_name,
                     INSTANCE_META_FILENAME):
            continue
        src = os.path.join(source_dir, entry)
        if not os.path.isfile(src):
            continue
        dst = os.path.join(target, entry)
        try:
            os.link(src, dst)
        except OSError:
            shutil.copyfile(src, dst)

    meta = {
        "profile": profile,
        "name": name or new_id,
        "mc_version": mc_version,
        "loader": loader,
        "source_version_id": source_version_id,
    }
    if isinstance(pack, dict) and pack:
        meta["pack"] = pack
    write_instance_meta(new_id, meta)
    return new_id



def require_loader_and_version(mc_version: str | None, loader: str | None, action: str) -> None:
    """Fails loudly instead of silently resolving to the 'unknown'/'vanilla'
    profile. This is the fix for mods silently landing in - or being read
    from - the wrong folder: previously a missing mc_version/loader just
    quietly fell through to get_profile_dir()'s 'unknown'/'vanilla'
    defaults, so a caller that forgot to pass them wouldn't error, it would
    just work on the wrong folder. Call this from any entry point that's
    about to read/write a profile on behalf of "the currently selected
    version+loader", so a wiring bug like that fails immediately and
    obviously instead of shipping mods nobody can find."""
    if not mc_version:
        raise ValueError(f"Can't {action}: no Minecraft version selected.")
    if not loader:
        raise ValueError(f"Can't {action}: no mod loader selected.")


def require_mod_loader(mc_version: str | None, loader: str | None, action: str) -> None:
    require_loader_and_version(mc_version, loader, action)
    if loader not in MOD_CAPABLE_LOADERS:
        raise ValueError("Vanilla can't load mods. Choose Fabric, Quilt, Forge, or NeoForge on the Play tab first.")


def list_profiles() -> list[dict]:
    """Every profile that currently has a folder, with its mod count -
    used to populate the 'copy mods from...' picker."""
    profiles = []
    if not os.path.isdir(PROFILES_DIR):
        return profiles
    for key in sorted(os.listdir(PROFILES_DIR)):
        path = os.path.join(PROFILES_DIR, key)
        if not os.path.isdir(path):
            continue
        meta_path = os.path.join(path, PROFILE_META_FILENAME)
        meta = {}
        if os.path.isfile(meta_path):
            try:
                with open(meta_path, "r", encoding="utf-8") as f:
                    meta = json.load(f)
            except (OSError, ValueError):
                meta = {}
            if not isinstance(meta, dict):
                meta = {}
        mod_count = sum(
            1 for fn in os.listdir(path)
            if fn.endswith(".jar") or fn.endswith(".jar.disabled")
        )
        if mod_count == 0:
            continue
        profiles.append({
            "key": key,
            "mc_version": meta.get("mc_version"),
            "loader": meta.get("loader"),
            "mod_count": mod_count,
        })
    return profiles


def record_mod_source(profile_dir: str, filename: str, slug: str | None = None,
                      project_id: str | None = None, url: str | None = None) -> None:
    """Public sidecar writer, for code outside this module that installs jars
    into a profile - chiefly the modpack installer, which had no way to record
    what it had just laid down and so left every pack mod anonymous."""
    _write_meta(profile_dir, filename, slug, project_id=project_id, url=url)


def _meta_path(profile_dir: str, filename: str) -> str:
    base = filename[:-len(".disabled")] if filename.endswith(".disabled") else filename
    return os.path.join(profile_dir, base + MOD_META_SUFFIX)


def _read_meta(profile_dir: str, filename: str) -> dict | None:
    return _read_sidecar_json(_meta_path(profile_dir, filename))


def _write_meta(profile_dir: str, filename: str, slug: str | None,
                project_id: str | None = None, url: str | None = None) -> None:
    """Record what a jar actually IS, next to it.

    Three fields, each earning its place:
      slug        - Modrinth's human id ("sodium"), what the browse view matches on.
      project_id  - Modrinth's opaque id ("AANobbMI"). A modpack manifest only
                    ever gives us this (it's in the CDN URL), never the slug, so
                    without it every pack-installed mod is unidentifiable.
      url         - where it came from. export_mrpack() already looks for this to
                    emit a `files` entry instead of bundling the whole jar; until
                    now nothing ever wrote it, so every export bundled everything.

    Writes the file if ANY of them is known - the old version bailed out unless
    a slug was present, which is precisely why modpack-installed mods ended up
    with no sidecar at all and read as "not installed" in the Mods tab.

    MERGES into an existing sidecar instead of replacing it. Callers know
    different subsets (a browse download has the slug, a pack install only the
    project id, a re-drop none), and overwriting used to erase the field it
    didn't pass - which then made an identical mod in the same profile
    unidentifiable and let a duplicate slip past find_other_copies()."""
    existing = _read_meta(profile_dir, filename)
    meta = dict(existing) if isinstance(existing, dict) else {}
    changed = False
    if slug:
        meta["slug"] = slug
        changed = True
    if project_id:
        meta["project_id"] = project_id
        changed = True
    if url:
        meta["url"] = url
        changed = True
    if not changed:
        return
    path = _meta_path(profile_dir, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(meta, f)
    # The mtime/size key is usually enough, but two same-size rewrites inside
    # one mtime tick would look identical - drop the entry explicitly.
    _forget_sidecar(path)


# Filename noise that identifies a *build*, not a mod: loader names, an "mc"
# prefix, and anything starting with a digit or 'v'+digit. Stripping these off
# the end of a jar name leaves the mod's own name, which is the only handle we
# have on jars that carry no sidecar (hand-dropped, or from a CurseForge pack
# where the CDN URL contains no project id).
_BUILD_NOISE = re.compile(
    r"^(?:v?\d.*|mc\d.*|fabric|forge|neoforge|quilt|universal|all|client|"
    r"release|stable|beta|alpha|snapshot)$",
    re.IGNORECASE,
)


def name_stem(filename: str) -> str:
    """"sodium-fabric-0.9.2-alpha.4+mc26.1.2.jar" -> "sodium",
    "sodium-extra-fabric-0.8.7+mc26.1.1.jar"     -> "sodium-extra",
    "fabric-api-0.155.2+26.1.2.jar"              -> "api".

    Trailing build noise is peeled off; whatever is left is the mod. Note the
    third example: leading "fabric" is real name text, but the peel only works
    from the right, so "fabric-api" reduces to "api". That's fine - it's stable,
    so both copies of Fabric API reduce to the same thing, which is all this is
    for. Comparing stems is deliberately the WEAKEST identity test here and is
    never used to delete anything, only to disable a jar the game shouldn't
    load; a stem collision between two genuinely different mods costs the user
    one click to re-enable, whereas a missed duplicate costs them a crash."""
    base = filename
    for suffix in (".disabled", ".jar"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    base = base.split("+", 1)[0]                     # drop "+mc26.1.2" tails
    parts = [p for p in re.split(r"[-_]", base) if p]
    while len(parts) > 1 and _BUILD_NOISE.match(parts[-1]):
        parts.pop()
    return "-".join(parts).lower()


def _version_key(filename: str, mc_version: str | None = None) -> tuple:
    """A sortable version for a jar filename: its MOD version as a tuple of ints.

    The old implementation returned the longest dotted-number run, which for
    "sodium-fabric-0.5.3+mc1.20.1.jar" was the Minecraft version
    "(1, 20, 1)" - for BOTH builds of the mod. They tied, and sync_mods_to_game
    linked whichever came first in sorted() order, i.e. the older one.

    Strip the parts that are not the mod's own version first: the "+mc1.20.1"
    build tail, any "mc<ver>" token, and the instance's literal MC version.
    The first remaining dotted run is the mod version. Used to answer "of these
    two copies of the same mod, which would Fabric have picked?" - Fabric takes
    the highest declared version, so mirroring that keeps our choice and its
    choice the same instead of introducing a third behaviour."""
    base = filename
    for suffix in (".disabled", ".jar"):
        if base.endswith(suffix):
            base = base[: -len(suffix)]
    base = base.split("+", 1)[0]                     # drop "+mc1.20.1" tails
    base = re.sub(r"mc\d+(?:\.\d+)*", "", base, flags=re.IGNORECASE)
    if mc_version:
        # Bounded by non-digits/non-dots so "1.20" cannot eat the start of
        # "1.20.1" (a mod version) in a filename with no other marker.
        base = re.sub(
            r"(?<![\d.])" + re.escape(str(mc_version)) + r"(?![\d.])",
            "", base)
    match = re.search(r"\d+(?:\.\d+)+", base)
    if not match:
        return ()
    return tuple(int(p) for p in match.group(0).split("."))


def _jar_mtime(profile_dir: str, filename: str) -> float:
    """Modification time of a profile jar, 0.0 if it vanished mid-scan."""
    try:
        return os.path.getmtime(os.path.join(profile_dir, filename))
    except OSError:
        return 0.0


def mod_identity(profile_dir: str, filename: str) -> tuple:
    """(slug, project_id, stem) for an installed jar - its identity across
    versions. slug/project_id come from the sidecar and are authoritative;
    stem is derived from the filename and is a fallback."""
    meta = _read_meta(profile_dir, filename) or {}
    return (
        (meta.get("slug") or "").lower() or None,
        (meta.get("project_id") or "").lower() or None,
        name_stem(filename),
    )


def find_other_copies(profile_dir: str, filename: str,
                      slug: str | None = None, project_id: str | None = None) -> list[dict]:
    """Other jars in this profile that are the SAME MOD as `filename`.

    This is the check that was missing everywhere. A mod's filename carries its
    version, so installing a newer build never overwrote the older one - it just
    sat down next to it, both got hardlinked into MINECRAFT_DIR/mods, and Fabric
    loaded whichever declared the higher version while the loser stayed on disk
    forever. Harmless-looking until two of those duplicates are a renderer and
    its compatibility patch (Sodium + Iris), at which point the pair the game
    ends up with is one nobody ever tested and the world won't open.

    Returns [{filename, strong}]; `strong` means matched on a recorded Modrinth
    id (provably the same project) rather than on a filename stem (a guess)."""
    want_slug = (slug or "").lower() or None
    want_pid = (project_id or "").lower() or None
    if not (want_slug or want_pid):
        want_slug, want_pid, _ = mod_identity(profile_dir, filename)
    want_stem = name_stem(filename)

    out = []
    try:
        entries = sorted(os.listdir(profile_dir))
    except OSError:
        return out
    for other in entries:
        if other == filename or not (other.endswith(".jar") or other.endswith(".jar.disabled")):
            continue
        o_slug, o_pid, o_stem = mod_identity(profile_dir, other)
        if (want_slug and o_slug and want_slug == o_slug) or \
           (want_pid and o_pid and want_pid == o_pid):
            out.append({"filename": other, "strong": True})
        elif want_stem and len(want_stem) >= 3 and want_stem == o_stem:
            out.append({"filename": other, "strong": False})
    return out


def supersede_older_copies(profile_dir: str, filename: str,
                           slug: str | None = None,
                           project_id: str | None = None) -> list[str]:
    """Make `filename` the only copy of its mod in this profile. Returns the
    human-readable names of what it moved out of the way.

    Strong (same Modrinth id) matches are DELETED - that's what updating a mod
    means, and leaving them would pile up a disabled jar per update forever.
    Stem matches are only DISABLED, because a stem match is a guess and a wrong
    guess must stay recoverable; a `.jar.disabled` is never synced to the game,
    so the crash is gone either way and the Mods tab still shows the jar with a
    toggle to bring it back."""
    moved = []
    for other in find_other_copies(profile_dir, filename, slug, project_id):
        name = other["filename"]
        src = os.path.join(profile_dir, name)
        try:
            if other["strong"]:
                os.remove(src)
                meta = _meta_path(profile_dir, name)
                if os.path.exists(meta):
                    os.remove(meta)
            elif not name.endswith(".disabled"):
                os.rename(src, src + ".disabled")
            else:
                continue  # already disabled, nothing to do
        except OSError:
            continue
        moved.append(name.replace(".jar.disabled", "").replace(".jar", ""))
    return moved


# ---------------------------------------------------------------------------
# Installed-mods CRUD for the current profile
# ---------------------------------------------------------------------------

# Mods Cubeon ships and depends on itself - CustomSkinLoader is what makes
# skins/capes work on an offline account (cubeon/csl.py), and the Cubeon
# Client mod is the in-game Cubeon button (cubeon/cubeonfriends.py). Both
# are re-installed automatically at launch, so a user "removing" one only
# ever breaks their own skins or the Cubeon button - protected the same way
# the server's managed plugins are (see cubeon/server.py PROTECTED_PLUGINS).
# Matched by filename stem (without .jar/.jar.disabled, lowercase prefix) and
# by Modrinth slug for the one we download from there (kept as a literal, not
# imported from csl.py - csl imports from this module, so it can't go the
# other way; tools/test_csl.py checks the two stay in agreement). The old
# cubeon-friends- name is still protected: profiles from before the rename
# have that jar until the next launch sweeps it (cubeonfriends.LEGACY_JAR_GLOBS).
PROTECTED_MOD_STEM_PREFIXES = ("customskinloader", "cubeon-client", "cubeon-friends")
CSL_MODRINTH_SLUG_LOCAL = "customskinloader"


def is_protected_mod_stem(stem: str) -> bool:
    """Whether a mod jar's name (without .jar/.jar.disabled) belongs to a
    Cubeon-managed client mod. Prefix match so versioned names like
    CustomSkinLoader_Fabric-14.15 or cubeon-friends-1.0.0+mc1.21 are covered."""
    low = (stem or "").lower()
    return any(low.startswith(p) for p in PROTECTED_MOD_STEM_PREFIXES)


def is_protected_mod(meta: dict | None = None, filename: str | None = None) -> bool:
    """Protected either by jar name or by the Modrinth slug it was installed
    from (the slug matters because Modrinth filenames don't always start with
    the project name)."""
    if meta and meta.get("slug") in (CSL_MODRINTH_SLUG_LOCAL,):
        return True
    if filename:
        stem = filename.replace(".jar.disabled", "").replace(".jar", "")
        return is_protected_mod_stem(stem)
    return False


def list_mods(mc_version: str | None, loader: str | None,
              version_id: str | None = None, *,
              profile_key: str | None = None) -> list[dict]:
    """Mods installed for this specific version+loader profile only.

    Pass version_id to read the profile owned by that installed instance (a
    modpack clone has its own); without it the legacy shared profile is used.
    Pass profile_key to read one exact profile folder (the pack export picker
    knows the folder, not always the instance id).
    """
    if profile_key:
        profile_dir = profile_dir_for_key(profile_key)
        if not profile_dir:
            return []
    else:
        profile_dir = resolve_profile_dir(mc_version, loader, version_id)
    mods = []
    if not os.path.isdir(profile_dir):
        return mods
    for fname in sorted(os.listdir(profile_dir)):
        if fname == PROFILE_META_FILENAME or fname.endswith(MOD_META_SUFFIX):
            continue
        full = os.path.join(profile_dir, fname)
        if os.path.isfile(full) and (fname.endswith(".jar") or fname.endswith(".jar.disabled")):
            enabled = not fname.endswith(".disabled")
            meta = _read_meta(profile_dir, fname) or {}
            mods.append({
                "filename": fname,
                "display_name": fname.replace(".jar.disabled", "").replace(".jar", ""),
                "enabled": enabled,
                "size_kb": round(os.path.getsize(full) / 1024, 1),
                "slug": meta.get("slug"),  # None for manually dropped-in jars
                # Modrinth's opaque id. A modpack manifest gives us only this,
                # so it's often the sole thing identifying a pack-installed mod.
                "project_id": meta.get("project_id"),
                "stem": name_stem(fname),
                # Cubeon-managed mods (CustomSkinLoader, Cubeon Friends) -
                # the Mods UI hides their controls and the core refuses to
                # delete/disable them even if asked directly.
                "protected": is_protected_mod(meta, fname),
            })
    return mods


def toggle_mod(mc_version: str | None, loader: str | None, filename: str,
               version_id: str | None = None) -> None:
    profile_dir = get_profile_dir(mc_version, loader, version_id)
    full = os.path.join(profile_dir, filename)
    # Stale-UI guard: the mod list is a snapshot; the file can vanish (user
    # deleted it in another tab/instance, or the link target is gone) between
    # render and click. Rename would raise FileNotFoundError from a click
    # handler - say what happened instead.
    if not os.path.lexists(full):
        raise ValueError("That mod is no longer on disk - refresh the mod list.")
    if is_protected_mod(_read_meta(profile_dir, filename), filename):
        raise ValueError(
            "That mod is managed by Cubeon and can't be disabled. "
            "Skins/capes and the Friends button depend on it.")
    new_name = filename[:-len(".disabled")] if filename.endswith(".disabled") else filename + ".disabled"
    # Both states can be on disk at once (a re-download while the old copy is
    # disabled). os.rename would silently REPLACE one on Linux/macOS (data
    # loss) and raise FileExistsError on Windows, uncaught inside a click
    # handler. Refuse instead and let the UI show the reason.
    target = os.path.join(profile_dir, new_name)
    if os.path.lexists(target):
        raise ValueError(
            "A copy of this mod with that state already exists - delete one first")
    os.rename(full, target)


def delete_mod(mc_version: str | None, loader: str | None, filename: str,
               version_id: str | None = None) -> None:
    profile_dir = get_profile_dir(mc_version, loader, version_id)
    full = os.path.join(profile_dir, filename)
    # Same stale-UI guard as toggle_mod(): deleting an already-gone entry is a
    # no-op (the goal - it not being in the profile - is already achieved), not
    # a crash. Missing sidecar/meta cleanup below is already exists()-guarded.
    if not os.path.lexists(full):
        return
    if is_protected_mod(_read_meta(profile_dir, filename), filename):
        raise ValueError(
            "That mod is managed by Cubeon and can't be removed. "
            "Skins/capes and the Friends button depend on it.")
    # lexists, not exists: a profile entry may be a dangling link into the
    # global mods store (the store's copy was deleted/moved). os.path.exists
    # is False for a dead link, so removing "the file" used to do nothing -
    # leaving the link behind forever while its sidecar was deleted. lexists
    # removes the link itself (unlink doesn't need the target to exist).
    # (The guard above already returned when it's gone, so this always runs.)
    os.remove(full)
    meta = _meta_path(profile_dir, filename)
    if os.path.exists(meta):
        os.remove(meta)


def _safe_jar_filename(raw_name: str) -> str:
    """Sanitize a user-supplied basename before it becomes a file in the
    profile dir. A file-picked name can carry characters that are legal on
    the OS it came from but not everywhere Cubeon runs (':' from a macOS/
    Windows filename breaks Windows; '/' or a NUL escapes/lonks oddly), and
    Windows also rejects names ending in a dot or space. Replace the bad
    characters instead of rejecting the install - the user picked the file,
    not its name."""
    stem, ext = os.path.splitext(raw_name)
    stem = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", stem).strip(" .") or "mod"
    return stem + (ext if ext else ".jar")


def _safe_download_filename(raw_name: str | None) -> str:
    """A sanitized, `.jar`-only filename for an API/download-supplied file.

    `filename` comes from Modrinth/CurseForge metadata or a pack's dependency
    list, not from the user: `../../evil`, an absolute path or a `.exe` must
    never become the join()ed destination inside the profile. Rejecting a
    non-jar keeps this from writing an executable next to the game.
    """
    # Windows separators do not split on POSIX; normalize first so "..\\x.jar"
    # cannot smuggle a path component through the sanitizer.
    base = os.path.basename(str(raw_name or "").replace("\\", "/"))
    if not base:
        raise ValueError("Refusing a download with no file name.")
    filename = _safe_jar_filename(base)
    if not filename.lower().endswith(".jar"):
        raise ValueError(f"Refusing to install '{base}' - a mod must be a .jar file.")
    return filename


def add_mod_file(mc_version: str | None, loader: str | None, src_path: str,
                 version_id: str | None = None) -> None:
    profile_dir = get_profile_dir(mc_version, loader, version_id)
    fname = _safe_jar_filename(os.path.basename(src_path))
    global_mod_cache.put_file(src_path, os.path.join(profile_dir, fname))


def _open_folder(path: str) -> None:
    if os.name == "nt":
        os.startfile(path)  # type: ignore[attr-defined]
    elif os.uname().sysname == "Darwin":
        import subprocess
        subprocess.Popen(["open", path])
    else:
        import subprocess
        subprocess.Popen(["xdg-open", path])


def open_mods_folder(mc_version: str | None, loader: str | None,
                     version_id: str | None = None) -> None:
    profile_dir = get_profile_dir(mc_version, loader, version_id)
    _open_folder(profile_dir)


def install_local_mod(src_path: str, mc_version: str | None, loader: str | None,
                      superseded_cb=None, version_id: str | None = None) -> str:
    """Installs a local .jar file into the (mc_version, loader) profile,
    the same destination download_mod() writes to. Used by the 'Install from
    file' button so the user can add a mod they already have on disk without
    going through Modrinth. The jar is stored once in the global mods store
    (a second profile wanting the same file links it, no copy) and the
    profile holds a link to it. Returns the filename it was stored as."""
    if not src_path.lower().endswith(".jar"):
        raise ValueError("That's not a .jar file.")
    if not os.path.isfile(src_path):
        raise ValueError("Couldn't find that file.")
    require_mod_loader(mc_version, loader, "install a mod")

    profile_dir = get_profile_dir(mc_version, loader, version_id)
    filename = _safe_jar_filename(os.path.basename(src_path))
    dest = os.path.join(profile_dir, filename)

    # Avoid clobbering an existing mod with the same filename - add a
    # short suffix instead of silently overwriting someone's install.
    if os.path.exists(dest):
        base, ext = os.path.splitext(filename)
        filename = f"{base}_{uuid.uuid4().hex[:6]}{ext}"
        dest = os.path.join(profile_dir, filename)

    global_mod_cache.put_file(src_path, dest)
    # No slug - this mod wasn't matched to a Modrinth project, so there's
    # nothing meaningful to record in the sidecar file. An older build of the
    # same mod can still be recognized by filename stem and is disabled (not
    # deleted - a hand-added jar may be the only copy the user has).
    _write_meta(profile_dir, filename, None)
    moved = supersede_older_copies(profile_dir, filename)
    if moved and superseded_cb:
        superseded_cb(moved)
    return filename


# ---------------------------------------------------------------------------
# Syncing the active profile into the real game mods/ folder
# ---------------------------------------------------------------------------

def sync_mods_to_game(mc_version: str | None, loader: str | None,
                      version_id: str | None = None) -> None:
    """Copies every *enabled* jar from the (mc_version, loader) profile into
    the real MINECRAFT_DIR/mods folder the game actually reads at launch,
    and clears out anything left over from a different profile. Without
    this, mods installed/enabled in a profile never actually load, since
    Minecraft has no idea the per-profile folders exist.

    Requires an explicit, non-empty mc_version and loader - this is the
    fix for the launcher's core "mods sometimes just don't load" bug: the
    launch flow used to call this with loader=None on every single launch,
    which silently took the 'vanilla / no mods' branch below and wiped
    MINECRAFT_DIR/mods without restoring anything, no matter what loader
    was actually selected on the Play tab."""
    require_loader_and_version(mc_version, loader, "sync mods to the game")

    os.makedirs(MODS_DIR, exist_ok=True)
    previously_synced = _read_synced_manifest()
    for fname in os.listdir(MODS_DIR):
        full = os.path.join(MODS_DIR, fname)
        if not os.path.isfile(full) or not fname.endswith(".jar"):
            continue
        if fname in previously_synced:
            # Ours: safe to remove and replace with this launch's profile.
            try:
                os.remove(full)
            except FileNotFoundError:
                pass
            except PermissionError as ex:
                # Windows keeps jars open while the game runs. Deleting one is
                # not optional (it would let the old profile leak into this
                # launch), so say exactly what to do instead of crashing with
                # a raw PermissionError.
                raise RuntimeError(
                    "Another Minecraft window is using these mods - close it "
                    "and try again") from ex
        else:
            # Not ours: the user dropped it in by hand. Keep it, out of the
            # way, instead of wiping it on every launch.
            _backup_user_jar(fname)

    if loader not in MOD_CAPABLE_LOADERS:
        # Vanilla (or an unrecognized loader) doesn't load mods - leave MODS_DIR
        # empty, and record that we linked nothing.
        write_json(os.path.join(MODS_DIR, _SYNC_MANIFEST), {"files": []})
        return

    profile_dir = get_profile_dir(mc_version, loader, version_id)

    # One jar per mod, even if the profile holds several builds of it.
    #
    # A profile accumulates duplicates easily: a modpack lays down its pinned
    # build of Sodium, then the user installs a newer Sodium from the Mods tab,
    # and because the version is in the filename nothing overwrote anything.
    # Handing the game both is what turns that into a crash - Fabric loads the
    # highest version of each mod, so the *set* the game runs is picked one mod
    # at a time with no regard for whether those particular builds go together.
    # Iris 1.11.3 + Sodium 0.9.2-alpha.4 is how that ends: Iris's Sodium-compat
    # mixin finds nothing to patch, aborts the login packet mid-setLevel, and
    # the next frame renders a level whose player was never assigned.
    #
    # So: group the enabled jars by identity and link only the build Fabric
    # would have chosen anyway. Nothing in the profile is modified - a profile
    # is the user's data and this runs on every launch; the loser simply isn't
    # copied into a folder that gets wiped and rebuilt each time regardless.
    chosen: dict = {}
    for fname in sorted(os.listdir(profile_dir)):
        if not fname.endswith(".jar"):  # skips *.jar.disabled and metadata
            continue
        # A profile entry whose link target is gone (store file deleted/moved,
        # or a pre-global-store link whose old cache was cleaned up) must not
        # crash the launch - there are no bytes to sync, so it just isn't
        # installed anymore. list_mods() already hides it via the same gate.
        src_full = os.path.join(profile_dir, fname)
        if not os.path.isfile(src_full):
            continue
        slug, pid, stem = mod_identity(profile_dir, fname)
        key = ("id", pid) if pid else ("slug", slug) if slug else ("stem", stem)
        if key[1]:
            previous = chosen.get(key)
            if previous is None:
                chosen[key] = fname
            else:
                # Highest MOD version wins; the mtime only breaks an exact tie
                # (two builds that report the same version) so a rename/rebuild
                # cannot make the older file win on sorted() order alone.
                chosen[key] = max(
                    (previous, fname),
                    key=lambda name: (_version_key(name, mc_version),
                                      _jar_mtime(profile_dir, name)))
        else:
            chosen[("file", fname)] = fname

    synced: list[str] = []
    for fname in sorted(chosen.values()):
        src = os.path.join(profile_dir, fname)
        dst = os.path.join(MODS_DIR, fname)
        # Hard link first: profile and mods live on the same disk, so the game
        # reads the exact same bytes with zero copy time - launching with a
        # big modpack no longer waits on re-copying hundreds of MB every
        # single launch. Falls back to a real copy wherever linking is not
        # possible (different filesystems, restrictive mount options).
        try:
            os.link(src, dst)
        except OSError:
            # A failed copy (disk full, I/O error) must not leave a truncated
            # jar behind - Fabric/Forge would try to load it and crash. Remove
            # the partial file and report which mod failed, readably.
            try:
                shutil.copyfile(src, dst)
            except Exception as ex:
                try:
                    os.remove(dst)
                except OSError:
                    pass
                raise RuntimeError(
                    f"Couldn't copy {fname} into the game's mods folder: {ex}"
                ) from ex
        synced.append(fname)

    # Remember exactly what we linked, so the NEXT launch can tell our jars
    # from files the user added by hand.
    write_json(os.path.join(MODS_DIR, _SYNC_MANIFEST),
               {"files": sorted(synced)})


def copy_mods_between_profiles(
    src_mc_version: str | None, src_loader: str | None,
    dst_mc_version: str | None, dst_loader: str | None,
    src_version_id: str | None = None, dst_version_id: str | None = None,
) -> list[dict]:
    """Copies mods from one profile to another. For mods we recognize (have
    a stored Modrinth slug), we fetch a build that actually matches the
    destination version+loader instead of blindly copying the jar - a jar
    built for one MC version usually won't load on another.

    Pass src_version_id / dst_version_id for isolated instances (modpack
    clones own a private profile); without them the legacy shared profile for
    that version+loader is used, exactly as before.

    Returns a per-mod result list: {name, status: 'copied'|'no_match'|'skipped', detail}."""
    results = []
    for m in list_mods(src_mc_version, src_loader, src_version_id):
        name = m["display_name"]
        if not m["slug"]:
            results.append({"name": name, "status": "skipped",
                             "detail": "unknown mod (no source info), copy manually"})
            continue
        try:
            file_info = get_mod_download(m["slug"], mc_version=dst_mc_version, loader=dst_loader)
        except requests.RequestException as ex:
            results.append({"name": name, "status": "no_match", "detail": str(ex)})
            continue
        if not file_info:
            results.append({"name": name, "status": "no_match",
                             "detail": f"no build for {dst_mc_version or 'that version'}"})
            continue
        try:
            download_mod(
                file_info["url"], file_info["filename"],
                mc_version=dst_mc_version, loader=dst_loader, slug=m["slug"],
                hashes=file_info.get("hashes"), version_id=dst_version_id,
            )
            results.append({"name": name, "status": "copied", "detail": file_info["version_number"]})
        except (OSError, ValueError, requests.RequestException) as ex:
            # One bad mod (sanitized/rejected filename, unsupported build) must
            # not abort the rest of the copy.
            results.append({"name": name, "status": "no_match", "detail": str(ex)})
    return results


# ---------------------------------------------------------------------------
# Mod discovery/download via Modrinth's public API (no auth required).
# Modrinth requires a distinctive User-Agent on every request.
# ---------------------------------------------------------------------------

def get_recommended_mods(mc_version: str | None = None, loader: str = "fabric",
                          category: str | None = None, limit: int = 100,
                          offset: int = 0) -> list[dict]:
    """Fetches mods to show before any search. With no category picked, this
    is the small curated set of popular all-rounder mods. With a category
    picked, it instead searches Modrinth for the top mods in that category
    (scoped to the current version+loader) so switching categories actually
    changes what's shown, sorted by relevance/downloads.

    The category path is a normal Modrinth search, so it honors limit/offset:
    the UI asks for ONE page at a time (offset = page * page_size) instead of
    pulling 100 hits up front just to slice them locally. The curated no-
    category set is tiny (a handful of slugs) and ignores offset/limit."""
    if category:
        return search_mods("", mc_version=mc_version, loader=loader,
                            categories=[category], limit=limit, offset=offset)

    cache_key = {"mc_version": mc_version, "loader": loader, "category": category, "slugs": RECOMMENDED_MOD_SLUGS}

    def _fetch() -> list[dict]:
        projects = net.get_json(
            f"{MODRINTH_API}/projects", params={"ids": json.dumps(RECOMMENDED_MOD_SLUGS)},
            headers=modrinth_headers(), timeout=10,
        )

        # Preserve curated order rather than whatever order the API returns
        by_slug = {p.get("slug"): p for p in projects}
        results = []
        for slug in RECOMMENDED_MOD_SLUGS:
            p = by_slug.get(slug)
            if not p:
                continue
            results.append({
                "project_id": p.get("id"),
                "slug": p.get("slug"),
                "title": p.get("title"),
                "description": p.get("description"),
                "icon_url": p.get("icon_url"),
                "downloads": p.get("downloads", 0),
                "author": None,
            })
        return results

    # Curated picks change about as often as Modrinth's front page: a day of
    # freshness, stale-while-revalidate after that, stale forever offline.
    return local_cache.cached_call("recommended_mods", cache_key, _fetch, max_age=86400)


def _mod_search_queries(query: str) -> list[str]:
    words = query.split()
    candidates = [query]
    if any(word.lower() == "armour" for word in words):
        candidates.append(" ".join("armor" if word.lower() == "armour" else word for word in words))
    if len(words) > 1:
        width = min(2, len(words) - 1)
        candidates.extend((" ".join(words[-width:]), " ".join(words[:width])))
    return list(dict.fromkeys(candidates))


def _mod_project_reference(query: str) -> str | None:
    try:
        parsed = urlsplit(query if "://" in query else "https://" + query)
    except ValueError:
        return None
    if parsed.scheme not in {"http", "https"} or parsed.netloc.lower() not in {
        "modrinth.com", "www.modrinth.com",
    }:
        return None
    parts = parsed.path.strip("/").split("/")
    if len(parts) < 2 or parts[0] not in {"mod", "project"}:
        return None
    return parts[1] if re.fullmatch(r"[A-Za-z0-9_-]+", parts[1]) else None


def _mod_search_hit(hit: dict, search_query: str) -> dict:
    loaders = hit.get("loaders")
    if loaders is None and "categories" in hit:
        loaders = [category for category in (hit["categories"] or []) if category in MOD_CAPABLE_LOADERS]
    return {
        "project_id": hit.get("project_id") or hit.get("id"),
        "slug": hit.get("slug"),
        "title": hit.get("title"),
        "description": hit.get("description"),
        "icon_url": hit.get("icon_url"),
        "downloads": hit.get("downloads", 0),
        "author": hit.get("author"),
        "game_versions": hit.get("game_versions", hit.get("versions")),
        "loaders": loaders,
        "search_query": search_query,
    }


def search_mods(query: str, mc_version: str | None = None, loader: str | None = "fabric",
                 categories: list[str] | None = None, limit: int = 100,
                 offset: int = 0) -> list[dict]:
    """Searches Modrinth for mods, optionally scoped to a specific MC version,
    loader, and one or more categories (e.g. "performance", "worldgen").
    Returns a simplified list of hit dicts ready for display.

    `offset` pages through Modrinth's result set: the Mods tab fetches one
    page at a time (limit = page size, offset = page * page size) so a browse
    never pulls every page up front. Offset is part of the cache key, so each
    page caches independently. Empty name searches try bounded shorter queries;
    hits identify the effective query so later pages stay on the same results.
    Modrinth project links resolve directly; installers still check compatibility.
    """
    query = " ".join((query or "").split())
    facets = [["project_type:mod"]]
    if loader:
        facets.append([f"categories:{loader}"])
    if mc_version:
        facets.append([f"versions:{mc_version}"])
    if categories:
        # Categories are OR'd together within their own facet group (any of
        # the selected categories match), while still being AND'd against
        # loader/version above - matches how Modrinth's own filters behave.
        facets.append([f"categories:{c}" for c in categories])

    cache_key = {
        "query": query, "mc_version": mc_version, "loader": loader,
        "categories": categories or [], "limit": limit, "offset": offset,
        "revision": 2,
    }

    def _fetch() -> list[dict]:
        reference = _mod_project_reference(query)
        if reference:
            if offset:
                return []
            project = get_mod_details(reference)
            if not project or project.get("project_type") != "mod":
                return []
            return [_mod_search_hit(project, query)]

        effective_query = query
        candidates = _mod_search_queries(query)
        if offset and len(candidates) > 1:
            first_page = search_mods(query, mc_version=mc_version, loader=loader,
                                     categories=categories, limit=limit)
            if not first_page:
                return []
            effective_query = first_page[0].get("search_query", query)
        params = {
            "query": effective_query, "limit": str(limit), "offset": str(offset),
            "facets": json.dumps(facets),
            "index": modrinth_search_index(query),
        }
        for candidate in ([effective_query] if offset else candidates):
            params["query"] = candidate
            data = net.get_json(f"{MODRINTH_API}/search", params=params,
                                headers=modrinth_headers(), timeout=10)
            if data.get("hits"):
                return rank_search_hits([
                    _mod_search_hit(hit, candidate) for hit in data["hits"]
                ], candidate)
        return []

    # Browse/search: 6 hours fresh (long enough that a browsing session never
    # blocks, short enough that "top downloads" stays current), then
    # stale-while-revalidate, then stale forever as the offline fallback.
    previous = local_cache.get_stale("search_mods", cache_key)
    return local_cache.cached_call(
        "search_mods", cache_key, _fetch,
        max_age=60 if previous == [] else 6 * 3600,
        background_refresh=previous != [],
    )


# In-memory slug -> icon URL cache for installed-mod rows. Lives for the
# process only: the bulk endpoint is one cheap request per session, and
# re-refreshing the installed list must not re-hit the network per row.
_icon_url_cache: dict[str, "str | None"] = {}


def get_mod_icons(slugs: "list[str]") -> dict[str, "str | None"]:
    """Returns {slug: icon_url} for the given Modrinth slugs (None where a
    slug has no icon or can't be resolved).

    Installed mods only store their slug in a sidecar file - not the icon the
    browse row showed - so the installed list needs this second lookup to
    render real mod pictures. One bulk GET /projects?ids=[...] covers every
    slug at once. Three cache layers on top: the per-process dict below, a
    7-day disk cache (so icons are right on relaunch, no fetch at all), and
    the disk copy as an offline fallback (installed list still gets its art
    with the network down)."""
    resolved: dict[str, "str | None"] = {}
    missing: list[str] = []
    for s in sorted({x for x in slugs if x}):
        if s in _icon_url_cache:
            resolved[s] = _icon_url_cache[s]
        else:
            cached = local_cache.get("mod_icons", s, max_age=7 * 86400)
            if cached is not None:
                _icon_url_cache[s] = cached
                resolved[s] = cached
            else:
                missing.append(s)

    if missing:
        try:
            projects = net.get_json(
                f"{MODRINTH_API}/projects",
                params={"ids": json.dumps(missing)},
                headers=modrinth_headers(), timeout=10,
            )
            for project in projects:
                url = project.get("icon_url") or None
                slug = project.get("slug")
                _icon_url_cache[slug] = url
                local_cache.set("mod_icons", slug, url)
        except Exception:
            pass  # offline / rate-limited: fall through to the stale tier
        for s in missing:
            if s not in _icon_url_cache:
                # Stale disk copy (last week's lookup) beats a re-fetch per
                # refresh; only a never-resolved slug stays None.
                stale = local_cache.get_stale("mod_icons", s)
                _icon_url_cache[s] = stale
    return {s: _icon_url_cache.get(s) for s in slugs if s}


# The launch path must not hold the spawn hostage while the route is dead.
# A version lookup is one small JSON: the UI/interactive policy (10 s per try,
# 3 tries, 1.5 s + 3 s backoff) is right for a click the user is watching, and
# measured 34.7 s on a blackholed route - before Minecraft even starts. One
# 3 s connect attempt is enough to tell "Modrinth is up" from "no network";
# a genuine success is unaffected because the first attempt is the only one.
LAUNCH_LOOKUP_TIMEOUT = (3, 10)   # (connect, read); read stays generous
LAUNCH_LOOKUP_ATTEMPTS = 1


def get_mod_download(project_id_or_slug: str, mc_version: str | None = None,
                      loader: str = "fabric", *,
                      timeout: int | tuple = 10,
                      attempts: int | None = None,
                      version_predicates=None) -> dict | None:
    """Finds the best matching version file for a mod, filtered by MC version
    and loader when given. Returns {filename, url, size} or None if no
    matching version exists.

    `timeout`/`attempts` exist for the launch path (see LAUNCH_LOOKUP_*):
    they bound the wait on a dead route. Everything else - the cache key
    included - is unchanged, so both callers share one cache.
    `version_predicates` requires ALL requesters' constraints, and uses its own
    cache entry so a pinned dependency cannot get an unconstrained latest jar.
    """
    if attempts is None:
        attempts = net.DEFAULT_ATTEMPTS
    params = {}
    if loader:
        params["loaders"] = json.dumps([loader])
    if mc_version:
        params["game_versions"] = json.dumps([mc_version])

    cache_key = {"project": project_id_or_slug, "mc_version": mc_version, "loader": loader, "revision": 2}
    if version_predicates is not None:
        cache_key["predicates"] = list(version_predicates)

    def _fetch():
        versions = net.get_json(
            f"{MODRINTH_API}/project/{project_id_or_slug}/version",
            params=params, headers=modrinth_headers(), timeout=timeout,
            attempts=attempts,
        )
        if not versions:
            return None

        # Versions come back newest-first. A release occasionally has an empty
        # `files` list (or only non-primary files); blindly using versions[0]
        # would return None and make the doctor wrongly DISABLE a mod that does
        # have a downloadable build. Take the newest version that actually has
        # a file.
        latest = next((v for v in versions if v.get("files") and all(
            version_satisfies(str(v.get("version_number") or ""), predicate)
            for predicate in (version_predicates or ()))), None)
        if latest is None:
            return None
        files = latest.get("files") or []
        primary = next((f for f in files if f.get("primary")), files[0])
        if not primary:
            return None

        return {
            "filename": primary.get("filename"),
            "url": primary.get("url"),
            "size_kb": round(primary.get("size", 0) / 1024, 1),
            "version_number": latest.get("version_number"),
            "hashes": primary.get("hashes") or {},
        }

    # File resolution is what runs between the click on "Download" and the
    # download starting - it must feel instant. 24h fresh, then serve stale
    # and revalidate in the background; a re-released mod picks up on the
    # next browse instead of blocking this click.
    previous = local_cache.get_stale("mod_download", cache_key)
    cached = local_cache.cached_call(
        "mod_download", cache_key, lambda: {"file": _fetch()},
        max_age=300 if previous and previous.get("file") is None else 86400,
        background_refresh=not (previous and previous.get("file") is None),
    )
    return cached["file"]


def get_mod_details(project_id_or_slug: str) -> dict | None:
    """Full Modrinth project record, normalized for the mod detail view.

    One cached GET /project/{id}: everything the detail dialog shows besides
    the version list - long description, gallery art, categories, supported
    loaders/versions, links and licence. Returns None when the project can't
    be resolved at all (deleted, or the id belongs to another platform such as
    a CurseForge-only pack entry), so callers can fall back to the row they
    already had instead of showing an empty dialog.
    """
    ref = (project_id_or_slug or "").strip()
    if not ref:
        return None

    def _fetch() -> dict:
        p = net.get_json(
            f"{MODRINTH_API}/project/{ref}",
            headers=modrinth_headers(), timeout=10,
        )

        gallery = []
        for img in p.get("gallery") or []:
            url = img.get("url")
            if url:
                gallery.append({
                    "url": url,
                    "featured": bool(img.get("featured")),
                    "title": img.get("title") or "",
                    "description": img.get("description") or "",
                })
        # Featured art first: it is the project's own chosen hero image, which
        # is a better lead than an arbitrary gallery order.
        gallery.sort(key=lambda g: not g["featured"])

        return {
            "project_id": p.get("id"),
            "project_type": p.get("project_type"),
            "slug": p.get("slug"),
            "title": p.get("title") or p.get("slug") or ref,
            "description": p.get("description") or "",
            "body": p.get("body") or "",
            "icon_url": p.get("icon_url"),
            "gallery": gallery,
            "downloads": p.get("downloads", 0),
            "followers": p.get("followers", 0),
            "categories": p.get("categories") or [],
            "loaders": p.get("loaders") or [],
            "game_versions": p.get("game_versions") or [],
            "client_side": p.get("client_side"),
            "server_side": p.get("server_side"),
            "source_url": p.get("source_url") or "",
            "issues_url": p.get("issues_url") or "",
            "wiki_url": p.get("wiki_url") or "",
            "discord_url": p.get("discord_url") or "",
            "license": (p.get("license") or {}).get("name") or "",
            "updated": p.get("updated"),
            "published": p.get("published"),
        }

    return local_cache.cached_call(
        "mod_details", {"project": ref, "revision": 2}, _fetch,
        max_age=6 * 3600)


def get_mod_versions(project_id_or_slug: str, mc_version: str | None = None,
                     loader: str | None = None, *,
                     allow_network: bool = True) -> list[dict]:
    """Every released version of a mod, newest first, normalized for the
    detail view. Each entry carries its own supported loaders and Minecraft
    versions, whether it is compatible with the profile the user is browsing
    (`compatible`), the primary downloadable file, and its dependencies.

    ONE GET /project/{id}/version covers the whole list - no per-version
    requests - and is cached for 6 hours, so opening a mod's menu twice costs
    nothing and the version picker stays usable offline via the stale tier.

    `allow_network=False` reads ONLY the last cached copy (no request), for
    callers that must never block on the network.
    """
    ref = (project_id_or_slug or "").strip()
    if not ref:
        return []
    def _fetch() -> list[dict]:
        versions = net.get_json(
            f"{MODRINTH_API}/project/{ref}/version",
            headers=modrinth_headers(), timeout=10,
        )
        out = []
        for v in versions:
            files = v.get("files") or []
            primary = next((f for f in files if f.get("primary")),
                           files[0] if files else None)
            if not primary:
                continue
            game_versions = v.get("game_versions") or []
            loaders = v.get("loaders") or []
            out.append({
                "id": v.get("id"),
                "version_number": v.get("version_number") or "",
                "name": v.get("name") or "",
                "version_type": v.get("version_type") or "release",
                "game_versions": game_versions,
                "loaders": loaders,
                "date_published": v.get("date_published") or "",
                "downloads": v.get("downloads", 0),
                "changelog": v.get("changelog") or "",
                "dependencies": [
                    {
                        "project_id": d.get("project_id"),
                        "version_id": d.get("version_id"),
                        "dependency_type": d.get("dependency_type"),
                    }
                    for d in (v.get("dependencies") or [])
                ],
                "filename": primary.get("filename"),
                "url": primary.get("url"),
                "size_kb": round(primary.get("size", 0) / 1024, 1),
                "hashes": primary.get("hashes") or {},
            })
        return out

    if allow_network:
        releases = local_cache.cached_call(
            "mod_versions", {"project": ref}, _fetch, max_age=6 * 3600)
    else:
        releases = local_cache.get_stale("mod_versions", {"project": ref})
    return [dict(v, compatible=(
        (not mc_version or mc_version in v.get("game_versions", []))
        and (not loader or loader in v.get("loaders", []))))
        for v in releases or []]


def _required_deps_cached(project_id_or_slug: str, mc_version: str | None,
                          loader: str) -> list[dict]:
    """required_dependencies() behind the 6h cache, so the doctor can check a
    whole profile without one network round trip per installed mod per run."""
    def _fetch() -> list[dict]:
        return required_dependencies(project_id_or_slug, mc_version, loader)
    return local_cache.cached_call(
        "mod_required_deps",
        {"project": project_id_or_slug, "mc": mc_version, "loader": loader},
        _fetch, max_age=6 * 3600)


# ---------------------------------------------------------------------------
# Mod-conflict detection (Fabric `breaks`)
#
# The single most confusing crash a modded player hits is a VERSION CONFLICT:
#
#   Mod 'Sodium' 0.8.14 is incompatible with version 1.10.7 or earlier of
#   mod 'Iris', yet a conflicting version is present: 1.10.7
#
# The Modrinth API does NOT expose this relationship - `dependencies` on a
# version only lists required/optional/embedded/incompatible PROJECTS, never
# Fabric's `breaks` version ranges. The only source of truth is the jar's own
# fabric.mod.json, so that is what we read. It is a local file operation, so
# detection works offline (and at launch); resolving an actual conflict needs
# the network to find a replacement build.
# ---------------------------------------------------------------------------


def _version_parts(version: str) -> list[str]:
    """Numeric/alpha runs of a version, build metadata after '+' dropped -
    the same thing Fabric ignores when matching `depends`/`breaks`."""
    base = (version or "").strip().split("+", 1)[0]
    return re.findall(r"\d+|[A-Za-z]+", base)


def _cmp_versions(a: str, b: str) -> int:
    """Maven-ish ordering: numeric vs numeric by value, a numeric run beats an
    alpha one (1.0 > 1.0-rc), a longer version beats its own prefix
    (1.0.1 > 1.0) unless the extra bit is a qualifier (1.0-rc < 1.0)."""
    pa, pb = _version_parts(a), _version_parts(b)
    for i in range(max(len(pa), len(pb))):
        x = pa[i] if i < len(pa) else None
        y = pb[i] if i < len(pb) else None
        if x is None:
            return 1 if (y and y.isalpha()) else -1
        if y is None:
            return -1 if x.isalpha() else 1
        if x.isdigit() and y.isdigit():
            if int(x) != int(y):
                return -1 if int(x) < int(y) else 1
        elif x.isdigit() != y.isdigit():
            return 1 if x.isdigit() else -1
        elif x.lower() != y.lower():
            return -1 if x.lower() < y.lower() else 1
    return 0


def _match_wildcard(version: str, pattern: str) -> bool:
    """Fabric-style wildcard: `0.8.x`, `1.21.*` match on their prefix."""
    pv = _version_parts(pattern)
    vv = _version_parts(version)
    for i, p in enumerate(pv):
        if p in ("x", "X", "*"):
            return True
        if i >= len(vv):
            return False
        if p.isdigit() and vv[i].isdigit():
            if int(p) != int(vv[i]):
                return False
        elif p.lower() != vv[i].lower():
            return False
    return True


def _satisfies_range(version: str, expr: str) -> bool:
    if re.fullmatch(r"\[[^,\[\]]+\]", expr.strip()):
        return _cmp_versions(version, expr.strip()[1:-1]) == 0
    for m in re.finditer(r"([\[\(])([^,\)]*),?([^\]\)]*)([\]\)])", expr):
        lo_inc = m.group(1) == "["
        hi_inc = m.group(4) == "]"
        lo, hi = m.group(2).strip(), m.group(3).strip()
        if lo:
            c = _cmp_versions(version, lo)
            if not (c >= 0 if lo_inc else c > 0):
                continue
        if hi:
            c = _cmp_versions(version, hi)
            if not (c <= 0 if hi_inc else c < 0):
                continue
        return True
    return False


def _tilde_caret_bounds(term: str):
    """(floor, ceiling) version strings for `~1.21.5` / `^1.2.3`, or None.

    Fabric/Quilt semver: `~X.Y.Z` = >=X.Y.Z <X.(Y+1).0 (`~X` = <(X+1)), and
    `^X.Y.Z` = >=X.Y.Z up to the next bump of the left-most non-zero part
    (^1.2.3 -> <2.0.0, ^0.2.3 -> <0.3.0). Without this a jar declaring
    `"minecraft": "~1.21.5"` was compared as an EXACT version, judged
    "built for another Minecraft version" on 1.21.11, and offered for removal."""
    match = re.match(r"^[~^]\s*(\d+(?:\.\d+)*)", term)
    if not match:
        return None
    nums = [int(p) for p in match.group(1).split(".")]
    floor = ".".join(str(n) for n in nums)
    if term[0] == "~":
        ceiling = [nums[0] + 1] if len(nums) == 1 else [nums[0], nums[1] + 1]
    else:
        padded = (nums + [0, 0, 0])[:3]
        index = next((i for i, n in enumerate(padded) if n), 2)
        ceiling = padded[:index] + [padded[index] + 1]
    return floor, ".".join(str(n) for n in ceiling)


def _satisfies_term(version: str, term: str) -> bool:
    term = term.strip()
    if term in ("", "*"):
        return True
    if term[:1] in ("~", "^") and not ("x" in term.lower() or "*" in term):
        bounds = _tilde_caret_bounds(term)
        if bounds is not None:
            floor, ceiling = bounds
            return _cmp_versions(version, floor) >= 0 and _cmp_versions(version, ceiling) < 0
    if "x" in term.lower() or "*" in term:
        return _match_wildcard(version, term)
    for op in ("<=", ">=", "!=", "==", "=", "<", ">"):
        if term.startswith(op):
            c = _cmp_versions(version, term[len(op):].strip())
            return {"<=": c <= 0, ">=": c >= 0, "!=": c != 0,
                    "==": c == 0, "=": c == 0, "<": c < 0, ">": c > 0}[op]
    # A bare version means exact (Fabric treats it as an upper bound only when
    # prefixed with an operator; `0.8.x` handled above).
    return _cmp_versions(version, term) == 0


def version_satisfies(version: str, predicate) -> bool:
    """True when `version` matches a Fabric/Maven version predicate such as
    `<=1.10.7`, `>=0.16.0`, `0.8.x`, `[1.0,2.0)`, `*`, or an AND/OR
    combination. A missing/blank predicate means "any version"."""
    if isinstance(predicate, (list, tuple)):
        return any(version_satisfies(version, p) for p in predicate)
    expr = str(predicate or "").strip()
    if expr in ("", "*", "any"):
        return True
    for alt in expr.split("||"):
        alt = alt.strip()
        if not alt:
            continue
        if alt[0] in "[(":
            if _satisfies_range(version, alt):
                return True
            continue
        if all(_satisfies_term(version, t) for t in alt.split()):
            return True
    return False


def _nested_mod_metadata(jar_path: str, *, max_depth: int = 2, loader: str | None = None) -> dict:
    """Every mod id a jar PROVIDES, including the ones bundled inside it.

    A Fabric jar may ship other mods as jar-in-jar (`META-INF/jars/*.jar`):
    Fabric API is 43 modules (`fabric-rendering-fluids-v1`,
    `fabric-resource-loader-v0`, ...), and c2me bundles 20+ of its own. Those
    nested mods are REAL - the loader registers them and they satisfy a
    `depends` entry - but they are not files in the mods folder and have no
    Modrinth project, so anything that only looks at top-level jars concludes
    they are missing. That is exactly how "Fix problems" used to DISABLE
    sodium, modmenu and c2me: their fabric.mod.json depends on Fabric API
    submodules and on their own bundled modules.

    Returns {id: version} for this jar's own metadata plus every nested one.
    Never raises; a jar it cannot read contributes nothing.
    """
    import io
    import zipfile

    out: dict = {}

    def _scan(blob: bytes, depth: int) -> None:
        if depth > max_depth:
            return
        try:
            with zipfile.ZipFile(io.BytesIO(blob)) as z:
                names = set(z.namelist())
                meta = read_mod_metadata(io.BytesIO(blob), loader)
                if meta and (not loader or loader in meta.get("loaders", [])):
                    if isinstance(meta.get("id"), str) and meta["id"]:
                        out.setdefault(meta["id"].lower(), str(meta.get("version") or ""))
                    for identity, version in (meta.get("provided") or {}).items():
                        out.setdefault(identity.lower(), version)
                for name in names:
                    if name.startswith("META-INF/jars/") and name.endswith(".jar"):
                        try:
                            _scan(z.read(name), depth + 1)
                        except Exception:
                            continue
        except Exception:
            return

    try:
        with open(jar_path, "rb") as fh:
            _scan(fh.read(), 1)
    except Exception:
        return {}
    return out


def read_mod_metadata(jar_path: str, loader: str | None = None) -> dict | None:
    """A jar's own declared identity: {id, version, name, depends, breaks}.

    Reads the descriptor for the instance's loader when a universal jar
    contains several. An unreadable jar contributes no compatibility claim.
    """
    import zipfile
    try:
        with zipfile.ZipFile(jar_path) as z:
            names = set(z.namelist())
            preferred = {
                "forge": ("META-INF/mods.toml",),
                "neoforge": ("META-INF/neoforge.mods.toml", "META-INF/mods.toml"),
                "quilt": ("quilt.mod.json", "fabric.mod.json"),
                "fabric": ("fabric.mod.json",),
            }.get(loader, ())
            descriptor = next((name for name in preferred if name in names), None)
            if descriptor is None:
                descriptor = next((name for name in ("fabric.mod.json", "quilt.mod.json",
                                  "META-INF/neoforge.mods.toml", "META-INF/mods.toml")
                                  if name in names), None)
            if descriptor == "fabric.mod.json":
                d = json.loads(z.read("fabric.mod.json").decode("utf-8", "replace"))
                return {
                    "id": d.get("id"),
                    "version": str(d.get("version") or ""),
                    "name": d.get("name") or d.get("id") or "",
                    "depends": d.get("depends") or {},
                    "breaks": d.get("breaks") or {},
                    "loaders": ["fabric", "quilt"],
                    "provided": {identity.lower(): str(d.get("version") or "")
                                 for identity in d.get("provides", []) if isinstance(identity, str)},
                }
            if descriptor == "quilt.mod.json":
                d = json.loads(z.read("quilt.mod.json").decode("utf-8", "replace"))
                q = d.get("quilt_loader") or {}
                def _pairs(items):
                    out = {}
                    for it in items or []:
                        if isinstance(it, dict) and it.get("id"):
                            out[it["id"]] = it.get("versions") or "*"
                    return out
                return {
                    "id": q.get("id"),
                    "version": str(q.get("version") or ""),
                    "name": q.get("id") or "",
                    "depends": _pairs(q.get("depends")),
                    "breaks": _pairs(q.get("breaks")),
                    "loaders": ["quilt"],
                }
            if descriptor:
                import tomllib
                data = tomllib.loads(z.read(descriptor).decode("utf-8"))
                declared = data.get("mods") or []
                if not declared:
                    return None
                primary = declared[0]
                dependencies = (data.get("dependencies") or {}).get(primary.get("modId"), [])
                dependencies = [entry for entry in dependencies
                                if str(entry.get("side", "BOTH")).upper() != "SERVER"]
                manifest = z.read("META-INF/MANIFEST.MF").decode("utf-8", "replace") if "META-INF/MANIFEST.MF" in names else ""
                implementation = re.search(r"(?m)^Implementation-Version:\s*(.+)$", manifest)
                def mod_version(entry):
                    value = str(entry.get("version") or "")
                    return (implementation.group(1).strip() if implementation else "") if "${" in value else value
                return {
                    "id": primary.get("modId"), "name": primary.get("displayName") or primary.get("modId"),
                    "version": mod_version(primary),
                    "depends": {entry["modId"]: entry.get("versionRange") or "*"
                                for entry in dependencies if entry.get("modId")
                                and (entry.get("mandatory") is True or entry.get("type") == "required")},
                    "breaks": {entry["modId"]: entry.get("versionRange") or "*"
                               for entry in dependencies if entry.get("modId") and entry.get("type") == "incompatible"},
                    "loaders": ["neoforge"] if descriptor.endswith("neoforge.mods.toml") else ["forge", "neoforge"],
                    "provided": {entry["modId"].lower(): mod_version(entry)
                                 for entry in declared if entry.get("modId")},
                }
    except Exception:
        return None
    return None


def _read_remote_mod_metadata(download_url: str, loader: str | None = None) -> dict | None:
    """Download a jar to a temp file just to read its fabric.mod.json, for
    conflict resolution. The bytes are discarded; nothing is installed."""
    import tempfile
    from . import net
    fd, tmp = tempfile.mkstemp(suffix=".jar")
    os.close(fd)
    try:
        net.download_to(tmp, download_url, headers=modrinth_headers(),
                        timeout=25, attempts=2)
        return read_mod_metadata(tmp, loader)
    except Exception:
        return None
    finally:
        try:
            os.remove(tmp)
        except OSError:
            pass


def _mod_ref(mod: dict) -> str | None:
    ref = (mod.get("project_id") or mod.get("slug") or "").strip()
    return ref or None


@lru_cache(maxsize=1024)
def _doctor_cached_metadata(path: str, signature: tuple, loader: str | None = None) -> tuple:
    metadata = read_mod_metadata(path, loader)
    provided = _nested_mod_metadata(path, loader=loader)
    if metadata:
        provided = {**(metadata.get("provided") or {}), **provided}
    return metadata, provided


def _doctor_metadata(path: str, loader: str | None = None) -> tuple:
    try:
        stat = os.stat(path)
        return _doctor_cached_metadata(path, (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns), loader)
    except Exception:
        return None, {}


def _doctor_local_incompatibility(metadata, mc_version, loader) -> str:
    if not metadata:
        return ""
    loaders = metadata.get("loaders")
    if loaders and loader not in loaders:
        return f"This installed build is for {'/'.join(loaders)}, not {loader}."
    predicate = (metadata.get("depends") or {}).get("minecraft")
    if predicate and isinstance(predicate, (str, list, tuple)) and not version_satisfies(mc_version, predicate):
        return f"This installed build requires Minecraft {predicate}; this instance uses {mc_version}."
    return ""


def _doctor_runtime_versions(mc_version: str, loader: str, version_id: str | None) -> dict:
    """Loader-provided dependencies, with versions from the selected profile.

    None means installed but unversioned, never a downloadable missing mod.
    """
    runtime = {"minecraft": mc_version, "java": None}
    keys = {"fabric": ("fabricloader",), "quilt": ("quilt_loader", "quilted_fabric_loader", "fabricloader"),
            "forge": ("forge",), "neoforge": ("neoforge", "forge")}.get(loader, ())
    runtime.update({key: None for key in keys})
    if not version_id:
        return runtime
    path = _instance_meta_path(version_id)
    if not path:
        return runtime
    try:
        with open(os.path.join(os.path.dirname(path), version_id + ".json"), encoding="utf-8") as source:
            profile = json.load(source)
        prefixes = {"forge": "net.minecraftforge:fmlloader:", "neoforge": "net.neoforged:neoforge:",
                    "fabric": "net.fabricmc:fabric-loader:", "quilt": "org.quiltmc:quilt-loader:"}
        for library in profile.get("libraries", []):
            name = library.get("name", "")
            prefix = prefixes.get(loader)
            if prefix and name.startswith(prefix):
                value = name[len(prefix):].split(":", 1)[0]
                if loader == "forge":
                    value = value.removeprefix(mc_version + "-")
                runtime[keys[0]] = value
        args = profile.get("arguments", {}).get("game", [])
        flag = "--fml.forgeVersion" if loader == "forge" else "--fml.neoForgeVersion"
        if loader in ("forge", "neoforge") and flag in args:
            index = args.index(flag) + 1
            if index < len(args) and isinstance(args[index], str):
                runtime[keys[0]] = args[index]
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    return runtime


def _doctor_online_checks(references, mc_version, loader, status_cb, cancel_event, *, dependencies=True) -> dict:
    results = {}
    if not references:
        return results

    def fetch(reference):
        if cancel_event is not None and cancel_event.is_set():
            return None
        try:
            file_info = get_mod_download(reference, mc_version=mc_version, loader=loader)
            required = _required_deps_cached(reference, mc_version, loader) if file_info and dependencies else []
            return {"file": file_info, "dependencies": required}
        except Exception as error:
            return {"error": str(error)}

    pool = ThreadPoolExecutor(max_workers=6, thread_name_prefix="doctor-metadata")
    futures = {pool.submit(fetch, reference): reference for reference in sorted(references)}
    try:
        for future in as_completed(futures):
            if cancel_event is not None and cancel_event.is_set():
                break
            results[futures[future]] = future.result()
            if status_cb:
                status_cb(f"Checking online metadata {len(results)}/{len(futures)}")
    finally:
        pool.shutdown(wait=not (cancel_event is not None and cancel_event.is_set()), cancel_futures=True)
    return results


def _doctor_profile_snapshot(profile_dir: str, names=None) -> tuple:
    snapshot = []
    for name in sorted(names if names is not None else os.listdir(profile_dir)):
        if name.endswith((".jar", ".jar.disabled", MOD_META_SUFFIX)):
            try:
                stat = os.stat(os.path.join(profile_dir, name))
                snapshot.append((name, stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns))
            except FileNotFoundError:
                snapshot.append((name, None))
    return tuple(snapshot)


def _request_mod_change(action: str, affected: list[dict], reason: str, *,
                        mc_version: str, loader: str, approve_cb, changes: list,
                        replacement: str | None = None, kept: str | None = None,
                        version_id: str | None = None) -> bool:
    change = {"action": action, "mc_version": mc_version, "loader": loader,
              "mods": [{"name": mod.get("display_name") or mod["filename"],
                        "filename": mod["filename"]} for mod in affected],
              "reason": reason, "replacement": replacement, "kept": kept, "approved": False}
    changes.append(change)
    if not approve_cb or not affected or any(mod.get("protected") for mod in affected):
        return False
    profile_dir = resolve_profile_dir(mc_version, loader, version_id)
    try:
        names = {mod["filename"] for mod in affected}
        names.update(name for name in (replacement, kept) if name)
        names.update({name + MOD_META_SUFFIX for name in list(names)})
        names.update({name + ".disabled" for name in list(names) if name.endswith(".jar")})
        before = _doctor_profile_snapshot(profile_dir, names)
        if any(not os.path.isfile(os.path.join(profile_dir, mod["filename"])) for mod in affected):
            return False
        change["files_snapshot"] = before
        approved = approve_cb(change) is True
        change["approved"] = approved and before == _doctor_profile_snapshot(profile_dir, names)
        if approved and not change["approved"]:
            change["reason"] += " The installed files changed while awaiting approval; run Doctor again."
    except Exception:
        change["approved"] = False
    return change["approved"]


def _doctor_disable(mc_version: str, loader: str, filename: str,
                    version_id: str | None = None) -> None:
    profile_dir = resolve_profile_dir(mc_version, loader, version_id)
    if not filename.endswith(".jar") or os.path.lexists(os.path.join(profile_dir, filename + ".disabled")):
        raise ValueError("The mod changed or already has a disabled copy. Refresh before repairing.")
    toggle_mod(mc_version, loader, filename, version_id=version_id)


def _doctor_enable(mc_version: str, loader: str, filename: str,
                   version_id: str | None = None) -> None:
    """Re-enable a `.jar.disabled` copy (the reverse of _doctor_disable)."""
    if not filename.endswith(".jar.disabled"):
        raise ValueError("Only a disabled jar can be re-enabled.")
    profile_dir = resolve_profile_dir(mc_version, loader, version_id)
    target = os.path.join(profile_dir, filename[:-len(".disabled")])
    if os.path.lexists(target):
        raise ValueError("An enabled copy already exists. Refresh before repairing.")
    toggle_mod(mc_version, loader, filename, version_id=version_id)


def _jar_read_error(path: str) -> str:
    """Why this jar cannot be read by the loader, or "" when it is fine.

    A truncated download, an HTML error page saved as .jar and a zero-byte
    file all fail the same way at launch (`invalid LOC header`, `zip END
    header not found`, ...). Catching it here lets the doctor name the file
    before the game does."""
    import zipfile
    try:
        size = os.path.getsize(path)
    except OSError as error:
        return f"the file cannot be read ({error})"
    if size == 0:
        return "the file is empty (a failed download?)"
    if not zipfile.is_zipfile(path):
        return "it is not a readable jar archive (a truncated or corrupt download?)"
    try:
        with zipfile.ZipFile(path) as archive:
            archive.infolist()
    except (OSError, zipfile.BadZipFile) as error:
        return f"the archive is corrupt ({error})"
    return ""


def _doctor_download(candidate: dict, *, mc_version: str, loader: str,
                     slug=None, project_id=None, approve_cb=None, changes=None,
                     reason="A compatible dependency needs to replace an installed build.",
                     version_id: str | None = None) -> bool:
    changes = changes if changes is not None else []
    profile_dir = resolve_profile_dir(mc_version, loader, version_id)
    filename = candidate["filename"]
    if os.path.lexists(os.path.join(profile_dir, filename)):
        return False
    copies = {item["filename"] for item in find_other_copies(profile_dir, filename, slug, project_id)}
    affected = [mod for mod in list_mods(mc_version, loader, version_id)
                if mod["filename"] in copies and mod["enabled"]]
    if affected and not _request_mod_change(
            "replace", affected, reason, mc_version=mc_version, loader=loader,
            approve_cb=approve_cb, changes=changes, replacement=filename,
            version_id=version_id):
        return False
    download_mod(candidate["url"], filename, mc_version=mc_version, loader=loader,
                 slug=slug, project_id=project_id, hashes=candidate.get("hashes"),
                 preserve_existing=True, version_id=version_id)
    for mod in affected:
        _doctor_disable(mc_version, loader, mod["filename"], version_id=version_id)
    return True


def _resolve_mod_conflict(declarer: dict, target: dict, target_id: str,
                          target_version: str, predicate, *,
                          mc_version: str | None, loader: str,
                          status_cb=None, approve_cb=None, changes=None,
                          version_id: str | None = None) -> tuple[bool, str]:
    """Try to make a `breaks` conflict go away by installing a build that no
    longer clashes. Two attempts, cheapest first:

      1. Update the TARGET (the mod being broken), e.g. a newer Iris that
         Sodium accepts. Nothing else installed changes.
      2. Otherwise REPLACE THE DECLARER with the newest build (stable builds
         preferred over betas) whose own `breaks` no longer names the
         installed target version, e.g. Sodium 0.8.14 -> 0.8.12 for Iris
         1.10.7.

    Returns (fixed, label). Never raises."""
    if status_cb:
        status_cb(f"Resolving conflict with {target.get('display_name') or 'a mod'}")

    def _install(candidate: dict, owner: dict):
        return _doctor_download(
            candidate, mc_version=mc_version, loader=loader,
            slug=owner.get("slug"), project_id=owner.get("project_id"),
            approve_cb=approve_cb, changes=changes, version_id=version_id,
            reason=f"{declarer['display_name']} conflicts with {target['display_name']} {target_version}. "
                   "Doctor found a compatible replacement; the old build will be disabled, not deleted.")

    def _candidates(versions, current_filename, *, limit=12):
        """Compatible builds only, newest first, stable before beta - and
        capped AFTER filtering, since the full list spans every Minecraft
        version and loader the project ever shipped for."""
        usable = [v for v in versions
                  if v.get("compatible") and v.get("filename") != current_filename
                  and v.get("url")]
        releases = [v for v in usable if v.get("version_type") == "release"]
        betas = [v for v in usable if v.get("version_type") != "release"]
        releases.sort(key=lambda x: x.get("date_published") or "", reverse=True)
        betas.sort(key=lambda x: x.get("date_published") or "", reverse=True)
        return (releases + betas)[:limit]

    # --- 1. update the target ------------------------------------------
    t_ref = _mod_ref(target)
    if t_ref:
        try:
            t_versions = get_mod_versions(t_ref, mc_version=mc_version,
                                          loader=loader)
        except Exception:
            t_versions = []
        for v in _candidates(t_versions, target.get("filename")):
            if not version_satisfies(v.get("version_number"), predicate):
                if not _install(v, target):
                    return False, "approval required"
                return True, f"updated {target.get('display_name')} to " \
                             f"{str(v.get('version_number')).split('+', 1)[0]}"

    # --- 2. replace the declarer ---------------------------------------
    d_ref = _mod_ref(declarer)
    if d_ref:
        try:
            d_versions = get_mod_versions(d_ref, mc_version=mc_version,
                                          loader=loader)
        except Exception:
            d_versions = []
        for v in _candidates(d_versions, declarer.get("filename")):
            meta = _read_remote_mod_metadata(v["url"], loader)
            if not meta:
                continue
            still = any(version_satisfies(target_version, p)
                        for k, p in (meta.get("breaks") or {}).items()
                        if str(k).lower() == target_id.lower())
            if not still:
                if not _install(v, declarer):
                    return False, "approval required"
                shown = str(meta.get("version") or v.get("version_number") or "")
                return True, f"replaced {declarer.get('display_name')} with " \
                             f"{shown.split('+', 1)[0]}"
    return False, ""


def mod_doctor(mc_version: str | None, loader: str | None, *,
               auto_fix: bool = True, check_online: bool = True,
               status_cb=None, approve_cb=None, cancel_event=None,
               version_id: str | None = None,
               crash_text: str | None = None) -> dict:
    """Find - and, when asked, fix - the common reasons a modpack won't load.

    Runs on every install, from a "Fix problems" action, and before a launch.
    Four checks, in order of how often each is the real cause of "the game
    crashes / the mod does nothing":

      1. **Duplicate mods.** Two copies of one mod (an update that left the
         old jar behind) is the classic crash. Extra copies are disabled only
         after approval; their files are kept so the change is reversible.
      2. **Missing required dependencies.** A mod that declares a required
         dependency (Fabric API, Sodium for Iris, ...) simply refuses to load
         without it. Each missing one is fetched.
      3. **Mods built for another loader or Minecraft version.** When the
         project has no release at all for the selected (mc_version, loader),
         the jar can never load; it is disabled rather than left to crash.
      4. **Version conflicts.** Fabric jars declare "this mod will not work
         with mod X version Y" in their own fabric.mod.json `breaks`, which
         Modrinth does not expose. Each installed jar is read locally and the
         clash is resolved by updating one side; failing that, by putting the
         declaring side on the newest build that accepts the other; failing
         that, by turning the clashing mod off so the game still launches.

    `check_online=False` skips the dependency and loader/version passes (each
    of which makes API calls per mod). Duplicate and conflict checks are
    filesystem-only for DETECTION; a conflict is still RESOLVED when auto_fix
    is on (a clash is a guaranteed crash), with a local disable as the last
    resort if no replacement can be reached.

    approve_cb(change) must return True before any existing mod is disabled
    or replaced. Without a callback, Doctor reports the proposed change and
    leaves the mod intact. Each change identifies its profile, files, and reason.

    Returns {"checked", "problems": [{kind, mod, detail, fixed, fix?}],
    "fixed", "unfixed", "changes"}. Never raises: a broken check costs a missed problem,
    never a launch. Every problem whose fix SUCCEEDED is listed in "fixed";
    one whose fix was attempted and failed (or skipped) is in "unfixed".
    """
    result = {"checked": 0, "problems": [], "fixed": [], "unfixed": [], "changes": [], "cancelled": False}
    if not mc_version or loader not in MOD_CAPABLE_LOADERS:
        return result
    try:
        require_loader_and_version(mc_version, loader, "check mods")
        profile_dir = get_profile_dir(mc_version, loader, version_id)
        mods = list_mods(mc_version, loader, version_id)
    except Exception:
        return result

    result["checked"] = len(mods)
    metadata = {mod["filename"]: _doctor_metadata(os.path.join(profile_dir, mod["filename"]), loader)
                for mod in mods if mod.get("enabled")}
    runtime_versions = _doctor_runtime_versions(mc_version, loader, version_id)

    def cancelled():
        result["cancelled"] = cancel_event is not None and cancel_event.is_set()
        return result["cancelled"]

    def _report(kind, mod, detail, fixed, fix_label="", action=""):
        entry = {"kind": kind, "mod": mod, "detail": detail, "fixed": fixed,
                 "action": action or ("repaired" if fixed else "none")}
        if fix_label:
            entry["fix"] = fix_label
        result["problems"].append(entry)
        (result["fixed"] if fixed else result["unfixed"]).append(entry)

    # --- 0. corrupt jars ----------------------------------------------------
    # A jar the zip reader cannot open is a guaranteed loader failure, and it
    # used to be invisible: read_mod_metadata returns None for it, so every
    # later pass simply skipped the file. Detect it first, disable it (rename,
    # never delete) after approval, and keep it out of the duplicate/conflict
    # passes - a broken archive has no trustworthy metadata.
    broken_files: set = set()
    for m in mods:
        if cancelled():
            return result
        if m.get("protected") or not m.get("enabled") or not m.get("filename"):
            continue
        path = os.path.join(profile_dir, m["filename"])
        error = _jar_read_error(path)
        if not error:
            continue
        broken_files.add(m["filename"])
        reason = (f"{error}, so the game's loader cannot read this mod and "
                  "will fail to start.")
        fixed, fix_label = False, ""
        if auto_fix and _request_mod_change(
                "disable", [m], reason + " The file will be kept so you can "
                "re-download or re-enable it.",
                mc_version=mc_version, loader=loader, approve_cb=approve_cb,
                changes=result["changes"], version_id=version_id):
            try:
                _doctor_disable(mc_version, loader, m["filename"],
                                version_id=version_id)
                fixed = True
                fix_label = (f"disabled it (kept as {m['filename']}.disabled; "
                             "re-download it to fix)")
            except Exception:
                log.warning("disabling corrupt mod %s failed", m["filename"],
                            exc_info=True)
        _report("mod-unreadable", m["display_name"],
                f"the jar can't be read: {error}", fixed, fix_label,
                action="disabled" if fixed else "none")

    # --- 1. duplicates -----------------------------------------------------
    # Only ENABLED jars count: a duplicate already sitting as .jar.disabled
    # was fixed by an earlier run and must not be re-reported forever.
    groups: dict = {}
    for m in mods:
        if m.get("protected") or not m.get("enabled"):
            continue
        fname = m.get("filename")
        if not fname or fname in broken_files:
            continue
        # The jar's OWN declared mod id is the only proof two files are the same
        # mod. Filename stems are a guess (two different mods can shrink to the
        # same short stem), so they are used only for jars whose metadata cannot
        # be read - never to merge two jars that both say who they are.
        jar_meta = (metadata.get(fname) or (None, {}))[0] or {}
        jar_id = str(jar_meta.get("id") or "").lower()
        slug, pid, stem = mod_identity(profile_dir, fname)
        ident = pid or slug
        if jar_id:
            key = ("jar", jar_id)
        else:
            key = ("id", ident.lower()) if ident else ("stem", stem)
        groups.setdefault(key, []).append(m)

    for key, group in groups.items():
        if cancelled():
            return result
        if len(group) < 2:
            continue
        ranked = sorted(group,
                        key=lambda mm: (not _doctor_local_incompatibility(
                            metadata.get(mm.get("filename"), (None, {}))[0], mc_version, loader),
                            _version_key(mm.get("filename") or "")),
                        reverse=True)
        winner = ranked[0]
        approved = auto_fix and _request_mod_change(
            "disable", ranked[1:],
            f"Multiple copies of {winner['display_name']} can prevent Minecraft from loading. "
            f"Keep {winner['filename']} and disable the extra copies. Nothing will be deleted.",
            mc_version=mc_version, loader=loader, approve_cb=approve_cb,
            changes=result["changes"], kept=winner["filename"],
            version_id=version_id)
        if approved:
            if status_cb:
                status_cb(f"Disabling approved extra copies of {winner['display_name']}")
            for loser in ranked[1:]:
                try:
                    _doctor_disable(mc_version, loader, loser["filename"],
                                    version_id=version_id)
                except Exception:
                    pass
        for loser in ranked[1:]:
            # Per-loser truth, not group-level: a loser is fixed only when its
            # own enabled file is actually gone now (deleted or moved to
            # .disabled). A partial failure must not be reported as success.
            still_here = os.path.isfile(
                os.path.join(profile_dir, loser.get("filename") or ""))
            fixed = bool(approved and not still_here)
            detail = (f"another copy of {winner['display_name']} is installed "
                      f"({loser['display_name']})")
            _report("duplicate", loser["display_name"], detail, fixed,
                    "disabled (can be re-enabled)" if fixed else "",
                    action="disabled" if fixed else "none")

    try:
        mods = list_mods(mc_version, loader, version_id)
    except Exception:
        pass

    incompatible_files = set()
    locally_verified = set()
    incompatible_references = {_mod_ref(mod) for mod in mods if mod.get("enabled") and not mod.get("protected")
                               and mod.get("filename") not in broken_files
                               and _mod_ref(mod) and _doctor_local_incompatibility(
                                   metadata.get(mod["filename"], (None, {}))[0], mc_version, loader)}
    alternatives = (_doctor_online_checks(incompatible_references, mc_version, loader, status_cb,
                                          cancel_event, dependencies=False)
                    if check_online and auto_fix else {})
    for mod in mods:
        if cancelled():
            return result
        if mod.get("protected") or not mod.get("enabled"):
            continue
        if mod.get("filename") in broken_files:
            continue
        meta = metadata.get(mod["filename"], (None, {}))[0]
        reason = _doctor_local_incompatibility(meta, mc_version, loader)
        if not reason:
            if meta and meta.get("loaders") and (meta.get("depends") or {}).get("minecraft"):
                locally_verified.add(mod["filename"])
            continue
        incompatible_files.add(mod["filename"])
        fixed, label = False, ""
        if auto_fix and not cancelled():
            candidate = None
            reference = _mod_ref(mod)
            if check_online and reference:
                candidate = (alternatives.get(reference) or {}).get("file")
            if candidate and candidate.get("filename") != mod["filename"]:
                try:
                    fixed = _doctor_download(candidate, mc_version=mc_version, loader=loader,
                                             slug=mod.get("slug"), project_id=mod.get("project_id"),
                                             approve_cb=approve_cb, changes=result["changes"],
                                             reason=reason, version_id=version_id)
                except Exception:
                    fixed = False
                label = "replaced with a compatible build" if fixed else ""
            elif _request_mod_change("disable", [mod], reason + " The file will be kept so you can re-enable it.",
                                     mc_version=mc_version, loader=loader,
                                     approve_cb=approve_cb, changes=result["changes"],
                                     version_id=version_id):
                try:
                    _doctor_disable(mc_version, loader, mod["filename"],
                                    version_id=version_id)
                    fixed, label = True, "disabled (can be re-enabled)"
                except Exception:
                    pass
        _report("incompatible", mod["display_name"], reason, fixed, label,
                action=("replaced" if "replaced" in label
                        else "disabled" if fixed else "none"))
    try:
        mods = list_mods(mc_version, loader, version_id)
        for mod in mods:
            if mod.get("enabled") and not mod.get("protected") and mod["filename"] not in metadata:
                metadata[mod["filename"]] = _doctor_metadata(os.path.join(profile_dir, mod["filename"]), loader)
    except Exception:
        pass

    # --- 2 + 3. dependency and loader/version checks (network) -------------
    if check_online:
        references = {_mod_ref(mod) for mod in mods if mod.get("enabled") and not mod.get("protected")
                      and mod["filename"] not in incompatible_files
                      and mod["filename"] not in locally_verified and _mod_ref(mod)}
        online = _doctor_online_checks(references, mc_version, loader, status_cb, cancel_event)
        installed_ids = installed_project_ids(mc_version, loader, version_id)
        unavailable = []
        for m in mods:
            if cancelled():
                return result
            if m.get("protected") or not m.get("enabled"):
                continue
            if (m["filename"] in incompatible_files
                    or m["filename"] in locally_verified
                    or m["filename"] in broken_files):
                continue
            ref = m.get("project_id") or m.get("slug")
            if not ref:
                continue
            lookup = online.get(ref) or {}
            if "error" in lookup:
                # A 300-mod profile used to produce one "verification
                # unavailable" entry per mod, burying every real problem under
                # a wall of identical network noise. Collect them and report a
                # single honest line after the loop.
                unavailable.append(m["display_name"])
                continue

            # 3. does any release exist for this loader + Minecraft version?
            try:
                if lookup.get("file") is None:
                    # Missing Modrinth listings cannot disprove a locally
                    # installed build, especially in CurseForge modpacks.
                    unavailable.append(m["display_name"])
                    continue
            except Exception:
                # Network/API problem, not a proven incompatibility - leave it.
                continue

            # 2. required dependencies the profile doesn't have yet.
            try:
                deps = lookup.get("dependencies") or []
            except Exception:
                deps = []
            for dep in deps:
                if cancelled():
                    return result
                dep_id = dep.get("project_id")
                if dep_id and dep_id in installed_ids:
                    continue
                dep_name = name_stem(dep.get("filename") or "a dependency")
                fixed = False
                fix_label = ""
                if auto_fix:
                    if status_cb:
                        status_cb(f"Installing {dep_name} \u2014 "
                                  f"{m['display_name']} requires it")
                    try:
                        fixed = _doctor_download(
                            dep, mc_version=mc_version, loader=loader, project_id=dep_id,
                            approve_cb=approve_cb, changes=result["changes"],
                            version_id=version_id)
                        fix_label = "installed" if fixed else ""
                        if fixed and dep_id:
                            installed_ids.add(dep_id)
                    except Exception:
                        fixed = False
                _report("missing-dependency", m["display_name"],
                        f"needs {dep_name}", fixed, fix_label,
                        action="installed" if fixed else "none")

        if unavailable:
            shown = ", ".join(sorted(unavailable)[:4])
            more = len(unavailable) - 4
            if more > 0:
                shown += f" and {more} more"
            _report("verification-unavailable",
                    f"{len(unavailable)} mod(s) couldn't be checked online",
                    f"Modrinth didn't answer for {shown}. Local checks still "
                    "ran and no mod was changed because of this; re-run Doctor "
                    "when you're online.", False, action="none")

    # --- 4. version conflicts (`breaks`) -----------------------------------
    # Read straight from the installed jars: Fabric records "this mod will not
    # work with mod X version Y" in fabric.mod.json's `breaks`, and the
    # Modrinth API does not expose it, so the jar is the only source. Local
    # file reads only - detection works offline; making the clash GO AWAY
    # needs the network, so it is only attempted when auto_fix is on.
    id_map: dict = {}
    metas: dict = {}
    for m in mods:
        if not m.get("enabled") or not m.get("filename"):
            continue
        if m["filename"] in incompatible_files or m["filename"] in broken_files:
            continue
        meta = metadata.get(m["filename"], (None, {}))[0]
        if not meta or not meta.get("id"):
            continue
        metas[m["filename"]] = meta
        key = str(meta["id"]).lower()
        prev = id_map.get(key)
        if prev is None or _cmp_versions(meta.get("version") or "",
                                         prev[1] or "") > 0:
            id_map[key] = (m, meta.get("version") or "")

    # --- 4b. UNSATISFIED `depends` (the loader hard-crash shape) -----------
    # A jar's own fabric.mod.json `depends` is what the LOADER enforces:
    # "More Culling requires cloth-config, which is missing!" is a hard
    # refuse-to-load for the whole game, not a degraded mod. The Modrinth
    # dependency pass above only knows the LATEST version's deps; the jar's
    # own declared deps are read locally from the SAME metas map the breaks
    # check just built. A dep id present in id_map with a matching version is
    # satisfied; anything else is repaired: the dep is fetched from Modrinth
    # (matched by fabric mod id).
    #
    # PROVIDED-BY-A-BUNDLED-JAR IS SATISFIED. A profile provides far more mod
    # ids than it has jar files: Fabric API ships 43 modules inside its own
    # jar, c2me bundles 20+. Reading only the top-level jars made sodium
    # ("fabric-block-getter-api-v2", "fabric-rendering-fluids-v1",
    # "fabric-resource-loader-v0"), modmenu and c2me (its own "c2me-base")
    # look like they depended on things that do not exist - and "Fix
    # problems" silently turned all three off. _nested_mod_metadata() indexes
    # what the jars actually PROVIDE.
    provided: dict = {}
    for m in mods:
        if not m.get("enabled") or not m.get("filename"):
            continue
        if m["filename"] in incompatible_files or m["filename"] in broken_files:
            continue
        try:
            bundled = metadata.get(m["filename"], (None, {}))[1]
        except Exception:
            continue
        for pid, pver in bundled.items():
            # Keep the HIGHEST bundled version of a module: several jars can
            # ship the same one (an outdated copy nested in an old mod), and
            # the loader registers only one. Taking the first would fail a
            # ">=x" predicate against a stale copy that is not actually used.
            prev = provided.get(pid)
            if prev is None or _cmp_versions(pver, prev) > 0:
                provided[pid] = pver

    # A disabled jar can satisfy a dependency with no download at all: the
    # exact build is already on disk as `.jar.disabled`. Re-enabling it is the
    # cheapest, fully reversible fix, and it is why this pass reads disabled
    # copies too (Fabric API switched off was reported as "missing" before).
    disabled_providers: dict = {}
    for m in mods:
        if m.get("enabled") or m.get("protected") or not m.get("filename"):
            continue
        if not m["filename"].endswith(".disabled"):
            continue
        disabled_meta, disabled_bundled = _doctor_metadata(
            os.path.join(profile_dir, m["filename"]), loader)
        if not disabled_meta:
            continue
        disabled_version = str(disabled_meta.get("version") or "")
        owner = str(disabled_meta.get("id") or "").lower()
        if owner:
            disabled_providers[owner] = (m, disabled_version, disabled_meta)
        for pid, pver in (disabled_bundled or {}).items():
            prev = disabled_providers.get(pid)
            if prev is None or _cmp_versions(pver or "", prev[1] or "") > 0:
                disabled_providers[pid] = (m, pver or "", disabled_meta)

    for m in mods:
        if cancelled():
            return result
        if m.get("protected") or not m.get("enabled") or not m.get("filename"):
            continue
        if m["filename"] in broken_files:
            continue
        meta = metas.get(m.get("filename"))
        if not meta:
            continue
        for dep_id, predicate in (meta.get("depends") or {}).items():
            dep_key = str(dep_id).lower()
            # Minecraft itself and the loader are always "present".
            if dep_key in runtime_versions:
                actual = runtime_versions[dep_key]
                if dep_key != "minecraft" and actual and not version_satisfies(actual, predicate):
                    _report("loader-version", m.get("display_name"),
                            f"requires {dep_id} {predicate}; this instance uses {actual}", False,
                            action="none")
                continue
            hit = id_map.get(dep_key)
            if hit is None:
                # Not an enabled mod of its own - it may still be a module
                # bundled inside one. The version comes from the nested jar so
                # a predicate like ">=2.0.0" is still checked honestly.
                bundled_version = provided.get(dep_key)
                if bundled_version is not None:
                    if version_satisfies(bundled_version or "*", predicate):
                        continue
                    _report("missing-dependency", m.get("display_name"),
                            f"needs {dep_id} {predicate} (bundled copy is "
                            f"{bundled_version or 'unversioned'})",
                            False, action="none")
                    continue
                candidate = disabled_providers.get(dep_key)
                if candidate is not None:
                    disabled_mod, disabled_version, disabled_meta = candidate
                    if not version_satisfies(disabled_version or "*", predicate):
                        _report("missing-dependency", m.get("display_name"),
                                f"needs {dep_id} {predicate} (the installed copy "
                                f"is disabled and is "
                                f"{disabled_version or 'unversioned'})",
                                False, action="none")
                        continue
                    fixed, fix_label = False, ""
                    if auto_fix:
                        approved = _request_mod_change(
                            "enable", [disabled_mod],
                            f"{m.get('display_name') or 'A mod'} requires "
                            f"{dep_id} {predicate}. The installed copy is "
                            "disabled; re-enabling it fixes the dependency "
                            "without downloading anything. You can disable it "
                            "again in Installed.",
                            mc_version=mc_version, loader=loader,
                            approve_cb=approve_cb, changes=result["changes"],
                            version_id=version_id)
                        if approved and not cancelled():
                            try:
                                _doctor_enable(mc_version, loader,
                                               disabled_mod["filename"],
                                               version_id=version_id)
                                fixed = True
                                fix_label = "re-enabled (it was disabled)"
                                enabled = dict(disabled_mod)
                                enabled["filename"] = disabled_mod["filename"][
                                    :-len(".disabled")]
                                enabled["enabled"] = True
                                metas[enabled["filename"]] = disabled_meta
                                id_map[dep_key] = (enabled, disabled_version)
                            except Exception:
                                log.warning(
                                    "re-enabling disabled dependency %s failed",
                                    disabled_mod["filename"], exc_info=True)
                    _report("missing-dependency", m.get("display_name"),
                            f"needs {dep_id} {predicate}; the installed copy is "
                            "disabled", fixed, fix_label,
                            action="enabled" if fixed else "none")
                    continue
            if hit and version_satisfies(hit[1] or "*", predicate):
                continue
            if hit and not version_satisfies(hit[1] or "*", predicate):
                # Present but the wrong version - the network conflict
                # resolver below (breaks pass) and the Modrinth dep pass
                # handle updates; here just report it, no local fix exists.
                _report("missing-dependency", m.get("display_name"),
                        f"needs {dep_id} {predicate} (found {hit[1]})",
                        False, action="none")
                continue
            dep_name = str(dep_id)
            fixed, fix_label = False, ""
            if auto_fix and check_online:
                try:
                    file_info = get_mod_download(dep_id, mc_version=mc_version,
                                                 loader=loader)
                except Exception:
                    file_info = None
                if file_info:
                    if cancelled():
                        return result
                    if status_cb:
                        status_cb(f"Installing {name_stem(file_info.get('filename') or dep_name)}"
                                  f" \u2014 {m['display_name']} requires it")
                    try:
                        fixed = _doctor_download(
                            file_info, mc_version=mc_version, loader=loader, slug=dep_id,
                            approve_cb=approve_cb, changes=result["changes"],
                            version_id=version_id)
                        fix_label = "installed" if fixed else ""
                        if fixed:
                            metas[file_info["filename"]] = {
                                "id": dep_id,
                                "version": str(file_info.get("version_number") or ""),
                                "name": dep_name, "depends": {}, "breaks": {},
                            }
                            id_map[dep_key] = (m, str(file_info.get("version_number") or ""))
                    except Exception:
                        fixed = False
            # NEVER turn the declaring mod off here. This used to be the
            # "resolvable or the game hard-fails" last resort, and it was
            # wrong in the most destructive way: an id that does not resolve
            # is NOT proof the dependency is missing. Bundled modules,
            # CurseForge-only mods, a 404, a momentary API failure and a
            # differently-named project all land in this branch, and the cost
            # of guessing wrong was silently disabling a working mod the user
            # never asked to touch (the "Fix problems disables my sodium"
            # report). Reporting it lets them decide; the game's own dependency
            # screen names the missing mod far more precisely than we can.
            _report("missing-dependency", m.get("display_name"),
                    f"requires {dep_name} ({predicate}), which isn't installed "
                    f"and couldn't be fetched automatically",
                    fixed, fix_label,
                    action="installed" if fixed else "none")

    seen_pairs: set = set()
    disabled_targets: set = set()
    for m in mods:
        if cancelled():
            return result
        if m.get("protected") or not m.get("enabled"):
            continue
        if m.get("filename") in broken_files:
            continue
        meta = metas.get(m.get("filename"))
        if not meta:
            continue
        decl_id = str(meta.get("id") or "").lower()
        for dep_id, predicate in (meta.get("breaks") or {}).items():
            dep_key = str(dep_id).lower()
            hit = id_map.get(dep_key)
            if not hit:
                continue
            target, target_version = hit
            if target.get("filename") == m.get("filename"):
                continue
            if not version_satisfies(target_version, predicate):
                continue
            pair = tuple(sorted([m.get("filename") or decl_id,
                                 target.get("filename") or dep_key]))
            if pair in seen_pairs:
                continue
            seen_pairs.add(pair)
            target_name = (metas.get(target.get("filename"), {}).get("name")
                           or target["display_name"])
            declarer_name = meta.get("name") or m["display_name"]
            target_disp = target_version.split("+", 1)[0]
            detail = f"does not work with {target_name} {target_disp}"
            fixed = False
            fix_label = ""
            if auto_fix:
                try:
                    fixed, fix_label = _resolve_mod_conflict(
                        dict(m, display_name=declarer_name),
                        dict(target, display_name=target_name),
                        dep_key, target_version, predicate,
                        mc_version=mc_version, loader=loader,
                            status_cb=status_cb, approve_cb=approve_cb, changes=result["changes"],
                            version_id=version_id)
                except Exception:
                    fixed, fix_label = False, ""
            if auto_fix and not fixed and fix_label != "approval required":
                if target.get("filename") in disabled_targets:
                    # Already turned off for an earlier declarer; don't toggle
                    # it back on.
                    fixed, fix_label = True, f"turned off {target_name}"
                else:
                    approved = _request_mod_change(
                        "disable", [target], f"{declarer_name} {meta.get('version') or ''} {detail}. "
                        f"Doctor recommends disabling {target_name} to avoid a loading failure. "
                        "Its file will be kept and you can re-enable it in Installed.",
                        mc_version=mc_version, loader=loader, approve_cb=approve_cb,
                        changes=result["changes"], version_id=version_id)
                    if approved:
                        try:
                            _doctor_disable(mc_version, loader, target["filename"],
                                            version_id=version_id)
                            fixed = True
                            fix_label = f"turned off {target_name}"
                            disabled_targets.add(target.get("filename"))
                            id_map.pop(dep_key, None)
                        except Exception:
                            fixed, fix_label = False, ""
            _report("conflict", declarer_name, detail, fixed, fix_label,
                    action=("replaced" if "replaced " in fix_label
                            else "disabled" if fixed else "none"))

    # --- 5. what the crash log itself blames -------------------------------
    # Some conflicts have no local declaration (two mixins fighting over one
    # class, a loader resolution the jar metadata cannot predict). The crash
    # log DOES name the culprit; `crash.mod_candidates` extracts only explicit
    # blame lines (never the "Fabric Mods:" table). This pass disables at most
    # ONE matched, currently-enabled mod - conservative on purpose, since
    # collateral disables are worse than a second crash that names the other
    # side.
    if crash_text and not cancelled():
        try:
            from .crash import mod_candidates
            candidates = mod_candidates(crash_text)
        except Exception:
            candidates = []
        if candidates:
            fixed_mods = {p.get("mod") for p in result["problems"]
                          if p.get("fixed")}
            enabled_now = []
            for m in mods:
                if (m.get("protected") or not m.get("enabled")
                        or not m.get("filename")):
                    continue
                if not os.path.isfile(os.path.join(profile_dir,
                                                   m["filename"])):
                    continue
                enabled_now.append(m)
            matched = None
            for candidate in candidates:
                token = candidate["name"].casefold()
                bare = token[:-4] if token.endswith(".jar") else token
                for m in enabled_now:
                    fields = {m.get("filename"), m.get("stem"),
                              m.get("display_name"), m.get("slug"),
                              m.get("project_id")}
                    meta = metadata.get(m["filename"], (None, {}))[0] or {}
                    fields.update({meta.get("id"), meta.get("name")})
                    for field in fields:
                        if not field:
                            continue
                        value = str(field).casefold()
                        if value in (token, bare) or (
                                len(bare) >= 4 and value.startswith(
                                    (bare + "-", bare + "_"))):
                            matched = (m, candidate)
                            break
                    if matched:
                        break
                if matched:
                    break
            if matched:
                m, candidate = matched
                if m["display_name"] not in fixed_mods:
                    detail = ("the crash log points at this mod: "
                              f"{candidate['reason']}")
                    fixed, fix_label = False, ""
                    approved = _request_mod_change(
                        "disable", [m],
                        f"{detail}. Disabling it keeps the file and lets "
                        "Minecraft start; re-enable it in Mods \u2192 Installed "
                        "if the crash returns.",
                        mc_version=mc_version, loader=loader,
                        approve_cb=approve_cb, changes=result["changes"],
                        version_id=version_id)
                    if approved and not cancelled():
                        try:
                            _doctor_disable(mc_version, loader,
                                            m["filename"],
                                            version_id=version_id)
                            fixed = True
                            fix_label = "disabled it (file kept)"
                        except Exception:
                            log.warning(
                                "disabling log-named mod %s failed",
                                m["filename"], exc_info=True)
                    _report("log-conflict", m["display_name"], detail,
                            fixed, fix_label,
                            action="disabled" if fixed else "none")

    return result


def installed_project_ids(mc_version: str | None, loader: str | None,
                          version_id: str | None = None) -> set:
    """The Modrinth project ids/slugs already present in a profile (from the
    meta sidecars download_mod writes). Used to skip dependencies that are
    already installed instead of re-downloading them."""
    out = set()
    try:
        for m in list_mods(mc_version, loader, version_id):
            if not m.get("enabled"):
                continue
            for key in ("project_id", "slug"):
                if m.get(key):
                    out.add(m[key])
    except Exception:
        pass
    return out


def required_dependencies(project_id_or_slug: str, mc_version: str | None,
                          loader: str = "fabric",
                          filename: str | None = None) -> list[dict]:
    """The REQUIRED Modrinth dependencies of a mod's latest version, resolved
    to downloadable files for (mc_version, loader).

    Pass `filename` when installing a specific build: the version whose
    `files[].filename` matches is used instead of the newest one, because a
    newer build can require different (or newer) dependencies than the jar the
    user actually chose. Without it the newest version is used, as before.

    Returns a list of the same shape get_mod_download returns, plus the
    dependency's project id: [{"project_id", "filename", "url", "size_kb",
    "hashes"}]. Optional/embedded/incompatible dependencies are ignored -
    only dependency_type == "required" is what makes a mod refuse to load
    without it.

    Fail-soft by design: the dependency graph is a nicety layered on top of a
    download that already worked. Any API change, missing data or network hiccup
    yields an empty list (the mod still installs; the user just installs the
    deps by hand like before), never an exception into the click handler.
    """
    try:
        params = {"loaders": json.dumps([loader]) if loader else None,
                  "game_versions": json.dumps([mc_version]) if mc_version else None}
        params = {k: v for k, v in params.items() if v}
        versions = net.get_json(
            f"{MODRINTH_API}/project/{project_id_or_slug}/version",
            params=params, headers=modrinth_headers(), timeout=10,
        )
        if not versions:
            return []
        chosen = versions[0]
        if filename:
            wanted = filename[:-len(".disabled")] if filename.endswith(".disabled") else filename
            for version in versions:
                names = [f.get("filename") for f in (version.get("files") or [])
                         if isinstance(f, dict)]
                if wanted in names:
                    chosen = version
                    break
        deps = chosen.get("dependencies") or []
        required_ids = sorted({d.get("project_id") for d in deps
                               if d.get("dependency_type") == "required"
                               and d.get("project_id")})
        out = []
        for dep_id in required_ids:
            file_info = get_mod_download(dep_id, mc_version=mc_version, loader=loader)
            if file_info:
                out.append({"project_id": dep_id, **file_info})
        return out
    except Exception:
        return []


def install_mod_with_dependencies(download_url: str, filename: str,
                                  mc_version: str | None, loader: str,
                                  slug: str | None = None,
                                  project_id: str | None = None,
                                  hashes: dict | None = None,
                                  progress_cb=None,
                                  status_cb=None,
                                  version_id: str | None = None) -> dict:
    """Downloads a mod AND every required dependency it needs that the profile
    doesn't already have.

    status_cb(text) is called with human progress ("Installing Fabric API...")
    so the UI can show what's happening between the clicks. Returns
    {"installed": [filenames], "skipped": n, "failed": [names]} - partial
    success is success for the main mod: a dependency that fails to resolve is
    reported, never raised.
    """
    require_mod_loader(mc_version, loader, "download a mod")
    # Reject a bad name before any network work: the dependency list and the
    # progress total are resolved from it, and an unsafe name must not reach
    # the profile folder through the main download either.
    filename = _safe_download_filename(filename)
    installed: list[str] = []
    skipped = 0
    failed: list[str] = []

    # Resolve the project identity BEFORE the download, then resolve the
    # dependency list - and therefore the total file count - before the first
    # byte moves. Both orderings matter for the progress bar: the count can
    # only be known once the project is known, and a batch whose size is
    # discovered *after* the main file has to re-scale mid-flight, which reads
    # as the percent falling backwards (100% -> 25%). Resolving first makes the
    # UI's percent a single clean climb from 0 to 100.
    #
    # project_id may be unknown to the caller (browse rows carry it, drag-drop
    # doesn't); resolve it from the filename's meta when needed. Reading the
    # meta *before* the install is also the correct order: for a re-dropped jar
    # the sidecar still describes the real project, whereas download_mod
    # rewrites it from the (possibly unknown) caller args.
    main_project = project_id or slug
    if not main_project:
        try:
            main_project = (_read_meta(get_profile_dir(mc_version, loader, version_id),
                                       filename) or {}).get("project_id")
        except Exception:
            main_project = None

    have = installed_project_ids(mc_version, loader, version_id)
    # The main mod is about to be installed, so its own id can't come back as a
    # dependency we still need; make sure a self/circular entry can't loop.
    for _ident in (project_id, slug, main_project):
        if _ident:
            have.add(_ident)

    pending: list[dict] = []
    if main_project:
        if status_cb:
            status_cb("Checking dependencies...")
        for dep in required_dependencies(main_project, mc_version, loader,
                                         filename=filename):
            dep_id = dep.get("project_id")
            if dep_id and dep_id in have:
                skipped += 1
                continue
            pending.append(dep)

    # Batch-aggregated progress (bugs-and-flaws follow-up): a mod like Sodium
    # pulls 2-4 dependencies, and a per-file percent that resets to 0 on every
    # dependency reads as broken. This reports progress in FILE UNITS
    # (whole files finished + the current file's fraction) across the entire
    # batch, so one mod with 3 dependencies is one 0->100 climb rather than
    # four separate 0->100 restarts. The floor is belt-and-braces: if a batch
    # ever does grow after it started, the reported value holds instead of
    # jumping back.
    _batch = {"done": 0.0, "total": float(1 + len(pending)), "floor": 0.0}

    def _batch_progress(done, total):
        if not progress_cb:
            return
        try:
            frac = (done / total) if total else 0.0
            value = _batch["done"] + frac
            if value < _batch["floor"]:
                value = _batch["floor"]
            else:
                _batch["floor"] = value
            progress_cb(value, _batch["total"])
        except Exception:
            pass

    download_mod(download_url, filename, progress_cb=_batch_progress,
                 slug=slug, mc_version=mc_version, loader=loader,
                 hashes=hashes, project_id=project_id, version_id=version_id)
    _batch["done"] = 1.0
    installed.append(filename)

    for i, dep in enumerate(pending, start=2):
        dep_id = dep.get("project_id")
        try:
            dep_name = _safe_download_filename(dep.get("filename"))
        except ValueError:
            # One unusable dependency is reported like any other failure; it
            # must not abort the main install.
            failed.append(name_stem(dep.get("filename") or "") or "a dependency")
            continue
        if status_cb:
            status_cb(f"Dependency {i}/{int(_batch['total'])}: "
                      f"{name_stem(dep_name)}")
        try:
            download_mod(dep["url"], dep_name,
                         mc_version=mc_version, loader=loader,
                         project_id=dep_id, hashes=dep.get("hashes"),
                         progress_cb=_batch_progress, version_id=version_id)
            installed.append(dep_name)
            # Count only files that actually landed: incrementing per success
            # (rather than assigning the loop index) means a failed dependency
            # leaves the bar short of 100 instead of silently claiming its
            # slot - the UI's "Installed, but failed: ..." line is what carries
            # that message.
            _batch["done"] += 1.0
            if dep_id:
                have.add(dep_id)
        except Exception:
            failed.append(name_stem(dep.get("filename") or "a dependency"))
    return {"installed": installed, "skipped": skipped, "failed": failed}


def download_mod(download_url: str, filename: str, progress_cb=None,
                  slug: str | None = None, mc_version: str | None = None,
                  loader: str | None = None, hashes: dict | None = None,
                  project_id: str | None = None,
                  superseded_cb=None, preserve_existing: bool = False,
                  version_id: str | None = None) -> str:
    """Streams a mod file into the profile folder for (mc_version, loader).
    progress_cb(downloaded, total) is called periodically if provided.
    Returns the final path. slug (when given) is recorded in a sidecar file
    so the UI/copy feature can identify the mod later.

    mc_version and loader are now REQUIRED (not just accepted) - this used
    to silently default to get_profile_dir(None, None), which resolves to
    the 'unknown-vanilla' folder instead of the profile the user actually
    has selected. A mod downloaded that way would show as installed in the
    browse view (which only checks slugs) but sync_mods_to_game() would
    never find it, so it would never load in-game - exactly the "downloads
    but doesn't do anything" symptom.

    hashes (Modrinth's {"sha512": ..., "sha1": ...} for this file, when
    known) lets this go through the same global mods store modpack installs
    use: if the exact jar is already stored from another profile/pack, it's
    linked in instead of downloaded again.

    Installing a build of a mod the profile already has REPLACES the old one
    (see supersede_older_copies). Before this, it didn't: the version lives in
    the filename, so the two copies coexisted and the game got both. That is
    the whole reason a modpack profile could end up unlaunchable after a single
    click of Download. superseded_cb(list_of_names), if given, is told what was
    moved aside so the UI can say so rather than silently mutating the list."""
    require_mod_loader(mc_version, loader, "download a mod")

    filename = _safe_download_filename(filename)
    # The modpack installer only fetches from the mrpack allowlist; a single
    # mod's URL comes from the same APIs (or a browse row) and gets the same
    # treatment, so a malicious/compromised response cannot point Cubeon at an
    # arbitrary host.
    from .modpacks import _host_allowed
    if not _host_allowed(download_url or ""):
        raise ValueError(
            f"Refusing to download '{filename}' from an untrusted host.")

    profile_dir = get_profile_dir(mc_version, loader, version_id)
    dest = os.path.join(profile_dir, filename)

    def fetch_fn(tmp_path):
        from . import net
        expected = None
        if hashes:
            for algo in ("sha512", "sha1"):
                if hashes.get(algo):
                    expected = (algo, hashes[algo])
                    break
        try:
            net.download_to(tmp_path, download_url, headers=modrinth_headers(),
                            timeout=15, expected_hash=expected,
                            progress_cb=progress_cb)
        except net.DownloadError as ex:
            raise RuntimeError(str(ex)) from ex

    global_mod_cache.get_or_fetch(dest, fetch_fn, hashes)
    # A caller usually knows only one of the two Modrinth ids: browse rows and
    # old callers pass the slug, a modpack manifest only the project id (it is
    # in the CDN URL). Record both when the other is one cached lookup away.
    # Without this, a copy written with slug-only and an older copy carrying
    # only project_id were not recognised as the same mod by
    # find_other_copies(), so the duplicate stayed behind as a disabled jar
    # forever (or worse, stayed enabled next to it).
    if (slug or project_id) and not (slug and project_id):
        try:
            details = get_mod_details(slug or project_id) or {}
            slug = slug or details.get("slug") or None
            project_id = project_id or details.get("project_id") or None
        except Exception:
            pass
    _write_meta(profile_dir, filename, slug, project_id=project_id, url=download_url)
    moved = [] if preserve_existing else supersede_older_copies(profile_dir, filename, slug, project_id)
    if moved and superseded_cb:
        superseded_cb(moved)
    return dest
