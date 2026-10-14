"""
One-pass tidy-up for the folders Cubeon owns.

WHY THIS EXISTS

`~/.cubeon_minecraft` is not just Cubeon's - it is the SAME folder name the
other launchers (TLauncher et al.) and every mod loader installer know, so it
accumulates a decade of their leftovers next to the game content Cubeon
actually needs. Over time the folder grows three kinds of rubbish:

  1. STRAY ASSET OBJECTS. A buggy asset pass once wrote Minecraft's object
     store one level too high, producing `<2-hex>/assets/objects/<2-hex>/<hash>`
     directories at the game root (63 of them on the machine this was written
     for). The objects are real - they are just in the wrong place - so they are
     MERGED into `assets/objects/`, never deleted.
  2. SUPERSEDED STORE COPIES. The global mod store names a jar for a human and
     appends `.<8-hex>` only when *different bytes* want that same name, so a
     shipped jar that gets rebuilt on every release (cubeon-client, cubeon-
     friends) lands 30 near-identical copies over a few months. Nobody wants
     those; only the newest matters, and any copy a profile still links to.
  3. FOREIGN LAUNCHER JUNK. `tlLoader/`, `TlauncherProfiles.json`,
     `TempOptifineStore-1.0.json`, `worlds-1.2.json` - none of it is Cubeon's
     and none of it is Minecraft's. Moved (never deleted) to `<game>/_legacy/`
     so the root reads as "game content", and nothing anybody might still want
     is destroyed.

DESIGN RULES

  * NEVER DELETE GAME CONTENT. `saves/`, `versions/`, `libraries/`, `assets/`,
    `mods/`, `resourcepacks/`, `shaderpacks/`, `screenshots/`, `logs/`,
    `options.txt`, `servers.dat`, worlds - untouched. The only deletions are
    (a) temp files (`.part`/`.tmp`) and (b) older copies of a jar whose newest
    copy is kept.
  * NEVER BREAK A PROFILE. A store file that any profile (or the game's own
    folders) still links to is kept, even if it looks superseded. Links are
    matched by resolved path AND by inode, so hardlinked copies count too.
  * IDEMPOTENT. Running it twice changes nothing the second time.
  * NON-FATAL. Every step is best-effort; an unwritable file is logged and
    skipped, never raised - this runs at startup.
"""
from __future__ import annotations

import logging
import os
import re
import shutil

from .paths import (
    CUBEON_HOME, GLOBAL_CONTENT_DIR, GLOBAL_MODS_DIR, MINECRAFT_DIR,
    PROFILES_DIR,
)

log = logging.getLogger(__name__)

# Where foreign-launcher leftovers go. Inside the game dir on purpose: it keeps
# "everything that was here is still here" true, so a user can go look.
LEGACY_DIR = os.path.join(MINECRAFT_DIR, "_legacy")

# Unambiguously-foreign entries. Each is MOVED, never removed. Anything Cubeon
# or the game reads/creates itself (backup/, backups/, cache/, data/, downloads/,
# runtime/, server-resource-packs/, launcher_profiles.json, usercache.json) is
# deliberately NOT here - those are either the game's or a mod's.
FOREIGN_ENTRIES = (
    "tlLoader",
    "TlauncherProfiles.json",
    "TempOptifineStore-1.0.json",
    "worlds-1.2.json",
)

# Temp files the downloaders/atomic writers leave behind on a crash.
_TEMP_RES = (
    re.compile(r"^\.fetch-.*\.part(?:\.part)?$"),
    re.compile(r"^\.atomic-.*\.tmp$"),
    re.compile(r"^.*\.tmp$"),
)

# The store's collision suffix: "<stem>.<8 hex><ext>".
_DISAMBIG = re.compile(r"\.[0-9a-fA-F]{8}(\.[A-Za-z0-9]+)$")

# A directory at the game root whose name is exactly two hex chars.
_STRAY_ASSET_DIR = re.compile(r"^[0-9a-fA-F]{2}$")

