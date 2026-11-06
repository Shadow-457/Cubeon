"""Optional performance-mod setup for the Play menu's FPS Boost.

Terrain rendering, game logic, batching, culling, memory and loading fixes.
Fabric/Quilt use Sodium/Lithium; Forge uses Embeddium and
Canary/Radium; NeoForge prefers Sodium/Lithium with compatible older ports.
Every candidate must publish an exact Minecraft-version/native-loader build.
Quilt can use the curated Fabric builds. Existing renderer/logic alternatives,
disabled JARs and profile removal preferences prevent competing additions.

More Culling, Enhanced Block Entities and Exordium require an explicit opt-in.
Legacy managed More Culling copies are disabled once; explicit installs, pack
content and required dependencies stay. ThreadTweak, Krypton and Dynamic FPS
stay retired. BadOptimizations was restored at the user's request.

Downloads are bounded and best-effort. Final prelaunch Doctor verifies the
installed dependency graph; no published build means no invented compatibility.
Graphics transitions are independent of the client menu and of mod downloads.
"""
import json
import os
from .storage import metadata_path
import threading

from . import net
from .atomicio import write_json
from .mod_loaders import MOD_CAPABLE_LOADERS
from .mods import (LAUNCH_LOOKUP_ATTEMPTS, LAUNCH_LOOKUP_TIMEOUT, delete_mod,
                   download_mod, get_mod_download, list_mods, name_stem,
                   read_mod_metadata, resolve_profile_dir, toggle_mod)

# (Modrinth slug, Modrinth project id, display label), in install order.
# Sodium first (biggest win, the one players recognise), then the companions.
PERF_MODS = (
    ("sodium", "AANobbMI", "Sodium"),
    ("lithium", "gvQqBUqZ", "Lithium"),
    ("immediatelyfast", "5ZwdcRci", "ImmediatelyFast"),
    ("entityculling", "NNAgCjsB", "Entity Culling"),
    ("ferrite-core", "uXXizFIs", "FerriteCore"),
    ("modernfix", "nmDcB62a", "ModernFix"),
    ("badoptimizations", "g96Z4WVZ", "BadOptimizations"),
)
_MORE_CULLING = ("moreculling", "51shyZVL", "More Culling")
OPTIONAL_PERF_MODS = (
    _MORE_CULLING,
    ("ebe", "OVuFYfre", "Enhanced Block Entities"),
    ("exordium", "DynYZEae", "Exordium"),
)
_EMBEDDIUM = ("embeddium", "sk9rgfiA", "Embeddium")
_CANARY = ("canary", "qa2H4BS9", "Canary")
_RADIUM = ("radium", "2gvRmQXx", "Radium")
# Existing renderers satisfy the same job; never add a competing renderer.
_RENDERERS = frozenset({"sodium", "embeddium", "rubidium", "optifine"})
_LOGIC_MODS = frozenset({"lithium", "canary", "radium"})
_KNOWN_PERF_MODS = PERF_MODS + OPTIONAL_PERF_MODS + (_EMBEDDIUM, _CANARY, _RADIUM,
                              ("rubidium", "", "Rubidium"), ("optifine", "", "OptiFine"))


def _suite_candidates(loader, optional_mods=()):
    """Use native ports and only explicitly selected optional projects."""
    if loader == "forge":
        first = ((_EMBEDDIUM,), (_CANARY, _RADIUM))
    elif loader == "neoforge":
        first = ((PERF_MODS[0], _EMBEDDIUM), (PERF_MODS[1], _RADIUM))
    else:
        first = ((PERF_MODS[0],), (PERF_MODS[1],))
    selected = optional_mods if isinstance(optional_mods, (list, tuple, set, frozenset)) else ()
    return (first + tuple((entry,) for entry in PERF_MODS[2:])
            + tuple((entry,) for entry in OPTIONAL_PERF_MODS if entry[0] in selected))


def _equivalents(slug):
    if slug in _RENDERERS:
        return _RENDERERS
    if slug in _LOGIC_MODS:
        return _LOGIC_MODS
    return frozenset({slug})

