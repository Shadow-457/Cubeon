"""Scan a folder for Minecraft content and import it into the active profile.

This is the logic behind Settings -> Import. It is deliberately free of any
Flet import so it can be unit-tested with plain temp folders.

Three jobs:

  scan_folder(root)       Walk a user-chosen folder and classify every piece of
                          Minecraft content it holds - mods, resource packs,
                          shader packs, modpacks and worlds - without ever
                          raising on a broken/locked/oddly-nested file. Every
                          failure is collected into ``errors`` and the walk
                          continues.

  mark_installed(result)  Flag the scanned entries whose exact bytes (mods,
                          packs) or folder name (worlds) are ALREADY in the
                          active profile / saves folder, so re-importing an
                          old backup never piles up duplicate copies.

  import_item(entry)      Install ONE scanned entry into the currently-active
                          (mc_version, loader) profile, reusing the exact same
                          installers the Mods/Modpacks tabs already trust -
                          or report "already there" and do nothing.

Layout facts this module depends on (see agents/docs/module-map.md):
  * Mods and packs live in a PER-PROFILE folder, not the wiped staging
    folders - we go through install_local_mod / install_local_content which
    store bytes once and link them in.
  * Worlds live in the shared ``saves/`` folder (not per-profile).
  * A mod/pack import needs BOTH mc_version and loader; a bare None lands in
    the throwaway ``unknown-vanilla`` profile, so require_loader_and_version
    (called by the installers) turns that into a clear error.
"""

import json
import os
import shutil
import tempfile
import zipfile

from cubeon.paths import MINECRAFT_DIR

# Worlds are shared across every instance, so they land here - not per-profile.
SAVES_DIR = os.path.join(MINECRAFT_DIR, "saves")

# Our category name -> content.py's content_type key (which is singular).
CONTENT_KIND = {"resourcepacks": "resourcepack", "shaderpacks": "shader"}

# Display labels for the summary line ("Found 3 resource packs, ...").
LABELS = {
    "mods": ("mod", "mods"),
    "resourcepacks": ("resource pack", "resource packs"),
    "shaderpacks": ("shader pack", "shader packs"),
    "modpacks": ("modpack", "modpacks"),
    "worlds": ("world", "worlds"),
}

CATEGORIES = ("mods", "resourcepacks", "shaderpacks", "modpacks", "worlds")

# Never descend into these - they either hold no user content or would flood
# the scan with false-positive .jar mods (a .minecraft's libraries/ and
# versions/ are full of library jars that are NOT mods).
_SKIP_DIRS = {
    ".git", ".svn", ".hg", "node_modules", "__pycache__", ".cache",
    ".gradle", ".maven", "assets", "libraries", "versions", "logs",
    "crash-reports", "natives", ".fabric", ".quilt", ".tlauncher",
}

_ARCHIVE_EXTS = (".jar", ".zip", ".mrpack")


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _size(path):
    try:
        return os.path.getsize(path)
    except OSError:
        return None


def human_size(n):
    """'1.2 MB' - or '' for None (we don't size folders; worlds can be huge)."""
    if not n:
        return ""
    f = float(n)
    for unit in ("B", "KB", "MB", "GB"):
        if f < 1024:
            return f"{f:.0f} {unit}" if unit == "B" else f"{f:.1f} {unit}"
        f /= 1024
    return f"{f:.1f} TB"


def _safe_name(name):
    """Strip anything that could turn a world name into a path escape."""
    name = os.path.basename(str(name or "").strip())
    for ch in ("/", "\\", "\0"):
        name = name.replace(ch, "_")
    return name or "imported"


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def _read_mod_info(path):
    """(loader, display_name, minecraft_dep) for a mod .jar - or None when
    the file is NOT a mod at all.

    A jar only counts as a mod if it declares itself: fabric.mod.json /
    quilt.mod.json (Fabric/Quilt), META-INF/mods.toml or neoforge.mods.toml
    (NeoForge/Forge 1.13+), mcmod.info (legacy Forge). Everything else - a
    library jar, a random .jar out of Downloads, a corrupt file - returns
    None so the scan can skip it instead of flooding the list with junk.
    """
    try:
        with zipfile.ZipFile(path) as z:
            names = set(z.namelist())
            if "fabric.mod.json" in names:
                d = json.loads(z.read("fabric.mod.json").decode("utf-8", "replace"))
                return "fabric", (d.get("name") or d.get("id") or ""), _mc_dep(d.get("depends"))
            if "quilt.mod.json" in names:
                d = json.loads(z.read("quilt.mod.json").decode("utf-8", "replace"))
                q = d.get("quilt_loader") or {}
                return "quilt", (q.get("name") or q.get("id") or ""), _mc_dep(q.get("depends"))
            if "META-INF/neoforge.mods.toml" in names:
                return "neoforge", "", None
            if "META-INF/mods.toml" in names:
                return "forge", "", None
            if "mcmod.info" in names:
                return "forge", "", None
    except Exception:
        pass
    return None


