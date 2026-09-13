"""
The Chat tab: the launcher's social surface.

Before this tab, the only friends UI was the in-game "Cubeon" mod, which talks
to the launcher over the localhost bridge. That left the launcher itself with a
realtime friends connection (FriendsService), a roster, encrypted DMs and friend
requests but no screen to use any of it. This tab is that screen, and it talks
to the same process-scoped FriendsService directly instead of going through the
HTTP bridge the mod uses.

What it shows, on one screen:
  - the automatic Cubeon ID: a 12-digit number the server assigns on first
    connect (000000000001, 000000000002, ...), shown so a friend can add you,
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
  - All service calls run on this module's own poll thread; every control write
    is wrapped in thread_safe_ui.TREE_LOCK and repainted with
    thread_safe_ui.refresh(control), never a whole-page update.
  - Built lazily the first time the tab opens (main.py's _ensure_tab), so no
    poll thread and no roster read happens until then.
"""
import threading
import time

import flet as ft

from cubeon.theme import (
    RADIUS, ON_ACCENT, WARNING, TEXT_FAINT, ACCENT_HI,
    CARD_FILL, CARD_BORDER, ROW_HOVER, ACCENT_TINT,
    AVATAR_COLORS, attach_hover,
)
from cubeon import dialogs as _dialogs
from cubeon import friends as _friends
from cubeon import thread_safe_ui

