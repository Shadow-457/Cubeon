"""
Minecraft version listing (installed + available) and vanilla install.
Mod-loader-specific installs live in mod_loaders.py.
"""
import json
import os
import re
import shutil

# minecraft_launcher_lib costs ~116ms to import (it pulls in requests);
# nothing here needs it until the user actually installs/launches, so it
# is imported on first use. `mll.<anything>` is unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
mll = LazyModule("minecraft_launcher_lib")

from . import local_cache
from . import net
from .paths import MINECRAFT_DIR


_MAX_INHERITS_DEPTH = 10


def _plain_filename(name: str) -> bool:
    return bool(name) and name not in (".", "..") \
        and os.sep not in name and not (os.altsep and os.altsep in name)


def _load_version_json(folder_path: str, filename: str) -> "dict | None":
    try:
        with open(os.path.join(folder_path, filename), "r",
                  encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError):
        return None
    return data if isinstance(data, dict) else None


def _client_jar_path(folder_path: str, data: dict) -> "str | None":
    candidates = [os.path.basename(os.path.normpath(folder_path)) + ".jar"]
    data_id = data.get("id")
    if isinstance(data_id, str) and _plain_filename(data_id):
        candidates.append(data_id + ".jar")
    for name in dict.fromkeys(candidates):
        path = os.path.join(folder_path, name)
        if os.path.isfile(path):
            return path
    return None


def _client_jar_problem(folder_path: str, data: dict, *,
                        want_sha1: bool = False) -> "str | None":
    """Is this version folder's client jar usable? Returns None when it is,
    or a human-readable issue when it isn't - the 2026-09-17 report was 'if
    my net goes mid-way it still showed INSTALLED even though it's half
    corrupted', because the old scan treated any jar-bearing folder as
    complete. A truncated jar has a size, a valid name, and garbage bytes.

    Checks, cheapest first: the canonical client jar exists (see
    _client_jar_path - a decoy jar must not stand in for it), size matches
    the manifest's downloads.client.size when the json records it, the file
    starts with a zip magic (the game cannot open anything else), and
    optionally the manifest sha1 (post-install only - hashing every jar at
    every scan is too slow for a dropdown refresh).

    A json with inheritsFrom is a loader profile: it ships no jar of its
    own, so the chain is walked instead (bounded depth, cycle-detected) and
    the BASE version's client jar is verified - a loader profile whose base
    is missing or broken is incomplete, not installed.
    """
    if not isinstance(data, dict):
        return "This version's metadata is unreadable."
    versions_dir = os.path.dirname(os.path.abspath(folder_path))
    seen: set[str] = set()
    for _ in range(_MAX_INHERITS_DEPTH + 1):
        downloads = data.get("downloads", {})
        if not isinstance(downloads, dict):
            return "This version's download information is invalid."
        expected = downloads.get("client", {})
        if not isinstance(expected, dict):
            return "This version's download information is invalid."
        if "size" in expected and (type(expected["size"]) is not int
                                   or expected["size"] <= 0):
            return "This version's download size is invalid."
        if "url" in expected and not isinstance(expected["url"], str):
            return "This version's download address is invalid."
        if "sha1" in expected and (not isinstance(expected["sha1"], str)
                                   or not re.fullmatch(r"[a-fA-F0-9]{40}", expected["sha1"])):
            return "This version's download checksum is invalid."
        if "inheritsFrom" not in data:
            break
        base_id = data.get("inheritsFrom")
        if not isinstance(base_id, str) or not _plain_filename(base_id) \
                or base_id in seen:
            return ("This version's loader setup is broken (it references "
                    "itself). Delete this version and install it again.")
        seen.add(base_id)
        base_folder = os.path.join(versions_dir, base_id)
        base_data = _load_version_json(base_folder, base_id + ".json")
        if base_data is None:
            return (f"This version needs Minecraft {base_id}, which is "
                    "missing or broken. Install that version first, or "
                    "delete and reinstall this one.")
        folder_path, data = base_folder, base_data
    else:
        return ("This version's loader setup is broken (it references "
                "itself). Delete this version and install it again.")
    jar_path = _client_jar_path(folder_path, data)
    if jar_path is None:
        return "Missing client .jar. This install didn't finish downloading."
    try:
        actual_size = os.path.getsize(jar_path)
    except OSError as ex:
        return f"Client jar is unreadable: {ex}"
    exp_size = expected.get("size")
    if isinstance(exp_size, int) and not isinstance(exp_size, bool) \
            and exp_size > 0 and actual_size != exp_size:
        return (f"Client jar is incomplete ({actual_size // 1024} of "
                f"{exp_size // 1024} KB) - the download was interrupted. "
                "Delete this version and install it again.")
    # Zip magic: a truncated-then-NULL-padded jar or an HTML error page saved
    # as .jar both fail this, and it costs 2 bytes of reading.
    try:
        with open(jar_path, "rb") as fh:
            if fh.read(2) != b"PK":
                return ("Client jar is not a valid Minecraft file (it may be "
                        "a corrupted or partial download). Delete this "
                        "version and install it again.")
    except OSError as ex:
        return f"Client jar is unreadable: {ex}"
    exp_sha1 = expected.get("sha1")
    if want_sha1 and isinstance(exp_sha1, str) and len(exp_sha1) == 40:
        import hashlib
        h = hashlib.sha1()
        try:
            with open(jar_path, "rb") as fh:
                for block in iter(lambda: fh.read(1 << 20), b""):
                    h.update(block)
        except OSError as ex:
            return f"Client jar is unreadable: {ex}"
        if h.hexdigest() != exp_sha1.lower():
            return ("Client jar failed its integrity check (corrupted "
                    "download). Delete this version and install it again.")
    return None


