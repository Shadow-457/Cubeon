"""Safe access to Minecraft screenshots for the launcher gallery.

Minecraft writes screenshots into Cubeon's private game directory.  This
module keeps all filesystem and image decoding rules in one place so the UI
can remain a thin viewer: only real image files inside that directory are
listed, thumbnails are bounded before they cross the Flet boundary, and
deletion can never escape the screenshots folder.
"""

from __future__ import annotations

import base64
import io
import os
import subprocess
import sys
from datetime import datetime

from PIL import Image, ImageOps

from .paths import MINECRAFT_DIR


SCREENSHOTS_DIR = os.path.join(MINECRAFT_DIR, "screenshots")
_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_MAX_IMAGE_BYTES = 64 * 1024 * 1024


def _safe_path(filename: str) -> str:
    """Resolve a screenshot filename without allowing path traversal."""
    if not isinstance(filename, str) or not filename or os.path.basename(filename) != filename:
        raise ValueError("Invalid screenshot name")
    path = os.path.realpath(os.path.join(SCREENSHOTS_DIR, filename))
    root = os.path.realpath(SCREENSHOTS_DIR)
    if os.path.commonpath((root, path)) != root:
        raise ValueError("Screenshot is outside the screenshots folder")
    return path


def list_screenshots() -> list[dict]:
    """Return valid screenshot metadata, newest first.

    Corrupt files are omitted rather than making the whole gallery fail.  The
    original path is never exposed to the UI; callers use ``filename`` for all
    later operations.
    """
    try:
        names = os.listdir(SCREENSHOTS_DIR)
    except OSError:
        return []
    result = []
    for filename in names:
        if os.path.splitext(filename)[1].lower() not in _EXTENSIONS:
            continue
        try:
            path = _safe_path(filename)
            size = os.path.getsize(path)
            if size <= 0 or size > _MAX_IMAGE_BYTES:
                continue
            with Image.open(path) as image:
                image.verify()
                width, height = image.size
            mtime = os.path.getmtime(path)
        except (OSError, ValueError, SyntaxError):
            continue
        except Exception:
            continue
        result.append({
            "filename": filename,
            "name": os.path.splitext(filename)[0].replace("_", " "),
            "width": width,
            "height": height,
            "bytes": size,
            "mtime": mtime,
            "date": datetime.fromtimestamp(mtime).strftime("%b %d, %Y  %H:%M"),
        })
    result.sort(key=lambda item: (item["mtime"], item["filename"]), reverse=True)
    return result


def image_base64(filename: str, *, max_size=(960, 640), quality: int = 88) -> str:
    """Decode and bound a screenshot, returning raw base64 for ``ft.Image``."""
    path = _safe_path(filename)
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="PNG", optimize=True)
    return base64.b64encode(out.getvalue()).decode("ascii")


def clipboard_path(filename: str) -> str:
    """Return a validated screenshot path for a desktop clipboard hand-off."""
    path = _safe_path(filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(filename)
    return path


def delete_screenshot(filename: str) -> None:
    """Delete one screenshot after resolving it inside the owned folder."""
    path = _safe_path(filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(filename)
    os.remove(path)


def open_screenshots_folder() -> None:
    """Ask the desktop file manager to open the screenshots directory."""
    os.makedirs(SCREENSHOTS_DIR, exist_ok=True)
    if sys.platform.startswith("linux"):
        command = ["xdg-open", SCREENSHOTS_DIR]
    elif sys.platform == "darwin":
        command = ["open", SCREENSHOTS_DIR]
    else:
        command = [os.path.abspath(SCREENSHOTS_DIR)]
    subprocess.Popen(command, stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL, start_new_session=True)
