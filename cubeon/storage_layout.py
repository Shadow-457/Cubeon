"""Readable instance folders with the shared Minecraft runtime inside Instances.

Only explicit organization moves existing folders. Moves are journaled before
they happen; startup recovers interrupted moves before any game work begins.
"""
from __future__ import annotations

import os
from pathlib import Path
import re

from . import storage
from .atomicio import write_json

_RUNTIME_PARTS = ("assets", "libraries", "versions")


def runtime_root(layout):
    if layout == "legacy":
        return storage.root()
    if layout == "runtime":
        return storage.root() / "runtime"
    if layout == "instances":
        return storage.root() / "instances" / ".runtime"
    raise ValueError("Unknown runtime layout.")


def folder_label(version_id, meta=None, label=None):
    from .instances import detect_loader
    from .versions import extract_mc_version
    meta = meta or {}
    name = label or meta.get("name")
    if not name:
        mc = meta.get("mc_version") or extract_mc_version(version_id)
        loader = meta.get("loader") or detect_loader(version_id)
        loader_name = {"neoforge": "NeoForge", "liteloader": "LiteLoader"}.get(loader, loader.title())
        name = str(mc) if loader == "vanilla" else f"{mc}-{loader_name}"
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "-", str(name)).strip(" .")[:64].rstrip(" .")
    name = name or "Minecraft"
    if name.split(".", 1)[0].upper() in {"CON", "PRN", "AUX", "NUL", *(f"COM{n}" for n in range(1, 10)), *(f"LPT{n}" for n in range(1, 10))}:
        name = "Minecraft-" + name
    return name


def new_folder_name(version_id, suffix):
    """Deterministic before creation too; optional install metadata cannot change it."""
    base = folder_label(version_id)
    parent = storage.root() / "instances"
    occupied = {p.name.casefold() for p in parent.iterdir()} if parent.exists() else set()
    return base if base.casefold() not in occupied else base + "-" + suffix[:8]


def plan(labels=None):
    value = storage.registry()
    if value is None:
        return {"runtime": False, "renames": []}
    parent = storage.root() / "instances"
    occupied = {p.name.casefold() for p in parent.iterdir()} if parent.exists() else set()
    renames = []
    for vid, old in sorted(value["instances"].items()):
        meta = storage.manifest(vid)
        if meta.get("folder_name_version") == 1:
            continue
        base = folder_label(vid, meta, (labels or {}).get(vid))
        if old == base:
            continue
        name, index = base, 2
        while name.casefold() in occupied:
            name = f"{base}-{index}"
            index += 1
        occupied.add(name.casefold())
        renames.append({"version_id": vid, "old": old, "new": name})
    return {"runtime": value["runtime"] != "instances", "renames": renames}


def needed(labels=None):
    proposal = plan(labels)
    return bool(proposal["runtime"] or proposal["renames"])


def _journal_path():
    return storage.root() / "instances" / "layout-migration.json"


def _identity(path):
    info = path.lstat()
    return [info.st_dev, info.st_ino, info.st_mode]


def _rename_paths(item):
    parent = storage.root() / "instances"
    return (storage._owned(parent, storage._name(item["old"])),
            storage._owned(parent, storage._name(item["new"])))


def _rollback_rename(item):
    source, target = _rename_paths(item)
    if source.exists() and target.exists():
        raise RuntimeError("Both instance folders exist after an interrupted rename. Keep both for review.")
    current = source if source.exists() else target
    if not current.is_dir() or _identity(current) != item["identity"]:
        raise RuntimeError("The instance folder changed during organization. Keep your files for recovery.")
    if current == target:
        os.replace(target, source)
    write_json(str(source / "instance.json"), item["before"])


def _rollback_runtime(item):
    source_root = runtime_root(item["previous"])
    destination = runtime_root("instances")
    for name in reversed(item["folders"]):
        if name not in _RUNTIME_PARTS:
            raise ValueError("Invalid runtime migration folder.")
        source = storage._owned(source_root, name)
        target = storage._owned(destination, name)
        if source.exists() and target.exists():
            raise RuntimeError("Both runtime folders exist after an interruption. Keep both for review.")
        current = source if source.exists() else target
        if not current.is_dir() or _identity(current) != item["identities"][name]:
            raise RuntimeError("A runtime folder changed during organization. Keep your files for recovery.")
        if current == target:
            source.parent.mkdir(parents=True, exist_ok=True)
            os.replace(target, source)


