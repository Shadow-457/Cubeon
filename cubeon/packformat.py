"""
Why a resource pack shows "Incompatible" in-game, and how we prevent it.

Minecraft does NOT judge a resource pack by the version list its author ticked
on Modrinth. It reads the pack's own `pack.mcmeta`:

    {"pack": {"pack_format": 15, "supported_formats": [15, 64], ...}}

and compares that against the format the RUNNING game expects. If the game's
format is neither equal to `pack_format` nor inside `supported_formats`, the
pack is shown in red as "Incompatible" and (since 1.20.2) cannot even be moved
into the selected list. That is the whole bug behind "I installed this pack and
the game says it's incompatible".

The launcher made it worse in a way that is invisible in the UI: resource
packs and shaders live in ONE shared folder (`resourcepacks/`, `shaderpacks/`)
that every installed version reads (see cubeon/content.py). So a pack that is
perfectly compatible with the version you were browsing with is judged by every
OTHER version you launch - a 1.21.11 pack (format 75) is simply incompatible
with 1.20.6 (32).

Two facts make this fixable without guessing:

  * the format a game version expects is authoritative IN THE CLIENT JAR:
    `version.json` inside it carries
    `"pack_version": {"resource_major": 75, "resource_minor": 0, ...}`.
    So we read it from the jar the user actually has (see
    resource_format_for) and only fall back to a table for versions that
    aren't downloaded yet.
  * `supported_formats` is an author-declared RANGE, so it can be widened
    without touching a single texture: the pack keeps working for the version
    it was built for and additionally becomes acceptable to the versions the
    user actually plays. That is what repair_pack() writes.

Everything here is offline and cheap: reading `version.json` out of a jar and
`pack.mcmeta` out of a zip reads a few hundred bytes (zip central directory +
one entry), and a zip is only REWRITTEN when a pack genuinely needs the fix.
"""
import json
import os
import zipfile

from . import logging_setup  # noqa: F401  (installs the file log handlers)
from .paths import MINECRAFT_DIR

import logging

log = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# The format a game version expects
# ---------------------------------------------------------------------------

# FALLBACK ONLY - used for a version that isn't installed yet, so its client
# jar can't be read. The jar is always preferred (see resource_format_for):
# it is authoritative for the exact version AND keeps working for versions
# that didn't exist when this table was written (26.x, anything future).
#
# (resource pack format, first Minecraft version that expects it)
FORMAT_TABLE = (
    (1, "1.6.1"), (2, "1.9"), (3, "1.11"), (4, "1.13"), (5, "1.15"),
    (6, "1.16.2"), (7, "1.17"), (8, "1.18"), (9, "1.19"), (12, "1.19.3"),
    (13, "1.19.4"), (15, "1.20"), (18, "1.20.2"), (22, "1.20.3"),
    (32, "1.20.5"), (34, "1.21"), (42, "1.21.2"), (46, "1.21.4"),
    (55, "1.21.5"), (63, "1.21.6"), (64, "1.21.7"), (69, "1.21.9"),
    (75, "1.21.11"),   # confirmed from 1.21.11.jar's version.json
    (84, "26.1"),      # confirmed from 26.1.2.jar's version.json
)

# From this resource format on, the game honours `supported_formats` (the
# field was introduced with 1.20.2 = format 18). Older versions judge a pack by
# `pack_format` alone, which is why repair_pack() has to write that one too
# when an older version is in the target set.
SUPPORTED_FORMATS_SINCE = 18

# Written IN ADDITION to supported_formats for modern targets: newer pack
# schemas also accept an explicit min/max pair. Unknown keys inside the "pack"
# object are ignored by older versions, so adding them is a no-op there.
MODERN_FORMAT_KEYS_SINCE = 63

_format_cache: dict = {}
_jar_format_cache: dict = {}


