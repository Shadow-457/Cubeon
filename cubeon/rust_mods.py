"""Horizon content mods for Cubeon's existing Rust instance.

The public registry pins original packages. Verify those bytes before adapting
the manifest/declaration names used by Cubeon's fork; artwork stays intact.
Native and retired WebAssembly code packages cannot run in the shipped beta.
"""
from __future__ import annotations

import base64
from collections import Counter
from functools import lru_cache
import hashlib
import io
import json
import logging
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
import threading
import tomllib
from urllib.parse import urlsplit
import zipfile

from . import atomicio, global_mod_cache, local_cache, net, rust_engine, storage
from .file_safety import download_name, entry_name
from .fuzzy_search import search_items

INDEX_URL = "https://horizon-rust.github.io/horizon-mods/index.json"
SOURCE = "horizon"
MAX_INDEX = 5 * 1024 * 1024
MAX_PACKAGE = 64 * 1024 * 1024
MAX_FILE = 16 * 1024 * 1024
MAX_TOTAL = 512 * 1024 * 1024
MAX_FILES = 65536
MANIFEST = "cubeon-mod.toml"
MOD_LIST = "cubeon-mods.txt"
_lock = threading.RLock()
_catalogue_lock = threading.Lock()
_log = logging.getLogger(__name__)


