"""Browse view for the Servers tab - live public-server browser.

One of the four server screens (Console / Browse / Plugins / Settings).
Shows a curated catalogue of well-known public servers whose player counts
are fetched LIVE (cubeon/server_browse.py), sorted most-playing to
none-playing, with tag chips (cracked / premium / genre...), a search bar
that also accepts a raw address ("check any server"), and a one-click Join
that launches the selected profile straight into the server through the
same launch path the friends flow uses.

Threading contract (the same one every browse surface in this app follows):
the view never blocks on the network. `refresh()` paints cached/last-known
rows instantly and starts ONE worker that annotates statuses; row controls
are updated in place from that worker through thread_safe_ui.refresh().
Keystrokes only ever filter the already-annotated list - they never fetch.
"""
import threading
from concurrent.futures import ThreadPoolExecutor

import flet as ft

from cubeon.theme import (
    RADIUS, attach_hover, TEXT_FAINT, ROW_HOVER, ACCENT_TINT, ACCENT_HI,
    ON_ACCENT, CARD_BORDER, CARD_FILL,
)
from cubeon import icons as _icons
from cubeon import server_browse as sb
from cubeon import thread_safe_ui
from cubeon.dialogs import show_snack


def build_server_browse_tab(page: ft.Page, cfg: dict, state: dict, *,
                            join_game, **theme):
    """Builds the Browse view.

    Args:
        join_game: callable(host: str, port: int, name: str) - main.py's
                   launcher closure. The view only collects the click; the
                   caller owns version/profile resolution and error UI.
        theme: the shared THEME tokens main.py passes to every tab
               (BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM, TEXT,
               TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO).

    Returns:
        (ft.Column, callable): the view and its refresh() (safe to call on
        every tab entry; it repaints from cache and re-annotates).
    """
    BG = theme["BG"]; SURFACE = theme["SURFACE"]; SURFACE_HI = theme["SURFACE_HI"]
    BORDER = theme["BORDER"]; ACCENT = theme["ACCENT"]; ACCENT_DIM = theme["ACCENT_DIM"]
    TEXT = theme["TEXT"]; TEXT_DIM = theme["TEXT_DIM"]
    DANGER = theme["DANGER"]; FONT_DISPLAY = theme["FONT_DISPLAY"]
    FONT_MONO = theme["FONT_MONO"]

    ONLINE_DOT = "#4ADE80"     # the app's success green (dark-theme tuned)
    OFFLINE_DOT = "#6B7280"
    CRACKED_FG = "#E0A34F"     # amber for the cracked chip
    CRACKED_BG = "#3A2E1B"

    # The annotated row list lives here; render() reads it, annotate() fills it.
    rows_state = {
        "entries": [],          # catalogue entries + "status" + "icon"
        "lookup": None,         # synthetic direct-lookup entry, pinned on top
        "query": "",
        "tag": None,
        "loading": False,
    }
    row_controls = {}           # host -> {"dot","players","motd","join","line2"}

    # ------------------------------------------------------------------
    # Row building
    # ------------------------------------------------------------------
    def _tag_chip(tag: str):
        if tag == "cracked":
            bg, fg = CRACKED_BG, CRACKED_FG
        elif tag == "premium":
            bg, fg = ACCENT_TINT, ACCENT
        else:
            bg, fg = SURFACE_HI, TEXT_DIM
        return ft.Container(
            content=ft.Text(tag, size=10, color=fg, weight=ft.FontWeight.W_600),
            bgcolor=bg, border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=8, vertical=3),
        )

    def _copy_address(e=None, host: str = ""):
        page.set_clipboard(host)
        show_snack(page, f"Address copied: {host}")

    def _build_row(entry: dict, *, pinned: bool = False) -> ft.Container:
        host = entry.get("host", "")
        status = entry.get("status") or {}
        icon_src = _icons.src(entry.get("icon"))
        if entry.get("icon"):
            _icons.prefetch(entry.get("icon"))

        dot = ft.Container(width=8, height=8, border_radius=4,
                           bgcolor=OFFLINE_DOT)
        players_text = ft.Text("checking…", size=12.5, color=TEXT_FAINT,
                               font_family=FONT_MONO)
        motd_text = ft.Text("", size=11, color=TEXT_FAINT, max_lines=1,
                            font_family=FONT_MONO)
        blurb_text = ft.Text(entry.get("blurb") or "", size=12,
                             color=TEXT_DIM, max_lines=1)

        version_id = state.get("selected_version")
        join_btn = attach_hover(
            ft.Container(
                content=ft.Text("JOIN", size=12.5, weight=ft.FontWeight.W_700,
                                color=ON_ACCENT),
                bgcolor=ACCENT if version_id else SURFACE_HI,
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=16, vertical=8),
                tooltip=("Launch Minecraft straight into this server"
                         if version_id else
                         "Select a Minecraft version on the Play tab first"),
            ),
            ACCENT, ACCENT_HI,
        )

        def _on_join(e=None, ent=entry, btn=join_btn):
            if not state.get("selected_version"):
                show_snack(page, "Pick a Minecraft version on the Play tab "
                                 "first - the server decides which one too.")
                return
            s = ent.get("status")
            if s is not None and not s.get("online"):
                show_snack(page, f"{ent.get('name', ent.get('host'))} looks "
                                 f"offline right now - joining anyway would "
                                 f"just time out.")
                return
            h, p = sb.parse_address(ent["host"])
            join_game(h, p, ent.get("name") or h)

        join_btn.on_click = _on_join
        join_btn.disabled = not bool(version_id)

        name_row = ft.Row(
            [
                ft.Text(entry.get("name") or host, size=15,
                        weight=ft.FontWeight.W_600, color=TEXT),
                ft.Container(width=2),
                ft.GestureDetector(
                    content=ft.Text(host, size=11.5, color=ACCENT_DIM,
                                    font_family=FONT_MONO),
                    on_tap=lambda e=None, h=host: _copy_address(e, h),
                    mouse_cursor=ft.MouseCursor.CLICK,
                ),
                ft.Row([_tag_chip(t) for t in (entry.get("tags") or [])],
                       spacing=5, wrap=False, run_spacing=5, expand=True),
            ],
            spacing=6,
        )

        row = ft.Container(
            bgcolor="transparent",
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
            margin=ft.Margin.only(bottom=6),
            border=ft.border.Border.all(1, BORDER) if pinned else None,
            content=ft.Row(
                [
                    ft.Container(
                        content=ft.Image(src=icon_src, width=38, height=38,
                                         border_radius=RADIUS,
                                         error_content=ft.Icon(
                                             ft.Icons.DNS_ROUNDED,
                                             size=20, color=TEXT_DIM))
                        if icon_src else
                        ft.Icon(ft.Icons.DNS_ROUNDED, size=22, color=TEXT_DIM),
                        width=40, height=40,
                        bgcolor=SURFACE_HI, border_radius=RADIUS,
                        alignment=ft.Alignment.CENTER,
                    ),
                    ft.Container(expand=True, content=ft.Column(
                        [
                            name_row,
                            blurb_text,
                            motd_text,
                        ],
                        spacing=3,
                    )),
                    ft.Column(
                        [
                            ft.Row([dot, players_text], spacing=6,
                                   run_spacing=6),
                            join_btn,
                        ],
                        spacing=8,
                        horizontal_alignment=ft.CrossAxisAlignment.END,
                    ),
                ],
                spacing=12,
            ),
        )
        attach_hover(row, "transparent", ROW_HOVER)
        row_controls[host] = {
            "dot": dot, "players": players_text, "motd": motd_text,
            "join": join_btn, "blurb": blurb_text,
        }
        _apply_status(row_controls[host], entry)
        return row

    # ------------------------------------------------------------------
    # Painting
    # ------------------------------------------------------------------
    results_col = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO, expand=True)
    status_line = ft.Text("", size=12, color=TEXT_FAINT)

    def _apply_status(ctrl: dict, entry: dict):
        """One place that turns an entry's status into row visuals - used at
        build time (so a cached status paints instantly) and by the worker
        that fills live values in later."""
        s = entry.get("status")
        if s and s.get("online"):
            ctrl["dot"].bgcolor = ONLINE_DOT
            ctrl["players"].value = f"{int(s.get('players') or 0):,} online"
            ctrl["players"].color = TEXT
            ctrl["motd"].value = s.get("motd") or ""
            ctrl["players"].tooltip = ("last seen recently - refreshing"
                                       if s.get("stale") else None)
        elif s is not None:
            ctrl["dot"].bgcolor = OFFLINE_DOT
            ctrl["players"].value = "offline"
            ctrl["players"].color = TEXT_FAINT
            ctrl["motd"].value = ""
        # else: leave the "checking…" placeholders alone

    def _paint_row(entry: dict):
        ctrl = row_controls.get(entry.get("host"))
        if ctrl:
            _apply_status(ctrl, entry)

    def render():
        """Rebuild the result list from rows_state (no network, instant)."""
        entries = list(rows_state["entries"])
        lookup = rows_state["lookup"]
        q = rows_state["query"].strip().lower()
        tag = rows_state["tag"]

        def _matches(entry: dict) -> bool:
            if tag and tag not in (entry.get("tags") or []):
                return False
            if q:
                hay = " ".join([entry.get("name", ""), entry.get("host", ""),
                                entry.get("blurb", ""),
                                " ".join(entry.get("tags") or [])]).lower()
                if q not in hay:
                    return False
            return True

        rest = [e for e in entries if e is not lookup and _matches(e)]
        shown = ([lookup] if lookup is not None else []) + \
            sb.sort_by_status(rest)

        results_col.controls = (
            [_build_row(e, pinned=(lookup is not None and e is lookup))
             for e in shown]
            if shown else
            [ft.Container(
                content=ft.Column(
                    [ft.Icon(ft.Icons.TRAVEL_EXPLORE_ROUNDED, size=34,
                             color=TEXT_DIM),
                     ft.Text("No servers match" if (q or tag)
                             else "Checking the big servers…",
                             size=14, color=TEXT_DIM),
                     ft.Text("Type any address like mc.example.net to check "
                             "and join it" if (q or tag) else
                             "Live player counts, refreshed in the "
                             "background",
                             size=12, color=TEXT_FAINT)],
                    spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                alignment=ft.Alignment.CENTER,
                padding=40,
            )]
        )
        online = sum(1 for e in shown
                     if (e.get("status") or {}).get("online"))
        players = sum(int((e.get("status") or {}).get("players") or 0)
                      for e in shown)
        status_line.value = (
            f"{len(shown)} servers · {online} online · {players:,} players "
            f"in total · sorted most playing first"
            if shown else "")
        thread_safe_ui.refresh(results_col)
        thread_safe_ui.refresh(status_line)

    # ------------------------------------------------------------------
    # Search + tag chips
    # ------------------------------------------------------------------
    search_field = ft.TextField(
        hint_text="Search servers, or type an address like mc.hypixel.net",
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        expand=True, dense=True, border_radius=RADIUS,
        border_color=BORDER, focused_border_color=ACCENT,
        cursor_color=ACCENT, content_padding=ft.padding.Padding.symmetric(
            horizontal=12, vertical=10),
    )

    chips_row = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO)
    tag_buttons = {}

    def _on_tag(tag: str | None):
        rows_state["tag"] = tag
        for t, btn in tag_buttons.items():
            active = rows_state["tag"] == t
            btn.bgcolor = ACCENT_TINT if active else SURFACE_HI
            btn.content.color = ACCENT if active else TEXT_DIM
        render()

    for t in ["All"] + sb.TAGS:
        tag_value = None if t == "All" else t
        chip = attach_hover(
            ft.Container(
                content=ft.Text(t, size=11.5, weight=ft.FontWeight.W_600,
                                color=TEXT_DIM),
                bgcolor=SURFACE_HI, border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=11, vertical=6),
            ),
            SURFACE_HI, ROW_HOVER,
        )
        chip.on_click = lambda e=None, tv=tag_value: _on_tag(tv)
        tag_buttons[tag_value] = chip
        chips_row.controls.append(chip)

    def _on_search(e=None, *, submit=False):
        text = search_field.value or ""
        # Address lookup is an EXPLICIT action (Enter/submit), never a
        # per-keystroke fetch: on_change only ever filters the loaded list.
        if not submit and e is not None and getattr(e, "name", "") == "submit":
            submit = True
        if submit:
            try:
                host, port = sb.parse_address(text)
            except ValueError:
                host = None
            if host:
                _run_lookup(host, port)
                return
        rows_state["query"] = text
        rows_state["lookup"] = None
        render()

    search_field.on_change = _on_search

    def _on_submit(e=None):
        _on_search(e, submit=True)

    search_field.on_submit = _on_submit

    def _run_lookup(host: str, port: int):
        key = f"{host}:{port}".lower()
        rows_state["query"] = ""
        rows_state["lookup"] = {
            "name": host, "host": key, "tags": ["lookup"],
            "blurb": "Direct address lookup - live status below.",
            "status": None, "icon": sb.icon_url(key),
        }
        render()

        def worker():
            status = sb.get_status(key, refresh=True)
            entry = rows_state["lookup"]
            if entry and entry["host"] == key:
                entry["status"] = status
                _paint_row(entry)
                thread_safe_ui.refresh(results_col)
                try:
                    show_snack(page, f"{host}: " +
                               (f"{status['players']:,} players online"
                                if status.get("online") else
                                "no answer - it may be offline, or it blocks "
                                "public pings"))
                except Exception:
                    pass  # the row already shows the answer; a snack is a bonus

        threading.Thread(target=worker, daemon=True,
                         name="server-browse-lookup").start()

    # ------------------------------------------------------------------
    # Refresh (tab entry / manual)
    # ------------------------------------------------------------------
    loading = {"value": False}

    def refresh(*, force: bool = False):
        """Paint from cache instantly, then annotate in the background."""
        if loading["value"]:
            return
        loading["value"] = True
        rows_state["loading"] = True

        def worker():
            try:
                entries = sb.browse()  # cached hosts stay cheap
                rows_state["entries"] = entries
                # A first paint: build rows so the user sees the catalogue
                # immediately, then fill the numbers in as they resolve.
                render()
                for entry in rows_state["entries"]:
                    _paint_row(entry)
                thread_safe_ui.refresh(results_col)
                # Second pass: force a network refresh when asked (the
                # manual refresh button) - statuses are TTL-cached inside
                # server_browse, so this never hammers the endpoints.
                if force:
                    with ThreadPoolExecutor(max_workers=6) as pool:
                        futures = {pool.submit(
                            lambda h=entry["host"]:
                            sb.get_status(h, refresh=True)): entry
                            for entry in rows_state["entries"]}
                        for fut, entry in futures.items():
                            try:
                                entry["status"] = fut.result(timeout=30)
                            except Exception:
                                pass  # keep last-known
                    rows_state["lookup"] = None
                    render()
            finally:
                loading["value"] = False
                rows_state["loading"] = False

        threading.Thread(target=worker, daemon=True,
                         name="server-browse-refresh").start()

    refresh_button = attach_hover(
        ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.REFRESH_ROUNDED, size=15,
                                    color=TEXT_DIM),
                            ft.Text("Refresh", size=12.5, color=TEXT_DIM)],
                           spacing=6),
            bgcolor=SURFACE_HI, border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
        ),
        SURFACE_HI, ROW_HOVER,
    )
    refresh_button.on_click = lambda e: (rows_state.update(lookup=None),
                                         refresh(force=True))

    # ------------------------------------------------------------------
    # Assembly
    # ------------------------------------------------------------------
    view = ft.Column(
        [
            ft.Row(
                [
                    ft.Text("Browse servers", size=28, color=TEXT,
                            font_family=FONT_DISPLAY),
                ],
                spacing=10,
            ),
            ft.Text("Live player counts from free public status APIs · "
                    "click a server's address to copy it · JOIN launches "
                    "the game straight into the server",
                    size=12, color=TEXT_FAINT),
            ft.Container(height=8),
            ft.Row([search_field, refresh_button], spacing=10),
            chips_row,
            ft.Container(height=4),
            status_line,
            ft.Container(height=2),
            ft.Container(content=results_col, expand=True,
                         border=ft.border.Border.all(1, BORDER),
                         border_radius=RADIUS, bgcolor=SURFACE,
                         padding=ft.padding.Padding.all(10)),
        ],
        spacing=4,
        expand=True,
    )

    return view, refresh