def version_key(version: str | None) -> tuple | None:
    """'1.21.11' -> (1, 21, 11), '26.1' -> (26, 1). None for anything that
    isn't a plain release number (snapshots like '24w14a', '1.21-pre1', ...),
    because those can't be compared or looked up in the table."""
    if not version:
        return None
    parts = str(version).strip().split(".")
    out = []
    for part in parts:
        if not part.isdigit():
            return None
        out.append(int(part))
    return tuple(out) or None


def _pad(key: tuple, width: int) -> tuple:
    return key + (0,) * (width - len(key))


def _le(a: tuple, b: tuple) -> bool:
    width = max(len(a), len(b))
    return _pad(a, width) <= _pad(b, width)


def _int(value) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def _format_from_jar(version_id: str | None) -> int | None:
    """The resource format of an INSTALLED version, read from its client jar.

    `version.json` inside the jar is the game's own metadata, so this is exact
    for every version (including 26.x and anything released after this code was
    written) - no table to go stale. A loader profile (fabric-loader-x-1.21.11)
    has the vanilla jar copied into its own folder, which is why a plain
    "look in versions/<id>/" works for both."""
    if not version_id:
        return None
    if version_id in _jar_format_cache:
        return _jar_format_cache[version_id]

    versions_dir = os.path.join(MINECRAFT_DIR, "versions")
    candidates = []
    try:
        if os.path.isdir(versions_dir):
            for name in sorted(os.listdir(versions_dir)):
                # exact folder, or a loader profile whose name ends with the
                # version we were asked about ("fabric-loader-0.19.5-1.21.11").
                if name == version_id or name.endswith("-" + version_id):
                    candidates.append(os.path.join(versions_dir, name))
    except OSError:
        candidates = []

    fmt = None
    for folder in candidates:
        try:
            jars = sorted(f for f in os.listdir(folder)
                          if f.lower().endswith(".jar"))
        except OSError:
            continue
        for jar_name in jars:
            fmt = _read_jar_format(os.path.join(folder, jar_name))
            if fmt is not None:
                break
        if fmt is not None:
            break

    # Cache POSITIVE results only. A cached None would pin "can't tell"
    # for the whole process lifetime: a version installed (or a snapshot
    # jar appearing) after an earlier lookup would keep every later check
    # in this session blind for it - packs would silently skip verdicts.
    # A failed lookup is one listdir + table probe; not worth the risk.
    if fmt is not None:
        _jar_format_cache[version_id] = fmt
    return fmt


def _read_jar_format(jar_path: str) -> int | None:
    try:
        with zipfile.ZipFile(jar_path) as zf:
            entry = next((n for n in zf.namelist()
                          if n.lower().endswith("version.json")
                          and "/" not in n), None)
            if not entry:
                return None
            data = json.loads(zf.read(entry).decode("utf-8", "replace"))
    except (OSError, zipfile.BadZipFile, ValueError, KeyError):
        return None
    if not isinstance(data, dict):
        return None
    pack_version = data.get("pack_version")
    if isinstance(pack_version, dict):
        for key in ("resource_major", "resource"):
            value = pack_version.get(key)
            fmt = _int(value)
            if fmt is not None:
                return fmt
            if isinstance(value, dict):
                fmt = _int(value.get("major"))
                if fmt is not None:
                    return fmt
    return None


def _format_from_table(mc_version: str | None) -> int | None:
    key = version_key(mc_version)
    if key is None:
        return None
    best = None
    for fmt, first_version in FORMAT_TABLE:
        first_key = version_key(first_version)
        if first_key is None:
            continue
        if _le(first_key, key):
            best = fmt
        else:
            break
    return best


def resource_format_for(mc_version: str | None,
                        version_id: str | None = None) -> int | None:
    """The resource pack format a given game version expects, or None when it
    can't be determined (unknown/snapshot version with no client jar).

    The jar wins, the table is the fallback. Cached because the UI asks for
    this once per installed pack."""
    cache_key = (mc_version or "", version_id or "")
    if cache_key in _format_cache:
        return _format_cache[cache_key]

    fmt = None
    for candidate in (version_id, mc_version):
        fmt = _format_from_jar(candidate)
        if fmt is not None:
            break
    if fmt is None:
        fmt = _format_from_table(mc_version or version_id)

    # Same rule as _format_from_jar: never cache a miss. A None here is
    # "unknown / not installed yet", which can become a concrete format
    # the moment the version is installed - within this same session.
    if fmt is not None:
        _format_cache[cache_key] = fmt
    return fmt


