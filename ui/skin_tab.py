"""Cosmetics: shared native 3D preview and local Skin / Cape / Shoulder / Back
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
    RADIUS,        # corner radius (design system single source)
    attach_hover,  # hover-state helper for hand-built Container "buttons"
    ACCENT_TINT, ACCENT_TINT_HI,  # selected/hover washes for tiles/cards
    text_tab,      # underline-style segment tab (same chrome as Mods' content types)
    keyboard_target,
    CARD_FILL, CARD_BORDER,  # translucent panel fills/outlines (Mods-tab language)
    ROW_HOVER,     # quiet hover lift for borderless rows/cards
)
from cubeon import thread_safe_ui  # control-level refresh() (thread-safe)
from cubeon import cosmetics
from ui.appearance_preview import AppearancePreview
from ui.image_memory import preview_image

# Our own launcher core module - contains logic for skin storage/rendering
import launcher_core as core

# The bundled preview of the shared Cubeon cape (the one the Worker serves to
# every player - see worker/cubeon-skins.js). This is a relative asset path,
# which ft.Image.src resolves against the app's assets_dir, so it shows up
# whenever no custom cape is selected instead of leaving the box blank.
DEFAULT_CAPE_PREVIEW_SRC = "capes/cubeon_cape_preview.png"
DEFAULT_SKIN_PREVIEW_SRC = "skins/steve-preview.png"


# Preview bytes are immutable once written, so base64-encoding them once and
# keeping the string in memory spares every grid rebuild a disk read + encode.
def build_skin_section(page: ft.Page, cfg: dict, *, section_label, pixel_divider,
                        BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                        TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO=None,
                        mc_version=None, mc_loader=None, file_picker=None,
                        cape_file_picker=None, assets_dir=None):
    """
    Build the retained Cosmetics tab content. Category tabs sit above a
    responsive preview/library layout; the parent owns vertical scrolling.

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
    skin_preview_name = ft.Text("Steve · Default skin", size=13, color=TEXT)

    def _refresh_status(control):
        with thread_safe_ui.TREE_LOCK:
            control.visible = bool(control.value)
        thread_safe_ui.refresh(control)

    def _fit_grid(grid, width=None):
        """Resize retained cards using their pane's actual available width."""
        width = width if width is not None else getattr(grid, "available_width", None)
        if not width or not math.isfinite(width) or width <= 0:
            return False
        grid.available_width = width
        columns = max(1, int((width + 12) / (132 + 12)))
        card_width = min(164, (width - 12 * (columns - 1)) / columns)
        changed = False
        for card in grid.controls:
            if callable(getattr(card, "set_selected", None)) and card.width != card_width:
                card.width = card_width
                changed = True
        return changed

    def _grid_resized(event):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            changed = _fit_grid(event.control, event.width)
        if changed:
            thread_safe_ui.refresh(event.control)

    def _card_grid():
        return ft.Row(spacing=12, wrap=True, run_spacing=12,
                      vertical_alignment=ft.CrossAxisAlignment.START,
                      on_size_change=_grid_resized)

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

    # One parent scroll area; grids wrap and resize without remounting cards.
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
                    icon=None, model_label=None, on_model=None):
        """Click the artwork/name to apply. Keep management actions separate;
        selection updates retain the image and its keyboard target.

        src: ready preview bytes/asset path (default cape, already-cached b64).
        lazy_thumb: ("skin"|"cape", filename) - build the card immediately with
        a placeholder and let the thumb worker fill the image in; the grid
        never waits on PIL. Pass neither for a permanent "not an image" icon.
        """
        if src:
            preview_img = preview_image(src=src, width=preview_w, height=preview_h,
                                   fit=ft.BoxFit.CONTAIN)
            placeholder = None
        elif lazy_thumb:
            # Visible only once the worker thread lands real bytes. The
            # placeholder keeps the card's height stable meanwhile, so the
            # grid doesn't reflow as thumbs pop in.
            preview_img = preview_image(src="icon.svg", width=preview_w,
                                   height=preview_h, fit=ft.BoxFit.CONTAIN,
                                   visible=False)
            placeholder = ft.Icon(ft.Icons.IMAGE_OUTLINED, color=TEXT_DIM,
                                  size=22)
            _PENDING_THUMBS.append((preview_img, placeholder,
                                    lazy_thumb[0], lazy_thumb[1]))
        else:
            preview_img, placeholder = None, ft.Icon(
                icon or ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED, color=TEXT_DIM,
                size=22)
        preview_stack = [c for c in (preview_img, placeholder) if c is not None]
        selected = {"value": active}
        name = ft.Text(label, size=12, color=TEXT, weight=ft.FontWeight.W_600,
                       max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                       text_align=ft.TextAlign.CENTER)
        check = ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=ACCENT, size=18,
                        right=2, top=2, visible=active)
        artwork = ft.Stack([
            ft.Container(content=ft.Row(preview_stack, spacing=0,
                         alignment=ft.MainAxisAlignment.CENTER),
                         height=preview_h + 12, alignment=ft.Alignment.CENTER),
            check,
        ])
        def apply_item(e):
            ft.context.disable_auto_update()
            with thread_safe_ui.TREE_LOCK:
                if not selected["value"]:
                    on_use(e)

        primary = ft.Container(
            content=ft.Column([artwork, name,
                ft.Text(sublabel, size=10, color=TEXT_DIM,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                        text_align=ft.TextAlign.CENTER) if sublabel else ft.Container()],
                spacing=5, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=8, border_radius=RADIUS, ink=False,
            tooltip=f"Apply {label}" + (f" ({sublabel})" if sublabel else ""),
            on_click=apply_item,
            on_hover=lambda e: card.on_hover(e),
        )
        actions = []
        if model_label:
            actions.append(keyboard_target(ft.Container(
                content=ft.Text(model_label, size=10, color=ACCENT),
                on_click=on_model, bgcolor=CARD_FILL,
                padding=ft.padding.Padding.symmetric(horizontal=6, vertical=5),
                border_radius=RADIUS,
                tooltip="Change arms: Auto → Alex (3 px) → Steve (4 px)"),
                f"Change arm model for {label}"))
        if on_delete is not None:
            actions.append(keyboard_target(ft.Container(
                content=ft.Icon(ft.Icons.DELETE_OUTLINE_ROUNDED, color=DANGER, size=16),
                width=30, height=28, bgcolor=CARD_FILL,
                border=ft.border.Border.all(1, CARD_BORDER), border_radius=RADIUS,
                alignment=ft.Alignment.CENTER, ink=False, on_click=on_delete,
                tooltip=i18n.t("Delete"),
            ), f"Delete {label}"))
        footer = ft.Row(actions, spacing=8,
                        alignment=ft.MainAxisAlignment.CENTER)
        card = ft.Container(
            content=ft.Column(
                [keyboard_target(primary, primary.tooltip),
                 ft.Container(content=footer, height=34)
                 if actions or preview_h != 76 else ft.Container()],
                spacing=0, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
            ),
            width=132,
            bgcolor=ACCENT_TINT if active else CARD_FILL,
            border=ft.border.Border.all(1, ACCENT if active else CARD_BORDER),
            border_radius=RADIUS,
            padding=4,
        )

        def set_selected(value):
            selected["value"] = bool(value)
            check.visible = bool(value)
            name.color = ACCENT if value else TEXT
            card.bgcolor = ACCENT_TINT if value else CARD_FILL
            card.border = ft.border.Border.all(1, ACCENT if value else CARD_BORDER)
            attach_hover(card, card.bgcolor, ACCENT_TINT_HI if value else ROW_HOVER)

        card.set_selected = set_selected
        set_selected(active)
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
    _PENDING_THUMBS = []  # (image_ctl, placeholder_ctl, kind, filename)

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
            return None  # unreadable/missing sheet: the placeholder stays

    def _flush_pending_thumbs():
        """Render queued card thumbs off-thread, one worker for the batch."""
        if not _PENDING_THUMBS:
            return
        jobs, _PENDING_THUMBS[:] = list(_PENDING_THUMBS), []

        def _worker():
            for img, ph, kind, fn in jobs:
                b64 = _render_thumb(kind, fn)
                if not b64:
                    continue
                with thread_safe_ui.TREE_LOCK:
                    img.src = b64
                    img.visible = True
                    if ph is not None:
                        ph.visible = False
                thread_safe_ui.refresh(img)
                if ph is not None:
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
                refresh_skins_list()
                upload_status.value = "Arm model updated. Restart Minecraft to apply it in-game."
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
        skin_cards.clear()
        skins_list_col.controls.clear()
        # Default Steve is a real choice; it clears the active custom skin.
        skins_list_col.controls.append(_owned_card(
            src=DEFAULT_SKIN_PREVIEW_SRC,
            label="Steve",
            sublabel="Default Minecraft skin",
            active=not cfg.get("active_skin"),
            on_use=lambda e: set_active(None),
            on_delete=None,
        ))
        if not skins:
            skins_list_col.controls.append(
                ft.Text("No uploaded skins yet.", size=12, color=TEXT_DIM)
            )
        for s in skins:
            is_active = cfg.get("active_skin") == s["filename"]
            # Ready bytes if the thumb was already rendered this session;
            # otherwise build the card around a placeholder and let the
            # worker thread fill it in - the grid never waits on PIL.
            cached = _THUMB_MEMO.get(("skin", s["filename"]))
            skins_list_col.controls.append(_owned_card(
                src=cached,
                lazy_thumb=None if cached else ("skin", s["filename"]),
                label=s["name"] + (" (slim)" if s.get("slim") else ""),
                sublabel="",
                active=is_active,
                on_use=lambda e, fn=s["filename"]: set_active(fn),
                on_delete=lambda e, fn=s["filename"]: delete_skin(fn),
                model_label=("Alex · 3 px" if s.get("model") == "slim"
                             else "Steve · 4 px" if s.get("model") == "classic"
                             else "Auto · " + ("Alex" if s.get("slim") else "Steve")),
                on_model=lambda e, fn=s["filename"]: change_skin_arms(fn),
            ))
        skin_cards[None] = skins_list_col.controls[0]
        skin_cards.update((s["filename"], card) for s, card in
                          zip(skins, skins_list_col.controls[1:]))
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
                msg = f"Uploaded and set '{entry['name']}' as active skin."
            except ValueError as ve:
                msg = str(ve)
            except Exception as ex:
                msg = f"Upload failed: {ex}"
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
        render_preview_for(_active_skin)
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
    capes_list_col = _card_grid()
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
        cape_cards.clear()
        capes_list_col.controls.clear()

        # "None" is a real choice here too. The shared cape is assigned by the
        # Worker, so this hides it locally (a transparent LocalSkin cape) -
        # friends still see the shared one. Picking any cape lifts the hide.
        hidden_active = bool(cfg.get("hide_cubeon_cape"))
        capes_list_col.controls.append(_owned_card(
            icon=ft.Icons.BLOCK_ROUNDED,
            label="None",
            sublabel="No cape on your screen",
            active=hidden_active,
            on_use=lambda e: hide_cape(),
            on_delete=None,
            preview_w=64, preview_h=84,
        ))

        # The built-in Cubeon cape leads the grid as a real, selectable card.
        # It's ACTIVE whenever no custom cape is set (that's what the Worker
        # serves to everyone); picking it just clears the custom cape via
        # set_active_cape(None). No delete - it's the shipped default.
        default_active = not cfg.get("active_cape") and not hidden_active
        capes_list_col.controls.append(_owned_card(
            src=DEFAULT_CAPE_PREVIEW_SRC,
            label="Cubeon Cape",
            sublabel="Default" if default_active else "Everyone sees this",
            active=default_active,
            on_use=lambda e: set_active_cape(None),
            on_delete=None,
            preview_w=64, preview_h=84,
        ))
        for c in capes:
            is_active = cfg.get("active_cape") == c["filename"]
            cached = _THUMB_MEMO.get(("cape", c["filename"]))
            capes_list_col.controls.append(_owned_card(
                src=cached,
                lazy_thumb=None if cached else ("cape", c["filename"]),
                label=c["name"],
                sublabel=("Built-in · Animated" if c.get("animated") else "Built-in")
                         if c.get("builtin") else "Animated GIF" if c.get("animated") else "",
                active=is_active,
                on_use=lambda e, fn=c["filename"]: set_active_cape(fn),
                on_delete=None if c.get("builtin") else lambda e, fn=c["filename"]: delete_cape(fn),
                preview_w=64, preview_h=84,
            ))

        cape_cards["__hidden__"] = capes_list_col.controls[0]
        cape_cards[None] = capes_list_col.controls[1]
        cape_cards.update((c["filename"], card) for c, card in
                          zip(capes, capes_list_col.controls[2:]))

        if not capes:
            capes_list_col.controls.append(
                ft.Text("No uploaded capes yet.", size=12, color=TEXT_DIM)
            )
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
                with thread_safe_ui.TREE_LOCK:
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

    refresh_capes_list()
    if cfg.get("active_cape"):
        _active_cape = cfg["active_cape"]
        render_cape_preview_for(_active_cape)
        _active_cape_entry = next(
            (c for c in core.list_capes()
             if c.get("filename") == _active_cape), None)
        cape_preview_name.value = (_active_cape_entry or {}).get("name") or "Custom cape"
    else:
        # No custom cape == the shared Cubeon cape is what's worn, so seed the
        # preview with it rather than leaving the box hidden on first paint -
        # unless the user chose None, which hides it locally.
        if cfg.get("hide_cubeon_cape"):
            appearance.refresh(invalidate=True)
            cape_preview_name.value = "No cape"
        else:
            show_default_cape_preview()

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
         skins_list_col, upload_status], spacing=12)
    cape_pane = ft.Column(
        [ft.Row([ft.Container(content=cape_preview_name, expand=True),
                 keyboard_target(cape_upload_button, "Upload cape")]),
         capes_list_col, cape_status], spacing=12)

    # --- Shoulder / Back cosmetics ----------------------------------------
    # These are not uploads: the art ships with the Cubeon Client, and the
    # launcher only records which id is worn. The cards therefore have no
    # Delete action - the honest actions are "use" and "empty slot".
    _COSMETIC_MEMO = {}

    def _cosmetic_thumb(item):
        hit = _COSMETIC_MEMO.get(item["id"])
        if hit is not None:
            return hit
        try:
            image = cosmetics.render_thumbnail(item, appearance.cosmetics_dir,
                                               size=(76, 76), simplify=True)
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
        grid = _card_grid()
        status = ft.Text("", size=12, color=TEXT_DIM, visible=False)
        equipped = ft.Text("Nothing equipped", size=12, color=TEXT,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        key = f"active_{slot}_item"
        cards = {}
        groups = {}
        category = {"id": "all"}
        filter_row = ft.Row(spacing=10, wrap=True, run_spacing=4)

        def sync_selection():
            active_id = cfg.get(key)
            item = cosmetics.get(active_id, appearance.cosmetics_dir)
            equipped.value = f"Equipped: {item['name']}" if item else "Nothing equipped"
            remove.disabled = item is None
            for item_id, card in cards.items():
                card.set_selected(active_id == item_id)

        def filter_items(group):
            with thread_safe_ui.TREE_LOCK:
                category["id"] = group
                for item_id, card in cards.items():
                    card.visible = group == "all" or groups[item_id] == group
                build_filters()
            thread_safe_ui.refresh(grid)
            thread_safe_ui.refresh(filter_row)

        def build_filters():
            filter_row.controls = [text_tab(label, selected=category["id"] == group,
                on_click=lambda e, g=group: filter_items(g))
                for group, label in (("all", "All"), ("small", "Small wings"),
                                     ("giant", "Giant wings"), ("pack", "Packs"))]

        def refresh():
            if not cards:
                items = cosmetics.items(slot, appearance.cosmetics_dir)
                # Start with the worn item in view; later choices keep their
                # position so applying/filtering never reshuffles the grid.
                items.sort(key=lambda item: item["id"] != cfg.get(key))
                for item in items:
                    wing = bool(item.get("feathers"))
                    group = "small" if item["id"].endswith("_small") else "giant" if wing else "pack"
                    cached = _COSMETIC_MEMO.get(item["id"])
                    card = _owned_card(
                        src=cached, lazy_thumb=None if cached else ("cosmetic", item["id"]),
                        label=item["name"].split(" (")[0] if wing else item["name"],
                        sublabel=("Small" if group == "small" else "Giant") if wing else "",
                        active=cfg.get(key) == item["id"],
                        on_use=lambda e, i=item["id"]: choose(i), on_delete=None,
                        preview_w=76, preview_h=76)
                    card.tooltip = item["blurb"]
                    cards[item["id"]] = card
                    groups[item["id"]] = group
                    grid.controls.append(card)
                _fit_grid(grid)
            sync_selection()

        def choose(item_id):
            if cfg.get(key) == item_id:
                return
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
            for control in (grid, equipped, remove):
                thread_safe_ui.refresh(control)
            _refresh_status(status)

        remove = ft.TextButton("Remove", icon=ft.Icons.CLOSE_ROUNDED,
                               on_click=lambda e: choose(None), disabled=True,
                               tooltip="Remove the equipped item")

        equipped.tooltip = _cosmetic_visibility_note()
        beta_badge = ft.Container(
            content=ft.Text("BETA", size=9, color=ACCENT, weight=ft.FontWeight.W_800),
            bgcolor=ACCENT_TINT, border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=8, vertical=4),
            data="cosmetic-beta-" + slot)
        controls = [ft.Row([ft.Container(content=equipped, expand=True),
                            beta_badge, remove], spacing=8)]
        if slot == "back":
            build_filters()
            controls.append(filter_row)
        controls.extend([grid, status])
        if slot == "back":
            equipped.tooltip += "\nSmall wings move gently. Press N in Minecraft for a Giant-wing flare; K → Cosmetic motion turns movement off."
        elif slot == "trail":
            equipped.tooltip += "\nA few short-lived particles while walking. Cosmetic motion turns them off; Minecraft's particle limit still applies."
        pane = ft.Column(controls, spacing=8)
        pane.load_items = refresh
        return pane

    # Keep the extra cosmetic categories hidden for now.
    cosmetic_panes = [(slot, cosmetics.SLOT_LABELS[slot],
                      ft.Container(content=ft.Column([
                          ft.Text("Coming soon", size=20, weight=ft.FontWeight.W_600, color=TEXT),
                          ft.Text("Auras are not available yet.", size=13, color=TEXT_DIM),
                      ], spacing=8), padding=24, data="cosmetic-coming-soon-aura")
                      if slot == "aura" else _cosmetic_pane(slot))
                     for slot in ("shoulder", "back", "aura")]

    # --- Tab state + switching --------------------------------------------
    # active_pane is a plain dict ref (same pattern the Mods tab uses for
    # active_content) so closures mutate without rebinding.
    active_pane = {"id": "skin"}

    PANES = [
        ("skin", "Skin", skin_pane),
        ("cape", "Cape", cape_pane),
        *cosmetic_panes,
    ]
    pane_holder = ft.Container(content=skin_pane)
    tab_row = ft.Row(spacing=12, wrap=True, run_spacing=8)

    def build_pane_tabs():
        tab_row.controls.clear()
        for pid, label, _ in PANES:
            tab_row.controls.append(
                text_tab(label,
                         selected=active_pane["id"] == pid,
                         on_click=lambda e, p=pid: switch_pane(p)))

    def switch_pane(pid):
        ft.context.disable_auto_update()
        if active_pane["id"] == pid:
            return
        active_pane["id"] = pid
        pane_holder.content = dict(
            (p[0], p[2]) for p in PANES)[pid]
        load_items = getattr(pane_holder.content, "load_items", None)
        if callable(load_items):
            load_items()
        build_pane_tabs()
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
        thread_safe_ui.refresh(tab_row)
        thread_safe_ui.refresh(pane_holder)
        _flush_pending_thumbs()

    build_pane_tabs()

    layout_size = {"compact": True}

    def _preview_resized(event):
        ft.context.disable_auto_update()
        width = event.width
        if width and math.isfinite(width) and width > 0:
            appearance.resize(min(width, 176 if layout_size["compact"] else 320))

    # The preview's own size notifications must honor the compact height too.
    appearance.viewport.on_size_change = _preview_resized

    def _layout_resized(event):
        ft.context.disable_auto_update()
        # Compact preview leaves room to reach the items in a short window.
        # Only geometry changes; the existing model/image and camera stay live.
        width = event.width
        if width and math.isfinite(width) and width > 0:
            layout_size["compact"] = width < 760
            preview_width = min(176, width) if width < 760 else min(320, (width - 16) / 3)
            appearance.resize(preview_width)

    layout = ft.ResponsiveRow([
        ft.Container(content=appearance.control, col={"xs": 12, "md": 4}),
        ft.Container(content=pane_holder,
                     bgcolor=CARD_FILL, border=ft.border.Border.all(1, CARD_BORDER),
                     border_radius=RADIUS, padding=12,
                     col={"xs": 12, "md": 8}, data="cosmetics-picker"),
    ], breakpoints={"xs": 0, "md": 760}, spacing=16, run_spacing=16,
       on_size_change=_layout_resized, data="cosmetics-layout")
    skin_section = ft.Column([
        ft.Text(i18n.t("Cosmetics"), size=24, color=TEXT,
                font_family=FONT_DISPLAY,
                tooltip="Choose a category, then click an item to equip it. Drag the preview to rotate."),
        tab_row,
        layout,
    ], spacing=12)

    appearance.refresh()
    return skin_section
