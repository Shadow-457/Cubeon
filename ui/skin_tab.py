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
    ACCENT_HI,     # brighter green - hover fill on the ACCENT hero
    ACCENT_TINT, ACCENT_TINT_HI,  # selected/hover washes for tiles/cards
    SURFACE_MAX,   # top-elevation surface - hover fill on selected hat tiles
    ON_ACCENT,     # explicit dark foreground on an ACCENT fill (same value as BG)
    text_tab,      # underline-style segment tab (same chrome as Mods' content types)
    CARD_FILL, CARD_BORDER,  # translucent panel fills/outlines (Mods-tab language)
    ROW_HOVER,     # quiet hover lift for borderless rows/cards
    TEXT_FAINT,    # tertiary hints/placeholders
)
from cubeon import thread_safe_ui  # control-level refresh() (thread-safe)
from cubeon import remotes  # TEST_HANDLER gate for the featured prefetch

# Our own launcher core module - contains logic for skin storage/rendering
import launcher_core as core

# The bundled preview of the shared Cubeon cape (the one the Worker serves to
# every player - see worker/cubeon-skins.js). This is a relative asset path,
# which ft.Image.src resolves against the app's assets_dir, so it shows up
# whenever no custom cape is selected instead of leaving the box blank.
DEFAULT_CAPE_PREVIEW_SRC = "capes/cubeon_cape_preview.png"

# The most recently built section registers a "re-read the gallery catalog"
# hook here. main.py's background prefetch fills the real-player cache off
# the UI thread; when it has new tiles to show it calls refresh_active_galleries()
# instead of digging the (rebuilt-every-time) closures out of the tree.
_ACTIVE_GALLERY_REFRESH = {"fn": None}

# Preview bytes are immutable once written, so base64-encoding them once and
# keeping the string in memory spares every grid rebuild a disk read + encode.
# Keyed by path with the file mtime, so a re-rendered preview self-invalidates.
_IMG_MEMO: dict[str, tuple[float, str]] = {}


def _img_b64(path):
    """base64 of a preview PNG, memoized. None for a missing/placeholder path."""
    if not path:
        return None
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return None
    hit = _IMG_MEMO.get(path)
    if hit is not None and hit[0] == mtime:
        return hit[1]
    try:
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode("ascii")
    except OSError:
        return None
    _IMG_MEMO[path] = (mtime, data)
    return data


def refresh_active_galleries() -> None:
    """Re-read the (network-free) gallery catalogs and repaint whichever skin
    section is currently mounted. Safe to call from the prefetch worker; a
    no-op before the first build. Never raises."""
    fn = _ACTIVE_GALLERY_REFRESH.get("fn")
    if not fn:
        return
    try:
        with thread_safe_ui.TREE_LOCK:
            fn()
    except Exception:  # a refresh must never kill the prefetch thread
        pass


