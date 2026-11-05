"""
Resource pack and shader management: Modrinth search/download plus CRUD over
the two game folders (.minecraft/resourcepacks, .minecraft/shaderpacks).

--- How a pack is stored (same model as mods) ---

A resource pack or shader belongs to an INSTANCE, exactly like a mod does:

    <game dir>/global_content/resourcepacks/Faithful.zip   <- one real copy
    <profiles>/<version>-<loader>/resourcepacks/Faithful.zip <- a symlink
    <game dir>/resourcepacks/Faithful.zip                  <- staged at launch

Three locations, three jobs, and every one of them is load-bearing:

  - the GLOBAL STORE holds the only real bytes, named for a human so the
    folder is browsable (mirrors global_mod_cache's mod store);
  - the PROFILE holds a link, so "which packs does this instance have" is
    answered by a folder listing and two instances can differ;
  - the GAME FOLDER is staging. Minecraft only ever reads this one folder, so
    sync_content_to_game() rebuilds it from the active profile right before
    the game starts - that rebuild is what makes packs and shaders follow the
    instance switch.

--- Why this is no longer "simpler than mods.py" ---

It used to be: packs and shaders went straight into the shared game folder
with no profiles, because that folder is what the game reads and the game
picks which packs are active. That is true, but it had a consequence users
hit immediately - installing a second modpack mixed its resource packs and
shaders into the first one's, and the two could never be separated again,
because *one* folder cannot describe two instances. Modpacks made it worse:
two packs shipping a file at the same relative path silently overwrote each
other (see modpacks._extract_overrides).

Mods already solved exactly this with the store + link + launch-sync pattern,
so packs now use it too. Two deliberate differences from mods:

  - Enable/disable controls profile availability by renaming to `.disabled`.
    Launch staging excludes disabled entries. Selecting an available pack
    stays in the game's own menus; the launcher does not rewrite that choice.
  - Hand-dropped files are ADOPTED, never deleted. A .zip sitting in the game
    folder that Cubeon didn't stage is moved into the store and linked into
    the profile being played (see _adopt_foreign_entries), so a user who
    installed a pack by hand - or by dragging it in from the file manager -
    keeps it, and it follows that instance from then on.

Shaders additionally need Iris (Fabric) or OptiFine installed to have any
effect in-game, but the .zip still just lives in shaderpacks/ either way, so
that's the mod-loader layer's concern, not this module's.
"""
import json
import base64
import io
from functools import lru_cache
import os
import shutil
import tempfile
import threading
import zipfile

from .atomicio import write_json
from .file_safety import child_directory, download_name, entry_name, inside, replace_directory

from .paths import (APP_NAME, CUBEON_HOME, GLOBAL_CONTENT_DIR, RESOURCEPACKS_DIR,
                    SHADERPACKS_DIR, modrinth_headers)
from . import global_mod_cache
from . import local_cache
from . import net
from . import packformat
# Reuse the exact same Modrinth browse-sort / relevance-banding logic the Mods
# tab uses, so "browse" and search behave identically across content types
# instead of drifting into two subtly different rankings.
from .mods import MODRINTH_API, modrinth_search_index, rank_search_hits, _select_download
# The per-instance plumbing is shared with mods on purpose: same profile
# folders (get_profile_dir), same link-into-place engine, same loud failure
# when a caller forgets which profile it is acting on.
from .mods import get_profile_dir, resolve_profile_dir, require_loader_and_version
from .mod_loaders import MOD_CAPABLE_LOADERS

import logging

log = logging.getLogger(__name__)


# Everything that differs between a resource pack and a shader, in one table,
# so every function below stays a single code path keyed by content_type
# instead of forking into near-duplicate resourcepack/shader variants.
#
#   dir          -> the game folder this content type is STAGED into (the one
#                   folder Minecraft reads; rebuilt per launch)
#   subdir       -> the per-type folder name inside the global store and the
#                   profile (same name in both, so the two are comparable)
#   project_type -> Modrinth's own project_type facet value
#   exts         -> accepted local-file extensions (both ship as .zip)
#   categories   -> (facet_id, label) quick-filter chips for this type; the
#                   ids are real Modrinth category slugs for this project_type
CONTENT_TYPES = {
    "resourcepack": {
        "dir": RESOURCEPACKS_DIR,
        "subdir": "resourcepacks",
        "project_type": "resourcepack",
        "label": "Resource pack",
        "label_plural": "Resource packs",
        "exts": (".zip",),
        "categories": [
            ("", "All"),
            ("realistic", "Realistic"),
            ("simplistic", "Simplistic"),
            ("vanilla-like", "Vanilla-like"),
            ("themed", "Themed"),
            ("decoration", "Decoration"),
            ("modded", "Modded"),
            ("utility", "Utility"),
        ],
    },
    "shader": {
        "dir": SHADERPACKS_DIR,
        "subdir": "shaderpacks",
        "project_type": "shader",
        "label": "Shader",
        "label_plural": "Shaders",
        "exts": (".zip",),
        "categories": [
            ("", "All"),
            ("realistic", "Realistic"),
            ("semi-realistic", "Semi-realistic"),
            ("fantasy", "Fantasy"),
            ("vanilla-like", "Vanilla-like"),
            ("cartoon", "Cartoon"),
            ("atmosphere", "Atmosphere"),
            ("reflections", "Reflections"),
        ],
    },
}


def _cfg(content_type: str) -> dict:
    try:
        return CONTENT_TYPES[content_type]
    except KeyError:
        raise ValueError(f"Unknown content type: {content_type!r}") from None


def content_dir(content_type: str) -> str:
    """The shared game folder this content type installs into, created on
    demand so a fresh install (or a user who wiped .minecraft) never hits a
    missing-folder error on first use."""
    d = _cfg(content_type)["dir"]
    os.makedirs(d, exist_ok=True)
    return d


