"""Versioned instance ownership and copy/verify migration.

Importing this module never migrates data. Only initialize() opts a launcher
session into the new layout; existing installs are recorded as legacy first.
"""
from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import tempfile
import threading
import uuid

from . import paths
from .atomicio import write_json

_mutex = threading.RLock()
_blocked = False
_owner = None
_restart_required = False
_session_file = None
_migration_mutex = threading.Lock()
_receipt_mutex = threading.RLock()
CONTENT_DIRS = ("mods", "resourcepacks", "shaderpacks")
_CONTENT_SCOPE = "instance-content-v1"
_SWITCH_SLOTS = (*CONTENT_DIRS, ".cubeon/mods", "instance.json")
_LEGACY_CONTENT_DIRS = ("global_mods", "global_content", *CONTENT_DIRS)


def root() -> Path:
    return Path(paths.MINECRAFT_DIR)


def registry_path() -> Path:
    return root() / "instances" / "storage.json"


def _read(path: Path, default=None):
    try:
        with path.open(encoding="utf-8") as stream:
            value = json.load(stream)
    except FileNotFoundError:
        return default
    except (OSError, ValueError) as error:
        raise RuntimeError(f"Cannot read storage metadata: {path}. Keep your files and retry.") from error
    if not isinstance(value, dict):
        raise RuntimeError(f"Invalid storage metadata: {path}")
    return value


def registry():
    value = _read(registry_path())
    if value is None and (root() / "instances" / ".layout-v2.json").exists():
        raise RuntimeError("The instance storage index is missing. Restore instances/storage.json from a backup before playing; your game folders are still intact.")
    if value is not None and (value.get("schema") != 1
                              or not isinstance(value.get("instances"), dict)
                              or not isinstance(value.get("legacy"), list)
                              or value.get("runtime") not in ("legacy", "runtime", "instances")):
        raise RuntimeError("This storage layout needs a compatible Cubeon version. No files were changed.")
    return value


def enabled() -> bool:
    return registry() is not None


def _name(value):
    if (not isinstance(value, str) or not value or value in (".", "..")
            or any(c in value for c in '/\\:\x00') or any(ord(c) < 32 for c in value)):
        raise ValueError("Invalid instance identity.")
    return value


def _owned(base: Path, *parts) -> Path:
    dest = base.joinpath(*parts)
    if not dest.resolve().is_relative_to(base.resolve()) or dest.resolve() == base.resolve():
        raise ValueError(f"Storage path leaves its folder: {dest}")
    # Refuse redirected destinations even when their target happens to be inside.
    cur = dest
    while cur != base:
        if cur.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(cur):
            raise ValueError(f"Storage destination is a link: {cur}")
        cur = cur.parent
    return dest


def initialize() -> dict:
    """Record old installs before new installs can be created. Never move data."""
    with _mutex:
        value = registry()
        if value is not None:
            _recover_content_switch()
            from . import storage_layout
            storage_layout.recover()
            return value
        versions = root() / "versions"
        instances_root = _owned(root(), "instances")
        if instances_root.is_dir() and any((p / "instance.json").is_file() for p in instances_root.iterdir() if p.is_dir()):
            raise RuntimeError("Found instance folders without their storage index. Restore instances/storage.json from a backup before playing.")
        legacy = sorted(p.name for p in versions.iterdir() if p.is_dir()) if versions.is_dir() else []
        value = {"schema": 1, "legacy": legacy, "instances": {},
                 "runtime": "legacy" if versions.exists() else "instances"}
        write_json(str(registry_path()), value)
        write_json(str(instances_root / ".layout-v2.json"), {"schema": 1})
        return value


def runtime_dir(legacy_root=None) -> str:
    # Explicit roots patched by existing integration harnesses remain isolated.
    base = Path(legacy_root) if legacy_root is not None else root()
    if base.absolute() != root().absolute():
        return str(base)
    value = registry()
    if value:
        from .storage_layout import runtime_root
        return str(runtime_root(value["runtime"]))
    return str(base)


def assert_writable():
    if _restart_required or (_blocked and threading.get_ident() != _owner):
        raise RuntimeError("Minecraft files are being organized. Restart Cubeon when migration finishes.")


def blocked() -> bool:
    return _blocked or _restart_required


def restart_required() -> bool:
    return _restart_required


