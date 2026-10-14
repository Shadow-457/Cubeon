"""
Unlock Minecraft's own frame-rate knobs.

Adding Sodium and friends only raises the frame rate a machine is *capable* of
rendering. A client whose options.txt still says `enableVsync:true` and a low
`maxFps` will keep reading 60 - or, worse, ~30 whenever a frame overruns the
vblank and Vsync snaps it to half the display refresh. That is the single most
common reason "I have Sodium but my FPS did not change" (FastClient-style
clients turn these two off as part of their perf preset).

So this module flips exactly the two options that are pure "unlock" and carry
no gameplay or visual choice:

  enableVsync:false     stop quantising output to the monitor's refresh rate
  maxFps:260            remove the hard frame cap (vanilla's top slider value)

Everything else in options.txt is left byte-for-byte alone. Render distance,
graphics, resource packs and shaders are the player's choices and the launcher
does not rewrite them (see content.py's rule) - raising the cap cannot make a
slow machine fast, it only stops a fast machine being held back.

Only keys that already exist are touched, so an options.txt from an older
Minecraft version that has no such key is not given an unknown one. The write
is atomic and idempotent. It is called on the launch path, before the JVM
starts, so it can never race the game's own save-on-exit.
"""
import os

from .paths import MINECRAFT_DIR

VSYNC_KEY = "enableVsync"
MAX_FPS_KEY = "maxFps"

# Max FPS mode (2026-10-14): Minecraft's own options that are pure speed with
# no gameplay cost. Each entry is (key, value, why). Deliberately absent:
# renderDistance / simulationDistance / mipmapLevels / smooth lighting /
# clouds / leaves / water - those change what the player SEES, and the
# launcher does not rewrite a player's visual choices (the content.py rule);
# these six only stop the engine wasting work.
MAX_FPS_OPTIONS = (
    ("graphicsMode", "0", "Fast graphics - the biggest lever after the renderer"),
    ("particles", "0", "Minimal particles"),
    ("entityShadows", "false", "no entity shadow passes"),
    ("entityDistanceScaling", "0.75", "fewer far-away entity updates"),
    ("biomeBlendRadius", "0", "fewer biome blend samples per pixel"),
    ("syncChunkWrites", "false", "chunk saves off the render thread"),
)

# Vanilla's FPS slider tops out at 260 and labels it "Unlimited"; anything
# above the slider is meaningless, and 260 is high enough to never be the cap
# on real hardware.
UNLIMITED_FPS = 260


def options_path() -> str:
    return os.path.join(MINECRAFT_DIR, "options.txt")


def unlock_frame_rate(path: str | None = None) -> dict:
    """Turns off Vsync and lifts the FPS cap in options.txt, in place.

    Returns {"changed": [...], "detail": str, "path": str}. "changed" lists the
    option keys actually rewritten (empty when there was nothing to do or no
    options.txt yet). Never raises: a missing/unwritable file is reported, not
    fatal - this is a bonus on top of the mods, not a launch requirement.
    """
    return _set_options(path or options_path(),
                        {VSYNC_KEY: "false", MAX_FPS_KEY: str(UNLIMITED_FPS)},
                        "frame rate unlock")


def _set_options(target: str, wanted: dict, label: str) -> dict:
    """Rewrites exactly the `wanted` keys in an options.txt, in place.

    Same contract as unlock_frame_rate(): only keys that already exist are
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
            current = raw.strip().strip('"')
            if current != value:
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

    Same never-raises contract as unlock_frame_rate(). Returns the same
    {"changed", "detail", "path"} shape.
    """
    return _set_options(path or options_path(),
                        {k: v for k, v, _ in MAX_FPS_OPTIONS},
                        "max fps")