def _id(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", value):
        raise ValueError("Invalid Horizon mod ID.")
    return value


def _https(value):
    if not isinstance(value, str) or any(c.isspace() or ord(c) < 32 for c in value) or "\\" in value:
        return False
    try:
        parsed = urlsplit(value or "")
        return (parsed.scheme == "https" and bool(parsed.hostname) and not parsed.fragment
                and parsed.port in (None, 443) and not parsed.username and not parsed.password)
    except (ValueError, TypeError):
        return False


def download_url(url, project):
    """Only registry/project GitHub releases and their asset redirects."""
    if not _https(url):
        return False
    parsed = urlsplit(url)
    if parsed.hostname in ("release-assets.githubusercontent.com", "objects.githubusercontent.com"):
        return True
    if parsed.hostname != "github.com":
        return False
    parts = parsed.path.strip("/").split("/")
    if len(parts) != 6 or parts[2:4] != ["releases", "download"] or not all(parts):
        return False
    source = urlsplit(project.get("source", ""))
    repositories = {("horizon-rust", "horizon-mods")}
    source_parts = source.path.strip("/").split("/")
    if source.hostname == "github.com" and len(source_parts) >= 2:
        repositories.add(tuple(part.lower() for part in source_parts[:2]))
    return tuple(part.lower() for part in parts[:2]) in repositories


def _text(value, limit):
    if not isinstance(value, str) or len(value) > limit:
        raise ValueError("Invalid Horizon text metadata.")
    return value


def _strings(value, limit=32):
    if not isinstance(value, list) or len(value) > limit or any(not isinstance(v, str) or len(v) > 256 for v in value):
        raise ValueError("Invalid Horizon list metadata.")
    return value


def _parse_index(data):
    if (not isinstance(data, dict) or type(data.get("schema")) is not int
            or data["schema"] != 1 or not isinstance(data.get("projects"), list)
            or len(data["projects"]) > 5000 or not isinstance(data.get("revoked", []), list)):
        raise ValueError("Horizon returned an unsupported mod catalogue. Retry or update Cubeon.")
    duplicates = Counter(p.get("id") for p in data["projects"]
                         if isinstance(p, dict) and isinstance(p.get("id"), str))
    projects = []
    for raw in data["projects"]:
        try:
            if not isinstance(raw, dict):
                raise ValueError("Invalid project metadata.")
            project = dict(raw)
            ident = _id(project.get("id"))
            if duplicates[ident] != 1:
                raise ValueError("Repeated project ID.")
            if project.get("kind") not in ("mod", "native-mod"):
                continue
            if not _text(project.get("name"), 256).strip() or not _https(project.get("source")):
                raise ValueError("Missing project name or source.")
            for key, limit in (("summary", 160), ("description", 10000), ("license", 256)):
                project[key] = _text(project.get(key, ""), limit)
            for key, limit in (("authors", 32), ("categories", 3), ("screenshots", 8)):
                project[key] = _strings(project.get(key, []), limit)
            if type(project.get("downloads", 0)) is not int or project.get("downloads", 0) < 0:
                raise ValueError("Invalid download count.")
            if project.get("key") is not None:
                public = base64.b64decode(_text(project["key"], 128), validate=True)
                if len(public) != 42 or public[:2] != b"Ed":
                    raise ValueError("Invalid minisign key.")
            if not isinstance(project.get("versions"), list) or not 0 < len(project["versions"]) <= 500:
                raise ValueError("Invalid release list.")
            project["icon"] = project.get("icon") if _https(project.get("icon")) else None
            versions = []
            seen = set()
            for raw_version in project.get("versions", []):
                try:
                    if not isinstance(raw_version, dict) or not isinstance(raw_version.get("file"), dict):
                        raise ValueError("Invalid release metadata.")
                    version = dict(raw_version)
                    version["capabilities"] = _strings(version.get("capabilities", []))
                    version["side"] = _text(version.get("side", "client"), 32)
                    for key, limit in (("version", 128), ("game", 128), ("api", 256), ("published", 128), ("changelog", 10000)):
                        version[key] = _text(version.get(key, ""), limit)
                    file = version["file"]
                    extensions = (".hmod", ".hnmod") if project["kind"] == "native-mod" else (".hmod",)
                    name = entry_name(file["name"], extensions=extensions)
                    if len(name) > 128 or not re.fullmatch(r"[A-Za-z0-9._+-]+", name):
                        raise ValueError("Invalid package filename.")
                    if (not version["version"] or not version["game"] or not version["api"]
                            or type(file.get("size")) is not int or not 0 < file["size"] <= MAX_PACKAGE
                            or not isinstance(file.get("sha256"), str)
                            or not re.fullmatch(r"[0-9a-f]{64}", file["sha256"])
                            or not download_url(file.get("url"), project)):
                        raise ValueError("Invalid package metadata.")
                    if bool(project.get("key")) != bool(file.get("signature")):
                        raise ValueError("Missing package signature or public key.")
                    if file.get("signature") is not None:
                        _text(file["signature"], 4096)
                    if version["version"] in seen:
                        raise ValueError("Repeated release version.")
                    seen.add(version["version"])
                    versions.append(version)
                except (ValueError, TypeError, KeyError) as error:
                    _log.debug("Ignoring Horizon release %s: %s", ident, error)
            if versions:
                project["versions"] = versions
                projects.append(project)
        except (ValueError, TypeError, KeyError) as error:
            _log.debug("Ignoring Horizon project: %s", error)
    revoked = []
    for raw in data.get("revoked", []):
        try:
            if not isinstance(raw, dict):
                continue
            _id(raw.get("id"))
            _text(raw.get("reason", ""), 10000)
            if (raw.get("sha256") is not None and (not isinstance(raw["sha256"], str)
                    or not re.fullmatch(r"[0-9a-f]{64}", raw["sha256"]))):
                continue
            revoked.append(raw)
        except (ValueError, TypeError):
            continue
    return {"schema": 1, "projects": projects, "revoked": revoked,
            "generated": data.get("generated", "")}


def catalogue(*, force=False, allow_network=True, cancel_event=None):
    net.check_cancelled(cancel_event)
    key = {"url": INDEX_URL, "revision": 2}
    if not allow_network:
        return local_cache.get_stale("horizon_mod_index", key) or {"projects": [], "revoked": []}

    def fetch():
        response = net.get_with_retry(INDEX_URL, timeout=(3, 10), attempts=1,
                                     url_validator=lambda url: url == INDEX_URL,
                                     cancel_check=lambda: net.check_cancelled(cancel_event))
        try:
            data = bytearray()
            for chunk in response.iter_content(65536):
                net.check_cancelled(cancel_event)
                data.extend(chunk)
                if len(data) > MAX_INDEX:
                    raise ValueError("Horizon's mod catalogue is too large.")
            return _parse_index(json.loads(data))
        finally:
            response.close()

    while not _catalogue_lock.acquire(timeout=.25):
        net.check_cancelled(cancel_event)
    try:
        net.check_cancelled(cancel_event)
        if force:
            result = local_cache.set("horizon_mod_index", key, fetch())
        else:
            result = local_cache.cached_call("horizon_mod_index", key, fetch, max_age=300,
                                             background_refresh=False, stale_ok=True)
    finally:
        _catalogue_lock.release()
    net.check_cancelled(cancel_event)
    return result


def _revoked_reason(index, ident, digest):
    return next((str(item.get("reason") or "This release was removed from Horizon.")
                 for item in index.get("revoked", [])
                 if item["id"] == ident and (not item.get("sha256") or item["sha256"] == digest)), "")


def _problem(index, project, version, mc_version=None, loader=None):
    reason = _revoked_reason(index, project["id"], version["file"]["sha256"])
    if reason:
        return "Withdrawn by Horizon: " + reason
    if project["kind"] == "native-mod":
        return "This native-code mod needs a newer Rust engine. Content mods work in this beta."
    if version["game"] != (mc_version or rust_engine.VERSION) or loader not in (None, "rust"):
        return "This release does not match the selected Rust instance."
    if (version["api"] != "0.2" or version.get("capabilities") != ["registries"]
            or version.get("side", "client") not in ("client", "both")):
        return "This beta supports content mods; WebAssembly code mods cannot run."
    return ""


def _project(index, ref):
    ref = str(ref or "").removeprefix("horizon:")
    return next((p for p in index["projects"] if p["id"] == ref), None)


def _details(project):
    return {"project_id": project["id"], "slug": project["id"], "source": SOURCE,
            "title": project["name"], "display_name": project["name"],
            "description": project.get("summary", ""), "body": project.get("description", ""),
            "icon_url": project.get("icon"), "downloads": project.get("downloads", 0),
            "project_type": "mod", "kind": project["kind"], "loaders": ["rust"],
            "game_versions": list(dict.fromkeys(v["game"] for v in project["versions"])),
            "categories": project.get("categories", []), "author": ", ".join(project.get("authors", [])),
            "license": project.get("license", ""), "source_url": project["source"],
            "verification": "Registry checksum · Signed package" if project.get("key") else "Registry checksum · Unsigned package",
            "client_side": "Supported", "server_side": "Content in Rust worlds",
            "website_url": "https://playhorizon.dev/mods/" + project["id"],
            "gallery": [{"url": url, "title": project["name"]} for url in project.get("screenshots", []) if _https(url)]}


def search(query="", mc_version=None, loader="rust", categories=None, limit=24, offset=0, *, force=False):
    from .mod_catalogue import reference
    index = catalogue(force=force)
    link = reference(query)
    if link and link["source"] != SOURCE:
        raise ValueError("Choose a Horizon content mod for a Rust instance.")
    items = []
    for project in index["projects"]:
        if link and project["id"] != link["project"]:
            continue
        candidates = [v for v in project["versions"] if not _problem(index, project, v, mc_version, loader)]
        if not candidates and not link:
            continue
        if categories and not set(categories).intersection(project.get("categories", [])):
            continue
        latest = candidates[0] if candidates else project["versions"][0]
        problem = _problem(index, project, latest, mc_version, loader)
        items.append(dict(_details(project), compatible=not problem, compatibility_reason=problem,
                          compatibility_target=[mc_version or rust_engine.VERSION, "rust"],
                          facet_compatible=not problem))
    items.sort(key=lambda p: (-p["downloads"], p["title"].casefold()))
    if not link:
        items = search_items(items, query, fields=("title", "slug", "project_id", "description"))
    return items[max(0, offset):max(0, offset) + min(100, max(1, limit))]


def details(ref, *, force=False):
    project = _project(catalogue(force=force), ref)
    return _details(project) if project else None


def versions(ref, mc_version=None, loader=None, *, force=False, allow_network=True, offset=0,
             file_id=None, cancel_event=None):
    index = catalogue(force=force, allow_network=allow_network, cancel_event=cancel_event)
    project = _project(index, ref)
    if not project:
        return []
    result = []
    for version in project["versions"]:
        if file_id and version["version"] != str(file_id):
            continue
        file = version["file"]
        problem = _problem(index, project, version, mc_version, loader)
        result.append({"id": version["version"], "file_id": version["version"],
                       "version_number": version["version"], "name": project["name"],
                       "filename": download_name(project["id"] + ".hmod", (".hmod",)),
                       "url": file["url"], "size": file["size"], "hashes": {"sha256": file["sha256"]},
                       "date_published": version.get("published", ""), "changelog": version.get("changelog", ""),
                       "game_versions": [version["game"]], "loaders": ["rust"],
                       "compatible": not problem, "compatibility_reason": problem, "source": SOURCE})
    return result[max(0, offset):]


def download(ref, mc_version=None, loader="rust", **kwargs):
    return next((v for v in versions(ref, mc_version, loader, **kwargs) if v["compatible"]), None)


def mods_dir(version_id, *, create=False):
    if not rust_engine.is_instance(version_id):
        raise ValueError("Horizon content mods require a selected Cubeon Rust instance.")
    directory = rust_engine._owned(Path(rust_engine.game_dir(create=create)) / "cubeon-mods")
    if create:
        storage.assert_writable()
        directory.mkdir(parents=True, exist_ok=True)
    return directory


def _settings():
    path = rust_engine._owned(Path(rust_engine.game_dir()) / MOD_LIST)
    try:
        if path.stat().st_size > 1024 * 1024:
            raise ValueError("Rust mod settings are too large.")
        return path, path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return path, ""


def _flags(text):
    flags = {}
    for line in text.splitlines():
        key, colon, value = line.partition(":")
        if colon and key.strip().startswith("mod.") and value.strip() in ("true", "false"):
            ident = key.strip()[4:]
            flags[ident] = flags.get(ident, False) or value.strip() == "true"
    return flags


def _set_enabled(ident, enabled):
    path, text = _settings()
    _write_text(path, _enabled_text(text, ident, enabled))


def _enabled_text(text, ident, enabled):
    lines = [line for line in text.splitlines() if line.partition(":")[0].strip() != "mod." + ident]
    lines.append(f"mod.{ident}:{str(bool(enabled)).lower()}")
    return "\n".join(lines) + "\n"


def _write_text(path, text):
    with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=path.parent,
                                     prefix=".mods-", delete=False) as stream:
        temporary = stream.name
        stream.write(text)
        stream.flush()
        os.fsync(stream.fileno())
    try:
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _manifest(text):
    value = tomllib.loads(text)
    _id(value.get("id"))
    allowed = {"id", "name", "version", "description", "authors", "api", "side",
               "capabilities", "namespaces", "experimental"}
    if set(value) - allowed:
        raise ValueError("This package uses a newer or native mod format.")
    if (value.get("api") != "0.2" or _strings(value.get("capabilities", [])) != ["registries"]
            or value.get("side", "client") not in ("client", "both")):
        raise ValueError("Only content mods (API 0.2) can run in this Rust beta.")
    if not all(isinstance(value.get(k), str) and value[k].strip() for k in ("name", "version")):
        raise ValueError("The mod needs a name and version.")
    _text(value["name"], 256)
    _text(value["version"], 128)
    _text(value.get("description", ""), 10000)
    _strings(value.get("authors", []))
    if any(capability != "registries" for capability in _strings(value.get("experimental", []))):
        raise ValueError("This content mod declares unsupported experimental capabilities.")
    namespaces = value.get("namespaces", [])
    if (not isinstance(namespaces, list) or any(not isinstance(ns, str) or not re.fullmatch(r"[a-z0-9_.-]{1,64}", ns)
            or ns in ("minecraft", "c", "cubeon", "horizon", value["id"]) for ns in namespaces)
            or len(set(namespaces)) != len(namespaces) or value["id"] in ("minecraft", "c", "cubeon", "horizon")):
        raise ValueError("The mod claims a reserved or repeated content namespace.")
    return value


