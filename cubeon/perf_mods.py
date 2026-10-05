"""
Client performance add-on for the Cubeon Client.

The Cubeon Client itself is a social mod: it draws a small name badge and opens
the Friends screen. It is deliberately cheap, which also means it does not make
Minecraft render any faster - so "activate Cubeon Client" would otherwise get
the button and nothing else. This module closes that gap by installing **Sodium**
(Modrinth `sodium`) into the same (mc_version, loader) profile.

**Sodium only, on purpose (2026-10-05).** The suite used to carry eight more
mods (Lithium, ImmediatelyFast, EntityCulling, MoreCulling, BadOptimizations,
Krypton, ThreadTweak, Dynamic FPS). Sodium is by itself the overwhelming share
of the client FPS win: it replaces the terrain/entity renderer, which is what a
CPU-bound client actually waits on. The extras added little on top, and the
broader the pile the more third-party crash surface it carried - EntityCulling
alone crashed the game on its first tick from a legacy config (see
`sanitize_entityculling_config` below). The user asked for exactly this: "no
more mods, just optimizing the Minecraft". Do not widen this list again without
the user's say-so.

Sodium is fetched from Modrinth exactly like a mod the user picked themselves:
matched to the profile's Minecraft version and loader, stored in the profile
folder, and skipped when it is already present (including a manual install).
The launcher's normal mod sync then carries it into the game.

`prune_retired_perf_mods()` removes the eight retired mods from a profile that
already has them, so an existing install stops loading the pile instead of
waiting for the user to delete eight jars by hand.

Best-effort by design, because this runs inside the launch path: no build for
this Minecraft version, a dead network, or a jar the user manages by hand all
just mean there is no boost. Nothing here can stop the game from starting.
"""
import json
import os

from .mod_loaders import MOD_CAPABLE_LOADERS
from .mods import (delete_mod, download_mod, get_mod_download, list_mods,
                   name_stem)

# (Modrinth slug, Modrinth project id, display label), in install order.
# Sodium only - see the module docstring for why the suite was narrowed.
PERF_MODS = (
    ("sodium", "AANobbMI", "Sodium"),
)

# The perf mods the suite used to install, kept here so an existing profile can
# be cleaned up (see prune_retired_perf_mods). Do NOT re-add these to
# PERF_MODS without the user's say-so.
RETIRED_PERF_MODS = (
    ("lithium", "gvQqBUqZ"),
    ("immediatelyfast", "5ZwdcRci"),
    ("entityculling", "NNAgCjsB"),
    ("moreculling", "51shyZVL"),
    ("badoptimizations", "g96Z4WVZ"),
    ("krypton", "fQEb0iXm"),
    ("threadtweak", "vSEH1ERy"),
    ("dynamic-fps", "LQ3K71Q1"),
)

# Kept as its own name: tests and callers refer to the slug tuple.
PERF_MOD_SLUGS = tuple(slug for slug, _pid, _label in PERF_MODS)

_LABELS = {slug: label for slug, _pid, label in PERF_MODS}

# EntityCulling's own whitelist arrays are a crash-on-start hazard. The mod is
# no longer installed by the suite, but a profile that already has it (from an
# older Cubeon, or the user's own install) can carry a legacy config: written by
# an older EntityCulling and never cleaned, its defaults and ConfigUpgrader only
# ever ADD resource ids. A `null` or an empty string in the list makes 1.11.2's
# `clientTick` throw while parsing it as a ResourceLocation:
#   NullPointerException: Cannot invoke "String.indexOf(int)" because "$$0" is null
# on the first tick - the window never reaches the menu. So Cubeon repairs the
# config before each launch. Only entries that cannot run are dropped; the
# player's own (and every valid default) entry is preserved.
_ENTITYCULLING_LISTS = (
    "blockEntityWhitelist",
    "entityWhitelist",
    "tickCullingWhitelist",
)


def entityculling_config_path() -> str:
    from .paths import MINECRAFT_DIR
    return os.path.join(MINECRAFT_DIR, "config", "entityculling.json")


def sanitize_entityculling_config(path: str | None = None) -> dict:
    """Drops null/empty whitelist entries from EntityCulling's config, in place.

    Returns {"removed", "detail", "path"}. Never raises: a missing or
    unreadable file means EntityCulling has not run yet, or the user does not
    use it - nothing to repair either way. Idempotent: a clean config is left
    byte-for-byte and reports removed == 0.
    """
    target = path or entityculling_config_path()
    result = {"removed": 0, "detail": "", "path": target}
    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except (OSError, ValueError):
        result["detail"] = "no readable entityculling.json"
        return result
    if not isinstance(data, dict):
        result["detail"] = "entityculling.json is not an object"
        return result

    removed = 0
    for key in _ENTITYCULLING_LISTS:
        current = data.get(key)
        if not isinstance(current, list):
            continue
        cleaned = [v for v in current
                   if isinstance(v, str) and v.strip()]
        if len(cleaned) != len(current):
            removed += len(current) - len(cleaned)
            data[key] = cleaned
    if not removed:
        result["detail"] = "entityculling whitelists already clean"
        return result

    try:
        tmp = target + ".cubeon-tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, target)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        result["detail"] = "entityculling.json is not writable"
        return result

    result["removed"] = removed
    result["detail"] = ("removed %d unrunnable EntityCulling whitelist "
                        "entr%s" % (removed, "y" if removed == 1 else "ies"))
    return result


