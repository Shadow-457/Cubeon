"""
The Chat tab: the launcher's social surface.

Before this tab, the only friends UI was the in-game "Cubeon" mod, which talks
to the launcher over the localhost bridge. That left the launcher itself with a
realtime friends connection (FriendsService), a roster, encrypted DMs and friend
requests but no screen to use any of it. This tab is that screen, and it talks
to the same process-scoped FriendsService directly instead of going through the
HTTP bridge the mod uses.

What it shows, on one screen:
  - the automatic Cubeon ID: an 8-digit number the server assigns on first
    connect (00000001, 00000002, ...), shown so a friend can add you,
  - the friend roster with presence and each friend's ID, plus add-by-ID,
  - incoming requests (accept / decline) and outgoing ones,
  - the selected conversation, decrypted by the service, with a composer.

The chat identity is the ID, not a name: a name is only a cosmetic label and
the owning secret is never shown or asked for. friends.ensure_identity() still
mints the internal name the relay keys the friend graph on, so there is no
claim prompt and no rename here.

Design rules it follows:
  - A classic two-pane chat: a roster rail on the left, the open conversation
    on the right. Rows and messages lift on hover via `attach_hover`.
  - The Mods-tab color language: translucent fills and quiet hover, no solid
    nested panels ("box in a box"). "Mine" messages are a faint green wash,
    never a solid green slab - green stays reserved for presence/actions.
  - Bubbles hug their text (width measured from the longest line, capped to
    the pane) instead of every message being the same fixed width.
  - Sends are OPTIMISTIC (2026-09-20): the bubble appears the instant Enter
    is pressed (dim, "Sending..."), the relay's echo-filed line replaces it,
    and a refusal or 12s silence turns it red "Couldn't send" (_pending /
    _append_optimistic / _sweep_pending). A red bubble is NOT thrown away: a
    late echo takes over that exact slot, so one message can never render as
    two bubbles (the dupe the user saw when the echo missed the 12s window).
  - The poll cadence is adaptive (2026-09-23): 1.5s idle, 0.5s while a
    conversation is open, 0.25s for a couple of seconds after a send (a tick
    is ~2ms of in-process dict work) - so chat feels immediate instead of
    lagging behind a fixed slow poll.
  - Auto-scroll is opt-in per position (_stick): new messages follow only
    while the view is at the bottom, so reading history never gets yanked
    down; opening a conversation always jumps to the end. A "Newest" pill
    (_jump_row) appears while the view is scrolled up and jumps back down.
  - Composer drafts survive friend switches and tab closes within the
    session (_drafts; saved on every keystroke, restored on _select) - a
    half-typed message is never lost.
  - Bubbles are click-to-copy, and every bubble/roster stamp carries the
    full date on hover. The clock line is GROUPED: only the first bubble of
    a same-side run (or a new day) shows it.
  - The roster can be filtered by name or ID (find_field, client-side over
    the last roster snapshot - the service is never queried per keystroke).
  - All service calls run on this module's own poll thread; every control write
    is wrapped in thread_safe_ui.TREE_LOCK and repainted with
    thread_safe_ui.refresh(control), never a whole-page update.
  - Built lazily the first time the tab opens (main.py's _ensure_tab), so no
    poll thread and no roster read happens until then.
"""
import base64
from copy import deepcopy
import os
import threading
import time

import flet as ft

from cubeon.theme import (
    RADIUS, ON_ACCENT, WARNING, TEXT_FAINT, ACCENT_HI,
    CARD_FILL, CARD_BORDER, ROW_HOVER, ACCENT_TINT,
    AVATAR_COLORS, attach_hover,
)
from cubeon.config import validate_username
from cubeon import dialogs as _dialogs
from cubeon import faces as _faces
from cubeon import friends as _friends
from cubeon import profile as _profile
from cubeon import thread_safe_ui

_POLL_SECONDS = 1.5
# Faster cadences (see _poll_interval): while a conversation is open the user
# is watching the transcript, so a new message lands within half a second; for
# a few seconds after sending, faster still, so the sender's own bubble
# confirms almost immediately. A tick is pure in-process dict work (measured
# ~2ms with a 20-friend roster + 50-message ring), so this costs nothing.
_POLL_ACTIVE_SECONDS = 0.5
_POLL_FAST_SECONDS = 0.25
# How long after a send the fast cadence stays armed (a relay echo normally
# lands in well under a second; this covers the round trip + a slow tick).
_CONFIRM_WINDOW_S = 2.0
# Unconfirmed/failed bubbles are kept so a late echo can take their place -
# but only a bounded number per conversation, so a long session can't grow
# them without limit.
_MAX_PENDING = 64

# Message bubbles measure themselves from their longest line so a "hi" is a
# small chip and a paragraph wraps at a sane width, instead of every message
# being the same fixed slab. _CHAR_PX is a rough Inter-13px average advance.
_BUBBLE_MAX = 560
_BUBBLE_MIN = 88
_CHAR_PX = 6.8


def _fmt_time(ts_ms) -> str:
    """A message timestamp (server sends ms) as a short local clock time."""
    try:
        ts = int(ts_ms)
        if ts > 10_000_000_000:   # ms epoch; seconds stay below this for now
            ts //= 1000
        return time.strftime("%H:%M", time.localtime(ts))
    except (TypeError, ValueError, OSError):
        return ""


def _full_date(ts_ms) -> str:
    """A timestamp as \"Mar 3, 2026 · 14:23\" — the hover detail for bubbles
    and roster rows, where the compact clock hides the day."""
    try:
        ts = int(ts_ms)
        if ts <= 0:
            return ""
        if ts > 10_000_000_000:
            ts //= 1000
        return time.strftime("%b %d, %Y · %H:%M", time.localtime(ts))
    except (TypeError, ValueError, OSError, OverflowError):
        return ""


def _short_stamp(ts_ms) -> str:
    """Roster-row stamp: \"14:23\" for today, \"Mar 3\" for anything older —
    a conversation from last week doesn't need a clock."""
    full = _full_date(ts_ms)
    if not full:
        return ""
    today = time.strftime("%Y-%m-%d")
    try:
        ts = int(ts_ms)
        if ts > 10_000_000_000:
            ts //= 1000
        day = time.strftime("%Y-%m-%d", time.localtime(ts))
    except (TypeError, ValueError, OSError):
        return full
    return time.strftime("%H:%M", time.localtime(ts)) if day == today else full.split(" · ")[0]


