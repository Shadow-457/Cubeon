"""Optional graphics defaults with per-instance, reversible boost transitions.

Normal boost applies once and retains later edits. Opt-in settings sync enforces
the preset before each launch, including distances, VSync and the frame cap.
Turning boost off restores only values still matching the applied preset.
"""
import os
from .storage import runtime_dir
import json
import threading
import re
import tempfile
import zipfile

from .atomicio import write_json

from .paths import MINECRAFT_DIR

VSYNC_KEY = "enableVsync"
MAX_FPS_KEY = "maxFps"
# Frame pacing is changed only by the explicit settings-sync option.

# Max FPS mode (2026-10-14; distance levers added 2026-10-18). Each entry is
# (key, value, why). Deliberately absent: resource packs, shaders, leaves and
# water quality - those have no measurable frame cost on this hardware and are
# pure taste.
#
# Two of these were WRONG until 2026-10-14 (both verified against the real
# 1.21.11 jar by tools/test_perf_mods.py's companion audit):
#   * Newer versions use `graphicsPreset`; earlier versions still use
#     `graphicsMode` or `fancyGraphics`. Apply only the keys present in the
#     selected instance's options, with that version's numeric/string codecs.
#   * `particles:"0"` is ALL particles, not minimal: the value is an enum id
#     (ALL=0, DECREASED=1, MINIMAL=2). Max FPS mode was *maximising* particles.
MAX_FPS_OPTIONS = (
    # A STRING option - the value must be written QUOTED (see _set_options).
    ("graphicsPreset", '"fast"',
     "Fast graphics - the biggest lever after the renderer"),
    ("graphicsMode", "0", "Fast graphics on earlier Minecraft versions"),
    ("fancyGraphics", "false", "Fast graphics on legacy Minecraft versions"),
    # Minimise particles (id 2 = MINIMAL; 0 = ALL).
    ("particles", "2", "Minimal particles"),
    # Ambient occlusion (smooth lighting) - real terrain-shading and meshing
    # work, and the last of the fast-preset defaults left on.
    ("ao", "false", "no ambient occlusion (smooth lighting)"),
    ("entityShadows", "false", "no entity shadow passes"),
    ("entityDistanceScaling", "0.75", "fewer far-away entity updates"),
    ("biomeBlendRadius", "0", "fewer biome blend samples per pixel"),
    ("syncChunkWrites", "false", "chunk saves off the render thread"),
    ("mipmapLevels", "2", "less texture mip work and VRAM"),
    # A STRING option too - quoted, like graphicsPreset.
    ("renderClouds", '"fast"', "2D clouds instead of 3D volumes"),
)

# Legacy explicit vanilla-look helper. Normal launch restores saved originals
# through sync_fps_boost instead. This legacy helper leaves distances alone.
VANILLA_LOOK_OPTIONS = {
    "graphicsPreset": '"fancy"',
    "particles": "0",
    "ao": "true",
    "entityShadows": "true",
    "entityDistanceScaling": "1.0",
    "biomeBlendRadius": "2",
    "syncChunkWrites": "true",
    # Smooth lighting (per-vertex light smoothing; vanilla ON). A bool, like ao.
    "smoothLighting": "true",
    "mipmapLevels": "4",
    "renderClouds": '"true"',
}

SYNC_OPTIONS = {
    "enableVsync": "false", "maxFps": "260",  # 260 encodes Unlimited, not a 260 FPS cap
    "renderDistance": "4", "simulationDistance": "5",
    "entityDistanceScaling": "0.5", "biomeBlendRadius": "0",
    "renderClouds": '"false"', "graphicsPreset": '"custom"',
    "smoothLighting": "false",
    "weatherRadius": "3", "cutoutLeaves": "false", "improvedTransparency": "false",
    "vignette": "false",
}


