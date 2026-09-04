"""
Cubeon - Mods tab UI.
Lets the user browse/download mods from Modrinth and manage the mods already
installed for the currently selected Minecraft version + loader.

This module defines the UI for the 'Mods' tab in the launcher. It is built
the same way as skin_tab.py: a build_mods_tab() function that main.py calls
once at startup, which returns the tab's root control plus a couple of
functions main.py needs to call from elsewhere (e.g. when the version or
loader switcher changes on the Play tab, the mods list needs to be
re-filtered for the new version+loader profile).
"""

# Standard library imports
import re          # For turning mod names into comparable "slugs"
import threading   # For running network calls in the background without freezing the UI

# Flet imports - Flet is a UI framework for Python (like Flutter)
import flet as ft

from cubeon.theme import (  # design system: blocky radius, on-accent fg, hover states
    RADIUS, ON_ACCENT, ACCENT_HI, INFO, attach_hover,
    TEXT_FAINT, CARD_FILL, CARD_BORDER, ROW_HOVER, ACCENT_TINT,
    quiet_chip, text_tab, pixel_divider, animated_switch,
)

# Our own launcher core module - contains all the actual mod file/network logic
import launcher_core as core

from cubeon import icons as _icons  # disk cache for Modrinth project art
from cubeon import thread_safe_ui  # TREE_LOCK for safe background-tree writes