def manifest(version_id) -> dict | None:
    value = registry()
    if value is None:
        return None
    _name(version_id)
    if not value or version_id not in value["instances"]:
        return None
    ident = _name(value["instances"][version_id])
    folder = _owned(root() / "instances", ident)
    data = _read(folder / "instance.json")
    if (not data or data.get("layout") != 2 or data.get("version_id") != version_id
            or data.get("game_subdir", "minecraft") not in (".", "minecraft")):
        raise RuntimeError(f"Instance metadata is missing or invalid for {version_id}. Restore it before playing.")
    return data


def folder_for(version_id, *, create=False, meta=None) -> Path | None:
    if not version_id or version_id == "cubeon-rust-26.3":
        return None
    with _mutex:
        value = registry()
        if value is None:
            return None
        _name(version_id)
        if version_id in value["instances"]:
            manifest(version_id)  # Never fall back to legacy after a corrupt manifest.
            return _owned(root() / "instances", _name(value["instances"][version_id]))
        if version_id in value["legacy"]:
            return None
        generation = value.get("generations", {}).get(version_id, 0)
        suffix = uuid.uuid5(uuid.NAMESPACE_URL, f"{root()}:{version_id}:{generation}").hex[:12]
        from .storage_layout import new_folder_name
        ident = new_folder_name(version_id, suffix)
        folder = _owned(root() / "instances", ident)
        if not create:
            return folder
        assert_writable()
        folder.mkdir(parents=True, exist_ok=False)
        for name in ("mods", "config", "saves", "resourcepacks", "shaderpacks", "screenshots", "logs", "crash-reports"):
            (folder / "minecraft" / name).mkdir(parents=True)
        data = {**(meta or {}), "layout": 2, "id": "instance-" + suffix, "version_id": version_id,
                "profile": (meta or {}).get("profile") or "instance-" + suffix,
                "folder_name_version": 1}
        write_json(str(folder / "instance.json"), data)
        value["instances"][version_id] = ident
        write_json(str(registry_path()), value)
        return folder


def game_dir(version_id, *, create=False):
    folder = folder_for(version_id, create=create)
    if folder is None:
        return None
    data = manifest(version_id) or {}
    return str(folder if data.get("game_subdir") == "." else _owned(folder, "minecraft"))


def update_meta(version_id, meta):
    with _mutex:
        assert_writable()
        folder = folder_for(version_id, create=True, meta=meta)
        if folder is None:
            return False
        old = manifest(version_id)
        write_json(str(folder / "instance.json"), {**old, **meta,
                   "layout": 2, "id": old["id"], "version_id": version_id,
                   "game_subdir": old.get("game_subdir", "minecraft")})
        return True


def archive_instance(version_id):
    """Deleting an install preserves its worlds in a clearly named recovery folder."""
    assert_writable()
    with _mutex:
        folder = folder_for(version_id)
        if folder is None:
            return
        data = manifest(version_id)
        backup = _owned(root(), "backups", "deleted-instances", data["id"])
        backup.parent.mkdir(parents=True, exist_ok=True)
        if backup.exists():
            raise RuntimeError("An instance recovery folder already exists; nothing was overwritten.")
        os.replace(folder, backup)
        value = registry()
        value["instances"].pop(version_id)
        value["legacy"] = [vid for vid in value["legacy"] if vid != version_id]
        generations = value.setdefault("generations", {})
        generations[version_id] = generations.get(version_id, 0) + 1
        try:
            write_json(str(registry_path()), value)
        except BaseException:
            os.replace(backup, folder)
            raise


def discard_registration(version_id, ident):
    """Undo only the registry entry created by a failed new pack installation."""
    with _mutex:
        value = registry()
        if value and value["instances"].get(version_id) == ident:
            value["instances"].pop(version_id)
            write_json(str(registry_path()), value)


def profile_for_key(key):
    value = registry()
    if value:
        for version in value["instances"]:
            data = manifest(version)
            if data.get("profile") == key or data["id"] == key:
                return str(Path(game_dir(version)) / "mods")
    return None


def instance_profiles():
    value = registry()
    return [(vid, manifest(vid), str(Path(game_dir(vid)) / "mods"))
            for vid in value["instances"]] if value else []


def _path_owner(path):
    p = Path(path).absolute()
    base = root() / "instances"
    if not p.is_relative_to(base.absolute()):
        return None
    rel = p.relative_to(base.absolute()).parts
    if len(rel) < 2:
        return None
    folder = base / rel[0]
    data = _read(folder / "instance.json", {})
    if data.get("layout") != 2:
        return None
    names = (*CONTENT_DIRS, ".cubeon") if data.get("game_subdir") == "." else ("minecraft", ".cubeon")
    return folder if rel[1] in names else None