# Every store a "one real copy, profiles link into it" folder. global_content
# keeps one subfolder per content type (resourcepacks/, shaderpacks/).
def store_dirs() -> list[str]:
    dirs = [GLOBAL_MODS_DIR]
    if os.path.isdir(GLOBAL_CONTENT_DIR):
        for name in sorted(os.listdir(GLOBAL_CONTENT_DIR)):
            sub = os.path.join(GLOBAL_CONTENT_DIR, name)
            if os.path.isdir(sub):
                dirs.append(sub)
    else:
        dirs.append(GLOBAL_CONTENT_DIR)
    return dirs


def family_key(filename: str) -> str:
    """Group key for a store file: the name with its `.<8 hex>` collision
    suffix removed. `cubeon-client-1.0.0+mc1.20-1.21.11e72c1c.jar` and
    `cubeon-client-1.0.0+mc1.20-1.21.jar` share one key, so older siblings can
    be recognised as superseded."""
    return _DISAMBIG.sub(r"\1", filename)


def _is_temp(name: str) -> bool:
    return any(r.match(name) for r in _TEMP_RES)


def _referenced() -> tuple[set[str], set[tuple[int, int]]]:
    """Every path a profile (or the game's own staged folders) still points
    at, as resolved paths AND as (device, inode) pairs so a hardlink counts.
    A store file in either set must never be pruned."""
    paths: set[str] = set()
    inodes: set[tuple[int, int]] = set()
    roots = [
        PROFILES_DIR,
        os.path.join(MINECRAFT_DIR, "mods"),
        os.path.join(MINECRAFT_DIR, "resourcepacks"),
        os.path.join(MINECRAFT_DIR, "shaderpacks"),
    ]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                p = os.path.join(dirpath, fn)
                try:
                    if os.path.islink(p):
                        paths.add(os.path.realpath(p))
                    else:
                        st = os.stat(p)
                        inodes.add((st.st_dev, st.st_ino))
                except OSError:
                    continue
    return paths, inodes


def _human_mb(n: int) -> str:
    return f"{n / (1024 * 1024):.1f} MB"


# ---------------------------------------------------------------------------
# Step 1: stray asset objects
# ---------------------------------------------------------------------------
def _stray_asset_dirs() -> list[str]:
    """Game-root `<2-hex>/` dirs that hold nothing but an `assets/objects`
    tree. Anything else under that name (a version folder, a real folder) is
    left alone."""
    found = []
    try:
        names = os.listdir(MINECRAFT_DIR)
    except OSError:
        return found
    for name in names:
        p = os.path.join(MINECRAFT_DIR, name)
        if not (_STRAY_ASSET_DIR.match(name) and os.path.isdir(p)):
            continue
        children = set(os.listdir(p))
        if children == {"assets"} and os.path.isdir(os.path.join(p, "assets", "objects")):
            found.append(p)
    return found


def _merge_stray_assets(apply: bool, report: dict) -> None:
    objects_root = os.path.join(MINECRAFT_DIR, "assets", "objects")
    for stray in _stray_asset_dirs():
        objects = os.path.join(stray, "assets", "objects")
        moved = dropped = 0
        for xx in _safe_listdir(objects):
            xdir = os.path.join(objects, xx)
            if not os.path.isdir(xdir):
                continue
            for obj in _safe_listdir(xdir):
                src = os.path.join(xdir, obj)
                if not os.path.isfile(src):
                    continue
                dest_dir = os.path.join(objects_root, xx)
                dest = os.path.join(dest_dir, obj)
                if os.path.exists(dest):
                    # Already in the real store - the stray copy is redundant.
                    try:
                        if os.path.getsize(dest) == os.path.getsize(src):
                            if apply:
                                os.remove(src)
                            dropped += 1
                            continue
                    except OSError:
                        pass
                if not apply:
                    moved += 1
                    continue
                try:
                    os.makedirs(dest_dir, exist_ok=True)
                    shutil.move(src, dest)
                    moved += 1
                except OSError as ex:
                    log.warning("maintenance: couldn't move %s -> %s (%s)",
                                src, dest, ex)
        report["assets_moved"] += moved
        report["assets_dropped"] += dropped
        if apply and moved + dropped:
            # Only remove the stray tree once it holds no real files at all.
            leftover = sum(len(fs) for _d, _s, fs in os.walk(stray))
            if leftover == 0:
                try:
                    shutil.rmtree(stray)
                    report["stray_dirs_removed"] += 1
                except OSError as ex:
                    log.warning("maintenance: couldn't remove %s (%s)", stray, ex)
    report["stray_dirs"] = len(_stray_asset_dirs())


