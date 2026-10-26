"""Official per-version artwork for the launcher UI.

The real Minecraft Launcher paints every version's patch-notes card with the
release's OFFICIAL key art, served from Mojang's own content host. We use the
exact same source: the launcher-content patch-notes feed at
https://launchercontent.mojang.com/v2/javaPatchNotes.json, whose entries pair a
version id ("1.21.11") with an image path ("/v2/images/...") on the same host.
That is the closest thing to "the real Minecraft artwork" that exists.

This module maps a version id to a local image file, downloading on first use
and caching under CACHE_DIR/version_art/. All lookups happen on background
threads; the UI never blocks on this.

Lookup order for a version:
1. The OFFICIAL Mojang image (above). Covers 1.13+ releases and the modern
   snapshot ids. Cached as "official_<id>.<ext>".
2. Fallback to the fan wiki (minecraft.wiki) for versions Mojang's feed does
   not carry - the pre-1.13 releases and the week-numbered snapshots
   ("25w14craftmine") whose ids don't match the feed's. Cached as "<id>.<ext>".
   The wiki path tries the standard "<id>_banner.jpg" first, then the page's
   own lead image via the MediaWiki API (pageimages prop) for older pages.

The official image is preferred, so a version that gains official art later
wins over a wiki banner already on disk.
"""
import base64
import json
import os
import re
import threading
import time
from collections import OrderedDict

from .net import get_with_retry
from .paths import CACHE_DIR, user_agent

ART_DIR = os.path.join(CACHE_DIR, "version_art")

# Mojang's launcher-content host: the patch-notes feed and the key art it
# points at. This is what the official Minecraft Launcher itself reads.
_OFFICIAL_FEED = "https://launchercontent.mojang.com/v2/javaPatchNotes.json"
_OFFICIAL_BASE = "https://launchercontent.mojang.com"
# The feed JSON is ~250KB and gains entries as versions ship; re-fetch daily.
_FEED_CACHE = os.path.join(CACHE_DIR, "version_art_feed.json")
_FEED_TTL = 24 * 60 * 60

_HEADERS = {
    "User-Agent": user_agent("version artwork fetch"),
    "Referer": "https://minecraft.wiki/",
}
_OFFICIAL_HEADERS = {"User-Agent": user_agent("version artwork fetch")}

_mem: dict[str, "str | None"] = {}
_mem_lock = threading.Lock()
_feed_mem: dict = {"value": None}
_feed_refreshing: dict = {"on": False}
_feed_lock = threading.Lock()

# ENCODED-ART CACHE. src() is called from the render path - on every Play-tab
# selection change - and each call used to re-open the file and base64-encode
# it again. Mojang's key art is a JPEG of 27-53 KB, so that was a genuine read
# + encode per call per control on the UI thread (measured 0.127 ms uncached
# vs 0.023 ms cached). The expensive part is downstream: each encoded banner is
# shipped to the client for that image control. The per-instance art cards and
# the Play tab's instance list are gone (2026-10-26), so the hero banner is the
# one consumer left - see tools/test_version_art_cache.py.
#
# The encoded string is keyed by the file's (mtime, size), so a re-downloaded
# banner - which lands via os.replace, giving it a new mtime - is picked up
# automatically and nothing can go stale. LRU-capped because a long session can
# walk through many versions and each entry is held in memory.
_src_cache: "OrderedDict[str, tuple]" = OrderedDict()   # path -> (mtime_ns, size, b64)
_SRC_CACHE_MAX = 12
_src_lock = threading.Lock()


def _enc(version: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]", "_", version)


def _parse_feed(data: dict) -> dict:
    """{version_id: {"image", "title", "shortText"}} from a patch-notes feed
    payload."""
    out: dict = {}
    for entry in (data.get("entries") or []):
        if not isinstance(entry, dict):
            continue
        version = entry.get("version")
        image = (entry.get("image") or {}).get("url")
        if version and image:
            out.setdefault(version, {
                "image": image,
                "title": (entry.get("title") or "").strip(),
                "shortText": (entry.get("shortText") or "").strip(),
            })
    return out