def owns_path(path) -> bool:
    return _path_owner(path) is not None


def pending_versions():
    value = registry()
    if not value:
        return []
    return [vid for vid in value["legacy"] if vid not in value["instances"]
            and (Path(runtime_dir()) / "versions" / vid).is_dir()
            and vid != "cubeon-rust-26.3"]


def needs_migration():
    return bool(pending_versions() or cleanup_pending())


def cleanup_pending():
    """Offer the missing cleanup step to installations migrated by older builds."""
    value = registry()
    if not value or not value["legacy"] or value.get("content_cleanup") == 1:
        return False
    if any(os.path.lexists(root() / name) for name in _LEGACY_CONTENT_DIRS):
        return True
    cleanup = _read(root() / "instances" / "migration.json", {}).get("cleanup", {})
    return bool(cleanup and cleanup.get("phase") != "complete")


def metadata_path(profile, name):
    _name(name)
    p = Path(profile)
    owner = _path_owner(p)
    if owner is not None and p.name == "mods":
        return str(_owned(owner, ".cubeon", "mods", name))
    return str(p / name)


def reconcile_mod_removals(profile, loader=None):
    with _receipt_mutex:
        return _reconcile_mod_removals(profile, loader)


def record_installed_file(destination):
    p = Path(destination)
    if p.parent.name != "mods" or not owns_path(p) or not p.name.endswith((".jar", ".jar.disabled")):
        return
    from . import mods
    details = mods.read_mod_metadata(str(p)) or {}
    with _receipt_mutex:
        receipt = Path(metadata_path(str(p.parent), "installed-files.json"))
        data = _read(receipt, {"files": {}, "removed": []})
        name = p.name.removesuffix(".disabled")
        data["files"][name] = {k: details.get(k) for k in ("slug", "project_id", "id", "name")}
        data["removed"] = [n for n in data["removed"] if n != name]
        write_json(str(receipt), data)


def _reconcile_mod_removals(profile, loader=None):
    """Remember changes made in a file manager before automatic mod preparation."""
    if not owns_path(profile):
        return {}
    from . import mods, perf_mods
    assert_writable()
    receipt = Path(metadata_path(profile, "installed-files.json"))
    prior = _read(receipt, {"files": {}, "removed": []})
    current = {}
    removed = set(prior.get("removed", []))
    for p in Path(profile).glob("*.jar*"):
        if not p.is_file() or not p.name.endswith((".jar", ".jar.disabled")):
            continue
        name = p.name.removesuffix(".disabled")
        meta = mods._read_meta(profile, p.name) or mods.read_mod_metadata(str(p), loader) or {}
        current[name] = {key: meta.get(key) for key in ("slug", "project_id", "id", "name")}
        removed.discard(name)
    for name, meta in prior.get("files", {}).items():
        if name not in current:
            identities = {str(meta.get(key) or "").lower() for key in ("id", "slug", "project_id")} - {""}
            if any(identities & {str(other.get(key) or "").lower() for key in ("id", "slug", "project_id")}
                   for other in current.values()):
                continue  # A newer build replaced this filename, not a manual opt-out.
            perf_mods.remember_removal(profile, name, meta, loader)
            removed.add(name)
    updated = {"files": current, "removed": sorted(removed)}
    if updated != prior:
        write_json(str(receipt), updated)
    return updated


def managed_removed(profile, prefix):
    if any(p.name.lower().startswith(prefix) for p in Path(profile).glob("*.jar")):
        return False
    if any(p.name.lower().startswith(prefix) for p in Path(profile).glob("*.jar.disabled")):
        return True
    data = _read(Path(metadata_path(profile, "installed-files.json")), {})
    return any(name.lower().startswith(prefix) for name in data.get("removed", []))


