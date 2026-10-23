"""
Cubeon - Play tab version management UI.

The Play tab's "manage my versions" surface used to be built inline in
``main()`` across ~350 lines: the Game-version button and its search dialog,
the "Jump back in" instance cards, and the rename/delete actions on the hero.
This module keeps that one concern in one place and lets ``cubeon/instances.py``
feed all of it the same descriptor dict.

  * ``VersionPicker``    - the Game-version button + its dialog. Rows are
    grouped Installed / Available and tagged with the loader, a snapshot
    badge and (online) the release date; a "Latest release" shortcut jumps
    straight to the current release.
  * ``InstanceCards``    - the "Jump back in" row: one art card per installed
    instance, now carrying loader + mod-count + last-played chips.
  * ``InstancesManager`` - a dialog listing every installed instance with its
    loader, mod count, on-disk size (computed off-thread) and last-played
    time, plus per-row Play / Rename / Delete.

All three are pure view code: they take callbacks and descriptor dicts in and
never reach for the config, the network or the game dir themselves. That keeps
them cheap to unit-test and free of the import cycle that would come from
importing ``launcher_core`` here.
"""
import threading

import flet as ft

from cubeon.theme import (
    RADIUS, ACCENT, ACCENT_TINT, TEXT, TEXT_DIM, TEXT_FAINT,
    SURFACE, SURFACE_HI, BORDER, CARD_FILL, CARD_BORDER, DANGER,
    FONT_MONO, section_label,
)
from cubeon import dialogs as cubeon_dialogs
from cubeon import instances as instance_info
from cubeon import thread_safe_ui

# Version art keeps a slightly rounder corner than the 8px controls.
ART_RADIUS = 12


def _chip(label, *, accent=False, danger=False):
    """A small mono tag used on picker rows and instance cards."""
    if danger:
        color, bg = DANGER, ft.Colors.with_opacity(0.14, DANGER)
    elif accent:
        color, bg = ACCENT, ACCENT_TINT
    else:
        color, bg = TEXT_DIM, SURFACE_HI
    return ft.Container(
        content=ft.Text(label, size=10, color=color,
                        weight=ft.FontWeight.W_600, font_family=FONT_MONO),
        bgcolor=bg, border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=7, vertical=2),
    )


def _group_header(text):
    return ft.Container(content=section_label(text),
                        padding=ft.padding.Padding.only(left=4, top=8, bottom=2))


def format_release(value) -> str:
    """A short, sortable-looking date for the picker's right column.

    Accepts the ISO string Mojang ships (``2024-06-13T...``) or an epoch
    number; anything else is shown as-is. Empty for None.
    """
    if not value:
        return ""
    if isinstance(value, (int, float)):
        import time
        try:
            return time.strftime("%Y-%m-%d", time.localtime(value))
        except (OSError, ValueError):
            return ""
    text = str(value)
    return text[:10] if len(text) >= 10 else text


