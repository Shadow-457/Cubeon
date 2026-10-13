"""Scan a folder for Minecraft content and import it into the active profile.

This is the logic behind Settings -> Import. It is deliberately free of any
Flet import so it can be unit-tested with plain temp folders.

Two jobs:

  scan_folder(root)   Walk a user-chosen folder and classify every piece of
                      Minecraft content it holds - mods, resource packs,
                      shader packs, modpacks and worlds - without ever raising
                      on a broken/locked/oddly-nested file. Every failure is
                      collected into ``errors`` and the walk continues.

  import_item(entry)  Install ONE scanned entry into the currently-active
                      (mc_version, loader) profile, reusing the exact same
                      installers the Mods/Modpacks tabs already trust.

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
import uuid
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
    """(loader, display_name, minecraft_dep) for a mod .jar.

    Fabric/Quilt jars declare themselves in fabric.mod.json / quilt.mod.json.
    Forge/NeoForge jars carry neither, so loader comes back None and we still
    surface the file - the player may well be running that loader.
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
    except Exception:
        pass
    return None, "", None


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
    hand back "modpack.zip" all the time and users rename things.
    """
    if ext == ".jar":
        loader, name, mc_dep = _read_mod_info(path)
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
            # Unrecognised archive: treat as a resource pack. The game ignores a
            # pack with no valid pack.mcmeta, so this is harmless and keeps the
            # "make every bit possible to work" promise instead of hiding files.
            return "resourcepacks", {}
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
        return f"Found {parts[0]}."
    return "Found " + ", ".join(parts[:-1]) + f" and {parts[-1]}."


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
    dest = os.path.join(SAVES_DIR, _safe_name(name))
    if os.path.exists(dest):
        dest = os.path.join(SAVES_DIR, f"{_safe_name(name)}_{uuid.uuid4().hex[:6]}")
    shutil.copytree(src_dir, dest)
    return f"Imported world '{os.path.basename(dest)}'."


def _zip_folder_to_temp(folder):
    fd, tmp = tempfile.mkstemp(suffix=".zip")
    os.close(fd)
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
    try:
        os.remove(path)
    except OSError:
        pass