def _package(data):
    if not 0 < len(data) <= MAX_PACKAGE:
        raise ValueError("A Rust mod package must be between 1 byte and 64 MB.")
    archive = zipfile.ZipFile(io.BytesIO(data))
    entries = archive.infolist()
    names = [entry.filename for entry in entries]
    if (len(entries) > MAX_FILES or len(set(names)) != len(names)
            or sum(e.file_size for e in entries) > MAX_TOTAL):
        archive.close()
        raise ValueError("The mod archive has repeated files or exceeds the content limits.")
    manifests = [name for name in (MANIFEST, "horizon-mod.toml") if name in names]
    if len(manifests) != 1 or "mod.wasm" in names or "horizon-native.json" in names or "cubeon-native.json" in names:
        archive.close()
        raise ValueError("Choose a content .hmod; native and WebAssembly code packages cannot run in this beta.")
    try:
        for entry in entries:
            name = entry.filename
            mode = entry.external_attr >> 16
            if (not name or "\\" in name or ":" in name or name.startswith("/")
                    or any(part in ("", ".", "..") for part in name.rstrip("/").split("/"))
                    or stat.S_ISLNK(mode) or entry.flag_bits & 1):
                raise ValueError("The mod archive contains an unsafe path, link or encrypted file.")
            if entry.file_size > MAX_FILE:
                raise ValueError("A mod content file exceeds 16 MB.")
        if archive.getinfo(manifests[0]).file_size > 65536:
            raise ValueError("The mod manifest is too large.")
        manifest = _manifest(archive.read(manifests[0]).decode("utf-8"))
        owned = {manifest["id"], *manifest.get("namespaces", [])}
        mapping = {}
        for entry in entries:
            name = entry.filename
            if entry.is_dir():
                continue
            if name == manifests[0]:
                mapping[name] = MANIFEST
                continue
            parts = name.split("/")
            if len(parts) >= 3 and parts[0] in ("assets", "data"):
                if not all(re.fullmatch(r"[a-z0-9_.-]+", part) for part in parts[1:]):
                    raise ValueError("A mod content path has invalid characters.")
                top, namespace, rest = parts[0], parts[1], "/".join(parts[2:])
                shared = (top == "data" and namespace in ("minecraft", "c") and rest.startswith("tags/"))
                atlas = top == "assets" and namespace == "minecraft" and rest.startswith("atlases/")
                if namespace not in owned and not shared and not atlas:
                    raise ValueError("A content mod cannot replace files in another mod or vanilla namespace.")
                if top == "data" and parts[2] in ("horizon", "cubeon"):
                    if namespace != manifest["id"]:
                        raise ValueError("Content declarations must use the mod's own ID.")
                    parts[2] = "cubeon"
                mapping[name] = "/".join(parts)
            elif PurePosixPath(name).name.lower().startswith(("license", "copying", "readme", "notice")):
                mapping[name] = name
            else:
                raise ValueError("This content package contains executable or unsupported files.")
        if len(set(mapping.values())) != len(mapping):
            raise ValueError("Adapting this package would replace another file.")
        return archive, manifest, mapping
    except BaseException:
        archive.close()
        raise