def _mc_dep(depends):
    """The 'minecraft' entry out of a fabric/quilt depends map, as a string."""
    if isinstance(depends, dict):
        v = depends.get("minecraft")
        if isinstance(v, str):
            return v
        if isinstance(v, list) and v:
            return str(v[0])
    return None


def _classify_archive(path, ext):
    """('mods'|'resourcepacks'|'shaderpacks'|'modpacks'|None, extra) for a file.

    Decides by what is INSIDE the archive, never by extension alone - browsers
    hand back "modpack.zip" all the time and users rename things. Anything
    that isn't recognisably Minecraft content returns (None, None) and is
    silently skipped: a random zip or library jar out of Downloads is NOT
    something to offer as a "resource pack".
    """
    if ext == ".jar":
        info = _read_mod_info(path)
        if info is None:
            return None, None
        loader, name, mc_dep = info
        return "mods", {"loader": loader, "display": name, "mc_dep": mc_dep}

    try:
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
            root_names = set()
            top_folders = set()
            has_shader = False
            for n in names:
                parts = n.split("/")
                root_names.add(parts[0])
                if len(parts) > 1:
                    top_folders.add(parts[0])
                low = n.lower()
                if low.endswith((".fsh", ".vsh", ".glsl")) or low.startswith("shaders/") or "/shaders/" in low:
                    has_shader = True

            if "modrinth.index.json" in root_names or "manifest.json" in root_names:
                return "modpacks", {}
            if "pack.mcmeta" in root_names:
                return "resourcepacks", {}
            # A pack nested one folder deep: "MyPack/pack.mcmeta".
            if len(top_folders) == 1:
                only = next(iter(top_folders))
                if f"{only}/pack.mcmeta" in names:
                    return "resourcepacks", {}
            if has_shader:
                return "shaderpacks", {}
            # Nothing Minecraft about this archive - skip it.
            return None, None
    except zipfile.BadZipFile:
        return None, None
    except Exception:
        return None, None


# ---------------------------------------------------------------------------
# The walk
# ---------------------------------------------------------------------------

def _entry(path, root, kind, *, name=None, is_dir=False, size=None,
           loader=None, mc_dep=None, note=None):
    return {
        "path": path,
        "rel": os.path.relpath(path, root),
        "name": name if name is not None else os.path.splitext(os.path.basename(path))[0],
        "size": size,
        "kind": kind,
        "is_dir": is_dir,
        "loader": loader,
        "mc_dep": mc_dep,
        "note": note,
    }