def _present(mc_version: str | None, loader: str | None) -> set:
    """The performance mods already in this profile, by slug.

    Matches the recorded Modrinth slug, the display name, the project id and
    the filename, so a jar the user dropped in by hand still counts - a second
    copy of Sodium is a duplicate-mod crash, not a boost."""
    found: set = set()
    if not mc_version or loader not in MOD_CAPABLE_LOADERS:
        return found
    try:
        mods = list_mods(mc_version, loader)
    except Exception:
        return found
    for mod in mods:
        identities = {str(mod.get(key) or "").lower()
                      for key in ("slug", "display_name", "project_id")}
        identities.add(name_stem(mod.get("filename") or ""))
        for slug, project_id, _label in PERF_MODS:
            if slug in identities or project_id.lower() in identities:
                found.add(slug)
    return found


def is_installed(mc_version: str | None, loader: str | None) -> bool:
    """True when every performance mod is already in the profile."""
    if not mc_version or loader not in MOD_CAPABLE_LOADERS:
        return False
    return _present(mc_version, loader) >= set(PERF_MOD_SLUGS)


def prune_retired_perf_mods(mc_version: str | None, loader: str | None) -> list:
    """Removes the retired perf mods from a profile that already has them.

    Only entries Cubeon itself installed are eligible: the match is on the
    Modrinth slug / project id recorded in the jar's sidecar metadata, never on
    a filename stem, so a jar the user dropped in by hand is left alone.
    Returns the display labels removed. Never raises - this is a cleanup on the
    launch path, not a requirement.
    """
    removed: list = []
    if not mc_version or loader not in ("fabric", "quilt"):
        return removed
    retired_slugs = {slug for slug, _pid in RETIRED_PERF_MODS}
    retired_pids = {pid.lower() for _slug, pid in RETIRED_PERF_MODS}
    try:
        mods = list_mods(mc_version, loader)
    except Exception:
        return removed
    for mod in mods:
        slug = (mod.get("slug") or "").lower()
        project_id = (mod.get("project_id") or "").lower()
        if slug in retired_slugs or (project_id and project_id in retired_pids):
            try:
                delete_mod(mc_version, loader, mod["filename"])
                removed.append(slug or project_id)
            except Exception:
                pass
    return removed


def ensure_installed(mc_version: str | None, loader: str | None,
                     status_cb=None) -> dict:
    """Installs any missing performance mod into the profile.

    Returns {"installed", "kept", "failed", "detail"} so the caller can log or
    show what actually happened. Never raises: every failure is reported as a
    slug in "failed" and the launch continues.
    """
    result = {"installed": [], "kept": [], "failed": [], "detail": ""}

    if not mc_version:
        result["detail"] = "no Minecraft version selected"
        return result
    if loader not in ("fabric", "quilt"):
        # These mods ship as Fabric mods; Forge/NeoForge/vanilla have no
        # compatible build to fetch, so there is nothing to pretend about.
        result["detail"] = "performance mods need a Fabric or Quilt profile"
        return result

    present = _present(mc_version, loader)
    for slug, project_id, label in PERF_MODS:
        if slug in present:
            result["kept"].append(slug)
            continue
        try:
            file_info = get_mod_download(slug, mc_version=mc_version, loader=loader)
            if not file_info:
                result["failed"].append(slug)
                continue
            if status_cb:
                status_cb(f"Installing {label}")
            download_mod(
                file_info["url"], file_info["filename"],
                slug=slug, project_id=project_id,
                mc_version=mc_version, loader=loader,
                hashes=file_info.get("hashes"),
            )
            result["installed"].append(slug)
        except Exception:
            # Network, disk, a version with no build - all the same answer:
            # the boost is smaller, the game still launches.
            result["failed"].append(slug)

    parts = []
    if result["installed"]:
        parts.append("installed " + ", ".join(
            _LABELS.get(s, s) for s in result["installed"]))
    if result["kept"]:
        parts.append("already had " + ", ".join(
            _LABELS.get(s, s) for s in result["kept"]))
    if result["failed"]:
        parts.append("couldn't get " + ", ".join(
            _LABELS.get(s, s) for s in result["failed"]))
    result["detail"] = "; ".join(parts)
    return result