def _demote_incomplete(entry: dict, issue: str) -> dict:
    """Marks an entry incomplete - it stays in the list (hiding a broken
    install is what caused the 'shows installed but isn't' confusion) but
    launches are blocked and the UI can explain why."""
    out = dict(entry)
    out["incomplete"] = True
    out["issue"] = issue
    out["display_name"] = f"{entry.get('display_name', entry['id'])} (incomplete)"
    return out


def get_installed_versions() -> list[dict]:
    """Tolerant scan: mll's built-in scanner requires the folder name to
    exactly match <name>.json/<name>.jar internally, which misses custom
    installs (TLauncher, modpacks, renamed folders). This falls back to
    scanning every subfolder of versions/ for *any* json+jar pair, and
    uses the json's own "id" field to build the real launch id, while
    keeping the folder name as a friendly display label."""
    versions_dir = os.path.join(MINECRAFT_DIR, "versions")
    if not os.path.isdir(versions_dir):
        return []

    found = {}

    # Pass 1: mll's strict, well-formed scan (fast path, always correct)
    try:
        for v in mll.utils.get_installed_versions(MINECRAFT_DIR):
            found[v["id"]] = {
                "id": v["id"],
                "display_name": v["id"],
                "type": v.get("type", "release"),
                "folder": v["id"],
            }
    except Exception:
        pass

    # Pass 2: tolerant scan for folders that don't match mll's naming rule,
    # including ones that are only partially installed (missing the jar,
    # missing libraries, etc.) - those get surfaced as "incomplete" rather
    # than silently hidden, so it's clear why they won't launch yet.
    for folder in os.listdir(versions_dir):
        folder_path = os.path.join(versions_dir, folder)
        if not os.path.isdir(folder_path):
            continue

        json_files = sorted(f for f in os.listdir(folder_path)
                            if f.endswith(".json"))
        jar_files = [f for f in os.listdir(folder_path) if f.endswith(".jar")]
        if not json_files:
            continue  # not a version folder at all, nothing to go on

        canonical_json = folder + ".json"
        json_path = os.path.join(
            folder_path,
            canonical_json if canonical_json in json_files else json_files[0])
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(data, dict):
            found[folder] = {
                "id": folder,
                "display_name": f"{suggest_friendly_name(folder, folder)} (incomplete)",
                "type": "release",
                "folder": folder,
                "incomplete": True,
                "issue": "This version's metadata is unreadable.",
            }
            continue

        real_id = data.get("id", folder)
        if not isinstance(real_id, str):
            real_id = folder
        if real_id in found:
            continue  # already picked up by the strict scan

        has_jar = bool(jar_files)
        # A version can be launchable via inheritsFrom (e.g. Fabric/Forge
        # profiles reuse the vanilla jar) even without its own jar file.
        inherits = data.get("inheritsFrom")
        is_complete = has_jar or bool(inherits)

        if not is_complete:
            vtype = data.get("type")
            found[folder] = {
                "id": folder,
                "display_name": f"{suggest_friendly_name(real_id, folder)} (incomplete)",
                "type": vtype if isinstance(vtype, str) else "release",
                "folder": folder,
                "incomplete": True,
                "issue": "Missing client .jar. This install didn't finish downloading.",
            }
            continue

        # The launch command needs <folder>/<folder>.json and <folder>/<folder>.jar
        # to exist (that's how mll resolves the version internally), so if this
        # folder's json/jar aren't named after the folder, normalize it. The
        # jar is only adopted when it is named after the version's own id -
        # an arbitrary first-picked jar could be an unrelated decoy.
        expected_json = os.path.join(folder_path, folder + ".json")
        expected_jar = os.path.join(folder_path, folder + ".jar")
        if not os.path.isfile(expected_json):
            shutil.copy(json_path, expected_json)
        if not os.path.isfile(expected_jar) and isinstance(real_id, str) \
                and _plain_filename(real_id):
            id_jar = os.path.join(folder_path, real_id + ".jar")
            if os.path.isfile(id_jar):
                shutil.copy(id_jar, expected_jar)

        vtype = data.get("type")
        found[folder] = {
            "id": folder,  # use folder name as launch id since that's what mll needs
            "display_name": suggest_friendly_name(real_id, folder),
            "type": vtype if isinstance(vtype, str) else "release",
            "folder": folder,
        }

    # Final integrity pass over EVERY entry - including the ones mll's strict
    # scan produced, which only checks that a jar exists, not that it is whole.
    # This is the scan half of the interrupted-download fix: a net death
    # mid-jar leaves a truncated file that the strict scan happily reports as
    # installed, and the game then crashes with no explanation.
    for vid, entry in list(found.items()):
        if entry.get("incomplete"):
            continue
        folder_path = os.path.join(versions_dir, entry["folder"])
        jsons = sorted(f for f in os.listdir(folder_path)
                       if f.endswith(".json")) \
            if os.path.isdir(folder_path) else []
        if not jsons:
            found[vid] = _demote_incomplete(
                entry, "This version's metadata is missing.")
            continue
        canonical_json = entry["folder"] + ".json"
        json_name = canonical_json if canonical_json in jsons else jsons[0]
        data = _load_version_json(folder_path, json_name)
        if data is None:
            found[vid] = _demote_incomplete(
                entry, "This version's metadata is unreadable.")
            continue
        problem = _client_jar_problem(folder_path, data)
        if problem:
            found[vid] = _demote_incomplete(entry, problem)

    return list(found.values())


