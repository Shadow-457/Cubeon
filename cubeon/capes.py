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
    no custom cape     -> the bundled Cubeon cape shows locally, even offline

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

"""
import json
import io
import os
import re
import uuid
import tempfile
import threading

from PIL import Image, ImageSequence

from .paths import CAPES_DIR, CSL_LOCAL_CAPES_DIR
from .config import save_config

# PyInstaller preserves the package's __file__ under _MEIPASS; its parent
# contains bundled assets in both the AppImage and standalone layouts.
_DEFAULT_CAPE_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                                 "assets", "capes", "cubeon_cape.png")

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
MAX_GIF_FRAMES = 500
MAX_SOURCE_PIXELS = 16_000_000
MAX_DECODED_PIXELS = 64_000_000
_LOCK = threading.RLock()



from .paths import instance_csl_path

def _load_capes_meta() -> dict:
    if os.path.exists(CAPES_META_PATH):
        try:
            with open(CAPES_META_PATH, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"capes": []}  # list of {"filename", "name"}


def _save_capes_meta(meta: dict) -> None:
    from .atomicio import write_json
    write_json(CAPES_META_PATH, meta)


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


def validate_cape_file(path: str) -> tuple[bool, str]:
    """Checks the file is something we can turn into a cape.

    Deliberately liberal: ANY decodable image is valid (see module docstring
    - non-cape shapes are auto-fitted, not rejected). The only failures are
    "not an image", "unreadable", and "absurdly large".
    """
    try:
        _decode_cape(path)
        return True, ""
    except ValueError as error:
        return False, str(error)


def _decode_cape(path):
    """Decode every composited GIF frame before publishing any library files."""
    try:
        if os.path.getsize(path) > MAX_SOURCE_BYTES:
            raise ValueError("That file is too large (over 8 MB).")
        with Image.open(path) as source:
            pixels = source.width * source.height
            if pixels > MAX_SOURCE_PIXELS:
                raise ValueError("Choose an image with fewer than 16 million pixels.")
            animated = source.format == "GIF" and source.n_frames > 1
            count = source.n_frames if animated else 1
            if count > MAX_GIF_FRAMES or pixels * count > MAX_DECODED_PIXELS:
                raise ValueError("Choose a shorter GIF or one with smaller frames.")
            frames, durations = [], []
            loop = source.info.get("loop")
            for frame in ImageSequence.Iterator(source) if animated else (source,):
                sheet = _to_cape_sheet(frame.convert("RGBA"))
                if animated and sheet.width > 128:
                    sheet = sheet.resize((128, 64), Image.Resampling.NEAREST)
                frames.append(sheet)
                durations.append(max(10, min(655350, int(frame.info.get("duration", 100) or 100))))
            return frames, durations, loop
    except ValueError:
        raise
    except Exception as error:
        raise ValueError("Couldn't read that file as an image. Try another image or GIF.") from error


def _write_bytes(path, data):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".cubeon-cape-", dir=os.path.dirname(path))
    try:
        with os.fdopen(fd, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def _png_bytes(image):
    output = io.BytesIO()
    image.save(output, "PNG")
    return output.getvalue()


def _gif_bytes(frames, durations, loop):
    indexed = []
    for frame in frames:
        picture = frame.convert("RGB").quantize(colors=255)
        picture.putpalette(picture.getpalette()[:765] + [0, 0, 0])
        picture.paste(255, mask=frame.getchannel("A").point(lambda alpha: 255 if alpha < 128 else 0))
        indexed.append(picture)
    output = io.BytesIO()
    indexed[0].save(output, "GIF", save_all=True, append_images=indexed[1:],
                    duration=durations, disposal=2, transparency=255, background=255, optimize=False,
                    **({"loop": loop} if loop is not None else {}))
    return output.getvalue()


def animation_info(filename):
    """Small validated manifest; frames stay on disk outside HTTP responses."""
    path = get_custom_cape_path(filename) + ".frames.json"
    try:
        if os.path.islink(path) or os.path.getsize(path) > 64 * 1024:
            raise ValueError("That GIF cape needs to be imported again.")
        with open(path, encoding="utf-8") as stream:
            data = json.load(stream)
    except FileNotFoundError:
        return None
    except (OSError, ValueError) as error:
        raise ValueError("That GIF cape needs to be imported again.") from error
    if (not isinstance(data, dict) or data.get("schema") != 1
            or type(data.get("count")) is not int or not 2 <= data["count"] <= MAX_GIF_FRAMES
            or data.get("width") not in (64, 128) or data.get("height") != data["width"] // 2
            or not isinstance(data.get("durations"), list) or len(data["durations"]) != data["count"]
            or any(type(d) is not int or not 10 <= d <= 655350 for d in data["durations"])
            or data.get("loop") is not None and (type(data["loop"]) is not int or not 0 <= data["loop"] <= 65535)):
        raise ValueError("That GIF cape needs to be imported again.")
    return data


def list_custom_capes() -> list[dict]:
    with _LOCK:
        return _load_capes_meta()["capes"]


def add_custom_cape(src_path: str, display_name: str) -> dict:
    """Copies a validated image into CAPES_DIR as a real cape layout.

    Returns the new cape's metadata entry ({"filename", "name"}).
    """
    frames, durations, loop = _decode_cape(src_path)
    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", display_name.strip())[:64] or "cape"
    filename = f"{safe_name}_{uuid.uuid4().hex[:8]}.png"
    os.makedirs(CAPES_DIR, exist_ok=True)
    dest = os.path.join(CAPES_DIR, filename)
    entry = {"filename": filename, "name": display_name.strip()[:80] or safe_name}
    files = {dest: _png_bytes(frames[0])}
    if len(frames) > 1:
        width, height = frames[0].size
        atlas = Image.new("RGBA", (width, height * len(frames)))
        for index, frame in enumerate(frames):
            atlas.paste(frame, (0, index * height))
        files[dest + ".frames.png"] = _png_bytes(atlas)
        files[dest + ".gif"] = _gif_bytes(frames, durations, loop)
        files[dest + ".frames.json"] = json.dumps({"schema": 1, "count": len(frames),
            "width": width, "height": height, "durations": durations, "loop": loop}).encode("utf-8")
        if any(len(data) > MAX_SOURCE_BYTES for data in files.values()):
            raise ValueError("Choose a shorter or simpler GIF (the saved cape must fit in 8 MB).")
        entry["animated"] = True
    with _LOCK:
        try:
            for path, data in files.items():
                _write_bytes(path, data)
            meta = _load_capes_meta()
            meta["capes"].append(entry)
            _save_capes_meta(meta)
        except Exception:
            for path in files:
                if os.path.isfile(path):
                    os.remove(path)
            raise
    return entry


def delete_custom_cape(filename: str) -> None:
    path = os.path.join(CAPES_DIR, filename)
    get_custom_cape_path(filename)  # validate before changing metadata
    with _LOCK:
        meta = _load_capes_meta()
        meta["capes"] = [c for c in meta["capes"] if c["filename"] != filename]
        _save_capes_meta(meta)
        for suffix in ("", ".frames.png", ".frames.json", ".gif"):
            try:
                os.remove(path + suffix)
            except FileNotFoundError:
                pass


def get_custom_cape_path(filename: str) -> str:
    if (not isinstance(filename, str) or not filename.endswith(".png")
            or filename.startswith(".") or any(c in filename for c in "/\\\x00")):
        raise ValueError("Choose a cape from your library.")
    return os.path.join(CAPES_DIR, filename)


def set_active_cape(cfg: dict, filename: str | None) -> None:
    if filename is not None:
        path = get_custom_cape_path(filename)
        if not os.path.isfile(path) or os.path.islink(path):
            raise ValueError("That cape is no longer in your library.")
        info = animation_info(filename)
        entry = next((entry for entry in list_custom_capes() if entry.get("filename") == filename), {})
        if entry.get("animated") and info is None:
            raise ValueError("That GIF cape needs to be imported again.")
        if info:
            atlas = path + ".frames.png"
            try:
                if os.path.islink(atlas) or os.path.getsize(atlas) > MAX_SOURCE_BYTES:
                    raise ValueError("Invalid animation atlas")
                with Image.open(atlas) as image:
                    if image.format != "PNG" or image.size != (info["width"], info["height"] * info["count"]):
                        raise ValueError("Invalid animation atlas")
                    image.verify()
            except (OSError, ValueError) as error:
                raise ValueError("That GIF cape needs to be imported again.") from error
    _set_selection(cfg, {"active_cape": filename, "hide_cubeon_cape": False})


def set_hide_cubeon_cape(cfg: dict, hide: bool) -> None:
    """The Cape pane's "None": hide the shared cape on THIS player's screen.

    A custom cape always wins when one is selected, so choosing None clears it.
    Other players still see the shared Cubeon cape - the Worker assigns that
    server-side, and a LocalSkin texture can only replace what this client
    renders. Implemented as a fully transparent LocalSkin cape, which beats the
    Worker's cape in CSL's load order (see the ORDER CONTRACT in cubeon/csl.py).
    """
    changes = {"hide_cubeon_cape": bool(hide)}
    if hide:
        changes["active_cape"] = None
    _set_selection(cfg, changes)


def _set_selection(cfg, changes):
    """A failed configuration save restores the prior cape and owned mirrors."""
    with _LOCK:
        keys = ("active_cape", "hide_cubeon_cape", "csl_synced_cape_name")
        before = {key: cfg[key] for key in keys if key in cfg}
        mirrors = {}
        folder = instance_csl_path(CSL_LOCAL_CAPES_DIR)
        for name in (cfg.get("username"), cfg.get("csl_synced_cape_name")):
            if isinstance(name, str) and re.fullmatch(r"[A-Za-z0-9_]{3,16}", name):
                path = os.path.join(folder, name + ".png")
                if os.path.isfile(path):
                    with open(path, "rb") as stream:
                        mirrors[path] = stream.read()
                else:
                    mirrors[path] = None
        try:
            cfg.update(changes)
            sync_local_cape_to_csl(cfg)
            save_config(cfg)
        except Exception:
            for key in keys:
                if key in before:
                    cfg[key] = before[key]
                else:
                    cfg.pop(key, None)
            for path, data in mirrors.items():
                if data is None:
                    if os.path.isfile(path):
                        os.remove(path)
                else:
                    _write_bytes(path, data)
            raise


def sync_local_cape_to_csl(cfg: dict) -> None:
    """Mirrors the active cape into CustomSkinLoader's LocalSkin/capes folder
    as <USERNAME>.png - the exact path CSL's LocalSkin source reads.

    Call this whenever the active cape *or* the username changes: offline
    accounts are keyed off the username, so a rename means CSL looks up a
    different file. Best-effort - a failure here must never block an upload.
    Uses its own cfg bookkeeping key (csl_synced_cape_name) so it never
    collides with the skin sync's csl_synced_name.

    When ``hide_cubeon_cape`` is on (and no custom cape is selected) this writes
    a fully transparent cape instead. CSL's LocalSkin source is ahead of the
    Worker source, so the transparent cape wins the slot and the shared Cubeon
    cape disappears from this player's screen only.

    The default cape is bundled too: this player's cape must not depend on a
    successful heartbeat or remote texture download. Friends still use the API.
    """
    username = (cfg.get("username") or "").strip()
    filename = cfg.get("active_cape")
    hide = bool(cfg.get("hide_cubeon_cape"))
    previous = cfg.get("csl_synced_cape_name")
    use_default = not (filename or hide) and cfg.get("manage_skin_mod", True)

    # Clean up the file we last wrote if the name changed (a rename would
    # otherwise strand <OLDNAME>.png) or there's nothing to wear anymore. Only
    # ever remove a name this launcher recorded writing, so a cape the user
    # dropped into LocalSkin by hand is never clobbered.
    if previous and (previous != username or not (filename or hide or use_default)):
        _remove_local_cape(previous)
        cfg["csl_synced_cape_name"] = None

    if not username:
        return

    try:
        os.makedirs(instance_csl_path(CSL_LOCAL_CAPES_DIR), exist_ok=True)
        dest = os.path.join(instance_csl_path(CSL_LOCAL_CAPES_DIR), f"{username}.png")
        if filename:
            src = get_custom_cape_path(filename)
            if not os.path.isfile(src):
                return
            with open(src, "rb") as source:
                _write_bytes(dest, source.read())
        elif hide:
            _write_bytes(dest, _png_bytes(_transparent_cape_sheet()))
        elif use_default:
            # Respect a cape placed here by hand, just as the skin mirror does.
            if previous != username and os.path.isfile(dest):
                return
            with open(_DEFAULT_CAPE_PATH, "rb") as source:
                data = source.read()
            try:
                with open(dest, "rb") as current:
                    unchanged = current.read() == data
            except FileNotFoundError:
                unchanged = False
            if not unchanged:
                # Publish a complete texture; CSL can read while sync runs.
                import tempfile
                fd, tmp = tempfile.mkstemp(prefix=".cubeon-cape-", suffix=".tmp",
                                           dir=instance_csl_path(CSL_LOCAL_CAPES_DIR))
                try:
                    with os.fdopen(fd, "wb") as output:
                        output.write(data)
                    os.replace(tmp, dest)
                finally:
                    if os.path.exists(tmp):
                        os.remove(tmp)
        else:
            return
        cfg["csl_synced_cape_name"] = username
    except OSError:
        pass


def _transparent_cape_sheet() -> Image.Image:
    """A vanilla-sized, fully transparent cape sheet: the "no cape" texture."""
    return Image.new("RGBA", (64, 32), (0, 0, 0, 0))


def _remove_local_cape(username: str) -> None:
    try:
        path = os.path.join(instance_csl_path(CSL_LOCAL_CAPES_DIR), f"{username}.png")
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
    info = animation_info(filename)
    if info:
        with Image.open(src_path + ".frames.png") as source:
            frames = []
            n = info["width"] // 64
            for index in range(info["count"]):
                y = index * info["height"]
                back = source.crop((n, y + n, 11 * n, y + 17 * n)).convert("RGBA")
                frames.append(back.resize((10 * scale, 16 * scale), Image.Resampling.NEAREST))
        _write_bytes(out_path, _gif_bytes(frames, info["durations"], info["loop"]))
        return out_path
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