def _sync_preset(current: dict, mc_version: str | None) -> dict:
    """Existing keys prove their schema; seed missing keys only for known releases."""
    values = {key: value for key, value, _ in MAX_FPS_OPTIONS}
    values.update(SYNC_OPTIONS)
    supported = set(current) & values.keys()
    match = re.fullmatch(r"(\d+)\.(\d+)(?:\.(\d+))?", mc_version or "")
    version = tuple(int(part or 0) for part in match.groups()) if match else None
    known = version and ((1, 8, 0) <= version <= (1, 21, 11)
                         or (26, 1, 0) <= version <= (26, 3, 0))
    if known:
        supported.update(("enableVsync", "maxFps", "renderDistance", "particles",
                          "ao", "entityShadows", "mipmapLevels", "renderClouds"))
        if version >= (1, 21, 11):
            supported.add("graphicsPreset")
        elif version >= (1, 16, 0):
            supported.add("graphicsMode")
        else:
            supported.add("fancyGraphics")
        if version >= (1, 15, 0):
            supported.add("biomeBlendRadius")
        if version >= (1, 16, 0):
            supported.update(("entityDistanceScaling", "syncChunkWrites"))
        if version >= (1, 18, 0):
            supported.add("simulationDistance")
        if version >= (26, 3, 0):  # verified against the 26.3 option codecs
            supported.update(("weatherRadius", "cutoutLeaves", "improvedTransparency", "vignette"))
    if (current.get("ao", "").strip() in ("0", "1", "2")
            or ("ao" not in current and known and version < (1, 19, 3))):
        values["ao"] = "0"
    clouds = current.get("renderClouds", "").strip()
    if (clouds and not clouds.startswith('"')) or (not clouds and known and version < (1, 19, 0)):
        values["renderClouds"] = "false"
    return {key: value for key, value in values.items() if key in supported}


def _initial_data_version(mc_version):
    """Avoid applying historical options migrations to a fresh modern preset."""
    if not re.fullmatch(r"\d+\.\d+(?:\.\d+)?", mc_version or ""):
        return None
    try:
        jar = os.path.join(runtime_dir(MINECRAFT_DIR), "versions", mc_version, mc_version + ".jar")
        with zipfile.ZipFile(jar) as archive:
            version = json.loads(archive.read("version.json")).get("world_version")
        return str(version) if type(version) is int else None
    except (OSError, KeyError, ValueError, zipfile.BadZipFile):
        return None


def options_path(game_dir: str | None = None) -> str:
    """<game dir>/options.txt. Per instance since the instance game folders
    exist (paths.game_dir_for): video settings are the player's per-instance
    state, not a launcher-wide constant. Omitted -> the shared root."""
    return os.path.join(game_dir or MINECRAFT_DIR, "options.txt")


