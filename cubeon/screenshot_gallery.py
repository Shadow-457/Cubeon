"""Safe access to Minecraft screenshots for the launcher gallery.

Minecraft writes screenshots into Cubeon's private game directory.  This
module keeps all filesystem and image decoding rules in one place so the UI
can remain a thin viewer: only real image files inside that directory are
listed, thumbnails are bounded before they cross the Flet boundary, and
deletion can never escape the screenshots folder.

Performance (2026-09-21): both hot paths used to re-read every screenshot
on every gallery open - ``list_screenshots`` ran ``Image.verify()`` (a full
file read) per PNG on the UI thread, and every thumbnail was fully decoded
and re-encoded per visit with no cache. Both are now cached:

  * the list is memoized against the screenshots directory's mtime
    (add/remove/rename bumps it; nothing else writes there), so opening
    the Images pane again is O(1);
  * bounded renders (thumbnails + the selected preview) are stored in the
    launcher cache dir keyed by source mtime + size bucket, so each
    screenshot is decoded at most once until it changes.
"""

from __future__ import annotations

import base64
import io
import os
import subprocess
import sys
import tempfile
from datetime import datetime

from PIL import Image, ImageOps

from .paths import CACHE_DIR, MINECRAFT_DIR


SCREENSHOTS_DIR = os.path.join(MINECRAFT_DIR, "screenshots")
_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp"}
_MAX_IMAGE_BYTES = 64 * 1024 * 1024

# Bounded renders live in the launcher cache (same convention as
# version_art), never inside the user's screenshots folder - so the cache
# can't be mistaken for captures by the game or any other tool.
_RENDER_CACHE_DIR = os.path.join(CACHE_DIR, "screenshot_renders")


def _folders():
    from . import storage
    result = {"": SCREENSHOTS_DIR}
    seen = {os.path.realpath(SCREENSHOTS_DIR)}
    for vid, meta, _profile in storage.instance_profiles():
        folder = os.path.join(storage.game_dir(vid), "screenshots")
        real = os.path.realpath(folder)
        if real not in seen:
            result[meta["id"]] = folder
            seen.add(real)
    return result


def _safe_path(filename: str) -> str:
    """Resolve a screenshot filename without allowing path traversal."""
    if not isinstance(filename, str) or not filename or os.path.basename(filename) != filename or "\\" in filename:
        raise ValueError("Invalid screenshot name")
    directory = SCREENSHOTS_DIR
    if filename.startswith("@") and filename.count("@") >= 2:
        _, ident, filename = filename.split("@", 2)
        directory = _folders().get(ident)
        if not directory or not filename or filename in (".", ".."):
            raise ValueError("Invalid screenshot instance")
    path = os.path.realpath(os.path.join(directory, filename))
    root = os.path.realpath(directory)
    if os.path.commonpath((root, path)) != root:
        raise ValueError("Screenshot is outside the screenshots folder")
    return path


# ---------------------------------------------------------------------------
# List caching: the screenshots folder is written by one producer (the game,
# + delete from the gallery) and nothing edits a file in place, so the
# directory's own mtime is a correct change signature. Cache hits skip the
# per-file Image.verify() (full-file read) that made every open slow.
# ---------------------------------------------------------------------------
_LIST_CACHE = {"signature": None, "items": None}


def _dir_signature() -> tuple | None:
    """(mtime_ns, inode) of the screenshots dir; None when it doesn't exist."""
    result = []
    for key, folder in _folders().items():
        try:
            st = os.stat(folder)
            result.append((key, folder, st.st_mtime_ns, st.st_ino))
        except FileNotFoundError:
            pass
    return tuple(result)


def list_screenshots() -> list[dict]:
    """Return valid screenshot metadata, newest first.

    Corrupt files are omitted rather than making the whole gallery fail.  The
    original path is never exposed to the UI; callers use ``filename`` for all
    later operations.

    Served from a directory-mtime-keyed cache: repeated opens (the Images
    pane refreshes on every visit) are O(1) instead of re-verifying every
    PNG on the UI thread. A new capture, a delete, or a folder change in
    any other way bumps the signature and triggers one real scan.
    """
    signature = _dir_signature()
    if _LIST_CACHE["signature"] == signature and _LIST_CACHE["items"] is not None:
        return list(_LIST_CACHE["items"])
    names = []
    for key, folder in _folders().items():
        try:
            names.extend(f"@{key}@{name}" if key else name for name in os.listdir(folder))
        except OSError:
            continue
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
            "name": os.path.splitext(os.path.basename(path))[0].replace("_", " "),
            "width": width,
            "height": height,
            "bytes": size,
            "mtime": mtime,
            "date": datetime.fromtimestamp(mtime).strftime("%b %d, %Y  %H:%M"),
        })
    result.sort(key=lambda item: (item["mtime"], item["filename"]), reverse=True)
    _LIST_CACHE.update(signature=signature, items=list(result))
    return result


