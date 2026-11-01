"""Top-right slide-in notifications (toasts).

Every notification in the launcher already goes through
``cubeon.dialogs.show_snack(page, msg, duration=..., action=..., action_label=...)``,
which drew a Flet SnackBar along the bottom edge. ``install(page)`` swaps that
one function for the toast below, so *every* caller (main.py, mods_tab,
server_tab, ...) gets the new look with no further edits.

Behaviour
  * Slides in from the right edge under the top bar, fades out the same way.
  * Up to 4 stacked at once; the oldest is dropped if a fifth arrives.
  * The same message is never shown twice at the same time.
  * Accent stripe + icon by kind: error / success / info (picked from the text).
  * Optional action button (``action`` is a callable taking the click event) and
    a close button. ``duration`` is in milliseconds; 0 or less means "stay until
    dismissed".
  * Thread-safe: callable from any worker thread, never raises.
"""
import logging
import threading
import time
import weakref

import flet as ft

from cubeon import dialogs as cubeon_dialogs
from cubeon import thread_safe_ui
from cubeon.theme import (
    ACCENT, CARD_BORDER, DANGER, INFO, SURFACE_HI, TEXT, TEXT_DIM,
)

log = logging.getLogger(__name__)

TOAST_W = 340
TOP_OFFSET = 64        # clears the top bar (nav + account/settings icons)
RIGHT_OFFSET = 18
MAX_VISIBLE = 4
SLIDE_MS = 280
OFFSCREEN = ft.Offset(1.2, 0)

_ERROR_WORDS = ("failed", "couldn't", "could not", "can't", "cannot", "error",
                "rejected", "isn't available", "no matching", "unavailable",
                "not found", "crash")
_OK_WORDS = ("fixed", "installed", "ready", "saved", "done", "connected",
             "copied", "restored", "no problems")

_hosts = weakref.WeakValueDictionary()
_active: dict = {}  # (page identity, text) -> dismissal Event
_lock = threading.Lock()


def _kind(text):
    low = (text or "").lower()
    if any(word in low for word in _ERROR_WORDS):
        return "error"
    if any(word in low for word in _OK_WORDS):
        return "ok"
    return "info"


def _ensure_host(page):
    with thread_safe_ui.TREE_LOCK:
        host = _hosts.get(id(page))
        if host is None:
            column = ft.Column([], spacing=10, tight=True,
                               horizontal_alignment=ft.CrossAxisAlignment.END)
            host = ft.Container(content=column, top=TOP_OFFSET, right=RIGHT_OFFSET,
                                width=TOAST_W, data="toast-host")
            _hosts[id(page)] = host
        if page.overlay and page.overlay[-1] is host:
            return host
        if host in page.overlay:
            page.overlay.remove(host)
        page.overlay.append(host)
        # A new host is unattached: updating it cannot mount it. Patch its
        # overlay parent, also keeping notices above later launcher panels.
        overlay = getattr(page, "_overlay", None)
        if overlay is not None:
            thread_safe_ui.refresh(overlay)
        else:
            page.update()
    return host


