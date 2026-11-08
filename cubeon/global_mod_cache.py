"""
Global mods store - ONE visible, human-named physical copy of every mod jar,
shared across every mod profile that uses it. Same idea as Prism/MultiMC's
central asset store: profiles never hold their own copy of a jar - they hold
a link into the store.

Layout:
    <game dir>/global_mods/sodium-fabric-0.9.2.jar   - the actual bytes,
        named for a human (NOT a hash) so the folder is browsable.
        If two different jars ever want the same name, the later one stores
        as "<name>.<first-8-of-sha256>.jar" so neither overwrites the other.
    <game dir>/global_mods/.hash_index.json
        - {"sha256": {"<sha256-hex>": "<stored filename>", ...},
           "manifest": {"<sha1-or-sha512-hex>": "<sha256-hex>", ...}}
        The sha256 map is what turns "do we already have this exact jar?"
        into a disk lookup (this is the exact-match reuse the UI promises:
        only identical bytes are reused, never a name-based guess). The
        manifest map exists because Modrinth manifests only ever give us
        sha1/sha512, never sha256 - it lets a manifest hash we've seen
        before resolve straight to a store hit *before* any network request.

The store sits at <game dir>/global_mods, deliberately OUTSIDE <game
dir>/mods: the game folder's mods/ is reconciled with the active profile
at every launch, so the store must never be touched by that sync.

SYMLINK ENGINE
    Placing a stored jar into a profile is a real OS symlink
    (os.symlink - unix symlink on Linux/macOS, an NTFS reparse point on
    Windows when Developer Mode or admin rights allow it), not a copy: the
    profile folder holds a link, the store holds the only real bytes.
    Falls back to a hardlink (same inode, still free) if symlinks aren't
    permitted on this OS/filesystem, and to a plain copy as the last resort
    so an install never fails outright just because linking isn't available.
"""
import hashlib
import json
import os
import shutil
import tempfile
import threading

from .paths import GLOBAL_MODS_DIR

_HASH_INDEX_PATH = os.path.join(GLOBAL_MODS_DIR, ".hash_index.json")
_INDEX_STRUCT = ("sha256", "manifest")

# A modpack now downloads its jars in parallel (see modpacks._install_from_zip),
# so several threads can finish and try to commit to the store at once. Every
# read-modify-write of the index - and the store-name choice, which is race
# prone if two different jars with the same human name land together - happens
# under this lock. Without it, concurrent _record() calls each load the index,
# add their own entry, and the later save silently drops the earlier one.
_INDEX_LOCK = threading.RLock()


def _store_root():
    from . import storage
    return str(storage.root() / "cache" / "downloads" / "mods") if storage.enabled() else GLOBAL_MODS_DIR


def _index_path():
    from . import storage
    return os.path.join(_store_root(), ".hash_index.json") if storage.enabled() else _HASH_INDEX_PATH



def _hash_file(path: str, algo: str = "sha256") -> str:
    h = hashlib.new(algo)
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_index() -> dict:
    """{"sha256": {sha256-hex: stored filename},
         "manifest": {sha1/sha512-hex: sha256-hex}}"""
    try:
        with open(_index_path(), "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            return {key: {k: v for k, v in data.get(key, {}).items()
                          if isinstance(k, str) and isinstance(v, str)}
                    if isinstance(data.get(key), dict) else {} for key in _INDEX_STRUCT}
    except (OSError, ValueError):
        pass
    return {k: {} for k in _INDEX_STRUCT}


def _save_index(index: dict) -> None:
    os.makedirs(_store_root(), exist_ok=True)
    from .atomicio import write_json
    write_json(_index_path(), index)


def _filename_for_sha(sha256_hex: str) -> "str | None":
    return _load_index()["sha256"].get(sha256_hex.lower())


def _store_path(filename: str) -> str:
    from .file_safety import entry_name, inside
    path = os.path.join(_store_root(), entry_name(filename))
    if not inside(_store_root(), path):
        raise ValueError('The cached file points outside its mod store.')
    return path


from functools import lru_cache


@lru_cache(maxsize=256)
def _verified_hash(path, stamp, algorithm='sha256'):
    return _hash_file(path, algorithm)


def _matches_hashes(path, hashes):
    try:
        stat = os.stat(path)
        stamp = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        return all(_verified_hash(path, stamp, algo) == str(digest).lower()
                   for algo, digest in (hashes or {}).items()
                   if algo in ('sha256', 'sha512', 'sha1') and digest)
    except OSError:
        return False


