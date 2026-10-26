"""
Minecraft version listing (installed + available) and vanilla install.
Mod-loader-specific installs live in mod_loaders.py.
"""
import json
import logging
import os
import re
import shutil
import threading
import sys
import time
from contextlib import contextmanager

log = logging.getLogger(__name__)

# minecraft_launcher_lib costs ~116ms to import (it pulls in requests);
# nothing here needs it until the user actually installs/launches, so it
# is imported on first use. `mll.<anything>` is unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
mll = LazyModule("minecraft_launcher_lib")

from . import local_cache
from . import net
from .paths import MINECRAFT_DIR, INSTANCE_META_FILENAME


_MAX_INHERITS_DEPTH = 10

# Version ids whose install is running in THIS process. A folder being written
# must never be reported as an incomplete install: the seed step writes the
# version json before the client jar arrives, so a rescan during that window
# used to paint "incomplete install" over a download that was working fine.
# The registry also keeps startup cleanup from deleting a live download (belt
# and braces with the mtime grace period in unfinished_install_reason()).
_active_installs: set[str] = set()
_active_installs_lock = threading.Lock()


def active_installs() -> set[str]:
    """Snapshot of version ids currently being installed in this process."""
    with _active_installs_lock:
        return set(_active_installs)


def install_in_progress(version_id: "str | None") -> bool:
    """True while install_version() is writing this version's folder."""
    if not version_id:
        return False
    with _active_installs_lock:
        return version_id in _active_installs


@contextmanager
def _active_install(version_id: str):
    with _active_installs_lock:
        if version_id in _active_installs:
            raise RuntimeError(f"Minecraft {version_id} is already installing.")
        _active_installs.add(version_id)
    try:
        yield
    finally:
        with _active_installs_lock:
            _active_installs.discard(version_id)


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
                # Never surface the raw launch id ("fabric-loader-0.19.5-26.1.2")
                # to the user - it reads as a second, separate game. The same
                # friendly label the tolerant scan uses.
                "display_name": suggest_friendly_name(v["id"], v["id"]),
                "type": v.get("type", "release"),
                "folder": v["id"],
            }
    except Exception:
        pass

    # Pass 2: tolerant scan for folders that don't match mll's naming rule,
    # including ones that are only partially installed (missing the jar,
    # missing libraries, etc.) - those get surfaced as "incomplete" rather
    # than silently hidden, so it's clear why they won't launch yet.
    active = active_installs()
    for folder in os.listdir(versions_dir):
        folder_path = os.path.join(versions_dir, folder)
        if not os.path.isdir(folder_path):
            continue
        if folder in active:
            # This folder belongs to an install running right now. It is not
            # installed yet, and the json that _seed_version_json writes
            # before the jar is not a broken install either - surfacing it as
            # "(incomplete)" mid-download is the 2026-10-26 report. The
            # install worker rescans when it actually finishes.
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
        # Dedupe by FOLDER, never by the json's declared id. This check used
        # to be `real_id in found`, which made the whole scan depend on
        # os.listdir() order: a folder whose metadata still carries another
        # version's id (a half-finished install keeps its template manifest -
        # see tools/test_version_integrity.py's netdeath case) was skipped
        # whenever that id had been seen first, so the broken install showed
        # up as NEITHER installed nor incomplete - it just vanished from the
        # list. The strict scan keys by folder name too, so that is the only
        # thing worth deduping against.
        if folder in found:
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
            if vid in active or entry.get("folder") in active:
                found.pop(vid, None)  # mid-install, not a broken install
            else:
                found[vid] = _demote_incomplete(
                    entry, "This version's metadata is missing.")
            continue
        canonical_json = entry["folder"] + ".json"
        json_name = canonical_json if canonical_json in jsons else jsons[0]
        data = _load_version_json(folder_path, json_name)
        if data is None:
            if vid in active or entry.get("folder") in active:
                found.pop(vid, None)
            else:
                found[vid] = _demote_incomplete(
                    entry, "This version's metadata is unreadable.")
            continue
        problem = _client_jar_problem(folder_path, data)
        if problem:
            if vid in active or entry.get("folder") in active:
                # The install is still writing this folder; keep it out of the
                # list until it either finishes or cleans itself up.
                found.pop(vid, None)
            else:
                found[vid] = _demote_incomplete(entry, problem)

    # Instance sidecars: a cloned pack instance carries its own display name
    # and profile. Without this every clone read as "1.21.11 (Fabric)" and
    # looked like a duplicate of the loader row it was cloned from.
    for vid, entry in found.items():
        folder = entry.get("folder") or vid
        sidecar = _read_instance_sidecar(folder)
        if not sidecar:
            continue
        entry["instance"] = sidecar
        name = sidecar.get("name")
        if isinstance(name, str) and name.strip():
            entry["display_name"] = name.strip()

    # Display order: newest game version first, so vanilla "1.21.11" and
    # "1.21.11 (Fabric)" sit next to each other instead of being scattered
    # by os.listdir() luck. Complete installs before incomplete ones;
    # entries with no decodable version (weird custom ids) last.
    def _display_key(entry):
        mc = extract_mc_version(entry.get("id") or entry.get("folder") or "")
        nums = tuple(int(p) for p in mc.split(".") if p.isdigit())
        return (bool(entry.get("incomplete")), not nums,
                tuple(-n for n in nums), entry.get("id") or "")

    return sorted(found.values(), key=_display_key)


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