def _build(text, action, action_label, dismissed):
    kind = _kind(text)
    color = {"error": DANGER, "ok": ACCENT, "info": INFO}[kind]
    icon = {"error": ft.Icons.ERROR_OUTLINE_ROUNDED,
            "ok": ft.Icons.CHECK_CIRCLE_OUTLINE_ROUNDED,
            "info": ft.Icons.INFO_OUTLINE_ROUNDED}[kind]

    def _close(_e=None):
        dismissed.set()

    def _act(e):
        dismissed.set()
        try:
            action(e)
        except Exception:
            log.warning("toast action failed", exc_info=True)

    body = [ft.Text(str(text), size=13, color=TEXT, max_lines=5,
                    overflow=ft.TextOverflow.ELLIPSIS, selectable=False)]
    if action and action_label:
        body.append(ft.Container(
            content=ft.Text(str(action_label), size=12.5, color=color,
                            weight=ft.FontWeight.W_700),
            padding=ft.padding.Padding.only(top=6),
            on_click=_act, ink=False, data="toast-action"))

    card = ft.Container(
        content=ft.Row(
            [
                ft.Container(width=4, bgcolor=color,
                             border_radius=ft.BorderRadius(8, 0, 8, 0)),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(icon, size=18, color=color),
                            ft.Column(body, spacing=0, tight=True, expand=True),
                            ft.Container(
                                content=ft.Icon(ft.Icons.CLOSE_ROUNDED, size=15,
                                                color=TEXT_DIM),
                                on_click=_close, ink=False, padding=2,
                                tooltip="Dismiss", data="toast-close"),
                        ],
                        spacing=10, vertical_alignment=ft.CrossAxisAlignment.START,
                    ),
                    padding=ft.padding.Padding.only(left=12, right=10, top=11, bottom=11),
                    expand=True,
                ),
            ],
            spacing=0, vertical_alignment=ft.CrossAxisAlignment.STRETCH,
            # The host Column gives children unbounded vertical space. Measure
            # the body first so STRETCH can size the accent stripe finitely.
            intrinsic_height=True,
        ),
        width=TOAST_W,
        bgcolor=SURFACE_HI,
        border=ft.border.Border.all(1, CARD_BORDER),
        border_radius=10,
        clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        shadow=ft.BoxShadow(blur_radius=18, color=ft.Colors.with_opacity(0.45, "#000000"),
                            offset=ft.Offset(0, 6)),
    )
    # The outer wrapper is what slides: mounted OFF to the right and invisible,
    # then moved to rest one frame later so the animation actually plays.
    return ft.Container(
        content=card, offset=OFFSCREEN, opacity=0,
        animate_offset=ft.Animation(SLIDE_MS, ft.AnimationCurve.EASE_OUT_CUBIC),
        animate_opacity=ft.Animation(SLIDE_MS, ft.AnimationCurve.EASE_OUT_CUBIC),
    )


def _life(host, wrap, key, duration):
    column = host.content
    dismissed = wrap.data
    try:
        with thread_safe_ui.TREE_LOCK:
            if dismissed.is_set():
                return
            column.controls.append(wrap)
            while len(column.controls) > MAX_VISIBLE:
                column.controls.pop(0).data.set()
        thread_safe_ui.refresh(column)
        time.sleep(0.04)
        with thread_safe_ui.TREE_LOCK:
            if not dismissed.is_set():
                wrap.offset = ft.Offset(0, 0)
                wrap.opacity = 1
        thread_safe_ui.refresh(wrap)

        dismissed.wait(timeout=(duration / 1000.0) if duration and duration > 0 else None)

        with thread_safe_ui.TREE_LOCK:
            wrap.offset = OFFSCREEN
            wrap.opacity = 0
        thread_safe_ui.refresh(wrap)
        time.sleep(SLIDE_MS / 1000.0 + 0.05)
        with thread_safe_ui.TREE_LOCK:
            if wrap in column.controls:
                column.controls.remove(wrap)
        thread_safe_ui.refresh(column)
    except Exception:
        log.warning("toast lifecycle error", exc_info=True)
    finally:
        with _lock:
            if _active.get(key) is dismissed:
                _active.pop(key, None)


def show(page, message, duration=4000, action=None, action_label=None,
         bgcolor=None, text_color=None, **_ignored):
    """Drop-in replacement for ``cubeon.dialogs.show_snack`` (extra styling
    arguments are accepted and ignored - the toast has its own look)."""
    key = None
    dismissed = threading.Event()
    try:
        text = str(message)
        key = (id(page), text)
        with _lock:
            if key in _active:
                return
            _active[key] = dismissed
        host = _ensure_host(page)
        wrap = _build(text, action, action_label, dismissed)
        wrap.data = dismissed
        threading.Thread(target=_life, args=(host, wrap, key, duration),
                         daemon=True, name="ux-toast").start()
    except Exception:
        with _lock:
            if _active.get(key) is dismissed:
                _active.pop(key, None)
        log.warning("toast failed", exc_info=True)


def install(page):
    """Route every ``dialogs.show_snack`` call through the toast."""
    _ensure_host(page)
    cubeon_dialogs.show_snack = show


def uninstall(page):
    """Release persistent notices when the window session ends."""
    with thread_safe_ui.TREE_LOCK:
        host = _hosts.pop(id(page), None)
        if host is not None and host in page.overlay:
            page.overlay.remove(host)
    with _lock:
        for key, dismissed in list(_active.items()):
            if key[0] == id(page):
                dismissed.set()
                _active.pop(key, None)
