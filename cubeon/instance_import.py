"""Reviewed, copy-only imports of installed FastClient profiles.

Launcher catalogues supply version identity only. Local game runtimes are
copied without installers or network requests; account records stay behind.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import time
import uuid
import zipfile
import threading
from pathlib import PurePosixPath

_RUNTIME_LOCK = threading.Lock()


def _relative(value):
    if (not isinstance(value, str) or not value or "\\" in value or ":" in value
            or any(ord(c) < 32 for c in value)):
        raise ValueError("Invalid local runtime path.")
    parts = PurePosixPath(value).parts
    if not parts or value.startswith("/") or any(p in (".", "..") for p in parts):
        raise ValueError("A runtime path leaves its folder.")
    return Path(*parts)


def _without_nulls(value):
    # FastClient serializes absent optional fields as null. MLL expects those
    # keys to be absent (notably library rules/natives and minecraftArguments).
    if isinstance(value, dict):
        return {k: _without_nulls(v) for k, v in value.items() if v is not None}
    if isinstance(value, list):
        return [_without_nulls(v) for v in value if v is not None]
    return value


def _runtime_inventory(profile, event=None):
    from minecraft_launcher_lib._helper import get_library_path, parse_rule_list

    directory = Path(profile["directory"])
    roots = {}
    for slot in ("versions", "libraries", "assets"):
        path = directory / slot
        if not path.exists():
            path = directory.parent.parent / slot
        # Only these three explicit FastClient runtime links are followed.
        # Game content still refuses every link.
        roots[slot] = path.resolve()
    versions_root = roots["versions"]
    mc, loader, build = profile["mc_version"], profile["loader"], profile["loader_version"]
    if not versions_root.is_dir():
        raise ValueError("FastClient's local game runtime is missing. Import needs its installed files; nothing will be downloaded.")

    def read_version(ident):
        _identity(ident, "runtime version")
        path = versions_root / ident / f"{ident}.json"
        if _linked(path) or _linked(path.parent):
            raise ValueError("A FastClient version file is redirected outside its runtime.")
        return _without_nulls(_json(path, 16 * 1024 * 1024))

    source_id = mc if loader == "vanilla" else None
    if loader != "vanilla":
        coordinates = {"fabric": f"net.fabricmc:fabric-loader:{build}",
                       "quilt": f"org.quiltmc:quilt-loader:{build}",
                       "forge": f"net.minecraftforge:forge:{mc}-{build}",
                       "neoforge": f"net.neoforged:neoforge:{build}"}
        for folder in sorted(versions_root.iterdir()):
            _check_cancel(event)
            if not folder.is_dir() or _linked(folder):
                continue
            try:
                data = read_version(folder.name)
            except (ValueError, OSError):
                continue
            libraries = data.get("libraries", [])
            names = [l.get("name", "") for l in libraries if isinstance(l, dict)]
            match = coordinates[loader]
            if data.get("inheritsFrom") == mc and any(n == match or n.startswith(match + ":") for n in names):
                source_id = folder.name
                break
        if source_id is None:
            raise ValueError(f"FastClient's installed {loader.title()} {build} for {mc} is missing. Nothing will be downloaded.")

    shared, version_entries, seen, library_keys = {}, [], set(), set()

    def file_entry(slot, rel, info=None):
        rel = _relative(rel)
        root = roots[slot]
        source = root / rel
        if source.resolve() != source.absolute() or not source.is_file():
            raise ValueError(f"FastClient is missing a regular local runtime file: {slot}/{rel.as_posix()}. Nothing will be downloaded.")
        expected = info or {}
        size, sha1 = expected.get("size"), expected.get("sha1")
        if size is not None and (type(size) is not int or size < 0 or source.stat().st_size != size):
            raise ValueError(f"FastClient's local runtime file is incomplete: {slot}/{rel.as_posix()}")
        if sha1 is not None and (not isinstance(sha1, str) or not re.fullmatch(r"[0-9a-fA-F]{40}", sha1)):
            raise ValueError("Invalid runtime checksum.")
        return {"source": str(source), "relative": f"{slot}/{rel.as_posix()}",
                "stamp": _stamp(source.stat()), "sha1": sha1}

    def add_shared(slot, rel, info=None):
        entry = file_entry(slot, rel, info)
        shared.setdefault(entry["relative"], entry)

    pending = [source_id]
    while pending:
        _check_cancel(event)
        ident = pending.pop(0)
        if ident in seen:
            continue
        if len(seen) >= 16:
            raise ValueError("FastClient's version inheritance is too deep.")
        seen.add(ident)
        data = read_version(ident)
        json_entry = file_entry("versions", f"{ident}/{ident}.json")
        files = []
        base = versions_root / ident
        for path in sorted(base.rglob("*")):
            if _linked(path):
                raise ValueError("A FastClient version contains linked runtime content.")
            if path.is_file() and path.name not in (f"{ident}.json", "_cubeon_instance.json"):
                client_info = (data.get("downloads") or {}).get("client") if path.name == f"{ident}.jar" else None
                files.append(file_entry("versions", path.relative_to(versions_root).as_posix(), client_info))
        version_entries.append({"id": ident, "data": data, "json": json_entry, "files": files})
        for ref in (data.get("inheritsFrom"), data.get("jar")):
            if ref and ref != ident:
                _identity(ref, "inherited runtime")
                pending.append(ref)
        for library in data.get("libraries", []):
            if not isinstance(library, dict) or not isinstance(library.get("name"), str):
                raise ValueError("Invalid FastClient runtime library metadata.")
            # Match MLL's child-over-parent library override rules, so an
            # unused base dependency need not exist in FastClient's cache.
            key = ":".join(library["name"].split(":")[:-1])
            if key in library_keys:
                continue
            library_keys.add(key)
            if library.get("rules") and not parse_rule_list(library["rules"], {}):
                continue
            # get_library_path supplies a libraries prefix, even if the local
            # runtime library directory has a custom name/parent.
            marker = Path(get_library_path(library["name"], "/runtime"))
            rel = marker.relative_to(Path("/runtime/libraries")).as_posix()
            downloads = library.get("downloads") or {}
            info = downloads.get("artifact") or {k: library[k] for k in ("size", "sha1") if k in library}
            add_shared("libraries", rel, info)
            os_key = "windows" if sys.platform == "win32" else "osx" if sys.platform == "darwin" else "linux"
            native = (library.get("natives") or {}).get(os_key, "")
            if not isinstance(native, str):
                raise ValueError("Invalid native runtime classifier.")
            native = native.replace("${arch}", "64" if sys.maxsize > 2**32 else "32")
            if native:
                native_info = (downloads.get("classifiers") or {}).get(native)
                if native_info:
                    add_shared("libraries", native_info["path"], native_info)
                else:
                    native_rel = Path(get_library_path(library["name"] + "-" + native, "/runtime")).relative_to(Path("/runtime/libraries"))
                    add_shared("libraries", native_rel.as_posix())
        index = data.get("assetIndex")
        if index:
            index_id = _identity(index.get("id"), "asset index")
            index_rel = f"indexes/{index_id}.json"
            add_shared("assets", index_rel, index)
            asset_data = _json(roots["assets"] / index_rel, 16 * 1024 * 1024)
            objects = asset_data.get("objects")
            if not isinstance(objects, dict) or len(objects) > 100000:
                raise ValueError("Invalid FastClient local asset index.")
            for logical, obj in objects.items():
                _check_cancel(event)
                digest = obj.get("hash") if isinstance(obj, dict) else None
                if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{40}", digest):
                    raise ValueError("Invalid local asset object hash.")
                add_shared("assets", f"objects/{digest[:2]}/{digest}", {"sha1": digest, "size": obj.get("size")})
                if asset_data.get("virtual"):
                    add_shared("assets", f"virtual/{index_id}/{logical}", {"sha1": digest, "size": obj.get("size")})
        logging_file = ((data.get("logging") or {}).get("client") or {}).get("file")
        if logging_file:
            add_shared("assets", "log_configs/" + _identity(logging_file.get("id"), "logging config"), logging_file)
    if mc not in seen:
        raise ValueError("FastClient's loader does not reference the selected Minecraft version.")
    return {"source_id": source_id, "roots": {k: str(v) for k, v in roots.items()},
            "versions": version_entries, "shared": list(shared.values())}


CONTENT_DIRS = frozenset(("mods", "config", "saves", "resourcepacks", "shaderpacks",
                          "screenshots", "data", "schematics", "replay_recordings",
                          "XaeroWaypoints", "XaeroWorldMap", "journeymap"))
CONTENT_FILES = frozenset(("options.txt", "optionsof.txt", "optionsshaders.txt",
                           "servers.dat", "servers.dat_old", "command_history.txt"))
LOADERS = frozenset(("vanilla", "fabric", "quilt", "forge", "neoforge"))


class ImportCancelled(RuntimeError):
    pass


def _check_cancel(event):
    if event is not None and event.is_set():
        raise ImportCancelled("Import cancelled. Your FastClient profile was kept intact.")


def _identity(value, label):
    if (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._+\-]{0,127}", value)
            or value.endswith(".") or value.upper().split(".")[0] in
            {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)),
             *(f"LPT{i}" for i in range(1, 10))}):
        raise ValueError(f"Invalid FastClient {label}.")
    return value


def _json(path, limit):
    with Path(path).open("rb") as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError(f"FastClient metadata is too large: {Path(path).name}")
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid FastClient metadata: {Path(path).name}")
    return data


def catalogue_roots():
    home = Path.home()
    if sys.platform == "win32":
        return [Path(os.environ[key]) / "FastClient" for key in ("APPDATA", "LOCALAPPDATA")
                if os.environ.get(key)]
    if sys.platform == "darwin":
        return [home / "Library/Application Support/FastClient"]
    return [Path(os.environ.get("XDG_DATA_HOME") or home / ".local/share") / "FastClient"]


def _catalogue(path):
    data = _json(path, 4 * 1024 * 1024)
    records = data.get("profiles")
    if not isinstance(records, list):
        raise ValueError("FastClient profiles.json must contain a profiles list.")
    settings_path = path.parent / "settings.json"
    settings = _json(settings_path, 1024 * 1024) if settings_path.exists() else {}
    game_root = settings.get("gameDirectory") or str(Path.home() / ".fastclient")
    if not isinstance(game_root, str) or not game_root.strip():
        raise ValueError("Invalid FastClient game directory.")
    game_root = Path(game_root).expanduser()
    if not game_root.is_absolute():
        game_root = path.parent / game_root
    result, errors, seen = [], [], set()
    for record in records:
        try:
            if not isinstance(record, dict):
                raise ValueError("Invalid FastClient profile record.")
            ident = _identity(record.get("id"), "profile ID")
            if ident.casefold() in seen:
                raise ValueError("Duplicate FastClient profile ID.")
            seen.add(ident.casefold())
            mc = _identity(record.get("version"), "Minecraft version")
            loader = str(record.get("modLoader") or "vanilla").lower()
            if loader == "none":
                loader = "vanilla"
            if loader not in LOADERS:
                raise ValueError(f"Unsupported FastClient loader: {loader}")
            build = None if loader == "vanilla" else _identity(record.get("loaderVersion"), "loader version")
            directory = game_root / "profiles" / ident
            if not directory.is_dir():
                raise ValueError(f"FastClient profile folder is missing: {ident}")
            name = record.get("name") or ident
            if not isinstance(name, str) or len(name) > 200 or any(ord(c) < 32 for c in name):
                raise ValueError("Invalid FastClient profile name.")
            result.append({"id": ident, "name": name, "mc_version": mc, "loader": loader,
                           "loader_version": build, "directory": str(directory.absolute()),
                           "catalogue": str(path.absolute())})
        except (ValueError, OSError) as error:
            errors.append(str(error))
    return result, errors


def discover(folder=None):
    """Find catalogues automatically, or matching a chosen settings/game folder."""
    candidates = [root / "profiles.json" for root in catalogue_roots()]
    chosen = Path(folder).expanduser().absolute() if folder else None
    if chosen:
        candidates = [chosen / "profiles.json", chosen.parent / "profiles.json",
                      chosen.parent.parent / "profiles.json", *candidates]
    profiles, errors, seen = [], [], set()
    for path in candidates:
        key = str(path.absolute())
        if key in seen or not path.is_file():
            continue
        seen.add(key)
        try:
            found, problems = _catalogue(path)
            if chosen and not chosen.is_relative_to(path.parent) and chosen != path.parent:
                found = [p for p in found if Path(p["directory"]).is_relative_to(chosen)
                         or chosen == Path(p["directory"])]
            profiles.extend(found)
            errors.extend(problems)
        except (OSError, ValueError) as error:
            errors.append(str(error))
    unique = {p["directory"]: p for p in profiles}
    return {"profiles": list(unique.values()), "errors": errors}


def _current(profile):
    found, _errors = _catalogue(Path(profile["catalogue"]))
    if profile not in found:
        raise ValueError("The FastClient profile changed. Scan it again before importing.")


def _linked(path):
    return path.is_symlink() or getattr(os.path, "isjunction", lambda _p: False)(path)


def _stamp(info):
    return (info.st_dev, info.st_ino, info.st_mode, info.st_size, info.st_mtime_ns, info.st_ctime_ns)


def _hud(path):
    if not path.name.lower().endswith((".jar", ".jar.disabled")):
        return False
    try:
        with zipfile.ZipFile(path) as archive:
            info = archive.getinfo("fabric.mod.json")
            if info.file_size > 2 * 1024 * 1024:
                return False
            return json.loads(archive.read(info)).get("id") == "fastclient-hud"
    except (OSError, ValueError, KeyError, zipfile.BadZipFile, AttributeError):
        return False


def _inventory(profile, cancel_event=None):
    root = Path(profile["directory"])
    # Refuse included links, including a redirected profile root. Runtime links
    # are outside the allowlist and never traversed.
    if any(_linked(p) for p in (root, root.parent, root.parent.parent)):
        raise ValueError("FastClient's profile folder is a link. Choose its real folder.")
    files, directories, skipped = [], [], []

    def visit(path):
        _check_cancel(cancel_event)
        rel = path.relative_to(root).as_posix()
        if _linked(path):
            raise ValueError(f"Cannot safely import linked game content: {rel}. Use a regular copy.")
        info = path.lstat()
        if stat.S_ISDIR(info.st_mode):
            directories.append((rel, _stamp(info)))
            for child in sorted(path.iterdir()):
                visit(child)
        elif stat.S_ISREG(info.st_mode):
            # Launcher receipts must not supply ownership or pack identity.
            if rel.startswith("mods/") and (path.name in ("_profile.json", "_modpack.json", "_cubeon_instance.json")
                                             or path.name.endswith(".cubeon.json")):
                skipped.append(rel)
            elif rel.startswith("mods/") and _hud(path):
                skipped.append(rel)
            else:
                files.append((rel, _stamp(info)))
        else:
            raise ValueError(f"Cannot import special game file: {rel}")

    directories.append((".", _stamp(root.stat())))
    for child in sorted(root.iterdir()):
        if child.name in CONTENT_DIRS or child.name in CONTENT_FILES:
            visit(child)
    return {"files": files, "directories": directories, "skipped": skipped}


def review(profile, cancel_event=None):
    _current(profile)
    inventory = _inventory(profile, cancel_event)
    runtime = _runtime_inventory(profile, cancel_event)
    runtime_bytes = sum(e["stamp"][3] for e in runtime["shared"])
    runtime_bytes += sum(v["json"]["stamp"][3] + sum(e["stamp"][3] for e in v["files"])
                         for v in runtime["versions"])
    return {"profile": dict(profile), **inventory,
            "runtime": runtime, "runtime_bytes": runtime_bytes,
            "bytes": sum(stamp[3] for _rel, stamp in inventory["files"]),
            "mods": sum(rel.startswith("mods/") and rel.lower().endswith((".jar", ".jar.disabled"))
                        for rel, _stamp_value in inventory["files"]),
            "worlds": sum(rel.startswith("saves/") and rel.count("/") == 1
                          for rel, _stamp_value in inventory["directories"])}


def _unchanged(plan, cancel_event):
    _current(plan["profile"])
    inventory = _inventory(plan["profile"], cancel_event)
    if any(inventory[key] != plan[key] for key in ("files", "directories", "skipped")):
        raise ValueError("FastClient files changed. Close the game and scan the profile again.")
    if _runtime_inventory(plan["profile"], cancel_event) != plan["runtime"]:
        raise ValueError("FastClient's local runtime changed. Scan the profile again.")


def _digest(path, algorithm, event):
    digest = hashlib.new(algorithm)
    with Path(path).open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            _check_cancel(event)
            digest.update(chunk)
    return digest.hexdigest()


def _copy_runtime_file(entry, dest, event, report):
    source = Path(entry["source"])
    if source.resolve() != source.absolute() or _stamp(source.stat()) != entry["stamp"]:
        raise ValueError("FastClient's local runtime changed. Scan it again.")
    algorithm = "sha1" if entry.get("sha1") else "sha256"
    expected = (entry.get("sha1") or _digest(source, algorithm, event)).lower()
    if dest.exists():
        if not dest.is_file() or _digest(dest, algorithm, event) != expected:
            raise ValueError(f"Cubeon has a different runtime file: {entry['relative']}. No existing file was replaced.")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".fastclient-copy-", dir=dest.parent)
    temporary = Path(temporary)
    try:
        digest = hashlib.new(algorithm)
        with os.fdopen(fd, "wb") as output, source.open("rb") as stream:
            done = 0
            while chunk := stream.read(1024 * 1024):
                _check_cancel(event)
                digest.update(chunk)
                output.write(chunk)
                done += len(chunk)
                report(done, max(entry["stamp"][3], 1), "Copying local runtime: " + entry["relative"])
            output.flush()
            os.fsync(output.fileno())
        if digest.hexdigest() != expected or _digest(temporary, algorithm, event) != expected:
            raise ValueError(f"FastClient's local runtime failed its checksum: {entry['relative']}")
        if _stamp(source.stat()) != entry["stamp"]:
            raise ValueError("FastClient's local runtime changed during copying.")
        shutil.copystat(source, temporary)
        # Publish without replacing an existing cache file, including another
        # process's copy. Verified shared cache entries can survive cancellation.
        try:
            os.link(temporary, dest)
        except FileExistsError:
            if _digest(dest, algorithm, event) != expected:
                raise ValueError("Another install changed this runtime file. Retry the import.")
        except OSError:
            # Filesystems without hard links still reserve only a new path.
            owned = False
            try:
                with dest.open("xb") as output, temporary.open("rb") as stream:
                    owned = True
                    while chunk := stream.read(1024 * 1024):
                        _check_cancel(event)
                        output.write(chunk)
                    output.flush()
                    os.fsync(output.fileno())
            except BaseException:
                if owned:
                    dest.unlink()
                raise
    finally:
        temporary.unlink(missing_ok=True)


def _import_runtime(plan, vid, token, targets, event, report):
    from . import storage, paths, versions
    from .atomicio import write_json
    runtime_root = Path(storage.runtime_dir(paths.MINECRAFT_DIR))
    runtime_root.mkdir(parents=True, exist_ok=True)
    source_runtime = plan["runtime"]
    identities = {v["id"]: (vid if v["id"] == source_runtime["source_id"] else
                  f"{plan['profile']['mc_version']}-vanilla-fastclient-runtime-{token}-{i}")
                  for i, v in enumerate(source_runtime["versions"])}
    with _RUNTIME_LOCK:
        for entry in source_runtime["shared"]:
            _check_cancel(event)
            report(0, 0, "Reusing local runtime: " + entry["relative"])
            dest = storage._owned(runtime_root, *_relative(entry["relative"]).parts)
            _copy_runtime_file(entry, dest, event, report)
        for source in source_runtime["versions"]:
            _check_cancel(event)
            ident = identities[source["id"]]
            target = storage._owned(runtime_root, "versions", ident)
            target.mkdir(parents=True, exist_ok=False)
            targets.append(target)
            data = dict(source["data"])
            data["id"] = ident
            for field in ("inheritsFrom", "jar"):
                if field in data:
                    data[field] = identities[data[field]]
            if data.get("inheritsFrom") and "jar" not in data:
                data["jar"] = identities[plan["profile"]["mc_version"]]
            write_json(str(target / f"{ident}.json"), data)
            for entry in source["files"]:
                relative = Path(entry["source"]).relative_to(Path(source_runtime["roots"]["versions"]) / source["id"])
                if relative.as_posix() == f"{source['id']}.jar":
                    relative = Path(f"{ident}.jar")
                _copy_runtime_file(entry, storage._owned(target, *relative.parts), event, report)
        # MLL resolves natives under the launch ID, while FastClient extracts
        # them under the base game version. Materialize those local files for
        # the imported loader's own launch folder as well.
        if source_runtime["source_id"] != plan["profile"]["mc_version"]:
            base = next(v for v in source_runtime["versions"] if v["id"] == plan["profile"]["mc_version"])
            target = runtime_root / "versions" / vid
            source_base = Path(source_runtime["roots"]["versions"]) / base["id"]
            for entry in base["files"]:
                relative = Path(entry["source"]).relative_to(source_base)
                if relative.parts[0] == "natives":
                    _copy_runtime_file(entry, storage._owned(target, *relative.parts), event, report)
    versions.validate_launch_profile(vid)
    # Validate the rewritten references, rather than the source's original IDs.
    launch = _json(runtime_root / "versions" / vid / f"{vid}.json", 16 * 1024 * 1024)
    issue = versions._client_jar_problem(str(runtime_root / "versions" / vid), launch, want_sha1=True)
    if issue:
        raise RuntimeError(f"The imported local runtime is incomplete: {issue}")
    return {"built_from": [new for new in identities.values() if new != vid],
            "source_version_id": launch.get("inheritsFrom")}


def _copy(plan, stage, event, report):
    root = Path(plan["profile"]["directory"])
    for rel, _info in plan["directories"]:
        (stage / rel).mkdir(parents=True, exist_ok=True)
    done = 0
    for rel, expected in plan["files"]:
        _check_cancel(event)
        source, dest = root / rel, stage / rel
        if source.resolve() != source.absolute() or _stamp(source.lstat()) != expected:
            raise ValueError(f"FastClient file changed: {rel}. Scan again.")
        flags = os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(source, flags)
        digest = hashlib.sha256()
        with os.fdopen(fd, "rb") as src, dest.open("xb") as dst:
            if _stamp(os.fstat(src.fileno())) != expected:
                raise ValueError(f"FastClient file changed: {rel}.")
            while chunk := src.read(1024 * 1024):
                _check_cancel(event)
                digest.update(chunk)
                dst.write(chunk)
                done += len(chunk)
                report(done, max(plan["bytes"], 1), f"Copying {rel}")
            dst.flush()
            os.fsync(dst.fileno())
            if _stamp(os.fstat(src.fileno())) != expected:
                raise ValueError(f"FastClient file changed during copying: {rel}.")
        copied = hashlib.sha256()
        with dest.open("rb") as stream:
            while chunk := stream.read(1024 * 1024):
                _check_cancel(event)
                copied.update(chunk)
        if copied.digest() != digest.digest() or dest.stat().st_size != expected[3]:
            raise OSError(f"Copy verification failed: {rel}")
        shutil.copystat(source, dest, follow_symlinks=False)


def import_review(plan, *, name=None, cancel_event=None, progress=None):
    """Build one new isolated instance; failures remove only our new paths.

    Verified local runtime cache copies remain reusable. No existing game/profile,
    global RAM/Java preferences, or modpack installation policy is changed.
    """
    from . import modpacks, paths, storage

    profile = plan["profile"]
    name = (name if name is not None else profile["name"]).strip()
    if not name or len(name) > 200 or any(ord(c) < 32 for c in name):
        raise ValueError("Enter an instance name (1–200 characters).")
    mc, loader = profile["mc_version"], profile["loader"]
    _identity(mc, "Minecraft version")
    if loader not in LOADERS:
        raise ValueError("Unsupported loader.")
    if loader != "vanilla":
        _identity(profile["loader_version"], "loader version")
    token = uuid.uuid4().hex
    vid = f"{mc}-{loader}-fastclient-{token}"
    folder = None
    targets = []
    claimed = False
    last_paint = 0.0
    last_touch = 0.0

    def report(done, total, text):
        nonlocal last_paint, last_touch
        _check_cancel(cancel_event)
        now = time.monotonic()
        if now - last_touch >= 10:
            modpacks._touch_pack_install(mc, loader)
            last_touch = now
        if progress and (text == "Saving imported instance" or now - last_paint >= 0.1):
            last_paint = now
            progress(done, total, text)

    def status(text):
        report(0, 0, str(text))

    with storage.update_operation():
        storage.assert_writable()
        if not storage.enabled():
            raise RuntimeError("Restart Cubeon to initialize instance storage before importing.")
        _unchanged(plan, cancel_event)
        modpacks._mark_pack_install(mc, f"Importing {name}", loader=loader, exclusive=True,
                                   profile=vid, version_id=vid)
        claimed = True
        try:
            staging_root = storage.root() / "instances"
            paths.ensure_disk_space(str(staging_root), plan["bytes"] + plan["runtime_bytes"], "FastClient import")
            with tempfile.TemporaryDirectory(prefix=".fastclient-import-", dir=staging_root) as tmp:
                stage = Path(tmp)
                _copy(plan, stage, cancel_event, report)
                _unchanged(plan, cancel_event)
                status("Copying FastClient's local game runtime")
                runtime_meta = _import_runtime(plan, vid, token, targets, cancel_event, report)
                _unchanged(plan, cancel_event)
                status("Saving imported instance")
                meta = {"name": name, "profile": vid, "mc_version": mc, "loader": loader,
                        "loader_version": profile["loader_version"], "imported_from": "fastclient", **runtime_meta}
                candidate_folder = storage.folder_for(vid)
                if candidate_folder is None or candidate_folder.exists():
                    raise RuntimeError("Couldn't reserve a fresh instance folder.")
                folder = candidate_folder
                registered = storage.folder_for(vid, create=True, meta=meta)
                if registered is None:
                    raise RuntimeError("Couldn't register the imported instance.")
                folder = registered
                game = Path(storage.game_dir(vid))
                for entry in stage.iterdir():
                    _check_cancel(cancel_event)
                    dest = game / entry.name
                    if dest.exists():
                        dest.rmdir()  # Only empty directories from our new registration.
                    os.replace(entry, dest)
                _unchanged(plan, cancel_event)
                _check_cancel(cancel_event)
                return {"version_id": vid, "name": name, "loader": loader, "skipped": plan["skipped"]}
        except BaseException:
            # Keep the predicted new folder before registration so a failed
            # manifest/index write cannot strand an unregistered instance.
            if folder is not None and folder.exists():
                storage.discard_registration(vid, folder.name)
                shutil.rmtree(folder)
            for target in reversed(targets):
                shutil.rmtree(target)
            raise
        finally:
            if claimed:
                modpacks._unmark_pack_install(mc, loader)
