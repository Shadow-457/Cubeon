"""
Custom cape uploads - stores user-supplied cape images locally, renders a
preview of the cape's visible face, and syncs the active cape into
CustomSkinLoader's LocalSkin/capes folder so it can show up in-game.

This is the cape counterpart to cubeon/skins.py and follows that module's
shape deliberately (same validate -> add -> set-active -> sync flow), so
the two read the same and the Profile/skin UI can drive them with one
pattern.

HOW A CAPE REACHES THE GAME (and who wins)
Same mechanism as local skins: Cubeon writes the active cape to
    .minecraft/CustomSkinLoader/LocalSkin/capes/<USERNAME>.png
which the CubeonLocalSkin source reads - registered by cubeon/csl.py with a
load-order contract that puts it AHEAD of the Worker API, so:

    custom cape set    -> your upload wins the cape slot
    no custom cape     -> the shared Cubeon cape (Worker) fills in

That ordering is entirely a csl.py concern (see the ORDER CONTRACT comment
above EXTRALIST_ENTRIES there); this module only stores the file and puts it
where CSL can find it.

Like every LocalSkin texture, a local cape is visible only to THIS player -
friends still see the shared Cubeon cape, because their own client fetches it
from the Worker for your username.

FLEXIBLE INPUT (2026-09-07)
Any image Pillow can read is accepted (PNG/JPEG/WebP/GIF/BMP...). The file
only has to be a real, decodable image; shape is not a precondition:

  * Already cape-shaped (2:1, sane width) -> kept as-is.
  * Anything else -> drawn onto a proper cape layout: the source is scaled
    to fit the visible back panel (the 10x16 region), everything else
    transparent. No user should ever have to learn what "64x32" means.

ANIMATED CAPES (2026-09-07)
A multi-frame input (GIF or APNG) becomes an animated cape:

  * The FIRST frame is baked into the static .png CSL serves - that's what
    everyone in-game sees if animation isn't running, and it's the fallback
    everywhere.
  * The full frame set (capped: MAX_FRAMES, downscaled to MAX_ANIM_WIDTH)
    is written next to the cape as <name>.frames.json for the launcher's
    local API to serve to the Cubeon mod, which animates it on the local
    player's back ONLY (see mod/src/.../AnimatedCape.java for why that
    costs other players and the server exactly nothing).

Frames live on this machine only. Nothing about an animated cape is ever
uploaded - the Worker never sees it, no KV writes, no bytes for anyone
else's client to fetch.
"""
import base64
import io
import json
import os
import re
import shutil
import uuid

from PIL import Image

from .paths import CAPES_DIR, CSL_LOCAL_CAPES_DIR
from .config import save_config

# Metadata lives inside CAPES_DIR (no separate paths.py constant needed) - the
# same {"filename", "name"} record list skins.py keeps, minus the slim flag
# (that's a skin-model concept; capes have no arm width).
CAPES_META_PATH = os.path.join(CAPES_DIR, "capes.json")

# Vanilla capes are 64x32. Modern "HD" capes keep the same 2:1 layout scaled
# up to a power-of-two width, so accept those too - the preview/sync math is
# ratio-relative and handles any of them.
_VALID_CAPE_WIDTHS = {64, 128, 256, 512, 1024}

# Hard input limit. Real capes are tiny; anything past this is either a
# camera photo or an accident, and both are better rejected than decoded.
MAX_SOURCE_BYTES = 8 * 1024 * 1024

# Animation caps, shared with the mod (AnimatedCape.MAX_FRAMES / MAX_FPS).
# The mod enforces its side of these too - never trust the API's own output.
MAX_FRAMES = 16
MAX_FPS = 10

# Frames wider than this get downscaled before being stored. 512px is an
# extremely generous HD cape; the point of the cap is that the worst-case
# in-memory cost of an animated cape stays trivial (16 * 512x256x4 = 8MB
# absolute ceiling, and that's for an absurd cape).
MAX_ANIM_WIDTH = 512


def _load_capes_meta() -> dict:
    if os.path.exists(CAPES_META_PATH):
        try:
            with open(CAPES_META_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"capes": []}  # list of {"filename", "name"}


def _save_capes_meta(meta: dict) -> None:
    with open(CAPES_META_PATH, "w", encoding="utf-8") as f:
        json.dump(meta, f, indent=2)


def _frame_sheet_size(w: int, h: int) -> tuple[int, int]:
    """The vanilla-faithful cape sheet size for an arbitrary input image.

    64x32 unless the image is already a bigger 2:1 layout: HD capes scale the
    whole sheet, and honoring that keeps HD uploads crisp instead of crushing
    them to 64x32.
    """
    if h > 0 and w == h * 2 and w in _VALID_CAPE_WIDTHS:
        return w, h
    return 64, 32