# ---------------------------------------------------------------------------
# Step 2: superseded store copies
# ---------------------------------------------------------------------------
def _prune_store_dir(store: str, referenced_paths: set[str],
                     referenced_inodes: set[tuple[int, int]],
                     apply: bool, report: dict) -> list[str]:
    """Remove older siblings of a jar family from one store. Returns the names
    that (will be / were) removed, for the hash-index cleanup."""
    if not os.path.isdir(store):
        return []
    families: dict[str, list[str]] = {}
    for name in _safe_listdir(store):
        p = os.path.join(store, name)
        if not os.path.isfile(p) or _is_temp(name):
            continue
        families.setdefault(family_key(name), []).append(name)

    removed: list[str] = []
    for _key, names in families.items():
        if len(names) < 2:
            continue
        # Keep: everything still referenced, plus the newest unreferenced copy.
        def _mtime(n: str) -> float:
            try:
                return os.path.getmtime(os.path.join(store, n))
            except OSError:
                return 0.0

        newest = max(names, key=_mtime)
        for name in names:
            p = os.path.join(store, name)
            try:
                st = os.stat(p)
                referenced = (os.path.realpath(p) in referenced_paths
                              or (st.st_dev, st.st_ino) in referenced_inodes)
            except OSError:
                referenced = False
            if referenced or name == newest:
                continue
            report["store_dupes"] += 1
            try:
                report["store_bytes"] += os.path.getsize(p)
            except OSError:
                pass
            removed.append(name)
            if apply:
                try:
                    os.remove(p)
                except OSError as ex:
                    log.warning("maintenance: couldn't remove store dupe %s (%s)", p, ex)
    return removed


