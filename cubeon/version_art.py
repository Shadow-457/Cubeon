"""Official per-version artwork for the launcher UI.

Every Minecraft release has a banner image on its official wiki page
(e.g. https://minecraft.wiki/w/Java_Edition_1.21.4 shows the "Garden
Awakens" banner). Those banners are the closest thing to "official"
version artwork that exists, so the new-UI template uses them to give
each version a visual identity instead of a bare text id.

This module maps a version id ("1.21.4", "1.20.1", snapshot ids) to a
local image file, downloading from the wiki on first use and caching
under CACHE_DIR/version_art/ forever (banners never change for a
released version). All lookups happen on background threads; the UI
never blocks on this.

Lookup order for a version:
1. "<id>_banner.jpg" - the standard banner most version pages have
   (verified live: 1.15.2 .. 1.21.11, snapshots like 25w14craftmine).
2. The page's own lead image via the MediaWiki API (pageimages prop) -
   covers old versions whose pages predate the banner convention
   (1.9/1.12/1.18 use "Java_Edition_<v>.png", 1.16 uses an unofficial
   banner; a 404 on shape 1 does NOT mean no art exists).
"""
import json
import os
import re
import threading

from .net import get_with_retry
from .paths import CACHE_DIR, user_agent

ART_DIR = os.path.join(CACHE_DIR, "version_art")

_HEADERS = {
    "User-Agent": user_agent("version artwork fetch"),
    "Referer": "https://minecraft.wiki/",
}

_mem: dict[str, "str | None"] = {}
_mem_lock = threading.Lock()


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


def _fetch(version: str) -> "str | None":
    """Try the banner URL shape, then the page's lead image. Returns the
    local cache path or None; caches the miss in memory only (a version
    whose page gains art later still gets another chance next launch)."""
    os.makedirs(ART_DIR, exist_ok=True)
    enc = re.sub(r"[^A-Za-z0-9._-]", "_", version)
    candidates = [f"{enc}_banner.jpg"]
    lead = _page_lead_image(enc)
    if lead:
        candidates.append(lead)
    for file_name in candidates:
        url = _wiki_url(file_name)
        try:
            resp = get_with_retry(url, headers=_HEADERS, timeout=20)
        except Exception:
            continue
        try:
            data = resp.content
        finally:
            resp.close()
        # Banners are ~100-500KB; anything tinier is an error page. Accept
        # JPEG or PNG lead images.
        is_jpeg = data[:3] == b"\xff\xd8\xff"
        is_png = data[:8] == b"\x89PNG\r\n\x1a\n"
        if len(data) > 4096 and (is_jpeg or is_png):
            ext = ".png" if is_png else ".jpg"
            dest = os.path.join(ART_DIR, f"{enc}{ext}")
            tmp = dest + ".tmp"
            with open(tmp, "wb") as fh:
                fh.write(data)
            os.replace(tmp, dest)
            return dest
    return None


def _cache_probe(version: str) -> "str | None":
    """Disk-only lookup for both extensions. No network."""
    enc = re.sub(r"[^A-Za-z0-9._-]", "_", version)
    for ext in (".jpg", ".png"):
        path = os.path.join(ART_DIR, f"{enc}{ext}")
        if os.path.isfile(path):
            return path
    return None


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