def _to_cape_sheet(img: Image.Image) -> Image.Image:
    """Turns any image into a proper cape layout.

    Cape-shaped inputs pass through untouched (bar an RGBA flatten). Anything
    else is fitted onto the visible back panel - the 10x16 region at (1,1) of
    a 64x32 sheet - scaled to fit, centered, with the rest transparent. The
    result is ALWAYS a valid cape no matter what the user picked.
    """
    img = img.convert("RGBA")
    w, h = img.size
    sheet_w, sheet_h = _frame_sheet_size(w, h)
    if (sheet_w, sheet_h) == (w, h):
        return img

    sheet = Image.new("RGBA", (sheet_w, sheet_h), (0, 0, 0, 0))
    n = sheet_w // 64
    panel_w, panel_h = 10 * n, 16 * n
    scale = min(panel_w / w, panel_h / h)
    tw, th = max(1, round(w * scale)), max(1, round(h * scale))
    fitted = img.resize((tw, th), Image.LANCZOS if scale < 1 else Image.NEAREST)
    # Center on the back panel, matching how the panel itself is centered.
    px = 1 * n + (panel_w - tw) // 2
    py = 1 * n + (panel_h - th) // 2
    sheet.paste(fitted, (px, py))
    return sheet


def _read_frames(src_path: str) -> list[Image.Image]:
    """Every frame of a multi-frame file, or [the image] for a still.

    Deduplicates consecutive identical frames (a common GIF authoring
    artifact that would otherwise waste frame slots) and honors nothing
    about timing - playback speed is fixed by the launcher, not the file.
    """
    with Image.open(src_path) as img:
        frames: list[Image.Image] = []
        prev = None
        for frame in range(getattr(img, "n_frames", 1)):
            img.seek(frame)
            # copy() because PIL reuses one buffer per seek.
            rgba = img.convert("RGBA").copy()
            if prev is not None and rgba.tobytes() == prev:
                continue
            frames.append(rgba)
            prev = rgba.tobytes()
            if len(frames) >= MAX_FRAMES:
                break
        return frames


def validate_cape_file(path: str) -> tuple[bool, str]:
    """Checks the file is something we can turn into a cape.

    Deliberately liberal: ANY decodable image is valid (see module docstring
    - non-cape shapes are auto-fitted, not rejected). The only failures are
    "not an image", "unreadable", and "absurdly large".
    """
    try:
        if os.path.getsize(path) > MAX_SOURCE_BYTES:
            return False, "That file is too large (over 8 MB)."
        with Image.open(path) as img:
            img.verify()  # structural check only
        return True, ""
    except Exception:
        return False, "Couldn't read that file as an image"


def list_custom_capes() -> list[dict]:
    return _load_capes_meta()["capes"]


def _frames_path_for(filename: str) -> str:
    return os.path.join(CAPES_DIR, filename + ".frames.json")


