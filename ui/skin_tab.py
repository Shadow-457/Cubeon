"""
Cubeon - Skin section.
Lets the user upload and manage a local custom in-game skin. Previously its
own "Skin" sidebar tab; now embedded as a section inside the Profile dialog
(main.py's "Signed in as" click target), alongside the launcher-only
profile picture and the username field.

It lets the user upload a real skin PNG, stores it locally, renders a
preview from its actual pixels, and applies it in-game if a local-skin
mod (CustomSkinLoader) is installed for the current profile.
"""

# Standard library imports
import base64
import os
import threading

# Flet imports - Flet is a UI framework for Python (like Flutter)
import flet as ft

from cubeon.theme import (
    RADIUS,        # blocky corner radius (design system single source)
    attach_hover,  # hover-state helper for hand-built Container "buttons"
    ACCENT_TINT, ACCENT_TINT_HI,  # selected/hover washes for tiles/cards
    text_tab,      # underline-style segment tab (same chrome as Mods' content types)
    CARD_FILL, CARD_BORDER,  # translucent panel fills/outlines (Mods-tab language)
    ROW_HOVER,     # quiet hover lift for borderless rows/cards
)
from cubeon import thread_safe_ui  # control-level refresh() (thread-safe)

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
                        cape_file_picker=None):
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

    # Preview image for whichever custom skin is selected/just uploaded.
    # src is set to a transparent 1x1 placeholder up front (not left empty)
    # since some Flet versions require Image.src to always be a real string.
    custom_preview = ft.Image(
        src="icon.svg",
        width=160, height=260, fit=ft.BoxFit.CONTAIN, visible=False,
    )

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
    skins_list_col = ft.Row(spacing=10, wrap=True, run_spacing=10)

    _preview_state = {"running": False, "queued": None}

    def _render_big_preview(filename: str):
        """The actual PIL work - worker-thread only."""
        out_path = (os.path.join(core.SKINS_DIR, f"_preview_{filename}.png")
                    if filename else
                    os.path.join(core.SKINS_DIR, "_preview_default.png"))
        try:
            if not filename:
                return
            core.render_local_skin_preview(filename, out_path, scale=8)
            # ft.Image.src resolves relative strings against assets_dir and
            # can otherwise only load actual URLs - SKINS_DIR lives under the
            # user's home folder (~/.cubeon_launcher), nowhere near the app's
            # assets/ folder, so pointing src at that absolute path just
            # fails to load (this was tried and didn't work). src_base64 is
            # the correct way to show bytes that aren't a bundled asset.
            # This Flet version (0.86) has no separate src_base64 property -
            # ft.Image.src itself accepts a str, base64 str, or raw bytes.
            # Setting a nonexistent `src_base64` attribute was silently
            # swallowed by Flet (it's just a plain Python attr, not a real
            # control field), so the client never got the new image and kept
            # showing the last real `src` value (the placeholder cube icon).
            with open(out_path, "rb") as f:
                custom_preview.src = base64.b64encode(f.read()).decode("ascii")
            custom_preview.visible = True
        except Exception as ex:
            upload_status.value = f"Couldn't render preview: {ex}"
            thread_safe_ui.refresh(upload_status)
        finally:
            _preview_state["running"] = False
            nxt = _preview_state["queued"]
            _preview_state["queued"] = None
            if nxt is not None:
                render_preview_for(nxt)

    def render_preview_for(filename: str):
        # The 8x body composite is hundreds of ms of PIL work - too heavy for
        # the UI thread every time the Profile tab opens or a Use click lands.
        # Single-flight: at most one render runs; a newer request while one is
        # in flight replaces the queued one (the newest intent wins), and the
        # finally block re-runs it when the current render finishes.
        if _preview_state["running"]:
            _preview_state["queued"] = filename
            return
        _preview_state["running"] = True
        threading.Thread(target=_render_big_preview, args=(filename,),
                         daemon=True, name="ux-skin-preview").start()

    def set_active(filename: str):
        try:
            core.set_active_skin(cfg, filename)
        except Exception as ex:
            upload_status.value = f"Couldn't switch skin: {ex}"
            thread_safe_ui.refresh(upload_status)
            return
        render_preview_for(filename)
        upload_status.value = "Active skin set to this one."
        refresh_skins_list()
        page.update()

    def delete_skin(filename: str):
        # Unguarded, a missing file or corrupt skins.json escaped the click
        # handler - Flet swallows handler exceptions, so the card just sat
        # there "undeletable" with no feedback. Surface it instead.
        try:
            if cfg.get("active_skin") == filename:
                core.set_active_skin(cfg, None)
                custom_preview.visible = False
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
                    src=None, lazy_thumb=None, preview_w=64, preview_h=92):
        """A selectable installed item: preview on top, name below, hover
        actions at the bottom. The active card swaps the Use button for an
        outlined ACTIVE pill and gets the accent border.

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
                ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED, color=TEXT_DIM, size=22)
        preview_stack = [c for c in (preview_img, placeholder) if c is not None]
        actions = [
            ft.Container(
                content=ft.Text("ACTIVE", size=9.5, color=ACCENT,
                                weight=ft.FontWeight.W_700,
                                style=ft.TextStyle(letter_spacing=0.8)),
                border=ft.border.Border.all(1, ACCENT), border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=9, vertical=5),
            )
            if active else
            ft.Container(
                content=ft.Text("Use", size=11, color=ACCENT,
                                weight=ft.FontWeight.W_700),
                bgcolor=ACCENT_TINT, border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=12, vertical=5),
                ink=False, on_click=on_use,
            ),
        ]
        if on_delete is not None:
            actions.append(ft.Container(
                content=ft.Icon(ft.Icons.DELETE_OUTLINE_ROUNDED, color=DANGER, size=16),
                width=30, height=28, bgcolor=CARD_FILL,
                border=ft.border.Border.all(1, CARD_BORDER), border_radius=RADIUS,
                alignment=ft.Alignment.CENTER, ink=False, on_click=on_delete,
                tooltip="Delete",
            ))
        footer = ft.Row(actions, spacing=6,
                        alignment=ft.MainAxisAlignment.CENTER)
        card = ft.Container(
            content=ft.Column(
                [
                    ft.Container(
                        content=ft.Row(preview_stack,
                                       alignment=ft.MainAxisAlignment.CENTER,
                                       spacing=0),
                        height=preview_h + 8, alignment=ft.Alignment.CENTER,
                    ),
                    ft.Text(label, size=12, color=ACCENT if active else TEXT,
                            weight=ft.FontWeight.W_700, font_family=FONT_MONO,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    (ft.Text(sublabel, size=10, color=TEXT_DIM)
                     if sublabel else ft.Container()),
                    ft.Container(height=4),
                    footer,
                ],
                spacing=3, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            width=138,
            bgcolor=ACCENT_TINT if active else CARD_FILL,
            border=ft.border.Border.all(1, ACCENT if active else CARD_BORDER),
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=10, vertical=12),
        )
        return attach_hover(card,
                            ACCENT_TINT if active else CARD_FILL,
                            ACCENT_TINT_HI if active else ROW_HOVER)

    def _grid_scroll(grid, height=290):
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
        folder = core.SKINS_DIR if kind == "skin" else core.CAPES_DIR
        out = os.path.join(folder, f"_thumb_{filename}.png")
        src = os.path.join(folder, filename)
        try:
            # The preview is a pure function of the sheet, so an up-to-date
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
                img.src = b64
                img.visible = True
                thread_safe_ui.refresh(img)
                if ph is not None:
                    ph.visible = False
                    thread_safe_ui.refresh(ph)

        threading.Thread(target=_worker, daemon=True,
                         name="ux-thumb-render").start()

    def _skin_card_b64(filename):
        # Synchronous path kept for callers that truly need the bytes now;
        # the grid itself uses lazy_thumb instead so it never waits on PIL.
        return _render_thumb("skin", filename)

    def _cape_card_b64(filename):
        return _render_thumb("cape", filename)


    def refresh_skins_list():
        skins = core.list_custom_skins()
        skins_list_col.controls.clear()
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
            ))
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
                entry = core.add_custom_skin(picked.path, display_name)
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
        padding=ft.padding.Padding.symmetric(vertical=12, horizontal=18),
        alignment=ft.Alignment.CENTER,
        ink=False,
        on_click=open_picker,
    ), None, SURFACE_HI)

    refresh_skins_list()
    if cfg.get("active_skin"):
        render_preview_for(cfg.get("active_skin"))

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

    cape_preview = ft.Image(
        src="icon.svg",
        width=120, height=192, fit=ft.BoxFit.CONTAIN, visible=False,
    )
    cape_status = ft.Text("", size=12, color=TEXT_DIM)
    # Wrapping card grid, same as the skins installed list (see _owned_card).
    capes_list_col = ft.Row(spacing=10, wrap=True, run_spacing=10)

    _cape_preview_state = {"running": False, "queued": None}

    def _render_big_cape_preview(filename: str):
        out_path = os.path.join(core.CAPES_DIR, f"_preview_{filename}.png")
        try:
            core.render_cape_preview(filename, out_path, scale=10)
            with open(out_path, "rb") as f:
                cape_preview.src = base64.b64encode(f.read()).decode("ascii")
            cape_preview.visible = True
        except Exception as ex:
            cape_status.value = f"Couldn't render preview: {ex}"
            thread_safe_ui.refresh(cape_status)
        finally:
            _cape_preview_state["running"] = False
            nxt = _cape_preview_state["queued"]
            _cape_preview_state["queued"] = None
            if nxt is not None:
                render_cape_preview_for(nxt)

    def render_cape_preview_for(filename: str):
        # Same single-flight worker-thread shape as the skin preview: the
        # 10x face composite never runs on the UI thread.
        if _cape_preview_state["running"]:
            _cape_preview_state["queued"] = filename
            return
        _cape_preview_state["running"] = True
        threading.Thread(target=_render_big_cape_preview, args=(filename,),
                         daemon=True, name="ux-cape-preview").start()

    def show_default_cape_preview():
        # No custom cape selected == wearing the shared Cubeon cape, which the
        # Worker serves to everyone. Show its bundled preview asset (resolved
        # against assets_dir) so the box is never blank and the default reads
        # as a real, selected choice.
        cape_preview.src = DEFAULT_CAPE_PREVIEW_SRC
        cape_preview.visible = True

    def set_active_cape(filename):
        try:
            core.set_active_cape(cfg, filename)
        except Exception as ex:
            cape_status.value = f"Couldn't switch cape: {ex}"
            thread_safe_ui.refresh(cape_status)
            return
        if filename:
            render_cape_preview_for(filename)
            cape_status.value = "Active cape set to this one."
        else:
            show_default_cape_preview()
            cape_status.value = "Using the default Cubeon cape."
        refresh_capes_list()
        page.update()

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

    def refresh_capes_list():
        capes = core.list_custom_capes()
        capes_list_col.controls.clear()

        # The built-in Cubeon cape leads the grid as a real, selectable card.
        # It's ACTIVE whenever no custom cape is set (that's what the Worker
        # serves to everyone); picking it just clears the custom cape via
        # set_active_cape(None). No delete - it's the shipped default.
        default_active = not cfg.get("active_cape")
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
        padding=ft.padding.Padding.symmetric(vertical=12, horizontal=18),
        alignment=ft.Alignment.CENTER,
        ink=False,
        on_click=open_cape_picker,
    ), None, SURFACE_HI)

    refresh_capes_list()
    if cfg.get("active_cape"):
        render_cape_preview_for(cfg["active_cape"])
    else:
        # No custom cape == the shared Cubeon cape is what's worn, so seed the
        # preview with it rather than leaving the box hidden on first paint.
        show_default_cape_preview()

    # --- Build the skin section layout. ---
    #
    # Organization: one underline-tab bar (Skin / Cape - the same
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

    skin_preview_box = ft.Container(
        content=ft.Column(
            [custom_preview],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=CARD_FILL, border=ft.border.Border.all(1, CARD_BORDER),
        border_radius=RADIUS, padding=12,
        width=180, height=290, alignment=ft.Alignment.CENTER,
    )

    cape_preview_box = ft.Container(
        content=ft.Column(
            [cape_preview],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=CARD_FILL, border=ft.border.Border.all(1, CARD_BORDER),
        border_radius=RADIUS, padding=12,
        width=150, height=232, alignment=ft.Alignment.CENTER,
    )

    # The hats/capes notes are tooltips on their pane labels rather than
    # visible paragraphs - same detail, none of the wall of text.

    def _cape_label_with_note():
        label = section_label("Your Capes")
        label.tooltip = ("Your custom cape replaces the shared Cubeon cape "
                         "in-game; friends still see the shared one on you "
                         "for now.")
        return label

    skin_pane = ft.Row(
        [
            skin_preview_box,
            ft.Container(width=16),
            ft.Column(
                [skins_label, _grid_scroll(skins_list_col),
                 ft.Container(height=2), upload_button, upload_status],
                spacing=6, expand=True,
            ),
        ],
        vertical_alignment=ft.CrossAxisAlignment.START,
    )

    cape_pane = ft.Row(
        [
            cape_preview_box,
            ft.Container(width=16),
            ft.Column(
                [_cape_label_with_note(), _grid_scroll(capes_list_col),
                 ft.Container(height=2), cape_upload_button, cape_status],
                spacing=6, expand=True,
            ),
        ],
        vertical_alignment=ft.CrossAxisAlignment.START,
    )

    # --- Tab state + switching --------------------------------------------
    # active_pane is a plain dict ref (same pattern the Mods tab uses for
    # active_content) so closures mutate without rebinding.
    active_pane = {"id": "skin"}

    PANES = [
        ("skin", "Skin", skin_pane),
        ("cape", "Cape", cape_pane),
    ]

    pane_holder = ft.Container(content=skin_pane)
    tab_row = ft.Row(spacing=18)

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
        build_pane_tabs()
        page.update()

    build_pane_tabs()

    skin_section = ft.Column(
        [
            tab_row,
            ft.Container(height=10),
            pane_holder,
        ],
        spacing=6,
    )

    return skin_section