def build_mods_tab(page: ft.Page, cfg: dict, state: dict, version_dropdown: ft.Dropdown, *,
                    section_label,
                    BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                    TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO):
    """
    Builds the Mods tab's root control (a Flet Column) and returns it along
    with a couple of functions main.py needs to call from other tabs.

    Args:
        page: The Flet page instance - needed to trigger page.update() from callbacks.
        cfg: The launcher configuration dictionary (unused directly here, kept
             for symmetry with the other tab builders and future settings).
        state: The shared mutable state dict from main.py. This module reads
               state["selected_mc_version"] and state["mod_loader"] - it never
               sets them, since those belong to the Play tab's version/loader
               controls; it only reacts to them.
        version_dropdown: The Play tab's version Dropdown control, needed to
               figure out which Minecraft version to search Modrinth against.
        section_label: Shared helper from main.py to create small section headings.
        BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM, TEXT, TEXT_DIM,
        DANGER, FONT_DISPLAY, FONT_MONO: Shared design tokens from main.py.

    Returns:
        A tuple (mods_tab, refresh_mods_list, load_recommended_mods, refresh_browse_for_new_profile):
          - mods_tab: ft.Column, the tab's root control.
          - refresh_mods_list: call this whenever the selected version or
            loader changes elsewhere in the app, so the Mods tab stays honest
            about which profile it's showing.
          - load_recommended_mods: call this the first time the user opens
            the Mods tab, to populate the browse section.
          - refresh_browse_for_new_profile: call this whenever the selected
            version or loader changes elsewhere in the app, so the Browse
            section (recommendations/search results) doesn't keep showing
            mods for a version/loader you've since switched away from.
    """

    # --- UI elements for the Mods tab ---

    # List of installed mods (will be populated by refresh_mods_list)
    mods_list_view = ft.Column(spacing=8)
    installed_count_text = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO)
    installed_show_all = {"value": False}

    # --- Installed-mod icons -------------------------------------------------
    # Installed jars only record their Modrinth *slug* in a sidecar file - the
    # icon the browse row showed isn't stored anywhere. So the installed list
    # renders instantly with a placeholder, then one bulk slug->icon lookup
    # (core.get_mod_icons, session-cached) patches real art in the moment it
    # lands. Manually-dropped jars have no slug and keep the placeholder.
    installed_icon_urls = {}   # slug -> icon URL (or None once resolved-and-missing)
    pending_icon_holders = {}  # slug -> [placeholder Containers awaiting art]

    def _icon_image(url):
        # Disk-cached art: the first-ever render uses the remote URL (exactly
        # as before) while a background thread files the bytes away; every
        # render after that shows the cached file (base64 src - Flet can't
        # load our absolute cache path directly) - instant and offline-safe.
        from cubeon import icons as _icons
        _icons.prefetch(url)
        return ft.Image(
            src=_icons.src(url), width=34, height=34, border_radius=RADIUS,
            fit=ft.BoxFit.COVER,
            error_content=ft.Icon(ft.Icons.EXTENSION_OUTLINED, color=TEXT_FAINT, size=18),
        )

    def _make_installed_icon(m):
        """The 34px leading icon for an installed-mod row: real art when we
        have (or can fetch) the slug's icon, a quiet glyph otherwise."""
        slug = m.get("slug")
        holder = ft.Container(
            width=34, height=34, bgcolor=CARD_FILL, border_radius=RADIUS,
            alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )
        url = installed_icon_urls.get(slug) if slug else None
        if url:
            holder.content = _icon_image(url)
        else:
            holder.content = ft.Icon(ft.Icons.EXTENSION_OUTLINED, color=TEXT_FAINT, size=18)
            if slug:
                pending_icon_holders.setdefault(slug, []).append(holder)
        return holder

    def _fetch_missing_icons():
        """Fires the bulk icon lookup for any placeholders rendered this pass
        and swaps the art in as each URL arrives. Runs off the UI thread;
        core.get_mod_icons memoises, so repeated refreshes don't re-fetch."""
        slugs = [s for s in pending_icon_holders if s not in installed_icon_urls]
        if not slugs:
            return

        def worker():
            try:
                got = core.get_mod_icons(slugs)
            except Exception:
                return
            installed_icon_urls.update(got)
            # Mutate the tree under the shared lock (see thread_safe_ui.py):
            # Flet's diff walks the control tree on the loop thread, and this
            # worker's holder swaps must never land mid-walk.
            with thread_safe_ui.TREE_LOCK:
                for s, url in got.items():
                    if not url:
                        continue
                    for holder in pending_icon_holders.get(s, []):
                        holder.content = _icon_image(url)
                pending_icon_holders.clear()
            page.update()

        threading.Thread(target=worker, daemon=True).start()

    # --- Category filters: collapsed behind a "..." button ------------------
    # A wrapped strip of a dozen chips ate a lot of vertical space above the
    # content, so they now live behind one small overflow button and only
    # unfold on demand. The button tints green while a non-All filter is
    # applied, so an active filter is never silently hidden.
    filters_open = {"value": False}

    def on_filters_toggle(e=None):
        filters_open["value"] = not filters_open["value"]
        category_chips_container.visible = filters_open["value"]
        filters_button.icon_color = (
            ACCENT if (filters_open["value"] or active_category["value"]) else TEXT_DIM
        )
        page.update()

    filters_button = ft.IconButton(
        ft.Icons.MORE_VERT_ROUNDED, icon_color=TEXT_DIM, icon_size=20,
        tooltip="Filters", on_click=on_filters_toggle,
    )

    # Filter field to search installed mods by name
    installed_filter_field = ft.TextField(
        hint_text="Filter installed mods...",
        border_color=CARD_BORDER,
        focused_border_color=ACCENT_DIM,
        color=TEXT,
        hint_style=ft.TextStyle(color=TEXT_FAINT),
        text_style=ft.TextStyle(size=13),
        bgcolor=CARD_FILL,
        border_radius=RADIUS,
        height=40,
        content_padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        on_change=lambda e: refresh_mods_list(),  # Re-filter on each keystroke
    )

    def installed_slugs() -> set:
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
        names = set()
        for m in core.list_mods(state["selected_mc_version"], state["mod_loader"]):
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
        return names

    def content_installed_tokens() -> set:
        """Compact, punctuation-free tokens of installed pack/shader filenames,
        used to mark a browse result as already installed. Resource packs and
        shaders have no stored Modrinth slug (they're just .zips in a shared
        folder), so we can't match on an exact slug the way mods do - instead
        we check whether a project's compacted slug appears inside an installed
        filename (e.g. "complementaryreimagined" inside
        "ComplementaryReimagined_r5.5.zip"). Best-effort, never wrong in a way
        that blocks a download: a miss just shows "Download" again."""
        tokens = set()
        for it in core.list_content(_ct()):
            tokens.add(re.sub(r"[^a-z0-9]+", "", it["display_name"].lower()))
        return tokens

    def refresh_mods_list():
        """
        Reloads the installed list for whatever content type is active and
        updates the UI. Mods come from the per-(version, loader) profile;
        resource packs / shaders come from their single shared game folder.
        Applies the filter from the installed_filter_field.
        """
        if _is_mod():
            vanilla_mods_notice.visible = (state["mod_loader"] == "vanilla")
            shader_notice.visible = False
            all_mods = core.list_mods(state["selected_mc_version"], state["mod_loader"])
        else:
            vanilla_mods_notice.visible = False
            shader_notice.visible = (_ct() == "shader")
            all_mods = core.list_content(_ct())
        query = installed_filter_field.value.strip().lower()
        mods = [m for m in all_mods if query in m["display_name"].lower()] if query else all_mods

        mods_list_view.controls.clear()
        pending_icon_holders.clear()  # this render re-registers what it needs
        installed_count_text.value = (
            f"{len(all_mods)} installed" if not query else f"{len(mods)} of {len(all_mods)} shown"
        )

        # If nothing installed, show a placeholder worded for the active type.
        if not all_mods:
            if _is_mod():
                empty_icon = ft.Icons.EXTENSION_OFF_ROUNDED
                empty_title = "No mods installed yet"
                empty_hint = "Download something above, or drop .jar files into the mods folder."
            else:
                empty_icon = ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED
                empty_title = f"No {core.CONTENT_TYPES[_ct()]['label_plural'].lower()} installed yet"
                empty_hint = "Download something above, or drop .zip files into the folder."
            mods_list_view.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(empty_icon, color=TEXT_DIM, size=28),
                            ft.Text(empty_title, size=14, color=TEXT, weight=ft.FontWeight.W_600),
                            ft.Text(empty_hint, size=12, color=TEXT_DIM),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4,
                    ),
                    padding=32, alignment=ft.Alignment.CENTER,
                )
            )
        elif not mods:
            # Filter returned no results
            mods_list_view.controls.append(
                ft.Container(
                    content=ft.Text("Nothing installed matches that filter.", size=13, color=TEXT_DIM),
                    padding=20,
                )
            )
        else:
            # Build a row for each mod
            visible_mods = mods if query or installed_show_all["value"] else mods[:5]
            for m in visible_mods:
                mods_list_view.controls.append(build_installed_row(m))
            if not query and len(mods) > 5:
                hidden = len(mods) - 5
                mods_list_view.controls.append(
                    attach_hover(ft.Container(
                        content=ft.Text(
                            "Show fewer" if installed_show_all["value"] else f"Show all installed ({hidden} more)",
                            size=12, color=ACCENT, weight=ft.FontWeight.W_700,
                        ),
                        padding=ft.padding.Padding.symmetric(vertical=8, horizontal=10),
                        border_radius=RADIUS,
                        ink=True,
                        on_click=lambda e: (installed_show_all.update({"value": not installed_show_all["value"]}), refresh_mods_list()),
                    ), None, SURFACE_HI)
                )
        _fetch_missing_icons()
        page.update()

    def build_installed_row(m):
        """
        Creates a single row widget for an installed item. Mods get an
        enable/disable switch (they're synced per profile); resource packs and
        shaders don't - the game itself decides which are active - so they get
        just a name, size, and remove button.

        Deliberately NOT a boxed card: rows are transparent and lift only on
        hover, so the list reads as one calm surface instead of a stack of
        rectangles inside the enclosing rectangle.
        """
        if not _is_mod():
            def on_delete_content(e):
                core.delete_content(_ct(), m["filename"])
                refresh_mods_list()
                # The browse section above still shows this item as Installed
                # (a disabled checkmark) until it is re-rendered against the
                # live installed state - without this there is no way to see
                # its Download button again short of re-running the search.
                _render_browse_page()

            row_icon = (ft.Icons.IMAGE_OUTLINED if _ct() == "resourcepack"
                        else ft.Icons.AUTO_AWESOME_OUTLINED)
            return attach_hover(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(row_icon, color=TEXT_FAINT, size=20),
                            ft.Column(
                                [
                                    ft.Text(m["display_name"], size=13.5, color=TEXT,
                                            weight=ft.FontWeight.W_600),
                                    ft.Text(f"{m['size_kb']:,.0f} KB", size=10.5,
                                            color=TEXT_FAINT, font_family=FONT_MONO),
                                ],
                                spacing=2, expand=True,
                            ),
                            ft.IconButton(ft.Icons.CLOSE_ROUNDED, icon_color=TEXT_FAINT,
                                          icon_size=17, tooltip="Remove",
                                          on_click=on_delete_content),
                        ],
                        spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
                ),
                "transparent", ROW_HOVER,
            )

        def on_toggle(e):
            if m.get("protected"):
                return  # Cubeon-managed mod - core would refuse anyway
            core.toggle_mod(state["selected_mc_version"], state["mod_loader"], m["filename"])  # Enable/disable the mod
            refresh_mods_list()  # Refresh the list to reflect the new state

        def on_delete(e):
            if m.get("protected"):
                return  # Cubeon-managed mod - core would refuse anyway
            core.delete_mod(state["selected_mc_version"], state["mod_loader"], m["filename"])  # Delete the mod file
            refresh_mods_list()
            # Re-render the browse page so a just-deleted mod that is still on
            # it stops reading as Installed and offers Download again.
            _render_browse_page()

        return attach_hover(
            ft.Container(
                content=ft.Row(
                    [
                        # Enabled mods read brighter; disabled ones dim. State is
                        # typography, not a colored bar. The icon is the mod's
                        # real Modrinth art once its slug resolves (placeholder
                        # until then - manually-dropped jars have no slug).
                        _make_installed_icon(m),
                        ft.Column(
                            [
                                ft.Text(m["display_name"], size=13.5,
                                        color=TEXT if m["enabled"] else TEXT_DIM,
                                        weight=ft.FontWeight.W_600),
                                ft.Text(
                                    f"{m['size_kb']:,.0f} KB  ·  {'Enabled' if m['enabled'] else 'Disabled'}",
                                    size=11, color=TEXT_FAINT, font_family=FONT_MONO,
                                ),
                            ],
                            spacing=2, expand=True,
                        ),
                        # Protected mods (CustomSkinLoader, Cubeon Friends)
                        # get a lock instead of the toggle/delete controls -
                        # same treatment the server tab gives its managed
                        # plugins. They're re-installed at launch anyway, so
                        # removing them only ever broke skins or Friends.
                        *(
                            [ft.Container(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.LOCK_ROUNDED, size=14, color=TEXT_DIM),
                                    ft.Text("System", size=11, color=TEXT_DIM, font_family=FONT_MONO),
                                ], spacing=4, tight=True),
                                padding=ft.padding.Padding.symmetric(horizontal=8, vertical=4),
                            )]
                            if m.get("protected") else [
                                # Toggle switch
                                animated_switch(value=m["enabled"], active_color=ACCENT, on_change=on_toggle, scale=0.85),
                                # Delete button
                                ft.IconButton(ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color=TEXT_FAINT,
                                              icon_size=18, tooltip="Remove", on_click=on_delete),
                            ]
                        ),
                    ],
                    spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
            ),
            "transparent", ROW_HOVER,
        )

    def open_folder_click(e):
        """Opens the folder for the active content type in the system file explorer."""
        if _is_mod():
            core.open_mods_folder(state["selected_mc_version"], state["mod_loader"])
        else:
            core.open_content_folder(_ct())

    # --- Install from file: lets the user pick a .jar already on their
    # disk and drop it straight into the current profile's mods folder,
    # without needing to find/search it on Modrinth first. ---

    # Hidden while empty - a visible-but-blank Text still occupies a full line,
    # which is what opened a dead band between the segment tabs and search.
    local_install_status = ft.Text("", size=12, color=TEXT_DIM, visible=False)

    def handle_local_mod_files(files):
        if not files:
            return
        picked = files[0]
        local_install_status.value = "Installing..."
        local_install_status.visible = True
        page.update()
        try:
            if _is_mod():
                core.install_local_mod(picked.path, state["selected_mc_version"], state["mod_loader"])
            else:
                core.install_local_content(_ct(), picked.path)
            local_install_status.value = f"Installed '{picked.name}'."
            refresh_mods_list()
        except ValueError as ve:
            local_install_status.value = str(ve)
        except Exception as ex:
            local_install_status.value = f"Install failed: {ex}"
        local_install_status.visible = True
        page.update()

    def on_local_mod_picked(e):
        # Old-Flet path: pick_files() ran synchronously and the result
        # arrives here via on_result. Untyped rather than annotated as
        # ft.FilePickerResultEvent - that class is missing on some pinned
        # Flet builds (e.g. 0.86.x) and a hard annotation crashes this
        # function's definition at import time on those builds.
        handle_local_mod_files(e.files)

    local_mod_file_picker = ft.FilePicker()
    local_mod_file_picker.on_result = on_local_mod_picked

    # Same version-spanning registration dance used for the profile
    # picture / skin FilePickers in main.py and skin_tab.py - newer Flet
    # self-registers Services, older Flet needs the explicit overlay append.
    _lmf_registered = False
    _lmf_services_list = getattr(page, "_services", None)
    _lmf_already_registered = (
        _lmf_services_list is not None
        and hasattr(_lmf_services_list, "_services")
        and local_mod_file_picker in _lmf_services_list._services
    )
    _lmf_register_fn = getattr(page, "register_service", None)
    if _lmf_already_registered:
        _lmf_registered = True
    elif callable(_lmf_register_fn):
        try:
            _lmf_register_fn(local_mod_file_picker)
            _lmf_registered = True
        except Exception:
            _lmf_registered = False
    if not _lmf_registered:
        try:
            if local_mod_file_picker not in page.overlay:
                page.overlay.append(local_mod_file_picker)
        except Exception:
            pass

    def open_local_mod_picker(e):
        if _is_mod():
            exts, title = ["jar"], "Choose a mod .jar"
        else:
            exts, title = ["zip"], f"Choose a {_type_label()} .zip"
        core.run_file_picker(
            page, local_mod_file_picker,
            on_files=handle_local_mod_files,
            dialog_title=title,
            allow_multiple=False,
            allowed_extensions=exts,
        )

    # --- Browse / download section (Modrinth integration) ---

    # Search happens LIVE as you type: a short debounce timer restarts on
    # every keystroke and only the last one actually fires, so typing
    # "sodium" costs one request instead of six. That's what lets the big
    # green "Search" button disappear - there was nothing left for it to do.
    mod_search_field = ft.TextField(
        hint_text="Search mods on Modrinth... e.g. sodium, iris, jei",
        border_color=CARD_BORDER,
        focused_border_color=ACCENT_DIM,
        color=TEXT,
        hint_style=ft.TextStyle(color=TEXT_FAINT),
        text_style=ft.TextStyle(size=13.5),
        bgcolor=CARD_FILL,
        border_radius=RADIUS,
        height=46,
        content_padding=ft.padding.Padding.symmetric(horizontal=14, vertical=12),
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        on_submit=lambda e: run_mod_search(),  # Enter = search immediately
        expand=True,
    )
    _search_debounce = {"timer": None}

    def _schedule_live_search(e=None):
        """Debounced on_change: cancel any pending search, start a new one."""
        pending = _search_debounce["timer"]
        if pending is not None:
            pending.cancel()
        _search_debounce["timer"] = threading.Timer(0.45, run_mod_search_safe)
        _search_debounce["timer"].daemon = True
        _search_debounce["timer"].start()

    def run_mod_search_safe():
        """The debounce fires on a background thread; route back onto the UI
        thread through Flet's page.run_task equivalent used elsewhere here
        (thread-safe page.update is installed app-wide)."""
        try:
            run_mod_search()
        except Exception:
            pass

    mod_search_field.on_change = _schedule_live_search

    browse_results_view = ft.Column(spacing=8)  # Will hold the search/recommendation results
    browse_status_text = ft.Text("", size=12, color=TEXT_DIM)
    # Full result set + current page live here so _render_browse_page() can
    # slice out just the 5 items to show without re-fetching from Modrinth.
    browse_state = {"results": [], "page": 0, "empty_msg": ""}
    browse_pager_label = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO)
    browse_pager_prev = ft.Container(
        content=ft.Icon(ft.Icons.CHEVRON_LEFT_ROUNDED, size=18, color=TEXT),
        padding=6, border_radius=RADIUS, ink=True,
    )
    browse_pager_next = ft.Container(
        content=ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=18, color=TEXT),
        padding=6, border_radius=RADIUS, ink=True,
    )
    browse_pager_row = ft.Row(
        [browse_pager_prev, browse_pager_label, browse_pager_next],
        alignment=ft.MainAxisAlignment.CENTER, spacing=4, visible=False,
    )
    browse_title_text = ft.Text("Recommended", size=12,
                                 color=TEXT_DIM, font_family=FONT_MONO)

    # Currently selected category filter ("" = All). Kept as mutable state
    # so both the chip row and the search/recommend functions can read it.
    active_category = {"value": ""}

    # Which kind of content this tab is currently showing. The same browse +
    # installed UI is reused for all three by routing its data calls through
    # the _is_mod() branches below - mods go through the per-profile
    # cubeon/mods.py path (version+loader keyed, synced at launch), while
    # resource packs and shaders go through cubeon/content.py, which installs
    # straight into the shared, version-agnostic .minecraft/resourcepacks and
    # shaderpacks folders the game reads directly (no profiles, no toggle, no
    # sync step - see cubeon/content.py for why they genuinely differ).
    active_content = {"type": "mod"}  # "mod" | "resourcepack" | "shader"
    CONTENT_TABS = [("mod", "Mods"), ("resourcepack", "Resource Packs"), ("shader", "Shaders")]

    def _ct() -> str:
        return active_content["type"]

    def _is_mod() -> bool:
        return active_content["type"] == "mod"

    def _type_label() -> str:
        """Singular human label for the active non-mod type, e.g. 'resource pack'."""
        return core.CONTENT_TYPES[_ct()]["label"].lower()

    def build_category_chips():
        """Builds the row of tappable category chips. Selecting one re-runs
        whatever's currently showing (search or recommendations) scoped to
        that category, so narrowing down to the right mod is a single tap
        instead of scrolling through everything.

        Chips are deliberately quiet - bare text until selected, then a faint
        green wash. A strip of bordered buttons above the results was half of
        the 'box inside box' problem."""
        chip_row = ft.Row(spacing=4, wrap=True)

        def make_chip(cat_id, label):
            return quiet_chip(
                label,
                selected=active_category["value"] == cat_id,
                on_click=lambda e, cid=cat_id: (
                    active_category.update({"value": cid}),
                    build_category_chips(),  # rebuild to update selected styling
                    run_mod_search() if mod_search_field.value.strip() else load_recommended_mods(),
                ),
            )

        for cat_id, label in (core.MOD_CATEGORIES if _is_mod() else core.category_choices(_ct())):
            chip_row.controls.append(make_chip(cat_id, label))

        category_chips_container.content = chip_row
        # Green dot-on-button: an applied filter must stay visible even while
        # the chip strip itself is folded away.
        filters_button.icon_color = ACCENT if active_category["value"] else TEXT_DIM
        page.update()

    category_chips_container = ft.Container(content=ft.Row())
    category_chips_container.visible = False  # folded behind the "..." button

    # --- Content-type segmented control (Mods / Resource Packs / Shaders) ---
    # Styled as underline tabs, not buttons: the selected section gets a
    # small accent rule and bright text; the rest are quiet dim labels.
    content_segment_row = ft.Row(spacing=18)

    def build_content_segment():
        content_segment_row.controls.clear()
        for tid, label in CONTENT_TABS:
            content_segment_row.controls.append(
                text_tab(label,
                         selected=_ct() == tid,
                         on_click=lambda e, t=tid: on_content_type_change(t))
            )
        page.update()

    def _apply_type_labels():
        """Refreshes the header/search/notice text to match the active type.
        Kept in one place so every type-dependent label switches together."""
        header_title.value = dict(CONTENT_TABS)[_ct()]
        if _is_mod():
            header_subtitle.value = "Browse and install mods, or manage what's already in your folder."
            mod_search_field.hint_text = "Search mods on Modrinth... e.g. sodium, iris, jei"
        elif _ct() == "resourcepack":
            header_subtitle.value = "Browse and install resource packs. They apply to every version."
            mod_search_field.hint_text = "Search resource packs... e.g. faithful, stay true"
        else:
            header_subtitle.value = "Browse and install shaders. They need Iris or OptiFine to run."
            mod_search_field.hint_text = "Search shaders... e.g. complementary, BSL, sildurs"

    def on_content_type_change(new_type):
        if _ct() == new_type:
            return
        active_content["type"] = new_type
        # Categories differ per type, so a category selected under one type is
        # meaningless under another - reset to All. Same for the "show all"
        # expansion and any in-flight search text.
        active_category["value"] = ""
        installed_show_all["value"] = False
        mod_search_field.value = ""
        build_content_segment()
        build_category_chips()
        _apply_type_labels()
        refresh_mods_list()
        load_recommended_mods()
        page.update()

    def current_mc_version_for_search() -> str | None:
        """
        Extracts the Minecraft version number (e.g., "1.20.4") from the selected version ID.
        This is used to find mods compatible with the current game version.
        """
        v = version_dropdown.value
        if not v:
            return None
        return core.extract_mc_version(v)

    def browse_loader() -> str:
        """The loader to filter Modrinth results by. Vanilla can't load mods
        at all, so default that case to Fabric (the most commonly supported
        loader) rather than sending an invalid facet."""
        return state["mod_loader"] if state["mod_loader"] != "vanilla" else "fabric"

    def load_recommended_mods():
        """
        Fetches items for the current version+category and displays them in the
        browse section. For mods this is the curated all-rounder picks (or the
        top mods in a category); for resource packs / shaders it's the most
        popular of that type, so switching categories changes what's shown.
        """
        cat = active_category["value"]
        if _is_mod():
            cat_label = dict(core.MOD_CATEGORIES).get(cat, "")
            default_title = "RECOMMENDED"
        else:
            cat_label = dict(core.category_choices(_ct())).get(cat, "")
            default_title = "POPULAR"
        browse_title_text.value = f"TOP {cat_label.upper()}" if cat else default_title
        browse_status_text.value = "Loading..."
        browse_results_view.controls.clear()
        page.update()

        # Run the network request in a background thread
        def worker():
            try:
                mc_version = current_mc_version_for_search()
                if _is_mod():
                    results = core.get_recommended_mods(mc_version=mc_version, loader=browse_loader(), category=cat)
                else:
                    results = core.get_recommended_content(_ct(), mc_version=mc_version, category=cat or None)
            except Exception as ex:
                browse_status_text.value = f"Couldn't load recommendations: {ex}"
                page.update()
                return
            render_browse_results(results, empty_msg="Nothing found for this version/category.")

        threading.Thread(target=worker, daemon=True).start()

    def run_mod_search():
        """
        Initiates a search on Modrinth based on the query entered in mod_search_field,
        scoped to the current version, active content type, and selected category.
        If the query is empty, it loads recommendations instead.
        """
        query = mod_search_field.value.strip()
        if not query:
            load_recommended_mods()
            return
        browse_title_text.value = f'RESULTS FOR "{query.upper()}"'
        browse_status_text.value = "Searching..."
        browse_results_view.controls.clear()
        page.update()

        def worker():
            try:
                mc_version = current_mc_version_for_search()
                cat = active_category["value"]
                if _is_mod():
                    results = core.search_mods(
                        query, mc_version=mc_version, loader=browse_loader(),
                        categories=[cat] if cat else None,
                    )
                else:
                    results = core.search_content(
                        _ct(), query, mc_version=mc_version,
                        categories=[cat] if cat else None,
                    )
            except Exception as ex:
                browse_status_text.value = f"Search failed: {ex}"
                page.update()
                return
            render_browse_results(results, empty_msg="Nothing found for that search.")

        threading.Thread(target=worker, daemon=True).start()

    def render_browse_results(results, empty_msg):
        """
        Stores the full result list and renders page 1. Pagination itself is
        done in _render_browse_page() - this just resets to the first page
        whenever a new search/recommendation set comes in.
        """
        browse_state["results"] = results or []
        browse_state["empty_msg"] = empty_msg
        browse_state["page"] = 0
        _render_browse_page()

    BROWSE_PAGE_SIZE = 5

    def _render_browse_page():
        """Renders one page (BROWSE_PAGE_SIZE items) of the stored results and
        updates the pager controls to match. However many results came back,
        this pages through all of them - not just the first handful."""
        results = browse_state["results"]
        page_num = browse_state["page"]
        total_pages = max(1, -(-len(results) // BROWSE_PAGE_SIZE))  # ceil div
        page_num = max(0, min(page_num, total_pages - 1))
        browse_state["page"] = page_num

        browse_results_view.controls.clear()
        if not results:
            browse_results_view.controls.append(
                ft.Text(browse_state.get("empty_msg", ""), size=13, color=TEXT_DIM))
        else:
            # Snapshot the mode once: a background recommend/search worker can
            # finish and call this right after the user flipped the content-type
            # segment, so re-checking _is_mod() per row could read one mode in
            # setup and the other in the loop (crashing on the unset variable).
            is_mod_now = _is_mod()
            already = installed_slugs() if is_mod_now else set()
            tokens = set() if is_mod_now else content_installed_tokens()
            start = page_num * BROWSE_PAGE_SIZE
            for mod in results[start:start + BROWSE_PAGE_SIZE]:
                if is_mod_now:
                    slug = (mod.get("slug") or "").lower()
                    compact = re.sub(r"[^a-z0-9]+", "", slug)
                    # Modrinth's opaque project id: a modpack install leaves
                    # exactly this and no slug, so it's often the only match
                    # for a pack-installed mod.
                    pid = (mod.get("project_id") or "").strip().lower()
                    is_installed = slug in already or (bool(compact) and compact in already) \
                        or (bool(pid) and pid in already)
                else:
                    # Resource packs / shaders store no Modrinth slug (they're
                    # just .zips in a shared folder), so match the project's
                    # slug OR title as a compacted token against installed
                    # filenames. Best-effort; a miss only shows "Download".
                    slug = re.sub(r"[^a-z0-9]+", "", (mod.get("slug") or "").lower())
                    title = re.sub(r"[^a-z0-9]+", "", (mod.get("title") or "").lower())
                    is_installed = (bool(slug) and any(slug in t for t in tokens)) or \
                        (bool(title) and any(title in t for t in tokens))
                browse_results_view.controls.append(build_browse_row(mod, is_installed))

        browse_status_text.value = f"{len(results)} mod(s)" if results else ""
        browse_pager_label.value = f"Page {page_num + 1} of {total_pages}"
        browse_pager_row.visible = len(results) > BROWSE_PAGE_SIZE
        browse_pager_prev.disabled = page_num <= 0
        browse_pager_next.disabled = page_num >= total_pages - 1
        page.update()

    def _browse_page_prev(e=None):
        if browse_state["page"] > 0:
            browse_state["page"] -= 1
            _render_browse_page()

    def _browse_page_next(e=None):
        total_pages = max(1, -(-len(browse_state["results"]) // BROWSE_PAGE_SIZE))
        if browse_state["page"] < total_pages - 1:
            browse_state["page"] += 1
            _render_browse_page()

    browse_pager_prev.on_click = _browse_page_prev
    browse_pager_next.on_click = _browse_page_next

    def build_browse_row(mod, is_installed=False):
        """
        Creates a row for a mod in the browse results.

        Reads like a store listing, not a database record: the mod's NAME is
        the dominant element (15px, bold), its description sits underneath at
        readable size, and download count is tiny metadata. The whole row is
        transparent until hovered - no enclosing slab - and the download
        action is a restrained green wash instead of a solid block, so five
        rows don't stack five loud buttons.
        """
        # The download button's text and icon change based on installed status
        download_btn_text = ft.Text(
            "Installed" if is_installed else "Download",
            size=12.5, weight=ft.FontWeight.W_700,
            color=TEXT_FAINT if is_installed else ACCENT,
        )
        download_btn = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECK_ROUNDED if is_installed else ft.Icons.DOWNLOAD_ROUNDED,
                            color=TEXT_FAINT if is_installed else ACCENT, size=15),
                    download_btn_text,
                ],
                spacing=6, tight=True,
            ),
            bgcolor=None if is_installed else ACCENT_TINT,
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=7),
            ink=not is_installed,
            disabled=is_installed,
        )

        def on_download(e):
            """
            Handles the download of a mod. It finds the appropriate file (compatible with
            current Minecraft version and loader), then downloads it and refreshes the installed list.
            """
            download_btn.disabled = True
            download_btn_text.value = "Finding file..."
            download_btn_text.color = TEXT_DIM
            download_btn.bgcolor = ROW_HOVER
            page.update()

            def worker():
                try:
                    # Search against the numeric MC version (Modrinth wants
                    # "1.20.4", not a loader-qualified id). For mods, STORE the
                    # download under state["selected_mc_version"] + loader - the
                    # exact keys list_mods()/sync_mods_to_game() use - so the
                    # mod ends up in the profile the game reads. Resource packs
                    # and shaders have no profile: they go straight into their
                    # shared game folder.
                    search_mc_version = current_mc_version_for_search()
                    if _is_mod():
                        file_info = core.get_mod_download(mod["project_id"], mc_version=search_mc_version, loader=browse_loader())
                    else:
                        file_info = core.get_content_download(_ct(), mod["project_id"], mc_version=search_mc_version)
                    if not file_info:
                        download_btn_text.value = "No matching file"
                        page.update()
                        return

                    download_btn_text.value = "Downloading..."
                    page.update()
                    if _is_mod():
                        # mc_version/loader must be passed explicitly - without
                        # them this silently lands in the wrong profile folder
                        # (get_profile_dir(None, None) => "unknown-vanilla") and
                        # the game never finds it at launch. See cubeon/mods.py.
                        core.download_mod(
                            file_info["url"], file_info["filename"],
                            mc_version=state["selected_mc_version"], loader=browse_loader(),
                            slug=mod.get("slug"), hashes=file_info.get("hashes"),
                        )
                    else:
                        core.download_content(_ct(), file_info["url"], file_info["filename"])

                    download_btn_text.value = "Installed"
                    download_btn_text.color = TEXT_FAINT
                    download_btn.bgcolor = None
                    download_btn.content.controls[0].name = ft.Icons.CHECK_ROUNDED
                    download_btn.content.controls[0].color = TEXT_FAINT
                    page.update()
                    refresh_mods_list()  # Update the installed list
                except Exception as ex:
                    download_btn_text.value = "Failed"
                    download_btn_text.color = DANGER
                    download_btn.disabled = False
                    download_btn.bgcolor = ACCENT_TINT
                    page.update()

            threading.Thread(target=worker, daemon=True).start()

        if not is_installed:
            download_btn.on_click = on_download

        description = (mod.get("description") or "").strip()

        # Cache this row's art for the next render (no-op if already cached).
        _icons.prefetch(mod.get("icon_url"))

        # Hover lift: transparent at rest, faint surface under the cursor -
        # affordance without another permanent rectangle.
        return attach_hover(
            ft.Container(
                content=ft.Row(
                    [
                        # Mod icon (or placeholder if none) - disk-cached art
                        (ft.Image(src=_icons.src(mod.get("icon_url")),
                                  width=48, height=48,
                                  border_radius=RADIUS, fit=ft.BoxFit.COVER)
                         if mod.get("icon_url") else
                         ft.Container(width=48, height=48, bgcolor=CARD_FILL, border_radius=RADIUS,
                                      content=ft.Icon(ft.Icons.EXTENSION_OUTLINED, color=TEXT_FAINT, size=22),
                                      alignment=ft.Alignment.CENTER)),
                        # Title leads; description and metadata support it.
                        ft.Column(
                            [
                                ft.Text(mod["title"], size=15, color=TEXT,
                                        weight=ft.FontWeight.W_700, max_lines=1),
                                ft.Text(description or " ", size=12, color=TEXT_DIM,
                                        max_lines=1),
                                ft.Row(
                                    [
                                        ft.Text(f"{mod.get('downloads', 0):,} downloads",
                                                size=11, color=TEXT_FAINT, font_family=FONT_MONO),
                                    ],
                                    spacing=8,
                                ),
                            ],
                            spacing=3, expand=True,
                        ),
                        download_btn,
                    ],
                    spacing=14, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=10, vertical=10),
            ),
            "transparent", ROW_HOVER,
        )

    # Warning shown when Vanilla is selected - mods never load without a mod
    # loader, so it's better to say that plainly than let the tab look
    # "installed" for nothing.
    vanilla_mods_notice = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, color=TEXT_DIM, size=14),
                ft.Text(
                    "Vanilla is selected. Mods here won't load until you switch to "
                    "Fabric, Quilt, Forge, or NeoForge on the Play tab.",
                    size=12, color=TEXT_DIM,
                ),
            ],
            spacing=8,
        ),
        visible=(state["mod_loader"] == "vanilla"),
        padding=ft.padding.Padding.symmetric(vertical=6),
    )

    # Shown on the Shaders segment: a shader .zip only does anything if Iris
    # (Fabric) or OptiFine is installed to read it, so say so plainly rather
    # than let a downloaded shader look like it should "just work".
    shader_notice = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, color=TEXT_DIM, size=14),
                ft.Text(
                    "Shaders need Iris (with Sodium) or OptiFine installed to run. "
                    "Grab Iris from the Mods tab, then pick a shader in-game under "
                    "Options > Video Settings > Shaders.",
                    size=12, color=TEXT_DIM,
                ),
            ],
            spacing=8,
        ),
        visible=False,
        padding=ft.padding.Padding.symmetric(vertical=6),
    )

    # Tracks the (version, loader) profile the browse section currently
    # reflects, so we only re-fetch recommendations/search when it's
    # actually stale, not on every unrelated refresh_mods_list() call.
    browse_profile = {"key": None}

    def refresh_browse_for_new_profile():
        """
        Called whenever the selected version or loader changes elsewhere in
        the app (Play tab dropdown, loader switcher). The Installed list is
        already kept in sync via refresh_mods_list(), but the Browse section
        was only ever loaded once on first tab open - meaning if you changed
        version/loader afterward, it kept showing mods for the OLD profile,
        which could be the wrong version or not even support the new loader.
        This re-fetches so Browse always matches what's actually selected.
        """
        key = (state.get("selected_mc_version"), state.get("mod_loader"))
        if key == browse_profile["key"]:
            return  # nothing actually changed for browse purposes
        browse_profile["key"] = key
        # Only bother re-fetching if the tab has been opened at least once -
        # otherwise this fires on startup before the user ever sees Mods.
        if state.get("mods_recommendations_loaded"):
            query = mod_search_field.value.strip()
            if query:
                run_mod_search()
            else:
                load_recommended_mods()

    build_category_chips()
    build_content_segment()

    # Header title/subtitle are refs so _apply_type_labels() can retarget them
    # when the content-type segment switches (Mods -> Resource Packs -> Shaders).
    header_title = ft.Text("Mods", size=28, weight=ft.FontWeight.W_800, color=TEXT,
                            font_family=FONT_DISPLAY)
    header_subtitle = ft.Text("Browse and install mods, or manage what's already in your folder.",
                              size=13, color=TEXT_DIM)
    _apply_type_labels()  # sync the refs now that they exist

    # Now assemble the Mods tab.
    #
    # Layout rhythm: section -> comfortable gap -> section. The old build
    # wrapped the results AND the installed list in bordered filled panels -
    # boxes around rows that were themselves boxes. Both wrappers are gone:
    # lists float directly on the surface, sections are separated by a single
    # hairline divider, and spacing snaps to one consistent scale instead of
    # alternating huge gaps with dense slabs.
    mods_tab = ft.Column(
        [
            # Header with title, description, and two quiet ghost actions.
            ft.Row(
                [
                    ft.Column(
                        [header_title, header_subtitle],
                        spacing=2,
                    ),
                    ft.Container(expand=True),
                    attach_hover(ft.Container(
                        content=ft.Row(
                            [ft.Icon(ft.Icons.UPLOAD_FILE_ROUNDED, color=TEXT_DIM, size=16),
                             ft.Text("Install from file", color=TEXT_DIM, size=13,
                                     weight=ft.FontWeight.W_600)],
                            spacing=6,
                        ),
                        border_radius=RADIUS,
                        padding=ft.padding.Padding.symmetric(horizontal=12, vertical=9),
                        ink=True, on_click=open_local_mod_picker,
                    ), "transparent", ROW_HOVER),
                    ft.Container(width=6),
                    attach_hover(ft.Container(
                        content=ft.Row(
                            [ft.Icon(ft.Icons.FOLDER_OPEN_ROUNDED, color=ACCENT, size=16),
                             ft.Text("Open folder", color=ACCENT, size=13, weight=ft.FontWeight.W_600)],
                            spacing=6,
                        ),
                        border_radius=RADIUS,
                        padding=ft.padding.Padding.symmetric(horizontal=12, vertical=9),
                        ink=True, on_click=open_folder_click,
                    ), "transparent", ACCENT_TINT),
                ],
            ),
            ft.Container(height=14),
            # Segment tabs and their contextual notices share ONE block: an
            # empty status line / hidden notice used to sit as separate
            # children here, each still collecting column spacing around a
            # zero-height slot - which is what opened a dead band between
            # the tabs and the search field.
            ft.Column(
                [
                    content_segment_row,
                    local_install_status,
                    vanilla_mods_notice,
                    shader_notice,
                ],
                spacing=6,
            ),
            ft.Container(height=14),
            # Search + the "..." that unfolds category filters. Live search
            # made a Search button redundant; the filters collapsed up here
            # stop a dozen chips from eating vertical space before content.
            ft.Row([mod_search_field, filters_button], spacing=6),
            category_chips_container,
            ft.Container(height=22),
            # Browse results header (title and status)
            ft.Row([browse_title_text, ft.Container(expand=True), browse_status_text],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(height=8),
            browse_results_view,
            browse_pager_row,
            ft.Container(height=26),
            pixel_divider(CARD_BORDER),
            ft.Container(height=20),
            # Installed section
            ft.Row([section_label("Installed"), ft.Container(expand=True), installed_count_text],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(height=10),
            installed_filter_field,
            ft.Container(height=10),
            mods_list_view,
        ],
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
    )

    return mods_tab, refresh_mods_list, load_recommended_mods, refresh_browse_for_new_profile
