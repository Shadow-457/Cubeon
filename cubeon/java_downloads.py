"""Choose a verified JRE route using transfer samples from this connection."""
import logging
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor
from urllib.parse import quote, urlparse

from . import local_cache, net

log = logging.getLogger(__name__)
AZUL_API = "https://api.azul.com/metadata/v1/zulu/packages"
LOOKUP_TIMEOUT = (3, 5)
SAMPLE_BYTES = 128 * 1024
SAMPLE_SECONDS = 5
TRUSTED_HOSTS = {
    "github.com", "release-assets.githubusercontent.com", "objects.githubusercontent.com",
    "cdn.azul.com", "mirrors.nju.edu.cn", "mirror.nju.edu.cn",
    "mirrors.tuna.tsinghua.edu.cn",
}


def trusted_url(url):
    parsed = urlparse(url)
    return (parsed.scheme == "https" and parsed.hostname in TRUSTED_HOSTS
            and parsed.port in (None, 443) and not parsed.username and not parsed.password)


def validate_asset(asset):
    name = asset.get("name") or ""
    digest = asset.get("sha256") or ""
    if not trusted_url(asset.get("link") or "") \
            or not re.fullmatch(r"[a-fA-F0-9]{64}", digest) \
            or name != os.path.basename(name) or "\\" in name \
            or not name.endswith((".zip", ".tar.gz")):
        raise ValueError("Java source did not supply a trusted archive and SHA-256")
    size = int(asset.get("size") or 0)
    if not 0 < size <= 512 * 1024 * 1024:
        raise ValueError("Java source supplied an invalid archive size")
    return dict(asset, sha256=digest.lower(), size=size)


def _azul_asset(major, platform):
    params = dict(java_version=major, os={"mac": "macos"}.get(platform["os"], platform["os"]),
                  arch="arm" if platform["architecture"] == "aarch64" else "x86",
                  hw_bitness=64, archive_type="zip" if platform["os"] == "windows" else "tar.gz",
                  java_package_type="jre", release_status="ga", availability_types="CA",
                  javafx_bundled="false", crac_supported="false", certifications="tck",
                  latest="true", page_size=100)
    rows = net.get_json(AZUL_API + "/", params=params, timeout=LOOKUP_TIMEOUT, attempts=1)
    rows = [row for row in rows if (row.get("java_version") or (None,))[0] == major
            and "-ca-jre" in row.get("name", "") and "musl" not in row.get("name", "")]
    rows.sort(key=lambda row: row.get("java_version") or [], reverse=True)
    if not rows:
        raise ValueError("Azul has no compatible JRE")
    row = rows[0]
    identity = row.get("package_uuid") or ""
    if not re.fullmatch(r"[a-fA-F0-9-]{36}", identity):
        raise ValueError("Azul supplied an invalid package identity")
    detail = net.get_json(AZUL_API + "/" + identity + "/", timeout=LOOKUP_TIMEOUT, attempts=1)
    if detail.get("java_package_type") != "jre" or (detail.get("java_version") or (None,))[0] != major \
            or detail.get("javafx_bundled") or detail.get("crac_supported") \
            or detail.get("crs_supported") or detail.get("os") != params["os"] \
            or detail.get("arch") != params["arch"] or detail.get("hw_bitness") != 64 \
            or (platform["os"] == "linux" and detail.get("lib_c_type") != "glibc"):
        raise ValueError("Azul package does not match this system")
    return validate_asset(dict(name=detail.get("name"), link=detail.get("download_url"),
                               sha256=detail.get("sha256_hash"), size=detail.get("size"),
                               provider="Azul Zulu CDN"))


def _sample(asset):
    start = time.monotonic()
    count = 0
    prefix = b""
    try:
        response = net.get_with_retry(
            asset["link"], headers={"Range": f"bytes=0-{SAMPLE_BYTES - 1}", "Accept-Encoding": "identity"},
            timeout=(2, 2), attempts=1, url_validator=trusted_url)
        try:
            if response.status_code == 206:
                content_range = response.headers.get("Content-Range", "")
                if not content_range.startswith("bytes 0-"):
                    raise ValueError("Java sample returned an unrelated byte range")
            # read1 avoids waiting for a full chunk on a trickling connection.
            while count < SAMPLE_BYTES and time.monotonic() - start < SAMPLE_SECONDS:
                block = response.raw.read1(min(8192, SAMPLE_BYTES - count), decode_content=True)
                if not block:
                    break
                prefix = (prefix + block)[:4]
                count += len(block)
        finally:
            response.close()
        if count and prefix.startswith((b"\x1f\x8b", b"PK\x03\x04")):
            return asset["size"] * (time.monotonic() - start) / count
    except Exception as error:
        log.info("Java route sample failed for %s: %s", asset["provider"], type(error).__name__)
    return None


