"""
Update check: does the installed launcher have a newer release available?

Cubeon ships as a static bundle (AppImage / EXE), so "update" here means
TELLING the user a new version exists and opening the download page - not
self-replacing binaries, which needs per-platform installers and signing
infrastructure Cubeon doesn't have yet. The check is one cheap GET against
the GitHub releases API, runs on a background thread at startup, and every
failure mode is silent-ish (logged, never a dialog): a launcher that can't
reach GitHub must still launch.
"""
import logging
import os
import re
import threading

import requests

log = logging.getLogger(__name__)

# Bump this with every release. The release feed's tag must match the same
# scheme ("v1.2.3") or the comparison can't work.
APP_VERSION = "1.0.0"

# Override with CUBEON_UPDATE_FEED for staging/testing; the default points at
# the project's GitHub releases. An unreachable feed must never bother the
# user - this is a hint service, not a dependency.
DEFAULT_FEED = "https://api.github.com/repos/Shadow-457/Cubeon/releases/latest"

_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _parse(tag: str):
    m = _TAG_RE.match((tag or "").strip())
    return tuple(int(g) for g in m.groups()) if m else None


def is_newer(remote_tag: str, local: str = APP_VERSION) -> bool:
    """True when remote_tag is strictly newer than local. Unparseable tags
    (rc suffixes, hashes) compare as 'not newer' - never nag on ambiguity."""
    remote, local_v = _parse(remote_tag), _parse(local)
    return bool(remote and local_v and remote > local_v)


def check_for_updates(timeout: float = 8.0, feed_url: str | None = None,
                      token: str | None = None) -> dict | None:
    """{'version', 'url', 'notes'} when a newer release exists, else None.
    Network errors raise - callers running in the UI should use the
    background wrapper below instead.

    PRIVATE repos: the releases API needs a token. Pass one (fine-grained,
    'Contents: read-only' is enough) via the token arg, the
    CUBEON_UPDATE_TOKEN env var, or config["update_token"]. Be aware the
    token ships inside the launcher build, so anyone who extracts it can
    read the private repo - fine for personal builds, not for wide
    distribution."""
    feed = feed_url or os.environ.get("CUBEON_UPDATE_FEED") or DEFAULT_FEED
    tok = token or os.environ.get("CUBEON_UPDATE_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    resp = requests.get(feed, timeout=timeout, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    tag, url = data.get("tag_name") or "", data.get("html_url") or feed
    if is_newer(tag):
        return {"version": tag.lstrip("v"),
                "url": url,
                "notes": (data.get("body") or "")[:400]}
    return None


def check_in_background(on_update, feed_url: str | None = None,
                        token: str | None = None) -> threading.Thread:
    """Run the check off the UI thread; on_update(dict) fires only on a
    POSITIVE result. Everything else - no update, no network, bad feed -
    stays in the log where it belongs."""
    def run():
        try:
            info = check_for_updates(feed_url=feed_url, token=token)
            if info:
                on_update(info)
            else:
                log.info("update check: up to date (v%s)", APP_VERSION)
        except Exception as ex:  # noqa: BLE001 - never surface, just log
            log.info("update check skipped: %s", ex.__class__.__name__)

    t = threading.Thread(target=run, name="cubeon-update-check", daemon=True)
    t.start()
    return t