def installed_resource_formats(mc_version: str | None = None,
                              version_id: str | None = None) -> list[int]:
    """Every resource format the packs in the shared folder may be judged by:
    all installed versions' formats, plus the one being launched or browsed.

    This is the heart of "bulletproof": a pack in the shared folder is read by
    EVERY installed version, so compatibility is not a property of one version
    - a pack has to satisfy all of them to never show up red in any of them."""
    formats = set()
    versions_dir = os.path.join(MINECRAFT_DIR, "versions")
    try:
        names = sorted(os.listdir(versions_dir)) if os.path.isdir(versions_dir) else []
    except OSError:
        names = []
    for name in names:
        # The folder name is either the plain version or a loader profile that
        # ends with it ("fabric-loader-0.19.5-1.21.11"); the jar inside is what
        # actually gets read.
        fmt = _format_from_jar(name)
        if fmt is None:
            fmt = _format_from_table(name.split("-")[-1])
        if fmt is not None:
            formats.add(fmt)

    for candidate in (mc_version, version_id):
        if candidate:
            fmt = resource_format_for(candidate)
            if fmt is not None:
                formats.add(fmt)
    return sorted(formats)


# ---------------------------------------------------------------------------
# Reading a pack's own metadata
# ---------------------------------------------------------------------------

# Top-level names that mean "this IS the pack root", so a zip whose only
# top-level name is one of these must NOT be treated as wrapped in a folder.
_ROOT_NAMES = {"assets", "data", "pack.mcmeta", "pack.png", "shaders",
               "resourcepack", "resourcepacks", "textures", "models",
               "font", "lang", "sounds"}


def _is_junk(name: str) -> bool:
    """OS/editor droppings that must never decide whether a zip is wrapped."""
    top = name.split("/")[0].lower()
    if top in {"__macosx", ".ds_store", "thumbs.db", "__pycache__"}:
        return True
    if name.lower().endswith((".ds_store", ".gitignore", ".gitattributes")):
        return True
    return top.startswith(".")


def _wrapper_dir(names: list) -> str | None:
    """The single folder a zip is wrapped in, if any.

    Authors sometimes upload `MyPack/assets/... MyPack/pack.mcmeta`, and the
    game only looks at the ZIP ROOT - so those packs install fine and then sit
    in the pack list unreadable. Detecting the wrapper is what lets repair
    flatten them."""
    tops = {}
    for name in names:
        if name.endswith("/") or _is_junk(name):
            continue
        tops[name.split("/")[0]] = tops.get(name.split("/")[0], 0) + 1
    if len(tops) != 1:
        return None
    only = next(iter(tops))
    return None if only.lower() in _ROOT_NAMES else only


def _pack_section(meta) -> dict:
    """The `pack` object of a pack.mcmeta. Tolerates a file that puts the keys
    at the top level instead (broken but common)."""
    if not isinstance(meta, dict):
        return {}
    section = meta.get("pack")
    if isinstance(section, dict):
        return section
    if any(k in meta for k in ("pack_format", "supported_formats")):
        return meta
    return {}


def _range_of(value) -> tuple | None:
    """`supported_formats` in any of its published shapes -> (lo, hi)."""
    if isinstance(value, (list, tuple)) and len(value) == 2:
        lo, hi = _int(value[0]), _int(value[1])
        if lo is not None and hi is not None:
            return (min(lo, hi), max(lo, hi))
        return None
    if isinstance(value, dict):
        lo = _int(value.get("min_inclusive", value.get("min")))
        hi = _int(value.get("max_inclusive", value.get("max")))
        if lo is not None and hi is not None:
            return (min(lo, hi), max(lo, hi))
        if lo is not None:
            return (lo, lo)
        return None
    single = _int(value)
    return (single, single) if single is not None else None