def category_choices(content_type: str) -> list:
    """(facet_id, label) pairs for this type's quick-filter chips."""
    return _cfg(content_type)["categories"]


# ---------------------------------------------------------------------------
# The three locations: store (real bytes) / profile (links) / game (staging)
# ---------------------------------------------------------------------------

# Marker written INSIDE a staging folder, listing the entries Cubeon put there.
# Its whole job is to make "which files may this sync delete?" a recorded fact
# instead of a guess: anything not in the list was not staged by us, so it is
# adopted (never removed).
_STAGED_MARKER = ".cubeon-staged.json"

# The store's collision tag: a pack stored as "Faithful.zip" that collides
# with DIFFERENT bytes of the same name becomes "<stem>.<8 of sha256>.zip", so
# neither file overwrites the other (the promise the mod store also makes).
_COLLISION_TAG = 8


def store_dir(content_type: str) -> str:
    """The global, human-browsable store this content type shares with every
    profile - the packs/shaders twin of GLOBAL_MODS_DIR."""
    d = child_directory(GLOBAL_CONTENT_DIR, _cfg(content_type)["subdir"])
    os.makedirs(d, exist_ok=True)
    return d


def resolve_content_profile_dir(content_type: str, mc_version: str | None,
                                loader: str | None,
                                version_id: str | None = None) -> str:
    require_loader_and_version(mc_version, loader, "read content")
    root = resolve_profile_dir(mc_version, loader, version_id)
    return child_directory(root, _cfg(content_type)["subdir"])


def profile_dir(content_type: str, mc_version: str | None,
                loader: str | None,
                version_id: str | None = None) -> str:
    """Where THIS instance's packs of this type live (a folder of links).

    Fails loudly on a missing version/loader rather than resolving to the
    'unknown-vanilla' folder, for the same reason mods.require_loader_and_version
    exists: a silently wrong profile is how packs end up "installed" somewhere
    the game never looks."""
    require_loader_and_version(
        mc_version, loader, f"manage {_cfg(content_type)['label_plural'].lower()}")
    d = child_directory(get_profile_dir(mc_version, loader, version_id),
                        _cfg(content_type)["subdir"])
    os.makedirs(d, exist_ok=True)
    return d


def _sha256(path: str) -> str:
    import hashlib
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _dir_sha256(path: str) -> str:
    """Stable content hash for an unpacked (folder) pack: every file's relative
    path + bytes. Only feeds the name-collision check, so 'stable' matters
    more than 'cryptographic'."""
    import hashlib
    h = hashlib.sha256()
    for dirpath, dirnames, filenames in os.walk(path):
        for child in (*dirnames, *filenames):
            full = os.path.join(dirpath, child)
            if os.path.islink(full) and not inside(path, full):
                raise ValueError('This pack contains a link outside its folder.')
        dirnames.sort()
        for fname in sorted(filenames):
            full = os.path.join(dirpath, fname)
            h.update(os.path.relpath(full, path).encode("utf-8", "replace"))
            try:
                with open(full, "rb") as f:
                    for chunk in iter(lambda: f.read(1 << 16), b""):
                        h.update(chunk)
            except OSError:
                continue
    return h.hexdigest()


def _entry_hash(path: str) -> str:
    return _dir_sha256(path) if os.path.isdir(path) else _sha256(path)


def _origin_path(stored_path: str) -> str:
    """Sidecar next to a STORED pack holding the SHA-256 of the bytes the user
    handed us. Dot-prefixed so it stays invisible to every pack lister (they
    skip dotfiles) and to file managers by default."""
    return os.path.join(os.path.dirname(stored_path),
                        "." + os.path.basename(stored_path) + ".origin")


def _write_origin_hash(stored_path: str, src_hash: str) -> None:
    """Records the source-bytes hash for a stored pack. Needed because
    _verify_and_fix REWRITES the stored copy (pack.mcmeta repair, shader
    flattening), after which its own hash no longer matches the file on the
    user's disk - and Import's duplicate detection (cubeon.importer.
    mark_installed) must still recognise "that's the pack I already added".
    Best-effort: a sidecar we can't write just makes detection fall back to
    comparing current bytes."""
    try:
        with open(_origin_path(stored_path), "w", encoding="ascii") as f:
            f.write(src_hash)
    except OSError:
        pass


def origin_hash(stored_path: str) -> str | None:
    """The source-bytes SHA-256 recorded at install time, or None."""
    try:
        with open(_origin_path(stored_path), "r", encoding="ascii") as f:
            h = f.read().strip()
        return h or None
    except (OSError, ValueError):
        return None


_STORE_LOCK = threading.RLock()


def _store_entry(content_type: str, src_path: str,
                 human_name: str | None = None) -> str:
    # A shared store name must never be replaced between collision detection
    # and publication. Downloads themselves remain parallel.
    with _STORE_LOCK:
        return _store_entry_locked(content_type, src_path, human_name)


def _store_entry_locked(content_type, src_path, human_name=None):
    """Puts a real pack file/folder into the global store, returning the stored
    path. Reuses the stored copy when the exact same bytes are already there
    (hashed first, so nothing is copied just to find that out)."""
    store = store_dir(content_type)
    name = (human_name or os.path.basename(src_path.rstrip("/\\"))).strip()
    if not name:
        name = _cfg(content_type)["subdir"] + ".zip"
    entry_name(name)
    src_hash = _entry_hash(src_path)

    candidate = os.path.join(store, name)
    if os.path.lexists(candidate):
        try:
            if inside(store, candidate) and _entry_hash(candidate) == src_hash:
                return candidate          # exact-match reuse, no copy
        except OSError:
            pass
        stem, ext = os.path.splitext(name)
        candidate = os.path.join(store, f"{stem}.{src_hash[:_COLLISION_TAG]}{ext}")

    # A truncated hash suffix is not proof that the bytes match. A preexisting
    # collision (or dangling link) gets another name, never reused blindly.
    stem, ext = os.path.splitext(name)
    suffix = 0
    while os.path.lexists(candidate):
        try:
            if inside(store, candidate) and _entry_hash(candidate) == src_hash:
                return candidate
        except OSError:
            pass
        suffix += 1
        candidate = os.path.join(store, f"{stem}.{src_hash}.{suffix}{ext}")

    if os.path.isdir(src_path):
        tmp = tempfile.mkdtemp(prefix=".store-", dir=store)
    else:
        fd, tmp = tempfile.mkstemp(prefix=".store-", dir=store)
        os.close(fd)
    try:
        if os.path.isdir(src_path):
            shutil.copytree(src_path, tmp, dirs_exist_ok=True)
        else:
            shutil.copyfile(src_path, tmp)
        os.replace(tmp, candidate)
    finally:
        if os.path.isdir(tmp):
            shutil.rmtree(tmp)
        elif os.path.lexists(tmp):
            os.remove(tmp)
    return candidate


