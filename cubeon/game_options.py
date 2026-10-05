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
    target = path or options_path()
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
    for line in lines:
        stripped = line.strip()
        key, sep, raw = stripped.partition(":")
        if sep and key == VSYNC_KEY:
            if raw.strip().lower() != "false":
                out.append(f"{VSYNC_KEY}:false")
                result["changed"].append(VSYNC_KEY)
                continue
        elif sep and key == MAX_FPS_KEY:
            value = raw.strip().strip('"')
            try:
                current = int(float(value))
            except ValueError:
                current = None
            if current is None or current < UNLIMITED_FPS:
                out.append(f"{MAX_FPS_KEY}:{UNLIMITED_FPS}")
                result["changed"].append(MAX_FPS_KEY)
                continue
        out.append(line)

    if not result["changed"]:
        result["detail"] = "frame rate already unlocked"
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

    result["detail"] = "turned off Vsync, lifted the FPS cap"
    return result