def _read_package(path):
    with Path(path).open("rb") as stream:
        return stream.read(MAX_PACKAGE + 1)


@lru_cache(maxsize=256)
def _installed_manifest(path, stamp):
    target = Path(path)
    if target.is_dir():
        return _manifest((target / MANIFEST).read_text(encoding="utf-8"))
    archive, manifest, _mapping = _package(_read_package(target))
    archive.close()
    return manifest


def _inspect_installed(path):
    info = path.stat()
    stamp = (info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns)
    if path.is_dir():
        meta = (path / MANIFEST).stat()
        stamp += (meta.st_size, meta.st_mtime_ns, meta.st_ctime_ns)
    return _installed_manifest(str(path), stamp)


def list_mods(version_id):
    from . import mods
    directory = mods_dir(version_id)
    if not directory.is_dir():
        return []
    flags = _flags(_settings()[1])
    index = catalogue(allow_network=False)
    result = []
    for path in sorted(directory.iterdir()):
        if path.name.startswith(".") or not (path.suffix == ".hmod" or path.is_dir() and (path / MANIFEST).is_file()):
            continue
        try:
            rust_engine._owned(path)
            manifest = _inspect_installed(path)
            meta = (mods._read_meta(str(directory), path.name) or {}) if path.suffix == ".hmod" else {}
            reason = _revoked_reason(index, manifest["id"], meta.get("source_sha256"))
            if reason and flags.get(manifest["id"], False):
                with _lock, storage.update_operation():
                    storage.assert_writable()
                    _set_enabled(manifest["id"], False)
                flags[manifest["id"]] = False
            result.append({"filename": path.name, "display_name": manifest["name"], "mod_id": manifest["id"],
                           "version": manifest["version"], "enabled": flags.get(manifest["id"], False),
                           "size_kb": round(path.stat().st_size / 1024, 1), "slug": meta.get("slug"),
                           "project_id": meta.get("project_id"), "source": meta.get("source"),
                           "icon_url": meta.get("icon_url"), "file_id": meta.get("file_id"),
                           "stem": manifest["id"], "protected": False,
                           **({"issue": "Withdrawn by Horizon: " + reason} if reason else {})})
        except (OSError, ValueError, UnicodeError, zipfile.BadZipFile, rust_engine.RustEngineError) as error:
            _log.debug("Cannot read Rust mod %s: %s", path.name, error)
            result.append({"filename": path.name, "display_name": path.stem, "mod_id": "",
                           "version": "", "enabled": False, "size_kb": 0, "slug": None,
                           "project_id": None, "source": None, "stem": path.stem,
                           "protected": False, "issue": str(error)})
    return result