def _clean_hash_index(store: str, removed_names: set[str]) -> None:
    """Drop hash-index entries whose file was pruned, so the index doesn't
    point at things that no longer exist."""
    index_path = os.path.join(store, ".hash_index.json")
    if not removed_names or not os.path.isfile(index_path):
        return
    try:
        import json
        with open(index_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        sha_map = data.get("sha256")
        if not isinstance(sha_map, dict):
            return
        kept = {sha: fn for sha, fn in sha_map.items() if fn not in removed_names}
        if len(kept) == len(sha_map):
            return
        data["sha256"] = kept
        tmp = index_path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(data, f)
        os.replace(tmp, index_path)
    except (OSError, ValueError) as ex:
        log.warning("maintenance: couldn't clean %s (%s)", index_path, ex)


# ---------------------------------------------------------------------------
# Step 3: foreign junk + temp files
# ---------------------------------------------------------------------------
def _move_foreign(apply: bool, report: dict) -> None:
    for name in FOREIGN_ENTRIES:
        src = os.path.join(MINECRAFT_DIR, name)
        if not os.path.lexists(src):
            continue
        report["legacy_moved"] += 1
        if not apply:
            continue
        dest = os.path.join(LEGACY_DIR, name)
        if os.path.lexists(dest):
            continue  # already archived on an earlier pass
        try:
            os.makedirs(LEGACY_DIR, exist_ok=True)
            shutil.move(src, dest)
        except OSError as ex:
            log.warning("maintenance: couldn't archive %s (%s)", src, ex)


def _remove_temp_files(apply: bool, report: dict) -> None:
    roots = [GLOBAL_MODS_DIR, GLOBAL_CONTENT_DIR, CUBEON_HOME,
             os.path.join(MINECRAFT_DIR, "mod_profiles")]
    for root in roots:
        if not os.path.isdir(root):
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for fn in filenames:
                if not _is_temp(fn):
                    continue
                p = os.path.join(dirpath, fn)
                report["temp_files"] += 1
                if apply:
                    try:
                        os.remove(p)
                    except OSError as ex:
                        log.warning("maintenance: couldn't remove %s (%s)", p, ex)


def _safe_listdir(path: str) -> list[str]:
    try:
        return os.listdir(path)
    except OSError:
        return []


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------
def scan() -> dict:
    """Dry-run: what organize() would do, with counts and bytes. Never touches
    disk."""
    return organize(apply=False)


def organize(apply: bool = True) -> dict:
    """Tidy Cubeon's own folders. With apply=False it only reports.

    Returns a report dict:
        stray_dirs          game-root `<2-hex>/assets/objects` dirs found
        assets_moved        asset objects merged into assets/objects/
        assets_dropped      stray objects already present in the real store
        stray_dirs_removed  stray dirs deleted once emptied
        store_dupes         superseded store files found
        store_bytes         bytes those store files occupy
        legacy_moved        foreign entries archived to _legacy/
        temp_files          .part/.tmp leftovers found
        freed_bytes         total bytes reclaimable/reclaimed
    """
    report = {
        "apply": bool(apply),
        "stray_dirs": 0,
        "assets_moved": 0,
        "assets_dropped": 0,
        "stray_dirs_removed": 0,
        "store_dupes": 0,
        "store_bytes": 0,
        "hash_index_entries": 0,
        "legacy_moved": 0,
        "temp_files": 0,
        "freed_bytes": 0,
    }
    try:
        _merge_stray_assets(apply, report)
        referenced_paths, referenced_inodes = _referenced()
        for store in store_dirs():
            removed = _prune_store_dir(store, referenced_paths,
                                       referenced_inodes, apply, report)
            if removed and apply:
                _clean_hash_index(store, set(removed))
        _move_foreign(apply, report)
        _remove_temp_files(apply, report)
    except Exception:  # never let tidy-up break a launch
        log.warning("maintenance: organize() hit an unexpected error", exc_info=True)
    report["freed_bytes"] = report["store_bytes"]
    return report


def summary(report: dict, *, applied: bool) -> str:
    """A one-line, human sentence for the status bar / log."""
    bits = []
    if report["stray_dirs"]:
        bits.append(f"{report['stray_dirs']} stray asset folders merged")
    if report["store_dupes"]:
        bits.append(f"{report['store_dupes']} duplicate jars "
                    f"({_human_mb(report['store_bytes'])} saved)")
    if report["legacy_moved"]:
        bits.append(f"{report['legacy_moved']} old launcher leftovers archived")
    if report["temp_files"]:
        bits.append(f"{report['temp_files']} temp files cleared")
    if not bits:
        return "Cubeon's files are already tidy."
    verb = "Tidied up" if applied else "Could tidy up"
    return verb + ": " + ", ".join(bits) + "."


def run_at_startup(cfg: dict | None = None) -> dict | None:
    """The startup entry point: runs a full organize pass off the UI thread,
    honouring the `auto_organize_files` config flag. Returns the report, or
    None when disabled. Never raises."""
    cfg = cfg or {}
    if not bool(cfg.get("auto_organize_files", True)):
        return None
    try:
        report = organize(apply=True)
        log.info("maintenance: %s", summary(report, applied=True))
        return report
    except Exception:  # defensive - organize() already swallows, but keep safe
        log.warning("maintenance: startup pass failed", exc_info=True)
        return None


if __name__ == "__main__":  # python -m cubeon.maintenance [--dry-run]
    import json
    import sys

    logging.basicConfig(level=logging.INFO)
    dry = "--dry-run" in sys.argv
    result = organize(apply=not dry)
    print(summary(result, applied=not dry))
    print(json.dumps(result, indent=2))