def delete_version(version_id: str) -> None:
    """Deletes an installed version's folder (.minecraft/versions/<id>).

    This is an explicit, user-initiated action, so unlike the client.json
    sanitizer (which must repair-never-delete files the user didn't create)
    it does remove data - but only the one version folder the caller named,
    nothing shared. Mod profiles live under CUBEON_HOME keyed by
    (mc_version, loader) and can be reused by other installs, so they are
    deliberately left untouched here.

    Raises ValueError with a readable message on anything the UI should
    surface (unknown id, path escape attempt, or an OS failure to remove).
    """
    if not version_id:
        raise ValueError("No version selected.")

    versions_dir = os.path.join(MINECRAFT_DIR, "versions")
    target = os.path.join(versions_dir, version_id)

    # Guard against a crafted id ("../..") escaping the versions folder.
    if os.path.abspath(target) != os.path.normpath(os.path.join(os.path.abspath(versions_dir), version_id)) \
            or not os.path.abspath(target).startswith(os.path.abspath(versions_dir) + os.sep):
        raise ValueError("Refusing to delete a path outside the versions folder.")

    if not os.path.isdir(target):
        raise ValueError("That version folder no longer exists.")

    try:
        shutil.rmtree(target)
    except OSError as ex:
        raise ValueError(f"Couldn't delete this version: {ex}") from ex


