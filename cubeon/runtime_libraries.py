"""Verify declared classpath libraries before Java; repair only runtime-owned files."""
from __future__ import annotations

from collections import OrderedDict
import hashlib
import json
import os
from pathlib import Path
import re
import tempfile
import threading
import time
from urllib.parse import urlsplit
import zipfile
import zlib

from . import net, storage, versions
from .paths import MINECRAFT_DIR

_CACHE = OrderedDict()
_LOCK = threading.RLock()
_HOSTS = frozenset({"libraries.minecraft.net", "maven.fabricmc.net", "maven.quiltmc.org",
                   "maven.minecraftforge.net", "maven.neoforged.net", "repo.spongepowered.org",
                   "repo1.maven.org", "repo.maven.apache.org", "maven.architectury.dev"})


def _allowed(url):
    parts = urlsplit(url)
    return (parts.scheme == "https" and parts.hostname in _HOSTS
            and parts.username is None and parts.password is None
            and parts.port in (None, 443))


def _problem(path, info, *, full=False):
    try:
        stat = path.stat()
        expected = info.get("size")
        if type(expected) is int and expected > 0 and stat.st_size != expected:
            return "incomplete download"
        fingerprint = (str(path), stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns,
                       info.get("sha1"), expected)
        if not full and fingerprint in _CACHE:
            _CACHE.move_to_end(fingerprint)
            return None
        sha1 = info.get("sha1")
        has_checksum = isinstance(sha1, str) and re.fullmatch(r"[0-9a-fA-F]{40}", sha1)
        with zipfile.ZipFile(path) as archive:
            entries = archive.infolist()
            if not entries or sum(entry.file_size for entry in entries) > 512 * 1024 * 1024:
                return "invalid JAR archive"
            if (full or not has_checksum) and archive.testzip() is not None:
                return "damaged JAR archive"
        if has_checksum:
            digest = hashlib.sha1()
            with path.open("rb") as stream:
                for block in iter(lambda: stream.read(1024 * 1024), b""):
                    digest.update(block)
            if digest.hexdigest() != sha1.lower():
                return "checksum mismatch"
        _CACHE[fingerprint] = True
        if len(_CACHE) > 512:
            _CACHE.popitem(last=False)
        return None
    except (OSError, ValueError, zipfile.BadZipFile, RuntimeError, EOFError, zlib.error):
        return "missing or damaged JAR archive"


def _sources(version_id, runtime):
    from minecraft_launcher_lib._helper import get_library_path
    result, seen, pending = {}, set(), [version_id]
    while pending:
        current = pending.pop()
        if current in seen:
            continue
        seen.add(current)
        folder = Path(versions.version_folder(current))
        with (folder / (current + ".json")).open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        parent = data.get("inheritsFrom")
        if parent:
            pending.append(parent)
        for library in data.get("libraries", []):
            if not isinstance(library, dict) or not isinstance(library.get("name"), str):
                continue
            path = Path(get_library_path(library["name"], str(runtime)))
            downloads = library.get("downloads") or {}
            artifact = downloads.get("artifact") or {}
            info = dict(artifact)
            if not info.get("url"):
                relative = path.relative_to(runtime / "libraries").as_posix()
                info["url"] = str(library.get("url") or "https://libraries.minecraft.net/").rstrip("/") + "/" + relative
            # Child profile entries own overrides for matching coordinates.
            result.setdefault(str(path), info)
            for native in (downloads.get("classifiers") or {}).values():
                if isinstance(native, dict) and isinstance(native.get("path"), str):
                    result.setdefault(str(runtime / "libraries" / native["path"]), dict(native))
    return result


def ensure(version_id, command, status_cb=None):
    """Bounded, stat-cached Play check; no world/mod/config or external-path writes."""
    classpath = []
    for index, arg in enumerate(command[:-1]):
        if arg in {"-cp", "-classpath", "--class-path", "--module-path", "-p"}:
            classpath.extend(command[index + 1].split(os.pathsep))
    if not classpath:
        return 0
    versions.validate_launch_profile(version_id)
    runtime = Path(storage.runtime_dir(MINECRAFT_DIR)).absolute()
    root = runtime / "libraries"
    repaired = 0
    deadline = time.monotonic() + 60
    with _LOCK:
        sources = _sources(version_id, runtime)
        for entry in dict.fromkeys(classpath):
            path = Path(entry).absolute()
            if path.suffix.lower() != ".jar" or not path.is_relative_to(root):
                continue
            if not path.resolve().is_relative_to(root.resolve()):
                raise RuntimeError("A runtime library points outside the runtime folder. Repair this instance first.")
            info = sources.get(str(path))
            if info is None:
                continue  # Custom classpath content is not owned by the launcher.
            problem = _problem(path, info)
            if problem is None:
                continue
            if repaired >= 16 or time.monotonic() >= deadline:
                raise RuntimeError("Runtime library repair limit reached. Press Play again to continue.")
            url = info.get("url")
            if not isinstance(url, str) or not _allowed(url):
                raise RuntimeError(f"{path.name} is {problem}; its download source is not trusted. Reinstall the loader.")
            if status_cb:
                status_cb(f"Repairing runtime library: {path.name}")
            path.parent.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryDirectory(prefix=".cubeon-library-", dir=path.parent) as temporary:
                candidate = Path(temporary) / path.name
                sha1 = info.get("sha1")
                checksum = ("sha1", sha1) if isinstance(sha1, str) and re.fullmatch(r"[0-9a-fA-F]{40}", sha1) else None
                try:
                    net.download_to(str(candidate), url, expected_hash=checksum,
                                    timeout=(3, 10), attempts=1, deadline=deadline,
                                    url_validator=_allowed)
                    issue = _problem(candidate, info, full=True)
                    if issue:
                        raise RuntimeError(issue)
                    os.replace(candidate, path)
                except Exception as error:
                    raise RuntimeError(f"Couldn't repair {path.name}: {error}. Reconnect and press Play again.") from error
            repaired += 1
    return repaired
