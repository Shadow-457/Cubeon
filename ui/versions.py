"""
Cubeon - Play tab version management UI.

The Play tab's "manage my versions" surface used to be built inline in
``main()`` across ~350 lines: the Game-version button and its search dialog,
the instance list, and the rename/delete actions on the hero. This module
keeps that one concern in one place and lets ``cubeon/instances.py`` feed all
of it the same descriptor dict.

  * ``VersionPicker`` - the Game-version button plus a right-hand slide-in
    panel that lists installed instances with a configurable block/mob icon,
    and can switch to a
    "New instance" view of versions that are not installed yet. Rows are
    tagged with the loader, a snapshot badge and (online) the release date;
    a "Latest release" shortcut jumps straight to the current release.

The panel is deliberately NOT a dialog: a dialog dims the whole launcher and
stacks on top of whatever else is open. The Play tab's version controls belong
beside the hero, so they use the same non-modal sheet as the Account panel.
It is pure view code: it takes callbacks and descriptor dicts in and never
reaches for the config, the network or the game dir itself. That keeps it
cheap to unit-test and free of the import cycle that would come from importing
``launcher_core`` here.
"""
import threading

import flet as ft
from cubeon import i18n

from cubeon.theme import (
    RADIUS, RADIUS_LG, ACCENT, ACCENT_TINT, TEXT, TEXT_DIM,
    TEXT_FAINT, SURFACE, SURFACE_HI, BORDER, DANGER,
    FONT_MONO, FONT_DISPLAY, section_label,
)
from cubeon import instances as instance_info
from cubeon import thread_safe_ui
from cubeon import instance_icons

BANNER_FADE_MS = 180


class VersionBanner:
    """Cross-fade only the backdrop, leaving the Play card's controls mounted."""

    def __init__(self, source="titleimg.jpg"):
        self.source = source
        self.control = ft.AnimatedSwitcher(
            content=self._frame(source),
            transition=ft.AnimatedSwitcherTransition.FADE,
            duration=BANNER_FADE_MS, reverse_duration=BANNER_FADE_MS,
            switch_in_curve=ft.AnimationCurve.EASE_IN_OUT,
            switch_out_curve=ft.AnimationCurve.EASE_IN_OUT,
            expand=True, data="play-banner",
        )

    @staticmethod
    def _frame(source):
        return ft.Container(image=ft.DecorationImage(src=source, fit=ft.BoxFit.COVER))

    def set_source(self, source):
        source = source or "titleimg.jpg"
        with thread_safe_ui.TREE_LOCK:
            if source == self.source:
                return False
            self.source = source
            self.control.content = self._frame(source)
        thread_safe_ui.refresh(self.control)
        return True