def link_into_profile(content_type: str, stored_path: str,
                      mc_version: str | None, loader: str | None,
                      version_id: str | None = None) -> str:
    """Links a stored pack into an instance's profile; returns the linked path.

    Links (symlink, then hardlink, then copy - global_mod_cache.link_into_place)
    rather than copying: the profile stays cheap metadata and the store stays
    the single place the bytes actually live."""
    if not inside(store_dir(content_type), stored_path):
        raise ValueError('The stored pack points outside its content store.')
    name = entry_name(os.path.basename(stored_path))
    dest = os.path.join(profile_dir(content_type, mc_version, loader, version_id), name)
    if os.path.isdir(stored_path):
        # link_into_place handles files only, so a folder pack is linked as a
        # symlink to the stored folder (or copied where symlinks are refused).
        with tempfile.TemporaryDirectory(prefix='.link-', dir=os.path.dirname(dest)) as work:
            staged = os.path.join(work, 'pack')
            try:
                os.symlink(stored_path, staged, target_is_directory=True)
            except OSError:
                shutil.copytree(stored_path, staged)
            replace_directory(staged, dest)
        return dest
    global_mod_cache.link_into_place(stored_path, dest)
    return dest


# ---------------------------------------------------------------------------
# Installed-content CRUD (per-instance links into a shared store)
# ---------------------------------------------------------------------------

# Packs and shaders are installed as bare .zips, so (unlike mods) nothing on
# disk remembers which Modrinth project they came from - yet the installed
# list should show the project's thumbnail so a user can spot it at a glance.
# This little sidecar maps content_type -> installed filename -> {icon_url,
# slug, title}, written at download time and read back by list_content().
# Best-effort: a pack installed before this existed, or dropped in by hand,
# simply has no art and falls back to the placeholder icon.
_CONTENT_META_PATH = os.path.join(CUBEON_HOME, "content_meta.json")
_CONTENT_META_LOCK = threading.RLock()


def _read_content_meta() -> dict:
    try:
        with open(_CONTENT_META_PATH, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_content_meta(data: dict) -> None:
    try:
        write_json(_CONTENT_META_PATH, data)
    except OSError:
        log.debug("couldn't write content metadata", exc_info=True)


def remember_content_meta(content_type: str, filename: str, *,
                          icon_url: str | None = None,
                          slug: str | None = None,
                          title: str | None = None) -> None:
    """Records a pack/shader's Modrinth identity against its installed
    filename. Called by download_content(); a no-op when nothing is known."""
    if not filename or not (icon_url or slug or title):
        return
    with _CONTENT_META_LOCK:
        data = _read_content_meta()
        bucket = data.get(content_type)
        if not isinstance(bucket, dict):
            bucket = data[content_type] = {}
        entry = bucket.get(filename)
        entry = dict(entry) if isinstance(entry, dict) else {}
        for key, value in (("icon_url", icon_url), ("slug", slug), ("title", title)):
            if value:
                entry[key] = value
        bucket[filename] = entry
        _write_content_meta(data)


def forget_content_meta(content_type: str, filename: str) -> None:
    """Drops a removed pack's metadata so a later pack that happens to reuse
    the filename doesn't inherit a stranger's thumbnail."""
    with _CONTENT_META_LOCK:
        data = _read_content_meta()
        bucket = data.get(content_type)
        if not isinstance(bucket, dict) or filename not in bucket:
            return
        bucket.pop(filename, None)
        _write_content_meta(data)


def _attach_content_meta(content_type: str, item: dict, metadata=None) -> None:
    bucket = (metadata if metadata is not None else _read_content_meta()).get(content_type)
    name = item['filename'].removesuffix('.disabled')
    entry = bucket.get(name) if isinstance(bucket, dict) else None
    if isinstance(entry, dict):
        for key in ('icon_url', 'slug', 'title'):
            if isinstance(entry.get(key), str) and entry[key]:
                item[key] = entry[key]


@lru_cache(maxsize=64)
def _read_pack_icon(path, stamp, folder):
    """Read bounded pack.png bytes on the snapshot worker, never extract files."""
    try:
        if folder:
            with open(path, 'rb') as stream:
                raw = stream.read(512 * 1024 + 1)
        else:
            with zipfile.ZipFile(path) as archive:
                info = archive.getinfo('pack.png')
                if info.file_size > 512 * 1024 or info.flag_bits & 1:
                    return None
                with archive.open(info) as stream:
                    raw = stream.read(512 * 1024 + 1)
        if len(raw) > 512 * 1024 or len(raw) < 24 or not raw.startswith(b'\x89PNG\r\n\x1a\n'):
            return None
        if int.from_bytes(raw[16:20], 'big') * int.from_bytes(raw[20:24], 'big') > 4_194_304:
            return None
        from PIL import Image
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height > 4_194_304:
                return None
            image.thumbnail((96, 96))
            output = io.BytesIO()
            image.convert('RGBA').save(output, format='PNG')
        return base64.b64encode(output.getvalue()).decode('ascii')
    except (OSError, ValueError, KeyError, RuntimeError, zipfile.BadZipFile):
        return None


def _pack_icon_source(path, folder):
    image_path = os.path.join(path, 'pack.png') if folder else path
    if folder and not inside(path, image_path):
        return None
    try:
        stamp = os.stat(image_path)
        return _read_pack_icon(image_path, (stamp.st_mtime_ns, stamp.st_ctime_ns, stamp.st_size), folder)
    except OSError:
        return None


def list_content(content_type: str, mc_version: str | None = None, *,
                 version_id: str | None = None, loader: str | None = None) -> list[dict]:
    """Every pack/shader installed for THIS instance, including disabled entries.
    Enabled means available at next launch. Application/order are chosen in
    Minecraft's own settings, which the launcher never rewrites.

    Needs mc_version AND loader: without them there is no instance to report
    on, so the answer is an empty list rather than a misleading union of every
    profile. Pass mc_version (and/or version_id) to also get a "compat" verdict
    per item, which is what lets the list warn about a pack the game would show
    as Incompatible (skipping that is cheaper: one zip read per item)."""
    if not mc_version or not loader:
        return []
    d = resolve_content_profile_dir(content_type, mc_version, loader, version_id)
    if not os.path.isdir(d):
        return []
    exts = _cfg(content_type)["exts"]
    items = []
    metadata = _read_content_meta()
    for fname in sorted(os.listdir(d)):
        try:
            entry_name(fname)
        except ValueError:
            continue
        full = os.path.join(d, fname)
        if fname.startswith("."):
            continue
        if os.path.isdir(full):
            # A folder pack: the game accepts unpacked packs, so it belongs
            # in the list (and the doctor's verdicts cover it too).
            pass
        elif os.path.isfile(full) and fname.removesuffix('.disabled').lower().endswith(exts):
            pass
        else:
            continue
        item = {
            "filename": fname,
            "display_name": os.path.splitext(fname.removesuffix('.disabled'))[0],
            "enabled": not fname.endswith('.disabled'),
            "size_kb": round(_path_size(full) / 1024, 1),
            "folder": os.path.isdir(full),
            # A link whose target is gone (store file deleted, or a profile
            # copied between machines) has no bytes, so it isn't installed -
            # the same gate list_mods() applies to a dead mod link.
            "missing": not os.path.exists(full) and not os.path.islink(full),
        }
        if mc_version or version_id:
            item["compat"] = content_compat(content_type, fname, mc_version,
                                            version_id, loader)
        _attach_content_meta(content_type, item, metadata)
        source = _pack_icon_source(full, item['folder'])
        if source:
            item['icon_source'] = source
        items.append(item)
    return items


def _path_size(path: str) -> float:
    """File size, or the total size of a folder pack's contents."""
    if os.path.isfile(path):
        try:
            return os.path.getsize(path)
        except OSError:
            return 0
    total = 0
    for dirpath, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(dirpath, f))
            except OSError:
                pass
    return total


