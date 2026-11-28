"""
Cubeon - Mods tab UI.
Browse mod providers and manage content for the selected instance.

ModsView owns the retained controls and actions for Mods, Resource Packs and
Shaders, and embeds the existing Modpacks host. build_mods_tab() preserves the
launcher's root-control and refresh-callback contract.
"""

import logging
import re
import threading
import time
import weakref
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import flet as ft

import launcher_core as core
from cubeon import cubeonfriends, dialogs, i18n, mod_catalogue, net, rust_engine, scrolling, status_text, storage, thread_safe_ui
from cubeon import eta as cubeon_eta
from cubeon import icons as _icons
from cubeon import instances as instance_info
from cubeon.background_refresh import BackgroundRefresh
from cubeon.content import content_mc_versions
from cubeon.content_checks import check_content
from cubeon.fuzzy_search import search_items
from cubeon.icon_loader import IconLoader
from cubeon.mod_loaders import MOD_CAPABLE_LOADERS
from cubeon.mods import resolve_profile_dir
from cubeon.theme import (
    ACCENT_HI, ACCENT_TINT, CARD_BORDER, CARD_FILL, INFO, ON_ACCENT,
    RADIUS, ROW_HOVER, TEXT_FAINT, animated_switch, attach_hover,
    pixel_divider, quiet_chip,
)
from ui.content_checks import show_content_issues
from ui.content_states import empty_state
from ui.content_tiles import (
    catalogue_views, downloads_label, layout_tiles, loading_tiles, style_tile,
    tile_grid, update_view_action,
)
from ui.image_memory import preview_image
from ui.install_feedback import (
    InstallFeedback, InstallRegistry, action_text, compact_status, progress_text,
)
from ui.project_readme import readme_markdown


@dataclass(frozen=True)
class InstalledSnapshot:
    """One worker read, including the instance's verified on-disk loader."""

    target: tuple
    items: list
    mods: list | None
    instance_loader: str | None


def batch_progress_text(value: float, total: float, eta: "str | None" = None) -> str:
    """The download label for one batch of files.

    A single click can install several files: a mod plus its required
    dependencies (Sodium -> Fabric API) are reported by the core as ONE batch
    counted in FILE UNITS - int(value) files are already done, so int(value)+1
    is the file being fetched now. Saying "file 2/3" is what stops a
    multi-file install from reading as a stuck 0-100 loop, and the percent is
    still of the WHOLE batch, so it never falls back to 0 between files.

    `eta` is the measured "~2m left" from cubeon/eta.py, appended when the
    estimate is worth showing (see that module for why it often is not).
    """
    files = int(total) if total else 1
    pct = int(value * 100 / total) if total else 0
    left = f" · {eta}" if eta else ""
    if files <= 1:
        return f"Downloading… {pct}%{left}"
    now = min(int(value) + 1, files)
    return f"Downloading… {pct}% (file {now}/{files}){left}"


def mod_compatibility_note(mod: dict, mc_version: str | None, loader: str | None) -> str:
    if mod.get("source") == "horizon":
        if loader != "rust":
            return "Choose a Cubeon Rust instance for Horizon content mods."
        return mod.get("compatibility_reason") or ""
    if loader not in MOD_CAPABLE_LOADERS:
        return "Choose a mod loader on the Play tab."
    if mod.get("compatibility_target") == [mc_version, loader] and mod.get("compatible") is False:
        return f"No matching build for Minecraft {mc_version} / {loader.title()}."
    return ""