def _set_options(target: str, wanted: dict, label: str, *, allow_missing=False) -> dict:
    """Rewrites exactly the `wanted` keys in an options.txt, in place.

    By default only existing keys are touched. Settings sync may also seed its
    version-checked whitelist; None restores an originally absent key. The value
    is written only when it differs, the write is atomic and idempotent, and
    every failure is reported instead of raised - a bonus on top of the mods,
    never a launch requirement. `label` is the wording of the summary line.
    """
    result = {"changed": [], "detail": "", "path": target}
    try:
        with open(target, "r", encoding="utf-8", errors="replace", newline="") as fh:
            original = fh.read()
    except FileNotFoundError:
        if not allow_missing:
            result["detail"] = "no options.txt yet"
            return result
        original = ""
    except OSError:
        result["detail"] = "no options.txt yet"
        return result

    newline = "\r\n" if "\r\n" in original else "\n"
    had_trailing = original.endswith(("\n", "\r"))
    lines = original.replace("\r\n", "\n").split("\n") if original else []
    if had_trailing and lines and lines[-1] == "":
        lines.pop()

    out = []
    seen_wanted = set()
    for line in lines:
        stripped = line.strip()
        key, sep, raw = stripped.partition(":")
        if sep and key in wanted:
            seen_wanted.add(key)
            value = wanted[key]
            if value is None:  # restore absence for a key seeded by sync
                result["changed"].append(key)
                continue
            # Compare the file's RAW text (quotes included) against the exact
            # string we would write. Stripping the quotes here was the bug:
            # a caller passing a quoted string (graphicsPreset:"fast") never
            # matched, so the file was rewritten and reported as "changed" on
            # EVERY launch. Now a quoted value round-trips and the write is
            # idempotent. A bare value (false/2/0.75) is written bare, which is
            # what options.txt uses for bool/number options.
            if raw.strip() != value:
                out.append(f"{key}:{value}")
                result["changed"].append(key)
                continue
        out.append(line)

    # Only the opt-in sync path supplies version-checked missing keys.
    missing = [k for k in wanted if k not in seen_wanted]
    if missing and allow_missing:
        for key in missing:
            if wanted[key] is not None:
                out.append(f"{key}:{wanted[key]}")
                result["changed"].append(key)
    elif missing:
        result["detail"] = "skipped (not in options.txt yet): " + ", ".join(missing)

    if not result["changed"]:
        if not result["detail"]:
            result["detail"] = f"{label} already applied"
        return result

    text = newline.join(out)
    if had_trailing or not original:
        text += newline

    tmp = None
    try:
        directory = os.path.dirname(target) or "."
        os.makedirs(directory, exist_ok=True)
        fd, tmp = tempfile.mkstemp(prefix=".cubeon-options-", suffix=".tmp", dir=directory)
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, target)
    except OSError:
        try:
            if tmp:
                os.unlink(tmp)
        except OSError:
            pass
        result["changed"] = []
        result["detail"] = "options.txt is not writable"
        return result

    parts = [f"{k}={wanted[k]}" for k in result["changed"]]
    result["detail"] = (", ".join(parts) + ("; " + result["detail"]
                        if result["detail"] else "")).strip("; ")
    return result


def apply_max_fps(path: str | None = None) -> dict:
    """Max FPS mode: set Minecraft's speed-only graphics options.

    Never raises; returns the shared {"changed", "detail", "path"} shape.
    """
    target = path or options_path()
    try:
        with open(target, encoding="utf-8", errors="replace") as source:
            current = dict(line.rstrip("\r\n").split(":", 1) for line in source if ":" in line)
    except OSError:
        current = {}
    wanted = {key: value for key, value, _ in MAX_FPS_OPTIONS
              if key not in ("graphicsMode", "fancyGraphics") or key in current}
    if current.get("ao", "").strip() in ("0", "1", "2"):
        wanted["ao"] = "0"
    if "renderClouds" in current and not current["renderClouds"].strip().startswith('"'):
        wanted["renderClouds"] = "fast"
    return _set_options(target, wanted, "max fps")


def restore_vanilla_look(path: str | None = None) -> dict:
    """Explicit vanilla graphics helper; launch uses saved originals instead.

    View/simulation distances remain unchanged. Never raises; same result shape.
    """
    return _set_options(path or options_path(), dict(VANILLA_LOOK_OPTIONS),
                        "vanilla look restored")


_BOOST_LOCK = threading.RLock()