def scan_folder(root, *, max_depth=8, max_files=50000):
    """Classify every piece of Minecraft content under ``root``.

    Returns {mods:[...], resourcepacks:[...], shaderpacks:[...],
    modpacks:[...], worlds:[...], root, scanned_files, errors}. Never raises:
    a folder we can't read just adds to ``errors``.
    """
    root = os.path.abspath(os.path.expanduser(str(root or "")))
    result = {c: [] for c in CATEGORIES}
    result.update({"root": root, "scanned_files": 0, "errors": []})
    if not os.path.isdir(root):
        result["errors"].append(f"Not a folder: {root}")
        return result

    errors = result["errors"]
    root_depth = root.rstrip(os.sep).count(os.sep)
    seen_real = set()

    for dirpath, dirnames, filenames in os.walk(root, topdown=True, followlinks=False):
        depth = dirpath.rstrip(os.sep).count(os.sep) - root_depth

        # Symlink-loop / duplicate-dir guard.
        try:
            rd = os.path.realpath(dirpath)
        except OSError:
            dirnames[:] = []
            continue
        if rd in seen_real:
            dirnames[:] = []
            continue
        seen_real.add(rd)

        # Depth cap + prune directories we never need to enter.
        if depth >= max_depth:
            dirnames[:] = []
        else:
            dirnames[:] = [n for n in dirnames
                           if n not in _SKIP_DIRS and not n.startswith(".")]

        # A world folder (level.dat at its root). Record and stop descending -
        # worlds hold tens of thousands of region files we never classify.
        if "level.dat" in filenames:
            result["worlds"].append(
                _entry(dirpath, root, "worlds", name=os.path.basename(dirpath.rstrip(os.sep)),
                       is_dir=True, note="world save"))
            dirnames[:] = []
            continue

        # An extracted resource pack folder (pack.mcmeta at its root).
        if "pack.mcmeta" in filenames:
            result["resourcepacks"].append(
                _entry(dirpath, root, "resourcepacks", is_dir=True,
                       note="extracted pack folder"))
            dirnames[:] = []
            continue

        # An extracted shader pack folder (a shaders/ subdir with shader files).
        shaders_sub = os.path.join(dirpath, "shaders")
        if os.path.isdir(shaders_sub) and _dir_has_shader_files(shaders_sub):
            result["shaderpacks"].append(
                _entry(dirpath, root, "shaderpacks", is_dir=True,
                       note="extracted shader folder"))
            dirnames[:] = []
            continue

        for fn in filenames:
            if result["scanned_files"] >= max_files:
                break
            ext = os.path.splitext(fn)[1].lower()
            if ext not in _ARCHIVE_EXTS:
                continue
            result["scanned_files"] += 1
            path = os.path.join(dirpath, fn)
            try:
                kind, extra = _classify_archive(path, ext)
            except Exception as ex:  # one bad file must not abort the scan
                errors.append(f"{fn}: {ex}")
                continue
            if not kind:
                continue
            extra = extra or {}
            result[kind].append(
                _entry(path, root, kind,
                       name=extra.get("display") or os.path.splitext(fn)[0],
                       size=_size(path),
                       loader=extra.get("loader"),
                       mc_dep=extra.get("mc_dep"),
                       note=extra.get("note")))

        if result["scanned_files"] >= max_files:
            errors.append("Stopped early: hit the file limit for this scan.")
            break

    for c in CATEGORIES:
        result[c].sort(key=lambda e: (e["name"] or "").lower())
    return result


def _dir_has_shader_files(d):
    try:
        for dirpath, _dirnames, files in os.walk(d):
            for fn in files:
                if fn.lower().endswith((".fsh", ".vsh", ".glsl")):
                    return True
    except OSError:
        pass
    return False


# ---------------------------------------------------------------------------
# Summary helpers (so the UI doesn't rebuild the wording)
# ---------------------------------------------------------------------------

def counts(result):
    return {c: len(result.get(c) or []) for c in CATEGORIES}


def total_found(result):
    return sum(counts(result).values())


def summary_line(result):
    """'Found 12 mods, 3 resource packs and 1 world' - or the empty message."""
    counts_ = counts(result)
    parts = []
    for c in CATEGORIES:
        n = counts_[c]
        if n:
            singular, plural = LABELS[c]
            parts.append(f"{n} {singular if n == 1 else plural}")
    if not parts:
        return "Nothing to import here."
    if len(parts) == 1:
        line = f"Found {parts[0]}."
    else:
        line = "Found " + ", ".join(parts[:-1]) + f" and {parts[-1]}."
    already = already_count(result)
    if already:
        line = line[:-1] + f" - {already} already added."
    return line


# ---------------------------------------------------------------------------
# Duplicate detection (mark_installed + the import_item guards it feeds)
# ---------------------------------------------------------------------------
#
# "Import the same backup twice" used to quietly pile up a suffixed second
# copy of every mod (foo_xxxxxx.jar), a suffixed world (MyWorld_xxxxxx/) and
# another link for every pack. Now: mods and zipped packs are compared by the
# SHA-256 of their bytes against the target profile, worlds by folder name in
# the shared saves/, and anything matching comes back flagged so the UI can
# grey it out and import_item refuses it. Modpacks are exempt: installing one
# recreates its version profile in place (an update, not a second copy).

