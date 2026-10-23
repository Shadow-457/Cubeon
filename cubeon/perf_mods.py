"""
Client performance add-on for the Cubeon Client.

The Cubeon Client itself is a social mod: it draws a small name badge and opens
the Friends screen. It is deliberately cheap, which also means it does not make
Minecraft render any faster - so "activate Cubeon Client" would otherwise get
the button and nothing else. This module closes that gap by installing **Sodium**
(Modrinth `sodium`) into the same (mc_version, loader) profile.

**Six mods (2026-10-14).** Sodium alone was the 2026-10-05 answer ("no more
mods"), but the user then asked for "twice as much FPS as any launcher", which
Sodium alone cannot deliver - its win is the terrain/entity renderer, and the
rest of the frame budget lives elsewhere. The suite is therefore the proven
companion set, each with a distinct job and measured gains on top of Sodium:

  - Sodium            terrain/entity renderer (the big one)
  - Lithium           game logic (tick loop, physics, block entities)
  - ImmediatelyFast   HUD/text/entity immediate-mode rendering
  - Entity Culling    skips drawing entities/blocks the camera can't see
  - FerriteCore       memory footprint (smaller heap -> shorter GC pauses)
  - More Culling      culls block faces/particles the camera can't see

ThreadTweak, BadOptimizations, Krypton and Dynamic FPS stay retired: measured
to add little on this stack and each is more third-party crash surface. This
list is again user-directed ("I need twice as much FPS, more fps please") -
narrowing it back is fine, widening it further needs the user's say-so.

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
# Sodium first (biggest win, the one players recognise), then the companions.
PERF_MODS = (
    ("sodium", "AANobbMI", "Sodium"),
    ("lithium", "gvQqBUqZ", "Lithium"),
    ("immediatelyfast", "5ZwdcRci", "ImmediatelyFast"),
    ("entityculling", "NNAgCjsB", "Entity Culling"),
    ("ferrite-core", "uXXizFIs", "FerriteCore"),
    ("moreculling", "51shyZVL", "More Culling"),
)

# The perf mods the suite used to install (2026-10-05 - 2026-10-14), kept here
# so an existing profile can be cleaned up (see prune_retired_perf_mods). Do
# NOT re-add these to PERF_MODS without the user's say-so.
RETIRED_PERF_MODS = (
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


# ---------------------------------------------------------------------------
# Sodium's own options (2026-10-18)
# ---------------------------------------------------------------------------
# Sodium's settings live in two places. The ones that mirror a vanilla option
# (render distance, graphics, clouds, ao, mipmaps, entity distance, ...) are
# BOUND to options.txt, and game_options.py already writes them. The
# renderer-only ones - the ones the vanilla screen has no equivalent for, and
# the ones that decide whether the renderer actually does the cheap thing - are
# kept in <game dir>/config/sodium-options.json.
#
# Unlike options.txt there is nothing to save for turning the boost off: every
# default in Sodium 0.8.x IS already the fast value, with ONE exception -
# chunk_builder_threads (see chunk_builder_threads() below). The rest was read
# straight off the option holder (SodiumOptions$*Settings, values verified by
# decompiling sodium-fabric 0.8.14): hiddenFluidCulling true,
# chunkBuildDeferMode ALWAYS, quadSplittingMode SAFE, useAdvancedStagingBuffers
# true, cpuRenderAheadLimit 3.
# So this is a REPAIR, not a preset - every key here is Sodium's own default
# except chunk_builder_threads - and it exists because nothing stops a
# profile from holding a config that is not the default: an older Sodium, an
# older Cubeon, or a "raise your FPS" guide telling the player to switch fog
# occlusion off. Those files sat there forever and kept the renderer doing work
# it did not have to, which is exactly the "my FPS did not change" report this
# closes. The file is rewritten on every boosted launch; FPS boost OFF simply
# stops enforcing it and hands Sodium's own config back to the player.
#
# Keys are matched by name against the section that is already in the file, so
# a config from a different Sodium generation is never given an unknown key:
# Sodium 0.4.x (Minecraft 1.20) keeps the same names for the shared performance
# switches (chunk_builder_threads, use_*_culling, animate_only_visible_textures)
# and simply has none of the newer ones (chunk_build_defer_mode,
# quad_splitting_mode, ...), which then no-op.
#
# Deliberately NOT touched, because they are taste rather than frame cost:
#   quality.pixel_filtering_mode          NEAREST (Sodium's default) vs LINEAR
#                                         texture filtering - a look, not a cost
#   quality.use_closest_point_entity_sort more correct translucent sorting,
#                                         off by default
#   notifications.*                       Sodium's own one-time prompts


def chunk_builder_threads() -> int:
    """How many Sodium chunk-builder threads Cubeon asks for: 2.

    Sodium's own default is 0 = Auto, which `ChunkBuilder.getThreadCount()`
    resolves to `clamp(max(cores/3, cores-6), 1, 10)` - 6 threads on a 12-core
    box. This is the one key in this table that is NOT Sodium's default, and
    that is deliberate.

    2026-10-18 the rule here was "never hardcode a thread count" (Auto was
    assumed better). 2026-10-24 the player measured the opposite on their own
    12-core machine: 2 builder threads gave steadier frame times than Auto's 6.
    That matches what chunk meshing is - bursty, memory-bound work that spends
    more time contending with the render thread and with itself the more
    builders there are. Their measurement beats the earlier theory, so 2 is the
    default now; the old note is kept in agents/docs/module-map.md so nobody
    "fixes" it back to Auto a third time.

    Still capped by cores so a small machine is never oversubscribed: 1 thread
    on a 1-2 core box, 2 from 3 cores up. Sodium clamps any value to
    `min(value, cores)` itself, so this can never ask for more than the box has.
    """
    cores = os.cpu_count() or 4
    return max(1, min(2, cores - 1))


SODIUM_MAX_FPS_OPTIONS = {
    "quality": {
        "hidden_fluid_culling": True,        # don't draw hidden fluid faces
        "improved_fluid_shaping": False,     # the cheap fluid mesher
    },
    "performance": {
        # 2, not Sodium's Auto (0): see chunk_builder_threads().
        "chunk_builder_threads": chunk_builder_threads(),
        "chunk_build_defer_mode": "ALWAYS",  # defer rebuilds off the frame
        "animate_only_visible_textures": True,
        "use_entity_culling": True,
        "use_fog_occlusion": True,
        "use_block_face_culling": True,
        "use_no_error_g_l_context": True,    # skip per-call GL error checks
        "quad_splitting_mode": "SAFE",
    },
    "advanced": {
        "enable_memory_tracing": False,
        "use_advanced_staging_buffers": True,  # persistent-mapped uploads
        "cpu_render_ahead_limit": 3,
    },
    "debug": {
        "terrain_sorting_enabled": True,
    },
}


def sodium_config_path() -> str:
    from .paths import MINECRAFT_DIR
    return os.path.join(MINECRAFT_DIR, "config", "sodium-options.json")


def _same(a, b) -> bool:
    """`a == b`, but a bool is never equal to the number that spells it in
    JSON: `use_fog_occlusion: 0` would otherwise read as already-correct `false`
    and be left alone (and vice versa for chunk_builder_threads: false)."""
    return a == b and isinstance(a, bool) == isinstance(b, bool)


def apply_max_fps_sodium(path: str | None = None) -> dict:
    """Puts Sodium's own renderer options back to the fast values, in place.

    Returns {"changed", "detail", "path"} - the same shape as
    game_options.py's appliers, and the same contract: only keys the file
    already has are touched (so a config from another Sodium generation is
    never given an unknown key), the write is atomic and idempotent, and every
    failure is reported instead of raised. This runs on the launch path before
    the JVM starts, so it can never race Sodium's own save-on-exit.

    A missing file is NOT created: without a config, Sodium uses its compiled
    defaults, which are the fast values for every key except
    chunk_builder_threads (Auto there, 2 once Sodium has written the file).
    """
    target = path or sodium_config_path()
    result = {"changed": [], "detail": "", "path": target}
    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        result["detail"] = ("no sodium-options.json yet (Sodium's own defaults "
                            "are already the fast values)")
        return result
    except (OSError, ValueError):
        result["detail"] = "sodium-options.json is not readable"
        return result
    if not isinstance(data, dict):
        result["detail"] = "sodium-options.json is not an object"
        return result

    for section, wanted in SODIUM_MAX_FPS_OPTIONS.items():
        current = data.get(section)
        if not isinstance(current, dict):
            continue        # not this generation's schema: leave it alone
        for key, value in wanted.items():
            if key in current and not _same(current[key], value):
                current[key] = value
                result["changed"].append(f"{section}.{key}")

    if not result["changed"]:
        result["detail"] = "sodium options already at the fast values"
        return result

    tmp = target + ".cubeon-tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
            fh.write("\n")
        os.replace(tmp, target)
    except OSError:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        result["changed"] = []
        result["detail"] = "sodium-options.json is not writable"
        return result

    result["detail"] = "set " + ", ".join(result["changed"])
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
