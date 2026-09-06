"""Disk cache for project icons (Modrinth art shown next to every mod,
plugin, resource pack, shader and modpack row).

Why this exists: before it, every browse row's ft.Image pointed straight at
the remote CDN URL, so Flet re-downloaded the same few-KB PNG on every tab
open, every page flip, every refresh - dozens of round trips the user waits
on for art that essentially never changes. Now each URL is downloaded exactly
once per machine, into ~/.cubeon_launcher/cache/icons/, and every render
after that reads a local file: instant, offline-safe, and invisible to the
user's bandwidth.

Callers use the pair like this:

    icons.prefetch(url)            # fire-and-forget: fills the disk cache
    src = icons.src(url)           # base64 of the cached file, else the URL

so the FIRST render still shows art (via the remote URL, exactly as before)
while the download happens on a background thread, and every later render is
the cached bytes inlined as base64 (Flet can't load absolute local paths -
see src() below). Failure anywhere just degrades to the old behavior - a
missing icon is cosmetic and must never surface as an error.
"""
import base64
import os
import threading
from hashlib import sha1
from urllib.parse import urlparse

# Lazy: `requests` costs ~97ms to import and every module that pulls it in
# eagerly puts that on the startup path, even for a session that never
# touches the network. Call sites are unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
requests = LazyModule("requests")

from .paths import CUBEON_HOME

ICON_DIR = os.path.join(CUBEON_HOME, "cache", "icons")

# The one User-Agent Modrinth's CDN expects on image requests.
_HEADERS = {"User-Agent": "fuckarch/cubeon/1.0"}

_lock = threading.Lock()


def _dest(url: str) -> str:
    digest = sha1(url.encode("utf-8")).hexdigest()
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext not in (".png", ".jpg", ".jpeg", ".gif", ".webp"):
        ext = ".png"
    return os.path.join(ICON_DIR, f"{digest}{ext}")


def local_path(url: str | None) -> str | None:
    """The cached local file for this icon URL, or None if not downloaded yet.
    Never touches the network."""
    if not url:
        return None
    path = _dest(url)
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            return path
    except OSError:
        pass
    return None


def src(url: str | None) -> str | None:
    """A value ft.Image.src can actually load for this icon URL.

    Flet's Image resolves a non-URL string against the app's assets folder and
    has no filesystem access of its own, so pointing src at our absolute cache
    path (~/.cubeon_launcher/cache/icons/...) silently fails to load. The two
    working kinds of src are a real URL (the CDN) and a base64 string - so a
    disk-cached icon comes back base64-encoded (the same approach the skin
    preview uses for ~/.cubeon_launcher images), and an uncached one falls
    back to its remote URL until prefetch() files it away."""
    path = local_path(url)
    if not path:
        return url
    try:
        with open(path, "rb") as f:
            return base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return url


def prefetch(url: str | None) -> None:
    """Downloads the icon to the disk cache on a daemon thread if missing.
    Safe to call on every render: an existing copy (or an in-flight download)
    makes it a no-op."""
    if not url:
        return
    path = _dest(url)

    def _download():
        with _lock:
            try:
                if os.path.isfile(path) and os.path.getsize(path) > 0:
                    return  # another thread won the race - nothing to do
            except OSError:
                return
        try:
            resp = requests.get(url, headers=_HEADERS, timeout=10)
            resp.raise_for_status()
            os.makedirs(ICON_DIR, exist_ok=True)
            tmp = path + ".tmp"
            with open(tmp, "wb") as f:
                f.write(resp.content)
            os.replace(tmp, path)
        except Exception:
            pass  # cosmetic: the row just falls back to the remote URL

    threading.Thread(target=_download, daemon=True).start()
