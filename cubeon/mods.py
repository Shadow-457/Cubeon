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
import uuid

import requests

from .paths import (
    APP_NAME, MODS_DIR, PROFILES_DIR,
    MOD_META_SUFFIX, PROFILE_META_FILENAME,
)
from .mod_loaders import MOD_CAPABLE_LOADERS
from . import local_cache
from . import global_mod_cache

MODRINTH_API = "https://api.modrinth.com/v2"
MODRINTH_HEADERS = {"User-Agent": f"fuckarch/{APP_NAME.lower()}/1.0"}


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


def get_profile_dir(mc_version: str | None, loader: str | None) -> str:
    key = profile_key(mc_version, loader)
    path = os.path.join(PROFILES_DIR, key)
    os.makedirs(path, exist_ok=True)
    meta_path = os.path.join(path, PROFILE_META_FILENAME)
    if not os.path.isfile(meta_path):
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"mc_version": mc_version, "loader": loader}, f)
    return path


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
            except (OSError, json.JSONDecodeError):
                pass
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
    path = _meta_path(profile_dir, filename)
    if os.path.isfile(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError):
            return None
    return None


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
    with no sidecar at all and read as "not installed" in the Mods tab."""
    meta = {}
    if slug:
        meta["slug"] = slug
    if project_id:
        meta["project_id"] = project_id
    if url:
        meta["url"] = url
    if not meta:
        return
    with open(_meta_path(profile_dir, filename), "w", encoding="utf-8") as f:
        json.dump(meta, f)


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


def _version_key(filename: str) -> tuple:
    """A sortable version for a jar filename: the longest dotted-number run in
    it, as a tuple of ints. Used only to answer "of these two copies of the
    same mod, which would Fabric have picked?" - Fabric takes the highest
    declared version, so mirroring that keeps our choice and its choice the
    same instead of introducing a third behaviour."""
    best: tuple = ()
    for token in re.findall(r"\d+(?:\.\d+)+", filename):
        parts = tuple(int(p) for p in token.split("."))
        if len(parts) > len(best) or (len(parts) == len(best) and parts > best):
            best = parts
    return best


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
# Friends mod is the in-game friends button (cubeon/cubeonfriends.py). Both
# are re-installed automatically at launch, so a user "removing" one only
# ever breaks their own skins or the Friends button - protected the same way
# the server's managed plugins are (see cubeon/server.py PROTECTED_PLUGINS).
# Matched by filename stem (without .jar/.jar.disabled, lowercase prefix) and
# by Modrinth slug for the one we download from there (kept as a literal, not
# imported from csl.py - csl imports from this module, so it can't go the
# other way; tools/test_csl.py checks the two stay in agreement).
PROTECTED_MOD_STEM_PREFIXES = ("customskinloader", "cubeon-friends")
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


def list_mods(mc_version: str | None, loader: str | None) -> list[dict]:
    """Mods installed for this specific version+loader profile only."""
    profile_dir = get_profile_dir(mc_version, loader)
    mods = []
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


def toggle_mod(mc_version: str | None, loader: str | None, filename: str) -> None:
    profile_dir = get_profile_dir(mc_version, loader)
    full = os.path.join(profile_dir, filename)
    if is_protected_mod(_read_meta(profile_dir, filename), filename):
        raise ValueError(
            "That mod is managed by Cubeon and can't be disabled. "
            "Skins/capes and the Friends button depend on it.")
    new_name = filename[:-len(".disabled")] if filename.endswith(".disabled") else filename + ".disabled"
    os.rename(full, os.path.join(profile_dir, new_name))


def delete_mod(mc_version: str | None, loader: str | None, filename: str) -> None:
    profile_dir = get_profile_dir(mc_version, loader)
    full = os.path.join(profile_dir, filename)
    if is_protected_mod(_read_meta(profile_dir, filename), filename):
        raise ValueError(
            "That mod is managed by Cubeon and can't be removed. "
            "Skins/capes and the Friends button depend on it.")
    # lexists, not exists: a profile entry may be a dangling link into the
    # global mods store (the store's copy was deleted/moved). os.path.exists
    # is False for a dead link, so removing "the file" used to do nothing -
    # leaving the link behind forever while its sidecar was deleted. lexists
    # removes the link itself (unlink doesn't need the target to exist).
    if os.path.lexists(full):
        os.remove(full)
    meta = _meta_path(profile_dir, filename)
    if os.path.exists(meta):
        os.remove(meta)


def add_mod_file(mc_version: str | None, loader: str | None, src_path: str) -> None:
    profile_dir = get_profile_dir(mc_version, loader)
    fname = os.path.basename(src_path)
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


def open_mods_folder(mc_version: str | None, loader: str | None) -> None:
    profile_dir = get_profile_dir(mc_version, loader)
    _open_folder(profile_dir)


def install_local_mod(src_path: str, mc_version: str | None, loader: str | None,
                      superseded_cb=None) -> str:
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
    require_loader_and_version(mc_version, loader, "install a mod")

    profile_dir = get_profile_dir(mc_version, loader)
    filename = os.path.basename(src_path)
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

def sync_mods_to_game(mc_version: str | None, loader: str | None) -> None:
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
    for fname in os.listdir(MODS_DIR):
        full = os.path.join(MODS_DIR, fname)
        if os.path.isfile(full) and fname.endswith(".jar"):
            os.remove(full)

    if loader not in MOD_CAPABLE_LOADERS:
        # Vanilla (or an unrecognized loader) doesn't load mods - leave MODS_DIR empty.
        return

    profile_dir = get_profile_dir(mc_version, loader)

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
        if key[1] and (key not in chosen or _version_key(fname) > _version_key(chosen[key])):
            chosen[key] = fname
        elif not key[1]:
            chosen[("file", fname)] = fname

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
            shutil.copyfile(src, dst)


def copy_mods_between_profiles(
    src_mc_version: str | None, src_loader: str | None,
    dst_mc_version: str | None, dst_loader: str | None,
) -> list[dict]:
    """Copies mods from one profile to another. For mods we recognize (have
    a stored Modrinth slug), we fetch a build that actually matches the
    destination version+loader instead of blindly copying the jar - a jar
    built for one MC version usually won't load on another.
    Returns a per-mod result list: {name, status: 'copied'|'no_match'|'skipped', detail}."""
    results = []
    for m in list_mods(src_mc_version, src_loader):
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
                hashes=file_info.get("hashes"),
            )
            results.append({"name": name, "status": "copied", "detail": file_info["version_number"]})
        except (OSError, requests.RequestException) as ex:
            results.append({"name": name, "status": "no_match", "detail": str(ex)})
    return results


# ---------------------------------------------------------------------------
# Mod discovery/download via Modrinth's public API (no auth required).
# Modrinth requires a distinctive User-Agent on every request.
# ---------------------------------------------------------------------------

def get_recommended_mods(mc_version: str | None = None, loader: str = "fabric",
                          category: str | None = None) -> list[dict]:
    """Fetches mods to show before any search. With no category picked, this
    is the small curated set of popular all-rounder mods. With a category
    picked, it instead searches Modrinth for the top mods in that category
    (scoped to the current version+loader) so switching categories actually
    changes what's shown, sorted by relevance/downloads."""
    if category:
        # Fetched well above the 5-per-page UI size so the Mods tab has
        # several real pages to page through instead of one page of results
        # and nothing behind it. 100 is Modrinth's own per-request cap.
        return search_mods("", mc_version=mc_version, loader=loader,
                            categories=[category], limit=100)

    cache_key = {"mc_version": mc_version, "loader": loader, "category": category, "slugs": RECOMMENDED_MOD_SLUGS}

    def _fetch() -> list[dict]:
        resp = requests.get(
            f"{MODRINTH_API}/projects", params={"ids": json.dumps(RECOMMENDED_MOD_SLUGS)},
            headers=MODRINTH_HEADERS, timeout=10,
        )
        resp.raise_for_status()
        projects = resp.json()

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