def recover():
    journal = storage._read(_journal_path(), {})
    if not journal.get("rename") and not journal.get("runtime"):
        return
    with storage._disk_lock():
        storage._check_idle()
        item = journal.get("rename")
        if item:
            if storage.registry()["instances"].get(item["version_id"]) != item["new"]:
                _rollback_rename(item)
            journal.pop("rename")
        item = journal.get("runtime")
        if item:
            if storage.registry()["runtime"] != "instances":
                _rollback_runtime(item)
            journal.pop("runtime")
        write_json(str(_journal_path()), journal)


def _move_runtime(journal, progress, cancel):
    value = storage.registry()
    if value["runtime"] == "instances":
        return False
    source_root, destination = runtime_root(value["runtime"]), runtime_root("instances")
    storage._owned(storage.root(), "instances", ".runtime")
    folders = []
    for name in _RUNTIME_PARTS:
        source, target = storage._owned(source_root, name), storage._owned(destination, name)
        if target.exists():
            raise RuntimeError(f"The new shared runtime already contains {name}. Nothing was overwritten; review that folder.")
        if source.exists():
            if not source.is_dir():
                raise RuntimeError(f"Expected a runtime folder: {source}")
            folders.append(name)
    item = {"previous": value["runtime"], "folders": folders,
            "identities": {name: _identity(source_root / name) for name in folders}}
    journal["runtime"] = item
    write_json(str(_journal_path()), journal)
    destination.mkdir(parents=True, exist_ok=True)
    try:
        for index, name in enumerate(folders):
            if cancel and cancel.is_set():
                raise InterruptedError("Organization paused. The original runtime will be restored.")
            if progress:
                progress("Moving shared game files into Instances", index, len(folders))
            os.replace(source_root / name, destination / name)
        value["runtime"] = "instances"
        write_json(str(storage.registry_path()), value)
    except BaseException:
        if storage.registry()["runtime"] != "instances":
            try:
                _rollback_runtime(item)
                journal.pop("runtime")
                write_json(str(_journal_path()), journal)
            except BaseException:
                storage._restart_required = True
                raise
        else:
            storage._restart_required = True
        raise
    storage._restart_required = True
    journal.pop("runtime")
    write_json(str(_journal_path()), journal)
    return True


def organize_locked(*, labels=None, progress=None, cancel=None):
    """Called only by storage.migrate while its write gate and disk lock are held."""
    storage._check_idle()
    if storage.pending_versions():
        raise RuntimeError("Finish migrating instance content before organizing folders.")
    journal = storage._read(_journal_path(), {"schema": 1})
    if journal.get("rename") or journal.get("runtime"):
        raise RuntimeError("Restart Cubeon to recover the interrupted folder move.")
    proposal = plan(labels)
    renamed = 0
    for index, move in enumerate(proposal["renames"]):
        if cancel and cancel.is_set():
            raise InterruptedError("Organization paused. Completed instances keep their folders.")
        if progress:
            progress("Giving instance folders readable names", index, len(proposal["renames"]))
        source, target = _rename_paths(move)
        if not source.is_dir() or target.exists():
            raise RuntimeError("An instance folder changed. Scan again before organizing.")
        before = storage.manifest(move["version_id"])
        old_game = str(Path(storage.game_dir(move["version_id"])))
        previous = list(dict.fromkeys([*before.get("previous_game_dirs", []), old_game]))
        after = {**before, "previous_game_dirs": previous, "folder_name_version": 1}
        item = {**move, "before": before, "identity": _identity(source)}
        journal["rename"] = item
        write_json(str(_journal_path()), journal)
        try:
            os.replace(source, target)
            write_json(str(target / "instance.json"), after)
            value = storage.registry()
            value["instances"][move["version_id"]] = move["new"]
            write_json(str(storage.registry_path()), value)
        except BaseException:
            if storage.registry()["instances"].get(move["version_id"]) != move["new"]:
                try:
                    _rollback_rename(item)
                    journal.pop("rename")
                    write_json(str(_journal_path()), journal)
                except BaseException:
                    storage._restart_required = True
                    raise
            else:
                storage._restart_required = True
            raise
        storage._restart_required = True
        renamed += 1
        journal.pop("rename")
        write_json(str(_journal_path()), journal)
    moved = _move_runtime(journal, progress, cancel)
    journal["phase"] = "complete"
    write_json(str(_journal_path()), journal)
    return {"renamed": renamed, "runtime_moved": moved, "organized": True}