def delete_content(content_type: str, filename: str,
                   mc_version: str | None = None, loader: str | None = None,
                   *, purge_store: bool = False,
                   version_id: str | None = None) -> None:
    """Removes a pack/shader from THIS instance's profile (the link), leaving
    the store copy alone - another instance may be using it, and re-installing
    is then instant. `purge_store=True` also deletes the stored bytes, for a
    caller that means "get rid of this entirely" (nothing uses it yet).

    Guards against a filename that escapes the content folder (a caller passing
    '../something'), the same path-escape check delete_version uses, since this
    deletes real files."""
    entry_name(filename)
    d = resolve_content_profile_dir(content_type, mc_version, loader, version_id)
    target = os.path.join(d, filename)
    if os.path.dirname(os.path.abspath(target)) != os.path.abspath(d):
        raise ValueError("Refusing to delete a path outside the content folder.")
    stored = _store_target_of(target) if purge_store else None
    if stored and not inside(store_dir(content_type), stored):
        raise ValueError('Refusing to purge files outside the content store.')
    if os.path.isdir(target) and not os.path.islink(target):
        shutil.rmtree(target)
    elif os.path.isfile(target) or os.path.islink(target):
        os.remove(target)
    if stored and _store_referenced(stored):
        stored = None
    if stored:
        try:
            if os.path.isdir(stored):
                shutil.rmtree(stored)
            else:
                os.remove(stored)
        except OSError:
            log.debug("couldn't purge stored pack %s", stored, exc_info=True)
    # Metadata describes the shared stored filename. Removing one profile's
    # link must not remove thumbnails/identity from sibling profiles.
    if stored:
        forget_content_meta(content_type, filename.removesuffix('.disabled'))


def _store_referenced(stored):
    from .mods import PROFILES_DIR
    for root, directories, files in os.walk(PROFILES_DIR, followlinks=False):
        for name in directories + files:
            try:
                if os.path.samefile(os.path.join(root, name), stored):
                    return True
            except OSError:
                pass
    return False


def toggle_content(content_type, filename, mc_version, loader, *, version_id=None):
    """Change only this profile's availability, retaining shared stored bytes."""
    entry_name(filename)
    with _STORE_LOCK:
        directory = resolve_content_profile_dir(content_type, mc_version, loader, version_id)
        source = os.path.join(directory, filename)
        if not os.path.lexists(source):
            raise ValueError('This content is no longer on disk. Refresh the list.')
        if not os.path.isdir(source) and not filename.removesuffix('.disabled').lower().endswith(_cfg(content_type)['exts']):
            raise ValueError('This is not a pack or shader entry.')
        name = filename.removesuffix('.disabled') if filename.endswith('.disabled') else filename + '.disabled'
        destination = os.path.join(directory, name)
        if os.path.lexists(destination):
            raise ValueError('Both enabled and disabled copies exist. Remove one first.')
        os.rename(source, destination)
        return name