def _digest(path, cancel=None):
    h = hashlib.sha256()
    with open(path, "rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            if cancel and cancel.is_set():
                raise InterruptedError("Migration paused. Original files are kept.")
            h.update(chunk)
    return h.hexdigest()


def _tree(source: Path, prefix: str, allowed: tuple[Path, ...], *, hash_files=True, cancel=None):
    """Materialize managed links; reject cycles, outside links and special files."""
    out = []
    def visit(path, rel, ancestors):
        if cancel and cancel.is_set():
            raise InterruptedError("Migration scan stopped.")
        resolved = path.resolve(strict=True)
        if not any(resolved.is_relative_to(base.resolve()) for base in allowed):
            raise ValueError(f"Review this link before migrating: {path}")
        info = path.stat()
        if stat.S_ISDIR(info.st_mode):
            if resolved in ancestors:
                raise ValueError(f"Circular folder link: {path}")
            out.append({"source": str(path), "relative": rel, "directory": True,
                        "children": sorted(child.name for child in path.iterdir())})
            for child in sorted(path.iterdir()):
                visit(child, f"{rel}/{child.name}" if rel else child.name, ancestors | {resolved})
        elif stat.S_ISREG(info.st_mode):
            out.append({"source": str(path), "relative": rel, "size": info.st_size,
                        "stamp": [info.st_size, info.st_mtime_ns], "sha256": _digest(path, cancel) if hash_files else None})
        else:
            raise ValueError(f"Unsupported file; original kept: {path}")
    if source.exists() or source.is_symlink():
        visit(source, prefix, set())
    return out


def _content_identity(path):
    try:
        info = path.lstat()
    except FileNotFoundError:
        return None
    return [info.st_dev, info.st_ino, info.st_mode, str(path.resolve())]


def inventory(*, progress=None, hash_files=True, cancel=None):
    """Plan content copies only; never scan worlds, settings or runtime files."""
    from . import mods, versions, instances
    value = registry()
    if value is None:
        raise RuntimeError("Storage has not been initialized.")
    pending = pending_versions()
    allowed = (root(), Path(paths.PROFILES_DIR))
    plans = []
    for vid in pending:
        if progress:
            progress("Checking files", len(plans), len(pending))
        mc = versions.resolve_mc_version(vid)
        loader = instances.detect_loader(vid)
        meta = mods.read_instance_meta(vid) or {"mc_version": mc, "loader": loader}
        old = Path(paths.game_dir_for(vid, create=False))
        if old.parent != root() / "instances":
            raise ValueError(f"Keep the existing game folder and review its content paths: {old}")
        _owned(root() / "instances", old.name)
        profile = Path(mods.resolve_profile_dir(mc, loader, vid))
        entries = []
        watched = {}
        # Known content links use this instance's profile, not launch staging.
        for name in CONTENT_DIRS:
            source = profile if name == "mods" else profile / name
            local = old / name
            sources = [source]
            # Materialize local content links too, but never copy another
            # instance's last-launch staging from the shared root.
            if local.exists() and local.resolve() != (root() / name).resolve() and local.resolve() != source.resolve():
                sources.append(local)
            for source in sources:
                if not source.exists():
                    watched[str(source)] = None
                    continue
                if not source.is_dir():
                    raise ValueError(f"Expected a content folder: {source}")
                watched[str(source)] = sorted(c.name for c in source.iterdir())
                for child in sorted(source.iterdir()):
                    if name == "mods" and child.name in ("resourcepacks", "shaderpacks"):
                        continue
                    is_meta = (name == "mods" and (child.name.endswith(paths.MOD_META_SUFFIX)
                               or child.name in ("_profile.json", "_modpack.json")
                               or child.name.startswith(".cubeon-") and child.name.endswith(".json")))
                    prefix = ".cubeon/mods" if is_meta else name
                    entries += _tree(child, f"{prefix}/{child.name}", allowed, hash_files=hash_files, cancel=cancel)
        unique = {}
        for entry in entries:
            rel = entry["relative"]
            previous = unique.get(rel)
            if previous and (previous.get("directory") != entry.get("directory")
                             or previous.get("size") != entry.get("size")
                             or previous.get("sha256") != entry.get("sha256")):
                raise ValueError(f"Conflicting files for {vid}: {rel}. Originals are unchanged; choose which to keep first.")
            unique[rel] = entry
        plans.append({"version_id": vid, "meta": meta, "legacy_game_dir": str(old),
                      "files": list(unique.values()),
                      "watched": watched,
                      "content_links": {name: _content_identity(old / name) for name in CONTENT_DIRS}})
    return {"scope": _CONTENT_SCOPE, "instances": plans, "hashed": hash_files,
            "cleanup": cleanup_pending(),
            "bytes": sum(e.get("size", 0) for p in plans for e in p["files"])}


@contextmanager
def _disk_lock():
    folder = root() / "instances"
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / ".migration.lock").open("a+b") as handle:
        try:
            if os.name == "nt":
                import msvcrt
                handle.seek(0)
                handle.write(b"0")
                handle.flush()
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as error:
            raise RuntimeError("Another Cubeon session is organizing these files.") from error
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