# =====================================================================
# VERSION PICKER - the Game-version button and its dialog
# =====================================================================
class VersionPicker:
    """The compact "Game version" button plus the search dialog behind it.

    The real ``ft.Dropdown`` stays the source of truth in ``main`` (dozens of
    paths read/write it); this only draws its face and the dialog. The dialog
    keeps its OWN filtered copy of the list, so typing in the search box can
    never move the selection or start a download - a bug the previous inline
    implementation had.
    """

    def __init__(self, page, *, get_selected, label_for, on_pick, on_browse_online,
                 on_manage=None):
        self.page = page
        self.get_selected = get_selected
        self.label_for = label_for or (lambda _v: None)
        self.on_pick = on_pick
        self.on_browse_online = on_browse_online
        self.on_manage = on_manage

        self._entries: list = []
        self._online = False
        self._latest = None

        self.label = ft.Text("No versions installed yet", size=14, color=TEXT_DIM,
                             font_family=FONT_MONO, expand=True)

        self.button = ft.Container(
            content=ft.Row(
                [self.label, ft.Icon(ft.Icons.ARROW_DROP_DOWN_ROUNDED, size=18,
                                     color=TEXT_DIM)],
                spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=SURFACE_HI,
            border=ft.border.Border.all(1, BORDER),
            border_radius=RADIUS,
            height=48,
            padding=ft.padding.Padding.symmetric(horizontal=12),
            ink=False,
            tooltip="Pick a Minecraft version",
            on_click=lambda e: self.open(),
        )

        self.filter_field = ft.TextField(
            hint_text="Filter versions... e.g. 1.20",
            border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
            bgcolor=SURFACE_HI, border_radius=RADIUS, height=44, text_size=13,
            content_padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            on_change=lambda e: self.rebuild(),
            visible=False,  # only worth showing once there's a long online list
        )

        self.offline_notice = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.WIFI_OFF_ROUNDED, color=TEXT_DIM, size=14),
                 ft.Text("No internet. Showing installed versions only.",
                         size=12, color=TEXT_DIM)],
                spacing=8,
            ),
            visible=False,
        )

        self.latest_chip = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.STAR_ROUNDED, color=ACCENT, size=13),
                 ft.Text("Latest release", size=12, color=ACCENT,
                         weight=ft.FontWeight.W_600)],
                spacing=6,
            ),
            on_click=lambda e: self._pick(self._latest),
            ink=False,
            visible=False,
        )

        self.browse_link = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.CLOUD_DOWNLOAD_ROUNDED, color=ACCENT, size=14),
                 ft.Text("Browse all versions \u2192", size=12, color=ACCENT,
                         weight=ft.FontWeight.W_600)],
                spacing=8,
            ),
            on_click=lambda e: self._browse(),
            ink=False,
        )

        # "Manage installed versions" lives here, not in the Jump back in
        # header: the Play tab's Jump back in is a row of cards, and the
        # manager belongs next to the other version controls (2026-10-16).
        self.manage_link = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.TUNE_ROUNDED, color=TEXT_DIM, size=14),
                 ft.Text("Manage installed versions", size=12, color=TEXT_DIM,
                         weight=ft.FontWeight.W_600)],
                spacing=8,
            ),
            on_click=lambda e: self._manage(),
            ink=False,
            tooltip="Manage installed versions",
        )

        self.list = ft.ListView([], spacing=2, scroll=ft.ScrollMode.AUTO, height=320,
                                cache_extent=320)

        self.dialog = ft.AlertDialog(
            modal=False, bgcolor=SURFACE,
            title=ft.Text("Game version", color=TEXT, weight=ft.FontWeight.W_800),
            content=ft.Container(
                width=460,
                content=ft.Column(
                    [
                        self.filter_field,
                        ft.Container(height=4),
                        self.list,
                        ft.Container(height=6),
                        ft.Row(
                            [self.latest_chip, self.offline_notice,
                             ft.Container(expand=True), self.manage_link,
                             self.browse_link],
                            spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                    ],
                    spacing=4, tight=True,
                ),
            ),
        )

    # -- state fed in by main -----------------------------------------
    def set_source(self, entries, *, online, latest=None):
        """Replace the list this dialog filters and rebuild its rows.

        No ``page.update()`` here on purpose: callers may be mid-paint, and the
        dialog usually isn't even open yet. ``open()`` / ``rebuild()`` flush.
        """
        self._entries = list(entries or [])
        self._online = bool(online)
        self._latest = latest
        self.filter_field.value = ""
        self.filter_field.visible = bool(online)
        self.offline_notice.visible = False
        self.latest_chip.visible = bool(online and latest)
        self._render_rows()

    def set_offline(self):
        """The online fetch failed: say so and hide the filter."""
        self.filter_field.visible = False
        self.offline_notice.visible = True
        self.latest_chip.visible = False

    def sync_label(self):
        """Mirror the dropdown's current value onto the button's label."""
        val = self.get_selected()
        label = self.label_for(val) if val else None
        self.label.value = (label or val or "No versions installed yet")
        self.label.color = TEXT if (label or val) else TEXT_DIM

    # -- interaction ---------------------------------------------------
    def open(self):
        self.filter_field.value = ""
        self._render_rows()
        cubeon_dialogs.open_dialog(self.page, self.dialog)

    def rebuild(self):
        self._render_rows()
        self.page.update()

    def _browse(self):
        if self.on_browse_online:
            self.on_browse_online()
        self.rebuild()

    def _manage(self):
        """Open the Instances manager. Closes this picker first so the two
        dialogs never stack (the manager is opened from main via on_manage)."""
        cubeon_dialogs.close_dialog(self.page, self.dialog)
        if self.on_manage:
            try:
                self.on_manage()
            except Exception:
                pass

    def _pick(self, key):
        if not key:
            return
        cubeon_dialogs.close_dialog(self.page, self.dialog)
        if self.on_pick:
            self.on_pick(key)

    def _row(self, entry, selected):
        text = entry.get("text") or entry.get("id") or ""
        chips = []
        if entry.get("incomplete"):
            chips.append(_chip("incomplete", danger=True))
        elif entry.get("loader") and entry["loader"] != "vanilla":
            chips.append(_chip(entry.get("loader_label") or entry["loader"], accent=True))
        if entry.get("type") == "snapshot":
            chips.append(_chip("snapshot"))
        date = format_release(entry.get("release_time"))
        tail = [ft.Text(date, size=10.5, color=TEXT_FAINT, font_family=FONT_MONO)] if date else []
        return ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECK_ROUNDED if selected else ft.Icons.CIRCLE,
                            size=12, color=ACCENT if selected else "transparent"),
                    ft.Text(text, size=13, expand=True,
                            color=TEXT if selected else TEXT_DIM,
                            weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_400),
                    *chips,
                    *tail,
                ],
                spacing=8,
            ),
            bgcolor=ACCENT_TINT if selected else None,
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
            ink=False,
            on_click=lambda e, k=entry.get("id"): self._pick(k),
            animate=100,
        )

    def _render_rows(self):
        query = (self.filter_field.value or "").strip().lower()

        def matches(e):
            if not query:
                return True
            return (query in (e.get("id") or "").lower()
                    or query in (e.get("text") or "").lower())

        installed = [e for e in self._entries if e.get("installed") and matches(e)]
        available = [e for e in self._entries if not e.get("installed") and matches(e)]

        selected = self.get_selected()
        # Only label the groups once there's something to distinguish them:
        # in offline mode every entry is installed and a lone "Installed"
        # heading is just noise.
        show_headers = bool(self._online and installed and available)
        rows = []
        if installed:
            if show_headers:
                rows.append(_group_header("Installed"))
            rows += [self._row(e, e.get("id") == selected) for e in installed]
        if available:
            if show_headers:
                rows.append(_group_header("Available to download"))
            rows += [self._row(e, e.get("id") == selected) for e in available]

        if not rows:
            rows.append(ft.Container(
                content=ft.Text(
                    ("No versions match your search." if query else
                     "No versions here yet. Press \u201cBrowse all versions\u201d "
                     "to load the online list."),
                    size=12, color=TEXT_DIM),
                padding=ft.padding.Padding.symmetric(horizontal=10, vertical=16),
            ))
        self.list.controls = rows