def _store_target_of(link_path: str) -> str | None:
    """The store file a profile link points at, or None when the profile holds
    a real copy instead of a link (the copy fallback on filesystems that allow
    no links)."""
    if not os.path.islink(link_path):
        return None
    try:
        target = os.path.realpath(link_path)
    except OSError:
        return None
    return target if os.path.exists(target) else None


def _require_install_target(content_type, mc_version, loader):
    require_loader_and_version(mc_version, loader, f"install {_cfg(content_type)['label'].lower()}")
    if content_type == "shader" and loader not in MOD_CAPABLE_LOADERS:
        raise ValueError("Vanilla can't run shader packs. Choose a compatible mod loader and install Iris or Oculus first.")


def install_local_content(content_type: str, src_path: str,
                          mc_version: str | None = None,
                          version_id: str | None = None,
                          loader: str | None = None,
                          fix_cb=None) -> str:
    """Puts a .zip the user already has on disk into the global store and links
    it into the CURRENT instance's profile. Returns the profile filename it was
    linked as (disambiguated in the store rather than clobbering an existing
    pack with the same name).

    A private prepared copy is checked against the profile's version and repaired
    if the game would have rejected it (a pack.mcmeta format that doesn't cover
    the version being played is the classic "Incompatible" report), so a pack
    added by hand lands in a state the game accepts."""
    _require_install_target(content_type, mc_version, loader)
    exts = _cfg(content_type)["exts"]
    label = _cfg(content_type)["label"].lower()
    if not src_path.lower().endswith(exts):
        raise ValueError(f"That's not a {label} (.zip) file.")
    if not os.path.isfile(src_path):
        raise ValueError("Couldn't find that file.")
    if not zipfile.is_zipfile(src_path):
        raise ValueError('That content is not a readable ZIP archive.')

    # Hash BEFORE storing: _verify_and_fix may rewrite the stored copy (it can
    # even hardlink back onto the source), and the origin record must describe
    # the bytes the user actually had.
    try:
        src_hash = _entry_hash(src_path)
    except OSError:
        src_hash = None

    # Repair a private temporary copy. Repairing a profile directory symlink
    # can otherwise rewrite bytes shared with a different instance.
    with tempfile.TemporaryDirectory(prefix='.prepare-', dir=store_dir(content_type)) as work:
        prepared = os.path.join(work, 'payload.zip')
        shutil.copyfile(src_path, prepared)
        _verify_and_fix(content_type, prepared, mc_version, version_id, fix_cb)
        if content_type == 'shader' and not packformat.shader_verdict(prepared)['ok']:
            raise ValueError('This archive has no readable shaders/ folder.')
        stored = _store_entry(content_type, prepared, human_name=os.path.basename(src_path))
    if src_hash:
        _write_origin_hash(stored, src_hash)
    dest = link_into_profile(content_type, stored, mc_version, loader, version_id)
    return os.path.basename(dest)


def open_content_folder(content_type: str, mc_version: str | None = None,
                        loader: str | None = None,
                        version_id: str | None = None) -> None:
    """Opens the folder this content type lives in FOR THE ACTIVE INSTANCE.

    The profile folder, not the game folder: the game folder is rebuilt at
    every launch, so deleting a file there would only look like it worked
    until the next launch put it back. Pass no profile to open the game folder
    (where the staged copies are), which is what a caller with no instance
    selected gets."""
    if mc_version and loader:
        d = profile_dir(content_type, mc_version, loader, version_id)
    else:
        d = content_dir(content_type)
    if os.name == "nt":
        os.startfile(d)
    elif os.uname().sysname == "Darwin":
        import subprocess
        subprocess.Popen(["open", d])
    else:
        import subprocess
        subprocess.Popen(["xdg-open", d])


def is_installed(content_type: str, filename: str,
                 mc_version: str | None = None, loader: str | None = None,
                 version_id: str | None = None) -> bool:
    """Is this pack in the active instance's profile? (A folder pack counts -
    the game accepts unpacked packs, and list_content lists them.)"""
    entry_name(filename)
    if mc_version and loader:
        target = os.path.join(resolve_content_profile_dir(
            content_type, mc_version, loader, version_id), filename)
    else:
        target = os.path.join(content_dir(content_type), filename)
    return os.path.isdir(target) or os.path.isfile(target)


# ---------------------------------------------------------------------------
# Compatibility: stop a pack from ever showing "Incompatible" in-game
#
# Everything here is offline (cubeon/packformat.py reads the pack's own
# pack.mcmeta and the target versions' client jars). Two entry points:
#
#   _verify_and_fix()  - runs on every install, so nothing incompatible lands
#   content_compat()   - what the installed list shows the user per item
# ---------------------------------------------------------------------------

def _verify_and_fix(content_type: str, path: str, mc_version: str | None = None,
                    version_id: str | None = None, fix_cb=None) -> dict:
    """Check a just-installed pack and repair it if the game would reject it.

    Returns {"checked", "changed", "reason"}. Never raises and never blocks an
    install: a pack that can't be checked is left exactly as it was."""
    report = {"checked": False, "changed": False, "reason": ""}
    try:
        if content_type == "shader":
            verdict = packformat.shader_verdict(path)
            report["checked"] = True
            if verdict["ok"]:
                return report
            wrapper = verdict.get("wrapper")
            if wrapper and packformat.flatten_pack(path, wrapper):
                report["changed"] = True
                report["reason"] = (f"moved shaders/ up out of '{wrapper}/' so "
                                    "the game can find it")
            else:
                report["reason"] = verdict["reason"]
            if report['changed'] and fix_cb:
                fix_cb(report)
            return report

        # Resource pack. The targets are the version that OWNS this pack: now
        # that a pack belongs to an instance, judging it by every installed
        # version would be wrong - and it was exactly why the verdict never
        # changed when the user switched instance.
        targets = _profile_formats(mc_version, version_id)
        verdict = packformat.pack_verdict(path, targets)
        report["checked"] = True
        if verdict["ok"] is not False:
            return report
        repair = packformat.repair_pack(path, targets)
        if repair.get("changed"):
            after = repair.get("after") or {}
            rng = after.get("supported_formats") or [None, None]
            report["changed"] = True
            report["reason"] = (
                f"adjusted its resource format range to {rng[0]}-{rng[1]} so it "
                "loads on your installed versions")
        else:
            report["reason"] = repair.get("reason") or verdict["reason"]
    except Exception:
        log.warning("content compatibility check failed for %s", path,
                    exc_info=True)
    if report["changed"] and fix_cb:
        try:
            fix_cb(report)
        except Exception:
            log.debug("fix callback failed", exc_info=True)
    return report