def register_session():
    global _session_file
    import atexit
    if _session_file is not None and _session_file.parent.parent.parent == root():
        return
    folder = root() / "instances" / ".sessions"
    folder.mkdir(parents=True, exist_ok=True)
    _session_file = folder / f"{os.getpid()}-{uuid.uuid4().hex}.json"
    with _disk_lock():
        from .watchdog import _process_identity
        write_json(str(_session_file), {"pid": os.getpid(), "identity": _process_identity(os.getpid())})
    path = _session_file
    atexit.register(lambda: path.unlink(missing_ok=True))


def _check_idle():
    from . import watchdog, versions, modpacks
    if watchdog.stale_session() is not None or versions.active_installs() or modpacks.active_pack_installs():
        raise RuntimeError("Close Minecraft and wait for installations to finish before migrating.")
    from ui.install_feedback import any_busy
    if any_busy():
        raise RuntimeError("Wait for mod and pack downloads to finish before migrating.")
    import psutil
    for process in psutil.process_iter(["name", "cmdline"]):
        try:
            if not str(process.info["name"] or "").lower().startswith(("java", "javaw")):
                continue
            args = process.info["cmdline"] or []
            for n, arg in enumerate(args[:-1]):
                if arg == "--gameDir" and Path(args[n + 1]).resolve().is_relative_to(root().resolve()):
                    raise RuntimeError("A Minecraft process is still using these files. Close it before migrating.")
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    for p in (root() / "instances" / ".sessions").glob("*.json"):
        data = _read(p)
        pid = data.get("pid") if data else None
        if not isinstance(pid, int) or pid <= 0 or pid == os.getpid():
            continue
        import psutil
        try:
            process = psutil.Process(pid)
            actual = {"created": process.create_time(), "boot": psutil.boot_time()}
            if process.is_running() and process.status() != psutil.STATUS_ZOMBIE and actual == data.get("identity"):
                raise RuntimeError("Close the other Cubeon launcher window before migrating.")
        except psutil.NoSuchProcess:
            continue
        except psutil.AccessDenied as error:
            raise RuntimeError("Cannot verify another Cubeon session. Close it before migrating.") from error


def _copy_verified(entries, target, progress, cancel):
    target.mkdir(parents=True, exist_ok=True)
    for n, entry in enumerate(entries):
        if cancel and cancel.is_set():
            raise InterruptedError("Migration paused. Original files are kept; reopen Cubeon to resume.")
        rel = Path(entry["relative"])
        if rel.is_absolute() or ".." in rel.parts:
            raise ValueError("Unsafe migration destination.")
        dest = _owned(target, *rel.parts)
        if entry.get("directory"):
            dest.mkdir(parents=True, exist_ok=True)
            continue
        source = Path(entry["source"])
        if progress:
            progress("Copying files", n, len(entries))
        dest.parent.mkdir(parents=True, exist_ok=True)
        if not dest.is_file() or _digest(dest) != entry["sha256"]:
            fd, temp_name = tempfile.mkstemp(prefix=".cubeon-copy-", dir=dest.parent)
            tmp = Path(temp_name)
            try:
                with os.fdopen(fd, "wb") as out, source.open("rb") as inp:
                    for chunk in iter(lambda: inp.read(1024 * 1024), b""):
                        if cancel and cancel.is_set():
                            raise InterruptedError("Migration paused. Original files are kept.")
                        out.write(chunk)
                    out.flush()
                    os.fsync(out.fileno())
                if _digest(tmp) != entry["sha256"]:
                    raise RuntimeError(f"File changed during migration: {source}")
                shutil.copystat(source, tmp)
                os.replace(tmp, dest)
            finally:
                tmp.unlink(missing_ok=True)
        if progress:
            progress("Verifying files", n + 1, len(entries))
        if _digest(source) != entry["sha256"] or _digest(dest) != entry["sha256"]:
            raise RuntimeError(f"Verification failed: {source}. Original files are kept.")


def _verify_sources(entries, watched=None):
    for source, children in (watched or {}).items():
        current = sorted(p.name for p in Path(source).iterdir()) if Path(source).is_dir() else None
        if current != children:
            raise RuntimeError(f"Folder changed during migration: {source}. Scan again before retrying.")
    for entry in entries:
        source = Path(entry["source"])
        if entry.get("directory"):
            if sorted(p.name for p in source.iterdir()) != entry["children"]:
                raise RuntimeError(f"Folder changed during migration: {source}")
        elif _digest(source) != entry["sha256"]:
            raise RuntimeError(f"File changed during migration: {source}")


