"""
Update check: does the installed launcher have a newer release available?

Startup fetches release metadata only. The download Worker keeps repository
credentials on the server; update files are fetched only after Update is
clicked. An offline or failed check must never stop the launcher opening.
"""
import logging
import os
import re
import threading

# Lazy: `requests` costs ~97ms to import and every module that pulls it in
# eagerly puts that on the startup path, even for a session that never
# touches the network. Call sites are unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
requests = LazyModule("requests")

log = logging.getLogger(__name__)

# Bump this with every release. The release feed's tag must match the same
# scheme ("v1.2.3") or the comparison can't work.
APP_VERSION = "1.3.29"

# Override with CUBEON_UPDATE_FEED for staging/testing. The public Worker
# resolves GitHub releases without distributing repository credentials.
#
# STABLE vs BETA (2026-10-24): `/releases/latest` is GitHub's own definition of
# stable - it never returns a draft or a prerelease - so the default feed needs
# no filtering. The beta channel asks for the full list and picks the highest
# tag itself, prereleases included. A release is beta when its patch is not
# zero (1.3.1, 1.3.2 ...), unless explicitly promoted; a stable is normally a
# minor bump (1.3.0, 1.4.0). tools/release_version.py owns that build policy;
# clients follow GitHub's prerelease flag, including promoted releases.
UPDATE_SERVICE = "https://cubeon-downloads.hamza-457-shahbaz.workers.dev"
DEFAULT_FEED = UPDATE_SERVICE + "/updates/stable"
DEFAULT_BETA_FEED = UPDATE_SERVICE + "/updates/beta"

# Where "there is a newer version" SENDS people. Our own download page, never
# the release's own html_url: this repo is private, so a visitor without an
# account (or without access) gets an auth wall or a 404 from
# github.com/<repo>/releases/tag/... The site is the public front door, it is
# what the site text and the download worker agree on, and it picks the right
# file for the visitor's OS. Override with CUBEON_DOWNLOAD_URL for staging.
DOWNLOAD_URL = "https://www.ylet.online/download"

# OS notifications remain once per version. The startup Skip / Update prompt
# is independent of this marker and can appear again on the next launch.
#
# WHY IT EXISTS (2026-10-18 report: "the notification of new cubeon release is
# just spamming ... coming up again and again"): the in-app snackbar had NO
# memory at all, so an available update was announced on every single start of
# the launcher, forever, until the user updated. One announcement per version,
# whatever the channel: the marker is written when the notice is handed to the
# UI, not when it is seen.
NOTICE_SEEN_KEY = "update_notice_seen"

_TAG_RE = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)$")


def _parse(tag: str):
    m = _TAG_RE.match((tag or "").strip())
    return tuple(int(g) for g in m.groups()) if m else None


def is_newer(remote_tag: str, local: str = APP_VERSION) -> bool:
    """True when remote_tag is strictly newer than local. Unparseable tags
    (rc suffixes, hashes) compare as 'not newer' - never nag on ambiguity."""
    remote, local_v = _parse(remote_tag), _parse(local)
    return bool(remote and local_v and remote > local_v)


def should_announce(cfg: dict, version: str) -> bool:
    """True the FIRST time this version is announced to this config - and the
    call MARKS it announced, so the caller must actually go on to announce it.

    The marker has to live in the config (not in memory): the whole complaint
    is about the message coming back on the NEXT start. `cfg[NOTICE_SEEN_KEY]`
    is set in place and the caller saves it (main.py already owns the config
    writer); a caller that forgets to save just gets one extra notice, never a
    crash and never a silent loss of this one.

    Total function by construction - a notice must not be able to raise:
      * a blank/absent version is "nothing to announce" (and marks nothing);
      * an unreadable config (not a dict, odd .get) still returns True, because
        a missed notice is worse than a repeated one and the alternative is an
        exception on the startup path.
    """
    v = str(version or "").strip()
    # The feed hands us `tag.lstrip("v")` already; normalising here too means a
    # caller that passes the raw tag ("v1.2.7") still matches a stored "1.2.7"
    # instead of re-announcing the same release.
    if v[:1] in ("v", "V"):
        v = v[1:].strip()
    if not v:
        return False
    try:
        if str(cfg.get(NOTICE_SEEN_KEY) or "") == v:
            return False
        cfg[NOTICE_SEEN_KEY] = v
        return True
    except Exception:
        log.debug("could not record the announced update", exc_info=True)
        return True


def _newest_release(payload, channel="beta"):
    """The newest non-draft release from a `/releases` LIST.

    A dict is returned as-is: staging feeds (and CUBEON_UPDATE_FEED) may answer
    with a single release object, and the beta channel must still work against
    one. Numeric per-segment ordering, so 1.3.10 beats 1.3.9.
    """
    if isinstance(payload, dict):
        payload = [payload]
    if not isinstance(payload, list):
        return {}
    best, best_version = {}, None
    for release in payload:
        if (not isinstance(release, dict) or release.get("draft")
                or (channel != "beta" and release.get("prerelease"))):
            continue
        version = _parse(release.get("tag_name") or "")
        if version is not None and (best_version is None or version > best_version):
            best, best_version = release, version
    return best


def check_for_updates(timeout: float = 8.0, feed_url: str | None = None,
                      token: str | None = None,
                      download_url: str | None = None,
                      channel: str = "stable") -> dict | None:
    """Release metadata when newer, otherwise None. Downloads require a click.

    Explicit feed overrides can still use GitHub-shaped release objects.
    Credentials are sent only to api.github.com, never to the public Worker.
    """
    beta = str(channel or "stable").strip().lower() == "beta"
    if beta:
        feed = (feed_url or os.environ.get("CUBEON_UPDATE_BETA_FEED")
                or os.environ.get("CUBEON_UPDATE_FEED") or DEFAULT_BETA_FEED)
    else:
        feed = feed_url or os.environ.get("CUBEON_UPDATE_FEED") or DEFAULT_FEED
    page = download_url or os.environ.get("CUBEON_DOWNLOAD_URL") or DOWNLOAD_URL
    tok = token or os.environ.get("CUBEON_UPDATE_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    from urllib.parse import urlparse
    if tok and urlparse(feed).hostname == "api.github.com":
        headers["Authorization"] = f"Bearer {tok}"
    resp = requests.get(feed, timeout=timeout, headers=headers)
    resp.raise_for_status()
    data = _newest_release(resp.json(), "beta" if beta else "stable")
    tag = data.get("tag_name") or ""
    if is_newer(tag):
        return {"version": tag.lstrip("v"),
                "url": page,
                "notes": (data.get("body") or "")[:400],
                "channel": "beta" if beta else "stable",
                "assets": data.get("assets") if isinstance(data.get("assets"), dict) else {}}
    return None


def check_in_background(on_update, feed_url: str | None = None,
                        token: str | None = None,
                        download_url: str | None = None,
                        channel: str = "stable") -> threading.Thread:
    """Run the check off the UI thread; on_update(dict) fires only on a
    POSITIVE result. Everything else - no update, no network, bad feed -
    stays in the log where it belongs."""
    def run():
        try:
            info = check_for_updates(feed_url=feed_url, token=token,
                                     download_url=download_url,
                                     channel=channel)
            if info:
                on_update(info)
            else:
                log.info("update check: up to date (v%s, %s)",
                         APP_VERSION, channel)
        except Exception as ex:  # noqa: BLE001 - never surface, just log
            log.info("update check skipped: %s", ex.__class__.__name__)

    t = threading.Thread(target=run, name="cubeon-update-check", daemon=True)
    t.start()
    return t