def _signature(data, key, signature):
    if not key and not signature:
        return
    try:
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
        pub = base64.b64decode(key.strip(), validate=True)
        lines = signature.splitlines()
        sig = base64.b64decode(lines[1], validate=True)
        global_sig = base64.b64decode(lines[3], validate=True)
        if (len(pub) != 42 or pub[:2] != b"Ed" or len(sig) != 74 or sig[:2] not in (b"ED", b"Ed")
                or pub[2:10] != sig[2:10] or len(global_sig) != 64
                or not lines[2].startswith("trusted comment: ")):
            raise ValueError("Invalid minisign key or signature.")
        verifier = Ed25519PublicKey.from_public_bytes(pub[10:])
        verifier.verify(sig[10:], hashlib.blake2b(data).digest() if sig[:2] == b"ED" else data)
        verifier.verify(global_sig, sig[10:] + lines[2][17:].encode("utf-8"))
    except Exception as error:
        raise ValueError("The Horizon mod's signature did not verify. Nothing was installed.") from error


def _adapt_json(value):
    if isinstance(value, str):
        return "cubeon:" + value[8:] if re.fullmatch(r"horizon:[a-z0-9_./-]+", value) else value
    if isinstance(value, list):
        return [_adapt_json(item) for item in value]
    if isinstance(value, dict):
        adapted = {_adapt_json(key): _adapt_json(item) for key, item in value.items()}
        if len(adapted) != len(value):
            raise ValueError("Adapting this package would replace another JSON field.")
        return adapted
    return value


