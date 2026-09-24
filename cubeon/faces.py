"""
Face avatars - every Cubeon player's head crop, fetched into the launcher.

The skins Worker serves GET <CUBEON_API_BASE>/faces/<name>.png (see
worker/cubeon-skins.js serveFace: name -> pointer -> uuid -> face texture,
the 8x8 head crop with the hat layer, upscaled to 128). The launcher never
used it: Chat-tab avatars were color-initial chips and the self fallback
(crafatar) 404s for offline accounts - so no profile picture showed in
chat, on friend ID cards, or on your own card. This module is the fetch
half the UI paints from.

Design mirrors icons.py (disk cache, background download, never blocks or
raises) with one crucial difference - a NEGATIVE cache. Unlike a Modrinth
icon, the 404 is a COMMON answer here: any name that isn't a registered
Cubeon player (or is moderation-blocked) returns not-found, and the chat
roster repaints every 1.5s. Without the negative cache a roster full of
non-Cubeon names would GET 404s forever.

Callers use get_face_b64() on every repaint:
    b64 = faces.get_face_b64(name)   # cached bytes as base64, else None
and render the color-initial chip when None. A miss schedules ONE
background download; when it lands, the caller's face-availability token
(usually just bool(faces.get_face_b64(name)) inside its repaint sig) flips
and the next repaint shows the face.
"""
import base64
import os
import re
import threading
import time

from .lazy import LazyModule
requests = LazyModule("requests")

from .csl import CUBEON_API_BASE
from .paths import CUBEON_HOME

FACE_DIR = os.path.join(CUBEON_HOME, "cache", "faces")

# Minecraft names only - the Worker's USERNAME_RE rejects anything wider
# anyway, and this doubles as a path-safety guard for the cache filename.
_NAME_RE = re.compile(r"^[A-Za-z0-9_]{1,16}$")
_HEADERS = {"User-Agent": "Cubeon/cubeon/1.0"}
_DOWNLOAD_TIMEOUT = 10
# How long a failed lookup stays negative before one retry is allowed.
# 404s get the long version: a name not on Cubeon rarely becomes one
# mid-session, and the retry keeps renames/late signups appearing. Local
# failures (a kill mid-write, a transient OSError) only earn _RETRY_LOCAL -
# otherwise one flaky write poisons the name for the whole session and the
# user sees "no faces until restart".
_MISS_RETRY = 600.0
_RETRY_LOCAL = 60.0

_lock = threading.Lock()
_missed: dict[str, float] = {}   # lowercased name -> monotonic retry-at deadline
_inflight: set[str] = set()


def url(name: str) -> "str | None":
    """The Worker face URL for this name, or None for an invalid one
    (blank, too long, or outside Minecraft's name charset)."""
    name = (name or "").strip()
    if not _NAME_RE.match(name):
        return None
    return f"{CUBEON_API_BASE}/faces/{name}.png"


def _dest(name: str) -> str:
    return os.path.join(FACE_DIR, f"{name.lower()}.png")


def _schedule(name: str) -> None:
    """Starts one background download for this name, unless one is already
    in flight or the negative cache is still fresh. Fire-and-forget."""
    key = name.lower()
    now = time.monotonic()
    with _lock:
        retry_at = _missed.get(key)  # deadline: don't ask again before this
        if retry_at is not None and now < retry_at:
            return
        if key in _inflight:
            return
        _inflight.add(key)

    def _download():
        try:
            u = url(name)
            if u is None:
                return
            resp = requests.get(u, headers=_HEADERS, timeout=_DOWNLOAD_TIMEOUT)
            if resp.status_code == 200 and resp.content:
                os.makedirs(FACE_DIR, exist_ok=True)
                tmp = _dest(name) + ".tmp"
                with open(tmp, "wb") as f:
                    f.write(resp.content)
                os.replace(tmp, _dest(name))
            else:
                # A real miss (404: not a Cubeon name / no skin) - stay
                # negative for a while so repaints don't re-hammer the Worker.
                with _lock:
                    _missed[key] = time.monotonic() + _MISS_RETRY
            # Local trouble (kill mid-write, transient OSError) is NOT the
            # same as a 404: poisoning the negative cache for 10 minutes
            # turned one flaky write into "no faces until restart". Retry
            # those after _RETRY_LOCAL seconds instead (see except).
        except Exception:
            with _lock:
                _missed[key] = time.monotonic() + _RETRY_LOCAL
        finally:
            with _lock:
                _inflight.discard(key)

    threading.Thread(target=_download, daemon=True).start()


def get_face_b64(name: str) -> "str | None":
    """base64 of this player's face PNG from the disk cache, or None.

    A cache miss kicks off the one background download (subject to the
    negative cache) so a LATER call - the next poll repaint - can show it.
    Never blocks, never raises: an avatar is cosmetic."""
    if url(name) is None:
        return None
    path = _dest(name)
    try:
        if os.path.isfile(path) and os.path.getsize(path) > 0:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
    except OSError:
        pass
    _schedule(name)
    return None