def meta(version: "str | None") -> dict:
    """Official release metadata for a version: {"image", "title",
    "shortText"}, or {} when Mojang's feed has no entry (old releases,
    week-numbered snapshots). Disk-only after the daily feed fetch; safe on
    the UI thread."""
    if not version or not _plausible_version(version):
        return {}
    return _official_map().get(version, {})


def _fetch_feed() -> dict:
    """Fetch Mojang's patch-notes feed over the network, write it to the disk
    cache and return the parsed {version_id: {...}} map ({} on any failure).

    BLOCKING: call only from a worker thread (see _schedule_feed_refresh, and
    _fetch which runs inside fetch_async's daemon thread)."""
    try:
        resp = get_with_retry(_OFFICIAL_FEED,
                              headers=_OFFICIAL_HEADERS, timeout=20)
        try:
            raw = resp.content
        finally:
            resp.close()
        mapping = _parse_feed(json.loads(raw.decode("utf-8", "replace")))
        try:
            tmp = _FEED_CACHE + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(raw)
            os.replace(tmp, _FEED_CACHE)
        except OSError:
            pass
        return mapping
    except Exception:
        return {}


def _schedule_feed_refresh() -> None:
    """Warm the feed from the network on a daemon thread, at most once per
    process. Used by the disk-only path when the cache is missing or stale so
    the official art still lands later this session - without ever making the
    UI thread wait on Mojang's host."""
    if _feed_refreshing["on"] or _feed_mem["value"]:
        return
    _feed_refreshing["on"] = True

    def _work():
        try:
            mapping = _fetch_feed()
            if mapping:
                _feed_mem["value"] = mapping
        finally:
            _feed_refreshing["on"] = False

    threading.Thread(target=_work, daemon=True,
                     name="cubeon-feed-refresh").start()


def _official_map(allow_fetch: bool = False) -> dict:
    """version id -> official image url, from a disk-cached copy of Mojang's
    feed (refreshed once a day).

    DISK-ONLY by default: it never touches the network, so it is safe on the
    UI thread - which is exactly what meta() promises. When the cache is
    missing or stale it returns {} and kicks a one-shot background refresh, so
    a cold start shows the fallback art and the official art fills in once the
    worker lands it. Pass allow_fetch=True from a worker thread when the
    caller genuinely needs the freshly fetched map (the image downloader)."""
    if _feed_mem["value"] is not None:
        return _feed_mem["value"]
    with _feed_lock:
        if _feed_mem["value"] is not None:
            return _feed_mem["value"]
        mapping: dict = {}
        try:
            if time.time() - os.path.getmtime(_FEED_CACHE) < _FEED_TTL:
                with open(_FEED_CACHE, "r", encoding="utf-8") as fh:
                    mapping = _parse_feed(json.load(fh))
        except (OSError, ValueError):
            mapping = {}
        if mapping:
            _feed_mem["value"] = mapping
            return mapping
        if not allow_fetch:
            # UI thread: never block on the feed; refresh it in the background.
            _schedule_feed_refresh()
            return {}
        mapping = _fetch_feed()
        _feed_mem["value"] = mapping
        return mapping


def _save_image(data: bytes, prefix: str) -> "str | None":
    """Write image bytes to ART_DIR as <prefix>.<ext>; None if not an image.
    Tiny payloads are error pages, not art."""
    is_jpeg = data[:3] == b"\xff\xd8\xff"
    is_png = data[:8] == b"\x89PNG\r\n\x1a\n"
    if len(data) <= 4096 or not (is_jpeg or is_png):
        return None
    ext = ".png" if is_png else ".jpg"
    dest = os.path.join(ART_DIR, f"{prefix}{ext}")
    tmp = dest + ".tmp"
    with open(tmp, "wb") as fh:
        fh.write(data)
    os.replace(tmp, dest)
    return dest


def _wiki_url(file_name: str) -> str:
    return f"https://minecraft.wiki/images/{file_name}"