def _slot(game, relative):
    """Validate parents, but allow the final legacy link to be renamed intact."""
    if relative not in _SWITCH_SLOTS:
        raise ValueError("Invalid content migration slot.")
    rel = Path(relative)
    parent = game if rel.parent == Path(".") else _owned(game, *rel.parent.parts)
    return parent / rel.name


def _exists(path):
    return os.path.lexists(path)


def _rollback_switch(transaction):
    game = _owned(root() / "instances", _name(transaction["ident"]))
    stage = _owned(root() / "instances", ".content-migration", _name(transaction["stage_id"]))
    backup = _owned(root(), "backups", "legacy-content", _name(transaction["backup_id"]))
    for slot in reversed(transaction["slots"]):
        relative = slot["relative"]
        target = _slot(game, relative)
        staged = _slot(stage, relative)
        original = _slot(backup, relative)
        # Each move is recoverable from its two endpoints, including a process
        # dying before the next journal write. Never traverse a saved junction.
        if not _exists(staged):
            if not _exists(target):
                raise RuntimeError(f"Missing migration copy: {target}. Keep recovery folders and retry.")
            staged.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, staged)
        if _exists(original):
            if _exists(target):
                raise RuntimeError(f"Recovery destination changed: {target}. Keep both copies for review.")
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(original, target)
        elif slot["existed"] and not _exists(target):
            raise RuntimeError(f"Missing original content: {target}. Keep recovery folders for review.")


def _recover_content_switch():
    journal_path = root() / "instances" / "migration.json"
    journal = _read(journal_path, {})
    transaction = journal.get("switch") if journal.get("scope") == _CONTENT_SCOPE else None
    if not transaction:
        return
    # Called before startup jobs, so legacy launch sync cannot run against a
    # half-published set of folders after a killed migration process.
    with _disk_lock():
        _check_idle()
        value = registry()
        if value["instances"].get(transaction["version_id"]) != transaction["ident"]:
            _rollback_switch(transaction)
        journal.pop("switch")
        write_json(str(journal_path), journal)


def _verify_content_independence(cancel=None):
    """No active content may depend on the folders about to leave the root."""
    if pending_versions():
        raise RuntimeError("Finish migrating every instance before cleaning up old content.")
    for vid, _meta, _profile in instance_profiles():
        game = Path(game_dir(vid))
        for name in CONTENT_DIRS:
            folder = _owned(game, name)
            if not folder.is_dir():
                raise RuntimeError(f"Missing instance content folder: {folder}. Old content is kept.")
            for base, dirs, files in os.walk(folder, followlinks=False):
                if cancel and cancel.is_set():
                    raise InterruptedError("Cleanup paused. Old content is kept for recovery.")
                for entry in dirs + files:
                    path = Path(base) / entry
                    if path.is_symlink() or getattr(os.path, "isjunction", lambda _: False)(path):
                        raise RuntimeError(f"Instance content still uses a link: {path}. Old folders are kept; resolve this link before cleanup.")