def cache_path_if_present(sha256_hex: str) -> "str | None":
    """Public accessor: the on-disk path for this exact jar (by sha256) if the
    store already has it, or None on a genuine miss. Used by callers (p2p.py)
    that need to check store presence without downloading anything."""
    filename = _filename_for_sha(sha256_hex)
    if not filename:
        return None
    try:
        path = _store_path(filename)
        stat = os.stat(path)
        stamp = (stat.st_dev, stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns)
        return path if _verified_hash(path, stamp) == sha256_hex.lower() else None
    except (OSError, ValueError):
        return None


def _resolve_manifest_hash(hashes: dict):
    """Resolve a manifest's sha512/sha1 (whichever it has) to a stored path
    we've already saved, or None if we've never seen that exact jar."""
    if not hashes:
        return None
    index = _load_index()
    sha_map, manifest = index['sha256'], index['manifest']
    for algo in ("sha512", "sha1"):
        digest = (hashes or {}).get(algo)
        if not isinstance(digest, str) or not digest:
            continue
        sha256_hex = manifest.get(digest.lower())
        if not sha256_hex:
            continue
        filename = sha_map.get(sha256_hex)
        if filename:
            path = cache_path_if_present(sha256_hex)
            if path and _matches_hashes(path, hashes):
                return path
    return None


def link_into_place(cached_path: str, dest_path: str) -> None:
    """Symlink engine: place a stored file at dest_path via a real OS
    symlink first, hardlink second, plain copy as the last-resort fallback -
    in that order of preference, cheapest/most-correct first.

    Logs which strategy succeeded so the user can tell whether their
    filesystem is doing symlinks, hardlinks, or copies."""
    from . import storage
    storage.assert_writable()
    if storage.enabled():
        parent = os.path.dirname(os.path.abspath(dest_path))
        os.makedirs(parent, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".copy-", dir=parent) as staging:
            staged = os.path.join(staging, "payload")
            shutil.copyfile(cached_path, staged)
            os.replace(staged, dest_path)
        storage.record_installed_file(dest_path)
        return
    try:
        if os.path.samefile(cached_path, dest_path):
            return
    except OSError:
        pass  # Missing or stale destination: publish the verified store file.
    parent = os.path.dirname(os.path.abspath(dest_path))
    os.makedirs(parent, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".link-", dir=parent) as staging:
        staged = os.path.join(staging, "payload")
        try:
            os.symlink(os.path.abspath(cached_path), staged)
        except OSError as e:
            try:
                os.link(cached_path, staged)
            except OSError:
                shutil.copyfile(cached_path, staged)
        os.replace(staged, dest_path)


def _choose_store_name(sha256_hex: str, human_name: str | None, index: dict) -> str:
    """The filename the bytes for sha256_hex will live under.

    A jar already in the store keeps the name it was first stored as (the
    sha256 map is authoritative, so a second install of the same bytes just
    links that existing file). A genuinely new jar gets `human_name` when
    one is offered - unless that name is already taken by DIFFERENT bytes,
    in which case it's disambiguated so nothing ever overwrites a stored
    jar. Returns a name that does not currently exist as a file."""
    existing = index["sha256"].get(sha256_hex)
    if existing:
        try:
            path = _store_path(existing)
            if not os.path.lexists(path) or _hash_file(path) == sha256_hex:
                return existing
        except (OSError, ValueError):
            pass

    base = (human_name or "").strip()
    if not base:
        base = f"{sha256_hex[:16]}.jar"
    # The caller hands us basenames of profile entries; be defensive anyway -
    # the store must never be written outside itself.
    base = os.path.basename(base.replace("\\", "/"))
    from .file_safety import download_name
    base = download_name(base, ('.jar', '.disabled'))

    candidate = base
    collision = 0
    while True:
        try:
            path = _store_path(candidate)
            if not os.path.lexists(path):
                return candidate
            if _hash_file(path, "sha256") == sha256_hex:
                return candidate
        except (OSError, ValueError):
            pass
        stem, dot, ext = base.rpartition(".")
        if not dot:
            stem, ext = base, ""
        collision += 1
        tag = sha256_hex[:8] if collision == 1 else f'{sha256_hex}.{collision}'
        candidate = f"{stem}.{tag}{dot}{ext}"


def _record(sha256_hex: str, filename: str, hashes: dict) -> None:
    """Persist sha256 -> stored filename and any manifest aliases."""
    with _INDEX_LOCK:
        index = _load_index()
        index["sha256"][sha256_hex] = filename
        for algo in ("sha512", "sha1"):
            digest = (hashes or {}).get(algo)
            if digest:
                index["manifest"][digest.lower()] = sha256_hex
        _save_index(index)


