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
import io
import os
import threading
from collections import OrderedDict
from hashlib import sha1, sha256
from urllib.parse import urlparse

# Lazy: `requests` costs ~97ms to import and every module that pulls it in
# eagerly puts that on the startup path, even for a session that never
# touches the network. Call sites are unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
requests = LazyModule("requests")

from .paths import CUBEON_HOME, modrinth_headers

ICON_DIR = os.path.join(CUBEON_HOME, "cache", "icons")

# The one User-Agent Modrinth's CDN expects on image requests. Shared with the
# API calls so mod art and mod metadata can't drift apart.
_HEADERS = modrinth_headers("modrinth cdn art")

_lock = threading.Lock()
_inflight = set()
_sources = OrderedDict()
_ready = {}
_SOURCE_LIMIT = 128
_SOURCE_BYTES = 16 * 1024 * 1024
_validated_sources = OrderedDict()
_VALIDATION_LIMIT = 64


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
        stat = os.stat(path)
        stamp = (stat.st_mtime_ns, stat.st_size)
        with _lock:
            cached = _sources.get(path)
            if cached and cached[0] == stamp:
                _sources.move_to_end(path)
                return cached[1]
        with open(path, "rb") as f:
            encoded = base64.b64encode(f.read()).decode("ascii")
        with _lock:
            _sources[path] = (stamp, encoded)
            _sources.move_to_end(path)
            retained_bytes = sum(len(entry[1]) for entry in _sources.values())
            while len(_sources) > _SOURCE_LIMIT or retained_bytes > _SOURCE_BYTES:
                _, removed = _sources.popitem(last=False)
                retained_bytes -= len(removed[1])
        return encoded
    except OSError:
        return url


def peek_src(url):
    """Memory-only lookup for hot UI paths; performs no filesystem work."""
    if not url:
        return None
    with _lock:
        cached = _sources.get(_dest(url))
        return cached[1] if cached else None


def valid_source(source):
    """Reject corrupt cached/embedded artwork before Flet gets its bytes."""
    if not isinstance(source, str) or len(source) > 4 * 1024 * 1024:
        return False
    key = sha256(source.encode("utf-8", errors="surrogatepass")).digest()
    with _lock:
        if key in _validated_sources:
            _validated_sources.move_to_end(key)
            return _validated_sources[key]
    from PIL import Image
    valid = False
    try:
        encoded = source.split(',', 1)[1] if source.startswith('data:image/') else source
        raw = base64.b64decode(encoded, validate=True)
        with Image.open(io.BytesIO(raw)) as image:
            if image.width * image.height <= 4_194_304:
                image.load()
                valid = True
    except (OSError, ValueError, IndexError, Image.DecompressionBombError):
        pass
    with _lock:
        _validated_sources[key] = valid
        _validated_sources.move_to_end(key)
        while len(_validated_sources) > _VALIDATION_LIMIT:
            _validated_sources.popitem(last=False)
    return valid


def load_source(url):
    """Resolve cached/downloaded artwork on a worker, without a second CDN fetch."""
    if not url:
        return None
    path = _dest(url)
    owned = False
    with _lock:
        ready = _ready.get(path)
        if ready is None and not local_path(url):
            _inflight.add(path)
            _ready[path] = ready = threading.Event()
            owned = True
    if owned:
        # IconLoader already owns a bounded worker: fetch here so its pooled
        # session survives for the next image, without a second download thread.
        from . import net
        _download_icon(url, path, ready, net._do_get)
    elif ready:
        ready.wait(12)
    source = src(url) if local_path(url) else None
    return source if valid_source(source) else None


def _download_icon(url, path, ready, get):
    response = None
    try:
        if local_path(url):
            return
        response = get(url, headers=_HEADERS, timeout=(3, 7))
        response.raise_for_status()
        os.makedirs(ICON_DIR, exist_ok=True)
        temporary = path + '.tmp'
        with open(temporary, 'wb') as output:
            output.write(response.content)
        os.replace(temporary, path)
    except Exception:
        pass
    finally:
        if response is not None and callable(getattr(response, 'close', None)):
            try:
                response.close()
            except Exception:
                pass
        with _lock:
            _inflight.discard(path)
            _ready.pop(path, None)
            ready.set()


def prefetch(url: str | None) -> None:
    """Downloads the icon to the disk cache on a daemon thread if missing.
    Safe to call on every render: an existing copy (or an in-flight download)
    makes it a no-op."""
    if not url:
        return
    path = _dest(url)
    with _lock:
        if path in _inflight or local_path(url):
            return
        _inflight.add(path)
        _ready[path] = ready = threading.Event()

    def _download():
        _download_icon(url, path, ready, requests.get)

    try:
        threading.Thread(target=_download, daemon=True).start()
    except Exception:
        with _lock:
            _inflight.discard(path)
            _ready.pop(path, None)
            ready.set()
