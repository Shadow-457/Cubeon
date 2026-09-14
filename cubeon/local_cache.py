"""Cubeon's local content cache: the one layer every browse/search/discovery
path goes through before it is allowed to touch the network.

Three tiers, coldest first:

1. In-process memory (LRU, ~256 entries) - repeated opens of the Mods tab or
   paging back and forth in a browse list cost nothing at all: no disk read,
   no JSON parse, no stat() calls.
2. Disk JSON (CACHE_DIR/<ns>_<sha1>.json) - survives launcher restarts, so the
   day's browse results are on screen the instant the tab opens.
3. The network - only hit when both tiers are stale, and NEVER allowed to
   take the UI down with it: `cached_call` implements stale-while-revalidate
   (serve the stale copy immediately, refresh on a background thread) and an
   offline fallback (fetch fails, stale exists -> return the stale copy).
   A launcher that shows yesterday's mod list while offline is infinitely
   better than one that shows a spinner, or nothing.

Negative results (a project with no matching file) are cached too, so a mod
with no build for this MC version doesn't re-hit the API on every click.
"""
import json
import os
import threading
import time
from collections import OrderedDict
from hashlib import sha1

from .paths import CACHE_DIR

# --- in-memory tier ---------------------------------------------------------
# Keyed by (namespace, digest) - the same identity the disk file has, so a mem
# hit and a disk hit can never disagree about which entry they mean. An LRU
# (not a plain dict) keeps long sessions from growing this without bound; the
# cap is generous because every entry is a handful of search hits, not bytes.
_MEM: "OrderedDict[tuple, tuple]" = OrderedDict()
_MEM_MAX = 256
_MEM_LOCK = threading.Lock()

# Keys with a background refresh in flight. Without this dedupe, ten rapid
# tab opens with a stale cache would spawn ten identical refresh threads.
_INFLIGHT: set = set()


def _path(namespace: str, key: object) -> str:
    raw = json.dumps(key, sort_keys=True, default=str)
    digest = sha1(raw.encode("utf-8")).hexdigest()
    safe_ns = "".join(ch if ch.isalnum() or ch in "._-" else "_" for ch in namespace)
    return os.path.join(CACHE_DIR, f"{safe_ns}_{digest}.json")


def _mem_get(kk: tuple):
    with _MEM_LOCK:
        if kk not in _MEM:
            return None
        _MEM.move_to_end(kk)  # LRU touch
        return _MEM[kk]


def _mem_put(kk: tuple, expires_at: float, value) -> None:
    with _MEM_LOCK:
        _MEM[kk] = (expires_at, value)
        _MEM.move_to_end(kk)
        while len(_MEM) > _MEM_MAX:
            _MEM.popitem(last=False)


def get(namespace: str, key: object, max_age: int = 86400):
    """Fresh-only read: memory first, then disk. None when missing OR stale."""
    kk = (namespace, _path(namespace, key))
    hit = _mem_get(kk)
    if hit is not None and time.time() <= hit[0]:
        return hit[1]

    path = kk[1]
    try:
        with open(path, "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    stored = payload.get("time", 0)
    value = payload.get("value")
    if max_age and time.time() - stored > max_age:
        return None  # stale: don't serve as fresh (cached_call handles the rest)
    _mem_put(kk, stored + (max_age or 0), value)
    return value


def get_stale(namespace: str, key: object):
    """Any-age read: the offline/slow-network fallback. None only if the key
    has NEVER been fetched on this machine."""
    kk = (namespace, _path(namespace, key))
    hit = _mem_get(kk)
    if hit is not None:
        return hit[1]
    try:
        with open(kk[1], "r", encoding="utf-8") as f:
            payload = json.load(f)
    except Exception:
        return None
    value = payload.get("value")
    _mem_put(kk, payload.get("time", 0) + 86400 * 365, value)
    return value


def set(namespace: str, key: object, value):
    path = _path(namespace, key)
    try:
        os.makedirs(CACHE_DIR, exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump({"time": time.time(), "value": value}, f)
        # Atomic-ish swap: a launcher killed mid-write can never leave a
        # half-written cache file that poisons every later read.
        os.replace(tmp, path)
    except Exception:
        pass
    _mem_put((namespace, path), time.time() + 86400, value)
    return value


def cached_call(namespace: str, key: object, fetch, max_age: int = 86400,
                stale_ok: bool = True, background_refresh: bool = True):
    """The one call site pattern for anything read-heavy and rarely-changing.

    Order of operations:
      1. fresh cache (memory or disk) -> return it, zero network
      2. stale cache + background_refresh -> return the stale copy NOW and
         refresh on a daemon thread (stale-while-revalidate: the user sees
         last session's results instantly, and next open is fresh)
      3. network fetch -> cache and return
      4. fetch failed + stale_ok + any stale copy exists -> return it
         (offline: better yesterday's list than an error)
      5. fetch failed, nothing cached -> re-raise, the caller shows the error
    """
    fresh = get(namespace, key, max_age)
    if fresh is not None:
        return fresh

    path = _path(namespace, key)
    kk = (namespace, path)
    stale = get_stale(namespace, key)

    def _refresh():
        try:
            value = fetch()
            set(namespace, key, value)
        except Exception:
            # keep the stale copy; the next call tries again - but leave a
            # trail (bugs-and-flaws #13): silent refresh failures made
            # stale-forever results impossible to diagnose.
            import logging
            logging.getLogger(__name__).debug(
                "cache background refresh failed for %s", namespace,
                exc_info=True)
        finally:
            _INFLIGHT.discard(kk)

    if stale is not None and background_refresh:
        if kk not in _INFLIGHT:
            _INFLIGHT.add(kk)
            threading.Thread(target=_refresh, daemon=True).start()
        return stale

    try:
        value = fetch()
    except Exception:
        if stale_ok and stale is not None:
            return stale
        raise
    return set(namespace, key, value)



def invalidate(namespace: str | None = None) -> int:
    """Explicit cache invalidation (bugs-and-flaws #16).

    The stale-while-revalidate flow self-heals search/browse results on the
    next open, but there was no way to FORCE a refresh (e.g. a future
    Settings 'clear content cache' button, or 'a mod was yanked and users
    keep seeing it for a day'). Drops the memory tier and, for the given
    namespace (or everything when None), the disk files. Returns the number
    of disk entries removed."""
    import glob
    with _MEM_LOCK:
        if namespace is None:
            _MEM.clear()
        else:
            for kk in [k for k in list(_MEM) if k[0] == namespace]:
                _MEM.pop(kk, None)
    removed = 0
    if namespace is None:
        pattern = "*.json"
    else:
        safe_ns = "".join(ch if ch.isalnum() or ch in "._-" else "_"
                          for ch in namespace)
        pattern = f"{safe_ns}_*.json"
    try:
        for p in glob.glob(os.path.join(CACHE_DIR, pattern)):
            try:
                os.remove(p)
                removed += 1
            except OSError:
                pass
    except Exception:
        pass
    return removed