def _sha256_file(path):
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _stem(name):
    return os.path.splitext(os.path.basename(str(name or "")))[0].lower()


def _profile_mod_hashes(mc_version, loader):
    """SHA-256 of every jar (enabled or disabled) in the target profile."""
    from cubeon import mods
    out = set()
    d = mods.get_profile_dir(mc_version, loader)
    for fn in os.listdir(d):
        if fn.endswith(".jar") or fn.endswith(".jar.disabled"):
            try:
                out.add(_sha256_file(os.path.join(d, fn)))
            except OSError:
                continue
    return out


def _profile_pack_hashes(content_type, mc_version, loader):
    """Every hash that identifies a pack already linked into the target
    profile: the SHA-256 of its CURRENT stored bytes plus the pre-repair
    "origin" hash recorded at install time (content._verify_and_fix rewrites
    packs on install, after which their own bytes no longer match the file on
    the user's disk). Symlinks, hardlinks and copied folders are all fine -
    _entry_hash follows them."""
    from cubeon import content
    out = set()
    d = content.profile_dir(content_type, mc_version, loader)
    store = content.store_dir(content_type)
    for fn in os.listdir(d):
        full = os.path.join(d, fn)
        try:
            out.add(content._entry_hash(full))
        except OSError:
            continue
        if not os.path.isdir(full):
            origin = content.origin_hash(os.path.join(store, fn))
            if origin:
                out.add(origin)
    return out


def _profile_pack_stems(content_type, mc_version, loader):
    """Filenames (stems, lowercased) of the packs linked into the profile -
    the fallback check for extracted-folder packs, whose zip-on-import bytes
    can't be hashed ahead of time."""
    from cubeon import content
    d = content.profile_dir(content_type, mc_version, loader)
    try:
        return {_stem(fn) for fn in os.listdir(d)}
    except OSError:
        return set()


def _saves_names():
    try:
        return set(os.listdir(SAVES_DIR))
    except OSError:
        return set()


def mark_installed(result, *, mc_version, loader, version_id=None):
    """Flag every scanned entry the target already has, in place.

    Sets entry["already"] to a short human reason (the UI shows it and greys
    the row out) and caches the entry's content hash on the entry as
    "_src_sha"/"_src_hash" so the import-time guard doesn't hash it twice.
    Returns how many entries got flagged. Flags are cleared on entries that
    don't match, so calling again after a target change or after imports is
    always correct. Without (mc_version, loader) every flag is cleared -
    there is no profile to compare against.
    """
    if not result:
        return 0

    mod_hashes = None
    pack_hashes = {}
    pack_stems = {}
    saves_names = None
    if mc_version and loader:
        try:
            mod_hashes = _profile_mod_hashes(mc_version, loader)
        except Exception:
            mod_hashes = set()
        try:
            saves_names = _saves_names()
        except Exception:
            saves_names = set()
        for kind, ct in CONTENT_KIND.items():
            try:
                pack_hashes[ct] = _profile_pack_hashes(ct, mc_version, loader)
                pack_stems[ct] = _profile_pack_stems(ct, mc_version, loader)
            except Exception:
                pack_hashes[ct] = set()
                pack_stems[ct] = set()

    def _flag(entries, reason, pred):
        n = 0
        for e in entries or []:
            e.pop("_src_sha", None)
            e.pop("_src_hash", None)
            if pred(e):
                e["already"] = reason
                n += 1
            else:
                e.pop("already", None)
        return n

    if mod_hashes is None:  # no target selected - nothing is "already" anything
        for c in CATEGORIES:
            for e in result.get(c) or []:
                e.pop("already", None)
                e.pop("_src_sha", None)
                e.pop("_src_hash", None)
        return 0

    marked = 0

    def _mod_pred(e):
        try:
            digest = _sha256_file(e["path"])
        except OSError:
            return False
        e["_src_sha"] = digest
        return digest in mod_hashes

    marked += _flag(result.get("mods"), "Already in this profile.", _mod_pred)

    for kind in ("resourcepacks", "shaderpacks"):
        ct = CONTENT_KIND[kind]

        def _pack_pred(e, _ct=ct):
            hashes = pack_hashes.get(_ct) or set()
            stems = pack_stems.get(_ct) or set()
            if e.get("is_dir"):
                # An extracted folder gets zipped at import time, so its bytes
                # can't be compared ahead of time - fall back to the name.
                return _stem(e["path"]) in stems
            from cubeon import content
            try:
                digest = content._entry_hash(e["path"])
            except OSError:
                return False
            e["_src_hash"] = digest
            return digest in hashes

        marked += _flag(result.get(kind), "Already in this profile.", _pack_pred)

    saves = saves_names or set()

    def _world_pred(e):
        return e["name"] in saves

    marked += _flag(result.get("worlds"), "Already in your worlds folder.",
                    _world_pred)

    # Modpacks are deliberately never flagged (see the section comment above).
    for e in result.get("modpacks") or []:
        e.pop("already", None)
    return marked