def _archive_legacy_content(journal, *, progress=None, cancel=None):
    """Finish a verified migration by moving obsolete content out of the root.

    Whole-folder renames preserve every original byte and need no duplicate
    disk space. The journal makes each rename resumable after interruption.
    Only the five former content stores/staging folders are eligible.
    """
    global _restart_required
    value = registry()
    if not value["legacy"] or value.get("content_cleanup") == 1:
        return {"archived": [], "backup": value.get("content_backup")}
    _check_idle()
    _verify_content_independence(cancel)
    cleanup = journal.get("cleanup")
    if cleanup is None:
        folders = [name for name in _LEGACY_CONTENT_DIRS if _exists(root() / name)]
        cleanup = {"phase": "moving", "archive": "shared-" + uuid.uuid4().hex[:12],
                   "folders": folders, "moved": [],
                   "identities": {name: _content_identity(root() / name)[:3] for name in folders}}
        journal["cleanup"] = cleanup
    if (not isinstance(cleanup.get("folders"), list)
            or any(name not in _LEGACY_CONTENT_DIRS for name in cleanup["folders"])):
        raise RuntimeError("Invalid content cleanup record. No old folders were removed.")
    backup = _owned(root(), "backups", "legacy-content", _name(cleanup["archive"]))
    journal_path = root() / "instances" / "migration.json"
    # Validate every endpoint before moving the first folder. Unknown backup
    # destinations and redirected source folders must never be overwritten.
    for name in cleanup["folders"]:
        source, target = _owned(root(), name), _owned(backup, name)
        if _exists(source) and _exists(target):
            raise RuntimeError(f"Both old and recovery folders exist for {name}. Keep both for review.")
        if not _exists(source) and not _exists(target):
            raise RuntimeError(f"Cannot find the old or recovery folder for {name}. Keep your backups and retry.")
        existing = source if _exists(source) else target
        if _content_identity(existing)[:3] != cleanup.get("identities", {}).get(name):
            raise RuntimeError(f"The {name} folder changed after cleanup started. Keep both locations for review.")
    write_json(str(journal_path), journal)  # intent before any rename
    if cleanup["folders"]:
        write_json(str(backup / "recovery.json"), {
            "schema": 1, "original_root": str(root()), "folders": cleanup["folders"],
            "note": "Original global content from before instance migration. Active content is in instances/. "
                    "To recover the old layout, close Cubeon and restore these folder names to original_root. "
                    "Preserved legacy profile links resolve again after restoring those paths."})
    for index, name in enumerate(cleanup["folders"]):
        if cancel and cancel.is_set():
            raise InterruptedError("Cleanup paused. Reopen Organize Minecraft files to finish; originals remain in the root or recovery folder.")
        if progress:
            progress("Cleaning up old content folders", index, len(cleanup["folders"]))
        source, target = _owned(root(), name), _owned(backup, name)
        if _exists(source):
            os.replace(source, target)
            _restart_required = True
        # If the process stopped after the rename, the existing destination
        # is its preserved original; record it and continue with the rest.
        if name not in cleanup["moved"]:
            cleanup["moved"].append(name)
        write_json(str(journal_path), journal)
    value = registry()
    value["content_cleanup"] = 1
    value["content_backup"] = str(backup.relative_to(root())) if cleanup["folders"] else None
    write_json(str(registry_path()), value)
    if cleanup["folders"]:
        _restart_required = True
    cleanup["phase"] = "complete"
    write_json(str(journal_path), journal)
    if progress:
        progress("Old content folders organized", len(cleanup["folders"]), len(cleanup["folders"]))
    return {"archived": list(cleanup["folders"]), "backup": value["content_backup"]}