def _ingest(tmp_path: str, human_name: str | None, hashes: dict) -> str:
    """Move freshly-fetched bytes (tmp_path) into the store under the right
    name, deduping against what's already there. Returns the stored path.

    The hashing stays outside the lock (it's the slow part); only the
    name-choice + move + index update are serialized, so two threads can't
    pick the same store filename for different bytes."""
    sha256_hex = _hash_file(tmp_path, "sha256")
    for algorithm in ('sha256', 'sha512', 'sha1'):
        expected = (hashes or {}).get(algorithm)
        if expected and _hash_file(tmp_path, algorithm) != str(expected).lower():
            raise ValueError('The mod does not match its published content hash.')

    with _INDEX_LOCK:
        existing = cache_path_if_present(sha256_hex)
        if existing:
            _record(sha256_hex, os.path.basename(existing), hashes)
            os.remove(tmp_path)
            return existing

        os.makedirs(_store_root(), exist_ok=True)
        filename = _choose_store_name(sha256_hex, human_name, _load_index())
        stored = _store_path(filename)
        os.replace(tmp_path, stored)
        _record(sha256_hex, filename, hashes)
        return stored


def get_or_fetch(dest_path: str, fetch_fn, hashes: dict = None,
                 human_name: str | None = None, *, cancel_check=None) -> str:
    """Ensure dest_path exists, using the global mods store when possible.

    fetch_fn(tmp_path) must produce the file at tmp_path (downloading it,
    raising on failure) and is only called on an actual store miss.

    dest_path is where the jar should end up (normally inside a profile) -
    get_or_fetch stores one physical copy in the store and links it there.
    human_name overrides the store's display name; it defaults to the
    basename of dest_path so the store's human-named file matches what the
    profile calls the mod.

    hashes: the manifest's {"sha512": ..., "sha1": ...} if known ahead of
    the download. A hit here goes through the manifest-alias index (a
    manifest hash we've resolved to a sha256 before); a genuinely new jar
    always has to be downloaded once to learn its sha256, same as any
    content-addressed store.

    Returns the path bytes were linked to (dest_path).
    """
    if cancel_check is not None:
        cancel_check()
    hashes = hashes or {}
    human_name = human_name or os.path.basename(dest_path.replace("\\", "/"))

    # Exact-match reuse: a manifest hash we've already resolved, or a sha256
    # we already know, links the stored file with no network at all.
    cached = _resolve_manifest_hash(hashes)
    if not cached:
        sha256_hex = (hashes or {}).get("sha256")
        cached = cache_path_if_present(sha256_hex) if sha256_hex else None
    if cached and _matches_hashes(cached, hashes):
        if cancel_check is not None:
            cancel_check()
        link_into_place(cached, dest_path)
        return dest_path

    # Store miss - fetch once, hash the real bytes, store under a human
    # name, remember the manifest hash -> sha256 alias for next time.
    os.makedirs(_store_root(), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".fetch-", suffix=".part", dir=_store_root())
    os.close(fd)
    try:
        fetch_fn(tmp_path)
        if cancel_check is not None:
            cancel_check()
        stored = _ingest(tmp_path, human_name, hashes)
    finally:
        for partial in (tmp_path, tmp_path + '.part'):
            try:
                os.remove(partial)
            except OSError:
                pass
    if cancel_check is not None:
        cancel_check()
    link_into_place(stored, dest_path)
    return dest_path


def put_file(src_path: str, dest_path: str, hashes: dict = None) -> str:
    """Store a jar that already exists on disk (an 'Install from file', a
    hand-add, or Cubeon's own shipped jars) and link it to dest_path -
    the local equivalent of get_or_fetch, with fetch_fn replaced by a copy.

    If the exact bytes are already in the store (hashed up front, so no
    copy is made first), it links straight to the stored file. Returns
    dest_path."""
    hashes = hashes or {}
    info = os.stat(src_path)
    stamp = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    sha256_hex = _verified_hash(os.path.realpath(src_path), stamp, "sha256")
    if not _matches_hashes(src_path, hashes):
        raise ValueError('The mod does not match its published content hash.')
    stored = cache_path_if_present(sha256_hex)
    if stored:
        link_into_place(stored, dest_path)
        return dest_path

    os.makedirs(_store_root(), exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(prefix=".fetch-", suffix=".part", dir=_store_root())
    os.close(fd)
    try:
        shutil.copyfile(src_path, tmp_path)
        stored = _ingest(tmp_path, os.path.basename(dest_path.replace("\\", "/")), hashes)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass
    link_into_place(stored, dest_path)
    return dest_path