# The perf mods the suite used to install (2026-10-05 - 2026-10-14), kept here
# so an existing profile can be cleaned up (see prune_retired_perf_mods). Do
# NOT re-add these to PERF_MODS without the user's say-so.
RETIRED_PERF_MODS = (
    ("krypton", "fQEb0iXm"),
    ("threadtweak", "vSEH1ERy"),
    ("dynamic-fps", "LQ3K71Q1"),
)

# Kept as its own name: tests and callers refer to the slug tuple.
PERF_MOD_SLUGS = tuple(slug for slug, _pid, _label in PERF_MODS)

_LABELS = {slug: label for slug, _pid, label in _KNOWN_PERF_MODS}

# Keep the choice beside the profile, rather than the shared jar store: removing
# a performance mod from one instance must not remove it from another instance.
REMOVED_MODS_FILE = ".cubeon-removed-performance-mods.json"
MORE_CULLING_MIGRATION = ".cubeon-moreculling-retirement.json"
_REMOVAL_LOCK = threading.RLock()


def _matching_slugs(mod: dict) -> set[str]:
    identities = {str(mod.get(key) or "").lower()
                  for key in ("slug", "display_name", "project_id", "id", "name")}
    identities.add(name_stem(mod.get("filename") or ""))
    if str(mod.get("filename") or "").lower().startswith(("optifine_", "optifine-")):
        identities.add("optifine")
    identities.discard("")
    return {slug for slug, project_id, label in _KNOWN_PERF_MODS
            if identities & {slug, project_id.lower(), label.lower(),
                             label.lower().replace(" ", "")}}