def _page_lead_image(version: str) -> "str | None":
    """Asks the MediaWiki API for the version page's lead image file name.
    Never raises; None when the page or image is missing."""
    api = ("https://minecraft.wiki/api.php?action=query&format=json"
           f"&titles=Java_Edition_{version}&prop=pageimages")
    try:
        resp = get_with_retry(api, headers=_HEADERS, timeout=20)
        try:
            data = json.loads(resp.content.decode("utf-8", "replace"))
        finally:
            resp.close()
        for page in (data.get("query", {}).get("pages", {}) or {}).values():
            name = page.get("pageimage")
            if name:
                return name
    except Exception:
        pass
    return None


def _plausible_version(version: "str | None") -> bool:
    """True when `version` could actually have official/wiki art.

    Every Minecraft release and snapshot id starts with a digit (1.21.11,
    25w14craftmine). Custom/junk instance ids the tolerant version scanner
    surfaces ("fgdg", a TLauncher folder name) never do, so skipping them
    avoids a pointless lookup + retry on every launch - those just keep the
    bundled placeholder art instead."""
    return bool(version) and version[0].isdigit()


def _official_cached(version: str) -> "str | None":
    enc = _enc(version)
    for ext in (".jpg", ".png"):
        path = os.path.join(ART_DIR, f"official_{enc}{ext}")
        if os.path.isfile(path):
            return path
    return None


def _wiki_cached(version: str) -> "str | None":
    enc = _enc(version)
    for ext in (".jpg", ".png"):
        path = os.path.join(ART_DIR, f"wiki_{enc}{ext}")
        if os.path.isfile(path):
            return path
    return None


def _cleanup_legacy_files() -> None:
    """One-time: drop the pre-official cache files.

    Older builds cached wiki banners as "<id>.jpg" with no source prefix. The
    official art is the whole point of this module now, and the user's
    complaint was that the wiki images looked wrong, so those un-prefixed files
    are removed rather than left to linger unused. Files written by this
    version ("official_*"/"wiki_*") are untouched. Best-effort."""
    try:
        for name in os.listdir(ART_DIR):
            if name.startswith(("official_", "wiki_")):
                continue
            try:
                os.unlink(os.path.join(ART_DIR, name))
            except OSError:
                pass
    except OSError:
        pass


def _fetch(version: str) -> "str | None":
    """Download this version's art into the cache, returning the local path or
    None. Official Mojang art first, then the wiki fallback. Caches the miss in
    memory only (a version whose art appears later still gets another chance
    next launch)."""
    if not _plausible_version(version):
        return None
    os.makedirs(ART_DIR, exist_ok=True)
    _cleanup_legacy_files()
    enc = _enc(version)

    # 1. Official Mojang key art (what the real launcher shows).
    already = _official_cached(version)
    if already:
        return already
    image_url = (_official_map(allow_fetch=True).get(version) or {}).get("image")
    if image_url:
        try:
            resp = get_with_retry(_OFFICIAL_BASE + image_url,
                                  headers=_OFFICIAL_HEADERS, timeout=20)
        except Exception:
            resp = None
        if resp is not None:
            try:
                data = resp.content
            finally:
                resp.close()
            saved = _save_image(data, f"official_{enc}")
            if saved:
                return saved

    # 2. Wiki fallback: the "<id>_banner.jpg" convention, then the page's own
    #    lead image. Covers pre-1.13 releases and week-numbered snapshots. An
    #    existing wiki file is reused instead of re-downloaded.
    cached_wiki = _wiki_cached(version)
    if cached_wiki:
        return cached_wiki
    for file_name in _wiki_candidates(enc):
        try:
            resp = get_with_retry(_wiki_url(file_name), headers=_HEADERS,
                                  timeout=20)
        except Exception:
            continue
        try:
            data = resp.content
        finally:
            resp.close()
        saved = _save_image(data, f"wiki_{enc}")
        if saved:
            return saved
    return None


def _wiki_candidates(enc: str) -> list:
    candidates = [f"{enc}_banner.jpg"]
    lead = _page_lead_image(enc)
    if lead:
        candidates.append(lead)
    return candidates


