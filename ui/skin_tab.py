"""Cosmetics: shared native 3D preview and local Skin / Cape / Shoulder / Back
libraries.

Uploads are stored locally and applied in-game when the corresponding
skin/cape mod is installed for the current profile. Shoulder and back items
are original Cubeon art drawn by the Cubeon Client itself (see
cubeon/cosmetics.py). Screenshots live in Settings.
"""

# Standard library imports
import base64
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
    SURFACE_MAX, TEXT_FAINT,
)
from cubeon import thread_safe_ui  # control-level refresh() (thread-safe)
from cubeon import cosmetics
from ui.appearance_preview import AppearancePreview

# Our own launcher core module - contains logic for skin storage/rendering
import launcher_core as core

# The bundled preview of the shared Cubeon cape (the one the Worker serves to
# every player - see worker/cubeon-skins.js). This is a relative asset path,
# which ft.Image.src resolves against the app's assets_dir, so it shows up
# whenever no custom cape is selected instead of leaving the box blank.
DEFAULT_CAPE_PREVIEW_SRC = "capes/cubeon_cape_preview.png"


# Preview bytes are immutable once written, so base64-encoding them once and
# keeping the string in memory spares every grid rebuild a disk read + encode.
def build_skin_section(page: ft.Page, cfg: dict, *, section_label, pixel_divider,
                        BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                        TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO=None,
                        mc_version=None, mc_loader=None, file_picker=None,
                        cape_file_picker=None, assets_dir=None):
    """
    Builds the skin-management section shown inside the Profile tab:
    a preview of the active skin, an upload button, and the list of
    previously uploaded skins to switch between or delete.

    This is a plain content block (no title/scroll wrapper of its own) -
    main.py's Profile tab supplies the surrounding layout, so this
    fits into a narrower, stacked (not side-by-side) column.

    Args:
        page: The Flet page instance - needed to trigger page.update() from callbacks.
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
            main.py and passed in here. This section rebuilds every time the
            Profile tab is opened (to reflect the current version/loader),
            so it must NOT construct+register its own FilePicker each call -
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
    skin_preview_name = ft.Text("Default Minecraft skin", size=13, color=TEXT)
    skin_preview_meta = ft.Text("Not wearing a custom skin", size=10, color=TEXT_DIM)

    upload_status = ft.Text("", size=12, color=TEXT_DIM)
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

    # The visibility explanation rides on the "Your Skins" section label as a
    # tooltip instead of an always-on paragraph - the profile page should read
    # at a glance and the detail is one hover away.
    skins_label = section_label("Your Skins")
    skins_label.tooltip = skin_visibility_note()

    # Installed items render as a wrapping card grid (see _owned_card below),
    # wrapped in a fixed-height scroll region so it never becomes an endless
    # scroll.
    skins_list_col = ft.Row(spacing=12, wrap=True, run_spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.START)
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
            thread_safe_ui.refresh(upload_status)
            return
        render_preview_for(filename)
        if filename is None:
            # Clearing the skin is the "None" card: offline Minecraft falls
            # back to its own default model (Steve or Alex), which is exactly
            # what the preview now shows.
            skin_preview_name.value = "Default Minecraft skin"
            skin_preview_meta.value = "Not wearing a custom skin"
            upload_status.value = "Showing the default Minecraft skin (Steve or Alex)."
        else:
            entry = next((s for s in core.list_custom_skins()
                          if s.get("filename") == filename), None)
            skin_preview_name.value = (entry or {}).get("name") or "Custom skin"
            skin_preview_meta.value = "Active · local preview"
            upload_status.value = "Active skin set to this one."
        thread_safe_ui.refresh(skin_preview_name)
        thread_safe_ui.refresh(skin_preview_meta)
        sync_skin_selection()
        thread_safe_ui.refresh(skins_list_col)
        thread_safe_ui.refresh(upload_status)

    def delete_skin(filename: str):
        # Unguarded, a missing file or corrupt skins.json escaped the click
        # handler - Flet swallows handler exceptions, so the card just sat
        # there "undeletable" with no feedback. Surface it instead.
        try:
            if cfg.get("active_skin") == filename:
                core.set_active_skin(cfg, None)
                render_preview_for(None)
            core.delete_custom_skin(filename)
            core.forget_file("skin", filename)
        except Exception as ex:
            upload_status.value = f"Couldn't delete: {ex}"
            thread_safe_ui.refresh(upload_status)
            return
        _THUMB_MEMO.pop(("skin", filename), None)
        refresh_skins_list()
        page.update()

    # --- Installed cards -------------------------------------------------
    # Installed items use one wrapping card grid language for both panes, and
    # language, and the pane wraps the grid in a fixed-height scroll region
    # (see _grid_scroll below) instead of paging. Each card shows a real
    # preview; the active item is highlighted, and hover reveals Use/Delete.
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
            preview_img = ft.Image(src=src, width=preview_w, height=preview_h,
                                   fit=ft.BoxFit.CONTAIN)
            placeholder = None
        elif lazy_thumb:
            # Visible only once the worker thread lands real bytes. The
            # placeholder keeps the card's height stable meanwhile, so the
            # grid doesn't reflow as thumbs pop in.
            preview_img = ft.Image(src="icon.svg", width=preview_w,
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
        state_label = ft.Text("", size=10, weight=ft.FontWeight.W_600,
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
            with thread_safe_ui.TREE_LOCK:
                if not selected["value"]:
                    on_use(e)

        primary = ft.Container(
            content=ft.Column([artwork, name,
                ft.Text(sublabel, size=10, color=TEXT_DIM,
                        text_align=ft.TextAlign.CENTER) if sublabel else ft.Container(),
                state_label], spacing=5, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
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
            width=144,
            bgcolor=ACCENT_TINT if active else CARD_FILL,
            border=ft.border.Border.all(1, ACCENT if active else CARD_BORDER),
            border_radius=RADIUS,
            padding=4,
        )

        def set_selected(value):
            selected["value"] = bool(value)
            check.visible = bool(value)
            name.color = ACCENT if value else TEXT
            state_label.value = "Equipped" if value else "Click to apply"
            state_label.color = ACCENT if value else TEXT_DIM
            card.bgcolor = ACCENT_TINT if value else CARD_FILL
            card.border = ft.border.Border.all(1, ACCENT if value else CARD_BORDER)
            attach_hover(card, card.bgcolor, ACCENT_TINT_HI if value else ROW_HOVER)

        card.set_selected = set_selected
        set_selected(active)
        return card

    def _grid_scroll(grid, height=350):
        """Fixed-height scroll region that keeps a wrapping card grid from
        stretching the tab to the length of the list."""
        return ft.Container(
            content=ft.Column([grid], scroll=ft.ScrollMode.AUTO),
            height=height,
        )

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
        out = os.path.join(folder, f"_thumb_{variant}{filename}.png")
        src = os.path.join(folder, filename)
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
        thread_safe_ui.refresh(upload_status)
        thread_safe_ui.refresh(skins_list_col)

    def sync_skin_selection():
        with thread_safe_ui.TREE_LOCK:
            for filename, card in skin_cards.items():
                card.set_selected(cfg.get("active_skin") == filename)

    def refresh_skins_list():
        skins = core.list_custom_skins()
        skin_cards.clear()
        skins_list_col.controls.clear()
        # "None" is a real choice, not a missing feature: it clears the custom
        # skin so offline Minecraft shows its own default model (Steve/Alex).
        skins_list_col.controls.append(_owned_card(
            icon=ft.Icons.BLOCK_ROUNDED,
            label="None",
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
        thread_safe_ui.refresh(upload_status)
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
            thread_safe_ui.refresh(upload_status)
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

    # Full-width outlined "+ Upload skin" CTA that sits at the BOTTOM of the
    # skins list (matching the target layout). Kept as a subtle outlined
    # button rather than the solid ACCENT hero so it reads as "add another"
    # beneath the list instead of competing with it. No fixed width - it
    # stretches to fill the column beside the preview box.
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
        padding=ft.padding.Padding.symmetric(vertical=12, horizontal=16),
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
        skin_preview_meta.value = "Active · local preview"

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
                                color=TEXT, weight=ft.FontWeight.W_700,
                                text_align=ft.TextAlign.CENTER)
    cape_preview_meta = ft.Text("Default · shared with friends", size=10,
                                color=TEXT_DIM, text_align=ft.TextAlign.CENTER)
    cape_status = ft.Text("", size=12, color=TEXT_DIM)
    # Wrapping card grid, same as the skins installed list (see _owned_card).
    capes_list_col = ft.Row(spacing=12, wrap=True, run_spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.START)
    cape_cards = {}

    def render_cape_preview_for(filename):
        appearance.refresh(invalidate=True)

    def show_default_cape_preview():
        appearance.refresh(invalidate=True)

    def set_active_cape(filename):
        if cfg.get("active_cape") == filename and not cfg.get("hide_cubeon_cape"):
            return
        try:
            core.set_active_cape(cfg, filename)
        except Exception as ex:
            cape_status.value = f"Couldn't switch cape: {ex}"
            thread_safe_ui.refresh(cape_status)
            return
        if filename:
            render_cape_preview_for(filename)
            entry = next((c for c in core.list_custom_capes()
                          if c.get("filename") == filename), None)
            cape_preview_name.value = (entry or {}).get("name") or "Custom cape"
            cape_preview_meta.value = "Active · local preview"
            cape_status.value = "Active cape set to this one."
        else:
            show_default_cape_preview()
            cape_preview_name.value = "Cubeon Cape"
            cape_preview_meta.value = "Default · shared with friends"
            cape_status.value = "Using the default Cubeon cape."
        thread_safe_ui.refresh(cape_preview_name)
        thread_safe_ui.refresh(cape_preview_meta)
        sync_cape_selection()
        thread_safe_ui.refresh(capes_list_col)
        thread_safe_ui.refresh(cape_status)

    def hide_cape():
        """The Cape pane's None card: no cape on this player's screen."""
        try:
            core.set_hide_cubeon_cape(cfg, True)
        except Exception as ex:
            cape_status.value = f"Couldn't hide the cape: {ex}"
            thread_safe_ui.refresh(cape_status)
            return
        appearance.refresh(invalidate=True)
        cape_preview_name.value = "No cape"
        cape_preview_meta.value = "Hidden on your screen"
        # Be honest: the shared cape is assigned server-side, so this hides it
        # locally rather than telling friends you have no cape.
        cape_status.value = ("Cape hidden on your screen. Friends still see "
                             "your shared Cubeon cape.")
        thread_safe_ui.refresh(cape_preview_name)
        thread_safe_ui.refresh(cape_preview_meta)
        sync_cape_selection()
        thread_safe_ui.refresh(capes_list_col)

    def delete_cape(filename):
        # Same guarded shape as delete_skin: silent handler exceptions made
        # a failed delete look like a dead button.
        try:
            if cfg.get("active_cape") == filename:
                core.set_active_cape(cfg, None)
                show_default_cape_preview()
            core.delete_custom_cape(filename)
            core.forget_file("cape", filename)
        except Exception as ex:
            cape_status.value = f"Couldn't delete: {ex}"
            thread_safe_ui.refresh(cape_status)
            return
        _THUMB_MEMO.pop(("cape", filename), None)
        refresh_capes_list()
        page.update()

    def sync_cape_selection():
        with thread_safe_ui.TREE_LOCK:
            hidden = bool(cfg.get("hide_cubeon_cape"))
            for filename, card in cape_cards.items():
                selected = hidden if filename == "__hidden__" else (
                    not hidden and cfg.get("active_cape") == filename)
                card.set_selected(selected)

    def refresh_capes_list():
        capes = core.list_custom_capes()
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
                sublabel="",
                active=is_active,
                on_use=lambda e, fn=c["filename"]: set_active_cape(fn),
                on_delete=lambda e, fn=c["filename"]: delete_cape(fn),
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
        _flush_pending_thumbs()

    def handle_cape_files(files):
        if not files:
            return
        picked = files[0]
        # Threaded for the same reason as handle_skin_files; also replaces
        # the bare page.update() (unsafe from a worker thread) with
        # control-level thread_safe_ui refreshes.
        cape_upload_button.disabled = True
        cape_status.value = "Uploading..."
        thread_safe_ui.refresh(cape_status)
        thread_safe_ui.refresh(cape_upload_button)

        def _work():
            try:
                display_name = os.path.splitext(picked.name)[0]
                entry = core.add_custom_cape(picked.path, display_name)
                set_active_cape(entry["filename"])
                msg = f"Uploaded and set '{entry['name']}' as active cape."
            except ValueError as ve:
                msg = str(ve)
            except Exception as ex:
                msg = f"Upload failed: {ex}"
            cape_status.value = msg
            cape_upload_button.disabled = False
            thread_safe_ui.refresh(cape_status)
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
            dialog_title="Choose a cape image",
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
        padding=ft.padding.Padding.symmetric(vertical=12, horizontal=16),
        alignment=ft.Alignment.CENTER,
        ink=False,
        on_click=open_cape_picker,
    ), None, SURFACE_HI)

    refresh_capes_list()
    if cfg.get("active_cape"):
        _active_cape = cfg["active_cape"]
        render_cape_preview_for(_active_cape)
        _active_cape_entry = next(
            (c for c in core.list_custom_capes()
             if c.get("filename") == _active_cape), None)
        cape_preview_name.value = (_active_cape_entry or {}).get("name") or "Custom cape"
        cape_preview_meta.value = "Active · local preview"
    else:
        # No custom cape == the shared Cubeon cape is what's worn, so seed the
        # preview with it rather than leaving the box hidden on first paint -
        # unless the user chose None, which hides it locally.
        if cfg.get("hide_cubeon_cape"):
            appearance.refresh(invalidate=True)
            cape_preview_name.value = "No cape"
            cape_preview_meta.value = "Hidden on your screen"
        else:
            show_default_cape_preview()

    # --- Build the skin section layout. ---
    #
    # Organization: one underline-tab bar (Skin / Cape / Images - the same
    # text_tab chrome the Mods tab uses for Mods/Packs/Shaders, so the
    # launcher speaks one visual language) with ONE pane visible at a time.
    # Previously all three sections stacked into a very long scroll: the
    # cape block's empty list + the hat grid's whitespace meant the actual
    # controls (upload buttons, list rows) lived far apart. Tabs collapse
    # that to "what am I here to change" up front.
    #
    # The panes share the two-column shape the old skin block established:
    # fixed-width preview on the left, the actionable content on the right,
    # so each pane reads the same way.

    # The hats/capes notes are tooltips on their pane labels rather than
    # visible paragraphs - same detail, none of the wall of text.

    def _cape_label_with_note():
        label = section_label("Your Capes")
        label.tooltip = ("Your custom cape replaces the shared Cubeon cape "
                         "in-game; friends still see the shared one on you "
                         "for now.")
        return label

    skin_pane = ft.Column(
        [ft.Row([ft.Container(content=skins_label, expand=True), upload_button]),
         _grid_scroll(skins_list_col), skin_preview_name,
         skin_preview_meta, upload_status], spacing=10)
    cape_pane = ft.Column(
        [ft.Row([ft.Container(content=_cape_label_with_note(), expand=True), cape_upload_button]),
         _grid_scroll(capes_list_col), cape_preview_name,
         cape_preview_meta, cape_status], spacing=10)

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

    def _cosmetic_pane(slot, title):
        grid = ft.Row(spacing=12, wrap=True, run_spacing=12,
                      vertical_alignment=ft.CrossAxisAlignment.START)
        status = ft.Text("", size=12, color=TEXT_DIM)
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
            sync_selection()

        def choose(item_id):
            if cfg.get(key) == item_id:
                return
            try:
                core.set_active_cosmetic(cfg, slot, item_id)
            except Exception as ex:
                status.value = f"Couldn't change this cosmetic: {ex}"
                thread_safe_ui.refresh(status)
                return
            with thread_safe_ui.TREE_LOCK:
                appearance.refresh(invalidate=True)
                status.value = ""
                sync_selection()
            for control in (grid, equipped, remove, status):
                thread_safe_ui.refresh(control)

        remove = ft.TextButton("Remove", icon=ft.Icons.CLOSE_ROUNDED,
                               on_click=lambda e: choose(None), disabled=True,
                               tooltip="Remove the equipped item")

        label = section_label("Your " + title)
        label.tooltip = _cosmetic_visibility_note()
        heading = ft.Row([label, ft.Container(
            content=ft.Text("BETA", size=9, color=ACCENT, weight=ft.FontWeight.W_800),
            bgcolor=ACCENT_TINT, border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=8, vertical=4),
            data="cosmetic-beta-" + slot)], spacing=8)
        controls = [ft.Row([ft.Container(content=heading, expand=True), remove]),
                    equipped]
        if slot == "back":
            build_filters()
            controls.append(filter_row)
        controls.extend([_grid_scroll(grid), status])
        if slot == "back":
            controls.append(ft.Text("Small wings move gently. Press N in Minecraft for a Giant-wing flare; K → Cosmetic motion turns movement off.",
                                    size=11, color=TEXT_DIM))
        elif slot == "trail":
            controls.append(ft.Text("A few short-lived particles while walking. Cosmetic motion turns them off; Minecraft's particle limit still applies.",
                                    size=11, color=TEXT_DIM))
        pane = ft.Column(controls, spacing=8)
        pane.load_items = refresh
        return pane

    # Keep the extra cosmetic categories hidden for now.
    cosmetic_panes = [(slot, cosmetics.SLOT_LABELS[slot],
                      _cosmetic_pane(slot, cosmetics.SLOT_LABELS[slot]))
                     for slot in ("shoulder", "back")]

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

    skin_section = ft.Column(
        [
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text(i18n.t("Cosmetics"), size=24, color=TEXT,
                                    font_family=FONT_DISPLAY),
                            ft.Text("Click an item to equip it. Your preview updates automatically.",
                                    size=12, color=TEXT_DIM),
                        ], spacing=4, expand=True,
                    ),
                ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
            ),
            ft.Container(height=8),
            ft.ResponsiveRow([
                ft.Container(content=appearance.control, col={"xs": 12, "md": 5, "lg": 4}),
                ft.Container(content=ft.Column([tab_row, ft.Container(height=4), pane_holder], spacing=8),
                             bgcolor=CARD_FILL, border=ft.border.Border.all(1, CARD_BORDER),
                             border_radius=RADIUS, padding=16,
                             col={"xs": 12, "md": 7, "lg": 8}, data="cosmetics-picker"),
            ], spacing=24, run_spacing=24),
        ],
        spacing=8,
    )

    appearance.refresh()
    return skin_section
