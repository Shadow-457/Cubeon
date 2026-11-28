"""Flet viewer for Minecraft screenshots."""

from __future__ import annotations

import threading

import flet as ft
from ui.image_memory import preview_image
from cubeon import i18n

from cubeon import dialogs
from cubeon import screenshot_gallery as store
from cubeon import thread_safe_ui
from cubeon.background_refresh import BackgroundRefresh
from cubeon.theme import (
    hover_hint,
    ACCENT, ACCENT_TINT, CARD_BORDER, CARD_FILL, DANGER,
    FONT_MONO, RADIUS, ROW_HOVER, SURFACE, SURFACE_MAX,
    TEXT, TEXT_DIM, TEXT_FAINT, attach_hover,
)

# A full screenshot decode is the expensive step (~100-200 ms for a
# 1920x1080 PNG). The first Images-pane open with N screenshots used to
# fire N concurrent decodes - saturating the CPU and flooding the loop
# with repaints as each one landed. Renders are now disk-cached
# (cubeon/screenshot_gallery.py), and the cache MISSES above stay bounded:
# at most this many decoding threads run at once.
_DECODE_POOL = threading.Semaphore(3)


def build_screenshot_gallery_tab(page: ft.Page, *, on_back=None) -> tuple[ft.Control, callable]:
    """Build the full-canvas screenshots tab and return its refresh callback."""
    state = {"items": [], "selected": None, "generation": 0,
             "thumb_generation": 0, "scanned": False}
    thumb_refs = {}

    selected_image = preview_image(
        src="icon.svg", width=620, height=430, fit=ft.BoxFit.CONTAIN,
        visible=False,
    )
    selected_image.width = selected_image.height = None
    selected_empty = ft.Column(
        [
            ft.Icon(ft.Icons.IMAGE_OUTLINED, size=32, color=TEXT_FAINT),
            ft.Text("Select a screenshot", size=14, color=TEXT_DIM),
            ft.Text("Your Minecraft captures appear here", size=11,
                    color=TEXT_FAINT),
        ], spacing=8, tight=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )
    selected_name = ft.Text("No screenshot selected", size=13, color=TEXT,
                            weight=ft.FontWeight.W_600, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS)
    selected_meta = ft.Text("", size=11, color=TEXT_DIM, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS)
    status = ft.Text("", size=11, color=TEXT_DIM, expand=True,
                     max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
    capture_count = ft.Text("0 captures", size=11, color=TEXT_DIM,
                            font_family=FONT_MONO)
    thumb_column = ft.ListView(spacing=6, scroll=ft.ScrollMode.AUTO, expand=True,
                              cache_extent=320)

    async def _copy_file_to_clipboard(filename):
        from flet.controls.services.clipboard import Clipboard

        copied = await Clipboard().set_files([store.clipboard_path(filename)])
        if copied is False:
            raise RuntimeError("the desktop clipboard rejected the screenshot")

    def _copy_selected(e=None):
        filename = state.get("selected")
        if not filename:
            return
        copy_button.disabled = True
        status.value = "Copying screenshot…"
        thread_safe_ui.refresh(copy_button)
        thread_safe_ui.refresh(status)

        async def _copy():
            try:
                await _copy_file_to_clipboard(filename)
                status.value = "Screenshot copied to clipboard."
            except Exception as ex:
                status.value = f"Couldn't copy screenshot: {ex}"
            finally:
                copy_button.disabled = False
                thread_safe_ui.refresh(copy_button)
                thread_safe_ui.refresh(status)

        try:
            page.run_task(_copy)
        except Exception as ex:
            copy_button.disabled = False
            status.value = f"Couldn't copy screenshot: {ex}"
            thread_safe_ui.refresh(copy_button)
            thread_safe_ui.refresh(status)

    copy_button = ft.TextButton(
        "Copy",
        icon=ft.Icons.CONTENT_COPY_ROUNDED,
        icon_color=ACCENT,
        tooltip=hover_hint("Copy the selected screenshot"),
        disabled=True,
        width=104, height=34,
        style=ft.ButtonStyle(color=TEXT_DIM,
                            shape=ft.RoundedRectangleBorder(radius=RADIUS),
                            side=ft.BorderSide(1, CARD_BORDER)),
        on_click=_copy_selected,
        data="screenshot-copy",
    )

    def _paint_selected_image(filename, generation):
        try:
            with _DECODE_POOL:
                encoded = store.image_base64(filename)
        except Exception as ex:
            with thread_safe_ui.TREE_LOCK:
                if generation != state["generation"]:
                    return
                status.value = f"Couldn't preview screenshot: {ex}"
                thread_safe_ui.refresh(status)
            return
        with thread_safe_ui.TREE_LOCK:
            if generation != state["generation"]:
                return
            selected_image.src = encoded
            selected_image.visible = True
            selected_empty.visible = False
            status.value = "Preview ready."
            thread_safe_ui.refresh(selected_image)
            thread_safe_ui.refresh(selected_empty)
            thread_safe_ui.refresh(status)

    def _select(item):
        with thread_safe_ui.TREE_LOCK:
            _select_locked(item)

    def _select_locked(item):
        filename = item["filename"]
        state["selected"] = filename
        state["generation"] += 1
        generation = state["generation"]
        selected_name.value = item["name"]
        selected_name.tooltip = hover_hint(item["name"])
        selected_meta.value = (
            f"{item['date']}  ·  {item['width']}×{item['height']}  ·  "
            f"{item['bytes'] / 1024:.0f} KB"
        )
        selected_meta.tooltip = hover_hint(selected_meta.value)
        status.value = "Loading preview…"
        selected_image.visible = False
        selected_empty.visible = True
        copy_button.disabled = False
        for name, (card, _img, _loading) in thumb_refs.items():
            card.border = ft.border.Border.all(
                1, ACCENT if name == filename else CARD_BORDER)
            card.bgcolor = ACCENT_TINT if name == filename else CARD_FILL
            thread_safe_ui.refresh(card)
        thread_safe_ui.refresh(selected_name)
        thread_safe_ui.refresh(selected_meta)
        thread_safe_ui.refresh(status)
        thread_safe_ui.refresh(copy_button)
        threading.Thread(target=_paint_selected_image,
                         args=(filename, generation), daemon=True,
                         name="cubeon-screenshot-preview").start()

    def _load_thumb(filename, image, loading, generation):
        try:
            with _DECODE_POOL:
                encoded = store.image_base64(filename, max_size=(180, 112))
        except Exception:
            return
        with thread_safe_ui.TREE_LOCK:
            if generation != state["thumb_generation"]:
                return
            image.src = encoded
            image.visible = True
            loading.visible = False
            thread_safe_ui.refresh(image)
            thread_safe_ui.refresh(loading)

    def _render_list(items):
        state["items"] = items
        state["generation"] += 1
        state["thumb_generation"] += 1
        thumb_generation = state["thumb_generation"]
        thumb_refs.clear()
        thumb_column.controls.clear()
        if not items:
            thumb_column.controls.append(ft.Container(
                content=ft.Column([
                    ft.Icon(ft.Icons.SCREENSHOT_MONITOR_OUTLINED, size=28,
                            color=TEXT_FAINT),
                    ft.Text("No screenshots yet", size=12, color=TEXT_DIM),
                    ft.Text("Press F2 in Minecraft to capture one.", size=10,
                            color=TEXT_FAINT, text_align=ft.TextAlign.CENTER),
                ], spacing=8, tight=True,
                   horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=16, alignment=ft.Alignment.CENTER,
            ))
            state["selected"] = None
            selected_image.visible = False
            selected_empty.visible = True
            selected_name.value = "No screenshot selected"
            selected_meta.value = ""
            copy_button.disabled = True
            capture_count.value = "0 captures"
            thread_safe_ui.refresh(thumb_column)
            thread_safe_ui.refresh(selected_image)
            thread_safe_ui.refresh(selected_empty)
            thread_safe_ui.refresh(selected_name)
            thread_safe_ui.refresh(selected_meta)
            thread_safe_ui.refresh(copy_button)
            thread_safe_ui.refresh(capture_count)
            return

        for item in items:
            filename = item["filename"]
            image = preview_image(src="icon.svg", width=84, height=52,
                             fit=ft.BoxFit.CONTAIN, visible=False)
            loading = ft.ProgressRing(width=18, height=18, stroke_width=2,
                                      color=ACCENT)
            card = attach_hover(ft.Container(
                content=ft.Row([
                    ft.Container(
                        content=ft.Stack([image, loading],
                                         alignment=ft.Alignment.CENTER),
                        width=84, height=52, bgcolor=SURFACE_MAX,
                        border_radius=6, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        alignment=ft.Alignment.CENTER,
                    ),
                    ft.Column([
                        ft.Text(item["name"], size=11.5, color=TEXT,
                                weight=ft.FontWeight.W_600, max_lines=1,
                                overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(item["date"], size=10, color=TEXT_DIM,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ], spacing=3, expand=True, alignment=ft.MainAxisAlignment.CENTER),
                ], spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                width=224, height=68, padding=8, bgcolor=CARD_FILL,
                border=ft.border.Border.all(1, CARD_BORDER),
                border_radius=RADIUS, ink=False,
                tooltip=hover_hint(item['name']),
                on_click=lambda e, data=item: _select(data),
            ), CARD_FILL, ROW_HOVER)
            thumb_refs[filename] = (card, image, loading)
            thumb_column.controls.append(card)

        selected = next((item for item in items
                         if item["filename"] == state.get("selected")), None)
        _select(selected or items[0])
        thread_safe_ui.refresh(thumb_column)
        for item in items:
            refs = thumb_refs[item["filename"]]
            threading.Thread(target=_load_thumb,
                             args=(item["filename"], refs[1], refs[2], thumb_generation),
                             daemon=True,
                             name="cubeon-screenshot-thumb").start()

    def _apply_scan(items):
        # Returning to the gallery keeps its selection and decoded artwork
        # when the inventory is unchanged.
        if not state["scanned"] or items != state["items"]:
            _render_list(items)
            state["scanned"] = True
        capture_count.value = (f"{len(items)} capture"
                               + ("s" if len(items) != 1 else ""))
        status.value = (f"{len(state['items'])} screenshot"
                        + ("s" if len(state["items"]) != 1 else "")
                        + " found")
        thread_safe_ui.refresh(capture_count)
        thread_safe_ui.refresh(status)

    def _scan_failed(error):
        status.value = f"Couldn't scan screenshots: {error}"
        thread_safe_ui.refresh(status)

    scans = BackgroundRefresh(lambda: store.list_screenshots(), _apply_scan,
                              name="cubeon-screenshot-scan", failed=_scan_failed)

    def _refresh(e=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            status.value = "Scanning screenshots…"
            thread_safe_ui.refresh(status)
        try:
            scans.request()
        except Exception as error:
            with thread_safe_ui.TREE_LOCK:
                _scan_failed(error)

    def _delete_selected(e=None):
        filename = state.get("selected")
        if not filename:
            return
        item = next((x for x in state["items"] if x["filename"] == filename), None)
        if item is None:
            return

        def _cancel(_e=None):
            dialogs.close_dialog(page, confirm)

        def _confirm(_e=None):
            try:
                store.delete_screenshot(filename)
                dialogs.close_dialog(page, confirm)
                _refresh()
            except Exception as ex:
                status.value = f"Couldn't delete screenshot: {ex}"
                thread_safe_ui.refresh(status)

        confirm = ft.AlertDialog(
            modal=True,
            title=ft.Text("Delete screenshot?", color=TEXT),
            content=ft.Text(f"{item['name']} will be removed from Minecraft's screenshots folder.",
                            color=TEXT_DIM),
            actions=[
                ft.TextButton(i18n.t("Cancel"), on_click=_cancel),
                ft.TextButton(i18n.t("Delete"), on_click=_confirm,
                              style=ft.ButtonStyle(color=DANGER)),
            ],
        )
        dialogs.open_dialog(page, confirm)

    def _open_folder(e=None):
        with thread_safe_ui.TREE_LOCK:
            if folder_button.disabled:
                return
            filename = state.get("selected")
            folder_button.disabled = True
            status.value = "Opening screenshots folder…"
            thread_safe_ui.refresh(folder_button)
            thread_safe_ui.refresh(status)

        def _finish(message):
            with thread_safe_ui.TREE_LOCK:
                status.value = message
                folder_button.disabled = False
                thread_safe_ui.refresh(folder_button)
                thread_safe_ui.refresh(status)

        def _open():
            try:
                store.open_screenshots_folder(filename)
                message = "Screenshots folder open requested."
            except Exception as ex:
                message = f"Couldn't open folder: {ex}"
            _finish(message)

        try:
            threading.Thread(target=_open, daemon=True,
                             name="cubeon-screenshot-folder").start()
        except Exception as ex:
            _finish(f"Couldn't open folder: {ex}")

    folder_button = ft.IconButton(
        icon=ft.Icons.FOLDER_OPEN_ROUNDED, icon_color=TEXT_DIM,
        tooltip=hover_hint("Open screenshots folder"), on_click=_open_folder,
        data="screenshot-folder",
    )

    folder_button.width = folder_button.height = 34
    header_title = ft.Text(i18n.t("Screenshots"), size=16, color=TEXT,
                           weight=ft.FontWeight.W_600, expand=True,
                           max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
    back = [ft.IconButton(
        icon=ft.Icons.ARROW_BACK_ROUNDED, icon_color=TEXT_DIM,
        width=34, height=34, tooltip=hover_hint(i18n.t("Back")), on_click=on_back,
        data="screenshots-back",
    )] if on_back is not None else [ft.Icon(ft.Icons.PHOTO_LIBRARY_OUTLINED,
                                          color=TEXT_DIM, size=20)]
    gallery_header = ft.Row([
        *back, header_title, capture_count,
        ft.IconButton(icon=ft.Icons.REFRESH_ROUNDED, icon_color=TEXT_DIM,
                      width=34, height=34, tooltip=hover_hint(i18n.t("Refresh")), on_click=_refresh),
        folder_button,
    ], spacing=8, height=36, data="screenshots-toolbar")

    delete_button = ft.IconButton(
        icon=ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color=DANGER,
        tooltip=hover_hint(i18n.t("Delete screenshot")), width=34, height=34,
        on_click=_delete_selected, data="screenshot-delete",
    )
    gallery_body = ft.Container(
        expand=True,
        content=ft.Row([
            ft.Container(
                width=240, content=thumb_column,
                bgcolor=SURFACE, border=ft.border.Border.all(1, CARD_BORDER),
                border_radius=RADIUS, padding=8,
            ),
            ft.Container(
                expand=True,
                content=ft.Column([
                    ft.Container(
                        content=ft.Stack([
                            selected_image,
                            ft.Container(selected_empty, alignment=ft.Alignment.CENTER),
                        ], fit=ft.StackFit.EXPAND),
                        bgcolor=SURFACE_MAX,
                        border=ft.border.Border.all(1, CARD_BORDER),
                        border_radius=RADIUS, clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                        expand=True,
                    ),
                    ft.Row([
                        ft.Column([selected_name, selected_meta], spacing=3,
                                  expand=True, alignment=ft.MainAxisAlignment.CENTER),
                        copy_button, delete_button,
                    ], spacing=8, height=42),
                ], spacing=6, expand=True),
            ),
        ], spacing=10, expand=True),
    )

    gallery_tab = ft.Column(
        [gallery_header, gallery_body, ft.Row([status], height=18)],
        spacing=8, expand=True, data="screenshot-gallery",
    )
    wide_body = gallery_body.content
    wide_body.vertical_alignment = ft.CrossAxisAlignment.STRETCH
    thumbnails, preview = wide_body.controls
    compact_body = ft.Column(spacing=8, expand=True,
                             horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    layout = {"compact": False}

    def layout_changed(event):
        ft.context.disable_auto_update()
        compact = float(event.width or 1000) < 680
        with thread_safe_ui.TREE_LOCK:
            if compact == layout["compact"]:
                return
            layout["compact"] = compact
            # Reuse the same preview and thumbnails. Small windows put the
            # image above a horizontal strip, leaving room for its actions.
            wide_body.controls.clear()
            compact_body.controls.clear()
            if compact:
                compact_body.controls.extend([preview, thumbnails])
            else:
                wide_body.controls.extend([thumbnails, preview])
            thumbnails.width = None if compact else 240
            thumbnails.height = 88 if compact else None
            thumb_column.horizontal = compact
            gallery_body.content = compact_body if compact else wide_body
            thread_safe_ui.refresh(gallery_tab)

    gallery_tab.on_size_change = layout_changed
    gallery_tab.size_change_interval = 100
    return gallery_tab, _refresh