def _cache_probe(version: str) -> "str | None":
    """Disk-only lookup. Prefers official art, then the wiki fallback. No
    network."""
    return _official_cached(version) or _wiki_cached(version)


def get_version_art(version: "str | None") -> "str | None":
    """Local path to the cached banner for a version, or None.

    Returns instantly if the art is cached (memory -> disk). If not, the
    download happens synchronously - callers should use fetch_async()
    from UI threads instead."""
    if not version:
        return None
    with _mem_lock:
        if version in _mem:
            hit = _mem[version]
            if hit is None or os.path.isfile(hit):
                return hit
    hit = _cache_probe(version)
    if hit:
        with _mem_lock:
            _mem[version] = hit
        return hit
    got = _fetch(version)
    with _mem_lock:
        _mem[version] = got
    return got


def fetch_async(version: "str | None", callback) -> None:
    """Fire-and-forget: download (if needed) on a daemon thread, then call
    callback(local_path_or_None) on that same thread. The callback must do
    its own page.run_task / thread_safe_ui marshalling."""
    if not version:
        return

    def _work():
        try:
            result = get_version_art(version)
        except Exception:
            result = None
        try:
            callback(result)
        except Exception:
            pass

    threading.Thread(target=_work, daemon=True,
                     name=f"cubeon-version-art-{version}").start()


def cached_path(version: "str | None") -> "str | None":
    """Disk-only path to the cached banner for a version, or None. No
    network - safe to call on the UI thread."""
    return _cache_probe(version) if version else None


def has_official(version: "str | None") -> bool:
    """True when the OFFICIAL Mojang art (not just the wiki fallback) is
    cached, so callers know nothing better can arrive. Disk-only."""
    return bool(version) and _plausible_version(version) \
        and _official_cached(version) is not None


def src(version: "str | None") -> "str | None":
    """A value `ft.Image.src` can actually load for this version's banner,
    or None when nothing is cached yet.

    Flet resolves a non-URL string against the app's assets folder and has no
    filesystem access of its own, so an absolute path under
    ~/.cubeon_launcher silently renders as a blank box. A cached banner is
    therefore fed back base64-encoded - the same trick cubeon/icons.py and the
    skin preview use. None means "not cached yet": call fetch_async()/prefetch()
    or fall back to a bundled placeholder image.

    The encoded string is cached per file (see _src_cache), so repeated renders
    - a card rebuild, or one selection change after another - are a dict lookup
    instead of a fresh read + encode of the banner.
    """
    path = cached_path(version)
    if not path:
        return None
    try:
        info = os.stat(path)
    except OSError:
        return None
    stamp = (info.st_mtime_ns, info.st_size)
    with _src_lock:
        hit = _src_cache.get(path)
        if hit is not None and hit[0] == stamp:
            _src_cache.move_to_end(path)
            return hit[1]
    try:
        with open(path, "rb") as fh:
            encoded = base64.b64encode(fh.read()).decode("ascii")
    except OSError:
        return None
    with _src_lock:
        _src_cache[path] = (stamp, encoded)
        _src_cache.move_to_end(path)
        while len(_src_cache) > _SRC_CACHE_MAX:
            _src_cache.popitem(last=False)
    return encoded


def prefetch(version: "str | None", on_ready=None) -> None:
    """Ensure a version's art is cached, then hand `on_ready` an
    `ft.Image.src`-safe value (base64 or None).

    If the OFFICIAL art is already cached, on_ready fires immediately on the
    calling thread. Otherwise the work runs on a daemon thread and on_ready
    fires there, so the callback must marshal its own UI update
    (thread_safe_ui) - this keeps the feed fetch and downloads off the UI
    thread. Never raises; a failed download simply reports whatever is cached
    (or None). Safe to call on every render."""
    if not version:
        return
    if _official_cached(version):
        if on_ready:
            try:
                on_ready(src(version))
            except Exception:
                pass
        return
    if not _plausible_version(version):
        if on_ready:
            try:
                on_ready(None)
            except Exception:
                pass
        return

    def _done(_path):
        if on_ready:
            try:
                on_ready(src(version))
            except Exception:
                pass

    fetch_async(version, _done)
