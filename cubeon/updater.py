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

# Lazy: `requests` costs ~97ms to import and every module that pulls it in
# eagerly puts that on the startup path, even for a session that never
# touches the network. Call sites are unchanged - see cubeon/lazy.py.
from .lazy import LazyModule
requests = LazyModule("requests")

log = logging.getLogger(__name__)

# Bump this with every release. The release feed's tag must match the same
# scheme ("v1.2.3") or the comparison can't work.
APP_VERSION = "1.2.11"

# Override with CUBEON_UPDATE_FEED for staging/testing; the default points at
# the project's GitHub releases. An unreachable feed must never bother the
# user - this is a hint service, not a dependency.
DEFAULT_FEED = "https://api.github.com/repos/Shadow-457/Cubeon/releases/latest"

# Where "there is a newer version" SENDS people. Our own download page, never
# the release's own html_url: this repo is private, so a visitor without an
# account (or without access) gets an auth wall or a 404 from
# github.com/<repo>/releases/tag/... The site is the public front door, it is
# what the site text and the download worker agree on, and it picks the right
# file for the visitor's OS. Override with CUBEON_DOWNLOAD_URL for staging.
DOWNLOAD_URL = "https://cubeon.ylet.online/download"

# Where the "we already told the user about version X" marker lives, in the
# launcher's config. Read it through should_announce() rather than by hand.
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


def check_for_updates(timeout: float = 8.0, feed_url: str | None = None,
                      token: str | None = None,
                      download_url: str | None = None) -> dict | None:
    """{'version', 'url', 'notes'} when a newer release exists, else None.
    Network errors raise - callers running in the UI should use the
    background wrapper below instead.

    `url` is always our public download page (DOWNLOAD_URL) and never the
    release's own `html_url`: release pages on this private repo are an auth
    wall for everyone without access, so sending users there is a dead end.

    PRIVATE repos: the releases API needs a token. Pass one (fine-grained,
    'Contents: read-only' is enough) via the token arg, the
    CUBEON_UPDATE_TOKEN env var, or config["update_token"]. Be aware the
    token ships inside the launcher build, so anyone who extracts it can
    read the private repo - fine for personal builds, not for wide
    distribution."""
    feed = feed_url or os.environ.get("CUBEON_UPDATE_FEED") or DEFAULT_FEED
    page = download_url or os.environ.get("CUBEON_DOWNLOAD_URL") or DOWNLOAD_URL
    tok = token or os.environ.get("CUBEON_UPDATE_TOKEN")
    headers = {"Accept": "application/vnd.github+json"}
    if tok:
        headers["Authorization"] = f"Bearer {tok}"
    resp = requests.get(feed, timeout=timeout, headers=headers)
    resp.raise_for_status()
    data = resp.json()
    tag = data.get("tag_name") or ""
    if is_newer(tag):
        return {"version": tag.lstrip("v"),
                "url": page,
                "notes": (data.get("body") or "")[:400]}
    return None


def check_in_background(on_update, feed_url: str | None = None,
                        token: str | None = None,
                        download_url: str | None = None) -> threading.Thread:
    """Run the check off the UI thread; on_update(dict) fires only on a
    POSITIVE result. Everything else - no update, no network, bad feed -
    stays in the log where it belongs."""
    def run():
        try:
            info = check_for_updates(feed_url=feed_url, token=token,
                                     download_url=download_url)
            if info:
                on_update(info)
            else:
                log.info("update check: up to date (v%s)", APP_VERSION)
        except Exception as ex:  # noqa: BLE001 - never surface, just log
            log.info("update check skipped: %s", ex.__class__.__name__)

    t = threading.Thread(target=run, name="cubeon-update-check", daemon=True)
    t.start()
    return t