def migrate(plan, *, progress=None, cancel=None):
    """Replace only content folders, retaining the exact existing game directory."""
    global _blocked, _owner, _restart_required
    with _migration_mutex, _disk_lock():
        if blocked():
            raise RuntimeError("Restart Cubeon before continuing migration.")
        _blocked, _owner = True, threading.get_ident()
        journal_path = root() / "instances" / "migration.json"
        try:
            _check_idle()
            organize_instances = bool(plan.get("organize_instances"))
            instance_labels = plan.get("instance_labels")
            # Old UI plans must never re-enable the former whole-game migration.
            if plan.get("scope") != _CONTENT_SCOPE or not plan.get("hashed", False):
                plan = inventory(progress=progress, cancel=cancel)
            paths.ensure_disk_space(str(root()), plan["bytes"], "Minecraft content migration")
            journal = _read(journal_path, {})
            if journal.get("scope") != _CONTENT_SCOPE:
                if journal:
                    saved = _owned(root() / "instances", ".content-migration", "previous-journal-" + uuid.uuid4().hex + ".json")
                    write_json(str(saved), journal)
                journal = {"schema": 2, "scope": _CONTENT_SCOPE, "committed": [], "pending": {}}
            if journal.get("switch"):
                raise RuntimeError("Restart Cubeon to recover the interrupted content switch.")
            write_json(str(journal_path), journal)
            migrated = 0
            for item in plan["instances"]:
                vid = _name(item["version_id"])
                value = registry()
                if vid in value["instances"]:
                    continue  # Already committed, including the previous nested layout.
                if cancel and cancel.is_set():
                    raise InterruptedError("Migration paused. Original content is still active.")
                game = Path(item["legacy_game_dir"])
                if game != Path(paths.game_dir_for(vid, create=False)) or game.parent != root() / "instances":
                    raise RuntimeError("The game folder changed. Scan again before retrying.")
                ident = _name(game.name)
                _owned(root() / "instances", ident)
                stage_id = journal["pending"].get(vid) or ident + "-" + uuid.uuid4().hex[:12]
                journal["pending"][vid] = _name(stage_id)
                journal["phase"] = "copying"
                write_json(str(journal_path), journal)
                stage = _owned(root() / "instances", ".content-migration", stage_id)
                signature = hashlib.sha256(json.dumps(item, sort_keys=True).encode()).hexdigest()
                transfer = stage / "transfer.json"
                if stage.exists() and _read(transfer, {}).get("signature") != signature:
                    recovery = _owned(root(), "backups", "interrupted-migration", stage_id + "-" + uuid.uuid4().hex[:8])
                    recovery.parent.mkdir(parents=True, exist_ok=True)
                    os.replace(stage, recovery)
                write_json(str(transfer), {"signature": signature})
                _copy_verified(item["files"], stage, progress, cancel)
                _verify_sources(item["files"], item.get("watched"))
                if any(_content_identity(game / name) != target for name, target in item["content_links"].items()):
                    raise RuntimeError("Content links changed. Scan again before retrying.")
                _check_idle()
                for name in CONTENT_DIRS:
                    (stage / name).mkdir(parents=True, exist_ok=True)
                data = {**item["meta"], "layout": 2, "id": ident, "profile": ident, "version_id": vid,
                        "game_subdir": ".", "legacy_profile": item["meta"].get("profile"),
                        "legacy_game_dir": str(game)}
                write_json(str(stage / "instance.json"), data)
                from . import mods
                receipt_files = {}
                for jar in (stage / "mods").glob("*.jar*"):
                    if jar.is_file() and jar.name.endswith((".jar", ".jar.disabled")):
                        name = jar.name.removesuffix(".disabled")
                        details = _read(stage / ".cubeon" / "mods" / (name + paths.MOD_META_SUFFIX), {})
                        details = details or mods.read_mod_metadata(str(jar), data.get("loader")) or {}
                        receipt_files[name] = {k: details.get(k) for k in ("slug", "project_id", "id", "name")}
                write_json(str(stage / ".cubeon" / "mods" / "installed-files.json"),
                           {"files": receipt_files, "removed": []})
                # Refuse unrelated launcher metadata instead of overwriting it.
                for relative in ("instance.json", ".cubeon/mods"):
                    if _exists(_slot(game, relative)):
                        raise RuntimeError(f"Existing instance metadata needs review: {game / relative}")
                backup_id = stage_id + "-" + uuid.uuid4().hex[:8]
                backup = _owned(root(), "backups", "legacy-content", backup_id)
                transaction = {"version_id": vid, "ident": ident, "stage_id": stage_id, "backup_id": backup_id,
                               "slots": [{"relative": relative, "existed": _exists(_slot(game, relative))}
                                         for relative in _SWITCH_SLOTS]}
                if cancel and cancel.is_set():
                    raise InterruptedError("Migration paused. Original content is still active.")
                journal["switch"] = transaction
                write_json(str(journal_path), journal)  # intent before the first rename
                try:
                    for slot in transaction["slots"]:
                        relative = slot["relative"]
                        target = _slot(game, relative)
                        saved = _slot(backup, relative)
                        target.parent.mkdir(parents=True, exist_ok=True)
                        if slot["existed"]:
                            saved.parent.mkdir(parents=True, exist_ok=True)
                            os.replace(target, saved)
                        os.replace(_slot(stage, relative), target)
                    value["instances"][vid] = ident
                    write_json(str(registry_path()), value)  # atomic ownership switch
                except BaseException:
                    if registry()["instances"].get(vid) == ident:
                        _restart_required = True
                    else:
                        try:
                            _rollback_switch(transaction)
                            journal.pop("switch")
                            write_json(str(journal_path), journal)
                        except BaseException:
                            _restart_required = True
                            raise
                    raise
                _restart_required = True
                migrated += 1
                journal.pop("switch")
                journal["committed"].append(vid)
                journal["pending"].pop(vid, None)
                write_json(str(journal_path), journal)
            cleanup = {"archived": [], "backup": None}
            if not pending_versions():
                cleanup = _archive_legacy_content(journal, progress=progress, cancel=cancel)
            organization = {}
            if organize_instances:
                from . import storage_layout
                organization = storage_layout.organize_locked(labels=instance_labels, progress=progress, cancel=cancel)
            journal["phase"] = "complete" if not needs_migration() else "paused"
            write_json(str(journal_path), journal)
            return {"migrated": migrated, "pending": len(pending_versions()), **cleanup, **organization}
        finally:
            _blocked, _owner = False, None