def _chip(label, *, accent=False, danger=False):
    """A small mono tag used on picker rows and instance rows."""
    if danger:
        color, bg = DANGER, ft.Colors.with_opacity(0.14, DANGER)
    elif accent:
        color, bg = ACCENT, ACCENT_TINT
    else:
        color, bg = ft.Colors.with_opacity(0.82, TEXT), SURFACE_HI
    return ft.Container(
        content=ft.Text(label, size=11, color=color,
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
# VERSION PICKER - the Game-version button and its side panel
# =====================================================================
class VersionPicker:
    """The compact "Game version" button plus the slide-in panel behind it.

    The real ``ft.Dropdown`` stays the source of truth in ``main`` (dozens of
    paths read/write it); this only draws its face and the panel. The panel
    keeps its OWN filtered copy of the available list, so typing in the search
    box can never move the selection or start a download - a bug the previous
    inline implementation had.

    The panel has two modes:

      * ``installed`` - select-only cards with icon editing and on-disk size
        (walked off-thread), plus "New instance".
      * ``icons``     - 20 blocks or 20 mob heads for the chosen instance.
      * ``new``       - versions that are not installed yet, with search and
        the "Latest release" shortcut.

    It replaces both the old ``AlertDialog`` picker and the separate Instances
    manager dialog: the Play tab's version controls are one non-modal surface.
    """

    PANEL_W = 440
    ANIM_MS = 260
    # Mounted squashed and parked off-screen, exactly like the Account panel:
    # one write opens it, so there is no start-value frame to flush.
    SQUASH = 0.04

    def __init__(self, page, *, get_selected, label_for, on_pick, on_browse_online,
                 get_instances=None, get_pack_name=None, on_open=None,
                 loaders=None, instance_exists=None, get_icon=None, on_set_icon=None):
        self.page = page
        self.get_selected = get_selected
        self.label_for = label_for or (lambda _v: None)
        self.on_pick = on_pick
        self.on_browse_online = on_browse_online
        self.get_instances = get_instances or (lambda: [])
        self.get_pack_name = get_pack_name
        self.on_open = on_open
        self.instance_exists = instance_exists
        self.get_icon = get_icon or (lambda _v: None)
        self.on_set_icon = on_set_icon
        self._icon_version = None
        self._icon_category = 'block'
        # (id, label) pairs. The loader is chosen here, while downloading a
        # NEW instance, and then belongs to that installation (2026-10-26).
        self.loaders = list(loaders or [("vanilla", "Vanilla")])
        self._install_loader = "vanilla"

        self._entries: list = []
        self._online = False
        self._latest = None
        # Two plain modes instead of one crowded list:
        #   "installed" - what you already have, plus one "New instance" button
        #   "new"       - only versions you can still add, with search + latest
        self._mode = "installed"
        self._offline = False
        self._loading = False

        self.label = ft.Text("No versions installed yet", size=14, color=TEXT_DIM,
                             font_family=FONT_MONO, expand=True)

        self.button = ft.Container(
            content=ft.Row(
                [self.label, ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=18,
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
                 ft.Text("Couldn't load versions. Try again in a moment.",
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

        # The ONE way to create an instance: a clear button, not a text link.
        self.browse_link = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.ADD_ROUNDED, color=ACCENT, size=16),
                 ft.Text(i18n.t("New instance"), size=13, color=ACCENT,
                         weight=ft.FontWeight.W_700)],
                spacing=6, tight=True,
            ),
            bgcolor=ACCENT_TINT, border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=14, vertical=9),
            on_click=lambda e: self._browse(),
            ink=False,
        )
        self.back_link = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.ARROW_BACK_ROUNDED, color=TEXT_DIM, size=14),
                 ft.Text(i18n.t("Back"), size=12.5, color=TEXT_DIM, weight=ft.FontWeight.W_600)],
                spacing=6, tight=True,
            ),
            padding=ft.padding.Padding.symmetric(horizontal=8, vertical=6),
            on_click=lambda e: self._back(),
            ink=False,
            visible=False,
        )

        # Install-time loader choice (2026-10-26): shown only in "New
        # instance" mode, because an installed instance's loader is fixed.
        self._loader_chips: dict[str, ft.Container] = {}
        loader_chip_row = ft.Row(spacing=6, run_spacing=6, wrap=True)
        for lid, label in self.loaders:
            chip = ft.Container(
                content=ft.Text(label, size=11.5,
                                weight=ft.FontWeight.W_600),
                data=f"install-loader-{lid}",
                bgcolor=ACCENT_TINT if lid == self._install_loader else SURFACE_HI,
                border=ft.border.Border.all(
                    1, ACCENT if lid == self._install_loader else BORDER),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=10, vertical=6),
                ink=False,
                on_click=lambda e, k=lid: self._set_install_loader(k),
            )
            self._loader_chips[lid] = chip
            loader_chip_row.controls.append(chip)
        self.loader_row = ft.Column(
            [
                ft.Text("1  CHOOSE YOUR LOADER", size=10.5, color=TEXT_DIM,
                        weight=ft.FontWeight.W_600),
                loader_chip_row,
            ],
            spacing=6, tight=True, visible=False,
        )
        self.loader_hint = ft.Text(
            "Vanilla Minecraft, without mods.", size=11, color=TEXT_DIM)
        self.loader_row.controls.append(self.loader_hint)
        self.version_heading = ft.Text(
            "2  CHOOSE A MINECRAFT VERSION", size=10.5, color=TEXT_DIM,
            weight=ft.FontWeight.W_600, visible=False)
        self.install_hint = ft.Text(
            "Select a version, then press Download & Play.",
            size=11, color=TEXT_DIM, visible=False)
        self.retry_link = ft.TextButton(
            i18n.t("Retry"), on_click=lambda e: self._browse(), visible=False)

        # Bounded lazy viewport: the panel is a long list, and building every
        # row at once made opening it visibly hitch on a big install set.
        self.list = ft.ListView([], spacing=2, scroll=ft.ScrollMode.AUTO,
                                expand=True, cache_extent=320,
                                build_controls_on_demand=True)

        self.title = ft.Text("Instances", size=22, color=TEXT,
                             font_family=FONT_DISPLAY, expand=True)
        self.icon_categories = ft.Row([
            ft.TextButton(i18n.t('Blocks'), on_click=lambda e: self._change_icon_category('block')),
            ft.TextButton(i18n.t('Mob heads'), on_click=lambda e: self._change_icon_category('mob')),
        ], visible=False, spacing=8)
        self.subtitle = ft.Text(
            "Switch, rename, or remove an installed instance.",
            size=11.5, color=TEXT_DIM,
        )

        # --- the sheet itself (same choreography as the Account panel) -----
        self.scrim = ft.Container(
            bgcolor=ft.Colors.with_opacity(0.55, "#000000"),
            left=0, top=0, right=0, bottom=0,
            opacity=0, visible=False, ink=False,
            data="versions-scrim",
            on_click=lambda e: self.close(),
            animate_opacity=ft.Animation(200),
        )
        self.panel = ft.Container(
            bgcolor=SURFACE,
            width=self.PANEL_W,
            top=0, bottom=0,
            right=-self.PANEL_W,
            data="versions-panel",
            animate_position=ft.Animation(self.ANIM_MS,
                                          ft.AnimationCurve.EASE_OUT_CUBIC),
            animate_scale=ft.Animation(self.ANIM_MS,
                                       ft.AnimationCurve.EASE_OUT_CUBIC),
            scale=ft.Scale(scale_x=1, scale_y=self.SQUASH,
                           alignment=ft.Alignment.TOP_RIGHT),
            border_radius=ft.BorderRadius(top_left=RADIUS, top_right=0,
                                          bottom_left=RADIUS, bottom_right=0),
            shadow=ft.BoxShadow(
                blur_radius=16,
                color=ft.Colors.with_opacity(0.45, "#000000"),
                offset=ft.Offset(-8, 0),
            ),
            padding=ft.padding.Padding.only(left=22, right=22, top=26, bottom=20),
            content=ft.Column(
                [
                    ft.Row(
                        [
                            self.title,
                            ft.IconButton(
                                icon=ft.Icons.CLOSE_ROUNDED, icon_size=20,
                                icon_color=TEXT_DIM, tooltip=i18n.t("Close"),
                                on_click=lambda e: self.close(),
                            ),
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    self.subtitle,
                    ft.Container(height=6),
                    self.filter_field,
                    self.loader_row,
                    self.offline_notice,
                    self.retry_link,
                    self.version_heading,
                    self.icon_categories,
                    self.list,
                    self.install_hint,
                    ft.Container(height=6),
                    ft.Row(
                        [self.back_link, self.latest_chip,
                         ft.Container(expand=True), self.browse_link],
                        spacing=12,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                ],
                spacing=8,
                expand=True,
            ),
        )

        # `ScrollPage` in the scrolling test has no overlay; a real page does.
        overlay = getattr(page, "overlay", None)
        if overlay is not None:
            overlay.extend([self.scrim, self.panel])

    # -- state fed in by main -----------------------------------------
    def set_source(self, entries, *, online, latest=None):
        """Replace the list this panel filters and rebuild its rows.

        No ``page.update()`` here on purpose: callers may be mid-paint, and the
        panel usually isn't even open yet. ``open()`` / ``rebuild()`` flush.
        """
        self._entries = list(entries or [])
        self._online = bool(online)
        self._latest = latest
        self._offline = False
        self._loading = False
        self.offline_notice.visible = False
        self._apply_mode()
        if self._mode == "new":
            self._render_new()
        elif self.is_open():
            # An install/delete finished while the sheet was open: keep the
            # installed rows in step instead of waiting for the next reopen.
            self._render_installed()
            thread_safe_ui.refresh(self.list)

    def set_offline(self):
        """The online fetch failed: say so and hide the filter."""
        self._offline = True
        self._loading = False
        self.filter_field.visible = False
        self.offline_notice.visible = self._mode == "new"
        self.latest_chip.visible = False
        self.retry_link.visible = self._mode == "new"
        if self._mode == "new":
            self._render_new()
            thread_safe_ui.refresh(self.panel)

    def sync_label(self):
        """Mirror the dropdown's current value onto the button's label."""
        val = self.get_selected()
        label = self.label_for(val) if val else None
        self.label.value = (label or val or "No versions installed yet")
        self.label.color = TEXT if (label or val) else TEXT_DIM

    # -- interaction ---------------------------------------------------
    def _apply_mode(self):
        new = self._mode == "new"
        icons = self._mode == "icons"
        if icons:
            self.title.value = i18n.t('Choose icon')
            self.subtitle.value = 'Pick a block or mob head for this instance.'
        elif new:
            self.title.value = i18n.t('New instance')
            self.subtitle.value = 'Build an instance with the version and loader you want.'
        else:
            self.title.value = 'Instances'
            self.subtitle.value = 'Switch instances or choose their icons.'
        self.icon_categories.visible = icons
        self.filter_field.visible = bool(new and self._online)
        self.loader_row.visible = bool(new)
        self.version_heading.visible = new
        self.install_hint.visible = new
        self.retry_link.visible = bool(new and self._offline)
        self.latest_chip.visible = bool(new and self._online and self._latest)
        self.back_link.visible = new or icons
        self.browse_link.visible = not new and not icons
        self.offline_notice.visible = bool(new and self._offline)

    def _set_install_loader(self, loader_id):
        """Choose the loader for the NEXT download only (2026-10-26)."""
        if loader_id not in self._loader_chips:
            return
        self._install_loader = loader_id
        self.loader_hint.value = {
            "vanilla": "Vanilla Minecraft, without mods.",
            "fabric": "A lightweight loader for Fabric mods.",
            "quilt": "A loader for Quilt-compatible mods.",
            "forge": "For mods and modpacks built for Forge.",
            "neoforge": "For mods and modpacks built for NeoForge.",
        }.get(loader_id, "Use mods made for this loader.")
        for lid, chip in self._loader_chips.items():
            active = lid == loader_id
            chip.bgcolor = ACCENT_TINT if active else SURFACE_HI
            chip.border = ft.border.Border.all(1, ACCENT if active else BORDER)
            chip.content.color = ACCENT if active else TEXT_DIM
            chip.content.weight = (ft.FontWeight.W_700 if active
                                   else ft.FontWeight.W_600)
        thread_safe_ui.refresh(self.loader_row)
        if self._mode == "new":
            self.rebuild()

    def _back(self):
        self._mode = "installed"
        self.filter_field.value = ""
        self._offline = False
        self.offline_notice.visible = False
        self._apply_mode()
        self._render_installed()
        thread_safe_ui.refresh(self.list)

    def is_open(self) -> bool:
        return self.panel.right == 0

    def open(self):
        if self.on_open:
            try:
                self.on_open()
            except Exception:
                pass
        self._mode = "installed"
        self.filter_field.value = ""
        self._offline = False
        self.offline_notice.visible = False
        self._set_install_loader("vanilla")
        self._apply_mode()
        self.sync_label()
        self._render_installed()
        self.scrim.visible = True
        self.scrim.opacity = 1
        self.panel.right = 0
        self.panel.scale = ft.Scale(scale_x=1, scale_y=1,
                                    alignment=ft.Alignment.TOP_RIGHT)
        # Per-control diff, not page.update(): a whole-page update re-syncs
        # every mounted tab and is what made the old dialogs feel heavy.
        thread_safe_ui.refresh(self.scrim)
        thread_safe_ui.refresh(self.panel)

    def close(self, e=None):
        self.panel.right = -self.PANEL_W
        self.panel.scale = ft.Scale(scale_x=1, scale_y=self.SQUASH,
                                    alignment=ft.Alignment.TOP_RIGHT)
        self.scrim.opacity = 0

        def _retire_scrim():
            # If the panel was reopened inside the fade window, the scrim is
            # legitimately visible again - hiding it would leave an open panel
            # with no dim and no click-catcher.
            if self.panel.right != -self.PANEL_W:
                return
            try:
                self.scrim.visible = False
                thread_safe_ui.refresh(self.scrim)
            except Exception:
                pass  # a late scrim hide must never surface as an error

        timer = threading.Timer(0.25, _retire_scrim)
        timer.daemon = True
        timer.start()
        thread_safe_ui.refresh(self.scrim)
        thread_safe_ui.refresh(self.panel)

    def rebuild(self):
        if self._mode == "new":
            self._render_new()
        elif self._mode == 'icons':
            self._render_icons()
        else:
            self._render_installed()
        thread_safe_ui.refresh(self.list)

    def refresh_rows(self):
        """Re-draw the installed rows while the panel is on screen.

        Called after Rename/Delete (including actions taken from a panel row):
        the panel stays mounted, so without this it would keep showing the old
        name or the instance that was just removed.
        """
        if not self.is_open() or self._mode != "installed":
            return
        try:
            self._render_installed()
        except Exception:
            pass
        thread_safe_ui.refresh(self.list)

    def _browse(self):
        self._mode = "new"
        self._loading = True
        self._offline = False
        self._apply_mode()
        self._render_new()
        thread_safe_ui.refresh(self.panel)
        if self.on_browse_online:
            self.on_browse_online()

    def _pick(self, key):
        if not key:
            return
        # Only a NEW download carries a loader choice. Installed instances
        # keep the loader they were created with.
        install_loader = self._install_loader if self._mode == "new" else None
        self.close()
        if self.on_pick:
            if install_loader and install_loader != "vanilla":
                self.on_pick(key, install_loader)
            else:
                self.on_pick(key)

    # -- rows ----------------------------------------------------------
    def _open_icons(self, version_id):
        if not callable(self.on_set_icon):
            return
        with thread_safe_ui.TREE_LOCK:
            self._icon_version = version_id
            self._mode = 'icons'
            current = self.get_icon(version_id)
            self._icon_category = 'mob' if isinstance(current,str) and current.startswith('mob-') else 'block'
            self._apply_mode()
            self._render_icons()
        thread_safe_ui.refresh(self.panel)

    def _change_icon_category(self, category):
        with thread_safe_ui.TREE_LOCK:
            self._icon_category = category
            self._render_icons()
        thread_safe_ui.refresh(self.list)

    def _choose_icon(self, icon_id):
        if not instance_icons.valid(icon_id) or not self._icon_version:
            return
        with thread_safe_ui.TREE_LOCK:
            if self.on_set_icon(self._icon_version,icon_id) is False:
                return
            self._back()
        thread_safe_ui.refresh(self.panel)

    def _render_icons(self):
        current = self.get_icon(self._icon_version)
        tiles=[]
        for icon in instance_icons.CATALOG:
            if icon['category'] != self._icon_category:
                continue
            active = current == icon['id']
            tiles.append(ft.Container(
                data='instance-icon-option-' + icon['id'],
                content=ft.Column([
                    ft.Image(src=icon['src'],width=56,height=64,fit=ft.BoxFit.CONTAIN),
                    ft.Text(icon['name'],size=10,color=ACCENT if active else TEXT_DIM,
                            max_lines=1,overflow=ft.TextOverflow.ELLIPSIS),
                ],spacing=4,horizontal_alignment=ft.CrossAxisAlignment.CENTER,tight=True),
                expand=True,bgcolor=ACCENT_TINT if active else SURFACE_HI,
                border=ft.border.Border.all(1,ACCENT if active else BORDER),
                border_radius=RADIUS,padding=8,tooltip=icon['name'],ink=False,
                on_click=lambda e,key=icon['id']:self._choose_icon(key),
            ))
        self.list.controls[:] = [ft.Row(tiles[i:i+4],spacing=8) for i in range(0,len(tiles),4)]

    def _installed_row(self, inst, selected):
        """Select-only card with a bundled SVG icon and a separate edit click.

        Rename and Delete live on Play. Opening this list never fetches art.
        """
        vid = inst["id"]
        name = inst.get("display_name") or vid
        base = inst.get("base_version") or ""
        loader = inst.get("loader") or "vanilla"
        loader_label = inst.get("loader_label") or "Vanilla"
        if inst.get("incomplete") and name.endswith(" (incomplete)"):
            name = name[:-len(" (incomplete)")]
        # A plain install's display name is just its id ("26.3"); the card
        # reads "Minecraft 26.3" like the reference. A loader/pack/renamed
        # instance keeps its own name.
        title = name
        if not base or name.strip().lower() in {
                str(vid).lower(), str(base).lower()}:
            title = f"Minecraft {base or vid}"
        pack = ""
        if self.get_pack_name:
            try:
                pack = self.get_pack_name(vid) or ""
            except Exception:
                pack = ""
        # "FastClient + Fabric 1.21.11": the pack (when there is one), then the
        # loader and base version. Vanilla keeps it to "Vanilla 1.21.11".
        subtitle = " + ".join(
            part for part in (pack, f"{loader_label} {base}".strip()) if part)

        meta_bits = []
        n = inst.get("mod_count") or 0
        if n:
            meta_bits.append(f"{n} mod" + ("s" if n != 1 else ""))
        played = instance_info.relative_time(inst.get("last_played"))
        if played:
            meta_bits.append(f"played {played}")

        size_text = ft.Text("\u2026", size=10.5, color=TEXT_FAINT,
                            font_family=FONT_MONO)

        thumb = ft.Image(src=instance_icons.source(self.get_icon(vid),loader=loader),
                         fit=ft.BoxFit.CONTAIN,width=104,height=118)
        edit = ft.IconButton(icon=ft.Icons.EDIT_ROUNDED,icon_size=16,icon_color=TEXT_DIM,
                             tooltip=i18n.t('Choose icon'),data='instance-icon-edit-' + vid,
                             on_click=lambda e,v=vid:self._open_icons(v),
                             visible=callable(self.on_set_icon),right=4,top=4)
        art = ft.Container(
            # Keep the card's square region while centering the smaller icon.
            aspect_ratio=1.0,
            bgcolor=SURFACE,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            content=ft.Stack([ft.Container(content=thumb,alignment=ft.Alignment.CENTER,
                                          left=0,right=0,top=0,bottom=0),edit]),
        )

        selected_chip = ft.Container(
            content=ft.Text("selected", size=9, color=ACCENT,
                            weight=ft.FontWeight.W_700,
                            font_family=FONT_MONO),
            bgcolor=ACCENT_TINT,
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=6, vertical=2),
            visible=selected,
        )
        return ft.Container(
            data=f"version-panel-row-{vid}",
            content=ft.Column(
                [
                    art,
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Row(
                                    [
                                        ft.Text(
                                            title, size=14, color=TEXT,
                                            weight=ft.FontWeight.W_700,
                                            max_lines=1,
                                            overflow=ft.TextOverflow.ELLIPSIS,
                                            expand=True),
                                        selected_chip,
                                        _chip("incomplete", danger=True)
                                        if inst.get("incomplete")
                                        else ft.Container(visible=False),
                                    ],
                                    spacing=6,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.Text(subtitle, size=11, color=TEXT_DIM,
                                        max_lines=1,
                                        overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Row(
                                    [ft.Text("  \u00b7  ".join(meta_bits),
                                             size=10.5, color=TEXT_FAINT,
                                             font_family=FONT_MONO,
                                             max_lines=1,
                                             overflow=ft.TextOverflow.ELLIPSIS,
                                             expand=True),
                                     size_text],
                                    spacing=6,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                            ],
                            spacing=2, tight=True,
                        ),
                        padding=ft.padding.Padding.symmetric(
                            horizontal=10, vertical=8),
                    ),
                ],
                spacing=0,
                horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            bgcolor=ACCENT_TINT if selected else SURFACE_HI,
            border=ft.border.Border.all(1, ACCENT if selected else BORDER),
            border_radius=RADIUS_LG,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
            ink=False,
            expand=True,
            on_click=lambda e, v=vid: self._pick(v),
        ), size_text, inst

    def _render_installed(self):
        """Re-draw the installed list from the LIVE instance listing."""
        try:
            listing = self.get_instances() or []
        except Exception:
            listing = []
        selected = self.get_selected()
        cards, size_slots = [], []
        for inst in listing:
            row, size_text, meta = self._installed_row(
                inst, inst["id"] == selected)
            cards.append(row)
            size_slots.append((inst["id"], meta.get("folder") or inst["id"],
                               size_text))
        if cards:
            # Two square art cards per row, like the reference grid. The
            # placeholder keeps a lone last card at half width instead of
            # stretching it across the panel.
            if len(cards) % 2:
                cards.append(ft.Container(expand=True))
            rows = [ft.Row(cards[i:i + 2], spacing=10,
                           vertical_alignment=ft.CrossAxisAlignment.START)
                    for i in range(0, len(cards), 2)]
        else:
            rows = [ft.Container(
                content=ft.Text(
                    "No instances yet. Press \u201cNew instance\u201d to add one.",
                    size=12, color=TEXT_DIM),
                padding=ft.padding.Padding.symmetric(horizontal=10, vertical=16))]
        with thread_safe_ui.TREE_LOCK:
            self.list.controls[:] = rows
        if size_slots:
            threading.Thread(target=self._fill_sizes, args=(size_slots,),
                             daemon=True, name="ux-instance-sizes").start()

    def _row(self, entry, selected):
        text = entry.get("text") or entry.get("id") or ""
        chips = []
        if entry.get("incomplete"):
            chips.append(_chip("incomplete", danger=True))
        elif entry.get("loader") and entry["loader"] != "vanilla":
            chips.append(_chip(entry.get("loader_label") or entry["loader"],
                               accent=True))
        if entry.get("type") == "snapshot":
            chips.append(_chip("snapshot"))
        date = format_release(entry.get("release_time"))
        tail = [ft.Text(date, size=10.5, color=TEXT_FAINT,
                        font_family=FONT_MONO)] if date else []
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

    def _render_new(self):
        query = (self.filter_field.value or "").strip().lower()

        def matches(e):
            if not query:
                return True
            return (query in (e.get("id") or "").lower()
                    or query in (e.get("text") or "").lower())

        available = [e for e in self._entries
                     if e.get("loader", "vanilla") == "vanilla"
                     and not (self.instance_exists(self._install_loader, e["id"])
                              if self.instance_exists else e.get("installed"))
                     and matches(e)]
        self.latest_chip.visible = bool(
            not self._loading and not self._offline and self._latest
            and any(e["id"] == self._latest for e in available))
        rows = [self._row(e, False) for e in available]
        if self._loading:
            rows = [ft.Container(
                content=ft.Row([
                    ft.ProgressRing(width=18, height=18, stroke_width=2, color=ACCENT),
                    ft.Text("Loading Minecraft versions…", color=TEXT_DIM, size=12),
                ], spacing=10), padding=12)]
        if not rows:
            msg = ("No versions match your search." if query else
                   "Loading versions..." if self._online is False
                   and not self.offline_notice.visible
                   else "Nothing new to add.")
            if self.offline_notice.visible:
                msg = "Can't reach the version list right now."
            rows.append(ft.Container(
                content=ft.Text(msg, size=12, color=TEXT_DIM),
                padding=ft.padding.Padding.symmetric(horizontal=10, vertical=16)))
        with thread_safe_ui.TREE_LOCK:
            self.list.controls[:] = rows

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


__all__ = ["VersionBanner", "VersionPicker", "format_release"]