def extract_mc_version(version_id: str) -> str:
    """Pulls the plain numeric Minecraft version (e.g. "1.20.1") out of a
    launch id that may be loader-tagged or renamed by a third-party
    launcher (e.g. "1.20.1-forge-47.2.0", TLauncher's own custom ids, or a
    modpack's launchable id). Falls back to the id itself if no version
    number is found so callers never get an empty string.

    This MUST be used anywhere a version id is about to be turned into a
    mods profile key (get_profile_dir / list_mods / sync_mods_to_game) or
    passed to a loader installer - those all expect the bare Mojang version
    string, not the launcher's raw id. Using the raw id there silently
    creates/reads a different, near-always-empty profile folder, which is
    why mods installed via modpacks or TLauncher-style installs wouldn't
    show up in the Mods tab or apply in-game even though the files existed
    on disk somewhere.

    A canonical loader install id (e.g. "fabric-loader-0.19.5-26.1.2",
    "quilt-loader-0.25.0-1.20.1") leads with the LOADER's own version, so
    the first numeric group is wrong - the MC version is the trailing one.
    Those ids can appear as direct rows in the version dropdown, so they
    must resolve to the same profile key as the bare base version or mods
    silently sync from an empty folder. Loader ids that START with the MC
    version ("1.20.1-forge-47.2.0") are already correct with the first
    group. NeoForge's own versioning ("neoforge-21.1.99") has no decodable
    MC number and is deliberately left alone."""
    raw = version_id or ""
    if re.match(r"(?:fabric|quilt)-loader-", raw):
        matches = list(re.finditer(r"(\d+\.\d+(?:\.\d+)?)", raw))
        if matches:
            return matches[-1].group(1)
    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", raw)
    return match.group(1) if match else raw


def suggest_friendly_name(version_id: str, folder_name: str) -> str:
    """Builds a readable label like '1.21.1 (Fabric)' or '1.20.4 (TLauncher)'
    from whatever messy id/folder name we found."""
    base = re.search(r"(\d+\.\d+(?:\.\d+)?)", version_id) or re.search(r"(\d+\.\d+(?:\.\d+)?)", folder_name)
    version_num = base.group(1) if base else version_id

    loader = ""
    lowered = (version_id + folder_name).lower()
    if "neoforge" in lowered:
        loader = "NeoForge"
    elif "fabric" in lowered:
        loader = "Fabric"
    elif "quilt" in lowered:
        loader = "Quilt"
    elif "forge" in lowered:
        loader = "Forge"
    elif "optifine" in lowered:
        loader = "OptiFine"

    if loader:
        return f"{version_num} ({loader})"
    if folder_name != version_id and not re.fullmatch(r"[\d.]+", folder_name):
        return f"{version_num} ({folder_name})"
    return version_num


# Mojang serves the same manifest from two hostnames, and either one can be
# DNS-blocked or route-broken independently (the usual reason the version list
# loads for everyone but one person). piston-meta is the canonical host now;
# launchermeta is the older alias. A failure on one is retried on the other
# before the user is ever told they're offline.
MANIFEST_URLS = (
    "https://piston-meta.mojang.com/mc/game/version_manifest_v2.json",
    "https://launchermeta.mojang.com/mc/game/version_manifest_v2.json",
)


def _download_manifest() -> dict:
    """Fetch the raw version manifest, trying each Mojang mirror in turn with
    timeout + retry. Raises the last error so the cache can fall back to a
    previously downloaded copy."""
    last_err: Exception | None = None
    for url in MANIFEST_URLS:
        try:
            resp = net.get_with_retry(url, timeout=15, attempts=2)
        except Exception as ex:
            last_err = ex
            continue
        try:
            data = resp.json()
        except Exception as ex:
            last_err = ex
            continue
        finally:
            resp.close()
        if isinstance(data, dict) and data.get("versions"):
            return data
        last_err = RuntimeError("the version manifest came back empty")
    raise last_err or RuntimeError("Couldn't fetch the Minecraft version list")


def _manifest() -> dict:
    """The version manifest, cached on disk for an hour and served stale when
    the network is down. Without this, one failed DNS lookup showed "No
    internet" even on a machine that was plainly online a second earlier."""
    return local_cache.cached_call(
        "mojang_manifest", "v2", _download_manifest,
        max_age=3600, stale_ok=True, background_refresh=False)