# --- Unfinished-install cleanup --------------------------------------------
#
# install_version() ALREADY CLEANS UP AFTER ITSELF: when an install fails or is
# cancelled it removes the partial jar and the folder that attempt created, so
# a plain failed install never shows up here (that is what
# tools/test_version_integrity.py's "failed install removes only what THAT
# attempt created" case pins). What is left over is what a HARD kill stranded -
# a crash, a power cut, a full disk, a killed process - plus whatever a foreign
# launcher left half-copied into versions/. Those folders can never launch and
# would otherwise sit in the Play list forever wearing "(incomplete)", so
# Cubeon sweeps them once at startup (opt-out: `auto_delete_incomplete`,
# Settings > Game versions, ON by default).
#
# DELETING IS NOT THE SAME DECISION AS DISPLAYING, and this bar is deliberately
# higher. get_installed_versions() flags a version incomplete for anything from
# a truncated jar to an unreadable metadata file and MUST keep showing those
# (hiding a broken install is what caused the "shows installed but isn't"
# confusion). Cleanup only ever touches the states that mean "the bytes never
# arrived":
#
#   * the client jar is missing entirely, or
#   * it is truncated (its size disagrees with the manifest), or
#   * it is not a zip at all (an HTML error page saved as .jar, etc.).
#
# Excluded, and why:
#   * "Client jar is unreadable: <OSError>" - a permissions problem or a file
#     held open by a RUNNING game (routine on Windows). The install is fine.
#   * metadata problems (missing/unreadable/invalid json) - a hand-made or
#     foreign-launcher folder, not a download Cubeon interrupted.
#   * loader-chain problems ("needs Minecraft X, which is missing") - the base
#     version is a separate install the user may well still want.
#   * sha1 mismatches - hashing every jar at startup is far too slow for a
#     maintenance pass, and an interrupted download is caught by the size check
#     long before the bytes happen to line up.
#
# A jar written within _CLEANUP_GRACE_SECONDS is left alone: it may be a
# download in flight right now (a second Cubeon instance, a manual copy).

_CLEANUP_GRACE_SECONDS = 600


def unfinished_install_reason(folder: str) -> "str | None":
    """Why `versions/<folder>` is an unfinished download, or None.

    Mirrors the download-completion half of _client_jar_problem() - see the
    block comment above for exactly which states qualify and why the rest are
    deliberately excluded. Never raises: anything it cannot read is left
    alone rather than guessed at.
    """
    if not _plain_filename(folder):
        return None
    if install_in_progress(folder):
        return None  # a live download, never a leftover to sweep
    folder_path = os.path.join(MINECRAFT_DIR, "versions", folder)
    if not os.path.isdir(folder_path):
        return None

    try:
        jsons = sorted(f for f in os.listdir(folder_path)
                       if f.endswith(".json"))
    except OSError:
        return None
    if not jsons:
        return None  # not a version folder at all, nothing to go on
    canonical = folder + ".json"
    data = _load_version_json(
        folder_path, canonical if canonical in jsons else jsons[0])
    if data is None:
        return None  # metadata problem: not a download we interrupted
    if isinstance(data.get("inheritsFrom"), str):
        return None  # a loader profile - its chain is a separate install

    jar_path = _client_jar_path(folder_path, data)
    if jar_path is None:
        return "the client .jar was never downloaded"
    try:
        actual_size = os.path.getsize(jar_path)
        age = time.time() - os.path.getmtime(jar_path)
    except OSError:
        return None  # unreadable (permissions / held open): leave it alone
    if age < _CLEANUP_GRACE_SECONDS:
        return None  # written moments ago - a download may be in flight

    downloads = data.get("downloads")
    client = downloads.get("client") if isinstance(downloads, dict) else None
    exp_size = client.get("size") if isinstance(client, dict) else None
    if isinstance(exp_size, int) and not isinstance(exp_size, bool) \
            and exp_size > 0 and actual_size != exp_size:
        return (f"the client .jar is truncated ({actual_size // 1024} of "
                f"{exp_size // 1024} KB)")
    # Zip magic: a truncated-then-NULL-padded jar or an HTML error page saved
    # as .jar both fail this, and it costs 2 bytes of reading.
    try:
        with open(jar_path, "rb") as fh:
            if fh.read(2) != b"PK":
                return "the client .jar is not a Minecraft file"
    except OSError:
        return None
    return None


def find_unfinished_installs() -> list[dict]:
    """Every version folder that is an unfinished download.

    Returns [{"id", "folder", "reason"}] - id/folder are the folder name (the
    launch id mll needs), reason is the short phrase from
    unfinished_install_reason(). Sorted for a stable log/status line.
    """
    versions_dir = os.path.join(MINECRAFT_DIR, "versions")
    if not os.path.isdir(versions_dir):
        return []
    try:
        names = sorted(os.listdir(versions_dir))
    except OSError:
        return []
    out = []
    for name in names:
        try:
            reason = unfinished_install_reason(name)
        except Exception:  # one odd folder must never break the whole pass
            log.debug("cleanup: could not inspect %s", name, exc_info=True)
            continue
        if reason:
            out.append({"id": name, "folder": name, "reason": reason})
    return out


