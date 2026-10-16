"""
Owner notifications - the launcher side (Phase 6, 2026-10-16).

One-off broadcasts the owner publishes from the command line (``python
notify``) and every running launcher shows ONCE, styled like the seasonal
greeting. The transport is the EXISTING cubeon-downloads Cloudflare Worker
(``worker/cubeon-downloads.js``): the owner POSTs with a secret token, the
launcher GETs the latest entry back.

Design notes:

* The fetch is ALWAYS off the UI thread. ``tools/test_startup.py`` asserts that
  startup opens no socket on the main thread, and a notification is never worth
  a slower window.
* Everything is best-effort. No entry, no KV binding, a dead network, a
  malformed body - every one of them is "show nothing", never an exception
  escaping into the caller's startup path.
* The seen marker is the entry's ``ts``, kept in the config as
  ``notify_seen_ts``: a newer publish always shows again, and re-showing the
  same one never happens.
* Nothing here ever sends anything: the launcher only reads.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import urllib.request

import flet as ft

from cubeon import dialogs as _dialogs
from cubeon.theme import (
    ACCENT, SURFACE_MAX, TEXT, TEXT_DIM, FONT_DISPLAY,
)

log = logging.getLogger(__name__)

# The public download/uninstall Worker - no secret, no VPS, already deployed
# for the installers (see worker/wrangler-downloads.toml).
DEFAULT_ENDPOINT = "https://cubeon-downloads.hamza-457-shahbaz.workers.dev/notify"

# config.json key: the `ts` of the last entry this install displayed.
SEEN_KEY = "notify_seen_ts"

_MAX_BODY = 4096


def endpoint() -> str:
    """The /notify URL, overridable for testing and for a self-hosted Worker."""
    return (os.environ.get("CUBEON_NOTIFY_ENDPOINT") or "").strip() or DEFAULT_ENDPOINT


def fetch_latest(url: str | None = None, timeout: float = 4.0,
                 opener=None) -> dict | None:
    """The latest published entry, or None.

    Never raises: an offline box, a 204 (nothing published), a 501 (KV not
    bound yet), an HTML error page or a truncated body all mean "nothing to
    show". ``opener`` is injectable so the tests need no socket.
    """
    url = url or endpoint()
    open_fn = opener or urllib.request.urlopen
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "cubeon-launcher"})
        with open_fn(req, timeout=timeout) as resp:
            if getattr(resp, "status", 200) != 200:
                return None
            raw = resp.read(_MAX_BODY)
        data = json.loads(raw.decode("utf-8", "replace"))
    except Exception:
        log.debug("notify fetch failed", exc_info=True)
        return None
    return normalise(data)


def normalise(data) -> dict | None:
    """A stored entry as a plain dict, or None when it is not usable.

    The Worker validates on the way in, but the launcher must not trust a
    response it did not write: `ts` has to be a number (it is the seen marker)
    and both text fields have to be non-empty strings.
    """
    if not isinstance(data, dict):
        return None
    headline = data.get("headline")
    content = data.get("content")
    ts = data.get("ts")
    if not isinstance(headline, str) or not headline.strip():
        return None
    if not isinstance(content, str) or not content.strip():
        return None
    if not isinstance(ts, (int, float)) or isinstance(ts, bool):
        return None
    entry = {
        "headline": headline.strip(),
        "content": content.strip(),
        "ts": float(ts),
        "url": None,
    }
    url = data.get("url")
    if isinstance(url, str) and url.startswith(("http://", "https://")):
        entry["url"] = url
    return entry


def should_show(entry: dict | None, seen_ts) -> bool:
    """True when `entry` is newer than the marker this install last showed."""
    if not entry:
        return False
    try:
        return float(entry["ts"]) > float(seen_ts or 0)
    except (TypeError, ValueError, KeyError):
        return False


def build_dialog(entry: dict, *, on_open=None, on_dismiss=None) -> ft.AlertDialog:
    """The popup, in the seasonal-greeting style (non-modal informative card).

    Deliberately NON-modal and closable two ways, like the seasonal greeting:
    an announcement must never trap anyone.
    """
    actions = []
    if entry.get("url") and on_open is not None:
        actions.append(ft.TextButton(
            "Open", on_click=on_open, style=ft.ButtonStyle(color=ACCENT)))
    actions.append(ft.TextButton(
        "Got it", on_click=on_dismiss, style=ft.ButtonStyle(color=TEXT_DIM)))
    return ft.AlertDialog(
        title=ft.Row(
            [
                ft.Text(entry["headline"], color=TEXT,
                        font_family=FONT_DISPLAY, size=20),
            ],
            spacing=12,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        content=ft.Container(
            content=ft.Text(entry["content"], size=13, color=TEXT_DIM),
            width=380,
        ),
        actions=actions,
        actions_alignment=ft.MainAxisAlignment.END,
    )


def poll_async(page, cfg, *, save_config=None, url: str | None = None,
               thread_factory=threading.Thread, opener=None) -> threading.Thread | None:
    """Fetch the latest notification off-thread and show it once.

    Returns the worker thread (useful for tests) or None when the harness has
    no threading. Every step is guarded: a notification must never be able to
    break startup.
    """
    def _work():
        try:
            entry = fetch_latest(url, opener=opener)
        except Exception:  # fetch_latest swallows its own; this is belt-and-braces
            return
        if not should_show(entry, cfg.get(SEEN_KEY)):
            return

        def _dismiss(e=None):
            try:
                _dialogs.close_dialog(page, dlg)
            except Exception:
                pass

        open_url = None
        if entry.get("url"):
            def open_url(e=None):
                try:
                    page.launch_url(entry["url"])
                except Exception:
                    log.debug("notify url could not open", exc_info=True)
                _dismiss()

        try:
            dlg = build_dialog(entry, on_open=open_url, on_dismiss=_dismiss)
        except Exception:
            return

        def _mark_seen():
            # Recorded the moment the popup actually reaches the screen, not on
            # dismiss: someone who quits the launcher without pressing "Got it"
            # must not be greeted by the same announcement on every start.
            cfg[SEEN_KEY] = entry["ts"]
            if save_config is not None:
                try:
                    save_config(cfg)
                except Exception:
                    log.debug("notify seen-marker save failed", exc_info=True)

        def _open_and_mark():
            try:
                _dialogs.open_dialog(page, dlg)
            except Exception:
                log.debug("notify dialog could not open", exc_info=True)
                return
            _mark_seen()

        # Prefer hopping onto the page's own loop. `page.run_task` is the
        # documented way to schedule work ON the loop from another thread;
        # thread_safe_ui also makes the plain path safe, so fall back to it.
        run_task = getattr(page, "run_task", None)
        if callable(run_task):
            async def _open():
                _open_and_mark()

            try:
                run_task(_open)
                return
            except Exception:
                log.debug("notify run_task failed; showing inline", exc_info=True)
        _open_and_mark()

    try:
        worker = thread_factory(target=_work, name="cubeon-notify", daemon=True)
        worker.start()
        return worker
    except Exception:
        log.debug("notify thread could not start", exc_info=True)
        return None