def _publish_files(files, temporary):
    """Publish the package, receipt and flags together, restoring all on error."""
    previous = {}
    for number, path in enumerate(files):
        rust_engine._owned(path)
        if path.exists():
            if not path.is_file():
                raise ValueError("A Rust mod or settings file is occupied by a folder.")
            backup = temporary / f"previous-{number}"
            shutil.copyfile(path, backup)
            previous[path] = backup
        else:
            previous[path] = None
    changed = []
    try:
        for path, staged in files.items():
            changed.append(path)
            os.replace(staged, path)
    except BaseException:
        for path in reversed(changed):
            if previous[path] is None:
                path.unlink(missing_ok=True)
            else:
                os.replace(previous[path], path)
        raise


def _publish(data, version_id, *, project=None, version=None, replace=False, cancel_event=None):
    from . import mods
    archive, manifest, mapping = _package(data)
    try:
        if project and (manifest["id"] != project["id"] or manifest["version"] != version["version"]
                or manifest["api"] != version["api"] or manifest.get("side", "client") != version.get("side", "client")
                or set(manifest.get("capabilities", [])) != set(version.get("capabilities", []))):
            raise ValueError("The downloaded mod does not match Horizon's catalogue entry.")
        digest = hashlib.sha256(data).hexdigest()
        reason = _revoked_reason(catalogue(allow_network=False), manifest["id"], digest)
        if reason:
            raise ValueError("Withdrawn by Horizon: " + reason)
        directory = mods_dir(version_id, create=True)
        name = download_name(manifest["id"] + ".hmod", (".hmod",))
        destination = rust_engine._owned(directory / name)
        with tempfile.TemporaryDirectory(prefix=".rust-mod-", dir=directory.parent) as temporary:
            staged = Path(temporary) / name
            with zipfile.ZipFile(staged, "w", compression=zipfile.ZIP_DEFLATED) as output:
                for source, target in mapping.items():
                    net.check_cancelled(cancel_event)
                    content = archive.read(source)
                    if target.endswith(".json"):
                        original = json.loads(content)
                        adapted = _adapt_json(original)
                        if adapted != original:
                            content = json.dumps(adapted, ensure_ascii=False).encode("utf-8")
                    output.writestr(target, content)
            if staged.stat().st_size > MAX_PACKAGE:
                raise ValueError("The adapted Rust mod exceeds 64 MB.")
            with _lock, storage.update_operation():
                storage.assert_writable()
                net.check_cancelled(cancel_event)
                existing = list_mods(version_id)
                matches = [item for item in existing if item["mod_id"] == manifest["id"]]
                if any(item["filename"] != name for item in matches):
                    raise ValueError("Another copy of this mod is installed. Remove it before installing an update.")
                if destination.exists():
                    prior = _inspect_installed(destination)
                    if prior["id"] != manifest["id"]:
                        raise ValueError("Another mod already uses this filename.")
                    if not replace:
                        raise ValueError("This mod is already installed. Remove it before importing a replacement.")
                receipt = Path(mods._meta_path(str(directory), name))
                old_meta = mods._read_meta(str(directory), name) or {}
                if (project and old_meta.get("source") == SOURCE and old_meta.get("signature_key")
                        and old_meta["signature_key"] != project.get("key")):
                    raise ValueError("This mod's signing key changed. The existing mod was kept.")
                meta = {"source_sha256": digest}
                if project:
                    meta.update(slug=project["id"], project_id=project["id"], source=SOURCE,
                                file_id=version["version"], url=version["file"]["url"],
                                icon_url=project.get("icon"), signature_key=project.get("key"))
                staged_meta = Path(temporary) / "receipt.json"
                atomicio.write_json(str(staged_meta), meta)
                settings, text = _settings()
                enabled = _flags(text).get(manifest["id"], False) if matches else True
                staged_settings = Path(temporary) / "settings.txt"
                _write_text(staged_settings, _enabled_text(text, manifest["id"], enabled))
                net.check_cancelled(cancel_event)
                _publish_files({destination: staged, receipt: staged_meta, settings: staged_settings}, Path(temporary))
                mods._forget_sidecar(str(receipt))
        return name
    finally:
        archive.close()