def sync_fps_boost(enabled: bool, path: str | None = None, *,
                   sync_settings: bool = False, mc_version: str | None = None) -> dict:
    """Apply once, or enforce before every launch when settings sync is enabled.

    Without sync, later in-game edits win, including during OFF restore. Existing installs
    without a backup are never reset to guessed vanilla values. No running game
    may call this; launch owns the spawn lock and calls it before spawning Java.
    """
    target = path or options_path()
    result = {"changed": [], "detail": "", "path": target}
    marker = target + ".cubeon-boost.json"
    with _BOOST_LOCK:
        try:
            with open(marker, encoding="utf-8") as fh:
                saved = json.load(fh)
            if (not isinstance(saved, dict) or saved.get("schema") != 1
                    or not isinstance(saved.get("before"), dict)
                    or not isinstance(saved.get("applied"), dict)
                    or any(value is not None and not isinstance(value, str)
                           for value in saved["before"].values())
                    or any(not isinstance(value, str) for value in saved["applied"].values())
                    or not isinstance(saved.get("previous_applied", {}), dict)
                    or any(not isinstance(value, str)
                           for value in saved.get("previous_applied", {}).values())):
                raise ValueError("invalid boost backup")
        except FileNotFoundError:
            saved = None
        except (OSError, ValueError):
            result["detail"] = "boost backup is not readable; keeping game settings"
            return result
        if not enabled and saved is None:
            result["detail"] = "no previous boost settings to restore"
            return result
        try:
            with open(target, encoding="utf-8") as fh:
                current = dict(line.rstrip("\r\n").split(":", 1)
                               for line in fh if ":" in line)
        except FileNotFoundError:
            if not (enabled and sync_settings):
                result["detail"] = "no readable options.txt yet"
                return result
            current = {}
        except OSError:
            result["detail"] = "no readable options.txt yet"
            return result
        if enabled and sync_settings:
            wanted = _sync_preset(current, mc_version)
            if not wanted:
                result["detail"] = "no known video settings for this Minecraft version yet"
                return result
            if saved is None or saved.get("enabled") is False:
                saved = {"schema": 1, "enabled": None, "before": {}, "applied": {}}
            # Retain the last committed preset while a new write is pending.
            # An interrupted/failed sync can still restore the preceding boost.
            saved.setdefault("previous_applied", dict(saved["applied"]))
            for key in wanted:
                saved["before"].setdefault(key, current.get(key))
            saved["applied"].update(wanted)
        elif saved and saved.get("enabled") is enabled:
            # Adopt newly supported legacy graphics keys once, while keeping
            # later player edits to already-managed settings.
            additions = {key: value for key, value, _ in MAX_FPS_OPTIONS
                         if enabled and key in ("graphicsMode", "fancyGraphics")
                         and key in current and key not in saved["applied"]}
            if not additions:
                result["detail"] = "boost already applied; keeping game settings"
                return result
            saved["before"].update({key: current[key] for key in additions})
            saved["applied"].update(additions)
            wanted = additions
        elif enabled:
            wanted = {key: value for key, value, _ in MAX_FPS_OPTIONS if key in current}
            if current.get("ao", "").strip() in ("0", "1", "2"):
                wanted["ao"] = "0"
            if "renderClouds" in current and not current["renderClouds"].strip().startswith('"'):
                wanted["renderClouds"] = "fast"
            if saved is None or saved.get("enabled") is False:
                saved = {"schema": 1, "enabled": None,
                         "before": {key: current[key] for key in wanted}, "applied": wanted}
            else:
                # A failed write retains the original backup for the retry.
                wanted = saved["applied"]
        else:
            managed_keys = {key for key, _, _ in MAX_FPS_OPTIONS} | SYNC_OPTIONS.keys()
            wanted = {key: value for key, value in saved["before"].items()
                      if key in managed_keys
                      and (current.get(key) == saved["applied"].get(key)
                           or (key in saved.get("previous_applied", {})
                               and current.get(key) == saved["previous_applied"][key]))}
        try:
            write_json(marker, saved)
        except OSError:
            result["detail"] = "could not back up boost settings; keeping game settings"
            return result
        # The backup intentionally excludes metadata; it only restores graphics.
        if enabled and sync_settings and not current:
            data_version = _initial_data_version(mc_version)
            if data_version is not None:
                wanted = dict(wanted, version=data_version)
        result = _set_options(target, wanted, "FPS boost" if enabled else "previous graphics restored",
                              allow_missing=enabled and sync_settings)
        if result["detail"] == "options.txt is not writable":
            return result
        saved["enabled"] = enabled
        saved.pop("previous_applied", None)
        try:
            write_json(marker, saved)
        except OSError:
            result["detail"] += "; could not record boost transition"
        return result
