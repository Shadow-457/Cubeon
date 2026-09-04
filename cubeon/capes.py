"""
Custom cape uploads - stores user-supplied cape PNGs locally, renders a
preview of the cape's visible face, and syncs the active cape into
CustomSkinLoader's LocalSkin/capes folder so it can show up in-game.

This is the cape counterpart to cubeon/skins.py and follows that module's
shape deliberately (same validate -> add -> set-active -> sync flow), so the
two read the same and the Profile/skin UI can drive them with one pattern.

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
"""
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


def _load_capes_meta() -> dict:
    if os.path.exists(CAPES_META_PATH):
        try:
            with open(CAPES_META_PATH, "r") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError):
            pass
    return {"capes": []}  # list of {"filename", "name"}


def _save_capes_meta(meta: dict) -> None:
    with open(CAPES_META_PATH, "w") as f:
        json.dump(meta, f, indent=2)


def validate_cape_file(path: str) -> tuple[bool, str]:
    """Checks the file is a real PNG with a valid Minecraft cape layout
    (64x32, or a 2:1 HD cape like 128x64 / 256x128)."""
    try:
        with Image.open(path) as img:
            if img.format != "PNG":
                return False, "Cape must be a PNG file"
            w, h = img.size
            if w != h * 2 or w not in _VALID_CAPE_WIDTHS:
                return False, (f"Invalid cape size {img.size}, must be 64x32 "
                               "(or a 2:1 HD cape like 128x64)")
        return True, ""
    except Exception:
        return False, "Couldn't read that file as an image"


def list_custom_capes() -> list[dict]:
    return _load_capes_meta()["capes"]


def add_custom_cape(src_path: str, display_name: str) -> dict:
    """Copies a validated cape PNG into CAPES_DIR under a unique filename and
    registers it. Returns the new cape's metadata entry."""
    ok, err = validate_cape_file(src_path)
    if not ok:
        raise ValueError(err)

    safe_name = re.sub(r"[^A-Za-z0-9_-]", "_", display_name.strip()) or "cape"
    filename = f"{safe_name}_{uuid.uuid4().hex[:8]}.png"
    os.makedirs(CAPES_DIR, exist_ok=True)
    dest = os.path.join(CAPES_DIR, filename)
    shutil.copyfile(src_path, dest)

    meta = _load_capes_meta()
    entry = {"filename": filename, "name": display_name.strip() or safe_name}
    meta["capes"].append(entry)
    _save_capes_meta(meta)
    return entry


def delete_custom_cape(filename: str) -> None:
    meta = _load_capes_meta()
    meta["capes"] = [c for c in meta["capes"] if c["filename"] != filename]
    _save_capes_meta(meta)
    path = os.path.join(CAPES_DIR, filename)
    if os.path.exists(path):
        os.remove(path)


def get_custom_cape_path(filename: str) -> str:
    return os.path.join(CAPES_DIR, filename)


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
