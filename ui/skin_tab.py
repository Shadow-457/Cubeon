"""Wardrobe: shared native 3D preview and local Skin / Cape / Shoulder / Back
libraries.

Uploads are stored locally and applied in-game when the corresponding
skin/cape mod is installed for the current profile. Shoulder and back items
are original Cubeon art drawn by the Cubeon Client itself (see
cubeon/cosmetics.py). Screenshots live in Settings.
"""

# Standard library imports
import base64
import math
import os
import threading
from io import BytesIO

# Flet imports - Flet is a UI framework for Python (like Flutter)
import flet as ft
from cubeon import i18n

from cubeon.theme import (
    RADIUS, RADIUS_LG,
    attach_hover,  # hover-state helper for hand-built Container "buttons"
    ACCENT_TINT, ACCENT_TINT_HI,  # selected/hover washes for tiles/cards
    text_tab,      # underline-style segment tab (same chrome as Mods' content types)
    keyboard_target,
    CARD_FILL, CARD_BORDER,  # translucent panel fills/outlines (Mods-tab language)
    ROW_HOVER,     # quiet hover lift for borderless rows/cards
)
from cubeon import thread_safe_ui  # control-level refresh() (thread-safe)
from cubeon import cosmetics, cosmetics_store
from ui.appearance_preview import AppearancePreview
from ui.image_memory import preview_image
from ui.content_states import skeleton_block
from ui.chrome import TabEntryQueue, TabPane

# Our own launcher core module - contains logic for skin storage/rendering
import launcher_core as core

# The bundled preview of the shared Cubeon cape (the one the Worker serves to
# every player - see worker/cubeon-skins.js). This is a relative asset path,
# which ft.Image.src resolves against the app's assets_dir, so it shows up
# whenever no custom cape is selected instead of leaving the box blank.
DEFAULT_CAPE_PREVIEW_SRC = "capes/cubeon_cape_preview.png"
DEFAULT_SKIN_PREVIEW_SRC = "skins/steve-preview.png"
COSMETIC_THUMB_SIZE = (64, 64)