def _profile_formats(mc_version: str | None, version_id: str | None) -> list[int]:
    """The resource formats a pack in a profile is judged by: the version that
    owns it.

    This used to be EVERY installed version (packformat.installed_resource_formats)
    because one shared folder was read by all of them. Packs are per-instance
    now, so only the owning version matters - and that change is what makes the
    verdict actually move when the user switches instance. With no version known
    at all there is no profile to judge for, so every installed version is the
    honest fallback."""
    fmt = packformat.resource_format_for(mc_version, version_id)
    if fmt is not None:
        return [fmt]
    return packformat.installed_resource_formats(mc_version, version_id)


def content_compat(content_type: str, filename: str,
                   mc_version: str | None = None,
                   version_id: str | None = None,
                   loader: str | None = None) -> dict | None:
    """The compatibility verdict for one installed item, for the UI.

    Resource packs: {"ok", "reason", "declared", "range", "targets"} - ok is
    True (this instance's version accepts it), False (the game would show it as
    Incompatible) or None (the version's format is unknown).
    Shaders: {"ok", "reason"} - structure only, they carry no format.
    None when the file can't be found/read at all."""
    if mc_version and loader:
        path = os.path.join(resolve_content_profile_dir(
            content_type, mc_version, loader, version_id), filename)
    else:
        path = os.path.join(content_dir(content_type), filename)
    if not os.path.exists(path):     # isdir too: a folder pack has no isfile
        return None
    try:
        if content_type == "shader":
            return packformat.shader_verdict(path)
        return packformat.pack_verdict(path, _profile_formats(mc_version, version_id))
    except Exception:
        log.warning("compat check failed for %s", path, exc_info=True)
        return None



# ---------------------------------------------------------------------------
# Discovery/download via Modrinth's public API (same endpoints as mods.py,
# just a different project_type facet).
# ---------------------------------------------------------------------------

def content_mc_versions(mc_version: str | None) -> list[str]:
    """Provider tags for packs that work on the selected Minecraft release.

    1.20 and 1.20.1 share resource format 15 and shader support. Authors
    commonly tag only 1.20.1; an exact 1.20 tag hides those packs. Keep this
    separate from mod compatibility and instance/profile identifiers.
    """
    if mc_version in ("1.20", "1.20.0"):
        return ["1.20", "1.20.1"]
    if mc_version == "1.20.1":
        return ["1.20.1", "1.20"]
    return [mc_version] if mc_version else []


def search_content(content_type: str, query: str, mc_version: str | None = None,
                    categories: list[str] | None = None, limit: int = 100,
                    offset: int = 0) -> list[dict]:
    """Searches Modrinth for packs/shaders of this type, optionally scoped to a
    Minecraft version and one or more categories. With no query text this is a
    most-downloaded-first browse (see modrinth_search_index). No loader facet:
    resource packs have no loader, and shaders are matched by version/category
    so the results aren't over-narrowed to one shader loader.

    `offset` pages through Modrinth's result set so the UI can fetch one page
    at a time instead of pulling 100 hits and slicing locally. Included in the
    cache key, so pages cache independently."""
    project_type = _cfg(content_type)["project_type"]
    facets = [[f"project_type:{project_type}"]]
    game_versions = content_mc_versions(mc_version)
    if game_versions:
        facets.append([f"versions:{version}" for version in game_versions])
    if categories:
        facets.append([f"categories:{c}" for c in categories])

    cache_key = {
        "type": content_type, "query": query, "mc_version": mc_version,
        "game_versions": game_versions,
        "categories": categories or [], "limit": limit, "offset": offset,
    }

    def _fetch() -> list[dict]:
        params = {
            "query": query, "limit": str(limit), "offset": str(offset),
            "facets": json.dumps(facets),
            "index": modrinth_search_index(query),
        }
        data = net.get_json(f"{MODRINTH_API}/search", params=params,
                            headers=modrinth_headers(), timeout=15)

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

    # Same tiers as search_mods: 6h fresh, stale-while-revalidate, offline fallback.
    return local_cache.cached_call("search_content", cache_key, _fetch, max_age=6 * 3600)


def get_recommended_content(content_type: str, mc_version: str | None = None,
                            category: str | None = None, limit: int = 100,
                            offset: int = 0) -> list[dict]:
    """The default browse view before the user searches: the most-downloaded
    packs/shaders of this type for the current version (and category, if one's
    picked). Unlike mods.py's curated slug list, this is a plain popularity
    browse - for cosmetics 'most popular' is exactly what a browse should show,
    and it can never come back empty the way a hard-coded slug list can if a
    slug is renamed upstream. limit/offset page through Modrinth so the UI
    fetches one page at a time."""
    return search_content(
        content_type, "", mc_version=mc_version,
        categories=[category] if category else None,
        limit=limit, offset=offset,
    )


