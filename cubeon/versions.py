"""
Minecraft version listing (installed + available) and vanilla install.
Mod-loader-specific installs live in mod_loaders.py.
"""
import json
import os
import re
import shutil

import minecraft_launcher_lib as mll

from .paths import MINECRAFT_DIR


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

        json_files = [f for f in os.listdir(folder_path) if f.endswith(".json")]
        jar_files = [f for f in os.listdir(folder_path) if f.endswith(".jar")]
        if not json_files:
            continue  # not a version folder at all, nothing to go on

        json_path = os.path.join(folder_path, json_files[0])
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError):
            continue

        real_id = data.get("id", folder)
        if real_id in found:
            continue  # already picked up by the strict scan

        has_jar = bool(jar_files)
        # A version can be launchable via inheritsFrom (e.g. Fabric/Forge
        # profiles reuse the vanilla jar) even without its own jar file.
        inherits = data.get("inheritsFrom")
        is_complete = has_jar or bool(inherits)

        if not is_complete:
            found[folder] = {
                "id": folder,
                "display_name": f"{suggest_friendly_name(real_id, folder)} (incomplete)",
                "type": data.get("type", "release"),
                "folder": folder,
                "incomplete": True,
                "issue": "Missing client .jar. This install didn't finish downloading.",
            }
            continue

        # The launch command needs <folder>/<folder>.json and <folder>/<folder>.jar
        # to exist (that's how mll resolves the version internally), so if this
        # folder's json/jar aren't named after the folder, normalize it.
        expected_json = os.path.join(folder_path, folder + ".json")
        expected_jar = os.path.join(folder_path, folder + ".jar")
        if not os.path.isfile(expected_json):
            shutil.copy(json_path, expected_json)
        if has_jar and not os.path.isfile(expected_jar):
            shutil.copy(os.path.join(folder_path, jar_files[0]), expected_jar)

        found[folder] = {
            "id": folder,  # use folder name as launch id since that's what mll needs
            "display_name": suggest_friendly_name(real_id, folder),
            "type": data.get("type", "release"),
            "folder": folder,
        }

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


def get_available_versions(include_snapshots=False, include_old=False) -> list[dict]:
    versions = mll.utils.get_version_list()
    out = []
    for v in versions:
        if v["type"] == "release":
            out.append(v)
        elif v["type"] == "snapshot" and include_snapshots:
            out.append(v)
        elif v["type"] in ("old_alpha", "old_beta") and include_old:
            out.append(v)
    return out


def get_latest_release() -> str:
    return mll.utils.get_latest_version()["release"]


def install_version(version_id: str, progress_cb, status_cb, max_cb) -> None:
    """progress_cb(int), status_cb(str), max_cb(int) - mirrors mll's callback dict."""
    callback = {"setStatus": status_cb, "setProgress": progress_cb, "setMax": max_cb}
    mll.install.install_minecraft_version(version_id, MINECRAFT_DIR, callback=callback)
