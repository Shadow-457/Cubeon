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

# `requests` costs ~97ms to import; this module is on the startup path but
# only touches the network when the user browses/downloads. Lazy so the
# window appears sooner - `requests.get(...)` call sites are unchanged.
from .lazy import LazyModule
requests = LazyModule("requests")

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

        # Versions come back newest-first. A release occasionally has an empty
        # `files` list (or only non-primary files); blindly using versions[0]
        # would return None and make the doctor wrongly DISABLE a mod that does
        # have a downloadable build. Take the newest version that actually has
        # a file.
        latest = next((v for v in versions if v.get("files")), None)
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
    return local_cache.cached_call("mod_download", cache_key, _fetch, max_age=86400)


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
        resp = requests.get(
            f"{MODRINTH_API}/project/{ref}",
            headers=MODRINTH_HEADERS, timeout=10,
        )
        resp.raise_for_status()
        p = resp.json()

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
        "mod_details", {"project": ref}, _fetch,
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
    if not allow_network:
        cached = local_cache.get_stale("mod_versions", {"project": ref})
        return cached if isinstance(cached, list) else []

    def _fetch() -> list[dict]:
        resp = requests.get(
            f"{MODRINTH_API}/project/{ref}/version",
            headers=MODRINTH_HEADERS, timeout=10,
        )
        resp.raise_for_status()
        out = []
        for v in resp.json():
            files = v.get("files") or []
            primary = next((f for f in files if f.get("primary")),
                           files[0] if files else None)
            if not primary:
                continue
            game_versions = v.get("game_versions") or []
            loaders = v.get("loaders") or []
            compatible = True
            if mc_version and mc_version not in game_versions:
                compatible = False
            if loader and loader not in loaders:
                compatible = False
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
                "compatible": compatible,
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

    return local_cache.cached_call(
        "mod_versions", {"project": ref}, _fetch,
        max_age=6 * 3600)


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


def _satisfies_term(version: str, term: str) -> bool:
    term = term.strip()
    if term in ("", "*"):
        return True
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


def read_mod_metadata(jar_path: str) -> dict | None:
    """A jar's own declared identity: {id, version, name, depends, breaks}.

    Fabric and Quilt only (the launcher's default loaders). Reads
    `fabric.mod.json`/`quilt.mod.json` straight out of the zip with no
    download and no network. Returns None for Forge/NeoForge or an
    unreadable file - callers treat that as "no metadata", never an error.
    """
    import zipfile
    try:
        with zipfile.ZipFile(jar_path) as z:
            names = set(z.namelist())
            if "fabric.mod.json" in names:
                d = json.loads(z.read("fabric.mod.json").decode("utf-8", "replace"))
                return {
                    "id": d.get("id"),
                    "version": str(d.get("version") or ""),
                    "name": d.get("name") or d.get("id") or "",
                    "depends": d.get("depends") or {},
                    "breaks": d.get("breaks") or {},
                }
            if "quilt.mod.json" in names:
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
                }
    except Exception:
        return None
    return None


def _read_remote_mod_metadata(download_url: str) -> dict | None:
    """Download a jar to a temp file just to read its fabric.mod.json, for
    conflict resolution. The bytes are discarded; nothing is installed."""
    import tempfile
    from . import net
    fd, tmp = tempfile.mkstemp(suffix=".jar")
    os.close(fd)
    try:
        net.download_to(tmp, download_url, headers=MODRINTH_HEADERS,
                        timeout=25, attempts=2)
        return read_mod_metadata(tmp)
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


def _resolve_mod_conflict(declarer: dict, target: dict, target_id: str,
                          target_version: str, predicate, *,
                          mc_version: str | None, loader: str,
                          status_cb=None) -> tuple[bool, str]:
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
        download_mod(candidate["url"], candidate["filename"],
                     mc_version=mc_version, loader=loader,
                     slug=owner.get("slug"), project_id=owner.get("project_id"),
                     hashes=candidate.get("hashes"))

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
                _install(v, target)
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
            meta = _read_remote_mod_metadata(v["url"])
            if not meta:
                continue
            still = any(version_satisfies(target_version, p)
                        for k, p in (meta.get("breaks") or {}).items()
                        if str(k).lower() == target_id.lower())
            if not still:
                _install(v, declarer)
                shown = str(meta.get("version") or v.get("version_number") or "")
                return True, f"replaced {declarer.get('display_name')} with " \
                             f"{shown.split('+', 1)[0]}"
    return False, ""


