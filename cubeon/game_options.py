"""Optional graphics defaults with per-instance, reversible boost transitions.

Launch uses sync_fps_boost: apply once when enabled, retain in-game changes on
later launches, and restore only unchanged boost values when disabled. View and
simulation distances, VSync and the frame cap always belong to the player.
"""
import os
import json
import threading

from .atomicio import write_json

from .paths import MINECRAFT_DIR

VSYNC_KEY = "enableVsync"
MAX_FPS_KEY = "maxFps"
# Deliberately NOT in any applier below: these two belong to the player. The
# launcher reads neither and writes neither (see the module docstring).

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
# through sync_fps_boost instead. Distances always remain player-owned.
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

# Vsync and maxFps are intentionally absent from every table above. A fresh
# install keeps Minecraft's own defaults (Vsync ON, maxFps 120); a player who
# turned Vsync off keeps it off. The launcher must not rewrite that choice -
# forcing it off on every launch is what turned Minecraft into a six-core
# space heater on 2026-10-24.


def options_path(game_dir: str | None = None) -> str:
    """<game dir>/options.txt. Per instance since the instance game folders
    exist (paths.game_dir_for): video settings are the player's per-instance
    state, not a launcher-wide constant. Omitted -> the shared root."""
    return os.path.join(game_dir or MINECRAFT_DIR, "options.txt")


def _set_options(target: str, wanted: dict, label: str) -> dict:
    """Rewrites exactly the `wanted` keys in an options.txt, in place.

    Contract shared by every applier here: only keys that already exist are
    touched (an older version's file is never given an unknown key), the value
    is written only when it differs, the write is atomic and idempotent, and
    every failure is reported instead of raised - a bonus on top of the mods,
    never a launch requirement. `label` is the wording of the summary line.
    """
    result = {"changed": [], "detail": "", "path": target}
    try:
        with open(target, "r", encoding="utf-8", errors="replace") as fh:
            original = fh.read()
    except OSError:
        result["detail"] = "no options.txt yet"
        return result

    newline = "\r\n" if "\r\n" in original else "\n"
    had_trailing = original.endswith(("\n", "\r"))
    lines = original.replace("\r\n", "\n").split("\n")
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

    # A key Minecraft has not written yet cannot be set: inventing it in a
    # file the game owns is how unknown-key bugs happen. Report honestly.
    missing = [k for k in wanted if k not in seen_wanted]
    if missing:
        result["detail"] = "skipped (not in options.txt yet): " + ", ".join(missing)

    if not result["changed"]:
        if not result["detail"]:
            result["detail"] = f"{label} already applied"
        return result

    text = newline.join(out)
    if had_trailing:
        text += newline

    tmp = target + ".cubeon-tmp"
    try:
        with open(tmp, "w", encoding="utf-8", newline="") as fh:
            fh.write(text)
        os.replace(tmp, target)
    except OSError:
        try:
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


def sync_fps_boost(enabled: bool, path: str | None = None) -> dict:
    """Apply on transitions only. Save originals before touching game options.

    A later in-game edit wins, including during OFF restore. Existing installs
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
                    or not isinstance(saved.get("applied"), dict)):
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
        except OSError:
            result["detail"] = "no readable options.txt yet"
            return result
        if saved and saved.get("enabled") is enabled:
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
            managed_keys = {key for key, _, _ in MAX_FPS_OPTIONS}
            wanted = {key: value for key, value in saved["before"].items()
                      if key in managed_keys
                      and current.get(key) == saved["applied"].get(key)}
        try:
            write_json(marker, saved)
        except OSError:
            result["detail"] = "could not back up boost settings; keeping game settings"
            return result
        result = _set_options(target, wanted, "FPS boost" if enabled else "previous graphics restored")
        if result["detail"] == "options.txt is not writable":
            return result
        saved["enabled"] = enabled
        try:
            write_json(marker, saved)
        except OSError:
            result["detail"] += "; could not record boost transition"
        return result