# Preview bytes are immutable once written, so base64-encoding them once and
# keeping the string in memory spares every grid rebuild a disk read + encode.
def build_skin_section(page: ft.Page, cfg: dict, *, section_label, pixel_divider,
                        BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                        TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO=None,
                        mc_version=None, mc_loader=None, file_picker=None,
                        cape_file_picker=None, assets_dir=None):
    """
    Build the retained Wardrobe with one category at a time, a shared preview
    and independently scrolling local/browse libraries.

    Args:
        page: The Flet page instance for pickers, preview sizing and scoped updates.
        cfg: The launcher configuration dictionary (we read/write cfg["active_skin"]).
        section_label, pixel_divider: Shared helper functions from main.py.
        BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM, TEXT, TEXT_DIM,
        DANGER, FONT_DISPLAY, FONT_MONO: Shared design tokens, defined in
            cubeon/theme.py and passed in as **THEME. DANGER used to default to
            "#e05555" here while main.py passed "#C25B4A" - two different reds
            for the same button depending on the call site. It's required now,
            so the tokens can't drift apart again. FONT_MONO is accepted (and
            unused) purely so this builder takes the same **THEME as the others.
        file_picker: A single ft.FilePicker created and registered ONCE by
            main.py and passed in here. When the selected version/loader
            changes, the section rebuilds using that same picker; it must
            NOT construct+register its own FilePicker each call -
            each registration adds another overlay entry the client never
            mounts, and only the very first one actually receives results,
            which is what made the Upload button appear dead after the tab
            had refreshed once. Reusing one shared, already-registered
            picker keeps the button working across every rebuild.

    Returns:
        ft.Column: The skin section's content, ready to drop into the
        Profile tab's layout.
    """

    # =====================================================================
    # CUSTOM SKIN UPLOAD - lets the user pick a local 64x64 (or legacy
    # 64x32) skin PNG, stores it via launcher_core, renders a real preview
    # from the actual uploaded pixels, and (if CustomSkinLoader is
    # installed) copies it into that mod's folder so it shows up in-game
    # for THIS player. Honest status text below explains what will and
    # won't be visible, instead of pretending it's a full skin-server swap.
    # =====================================================================

    appearance = AppearancePreview(cfg, assets_dir, page=page)
    active_pane = {"id": "skin"}
    thumb_grids = []
    skin_preview_name = ft.Text("Steve · Default skin", size=13, color=TEXT)

    def _refresh_status(control):
        with thread_safe_ui.TREE_LOCK:
            control.visible = bool(control.value)
        thread_safe_ui.refresh(control)

    def _update_thumb_window(grid):
        """Render the visible rows and one nearby row, not the whole library."""
        stride = grid.card_height + grid.spacing
        first = max(0, int(grid.scroll_pixels // stride) - 1) * grid.runs_count
        end = math.ceil((grid.scroll_pixels + grid.viewport_height) / stride) + 1
        cards = [card for card in grid.controls if card.visible]
        grid.attached_cards = {id(card) for card in grid.controls}
        window = {id(card) for card in cards[first:end * grid.runs_count]}
        changed = window != grid.thumb_window
        grid.thumb_window = window
        return changed

    def _fit_grid(grid, width=None):
        """Let the lazy native grid size cells without resizing every card."""
        width = width if width is not None else getattr(grid, "available_width", None)
        if not width or not math.isfinite(width) or width <= 0:
            return False
        grid.available_width = width
        columns = max(1, min(4, int((width + 12) / (148 + 12))))
        card_width = (width - 12 * (columns - 1)) / columns
        ratio = card_width / grid.card_height
        changed = grid.runs_count != columns or grid.child_aspect_ratio != ratio
        grid.runs_count = columns
        grid.child_aspect_ratio = ratio
        _update_thumb_window(grid)
        return changed

    def _grid_resized(event):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            height = getattr(event, "height", None)
            if height and math.isfinite(height) and height > 0:
                event.control.viewport_height = height
            changed = _fit_grid(event.control, event.width)
        if changed:
            thread_safe_ui.refresh(event.control)
        _flush_pending_thumbs()

    def _grid_scrolled(event):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            grid = event.control
            grid.scroll_pixels = max(0, event.pixels)
            changed = _update_thumb_window(grid)
        if changed:
            _flush_pending_thumbs()

    def _card_grid(card_height=190):
        # Same native lazy-grid approach as content_tiles; Wardrobe keeps its
        # existing artwork/actions and shorter, fixed-height item cards.
        grid = ft.GridView(spacing=12, run_spacing=12, expand=True, padding=0,
                          scroll=ft.ScrollMode.ALWAYS, cache_extent=card_height + 12,
                          build_controls_on_demand=True, scroll_interval=80,
                          on_scroll=_grid_scrolled, on_size_change=_grid_resized,
                          size_change_interval=100, data="cosmetics-picker-scroll")
        grid.card_height = card_height
        grid.viewport_height = 320
        grid.scroll_pixels = 0
        grid.thumb_window = set()
        _fit_grid(grid, 480)
        thumb_grids.append(grid)
        return grid

    def _scroll_cards(grid):
        return grid

    upload_status = ft.Text("", size=12, color=TEXT_DIM, visible=False)
    # Honest, specific status about what will actually be visible in-game, so
    # the user isn't left guessing whether an upload "worked". Three genuinely
    # different situations, and conflating them is what makes a launcher feel
    # broken:
    #   - no mod loader   -> nothing can load a custom skin at all
    #   - loader, no CSL  -> it'll be installed on the next launch
    #   - CSL present     -> working, but local-only for skins (the cape is
    #                        the part other players can see)
    def skin_visibility_note() -> str:
        if mc_loader not in core.MOD_CAPABLE_LOADERS or not mc_version:
            return ("Pick a mod loader (Fabric) on the Play tab. Offline "
                    "Minecraft can't show a custom skin without one.")
        if core.skin_mod_installed(mc_version, mc_loader):
            return ("Working. Only you see your own skin for now. Your Cubeon "
                    "cape is what other Cubeon players see.")
        return ("Skin support installs automatically the next time you press "
                "Play, then your skin shows up in-game.")

    # Grids wrap and resize inside the picker without remounting cards.
    skins_list_col = _card_grid()
    skin_cards = {}

    def render_preview_for(filename):
        appearance.refresh(invalidate=True)

    def set_active(filename: str | None):
        if cfg.get("active_skin") == filename:
            return
        try:
            core.set_active_skin(cfg, filename)
        except Exception as ex:
            upload_status.value = f"Couldn't switch skin: {ex}"
            _refresh_status(upload_status)
            return
        render_preview_for(filename)
        if filename is None:
            # Clearing the custom skin selects the bundled classic Steve sheet.
            skin_preview_name.value = "Steve · Default skin"
            upload_status.value = ""
        else:
            entry = next((s for s in core.list_custom_skins()
                          if s.get("filename") == filename), None)
            skin_preview_name.value = (entry or {}).get("name") or "Custom skin"
            upload_status.value = ""
        thread_safe_ui.refresh(skin_preview_name)
        sync_skin_selection()
        thread_safe_ui.refresh(skins_list_col)
        _refresh_status(upload_status)

    def delete_skin(filename: str):
        ft.context.disable_auto_update()
        # Unguarded, a missing file or corrupt skins.json escaped the click
        # handler - Flet swallows handler exceptions, so the card just sat
        # there "undeletable" with no feedback. Surface it instead.
        try:
            if cfg.get("active_skin") == filename:
                core.set_active_skin(cfg, None)
                render_preview_for(None)
                skin_preview_name.value = "Steve · Default skin"
            core.delete_custom_skin(filename)
            core.forget_file("skin", filename)
        except Exception as ex:
            upload_status.value = f"Couldn't delete: {ex}"
            _refresh_status(upload_status)
            return
        _THUMB_MEMO.pop(("skin", filename), None)
        refresh_skins_list()
        thread_safe_ui.refresh(skins_list_col)
        thread_safe_ui.refresh(skin_preview_name)

    # --- Installed cards -------------------------------------------------
    # Clicking the artwork applies an item; the check and rim show selection.
    def _owned_card(*, label, sublabel, active, on_use, on_delete,
                    src=None, lazy_thumb=None, preview_w=76, preview_h=112,
                    icon=None, model_label=None, on_model=None, action_label="Apply",
                    thumb_grid=None, thumb_pane=None):
        """Click the artwork/name to apply. Keep management actions separate;
        selection updates retain the image and its keyboard target.

        src: ready preview bytes/asset path (default cape, already-cached b64).
        lazy_thumb: ("skin"|"cape", filename) - build the card immediately with
        a placeholder and let the thumb worker fill the image in; the grid
        never waits on PIL. Pass neither for a permanent "not an image" icon.
        """
        if src:
            preview_img = preview_image(src=src, width=preview_w, height=preview_h,
                                   fit=ft.BoxFit.CONTAIN, cache_width=preview_w,
                                   filter_quality=ft.FilterQuality.LOW)
            placeholder = None
        elif lazy_thumb:
            # Visible only once the worker thread lands real bytes. The
            # placeholder keeps the card's height stable meanwhile, so the
            # grid doesn't reflow as thumbs pop in.
            preview_img = preview_image(src="icon.svg", width=preview_w,
                                   height=preview_h, fit=ft.BoxFit.CONTAIN,
                                   cache_width=preview_w, filter_quality=ft.FilterQuality.LOW,
                                   visible=False)
            placeholder = skeleton_block(preview_w, preview_h, fill=BORDER)
        else:
            preview_img, placeholder = None, ft.Icon(
                icon or ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED, color=TEXT_DIM,
                size=22)
        preview_stack = [c for c in (preview_img, placeholder) if c is not None]
        selected = {"value": None}
        name = ft.Text(label, size=12, color=TEXT, weight=ft.FontWeight.W_600,
                       max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                       text_align=ft.TextAlign.CENTER)
        subtitle = ft.Text(sublabel, size=10, color=TEXT_DIM,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                           text_align=ft.TextAlign.CENTER, visible=bool(sublabel))
        check = ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=ACCENT, size=16,
                        left=2, top=2, visible=active)
        artwork = ft.Stack([
            ft.Container(content=ft.Row(preview_stack, spacing=0,
                         alignment=ft.MainAxisAlignment.CENTER),
                         height=preview_h + 12, alignment=ft.Alignment.CENTER),
            check,
        ])
        def apply_item(e):
            ft.context.disable_auto_update()
            with thread_safe_ui.TREE_LOCK:
                selected_now = selected["value"]
            if not selected_now:
                on_use(e)

        primary = ft.Container(
            content=ft.Column([artwork, name,
                subtitle],
                spacing=5, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=8, border_radius=RADIUS, ink=False,
            tooltip=f"{action_label} {label}" + (f" ({sublabel})" if sublabel else ""),
            on_click=apply_item,
            on_hover=lambda e: card.on_hover(e),
        )
        actions = []
        if model_label:
            actions.append(ft.PopupMenuItem(
                content=ft.Text(f"Arms: {model_label}", size=12, color=TEXT),
                icon=ft.Icons.ACCESSIBILITY_NEW_ROUNDED, on_click=on_model,
                tooltip="Change arms: Auto → Alex (3 px) → Steve (4 px)"))
        if on_delete is not None:
            actions.append(ft.PopupMenuItem(
                content=ft.Text(i18n.t("Delete"), size=12, color=DANGER),
                icon=ft.Icons.DELETE_OUTLINE_ROUNDED, on_click=on_delete,
                tooltip=i18n.t("Delete")))
        contents = [keyboard_target(primary, primary.tooltip)]
        if actions:
            contents.append(ft.PopupMenuButton(
                items=actions, icon=ft.Icons.MORE_HORIZ_ROUNDED,
                icon_size=18, icon_color=TEXT_DIM, bgcolor=SURFACE_HI,
                width=30, height=30, padding=4, right=4, top=4,
                tooltip=f"Manage {label}"))
        card = ft.Container(
            content=ft.Stack(contents),
            width=148,
            bgcolor=ACCENT_TINT if active else CARD_FILL,
            border=ft.border.Border.all(1, ACCENT if active else CARD_BORDER),
            border_radius=RADIUS,
            padding=4,
        )

        def set_selected(value):
            value = bool(value)
            if selected["value"] is value:
                return
            selected["value"] = value
            check.visible = bool(value)
            name.color = ACCENT if value else TEXT
            card.bgcolor = ACCENT_TINT if value else CARD_FILL
            card.border = ft.border.Border.all(1, ACCENT if value else CARD_BORDER)
            attach_hover(card, card.bgcolor, ACCENT_TINT_HI if value else ROW_HOVER)
            return True

        card.set_selected = set_selected
        def set_sublabel(value):
            subtitle.value = value
            subtitle.visible = bool(value)
        card.set_sublabel = set_sublabel
        set_selected(active)
        if lazy_thumb and not src:
            card._cubeon_thumb_job = (thumb_grid, card, thumb_pane or lazy_thumb[0],
                                     preview_img, placeholder, *lazy_thumb)
        return card

    # Preview bytes are immutable once written, so base64-encoding them once
    # and keeping the string in memory spares every list rebuild a disk read
    # + encode.
    _IMG_MEMO = {}

    def _img_b64(path):
        hit = _IMG_MEMO.get(path)
        if hit is not None:
            return hit
        try:
            with open(path, "rb") as f:
                b64 = base64.b64encode(f.read()).decode("ascii")
        except Exception:
            return None
        _IMG_MEMO[path] = b64
        return b64

    # --- card thumbnails: cached, lazily rendered --------------------------
    # Every card needs a PIL composite (decode + body assemble + upscale +
    # PNG encode). Doing that inside refresh_* blocked the UI thread once per
    # card on every list rebuild - open the Cosmetics tab with ten skins and
    # the tab froze for the sum of ten composites. Now refresh_* builds every
    # card INSTANTLY (cached b64 if we have one, quiet placeholder if not)
    # and the composites happen on a worker thread that patches the image
    # control per-card via thread_safe_ui.
    _THUMB_MEMO = {}   # (kind, filename) -> b64 (bytes are immutable once written)
    _PENDING_THUMBS = []  # (grid, card, pane, image, placeholder, kind, filename)
    _THUMB_RUNNING = False

    def _render_thumb(kind, filename):
        """PIL-heavy thumbnail render -> b64, or None. Worker-thread only."""
        if kind == "cosmetic":
            return _cosmetic_thumb(cosmetics.get(filename, appearance.cosmetics_dir))
        folder = core.SKINS_DIR if kind == "skin" else core.CAPES_DIR
        variant = ""
        if kind == "skin":
            entry = next((s for s in core.list_custom_skins()
                          if s.get("filename") == filename), {})
            variant = "alex_" if entry.get("slim") else "steve_"
        suffix = "png"
        if kind == "cape":
            entry = next((c for c in core.list_capes() if c.get("filename") == filename), {})
            suffix = "gif" if entry.get("animated") else "png"
        out = os.path.join(folder, f"_thumb_{variant}{filename}.{suffix}")
        src = core.get_cape_path(filename) if kind == "cape" else os.path.join(folder, filename)
        try:
            # The preview depends on the sheet and arm model, so an up-to-date
            # thumb file on disk IS the render - skip the composite entirely.
            # Without this, every rebuild re-encoded every thumb (the UI jank
            # half), and with the async path it would also mean N threads
            # redoing finished work each time the tab is opened.
            if not (os.path.exists(out)
                    and os.path.getmtime(out) >= os.path.getmtime(src)):
                if kind == "skin":
                    core.render_local_skin_preview(filename, out, scale=3)
                else:
                    core.render_cape_preview(filename, out, scale=3)
            b64 = _img_b64(out)
            if b64:
                _THUMB_MEMO[(kind, filename)] = b64
            return b64
        except Exception:
            return None  # worker replaces loading with an unavailable-art icon

    def _flush_pending_thumbs():
        """One draining worker prioritizes the open pane; hidden cards wait."""
        nonlocal _THUMB_RUNNING

        def attached(job):
            grid, card = job[:2]
            return grid is not None and id(card) in grid.attached_cards

        def visible(job):
            return (job[2] == active_pane["id"] and job[1].visible
                    and id(job[1]) in job[0].thumb_window)

        with thread_safe_ui.TREE_LOCK:
            # Collect only attached cards. An existing worker can otherwise
            # discard a new card between construction and its grid insertion.
            for grid in thumb_grids:
                grid.attached_cards = {id(card) for card in grid.controls}
                for card in grid.controls:
                    job = getattr(card, "_cubeon_thumb_job", None)
                    if job is not None:
                        _PENDING_THUMBS.append(job)
                        card._cubeon_thumb_job = None
            _PENDING_THUMBS[:] = [job for job in _PENDING_THUMBS if attached(job)]
            if _THUMB_RUNNING or not any(visible(job) for job in _PENDING_THUMBS):
                return
            _THUMB_RUNNING = True

        def _worker():
            nonlocal _THUMB_RUNNING
            while True:
                with thread_safe_ui.TREE_LOCK:
                    for grid in thumb_grids:
                        grid.attached_cards = {id(card) for card in grid.controls}
                    _PENDING_THUMBS[:] = [job for job in _PENDING_THUMBS if attached(job)]
                    index = next((i for i, job in enumerate(_PENDING_THUMBS) if visible(job)), None)
                    if index is None:
                        _THUMB_RUNNING = False
                        return
                    job = _PENDING_THUMBS.pop(index)
                    _, _, _, img, ph, kind, fn = job
                b64 = _render_thumb(kind, fn)
                with thread_safe_ui.TREE_LOCK:
                    if b64:
                        img.src = b64
                        img.visible = True
                        ph.visible = False
                    else:
                        # A missing sheet is an error state, never endless loading.
                        ph.bgcolor = None
                        ph.data = "content-artwork-unavailable"
                        ph.content = ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED,
                                             color=TEXT_DIM, size=22)
                        ph.alignment = ft.Alignment.CENTER
                    repaint = attached(job) and visible(job)
                if repaint:
                    thread_safe_ui.refresh(img)
                    thread_safe_ui.refresh(ph)

        threading.Thread(target=_worker, daemon=True,
                         name="ux-thumb-render").start()

    def _skin_card_b64(filename):
        # Synchronous path kept for callers that truly need the bytes now;
        # the grid itself uses lazy_thumb instead so it never waits on PIL.
        return _render_thumb("skin", filename)

    def _cape_card_b64(filename):
        return _render_thumb("cape", filename)


    def change_skin_arms(filename):
        ft.context.disable_auto_update()
        entry = next((s for s in core.list_custom_skins()
                      if s.get("filename") == filename), None)
        if entry is None:
            return
        current = entry.get("model", "auto")
        choices = ("auto", "slim", "classic")
        wanted = choices[(choices.index(current) + 1) % 3] if current in choices else "auto"
        try:
            if not core.set_skin_model(cfg, filename, wanted):
                raise ValueError("Skin no longer exists")
            with thread_safe_ui.TREE_LOCK:
                _THUMB_MEMO.pop(("skin", filename), None)
                if cfg.get("active_skin") == filename:
                    appearance.refresh(invalidate=True)
                upload_status.value = "Arm model updated. Restart Minecraft to apply it in-game."
            refresh_skins_list()
        except Exception as ex:
            with thread_safe_ui.TREE_LOCK:
                upload_status.value = f"Couldn't change arms: {ex}"
        _refresh_status(upload_status)
        thread_safe_ui.refresh(skins_list_col)

    def sync_skin_selection():
        with thread_safe_ui.TREE_LOCK:
            for filename, card in skin_cards.items():
                card.set_selected(cfg.get("active_skin") == filename)

    def refresh_skins_list():
        skins = core.list_custom_skins()
        with thread_safe_ui.TREE_LOCK:
            for filename in list(skin_cards):
                if filename is not None and not any(entry["filename"] == filename for entry in skins):
                    del skin_cards[filename]
            if None not in skin_cards:
                skin_cards[None] = _owned_card(
                    src=DEFAULT_SKIN_PREVIEW_SRC, label="Steve",
                    sublabel="Default Minecraft skin", active=not cfg.get("active_skin"),
                    on_use=lambda e: set_active(None), on_delete=None)
            for entry in skins:
                filename = entry["filename"]
                if filename in skin_cards and skin_cards[filename]._entry == entry:
                    continue
                cached = _THUMB_MEMO.get(("skin", filename))
                card = _owned_card(
                    src=cached, lazy_thumb=None if cached else ("skin", filename),
                    thumb_grid=skins_list_col,
                    label=entry["name"] + (" (slim)" if entry.get("slim") else ""),
                    sublabel="", active=cfg.get("active_skin") == filename,
                    on_use=lambda e, fn=filename: set_active(fn),
                    on_delete=lambda e, fn=filename: delete_skin(fn),
                    model_label=("Alex · 3 px" if entry.get("model") == "slim"
                                 else "Steve · 4 px" if entry.get("model") == "classic"
                                 else "Auto · " + ("Alex" if entry.get("slim") else "Steve")),
                    on_model=lambda e, fn=filename: change_skin_arms(fn))
                card._entry = dict(entry)
                skin_cards[filename] = card
            skins_list_col.controls = [skin_cards[None]] + [skin_cards[e["filename"]] for e in skins]
            sync_skin_selection()
            _fit_grid(skins_list_col)
        _flush_pending_thumbs()

    def handle_skin_files(files):
        if not files:
            return
        picked = files[0]
        # Validate + PIL-probe + copy + CSL sync + preview render is a
        # multi-hundred-ms chain; it used to run inside the picker callback
        # on the UI thread (same freeze class as the old profile-picture
        # upload). Work happens on a thread; the button is parked so a
        # double-click can't start two uploads of the same file.
        with thread_safe_ui.TREE_LOCK:
            if upload_button.disabled:
                return
            upload_button.disabled = True
            upload_status.value = "Uploading..."
        _refresh_status(upload_status)
        thread_safe_ui.refresh(upload_button)

        def _work():
            try:
                display_name = os.path.splitext(picked.name)[0]
                entry = core.add_custom_skin(
                    picked.path, display_name, model="auto")
                set_active(entry["filename"])
                refresh_skins_list()
                thread_safe_ui.refresh(skins_list_col)
                msg = f"Uploaded and set '{entry['name']}' as active skin."
            except ValueError as ve:
                msg = str(ve)
            except Exception as ex:
                msg = f"Upload failed: {ex}"
            with thread_safe_ui.TREE_LOCK:
                upload_status.value = msg
                upload_button.disabled = False
            _refresh_status(upload_status)
            thread_safe_ui.refresh(upload_button)

        threading.Thread(target=_work, daemon=True,
                         name="ux-skin-upload").start()

    def on_files_picked(e):
        # Old-Flet path: pick_files() ran synchronously and the result
        # arrives here via on_result. Untyped rather than annotated as
        # ft.FilePickerResultEvent - missing on some pinned Flet builds
        # (e.g. 0.86.x), which would crash this def at import time.
        handle_skin_files(e.files)

    # Reuse the shared FilePicker passed in from main.py (created and
    # registered once, outside this function) instead of constructing and
    # registering a new one every time this section rebuilds. Just point
    # its on_result at this rebuild's own on_files_picked closure.
    file_picker.on_result = on_files_picked

    def open_picker(e=None):
        core.run_file_picker(
            page, file_picker,
            on_files=handle_skin_files,
            dialog_title="Choose a skin PNG (64x64)",
            allow_multiple=False,
            allowed_extensions=["png"],
        )

    # Compact upload action shares the current-selection toolbar.
    upload_button = attach_hover(ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.ADD_ROUNDED, color=ACCENT, size=18),
                ft.Text("Upload skin", color=ACCENT, weight=ft.FontWeight.W_700, size=13),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=8,
            tight=True,
        ),
        border=ft.border.Border.all(1, ACCENT_DIM),
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=8, horizontal=10),
        alignment=ft.Alignment.CENTER,
        ink=False,
        on_click=open_picker,
    ), None, SURFACE_HI)

    refresh_skins_list()
    if cfg.get("active_skin"):
        _active_skin = cfg.get("active_skin")
        _active_skin_entry = next(
            (s for s in core.list_custom_skins()
             if s.get("filename") == _active_skin), None)
        skin_preview_name.value = (_active_skin_entry or {}).get("name") or "Custom skin"

    # =====================================================================
    # CUSTOM CAPE - upload/store a cape PNG, preview its visible face, set
    # one active, and sync it into CustomSkinLoader's LocalSkin/capes folder
    # (cubeon/capes.py). Same shape as the skin uploader above. A custom cape
    # WINS the cape slot in-game (csl.py's load-order contract puts the local
    # source ahead of the Worker); with none set, the shared Cubeon cape is
    # what's worn. Visibility is you-only either way - the note below says so
    # rather than pretending otherwise.
    # =====================================================================

    # main.py passes a single shared, pre-registered cape picker. Fall back to
    # a throwaway only when one wasn't supplied (e.g. the headless smoke test),
    # so building never crashes; the real app always hands one in.
    if cape_file_picker is None:
        cape_file_picker = ft.FilePicker()

    cape_preview_name = ft.Text("Cubeon Cape", size=13,
                                color=TEXT)
    cape_status = ft.Text("", size=12, color=TEXT_DIM, visible=False)
    # Wrapping card grid, same as the skins installed list (see _owned_card).
    capes_list_col = _card_grid(170)
    cape_cards = {}

    def render_cape_preview_for(filename):
        appearance.refresh(invalidate=True)

    def show_default_cape_preview():
        appearance.refresh(invalidate=True)

    def set_active_cape(filename):
        if cfg.get("active_cape") == filename and not cfg.get("hide_cubeon_cape"):
            return True
        try:
            core.set_active_cape(cfg, filename)
        except Exception as ex:
            cape_status.value = f"Couldn't switch cape: {ex}"
            _refresh_status(cape_status)
            return False
        if filename:
            render_cape_preview_for(filename)
            entry = next((c for c in core.list_capes()
                          if c.get("filename") == filename), None)
            cape_preview_name.value = (entry or {}).get("name") or "Custom cape"
            cape_status.value = ""
        else:
            show_default_cape_preview()
            cape_preview_name.value = "Cubeon Cape"
            cape_status.value = ""
        thread_safe_ui.refresh(cape_preview_name)
        sync_cape_selection()
        thread_safe_ui.refresh(capes_list_col)
        _refresh_status(cape_status)
        return True

    def hide_cape():
        """The Cape pane's None card: no cape on this player's screen."""
        try:
            core.set_hide_cubeon_cape(cfg, True)
        except Exception as ex:
            cape_status.value = f"Couldn't hide the cape: {ex}"
            _refresh_status(cape_status)
            return
        appearance.refresh(invalidate=True)
        cape_preview_name.value = "No cape"
        # Be honest: the shared cape is assigned server-side, so this hides it
        # locally rather than telling friends you have no cape.
        cape_status.value = ("Cape hidden on your screen. Friends still see "
                             "your shared Cubeon cape.")
        thread_safe_ui.refresh(cape_preview_name)
        sync_cape_selection()
        thread_safe_ui.refresh(capes_list_col)
        _refresh_status(cape_status)

    def delete_cape(filename):
        ft.context.disable_auto_update()
        # Same guarded shape as delete_skin: silent handler exceptions made
        # a failed delete look like a dead button.
        try:
            if cfg.get("active_cape") == filename:
                core.set_active_cape(cfg, None)
                show_default_cape_preview()
                cape_preview_name.value = "Cubeon Cape"
            core.delete_custom_cape(filename)
            core.forget_file("cape", filename)
        except Exception as ex:
            cape_status.value = f"Couldn't delete: {ex}"
            _refresh_status(cape_status)
            return
        _THUMB_MEMO.pop(("cape", filename), None)
        refresh_capes_list()
        thread_safe_ui.refresh(capes_list_col)
        thread_safe_ui.refresh(cape_preview_name)

    def sync_cape_selection():
        with thread_safe_ui.TREE_LOCK:
            hidden = bool(cfg.get("hide_cubeon_cape"))
            for filename, card in cape_cards.items():
                selected = hidden if filename == "__hidden__" else (
                    not hidden and cfg.get("active_cape") == filename)
                card.set_selected(selected)

    def refresh_capes_list():
        capes = core.list_capes()
        with thread_safe_ui.TREE_LOCK:
            for filename in list(cape_cards):
                if filename not in (None, "__hidden__") and not any(entry["filename"] == filename for entry in capes):
                    del cape_cards[filename]
            if "__hidden__" not in cape_cards:
                cape_cards["__hidden__"] = _owned_card(
                    icon=ft.Icons.BLOCK_ROUNDED, label="None", sublabel="No cape on your screen",
                    active=bool(cfg.get("hide_cubeon_cape")), on_use=lambda e: hide_cape(),
                    on_delete=None, preview_w=64, preview_h=84)
            if None not in cape_cards:
                cape_cards[None] = _owned_card(
                    src=DEFAULT_CAPE_PREVIEW_SRC, label="Cubeon Cape", sublabel="Default",
                    active=not cfg.get("active_cape") and not cfg.get("hide_cubeon_cape"),
                    on_use=lambda e: set_active_cape(None), on_delete=None, preview_w=64, preview_h=84)
            for entry in capes:
                filename = entry["filename"]
                if filename in cape_cards and cape_cards[filename]._entry == entry:
                    continue
                cached = _THUMB_MEMO.get(("cape", filename))
                card = _owned_card(
                    src=cached, lazy_thumb=None if cached else ("cape", filename),
                    thumb_grid=capes_list_col, label=entry["name"],
                    sublabel=("Built-in · Animated" if entry.get("animated") else "Built-in")
                             if entry.get("builtin") else "Animated GIF" if entry.get("animated") else "",
                    active=cfg.get("active_cape") == filename,
                    on_use=lambda e, fn=filename: set_active_cape(fn),
                    on_delete=None if entry.get("builtin") else lambda e, fn=filename: delete_cape(fn),
                    preview_w=64, preview_h=84)
                card._entry = dict(entry)
                cape_cards[filename] = card
            capes_list_col.controls = [cape_cards["__hidden__"], cape_cards[None]] + [cape_cards[e["filename"]] for e in capes]
            active = next((e for e in capes if e["filename"] == cfg.get("active_cape")), None)
            if active:
                cape_preview_name.value = active["name"]
            sync_cape_selection()
            _fit_grid(capes_list_col)
        _flush_pending_thumbs()

    def handle_cape_files(files):
        if not files:
            return
        picked = files[0]
        # Threaded for the same reason as handle_skin_files; also replaces
        # the bare page.update() (unsafe from a worker thread) with
        # control-level thread_safe_ui refreshes.
        with thread_safe_ui.TREE_LOCK:
            if cape_upload_button.disabled:
                return
            cape_upload_button.disabled = True
            cape_status.value = "Uploading..."
            _refresh_status(cape_status)
            thread_safe_ui.refresh(cape_upload_button)

        def _work():
            try:
                display_name = os.path.splitext(picked.name)[0]
                entry = core.add_custom_cape(picked.path, display_name)
                applied = set_active_cape(entry["filename"])
                msg = f"Uploaded and set '{entry['name']}' as active cape." if applied else cape_status.value
                refresh_capes_list()
                thread_safe_ui.refresh(capes_list_col)
            except ValueError as ve:
                msg = str(ve)
            except Exception as ex:
                msg = f"Upload failed: {ex}"
            with thread_safe_ui.TREE_LOCK:
                cape_status.value = msg
                cape_upload_button.disabled = False
                _refresh_status(cape_status)
                thread_safe_ui.refresh(cape_upload_button)

        threading.Thread(target=_work, daemon=True,
                         name="ux-cape-upload").start()

    def on_cape_files_picked(e):
        # Untyped for the same version-spanning reason as on_files_picked.
        handle_cape_files(e.files)

    cape_file_picker.on_result = on_cape_files_picked

    def open_cape_picker(e=None):
        # Any image goes: PNG/JPEG/WebP/GIF/BMP... Non-cape shapes are
        # auto-fitted onto the cape layout (see cubeon/capes.py).
        core.run_file_picker(
            page, cape_file_picker,
            on_files=handle_cape_files,
            dialog_title="Choose a cape image or GIF",
            allow_multiple=False,
            allowed_extensions=[
                "png", "jpg", "jpeg", "webp", "gif", "bmp",
            ],
        )

    cape_upload_button = attach_hover(ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.ADD_ROUNDED, color=ACCENT, size=18),
                ft.Text("Upload cape", color=ACCENT, weight=ft.FontWeight.W_700, size=13),
            ],
            alignment=ft.MainAxisAlignment.CENTER,
            spacing=8,
            tight=True,
        ),
        border=ft.border.Border.all(1, ACCENT_DIM),
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=8, horizontal=10),
        alignment=ft.Alignment.CENTER,
        ink=False,
        tooltip="Upload an image or animated GIF up to 8 MB",
        on_click=open_cape_picker,
    ), None, SURFACE_HI)

    if cfg.get("active_cape"):
        cape_preview_name.value = "Custom cape"
    else:
        # No custom cape == the shared Cubeon cape is what's worn, so seed the
        # preview with it rather than leaving the box hidden on first paint -
        # unless the user chose None, which hides it locally.
        if cfg.get("hide_cubeon_cape"):
            cape_preview_name.value = "No cape"

    # Selection and management share one toolbar; details stay in tooltips.
    skin_preview_name.tooltip = skin_visibility_note()
    cape_preview_name.tooltip = ("Your custom cape replaces the shared Cubeon cape "
                                 "in-game; friends still see the shared one on you "
                                 "for now.")
    for name in (skin_preview_name, cape_preview_name):
        name.max_lines = 1
        name.overflow = ft.TextOverflow.ELLIPSIS
    skin_pane = ft.Column(
        [ft.Row([ft.Container(content=skin_preview_name, expand=True),
                 keyboard_target(upload_button, "Upload skin")]),
         _scroll_cards(skins_list_col), upload_status], spacing=12, expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    cape_pane = ft.Column(
        [ft.Row([ft.Container(content=cape_preview_name, expand=True),
                 keyboard_target(cape_upload_button, "Upload cape")]),
         _scroll_cards(capes_list_col), cape_status], spacing=12, expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    def load_capes():
        if not cape_cards:
            refresh_capes_list()
            return True
        return False
    cape_pane.load_items = load_capes

    # --- Public cape store -------------------------------------------------
    # Fetch only on first opening or Refresh. Downloads import into the existing
    # Cape library; they never change the player's active cape or publish skin state.
    store_grid = _card_grid(170)
    store_status = ft.Text("", size=12, color=TEXT_DIM, visible=False)
    store_page = ft.Text("Page 1", size=12, color=TEXT_DIM)
    store_state = {"loaded": False, "loading": False, "offset": 0, "more": False,
                   "signature": None, "downloads": set(), "cards": {}, "items": {}, "request": 0,
                   "query": "", "timer": None}

    def sync_store_buttons():
        busy = store_state["loading"] or bool(store_state["downloads"])
        store_refresh.disabled = busy
        store_previous.disabled = busy or store_state["offset"] == 0
        store_next.disabled = busy or not store_state["more"]
        store_search.disabled = bool(store_state["downloads"])
        store_page.value = f"Page {store_state['offset'] // cosmetics_store.PAGE_SIZE + 1}"

    def download_store_cape(item):
        with thread_safe_ui.TREE_LOCK:
            if store_state["loading"] or item["id"] in store_state["downloads"]:
                return
            # A saved page remains usable during its background refresh. That
            # refresh must not replace controls beneath an active download.
            store_state["request"] += 1
            store_state["downloads"].add(item["id"])
            card = store_state["cards"][item["id"]]
            card.disabled = True
            card.set_sublabel("Downloading…")
            store_status.value = f"Downloading {item['name']}…"
            sync_store_buttons()
        thread_safe_ui.refresh(card)
        thread_safe_ui.refresh(store_toolbar)
        _refresh_status(store_status)

        def work():
            try:
                cosmetics_store.download(item)
                destination = {'cape': 'Cape', 'pet': 'Pets', 'wing': 'Back', 'head': 'Head', 'feet': 'Feet', 'aura': 'Aura'}[item['kind']]
                message = f"Downloaded {item['name']}. Open {destination} to equip it."
                success = True
            except Exception as error:
                message = f"Couldn't download this cosmetic: {error}"
                success = False
            if success and item["kind"] == "cape":
                refresh_capes_list()
            with thread_safe_ui.TREE_LOCK:
                store_state["downloads"].discard(item["id"])
                card.disabled = False
                card.set_selected(success)
                card.set_sublabel("Downloaded" if success else "Free cosmetic")
                store_status.value = message
                sync_store_buttons()
            thread_safe_ui.refresh(card)
            thread_safe_ui.refresh(store_toolbar)
            if success and item["kind"] == "cape":
                thread_safe_ui.refresh(capes_list_col)
            _refresh_status(store_status)

        threading.Thread(target=work, daemon=True, name="cubeon-store-download").start()

    def load_store(offset=None, *, force=False):
        with thread_safe_ui.TREE_LOCK:
            query = (store_search.value or "").strip()
            if store_state["downloads"] or (store_state["loading"] and query == store_state["query"]):
                return
            if store_state["loaded"] and offset is None and not force and query == store_state["query"]:
                return
            requested = 0 if query != store_state["query"] else store_state["offset"] if offset is None else offset
            store_state["request"] += 1
            request = store_state["request"]
            store_state["query"] = query
            store_state["loading"] = True
            store_status.value = "Loading cosmetics…"
            sync_store_buttons()
        thread_safe_ui.refresh(store_toolbar)
        _refresh_status(store_status)

        def paint(data, *, message=""):
            owned = {item["id"]: cosmetics_store.has_installed(item) for item in data["items"]} if data else {}
            with thread_safe_ui.TREE_LOCK:
                if request != store_state["request"]:
                    return
                store_state["loading"] = False
                if data is not None:
                    signature = (requested, tuple((item["id"], item["sha256"], item["name"],
                        item["description"], item["preview_png"]) for item in data["items"]))
                    if signature != store_state["signature"]:
                        store_grid.controls.clear()
                        store_state["cards"].clear()
                        for item in data["items"]:
                            card = _owned_card(src=item["preview_png"], label=item["name"],
                                sublabel="Downloaded" if owned[item["id"]] else "Free cosmetic",
                                active=bool(owned[item["id"]]),
                                on_use=lambda e, value=item: download_store_cape(value),
                                on_delete=None, preview_w=64, preview_h=84, action_label="Download")
                            card.tooltip = item["description"]
                            store_state["cards"][item["id"]] = card
                            store_grid.controls.append(card)
                        _fit_grid(store_grid)
                        store_state["signature"] = signature
                    else:
                        for item_id, card in store_state["cards"].items():
                            card.set_selected(bool(owned[item_id]))
                            card.set_sublabel("Downloaded" if owned[item_id] else "Free cosmetic")
                    store_state["items"] = {item["id"]: item for item in data["items"]}
                    store_state.update(loaded=True, offset=requested, more=data["has_more"])
                    store_status.value = message or ("" if data["items"] else
                        f'No cosmetics match “{query}”.' if query else "No cosmetics are available yet.")
                else:
                    store_status.value = message or "The cosmetics store is unavailable. Try Refresh."
                sync_store_buttons()
            thread_safe_ui.refresh(store_grid)
            thread_safe_ui.refresh(store_toolbar)
            _refresh_status(store_status)

        def work():
            try:
                if query:
                    saved = cosmetics_store.cached_catalog()
                    recent = None if force else cosmetics_store.cached_catalog(max_age=60, bundled=False)
                    cached = cosmetics_store.search_page(saved, query, requested) if saved else None
                    fresh = cosmetics_store.search_page(recent, query, requested) if recent else None
                else:
                    cached = cosmetics_store.cached_page(requested)
                    fresh = None if force else cosmetics_store.cached_page(requested, max_age=60, bundled=False)
            except Exception:
                cached, fresh = None, None
            if cached is not None:
                paint(cached, message="" if fresh is not None else "Updating cosmetics…")
            if fresh is not None:
                return
            try:
                data = cosmetics_store.search_page(cosmetics_store.fetch_catalog(force=force), query, requested) \
                    if query else cosmetics_store.fetch_page(requested)
            except Exception:
                if cached is not None:
                    paint(cached, message="Showing matches from saved pages. Refresh when online to search the full collection."
                        if query and not cached["complete"] else
                        "Showing saved cosmetics. Try Refresh for the latest collection.")
                else:
                    paint(None)
            else:
                paint(data)

        threading.Thread(target=work, daemon=True, name="cubeon-store-catalog").start()

    def search_store_now(e=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if store_state["timer"] is not None:
                store_state["timer"].cancel()
                store_state["timer"] = None
        load_store(0)

    def schedule_store_search(e=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if store_state["timer"] is not None:
                store_state["timer"].cancel()
            store_state["request"] += 1
            store_state["loading"] = False
            store_state["timer"] = threading.Timer(.2, lambda: load_store(0))
            store_state["timer"].daemon = True
            store_state["timer"].start()
            sync_store_buttons()
        thread_safe_ui.refresh(store_toolbar)

    store_search = ft.TextField(hint_text="Search the collection…", prefix_icon=ft.Icons.SEARCH_ROUNDED,
        border_color=CARD_BORDER, focused_border_color=ACCENT_DIM, color=TEXT,
        hint_style=ft.TextStyle(color=TEXT_DIM, size=13), text_style=ft.TextStyle(size=13),
        bgcolor=CARD_FILL, border_radius=RADIUS, height=40, dense=True,
        content_padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
        on_change=schedule_store_search, on_submit=search_store_now, expand=True,
        data="cosmetics-store-search")

    store_refresh = ft.IconButton(ft.Icons.REFRESH_ROUNDED, tooltip="Refresh collection",
                                  on_click=lambda e: load_store(force=True))
    store_previous = ft.IconButton(ft.Icons.CHEVRON_LEFT_ROUNDED, tooltip="Previous store page",
        disabled=True, on_click=lambda e: load_store(store_state["offset"] - cosmetics_store.PAGE_SIZE))
    store_next = ft.IconButton(ft.Icons.CHEVRON_RIGHT_ROUNDED, tooltip="Next store page",
        disabled=True, on_click=lambda e: load_store(store_state["offset"] + cosmetics_store.PAGE_SIZE))
    store_toolbar = ft.Column([ft.Row([store_search, store_refresh], spacing=8),
        ft.Row([store_page, ft.Container(expand=True), store_previous, store_next], spacing=4)],
        spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    store_pane = ft.Column([store_toolbar,
        _scroll_cards(store_grid), store_status], spacing=8, expand=True,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH, data="cosmetics-store")
    store_pane.load_items = load_store

    # --- Shoulder / Back cosmetics ----------------------------------------
    # Bundled artwork stays available; downloaded revisions have the same
    # separate delete action as imported skins and capes.
    _COSMETIC_MEMO = {}

    def _cosmetic_thumb(item):
        if item is None:
            return None
        hit = _COSMETIC_MEMO.get(item["id"])
        if hit is not None:
            return hit
        try:
            image = cosmetics.render_thumbnail(item, appearance.cosmetics_dir,
                                               size=COSMETIC_THUMB_SIZE, simplify=True)
            buffer = BytesIO()
            image.save(buffer, format="PNG", compress_level=3)
            hit = base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:
            return None
        _COSMETIC_MEMO[item["id"]] = hit
        return hit

    def _cosmetic_visibility_note():
        if mc_loader not in core.MOD_CAPABLE_LOADERS or not mc_version:
            return ("Pick Fabric or Quilt on the Play tab: the Cubeon Client "
                    "draws these in-game, and vanilla Minecraft cannot load it.")
        if not cfg.get("client_mod_enabled", True):
            return ("Cubeon Client is switched off in Settings, so this item "
                    "shows in the preview but not in-game.")
        return ("Drawn by Cubeon Client in-game. Wearables follow your character; "
                "trails appear briefly while walking.")

    def _cosmetic_pane(slot):
        grid = _card_grid(154)
        status = ft.Text("", size=12, color=TEXT_DIM, visible=False)
        equipped = ft.Text("Nothing equipped", size=12, color=TEXT,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        key = f"active_{slot}_item"
        cards = {}
        groups = {}
        metadata = {}
        revision = {"value": 0}
        category = {"id": "all"}
        filter_row = ft.Row(spacing=10, wrap=True, run_spacing=4)
        filters = {group: text_tab(label, selected=group == "all",
            on_click=lambda e, g=group: filter_items(g))
            for group, label in (("all", "All"), ("small", "Small wings"),
                                 ("giant", "Giant wings"), ("pack", "Packs"))}
        filter_row.controls = list(filters.values())

        def sync_selection():
            active_id = cfg.get(key)
            item = metadata.get(active_id)
            label = f"Equipped: {item['name']}" if item else "Nothing equipped"
            changed = equipped.value != label or remove.disabled != (item is None)
            equipped.value = label
            remove.disabled = item is None
            for item_id, card in cards.items():
                changed = card.set_selected(active_id == item_id) or changed
            return changed

        def filter_items(group):
            ft.context.disable_auto_update()
            with thread_safe_ui.TREE_LOCK:
                if category["id"] == group:
                    return
                category["id"] = group
                for item_id, card in cards.items():
                    card.visible = group == "all" or groups[item_id] == group
                for filter_id, button in filters.items():
                    button.set_selected(group == filter_id)
                _update_thumb_window(grid)
            thread_safe_ui.refresh(grid)
            thread_safe_ui.refresh(filter_row)
            _flush_pending_thumbs()

        def refresh():
            with thread_safe_ui.TREE_LOCK:
                revision["value"] += 1
                request = revision["value"]
            items = cosmetics.items(slot, appearance.cosmetics_dir)
            ids = {item["id"] for item in items}
            with thread_safe_ui.TREE_LOCK:
                if request != revision["value"]:
                    return False
                changed = ids != set(cards)
                metadata.clear()
                metadata.update((item["id"], item) for item in items)
                for item_id in list(cards):
                    if item_id not in ids:
                        grid.controls.remove(cards.pop(item_id))
                        groups.pop(item_id, None)
                if not cards:
                    # Start with the worn item in view; later choices keep their
                    # position so applying/filtering never reshuffles the grid.
                    items.sort(key=lambda item: item["id"] != cfg.get(key))
            for item in items:
                # Release the tree lock between cards so a large first library
                # cannot hold pointer/navigation events behind the whole build.
                with thread_safe_ui.TREE_LOCK:
                    if request != revision["value"]:
                        return False
                    if item["id"] in cards:
                        continue
                    wing = bool(item.get("feathers"))
                    group = "small" if item["id"].endswith("_small") or (wing and item.get("wing_flare") is False) else "giant" if wing else "pack"
                    cached = _COSMETIC_MEMO.get(item["id"])
                    card = _owned_card(
                        src=cached, lazy_thumb=None if cached else ("cosmetic", item["id"]),
                        thumb_grid=grid, thumb_pane=slot,
                        label=item["name"].split(" (")[0] if wing else item["name"],
                        sublabel=("Small" if group == "small" else "Giant") if wing else "",
                        active=cfg.get(key) == item["id"],
                        on_use=lambda e, i=item["id"]: choose(i),
                        on_delete=(lambda e, i=item["id"]: delete(i)) if item.get("_store_directory") else None,
                        preview_w=76, preview_h=76)
                    card.tooltip = item["blurb"]
                    cards[item["id"]] = card
                    groups[item["id"]] = group
                    card.visible = category["id"] == "all" or category["id"] == group
                    grid.controls.append(card)
            with thread_safe_ui.TREE_LOCK:
                if request != revision["value"]:
                    return False
                changed = _fit_grid(grid) or changed
                changed = sync_selection() or changed
                return changed

        def delete(item_id):
            ft.context.disable_auto_update()
            item = cosmetics.get(item_id, appearance.cosmetics_dir)
            try:
                core.delete_downloaded_cosmetic(cfg, item_id)
            except Exception as error:
                status.value = f"Couldn't delete this cosmetic: {error}"
                _refresh_status(status)
                return
            refresh()
            store_id = item.get("store_id") if item else None
            metadata = store_state["items"].get(store_id)
            owned = cosmetics_store.installed(metadata) is not None if metadata else False
            with thread_safe_ui.TREE_LOCK:
                _COSMETIC_MEMO.pop(item_id, None)
                appearance.refresh(invalidate=True)
                status.value = ""
                card = store_state["cards"].get(store_id)
                if card is not None and metadata is not None:
                    card.set_selected(owned)
                    card.set_sublabel("Downloaded" if owned else "Free cosmetic")
            for control in (grid, equipped, remove):
                thread_safe_ui.refresh(control)
            if card is not None:
                thread_safe_ui.refresh(card)
            _refresh_status(status)

        def choose(item_id):
            ft.context.disable_auto_update()
            if cfg.get(key) == item_id:
                return
            previous = cfg.get(key)
            try:
                core.set_active_cosmetic(cfg, slot, item_id)
            except Exception as ex:
                status.value = f"Couldn't change this cosmetic: {ex}"
                _refresh_status(status)
                return
            with thread_safe_ui.TREE_LOCK:
                appearance.refresh(invalidate=True)
                status.value = ""
                sync_selection()
            # Equipping changes two cards, not the layout or every image in
            # the category. Keep the large grid out of the selection diff.
            for selected_id in (previous, item_id):
                card = cards.get(selected_id)
                if card is not None:
                    thread_safe_ui.refresh(card)
            for control in (equipped, remove):
                thread_safe_ui.refresh(control)
            _refresh_status(status)

        remove = ft.TextButton("Remove", icon=ft.Icons.CLOSE_ROUNDED,
                               on_click=lambda e: choose(None), disabled=True,
                               tooltip="Remove the equipped item")

        equipped.tooltip = _cosmetic_visibility_note()
        controls = [ft.Row([ft.Container(content=equipped, expand=True),
                            remove], spacing=8)]
        if slot == "back":
            controls.append(filter_row)
        controls.extend([_scroll_cards(grid), status])
        if slot == "back":
            equipped.tooltip += "\nSmall wings move gently. Press N in Minecraft for a Giant-wing flare; K → Cosmetic motion turns movement off."
        elif slot == "trail":
            equipped.tooltip += "\nA few short-lived particles while walking. Cosmetic motion turns them off; Minecraft's particle limit still applies."
        pane = ft.Column(controls, spacing=8, expand=True,
                         horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        pane.load_items = refresh
        return pane

    # Headwear and footwear share the existing picker and selection flow.
    cosmetic_panes = [(slot, cosmetics.SLOT_LABELS[slot], _cosmetic_pane(slot))
                     for slot in ("shoulder", "back", "head", "feet", "aura")]

    # One local category at a time. Browse is a separate mode so opening the
    # wardrobe never fetches the public catalogue. Visible category buttons
    # live inside My items, beside the library they control.
    PANES = [
        ("skin", "Skin", skin_pane),
        ("cape", "Cape", cape_pane),
        ("store", "Store", store_pane),
        *cosmetic_panes,
    ]
    pane_views = {pid: TabPane(pane, visible=pid == "skin", expand=True)
                  for pid, _, pane in PANES}
    pane_holder = ft.Stack(list(pane_views.values()), expand=True, fit=ft.StackFit.EXPAND,
                           data="cosmetics-panes")
    pane_holder._shell_only = True
    tab_row = ft.Row(spacing=24, data="wardrobe-modes")
    library_state = {"last": "skin"}
    category_buttons = {pid: text_tab(label, selected=pid == "skin",
        on_click=lambda event, key=pid: switch_pane(key))
        for pid, label, _ in PANES if pid != "store"}
    category_row = ft.Row(list(category_buttons.values()), spacing=12,
                          wrap=True, run_spacing=6, data="wardrobe-categories")
    mode_buttons = [
        text_tab(i18n.t("My items"), selected=True,
                 on_click=lambda e: switch_pane(library_state["last"])),
        text_tab(i18n.t("Browse"), on_click=lambda e: switch_pane("store")),
    ]
    tab_row.controls = mode_buttons

    def prepare_pane(pid, generation):
        pane = pane_views[pid].content
        load_items = getattr(pane, "load_items", None)
        changed = False
        if callable(load_items):
            changed = load_items()
        with thread_safe_ui.TREE_LOCK:
            current = pane_queue.is_current(generation) and active_pane["id"] == pid
        if current:
            if changed is not False:
                thread_safe_ui.refresh(pane)
            _flush_pending_thumbs()

    pane_queue = TabEntryQueue(page, prepare_pane)

    def build_pane_tabs():
        browsing = active_pane["id"] == "store"
        category_row.visible = not browsing
        if not browsing:
            library_state["last"] = active_pane["id"]
        mode_buttons[0].set_selected(not browsing)
        mode_buttons[1].set_selected(browsing)
        for pid, button in category_buttons.items():
            button.set_selected(active_pane["id"] == pid)

    def switch_pane(pid):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if pid not in pane_views:
                return
            if active_pane["id"] == pid:
                return
            active_pane["id"] = pid
            for key, pane in pane_views.items():
                pane.visible = key == pid
            build_pane_tabs()
        # Paint the retained shell before catalogue reads or card construction.
        thread_safe_ui.refresh(tab_row)
        thread_safe_ui.refresh(category_row)
        thread_safe_ui.refresh(pane_holder)
        if pid == "cape":
            appearance.turn(180 - appearance.yaw)
        elif pid == "back":
            # Back items are behind the player; the default front view hides
            # them almost completely. Turn the model round so the choice is
            # visible the moment the pane opens.
            appearance.turn(180 - appearance.yaw)
        elif pid == "shoulder":
            # Right shoulder is on the viewer's left in the front view; a
            # slight turn shows the pet and the face together.
            appearance.turn(25 - appearance.yaw)
        elif pid in cosmetics.SLOTS:
            appearance.turn(25 - appearance.yaw if pid in ("hand", "waist", "trail")
                            else -appearance.yaw)
        pane_queue.request(pid)

    build_pane_tabs()

    layout_size = {"compact": True, "height": getattr(page, "height", None) or 660}
    picker = ft.Container(
        content=ft.Column([category_row, pane_holder], expand=True, spacing=12,
                          horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        bgcolor=SURFACE, border=ft.border.Border.all(1, CARD_BORDER),
        border_radius=RADIUS_LG, padding=16,
        col={"xs": 12, "md": 8, "lg": 9}, data="cosmetics-picker")

    def _fit_picker():
        compact = layout_size["compact"]
        height = max(132 if compact else 200, min(320 if compact else 520,
                             layout_size["height"] - (400 if compact else 100)))
        if picker.height != height:
            picker.height = height
            thread_safe_ui.refresh(picker)

    def set_viewport_height(height):
        if height and math.isfinite(height) and height > 0:
            with thread_safe_ui.TREE_LOCK:
                layout_size["height"] = height
                _fit_picker()

    _fit_picker()

    def _preview_resized(event):
        ft.context.disable_auto_update()
        width = event.width
        if width and math.isfinite(width) and width > 0:
            appearance.resize(min(width, 176 if layout_size["compact"] else 256))

    # The preview's own size notifications must honor the compact height too.
    appearance.viewport.on_size_change = _preview_resized

    def _layout_resized(event):
        ft.context.disable_auto_update()
        # Compact preview leaves room to reach the items in a short window.
        # Only geometry changes; the existing model/image and camera stay live.
        width = event.width
        if width and math.isfinite(width) and width > 0:
            layout_size["compact"] = width < 760
            preview_width = min(176, width) if width < 760 else min(256, (width - 16) / (4 if width >= 1050 else 3))
            appearance.resize(preview_width)
            with thread_safe_ui.TREE_LOCK:
                _fit_picker()

    layout = ft.ResponsiveRow([
        ft.Container(content=ft.Column([
            ft.Text("Your look", size=13, color=TEXT_DIM), appearance.control,
        ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            col={"xs": 12, "md": 4, "lg": 3}, padding=12,
            bgcolor=SURFACE, border=ft.border.Border.all(1, CARD_BORDER),
            border_radius=RADIUS_LG, data="wardrobe-preview"),
        picker,
    ], breakpoints={"xs": 0, "md": 760, "lg": 1050}, spacing=16, run_spacing=16,
       on_size_change=_layout_resized, data="cosmetics-layout")
    skin_section = ft.Column([
        ft.Column([
            ft.Text(i18n.t("Wardrobe"), size=24, color=TEXT, font_family=FONT_DISPLAY),
            ft.Text("Make your Minecraft look your own.", size=12, color=TEXT_DIM),
        ], spacing=4),
        tab_row,
        layout,
    ], spacing=16)
    skin_section.set_viewport_height = set_viewport_height

    appearance.refresh()
    return skin_section