def already_count(result):
    """How many scanned entries are already in the target profile / saves."""
    return sum(1 for c in CATEGORIES
               for e in (result.get(c) or []) if e.get("already"))


# ---------------------------------------------------------------------------
# Instance targeting (the "Import to" picker)
# ---------------------------------------------------------------------------

def loader_of(version_id):
    """Best-effort loader name for a version id:
    'fabric-loader-0.16.9-1.21.11' -> 'fabric'; '1.21.11' -> 'vanilla'."""
    vid = str(version_id or "").lower()
    if "fabric" in vid:
        return "fabric"
    if "quilt" in vid:
        return "quilt"
    if "neoforge" in vid:
        return "neoforge"
    if "forge" in vid:
        return "forge"
    return "vanilla"


# Which instances can host jars built for a given loader. Quilt loads Fabric
# jars; nothing else crosses over. A mod whose loader we couldn't read
# (want=None) is allowed everywhere - the game is the final judge.
_LOADERS_OK = {
    "fabric": {"fabric", "quilt"},
    "quilt": {"quilt"},
    "forge": {"forge"},
    "neoforge": {"neoforge"},
}


def _plain_version(s):
    """True for a bare dotted version ('1.21', '1.20.1') - not a range
    expression ('>=1.20', '~1.21'), which we can't evaluate offline."""
    s = str(s or "")
    return bool(s) and s[0].isdigit() and all(c in "0123456789." for c in s)


def _mc_matches(mc_version, dep):
    """'1.21' satisfies 1.21.11 (dot-boundary prefix); '1.20.1' satisfies
    1.20.1 and 1.20.14-no such thing (dot boundary again)."""
    mc = str(mc_version or "")
    dep = str(dep or "")
    return mc == dep or mc.startswith(dep + ".")


def instance_compatibility(entry, mc_version, loader):
    """(ok, reason) - may this scanned entry go into that instance?

    Only mods can be incompatible: a loader mismatch (a Fabric jar into a
    Forge instance) or a declared Minecraft dependency the instance doesn't
    match. Packs are format-repaired at install time and worlds live in the
    shared saves/ folder, so both are compatible everywhere. Modpacks bring
    their own loader+version, so they too are compatible everywhere."""
    if entry.get("kind") == "mods":
        want = entry.get("loader")
        # Vanilla (or any non-mod loader) can't load mods at all, so pointing
        # a mod jar at a vanilla instance would silently land it in a profile
        # the game never reads. Refuse with an actionable reason instead.
        from .mod_loaders import MOD_CAPABLE_LOADERS
        if loader and loader not in MOD_CAPABLE_LOADERS:
            return False, (f"vanilla can't load mods - switch the loader on the "
                           f"Play tab and press Play to add one")
        if want and loader and loader not in _LOADERS_OK.get(want, {want}):
            return False, f"{want} mod - needs a {want} instance"
        dep = entry.get("mc_dep")
        if dep and mc_version and _plain_version(dep) and not _mc_matches(mc_version, dep):
            return False, f"needs Minecraft {dep}"
    return True, ""