# =====================================================================
# INSTANCE CARDS - the "Jump back in" row
# =====================================================================
class InstanceCards:
    """One art card per installed version, carrying loader / mods / last-played.

    Cards are built ONCE and afterwards only RESTYLED (selection), have their
    non-image chip row refreshed, or get their name label edited in place. A
    rebuilt ``ft.Image`` is a brand-new control, so Flet re-sends its whole
    base64 payload and every thumbnail in the row reloads - see
    tools/test_version_art_cache.py.

    For the same reason the row's ``controls`` list is only ever MUTATED, never
    reassigned: assigning a non-equal list lands in Flet's ``__changes`` and is
    patched as a whole-list replace, which re-serialises every child (and thus
    every thumbnail). In-place mutation is diffed child by child, so adding,
    removing or reordering one card leaves the other images untouched.
    """

    def __init__(self, page, *, get_metas, get_labels, get_selected, on_select,
                 art_src, request_art):
        self.page = page
        self.get_metas = get_metas
        self.get_labels = get_labels
        self.get_selected = get_selected
        self.on_select = on_select
        self.art_src = art_src
        self.request_art = request_art

        self.row = ft.Row([], spacing=14, scroll=ft.ScrollMode.AUTO)
        self.empty = ft.Text(
            "No versions installed yet - pick one above and press Play.",
            size=12, color=TEXT_DIM, visible=False,
        )
        self._widgets: dict = {}    # version_id -> (card, art)
        self._chips: dict = {}      # version_id -> the chip Row control
        self._names: dict = {}      # version_id -> the name the card was drawn with
        self._name_controls: dict = {}  # version_id -> the card's name ft.Text
        self._order = None          # the installed set/order the row holds
        self._selected_styled = None
        # rebuild() is reachable from MORE than one thread: the Play tab's own
        # selection path runs it on the UI thread, while the install/launch
        # workers repaint through update_hero -> _rescan_installed. Two of
        # those interleaving is what this lock prevents - see rebuild().
        self._lock = threading.Lock()

    def _chip_specs(self, info):
        specs = []
        if info.get("incomplete"):
            specs.append(("incomplete", "danger"))
        if info.get("loader") and info["loader"] != "vanilla":
            specs.append((info.get("loader_label") or info["loader"], "accent"))
        n = info.get("mod_count") or 0
        if n:
            specs.append((f"{n} mod" + ("s" if n != 1 else ""), "plain"))
        played = instance_info.relative_time(info.get("last_played"))
        if played:
            specs.append((played, "plain"))
        return specs

    def _sync_chips(self, chips, info):
        specs = self._chip_specs(info)
        if chips.data == specs:
            return False
        chips.data = specs
        chips.controls = [_chip(lbl, accent=(kind == "accent"),
                                danger=(kind == "danger")) for lbl, kind in specs]
        chips.visible = bool(specs)
        return True

    def _make_card(self, vid, meta, label, name):
        info = instance_info.describe(vid, meta, label)
        base = info["base_version"]
        art = ft.Image(src=self.art_src(base) or "titleimg.jpg",
                       fit=ft.BoxFit.COVER, width=208, height=150)

        def _ready(value, img=art):
            if value and img.src != value:
                img.src = value
                thread_safe_ui.refresh(img)

        try:
            self.request_art(base, _ready)
        except Exception:
            pass

        chips = ft.Row([], spacing=6, run_spacing=4, wrap=True)
        self._sync_chips(chips, info)
        name_text = ft.Text(name, size=13.5, color=TEXT,
                            weight=ft.FontWeight.W_600, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS)
        card = ft.Container(
            content=ft.Column(
                [
                    ft.Container(content=art, height=150,
                                 clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                                 border_radius=ft.BorderRadius(
                                     top_left=ART_RADIUS, top_right=ART_RADIUS,
                                     bottom_left=0, bottom_right=0)),
                    ft.Container(
                        content=ft.Column(
                            [
                                name_text,
                                ft.Text(base, size=10.5, color=TEXT_FAINT,
                                        font_family=FONT_MONO, max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                chips,
                            ],
                            spacing=3, tight=True,
                        ),
                        padding=ft.padding.Padding.symmetric(horizontal=10, vertical=9),
                    ),
                ],
                spacing=0, tight=True,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            width=210,
            bgcolor=CARD_FILL,
            border=ft.border.Border.all(1, CARD_BORDER),
            border_radius=ART_RADIUS,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            ink=False,
            tooltip=f"Select {name}",
            on_click=lambda e, k=vid: self.on_select(k),
        )
        return card, art, chips, name_text

    @staticmethod
    def _style(card, selected):
        card.bgcolor = ACCENT_TINT if selected else CARD_FILL
        card.border = ft.border.Border.all(1, ACCENT if selected else CARD_BORDER)

    def rebuild(self):
        """Sync the row with the installed set.

        Serialized on this object: dropped ids are popped from the dicts
        BEFORE the row is assembled from them, so an interleaved pair of calls
        (a background install/launch rescan racing the UI thread's own repaint
        - both are real, see the _lock comment in __init__) used to raise
        KeyError on the id the other call had just popped, taking the whole
        repaint - and the exception handler that ran it - down with it.
        """
        with self._lock:
            self._rebuild()

    def _rebuild(self):
        metas = self.get_metas() or {}
        labels = self.get_labels() or {}
        touched = False
        for gone in [v for v in self._widgets if v not in metas]:
            self._widgets.pop(gone, None)
            self._chips.pop(gone, None)
            self._names.pop(gone, None)
            self._name_controls.pop(gone, None)
            touched = True
        for vid in metas:
            meta = metas.get(vid, {})
            label = labels.get(vid)
            name = label or meta.get("display_name") or vid
            if vid not in self._widgets:
                card, art, chips, name_text = self._make_card(
                    vid, meta, label, name)
                self._widgets[vid] = (card, art)
                self._chips[vid] = chips
                self._names[vid] = name
                self._name_controls[vid] = name_text
                touched = True
                continue
            if self._names.get(vid) != name:
                # Rename only: edit the label in place. Re-creating the card
                # would build a new ft.Image, and Flet cannot diff that - it
                # re-sends the base64 art and every thumbnail in the row
                # visibly reloads. See the class docstring.
                self._name_controls[vid].value = name
                self._widgets[vid][0].tooltip = f"Select {name}"
                self._names[vid] = name
                thread_safe_ui.refresh(self._widgets[vid][0])
            if self._sync_chips(self._chips[vid],
                                instance_info.describe(vid, meta, label)):
                thread_safe_ui.refresh(self._chips[vid])
        order = list(metas)
        if order != self._order:
            self._order = order
            touched = True
        if touched:
            cards = [self._widgets[vid][0] for vid in order]
            # Mutate the existing list: reassigning it is tracked as a
            # structural change and patched as a full-list replace, which
            # re-serialises every card (and every image) even when only one
            # card was added or moved. In-place mutation lets Flet's keyed
            # list diff touch only the children that actually changed.
            if list(self.row.controls) != cards:
                self.row.controls[:] = cards
            self.row.visible = bool(cards)
            self.empty.visible = not cards
            thread_safe_ui.refresh(self.row)
            thread_safe_ui.refresh(self.empty)
            self._selected_styled = None
        selected = self.get_selected()
        if selected != self._selected_styled:
            self._selected_styled = selected
            for vid, (card, _art) in self._widgets.items():
                self._style(card, vid == selected)
                thread_safe_ui.refresh(card)


# =====================================================================
# INSTANCES MANAGER - one dialog to see and manage every install
# =====================================================================
class InstancesManager:
    """A dialog listing every installed instance with its loader, mod count,
    on-disk size and last-played time, plus per-row Play / Rename / Delete.

    Opened from the version picker's "Manage installed versions" link (it used
    to hang off a "Manage" button in the Play tab's Jump back in header; that
    was removed 2026-10-16).

    The size walk is the one expensive thing here, so it runs on a worker
    thread and fills its labels in afterwards - the dialog opens instantly.
    """

    def __init__(self, page, *, get_instances, get_selected, on_play, on_rename,
                 on_delete):
        self.page = page
        self.get_instances = get_instances
        self.get_selected = get_selected
        self.on_play = on_play
        self.on_rename = on_rename
        self.on_delete = on_delete
        # One dialog, reused: its rows are re-drawn on every open AND after an
        # action taken from a row, so a deleted instance can't linger in a
        # dialog that is still on screen. See refresh().
        self._body: ft.ListView | None = None
        self._dialog: ft.AlertDialog | None = None

    def _row(self, inst, selected):
        vid = inst["id"]
        name = inst["display_name"]
        sub = ft.Row(
            [
                ft.Text(inst["base_version"], size=11, color=TEXT_FAINT,
                        font_family=FONT_MONO),
                _chip(inst["loader_label"],
                      accent=(inst["loader"] != "vanilla")),
            ],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )
        meta_bits = []
        n = inst.get("mod_count") or 0
        if n:
            meta_bits.append(f"{n} mod" + ("s" if n != 1 else ""))
        played = instance_info.relative_time(inst.get("last_played"))
        if played:
            meta_bits.append(f"played {played}")
        if inst.get("incomplete"):
            meta_bits.append("incomplete")

        size_text = ft.Text("\u2026", size=11, color=TEXT_FAINT, font_family=FONT_MONO)

        def _fire(fn, e=None):
            if fn:
                fn(vid)

        return ft.Container(
            content=ft.Row(
                [
                    ft.Column(
                        [
                            ft.Row(
                                [ft.Text(name, size=13.5, color=TEXT,
                                         weight=ft.FontWeight.W_600,
                                         max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                         expand=True),
                                 ft.Container(
                                     content=ft.Text("selected", size=9.5, color=ACCENT,
                                                     weight=ft.FontWeight.W_700,
                                                     font_family=FONT_MONO),
                                     bgcolor=ACCENT_TINT, border_radius=RADIUS,
                                     padding=ft.padding.Padding.symmetric(horizontal=6, vertical=2),
                                     visible=selected),
                                 ],
                                spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            sub,
                            ft.Text("  \u00b7  ".join(meta_bits) if meta_bits else "",
                                    size=11, color=TEXT_FAINT,
                                    visible=bool(meta_bits)),
                        ],
                        spacing=3, tight=True, expand=True,
                    ),
                    size_text,
                    ft.IconButton(ft.Icons.PLAY_ARROW_ROUNDED, icon_color=ACCENT,
                                  icon_size=18, tooltip="Play this instance",
                                  on_click=lambda e, fn=self.on_play: _fire(fn)),
                    ft.IconButton(ft.Icons.DRIVE_FILE_RENAME_OUTLINE_ROUNDED,
                                  icon_color=TEXT_DIM, icon_size=18,
                                  tooltip="Rename", on_click=lambda e, fn=self.on_rename: _fire(fn)),
                    ft.IconButton(ft.Icons.DELETE_OUTLINE_ROUNDED,
                                  icon_color=ft.Colors.with_opacity(0.7, DANGER),
                                  icon_size=18, tooltip="Delete",
                                  on_click=lambda e, fn=self.on_delete: _fire(fn)),
                ],
                spacing=6, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            bgcolor=ACCENT_TINT if selected else SURFACE_HI,
            border=ft.border.Border.all(1, ACCENT if selected else BORDER),
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
        ), size_text, inst

    def _render(self):
        """Re-draw the row list from the LIVE instance listing (and kick off
        the off-thread size walk for the rows just built)."""
        try:
            listing = self.get_instances() or []
        except Exception:
            listing = []
        selected = self.get_selected()
        rows, size_slots = [], []
        for inst in listing:
            row, size_text, meta = self._row(inst, inst["id"] == selected)
            rows.append(row)
            size_slots.append((inst["id"], meta.get("folder") or inst["id"], size_text))
        if not rows:
            rows = [ft.Container(
                content=ft.Text("No versions installed yet.", size=12, color=TEXT_DIM),
                padding=ft.padding.Padding.symmetric(horizontal=4, vertical=16))]
        if self._body is None:
            self._body = ft.ListView([], spacing=8, scroll=ft.ScrollMode.AUTO,
                                     height=420, cache_extent=320)
        self._body.controls = rows
        if size_slots:
            threading.Thread(target=self._fill_sizes, args=(size_slots,),
                             daemon=True).start()

    def _close(self):
        """The Close button: dismiss the dialog AND forget our reference to it.

        Flet keeps a closed-but-not-yet-dismissed dialog in its dialog stack
        and ``show_dialog()`` RAISES for one that is still mounted, so the next
        open() builds a fresh object instead of racing that teardown. The body
        (and the size text controls inside it) is dropped with it - _render()
        always redraws from the live listing.
        """
        if self._dialog is not None:
            cubeon_dialogs.close_dialog(self.page, self._dialog)
        self._dialog = None
        self._body = None

    def _is_mounted(self) -> bool:
        """Is our dialog currently in the page's dialog stack?

        ``show_dialog()`` RAISES for a dialog that is already mounted, so
        open() must not re-show one. Membership is the accurate test: Flet
        removes a barrier-dismissed dialog from its stack WITHOUT clearing
        ``.open``, so the flag alone would report a dismissed dialog as still
        on screen and the Manager would stop reopening (older Flet versions
        have no stack to ask, so the flag is the fallback there).
        """
        stack = getattr(getattr(self.page, "_dialogs", None), "controls", None)
        if stack is None:
            return bool(getattr(self._dialog, "open", False))
        return self._dialog in list(stack)

    def open(self):
        if self._dialog is None:
            self._body = ft.ListView([], spacing=8, scroll=ft.ScrollMode.AUTO,
                                     height=420, cache_extent=320)
            self._dialog = ft.AlertDialog(
                modal=False, bgcolor=SURFACE,
                title=ft.Text("Instances", color=TEXT, weight=ft.FontWeight.W_800),
                content=ft.Container(width=560, content=self._body),
                actions=[ft.TextButton("Close", on_click=lambda e: self._close())],
            )
        self._render()
        if self._is_mounted():
            # Already on screen (a second Manage click): the rows were just
            # redrawn from the live listing, so all that's left is to flush.
            self.page.update()
        else:
            cubeon_dialogs.open_dialog(self.page, self._dialog)

    def refresh(self):
        """Re-draw the rows of the manager dialog that is on screen.

        Called after an action taken from one of those rows (Delete in
        particular): the dialog stays mounted across the action, so without
        this it kept showing the instance that had just been removed - its row
        only went away when the dialog was closed and reopened. A no-op when
        the dialog isn't open (open() always renders from the live listing,
        and _close() drops the reference).
        """
        if self._dialog is None or not getattr(self._dialog, "open", False):
            return
        try:
            self._render()
        except Exception:
            pass
        self.page.update()

    @staticmethod
    def _fill_sizes(slots):
        for vid, folder, text in slots:
            try:
                size = instance_info.instance_size_bytes(vid, folder)
            except Exception:
                size = None
            label = instance_info.format_size(size) or "\u2014"
            try:
                text.value = label
                thread_safe_ui.refresh(text)
            except Exception:
                pass


__all__ = ["VersionPicker", "InstanceCards", "InstancesManager", "format_release"]