def search_mods(query: str, mc_version: str | None = None, loader: str = "fabric",
                 categories: list[str] | None = None, limit: int = 100) -> list[dict]:
    """Searches Modrinth for mods, optionally scoped to a specific MC version,
    loader, and one or more categories (e.g. "performance", "worldgen").
    Returns a simplified list of hit dicts ready for display."""
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
        "categories": categories or [], "limit": limit,
    }

    def _fetch() -> list[dict]:
        params = {
            "query": query, "limit": str(limit), "facets": json.dumps(facets),
            "index": modrinth_search_index(query),
        }
        resp = requests.get(f"{MODRINTH_API}/search", params=params, headers=MODRINTH_HEADERS, timeout=10)
        resp.raise_for_status()
        data = resp.json()

        results = []
        for hit in data.get("hits", []):
            results.append({
                "project_id": hit.get("project_id"),
                "slug": hit.get("slug"),
                "title": hit.get("title"),
                "description": hit.get("description"),
                "icon_url": hit.get("icon_url"),
                "downloads": hit.get("downloads", 0),
                "author": hit.get("author"),
            })
        return rank_search_hits(results, query)

    # Browse/search: 6 hours fresh (long enough that a browsing session never
    # blocks, short enough that "top downloads" stays current), then
    # stale-while-revalidate, then stale forever as the offline fallback.
    return local_cache.cached_call("search_mods", cache_key, _fetch, max_age=6 * 3600)


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
            resp = requests.get(
                f"{MODRINTH_API}/projects",
                params={"ids": json.dumps(missing)},
                headers=MODRINTH_HEADERS, timeout=10,
            )
            resp.raise_for_status()
            for project in resp.json():
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