def already_in_profile(entry, mc_version, loader):
    """Is this exact entry already in that instance (or saves/, which every
    instance shares, for worlds)? The same checks mark_installed uses, one
    entry at a time - the Import-to picker calls it once per instance row."""
    kind = entry.get("kind")
    if not mc_version or not loader:
        return False
    if kind == "mods":
        try:
            digest = entry.get("_src_sha") or _sha256_file(entry["path"])
        except OSError:
            return False
        try:
            return digest in _profile_mod_hashes(mc_version, loader)
        except Exception:
            return False
    if kind in ("resourcepacks", "shaderpacks"):
        from cubeon import content
        ct = CONTENT_KIND[kind]
        try:
            if entry.get("is_dir"):
                return _stem(entry["path"]) in _profile_pack_stems(
                    ct, mc_version, loader)
            digest = entry.get("_src_hash") or content._entry_hash(entry["path"])
        except OSError:
            return False
        try:
            return digest in _profile_pack_hashes(ct, mc_version, loader)
        except Exception:
            return False
    if kind == "worlds":
        return entry["name"] in _saves_names()
    return False  # modpacks install/update in place - never a duplicate


# ---------------------------------------------------------------------------
# Import
# ---------------------------------------------------------------------------

def import_item(entry, *, mc_version, loader, version_id=None,
                status_cb=None, max_cb=None):
    """Install one scanned entry into the (mc_version, loader) profile.

    Returns a human message. Raises ValueError on a clear, user-fixable
    problem (e.g. no version selected yet).
    """
    kind = entry["kind"]
    path = entry["path"]

    if kind == "mods":
        from cubeon import mods
        # Vanilla can't load mods. Without this guard the jar would land in
        # the vanilla profile folder the game never reads, and the import
        # would look like it silently did nothing.
        from .mod_loaders import MOD_CAPABLE_LOADERS
        if loader and loader not in MOD_CAPABLE_LOADERS:
            raise ValueError(
                "Vanilla can't load mods - switch the loader on the Play tab "
                "(e.g. Fabric) and press Play to add it, then import again.")
        # Exact-bytes guard: re-importing a jar that's already linked into
        # this profile would only create a foo_xxxxxx.jar twin (install_local_
        # mod suffixes on filename clashes), so refuse instead.
        digest = entry.get("_src_sha")
        if digest is None:
            try:
                digest = _sha256_file(path)
            except OSError:
                digest = None
        if digest:
            pdir = mods.get_profile_dir(mc_version, loader)
            try:
                names = os.listdir(pdir)
            except OSError:
                names = []
            for fn in names:
                if not (fn.endswith(".jar") or fn.endswith(".jar.disabled")):
                    continue
                try:
                    if _sha256_file(os.path.join(pdir, fn)) == digest:
                        return f"'{entry['name']}' is already in this profile."
                except OSError:
                    continue
        moved = []
        name = mods.install_local_mod(
            path, mc_version, loader,
            superseded_cb=lambda m: moved.extend(m if isinstance(m, list) else [m]))
        msg = f"Added mod '{name}'."
        if moved:
            msg += f" Replaced {len(moved)} older build(s)."
        return msg

    if kind in ("resourcepacks", "shaderpacks"):
        from cubeon import content
        ct = CONTENT_KIND[kind]
        label = content.CONTENT_TYPES[ct]["label"].lower()
        # Already-there guard, for ZIPS AND FOLDER PACKS alike.
        #
        # Zips compare exact bytes: the profile's stored bytes plus their
        # install-time origin hashes, because _verify_and_fix may have
        # rewritten the stored copy.
        #
        # Folders can't - they are re-zipped at import time, so the bytes
        # hashed here would never match the stored zip - so they fall back to
        # the pack's name (stem), which is stable across that re-zip. This
        # matters because the ACTIVE target has no gate of its own: the Import-
        # to picker refuses an instance the pack is installed in, but
        # _import_one relies on the scan-time badge, which a rescan or a
        # direct call can be stale about. Without it, re-adding a folder pack
        # reported "Added ..." for work _store_entry had quietly reused.
        if entry.get("is_dir"):
            dup = _stem(path) in _profile_pack_stems(ct, mc_version, loader)
        else:
            digest = entry.get("_src_hash")
            if digest is None:
                try:
                    digest = content._entry_hash(path)
                except OSError:
                    digest = None
            dup = False
            if digest:
                try:
                    known = _profile_pack_hashes(ct, mc_version, loader)
                except Exception:
                    known = set()
                dup = digest in known
        if dup:
            return f"'{entry['name']}' is already in this profile."
        tmp = None
        try:
            src = path
            if entry.get("is_dir"):
                # install_local_content only accepts a .zip, so zip an extracted
                # pack folder up first (pack.mcmeta ends up at the archive root,
                # which is where the game looks for it).
                tmp = _zip_folder_to_temp(path)
                src = tmp
            name = content.install_local_content(ct, src, mc_version, version_id, loader)
        finally:
            if tmp:
                _cleanup(tmp)
        return f"Added {label} '{name}'."

    if kind == "modpacks":
        from cubeon import modpacks
        meta = modpacks.install_modpack_from_file(
            path, status_cb=status_cb, max_cb=max_cb)
        vid = (meta or {}).get("version_id")
        nm = (meta or {}).get("name") or entry["name"]
        return f"Installed modpack '{nm}'" + (f" as version {vid}." if vid else ".")

    if kind == "worlds":
        return _import_world(path, entry["name"])

    raise ValueError(f"Unknown content kind '{kind}'.")