def mod_doctor(mc_version: str | None, loader: str | None, *,
               auto_fix: bool = True, check_online: bool = True,
               status_cb=None) -> dict:
    """Find - and, when asked, fix - the common reasons a modpack won't load.

    Runs on every install, from a "Fix problems" action, and before a launch.
    Four checks, in order of how often each is the real cause of "the game
    crashes / the mod does nothing":

      1. **Duplicate mods.** Two copies of one mod (an update that left the
         old jar behind) is the classic crash. Same Modrinth id -> the older
         copy is DELETED (that is what updating means); same filename stem
         only -> the older copy is DISABLED, which is reversible.
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

    Returns {"checked", "problems": [{kind, mod, detail, fixed, fix?}],
    "fixed", "unfixed"}. Never raises: a broken check costs a missed problem,
    never a launch. Every problem whose fix SUCCEEDED is listed in "fixed";
    one whose fix was attempted and failed (or skipped) is in "unfixed".
    """
    result = {"checked": 0, "problems": [], "fixed": [], "unfixed": []}
    if not mc_version or loader not in MOD_CAPABLE_LOADERS:
        return result
    try:
        require_loader_and_version(mc_version, loader, "check mods")
        profile_dir = get_profile_dir(mc_version, loader)
        mods = list_mods(mc_version, loader)
    except Exception:
        return result

    result["checked"] = len(mods)

    def _report(kind, mod, detail, fixed, fix_label=""):
        entry = {"kind": kind, "mod": mod, "detail": detail, "fixed": fixed}
        if fix_label:
            entry["fix"] = fix_label
        result["problems"].append(entry)
        (result["fixed"] if fixed else result["unfixed"]).append(entry)

    # --- 1. duplicates -----------------------------------------------------
    # Only ENABLED jars count: a duplicate already sitting as .jar.disabled
    # was fixed by an earlier run and must not be re-reported forever.
    groups: dict = {}
    for m in mods:
        if m.get("protected") or not m.get("enabled"):
            continue
        fname = m.get("filename")
        if not fname:
            continue
        slug, pid, stem = mod_identity(profile_dir, fname)
        ident = pid or slug
        key = ("id", ident.lower()) if ident else ("stem", stem)
        groups.setdefault(key, []).append(m)

    for key, group in groups.items():
        if len(group) < 2:
            continue
        ranked = sorted(group,
                        key=lambda mm: _version_key(mm.get("filename") or ""),
                        reverse=True)
        winner = ranked[0]
        # supersede_older_copies handles EVERY other copy of the winner in one
        # call, so run it once for the group rather than once per loser - a
        # second call finds nothing left and would report the rest as unfixed.
        if auto_fix:
            if status_cb:
                status_cb(f"Removing extra copies of {winner['display_name']}")
            try:
                supersede_older_copies(
                    profile_dir, winner["filename"],
                    winner.get("slug"), winner.get("project_id"))
            except Exception:
                pass
        for loser in ranked[1:]:
            # Per-loser truth, not group-level: a loser is fixed only when its
            # own enabled file is actually gone now (deleted or moved to
            # .disabled). A partial failure must not be reported as success.
            still_here = os.path.isfile(
                os.path.join(profile_dir, loser.get("filename") or ""))
            fixed = bool(auto_fix and not still_here)
            detail = (f"another copy of {winner['display_name']} is installed "
                      f"({loser['display_name']})")
            _report("duplicate", loser["display_name"], detail, fixed,
                    "removed" if fixed else "")

    # --- 2 + 3. dependency and loader/version checks (network) -------------
    if check_online:
        installed_ids = installed_project_ids(mc_version, loader)
        for m in mods:
            if m.get("protected") or not m.get("enabled"):
                continue
            ref = m.get("project_id") or m.get("slug")
            if not ref:
                continue

            # 3. does any release exist for this loader + Minecraft version?
            try:
                if get_mod_download(ref, mc_version=mc_version, loader=loader) is None:
                    if auto_fix and status_cb:
                        status_cb(f"Turning off {m['display_name']}")
                    fixed = False
                    fix_label = ""
                    if auto_fix:
                        try:
                            toggle_mod(mc_version, loader, m["filename"])
                            fixed = True
                            fix_label = "disabled"
                        except Exception:
                            fixed = False
                    _report("incompatible", m["display_name"],
                            f"no release for {loader} {mc_version}",
                            fixed, fix_label)
                    continue  # a jar that can't load has no useful deps to add
            except Exception:
                # Network/API problem, not a proven incompatibility - leave it.
                continue

            # 2. required dependencies the profile doesn't have yet.
            try:
                deps = _required_deps_cached(ref, mc_version, loader)
            except Exception:
                deps = []
            for dep in deps:
                dep_id = dep.get("project_id")
                if dep_id and dep_id in installed_ids:
                    continue
                dep_name = name_stem(dep.get("filename") or "a dependency")
                fixed = False
                fix_label = ""
                if auto_fix:
                    if status_cb:
                        status_cb(f"Installing {dep_name}")
                    try:
                        download_mod(dep["url"], dep["filename"],
                                     mc_version=mc_version, loader=loader,
                                     project_id=dep_id, hashes=dep.get("hashes"))
                        fixed = True
                        fix_label = "installed"
                        if dep_id:
                            installed_ids.add(dep_id)
                    except Exception:
                        fixed = False
                _report("missing-dependency", m["display_name"],
                        f"needs {dep_name}", fixed, fix_label)

    # --- 4. version conflicts (`breaks`) -----------------------------------
    # Read straight from the installed jars: Fabric records "this mod will not
    # work with mod X version Y" in fabric.mod.json's `breaks`, and the
    # Modrinth API does not expose it, so the jar is the only source. Local
    # file reads only - detection works offline; making the clash GO AWAY
    # needs the network, so it is only attempted when auto_fix is on.
    id_map: dict = {}
    metas: dict = {}
    for m in mods:
        if m.get("protected") or not m.get("enabled") or not m.get("filename"):
            continue
        try:
            meta = read_mod_metadata(os.path.join(profile_dir, m["filename"]))
        except Exception:
            meta = None
        if not meta or not meta.get("id"):
            continue
        metas[m["filename"]] = meta
        key = str(meta["id"]).lower()
        prev = id_map.get(key)
        if prev is None or _cmp_versions(meta.get("version") or "",
                                         prev[1] or "") > 0:
            id_map[key] = (m, meta.get("version") or "")

    seen_pairs: set = set()
    disabled_targets: set = set()
    for m in mods:
        if m.get("protected") or not m.get("enabled"):
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
                        status_cb=status_cb)
                except Exception:
                    fixed, fix_label = False, ""
            if auto_fix and not fixed:
                # Last resort so the game ALWAYS launches: no compatible build
                # of either side exists, so the two simply cannot coexist. The
                # declarer refuses to load while the target is present, so turn
                # the target off (reversible - the user can re-enable it in the
                # Mods tab). Never delete.
                if target.get("filename") in disabled_targets:
                    # Already turned off for an earlier declarer; don't toggle
                    # it back on.
                    fixed, fix_label = True, f"turned off {target_name}"
                else:
                    if status_cb:
                        status_cb(f"Turning off {target_name} to avoid a crash")
                    try:
                        toggle_mod(mc_version, loader, target["filename"])
                        fixed = True
                        fix_label = f"turned off {target_name}"
                        disabled_targets.add(target.get("filename"))
                        id_map.pop(dep_key, None)
                    except Exception:
                        fixed, fix_label = False, ""
            _report("conflict", declarer_name, detail, fixed, fix_label)

    return result