def get_mod_download(project_id_or_slug: str, mc_version: str | None = None,
                      loader: str = "fabric") -> dict | None:
    """Finds the best matching version file for a mod, filtered by MC version
    and loader when given. Returns {filename, url, size} or None if no
    matching version exists."""
    params = {}
    if loader:
        params["loaders"] = json.dumps([loader])
    if mc_version:
        params["game_versions"] = json.dumps([mc_version])

    cache_key = {"project": project_id_or_slug, "mc_version": mc_version, "loader": loader}

    def _fetch():
        resp = requests.get(
            f"{MODRINTH_API}/project/{project_id_or_slug}/version",
            params=params, headers=MODRINTH_HEADERS, timeout=10,
        )
        resp.raise_for_status()
        versions = resp.json()
        if not versions:
            return None

        # Versions come back newest-first; take the first with a primary file
        latest = versions[0]
        files = latest.get("files", [])
        primary = next((f for f in files if f.get("primary")), files[0] if files else None)
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
    return local_cache.cached_call("mod_download", cache_key, _fetch, max_age=86400)


def download_mod(download_url: str, filename: str, progress_cb=None,
                  slug: str | None = None, mc_version: str | None = None,
                  loader: str | None = None, hashes: dict | None = None,
                  project_id: str | None = None,
                  superseded_cb=None) -> str:
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
    require_loader_and_version(mc_version, loader, "download a mod")

    profile_dir = get_profile_dir(mc_version, loader)
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
            net.download_to(tmp_path, download_url, headers=MODRINTH_HEADERS,
                            timeout=15, expected_hash=expected,
                            progress_cb=progress_cb)
        except net.DownloadError as ex:
            raise RuntimeError(str(ex)) from ex

    global_mod_cache.get_or_fetch(dest, fetch_fn, hashes)
    _write_meta(profile_dir, filename, slug, project_id=project_id, url=download_url)
    moved = supersede_older_copies(profile_dir, filename, slug, project_id)
    if moved and superseded_cb:
        superseded_cb(moved)
    return dest