def _import_world(src_dir, name):
    src = os.path.realpath(src_dir)
    saves = os.path.realpath(SAVES_DIR)
    # Never "import" a world onto itself (the user pointed us at saves/).
    try:
        if src == saves or src.startswith(saves + os.sep):
            return f"'{name}' is already in your worlds folder."
    except OSError:
        pass
    os.makedirs(SAVES_DIR, exist_ok=True)
    dest_name = _safe_name(name)
    dest = os.path.join(SAVES_DIR, dest_name)
    # A world with this name is already there: importing again would just
    # create a MyWorld_xxxxxx twin, so treat it as the duplicate it is. (The
    # rare "different world, same name" case is fixed by renaming the source
    # folder first - better than silently accumulating copies.)
    if os.path.exists(dest):
        return f"'{name}' is already in your worlds folder."
    shutil.copytree(src_dir, dest)
    return f"Imported world '{dest_name}'."


def _zip_folder_to_temp(folder):
    # Zip an extracted pack folder under the folder's OWN name, so the stored
    # pack is named "<folder>.zip" instead of a random temp name.
    #
    # install_local_content derives the stored pack's filename from the SOURCE
    # basename (content._store_entry), and that filename is the pack's identity
    # for dedup: the two folder checks (mark_installed / already_in_profile)
    # compare the SOURCE folder's stem against the profile's pack stems. A bare
    # mkstemp() named every import "tmpAbC123.zip", so the profile held
    # "tmpAbC123" while the scan showed a folder called "Faithful-32x" - the
    # stems could never match, and every rescan offered to import the same pack
    # again, piling another random-named copy into both the store and the
    # profile.
    #
    # mkstemp always appends a random token, so it cannot hand back the exact
    # name needed. Stage inside a private temp directory instead, where the
    # name is ours to choose and cannot collide with anything else in the
    # system temp dir. _cleanup removes the whole directory.
    staging = tempfile.mkdtemp(prefix="cubeon-pack-")
    stem = _safe_name(os.path.splitext(os.path.basename(folder.rstrip("/\\")))[0])
    tmp = os.path.join(staging, f"{stem}.zip")
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as zf:
            for dirpath, _dirnames, filenames in os.walk(folder):
                for fn in filenames:
                    fp = os.path.join(dirpath, fn)
                    arc = os.path.relpath(fp, folder)
                    try:
                        zf.write(fp, arc)
                    except OSError:
                        continue
    except Exception:
        _cleanup(tmp)
        raise
    return tmp


def _cleanup(path):
    # Remove the staged zip and the private directory _zip_folder_to_temp put
    # it in. rmtree on the parent would also do, but only the parent is ours -
    # a stray caller passing an ordinary file must not take a directory with it.
    try:
        os.remove(path)
    except OSError:
        pass
    parent = os.path.dirname(os.path.abspath(path))
    if os.path.basename(parent).startswith("cubeon-pack-"):
        shutil.rmtree(parent, ignore_errors=True)