def get_available_versions(include_snapshots=False, include_old=False) -> list[dict]:
    out = []
    for v in _manifest().get("versions", []):
        vtype = v.get("type")
        if vtype == "release":
            out.append({"id": v["id"], "type": vtype})
        elif vtype == "snapshot" and include_snapshots:
            out.append({"id": v["id"], "type": vtype})
        elif vtype in ("old_alpha", "old_beta") and include_old:
            out.append({"id": v["id"], "type": vtype})
    return out


def get_latest_release() -> str:
    return _manifest()["latest"]["release"]


def _jar_sizes(folder: str) -> "dict[str, int]":
    """Name -> size of every .jar in a version folder, snapshotted BEFORE an
    install attempt. A failed attempt diffs against this so it can remove
    only the files it itself created or clobbered."""
    if not os.path.isdir(folder):
        return {}
    sizes: dict[str, int] = {}
    for name in os.listdir(folder):
        if not name.endswith(".jar"):
            continue
        try:
            sizes[name] = os.path.getsize(os.path.join(folder, name))
        except OSError:
            continue
    return sizes


def install_version(version_id: str, progress_cb, status_cb, max_cb) -> None:
    """progress_cb(int), status_cb(str), max_cb(int) - mirrors mll's callback dict.

    Guarded: mll's own downloader has no resume and no integrity check, so a
    network death mid-install used to leave a truncated jar that the version
    list then reported as INSTALLED (the exact 2026-09-17 report). Now:
      - after mll finishes, the jar is verified against the manifest's size
        AND sha1 before this returns - a bad byte is a failure, not a launch;
      - if mll raises (net died mid-install), the jar files this attempt
        created or clobbered are removed so nothing can mistake the folder
        for a complete install, then a readable error is re-raised (retrying
        re-downloads from scratch; partial Minecraft files are worthless,
        unlike resumable mod packs). Jars that existed before the attempt
        with an unchanged size - a previously valid client, an unrelated
        hand-placed jar - are never touched: a failed reinstall must not
        destroy a working install (or the user's own files).
    """
    callback = {"setStatus": status_cb, "setProgress": progress_cb, "setMax": max_cb}
    folder = os.path.join(MINECRAFT_DIR, "versions", version_id)
    json_path = os.path.join(folder, version_id + ".json")
    jar_sizes_before = _jar_sizes(folder)

    def _drop_attempt_jars() -> None:
        """Removes only the jar files THIS failed attempt is responsible for:
        new files, or a known name whose size changed (mll overwrote it with
        a partial download - the pre-attempt bytes are gone either way).
        Anything pre-existing and size-unchanged survives."""
        if not os.path.isdir(folder):
            return
        for name in os.listdir(folder):
            if not name.endswith(".jar"):
                continue
            path = os.path.join(folder, name)
            try:
                size = os.path.getsize(path)
            except OSError:
                continue
            if size == jar_sizes_before.get(name):
                continue
            try:
                os.remove(path)
            except OSError:
                pass  # the scan's integrity pass will still flag it
        status_cb("Download interrupted - partial files cleaned up. "
                  "Reconnect and try again.")

    try:
        mll.install.install_minecraft_version(version_id, MINECRAFT_DIR,
                                              callback=callback)
    except Exception as ex:
        _drop_attempt_jars()
        raise RuntimeError(
            f"The download was interrupted ({ex.__class__.__name__}). "
            "Your files were cleaned up - reconnect and install again.") from ex

    # mll "succeeded" - prove it. The version json it wrote lists the exact
    # size and sha1 of the client jar; anything else is a corrupted download.
    if not os.path.isfile(json_path):
        _drop_attempt_jars()
        raise RuntimeError(
            "The installer finished but didn't write the version metadata. "
            "Try installing again.")
    try:
        with open(json_path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (json.JSONDecodeError, OSError, UnicodeError) as ex:
        _drop_attempt_jars()
        raise RuntimeError(
            f"The version metadata it downloaded is unreadable ({ex}). "
            "Delete this version and install again.") from ex
    problem = _client_jar_problem(folder, data, want_sha1=True)
    if problem:
        _drop_attempt_jars()
        raise RuntimeError(problem)