def _declared(section: dict) -> tuple:
    """(pack_format, range) as declared by the pack. The range also accepts the
    newer explicit min_format/max_format pair."""
    declared = _int(section.get("pack_format"))
    rng = _range_of(section.get("supported_formats"))
    if rng is None:
        lo = _int(section.get("min_format"))
        hi = _int(section.get("max_format"))
        if lo is not None and hi is not None:
            rng = (min(lo, hi), max(lo, hi))
    return declared, rng


def read_pack_meta(zip_path: str) -> tuple:
    """(meta_dict_or_None, entry_name_or_None, wrapper_dir_or_None).

    meta is None when the file is missing OR isn't valid JSON - repair_pack
    rewrites it either way, which is why the entry name is returned
    separately."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = [i.filename for i in zf.infolist() if not i.is_dir()]
            wrapper = _wrapper_dir(names)
            metas = [n for n in names
                     if n.lower().endswith("pack.mcmeta") and not _is_junk(n)]
            root = [n for n in metas if "/" not in n]
            entry = root[0] if root else (metas[0] if metas else None)
            meta = None
            if entry:
                try:
                    meta = json.loads(zf.read(entry).decode("utf-8-sig", "replace"))
                except (ValueError, KeyError):
                    meta = None
    except (OSError, zipfile.BadZipFile):
        return None, None, None
    return (meta if isinstance(meta, dict) else None), entry, wrapper


def _as_targets(targets) -> list:
    if targets is None:
        return []
    if isinstance(targets, int):
        targets = [targets]
    out = set()
    for value in targets:
        fmt = _int(value)
        if fmt is not None:
            out.add(fmt)
    return sorted(out)


def _covers(target: int, declared, rng) -> bool:
    """Does a game expecting `target` accept this pack?

    `supported_formats` is only read from 1.20.2 (format 18) onwards; older
    games judge a pack by `pack_format` alone, which is why a range covering
    the target is NOT enough there."""
    if target >= SUPPORTED_FORMATS_SINCE and rng and rng[0] <= target <= rng[1]:
        return True
    return declared == target


def pack_verdict(zip_path: str, targets) -> dict:
    """Will the game(s) expecting `targets` accept this pack?

    targets: one format or an iterable of them (see
    installed_resource_formats - a pack in the shared folder is judged by every
    installed version, not just the selected one).

    Returns {"ok", "reason", "declared", "range", "targets", "entry",
    "wrapper", "nested", "blocked"} where ok is True (accepted everywhere),
    False (something will show it as Incompatible) or None (the format of the
    target version can't be determined - a snapshot, or a version with no
    client jar; never treated as a problem to fix)."""
    target_list = _as_targets(targets)
    meta, entry, wrapper = read_pack_meta(zip_path)
    nested = bool(entry) and "/" in entry
    section = _pack_section(meta)
    declared, rng = _declared(section)

    verdict = {
        "ok": None, "reason": "", "declared": declared, "range": rng,
        "targets": target_list, "entry": entry, "wrapper": wrapper,
        "nested": nested, "blocked": [],
    }
    if not target_list:
        verdict["reason"] = ("can't tell which resource format this Minecraft "
                             "version expects")
        return verdict
    if not zipfile.is_zipfile(zip_path):
        verdict.update(ok=False, blocked=list(target_list),
                       reason="the file isn't a readable zip (a truncated "
                              "download?)")
        return verdict
    if nested:
        verdict.update(ok=False, blocked=list(target_list),
                       reason="its pack.mcmeta sits inside a folder, so the "
                              "game never reads it")
        return verdict
    if entry is None:
        verdict.update(ok=False, blocked=list(target_list),
                       reason="it has no pack.mcmeta, so the game can't "
                              "recognise it as a resource pack")
        return verdict
    if meta is None:
        verdict.update(ok=False, blocked=list(target_list),
                       reason="its pack.mcmeta isn't valid JSON")
        return verdict
    if declared is None and rng is None:
        verdict.update(ok=False, blocked=list(target_list),
                       reason="its pack.mcmeta declares no pack_format")
        return verdict

    missing = [t for t in target_list if not _covers(t, declared, rng)]
    if not missing:
        verdict.update(ok=True)
        return verdict

    verdict.update(
        ok=False, blocked=missing,
        reason=f"it's built for resource format {_pretty_declared(declared, rng)}, "
               "but this game wants " + "/".join(str(t) for t in missing))
    return verdict


def _pretty_declared(declared, rng) -> str:
    if rng and declared is not None and rng[0] != rng[1]:
        return f"{declared} ({rng[0]}-{rng[1]})"
    if rng:
        return f"{rng[0]}-{rng[1]}"
    return str(declared)


def _rewrite_zip(zip_path: str, *, wrapper: str | None = None,
                 replace: tuple | None = None,
                 add: list | None = None) -> None:
    """Rewrite a zip in place (atomically), optionally flattening a wrapper
    folder, swapping one entry's bytes, and/or adding new entries.

    Every other entry keeps its name, timestamp and compression mode. A temp
    file + os.replace means a crash mid-rewrite can never leave a half-written
    pack in the game folder for the next launch to choke on."""
    tmp_path = zip_path + ".cubeon-new"
    try:
        with zipfile.ZipFile(zip_path) as zin, \
                zipfile.ZipFile(tmp_path, "w", zipfile.ZIP_DEFLATED) as zout:
            for info in zin.infolist():
                if info.is_dir():
                    continue
                name = info.filename
                if _is_junk(name):
                    continue
                rel = name
                if wrapper and name.startswith(wrapper + "/"):
                    rel = name[len(wrapper) + 1:]
                if not rel:
                    continue
                data = replace[1] if (replace and rel == replace[0]) \
                    else zin.read(name)
                new_info = zipfile.ZipInfo(rel, date_time=info.date_time)
                new_info.compress_type = info.compress_type
                new_info.external_attr = info.external_attr
                zout.writestr(new_info, data)
            for name, data in (add or []):
                zout.writestr(name, data)
        os.replace(tmp_path, zip_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def repair_pack(zip_path: str, targets, *, dry_run: bool = False) -> dict:
    """Make a pack acceptable to every game in `targets` by widening the range
    it declares - no texture is touched.

    Four broken shapes, all fixed by the same operation:
      * a range that doesn't cover the target versions (the common case),
      * no `supported_formats` at all (a pack that only ever named one format),
      * a missing, malformed, or folder-nested `pack.mcmeta` (rewritten at the
        zip root, and the wrapper folder flattened so the game can see it),
      * the newer min_format/max_format pair, written as well for modern
        targets (unknown keys are ignored by older games).

    Returns {"changed", "reason", "before", "after"}; changed=False when the
    pack is already fine, or when the target format can't be determined."""
    verdict = pack_verdict(zip_path, targets)
    if verdict["ok"] is True:
        return {"changed": False, "reason": "already compatible"}
    target_list = verdict["targets"]
    if not target_list:
        return {"changed": False,
                "reason": verdict["reason"] or "unknown target format"}
    if not zipfile.is_zipfile(zip_path):
        # Nothing to repair: rewriting a non-zip would only destroy whatever
        # the file actually is. Reported so the user can re-download it.
        return {"changed": False, "reason": verdict["reason"]}

    meta, _entry, wrapper = read_pack_meta(zip_path)
    section = _pack_section(meta)
    declared, rng = _declared(section)

    # The widened range must still cover what the pack was built for, or the
    # repair would break the very version it was made for.
    lows = [t for t in (rng[0] if rng else declared,) if t is not None]
    highs = [t for t in (rng[1] if rng else declared,) if t is not None]
    lo = min(lows + [min(target_list)])
    hi = max(highs + [max(target_list)])

    # Games older than 1.20.2 ignore supported_formats entirely and read only
    # pack_format, so when such a version is in the target set that field has
    # to name its format.
    legacy = [t for t in target_list if t < SUPPORTED_FORMATS_SINCE]
    if legacy:
        pack_format = min(legacy)
    elif declared is not None:
        pack_format = declared
    else:
        pack_format = max(target_list)

    new_section = dict(section)
    new_section["pack_format"] = pack_format
    new_section["supported_formats"] = [lo, hi]
    if hi >= MODERN_FORMAT_KEYS_SINCE:
        new_section["min_format"] = lo
        new_section["max_format"] = hi
    if not new_section.get("description"):
        new_section["description"] = "Cubeon: format range adjusted"

    before = {"pack_format": declared, "supported_formats": rng}
    after = {"pack_format": pack_format, "supported_formats": [lo, hi]}
    if dry_run:
        return {"changed": True, "before": before, "after": after,
                "reason": verdict["reason"], "dry_run": True}

    new_meta = dict(meta) if isinstance(meta, dict) else {}
    new_meta["pack"] = new_section
    payload = json.dumps(new_meta, indent=2).encode("utf-8")
    # Where the game will actually look for it: the zip root, after any
    # wrapper folder is flattened away. Only a meta that lands exactly at the
    # root can be REPLACED - a missing one (or one buried too deep) has to be
    # written fresh, which is the whole point for packs that have none.
    rel_entry = _entry
    if wrapper and _entry and _entry.startswith(wrapper + "/"):
        rel_entry = _entry[len(wrapper) + 1:]
    if rel_entry == "pack.mcmeta":
        _rewrite_zip(zip_path, wrapper=wrapper,
                     replace=("pack.mcmeta", payload))
    else:
        _rewrite_zip(zip_path, wrapper=wrapper, add=[("pack.mcmeta", payload)])
    log.info("resource pack format repaired: %s %s -> %s (targets %s)",
             os.path.basename(zip_path), before, after, target_list)
    return {"changed": True, "before": before, "after": after,
            "reason": verdict["reason"], "flattened": bool(wrapper)}