def install(ref, version_id, *, mc_version=None, loader="rust", file_id=None,
            progress_cb=None, status_cb=None, cancel_event=None):
    mods_dir(version_id)
    if loader != "rust" or mc_version not in (None, rust_engine.VERSION):
        raise ValueError("Horizon mods require the selected Rust 26.3 instance.")
    index = catalogue(cancel_event=cancel_event)
    project = _project(index, ref)
    if not project:
        raise ValueError("This mod is no longer in Horizon's catalogue.")
    version = next((v for v in project["versions"] if
                    (not file_id or v["version"] == str(file_id)) and not _problem(index, project, v, mc_version, loader)), None)
    if not version:
        raise ValueError(_problem(index, project, project["versions"][0], mc_version, loader)
                         or "No compatible content release was found.")
    file = version["file"]
    if status_cb:
        status_cb("Downloading " + project["name"] + "…")
    mods_dir(version_id, create=True)
    with tempfile.TemporaryDirectory(prefix=".horizon-download-", dir=Path(rust_engine.game_dir())) as temporary:
        raw = Path(temporary) / "original.hmod"

        def fetch(path):
            def progress(done, total):
                if done > file["size"]:
                    raise ValueError("The Horizon download exceeds its published size.")
                if progress_cb:
                    progress_cb(done / file["size"], 1)
            net.download_to(path, file["url"], expected_hash=("sha256", file["sha256"]),
                            url_validator=lambda url: download_url(url, project),
                            cancel_check=lambda: net.check_cancelled(cancel_event),
                            progress_cb=progress)

        global_mod_cache.get_or_fetch(str(raw), fetch, hashes={"sha256": file["sha256"]},
                                     human_name=file["name"], cancel_check=lambda: net.check_cancelled(cancel_event))
        data = _read_package(raw)
        if len(data) != file["size"] or hashlib.sha256(data).hexdigest() != file["sha256"]:
            raise ValueError("The Horizon package failed its size or SHA-256 check.")
        _signature(data, project.get("key"), file.get("signature"))
        net.check_cancelled(cancel_event)
        installed = _publish(data, version_id, project=project, version=version, replace=True, cancel_event=cancel_event)
    if progress_cb:
        progress_cb(1, 1)
    return {"installed": [installed], "skipped": 0, "failed": []}


