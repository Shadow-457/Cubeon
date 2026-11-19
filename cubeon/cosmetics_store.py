"""Public Neon-backed cape downloads through Cubeon's server API.

The launcher has no Neon credential. Downloads use the existing cape importer;
selection remains explicit in the Cape library. No startup polling or fetching.
"""
from __future__ import annotations

import base64
import hashlib
import io
import os
from pathlib import Path
import re
import tempfile
import threading
from urllib.parse import urlencode, urlsplit

from PIL import Image

from . import capes, net, cosmetic_packages
from .paths import user_agent

DEFAULT_API = "https://www.ylet.online/api/cosmetics"
PAGE_SIZE = 12
MAX_FILE_BYTES = 2 * 1024 * 1024
_IMPORT_LOCK = threading.Lock()
_ID = re.compile(r"[a-z][a-z0-9_-]{2,63}")
_SHA = re.compile(r"[a-f0-9]{64}")


def api_url():
    url = os.environ.get("CUBEON_COSMETICS_API", DEFAULT_API).rstrip("/")
    parsed = urlsplit(url)
    local = parsed.hostname in ("localhost", "127.0.0.1", "::1")
    if (parsed.scheme != "https" and not (local and parsed.scheme == "http")) or (
            not parsed.hostname or parsed.username or parsed.password or parsed.query or parsed.fragment):
        raise ValueError("The cosmetics store address is invalid.")
    return url


def _bytes(url, limit):
    # Reuse the launcher's pooled transport and global download gate. Restrict
    # redirects to the same API origin; catalog data never supplies file URLs.
    parsed = urlsplit(url)
    def trusted(candidate):
        other = urlsplit(candidate)
        return (other.scheme, other.netloc, other.path) == (parsed.scheme, parsed.netloc, parsed.path)
    with net.DOWNLOAD_GATE:
        with net.get_with_retry(url, headers={"User-Agent": user_agent("cosmetics store")},
                                timeout=15, attempts=1, url_validator=trusted) as response:
            size = response.headers.get("Content-Length")
            if size and (not size.isdigit() or int(size) > limit):
                raise ValueError("The store returned an oversized download.")
            parts, total = [], 0
            for chunk in response.iter_content(65536):
                total += len(chunk)
                if total > limit:
                    raise ValueError("The store returned an oversized download.")
                parts.append(chunk)
            return b"".join(parts)


def _entry(raw):
    if not isinstance(raw, dict):
        raise ValueError("The store returned an invalid cosmetic.")
    item = dict(raw)
    if (not isinstance(item.get("id"), str) or not _ID.fullmatch(item["id"]) or
            item.get("kind") not in ("cape", "pet", "wing") or not isinstance(item.get("sha256"), str) or
            not _SHA.fullmatch(item["sha256"]) or
            item.get("mime_type") not in (("image/png", "image/gif") if item.get("kind") == "cape" else (cosmetic_packages.MIME,)) or
            type(item.get("byte_size")) is not int or not 0 < item["byte_size"] <= MAX_FILE_BYTES or
            not isinstance(item.get("name"), str) or not 0 < len(item["name"].strip()) <= 80 or
            not isinstance(item.get("description"), str) or len(item["description"]) > 400):
        raise ValueError("The store returned an invalid cosmetic.")
    preview = item.get("preview_png")
    if not isinstance(preview, str) or not 0 < len(preview) <= 32768:
        raise ValueError("The cape preview is invalid.")
    try:
        decoded = base64.b64decode(preview, validate=True)
        with Image.open(io.BytesIO(decoded)) as image:
            if image.format != "PNG" or image.size != (80, 128):
                raise ValueError("The cape preview is invalid.")
            image.verify()
    except (OSError, ValueError) as error:
        raise ValueError("The cape preview is invalid.") from error
    return item


def fetch_page(offset=0):
    import json
    if type(offset) is not int or not 0 <= offset <= 10000:
        raise ValueError("The store page is invalid.")
    data = json.loads(_bytes(api_url() + "?" + urlencode({"offset": offset, "kind": "all"}), 450000))
    if (not isinstance(data, dict) or data.get("schema") != 1 or
            data.get("offset") != offset or data.get("page_size") != PAGE_SIZE or
            type(data.get("has_more")) is not bool or not isinstance(data.get("items"), list) or
            len(data["items"]) > PAGE_SIZE):
        raise ValueError("The store returned an invalid catalog.")
    entries = [_entry(item) for item in data["items"]]
    if len({item["id"] for item in entries}) != len(entries):
        raise ValueError("The store returned duplicate cosmetics.")
    return {**data, "items": entries}


def installed(item):
    """Find a previously imported revision; deletion permits downloading again."""
    if item.get("kind") in ("pet", "wing"):
        return cosmetic_packages.installed(item)
    for entry in capes.list_custom_capes():
        if (isinstance(entry, dict) and isinstance(entry.get("filename"), str) and
                re.fullmatch(r"[A-Za-z0-9_-]+\.png", entry["filename"]) and
                entry.get("store_id") == item["id"] and entry.get("store_sha256") == item["sha256"] and
                Path(capes.get_custom_cape_path(entry["filename"])).is_file()):
            return entry
    return None


def download(item):
    item = _entry(item)
    existing = installed(item)
    if existing:
        return existing
    url = api_url() + "?" + urlencode({"id": item["id"], "sha256": item["sha256"]})
    payload = _bytes(url, MAX_FILE_BYTES)
    if len(payload) != item["byte_size"] or hashlib.sha256(payload).hexdigest() != item["sha256"]:
        raise ValueError("The cosmetic download was incomplete or changed. Refresh the store and try again.")
    if item["kind"] != "cape":
        return cosmetic_packages.install(payload, item)
    magic = payload.startswith(b"\x89PNG\r\n\x1a\n") if item["mime_type"] == "image/png" else payload[:6] in (b"GIF87a", b"GIF89a")
    if not magic:
        raise ValueError("The downloaded file is not a cape image.")
    suffix = ".gif" if item["mime_type"] == "image/gif" else ".png"
    with tempfile.TemporaryDirectory(prefix="cubeon-store-") as temporary:
        source = Path(temporary) / ("cape" + suffix)
        source.write_bytes(payload)
        # Concurrent downloads of one revision import only once. The cape
        # importer owns atomic metadata/files and preserves GIF animation.
        with _IMPORT_LOCK:
            existing = installed(item)
            if existing:
                return existing
            return capes.add_custom_cape(str(source), item["name"], store_id=item["id"],
                                         store_sha256=item["sha256"])