def installed_project_ids(mc_version: str | None, loader: str | None) -> set:
    """The Modrinth project ids/slugs already present in a profile (from the
    meta sidecars download_mod writes). Used to skip dependencies that are
    already installed instead of re-downloading them."""
    out = set()
    try:
        for m in list_mods(mc_version, loader):
            for key in ("project_id", "slug"):
                if m.get(key):
                    out.add(m[key])
    except Exception:
        pass
    return out


def required_dependencies(project_id_or_slug: str, mc_version: str | None,
                          loader: str = "fabric") -> list[dict]:
    """The REQUIRED Modrinth dependencies of a mod's latest version, resolved
    to downloadable files for (mc_version, loader).

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
        resp = requests.get(
            f"{MODRINTH_API}/project/{project_id_or_slug}/version",
            params=params, headers=MODRINTH_HEADERS, timeout=10,
        )
        resp.raise_for_status()
        versions = resp.json()
        if not versions:
            return []
        deps = versions[0].get("dependencies") or []
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
                                  status_cb=None) -> dict:
    """Downloads a mod AND every required dependency it needs that the profile
    doesn't already have.

    status_cb(text) is called with human progress ("Installing Fabric API...")
    so the UI can show what's happening between the clicks. Returns
    {"installed": [filenames], "skipped": n, "failed": [names]} - partial
    success is success for the main mod: a dependency that fails to resolve is
    reported, never raised.
    """
    require_loader_and_version(mc_version, loader, "download a mod")
    installed: list[str] = []
    skipped = 0
    failed: list[str] = []

    download_mod(download_url, filename, progress_cb=progress_cb,
                 slug=slug, mc_version=mc_version, loader=loader,
                 hashes=hashes, project_id=project_id)
    installed.append(filename)

    have = installed_project_ids(mc_version, loader)
    # The main mod is installed now, so its own id can't come back as a
    # dependency we still need; make sure a self/circular entry can't loop.
    if project_id:
        have.add(project_id)
    if slug:
        have.add(slug)

    # project_id may be unknown to the caller (browse rows carry it, drag-drop
    # doesn't); resolve it from the filename's meta when needed.
    main_project = project_id
    if not main_project and slug:
        main_project = slug
    if not main_project:
        try:
            main_project = (_read_meta(get_profile_dir(mc_version, loader),
                                       filename) or {}).get("project_id")
        except Exception:
            main_project = None
    if main_project:
        have.add(main_project)

    if status_cb:
        status_cb("Checking dependencies...")
    for dep in required_dependencies(main_project or slug or filename,
                                     mc_version, loader):
        dep_id = dep.get("project_id")
        if dep_id and dep_id in have:
            skipped += 1
            continue
        if status_cb:
            status_cb(f"Installing dependency: {name_stem(dep.get('filename') or '')}")
        try:
            download_mod(dep["url"], dep["filename"], mc_version=mc_version,
                         loader=loader, project_id=dep_id,
                         hashes=dep.get("hashes"))
            installed.append(dep["filename"])
            if dep_id:
                have.add(dep_id)
        except Exception:
            failed.append(name_stem(dep.get("filename") or "a dependency"))
    return {"installed": installed, "skipped": skipped, "failed": failed}


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