def get_content_download(content_type: str, project_id_or_slug: str,
                         mc_version: str | None = None) -> dict | None:
    """Finds the best matching version file for a pack/shader, filtered by MC
    version when given. Returns {filename, url, size_kb, version_number} or
    None if no matching version exists. No loader filter - see search_content."""
    params = {}
    game_versions = content_mc_versions(mc_version)
    if game_versions:
        params["game_versions"] = json.dumps(game_versions)

    cache_key = {"type": content_type, "project": project_id_or_slug, "mc_version": mc_version,
                 "game_versions": game_versions, 'revision': 2}

    def _fetch():
        versions = net.get_json(
            f"{MODRINTH_API}/project/{project_id_or_slug}/version",
            params=params, headers=modrinth_headers(), timeout=15,
        )
        # Prefer an exact tagged release before the compatible patch tag.
        for candidate in game_versions or [None]:
            selected = _select_download(versions, mc_version=candidate,
                                        extensions=_cfg(content_type)['exts'])
            if selected:
                return selected
        return None

    # Between click and download start - 24h fresh, then SWR, offline fallback.
    return local_cache.cached_call("content_download", cache_key, _fetch, max_age=86400)


def download_content(content_type: str, download_url: str, filename: str,
                     progress_cb=None, hashes: dict | None = None, *,
                     mc_version: str | None = None,
                     version_id: str | None = None,
                     loader: str | None = None, fix_cb=None,
                     icon_url: str | None = None,
                     slug: str | None = None,
                     title: str | None = None) -> str:
    """Streams a pack/shader file into the shared folder for this content type.

    Goes through cubeon.net like every other download: retry with backoff,
    HTTP Range resume after a dropped connection, a global concurrency cap,
    and an atomic .part -> final replace so a half-file is never mistaken for
    a complete pack. (This was the last install path still doing a bare
    single-attempt requests.get - exactly why a brief Wi-Fi hiccup showed up
    to the user as a hard "network error" instead of quietly retrying.)

    hashes: the Modrinth file's {"sha512"/"sha1": ...} when known; a mismatch
    is rejected rather than installing corrupt bytes. The verify-and-repair
    pass runs on the downloaded file BEFORE it becomes the stored copy, so the
    store never holds a pack the game would reject. progress_cb(downloaded,
    total) is throttled inside net. Returns the profile path it was linked at."""
    _require_install_target(content_type, mc_version, loader)
    filename = download_name(filename, _cfg(content_type)["exts"])
    from .modpacks import _host_allowed
    if not _host_allowed(download_url or ''):
        raise ValueError('Refusing a content download from an untrusted host.')
    algo, expected = None, None
    for a in ("sha512", "sha256", "sha1"):
        if (hashes or {}).get(a):
            if not isinstance(hashes[a], str):
                raise ValueError('The download has an invalid published hash.')
            algo, expected = a, hashes[a].lower()
            break
    expected_pair = (algo, expected) if algo and expected else None
    store = store_dir(content_type)
    fd, tmp = tempfile.mkstemp(prefix='.fetch-', suffix='.zip', dir=store)
    os.close(fd)
    try:
        net.download_to(tmp, download_url, headers=modrinth_headers(), timeout=60,
                        expected_hash=expected_pair, progress_cb=progress_cb,
                        url_validator=_host_allowed)
        if not zipfile.is_zipfile(tmp):
            raise ValueError('The downloaded content is not a readable ZIP archive.')
        # Last step before the bytes are kept: make sure the game will accept
        # them. Modrinth's metadata says which Minecraft versions the AUTHOR
        # thinks a pack supports; the pack's own pack.mcmeta is what the game
        # reads, and the two disagree often enough that this is the difference
        # between "installed" and "shows Incompatible in game".
        _verify_and_fix(content_type, tmp, mc_version, version_id, fix_cb)
        if content_type == 'shader' and not packformat.shader_verdict(tmp)['ok']:
            raise ValueError('This archive has no readable shaders/ folder.')
        stored = _store_entry(content_type, tmp, human_name=filename)
    finally:
        for leftover in (tmp, tmp + '.part'):
            try:
                os.remove(leftover)
            except OSError:
                pass
    linked = link_into_profile(content_type, stored, mc_version, loader, version_id)
    # Remember which project this came from so the installed list can show its
    # thumbnail later (a bare .zip carries no Modrinth identity).
    remember_content_meta(content_type, os.path.basename(linked),
                          icon_url=icon_url, slug=slug, title=title)
    return linked


# ---------------------------------------------------------------------------
# Launch-time staging: the step that makes packs follow the instance
# ---------------------------------------------------------------------------