def candidates(major, platform, adoptium_lookup):
    """Resolve vendors in parallel, then rank routes; no location/IP lookup."""
    def lookup(provider):
        try:
            fetch = adoptium_lookup if provider == "temurin" else lambda: _azul_asset(major, platform)
            asset = local_cache.cached_call(
                "java_assets", dict(major=major, platform=platform, provider=provider),
                lambda: validate_asset(fetch()), max_age=24 * 3600, background_refresh=False)
            return validate_asset(asset)
        except Exception as error:
            log.info("Java metadata unavailable for %s: %s", provider, type(error).__name__)
            return None

    with ThreadPoolExecutor(max_workers=2) as pool:
        assets = [asset for asset in pool.map(lookup, ("temurin", "azul")) if asset]
    if not assets:
        raise RuntimeError("No verified Java download is reachable; check the connection and retry")
    temurin = next((a for a in assets if a.get("provider") == "Eclipse Temurin"), None)
    if temurin:
        suffix = f"{major}/jre/{platform['architecture']}/{platform['os']}/{quote(temurin['name'])}"
        for label, base in (("NJU mirror", "https://mirrors.nju.edu.cn/adoptium/"),
                            ("Tsinghua mirror", "https://mirrors.tuna.tsinghua.edu.cn/Adoptium/")):
            assets.append(dict(temurin, link=base + suffix, provider=label))
    if len(assets) == 1:
        return assets
    key = [(a["link"], a["sha256"]) for a in assets]
    order = local_cache.get("java_routes", key, max_age=1800)
    if order:
        return sorted(assets, key=lambda a: order.index(a["link"]) if a["link"] in order else len(order))
    with ThreadPoolExecutor(max_workers=min(4, len(assets))) as pool:
        scores = list(pool.map(_sample, assets))
    ranked = sorted(zip(assets, scores), key=lambda pair: pair[1] if pair[1] is not None else float("inf"))
    if any(score is not None for score in scores):
        local_cache.set("java_routes", key, [a["link"] for a, score in ranked])
    # Failed probes are omitted while a reachable route exists; if every probe
    # failed, retain vendor routes for a normal resumable attempt.
    return [a for a, score in ranked if score is not None] or assets[:2]


class SlowSource(net.DownloadError):
    pass


def download(assets, directory, major, progress_cb=None, status_cb=None):
    """Retain partial archives by hash; switching vendors never mixes bytes."""
    os.makedirs(directory, exist_ok=True)
    errors = []
    # One attempt per route, then one resumable retry of the last route.
    routes = list(assets) + [assets[-1]]
    for index, asset in enumerate(routes):
        archive = os.path.join(directory, asset["sha256"] + "-" + asset["name"])
        if os.path.isfile(archive):
            from .global_mod_cache import _matches_hashes
            if _matches_hashes(archive, {"sha256": asset["sha256"]}):
                return archive
            os.remove(archive)
        if status_cb:
            status_cb(f"Downloading Java {major} ({asset['size'] // (1024 * 1024)} MB) · {asset['provider']}")
        started = time.monotonic()
        partial = archive + ".part"
        initial = os.path.getsize(partial) if os.path.isfile(partial) else 0

        def progress(done, total):
            nonlocal initial
            if done < initial:
                initial = 0  # This route ignored Range and restarted the archive.
            if progress_cb:
                progress_cb(done, total or asset["size"])
            elapsed = time.monotonic() - started
            if index < len(assets) - 1 and elapsed >= 12 and done < asset["size"] \
                    and max(0, done - initial) / elapsed < 32 * 1024:
                raise SlowSource("Java source became too slow")

        try:
            net.download_to(archive, asset["link"], timeout=(4, 6), attempts=1,
                            expected_hash=("sha256", asset["sha256"]), progress_cb=progress,
                            deadline=time.monotonic() + 1800, url_validator=trusted_url)
            return archive
        except net.DownloadError as error:
            errors.append(f"{asset['provider']}: {error}")
            log.info("Java route failed: %s", errors[-1])
            if index < len(routes) - 1 and status_cb:
                status_cb(f"Trying another Java {major} download route")
    raise RuntimeError("Java download routes failed. Partial downloads are kept for retry. " + "; ".join(errors))