def _read_removals(profile_dir: str) -> set[str]:
    """Missing means no removals; unreadable preferences must not undo choices."""
    with _REMOVAL_LOCK:
        try:
            with open(metadata_path(profile_dir, REMOVED_MODS_FILE), encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            return set()
        if not isinstance(data, dict) or not isinstance(data.get("removed"), list):
            raise ValueError("Invalid performance-mod removal preferences")
        return {slug for slug in data["removed"]
                if isinstance(slug, str) and slug in _LABELS}


def allow_explicit_more_culling(profile_dir: str) -> None:
    """A deliberate new install must not be treated as an old default."""
    with _REMOVAL_LOCK:
        write_json(metadata_path(profile_dir, MORE_CULLING_MIGRATION), {"completed": True})


def retire_legacy_more_culling(mc_version: str | None, loader: str | None,
                              version_id: str | None = None) -> list[str]:
    """Disable legacy launcher-managed More Culling once; never delete a jar.

    Preserve untracked manual jars, modpack profiles and profiles with an enabled
    mod requiring More Culling. Old Modrinth sidecars do not distinguish automatic
    installs from old browse installs, so both migrate once; a user can re-enable
    the retained file afterwards. Persist pending filenames before renaming so
    failed/interrupted migrations can resume without overwriting backups.
    """
    if not mc_version or loader not in ("fabric", "quilt"):
        return []
    profile = resolve_profile_dir(mc_version, loader, version_id)
    if not os.path.isdir(profile) or os.path.lexists(os.path.join(profile, "_modpack.json")):
        return []
    marker = metadata_path(profile, MORE_CULLING_MIGRATION)
    with _REMOVAL_LOCK:
        try:
            with open(marker, encoding="utf-8") as fh:
                state = json.load(fh)
        except FileNotFoundError:
            state = {}
        if not isinstance(state, dict):
            raise ValueError("Invalid More Culling migration state")
        if state.get("completed") is True:
            return []
        installed = list_mods(mc_version, loader, version_id=version_id)
        eligible = set()
        for item in installed:
            if not item.get("enabled"):
                continue
            descriptor = read_mod_metadata(os.path.join(profile, item["filename"]), loader)
            if descriptor and "moreculling" in (descriptor.get("depends") or {}):
                allow_explicit_more_culling(profile)
                return []
            if (str(item.get("slug") or "").lower() == _MORE_CULLING[0]
                    or str(item.get("project_id") or "").lower() == _MORE_CULLING[1].lower()):
                # A descriptor wins over a misleading/stale sidecar, including
                # when a pending filename was replaced after an interruption.
                if descriptor is None or descriptor.get("id") == "moreculling":
                    eligible.add(item["filename"])
        pending = state.get("pending")
        if pending is None:
            pending = sorted(eligible)
            write_json(marker, {"pending": pending, "completed": False})
        if not isinstance(pending, list) or any(
                not isinstance(name, str) or os.path.basename(name) != name
                or "/" in name or "\\" in name or not name.endswith(".jar")
                for name in pending):
            raise ValueError("Invalid More Culling migration filenames")
        changed = []
        for filename in pending:
            source = os.path.join(profile, filename)
            if filename in eligible and os.path.lexists(source):
                toggle_mod(mc_version, loader, filename, version_id=version_id)
                changed.append(filename)
        write_json(marker, {"completed": True})
        return changed


def remember_removal(profile_dir: str, filename: str, metadata: dict,
                     loader: str | None) -> None:
    """Persist a performance-mod opt-out BEFORE deleting its profile entry.

    The descriptor handles renamed manual jars; sidecars/filenames still handle
    broken store links. A failed write raises so the UI keeps the mod and can
    report the failure, rather than claiming a removal Play will immediately undo.
    """
    declared = read_mod_metadata(os.path.join(profile_dir, filename), loader)
    removed = _matching_slugs(declared) if declared else _matching_slugs(
        dict(metadata or {}, filename=filename))
    if not removed:
        return
    with _REMOVAL_LOCK:
        previous = _read_removals(profile_dir)
        if removed <= previous:
            return
        write_json(metadata_path(profile_dir, REMOVED_MODS_FILE),
                   {"removed": sorted(previous | removed)})

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


def entityculling_config_path(game_dir: str | None = None) -> str:
    """<game dir>/config/entityculling.json.

    `game_dir` is an instance's own folder (paths.game_dir_for): mod configs
    are per instance now, so a launch must name the instance it is starting.
    Omitted -> the shared root, which is what a pre-instance-folder install
    still uses.
    """
    from .paths import MINECRAFT_DIR
    return os.path.join(game_dir or MINECRAFT_DIR, "config", "entityculling.json")


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
# Apart from the shared chunk_builder_threads option, keys are matched by name
# against the section that is already in the file, so
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

    Always save 2, as requested by the player. Sodium applies its own runtime
    hardware limit; Cubeon must not silently turn this setting into 1 or Auto.
    """
    return 2


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


def sodium_config_path(game_dir: str | None = None) -> str:
    from .paths import MINECRAFT_DIR
    return os.path.join(game_dir or MINECRAFT_DIR, "config", "sodium-options.json")


def _same(a, b) -> bool:
    """`a == b`, but a bool is never equal to the number that spells it in
    JSON: `use_fog_occlusion: 0` would otherwise read as already-correct `false`
    and be left alone (and vice versa for chunk_builder_threads: false)."""
    return a == b and isinstance(a, bool) == isinstance(b, bool)


def apply_max_fps_sodium(path: str | None = None, *, preserve_existing: bool = False) -> dict:
    """Puts Sodium's own renderer options back to the fast values, in place.

    Returns {"changed", "detail", "path"} - the same shape as
    game_options.py's appliers, and the same contract: only keys the file
    already has are touched, except the chunk-builder count shared by all
    supported Sodium generations. The write is atomic and idempotent, and every
    failure is reported instead of raised. This runs on the launch path before
    the JVM starts, so it can never race Sodium's own save-on-exit.

    Launch passes preserve_existing=True: retain player/driver workarounds,
    including builder counts, and only seed a missing builder count.

    A fresh config seeds only performance.chunk_builder_threads. Sodium fills
    its other compiled defaults when reading that partial config, so the first
    launch also gets two builders without inventing version-specific options.
    """
    target = path or sodium_config_path()
    result = {"changed": [], "detail": "", "path": target}
    try:
        with open(target, "r", encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        data = {}
    except (OSError, ValueError):
        result["detail"] = "sodium-options.json is not readable"
        return result
    if not isinstance(data, dict):
        result["detail"] = "sodium-options.json is not an object"
        return result

    # Every supported Sodium (0.4 through 0.9) has this section/key. Missing
    # fields otherwise fall back to Auto even in an existing partial config.
    if "performance" not in data:
        data["performance"] = {}
    performance = data.get("performance")
    if isinstance(performance, dict) and "chunk_builder_threads" not in performance:
        performance["chunk_builder_threads"] = chunk_builder_threads()
        result["changed"].append("performance.chunk_builder_threads")

    for section, wanted in SODIUM_MAX_FPS_OPTIONS.items():
        current = data.get(section)
        if not isinstance(current, dict):
            continue        # not this generation's schema: leave it alone
        for key, value in wanted.items():
            if not preserve_existing and key in current and not _same(current[key], value):
                current[key] = value
                result["changed"].append(f"{section}.{key}")

    if not result["changed"]:
        result["detail"] = "sodium options already at the fast values"
        return result

    try:
        write_json(target, data)
    except OSError:
        result["changed"] = []
        result["detail"] = "sodium-options.json is not writable"
        return result

    result["detail"] = "set " + ", ".join(result["changed"])
    return result


def _present(mc_version: str | None, loader: str | None,
             version_id: str | None = None) -> set:
    """The performance mods already in this profile, by slug.

    Matches the recorded Modrinth slug, the display name, the project id and
    the filename, so a jar the user dropped in by hand still counts - a second
    copy of Sodium is a duplicate-mod crash, not a boost."""
    found: set = set()
    if not mc_version or loader not in MOD_CAPABLE_LOADERS:
        return found
    try:
        mods = list_mods(mc_version, loader, version_id=version_id)
    except Exception:
        return found
    for mod in mods:
        matches = _matching_slugs(mod)
        if not matches and mod.get("filename"):
            descriptor = read_mod_metadata(os.path.join(
                resolve_profile_dir(mc_version, loader, version_id), mod["filename"]), loader)
            if descriptor:
                matches = _matching_slugs(descriptor)
        found.update(matches)
    return found


def is_installed(mc_version: str | None, loader: str | None,
                 version_id: str | None = None) -> bool:
    """True when every performance mod is already in the profile."""
    if not mc_version or loader not in MOD_CAPABLE_LOADERS:
        return False
    present = _present(mc_version, loader, version_id)
    return all(present & _equivalents(choices[0][0]) for choices in _suite_candidates(loader))


def seed_renderer_options(mc_version, loader, version_id, game_dir):
    """Seed the installed renderer's config, preserving player workarounds."""
    reports = []
    for renderer in sorted(_present(mc_version, loader, version_id) &
                           {"sodium", "embeddium", "rubidium"}):
        reports.append(apply_max_fps_sodium(
            os.path.join(game_dir, "config", renderer + "-options.json"), preserve_existing=True))
    return reports


def prune_retired_perf_mods(mc_version: str | None, loader: str | None,
                            version_id: str | None = None) -> list:
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
        mods = list_mods(mc_version, loader, version_id=version_id)
    except Exception:
        return removed
    for mod in mods:
        slug = (mod.get("slug") or "").lower()
        project_id = (mod.get("project_id") or "").lower()
        if slug in retired_slugs or (project_id and project_id in retired_pids):
            try:
                delete_mod(mc_version, loader, mod["filename"],
                           version_id=version_id)
                removed.append(slug or project_id)
            except Exception:
                pass
    return removed


def ensure_installed(mc_version: str | None, loader: str | None,
                     status_cb=None, version_id: str | None = None, *,
                     repair_dependencies: bool = True, optional_mods=()) -> dict:
    """Installs any missing performance mod into the profile.

    Returns installed/kept/skipped/unavailable/failed lists so the caller can log or
    show what actually happened. Download failures are reported; failed legacy
    retirement raises so Play can stop before loading an unsafe profile.
    """
    result = {"installed": [], "kept": [], "skipped": [], "unavailable": [],
              "failed": [], "detail": ""}

    if not mc_version:
        result["detail"] = "no Minecraft version selected"
        return result
    if loader not in MOD_CAPABLE_LOADERS:
        result["detail"] = "performance mods need a modded profile"
        return result

    from . import storage
    storage.reconcile_mod_removals(resolve_profile_dir(mc_version, loader, version_id), loader)
    retired = retire_legacy_more_culling(mc_version, loader, version_id)
    present = _present(mc_version, loader, version_id)
    suite = _suite_candidates(loader, optional_mods)
    relevant = set().union(*(_equivalents(choices[0][0]) for choices in suite))
    result["kept"] = sorted(present - relevant)
    try:
        removed = _read_removals(resolve_profile_dir(mc_version, loader, version_id))
    except (OSError, ValueError) as error:
        result["failed"] = [choices[0][0] for choices in suite
                            if not present & _equivalents(choices[0][0])]
        result["detail"] = f"Couldn't read performance-mod removal preferences: {error}"
        return result
    result["skipped"] = sorted(removed - relevant - present)
    # Once a lookup fails at the connection level the route is down, and every
    # remaining mod would pay the same timeout again before Minecraft starts
    # (measured 3 s x 6 on a blackholed network). The answer for the rest of
    # this launch is already known; the next launch retries. A server that
    # *answered* (HTTP error) is not a dead route and does not trip this.
    network_down = False
    for choices in suite:
        primary = choices[0][0]
        equivalent = _equivalents(primary)
        if present & equivalent:
            result["kept"].extend(sorted(present & equivalent))
            continue
        if removed & equivalent:
            result["skipped"].extend(sorted(removed & equivalent))
            continue
        if network_down:
            result["failed"].append(primary)
            continue
        installed = False
        available = False
        for slug, project_id, label in choices:
            try:
                file_info = get_mod_download(
                    slug, mc_version=mc_version, loader="fabric" if loader == "quilt" else loader,
                    timeout=LAUNCH_LOOKUP_TIMEOUT, attempts=LAUNCH_LOOKUP_ATTEMPTS,
                )
                if not file_info:
                    continue
                available = True
                if status_cb:
                    status_cb(f"Installing {label}")
                download_mod(
                    file_info["url"], file_info["filename"],
                    slug=slug, project_id=project_id,
                    mc_version=mc_version, loader=loader,
                    hashes=file_info.get("hashes"), version_id=version_id,
                )
                result["installed"].append(slug)
                installed = True
            except Exception as ex:
                available = True  # lookup/download failed; availability is unknown
                if isinstance(ex, net.DownloadError) and not isinstance(ex, net.HTTPStatusError):
                    network_down = True
            # Fallback ports are for missing builds, never for replacing a
            # failed download or a partially installed renderer.
            break
        if not installed:
            result["failed" if available else "unavailable"].append(primary)

    parts = []
    if retired:
        parts.append("disabled legacy More Culling (kept in Mods as Disabled)")
    if repair_dependencies:
        # Read the actual jars, including already-kept builds: old launchers
        # installed More Culling without Cloth Config. Play defers this to its
        # final Doctor gate so dependency repair runs only once per launch.
        try:
            from .mod_dependencies import run_dependency_doctor
            dependencies = run_dependency_doctor(
                mc_version, loader, version_id=version_id, status_cb=status_cb,
                check_online=not network_down)
            if dependencies["fixed"]:
                parts.append("repaired dependencies: " + ", ".join(
                    item["dependency"] for item in dependencies["fixed"]))
            if dependencies["unfixed"]:
                parts.append("dependencies need repair: " + "; ".join(
                    item["detail"] for item in dependencies["unfixed"]))
        except Exception as error:
            parts.append(f"dependency check failed: {error}")
    if result["installed"]:
        parts.append("installed " + ", ".join(
            _LABELS.get(s, s) for s in result["installed"]))
    if result["kept"]:
        parts.append("already had " + ", ".join(
            _LABELS.get(s, s) for s in result["kept"]))
    if result["skipped"]:
        parts.append("left removed by you: " + ", ".join(
            _LABELS.get(s, s) for s in result["skipped"]))
    if result["failed"]:
        parts.append("couldn't get " + ", ".join(
            _LABELS.get(s, s) for s in result["failed"]))
    if result["unavailable"]:
        parts.append("no compatible build: " + ", ".join(
            _LABELS.get(s, s) for s in result["unavailable"]))
    result["detail"] = "; ".join(parts)
    return result
