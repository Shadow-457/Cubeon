"""
Profile picture - a single local avatar image shown in the sidebar/profile
panel. Separate from the in-game skin (skins.py) - this is launcher-only
chrome, any image works, no 64x64 restriction.
"""
import os

from PIL import Image

from .paths import PFP_DIR
from .config import save_config

_VALID_PFP_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"}


def validate_pfp_file(path: str) -> "tuple[bool, str]":
    ext = os.path.splitext(path)[1].lower()
    if ext not in _VALID_PFP_EXTENSIONS:
        return False, "Pick an image file (PNG, JPG, WEBP, GIF, or BMP)."
    try:
        with Image.open(path) as img:
            img.verify()
        return True, ""
    except Exception:
        return False, "Couldn't read that file as an image."


def set_profile_picture(src_path: str) -> str:
    """Validates and copies the chosen image into PFP_DIR as a square
    thumbnail, replacing any previous profile picture. Returns the stored
    filename (always 'avatar.png' - old copies are overwritten so PFP_DIR
    never accumulates stale images)."""
    ok, err = validate_pfp_file(src_path)
    if not ok:
        raise ValueError(err)

    with Image.open(src_path) as img:
        img = img.convert("RGBA")
        # Center-crop to square, then downscale - keeps the avatar sharp at
        # sidebar/dialog sizes without hanging onto a huge original file.
        w, h = img.size
        side = min(w, h)
        left, top = (w - side) // 2, (h - side) // 2
        img = img.crop((left, top, left + side, top + side))
        img = img.resize((256, 256), Image.LANCZOS)
        dest = os.path.join(PFP_DIR, "avatar.png")
        img.save(dest, "PNG")

    return "avatar.png"


def get_profile_picture_path(cfg: dict) -> "str | None":
    filename = cfg.get("profile_picture")
    if not filename:
        return None
    path = os.path.join(PFP_DIR, filename)
    return path if os.path.isfile(path) else None


def clear_profile_picture(cfg: dict) -> None:
    filename = cfg.get("profile_picture")
    cfg["profile_picture"] = None
    save_config(cfg)
    if filename:
        path = os.path.join(PFP_DIR, filename)
        if os.path.isfile(path):
            os.remove(path)