def add_custom_cape(src_path: str, display_name: str) -> dict:
    """Copies a validated image into CAPES_DIR as a real cape layout, and -
    if it had multiple frames - stores the animation alongside.

    Returns the new cape's metadata entry ({"filename", "name"}), plus an
    "animated" flag the UI reads to badge the entry.
    """
    ok, err = validate_cape_file(src_path)
    if not ok:
        raise ValueError(err)

    frames = _read_frames(src_path)
    if not frames:
        raise ValueError("Couldn't read that file as an image")

    # The static sheet (what CSL loads and what everyone else would see) is
    # the first frame, fitted onto a cape layout.
    sheet = _to_cape_sheet(frames[0])

    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", display_name.strip()) or "cape"
    filename = f"{safe_name}_{uuid.uuid4().hex[:8]}.png"
    os.makedirs(CAPES_DIR, exist_ok=True)
    dest = os.path.join(CAPES_DIR, filename)
    sheet.save(dest, "PNG")

    entry = {"filename": filename, "name": display_name.strip() or safe_name}

    # Animation: store capped, downscaled frames as base64 PNGs next to the
    # cape. Served only to this machine's Cubeon mod via the local API.
    if len(frames) > 1:
        encoded = []
        for fr in frames:
            f = _to_cape_sheet(fr)
            if f.width > MAX_ANIM_WIDTH:
                f = f.resize(
                    (MAX_ANIM_WIDTH, MAX_ANIM_WIDTH // 2), Image.LANCZOS)
            buf = io.BytesIO()
            f.save(buf, "PNG")
            encoded.append(base64.b64encode(buf.getvalue()).decode("ascii"))
        with open(_frames_path_for(filename), "w", encoding="utf-8") as f:
            json.dump({"fps": min(MAX_FPS, max(2, len(encoded))),
                       "frames": encoded}, f)
        entry["animated"] = True

    meta = _load_capes_meta()
    meta["capes"].append(entry)
    _save_capes_meta(meta)
    return entry


def delete_custom_cape(filename: str) -> None:
    meta = _load_capes_meta()
    meta["capes"] = [c for c in meta["capes"] if c["filename"] != filename]
    _save_capes_meta(meta)
    for path in (os.path.join(CAPES_DIR, filename),
                 _frames_path_for(filename)):
        if os.path.exists(path):
            try:
                os.remove(path)
            except OSError:
                pass


def get_custom_cape_path(filename: str) -> str:
    return os.path.join(CAPES_DIR, filename)


def animated_cape_frames(filename: str | None) -> dict | None:
    """The stored animation for a cape, as the local API serves it.

    Returns {"fps": int, "frames": [b64...], "version": int} or None when
    the cape has no animation. `version` is the frames file's mtime-ns: it
    changes whenever the user swaps the animated cape, which lets the mod
    skip re-decoding an unchanged set. Reads are cheap (one small JSON file
    the launcher itself wrote); there is no caching because the endpoint is
    polled at the mod's idle rate, not per frame.
    """
    if not filename:
        return None
    path = _frames_path_for(filename)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        frames = [s for s in data.get("frames", [])
                  if isinstance(s, str) and s]
        if not frames:
            return None
        return {"fps": int(data.get("fps", 2) or 2),
                "frames": frames[:MAX_FRAMES],
                "version": os.stat(path).st_mtime_ns}
    except (OSError, ValueError, TypeError):
        return None


def set_active_cape(cfg: dict, filename: str | None) -> None:
    cfg["active_cape"] = filename
    # Sync before saving so the recorded "name we wrote under" lands in the
    # same save - mirrors skins.set_active_skin().
    sync_local_cape_to_csl(cfg)
    save_config(cfg)


def sync_local_cape_to_csl(cfg: dict) -> None:
    """Mirrors the active cape into CustomSkinLoader's LocalSkin/capes folder
    as <USERNAME>.png - the exact path CSL's LocalSkin source reads.

    Call this whenever the active cape *or* the username changes: offline
    accounts are keyed off the username, so a rename means CSL looks up a
    different file. Best-effort - a failure here must never block an upload.
    Uses its own cfg bookkeeping key (csl_synced_cape_name) so it never
    collides with the skin sync's csl_synced_name.
    """
    username = (cfg.get("username") or "").strip()
    filename = cfg.get("active_cape")
    previous = cfg.get("csl_synced_cape_name")

    # Clean up the file we last wrote if the name changed (a rename would
    # otherwise strand <OLDNAME>.png) or there's no active cape anymore. Only
    # ever remove a name this launcher recorded writing, so a cape the user
    # dropped into LocalSkin by hand is never clobbered.
    if previous and (previous != username or not filename):
        _remove_local_cape(previous)
        cfg["csl_synced_cape_name"] = None

    if not (username and filename):
        return

    src = get_custom_cape_path(filename)
    if not os.path.isfile(src):
        return
    try:
        os.makedirs(CSL_LOCAL_CAPES_DIR, exist_ok=True)
        shutil.copyfile(src, os.path.join(CSL_LOCAL_CAPES_DIR, f"{username}.png"))
        cfg["csl_synced_cape_name"] = username
    except OSError:
        pass


def _remove_local_cape(username: str) -> None:
    try:
        path = os.path.join(CSL_LOCAL_CAPES_DIR, f"{username}.png")
        if os.path.isfile(path):
            os.remove(path)
    except OSError:
        pass


def render_cape_preview(filename: str, out_path: str, scale: int = 10) -> str:
    """Renders the visible back face of the cape as a crisp pixel-art preview.

    In the 64x32 cape layout the outer back panel is the 10x16 region at
    (1,1). HD capes scale that layout by width/64, so the crop is computed
    relative to the sheet's own resolution and always grabs the same panel.
    """
    src_path = get_custom_cape_path(filename)
    with Image.open(src_path) as img:
        img = img.convert("RGBA")
        n = max(1, img.width // 64)  # HD scale factor (1 for a vanilla 64x32)
        back = img.crop((1 * n, 1 * n, 11 * n, 17 * n))
        # Reduce an HD cape back to its logical 10x16 grid first, then blow it
        # up at `scale` with nearest-neighbour so the pixels stay square.
        if n > 1:
            back = back.resize((10, 16), Image.NEAREST)
        back = back.resize((10 * scale, 16 * scale), Image.NEAREST)
        back.save(out_path)
    return out_path