def install_local(source, version_id, *, replace=False):
    mods_dir(version_id)
    entry_name(Path(source).name, extensions=(".hmod",))
    return _publish(_read_package(source), version_id, replace=replace)


def toggle(version_id, filename):
    directory = mods_dir(version_id)
    path = rust_engine._owned(directory / entry_name(filename))
    with _lock, storage.update_operation():
        storage.assert_writable()
        ident = _inspect_installed(path)["id"]
        enabled = not _flags(_settings()[1]).get(ident, False)
        from . import mods
        meta = mods._read_meta(str(directory), filename) if path.suffix == ".hmod" else {}
        reason = _revoked_reason(catalogue(allow_network=False), ident, (meta or {}).get("source_sha256"))
        if enabled and reason:
            raise ValueError("Withdrawn by Horizon: " + reason)
        _set_enabled(ident, enabled)


def delete(version_id, filename):
    from . import mods
    path = rust_engine._owned(mods_dir(version_id) / entry_name(filename))
    with _lock, storage.update_operation():
        storage.assert_writable()
        try:
            ident = _inspect_installed(path)["id"]
        except (ValueError, UnicodeError, OSError, zipfile.BadZipFile):
            ident = None
        if ident:
            _set_enabled(ident, False)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink()
        if path.suffix == ".hmod":
            Path(mods._meta_path(str(path.parent), path.name)).unlink(missing_ok=True)