def _start_featured_prefetch(page, *, limit: int = 5) -> None:
    """Kick off a background fill of the recommended-players cache so the
    Recommended grid isn't empty on a fresh install. Fetches in small batches
    and repaints after each one (tiles appear fast), continuing until the whole
    curated list is cached or a pass makes no progress (offline / dead name).
    Only ever runs one prefetch at a time."""
    if _ACTIVE_GALLERY_REFRESH.get("prefetching"):
        return
    if remotes.TEST_HANDLER is not None:
        return  # tests drive the fake network themselves - no real prefetch
    try:
        already = core.featured_cached_count()
        target = core.featured_count()
    except Exception:
        return
    if already >= target:
        return
    _ACTIVE_GALLERY_REFRESH["prefetching"] = True

    def worker():
        try:
            cached = already
            # Bounded: target/limit batches is enough to fill the list; the
            # extra couple cover names that resolve to a cape-less snapshot.
            for _ in range((target // max(1, limit)) + 3):
                if cached >= target:
                    break
                core.prefetch_featured(limit=limit)
                refresh_active_galleries()
                try:
                    page.update()
                except Exception:
                    pass
                now = core.featured_cached_count()
                if now <= cached:
                    break  # no progress (offline, or a name won't resolve)
                cached = now
        finally:
            _ACTIVE_GALLERY_REFRESH["prefetching"] = False

    threading.Thread(target=worker, daemon=True,
                     name="cubeon-featured-prefetch").start()



def build_skin_section(page: ft.Page, cfg: dict, *, section_label, pixel_divider,
                        BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                        TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO=None,
                        mc_version=None, mc_loader=None, file_picker=None,
                        cape_file_picker=None, start_prefetch=True):
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
    # exactly like Browse - one visual language, and the pane wraps it in a
    # fixed-height scroll region so it never becomes an endless scroll.
    skins_list_col = ft.Row(spacing=10, wrap=True, run_spacing=10)

    # View state for the Browse | Installed split (same pattern the Mods tab
    # uses), plus a late-bound sync hook: refresh_skins_list/refresh_capes_list
    # also run during the build, before the view-tab rows exist, so they only
    # ping the hook once it's set (it re-renders the "Installed (N)" counts).
    view_state = {"skin": "browse", "cape": "browse"}
    view_sync = {"fn": None}
    # pane_id -> (browse_column, installed_column). The two views are both
    # mounted and switching flips `.visible`; this registry is how the tab
    # click reaches the columns (they're built after the tab row).
    view_panes = {}


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
        # Reflect the new active state in Browse too: the gallery grid may be
        # showing this same player's art, and an upload just now makes it
        # "Installed". Network-free.
        skin_tiles_sig["ids"] = None
        refresh_skin_gallery()
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
        # If this file came from the gallery, un-map it so Browse stops
        # advertising it as Installed.
        core.forget_file("skin", filename)
        refresh_skins_list()
        refresh_hat_row()
        skin_tiles_sig["ids"] = None
        refresh_skin_gallery()
        page.update()

    # --- Installed cards -------------------------------------------------
    # Installed items use the SAME wrapping card grid as Browse - one visual
    # language, and the pane wraps the grid in a fixed-height scroll region
    # (see _grid_scroll below) instead of paging. Each card shows a real
    # preview; the active item is highlighted, and hover reveals Use/Delete.
    def _owned_card(*, src, label, sublabel, active, on_use, on_delete,
                    preview_w=64, preview_h=92):
        """A selectable installed item: preview on top, name below, hover
        actions at the bottom. The active card swaps the Use button for an
        outlined ACTIVE pill and gets the accent border."""
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
                        content=(ft.Image(src=src, width=preview_w, height=preview_h,
                                          fit=ft.BoxFit.CONTAIN)
                                 if src else
                                 ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED,
                                         color=TEXT_DIM, size=22)),
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

    def _skin_card_b64(filename):
        out = os.path.join(core.SKINS_DIR, f"_thumb_{filename}.png")
        try:
            core.render_local_skin_preview(filename, out, scale=3)
        except Exception:
            return None
        return _img_b64(out)

    def _cape_card_b64(filename):
        out = os.path.join(core.CAPES_DIR, f"_thumb_{filename}.png")
        try:
            core.render_cape_preview(filename, out, scale=3)
        except Exception:
            return None
        return _img_b64(out)

    def refresh_skins_list():
        skins = core.list_custom_skins()
        skins_list_col.controls.clear()
        if not skins:
            skins_list_col.controls.append(
                ft.Text("No uploaded skins yet.", size=12, color=TEXT_DIM)
            )
        for s in skins:
            is_active = cfg.get("active_skin") == s["filename"]
            skins_list_col.controls.append(_owned_card(
                src=_skin_card_b64(s["filename"]),
                label=s["name"] + (" (slim)" if s.get("slim") else ""),
                sublabel="",
                active=is_active,
                on_use=lambda e, fn=s["filename"]: set_active(fn),
                on_delete=lambda e, fn=s["filename"]: delete_skin(fn),
            ))

        if view_sync["fn"]:
            view_sync["fn"]()

    def handle_skin_files(files):
        if not files:
            return
        picked = files[0]
        # Both upload CTAs (Browse + Installed) share this handler; write the
        # progress/result to both status lines so the feedback is always in
        # the pane the click actually came from.
        upload_status.value = skin_browse_upload_status.value = "Uploading..."
        thread_safe_ui.refresh(upload_status)
        thread_safe_ui.refresh(skin_browse_upload_status)
        try:
            display_name = os.path.splitext(picked.name)[0]
            entry = core.add_custom_skin(picked.path, display_name)
            set_active(entry["filename"])
            msg = f"Uploaded and set '{entry['name']}' as active skin."
        except ValueError as ve:
            msg = str(ve)
        except Exception as ex:
            msg = f"Upload failed: {ex}"
        upload_status.value = skin_browse_upload_status.value = msg
        thread_safe_ui.refresh(upload_status)
        thread_safe_ui.refresh(skin_browse_upload_status)

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
    if cfg.get("active_skin") or cfg.get("cosmetic_hat"):
        render_preview_for(cfg.get("active_skin"))

    # =====================================================================
    # SKIN GALLERY (cubeon/gallery.py) - real players' real skins, so nobody
    # has to hunt down a PNG. One search box filters the grid fuzzy (no exact
    # name needed); each tile's GET installs and wears that player's skin.
    # =====================================================================

    skin_browse_status = ft.Text("", size=12, color=TEXT_DIM)
    skin_gallery_caption = ft.Text("", size=12, color=TEXT_DIM)
    skin_empty_hint = ft.Text("", size=12, color=TEXT_DIM)
    skin_gallery_row = ft.Row(spacing=10, wrap=True)

    def gallery_tile(name, preview_src, installed, on_get, *, img_w, img_h, tip=None):
        """One browse-grid tile: preview art, name, and a Get/Installed state.
        Shared by the skin and cape galleries so both read the same way. The
        preview is rendered at this exact size (see gallery._ensure_previews)
        so the pixels stay crisp instead of being rescaled by the client."""
        btn = (
            ft.Container(
                content=ft.Text(
                    "INSTALLED", size=9, color=TEXT_DIM,
                    weight=ft.FontWeight.W_700,
                    style=ft.TextStyle(letter_spacing=0.6)),
                border=ft.border.Border.all(1, BORDER),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=8, vertical=4),
            )
            if installed else
            attach_hover(ft.Container(
                content=ft.Text("GET", size=10.5, color=ACCENT,
                                weight=ft.FontWeight.W_800,
                                style=ft.TextStyle(letter_spacing=0.6)),
                border=ft.border.Border.all(1, ACCENT_DIM),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=12, vertical=4),
                ink=False, on_click=on_get,
            ), None, ACCENT_TINT)
        )
        tile = ft.Container(
            content=ft.Column(
                [
                    (ft.Image(src=preview_src, width=img_w, height=img_h,
                              fit=ft.BoxFit.CONTAIN) if preview_src else
                     ft.Container(width=img_w, height=img_h,
                                  content=ft.Icon(ft.Icons.CHECKROOM_ROUNDED,
                                                  color=TEXT_DIM, size=28),
                                  alignment=ft.Alignment.CENTER)),
                    ft.Text(name, size=10.5, color=TEXT if not installed else TEXT_DIM,
                            weight=ft.FontWeight.W_600, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS,
                            width=img_w + 20,
                            text_align=ft.TextAlign.CENTER),
                    btn,
                ],
                spacing=6, horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                tight=True,
            ),
            bgcolor=CARD_FILL, border=ft.border.Border.all(1, CARD_BORDER),
            border_radius=RADIUS, padding=10, width=img_w + 40,
        )
        if tip:
            tile.tooltip = tip
        return attach_hover(tile, CARD_FILL, ROW_HOVER)

    skin_tiles_sig = {"ids": None}

    def refresh_skin_gallery():
        """Builds the skin grid once (all cached + recommended tiles) then
        filters by flipping tile visibility. No tree rebuild, so a search
        keystroke is instant and images never reload/flicker. Installed gallery
        skins show the INSTALLED pill instead of a GET button."""
        q = (skin_search.value or "").strip()
        try:
            items = core.all_gallery_items("skin")
        except Exception as ex:
            skin_browse_status.value = f"Couldn't load the gallery: {ex}"
            return
        ids = tuple(it["id"] for it in items)
        if ids != skin_tiles_sig["ids"]:
            # The catalog gained/lost a player (background prefetch) - rebuild.
            skin_tiles_sig["ids"] = ids
            skin_gallery_row.controls.clear()
        if not skin_gallery_row.controls:
            installed_ids = set()
            try:
                for s in core.list_custom_skins():
                    gid = core.gallery_id_for_file("skin", s["filename"])
                    if gid:
                        installed_ids.add(gid)
            except Exception:
                pass
            for item in items:
                is_installed = item["id"] in installed_ids
                cached = item.get("cached", True)
                tile = gallery_tile(
                    item["name"], _img_b64(item["preview_path"]), is_installed,
                    lambda e, gid=item["id"], ok=cached: get_gallery_skin(gid, ok),
                    img_w=48, img_h=96,
                    tip=("Recommended. " if item.get("featured") else "") +
                        ("Already in your skins - find it under Installed."
                         if is_installed else
                         "Install and wear this skin right away."))
                tile.data = {"skin_gid": item["id"], "cached": cached,
                             "name": item["name"], "featured": item.get("featured")}
                skin_gallery_row.controls.append(tile)
        all_items = {it["id"]: it for it in items}
        shown = 0
        for tile in skin_gallery_row.controls:
            meta = getattr(tile, "data", None)
            if not isinstance(meta, dict) or "skin_gid" not in meta:
                continue
            item = all_items.get(meta["skin_gid"], {"id": meta["skin_gid"],
                                                    "name": meta["name"],
                                                    "tags": [], "cached": meta["cached"]})
            visible = core.matches_query(item, q)
            tile.visible = visible
            shown += int(visible)
        skin_gallery_caption.value = (
            f'Results for "{q}"' if q
            else "Recommended players")
        skin_empty_hint.value = (
            (f'No match for "{q}"' if q else
             "Loading recommended players...")
            if not shown else "")

    def get_gallery_skin(gid, cached=True):
        def do_install():
            try:
                entry = core.install_gallery_skin(cfg, gid)
            except Exception as ex:
                with thread_safe_ui.TREE_LOCK:
                    skin_browse_status.value = f"Couldn't install: {ex}"
                page.update()
                return
            with thread_safe_ui.TREE_LOCK:
                # entry["name"] may be absent under test stubs - fall back to id.
                skin_browse_status.value = (
                    f"Installed '{entry.get('name', gid)}' - "
                    "it's your active skin now.")
                render_preview_for(entry["filename"])
                refresh_skins_list()
                refresh_hat_row()
                skin_tiles_sig["ids"] = None
                refresh_skin_gallery()
            page.update()

        if cached:
            do_install()
        else:
            # A recommended player whose art isn't cached yet - downloading is
            # network, so do it off the UI thread.
            skin_browse_status.value = f"Loading {gid}'s skin\u2026"
            page.update()
            threading.Thread(target=do_install, daemon=True,
                             name="cubeon-skin-get").start()

    # Search filters the cached/recommended grid instantly (fuzzy). No
    # "type a name to fetch" flow - the gallery is browsed, not queried.
    skin_search = ft.TextField(
        hint_text="Search skins\u2026",
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        expand=True, dense=True,
        content_padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
        bgcolor=CARD_FILL, border_color=CARD_BORDER,
        focused_border_color=ACCENT_DIM, cursor_color=ACCENT,
        color=TEXT, hint_style=ft.TextStyle(color=TEXT_FAINT),
        on_change=lambda e: refresh_skin_gallery(),
    )
    skin_search_row = ft.Row([skin_search], spacing=8)

    # Your own PNG is the other way to get a skin, so the upload CTA lives
    # here in Browse too (not only under Installed) - "browse ready-made /
    # fetch a real player / upload your own" reads as one grouped action.
    # A Flet control can only live in ONE pane, so this is a second instance
    # sharing the same picker closures as the Installed-pane button.
    skin_browse_upload_status = ft.Text("", size=12, color=TEXT_DIM)
    skin_browse_upload = attach_hover(ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.ADD_ROUNDED, color=ACCENT, size=18),
                ft.Text("Upload your own skin PNG",
                        color=ACCENT, weight=ft.FontWeight.W_700, size=13),
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

    refresh_skin_gallery()


    # =====================================================================
    # COSMETICS - hat picker. Hats are pixel art baked into the skin's
    # hat layer and flow to the game through the same CustomSkinLoader
    # sync as the skin itself - no extra mods, nothing new at launch.
    # =====================================================================

    hat_status = ft.Text("", size=12, color=TEXT_DIM, visible=False)
    hat_row = ft.Row(spacing=10, wrap=True)

    # A big live preview of the current skin+hat, mirroring the Skin/Cape
    # panes' left-hand stage. Picking a hat is then a visual choice: the
    # stage updates on every click, so the tile names don't have to carry
    # the whole story in text.
    hat_preview = ft.Image(src="icon.svg", width=140, height=232,
                           fit=ft.BoxFit.CONTAIN, visible=False)
    hat_preview_caption = ft.Text("No hat", size=12, color=TEXT_DIM,
                                  weight=ft.FontWeight.W_600)

    # The hat catalogue is already "everything ready-made", so its browser is
    # just a search box over the grid - no upload flow applies to hats.
    hat_search = ft.TextField(
        hint_text="Search hats...",
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        expand=True, dense=True,
        content_padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
        bgcolor=CARD_FILL, border_color=CARD_BORDER,
        focused_border_color=ACCENT_DIM, cursor_color=ACCENT,
        color=TEXT, hint_style=ft.TextStyle(color=TEXT_FAINT),
        on_change=lambda e: refresh_hat_row(),
    )

    def hat_name(hat_id):
        for h in core.list_hats():
            if h["id"] == hat_id:
                return h["name"]
        return hat_id

    def render_hat_stage():
        """Repaints the big preview to exactly what the game shows with the
        current hat (default Steve if no skin), and names it underneath."""
        out_path = os.path.join(core.SKINS_DIR, "_hat_stage.png")
        try:
            core.preview_composed_body(cfg, out_path, scale=8)
            with open(out_path, "rb") as f:
                hat_preview.src = base64.b64encode(f.read()).decode("ascii")
            hat_preview.visible = True
        except Exception:
            pass  # the stage is decoration - wearing still works without it
        worn = cfg.get("cosmetic_hat")
        hat_preview_caption.value = hat_name(worn) if worn else "No hat"

    def set_hat_status(msg):
        """Single-line status under the grid; hidden when empty so the pane
        stays quiet unless there's something worth reading."""
        hat_status.value = msg or ""
        hat_status.visible = bool(msg)

    def hat_progress(hat_id):
        """(current, goal) for a locked hat's requirement, or None when the
        hat is unlocked/free. Drives the mini progress bar on locked tiles."""
        from cubeon import milestones
        req = core.hat_requirement(hat_id)
        if req is None or core.hat_unlocked(hat_id):
            return None
        for m in milestones.MILESTONES:
            if m["id"] == req:
                return milestones.progress(m)
        return None

    def hat_earn_hint(hat_id):
        """Short "how to earn this" for a locked hat (e.g. '7.4 / 10 h in
        game'). Returns '' for unlocked hats."""
        from cubeon import milestones
        req = core.hat_requirement(hat_id)
        if req is None or core.hat_unlocked(hat_id):
            return ""
        for m in milestones.MILESTONES:
            if m["id"] == req:
                cur, goal = milestones.progress(m)
                if m["kind"] == "hours_played":
                    return f"{cur:.1f} / {goal:.0f} h in game"
                if m["kind"] == "friends":
                    return f"{int(cur)} / {int(goal)} friends"
                if m["kind"] == "hosted":
                    return f"{int(cur)} / {int(goal)} hosted"
                return m["desc"]
        return "Keep playing to earn this"

    def wear_hat(e, hat_id=None):
        try:
            core.set_hat(cfg, hat_id)
        except PermissionError:
            set_hat_status(f"Locked - {hat_earn_hint(hat_id)}")
            refresh_hat_row()
            page.update()
            return
        except Exception as ex:
            set_hat_status(f"Couldn't apply hat: {ex}")
            page.update()
            return
        set_hat_status("")  # the big stage + selected tile say what's worn
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
            if locked:
                # Show "how close am I" as a bar, not a paragraph: the
                # tooltip keeps the exact numbers, the bar carries the gist.
                cur, goal = hat_progress(hat_id) or (0.0, 1.0)
                content.controls.append(ft.ProgressBar(
                    value=(cur / goal) if goal else 0.0,
                    width=52, height=4, color=ACCENT_DIM, bgcolor=SURFACE,
                    border_radius=2,
                ))
            # Locked tiles carry the earn hint as their tooltip so the
            # requirement is discoverable on hover without a click that
            # would just say "locked".
            container = ft.Container(
                content,
                bgcolor=ACCENT_TINT if selected else CARD_FILL,
                border=ft.border.Border.all(1, ACCENT if selected else CARD_BORDER),
                border_radius=RADIUS,
                padding=10,
                ink=False,
                on_click=lambda e, h=hat_id: wear_hat(e, h),
            )
            if locked:
                container.tooltip = hat_earn_hint(hat_id) or "Locked"
                container.bgcolor = CARD_FILL
                container.content.controls[1].color = TEXT_DIM
            return attach_hover(
                container,
                ACCENT_TINT if selected else CARD_FILL,
                ACCENT_TINT_HI if selected else ROW_HOVER,
            )

        hat_row.controls.append(tile("None", None))
        hq = (hat_search.value or "").strip().lower()
        for h in core.list_hats():
            if hq and hq not in h["name"].lower():
                continue
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

        # Repaint the big stage last so it reflects whatever is now worn.
        render_hat_stage()

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
    # Wrapping card grid, same as the skins installed list (see _owned_card).
    capes_list_col = ft.Row(spacing=10, wrap=True, run_spacing=10)

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
        # Keep Browse's Installed pills honest after an upload / switch.
        cape_tiles_sig["ids"] = None
        refresh_cape_gallery()
        page.update()

    def delete_cape(filename):
        if cfg.get("active_cape") == filename:
            core.set_active_cape(cfg, None)
            show_default_cape_preview()
        core.delete_custom_cape(filename)
        # Un-map a gallery cape so Browse doesn't keep it as Installed.
        core.forget_file("cape", filename)
        refresh_capes_list()
        cape_tiles_sig["ids"] = None
        refresh_cape_gallery()
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
            capes_list_col.controls.append(_owned_card(
                src=_cape_card_b64(c["filename"]),
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

        if view_sync["fn"]:
            view_sync["fn"]()

    def handle_cape_files(files):
        if not files:
            return
        picked = files[0]
        # Both upload CTAs (Browse + Installed) share this handler; write the
        # progress/result to both status lines so the feedback is always in
        # the pane the click actually came from.
        cape_status.value = cape_browse_upload_status.value = "Uploading..."
        page.update()
        try:
            display_name = os.path.splitext(picked.name)[0]
            entry = core.add_custom_cape(picked.path, display_name)
            set_active_cape(entry["filename"])
            msg = f"Uploaded and set '{entry['name']}' as active cape."
        except ValueError as ve:
            msg = str(ve)
        except Exception as ex:
            msg = f"Upload failed: {ex}"
        cape_status.value = cape_browse_upload_status.value = msg
        page.update()

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

    # =====================================================================
    # CAPE GALLERY (cubeon/gallery.py) - ready-made capes to browse and
    # wear with one click, so uploading a PNG is only for people who
    # genuinely made their own. Same "Get installs and wears it" flow as
    # the skin gallery.
    # =====================================================================

    cape_browse_status = ft.Text("", size=12, color=TEXT_DIM)
    cape_gallery_caption = ft.Text("", size=12, color=TEXT_DIM)
    cape_empty_hint = ft.Text("", size=12, color=TEXT_DIM)
    cape_gallery_row = ft.Row(spacing=10, wrap=True)

    cape_tiles_sig = {"ids": None}

    def refresh_cape_gallery():
        """Builds the cape grid once, then filters by flipping visibility. One
        search box filters fuzzy; no rebuild per keystroke, no image flicker."""
        q = (cape_search.value or "").strip()
        try:
            items = core.all_gallery_items("cape")
        except Exception as ex:
            cape_browse_status.value = f"Couldn't load the gallery: {ex}"
            return
        ids = tuple(it["id"] for it in items)
        if ids != cape_tiles_sig["ids"]:
            cape_tiles_sig["ids"] = ids
            cape_gallery_row.controls.clear()
        if not cape_gallery_row.controls:
            installed_ids = set()
            try:
                for c in core.list_custom_capes():
                    gid = core.gallery_id_for_file("cape", c["filename"])
                    if gid:
                        installed_ids.add(gid)
            except Exception:
                pass
            for item in items:
                is_installed = item["id"] in installed_ids
                cached = item.get("cached", True)
                tile = gallery_tile(
                    item["name"], _img_b64(item["preview_path"]), is_installed,
                    lambda e, gid=item["id"], ok=cached: get_gallery_cape(gid, ok),
                    img_w=60, img_h=96,
                    tip=("Recommended. " if item.get("featured") else "") +
                        ("Already installed - find it under Installed."
                         if is_installed else
                         "Install and wear this cape right away."))
                tile.data = {"cape_gid": item["id"], "cached": cached,
                             "name": item["name"], "featured": item.get("featured")}
                cape_gallery_row.controls.append(tile)
        all_items = {it["id"]: it for it in items}
        shown = 0
        for tile in cape_gallery_row.controls:
            meta = getattr(tile, "data", None)
            if not isinstance(meta, dict) or "cape_gid" not in meta:
                continue
            item = all_items.get(meta["cape_gid"], {"id": meta["cape_gid"],
                                                    "name": meta["name"],
                                                    "tags": [], "cached": meta["cached"]})
            visible = core.matches_query(item, q)
            tile.visible = visible
            shown += int(visible)
        cape_gallery_caption.value = (
            f'Results for "{q}"' if q
            else "Recommended capes")
        cape_empty_hint.value = (
            (f'No match for "{q}"' if q else
             "Loading recommended capes...")
            if not shown else "")

    def get_gallery_cape(gid, cached=True):
        def do_install():
            try:
                entry = core.install_gallery_cape(cfg, gid)
            except Exception as ex:
                with thread_safe_ui.TREE_LOCK:
                    cape_browse_status.value = f"Couldn't install: {ex}"
                page.update()
                return
            with thread_safe_ui.TREE_LOCK:
                cape_browse_status.value = (
                    f"Installed '{entry.get('name', gid)}' - "
                    "you're wearing it now.")
                render_cape_preview_for(entry["filename"])
                refresh_capes_list()
                cape_tiles_sig["ids"] = None
                refresh_cape_gallery()
            page.update()

        if cached:
            do_install()
        else:
            cape_browse_status.value = f"Loading {gid}'s cape\u2026"
            page.update()
            threading.Thread(target=do_install, daemon=True,
                             name="cubeon-cape-get").start()

    # Search filters the cached/recommended grid instantly (fuzzy). No
    # "type a name to fetch" flow - the gallery is browsed, not queried.
    cape_search = ft.TextField(
        hint_text="Search capes\u2026",
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        expand=True, dense=True,
        content_padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
        bgcolor=CARD_FILL, border_color=CARD_BORDER,
        focused_border_color=ACCENT_DIM, cursor_color=ACCENT,
        color=TEXT, hint_style=ft.TextStyle(color=TEXT_FAINT),
        on_change=lambda e: refresh_cape_gallery(),
    )
    cape_search_row = ft.Row([cape_search], spacing=8)

    refresh_cape_gallery()

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
    # Skin and Cape now use the Mods tab's Browse | Installed split: Browse
    # = the searchable ready-made gallery, Installed = the uploads and
    # gallery installs you manage yourself. Both sub-panes stay mounted and
    # switching only flips .visible (no rebuild), exactly like mods_tab's
    # view_segment_row pattern.

    def _apply_view(pane_id):
        """Flips Browse/Installed visibility for one pane. The columns are
        built once and kept mounted, so this is the ONLY thing that changes
        what the user sees - without it the tab underline moved but the
        content stayed on Browse, which read as "Installed shows nothing"."""
        pair = view_panes.get(pane_id)
        if not pair:
            return
        browse, installed = pair
        browse.visible = view_state[pane_id] == "browse"
        installed.visible = view_state[pane_id] == "installed"

    def _view_tabs(pane_id, views):
        """Builds the underline tab row for one pane's Browse/Installed views.
        views: [(view_id, label_fn)] - label_fn is re-evaluated on every
        rebuild so the Installed label can carry a live count."""
        row = ft.Row(spacing=18)

        def rebuild():
            row.controls.clear()
            for vid, label_fn in views:
                row.controls.append(text_tab(
                    label_fn(),
                    selected=view_state[pane_id] == vid,
                    # pane_id comes from _view_tabs' closure (one invocation
                    # per pane), so only v is passed - a second positional
                    # arg overflows switch_view(vid) at click time.
                    on_click=lambda e, v=vid: switch_view(v)))

        def switch_view(vid):
            if view_state[pane_id] == vid:
                return
            view_state[pane_id] = vid
            _apply_view(pane_id)
            rebuild()
            page.update()

        rebuild()
        return row, rebuild

    def _installed_count(list_fn):
        try:
            return len(list_fn())
        except Exception:
            return 0

    skin_views_row, rebuild_skin_views = _view_tabs(
        "skin",
        [("browse", lambda: "Browse"),
         ("installed", lambda: f"Installed "
          f"({_installed_count(core.list_custom_skins)})")])

    cape_views_row, rebuild_cape_views = _view_tabs(
        "cape",
        [("browse", lambda: "Browse"),
         ("installed", lambda: f"Installed "
          f"({_installed_count(core.list_custom_capes)})")])

    def _view_pane(pane_id, views_row, browse_children, installed_children):
        browse = ft.Column(browse_children, spacing=6, visible=(view_state[pane_id] == "browse"))
        installed = ft.Column(installed_children, spacing=8,
                              visible=(view_state[pane_id] == "installed"))
        view_panes[pane_id] = (browse, installed)
        return browse, installed

    skin_browse_pane, skin_installed_pane = _view_pane(
        "skin", skin_views_row,
        [skin_search_row, ft.Container(height=4), skin_gallery_caption,
         ft.Container(height=2), skin_empty_hint,
         ft.Container(height=6), _grid_scroll(skin_gallery_row),
         ft.Container(height=2), skin_browse_status],
        [skins_label, _grid_scroll(skins_list_col), ft.Container(height=2),
         upload_button, upload_status])

    cape_browse_pane, cape_installed_pane = _view_pane(
        "cape", cape_views_row,
        [cape_search_row, ft.Container(height=4), cape_gallery_caption,
         ft.Container(height=2), cape_empty_hint,
         ft.Container(height=6), _grid_scroll(cape_gallery_row),
         ft.Container(height=2), cape_browse_status],
        [_cape_label_with_note(), _grid_scroll(capes_list_col),
         ft.Container(height=2), cape_upload_button, cape_status])

    # Late-bound count sync: the installed lists call this whenever they
    # rebuild so the "Installed (N)" tab labels stay honest.
    def sync_installed_counts():
        rebuild_skin_views()
        rebuild_cape_views()

    view_sync["fn"] = sync_installed_counts

    skin_pane = ft.Row(
        [
            skin_preview_box,
            ft.Container(width=16),
            ft.Column(
                [skin_views_row, ft.Container(height=6),
                 skin_browse_pane, skin_installed_pane],
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
                [cape_views_row, ft.Container(height=6),
                 cape_browse_pane, cape_installed_pane],
                spacing=6, expand=True,
            ),
        ],
        vertical_alignment=ft.CrossAxisAlignment.START,
    )

    # Cosmetics pane: same two-column shape as Skin/Cape - a big live stage
    # on the left (what the game will show), search + hat grid on the right.
    # The stage makes picking a hat a visual choice and lets the tiles stay
    # light on text. Locked tiles carry a small progress bar, not a paragraph.
    cosmetics_pane = ft.Row(
        [
            ft.Container(
                content=ft.Column(
                    [hat_preview, ft.Container(height=6), hat_preview_caption],
                    horizontal_alignment=ft.CrossAxisAlignment.CENTER,
                    spacing=4,
                ),
                bgcolor=CARD_FILL, border=ft.border.Border.all(1, CARD_BORDER),
                border_radius=RADIUS, padding=12,
                width=180, height=290, alignment=ft.Alignment.CENTER,
            ),
            ft.Container(width=16),
            ft.Column(
                [
                    _hat_label_with_note(),
                    hat_search,
                    ft.Container(height=6),
                    _grid_scroll(hat_row, height=290),
                    hat_status,
                ],
                spacing=8, expand=True,
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

    # Let the background featured-prefetch (and anything else that fills the
    # cache) repaint the grids without holding a reference to these closures.
    def _refresh_galleries():
        refresh_skin_gallery()
        refresh_cape_gallery()

    _ACTIVE_GALLERY_REFRESH["fn"] = _refresh_galleries
    if start_prefetch:
        _start_featured_prefetch(page)

    return skin_section
