"""
Minecraft's own graphics knobs, without touching the player's frame pacing.

Adding Sodium and friends only raises the frame rate a machine is *capable* of
rendering. Max FPS mode (apply_max_fps) is the launcher's DEFAULT graphics
config (fps_boost_enabled defaults to True). It sets the engine-work options -
fast graphics preset, minimal particles, no ambient occlusion/shadow passes,
trimmed entity update distance, no biome blending, chunk saves off the render
thread - plus the four levers that dominate frame rate on real hardware:
renderDistance (8/12 -> 6), simulationDistance (12 -> 5), mipmapLevels (2) and
2D clouds (renderClouds "fast").

  2026-10-18: those four used to be deliberately left alone "because they
  change what the player sees". A side-by-side run against FastClient on the
  same box settled it the other way: the GPU sat idle (0-76% busy) while both
  games were Java-bound, and Cubeon at renderDistance 8 was meshing +70% more
  chunks than FastClient at 6. FastClient's own options.txt sets every
  speed-only key AND render/simulation distance, so leaving them out meant
  Cubeon shipped measurably slower than the thing it is compared to. This is
  still a DEFAULT, not a lock: FPS boost OFF rewrites every one of these keys
  back to Minecraft's own defaults, render distance included.

  2026-10-24: the launcher NO LONGER touches enableVsync or maxFps at all.
  It used to force `enableVsync:false` + `maxFps:260` on every launch, which
  meant a player could never keep Vsync on - and on a machine that can feed
  frames faster than the monitor, that turns Minecraft into a six-core space
  heater (the 2026-10-24 fan-noise report: 582% CPU, 83 C package, in a
  singleplayer world). A fresh install now keeps Minecraft's own defaults
  (Vsync ON, maxFps 120); a player who already turned Vsync off keeps it off.
  The launcher never rewrites that choice in either direction.

restore_vanilla_look() is Max FPS mode's OFF switch (2026-10-15): it rewrites
the SAME keys back to Minecraft's own defaults, so turning FPS boost off in
the Play menu actually undoes the boost on an already-installed instance -
instead of leaving the fast values baked into options.txt (the old Settings
toggle only stopped FUTURE launches from re-applying them, which is why it
"did nothing" once installed). It also restores the smooth-lighting key, so
shadows and textures come back the way vanilla draws them. Like every applier
here it only touches keys the file already has, and never resource packs or
shaders.

Only keys that already exist are touched, so an options.txt from an older
Minecraft version that has no such key is not given an unknown one. The write
is atomic and idempotent. It is called on the launch path, before the JVM
starts, so it can never race the game's own save-on-exit.
"""
import os

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
#   * `graphicsMode` does not exist any more - it survives only in a legacy
#     DataFixer, so writing it was a silent no-op and the "biggest lever" never
#     fired. The live key is `graphicsPreset`.
#   * `particles:"0"` is ALL particles, not minimal: the value is an enum id
#     (ALL=0, DECREASED=1, MINIMAL=2). Max FPS mode was *maximising* particles.
MAX_FPS_OPTIONS = (
    # A STRING option - the value must be written QUOTED (see _set_options).
    ("graphicsPreset", '"fast"',
     "Fast graphics - the biggest lever after the renderer"),
    # Minimise particles (id 2 = MINIMAL; 0 = ALL).
    ("particles", "2", "Minimal particles"),
    # Ambient occlusion (smooth lighting) - real terrain-shading and meshing
    # work, and the last of the fast-preset defaults left on.
    ("ao", "false", "no ambient occlusion (smooth lighting)"),
    ("entityShadows", "false", "no entity shadow passes"),
    ("entityDistanceScaling", "0.75", "fewer far-away entity updates"),
    ("biomeBlendRadius", "0", "fewer biome blend samples per pixel"),
    ("syncChunkWrites", "false", "chunk saves off the render thread"),
    # The distance levers (2026-10-18). Chunk meshing is CPU work, so these
    # cost frames directly: 6 is 169 chunks in view against 289 at 8.
    ("renderDistance", "6", "fewer chunks meshed and drawn"),
    ("simulationDistance", "5", "fewer ticked chunks and entities"),
    ("mipmapLevels", "2", "less texture mip work and VRAM"),
    # A STRING option too - quoted, like graphicsPreset.
    ("renderClouds", '"fast"', "2D clouds instead of 3D volumes"),
)

# The OFF switch for Max FPS mode: the SAME keys, at Minecraft's own defaults
# (verified against the 1.21.11 jar's options.txt - the same audit that fixed
# the values above). ao:true is smooth lighting, the "shadows on the ground"
# look; graphicsPreset fancy is textured, shadowed terrain. renderDistance /
# simulationDistance go back to the client's own 12, mipmaps to 4 and clouds
# to "true". Only keys the file already has are touched, so a fresh install
# that has never written e.g. syncChunkWrites is not given one.
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
    "renderDistance": "12",
    "simulationDistance": "12",
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
    return _set_options(path or options_path(),
                        {k: v for k, v, _ in MAX_FPS_OPTIONS},
                        "max fps")


def restore_vanilla_look(path: str | None = None) -> dict:
    """FPS boost OFF: put Minecraft's speed-only graphics options back to the
    game's own defaults, so an install that ran with the boost on looks
    vanilla again (fancy graphics, smooth lighting, entity shadows, all
    particles, full biome blend, full render/simulation distance, 4x mipmaps,
    3D clouds). Never raises; same result shape.
    """
    return _set_options(path or options_path(), dict(VANILLA_LOOK_OPTIONS),
                        "vanilla look restored")
