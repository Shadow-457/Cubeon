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

# Flet imports - Flet is a UI framework for Python (like Flutter)
import flet as ft

from cubeon.theme import (
    RADIUS,        # blocky corner radius (design system single source)
    attach_hover,  # hover-state helper for hand-built Container "buttons"
    ACCENT_HI,     # brighter green - hover fill on the ACCENT hero
    ACCENT_TINT, ACCENT_TINT_HI,  # selected/hover washes for hat tiles
    SURFACE_MAX,   # top-elevation surface - hover fill on selected hat tiles
    ON_ACCENT,     # explicit dark foreground on an ACCENT fill (same value as BG)
    text_tab,      # underline-style segment tab (same chrome as Mods' content types)
)
from cubeon import thread_safe_ui  # control-level refresh() (thread-safe)

# Our own launcher core module - contains logic for skin storage/rendering
import launcher_core as core

# The bundled preview of the shared Cubeon cape (the one the Worker serves to
# every player - see worker/cubeon-skins.js). This is a relative asset path,
# which ft.Image.src resolves against the app's assets_dir, so it shows up
# whenever no custom cape is selected instead of leaving the box blank.
DEFAULT_CAPE_PREVIEW_SRC = "capes/cubeon_cape_preview.png"


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
        return ("CustomSkinLoader gets installed automatically the next time "
                "you press Play, then your skin shows up in-game.")

    # The visibility explanation rides on the "Your Skins" section label as a
    # tooltip instead of an always-on paragraph - the profile page should read
    # at a glance and the detail is one hover away.
    skins_label = section_label("Your Skins")
    skins_label.tooltip = skin_visibility_note()

    skins_list_col = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    def render_preview_for(filename: str):
        # With a hat worn, preview exactly what the game will show: the
        # composed sheet (active skin or built-in default + hat), not the
        # raw uploaded file.
        out_path = (os.path.join(core.SKINS_DIR, f"_preview_{filename}.png")
                    if filename else
                    os.path.join(core.SKINS_DIR, "_preview_default.png"))
        try:
            if cfg.get("cosmetic_hat"):
                core.preview_composed_body(cfg, out_path, scale=8)
            elif filename:
                core.render_local_skin_preview(filename, out_path, scale=8)
            else:
                return
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

    def set_active(filename: str):
        core.set_active_skin(cfg, filename)
        render_preview_for(filename)
        upload_status.value = "Active skin set to this one."
        refresh_skins_list()
        refresh_hat_row()
        page.update()

    def delete_skin(filename: str):
        if cfg.get("active_skin") == filename:
            core.set_active_skin(cfg, None)
            # With a hat worn there's still a composed skin to show (hat on
            # the built-in default), so only hide the preview when bare.
            if not cfg.get("cosmetic_hat"):
                custom_preview.visible = False
            else:
                render_preview_for(filename)
        core.delete_custom_skin(filename)
        refresh_skins_list()
        refresh_hat_row()
        page.update()

    def refresh_skins_list():
        skins_list_col.controls.clear()
        skins = core.list_custom_skins()
        if not skins:
            skins_list_col.controls.append(
                ft.Text("No uploaded skins yet.", size=12, color=TEXT_DIM)
            )
        for s in skins:
            is_active = cfg.get("active_skin") == s["filename"]
            # Active rows show an outlined "ACTIVE" pill; inactive rows show a
            # "Use" button. The "..." menu carries the overflow actions
            # (Use / Delete), matching the target layout.
            trailing = (
                ft.Container(
                    content=ft.Text(
                        "ACTIVE", size=9.5, color=ACCENT, weight=ft.FontWeight.W_700,
                        style=ft.TextStyle(letter_spacing=0.8),
                    ),
                    border=ft.border.Border.all(1, ACCENT),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=10, vertical=5),
                )
                if is_active else
                attach_hover(ft.Container(
                    content=ft.Text("Use", size=11, color=TEXT, weight=ft.FontWeight.W_700),
                    bgcolor=SURFACE_HI,
                    border=ft.border.Border.all(1, BORDER),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=12, vertical=6),
                    ink=True,
                    on_click=lambda e, fn=s["filename"]: set_active(fn),
                ), SURFACE_HI, SURFACE)
            )

            skins_list_col.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            # Leading thumbnail-style icon chip
                            ft.Container(
                                content=ft.Icon(ft.Icons.CHECKROOM_ROUNDED, color=ACCENT, size=15),
                                width=30, height=30, bgcolor=SURFACE,
                                border_radius=RADIUS, alignment=ft.Alignment.CENTER,
                            ),
                            ft.Text(
                                s["name"] + (" (slim)" if s.get("slim") else ""),
                                size=12.5,
                                color=ACCENT if is_active else TEXT,
                                weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL,
                                font_family=FONT_MONO,
                                expand=True,
                            ),
                            trailing,
                            ft.PopupMenuButton(
                                icon=ft.Icons.MORE_HORIZ,
                                icon_color=TEXT_DIM,
                                bgcolor=SURFACE_HI,
                                tooltip="More",
                                items=[
                                    ft.PopupMenuItem(
                                        content=ft.Text("Use", color=TEXT, size=12.5),
                                        on_click=lambda e, fn=s["filename"]: set_active(fn),
                                    ),
                                    ft.PopupMenuItem(
                                        content=ft.Row(
                                            [
                                                ft.Icon(ft.Icons.DELETE_OUTLINE_ROUNDED, color=DANGER, size=16),
                                                ft.Text("Delete", color=DANGER, size=12.5),
                                            ],
                                            spacing=8, tight=True,
                                        ),
                                        on_click=lambda e, fn=s["filename"]: delete_skin(fn),
                                    ),
                                ],
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=SURFACE_HI,
                    border=ft.border.Border.all(1, BORDER),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
                )
            )

    def handle_skin_files(files):
        if not files:
            return
        picked = files[0]
        upload_status.value = "Uploading..."
        thread_safe_ui.refresh(upload_status)
        try:
            display_name = os.path.splitext(picked.name)[0]
            entry = core.add_custom_skin(picked.path, display_name)
            set_active(entry["filename"])
            upload_status.value = f"Uploaded and set '{entry['name']}' as active skin."
        except ValueError as ve:
            upload_status.value = str(ve)
        except Exception as ex:
            upload_status.value = f"Upload failed: {ex}"
        thread_safe_ui.refresh(upload_status)

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
        ink=True,
        on_click=open_picker,
    ), None, SURFACE_HI)

    refresh_skins_list()
    if cfg.get("active_skin") or cfg.get("cosmetic_hat"):
        render_preview_for(cfg.get("active_skin"))

    # =====================================================================
    # COSMETICS - hat picker. Hats are pixel art baked into the skin's
    # hat layer and flow to the game through the same CustomSkinLoader
    # sync as the skin itself - no extra mods, nothing new at launch.
    # =====================================================================

    hat_status = ft.Text("", size=12, color=TEXT_DIM)
    hat_row = ft.Row(spacing=10, wrap=True)

    def hat_name(hat_id):
        for h in core.list_hats():
            if h["id"] == hat_id:
                return h["name"]
        return hat_id

    def hat_earn_hint(hat_id):
        """One-line "how to earn this" for a locked hat, with live progress
        (e.g. '7.4 / 10 hours in game'). Returns '' for unlocked hats."""
        from cubeon import milestones
        req = core.hat_requirement(hat_id)
        if req is None or core.hat_unlocked(hat_id):
            return ""
        for m in milestones.MILESTONES:
            if m["id"] == req:
                cur, goal = milestones.progress(m)
                if m["kind"] == "hours_played":
                    return f"{cur:.1f} / {goal:.0f} hours in game"
                if m["kind"] == "friends":
                    return f"{int(cur)} / {int(goal)} friends ({m['desc']})"
                if m["kind"] == "hosted":
                    return f"{int(cur)} / {int(goal)} hosted ({m['desc']})"
                return m["desc"]
        return "Keep playing to earn this"

    def wear_hat(e, hat_id=None):
        try:
            core.set_hat(cfg, hat_id)
        except PermissionError:
            hat_status.value = f"Locked - {hat_earn_hint(hat_id)}"
            refresh_hat_row()
            page.update()
            return
        except Exception as ex:
            hat_status.value = f"Couldn't apply hat: {ex}"
            page.update()
            return
        hat_status.value = (f"Wearing {hat_name(hat_id)}." if hat_id else "Hat removed.")
        render_preview_for(cfg.get("active_skin"))
        refresh_hat_row()
        page.update()

    def refresh_hat_row():
        hat_row.controls.clear()
        worn = cfg.get("cosmetic_hat")

        def tile(label, hat_id, preview_src=None, locked=False):
            selected = (worn or None) == hat_id
            img = (ft.Image(src=preview_src, width=48, height=96, fit=ft.BoxFit.CONTAIN)
                   if preview_src else
                   ft.Container(width=48, height=96, alignment=ft.Alignment.CENTER,
                                content=ft.Icon(ft.Icons.NO_MEETING_ROOM_OUTLINED,
                                                color=TEXT_DIM, size=26)))
            if locked:
                # Dim the art and badge it - a locked hat must look locked,
                # not like a broken tile. The lock glyph overlaps the art.
                img = ft.Stack(
                    [img,
                     ft.Container(
                         content=ft.Icon(ft.Icons.LOCK_OUTLINED,
                                         color=TEXT_DIM, size=16),
                         bgcolor=SURFACE_MAX, border_radius=99,
                         padding=2, right=0, bottom=0)],
                    width=52, height=96)
            content = ft.Column(
                [
                    img,
                    ft.Text(label, size=11,
                            color=ACCENT if selected else TEXT_DIM,
                            weight=ft.FontWeight.W_600 if selected else ft.FontWeight.W_500,
                            text_align=ft.TextAlign.CENTER),
                ],
                spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER, tight=True,
            )
            # Locked tiles carry the earn hint as their tooltip so the
            # requirement is discoverable on hover without a click that
            # would just say "locked".
            container = ft.Container(
                content,
                bgcolor=ACCENT_TINT if selected else SURFACE_HI,
                border=ft.border.Border.all(1, ACCENT if selected else BORDER),
                border_radius=RADIUS,
                padding=10,
                ink=True,
                on_click=lambda e, h=hat_id: wear_hat(e, h),
            )
            if locked:
                container.tooltip = hat_earn_hint(hat_id) or "Locked"
                container.bgcolor = SURFACE_HI
                container.content.controls[1].color = TEXT_DIM
            return attach_hover(
                container,
                ACCENT_TINT if selected else SURFACE_HI,
                ACCENT_TINT_HI if selected else SURFACE_MAX,
            )

        hat_row.controls.append(tile("None", None))
        for h in core.list_hats():
            out_path = os.path.join(core.SKINS_DIR, f"_hat_{h['id']}.png")
            src = None
            try:
                core.render_hat_preview(h["id"], cfg, out_path, scale=6)
                with open(out_path, "rb") as f:
                    src = base64.b64encode(f.read()).decode("ascii")
            except Exception:
                pass  # tile falls back to the bare glyph; wearing still works
            locked = h.get("require") and not core.hat_unlocked(h["id"])
            hat_row.controls.append(tile(h["name"], h["id"], src,
                                         locked=bool(locked)))

        if worn:
            hat_status.value = f"Wearing {hat_name(worn)}."
        elif not hat_status.value:
            hat_status.value = ""

    refresh_hat_row()

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
    capes_list_col = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO)

    def render_cape_preview_for(filename: str):
        out_path = os.path.join(core.CAPES_DIR, f"_preview_{filename}.png")
        try:
            core.render_cape_preview(filename, out_path, scale=10)
            with open(out_path, "rb") as f:
                cape_preview.src = base64.b64encode(f.read()).decode("ascii")
            cape_preview.visible = True
        except Exception as ex:
            cape_status.value = f"Couldn't render preview: {ex}"

    def show_default_cape_preview():
        # No custom cape selected == wearing the shared Cubeon cape, which the
        # Worker serves to everyone. Show its bundled preview asset (resolved
        # against assets_dir) so the box is never blank and the default reads
        # as a real, selected choice.
        cape_preview.src = DEFAULT_CAPE_PREVIEW_SRC
        cape_preview.visible = True

    def set_active_cape(filename):
        core.set_active_cape(cfg, filename)
        if filename:
            render_cape_preview_for(filename)
            cape_status.value = "Active cape set to this one."
        else:
            show_default_cape_preview()
            cape_status.value = "Using the default Cubeon cape."
        refresh_capes_list()
        page.update()

    def delete_cape(filename):
        if cfg.get("active_cape") == filename:
            core.set_active_cape(cfg, None)
            show_default_cape_preview()
        core.delete_custom_cape(filename)
        refresh_capes_list()
        page.update()

    def refresh_capes_list():
        capes_list_col.controls.clear()

        # The built-in Cubeon cape always leads the list as a real, selectable
        # entry. It's ACTIVE whenever no custom cape is set (that's what the
        # Worker serves to everyone), and picking it just clears the custom
        # cape via set_active_cape(None). No "..." menu / delete - it's the
        # shipped default and can't be removed.
        default_active = not cfg.get("active_cape")
        default_trailing = (
            ft.Container(
                content=ft.Text(
                    "ACTIVE", size=9.5, color=ACCENT, weight=ft.FontWeight.W_700,
                    style=ft.TextStyle(letter_spacing=0.8),
                ),
                border=ft.border.Border.all(1, ACCENT),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=10, vertical=5),
            )
            if default_active else
            attach_hover(ft.Container(
                content=ft.Text("Use", size=11, color=TEXT, weight=ft.FontWeight.W_700),
                bgcolor=SURFACE_HI,
                border=ft.border.Border.all(1, BORDER),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=12, vertical=6),
                ink=True,
                on_click=lambda e: set_active_cape(None),
            ), SURFACE_HI, SURFACE)
        )
        capes_list_col.controls.append(
            ft.Container(
                content=ft.Row(
                    [
                        ft.Container(
                            content=ft.Image(
                                src=DEFAULT_CAPE_PREVIEW_SRC,
                                width=18, height=28, fit=ft.BoxFit.CONTAIN,
                            ),
                            width=30, height=30, bgcolor=SURFACE,
                            border_radius=RADIUS, alignment=ft.Alignment.CENTER,
                        ),
                        ft.Column(
                            [
                                ft.Text(
                                    "Cubeon Cape",
                                    size=12.5,
                                    color=ACCENT if default_active else TEXT,
                                    weight=ft.FontWeight.W_600 if default_active else ft.FontWeight.NORMAL,
                                    font_family=FONT_MONO,
                                ),
                                ft.Text(
                                    "Default - everyone sees this",
                                    size=10, color=TEXT_DIM,
                                ),
                            ],
                            spacing=1, tight=True, expand=True,
                        ),
                        default_trailing,
                    ],
                    spacing=10,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=SURFACE_HI,
                border=ft.border.Border.all(1, ACCENT if default_active else BORDER),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
            )
        )

        capes = core.list_custom_capes()
        if not capes:
            capes_list_col.controls.append(
                ft.Text("No uploaded capes yet.", size=12, color=TEXT_DIM)
            )
        for c in capes:
            is_active = cfg.get("active_cape") == c["filename"]
            trailing = (
                ft.Container(
                    content=ft.Text(
                        "ACTIVE", size=9.5, color=ACCENT, weight=ft.FontWeight.W_700,
                        style=ft.TextStyle(letter_spacing=0.8),
                    ),
                    border=ft.border.Border.all(1, ACCENT),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=10, vertical=5),
                )
                if is_active else
                attach_hover(ft.Container(
                    content=ft.Text("Use", size=11, color=TEXT, weight=ft.FontWeight.W_700),
                    bgcolor=SURFACE_HI,
                    border=ft.border.Border.all(1, BORDER),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=12, vertical=6),
                    ink=True,
                    on_click=lambda e, fn=c["filename"]: set_active_cape(fn),
                ), SURFACE_HI, SURFACE)
            )

            # The "..." menu carries Use (or Remove, when this cape is the
            # active one) plus Delete - matching the skin rows above.
            menu_items = [
                (ft.PopupMenuItem(
                    content=ft.Text("Remove", color=TEXT, size=12.5),
                    on_click=lambda e: set_active_cape(None),
                ) if is_active else
                 ft.PopupMenuItem(
                    content=ft.Text("Use", color=TEXT, size=12.5),
                    on_click=lambda e, fn=c["filename"]: set_active_cape(fn),
                )),
                ft.PopupMenuItem(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.DELETE_OUTLINE_ROUNDED, color=DANGER, size=16),
                            ft.Text("Delete", color=DANGER, size=12.5),
                        ],
                        spacing=8, tight=True,
                    ),
                    on_click=lambda e, fn=c["filename"]: delete_cape(fn),
                ),
            ]

            capes_list_col.controls.append(
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Container(
                                content=ft.Icon(ft.Icons.CHECKROOM_ROUNDED, color=ACCENT, size=15),
                                width=30, height=30, bgcolor=SURFACE,
                                border_radius=RADIUS, alignment=ft.Alignment.CENTER,
                            ),
                            ft.Text(
                                c["name"],
                                size=12.5,
                                color=ACCENT if is_active else TEXT,
                                weight=ft.FontWeight.W_600 if is_active else ft.FontWeight.NORMAL,
                                font_family=FONT_MONO,
                                expand=True,
                            ),
                            trailing,
                            ft.PopupMenuButton(
                                icon=ft.Icons.MORE_HORIZ,
                                icon_color=TEXT_DIM,
                                bgcolor=SURFACE_HI,
                                tooltip="More",
                                items=menu_items,
                            ),
                        ],
                        spacing=10,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    bgcolor=SURFACE_HI,
                    border=ft.border.Border.all(1, BORDER),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
                )
            )

    def handle_cape_files(files):
        if not files:
            return
        picked = files[0]
        cape_status.value = "Uploading..."
        page.update()
        try:
            display_name = os.path.splitext(picked.name)[0]
            entry = core.add_custom_cape(picked.path, display_name)
            set_active_cape(entry["filename"])
            cape_status.value = f"Uploaded and set '{entry['name']}' as active cape."
        except ValueError as ve:
            cape_status.value = str(ve)
        except Exception as ex:
            cape_status.value = f"Upload failed: {ex}"
        page.update()

    def on_cape_files_picked(e):
        # Untyped for the same version-spanning reason as on_files_picked.
        handle_cape_files(e.files)

    cape_file_picker.on_result = on_cape_files_picked

    def open_cape_picker(e=None):
        core.run_file_picker(
            page, cape_file_picker,
            on_files=handle_cape_files,
            dialog_title="Choose a cape PNG (64x32)",
            allow_multiple=False,
            allowed_extensions=["png"],
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
        ink=True,
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
    # Organization: one underline-tab bar (Skin / Cosmetics / Cape - the same
    # text_tab chrome the Mods tab uses for Mods/Packs/Shaders, so the
    # launcher speaks one visual language) with ONE pane visible at a time.
    # Previously all three sections stacked into a very long scroll: the
    # cape block's empty list + the hat grid's whitespace meant the actual
    # controls (upload buttons, list rows) lived far apart. Tabs collapse
    # that to "what am I here to change" up front.
    #
    # The panes share the two-column shape the old skin block established:
    # fixed-width preview on the left, the actionable list + upload CTA on
    # the right, so each pane reads the same way.

    def _pane(preview_box, label_ctrl, list_col, upload_btn, status_txt,
              preview_width=180, preview_height=290):
        """One tab pane: [preview box] | [label + list + upload + status].
        Shared by Skin and Cape; Cosmetics builds its own wider layout."""
        return ft.Row(
            [
                preview_box,
                ft.Container(width=16),
                ft.Column(
                    [label_ctrl, list_col, ft.Container(height=2),
                     upload_btn, status_txt],
                    spacing=8,
                    expand=True,
                ),
            ],
            vertical_alignment=ft.CrossAxisAlignment.START,
        )

    skin_preview_box = ft.Container(
        content=ft.Column(
            [custom_preview],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=SURFACE, border=ft.border.Border.all(2, ACCENT_DIM),
        border_radius=RADIUS, padding=12,
        width=180, height=290, alignment=ft.Alignment.CENTER,
    )

    cape_preview_box = ft.Container(
        content=ft.Column(
            [cape_preview],
            horizontal_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=SURFACE, border=ft.border.Border.all(2, ACCENT_DIM),
        border_radius=RADIUS, padding=12,
        width=150, height=232, alignment=ft.Alignment.CENTER,
    )

    # The hats/capes notes are tooltips on their pane labels rather than
    # visible paragraphs - same detail, none of the wall of text.
    def _hat_label_with_note():
        label = section_label("Hat")
        label.tooltip = ("Only you see hats right now - like your skin. "
                         "Hats with a lock are earned by playing - hover one "
                         "to see how close you are.")
        return label

    def _cape_label_with_note():
        label = section_label("Your Capes")
        label.tooltip = ("Your custom cape replaces the shared Cubeon cape "
                         "in-game; friends still see the shared one on you "
                         "for now.")
        return label

    # --- The three panes -------------------------------------------------
    skin_pane = _pane(
        skin_preview_box, skins_label, skins_list_col,
        upload_button, upload_status)

    cape_pane = _pane(
        cape_preview_box, _cape_label_with_note(), capes_list_col,
        cape_upload_button, cape_status)

    # Cosmetics pane: the hat grid is the wide content here, so it gets the
    # full width; the status line sits right under the grid. A mini preview
    # of the current skin+hat combo would duplicate the Skin pane's preview,
    # which already composes the hat in - so the pane is just the grid.
    cosmetics_pane = ft.Column(
        [
            _hat_label_with_note(),
            ft.Container(height=8),
            hat_row,
            ft.Container(height=4),
            hat_status,
        ],
        spacing=6,
    )

    # --- Tab state + switching --------------------------------------------
    # active_pane is a plain dict ref (same pattern the Mods tab uses for
    # active_content) so closures mutate without rebinding.
    active_pane = {"id": "skin"}

    PANES = [
        ("skin", "Skin", skin_pane),
        ("cosmetics", "Cosmetics", cosmetics_pane),
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