def _read_staged(content_type: str) -> list[str]:
    """The entries Cubeon staged into the game folder last time (empty when the
    marker is missing/corrupt - treating it as "nothing was staged" is the safe
    read, since it only means foreign files get adopted rather than removed)."""
    try:
        with open(os.path.join(content_dir(content_type), _STAGED_MARKER),
                  "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, list):
            names = []
            for name in data:
                try:
                    names.append(entry_name(name))
                except ValueError:
                    continue
            return names
    except (OSError, ValueError):
        pass
    return []


def _write_staged(content_type: str, names: list[str]) -> None:
    path = os.path.join(content_dir(content_type), _STAGED_MARKER)
    try:
        if sorted(names) != sorted(_read_staged(content_type)) or not os.path.isfile(path):
            write_json(path, sorted(names))
    except OSError:
        log.debug("couldn't record staged %s", content_type, exc_info=True)


def _store_from_game_folder(content_type: str, path: str, name: str) -> str:
    """Moves a game-folder entry into the store, returning the stored path.

    A link already pointing into the store just resolves. Originals remain
    until the caller successfully publishes a profile link."""
    if os.path.islink(path):
        real = os.path.realpath(path)
        store_root = os.path.realpath(store_dir(content_type))
        if os.path.exists(real) and real.startswith(store_root + os.sep):
            return real
    stored = _store_entry(content_type, path, human_name=name)
    return stored


def _adopt_foreign_entries(content_type: str, staged: list[str],
                           mc_version: str | None, loader: str | None,
                           version_id: str | None = None) -> int:
    """Takes ownership of anything in the game folder this sync did not put
    there: a pack the user dropped in by hand, dragged from a file manager, or
    installed with a build of Cubeon that had no profiles.

    It is MOVED into the store and linked into the profile being played, so the
    bytes are never deleted and the pack follows this instance from now on.
    Leaving it instead would keep it visible in every instance, which is the
    exact behaviour this change exists to remove."""
    d = content_dir(content_type)
    exts = _cfg(content_type)["exts"]
    adopted = 0
    try:
        names = sorted(os.listdir(d))
    except OSError:
        return 0
    for fname in names:
        if fname.startswith(".") or fname in staged:
            continue
        full = os.path.join(d, fname)
        if not (os.path.isdir(full)
                or (os.path.isfile(full) and fname.lower().endswith(exts))):
            continue
        try:
            stored = _store_from_game_folder(content_type, full, fname)
            link_into_profile(content_type, stored, mc_version, loader, version_id)
            # Only retire the original after the profile link succeeds.
            if os.path.realpath(full) != os.path.realpath(stored):
                if os.path.isdir(full) and not os.path.islink(full):
                    shutil.rmtree(full)
                else:
                    os.remove(full)
            adopted += 1
        except Exception:      # noqa: BLE001 - never break a launch over this
            log.warning("couldn't adopt %s from the game folder", full,
                        exc_info=True)
    return adopted


def sync_content_to_game(mc_version: str | None, loader: str | None,
                         version_id: str | None = None) -> None:
    """Rebuilds the game's resourcepacks/ and shaderpacks/ from THIS instance's
    profile - the packs/shaders twin of mods.sync_mods_to_game(), and the step
    that makes them change when the user changes instance.

    Order matters: adopt foreign entries first (so nothing the user placed by
    hand is ever removed), then drop whatever this sync staged for a DIFFERENT
    instance, then link the current profile's packs in. Unlike mods there is no
    version-aware de-duplication: two builds of the same pack in one profile are
    the user's business, not a guaranteed crash the way two mod builds are.

    Best-effort by design - a pack that can't be staged must never stop a
    launch."""
    require_loader_and_version(mc_version, loader, "sync packs into the game")
    for content_type in ("resourcepack", "shader"):
        try:
            _sync_content_type(content_type, mc_version, loader, version_id)
        except Exception:      # noqa: BLE001
            log.warning("couldn't sync %s into the game", content_type,
                        exc_info=True)


def _sync_content_type(content_type: str, mc_version: str,
                       loader: str, version_id: str | None = None) -> None:
    d = content_dir(content_type)
    staged = _read_staged(content_type)
    from .file_safety import copy_source_stamp, copied_entry_matches, copied_entry_receipt
    from .mods import _read_copy_receipts, _write_copy_receipts
    previous_copies = _read_copy_receipts(d, _STAGED_MARKER)
    copies = {}
    _adopt_foreign_entries(content_type, staged, mc_version, loader, version_id)

    profile = profile_dir(content_type, mc_version, loader, version_id)
    wanted = [n for n in sorted(os.listdir(profile))
              if not n.startswith('.') and not n.endswith('.disabled')
              and (os.path.isdir(os.path.join(profile, n))
                   or n.lower().endswith(_cfg(content_type)['exts']))]
    wanted = [n for n in wanted if _valid_entry(n)]
    published = set()

    # Drop what we staged for an instance that is no longer selected. Only ever
    # an entry we recorded - a file we didn't stage is never a candidate here.
    for fname in staged:
        if fname in wanted:
            continue
        leftover = os.path.join(d, fname)
        try:
            if os.path.isdir(leftover) and not os.path.islink(leftover):
                shutil.rmtree(leftover)
            elif os.path.lexists(leftover):
                os.remove(leftover)
        except OSError:
            published.add(fname)  # Keep ownership of a failed removal.
            log.debug("couldn't unstage %s", leftover, exc_info=True)

    for fname in wanted:
        src = os.path.join(profile, fname)
        if not os.path.exists(src):
            continue          # dead link: store copy gone, so nothing to stage
        dst = os.path.join(d, fname)
        if os.path.lexists(dst):
            if fname not in staged:
                continue
            try:
                if os.path.samefile(src, dst):
                    published.add(fname)
                    continue
            except OSError:
                pass
            if copied_entry_matches(src, dst, previous_copies.get(fname)):
                published.add(fname)
                copies[fname] = previous_copies[fname]
                continue
        before = None
        copied = False
        fd, tmp = tempfile.mkstemp(prefix=".stage-", dir=d)
        os.close(fd)
        os.remove(tmp)
        try:
            if os.path.isdir(src):
                try:
                    os.symlink(src, tmp, target_is_directory=True)
                except OSError:
                    before = copy_source_stamp(src)
                    shutil.copytree(src, tmp)
                    copied = True
            else:
                try:
                    os.link(src, tmp)
                except OSError:
                    before = copy_source_stamp(src)
                    shutil.copyfile(src, tmp)
                    copied = True
            if os.path.isdir(dst) and not os.path.islink(dst):
                backup = tmp + ".old"
                os.replace(dst, backup)
                try:
                    os.replace(tmp, dst)
                except OSError:
                    os.replace(backup, dst)
                    raise
                shutil.rmtree(backup)
            else:
                os.replace(tmp, dst)
            published.add(fname)
            if copied:
                receipt = copied_entry_receipt(src, dst, before)
                if receipt is not None:
                    copies[fname] = receipt
        except OSError:
            if fname in staged and os.path.lexists(dst):
                published.add(fname)
            log.warning('couldn\'t stage %s', dst, exc_info=True)
        finally:
            if os.path.isdir(tmp) and not os.path.islink(tmp):
                shutil.rmtree(tmp)
            elif os.path.lexists(tmp):
                os.remove(tmp)

    _write_staged(content_type, list(published))
    _write_copy_receipts(d, _STAGED_MARKER, copies)


def _valid_entry(name):
    try:
        entry_name(name)
        return True
    except ValueError:
        return False