def cleanup_unfinished_installs(*, skip=(), dry_run: bool = False) -> list[dict]:
    """Deletes version folders whose download never finished.

    The startup half of the feature (Settings > Game versions, ON by default):
    main.py calls this once before the first version scan, so a stranded
    half-install never appears in the list at all.

    `skip` names ids to leave alone - an install running in THIS process, or
    the version the user has selected - because a folder being written right
    now is not (only) a leftover. unfinished_install_reason() applies the same
    protection by mtime to installs this process cannot see.

    `dry_run` reports without deleting anything (the test path).

    Never raises, and only ever removes the one folder named: delete_version()
    re-validates the path and leaves shared stores (mod profiles, libraries,
    assets) untouched. Returns what was removed (or would be), each
    {"id", "folder", "reason"}.
    """
    skip = {s for s in skip if s}
    removed = []
    for item in find_unfinished_installs():
        if item["folder"] in skip:
            log.info("cleanup: keeping %s (in use)", item["folder"])
            continue
        if dry_run:
            removed.append(item)
            continue
        try:
            delete_version(item["folder"])
        except Exception as ex:  # ValueError, or anything the OS threw
            log.warning("cleanup: could not delete %s: %s",
                        item["folder"], ex)
            continue
        log.info("cleanup: removed unfinished install %s (%s)",
                 item["folder"], item["reason"])
        removed.append(item)
    return removed