def _bounded_render_cache_path(filename: str, max_size) -> str:
    """Cache file for one (filename, size bucket) render."""
    stem, ext = os.path.splitext(filename)
    return os.path.join(_RENDER_CACHE_DIR,
                        f"{stem}{ext}.{max_size[0]}x{max_size[1]}.png")


def _read_cache_b64(path: str) -> str | None:
    """base64 of a cached render, or None on any read failure."""
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None


def _write_cache(path: str, data: bytes) -> None:
    """tmp+replace write (the repo's atomic write invariant); cache writes
    are disposable, so a failure just silently skips caching."""
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + f".tmp{os.getpid()}"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, path)
    except OSError:
        try:
            if os.path.exists(tmp):
                os.remove(tmp)
        except OSError:
            pass


def image_base64(filename: str, *, max_size=(960, 640), quality: int = 88) -> str:
    """Decode and bound a screenshot, returning raw base64 for ``ft.Image``.

    Render is disk-cached (keyed by the source's mtime + the size bucket),
    so revisiting the gallery re-encodes a small cached PNG instead of
    re-decoding the full-resolution screenshot every time.
    """
    path = _safe_path(filename)
    try:
        source_mtime = os.path.getmtime(path)
    except OSError:
        raise FileNotFoundError(filename)
    cache_path = _bounded_render_cache_path(filename, max_size)
    cached = _read_cache_b64(cache_path)
    if cached is not None and os.path.getmtime(cache_path) >= source_mtime:
        return cached
    with Image.open(path) as source:
        image = ImageOps.exif_transpose(source).convert("RGBA")
        image.thumbnail(max_size, Image.Resampling.LANCZOS)
        out = io.BytesIO()
        image.save(out, format="PNG", optimize=True)
        out_bytes = out.getvalue()
    _write_cache(cache_path, out_bytes)
    return base64.b64encode(out_bytes).decode("ascii")


def clipboard_path(filename: str) -> str:
    """Return a validated screenshot path for a desktop clipboard hand-off."""
    path = _safe_path(filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(filename)
    return path


def delete_screenshot(filename: str) -> None:
    """Delete one screenshot after resolving it inside the owned folder.

    The directory mtime bump invalidates the list cache automatically; the
    file's cached renders are dropped too so a reused filename can't show
    the deleted picture.
    """
    from . import storage
    storage.assert_writable()
    path = _safe_path(filename)
    if not os.path.isfile(path):
        raise FileNotFoundError(filename)
    os.remove(path)
    directory = os.path.dirname(_bounded_render_cache_path(filename, (1, 1)))
    stem, ext = os.path.splitext(filename)
    for name in os.listdir(directory) if os.path.isdir(directory) else []:
        if name.startswith(f"{stem}{ext}."):
            try:
                os.remove(os.path.join(directory, name))
            except OSError:
                pass


def open_screenshots_folder(filename: str | None = None) -> str:
    """Open the selected capture's folder, or the active screenshots directory.

    Run off the UI thread: desktop helpers may take time to hand off the request.
    A failed helper must reach the caller instead of reporting a successful open.
    """
    from . import storage, paths
    if filename is not None:
        folder = os.path.dirname(clipboard_path(filename))
    else:
        folder = os.path.join(paths.active_game_dir(), "screenshots") if storage.enabled() else SCREENSHOTS_DIR
    folder = os.path.abspath(folder)
    os.makedirs(folder, exist_ok=True)
    if sys.platform == "win32":
        os.startfile(folder)  # type: ignore[attr-defined]
        return folder
    elif sys.platform.startswith("linux"):
        command = ["xdg-open", folder]
    elif sys.platform == "darwin":
        command = ["open", folder]
    else:
        raise OSError(f"Opening folders is unsupported on {sys.platform}")

    env = os.environ.copy()
    if sys.platform.startswith("linux") and getattr(sys, "frozen", False):
        # PyInstaller prepends its bundled libraries; system file managers need
        # the original search path rather than Cubeon's bundled libraries.
        original = env.pop("LD_LIBRARY_PATH_ORIG", None)
        if original is not None:
            env["LD_LIBRARY_PATH"] = original
        else:
            env.pop("LD_LIBRARY_PATH", None)

    # A file avoids pipe backpressure if a helper keeps the file manager alive.
    with tempfile.TemporaryFile() as errors:
        process = subprocess.Popen(command, stdout=subprocess.DEVNULL,
                                   stderr=errors, start_new_session=True, env=env)
        try:
            code = process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            # Some desktop helpers remain attached to the open file manager.
            # Leave it running; opening a folder must never close its window.
            return folder
        if code:
            errors.seek(0)
            detail = errors.read(1024).decode("utf-8", errors="replace").strip()
            raise OSError(detail or f"{command[0]} exited with status {code}")
    return folder