class ModsView:
    """Own the retained content controls, instance state and Mods actions.

    File/catalogue operations stay in the existing Cubeon services; this view
    coordinates their workers and paints through the shared UI lock. Row and
    detail callbacks capture their own install target and shared feedback job.
    """

    def __init__(self, page: ft.Page, cfg: dict, state: dict, version_dropdown: ft.Dropdown, *,
                        section_label,
                        BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                        TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO,
                        switch_loader=None, modpacks_content=None, on_modpacks_open=None,
                        on_client_mod_change=None):
        self.page = page
        self.cfg = cfg
        self.state = state
        self.version_dropdown = version_dropdown
        self.section_label = section_label
        self.BG = BG
        self.SURFACE = SURFACE
        self.SURFACE_HI = SURFACE_HI
        self.BORDER = BORDER
        self.ACCENT = ACCENT
        self.ACCENT_DIM = ACCENT_DIM
        self.TEXT = TEXT
        self.TEXT_DIM = TEXT_DIM
        self.DANGER = DANGER
        self.FONT_DISPLAY = FONT_DISPLAY
        self.FONT_MONO = FONT_MONO
        self.switch_loader = switch_loader
        self.modpacks_content = modpacks_content
        self.on_modpacks_open = on_modpacks_open
        self.on_client_mod_change = on_client_mod_change

        self._build_installed_controls()
        self._build_browse_controls()
        self._build_content_layout()

    def _build_installed_controls(self):
        """Create installed cards, shared refresh service and local file picker."""
        self.mods_list_view = tile_grid()
        self.installed_count_text = ft.Text("", size=12, color=self.TEXT_DIM, font_family=self.FONT_MONO,
                                       max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.installed_show_all = {"value": False}
        self.installed_limit = {"value": 50}
        self.installed_snapshots = {}
        self.installed_snapshot_at = {}
        self.installed_match_sets = {}
        self.instance_loaders = {}
        self._installed_pending_target = None
        self._rendered_installed_context = None
        self.INSTALLED_CACHE_SECONDS = 15
        self.artwork = IconLoader()
        self.local_install_busy = False
        self.picker_target = None
        self.installed_rows = {}
        self.installed_collisions = set()
        self.browse_rows = {}
        self.install_registry = InstallRegistry()

        # Row-action feedback line (under the Installed header): toggle/remove
        # failures used to raise out of the click handler, which Flet swallows -
        # the switch/delete just looked dead. Surface the reason instead.
        self.installed_status = ft.Text("", size=11.5, color=self.TEXT_DIM,
                                   font_family=self.FONT_MONO, visible=False,
                                   max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)

        # --- Installed-mod icons -------------------------------------------------
        # Installed jars only record their Modrinth *slug* in a sidecar file - the
        # icon the browse row showed isn't stored anywhere. So the installed list
        # renders instantly with a placeholder, then one bulk slug->icon lookup
        # (core.get_mod_icons, session-cached) patches real art in the moment it
        # lands. Manually-dropped jars have no slug and keep the placeholder.
        self.installed_icon_urls = {}   # slug -> icon URL (or None once resolved-and-missing)
        self.pending_icon_holders = {}  # slug -> [placeholder Containers awaiting art]
        self.icon_inflight = set()

        # --- Categories: retired (2026-11-15 user ask) ---------------------------
        # Browse is a plain search grid now: the category chip strip and the Filters
        # popover that held it are gone, so results start higher on screen and the
        # only way to narrow a list is the search field.

        # Filter field to search installed mods by name
        # Typing used to rebuild every row per keystroke (~120 ms with 300 mods
        # installed), which stutters while typing. Restart a short timer on each
        # keystroke and re-filter once it settles - the same debounce the browse
        # search box uses. Enter filters immediately.
        self._filter_timer = None

        self.installed_filter_field = ft.TextField(
            hint_text="Search installed mods...",
            border_color=CARD_BORDER,
            focused_border_color=self.ACCENT_DIM,
            color=self.TEXT,
            hint_style=ft.TextStyle(color=self.TEXT_DIM, size=13),
            text_style=ft.TextStyle(size=13),
            bgcolor=CARD_FILL,
            border_radius=RADIUS,
            height=40,
            dense=True,
            content_padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            on_change=self._schedule_mods_filter,  # Debounced - see above
            on_submit=self._filter_now,            # Enter = filter immediately
        )

        self.installed_refresh = BackgroundRefresh(self._read_installed_snapshot, self._apply_installed_snapshot,
                                             name='mods-refresh', failed=self._installed_failed)

        self.repair_status = ft.Text("", size=11.5, color=self.TEXT_DIM,
                                font_family=self.FONT_MONO, visible=False,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.repair_details = ft.Text("", size=12, color=self.TEXT_DIM, visible=False,
                                 data="mods-check-details", selectable=True,
                                 max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        self.repair_lock = threading.Lock()
        self.AUTO_CHECK_SECONDS = 15 * 60
        self.auto_check_state = {"last": {}}

        self.check_repair_btn = attach_hover(ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.FACT_CHECK_OUTLINED, color=self.TEXT_DIM, size=14),
                 ft.Text(i18n.t("Check compatibility"), color=self.TEXT_DIM, size=12,
                         weight=ft.FontWeight.W_600)], spacing=4, tight=True),
            border=ft.border.Border.all(1, CARD_BORDER), border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=4),
            tooltip="Check for missing dependencies and conflicts on this instance.",
            ink=False, on_click=self.run_mod_repair, data="mods-check-compatibility",
        ), "transparent", ROW_HOVER)

        self.row_actions = set()

        # --- Install from file: lets the user pick a .jar already on their
        # disk and drop it straight into the current profile's mods folder,
        # without needing to find/search it on Modrinth first. ---

        # Hidden while empty - a visible-but-blank Text still occupies a full line,
        # which is what opened a dead band between the segment tabs and search.
        self.local_install_status = ft.Text("", size=12, color=self.TEXT_DIM, visible=False)
        self.local_install_label = ft.Text(i18n.t('Import mods'), color=self.TEXT_DIM, size=12, weight=ft.FontWeight.W_600)

        self.local_mod_file_picker = ft.FilePicker()
        self.local_mod_file_picker.on_result = self.on_local_mod_picked

        # Same version-spanning registration dance used for the profile
        # picture / skin FilePickers in main.py and skin_tab.py - newer Flet
        # self-registers Services, older Flet needs the explicit overlay append.
        _lmf_registered = False
        _lmf_services_list = getattr(self.page, "_services", None)
        _lmf_already_registered = (
            _lmf_services_list is not None
            and hasattr(_lmf_services_list, "_services")
            and self.local_mod_file_picker in _lmf_services_list._services
        )
        _lmf_register_fn = getattr(self.page, "register_service", None)
        if _lmf_already_registered:
            _lmf_registered = True
        elif callable(_lmf_register_fn):
            try:
                _lmf_register_fn(self.local_mod_file_picker)
                _lmf_registered = True
            except Exception:
                _lmf_registered = False
        if not _lmf_registered:
            try:
                if self.local_mod_file_picker not in self.page.overlay:
                    self.page.overlay.append(self.local_mod_file_picker)
            except Exception:
                pass

    def _build_browse_controls(self):
        """Create the retained search grid, provider sessions and detail host."""
        # --- Browse / download section (Modrinth integration) ---

        # Search happens LIVE as you type: a short debounce timer restarts on
        # every keystroke and only the last one actually fires, so typing
        # "sodium" costs one request instead of six. That's what lets the big
        # green "Search" button disappear - there was nothing left for it to do.
        self.mod_search_field = ft.TextField(
            hint_text=i18n.t("Search mods... e.g. sodium, iris, jei"),
            border_color=CARD_BORDER,
            focused_border_color=self.ACCENT_DIM,
            color=self.TEXT,
            hint_style=ft.TextStyle(color=self.TEXT_DIM, size=13),
            text_style=ft.TextStyle(size=13),
            bgcolor=CARD_FILL,
            border_radius=RADIUS,
            height=40,
            dense=True,
            content_padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
            prefix_icon=ft.Icons.SEARCH_ROUNDED,
            on_submit=lambda e: self.run_mod_search(),  # Enter = search immediately
            expand=True,
        )
        self._search_timer = None

        self.mod_search_field.on_change = self._schedule_live_search

        self.browse_results_view = tile_grid()
        self.browse_results_view.scroll_interval = 100
        self.browse_status_text = ft.Text("", size=12, color=self.TEXT_DIM)
        self.browse_status_text.max_lines = 1
        self.browse_status_text.overflow = ft.TextOverflow.ELLIPSIS
        # Popular Mods appends provider pages on demand. Other catalogues use
        # the same batch size with a pager.
        self.BROWSE_PAGE_SIZE = 24  # Stable offsets; viewport changes only lay out tiles.
        self.MAX_BROWSE_PAGES = -(-100 // self.BROWSE_PAGE_SIZE)
        self.browse_state = {
            "results": [],          # items on the page currently rendered
            "page": 0,
            "empty_msg": "",
            "pages": {},            # page_num -> [items] already fetched
            "total_pages": self.MAX_BROWSE_PAGES,
            "token": None,          # (generation, key) these pages belong to
            "paged": True,          # later pages fetch on demand
        }
        self.browse_pager_label = ft.Text("", size=12, color=self.TEXT_DIM, font_family=self.FONT_MONO,
                                    text_align=ft.TextAlign.CENTER, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS)
        self.browse_pager_prev = ft.Container(
            content=ft.Icon(ft.Icons.CHEVRON_LEFT_ROUNDED, size=18, color=self.TEXT),
            padding=8, border_radius=RADIUS, ink=False,
        )
        self.browse_pager_next = ft.Container(
            content=ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=18, color=self.TEXT),
            padding=8, border_radius=RADIUS, ink=False,
        )
        self.browse_retry = ft.TextButton(i18n.t('Retry'), height=32, opacity=0,
                                    disabled=True, on_click=lambda e: self._retry_search(e))
        self.browse_pager_caption = ft.Container(self.browse_pager_label, width=140, alignment=ft.Alignment.CENTER)
        self.browse_pager_spacer = ft.Container(width=64)
        self.browse_load_more = ft.TextButton(i18n.t("Load more"), height=32, visible=False,
                                             on_click=self._load_more_browse)
        self.browse_pager_row = ft.Row(
            [self.browse_pager_spacer, self.browse_pager_prev, self.browse_pager_caption,
             self.browse_pager_next, self.browse_load_more, self.browse_retry],
            alignment=ft.MainAxisAlignment.CENTER, spacing=4, height=40,
        )
        self.browse_title_text = ft.Text(i18n.t("Popular"), size=12, max_lines=1,
                                     overflow=ft.TextOverflow.ELLIPSIS,
                                     color=self.TEXT_DIM, font_family=self.FONT_MONO)
        self.search_scope = {"compatible": True}
        self.browse_scope_text = ft.Text("", size=11.5, color=self.TEXT_DIM)

        # No category filter any more: every browse query uses "" (All). Kept as
        # the single place the data calls read the category from.
        self.active_category = {"value": ""}

        # Reuse one catalogue for all three content types. Mods route through
        # cubeon.mods; resource packs and shaders route through cubeon.content.
        # Each service keeps files isolated to the captured instance profile.
        self.active_content = {"type": "mod"}  # "mod" | "resourcepack" | "shader"
        self.CONTENT_TABS = [("mod", "Mods"), ("resourcepack", "Resource Packs"), ("shader", "Shaders")]

        self.browse_generation = {"value": 0}
        self.browse_inflight = set()
        self.browse_sessions = {}
        self.type_preferences = {}

        self.force_search = {"value": False}

        self._painted_browse = {'key': None}
        self._rendered_browse_context = None
        self._rendered_browse_results = None
        self._rendered_browse_items = []

        self.detail_host = ft.Column(visible=False, expand=True, spacing=16, data="mod-detail-page")
        self.detail_navigation = {"generation": 0}

        self.browse_pager_prev.on_click = self._browse_page_prev
        self.browse_pager_next.on_click = self._browse_page_next

    def _build_content_layout(self):
        """Compose the existing panes, supplied selectors and Modpacks host."""
        # Warning shown when Vanilla is selected - mods never load without a mod
        # loader, so it's better to say that plainly than let the tab look
        # "installed" for nothing.
        self.vanilla_mods_notice = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, color=self.TEXT_DIM, size=14),
                    ft.Text(
                        "Mods need Fabric, Quilt, Forge, or NeoForge. Choose a loader on Play.",
                        size=12, color=self.TEXT_DIM,
                    ),
                ],
                spacing=8,
            ),
            visible=(self.state["mod_loader"] == "vanilla"),
            padding=ft.padding.Padding.symmetric(vertical=8),
        )

        # Shown on the Shaders segment: a shader .zip only does anything if Iris
        # (Fabric) or OptiFine is installed to read it, so say so plainly rather
        # than let a downloaded shader look like it should "just work".
        self.shader_notice_text = ft.Text("", size=12.5, color=self.TEXT_DIM, expand=True)
        self.shader_setup_label = ft.Text("Set up shaders", size=12.5, color=self.ACCENT,
                                     weight=ft.FontWeight.W_700)
        self.shader_setup_btn = ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=15, color=self.ACCENT),
                            self.shader_setup_label], spacing=8, tight=True),
            bgcolor=ACCENT_TINT, border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=16, vertical=8),
            ink=False,
            on_click=lambda e: self._setup_shaders(),
        )
        self.shader_notice = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, color=self.TEXT_DIM, size=14),
                    self.shader_notice_text,
                    self.shader_setup_btn,
                ],
                spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            visible=False,
            padding=ft.padding.Padding.symmetric(vertical=8),
        )

        self.setup_busy = False

        # Tracks the (version, loader) profile the browse section currently
        # reflects, so we only re-fetch recommendations/search when it's
        # actually stale, not on every unrelated refresh_mods_list() call.
        self.browse_profile = {"key": None}

        # --- Browse / Installed view tabs ---------------------------------------
        # One thing on screen at a time: the browse surface (search + results)
        # or the installed list. Switching is instant and free - both panes stay
        # mounted, only their visibility flips, so nothing is rebuilt or
        # re-fetched on toggle.
        self.active_view = {"value": "browse"}  # "browse" | "installed"

        # Context belongs beside the results, leaving one compact search toolbar.
        # Each retained pane owns its label; a control cannot have two parents.
        self.header_title = ft.Text(i18n.t("Mods"), size=26, weight=ft.FontWeight.W_700, color=self.TEXT,
                               font_family=self.FONT_DISPLAY)
        self.header_subtitle = ft.Text("", size=11.5, color=self.TEXT_DIM, max_lines=1,
                                  overflow=ft.TextOverflow.ELLIPSIS)
        self.installed_context = ft.Text("", size=11.5, color=self.TEXT_DIM, max_lines=1,
                                    overflow=ft.TextOverflow.ELLIPSIS)

        self.browse_pane = ft.Column(
            [
                ft.Row([ft.Container(ft.Row([self.browse_title_text,
                                            ft.Text('·', color=TEXT_FAINT),
                                            ft.Container(self.header_subtitle, expand=True)], spacing=8), expand=3),
                        ft.Container(self.browse_status_text, expand=True, alignment=ft.Alignment.CENTER_RIGHT)],
                       height=32, alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
                self.browse_results_view,
                self.browse_pager_row,
            ],
            spacing=8,
            visible=True,
            expand=True,
        )

        # Keep opt-in available after an OFF launch removes the managed client
        # JAR, or before the first launch has installed it.
        self.client_preference_switch = animated_switch(
            value=bool(self.cfg.get('client_mod_enabled', True)), active_color=self.ACCENT, scale=0.85,
            on_change=lambda e: self._change_client_enabled(bool(self.client_preference_switch.value)),
            tooltip='Enable or disable Cubeon Client for all instances on the next launch',
        )
        self.client_preference_switch.data = 'installed-cubeon-client-enabled'
        self.client_preference_row = style_tile(ft.Container(ft.Row([
            ft.Container(ft.Image(src='icon_64.png', width=44, height=44, fit=ft.BoxFit.CONTAIN)),
            ft.Column([ft.Text('Cubeon Client', color=self.TEXT, size=13.5, weight=ft.FontWeight.W_600,
                              max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                       ft.Text('Next launch · All instances', color=self.TEXT_DIM, size=11.5,
                               max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)],
                      spacing=4, expand=True),
            self.client_preference_switch,
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER), visible=False),
            self.SURFACE, self.BORDER, ROW_HOVER)

        self.installed_pane = ft.Column(
            [
                # Match Browse's metadata / grid / fixed-footer rhythm.
                # The row uses an expanding spacer, so it must not set wrap=True
                # (Flutter's wrapped layout cannot host flex children).
                ft.Row(
                    [ft.Container(ft.Row([self.section_label(i18n.t("Installed")),
                                          ft.Text('·', color=TEXT_FAINT),
                                          ft.Container(self.installed_context, expand=True)], spacing=8), expand=3),
                     self.check_repair_btn, ft.Container(self.installed_count_text, expand=True,
                                                    alignment=ft.Alignment.CENTER_RIGHT)],
                    height=32, spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                self.mods_list_view,
                ft.Container(ft.Column([
                    ft.Row([ft.Container(self.installed_status, expand=True),
                            ft.Container(self.repair_status, expand=True, alignment=ft.Alignment.CENTER_RIGHT)],
                           height=18),
                    ft.Container(self.repair_details, height=18),
                ], spacing=4), height=40, data='mods-feedback'),
            ],
            spacing=8,
            visible=False,
            expand=True,
        )

        view_port, browse_host, installed_host, self.select_view = catalogue_views(self.page, self.browse_pane, self.installed_pane)

        self.view_segment_row = ft.Row(spacing=8)

        self._build_view_segment()

        self.selected_content = {'value': 'mod'}

        kinds = [('mod', 'Mods', 'icons/mods.svg')]
        if self.modpacks_content is not None:
            kinds.append(('modpack', 'Modpacks', 'icons/modpacks.svg'))
        kinds.extend([('resourcepack', 'Resource Packs', 'icons/resource-packs.svg'),
                      ('shader', 'Shaders', 'icons/shaders.svg')])
        self.content_buttons = {
            kind: ft.TextButton(
                content=ft.Row([ft.Image(src=icon, width=18, height=18, fit=ft.BoxFit.CONTAIN,
                                        exclude_from_semantics=True), ft.Text(i18n.t(label), size=12,
                                                              weight=ft.FontWeight.W_600)], spacing=8, tight=True),
                height=32, style=self.selector_style(kind == 'mod'),
                on_click=lambda e, t=kind: self.on_content_type_change(t),
                data='content-' + kind,
            ) for kind, label, icon in kinds
        }
        selector_group = ft.Container(
            ft.Row(list(self.content_buttons.values()), spacing=2, tight=True),
            bgcolor=CARD_FILL, border=ft.border.Border.all(1, CARD_BORDER),
            border_radius=RADIUS, padding=4,
        )
        self.content_selector = ft.Row([selector_group], alignment=ft.MainAxisAlignment.CENTER,
                                  scroll=ft.ScrollMode.AUTO, height=42, data='mods-content-selector')

        # Now assemble the Mods tab.
        #
        # Layout rhythm: section -> comfortable gap -> section. The old build
        # wrapped the results AND the installed list in bordered filled panels -
        # boxes around rows that were themselves boxes. Both wrappers are gone:
        # lists float directly on the surface, sections are separated by a single
        # Header action: "Install from file" (ghost button). Named so the local-
        # install worker can park it while an install runs (double-pick guard).
        self.local_install_btn = attach_hover(ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.UPLOAD_FILE_ROUNDED, color=self.TEXT_DIM, size=14),
                 self.local_install_label],
                spacing=4, tight=True,
            ),
            border=ft.border.Border.all(1, CARD_BORDER),
            border_radius=RADIUS,
            height=36, alignment=ft.Alignment.CENTER,
            padding=ft.padding.Padding.symmetric(horizontal=10, vertical=6),
            tooltip="Install from a file on your computer",
            ink=False, on_click=self.open_local_mod_picker,
        ), "transparent", ROW_HOVER)
        self._apply_type_labels()

        # Both search controls remain mounted and retain their query and callbacks.
        self.browse_search_host = ft.Container(self.mod_search_field, expand=True)
        self.installed_search_host = ft.Container(self.installed_filter_field, expand=True,
                                             visible=False, disabled=True)
        self.search_port = ft.Stack([self.browse_search_host, self.installed_search_host],
                               height=40, fit=ft.StackFit.EXPAND, data='mods-search-port')
        search_toolbar = ft.ResponsiveRow([
            ft.Container(self.search_port, col={'xs': 12, 'sm': 8, 'md': 9}),
            ft.Container(ft.Row([self.view_segment_row, self.local_install_btn], spacing=8,
                                alignment=ft.MainAxisAlignment.END),
                         col={'xs': 12, 'sm': 4, 'md': 3}),
        ], breakpoints={'xs': 0, 'sm': 760, 'md': 1050}, spacing=10, run_spacing=6,
           vertical_alignment=ft.CrossAxisAlignment.CENTER, data='mods-search-toolbar')

        self.mods_body = ft.Column(
            [
                search_toolbar,
                # Contextual notices disappear without leaving another toolbar.
                ft.Column(
                    [
                        self.local_install_status,
                        self.vanilla_mods_notice,
                        self.shader_notice,
                    ],
                    spacing=8,
                ),
                view_port,
            ],
            spacing=8,
            expand=True,
        )

        if self.modpacks_content is not None:
            self.modpacks_content.visible = False
        self.catalogue_host = ft.Column([self.content_selector, self.mods_body,
                                   *([self.modpacks_content] if self.modpacks_content is not None else [])],
                                  spacing=10, expand=True, data="mods-catalogue")
        self.mods_tab = ft.Column([self.catalogue_host, self.detail_host], spacing=0, expand=True)
        self.mods_tab.select_content_type = self.on_content_type_change
        self.mods_tab.close_detail = self.close_mod_detail
        pack_tab = getattr(self.modpacks_content, "content", None) or self.modpacks_content
        if getattr(pack_tab, "close_detail", None):
            pack_tab.on_detail_change = self.pack_detail_changed
        self.mods_tab.refresh_client_preference = self.refresh_client_preference

    def _row_key(self, identity):
        return (*self._installed_target(), identity)

    def _remember_row(self, cache, key, entry):
        cache[key] = entry
        if len(cache) > 200:
            cache.pop(next(iter(cache)))

    def _set_installed_status(self, t):
        with thread_safe_ui.TREE_LOCK:
            self.installed_status.value = t
            self.installed_status.tooltip = t
            self.installed_status.visible = True
            thread_safe_ui.refresh(self.installed_status)

    def _art_image(self, url, width=44, height=44, radius=RADIUS):
        cached_source = _icons.peek_src(url)
        image = preview_image(
            src=cached_source if _icons.valid_source(cached_source) else 'icon_64.png',
            width=width, height=height, border_radius=radius,
            fit=ft.BoxFit.COVER, gapless_playback=True,
            data=url,
            error_content=preview_image(src='icon_64.png', width=width, height=height, fit=ft.BoxFit.CONTAIN),
        )
        def ready(source):
            if image.data == url and image.src != source and _icons.valid_source(source):
                image.src = source
                thread_safe_ui.refresh(image)
        if url and not _icons.peek_src(url):
            self.artwork.request(url, ready)
        return image

    def _icon_image(self, url):
        return self._art_image(url)

    def _make_installed_icon(self, m):
        """Embedded pack art, stored project art or a Cubeon logo fallback."""
        slug = (mod_catalogue.identity(m) if m.get("source") in ("curseforge", "horizon") else m.get("slug"))
        holder = ft.Container(
            width=44, height=44, bgcolor=CARD_FILL, border_radius=RADIUS,
            alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )
        url = m.get('icon_url') or (self.installed_icon_urls.get(slug) if slug else None)
        if _icons.valid_source(m.get('icon_source')):
            holder.content = preview_image(src=m['icon_source'], width=44, height=44, fit=ft.BoxFit.COVER,
                                      border_radius=RADIUS, gapless_playback=True,
                                      error_content=preview_image(src='icon_64.png', width=44, height=44))
        elif url:
            holder.content = self._icon_image(url)
        else:
            holder.content = self._art_image(None)
            if slug and slug not in self.installed_icon_urls:
                self.pending_icon_holders.setdefault(slug, []).append(weakref.ref(holder))
        return holder

    def _fetch_missing_icons(self):
        """Fires the bulk icon lookup for any placeholders rendered this pass
        and swaps the art in as each URL arrives. Runs off the UI thread;
        core.get_mod_icons memoises, so repeated refreshes don't re-fetch."""
        with thread_safe_ui.TREE_LOCK:
            slugs = [s for s in self.pending_icon_holders
                     if s not in self.installed_icon_urls and s not in self.icon_inflight]
            self.icon_inflight.update(slugs)
        if not slugs:
            return

        def worker():
            try:
                mr_slugs = [slug for slug in slugs if not slug.startswith(("curseforge:", "horizon:"))]
                got = core.get_mod_icons(mr_slugs) if mr_slugs else {}
                for slug in slugs:
                    if slug.startswith(("curseforge:", "horizon:")):
                        try:
                            got[slug] = (core.get_mod_details(slug) or {}).get("icon_url")
                        except Exception:
                            pass
            except Exception:
                with thread_safe_ui.TREE_LOCK:
                    self.icon_inflight.difference_update(slugs)
                return
            # Mutate the tree under the shared lock (see thread_safe_ui.py):
            # Flet's diff walks the control tree on the loop thread, and this
            # worker's holder swaps must never land mid-walk.
            changed_holders = []
            with thread_safe_ui.TREE_LOCK:
                for s in slugs:
                    url = got.get(s)
                    self.installed_icon_urls[s] = url
                    holders = self.pending_icon_holders.pop(s, [])
                    if not url:
                        continue
                    for holder_ref in holders:
                        holder = holder_ref()
                        if holder is not None:
                            holder.content = self._icon_image(url)
                            changed_holders.append(holder)
                self.icon_inflight.difference_update(slugs)
            for holder in changed_holders:
                thread_safe_ui.refresh(holder)

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception:
            with thread_safe_ui.TREE_LOCK:
                self.icon_inflight.difference_update(slugs)
            logging.getLogger(__name__).warning('icon lookup could not start', exc_info=True)

    def _run_mods_filter(self):
        """The debounce fires on a background thread; the rebuild mutates the
        tree, so take the shared lock (see cubeon/thread_safe_ui.py)."""
        try:
            with thread_safe_ui.TREE_LOCK:
                self._render_installed_snapshot(self._cached_installed())
                scrolling.to_top(self.page, self.mods_list_view)
        except Exception:
            pass

    def _schedule_mods_filter(self, e=None):
        ft.context.disable_auto_update()
        pending = self._filter_timer
        if pending is not None:
            pending.cancel()
        self._filter_timer = threading.Timer(0.15, self._run_mods_filter)
        self._filter_timer.daemon = True
        self._filter_timer.start()

    def _filter_now(self, e=None):
        pending = self._filter_timer
        if pending is not None:
            pending.cancel()
        self._run_mods_filter()

    def installed_slugs(self) -> set:
        """
        Returns a set of identifiers for installed mods. Includes each mod's
        canonical Modrinth slug (recorded in its sidecar meta when downloaded
        from Modrinth), its opaque Modrinth project id (the ONLY identifier a
        modpack manifest leaves behind - pack-installed mods have no slug, so
        without this every pack mod re-read as "not installed" in browse),
        plus a punctuation-free token of its display name, so a
        browse result reads as "already installed" whether it was pulled from
        Modrinth (exact slug match), installed by a modpack (project-id
        match), or dropped in as a local .jar (name-token
        match). Slug-only matching used to miss mods whose Modrinth slug
        differs from the hyphenated display name (e.g. "Mod Menu" -> slug
        "modmenu"), which re-showed the Download button on already-installed
        mods.
        """
        target = self._installed_target('mod')
        items = self.installed_snapshots.get(target, [])
        cached = self.installed_match_sets.get(target)
        if cached is not None and cached[0] is items:
            return cached[1]
        names = set()
        for m in items:
            if m.get("project_id") or m.get("slug"):
                names.add(mod_catalogue.identity(m))
                if m.get("source") in ("curseforge", "horizon"):
                    continue
            if self._is_rust():
                if m.get("mod_id"):
                    names.add("horizon:" + m["mod_id"])
                continue
            inst_slug = (m.get("slug") or "").lower()
            if inst_slug:
                names.add(inst_slug)
            inst_pid = (m.get("project_id") or "").strip()
            if inst_pid:
                names.add(inst_pid.lower())
            token = re.sub(r"[^a-z0-9]+", "", (m.get("display_name") or "").lower())
            if token:
                names.add(token)
            # The filename stem ("sodium-extra-fabric-0.8.7+mc26.1.1" ->
            # "sodium-extra"). CurseForge packs leave NO sidecar - their CDN
            # URLs carry no Modrinth id - so the stem is the only handle on
            # those jars, and it happens to equal Modrinth's compacted slug
            # for every pack mod checked. The raw display-name token above
            # ("sodiumextrafabric087mc2611") never matches anything.
            stem = re.sub(r"[^a-z0-9]+", "", (m.get("stem") or "").lower())
            if stem:
                names.add(stem)
                # Modrinth slugs often carry a loader word the jar's stem has
                # already had peeled ("c2me-fabric" jar -> stem "c2me", but the
                # project's slug is "c2me-fabric"), so register those variants
                # too. Loader-only suffixes, never anything that could collide
                # with a different mod's name.
                for sfx in ("fabric", "forge", "neoforge", "quilt"):
                    names.add(stem + sfx)
        self._cache_matches(target, items, names)
        return names

    def content_installed_tokens(self) -> set:
        """Cached per-instance filenames and recorded project identities.

        Filename tokens also recognize content installed without a sidecar.
        Disabled entries remain installed and can be re-enabled in Installed.
        """
        target = self._installed_target()
        items = self.installed_snapshots.get(target, [])
        cached = self.installed_match_sets.get(target)
        if cached is not None and cached[0] is items:
            return cached[1]
        tokens = set()
        for it in items:
            tokens.add(re.sub(r"[^a-z0-9]+", "", it["display_name"].lower()))
            for identity in (it.get('slug'), it.get('title')):
                if identity:
                    tokens.add(re.sub(r"[^a-z0-9]+", "", identity.lower()))
        self._cache_matches(target, items, tokens)
        return tokens

    def _cache_matches(self, target, items, matches):
        self.installed_match_sets[target] = (items, matches)
        while len(self.installed_match_sets) > 12:
            self.installed_match_sets.pop(next(iter(self.installed_match_sets)))

    def shader_requirement_installed(self) -> bool:
        """True once Iris or OptiFine is present in the current profile - the
        only two things that can actually load a shader pack. Sodium alone
        can't (it needs Iris), so it doesn't count. The Shaders segment's
        'install Iris' notice is only useful before this point, so it retires
        itself instead of nagging someone who already did it."""
        try:
            mods = self._cached_installed('mod')
        except Exception:
            return False
        for m in mods:
            if not m.get('enabled'):
                continue
            name = re.sub(r"[^a-z0-9]+", "", (m.get("display_name") or "").lower())
            stem = str(m.get('stem') or m.get('slug') or '').lower()
            if stem in ('iris', 'optifine', 'oculus') or name.startswith(('iris', 'optifine', 'oculus')):
                return True
        return False

    def _installed_target(self, kind=None):
        if self._is_rust():
            return (kind or self._ct(), rust_engine.VERSION, "rust", self.version_dropdown.value)
        return (kind or self._ct(), self.state.get('selected_mc_version'),
                self.state.get('mod_loader'), self.version_dropdown.value)

    def _cached_installed(self, kind=None):
        return self.installed_snapshots.get(self._installed_target(kind), [])

    def _is_client_mod(self, m):
        name = str(m.get('filename') or '').lower()
        return (name.startswith(('cubeon-client', 'cubeon-friends'))
                or m.get('slug') in ('cubeon-client', 'cubeon-friends'))

    def _installed_display_count(self):
        items = self._cached_installed()
        backups = max(0, sum(self._is_client_mod(m) for m in items) - 1) if self._is_mod() else 0
        return len(items) - backups

    def _change_client_enabled(self, enabled):
        with thread_safe_ui.TREE_LOCK:
            changed = False
            try:
                if self.on_client_mod_change is not None:
                    if self.on_client_mod_change(enabled) is False:
                        raise RuntimeError('Could not save Cubeon Client settings')
                else:
                    existed, previous = 'client_mod_enabled' in self.cfg, self.cfg.get('client_mod_enabled', True)
                    self.cfg['client_mod_enabled'] = bool(enabled)
                    try:
                        core.save_config(self.cfg)
                    except Exception:
                        if existed:
                            self.cfg['client_mod_enabled'] = previous
                        else:
                            self.cfg.pop('client_mod_enabled', None)
                        raise
            except Exception as error:
                self._set_installed_status(f"Could not save Cubeon Client settings: {error}")
            else:
                changed = True
                self._set_installed_status(f"Cubeon Client {'enabled' if enabled else 'disabled'}. "
                                      'Applies to all instances on the next launch.')
            self._render_installed_snapshot(self._cached_installed())
            return changed

    def _client_browse_entry(self):
        if self._is_rust():
            return None
        # A local catalogue entry shares the normal Browse grid. Never alter
        # provider pages/offsets or offer a client for an unsupported profile.
        if (not self._is_mod() or (self.browse_state['page'] != 0 and not self.browse_state.get('infinite'))
                or self.state.get('mod_loader') not in ('fabric', 'quilt', 'forge')
                or cubeonfriends.client_support_status(
                    self.state.get('selected_mc_version'), self.state.get('mod_loader')) is None
                or self.active_category['value'] not in ('', 'utility', 'social')):
            return None
        if any(word not in 'cubeon client cosmetics friends chat hud' for word in self._browse_query().lower().split()):
            return None
        return dict(slug='cubeon-client', title='Cubeon Client', author='Cubeon',
                    description='Cosmetics, friends, chat and HUD controls.', builtin_client=True)

    def _install_client(self, target, feedback):
        with thread_safe_ui.TREE_LOCK:
            if (target != self._installed_target('mod') or not self._is_mod() or not self._can_install('mod') or feedback.busy
                    or target[2] not in ('fabric', 'quilt', 'forge')
                    or cubeonfriends.client_support_status(target[1], target[2]) is None):
                return
            if not self.cfg.get('client_mod_enabled', True) and not self._change_client_enabled(True):
                feedback.finish(error=self.installed_status.value)
                return
            if not feedback.start(text='Installing Cubeon Client...'):
                return

        def worker():
            try:
                profile = resolve_profile_dir(target[1], target[2], target[3])
                if not cubeonfriends.ensure_installed(target[1], target[2], profile):
                    raise RuntimeError('The matching Cubeon Client file is unavailable. Update the launcher and retry.')
                feedback.finish(note='Cubeon Client installed. Available on the next game launch.')
                self._refresh_after_install(target)
            except Exception as error:
                feedback.finish(error=f"Couldn't install Cubeon Client: {error}")

        try:
            threading.Thread(target=worker, daemon=True, name='cubeon-client-install').start()
        except Exception as error:
            feedback.finish(error=f"Couldn't start Cubeon Client installation: {error}")

    def _mod_status(self, m):
        if m.get("issue"):
            return "Unavailable · " + m["issue"]
        if self._is_client_mod(m):
            return f"{'Enabled' if m['enabled'] else 'Disabled'} · Next launch · All instances"
        return f"{m['size_kb']:,.0f} KB  ·  {'Enabled' if m['enabled'] else 'Disabled'}"

    def _read_installed_snapshot(self, target):
        kind, mc, loader, version = target
        if rust_engine.is_instance(version):
            mods = core.list_mods(mc, "rust", version_id=version) if kind == 'mod' else None
            return InstalledSnapshot(target, mods or [], mods, "rust")
        mods = core.list_mods(mc, loader, version_id=version) if kind in ('mod', 'shader') else None
        items = mods if kind == 'mod' else core.list_content(kind, mc, loader=loader, version_id=version)
        # Describe once on the worker, never once per tile while painting.
        meta = (self.state.get('installed_meta') or {}).get(version) or {}
        info = instance_info.describe(version, meta, with_mods=False, play_store={}) if version else {}
        return InstalledSnapshot(target, items, mods, info.get('loader'))

    def _apply_installed_snapshot(self, snapshot, *, render_installed=False):
        target, items, mods = snapshot.target, snapshot.items, snapshot.mods
        if self._installed_pending_target == target:
            self._installed_pending_target = None
        self.instance_loaders[target[3]] = snapshot.instance_loader
        while len(self.instance_loaders) > 12:
            self.instance_loaders.pop(next(iter(self.instance_loaders)))
        self.installed_snapshots[target] = items
        self.installed_snapshot_at[target] = time.monotonic()
        self.installed_match_sets.pop(target, None)
        if mods is not None:
            mod_target = ('mod', *target[1:])
            self.installed_snapshots[mod_target] = mods
            self.installed_snapshot_at[mod_target] = self.installed_snapshot_at[target]
            self.installed_match_sets.pop(mod_target, None)
        while len(self.installed_snapshots) > 12:
            retired = next(iter(self.installed_snapshots))
            self.installed_snapshots.pop(retired)
            self.installed_snapshot_at.pop(retired, None)
            self.installed_match_sets.pop(retired, None)
        if target == self._installed_target():
            self._rendered_installed_context = None
            self._rendered_browse_context = None
            if render_installed or (self.active_view['value'] == 'installed' and self._tab_visible()):
                self._render_installed_snapshot(items)
                if self._tab_visible() and self.active_view['value'] == 'installed':
                    self.auto_check()
            elif self._tab_visible():
                self._apply_type_labels()
                self._build_view_segment()
                self._render_browse_page()

    def _installed_failed(self, error):
        self._installed_pending_target = None
        self._rendered_installed_context = None
        self._set_installed_status(f"Couldn't read installed content: {error}")
        self.mods_list_view.controls[:] = [empty_state('Couldn\'t read installed content',
                                                 'Try refreshing this instance.'),
                                     quiet_chip('Retry', on_click=lambda e: self.refresh_mods_list(background=True))]
        thread_safe_ui.refresh(self.mods_list_view)

    def _install_gate_context(self):
        """Inputs that can change actions without changing catalogue results."""
        target = self._installed_target()
        pending = self.state.get('pending_loader_install') or {}
        return (target, bool(self.cfg.get('client_mod_enabled', True)),
                target[3] in (self.state.get('installed') or set()),
                pending.get('version_id'), pending.get('loader'))

    def _installed_render_context(self):
        return (*self._install_gate_context(),
                self.installed_filter_field.value, self.installed_limit['value'],
                self.local_install_busy, self.picker_target)

    def refresh_mods_list(self, *, background=False, force=False, navigation=False):
        if navigation and (not self._tab_visible() or self.selected_content['value'] == 'modpack'):
            return
        target = self._installed_target()
        if background:
            # Cached rows can paint immediately; filesystem/archive reads stay
            # on the worker even when this callback holds the UI tree lock.
            with thread_safe_ui.TREE_LOCK:
                if (self.active_view['value'] == 'installed' and (not navigation or force or
                        self._rendered_installed_context != self._installed_render_context())):
                    self._render_installed_snapshot(self._cached_installed(), loading=target not in self.installed_snapshots)
                elif (navigation and self._browse_ready() and
                      (self._rendered_browse_context != self._install_gate_context() or
                       self._rendered_browse_results is not self.browse_state['pages'].get(self.browse_state['page']))):
                    self._render_browse_page()
                if (not force and target in self.installed_snapshots and
                        time.monotonic() - self.installed_snapshot_at.get(target, 0) < self.INSTALLED_CACHE_SECONDS):
                    if self.active_view['value'] == 'installed' and self._tab_visible():
                        self.auto_check()
                    return
                if not force and self._installed_pending_target == target:
                    return
                # Browse needs installation badges, not a hidden archive/card
                # scan competing with its first provider responses.
                if navigation and self.active_view['value'] == 'browse' and not self._browse_ready():
                    return
                self._installed_pending_target = target
            try:
                self.installed_refresh.request(target)
            except Exception as error:
                self._installed_pending_target = None
                self._set_installed_status(f"Couldn't refresh installed content: {error}")
            return
        self.installed_refresh.invalidate()
        self._installed_pending_target = None
        snapshot = self._read_installed_snapshot(target)
        with thread_safe_ui.TREE_LOCK:
            self._apply_installed_snapshot(snapshot, render_installed=True)

    def _refresh_after_install(self, target):
        # The installation has already succeeded. A repaint failure must not
        # turn that result into a failed download or encourage a second one.
        try:
            snapshot = self._read_installed_snapshot(target)
            with thread_safe_ui.TREE_LOCK:
                if target == self._installed_target():
                    self.installed_refresh.invalidate()
                self._apply_installed_snapshot(snapshot)
        except Exception:
            logging.getLogger(__name__).warning('post-install refresh failed', exc_info=True)

    def _render_installed_snapshot(self, all_mods, *, loading=False):
        """
        Reloads the installed list for whatever content type is active and
        updates the UI. Mods come from the per-(version, loader) profile;
        resource packs / shaders come from their per-instance content profile.
        Applies the filter from the installed_filter_field.
        """
        # Client availability is a persisted preference, applied at launch.
        # Keep disk snapshots intact for Doctor and dependency checks.
        if self._is_mod():
            clients = [m for m in all_mods if self._is_client_mod(m)]
            client = next((m for m in clients if m.get('enabled')), clients[0] if clients else None)
            displayed, client_added = [], False
            for m in all_mods:
                if self._is_client_mod(m):
                    # A launch can reinstall the current JAR beside an older
                    # .jar.disabled backup. They share one managed preference,
                    # so expose one switch while preserving every disk entry.
                    if not client_added:
                        displayed.append(dict(client, display_name='Cubeon Client',
                                              enabled=bool(self.cfg.get('client_mod_enabled', True)), protected=True))
                        client_added = True
                else:
                    displayed.append(m)
            all_mods = displayed
        names = [m.get('filename', '').removesuffix('.disabled') for m in all_mods]
        self.installed_collisions.clear()
        self.installed_collisions.update(name for name, count in Counter(names).items() if count > 1)
        self._apply_type_labels()
        query = self.installed_filter_field.value.strip().lower()
        mods = search_items(all_mods, query)

        rows = []
        self.installed_count_text.value = 'Checking installed content...' if loading else (
            f"{len(all_mods)} installed" if not query else f"{len(mods)} of {len(all_mods)} shown"
        )

        # If nothing installed, show a placeholder worded for the active type.
        if loading:
            rows.extend(loading_tiles(self.mods_list_view))
        elif not all_mods:
            if self._is_mod():
                empty_icon = ft.Icons.EXTENSION_OFF_ROUNDED
                empty_title = "No mods installed yet"
                empty_hint = "Browse mods or select Import mods to add a JAR."
            else:
                empty_icon = ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED
                empty_title = f"No {core.CONTENT_TYPES[self._ct()]['label_plural'].lower()} installed yet"
                empty_hint = "Find content with search, or import files you already have."
            rows.append(empty_state(empty_title, empty_hint, icon=empty_icon,
                                    action_label="Find content", on_action=lambda e: self.on_view_change("browse")))
        elif not mods:
            # Filter returned no results
            rows.append(
                empty_state("No matching installed content", "Try another filter.")
            )
        else:
            # Build a row for each mod
            # A real scrollable library, independent of window capacity. The
            # native viewport builds nearby rows lazily; More appends in place.
            limit = max(50, self.installed_limit['value'])
            visible_mods = mods[:limit]
            for m in visible_mods:
                rows.append(self.build_installed_row(m))
            if len(mods) > len(visible_mods):
                hidden = len(mods) - len(visible_mods)
                def more(e):
                    self.installed_limit['value'] = len(visible_mods) + 50
                    self.installed_show_all['value'] = True
                    self._render_installed_snapshot(self._cached_installed())
                rows.append(
                    attach_hover(ft.Container(
                        content=ft.Text(
                            f"Show more installed ({hidden} more)",
                            size=12, color=self.ACCENT, weight=ft.FontWeight.W_700,
                        ),
                        padding=ft.padding.Padding.symmetric(vertical=8, horizontal=12),
                        border_radius=RADIUS,
                        ink=False,
                        on_click=more,
                    ), None, self.SURFACE_HI)
                )
        self.mods_list_view.controls[:] = rows
        if self.client_preference_row.visible and not loading and not query:
            if not all_mods:
                rows[:] = []
            rows.append(self.client_preference_row)
            self.mods_list_view.controls[:] = rows
        layout_tiles(self.mods_list_view, bool(mods) or loading or
                     (self.client_preference_row.visible and not query))
        self._fetch_missing_icons()
        # Rebuilt the list: repaint just the list region + count, not the
        # full tree (this fires per keystroke of the installed filter).
        thread_safe_ui.refresh(self.mods_list_view)
        thread_safe_ui.refresh(self.installed_count_text)
        thread_safe_ui.refresh(self.installed_filter_field)
        thread_safe_ui.refresh(self.local_install_btn)
        thread_safe_ui.refresh(self.vanilla_mods_notice)
        thread_safe_ui.refresh(self.shader_notice)
        # Keep the "Installed (N)" tab label in step with reality.
        self._build_view_segment()
        self._rendered_installed_context = self._installed_render_context()

    def _set_repair_status(self, text, detail=None):
        with thread_safe_ui.TREE_LOCK:
            self.repair_status.value = i18n.t(text)
            self.repair_status.visible = bool(text)
            self.repair_status.tooltip = detail
            self.repair_details.value = detail or ""
            self.repair_details.tooltip = detail
            self.repair_details.visible = bool(detail)
            thread_safe_ui.refresh(self.repair_status)
            thread_safe_ui.refresh(self.repair_details)

    def _repair_sections(self):
        return ["mods"] if self._is_mod() else ["shaders" if self._ct() == "shader" else "resourcepacks"]

    def _check_install_issues(self, target, report=None):
        if rust_engine.is_instance(target[3]):
            return
        try:
            report = report if report is not None else check_content(target)
            if report.get("unfixed"):
                show_content_issues(self.page, self.state, target, report)
        except Exception as error:
            logging.getLogger(__name__).warning("post-install compatibility check failed", exc_info=True)
            dialogs.show_snack(self.page, f"Installed, but the compatibility check could not finish: {error}",
                               bgcolor=self.SURFACE_HI, text_color=self.TEXT)

    def _start_repair(self, mc, loader, version_id, sections, *, explicit=False):
        if rust_engine.is_instance(version_id):
            return False
        if (self.state.get("running_version") or self.state.get("installing_version")
                or self.state.get("launching_version") or self.state.get("fixing_mods")):
            if explicit:
                self._set_repair_status("Close the game and finish installs before checking")
            return False
        if not self.repair_lock.acquire(blocking=False):
            return False
        with thread_safe_ui.TREE_LOCK:
            self.check_repair_btn.disabled = True
            thread_safe_ui.refresh(self.check_repair_btn)
        self._set_repair_status("Checking compatibility…")
        target = ("mod" if sections == ["mods"] else "shader" if sections == ["shaders"] else "resourcepack",
                  mc, loader, version_id)

        def done(report):
            if self.version_dropdown.value == version_id and self._repair_sections() == sections:
                self.refresh_mods_list(background=True)
                unresolved = report.get("unfixed") or []
                self._set_repair_status(f"{len(unresolved)} issues need attention" if unresolved else
                    "Mod files checked · loader checks on Play" if report.get("loader_managed") else "Everything is compatible")

        def worker():
            try:
                report = check_content(target)
                unresolved = (report or {}).get("unfixed") or []
                detail = "\n".join(p.get("detail") or p.get("mod") or p.get("item") or "Unknown issue"
                                   for p in unresolved[:10])
                if self.version_dropdown.value == version_id and self._repair_sections() == sections:
                    if unresolved:
                        self._set_repair_status(f"{len(unresolved)} issues need attention", detail)
                        show_content_issues(self.page, self.state, target, report, on_done=done,
                                            on_status=self._set_repair_status)
                    else:
                        label = ("Mod files checked · loader checks on Play" if report.get("loader_managed") else
                                 "Mods checked · runtime checked on Play" if report.get("runtime_unverified") else "Compatible")
                        self._set_repair_status(f"{label} · {report.get('elapsed', 0) * 1000:.0f} ms")
            except Exception as error:
                logging.getLogger(__name__).warning("background content check failed", exc_info=True)
                self._set_repair_status(f"Could not complete this check: {error}")
            finally:
                with thread_safe_ui.TREE_LOCK:
                    self.check_repair_btn.disabled = False
                    thread_safe_ui.refresh(self.check_repair_btn)
                self.repair_lock.release()

        try:
            threading.Thread(target=worker, daemon=True, name="cubeon-content-check").start()
        except Exception:
            self.check_repair_btn.disabled = False
            thread_safe_ui.refresh(self.check_repair_btn)
            self.repair_lock.release()
            raise
        return True

    def run_mod_repair(self, e=None):
        if self._is_rust():
            return
        mc = self.state.get("selected_mc_version")
        loader = self.state.get("mod_loader") or "vanilla"
        version_id = self.version_dropdown.value
        if not mc or not version_id:
            self._set_repair_status("Pick an instance first")
            return
        if self._is_mod() and loader == "vanilla":
            self._set_repair_status("Vanilla runs resource packs, not mods")
            return
        self._start_repair(mc, loader, version_id, self._repair_sections(), explicit=True)

    def auto_check(self, force=False):
        if self._is_rust():
            return
        mc = self.state.get("selected_mc_version")
        loader = self.state.get("mod_loader") or "vanilla"
        version_id = self.version_dropdown.value
        if not mc or not version_id:
            return
        key = (version_id, loader, self._ct())
        last = self.auto_check_state["last"].get(key)
        if not force and last and time.monotonic() - last < self.AUTO_CHECK_SECONDS:
            return
        if self._start_repair(mc, loader, version_id, self._repair_sections()):
            self.auto_check_state["last"][key] = time.monotonic()

    def _compat_lines(self, m):
        """The one-line compatibility verdict for an installed pack/shader.

        Silence means "the game will load it" - a positive line on every row
        would just add noise. A pack the game would show as Incompatible is the
        whole reason this exists, so that one is called out in red with the
        full explanation in a tooltip (and Check & repair fixes supported issues)."""
        compat = m.get("compat")
        if not compat or compat.get("ok") is True:
            return []
        detail = (compat.get("reason") or "").strip()
        if compat.get("ok") is False:
            return [ft.Text(
                "Incompatible — check compatibility",
                size=10.5, color=self.DANGER,
                tooltip=detail or "The game would show this as incompatible.")]
        return [ft.Text(
            "Can't check the format for this version", size=10.5,
            color=TEXT_FAINT, tooltip=detail)]

    def _run_row_action(self, target, row, action, success, *, pending="Applying change…", enabled_before=None):
        ft.context.disable_auto_update()
        # Folder removal and post-action archive scans must not stall Flet.
        key = (target, id(row))
        with thread_safe_ui.TREE_LOCK:
            if key in self.row_actions:
                return
            feedback = InstallFeedback()
            if not feedback.start(text=pending):
                return
            row._action_feedback = feedback
            self.row_actions.add(key)
            # Keep the artwork/text stable while only the actions are parked.
            actions = row.content.controls[2:]
            for control in actions:
                control.disabled = True
            status = row.content.controls[1].controls[1]
            previous_status = status.value
            status.value = pending
            thread_safe_ui.refresh(row)

        def worker():
            action_error = None
            try:
                with storage.update_operation():
                    action()
                message = success
            except Exception as error:
                action_error = error
                message = str(error)
            try:
                snapshot = self._read_installed_snapshot(target)
            except Exception as error:
                snapshot = None
                message += f" Couldn't refresh the list: {error}"
            with thread_safe_ui.TREE_LOCK:
                self.row_actions.discard(key)
                for control in actions:
                    control.disabled = False
                status.value = previous_status
                if action_error is not None and enabled_before is not None:
                    row.content.controls[2].value = enabled_before
                feedback.finish(error=action_error)
                if snapshot is not None:
                    if target == self._installed_target():
                        self.installed_refresh.invalidate()
                    self._apply_installed_snapshot(snapshot)
                if target == self._installed_target():
                    self._set_installed_status(message)
                    thread_safe_ui.refresh(row)

        try:
            threading.Thread(target=worker, daemon=True, name='mods-row-action').start()
        except Exception as error:
            with thread_safe_ui.TREE_LOCK:
                self.row_actions.discard(key)
                for control in actions:
                    control.disabled = False
                status.value = previous_status
                if enabled_before is not None:
                    row.content.controls[2].value = enabled_before
                feedback.finish(error=error)
                self._set_installed_status(f"Couldn't start this action: {error}")
                thread_safe_ui.refresh(row)

    def build_installed_row(self, m):
        """
        Installed items expose per-instance availability and removal.

        Deliberately NOT a boxed card: rows are transparent and lift only on
        hover, so the list reads as one calm surface instead of a stack of
        rectangles inside the enclosing rectangle.
        """
        row_target = self._installed_target()
        identity = m.get('filename') or m.get('id') or m['display_name']
        key = self._row_key(identity if identity.removesuffix('.disabled') in self.installed_collisions
                       else identity.removesuffix('.disabled'))
        cached = self.installed_rows.get(key)
        if cached:
            metadata, row = cached
            pending = (row_target, id(row)) in self.row_actions
            if self._is_mod() and bool(metadata.get("protected")) == bool(m.get("protected")):
                metadata.clear()
                metadata.update(m)
                labels = row.content.controls[1].controls
                labels[0].value = m["display_name"]
                labels[0].color = self.TEXT if m["enabled"] else self.TEXT_DIM
                if not pending:
                    labels[1].value = self._mod_status(m)
                if not pending and (not m.get("protected") or self._is_client_mod(m)):
                    row.content.controls[2].value = m["enabled"]
                    row.content.controls[2].disabled = bool(m.get("issue"))
                    row.content.controls[2].tooltip = m.get("issue")
                row.on_click = (
                    (lambda event, metadata=metadata: self.open_mod_detail(metadata))
                    if not m.get("protected") and (m.get("project_id") or m.get("slug")) else None
                )
                return row
            if metadata == m:
                return row
            if not self._is_mod() and {k: v for k, v in metadata.items() if k not in ('enabled', 'filename')} == {
                    k: v for k, v in m.items() if k not in ('enabled', 'filename')}:
                metadata.clear()
                metadata.update(m)
                labels = row.content.controls[1].controls
                labels[0].color = self.TEXT if m.get('enabled', True) else self.TEXT_DIM
                if not pending:
                    labels[1].value = f"{m['size_kb']:,.0f} KB · {'Enabled' if m.get('enabled', True) else 'Disabled'}"
                    row.content.controls[2].value = m.get('enabled', True)
                row.content.controls[2].tooltip = ('Disable for this instance on next launch' if m.get('enabled', True)
                                                   else 'Enable for this instance on next launch')
                return row
        m = dict(m)
        if not self._is_mod():
            def on_toggle_content(e):
                if row_target != self._installed_target():
                    return
                def action():
                    core.toggle_content(row_target[0], m['filename'], row_target[1], row_target[2],
                                        version_id=row_target[3])
                self._run_row_action(row_target, row, action,
                                f"{'Disabled' if m.get('enabled', True) else 'Enabled'} '{m['display_name']}'.",
                                pending="Disabling…" if m.get('enabled', True) else "Enabling…",
                                enabled_before=m.get('enabled', True))

            def on_delete_content(e):
                if row_target != self._installed_target():
                    self._set_installed_status('This row belongs to another instance. Refresh the list.')
                    return
                def action():
                    core.delete_content(row_target[0], m["filename"], row_target[1],
                                        version_id=row_target[3], loader=row_target[2])
                self._run_row_action(row_target, row, action, f"Removed '{m['display_name']}'.", pending="Removing…")

            row_icon = self._make_installed_icon(m)
            row = style_tile(
                ft.Container(
                    content=ft.Row(
                        [
                            row_icon,
                            ft.Column(
                                [
                                    ft.Text(m["display_name"], size=13.5,
                                            color=self.TEXT if m.get('enabled', True) else self.TEXT_DIM,
                                            weight=ft.FontWeight.W_600, max_lines=1,
                                            overflow=ft.TextOverflow.ELLIPSIS, tooltip=m['display_name']),
                                    ft.Text(f"{m['size_kb']:,.0f} KB · {'Enabled' if m.get('enabled', True) else 'Disabled'}", size=10.5,
                                            color=self.TEXT_DIM, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    *self._compat_lines(m),
                                ],
                                spacing=4, expand=True,
                            ),
                            animated_switch(value=m.get('enabled', True), active_color=self.ACCENT,
                                            on_change=on_toggle_content, scale=0.85,
                                            tooltip='Disable for this instance on next launch' if m.get('enabled', True)
                                            else 'Enable for this instance on next launch'),
                            ft.IconButton(ft.Icons.CLOSE_ROUNDED, icon_color=TEXT_FAINT,
                                          icon_size=17, tooltip=i18n.t("Remove"),
                                          on_click=on_delete_content),
                        ],
                        spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
                ),
                self.SURFACE, self.BORDER, ROW_HOVER,
            )
            self._remember_row(self.installed_rows, key, (m, row))
            return row

        def on_toggle(e):
            if row_target != self._installed_target():
                return
            if self._is_client_mod(m):
                self._change_client_enabled(not m['enabled'])
                return
            if m.get("protected"):
                return  # Cubeon-managed mod - core would refuse anyway
            def action():
                core.toggle_mod(row_target[1], row_target[2], m["filename"],
                                version_id=row_target[3])
            self._run_row_action(row_target, row, action,
                            f"{'Disabled' if m['enabled'] else 'Enabled'} '{m['display_name']}'.",
                            pending="Disabling…" if m['enabled'] else "Enabling…", enabled_before=m['enabled'])

        def on_delete(e):
            if row_target != self._installed_target():
                return
            if m.get("protected"):
                return  # Cubeon-managed mod - core would refuse anyway
            def action():
                core.delete_mod(row_target[1], row_target[2], m["filename"],
                                version_id=row_target[3])
            self._run_row_action(row_target, row, action, f"Removed '{m['display_name']}'.", pending="Removing…")

        row = style_tile(
            ft.Container(
                content=ft.Row(
                    [
                        # Enabled mods read brighter; disabled ones dim. State is
                        # typography, not a colored bar. The icon is the mod's
                        # real Modrinth art once its slug resolves (placeholder
                        # until then - manually-dropped jars have no slug).
                        self._make_installed_icon(m),
                        ft.Column(
                            [
                                ft.Text(m["display_name"], size=13.5,
                                        color=self.TEXT if m["enabled"] else self.TEXT_DIM,
                                        weight=ft.FontWeight.W_600, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(
                                    self._mod_status(m),
                                    size=11.5, color=self.TEXT_DIM, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                            ],
                            spacing=4, expand=True,
                        ),
                        # Client uses its persisted global preference. Other
                        # managed mods retain their lock and deletion guard.
                        *(
                            [animated_switch(value=m['enabled'], active_color=self.ACCENT,
                                             on_change=on_toggle, scale=0.85,
                                             tooltip='Enable or disable Cubeon Client for all instances on the next launch')]
                            if self._is_client_mod(m) else
                            [ft.Container(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.LOCK_ROUNDED, size=14, color=self.TEXT_DIM),
                                    ft.Text(i18n.t("System"), size=11, color=self.TEXT_DIM, font_family=self.FONT_MONO),
                                ], spacing=4, tight=True),
                                padding=ft.padding.Padding.symmetric(horizontal=8, vertical=4),
                            )]
                            if m.get("protected") else [
                                # Toggle switch
                                animated_switch(value=m["enabled"], active_color=self.ACCENT, on_change=on_toggle, scale=0.85,
                                                disabled=bool(m.get("issue")), tooltip=m.get("issue")),
                                # Delete button
                                ft.IconButton(ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color=TEXT_FAINT,
                                              icon_size=18, tooltip=i18n.t("Remove"), on_click=on_delete),
                            ]
                        ),
                    ],
                    spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
            ),
            self.SURFACE, self.BORDER, ROW_HOVER,
        )
        # Clicking the row (not the switch/delete) opens the full mod menu.
        # Protected/system files have no store identity to look up.
        if not m.get("protected") and (m.get("project_id") or m.get("slug")):
            row.on_click = lambda e, mm=m: self.open_mod_detail(mm)
        self._remember_row(self.installed_rows, key, (m, row))
        return row

    def open_folder_click(self, e):
        """Opens the folder for the active content type in the system file explorer."""
        if self._is_mod():
            core.open_mods_folder(self.state["selected_mc_version"], self.state["mod_loader"],
                                  version_id=self.version_dropdown.value)
        else:
            core.open_content_folder(self._ct(), self.state["selected_mc_version"],
                                     version_id=self.version_dropdown.value,
                                     loader=self.loader_for_content())

    def handle_local_mod_files(self, files):
        if not files:
            self.picker_target = None
            self.local_install_btn.disabled = not self._can_install(verify=False)
            thread_safe_ui.refresh(self.local_install_btn)
            return
        if self.local_install_busy:
            return
        target = self.picker_target or self._installed_target()
        self.picker_target = None
        if target != self._installed_target():
            self.local_install_status.value = 'The selected instance changed. Choose the file again.'
            self.local_install_status.visible = True
            self.local_install_btn.disabled = not self._can_install(verify=False)
            thread_safe_ui.refresh(self.local_install_status)
            thread_safe_ui.refresh(self.local_install_btn)
            return
        if not self._can_install():
            self.local_install_status.value = "Choose a compatible mod loader on the Play tab first. Texture packs work in vanilla."
            self.local_install_status.visible = True
            self.local_install_btn.disabled = True
            thread_safe_ui.refresh(self.local_install_status)
            thread_safe_ui.refresh(self.local_install_btn)
            return
        self.local_install_busy = True
        self.local_install_status.value = "Checking selected mods…" if target[0] == 'mod' else "Installing selected files…"
        self.local_install_status.visible = True
        thread_safe_ui.refresh(self.local_install_status)
        # Park the trigger so a double-pick can't run two installs into the
        # same profile; the worker below restores it.
        self.local_install_btn.disabled = True
        thread_safe_ui.refresh(self.local_install_btn)

        if target[0] == 'mod' and not rust_engine.is_instance(target[3]):
            def release_import():
                with thread_safe_ui.TREE_LOCK:
                    self.local_install_busy = False
                    self.local_install_btn.disabled = not self._can_install(verify=False)
                    thread_safe_ui.refresh(self.local_install_btn)

            def imported(results):
                self._refresh_after_install(target)
                with thread_safe_ui.TREE_LOCK:
                    if target == self._installed_target():
                        count = sum(result['status'] == 'imported' for result in results)
                        failed = sum(result['status'] == 'failed' for result in results)
                        self.local_install_status.value = f'{count} mods imported' + (f' · {failed} failed' if failed else '')
                        thread_safe_ui.refresh(self.local_install_status)

            def review_worker():
                try:
                    from cubeon import local_mods
                    from ui.local_mod_import import LocalModImport
                    review = local_mods.review_files([getattr(file, 'path', None) for file in files],
                                                    target[1], target[2], version_id=target[3])
                    with thread_safe_ui.TREE_LOCK:
                        if target != self._installed_target():
                            release_import()
                            return
                        self.local_install_status.value = ''
                        self.local_install_status.visible = False
                        thread_safe_ui.refresh(self.local_install_status)
                        LocalModImport(self.page, review,
                                       instance_label=(self.cfg.get('version_labels') or {}).get(target[3]) or target[3],
                                       finished=imported, closed=release_import).open()
                except Exception as error:
                    with thread_safe_ui.TREE_LOCK:
                        if target == self._installed_target():
                            self.local_install_status.value = f"Couldn't check the selected files: {error}"
                            thread_safe_ui.refresh(self.local_install_status)
                    release_import()
            try:
                threading.Thread(target=review_worker, daemon=True, name='cubeon-local-mod-install').start()
            except Exception as error:
                self.local_install_status.value = f"Couldn't start importing: {error}"
                thread_safe_ui.refresh(self.local_install_status)
                release_import()
            return

        # The install is real disk work (global-store copy/link, sidecar meta;
        # for packs a full copy + pack.mcmeta verify/fix) and run_mod_repair
        # even does network checks - none of it belongs on the UI thread
        # (same treatment the cosmetics uploads got).
        def worker():
            message = None
            try:
                imported_count, failures = 0, []
                for picked in files:
                    try:
                        if target[0] == 'mod':
                            core.install_local_mod(picked.path, target[1], target[2], version_id=target[3])
                        else:
                            core.install_local_content(target[0], picked.path, target[1], target[3], target[2])
                        imported_count += 1
                    except Exception as error:
                        failures.append(f'{picked.name}: {error}')
                message = f'Imported {imported_count} file(s).'
                if failures:
                    message += '\n' + '\n'.join(failures)
                self._refresh_after_install(target)
                # Phase 7: a local OS toast so a slow install can finish while
                # the launcher is behind another window. Best-effort by
                # construction (see cubeon/osnotify.py) - and it never names a
                # kind with no Settings switch (content_kind maps shaders onto
                # the texture-pack one).
                try:
                    from cubeon import osnotify
                    osnotify.install_finished(osnotify.content_kind(target[0]),
                                              f'{imported_count} file(s)')
                except Exception:
                    pass
            except ValueError as ve:
                message = str(ve)
            except Exception as ex:
                message = f"Install failed: {ex}"
            finally:
                with thread_safe_ui.TREE_LOCK:
                    if target == self._installed_target():
                        self.local_install_status.value = message
                        self.local_install_status.visible = True
                        thread_safe_ui.refresh(self.local_install_status)
                    self.local_install_busy = False
                    self.local_install_btn.disabled = not self._can_install(verify=False)
                    thread_safe_ui.refresh(self.local_install_btn)

        try:
            threading.Thread(target=worker, daemon=True, name="cubeon-local-mod-install").start()
        except Exception as error:
            self.local_install_busy = False
            self.local_install_status.value = f"Couldn't start installation: {error}"
            self.local_install_btn.disabled = not self._can_install(verify=False)
            thread_safe_ui.refresh(self.local_install_status)
            thread_safe_ui.refresh(self.local_install_btn)

    def on_local_mod_picked(self, e):
        # Old-Flet path: pick_files() ran synchronously and the result
        # arrives here via on_result. Untyped rather than annotated as
        # ft.FilePickerResultEvent - that class is missing on some pinned
        # Flet builds (e.g. 0.86.x) and a hard annotation crashes this
        # function's definition at import time on those builds.
        self.handle_local_mod_files(e.files)

    def open_local_mod_picker(self, e):
        if self.local_install_busy or self.picker_target is not None:
            return
        if not self._can_install():
            self.local_install_status.value = "Mods and shaders need a compatible mod loader. Choose one on the Play tab."
            self.local_install_status.visible = True
            thread_safe_ui.refresh(self.local_install_status)
            return
        if self._is_mod():
            # Vanilla can't load mods: refuse here instead of letting the
            # install land in a profile the game never reads. (install_local_
            # mod enforces the same rule at the core layer as a backstop.)
            if not self._is_rust() and self.state["mod_loader"] == "vanilla":
                self.local_install_status.value = (
                    "Vanilla can't load mods - switch the loader on the "
                    "Play tab first.")
                self.local_install_status.visible = True
                thread_safe_ui.refresh(self.local_install_status)
                return
            exts, title = (["hmod"], "Choose Rust content mods to import") if self._is_rust() else (["jar"], "Choose mod JARs to import")
        else:
            exts, title = ["zip"], f"Choose a {self._type_label()} .zip"
        self.picker_target = self._installed_target()
        self.local_install_btn.disabled = True
        thread_safe_ui.refresh(self.local_install_btn)
        def picker_failed(error):
            with thread_safe_ui.TREE_LOCK:
                self.picker_target = None
                self.local_install_btn.disabled = not self._can_install(verify=False)
                self.local_install_status.value = f"Couldn't open the file chooser: {error}"
                self.local_install_status.visible = True
                thread_safe_ui.refresh(self.local_install_status)
                thread_safe_ui.refresh(self.local_install_btn)
        try:
            core.run_file_picker(
                self.page, self.local_mod_file_picker,
                on_files=self.handle_local_mod_files, on_error=picker_failed,
                dialog_title=title, allow_multiple=True,
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=exts,
            )
        except Exception as error:
            picker_failed(error)

    def _schedule_live_search(self, e=None):
        """Debounced on_change: cancel any pending search, start a new one."""
        ft.context.disable_auto_update()
        pending = self._search_timer
        if pending is not None:
            pending.cancel()
        # Match Prism Launcher's search cadence: quick enough to feel live,
        # long enough that typing a word still produces one request.
        self._search_timer = threading.Timer(0.35, self.run_mod_search_safe)
        self._search_timer.daemon = True
        self._search_timer.start()

    def _cancel_search_timer(self):
        pending = self._search_timer
        if pending is not None:
            pending.cancel()
            self._search_timer = None

    def run_mod_search_safe(self):
        with thread_safe_ui.TREE_LOCK:
            self.run_mod_search()

    def _ct(self) -> str:
        return self.active_content["type"]

    def _is_mod(self) -> bool:
        return self.active_content["type"] == "mod"

    def _is_rust(self) -> bool:
        return rust_engine.is_instance(self.version_dropdown.value)

    def _instance_mod_capable(self, *, verify=True):
        """Does the SELECTED INSTANCE really have a mod loader?

        ``state["mod_loader"]`` is the switcher's choice, not on-disk truth: it
        can read "fabric" because another instance on the same Minecraft
        version has Fabric, or because the user armed Play to install one.
        Trusting it let a plain Vanilla folder accept mods and shaders (the
        2026-10-25 report). An installed instance therefore has to prove it
        with its own descriptor; a not-yet-installed version still follows the
        switcher, and a pending loader install counts as the intent to become
        modded.
        """
        vid = self.version_dropdown.value
        if not vid:
            return False
        pending = self.state.get("pending_loader_install") or {}
        if (pending.get("version_id") == vid
                and pending.get("loader") in MOD_CAPABLE_LOADERS):
            return True
        if vid in (self.state.get("installed") or set()):
            if not verify:
                return self.instance_loaders.get(vid) in MOD_CAPABLE_LOADERS
            try:
                meta = (self.state.get("installed_meta") or {}).get(vid) or {}
                info = instance_info.describe(
                    vid, meta, (self.cfg.get("version_labels") or {}).get(vid),
                    with_mods=False, play_store={})
                return info.get("loader") in MOD_CAPABLE_LOADERS
            except Exception:
                return False
        # Not installed yet: the switcher is the only loader information.
        return self.state.get("mod_loader") in MOD_CAPABLE_LOADERS

    def _can_install(self, content_type=None, *, verify=True):
        kind = content_type or self._ct()
        if self._is_rust():
            return kind == "mod"
        if kind == "resourcepack":
            # Texture packs work in plain Vanilla - always allowed.
            return True
        return (self._instance_mod_capable(verify=verify)
                and self.state.get("mod_loader") in MOD_CAPABLE_LOADERS)

    def loader_for_content(self) -> str | None:
        """The loader half of the profile key a pack is stored under.

        Content has no loader of its own, but the profile that OWNS it does: a
        Vanilla instance gets its own set of packs instead of sharing the
        modded instance's (which matters because a shader is only usable where
        Iris/OptiFine is actually installed)."""
        return "rust" if self._is_rust() else self.state.get("mod_loader")

    def _type_label(self) -> str:
        """Singular human label for the active non-mod type, e.g. 'resource pack'."""
        return core.CONTENT_TYPES[self._ct()]["label"].lower()

    def _sync_client_preference(self):
        self.client_preference_switch.value = bool(self.cfg.get('client_mod_enabled', True))
        self.client_preference_row.visible = (
            self._is_mod() and not self._is_rust() and bool(self.state.get('selected_mc_version'))
            and self.state.get('mod_loader') in MOD_CAPABLE_LOADERS
            and not any(self._is_client_mod(item) for item in self._cached_installed()))
        thread_safe_ui.refresh(self.client_preference_row)

    def _sync_content_notices(self):
        for notice, visible in (
            (self.vanilla_mods_notice, self._is_mod() and not self._is_rust() and self.state.get('mod_loader') == 'vanilla'),
            (self.shader_notice, self._ct() == 'shader' and not self._is_rust() and not self.shader_requirement_installed()),
        ):
            if notice.visible != visible:
                notice.visible = visible
                thread_safe_ui.refresh(notice)
        if self.shader_notice.visible:
            previous = (self.shader_setup_btn.disabled, self.shader_notice_text.value, self.shader_setup_label.value)
            self._sync_shader_notice()
            current = (self.shader_setup_btn.disabled, self.shader_notice_text.value, self.shader_setup_label.value)
            if current != previous:
                thread_safe_ui.refresh(self.shader_notice)

    def _sync_local_install_action(self):
        allowed = self._can_install(verify=False)
        disabled = self.local_install_busy or self.picker_target is not None or not allowed
        tooltip = None if allowed else ('This Rust beta supports Horizon content mods.' if self._is_rust()
                                       else 'Choose a mod loader on the Play tab first.')
        if (self.local_install_btn.disabled, self.local_install_btn.tooltip) != (disabled, tooltip):
            self.local_install_btn.disabled, self.local_install_btn.tooltip = disabled, tooltip
            thread_safe_ui.refresh(self.local_install_btn)

    def _apply_type_labels(self):
        """Synchronize the retained labels and preference for the selected type."""
        self._sync_client_preference()
        self._sync_content_notices()
        self._sync_local_install_action()
        if self.check_repair_btn.visible == self._is_rust():
            self.check_repair_btn.visible = not self._is_rust()
            thread_safe_ui.refresh(self.check_repair_btn)
        self.installed_filter_field.hint_text = ('Search installed mods...' if self._is_mod()
                                            else 'Search installed resource packs...' if self._ct() == 'resourcepack'
                                            else 'Search installed shaders...')
        self.header_title.value = dict(self.CONTENT_TABS)[self._ct()]
        if self._is_mod():
            self.header_subtitle.value = "Choose a mod loader on Play to install mods." if not self._can_install(verify=False) else ''
            self.mod_search_field.hint_text = ("Search Horizon content mods or paste a Horizon link..." if self._is_rust()
                                               else "Search mods or paste a Modrinth / CurseForge link...")
        elif self._ct() == "resourcepack":
            self.header_subtitle.value = "Texture packs work in vanilla and modded Minecraft."
            self.mod_search_field.hint_text = "Search resource packs... e.g. faithful, stay true"
        else:
            self.header_subtitle.value = "Shaders need Iris, Oculus, or OptiFine."
            self.mod_search_field.hint_text = "Search shaders... e.g. complementary, BSL, sildurs"
        self.local_install_label.value = i18n.t('Import mods' if self._is_mod() else 'Import packs' if self._ct() == 'resourcepack' else 'Import shaders')
        self._refresh_browse_scope()

    def on_content_type_change(self, new_type):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if self.selected_content['value'] == new_type:
                return
            self.close_mod_detail()
            self._cancel_search_timer()
            pending = self._filter_timer
            if pending is not None:
                pending.cancel()
            self.type_preferences[self._ct()] = (self.mod_search_field.value, self.active_category['value'],
                                       self.installed_filter_field.value, self.active_view['value'],
                                       self.installed_limit['value'])
            self.selected_content['value'] = new_type
            for kind, button in self.content_buttons.items():
                button.style = self.selector_style(kind == new_type)
                thread_safe_ui.refresh(button)
            self.mods_body.visible = new_type != 'modpack'
            if self.modpacks_content is not None:
                self.modpacks_content.visible = new_type == 'modpack'
            if new_type == 'modpack':
                thread_safe_ui.refresh(self.mods_body)
                if self.on_modpacks_open:
                    self.on_modpacks_open()
                pack_tab = getattr(self.modpacks_content, 'content', None)
                if getattr(pack_tab, 'close_detail', None):
                    pack_tab.on_detail_change = self.pack_detail_changed
                thread_safe_ui.refresh(self.modpacks_content)
                return
            if self.modpacks_content is not None:
                thread_safe_ui.refresh(self.modpacks_content)
            self.active_content['type'] = new_type
            query, category, installed_query, view, limit = self.type_preferences.get(
                new_type, ('', '', '', 'browse', 50))
            self.mod_search_field.value = query
            self.active_category['value'] = category
            self.installed_filter_field.value = installed_query
            self.installed_limit['value'] = limit
            self.installed_show_all['value'] = False
            self.active_view['value'] = view
            self.browse_pane.visible = view == 'browse'
            self.installed_pane.visible = view == 'installed'
            self._sync_view_hosts()
            self._apply_type_labels()
            self._build_view_segment()
            # Never display the previous type's cards while the new type loads.
            self.browse_results_view.controls.clear()
            self._load_visible_content()
            thread_safe_ui.refresh(self.mods_body)

    def current_mc_version_for_search(self) -> str | None:
        """
        Extracts the Minecraft version number (e.g., "1.20.4") from the selected version ID.
        This is used to find mods compatible with the current game version.
        """
        v = self.version_dropdown.value
        if not v:
            return None
        if rust_engine.is_instance(v):
            return rust_engine.VERSION
        return self.state.get('selected_mc_version') or core.extract_mc_version(v)

    def browse_loader(self) -> str:
        """The loader to filter Modrinth results by. Vanilla can't load mods
        at all, so default that case to Fabric (the most commonly supported
        loader) rather than sending an invalid facet."""
        loader = self.loader_for_content() or "vanilla"
        return loader if loader != "vanilla" else "fabric"

    def _search_all_modrinth(self, event=None):
        self.active_category["value"] = ""
        self.search_scope["compatible"] = False
        self.run_mod_search() if self.mod_search_field.value.strip() else self.load_recommended_mods()

    def _refresh_browse_scope(self):
        if self._is_rust():
            label = (f"Horizon · Rust {rust_engine.VERSION} · Content mods" if self._is_mod()
                     else f"Rust {rust_engine.VERSION} · Horizon content mods are supported in this beta")
        elif self._is_mod() and not self.search_scope["compatible"]:
            label = "All Minecraft versions · all loaders"
        else:
            version = self.current_mc_version_for_search() or "all versions"
            label = f"Minecraft {version}"
            if self._is_mod():
                label = f"{self.browse_loader().title()} · {label}"
        category = self.active_category["value"]
        if category:
            choices = core.MOD_CATEGORIES if self._is_mod() else core.category_choices(self._ct())
            label += f" · {dict(choices).get(category, category)}"
        self.browse_scope_text.value = label
        self.header_subtitle.value = label
        self.header_subtitle.tooltip = label
        self.installed_context.value = label
        self.installed_context.tooltip = label
        thread_safe_ui.refresh(self.header_subtitle)
        thread_safe_ui.refresh(self.installed_context)

    def _browse_key(self):
        return (self.mod_search_field.value.strip(), self.current_mc_version_for_search(),
                self.version_dropdown.value, self.loader_for_content(), self._ct(),
                self.active_category["value"], self.search_scope["compatible"], self.BROWSE_PAGE_SIZE)

    def _begin_browse(self):
        self._cancel_search_timer()
        self._refresh_browse_scope()
        key = self._browse_key()
        cached = self.browse_sessions.get(key)
        if cached and (time.monotonic() - cached.get("fetched_at", time.monotonic()) >= 60
                       and (not any(cached["pages"].values())
                            or (cached.get("provider_errors") and not cached.get("infinite")))):
            self.browse_sessions.pop(key, None)
            cached = None
        if cached is not None:
            return cached['token']
        self.browse_generation["value"] += 1
        return self.browse_generation["value"], key

    def _browse_current(self, token):
        return (token is not None and token == self.browse_state['token']
                and token[1] == self._browse_key() and self._tab_visible()
                and self.active_view['value'] == 'browse')

    def _browse_ready(self):
        return self._browse_current(self.browse_state['token']) and bool(self.browse_state['pages'])

    def _retry_search(self, event=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            session = self.browse_state
            token = session["token"]
            if session.get("infinite") and self._browse_current(token):
                if session.get("provider_errors"):
                    self._load_mod_page(session["page"], token, retry=True)
                return
            self.force_search["value"] = True
            self.browse_sessions.pop(self._browse_key(), None)
            self.run_mod_search_safe()

    # Each request fetches one offset per provider. Cached pages belong to the
    # query, instance and filters captured in the browse token.
    def _browse_query(self) -> str:
        return self.mod_search_field.value.strip()

    def _browse_is_paged(self) -> bool:
        """Every catalogue, including popular Mods, fetches one page at a time."""
        return True

    def _browse_fetch(self, page_num: int, key=None, *, source="modrinth", force=False):
        """One page of results for the CURRENT browse key. Runs on a worker
        thread. May return fewer than BROWSE_PAGE_SIZE hits, which the caller
        treats as the last page."""
        query, mc_version, version, loader, content_type, cat, compatible, page_size = key or self._browse_key()
        if content_type == "mod" and rust_engine.is_instance(version):
            return core.search_mods(query, mc_version=rust_engine.VERSION, loader="rust", source="horizon",
                                    categories=[cat] if cat else None, limit=page_size,
                                    offset=page_num * page_size, **({"force": True} if force else {}))
        loader = loader if loader and loader != 'vanilla' else 'fabric'
        if content_type == "mod" and not compatible:
            mc_version, loader = None, None
        offset = page_num * page_size
        if content_type == "mod":
            options = {"source": source} if source != "modrinth" else {}
            if force:
                options["force"] = True
            if query:
                return core.search_mods(
                    query, mc_version=mc_version, loader=loader,
                    categories=[cat] if cat else None,
                    limit=page_size, offset=offset, **options)
            return core.get_recommended_mods(
                mc_version=mc_version, loader=loader, category=cat or None,
                limit=page_size, offset=offset, **options)
        if query:
            return core.search_content(
                content_type, query, mc_version=mc_version,
                categories=[cat] if cat else None,
                limit=page_size, offset=offset)
        return core.get_recommended_content(
            content_type, mc_version=mc_version, category=cat or None,
            limit=page_size, offset=offset)

    def _load_mod_page(self, page_num, token, *, retry=False):
        session = self.browse_sessions.get(token[1])
        if session is None:
            return
        request = (token, page_num)
        if request in self.browse_inflight:
            return
        self.browse_inflight.add(request)
        link = mod_catalogue.reference(token[1][0])
        sources = (("horizon",) if rust_engine.is_instance(token[1][2]) else
                   (link["source"],) if link else mod_catalogue.SOURCES)
        ends = session.setdefault("provider_ends", {})
        infinite = session.get("infinite", False)
        previous = session.get("provider_page") if retry else None
        progress = mod_catalogue.ProviderPage(tuple(previous.errors) if previous else sources)
        if previous:
            progress.results.update(previous.results)
        if infinite:
            session["provider_page"] = progress
        session["provider_pending"] = progress.pending
        if infinite and (page_num or retry) and self._browse_current(token):
            session["provider_errors"] = {}
            self.browse_status_text.value = i18n.t("Loading…")
            self.browse_status_text.tooltip = self.browse_status_text.value
            self.browse_load_more.disabled = True
            self.browse_retry.opacity, self.browse_retry.disabled = 0, True
            self.browse_retry.visible = False
            thread_safe_ui.refresh(self.browse_status_text)
            thread_safe_ui.refresh(self.browse_pager_row)
        retained_rows = []
        if not infinite and any(callable(getattr(row, "on_click", None))
                                and row.data not in ("content-loading", "content-empty", "cubeon-client-browse")
                                for row in self.browse_results_view.controls):
            retained_rows = list(self.browse_results_view.controls)

        def publish(source, hits, error=None):
            with thread_safe_ui.TREE_LOCK:
                if self.browse_sessions.get(token[1]) is not session:
                    self.browse_inflight.discard(request)
                    return
                progress.record(source, hits, error)
                if error is None and len(hits or []) < self.BROWSE_PAGE_SIZE:
                    ends[source] = min(page_num, ends.get(source, page_num))
                session["provider_errors"] = dict(progress.errors)
                # Keep all mounted cards stable during a tail fetch. Page one
                # can still show each provider as soon as it arrives.
                if infinite and (page_num or retry) and not progress.complete:
                    return
                merged = progress.merged()
                if merged or progress.complete:
                    session["pages"][page_num] = merged
                if progress.complete:
                    self.browse_inflight.discard(request)
                    session["fetched_at"] = time.monotonic()
                    if not progress.errors and all(source in ends for source in sources):
                        session["total_pages"] = max(ends[source] for source in sources) + 1
                    if infinite:
                        session["has_more"] = any(
                            source not in progress.errors and page_num < ends.get(source, page_num + 1)
                            for source in sources)
                if self._browse_current(token):
                    if not infinite and not merged and progress.errors and retained_rows:
                        self.browse_results_view.controls[:] = retained_rows
                        for row in retained_rows:
                            row.ignore_interactions = False
                        self.browse_results_view.disabled = False
                        self.browse_status_text.value = " · ".join(f"{mod_catalogue.LABELS[s]} unavailable" for s in progress.errors)
                        self.browse_retry.opacity, self.browse_retry.disabled = 1, False
                        for control in (self.browse_results_view, self.browse_status_text, self.browse_retry):
                            thread_safe_ui.refresh(control)
                    elif merged or progress.complete:
                        self._render_browse_page()
                        self.refresh_mods_list(background=True, navigation=True)
                    elif progress.errors:
                        self.browse_status_text.value = " · ".join(f"{mod_catalogue.LABELS[s]} unavailable" for s in progress.errors)
                        self.browse_retry.opacity, self.browse_retry.disabled = 1, False
                        for control in (self.browse_status_text, self.browse_retry):
                            thread_safe_ui.refresh(control)

        def worker(source):
            try:
                hits = self._browse_fetch(page_num, token[1], source=source, force=retry or session.get("force", False))
                publish(source, hits)
            except Exception as error:
                publish(source, [], error)

        for source in progress.sources:
            if page_num > ends.get(source, page_num):
                publish(source, [])
                continue
            try:
                threading.Thread(target=lambda source=source: worker(source), daemon=True,
                                 name=f"cubeon-mod-search-{source}").start()
            except Exception as error:
                publish(source, [], error)

    def _load_browse_page(self, page_num: int, token, error_prefix: str):
        """Fetches page `page_num` for `token` and renders it when it still
        belongs to the current browse. An already-cached page just re-renders."""
        if page_num in self.browse_state["pages"]:
            self._render_browse_page()
            return
        if token[1][4] == "mod":
            self._load_mod_page(page_num, token)
            return
        request = (token, page_num)
        if request in self.browse_inflight:
            return
        self.browse_inflight.add(request)
        self.browse_status_text.value = "Loading..."
        thread_safe_ui.refresh(self.browse_status_text)

        def worker():
            try:
                items = self._browse_fetch(page_num, token[1])
            except Exception as ex:
                logging.getLogger(__name__).warning("%s: %s", error_prefix, ex, exc_info=True)
                with thread_safe_ui.TREE_LOCK:
                    self.browse_inflight.discard(request)
                    if not self._browse_current(token):
                        return
                    self.browse_sessions.pop(token[1], None)
                    self.browse_status_text.value = "Search unavailable"
                    client_entry = self._client_browse_entry()
                    self.browse_results_view.disabled = False
                    retained = any(isinstance(row, ft.Container) and row.data not in
                                   ('content-loading', 'content-empty', 'cubeon-client-browse')
                                   and callable(row.on_click) for row in self.browse_results_view.controls)
                    if retained:
                        # Keep a readable, scrollable last page after a failed refresh.
                        for row in self.browse_results_view.controls:
                            row.ignore_interactions = False
                    elif client_entry:
                        # Bundled client recovery remains available offline, in
                        # the same compact grid as successful provider results.
                        self.browse_results_view.controls[:] = [
                            self.build_browse_row(client_entry, any(self._is_client_mod(m) for m in self._cached_installed('mod'))),
                            ft.Container(ft.Column([
                                ft.Text('Modrinth unavailable', size=12, color=self.TEXT_DIM),
                                ft.TextButton('Retry', on_click=self._retry_search),
                            ], spacing=4), padding=12),
                        ]
                    else:
                        self.browse_results_view.controls[:] = [
                            empty_state("Search unavailable", "Check your connection, then try again.",
                                        icon=ft.Icons.WIFI_OFF_ROUNDED),
                            quiet_chip('Retry', on_click=self._retry_search),
                        ]
                    if not retained:
                        layout_tiles(self.browse_results_view, bool(client_entry))
                    self.browse_pager_label.value = 'Couldn\'t load results'
                    self.browse_retry.opacity = 1
                    self.browse_retry.disabled = False
                thread_safe_ui.refresh(self.browse_status_text)
                thread_safe_ui.refresh(self.browse_results_view)
                thread_safe_ui.refresh(self.browse_pager_row)
                return
            with thread_safe_ui.TREE_LOCK:
                self.browse_inflight.discard(request)
                session = self.browse_sessions.get(token[1])
                if session is None or session['token'] != token:
                    return
                items = items or []
                if session['paged']:
                    items = items[:self.BROWSE_PAGE_SIZE]
                session["pages"][page_num] = items
                if len(items) < self.BROWSE_PAGE_SIZE:
                    session["total_pages"] = min(session["total_pages"], page_num + 1)
                if self._browse_current(token):
                    self._render_browse_page()
                    self.refresh_mods_list(background=True, navigation=True)

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as error:
            self.browse_inflight.discard(request)
            self.browse_results_view.disabled = False
            self.browse_status_text.value = f"Couldn't start search: {error}"
            thread_safe_ui.refresh(self.browse_results_view)
            thread_safe_ui.refresh(self.browse_status_text)

    def render_browse_results(self, empty_msg):
        """
        Resets the browse to page 1 for the current key and starts its fetch.
        Later pages load only when the pager asks for them.
        """
        token = self.browse_state['token']
        key = token[1]
        cached = self.browse_sessions.get(key)
        if cached is None:
            cached = dict(empty_msg=empty_msg, page=0, pages={}, results=[],
                          paged=self._browse_is_paged(), total_pages=self.MAX_BROWSE_PAGES,
                          infinite=key[4] == "mod" and not key[0],
                          token=token, force=self.force_search["value"])
            self.force_search["value"] = False
            self.browse_sessions[key] = cached
            while len(self.browse_sessions) > 12:
                self.browse_sessions.pop(next(iter(self.browse_sessions)))
        self.browse_state = cached
        infinite = cached["infinite"]
        self.browse_results_view.on_scroll = self._browse_scrolled if infinite else None
        for control in (self.browse_pager_spacer, self.browse_pager_prev,
                        self.browse_pager_caption, self.browse_pager_next):
            control.visible = not infinite
        self._render_browse_page()

    def load_recommended_mods(self):
        """
        Fetches the first page of items for the current version+category and
        displays them in the browse section. All types use popular results
        (or the top results in a category), one page at a time.
        """
        with thread_safe_ui.TREE_LOCK:
            token = self._begin_browse()
            self.browse_state = dict(self.browse_state, token=token)
            content_type = self._ct()
            cat = self.active_category["value"]
            if content_type == "mod":
                cat_label = dict(core.MOD_CATEGORIES).get(cat, "")
            else:
                cat_label = dict(core.category_choices(self._ct())).get(cat, "")
            self.browse_title_text.value = f"TOP {cat_label.upper()}" if cat else i18n.t("Popular").upper()
            self.browse_title_text.tooltip = None
            thread_safe_ui.refresh(self.browse_title_text)
            self.render_browse_results(empty_msg="No results for this Minecraft version and category.")

    def run_mod_search(self):
        """
        Initiates a search on Modrinth based on the query entered in mod_search_field,
        scoped to the current version, active content type, and selected category.
        If the query is empty, it loads recommendations instead.
        """
        with thread_safe_ui.TREE_LOCK:
            query = self.mod_search_field.value.strip()
            if not query:
                self.load_recommended_mods()
                return
            token = self._begin_browse()
            self.browse_state = dict(self.browse_state, token=token)
            self.browse_title_text.value = i18n.t("Search results").upper()
            self.browse_title_text.tooltip = query
            # Live search repaints only the browse region (title/results), not the
            # whole mounted tree - this fires per debounced keystroke.
            thread_safe_ui.refresh(self.browse_title_text)
            self.render_browse_results(empty_msg="Nothing found for that search.")

    def _show_browse_loading(self):
        """Keep the grid, scroll position and pager geometry while fetching."""
        if (not self.browse_results_view.controls or isinstance(self.browse_results_view.controls[0], (ft.Text, ft.Row))
                or getattr(self.browse_results_view.controls[0], "data", None) == "content-empty"):
            self.browse_results_view.controls[:] = loading_tiles(self.browse_results_view)
            client_entry = self._client_browse_entry()
            if client_entry:
                client_row = self.build_browse_row(
                    client_entry, any(self._is_client_mod(m) for m in self._cached_installed('mod')))
                if len(self.browse_results_view.controls) > 1:
                    self.browse_results_view.controls[1] = client_row
                else:
                    self.browse_results_view.controls.append(client_row)
            layout_tiles(self.browse_results_view)
        for row in self.browse_results_view.controls:
            if isinstance(row, ft.Container):
                row.ignore_interactions = row.data != 'cubeon-client-browse'
        # Ignore stale tile actions while leaving the native scroll viewport live.
        self.browse_results_view.disabled = False
        self.browse_pager_prev.disabled = self.browse_pager_next.disabled = True
        self.browse_pager_label.value = i18n.t('Loading…')
        self.browse_load_more.visible = False
        self.browse_retry.opacity = 0
        self.browse_retry.disabled = True
        self.browse_retry.visible = not self.browse_state.get("infinite")
        # Scoped: a full page.update() here re-synced every mounted tab right
        # after switch_tab had already painted the shell - that double diff is
        # part of the "click Mods and everything lags at once" report.
        thread_safe_ui.refresh(self.browse_results_view)
        thread_safe_ui.refresh(self.browse_pager_row)

    def _render_browse_page(self):
        """Renders the current page from the cache, fetching it if this is the
        first visit. Whatever isn't cached stays un-fetched until asked for."""
        if self.browse_state["token"] is None:
            # No browse has been started yet (e.g. a re-render triggered by an
            # install/delete before the tab's first load) - nothing to show.
            return
        page_num = self.browse_state["page"]
        token = self.browse_state["token"]
        infinite = self.browse_state.get("infinite", False)

        if infinite:
            pages = self.browse_state["pages"]
            if 0 not in pages:
                self._show_browse_loading()
                self._load_mod_page(0, token)
                return
            page_results = pages.get(page_num)
            by_project = {}
            for items in pages.values():
                for item in items:
                    by_project.setdefault(mod_catalogue.identity(item), item)
            results = list(by_project.values())
        elif not self.browse_state["paged"]:
            # Legacy non-paged sessions slice their cached results locally.
            all_items = self.browse_state["pages"].get(0)
            if all_items is None:
                self._show_browse_loading()
                self._load_browse_page(0, token, "Couldn't load recommendations")
                return
            total_pages = max(1, -(-len(all_items) // self.BROWSE_PAGE_SIZE))
            page_num = max(0, min(page_num, total_pages - 1))
            self.browse_state["page"] = page_num
            self.browse_state["total_pages"] = total_pages
            results = all_items[page_num * self.BROWSE_PAGE_SIZE:
                                (page_num + 1) * self.BROWSE_PAGE_SIZE]
            page_results = results
        else:
            results = self.browse_state["pages"].get(page_num)
            if results is None:
                self._show_browse_loading()
                self._load_browse_page(page_num, token, "Search failed")
                return
            total_pages = max(1, self.browse_state["total_pages"])
            page_results = results

        self.browse_state["results"] = results

        client_entry = self._client_browse_entry()
        displayed_results = ([client_entry] if client_entry else []) + [
            item for item in results if not client_entry or item.get('slug') != 'cubeon-client']
        painted_key = (token, 0 if infinite else page_num)
        render_context = self._install_gate_context()
        retained = 0
        if (infinite and painted_key == self._painted_browse['key']
                and self._rendered_browse_context == render_context
                and len(self._rendered_browse_items) == len(self.browse_results_view.controls)):
            for old, new in zip(self._rendered_browse_items, displayed_results):
                if old != new:
                    break
                retained += 1
        rows = self.browse_results_view.controls[:retained]
        if not displayed_results:
            rows.append(
                empty_state(self.browse_state.get("empty_msg") or "No results",
                            "Try a different search or adjust the filters."))
            if self._is_mod() and not self._is_rust() and self._browse_query() and (self.search_scope["compatible"] or self.active_category["value"]):
                rows.append(quiet_chip("Search all versions and loaders", on_click=self._search_all_modrinth))
        else:
            # Snapshot the mode once: a background recommend/search worker can
            # finish and call this right after the user flipped the content-type
            # segment, so re-checking _is_mod() per row could read one mode in
            # setup and the other in the loop (crashing on the unset variable).
            is_mod_now = self._is_mod()
            already = self.installed_slugs() if is_mod_now else set()
            tokens = set() if is_mod_now else self.content_installed_tokens()
            for mod in displayed_results[retained:]:
                if is_mod_now:
                    slug = (mod.get("slug") or "").lower()
                    compact = re.sub(r"[^a-z0-9]+", "", slug)
                    # Modrinth's opaque project id: a modpack install leaves
                    # exactly this and no slug, so it's often the only match
                    # for a pack-installed mod.
                    pid = (mod.get("project_id") or "").strip().lower()
                    is_installed = (any(self._is_client_mod(item) and item.get('enabled', True)
                                        for item in self._cached_installed('mod'))
                                    if mod.get('builtin_client') else
                                    slug in already or (bool(compact) and compact in already)
                                    or (bool(pid) and pid in already)) if mod_catalogue.source_of(mod) == "modrinth" else (mod_catalogue.identity(mod) in already)
                else:
                    # Resource packs / shaders store no Modrinth slug (they're
                    # just .zips in a shared folder), so match the project's
                    # slug OR title as a compacted token against installed
                    # filenames. Best-effort; a miss only shows "Download".
                    slug = re.sub(r"[^a-z0-9]+", "", (mod.get("slug") or "").lower())
                    title = re.sub(r"[^a-z0-9]+", "", (mod.get("title") or "").lower())
                    is_installed = (bool(slug) and any(slug in t for t in tokens)) or \
                        (bool(title) and any(title in t for t in tokens))
                rows.append(self.build_browse_row(mod, is_installed))

        self.browse_results_view.controls[:] = rows
        for row in rows:
            row.ignore_interactions = False
        layout_tiles(self.browse_results_view, bool(displayed_results))
        self.browse_results_view.disabled = False

        self.browse_status_text.value = (
            i18n.t("{count} result(s)", count=len(displayed_results)) if displayed_results else "")
        self.browse_status_text.tooltip = self.browse_status_text.value
        self.browse_pager_row.visible = True
        self.browse_load_more.visible = infinite and self.browse_state.get("has_more", False)
        self.browse_load_more.disabled = bool(self.browse_state.get("provider_pending"))
        if not infinite:
            self.browse_pager_label.value = f"Page {page_num + 1} of {total_pages}"
            self.browse_pager_prev.disabled = page_num <= 0
            self.browse_pager_next.disabled = page_num >= total_pages - 1
        self.browse_retry.opacity = 0
        self.browse_retry.disabled = True
        self.browse_retry.visible = not infinite
        if self._is_mod():
            errors = self.browse_state.get("provider_errors", {})
            pending = self.browse_state.get("provider_pending", set())
            notes = [i18n.t("{provider} unavailable", provider=mod_catalogue.LABELS[source]) for source in errors]
            notes.extend(i18n.t("Loading {provider}…", provider=mod_catalogue.LABELS[source])
                         for source in sorted(pending))
            if notes:
                self.browse_status_text.value = " · ".join(notes)
                self.browse_status_text.tooltip = "\n".join(errors.values()) or self.browse_status_text.value
            if errors:
                self.browse_retry.visible = True
                self.browse_retry.opacity, self.browse_retry.disabled = 1, False
            if errors and not displayed_results:
                self.browse_results_view.controls[:] = [empty_state("Search unavailable", "Couldn't load the mod catalogue. Retry the search."),
                                                  quiet_chip("Retry", on_click=self._retry_search)]
                layout_tiles(self.browse_results_view, False)
        # Results often land moments after the tab switch, while the user is
        # already moving. Repaint only the browse region instead of diffing
        # the whole page in that moment.
        thread_safe_ui.refresh(self.browse_results_view)
        thread_safe_ui.refresh(self.browse_status_text)
        thread_safe_ui.refresh(self.browse_pager_row)
        self._rendered_browse_context = render_context
        self._rendered_browse_results = page_results
        self._rendered_browse_items = displayed_results if infinite else []
        if painted_key != self._painted_browse['key']:
            self._painted_browse['key'] = painted_key
            scrolling.to_top(self.page, self.browse_results_view)

    # --- Mod detail menu ----------------------------------------------------
    # Clicking a mod (browse or installed) opens this: cover art, the full
    # description, the numbers, and every released version with a one-click
    # install. A list row only has room for a name and a line of text; this is
    # where "what is this, and which version do I want?" gets answered.

    def _detail_loading_row(self):
        return ft.Row(
            [ft.ProgressRing(width=16, height=16, stroke_width=2, color=self.ACCENT),
             ft.Text("Loading details...", size=13, color=self.TEXT_DIM)],
            spacing=12, alignment=ft.MainAxisAlignment.CENTER,
        )

    def _provider_icon(self, source):
        label = mod_catalogue.LABELS[source]
        asset = 'loader-icons/rust.png' if source == 'horizon' else f'provider-icons/{source}.svg'
        return ft.Image(src=asset, width=16, height=16,
                        fit=ft.BoxFit.CONTAIN, tooltip=label, semantics_label=label)

    def _detail_badge(self, text, tone="dim"):
        """A tiny metadata pill. Quiet by default; green only for the one
        version that matches the profile the user is browsing."""
        accent = tone == "accent"
        return ft.Container(
            content=ft.Text(text, size=10.5,
                            color=self.ACCENT if accent else TEXT_FAINT,
                            weight=ft.FontWeight.W_600,
                            font_family=self.FONT_MONO),
            bgcolor=ACCENT_TINT if accent else CARD_FILL,
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=8, vertical=4),
            border=None if accent else ft.border.Border.all(1, CARD_BORDER),
        )

    def close_mod_detail(self, event=None):
        if not self.detail_host.visible:
            pack_tab = getattr(self.modpacks_content, "content", None) or self.modpacks_content
            close_pack_detail = getattr(pack_tab, "close_detail", None)
            if close_pack_detail:
                return close_pack_detail(event)
            return False
        with thread_safe_ui.TREE_LOCK:
            self.detail_navigation["generation"] += 1
            self.detail_host.visible = False
            self.catalogue_host.visible = True
            self.detail_host.controls.clear()
            thread_safe_ui.refresh(self.detail_host)
            thread_safe_ui.refresh(self.catalogue_host)
        return True

    def open_mod_detail(self, mod, content_type=None, *, force=False):
        """Open the full menu for one mod, keyed by its Modrinth id or slug.
        Manually dropped-in files have neither, so there is nothing to look
        up - those rows simply don't open a menu."""
        ref = (mod.get("project_id") or mod.get("slug") or "").strip()
        if not ref:
            return

        content_type = content_type or self._ct()
        detail_source = mod_catalogue.source_of(mod)
        lookup_ref = mod_catalogue.identity(mod, ref) if detail_source != "modrinth" else ref
        _, detail_mc, detail_loader, detail_version = self._installed_target(content_type)
        detail_search_mc = self.current_mc_version_for_search()
        feedback = self.install_registry.project(
            (content_type, detail_mc, detail_loader, detail_version, detail_source), ref, mod.get("slug"))
        title = mod.get("title") or mod.get("display_name") or "Mod"
        icon_url = mod.get("icon_url") or self.installed_icon_urls.get(lookup_ref if detail_source != 'modrinth' else mod.get('slug'))
        blurb = (mod.get("description") or "").strip()

        self.detail_navigation["generation"] += 1
        generation = self.detail_navigation["generation"]
        detail_body = ft.Column(
            [self._detail_loading_row()],
            spacing=16, expand=True,
            scroll=ft.ScrollMode.AUTO,
            data="mod-detail-body",
        )
        hero_action = ft.Container(content=ft.Text("Loading…", color=self.TEXT_DIM, size=12), width=180)
        hero_title = ft.Text(title, size=22, color=self.ACCENT, font_family=self.FONT_DISPLAY,
                             weight=ft.FontWeight.W_700, max_lines=1,
                             overflow=ft.TextOverflow.ELLIPSIS, tooltip=title)
        hero_description = ft.Text(blurb, size=12.5, color=self.TEXT_DIM, max_lines=2)
        hero_meta = ft.Text(f"{(detail_loader or 'vanilla').title()} · {detail_mc or 'Choose an instance'}",
                            size=11.5, color=self.TEXT_DIM)
        hero_icon = self._art_image(icon_url, 58, 58)
        hero_icon.data = icon_url
        hero = ft.Container(content=ft.Row([
            hero_icon,
            ft.Column([hero_title, hero_meta, hero_description], spacing=5, expand=True),
            hero_action], spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            padding=16, height=120, bgcolor=self.SURFACE_HI, border_radius=RADIUS)
        detail_tabs = ft.Row(spacing=8, data="mod-detail-tabs")
        with thread_safe_ui.TREE_LOCK:
            self.catalogue_host.visible = False
            self.detail_host.visible = True
            self.detail_host.controls = [ft.Row([
                ft.TextButton(content=i18n.t("Back"), icon=ft.Icons.ARROW_BACK_ROUNDED,
                              on_click=self.close_mod_detail, data="mod-detail-back",
                              style=ft.ButtonStyle(color=self.ACCENT)),
                ft.Container(expand=True),
                ft.Text(f"{(detail_loader or 'vanilla').title()} {detail_mc or ''}", size=11, color=self.TEXT_DIM)],
                vertical_alignment=ft.CrossAxisAlignment.CENTER), hero, detail_tabs, detail_body]
            thread_safe_ui.refresh(self.catalogue_host)
            thread_safe_ui.refresh(self.detail_host)

        def current():
            return self.detail_host.visible and self.detail_navigation["generation"] == generation

        def _http_url(value):
            from urllib.parse import urlsplit
            try:
                parsed = urlsplit(value or "")
                return value if parsed.scheme in ("https", "http") and parsed.netloc else None
            except ValueError:
                return None

        installed_now = {}
        try:
            items = self._cached_installed(content_type)
            for m in items:
                if m.get("filename"):
                    installed_now[m["filename"]] = m
        except Exception:
            installed_now = {}

        def release_installed(version):
            installed = installed_now.get(version.get("filename"))
            if detail_source == "horizon" and installed:
                return (installed.get("file_id") or installed.get("version")) == (version.get("file_id") or version.get("version_number"))
            return bool(installed)

        # --- Shared install plumbing ---------------------------------------
        # One path for the top "Install latest" button and every row in the
        # version list, so their states can never drift apart.
        def _human_count(n):
            try:
                n = int(n)
            except (TypeError, ValueError):
                return str(n)
            if n >= 1_000_000:
                return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
            if n >= 1_000:
                return f"{n / 1_000:.1f}K".replace(".0K", "K")
            return str(n)

        def _plain_preview(md):
            """A short, readable teaser from the Markdown body: images, links
            and markup stripped, whitespace collapsed."""
            t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md or "")
            t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
            t = re.sub(r"<[^>]+>", " ", t)
            t = re.sub(r"[#>*_`~|]+", " ", t)
            return re.sub(r"\s+", " ", t).strip()

        def _run_install(v, details, *, on_status, on_done, on_error):
            # Progress on whatever control shows status: whole-percent only, so
            # page.update() isn't flooded on fast links. The core reports the
            # mod + its required dependencies as ONE batch counted in FILE UNITS,
            # so the label says "file 2/3" and the percent is of the whole batch
            # - a single file no longer restarts the bar at 0 (see
            # batch_progress_text).
            _pct = {"v": -1}
            _eta = cubeon_eta.EtaEstimator()

            def _install_progress(done, total):
                pct = min(100, int(done * 100 / total)) if total else -1
                if pct != _pct["v"]:
                    _pct["v"] = pct
                    on_status(progress_text(done, total, batch=True,
                                            eta=_eta.note(done, total)))

            def worker():
                try:
                    result = {"failed": []}
                    feedback.check_cancelled()
                    if content_type == "mod":
                        result = core.install_mod_with_dependencies(
                            v["url"], v["filename"],
                            mc_version=detail_mc, loader=detail_loader,
                            version_id=detail_version,
                            slug=details.get("slug"), project_id=details.get("project_id"),
                            hashes=v.get("hashes"),
                            status_cb=on_status, progress_cb=_install_progress,
                            cancel_event=feedback.cancel_event,
                            **({"source": detail_source, "file_id": v.get("file_id") or v.get("id")}
                               if detail_source != "modrinth" else {"file_id": v.get("id")}),
                        )
                    else:
                        core.download_content(
                            content_type, v["url"], v["filename"],
                            mc_version=detail_mc, version_id=detail_version,
                            loader=detail_loader, hashes=v.get("hashes"),
                            icon_url=details.get("icon_url"),
                            slug=details.get("slug"),
                            title=details.get("title"),
                            cancel_event=feedback.cancel_event,
                            progress_cb=lambda done, total: on_status(progress_text(done, total)))
                    if result.get("failed"):
                        self._refresh_after_install((content_type, detail_mc, detail_loader, detail_version))
                        on_error(RuntimeError("Installed, but dependencies failed: "
                                              + ", ".join(result["failed"])))
                        self._check_install_issues((content_type, detail_mc, detail_loader, detail_version), result.get("compatibility"))
                        return
                    self._refresh_after_install((content_type, detail_mc, detail_loader, detail_version))
                    with thread_safe_ui.TREE_LOCK:
                        installed_now[v["filename"]] = {"filename": v["filename"],
                                                       "file_id": v.get("file_id") or v.get("id"),
                                                       "version": v.get("version_number")}
                        on_done(0)
                    self._check_install_issues((content_type, detail_mc, detail_loader, detail_version), result.get("compatibility"))
                except Exception as ex:
                    on_error(ex)
            try:
                threading.Thread(target=worker, daemon=True).start()
            except Exception as error:
                on_error(error)

        quick_state = {"repaints": []}
        release_state = {"error": None, "checked": False, "next_offset": None, "loading": False}

        def _external_action(url):
            def visit(event):
                if _http_url(url):
                    self.page.run_task(ft.UrlLauncher().launch_url, url)
            def import_file(event):
                if (content_type, detail_mc, detail_loader, detail_version) == self._installed_target(content_type):
                    self.open_local_mod_picker(event)
            return ft.Column([
                ft.Text("Download on CurseForge, then import the JAR.", size=11, color=self.TEXT_DIM),
                ft.TextButton("Open CurseForge", on_click=visit),
                ft.TextButton("Import from file", on_click=import_file),
            ], spacing=0)

        def _install_button(v, details, *, label="Install", big=False):
            """An Install button that owns its busy / done / error states."""
            if v.get("compatible") and not v.get("url") and v.get("website_url"):
                return _external_action(v["website_url"])
            done = {"v": release_installed(v)}
            rust_target = content_type == "mod" and detail_source == "horizon" and rust_engine.is_instance(detail_version)
            blocked = (not detail_mc or not detail_loader or not detail_version
                       or not v.get('url') or not v.get('filename')
                       or (content_type != "resourcepack" and detail_loader not in MOD_CAPABLE_LOADERS and not rust_target)
                       or (rust_engine.is_instance(detail_version) and not rust_target)
                       or v.get('compatible') is False)
            blocked_note = ('This release has no downloadable file.' if not v.get('url') or not v.get('filename') else
                            (v.get('compatibility_reason') or "This build doesn't match this instance's Minecraft version or loader.")
                            if v.get('compatible') is False else
                            'Choose a compatible mod loader on the Play tab first.')
            fg = ON_ACCENT if big else self.ACCENT
            text = ft.Text(label, size=13 if big else 12,
                           weight=ft.FontWeight.W_700,
                           color=TEXT_FAINT if done["v"] else fg)
            icon = ft.Icon(ft.Icons.CHECK_ROUNDED if done["v"]
                           else ft.Icons.DOWNLOAD_ROUNDED,
                           color=TEXT_FAINT if done["v"] else fg,
                           size=16 if big else 15)
            btn = ft.Container(
                content=ft.Row([icon, text], spacing=8, tight=True),
                bgcolor=ACCENT_TINT if done["v"]
                else (self.ACCENT if big else ACCENT_TINT),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(
                    horizontal=16 if big else 12, vertical=12 if big else 8),
                ink=False, disabled=done["v"] or blocked,
                tooltip=blocked_note if blocked else None,
            )

            seen = {"result": feedback.result_id}
            def paint(job):
                if seen["result"] != job.result_id:
                    seen["result"] = job.result_id
                    if job.result == "success" and job.filename:
                        installed_now.setdefault(job.filename, {"filename": job.filename})
                done["v"] = release_installed(v)
                btn.disabled = job.cancelling if job.busy and job.cancellable else job.busy or done["v"] or blocked
                text.value = action_text(job) if job.busy else (
                    i18n.t("Installed") if done["v"] else "Try again" if job.result == "error" else label)
                text.color = self.TEXT_DIM if job.busy else TEXT_FAINT if done["v"] else self.DANGER if job.result == "error" else fg
                icon.icon = ft.Icons.CLOSE_ROUNDED if job.busy and job.cancellable else ft.Icons.CHECK_ROUNDED if done["v"] and not job.busy else ft.Icons.DOWNLOAD_ROUNDED
                icon.color = text.color
                btn.bgcolor = ROW_HOVER if job.busy else ACCENT_TINT if done["v"] or not big else self.ACCENT
                btn.tooltip = job.text if job.busy or job.result == "error" else (
                    blocked_note if blocked else None)

            def on_click(e):
                if feedback.busy:
                    feedback.cancel()
                    return
                if done["v"] or blocked or not feedback.start(v.get("filename"), "Installing...", cancellable=True):
                    return

                def finished(fixed):
                    feedback.finish(v.get("filename"))
                    for _repaint in quick_state.get("repaints", []):
                        try:
                            _repaint()
                        except Exception:
                            pass
                    if fixed:
                        dialogs.show_snack(self.page, f"Installed. Fixed {fixed} problem(s).",
                                           bgcolor=self.SURFACE_HI, text_color=self.TEXT)

                def failed(ex):
                    if isinstance(ex, net.DownloadCancelled):
                        feedback.finish(error=ex)
                        self._refresh_after_install((content_type, detail_mc, detail_loader, detail_version))
                        return
                    feedback.finish(v.get("filename"), error=f"Install failed: {ex}")
                    dialogs.show_snack(self.page, f"Install failed: {ex}",
                                       bgcolor=self.SURFACE_HI, text_color=self.TEXT)

                _run_install(v, details, on_status=feedback.status,
                             on_done=finished, on_error=failed)

            btn.on_click = on_click
            feedback.watch(btn, paint)
            return btn

        def _gallery_strip(gallery):
            """All screenshots, hero first, in a sideways-scrolling strip -
            one image made the menu feel like it was hiding the rest."""
            tiles = []
            for g in gallery[:8]:
                tiles.append(ft.Container(
                    content=self._art_image(g['url'], 300, 170),
                    border_radius=RADIUS,
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    border=ft.border.Border.all(1, CARD_BORDER),
                ))
            return ft.Row(tiles, spacing=12, scroll=ft.ScrollMode.AUTO)

        def _meta_line(details):
            """Only what a player decides on: how popular it is, what loader it
            runs on, and which Minecraft versions it covers."""
            pills = [self._provider_icon(detail_source)] if content_type == "mod" else []
            if details.get("downloads"):
                pills.append(self._detail_badge(
                    _human_count(details["downloads"]) + " downloads"))
            loaders = details.get("loaders") or []
            if loaders:
                pills.append(self._detail_badge(
                    " / ".join(x.title() for x in loaders[:3])))
            gvs = details.get("game_versions") or []
            if gvs:
                shown = ", ".join(gvs[:3]) + ("…" if len(gvs) > 3 else "")
                pills.append(self._detail_badge("Minecraft " + shown))
            return ft.Row(pills, spacing=8, run_spacing=8, wrap=True) if pills else None

        def _quick_action(details, versions):
            """The one thing most people came to do, at the top: get the newest
            build that matches their game, or see they already have it - no
            scanning a long list required."""
            compat = [v for v in versions if v.get("compatible") and v.get("url")]
            compat.sort(key=lambda v: v.get("date_published") or "", reverse=True)
            holder = ft.Container(width=180)

            def _paint():
                restricted = next((v for v in versions if v.get("compatible") and not v.get("url") and v.get("website_url")), None)
                if not compat and restricted:
                    holder.content = _external_action(restricted["website_url"])
                elif not compat:
                    message = ("Couldn't check compatible releases." if release_state["error"]
                               or not release_state["checked"] else
                               next((v.get("compatibility_reason") for v in versions if v.get("compatibility_reason")),
                                    "No matching build for this Minecraft version and loader."))
                    holder.content = ft.Column([
                        ft.Text(message, size=12.5, color=self.TEXT_DIM,
                                tooltip=release_state["error"]),
                        ft.TextButton(content="Retry", on_click=lambda event: self.open_mod_detail(mod, content_type, force=True),
                                      style=ft.ButtonStyle(color=self.ACCENT))], spacing=4)
                else:
                    best = compat[0]
                    vnum = str(best.get("version_number")
                               or best.get("name") or "").split("+", 1)[0]
                    if release_installed(best):
                        holder.content = ft.Row(
                            [ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=20,
                                     color=self.ACCENT),
                             ft.Column(
                                 [ft.Text("You're up to date", size=13,
                                          color=self.ACCENT,
                                          weight=ft.FontWeight.W_700),
                                  ft.Text(f"{vnum} is installed", size=11.5,
                                          color=self.TEXT_DIM)],
                                 spacing=4, expand=True)],
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER)
                    else:
                        holder.content = ft.Row(
                            [ft.Column(
                                [ft.Text("Latest for your setup", size=11,
                                         color=ft.Colors.with_opacity(0.7, self.TEXT), font_family=self.FONT_MONO),
                                 ft.Text(vnum, size=16, color=self.TEXT,
                                         weight=ft.FontWeight.W_800,
                                         font_family=self.FONT_MONO)],
                                spacing=4, expand=True),
                             _install_button(best, details,
                                             label="Install", big=True)],
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER)
                try:
                    thread_safe_ui.refresh(holder)
                except Exception:
                    pass

            quick_state["repaints"].append(_paint)
            _paint()
            return holder

        def _description_block(body):
            def open_link(event):
                safe_url = _http_url(event.data)
                if safe_url and callable(getattr(self.page, "run_task", None)):
                    self.page.run_task(ft.UrlLauncher().launch_url, safe_url)

            return ft.Markdown(readme_markdown(body) or blurb or "No description available.", selectable=True,
                extension_set=ft.MarkdownExtensionSet.GITHUB_WEB, shrink_wrap=True,
                image_error_content=ft.Text("Image unavailable", color=self.TEXT_DIM, size=11),
                on_tap_link=open_link, md_style_sheet=ft.MarkdownStyleSheet(
                    p_text_style=ft.TextStyle(color=self.TEXT, size=13, height=1.6),
                    a_text_style=ft.TextStyle(color=self.ACCENT),
                    h1_text_style=ft.TextStyle(color=self.TEXT, size=22, weight=ft.FontWeight.W_700),
                    h2_text_style=ft.TextStyle(color=self.TEXT, size=18, weight=ft.FontWeight.W_700),
                    h3_text_style=ft.TextStyle(color=self.TEXT, size=15, weight=ft.FontWeight.W_600),
                    list_bullet_text_style=ft.TextStyle(color=self.TEXT_DIM, size=13),
                    code_text_style=ft.TextStyle(color=self.ACCENT, font_family=self.FONT_MONO, size=12),
                    block_spacing=14),
                data="mod-detail-readme")

        def _versions_section(details, versions):
            """Compatible builds first, and only a handful of them - a mod like
            Sodium has hundreds of releases across every Minecraft version."""
            compat = [v for v in versions if v.get("compatible")]
            compat.sort(key=lambda v: v.get("date_published") or "", reverse=True)
            others = [v for v in versions if not v.get("compatible")]
            others.sort(key=lambda v: v.get("date_published") or "", reverse=True)
            version_limit = {'value': 8}
            list_holder = ft.Column(spacing=4)
            more_text = ft.Text("", size=12, color=self.ACCENT,
                                weight=ft.FontWeight.W_700)
            more = ft.Container(content=more_text, visible=False, ink=False,
                                padding=ft.padding.Padding.symmetric(vertical=8))

            def _paint():
                rows = []
                if not versions:
                    rows.append(ft.Text("Couldn't load releases. Use Retry above." if release_state["error"]
                                        else "No versions are available for this mod.",
                                        size=12.5, color=self.TEXT_DIM))
                else:
                    ordered = sorted(versions, key=lambda v: (bool(v.get("compatible")), v.get("date_published") or ""), reverse=True)
                    for v in ordered[:version_limit['value']]:
                        rows.append(_build_version_row(v, details))
                    hidden = max(0, len(ordered) - version_limit['value'])
                    if release_state["loading"]:
                        more.visible, more.disabled = True, True
                        more_text.value = "Loading releases…"
                    elif not hidden and release_state["next_offset"] is not None:
                        more.visible, more.disabled = True, False
                        more_text.value = "Retry more releases" if release_state["error"] else "Show more versions"
                    elif not hidden and version_limit['value'] > 8:
                        more.visible = True
                        more_text.value = "Show fewer versions"
                    elif hidden > 0:
                        more.visible = True
                        more_text.value = f"Show more versions ({hidden} more)"
                    else:
                        more.visible = False
                list_holder.controls = rows
                try:
                    thread_safe_ui.refresh(list_holder)
                    thread_safe_ui.refresh(more)
                except Exception:
                    pass

            def _toggle(e=None):
                if (detail_source == "curseforge" and version_limit['value'] >= len(versions)
                        and release_state["next_offset"] is not None):
                    if release_state["loading"]:
                        return
                    release_state["loading"] = True
                    _paint()
                    def load_more():
                        try:
                            items = core.get_mod_versions(lookup_ref, mc_version=detail_search_mc,
                                loader=detail_loader, offset=release_state["next_offset"],
                                force=bool(release_state["error"]))
                            with thread_safe_ui.TREE_LOCK:
                                if not current():
                                    return
                                seen_ids = {v["id"] for v in versions}
                                versions.extend(v for v in items if v["id"] not in seen_ids)
                                release_state["next_offset"] = getattr(items, "next_offset", None)
                                release_state["error"] = None
                                version_limit['value'] += 25
                        except Exception as error:
                            with thread_safe_ui.TREE_LOCK:
                                release_state["error"] = str(error)
                        finally:
                            with thread_safe_ui.TREE_LOCK:
                                release_state["loading"] = False
                                more.disabled = False
                                if current():
                                    _paint()
                    try:
                        threading.Thread(target=load_more, daemon=True, name="cubeon-mod-releases").start()
                    except Exception as error:
                        release_state.update(loading=False, error=str(error))
                        more.disabled = False
                        _paint()
                    return
                version_limit['value'] = (version_limit['value'] + 25
                                          if version_limit['value'] < len(versions) else 8)
                _paint()

            more.on_click = _toggle
            _paint()
            quick_state["repaints"].append(_paint)
            return ft.Column(
                [ft.Text(i18n.t("Versions"), size=15, color=self.TEXT,
                         weight=ft.FontWeight.W_700, font_family=self.FONT_MONO),
                 list_holder, more],
                spacing=8)

        def _render_details(details, versions):
            if not current():
                return
            gallery = [g for g in (details.get("gallery") or []) if g.get("url")]
            resolved_icon = details.get('icon_url') or icon_url
            if resolved_icon and hero_icon.data != resolved_icon:
                # Metadata often supplies the icon missing from an installed JAR row.
                # Keep the same Image and fixed footprint while its bytes load.
                hero_icon.data = resolved_icon
                cached_source = _icons.peek_src(resolved_icon)
                if _icons.valid_source(cached_source):
                    hero_icon.src = cached_source
                else:
                    def ready(source):
                        if current() and hero_icon.data == resolved_icon and _icons.valid_source(source):
                            hero_icon.src = source
                            thread_safe_ui.refresh(hero_icon)
                    self.artwork.request(resolved_icon, ready)
            hero_title.value = details.get("title") or title
            hero_title.tooltip = hero_title.value
            hero_description.value = details.get("description") or blurb
            author = details.get("author") or mod.get("author")
            target = " ".join(filter(None, [(detail_loader or "vanilla").title(), detail_mc]))
            hero_meta.value = " · ".join(filter(None, [f"by {author}" if author else "",
                f"Target: {target}" if target else ""]))
            hero_action.content = _quick_action(details, versions)
            thread_safe_ui.refresh(hero)
            sidebar = ft.Column(spacing=10)
            sidebar.controls.append(ft.Text(i18n.t("About this mod"), color=self.ACCENT, size=13,
                                            font_family=self.FONT_MONO))
            for label, value in (("Downloads", f"{details.get('downloads', 0):,}"),
                                 ("License", details.get("license") or "Not specified"),
                                 ("Categories", ", ".join(details.get("categories") or []) or "Not specified"),
                                 ("Environment", f"Client: {details.get('client_side') or 'Unknown'}\nServer: {details.get('server_side') or 'Unknown'}")):
                sidebar.controls.append(ft.Column([
                    ft.Text(i18n.t(label), color=self.TEXT_DIM, size=10.5),
                    ft.Text(str(value), color=self.TEXT, size=11.5, selectable=True)], spacing=4))
            sidebar.controls.append(ft.Text(i18n.t("Links"), color=self.ACCENT, size=13, font_family=self.FONT_MONO))
            from urllib.parse import quote
            project_link = (("Project on CurseForge", details.get("website_url")) if detail_source == "curseforge" else
                            ("Project on Horizon", details.get("website_url")) if detail_source == "horizon" else
                            ("Project on Modrinth", f"https://modrinth.com/{content_type}/{quote(details.get('slug') or ref, safe='')}"))
            if detail_source == "horizon":
                sidebar.controls.append(ft.Text(details.get("verification") or "Registry checksum · Unsigned package",
                                               size=11, color=self.TEXT_DIM))
            for label, url in (project_link,
                               ("Source code", details.get("source_url")), ("Report an issue", details.get("issues_url")),
                               ("Wiki", details.get("wiki_url")), ("Discord", details.get("discord_url"))):
                safe_url = _http_url(url)
                if safe_url:
                    sidebar.controls.append(ft.TextButton(content=i18n.t(label), url=safe_url,
                        icon=ft.Icons.OPEN_IN_NEW_ROUNDED, style=ft.ButtonStyle(color=self.ACCENT),
                        tooltip=safe_url))
            metadata = ft.Container(content=sidebar, padding=16, bgcolor=self.SURFACE_HI,
                border_radius=RADIUS, col={"xs": 12, "md": 3}, data="mod-detail-metadata")
            panes = {}
            active = {"value": "Overview"}

            def select(name):
                if not current():
                    return
                active["value"] = name
                if name not in panes:
                    if name == "Overview":
                        overview = ft.Column([_description_block(details.get("body") or "")], spacing=16)
                        panes[name] = ft.ResponsiveRow([
                            ft.Container(content=overview, col={"xs": 12, "md": 9}), metadata],
                            spacing=24, run_spacing=16, vertical_alignment=ft.CrossAxisAlignment.START)
                    elif name == "Versions":
                        panes[name] = _versions_section(details, versions)
                    else:
                        panes[name] = ft.Column([
                            _gallery_strip(gallery) if gallery else ft.Text("No gallery images available.", color=self.TEXT_DIM)], spacing=16)
                detail_tabs.controls = [ft.TextButton(content=i18n.t(label),
                    on_click=lambda event, chosen=label: select(chosen), data="mod-detail-tab-" + label.lower(),
                    style=ft.ButtonStyle(color=self.ACCENT if label == name else self.TEXT_DIM,
                        bgcolor=self.SURFACE_HI if label == name else None,
                        shape=ft.RoundedRectangleBorder(radius=RADIUS))) for label in ("Overview", "Versions", "Gallery")]
                detail_body.controls = [panes[name]]
                thread_safe_ui.refresh(detail_tabs)
                thread_safe_ui.refresh(detail_body)

            select(active["value"])

        def _build_version_row(v, details):
            vnum = str(v.get("version_number") or v.get("name")
                       or "version").split("+", 1)[0]
            already = release_installed(v)

            tags = list(v.get("loaders") or [])
            gv = v.get("game_versions") or []
            tag_text = " · ".join([x.title() for x in tags] + [", ".join(gv[:3])])
            if len(gv) > 3:
                tag_text += "…"

            return ft.Container(
                content=ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Row(
                                    [ft.Text(vnum, size=13.5, color=self.TEXT,
                                             weight=ft.FontWeight.W_700),
                                     *([self._detail_badge("match", "accent")]
                                       if v.get("compatible")
                                       else [self._detail_badge("other version")])],
                                    spacing=8,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.Text(
                                    (v.get("version_type") or "release").title()
                                    + (f"  ·  {tag_text}" if tag_text else ""),
                                    size=11, color=TEXT_FAINT,
                                    font_family=self.FONT_MONO, max_lines=2),
                            ],
                            spacing=4, expand=True,
                        ),
                        _install_button(
                            v, details,
                            label="Installed" if already else "Install"),
                    ],
                    spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=CARD_FILL if already else None,
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=8, vertical=8),
            )

        def worker():
            # Prism loads project information and the filtered version list as
            # separate jobs. Do the same so opening details costs one network
            # round-trip instead of two serial waits.
            def fetch_details():
                try:
                    return core.get_mod_details(lookup_ref, **({"force": True} if force else {})) or {}, None
                except Exception as error:
                    return {}, error

            def fetch_versions():
                try:
                    return core.get_mod_versions(
                        lookup_ref, mc_version=detail_search_mc,
                        loader=detail_loader if content_type == "mod" else None,
                        **({"force": True} if force else {}),
                        **({"file_id": mod["file_id"]} if mod.get("file_id") else {})), None
                except Exception as error:
                    return [], error

            with ThreadPoolExecutor(max_workers=2, thread_name_prefix="cubeon-mod-detail") as pool:
                details_job = pool.submit(fetch_details)
                versions_job = pool.submit(fetch_versions)
                details, _details_error = details_job.result()
                versions, versions_error = versions_job.result()

            release_state["next_offset"] = getattr(versions, "next_offset", None)
            release_state["checked"] = versions_error is None
            release_state["error"] = str(versions_error) if versions_error else None
            if content_type != "mod":
                candidates = content_mc_versions(detail_search_mc)
                versions = [dict(v, compatible=(not candidates or any(
                    candidate in (v.get("game_versions") or []) for candidate in candidates)))
                    for v in versions]
            details = {**mod, **details}
            try:
                target = (content_type, detail_mc, detail_loader, detail_version)
                with thread_safe_ui.TREE_LOCK:
                    items = (self.installed_snapshots.get(target) if
                             time.monotonic() - self.installed_snapshot_at.get(target, 0) < self.INSTALLED_CACHE_SECONDS
                             else None)
                if items is None:
                    snapshot = self._read_installed_snapshot(target)
                    items = snapshot.items
                    with thread_safe_ui.TREE_LOCK:
                        self._apply_installed_snapshot(snapshot)
                with thread_safe_ui.TREE_LOCK:
                    installed_now.clear()
                    installed_now.update((m['filename'].removesuffix('.disabled'), m)
                                         for m in items if m.get('filename'))
            except Exception:
                logging.getLogger(__name__).debug('detail installed scan failed', exc_info=True)
            if not details and not versions:
                def _failed():
                    detail_body.controls.clear()
                    detail_body.controls.append(ft.Text(
                        "Couldn't load this mod's details. Check your "
                        "connection and try again.", size=13, color=self.TEXT_DIM))
                    thread_safe_ui.refresh(detail_body)
                with thread_safe_ui.TREE_LOCK:
                    if current():
                        _failed()
                return
            with thread_safe_ui.TREE_LOCK:
                _render_details(details, versions)

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as error:
            with thread_safe_ui.TREE_LOCK:
                if current():
                    detail_body.controls[:] = [empty_state('Couldn\'t load details', str(error))]
                    thread_safe_ui.refresh(detail_body)

    def _browse_scrolled(self, event):
        ft.context.disable_auto_update()
        if event.pixels > 0 and event.max_scroll_extent - event.pixels <= 216:
            self._load_more_browse()

    def _load_more_browse(self, event=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            session = self.browse_state
            token = session["token"]
            if (session.get("infinite") and session.get("has_more")
                    and not session.get("provider_pending") and not self.detail_host.visible
                    and self._browse_current(token)):
                session["page"] += 1
                self._load_mod_page(session["page"], token)

    def _browse_page_prev(self, e=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if not self.browse_state.get("infinite") and self.browse_state["page"] > 0:
                self.browse_state["page"] -= 1
                self._render_browse_page()

    def _browse_page_next(self, e=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            total_pages = max(1, self.browse_state["total_pages"])
            if not self.browse_state.get("infinite") and self.browse_state["page"] < total_pages - 1:
                self.browse_state["page"] += 1
                self._render_browse_page()

    def build_browse_row(self, mod, is_installed=False):
        """
        Creates a row for a mod in the browse results.

        Reads like a store listing, not a database record: the mod's NAME is
        the dominant element (15px, bold), its description sits underneath at
        readable size, and download count is tiny metadata. The whole row is
        transparent until hovered - no enclosing slab - and the download
        action is a restrained green wash instead of a solid block, so five
        rows don't stack five loud buttons.
        """
        builtin = bool(mod.get('builtin_client'))
        row_content_type = self._ct()
        if mod.get('slug') and mod.get('icon_url'):
            self.installed_icon_urls[mod_catalogue.identity(mod) if mod.get("source") != "modrinth" and mod.get("source") else mod["slug"]] = mod["icon_url"]
        row_target = self._installed_target(row_content_type)
        compatibility_note = ""
        if row_content_type == "mod" and not mod.get("facet_compatible"):
            compatibility_note = mod_compatibility_note(
                mod, self.current_mc_version_for_search(), self.loader_for_content())
        row_source = mod_catalogue.source_of(mod)
        key = self._row_key(mod_catalogue.identity(mod))
        feedback = self.install_registry.project(key[:4] + (row_source,), mod.get("project_id") or mod.get("slug") or mod.get("title"), mod.get("slug"))
        cached = self.browse_rows.get(key)
        if cached and cached[0] == mod:
            cached[2](is_installed)
            return cached[1]
        compatible = not compatibility_note
        available = not is_installed and compatible and self._can_install(row_content_type, verify=False)
        # The download button's text and icon change based on installed status
        download_btn_text = ft.Text(
            i18n.t("Installed") if is_installed else "Incompatible" if not compatible else "Install",
            size=12.5, weight=ft.FontWeight.W_700,
            color=ON_ACCENT if available else self.TEXT_DIM,
            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True,
        )
        download_btn = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECK_ROUNDED if is_installed else ft.Icons.DOWNLOAD_ROUNDED,
                            color=ON_ACCENT if available else self.TEXT_DIM, size=15),
                    download_btn_text,
                ],
                spacing=6,
            ),
            bgcolor=self.ACCENT if available else None,
            width=104, height=30, alignment=ft.Alignment.CENTER,
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=8),
            ink=False,
            disabled=is_installed or not compatible or not self._can_install(row_content_type, verify=False),
            tooltip=(compatibility_note or
                     ("Choose a compatible mod loader on the Play tab first."
                      if not self._can_install(row_content_type, verify=False) else None)),
        )

        def on_download(e):
            """
            Handles the download of a mod. It finds the appropriate file (compatible with
            current Minecraft version and loader), then downloads it and refreshes the installed list.
            """
            if feedback.busy:
                feedback.cancel()
                return
            if builtin:
                self._install_client(row_target, feedback)
                return
            content_type = row_content_type
            if row_target != self._installed_target(row_content_type):
                return
            if not self._can_install(content_type) or (content_type == "mod" and compatibility_note):
                return
            _, selected_mc, selected_loader, selected_version = row_target
            search_mc_version = self.current_mc_version_for_search()
            force_lookup = feedback.result == "error"
            if row_state["installed"] or not feedback.start(cancellable=True):
                return

            def worker():
                try:
                    # Search against the numeric MC version (Modrinth wants
                    # "1.20.4", not a loader-qualified id). For mods, STORE the
                    # download under state["selected_mc_version"] + loader - the
                    # exact keys list_mods()/sync_mods_to_game() use - so the
                    # mod ends up in the profile the game reads. Resource packs
                    # and shaders also use the captured instance's profile.
                    feedback.check_cancelled()
                    if content_type == "mod":
                        file_info = core.get_mod_download(mod["project_id"], mc_version=search_mc_version,
                                                          loader=selected_loader, cancel_event=feedback.cancel_event,
                                                          **({"source": row_source} if row_source != "modrinth" else {}),
                                                          **({"file_id": mod["file_id"]} if mod.get("file_id") else {}),
                                                          **({"force": True} if force_lookup else {}))
                    else:
                        file_info = core.get_content_download(content_type, mod["project_id"], mc_version=search_mc_version,
                                                              cancel_event=feedback.cancel_event)
                    feedback.check_cancelled()
                    if not file_info:
                        feedback.finish(error="No matching build for this version and loader.")
                        return

                    feedback.status("Downloading...")
                    # Progress on the button itself (bugs-and-flaws follow-up: a
                    # static "Downloading..." gave no way to tell a 2 MB shader
                    # from a 400 MB mod). Coalesced to whole percent so
                    # page.update() isn't flooded. The two callers below report
                    # in DIFFERENT units, so each gets its own label: the mod
                    # path counts the whole install (the mod + its required
                    # dependencies) in FILE UNITS, the resourcepack/shader path
                    # counts bytes.
                    _pct = {"v": -1}

                    def _reporter(label_fn):
                        _eta = cubeon_eta.EtaEstimator()

                        def _report(done, total):
                            pct = min(100, int(done * 100 / total)) if total else done // 65536
                            if pct == _pct["v"]:
                                return
                            _pct["v"] = pct
                            feedback.status(label_fn(done, total, _eta.note(done, total)))
                        return _report

                    def _bytes_label(done, total, eta=None):
                        return progress_text(done, total, eta=eta)

                    _progress = _reporter(_bytes_label)
                    _batch_progress = _reporter(lambda d, t, eta: progress_text(d, t, batch=True, eta=eta))
                    # Keep dependency/repair details in the success tooltip;
                    # the compact action label stays readable.
                    deps_note = ""
                    # Any compatibility repair the install needed, so the user
                    # is told why a pack they just installed was touched.
                    fix_note = {"text": ""}

                    def _note_fix(rep):
                        fix_note["text"] = rep.get("reason") or ""

                    if content_type == "mod":
                        # mc_version/loader must be passed explicitly - without
                        # them this silently lands in the wrong profile folder
                        # (get_profile_dir(None, None) => "unknown-vanilla") and
                        # the game never finds it at launch. See cubeon/mods.py.
                        #
                        # install_mod_with_dependencies also pulls in every
                        # REQUIRED Modrinth dependency the profile doesn't have
                        # yet (Fabric API is the classic one), so a fresh click
                        # actually results in a mod that loads in-game.
                        def _dep_status(t):
                            feedback.status(t)
                        result = core.install_mod_with_dependencies(
                            file_info["url"], file_info["filename"],
                            mc_version=selected_mc, loader=selected_loader,
                            version_id=selected_version,
                            slug=mod.get("slug"), project_id=mod.get("project_id"),
                            hashes=file_info.get("hashes"),
                            status_cb=_dep_status, progress_cb=_batch_progress,
                            cancel_event=feedback.cancel_event,
                            **({"source": row_source, "file_id": file_info.get("file_id") or file_info.get("id")}
                               if row_source != "modrinth" else {"file_id": file_info.get("modrinth_version_id")}),
                        )
                        deps_note = f" +{len(result['installed']) - 1} deps" \
                            if len(result["installed"]) > 1 else ""
                        if result["failed"]:
                            feedback.finish(file_info["filename"], error="Installed, but dependencies failed: " + ", ".join(result["failed"]))
                            self._refresh_after_install((content_type, selected_mc, selected_loader, selected_version))
                            self._check_install_issues((content_type, selected_mc, selected_loader, selected_version), result.get("compatibility"))
                            return
                    else:
                        # hashes = Modrinth's per-file sha512/sha1; passing them
                        # makes the install reject a corrupt/truncated transfer
                        # instead of dropping bad bytes into resourcepacks/.
                        # mc_version/version_id/fix_cb: the core then checks the
                        # pack's own pack.mcmeta against every installed version
                        # and widens its range if the game would show it as
                        # Incompatible (an author's Modrinth version list is not
                        # what the game reads).
                        core.download_content(
                            content_type, file_info["url"], file_info["filename"],
                            progress_cb=_progress,
                            hashes=file_info.get("hashes"),
                            mc_version=selected_mc,
                            version_id=selected_version,
                            loader=selected_loader,
                            icon_url=mod.get("icon_url"),
                            slug=mod.get("slug"),
                            title=mod.get("title"),
                            fix_cb=_note_fix, cancel_event=feedback.cancel_event)

                    feedback.finish(file_info["filename"], note=fix_note["text"] or (
                        "Installed" + deps_note if deps_note else None))
                    self._refresh_after_install((content_type, selected_mc, selected_loader, selected_version))
                    # Automatic repair: catch a duplicate/missing dependency
                    # introduced by this install before it can crash a launch.
                    if (content_type == "mod" and not rust_engine.is_instance(selected_version)
                            and selected_mc == self.state["selected_mc_version"]
                            and selected_loader == self.browse_loader()
                            and selected_version == self.version_dropdown.value):
                        self.run_mod_repair()
                except net.DownloadCancelled as error:
                    feedback.finish(error=error)
                    self._refresh_after_install((content_type, selected_mc, selected_loader, selected_version))
                except mod_catalogue.ExternalDownloadRequired as error:
                    feedback.finish(error=error)
                    with thread_safe_ui.TREE_LOCK:
                        if row_target == self._installed_target(row_content_type):
                            self.open_mod_detail(mod, row_content_type, force=True)
                except Exception as ex:
                    # Say WHY in one line - "Failed" alone left the user with
                    # no idea whether to retry, free up disk, or pick another
                    # file. net.DownloadError messages are already human-sized.
                    reason = (str(ex).strip().splitlines() or [""])[0] \
                        or type(ex).__name__
                    feedback.finish(error=f"Failed - {status_text.human(reason)}")

            try:
                threading.Thread(target=worker, daemon=True).start()
            except Exception as error:
                feedback.finish(error=f"Couldn't start installation: {error}")

        if not is_installed:
            download_btn.on_click = on_download

        description = (mod.get("description") or "").strip()
        # Cache this row's art for the next render (no-op if already cached).

        # Compact horizontal tiles keep artwork, identity and the action in
        # fixed slots. Descriptions stay in the tooltip and project details.
        download_btn.width, download_btn.height = 96, 30
        metadata = [ft.Icon(ft.Icons.DOWNLOAD_OUTLINED, size=12, color=TEXT_FAINT),
                    ft.Text("Bundled" if builtin else downloads_label(mod.get('downloads')),
                            size=10.5, color=self.TEXT_DIM)]
        if not builtin:
            metadata.append(self._provider_icon(row_source))
        icon = ft.Container(
            ft.Image(src="icon_64.png", width=44, height=44, fit=ft.BoxFit.CONTAIN)
            if builtin else self._art_image(mod.get("icon_url")),
            width=44, height=44, border_radius=RADIUS,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )
        row = style_tile(ft.Container(
            content=ft.Row([
                icon,
                ft.Column([
                    ft.Text(mod["title"], size=13.5, color=self.TEXT,
                            weight=ft.FontWeight.W_700, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(mod.get('author') or mod.get('author_name') or 'Community project',
                            size=11, color=self.TEXT_DIM, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Row(metadata, spacing=6, tight=True),
                ], spacing=3, expand=True, alignment=ft.MainAxisAlignment.CENTER),
                download_btn,
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            tooltip=compatibility_note or description or f"{mod.get('downloads', 0):,} downloads · Open details",
        ), self.SURFACE, self.BORDER, ROW_HOVER)
        row.on_click = None if builtin else lambda e: self.open_mod_detail(mod, row_content_type)
        if builtin:
            row.data = 'cubeon-client-browse'
            download_btn.data = 'cubeon-client-install'

        row_state = {"installed": is_installed, "result": feedback.result_id}
        def paint(job):
            if row_state["result"] != job.result_id:
                row_state["result"] = job.result_id
                if job.result == "success":
                    row_state["installed"] = True
            installed = row_state["installed"]
            download_btn.visible = True
            icon = download_btn.content.controls[0]
            icon.icon = ft.Icons.CLOSE_ROUNDED if job.busy and job.cancellable else ft.Icons.CHECK_ROUNDED if installed and not job.busy else ft.Icons.DOWNLOAD_ROUNDED
            download_btn_text.value = action_text(job, compact=True) if job.busy else (
                "Try again" if builtin and job.result == "error" else
                "Reinstall" if builtin and installed else i18n.t("Installed") if installed else "Try again" if job.result == "error"
                else "Incompatible" if not compatible else "Install")
            can_install = (builtin or not installed) and compatible and self._can_install(row_content_type, verify=False)
            download_btn_text.color = (self.TEXT_DIM if job.busy or not can_install else
                                       self.DANGER if job.result == 'error' else ON_ACCENT)
            icon.color = download_btn_text.color
            download_btn.bgcolor = self.SURFACE_HI if job.busy else self.ACCENT if can_install and job.result != 'error' else None
            download_btn.disabled = job.cancelling if job.busy and job.cancellable else job.busy or (installed and not builtin) or not compatible or not self._can_install(row_content_type, verify=False)
            download_btn.tooltip = (f"Cancel download · {job.text}" if job.busy and job.cancellable and not job.cancelling
                                    else job.text) if job.busy or job.result == "error" else (
                job.note if installed else compatibility_note or None)
            download_btn.on_click = None if installed and not builtin and not job.busy else on_download

        def sync_action(installed):
            row_state["installed"] = installed
            paint(feedback)

        feedback.watch(download_btn, paint)
        feedback.watch(row, paint)

        self._remember_row(self.browse_rows, key, (dict(mod), row, sync_action))
        return row

    def _sync_shader_notice(self):
        """Describe shader support without promising an instance conversion."""
        loader = self.state.get('mod_loader')
        self.shader_setup_btn.disabled = self.setup_busy or not self._can_install('shader', verify=False)
        if loader in ("fabric", "quilt", 'neoforge'):
            self.shader_notice_text.value = ("Shaders need Iris (with Sodium) to run. "
                                        "Install the compatible build for this instance.")
            self.shader_setup_label.value = "Install Iris"
        elif loader == 'forge':
            self.shader_notice_text.value = 'Shaders need Oculus and its dependencies. Availability depends on your Minecraft version.'
            self.shader_setup_label.value = 'Install Oculus'
        else:
            self.shader_notice_text.value = 'Shaders need a mod loader. Create or choose a Fabric instance on Play first.'
            self.shader_setup_label.value = "Set up shaders"

    def _setup_shaders(self):
        """Install Iris or Oculus and required dependencies for this loader.

        Resolve compatible builds without changing the selected instance.
        """
        if self.setup_busy:
            return
        target = self._installed_target()

        def say(text, bad=False):
            with thread_safe_ui.TREE_LOCK:
                if target != self._installed_target():
                    return
                self.local_install_status.value = text
                self.local_install_status.color = self.DANGER if bad else self.TEXT_DIM
                self.local_install_status.visible = True
                thread_safe_ui.refresh(self.local_install_status)

        if not self.state.get("selected_mc_version") or not self.version_dropdown.value:
            say("Pick a Minecraft version on the Play tab first.", bad=True)
            return
        if not self._can_install('shader'):
            say('Choose a mod-loader instance on Play first.', bad=True)
            return
        self.setup_busy = True
        self.shader_setup_btn.disabled = True
        self.shader_setup_label.value = "Setting up..."
        thread_safe_ui.refresh(self.shader_setup_btn)

        def worker():
            try:
                loader, mc, version_id, search_mc = setup_target
                project = 'oculus' if loader == 'forge' else 'iris'
                label = project.title()
                say(f"Finding {label}...")
                info = core.get_mod_download(project, mc_version=search_mc, loader=loader)
                if not info:
                    say(f"{label} has no build for Minecraft {search_mc} with {loader.title()}. Choose another compatible instance.", bad=True)
                    return
                result = core.install_mod_with_dependencies(
                    info["url"], info["filename"],
                    mc_version=mc, loader=loader, version_id=version_id,
                    slug=project, project_id=info.get("project_id") or project,
                    hashes=info.get("hashes"),
                    status_cb=lambda t: say(status_text.human(t)),
                    progress_cb=lambda done, total: say(
                        f"Installing {label} and dependencies... {int(done * 100 / total)}%") if total else None,
                )
                self._refresh_after_install(target)
                if result.get("failed"):
                    say("Installed, but these failed: " + ", ".join(result["failed"]), bad=True)
                else:
                    say(f"{label} is installed. Add a shader pack, press Play, then select it in the game's shader settings.")
            except Exception as ex:
                say(f"Couldn't set up shaders: {ex}", bad=True)
            finally:
                with thread_safe_ui.TREE_LOCK:
                    self.setup_busy = False
                    self._sync_shader_notice()
                    thread_safe_ui.refresh(self.shader_notice)

        setup_target = (self.state.get('mod_loader'), self.state['selected_mc_version'],
                        self.version_dropdown.value, self.current_mc_version_for_search())
        try:
            threading.Thread(target=worker, daemon=True, name="ux-shader-setup").start()
        except Exception as error:
            self.setup_busy = False
            self.shader_setup_btn.disabled = False
            say(f"Couldn't start shader setup: {error}", bad=True)
            self._sync_shader_notice()

    def _sync_view_hosts(self, animate=False):
        self.select_view(self.active_view['value'], animate=animate)
        for host, view in ((self.browse_search_host, 'browse'), (self.installed_search_host, 'installed')):
            host.visible = self.active_view['value'] == view
            host.disabled = not host.visible
        thread_safe_ui.refresh(self.search_port)

    def _build_view_segment(self):
        update_view_action(self.view_segment_row, self.active_view['value'], self._installed_display_count(),
                           self.on_view_change, data='mods-installed-toggle', color=self.TEXT_DIM,
                           compact=True)

    def on_view_change(self, new_view):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if self.active_view["value"] == new_view:
                return
            self.active_view["value"] = new_view
            self.browse_pane.visible = (new_view == "browse")
            self.installed_pane.visible = (new_view == "installed")
            self._sync_view_hosts(animate=True)
            self.browse_scope_text.visible = (new_view == "browse")
            thread_safe_ui.refresh(self.browse_scope_text)
            self._build_view_segment()
            self._load_visible_content()
            thread_safe_ui.refresh(self.browse_pane)
            thread_safe_ui.refresh(self.installed_pane)

    def refresh_browse_for_new_profile(self):
        """
        Called whenever the selected version or loader changes elsewhere in
        the app (Play tab dropdown, loader switcher). The Installed list is
        already kept in sync via refresh_mods_list(), but the Browse section
        was only ever loaded once on first tab open - meaning if you changed
        version/loader afterward, it kept showing mods for the OLD profile,
        which could be the wrong version or not even support the new loader.
        This re-fetches so Browse always matches what's actually selected.
        """
        key = (self.state.get("selected_mc_version"), self.state.get("mod_loader"), self.version_dropdown.value)
        if key == self.browse_profile["key"]:
            return  # nothing actually changed for browse purposes
        self.browse_profile["key"] = key
        # Only bother re-fetching if the tab has been opened at least once -
        # otherwise this fires on startup before the user ever sees Mods.
        if self.state.get("mods_recommendations_loaded") and self._tab_visible():
            self._load_visible_content()

    def selector_style(self, selected):
        return ft.ButtonStyle(
            color=self.TEXT if selected else self.TEXT_DIM, bgcolor=self.SURFACE_HI if selected else 'transparent',
            shape=ft.RoundedRectangleBorder(radius=6),
            side=ft.BorderSide(1, self.BORDER if selected else 'transparent'),
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=6),
        )

    def pack_detail_changed(self, visible):
        self.content_selector.visible = not visible
        thread_safe_ui.refresh(self.content_selector)

    def refresh_client_preference(self):
        with thread_safe_ui.TREE_LOCK:
            self._render_installed_snapshot(self._cached_installed(), loading=self._installed_target() not in self.installed_snapshots)

    def _tab_visible(self):
        # Standalone builders have no launcher shell and are visible by default.
        return (self.state.get('active_tab', 'mods') == 'mods'
                and self.selected_content['value'] != 'modpack')

    def _load_visible_content(self):
        """Load the selected pane; catalogue, file scan, then checks as needed.

        Browse starts provider page one and reads install badges after a result
        arrives. Installed starts its snapshot and checks compatibility after
        that read completes. Cached panes keep their rows and skip repeated work.
        """
        if self.selected_content['value'] == 'modpack':
            if self.on_modpacks_open:
                self.on_modpacks_open()
            return
        self._sync_content_notices()
        self._sync_local_install_action()
        if self.active_view['value'] == 'installed':
            self.refresh_mods_list(background=True, navigation=True)
            return
        token = self.browse_state['token']
        session = self.browse_sessions.get(self._browse_key())
        stale = (session and session.get('provider_errors') and
                 (not session.get('infinite') or not any(session['pages'].values())) and
                 time.monotonic() - session.get('fetched_at', 0) >= 60)
        if not self._browse_current(token) or stale:
            self.run_mod_search()
        else:
            self.refresh_mods_list(background=True, navigation=True)

    def open_hook(self):
        """Enter the retained Mods surface without replaying cached loads."""
        with thread_safe_ui.TREE_LOCK:
            self._load_visible_content()


def build_mods_tab(page: ft.Page, cfg: dict, state: dict, version_dropdown: ft.Dropdown, *,
                    section_label,
                    BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                    TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO,
                    switch_loader=None, modpacks_content=None, on_modpacks_open=None,
                    on_client_mod_change=None):
    """Build one ModsView and retain the launcher's four-value callback API."""
    view = ModsView(
        page, cfg, state, version_dropdown,
        section_label=section_label,
        BG=BG, SURFACE=SURFACE, SURFACE_HI=SURFACE_HI, BORDER=BORDER,
        ACCENT=ACCENT, ACCENT_DIM=ACCENT_DIM, TEXT=TEXT, TEXT_DIM=TEXT_DIM,
        DANGER=DANGER, FONT_DISPLAY=FONT_DISPLAY, FONT_MONO=FONT_MONO,
        switch_loader=switch_loader, modpacks_content=modpacks_content,
        on_modpacks_open=on_modpacks_open, on_client_mod_change=on_client_mod_change,
    )
    return view.mods_tab, view.refresh_mods_list, view.open_hook, view.refresh_browse_for_new_profile