def _day_key(ts_ms):
    """(calendar day string, human label) for a message timestamp.

    The day string is what the transcript groups on; the label is what a
    separator reads. Blank ts (an old/seeded message with no clock) returns
    (None, "") so it never forces a bogus "Today" separator."""
    try:
        ts = int(ts_ms)
        if ts <= 0:
            return None, ""
        if ts > 10_000_000_000:
            ts //= 1000
        lt = time.localtime(ts)
        key = time.strftime("%Y-%m-%d", lt)
        now = time.localtime()
        if key == time.strftime("%Y-%m-%d", now):
            return key, "Today"
        if key == time.strftime("%Y-%m-%d", time.localtime(
                time.mktime(now) - 86400)):
            return key, "Yesterday"
        return key, time.strftime("%B %d, %Y", lt)
    except (TypeError, ValueError, OSError, OverflowError):
        return None, ""


def build_chat_tab(page: ft.Page, cfg: dict, state: dict, service, *,
                   section_label,
                   BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                   TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO):
    """Builds the Chat tab. Returns (root_control, refresh).

    `service` is the process-scoped FriendsService, or None in a public build
    with the feature disabled - in which case the tab renders a short notice
    and does nothing (it is unreachable from the nav in that build anyway).
    `refresh` is main.py's hook when the tab opens; it reconciles once without
    waiting for the next poll tick.
    """

    # --- no-service build: a plain notice, no threads --------------------
    if service is None:
        notice = ft.Column(
            [
                ft.Text("Chat", size=28, color=TEXT, font_family=FONT_DISPLAY),
                ft.Text("Chat is disabled in this build.", size=13,
                        color=TEXT_DIM),
                ft.Text("It's only available in development builds.",
                        size=12, color=TEXT_FAINT),
            ],
            spacing=8,
            expand=True,
        )
        return notice, (lambda: None)

    # --- live model ------------------------------------------------------
    selected = {"name": None}
    last_seq = {}          # canon friend -> highest message seq seen
    cursor = {"v": -1}     # events cursor; -1 = first sync (no backlog)
    _last_roster = {"v": None}
    _roster_sig = {"v": None}
    _identity_sig = {"v": None}
    _header_sig = {"v": None}
    _last_day = {}
    _last_dir = {}
    # Optimistic sends: canon friend -> [{"text", "wrap", "ts", "t0",
    # "failed"}] for bubbles shown before the relay's echo confirms them. The
    # echo-filed message REPLACES its pending bubble in _append_messages. A
    # bubble that timed out (failed=True) stays in the list on purpose: if the
    # echo lands late the real line takes over that same slot, so one message
    # can never show up twice (a red "Couldn't send" bubble PLUS the real one).
    _pending = {}
    # Fast-confirm window: after a send, poll every _POLL_FAST_SECONDS until
    # this deadline, so the sender's own bubble confirms in a few hundred ms
    # instead of waiting out a full idle tick. Set by _do_send / _run.done.
    _fast_until = {"v": 0.0}
    # The poll loop's own wake-up: a handler that just changed something wins
    # an immediate tick instead of waiting for the next interval.
    _wake = threading.Event()
    # Composer drafts: canon friend -> composer text, kept across friend
    # switches and tab closes within the session (the tab stays mounted once
    # built; a fresh launch starts with empty drafts).
    _drafts = {}
    # Auto-scroll: True while the view sits at the bottom, so appended
    # messages follow, but reading history doesn't get yanked down.
    _stick = {"at_end": True}
    tick_lock = threading.Lock()
    stop = threading.Event()

    # --- controls --------------------------------------------------------
    you_avatar = ft.Container(width=34, height=34, border_radius=RADIUS)
    conn_dot = ft.Container(width=8, height=8, border_radius=4,
                            bgcolor=TEXT_FAINT)
    conn_text = ft.Text("", size=11, color=TEXT_DIM)

    you_text = ft.Text("", size=14, color=TEXT,
                       weight=ft.FontWeight.W_700, max_lines=1,
                       overflow=ft.TextOverflow.ELLIPSIS)
    # The 8-digit ID is the personal, un-takeable account handle - owned by the
    # secret, never renamed away. It stays small and quiet: it's what a
    # friend types to ADD you, not your display identity.
    your_id_text = ft.Text("Waiting for your ID…", size=11, color=TEXT_DIM,
                           font_family=FONT_MONO, selectable=True,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
    def _do_copy(_e=None):
        value = your_id_text.value or ""
        try:
            from flet.controls.services.clipboard import Clipboard
            page.run_task(Clipboard().set, value)
        except Exception:
            pass   # headless/older hosts have no clipboard service
        _set_status("Cubeon ID copied to clipboard.")

    copy_id_btn = ft.IconButton(
        icon=ft.Icons.CONTENT_COPY_ROUNDED, icon_size=14,
        icon_color=TEXT_DIM, tooltip="Copy your Cubeon ID",
        visible=False,
        on_click=_do_copy,
    )

    add_field = ft.TextField(
        hint_text="Add a friend by ID",
        prefix_icon=ft.Icons.PERSON_ADD_ROUNDED,
        border_color=CARD_BORDER,
        focused_border_color=ACCENT,
        color=TEXT,
        hint_style=ft.TextStyle(color=TEXT_FAINT),
        text_style=ft.TextStyle(size=13),
        bgcolor=CARD_FILL,
        border_radius=RADIUS,
        height=40,
        content_padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
        on_submit=lambda e: _do_add(),
    )

    # Client-side roster filter: narrows the Friends list by name (or ID)
    # without touching the service - every keystroke just re-renders the
    # matching rows from the last roster snapshot.
    find_field = ft.TextField(
        hint_text="Find a friend…",
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        border_color=CARD_BORDER,
        focused_border_color=ACCENT,
        color=TEXT,
        hint_style=ft.TextStyle(color=TEXT_FAINT),
        text_style=ft.TextStyle(size=13),
        bgcolor=CARD_FILL,
        border_radius=RADIUS,
        height=36,
        content_padding=ft.padding.Padding.symmetric(horizontal=10, vertical=6),
        on_change=lambda e: _rebuild_friends(_last_roster["v"] or {}),
    )

    requests_label = section_label("Requests")
    requests_col = ft.Column(spacing=6)
    friends_label = section_label("Friends")
    friends_col = ft.Column(spacing=3)

    transcript_header = ft.Text("", size=16, color=TEXT,
                                weight=ft.FontWeight.W_700, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS)
    transcript_sub = ft.Text("", size=11, color=TEXT_FAINT)
    header_avatar = ft.Container(width=36, height=36, border_radius=RADIUS,
                                 visible=False)
    remove_btn = ft.IconButton(icon=ft.Icons.PERSON_REMOVE_ROUNDED,
                               icon_size=18, icon_color=TEXT_DIM,
                               hover_color=DANGER,
                               tooltip="Remove friend", visible=False)
    # auto_scroll=False on purpose: it slams to the newest line on EVERY
    # control update, which makes reading history impossible. _stick_bottom()
    # reproduces the good half (follow new messages) only while the user is
    # already at the bottom - tracked by the on_scroll handler.
    transcript = ft.ListView(expand=True, spacing=0, auto_scroll=False,
                             on_scroll=lambda e: _on_transcript_scroll(e),
                             padding=ft.padding.Padding.symmetric(
                                 vertical=6, horizontal=2), visible=False)

    # "Jump to newest" pill: appears while the view is scrolled up and sends
    # the transcript back to the bottom with one click.
    jump_row = ft.Container(
        content=ft.Row(
            [
                ft.Container(expand=True),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.VERTICAL_ALIGN_BOTTOM_ROUNDED,
                                    size=15, color=ACCENT),
                            ft.Text("Newest", size=11, color=ACCENT,
                                    weight=ft.FontWeight.W_600),
                        ],
                        spacing=5, tight=True,
                        alignment=ft.MainAxisAlignment.CENTER,
                    ),
                    bgcolor=SURFACE_HI,
                    border=ft.border.Border.all(1, ACCENT_DIM),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=10,
                                                         vertical=6),
                    ink=False,
                    on_click=lambda e: _stick_bottom(force=True),
                ),
            ],
            tight=True,
        ),
        visible=False,
    )

    def _on_composer_change(_e=None):
        """Keep the open conversation's draft fresh while typing, so leaving
        the conversation (or the tab) never loses what was half-typed."""
        key = selected["name"]
        if not key:
            return
        value = composer.value or ""
        if value.strip():
            _drafts[key] = value
        else:
            _drafts.pop(key, None)

    composer = ft.TextField(
        hint_text="Message...",
        border_color=CARD_BORDER,
        focused_border_color=ACCENT,
        color=TEXT,
        hint_style=ft.TextStyle(color=TEXT_FAINT),
        bgcolor=CARD_FILL,
        border_radius=RADIUS,
        expand=True,
        multiline=True,
        shift_enter=True,
        min_lines=1,
        max_lines=4,
        content_padding=ft.padding.Padding.symmetric(horizontal=12, vertical=12),
        on_submit=lambda e: _do_send(),
        on_change=_on_composer_change,
    )
    send_btn = attach_hover(ft.Container(
        content=ft.Icon(ft.Icons.SEND_ROUNDED, size=18, color=ON_ACCENT),
        bgcolor=ACCENT, border_radius=RADIUS, width=44, height=44,
        alignment=ft.Alignment.CENTER, ink=False,
        on_click=lambda e: _do_send(),
    ), ACCENT, ACCENT_HI)

    # --- emoji picker -------------------------------------------------
    # A small, game-flavored set. Kept as literal text so no platform emoji
    # plugin is needed; clicking one appends it at the composer's end.
    _EMOJIS = ("😀 😂 🥹 😍 😎 🤔 😅 😢 😡 🥳 😴 🤝 👍 👎 🙏 👏 💪 🔥 💀 🎉 "
               "🎮 ⚔️ ⛏️ 🧱 💎 🌳 🐷 💥 ✅ ❌ ❓ 👀").split()

    def _insert_emoji(em):
        composer.value = (composer.value or "") + em
        thread_safe_ui.refresh(composer)

    def _toggle_emoji():
        emoji_panel.visible = not emoji_panel.visible
        thread_safe_ui.refresh(emoji_panel)

    emoji_btn = ft.IconButton(
        icon=ft.Icons.EMOJI_EMOTIONS_ROUNDED, icon_size=20,
        icon_color=TEXT_DIM, tooltip="Emoji", visible=False,
        on_click=lambda e: _toggle_emoji(),
    )
    emoji_panel = ft.Container(
        content=ft.Column(
            [ft.Row(
                [ft.Container(
                    ft.Text(em, size=18), padding=4, border_radius=RADIUS,
                    ink=False, on_click=lambda e, em=em: _insert_emoji(em),
                    tooltip=None,
                 ) for em in _EMOJIS[i:i + 8]],
                spacing=2, run_spacing=2, wrap=True,
            ) for i in range(0, len(_EMOJIS), 8)],
            spacing=0, tight=True,
        ),
        bgcolor=SURFACE_HI,
        border=ft.border.Border.all(1, CARD_BORDER),
        border_radius=RADIUS,
        padding=ft.padding.Padding.all(6),
        visible=False,
    )
    composer_status = ft.Text("", size=11, color=DANGER, max_lines=2,
                              overflow=ft.TextOverflow.ELLIPSIS, visible=False)
    composer_row = ft.Row([emoji_btn, composer, send_btn], spacing=8,
                          visible=False,
                          vertical_alignment=ft.CrossAxisAlignment.END)

    empty_title = ft.Text("Pick a friend to start chatting", size=14,
                          color=TEXT_DIM)
    empty_sub = ft.Text("Messages are private to you and them.", size=12,
                        color=TEXT_FAINT)
    empty_state = ft.Container(
        content=ft.Column(
            [
                ft.Icon(ft.Icons.CHAT_BUBBLE_OUTLINE_ROUNDED, size=38,
                        color=TEXT_FAINT),
                empty_title,
                empty_sub,
            ],
            spacing=8, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            tight=True,
        ),
        alignment=ft.Alignment.CENTER, expand=True,
    )

    conn_banner_text = ft.Text("", size=12, color=WARNING)
    conn_banner = ft.Container(
        content=ft.Row([ft.Icon(ft.Icons.CLOUD_OFF_ROUNDED, size=16,
                                color=WARNING),
                        conn_banner_text],
                       spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        bgcolor=ft.Colors.with_opacity(0.10, WARNING),
        border=ft.border.Border.all(1, ft.Colors.with_opacity(0.35, WARNING)),
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
        visible=False,
    )

    # --- small builders --------------------------------------------------
    def _avatar_color(name):
        h = 0
        for ch in (name or "?"):
            h = (h * 31 + ord(ch)) & 0xFFFFFFFF
        return AVATAR_COLORS[h % len(AVATAR_COLORS)]

    def _paint_avatar(box, name, size, online=None):
        """Fills an existing rounded-square avatar with the player's Cubeon
        face (fetched from the skins Worker, disk-cached by cubeon.faces)
        when one exists, falling back to the name's initial in a stable
        per-name color. `online=True` rings it in the presence green, which
        is the one place green is allowed to appear here."""
        color = _avatar_color(name)
        box.width = box.height = size
        box.border_radius = RADIUS
        box.border = ft.border.Border.all(
            2 if online else 1, ACCENT if online else CARD_BORDER)
        box.alignment = ft.Alignment.CENTER
        face = _faces.get_face_b64(name)
        if face:
            box.bgcolor = SURFACE_HI
            box.content = ft.Image(src=face, width=size - 2, height=size - 2,
                                   fit=ft.ImageFit.COVER,
                                   border_radius=RADIUS)
        else:
            box.bgcolor = ft.Colors.with_opacity(0.16, color)
            box.content = ft.Text((name[:1] or "?").upper(),
                                  size=int(size * 0.42), color=color,
                                  weight=ft.FontWeight.W_700)

    def _avatar(name, size, online=None):
        box = ft.Container()
        _paint_avatar(box, name, size, online)
        return box

    def _set_you_avatar(name):
        """Your identity-card avatar: the profile picture you set on the
        Profile tab when you have one, else your Cubeon skin face (the
        same /faces/<name>.png every friend card shows), else the
        color-initial chip."""
        you_avatar.width = you_avatar.height = 34
        pfp_path = _profile.get_profile_picture_path(cfg)
        if pfp_path:
            # ft.Image.src only accepts asset-relative paths or URLs in this
            # Flet version - an absolute path under ~/.cubeon_launcher fails
            # to load and renders as a permanently blank square (see
            # skin_tab.render_preview_for for the same discovery). Feed it
            # base64 bytes instead; if the file can't be read, fall back to
            # the color-initial chip so the card is never an empty box.
            try:
                with open(pfp_path, "rb") as f:
                    b64 = base64.b64encode(f.read()).decode("ascii")
            except OSError:
                b64 = None
            if b64:
                you_avatar.bgcolor = SURFACE_HI
                you_avatar.border = ft.border.Border.all(1, CARD_BORDER)
                you_avatar.alignment = ft.Alignment.CENTER
                you_avatar.content = ft.Image(src=b64, width=32, height=32,
                                              fit=ft.ImageFit.COVER,
                                              border_radius=RADIUS)
            else:
                _paint_avatar(you_avatar, name, 34)
        else:
            _paint_avatar(you_avatar, name, 34)

    def _pill(label, fill, fg, on_click):
        return ft.Container(
            content=ft.Text(label, size=11, weight=ft.FontWeight.W_600,
                            color=fg),
            bgcolor=fill, border_radius=RADIUS, ink=False,
            padding=ft.padding.Padding.symmetric(horizontal=10, vertical=4),
            on_click=on_click,
        )

    def _row_bg(is_sel):
        return ACCENT_TINT if is_sel else None

    def _presence(f):
        online = bool(f.get("online"))
        if online and f.get("version"):
            return f"Playing {f['version']}", ACCENT
        if online:
            return "Online", ACCENT
        return "Offline", TEXT_FAINT

    def _unread_badge(count):
        return ft.Container(
            content=ft.Text(str(count) if count < 100 else "99+", size=10,
                            color=ON_ACCENT, weight=ft.FontWeight.W_700),
            bgcolor=ACCENT, border_radius=9, ink=False,
            padding=ft.padding.Padding.symmetric(horizontal=6, vertical=1),
        )

    def _identity_label(metadata):
        uid = _friends.canonical_uid(metadata.get("uid")) or ""
        username = metadata.get("minecraft_username")
        username = username if isinstance(username, str) else ""
        if username != username.strip() or not validate_username(username)[0]:
            username = ""
        return username or (f"Cubeon ID {uid}" if uid else "Player"), uid

    def _peer_identity(name, details=None):
        metadata = {}
        resolver = getattr(service, "peer_metadata", None)
        if callable(resolver):
            try:
                resolved = resolver(name)
                if isinstance(resolved, dict):
                    metadata.update(resolved)
            except Exception:
                pass
        if details is None:
            roster = _last_roster["v"] or {}
            for key in ("friends", "requests_in_details", "requests_out_details"):
                for row in roster.get(key) or []:
                    if isinstance(row, dict) and row.get("name") == name:
                        metadata.update(row)
        elif isinstance(details, dict):
            metadata.update(details)
        return _identity_label(metadata)

    def _recipient(name, details=None):
        label, uid = _peer_identity(name, details)
        recipient = (f"{label} (Cubeon ID {uid})"
                     if uid and label != f"Cubeon ID {uid}" else label)
        resolver = getattr(service, "peer_label", None)
        if callable(resolver):
            try:
                resolved = resolver(name)
                if resolved == recipient:
                    return resolved
            except Exception:
                pass
        return recipient

    def _uid_line(uid):
        return f"Cubeon ID {uid}" if uid else "Cubeon ID unavailable"

    def _friend_row(f):
        name = f.get("name") or ""
        label, uid = _peer_identity(name, f)
        is_sel = selected["name"] == name
        online = bool(f.get("online"))
        last_text = str(f.get("last_text") or "").strip()
        last_ts = int(f.get("last_ts") or 0)
        unread = int(f.get("unread") or 0)
        if last_text:
            preview = ("You: " if f.get("last_dir") == "out" else "") + last_text
            preview = preview.replace("\n", " ")
            preview_color = TEXT_DIM if online or unread else TEXT_FAINT
        else:
            preview, preview_color = _presence(f)
        stamp = _short_stamp(last_ts) if last_ts else ""
        trailing = ft.Column(
            [
                ft.Text(stamp, size=10,
                        color=ACCENT if unread else TEXT_FAINT,
                        tooltip=_full_date(last_ts) if last_ts else None),
                _unread_badge(unread) if unread else ft.Container(),
            ],
            spacing=3, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.END,
        )
        row = ft.Container(
            content=ft.Row(
                [
                    _avatar(label, 34, online),
                    ft.Column(
                        [
                            ft.Text(label, size=13, color=TEXT,
                                    weight=ft.FontWeight.W_600, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(_uid_line(uid), size=10, color=TEXT_FAINT,
                                    font_family=FONT_MONO, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                            ft.Text(preview, size=11, color=preview_color,
                                    max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS),
                        ],
                        spacing=1, tight=True, expand=True,
                    ),
                    trailing,
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=_row_bg(is_sel),
            border_radius=RADIUS,
            ink=False,
            padding=ft.padding.Padding.symmetric(horizontal=8, vertical=7),
            tooltip=_recipient(name, f),
            on_click=lambda e, n=name: _select(n),
        )
        attach_hover(row, _row_bg(is_sel), ROW_HOVER)
        return row

    def _request_row(name):
        label, uid = _peer_identity(name)
        return ft.Container(
            tooltip=_recipient(name),
            content=ft.Row(
                [
                    _avatar(label, 30),
                    ft.Column([
                        ft.Text(label, size=12, color=TEXT,
                                weight=ft.FontWeight.W_600, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(_uid_line(uid), size=10, color=TEXT_FAINT,
                                font_family=FONT_MONO, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=1, tight=True, expand=True),
                    _pill("Accept", ACCENT, ON_ACCENT,
                          lambda e, n=name: _accept(n)),
                    _pill("Decline", None, TEXT_DIM,
                          lambda e, n=name: _decline(n)),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=CARD_FILL,
            border=ft.border.Border.all(1, CARD_BORDER),
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=8, vertical=7),
        )

    def _outgoing_row(name):
        label, uid = _peer_identity(name)
        return ft.Container(
            tooltip=_recipient(name),
            content=ft.Row(
                [
                    _avatar(label, 30),
                    ft.Column([
                        ft.Text(f"Waiting on {label}", size=12, color=TEXT_DIM,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(_uid_line(uid), size=10, color=TEXT_FAINT,
                                font_family=FONT_MONO, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=1, tight=True, expand=True),
                    ft.Text("Pending", size=10, color=WARNING,
                            weight=ft.FontWeight.W_600),
                ],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.Padding.symmetric(horizontal=8, vertical=4),
        )

    # --- rendering -------------------------------------------------------
    def _set_status(text, error=False):
        text = str(text or "").strip()
        if not text:
            return
        status_text.value = text
        status_text.color = DANGER if error else TEXT_DIM
        thread_safe_ui.refresh(status_text)

    def _set_composer_status(text):
        text = str(text or "").strip()
        composer_status.value = text
        composer_status.visible = bool(text)
        thread_safe_ui.refresh(composer_status)

    def _mark_read(name):
        fn = getattr(service, "mark_read", None)
        if not callable(fn):
            return
        try:
            fn(name)
        except Exception:
            pass

    def _apply_identity(roster):
        shown, uid = _identity_label({
            "uid": roster.get("you_uid"),
            "minecraft_username": roster.get("you_minecraft_username"),
        })
        connected = bool(roster.get("connected"))
        available = bool(roster.get("available"))
        pfp_path = _profile.get_profile_picture_path(cfg)
        # Face-availability rides in the sig so a face that finishes
        # downloading flips the token and the next repaint paints it
        # (None when your uploaded picture wins - the face is moot then).
        you_face = None if pfp_path else bool(_faces.get_face_b64(shown))
        sig = (shown, uid, roster.get("you_minecraft_username"),
               roster.get("you_display_name"), connected, available, pfp_path,
               you_face)
        if sig == _identity_sig["v"]:
            return
        _identity_sig["v"] = sig
        you_text.value = shown
        your_id_text.value = uid or "Waiting for your ID…"
        copy_id_btn.visible = bool(uid)
        you_avatar.tooltip = _uid_line(uid)
        _set_you_avatar(shown)
        conn_dot.bgcolor = (ACCENT if connected
                            else (WARNING if available else DANGER))
        conn_text.value = ("Connected" if connected else
                           ("Connecting…" if available else "Add-on missing"))
        if available and not connected:
            conn_banner_text.value = ("Connecting to Cubeon… messages will "
                                      "send once you're back online.")
            conn_banner.visible = True
        else:
            conn_banner.visible = False
        empty_sub.value = ("Add a friend by ID, or wait for someone to add you."
                           if connected else
                           "You're offline — messages send once you reconnect.")
        for ctrl in (you_text, your_id_text, copy_id_btn, you_avatar, conn_dot,
                     conn_text, conn_banner, empty_sub):
            thread_safe_ui.refresh(ctrl)

    def _rebuild_requests(roster):
        incoming = [n for n in (roster.get("requests_in") or [])
                    if isinstance(n, str) and n]
        outgoing = [n for n in (roster.get("requests_out") or [])
                    if isinstance(n, str) and n]
        has_any = bool(incoming or outgoing)
        with thread_safe_ui.TREE_LOCK:
            requests_col.controls.clear()
            for name in incoming:
                requests_col.controls.append(_request_row(name))
            for name in outgoing:
                requests_col.controls.append(_outgoing_row(name))
        requests_label.visible = has_any
        requests_col.visible = has_any
        thread_safe_ui.refresh(requests_col)
        thread_safe_ui.refresh(requests_label)

    def _rebuild_friends(roster):
        friends = [f for f in (roster.get("friends") or [])
                   if isinstance(f, dict) and f.get("name")]
        query = (find_field.value or "").strip().lower()
        if query:
            def _match(f):
                label, uid = _peer_identity(f.get("name"), f)
                return (query in (label or "").lower()
                        or (uid and query in uid))
            friends = [f for f in friends if _match(f)]
        with thread_safe_ui.TREE_LOCK:
            friends_col.controls.clear()
            if not friends and not query:
                friends_col.controls.append(
                    ft.Text("No friends yet. Add one above.", size=12,
                            color=TEXT_FAINT))
            elif not friends:
                friends_col.controls.append(
                    ft.Text("No friend matches that.", size=12,
                            color=TEXT_FAINT))
            for f in friends:
                friends_col.controls.append(_friend_row(f))
        thread_safe_ui.refresh(friends_col)

    def _friend_by_name(name):
        for f in (_last_roster["v"] or {}).get("friends") or []:
            if isinstance(f, dict) and f.get("name") == name:
                return f
        return None

    def _refresh_header():
        name = selected["name"]
        if not name:
            return
        f = _friend_by_name(name) or {}
        label, uid = _peer_identity(name, f)
        sub, sub_color = _presence(f)
        sig = (name, label, uid, sub, sub_color, bool(_faces.get_face_b64(label)))
        if sig == _header_sig["v"]:
            return
        _header_sig["v"] = sig
        transcript_header.value = label
        transcript_header.tooltip = _recipient(name, f)
        transcript_sub.value = f"{sub}  ·  {_uid_line(uid)}"
        transcript_sub.color = sub_color
        _paint_avatar(header_avatar, label, 36, f.get("online"))
        header_avatar.tooltip = _recipient(name, f)
        remove_btn.tooltip = f"Remove {_recipient(name, f)}"
        for ctrl in (transcript_header, transcript_sub, header_avatar, remove_btn):
            thread_safe_ui.refresh(ctrl)

    def _render_roster(roster=None, force=False):
        if roster is not None:
            _last_roster["v"] = roster
        roster = _last_roster["v"]
        if not roster:
            return
        _refresh_header()
        requests = [n for key in ("requests_in", "requests_out")
                    for n in roster.get(key) or [] if isinstance(n, str) and n]
        sig = (roster.get("friends") or [],
               roster.get("requests_in") or [],
               roster.get("requests_out") or [],
               roster.get("requests_in_details") or [],
               roster.get("requests_out_details") or [],
               tuple((n, _peer_identity(n)) for n in requests),
               selected["name"])
        if not force and sig == _roster_sig["v"]:
            return
        _roster_sig["v"] = deepcopy(sig)
        _rebuild_requests(roster)
        _rebuild_friends(roster)

    def _bubble_max_width():
        w = getattr(page, "width", None) or 1000
        return max(220, min(_BUBBLE_MAX, int(w * 0.5)))

    def _bubble_text_width(text, max_w):
        lines = (text or "").split("\n")
        longest = max((len(ln) for ln in lines), default=1)
        return min(max_w, max(_BUBBLE_MIN, int(longest * _CHAR_PX) + 6))

    def _day_separator(label):
        """A centered "Today"/date rule, the standard way a long transcript
        marks where a new day begins instead of a bare stream of timestamps."""
        def _rule():
            return ft.Container(height=1, bgcolor=CARD_BORDER, expand=True)
        return ft.Container(
            content=ft.Row(
                [_rule(),
                 ft.Text(label, size=10, color=TEXT_FAINT,
                         weight=ft.FontWeight.W_600),
                 _rule()],
                spacing=8,
                vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            margin=ft.Margin(0, 12, 0, 4),
        )

    def _on_transcript_scroll(e):
        try:
            # "At the end" with a little tolerance, so a half-pixel drift
            # doesn't strand the follow on.
            at_end = e.extent_after < 48
            _stick["at_end"] = at_end
            if jump_row.visible == at_end:
                jump_row.visible = not at_end
                thread_safe_ui.refresh(jump_row)
        except Exception:
            pass

    def _stick_bottom(force=False):
        """Follow the newest message, but only when the user wants that:
        either forced (conversation just opened) or the view is already at
        the bottom. scroll_to is async - it must ride page.run_task."""
        if not (force or _stick["at_end"]):
            return
        try:
            page.run_task(transcript.scroll_to, -1)
        except Exception:
            pass   # headless/test hosts have no run_task

    def _copy_message(text):
        """Copy a single message's text; the bubble is the + copy affordance."""
        try:
            from flet.controls.services.clipboard import Clipboard
            page.run_task(Clipboard().set, text)
            _set_status("Message copied.")
        except Exception:
            pass   # headless/older hosts have no clipboard service

    def _make_bubble(text, mine, ts, dim=False, failed=False, status=None,
                     with_time=True):
        """One message bubble. `dim` is the optimistic pre-echo state; `failed`
        marks a send that the service refused. `with_time` is the grouped-clock
        rule: consecutive messages from one side show no clock (the full date
        lives on hover); the first message of a group or day does."""
        max_w = _bubble_max_width()
        rows = [ft.Text(text, size=13, selectable=True,
                        color=TEXT_DIM if dim else TEXT,
                        width=_bubble_text_width(text, max_w),
                        tooltip="Click the bubble to copy this message")]
        meta = _fmt_time(ts)
        if status:
            rows.append(ft.Row(
                [ft.Text(meta + ("  ·  " + status if meta else status),
                         size=9, color=DANGER if failed else TEXT_FAINT,
                         tooltip=_full_date(ts) if ts else None)],
                alignment=(ft.MainAxisAlignment.END if mine
                           else ft.MainAxisAlignment.START)))
        elif meta and with_time:
            rows.append(ft.Text(meta, size=9, color=TEXT_FAINT,
                                tooltip=_full_date(ts) if ts else None,
                                text_align=(ft.TextAlign.RIGHT if mine
                                            else ft.TextAlign.LEFT)))
        return ft.Container(
            content=ft.Column(rows, spacing=2, tight=True),
            bgcolor=(CARD_FILL if (dim or failed)
                     else (ACCENT_TINT if mine else SURFACE_HI)),
            border=ft.border.Border.all(
                1, DANGER if failed
                else (CARD_BORDER if (dim or failed)
                      else (ACCENT_DIM if mine else CARD_BORDER))),
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=11, vertical=8),
            ink=False,
            tooltip=((_full_date(ts) + "  ·  click to copy") if ts
                     else "Click to copy this message"),
            on_click=lambda e, t=text: _copy_message(t),
        )

    def _bubble_row(bubble, mine, gap):
        return ft.Container(
            content=ft.Row(
                [bubble],
                alignment=(ft.MainAxisAlignment.END if mine
                           else ft.MainAxisAlignment.START)),
            margin=ft.Margin(0, gap, 0, 0),
        )

    def _append_optimistic(name, text):
        """Show an outgoing message BEFORE the relay confirms it, so pressing
        Enter feels instant. The real echo-filed line replaces this bubble
        in _append_messages; a refusal marks it failed in _do_send's done()."""
        ts = int(time.time() * 1000)
        with thread_safe_ui.TREE_LOCK:
            day, label = _day_key(ts)
            if day and day != _last_day.get(name):
                _last_day[name] = day
                _last_dir[name] = None
                transcript.controls.append(_day_separator(label))
            _last_dir[name] = "out"
            wrap = _bubble_row(
                _make_bubble(text, True, ts, dim=True, status="Sending…"),
                True, 2)
            transcript.controls.append(wrap)
            q = _pending.setdefault(name, [])
            q.append({"text": text, "wrap": wrap, "ts": ts,
                      "t0": time.monotonic(), "failed": False})
            # Bound the queue (this is what a session with an offline relay
            # looks like: every send times out and stays as a red bubble).
            while len(q) > _MAX_PENDING:
                q.pop(0)
        thread_safe_ui.refresh(transcript)
        _stick_bottom()

    def _fail_pending(name, text=None, entry=None):
        """Turn a pending bubble into a red "couldn't send" bubble. Called on
        a send refusal (matched by text) and on the send timeout sweep.

        The entry STAYS in _pending (marked failed) rather than being dropped:
        that is what lets a late-arriving real line replace this bubble in
        place instead of appending a second one for the same message."""
        with thread_safe_ui.TREE_LOCK:
            q = _pending.get(name) or []
            if entry is None:
                for p in q:
                    if p["text"] == text:
                        entry = p
                        break
            if entry is None or entry.get("failed"):
                return
            entry["failed"] = True
            try:
                idx = transcript.controls.index(entry["wrap"])
                fresh = _bubble_row(
                    _make_bubble(entry["text"], True, entry["ts"],
                                 failed=True, status="Couldn't send"), True, 2)
                transcript.controls[idx] = fresh
                entry["wrap"] = fresh
            except ValueError:
                pass   # the conversation was rebuilt - nothing to mark
        thread_safe_ui.refresh(transcript)

    def _sweep_pending():
        """A pending bubble that was never confirmed (relay dropped it, echo
        never arrived) can't stay "Sending…" forever: after 12s it goes red
        like a refusal. If it DOES land later, the real line replaces the red
        bubble in _append_messages instead of duplicating it."""
        cutoff = time.monotonic() - 12.0
        stale = [(name, p) for name, q in list(_pending.items())
                 for p in list(q)
                 if p["t0"] < cutoff and not p.get("failed")]
        for name, p in stale:
            _fail_pending(name, entry=p)

    def _append_messages_inner(msgs, name):
        for m in msgs:
            seq = m.get("seq")
            if seq is not None:
                last_seq[name] = max(last_seq.get(name, -1), int(seq))
            mine = m.get("dir") == "out"
            side = "out" if mine else "in"
            text = m.get("text") or ""
            ts = m.get("ts")
            # A confirmed echo of a message we showed optimistically replaces
            # that pending bubble (FIFO by text) instead of duplicating it. A
            # bubble that already timed out red is replaced IN PLACE, keeping
            # its slot: otherwise the same message shows twice (the red
            # "Couldn't send" bubble plus the real line) whenever the echo
            # arrived after the 12s sweep.
            if mine:
                q = _pending.get(name) or []
                handled_in_place = False
                for p in list(q):
                    if p["text"] != text:
                        continue
                    q.remove(p)
                    if p.get("failed"):
                        # Replace the red bubble where it sits: appending the
                        # real line as well would show the message twice.
                        with thread_safe_ui.TREE_LOCK:
                            try:
                                pos = transcript.controls.index(p["wrap"])
                                transcript.controls[pos] = _bubble_row(
                                    _make_bubble(text, True, ts), True, 2)
                                handled_in_place = True
                            except ValueError:
                                handled_in_place = False
                    else:
                        with thread_safe_ui.TREE_LOCK:
                            try:
                                transcript.controls.remove(p["wrap"])
                            except ValueError:
                                pass
                    break
                if handled_in_place:
                    continue   # this message is on screen - do not append it
            day, label = _day_key(ts)
            prev_side = _last_dir.get(name)
            new_day = bool(day and day != _last_day.get(name))
            if new_day:
                _last_day[name] = day
                _last_dir[name] = None
                prev_side = None
                transcript.controls.append(_day_separator(label))
            # Grouped-clock rule: only the first bubble of a group (or day)
            # shows the clock; run-on messages from the same side keep the
            # transcript quiet, with the full date on hover.
            with_time = new_day or prev_side != side
            gap = 2 if prev_side == side else (6 if _last_day.get(name) else 10)
            _last_dir[name] = side
            transcript.controls.append(_bubble_row(
                _make_bubble(text, mine, ts, with_time=with_time), mine, gap))
        thread_safe_ui.refresh(transcript)

    def _append_messages(msgs, name):
        if not msgs or selected["name"] != name:
            return
        with thread_safe_ui.TREE_LOCK:
            _append_messages_inner(msgs, name)
        _stick_bottom()

    # --- actions ---------------------------------------------------------
    def _select(name):
        prev = selected["name"]
        if prev and prev != name:
            _drafts[prev] = composer.value
        selected["name"] = name
        last_seq[name] = -1
        _last_day[name] = None
        _last_dir[name] = None
        _pending[name] = []       # the transcript is rebuilt; pending bubbles die
        _stick["at_end"] = True   # opening a conversation starts at the bottom
        emoji_panel.visible = False
        composer_status.visible = False
        composer.value = _drafts.get(name) or ""
        with thread_safe_ui.TREE_LOCK:
            transcript.controls.clear()
        transcript.visible = True
        empty_state.visible = False
        _header_sig["v"] = None
        _refresh_header()
        header_avatar.visible = True
        remove_btn.visible = True
        header_rule.visible = True
        remove_btn.on_click = lambda e, n=name: _confirm_remove(n)
        composer_row.visible = True
        emoji_btn.visible = True
        jump_row.visible = False   # opening starts at the bottom
        _roster_sig["v"] = None   # repaint the selection highlight
        for ctrl in (transcript, empty_state, transcript_header,
                     transcript_sub, header_avatar, remove_btn, header_rule,
                     composer_row, composer_status, emoji_btn, emoji_panel,
                     jump_row, composer):
            thread_safe_ui.refresh(ctrl)
        _mark_read(name)
        _tick()
        _stick_bottom(force=True)

    def _run(action, done, label):
        """Run a service call off the UI thread. Several do real network I/O
        (claim a name, publish/lookup an E2EE key), and a Flet event handler
        runs on the UI thread - doing that inline freezes the whole window."""
        def work():
            try:
                res = action() or {}
            except Exception:
                res = {"ok": False, "error": "That didn't work. Please try again."}
            done(res)
            _tick()
            _wake.set()   # the poll loop re-checks soon after any action
        threading.Thread(target=work, daemon=True, name=label).start()

    def _do_send():
        name = selected["name"]
        text = (composer.value or "").strip()
        if not name or not text:
            return

        _set_composer_status("")
        emoji_panel.visible = False
        # Optimistic: clear the box and show the bubble NOW. send_chat blocks
        # on the peer-pubkey lookup + WS send (~a second); the user must never
        # wait on that. If the send is refused, the pending bubble turns red
        # below; if it's accepted, the relay's echo files the real line which
        # replaces the pending bubble in _append_messages.
        composer.value = ""
        _drafts.pop(name, None)   # the message left the box - draft is spent
        thread_safe_ui.refresh(composer)
        _append_optimistic(name, text)
        # Confirm fast: poll every _POLL_FAST_SECONDS until the echo files the
        # real line, so the bubble flips out of "Sending…" in a few hundred ms
        # instead of waiting out an idle tick.
        _fast_until["v"] = time.monotonic() + _CONFIRM_WINDOW_S
        _wake.set()

        def done(res):
            if not res.get("ok"):
                _set_composer_status(res.get("error")
                                     or "Couldn't send that message.")
                _fail_pending(name, text)

        _run(lambda: service.send_chat(name, text), done, "cubeon-chat-send")

    def _do_add():
        raw = (add_field.value or "").strip()
        if not raw:
            return
        uid = _friends.canonical_uid(raw)
        if not uid:
            _set_status("Enter your friend's 8-number ID.", error=True)
            return

        def done(res):
            if res.get("ok"):
                add_field.value = ""
                _set_status(f"Friend request sent to ID {uid}.")
                thread_safe_ui.refresh(add_field)
            else:
                _set_status(res.get("error") or "Couldn't send that request.",
                            error=True)

        _run(lambda: service.add_friend(uid), done, "cubeon-chat-add")

    def _accept(name):
        _forward(service.accept, name,
                 f"You and {_recipient(name)} are now friends.")

    def _decline(name):
        _forward(service.decline, name,
                 f"Declined {_recipient(name)}'s request.")

    def _forward(method, name, success):
        def done(res):
            _set_status(success if res.get("ok")
                        else (res.get("error") or "That didn't work."),
                        error=not res.get("ok"))

        _run(lambda: method(name), done, "cubeon-chat-request")

    def _do_remove(name):
        recipient = _recipient(name)

        def done(res):
            if res.get("ok"):
                if selected["name"] == name:
                    _clear_conversation()
                _set_status(f"Removed {recipient}.")
            else:
                _set_status(res.get("error") or "Couldn't remove that friend.",
                            error=True)

        _run(lambda: service.remove(name), done, "cubeon-chat-remove")

    def _clear_conversation():
        if selected["name"]:
            _drafts[selected["name"]] = composer.value
        selected["name"] = None
        composer.value = ""
        with thread_safe_ui.TREE_LOCK:
            transcript.controls.clear()
        transcript.visible = False
        empty_state.visible = True
        transcript_header.value = ""
        transcript_header.tooltip = None
        transcript_sub.value = ""
        _header_sig["v"] = None
        header_avatar.tooltip = None
        header_avatar.visible = False
        remove_btn.tooltip = "Remove friend"
        remove_btn.visible = False
        header_rule.visible = False
        composer_row.visible = False
        emoji_btn.visible = False
        emoji_panel.visible = False
        composer_status.visible = False
        jump_row.visible = False
        for name in list(_pending):
            _pending[name] = []
        _roster_sig["v"] = None
        for ctrl in (transcript, empty_state, transcript_header,
                     transcript_sub, header_avatar, remove_btn, header_rule,
                     composer_row, composer_status, emoji_btn, emoji_panel,
                     jump_row, composer):
            thread_safe_ui.refresh(ctrl)

    def _confirm_remove(name):
        dlg = ft.AlertDialog(modal=True)
        dlg.title = ft.Text(f"Remove {_recipient(name)}?", size=18, color=TEXT,
                            font_family=FONT_DISPLAY)
        dlg.content = ft.Text("They'll disappear from your friends list. You "
                              "can add them back later.", size=13, color=TEXT_DIM)
        dlg.actions = [
            ft.TextButton("Cancel",
                          on_click=lambda e: _dialogs.close_dialog(page, dlg)),
            ft.TextButton("Remove", on_click=lambda e: (
                _dialogs.close_dialog(page, dlg), _do_remove(name))),
        ]
        _dialogs.open_dialog(page, dlg)

    # --- poll loop -------------------------------------------------------
    def _tick():
        if not tick_lock.acquire(blocking=False):
            return
        try:
            try:
                roster = service.roster_payload()
            except Exception:
                roster = None
            if roster:
                _apply_identity(roster)
                _render_roster(roster)
            try:
                ev = service.events_since(cursor["v"]) or {}
            except Exception:
                ev = {}
            if cursor["v"] >= 0:
                for e in ev.get("events", []):
                    _set_status(e.get("text") or "", bool(e.get("error")))
            cursor["v"] = ev.get("cursor", cursor["v"])
            name = selected["name"]
            if name:
                _sweep_pending()
                try:
                    payload = service.chat_payload(
                        name, last_seq.get(name, -1)) or {}
                except Exception:
                    payload = {}
                _append_messages(payload.get("messages") or [], name)
                _mark_read(name)
        finally:
            tick_lock.release()

    def refresh():
        _tick()

    def _poll_interval():
        """How long the poll loop sleeps before its next tick.

        Idle (no conversation open, nothing in flight) keeps the old relaxed
        1.5s; an open conversation means someone is watching the transcript,
        so new lines land in half a second; and for a couple of seconds after
        a send we poll fastest, which is what confirms the sender's own bubble
        promptly instead of making them watch "Sending…"."""
        if _pending or time.monotonic() < _fast_until["v"]:
            return _POLL_FAST_SECONDS
        if selected["name"]:
            return _POLL_ACTIVE_SECONDS
        return _POLL_SECONDS

    def _poller():
        while not stop.is_set():
            try:
                _tick()
            except Exception:
                pass
            if _wake.wait(_poll_interval()):
                _wake.clear()

    # --- layout ----------------------------------------------------------
    status_text = ft.Text("", size=12, color=TEXT_DIM,
                          max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)

    left = ft.Container(
        width=290,
        content=ft.Column(
            [
                ft.Row(
                    [
                        ft.Text("Chat", size=24, color=TEXT,
                                font_family=FONT_DISPLAY),
                        ft.Container(expand=True),
                        conn_dot,
                        conn_text,
                    ],
                    spacing=6,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(height=4),
                ft.Container(
                    content=ft.Row(
                        [
                            you_avatar,
                            ft.Column(
                                [
                                    you_text,
                                    your_id_text,
                                ],
                                spacing=1, tight=True, expand=True,
                            ),
                            copy_id_btn,
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    tooltip="Your Cubeon account (the ID is yours alone - "
                            "it can't be renamed or taken)",
                    bgcolor=CARD_FILL,
                    border=ft.border.Border.all(1, CARD_BORDER),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=10,
                                                         vertical=8),
                ),
                ft.Container(height=6),
                add_field,
                requests_label,
                requests_col,
                find_field,
                friends_label,
                friends_col,
                ft.Container(height=8),
                status_text,
            ],
            spacing=6,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        ),
    )

    # The hairline rule under the conversation header. It only makes sense
    # when a header exists - with no friend selected the header row is
    # invisible, and this rule alone rendered as a stray floating line
    # across the empty right pane.
    header_rule = ft.Container(height=1, bgcolor=CARD_BORDER, visible=False)

    right = ft.Container(
        expand=True,
        content=ft.Column(
            [
                ft.Row(
                    [
                        header_avatar,
                        ft.Column([transcript_header, transcript_sub],
                                  spacing=1, expand=True, tight=True),
                        remove_btn,
                    ],
                    spacing=12,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                conn_banner,
                header_rule,
                transcript,
                jump_row,
                empty_state,
                composer_status,
                emoji_panel,
                composer_row,
            ],
            spacing=12,
            expand=True,
        ),
    )

    root = ft.Row(
        [left, ft.Container(width=1, bgcolor=CARD_BORDER), right],
        spacing=16,
        expand=True,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
    )

    # Poll only after every control exists, so a tick can never touch an
    # unassigned local; then reconcile once immediately for the first paint.
    threading.Thread(target=_poller, daemon=True,
                     name="cubeon-chat-tab").start()
    refresh()
    return root, refresh