def _inherited_base_version(version_id: str) -> "str | None":
    """The base Minecraft version a loader install on disk inherits from,
    read from that install's own version json (`inheritsFrom`).

    This is the only AUTHORITATIVE answer for a loader id that does not
    encode the game version: NeoForge numbers itself after the game, so
    "neoforge-21.1.99" means "99th NeoForge build for 1.21.1" and arithmetic
    on the bare number would give "21.1.99" - a version that does not exist.
    The older 1.20.1-era numbering ("neoforge-47.1.2") cannot be recovered by
    arithmetic at all, so the json is the only safe source.

    Returns None when the folder or json is missing (a half-written install,
    or an id quoted from somewhere other than this disk) so the caller can
    fall back to leaving the id untouched rather than guessing wrong.
    """
    if not _plain_filename(version_id):
        return None
    folder = os.path.join(MINECRAFT_DIR, "versions", version_id)
    data = _load_version_json(folder, f"{version_id}.json")
    if not isinstance(data, dict):
        return None
    base = data.get("inheritsFrom")
    return base if isinstance(base, str) and _plain_filename(base) else None


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
    MC number - it numbers ITSELF after the game, so 21.1.99 means "the 99th
    NeoForge build for 1.21.1". The bare number is therefore NOT the MC
    version, and returning it silently pointed the Mods tab at an empty
    profile while find_installed_loader_version() failed to recognise the
    install and offered to reinstall it on every launch. The real MC version
    is the install's own inheritsFrom (read from disk); when the folder is
    absent the id is left alone rather than guessed at, because the older
    1.20.1-era numbering ("neoforge-47.1.2") and a future un-prefixed MC
    major cannot be recovered by arithmetic."""
    raw = version_id or ""
    if re.match(r"(?:fabric|quilt)-loader-", raw):
        matches = list(re.finditer(r"(\d+\.\d+(?:\.\d+)?)", raw))
        if matches:
            return matches[-1].group(1)
    if re.fullmatch(r"neoforge-\d+\.\d+\.\d+", raw):
        inherited = _inherited_base_version(raw)
        if inherited:
            return inherited
        return raw
    match = re.search(r"(\d+\.\d+(?:\.\d+)?)", raw)
    return match.group(1) if match else raw


def _read_instance_sidecar(folder: str) -> dict | None:
    """The `_cubeon_instance.json` record inside a version folder, or None.

    Read directly (not through mods.py) so this scan stays free of the mod
    stack; a bad sidecar just means "legacy install"."""
    if not folder or os.path.basename(folder) != folder:
        return None
    path = os.path.join(MINECRAFT_DIR, "versions", folder,
                        INSTANCE_META_FILENAME)
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, json.JSONDecodeError):
        return None
    return data if isinstance(data, dict) else None


def suggest_friendly_name(version_id: str, folder_name: str) -> str:
    """Builds a readable label like '1.21.1 (Fabric)' or '1.20.4 (TLauncher)'
    from whatever messy id/folder name we found.

    Uses extract_mc_version so loader-tagged ids resolve to the GAME version,
    not the loader's own: "fabric-loader-0.19.5-26.1.2" becomes
    "26.1.2 (Fabric)", never "0.19.5 (Fabric)" - the list must read as
    Minecraft versions with a loader tag, not as random other numbers."""
    version_num = extract_mc_version(version_id or folder_name or "")
    if not re.fullmatch(r"[\d.]+.*", version_num) and folder_name and folder_name != version_id:
        # No decodable version in the id (custom/TLauncher ids): try the folder.
        maybe = extract_mc_version(folder_name)
        if re.fullmatch(r"[\d.]+.*", maybe):
            version_num = maybe

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
        # releaseTime rides along so the Play tab's picker can show when a
        # release shipped - Mojang ships it in the manifest we already fetched,
        # so this costs nothing extra.
        entry = {"id": v["id"], "type": vtype, "releaseTime": v.get("releaseTime")}
        if vtype == "release":
            out.append(entry)
        elif vtype == "snapshot" and include_snapshots:
            out.append(entry)
        elif vtype in ("old_alpha", "old_beta") and include_old:
            out.append(entry)
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


# --- Cancellation-aware downloads -------------------------------------------
#
# mll 8.0 downloads every file with requests but WITHOUT a timeout, and
# copies the body with shutil.copyfileobj - one big file (client jar, Java
# runtime, asset index) or a stalled connection can hold the install for
# minutes with NO callback firing. That is why a cancelled install used to
# keep running for minutes: the cancel was only ever checked at the next
# file boundary. While an install with a cancel_event runs, mll's
# download_file (the module-global name in `install` and `runtime`, the two
# modules the version installer drives) is patched with the mirror below:
# same behavior, plus a read timeout and a per-chunk cancel check.
#
# Thread mapping: mll calls setStatus from the very worker thread that is
# about to download, right before it starts - so the callback wrappers
# register that thread under this install's bridge, and the chunk loop can
# tell "this thread belongs to a cancelled install" from "another install
# was cancelled" (two versions may legally install at once).


class _InstallCancelBridge:
    """Maps the threads inside one install call to its cancel event."""

    def __init__(self, event: threading.Event):
        self.event = event
        self._lock = threading.Lock()
        self._threads: set[int] = set()

    def note_thread(self) -> None:
        with self._lock:
            self._threads.add(threading.get_ident())

    def release(self) -> None:
        with self._lock:
            self._threads.clear()

    def should_stop(self) -> bool:
        with self._lock:
            return self.event.is_set() and threading.get_ident() in self._threads


class _DownloadCancelled(Exception):
    """Raised mid-chunk when the owning install's cancel event is set.
    install_version re-wraps anything mll raises as a RuntimeError; callers
    decide "cancelled vs failed" from the event, never the exception type."""


_live_cancel_bridges: "list[_InstallCancelBridge]" = []
_bridges_lock = threading.Lock()
# mll imports mutable globals into several modules. Keep patch lifetimes
# serial (and reentrant for a loader's base install), so one worker cannot
# restore another worker's downloader while it is still using it.
_mll_patch_lock = threading.RLock()

_MIRROR_TIMEOUT = (15, 60)  # (connect, read-between-bytes) - a stalled
# connection must never hang the install forever, but a slow one that keeps
# moving is legitimate and only bounded by the chunk-level cancel check.

#: Retries per file. mll's own downloader has no timeout, no retry, no resume
#: and no integrity check on a body that stopped early, so one dropped
#: connection mid-asset-phase either failed the whole install or - worse - left
#: a file the version list then reported as installed (the 2026-09-17 report).
_DOWNLOAD_ATTEMPTS = 3
_DOWNLOAD_BACKOFF = 1.5  # seconds, doubled per retry: 1.5s, 3s
_DOWNLOAD_RETRY_AFTER_CAP = 30.0  # a CDN's Retry-After, capped

#: mll fans a vanilla install out over thousands of asset objects across
#: ThreadPoolExecutor(max_workers=None) - up to 32 threads on a normal CPU -
#: while handing them a session with requests' default pool of 10. Every thread
#: past the tenth then builds (and discards) its own TCP+TLS connection per
#: file. One process-wide session this wide lets all of them reuse a warm
#: connection; with ~4000 small files the handshakes were a real slice of the
#: "install is so slow" wall clock. Built lazily so importing cubeon.versions
#: never drags `requests` in ahead of an actual install.
_MLL_POOL_SIZE = 32
_mll_session = None
_mll_session_lock = threading.Lock()


def _install_session():
    """The shared, wide connection pool every mll file fetch goes through."""
    global _mll_session
    with _mll_session_lock:
        if _mll_session is None:
            import requests
            from requests.adapters import HTTPAdapter
            session = requests.Session()
            adapter = HTTPAdapter(pool_connections=_MLL_POOL_SIZE,
                                  pool_maxsize=_MLL_POOL_SIZE,
                                  max_retries=0)  # our own retries, with resume
            session.mount("https://", adapter)
            session.mount("http://", adapter)
            _mll_session = session
    return _mll_session


#: path -> (size, mtime_ns) for files this process has already hashed and found
#: correct. A loader install runs install_minecraft_version more than once (the
#: base version, then the loader profile whose json inheritsFrom it) and every
#: pass re-hashes every library and asset - thousands of files, hundreds of MB,
#: for an answer we already have. Size+mtime is the same evidence the instance
#: list trusts between launches, and rewriting a file changes its mtime, so a
#: stale entry can never vouch for new bytes.
_VERIFIED_FILES: "dict[str, tuple[int, int, str | None]]" = {}
_verified_lock = threading.Lock()


class _MllDownloadError(RuntimeError):
    """A file the install needs could not be fetched - with a message written
    for the user. install_version shows this text instead of a class name."""


def _mll_modules() -> list:
    """Every mll module that carries a download/install name of its own.

    mll imports these into several modules (`from .install import
    install_minecraft_version` is repeated in fabric, forge, quilt and mrpack),
    so patching minecraft_launcher_lib.install alone would leave a loader
    install calling the original. Enumerated dynamically and duck-typed rather
    than hardcoded, so the SimpleNamespace stand-ins a test builds for mll are
    patched exactly like the real thing.
    """
    mods = []
    for name in dir(mll):
        try:
            mod = getattr(mll, name)
        except Exception:
            continue
        if (hasattr(mod, "download_file")
                or hasattr(mod, "install_minecraft_version")):
            mods.append(mod)
    # mll 8's unified loaders use _internal.mod_loader.* modules rather
    # than the deprecated top-level fabric/forge functions.
    for name, mod in tuple(sys.modules.items()):
        if (name.startswith("minecraft_launcher_lib.") and mod is not None
                and (hasattr(mod, "download_file")
                     or hasattr(mod, "install_minecraft_version"))
                and mod not in mods):
            mods.append(mod)
    return mods


def _make_resilient_download_file():
    """Builds a drop-in replacement for mll 8.0's _helper.download_file.

    Why a replacement at all (the 2026-10-17 report: "download on instances
    isn't working on some users"): mll's downloader reports a bad status by
    returning False, and every one of its callers ignores that return value.
    So a CDN answering 429 to a burst of asset requests, or a proxy dropping a
    connection mid-jar, produced an install that "completed" with holes in it,
    with nothing in the UI to say which file was missing. This one:
      * bounds connect (15s) and read (60s);
      * retries 3x with backoff on network errors, timeouts, 5xx and 429
        (honouring a Retry-After header), resuming from the bytes already on
        disk with a Range request instead of starting the file over;
      * verifies sha1 and takes the whole file again on a mismatch;
      * raises with the file and the status on a permanent failure, so the
        error names what is missing instead of failing silently.

    The signature mirrors mll's exactly, including `session`, which is ignored
    in favour of Cubeon's own wide pool (mll builds one session per phase and
    never closes it). Used for EVERY install, cancellable or not: the
    resilience is the point, not the cancel.
    """
    import lzma
    from minecraft_launcher_lib._helper import (
        check_path_inside_minecraft_directory, get_sha1_hash, get_user_agent)
    from minecraft_launcher_lib.exceptions import InvalidChecksum

    def _stopped() -> bool:
        for bridge in tuple(_live_cancel_bridges):
            if bridge.should_stop():
                return True
        return False

    def _remember(path, sha1) -> None:
        try:
            stat = os.stat(path)
        except OSError:
            return
        with _verified_lock:
            _VERIFIED_FILES[str(path)] = (stat.st_size, stat.st_mtime_ns, sha1)

    def _verified(path, sha1) -> bool:
        try:
            stat = os.stat(path)
        except OSError:
            return False
        with _verified_lock:
            return _VERIFIED_FILES.get(str(path)) == (stat.st_size,
                                                      stat.st_mtime_ns, sha1)

    def _wait(attempt, retry_after=None) -> None:
        """Backoff between attempts. Retry-After wins when the server sends one
        (a CDN rate limiter asking us to slow down), capped so a hostile value
        cannot park the install."""
        if attempt >= _DOWNLOAD_ATTEMPTS - 1:
            return
        delay = _DOWNLOAD_BACKOFF * (2 ** attempt)
        try:
            if retry_after:
                delay = max(delay,
                            min(float(retry_after), _DOWNLOAD_RETRY_AFTER_CAP))
        except (TypeError, ValueError):
            pass
        deadline = time.monotonic() + delay
        while time.monotonic() < deadline:
            if _stopped():
                raise _DownloadCancelled()
            time.sleep(min(0.1, max(0, deadline - time.monotonic())))

    def download_file(url, path, callback=None, sha1=None, lzma_compressed=False,
                      session=None, minecraft_directory=None, overwrite=False):
        if callback is None:
            callback = {}
        if minecraft_directory is not None:
            check_path_inside_minecraft_directory(minecraft_directory, path)
        if _stopped():
            raise _DownloadCancelled()
        if os.path.isfile(path) and not overwrite:
            if sha1 is None:
                return False
            if _verified(path, sha1) or get_sha1_hash(path) == sha1:
                _remember(path, sha1)
                return False
        try:
            os.makedirs(os.path.dirname(path))
        except Exception:
            pass
        callback.get("setStatus", lambda *_: None)(
            "Download " + os.path.basename(path))
        headers = {"user-agent": get_user_agent()}
        http = _install_session()
        clean = os.path.basename(path)
        part_path = str(path) + ".part"
        last_err = None
        for attempt in range(_DOWNLOAD_ATTEMPTS):
            if _stopped():
                raise _DownloadCancelled()
            # Only staged bytes are resumable. A checksum-invalid final file
            # is never assumed to be a prefix, and remains intact on failure.
            offset = 0
            if not lzma_compressed and not overwrite:
                try:
                    if os.path.isfile(part_path):
                        offset = os.path.getsize(part_path)
                except OSError:
                    offset = 0
            req_headers = dict(headers)
            if offset:
                req_headers["Range"] = f"bytes={offset}-"
            try:
                resp = http.get(url, stream=True, timeout=_MIRROR_TIMEOUT,
                                headers=req_headers)
            except Exception as ex:
                last_err = ex
                _wait(attempt)
                continue
            try:
                status = resp.status_code
                if 500 <= status < 600 or status == 429:
                    last_err = _MllDownloadError(
                        f"{clean} is temporarily unavailable (HTTP {status})")
                    _wait(attempt, resp.headers.get("Retry-After"))
                    continue
                if status == 416 and offset:
                    # Our resume offset is stale - the file on disk is longer
                    # than this body, or is not part of it at all. Drop it and
                    # take the file whole instead of failing the install over a
                    # bad guess. Deleting means the retry sends no Range, so
                    # this can only ever happen once per download.
                    try:
                        os.remove(part_path)
                    except OSError:
                        pass
                    last_err = _MllDownloadError(
                        f"{clean} restarted from scratch (stale partial file)")
                    _wait(attempt)
                    continue
                if status not in (200, 206):
                    # A 4xx is an answer, not a blip: retrying cannot help, and
                    # mll's silent `return False` here is the hole this whole
                    # function exists to close.
                    raise _MllDownloadError(
                        f"{clean} is not on the server (HTTP {status})")
                if status == 206:
                    match = re.fullmatch(r"bytes (\d+)-(\d+)/(\d+)",
                                         resp.headers.get("Content-Range", ""))
                    if (not match or int(match[1]) != offset
                            or int(match[2]) + 1 != int(match[3])):
                        # Appending the wrong range corrupts a file even when
                        # the server returns a superficially successful 206.
                        try:
                            os.remove(part_path)
                        except OSError:
                            pass
                        raise ValueError("Invalid download range")
                written = 0
                with open(part_path, "ab" if status == 206 else "wb") as fh:
                    if lzma_compressed:
                        fh.write(lzma.decompress(resp.content))
                    else:
                        resp.raw.decode_content = True
                        while True:
                            if _stopped():
                                raise _DownloadCancelled()
                            chunk = resp.raw.read(65536)
                            if not chunk:
                                break
                            fh.write(chunk)
                            written += len(chunk)
                if not lzma_compressed and not resp.headers.get("Content-Encoding"):
                    length = resp.headers.get("Content-Length")
                    if length is not None and written != int(length):
                        raise ValueError("Download ended before all bytes arrived")
                    if status == 206 and os.path.getsize(part_path) != int(match[3]):
                        raise ValueError("Incomplete download range")
            except _DownloadCancelled:
                raise
            except _MllDownloadError:
                raise
            except Exception as ex:
                last_err = ex
                _wait(attempt)
                continue
            finally:
                try:
                    resp.close()
                except Exception:
                    pass
            if sha1 is not None:
                checksum = get_sha1_hash(part_path)
                if checksum != sha1:
                    # A resumed file that still does not match is not a prefix
                    # of this body: throw it away and take the whole file.
                    try:
                        os.remove(part_path)
                    except OSError:
                        pass
                    last_err = InvalidChecksum(url, path, sha1, checksum)
                    _wait(attempt)
                    continue
            if _stopped():
                raise _DownloadCancelled()
            os.replace(part_path, path)
            _remember(path, sha1)
            return True
        if isinstance(last_err, _MllDownloadError):
            raise last_err
        raise _MllDownloadError(
            f"{clean} could not be downloaded after {_DOWNLOAD_ATTEMPTS} tries"
            f" ({last_err.__class__.__name__ if last_err else 'no response'})")

    return download_file


class _PatchedMllDownloads:
    """Context manager: holds Cubeon's mll patches for the length of one install.

    Beyond the resilient downloader above, two install-wide shortcuts:

      * install_minecraft_version() is memoised per version id. A loader
        install calls it for the base version, then again for the loader
        profile whose json inheritsFrom the base - and mll's inheritsFrom branch
        re-installs the base inside THAT call, so the base pass runs two or
        three times for one Fabric/Forge install, re-walking every library and
        asset each time. The loader profile's own libraries are real work and
        still happen; the repeat of a version already finished in THIS install
        is skipped, which is the difference between one full pass and two.
      * install_jvm_runtime() is skipped when the caller passes explicit_java:
        mll then downloads a whole second JDK - tens of MB, hundreds of files -
        into the game directory that the launch never uses, because
        build_launch_command passes executablePath. It is kept by default
        because without an explicit path mll's own command builder falls back
        to exactly that runtime (minecraft_launcher_lib/command.py), and on a
        machine with no Java of its own it is the only Java there is.

    Tolerant of a fake mll (tests): only modules that actually expose the names
    are touched, and __exit__ puts back exactly what was there.
    """

    def __init__(self, bridge: "_InstallCancelBridge | None" = None,
                 explicit_java: bool = False):
        self._bridge = bridge
        self._explicit_java = explicit_java
        self._saved: "list[tuple[object, str, object]]" = []
        #: Version ids install_minecraft_version has already finished in this
        #: install - the memo that kills the repeated base pass.
        self._done: "set[str]" = set()

    def _swap(self, mod, name, replacement) -> None:
        if mod is not None and hasattr(mod, name):
            self._saved.append((mod, name, getattr(mod, name)))
            setattr(mod, name, replacement)

    def __enter__(self):
        while not _mll_patch_lock.acquire(timeout=0.1):
            if self._bridge is not None and self._bridge.should_stop():
                raise _DownloadCancelled()
        try:
            return self._enter_locked()
        except BaseException:
            self.__exit__()
            raise

    def _enter_locked(self):
        with _bridges_lock:
            if self._bridge is not None:
                _live_cancel_bridges.append(self._bridge)
            downloader = _make_resilient_download_file()
            install_mod = getattr(mll, "install", None)

            def _memoised(original):
                def call(version, *args, **kwargs):
                    if version in self._done:
                        return None
                    original(version, *args, **kwargs)
                    self._done.add(version)
                return call

            for mod in _mll_modules():
                self._swap(mod, "download_file", downloader)
                if hasattr(mod, "install_minecraft_version"):
                    self._swap(mod, "install_minecraft_version",
                               _memoised(getattr(mod,
                                                 "install_minecraft_version")))
                if mod is install_mod and self._explicit_java:
                    self._swap(mod, "install_jvm_runtime", lambda *a, **k: None)
        return self

    def __exit__(self, *exc):
        with _bridges_lock:
            if self._bridge is not None and self._bridge in _live_cancel_bridges:
                _live_cancel_bridges.remove(self._bridge)
            for mod, name, original in self._saved:
                try:
                    setattr(mod, name, original)
                except Exception:
                    pass  # a fake mll that rejects rebinding - nothing to undo
            self._saved.clear()
        _mll_patch_lock.release()
        return False


#: An asset object's name on disk is its sha1 - 40 hex characters, no
#: extension, nothing a human can read. Deliberately narrow (the full 40, or a
#: long run of hex) so no real library/file name can be swallowed by it.
_HEX_NAME_RE = re.compile(r"^(?:[0-9a-f]{40}|[0-9a-f]{16,})$")


class _FriendlyStatus:
    """Turns mll's per-file status into something a player can read.

    mll names every file it fetches by its basename, which is fine for
    libraries ("authlib-6.0.54.jar") but useless for the asset phase: there the
    basename is the object's raw sha1, so the launcher's status line read
    "Download c4dbabc820f04ba685694c63359429b22e3a62b5" - a wall of hex that
    looks like a memory address and tells the user nothing at all. Assets are
    interchangeable to a human, so they are reported as their phase plus how
    many of how many, which is also what makes the progress bar's numbers mean
    something.
    """

    def __init__(self):
        self.max = 0
        self.current = 0

    def progress(self, value) -> None:
        try:
            self.current = int(value)
        except (TypeError, ValueError):
            pass

    def maximum(self, value) -> None:
        try:
            self.max = int(value)
        except (TypeError, ValueError):
            pass

    def status(self, text) -> str:
        if not isinstance(text, str) or not text.startswith("Download "):
            return text
        name = text[len("Download "):].strip()
        if not _HEX_NAME_RE.match(name):
            return text
        if self.max > 0:
            return (f"Downloading game assets "
                    f"({min(self.current, self.max)}/{self.max})")
        return "Downloading game assets"


def _manifest_entry(version_id: str) -> "dict | None":
    """The cached manifest's own record for a version - its json url + sha1 -
    or None when the manifest doesn't know it (a snapshot, an old alpha, or a
    renamed TLauncher-style id)."""
    try:
        for v in _manifest().get("versions", []):
            if v.get("id") == version_id and isinstance(v.get("url"), str):
                return v
    except Exception:
        return None
    return None


def _seed_version_json(version_id: str, folder: str, json_path: str,
                       status_cb, max_cb, progress_cb,
                       bridge: "_InstallCancelBridge | None" = None) -> None:
    """Put a version's own json on disk before mll goes looking for it.

    Why this exists: mll's install_minecraft_version() checks for
    versions/<id>/<id>.json and, when it is missing, starts with a bare
    requests.get() of Mojang's ~4 MB version_manifest_v2.json - no status, no
    progress, no timeout and no retry. That is a long silent "Preparing" on a
    slow link (and a possible indefinite hang on a flaky one) on the FIRST
    install of every version, before a single progress callback can fire.

    Cubeon already keeps that manifest for the version list - cached on disk,
    served stale when offline, retried, with a mirror fallback - so the one
    small file mll actually needs can be fetched here instead, where progress
    and cancellation work. mll then finds it waiting and goes straight to the
    libraries/assets phases, whose progress is what the user expects to see.

    Strictly best-effort: anything unexpected (no manifest entry, a bad
    checksum, no network) and mll does it the old way. A slow path must never
    become a broken one.

    A cancel is the one failure NOT swallowed: this runs before mll, so a
    cancel arriving here (or during the fetch) has to abort the install the
    same way a mid-download cancel does, not sit behind a blocking request.
    `bridge` is the install's own cancel bridge, so only this install's
    threads see the flag - see _InstallCancelBridge.
    """
    if os.path.isfile(json_path):
        return
    status_cb("Fetching the version files")
    if bridge is not None and bridge.should_stop():
        raise _DownloadCancelled()
    entry = _manifest_entry(version_id)
    if not entry:
        return  # not ours to guess - mll's own lookup handles it
    sha1 = entry.get("sha1")
    seen_total = {"v": None}

    def _on_progress(done, total):
        if bridge is not None and bridge.should_stop():
            raise _DownloadCancelled()
        if total and total != seen_total["v"]:
            seen_total["v"] = total
            max_cb(total)
        progress_cb(done)

    try:
        os.makedirs(folder, exist_ok=True)
        net.download_to(
            json_path, entry["url"],
            expected_hash=("sha1", sha1) if sha1 else None,
            progress_cb=_on_progress)
    except _DownloadCancelled:
        # A cancel is a choice, not a failure to fall back from: drop the
        # partial and let install_version report it like any other cancel.
        try:
            os.unlink(json_path + ".part")
        except OSError:
            pass
        raise
    except Exception:
        # Leave nothing half-written behind for mll to read as the version
        # metadata; a download_to failure keeps its bytes in the .part file.
        try:
            if not os.path.isfile(json_path):
                os.unlink(json_path + ".part")
        except OSError:
            pass


def install_version(version_id: str, progress_cb, status_cb, max_cb,
                    cancel_event: "threading.Event | None" = None,
                    explicit_java: bool = False) -> None:
    """progress_cb(int), status_cb(str), max_cb(int) - mirrors mll's callback dict.

    cancel_event (optional): a threading.Event; when given, the download mll
    performs is made cancellable PER CHUNK and gets a read timeout - without
    it a cancel was only honored at the next file boundary, and a stalled
    connection could hang the install for minutes with no callback firing.
    See the _PatchedMllDownloads comment above for how the mapping works. The
    resilient downloader (timeouts, retries, resume, checksum) is installed
    with or without a cancel_event - only the abort depends on it.

    explicit_java: True when the caller launches this version with a Java path
    of its own (Cubeon passes cfg["java_path"]), so the copy of Java mll would
    install into the game directory is never the JVM the game runs on and is
    skipped - a whole second JDK, tens of MB. Leave it False otherwise: see
    _PatchedMllDownloads for why that runtime is load-bearing.

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
    # Every callback is wrapped: the status one so the asset phase reports
    # something readable instead of a sha1 (see _FriendlyStatus), and all three
    # so the cancel bridge sees which thread is downloading.
    friendly = _FriendlyStatus()

    def _status(text):
        status_cb(friendly.status(text))

    def _progress(value):
        friendly.progress(value)
        progress_cb(value)

    def _maximum(value):
        friendly.maximum(value)
        max_cb(value)

    callback = {"setStatus": _status, "setProgress": _progress,
                "setMax": _maximum}
    if cancel_event is not None:
        # The download runs on mll's own worker threads; register each thread
        # with this install's bridge the moment it reports a status, so the
        # chunk loop below knows exactly whose cancel it is checking.
        bridge = _InstallCancelBridge(cancel_event)
        bridge.note_thread()  # the install thread itself downloads json/index/jar

        def _noted(cb):
            def call(*a):
                bridge.note_thread()
                cb(*a)
            return call
        callback = {"setStatus": _noted(_status),
                    "setProgress": _noted(_progress),
                    "setMax": _noted(_maximum)}
    else:
        bridge = None
    folder = os.path.join(MINECRAFT_DIR, "versions", version_id)
    json_path = os.path.join(folder, version_id + ".json")
    # Did this attempt create the version folder, or is it re-installing over
    # one that was already there? A failed FRESH install must leave nothing
    # behind: the seeded json alone would otherwise sit in the list wearing
    # "(incomplete)" until the next startup sweep (2026-10-26 report).
    folder_existed = os.path.isdir(folder)
    jar_sizes_before = _jar_sizes(folder)

    def _drop_attempt_jars() -> None:
        """Removes only the jar files THIS failed attempt is responsible for:
        new files, or a known name whose size changed (mll overwrote it with
        a partial download - the pre-attempt bytes are gone either way).
        Anything pre-existing and size-unchanged survives. A folder this
        attempt created is removed entirely, so a failed fresh install never
        lingers as an "(incomplete)" instance."""
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
        if not folder_existed:
            shutil.rmtree(folder, ignore_errors=True)
        status_cb("Download interrupted - partial files cleaned up. "
                  "Reconnect and try again.")

    with _active_install(version_id):
        # Seed the version json ourselves (see _seed_version_json) - without
        # this, mll answers the missing json with a silent, un-timed 4 MB
        # manifest fetch before its first progress callback, which is the "it
        # prepares for a long time" the user sees on a first install. It
        # carries the same cancel bridge as the mll call below, so Cancel works
        # during this step too.
        try:
            _seed_version_json(version_id, folder, json_path, status_cb,
                               _maximum, _progress, bridge)
        except _DownloadCancelled as ex:
            _drop_attempt_jars()
            raise RuntimeError(
                "The download was cancelled.") from ex

        try:
            try:
                # Always patched - a cancellable install is not the only one
                # that needs timeouts, retries, resume and a checksum, and the
                # repeated base pass of a loader install is skipped for every
                # caller.
                with _PatchedMllDownloads(bridge,
                                          explicit_java=explicit_java):
                    mll.install.install_minecraft_version(
                        version_id, MINECRAFT_DIR, callback=callback)
            finally:
                if bridge is not None:
                    bridge.release()
        except _DownloadCancelled as ex:
            # Same cleanup as any other failure: a half-written client jar left
            # in the version folder is a version the list would call installed
            # and the launcher would then try to run (the 2026-09-17 report).
            # Assets and libraries are NOT dropped - those resume from where
            # they stopped.
            _drop_attempt_jars()
            raise RuntimeError("The download was cancelled.") from ex
        except Exception as ex:
            _drop_attempt_jars()
            if isinstance(ex, _MllDownloadError):
                # Our downloader writes for the user ("client.jar is not on the
                # server (HTTP 404)"); that text is the whole point of it.
                raise RuntimeError(f"The download failed: {ex}.") from ex
            raise RuntimeError(
                f"The download was interrupted ({ex.__class__.__name__}). "
                "Your files were cleaned up - reconnect and install again."
            ) from ex

        # mll "succeeded" - prove it. The version json it wrote lists the exact
        # size and sha1 of the client jar; anything else is a corrupted
        # download.
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