_POLL_SECONDS = 1.5

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
    _last_day = {}
    _last_dir = {}
    tick_lock = threading.Lock()
    stop = threading.Event()

    # --- controls --------------------------------------------------------
    you_text = ft.Text("Setting up...", size=13, color=TEXT,
                       weight=ft.FontWeight.W_600, max_lines=1,
                       overflow=ft.TextOverflow.ELLIPSIS)
    you_avatar = ft.Container(width=34, height=34, border_radius=RADIUS)
    conn_dot = ft.Container(width=8, height=8, border_radius=4,
                            bgcolor=TEXT_FAINT)
    conn_text = ft.Text("", size=11, color=TEXT_DIM)

    your_id_text = ft.Text("", size=15, color=ACCENT, font_family=FONT_MONO,
                           weight=ft.FontWeight.W_700, selectable=True,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)

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
    transcript = ft.ListView(expand=True, spacing=0, auto_scroll=True,
                             padding=ft.padding.Padding.symmetric(
                                 vertical=6, horizontal=2), visible=False)

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
    )
    send_btn = attach_hover(ft.Container(
        content=ft.Icon(ft.Icons.SEND_ROUNDED, size=18, color=ON_ACCENT),
        bgcolor=ACCENT, border_radius=RADIUS, width=44, height=44,
        alignment=ft.Alignment.CENTER, ink=False,
        on_click=lambda e: _do_send(),
    ), ACCENT, ACCENT_HI)
    composer_status = ft.Text("", size=11, color=DANGER, max_lines=2,
                              overflow=ft.TextOverflow.ELLIPSIS, visible=False)
    composer_row = ft.Row([composer, send_btn], spacing=8, visible=False,
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
        """Fills an existing rounded-square avatar with the name's initial in
        a stable per-name color - so the roster has identity without color
        noise, and green stays semantic. `online=True` rings it in the presence
        green, which is the one place green is allowed to appear here."""
        color = _avatar_color(name)
        box.width = box.height = size
        box.border_radius = RADIUS
        box.bgcolor = ft.Colors.with_opacity(0.16, color)
        box.border = ft.border.Border.all(
            2 if online else 1, ACCENT if online else CARD_BORDER)
        box.alignment = ft.Alignment.CENTER
        box.content = ft.Text((name[:1] or "?").upper(),
                              size=int(size * 0.42), color=color,
                              weight=ft.FontWeight.W_700)

    def _avatar(name, size, online=None):
        box = ft.Container()
        _paint_avatar(box, name, size, online)
        return box

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

    def _friend_row(f):
        name = f.get("name") or ""
        uid = str(f.get("uid") or "")
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
        stamp = _fmt_time(last_ts) if last_ts else ""
        trailing = ft.Column(
            [
                ft.Text(stamp, size=10,
                        color=ACCENT if unread else TEXT_FAINT),
                _unread_badge(unread) if unread else ft.Container(),
            ],
            spacing=3, tight=True,
            horizontal_alignment=ft.CrossAxisAlignment.END,
        )
        row = ft.Container(
            content=ft.Row(
                [
                    _avatar(name, 34, online),
                    ft.Column(
                        [
                            ft.Text(name, size=13, color=TEXT,
                                    weight=ft.FontWeight.W_600, max_lines=1,
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
            tooltip=f"ID {uid}" if uid else None,
            on_click=lambda e, n=name: _select(n),
        )
        attach_hover(row, _row_bg(is_sel), ROW_HOVER)
        return row

    def _request_row(name):
        return ft.Container(
            content=ft.Row(
                [
                    _avatar(name, 30),
                    ft.Text(name, size=12, color=TEXT, expand=True,
                            weight=ft.FontWeight.W_600, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
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
        return ft.Container(
            content=ft.Row(
                [
                    _avatar(name, 30),
                    ft.Text(f"Waiting on {name}", size=12, color=TEXT_DIM,
                            expand=True, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
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
        uid = roster.get("you_uid") or ""
        sig = (roster.get("you"), uid, bool(roster.get("connected")),
               bool(roster.get("available")))
        if sig == _identity_sig["v"]:
            return
        _identity_sig["v"] = sig
        name = roster.get("you") or ""
        connected = bool(roster.get("connected"))
        available = bool(roster.get("available"))
        you_text.value = name or "Setting up..."
        you_id_text.value = uid or "Waiting for your ID…"
        conn_dot.bgcolor = (ACCENT if connected
                            else (WARNING if available else DANGER))
        conn_text.value = ("Connected" if connected else
                           ("Connecting…" if available else "Add-on missing"))
        _paint_avatar(you_avatar, name or "?", 34)
        if available and not connected:
            conn_banner_text.value = ("Connecting to Cubeon… messages will "
                                      "send once you're back online.")
            conn_banner.visible = True
        else:
            conn_banner.visible = False
        empty_sub.value = ("Add a friend by ID, or wait for someone to add you."
                           if connected else
                           "You're offline — messages send once you reconnect.")
        for ctrl in (you_text, you_id_text, you_avatar, conn_dot, conn_text,
                     conn_banner, empty_sub):
            thread_safe_ui.refresh(ctrl)

    def _rebuild_requests(roster):
        incoming = [n for n in (roster.get("requests_in") or []) if n]
        outgoing = [n for n in (roster.get("requests_out") or []) if n]
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
        with thread_safe_ui.TREE_LOCK:
            friends_col.controls.clear()
            if not friends:
                friends_col.controls.append(
                    ft.Text("No friends yet. Add one above.", size=12,
                            color=TEXT_FAINT))
            for f in friends:
                friends_col.controls.append(_friend_row(f))
        thread_safe_ui.refresh(friends_col)

    def _friend_by_name(name):
        for f in (_last_roster["v"] or {}).get("friends") or []:
            if isinstance(f, dict) and f.get("name") == name:
                return f
        return None

    def _render_roster(roster=None, force=False):
        if roster is not None:
            _last_roster["v"] = roster
        roster = _last_roster["v"]
        if not roster:
            return
        sig = (tuple(roster.get("friends") or []),
               tuple(roster.get("requests_in") or []),
               tuple(roster.get("requests_out") or []),
               selected["name"])
        if not force and sig == _roster_sig["v"]:
            return
        _roster_sig["v"] = sig
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

    def _append_messages(msgs, name):
        if not msgs or selected["name"] != name:
            return
        max_w = _bubble_max_width()
        with thread_safe_ui.TREE_LOCK:
            for m in msgs:
                seq = m.get("seq")
                if seq is not None:
                    last_seq[name] = max(last_seq.get(name, -1), int(seq))
                mine = m.get("dir") == "out"
                side = "out" if mine else "in"
                text = m.get("text") or ""
                ts = m.get("ts")
                day, label = _day_key(ts)
                if day and day != _last_day.get(name):
                    _last_day[name] = day
                    _last_dir[name] = None
                    transcript.controls.append(_day_separator(label))
                same = _last_dir.get(name) == side
                gap = 2 if same else (6 if _last_day.get(name) else 10)
                _last_dir[name] = side
                bubble = ft.Container(
                    content=ft.Column(
                        [
                            ft.Text(text, size=13, selectable=True, color=TEXT,
                                    width=_bubble_text_width(text, max_w)),
                            ft.Text(_fmt_time(ts), size=9, color=TEXT_FAINT,
                                    text_align=(ft.TextAlign.RIGHT if mine
                                                else ft.TextAlign.LEFT)),
                        ],
                        spacing=2, tight=True,
                    ),
                    bgcolor=ACCENT_TINT if mine else SURFACE_HI,
                    border=ft.border.Border.all(
                        1, ACCENT_DIM if mine else CARD_BORDER),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=11,
                                                         vertical=8),
                )
                transcript.controls.append(
                    ft.Container(
                        content=ft.Row(
                            [bubble],
                            alignment=(ft.MainAxisAlignment.END if mine
                                       else ft.MainAxisAlignment.START)),
                        margin=ft.Margin(0, gap, 0, 0),
                    ))
        thread_safe_ui.refresh(transcript)

    # --- actions ---------------------------------------------------------
    def _select(name):
        selected["name"] = name
        last_seq[name] = -1
        _last_day[name] = None
        _last_dir[name] = None
        composer_status.visible = False
        with thread_safe_ui.TREE_LOCK:
            transcript.controls.clear()
        transcript.visible = True
        empty_state.visible = False
        transcript_header.value = name
        f = _friend_by_name(name) or {}
        sub, sub_color = _presence(f)
        uid = str(f.get("uid") or "")
        transcript_sub.value = f"{sub}  ·  ID {uid}" if uid else sub
        transcript_sub.color = sub_color
        _paint_avatar(header_avatar, name, 36, f.get("online"))
        header_avatar.visible = True
        remove_btn.visible = True
        remove_btn.on_click = lambda e, n=name: _confirm_remove(n)
        composer_row.visible = True
        _roster_sig["v"] = None   # repaint the selection highlight
        for ctrl in (transcript, empty_state, transcript_header,
                     transcript_sub, header_avatar, remove_btn, composer_row,
                     composer_status):
            thread_safe_ui.refresh(ctrl)
        _mark_read(name)
        _tick()

    def _run(action, done, label):
        """Run a service call off the UI thread. Several do real network I/O
        (claim a name, publish/lookup an E2EE key), and a Flet event handler
        runs on the UI thread - doing that inline freezes the whole window."""
        def work():
            try:
                res = action() or {}
            except Exception as ex:
                res = {"ok": False, "error": str(ex)}
            done(res)
            _tick()
        threading.Thread(target=work, daemon=True, name=label).start()

    def _do_send():
        name = selected["name"]
        text = (composer.value or "").strip()
        if not name or not text:
            return

        _set_composer_status("")

        def done(res):
            if res.get("ok"):
                composer.value = ""
                thread_safe_ui.refresh(composer)
            else:
                _set_composer_status(res.get("error")
                                     or "Couldn't send that message.")

        _run(lambda: service.send_chat(name, text), done, "cubeon-chat-send")

    def _do_add():
        raw = (add_field.value or "").strip()
        if not raw:
            return
        uid = _friends.canonical_uid(raw)
        if not uid:
            _set_status("Enter your friend's 12-number ID.", error=True)
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
        _forward(service.accept, name, f"You and {name} are now friends.")

    def _decline(name):
        _forward(service.decline, name, f"Declined {name}'s request.")

    def _forward(method, name, success):
        def done(res):
            _set_status(success if res.get("ok")
                        else (res.get("error") or "That didn't work."),
                        error=not res.get("ok"))

        _run(lambda: method(name), done, "cubeon-chat-request")

    def _do_remove(name):
        def done(res):
            if res.get("ok"):
                if selected["name"] == name:
                    _clear_conversation()
                _set_status(f"Removed {name}.")
            else:
                _set_status(res.get("error") or "Couldn't remove that friend.",
                            error=True)

        _run(lambda: service.remove(name), done, "cubeon-chat-remove")

    def _clear_conversation():
        selected["name"] = None
        with thread_safe_ui.TREE_LOCK:
            transcript.controls.clear()
        transcript.visible = False
        empty_state.visible = True
        transcript_header.value = ""
        transcript_sub.value = ""
        header_avatar.visible = False
        remove_btn.visible = False
        composer_row.visible = False
        composer_status.visible = False
        _roster_sig["v"] = None
        for ctrl in (transcript, empty_state, transcript_header,
                     transcript_sub, header_avatar, remove_btn, composer_row,
                     composer_status):
            thread_safe_ui.refresh(ctrl)

    def _confirm_remove(name):
        dlg = ft.AlertDialog(modal=True)
        dlg.title = ft.Text(f"Remove {name}?", size=18, color=TEXT,
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

    def _poller():
        while not stop.is_set():
            try:
                _tick()
            except Exception:
                pass
            stop.wait(_POLL_SECONDS)

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
                ft.Row(
                    [
                        you_avatar,
                        ft.Column(
                            [
                                ft.Text("You", size=10, color=TEXT_FAINT,
                                        weight=ft.FontWeight.W_600),
                                you_text,
                            ],
                            spacing=1, tight=True, expand=True,
                        ),
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.BADGE_OUTLINED, size=16,
                                    color=ACCENT),
                            ft.Column(
                                [
                                    ft.Text("Your friend ID", size=10,
                                            color=TEXT_FAINT),
                                    your_id_text,
                                ],
                                spacing=0, tight=True, expand=True,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
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
                ft.Container(height=1, bgcolor=CARD_BORDER),
                transcript,
                empty_state,
                composer_status,
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