def shader_verdict(zip_path: str) -> dict:
    """Is this actually a shader pack the game can read?

    Shader packs carry no pack_format (Iris and OptiFine decide by the
    `shaders/` folder), so the only real failure here is structure: a zip whose
    shaders live one folder down, or a file that isn't a shader pack at all
    (a resource pack dropped into shaderpacks/ is the classic)."""
    try:
        with zipfile.ZipFile(zip_path) as zf:
            names = [i.filename for i in zf.infolist() if not i.is_dir()]
    except (OSError, zipfile.BadZipFile):
        return {"ok": False, "wrapper": None,
                "reason": "the file is unreadable (not a zip)"}
    wrapper = _wrapper_dir(names)

    def relative(name: str) -> str:
        if wrapper and name.startswith(wrapper + "/"):
            return name[len(wrapper) + 1:]
        return name

    rel = [relative(n) for n in names if not _is_junk(n)]
    if any(n.startswith("shaders/") for n in rel):
        if wrapper:
            return {"ok": False, "wrapper": wrapper,
                    "reason": f"its shaders/ folder sits inside '{wrapper}/', "
                              "so the game won't find it"}
        return {"ok": True, "reason": "", "wrapper": None}
    return {"ok": False, "wrapper": wrapper,
            "reason": "it has no shaders/ folder - this looks like a resource "
                      "pack, not a shader pack"}


def flatten_pack(zip_path: str, wrapper: str | None = None) -> bool:
    """Move a wrapped pack up to the zip root (what the game actually reads).
    Returns True when the zip was rewritten."""
    if wrapper is None:
        _meta, _entry, wrapper = read_pack_meta(zip_path)
    if not wrapper:
        return False
    _rewrite_zip(zip_path, wrapper=wrapper)
    log.info("flattened wrapped pack: %s (removed '%s/')",
             os.path.basename(zip_path), wrapper)
    return True
