"""Flet viewer for Minecraft screenshots."""

from __future__ import annotations

import threading

import flet as ft

from cubeon import dialogs
from cubeon import screenshot_gallery as store
from cubeon import thread_safe_ui
from cubeon.theme import (
    ACCENT, ACCENT_TINT, CARD_BORDER, CARD_FILL, DANGER,
    FONT_DISPLAY, FONT_MONO, INFO, RADIUS, ROW_HOVER, SURFACE, SURFACE_HI, SURFACE_MAX,
    TEXT, TEXT_DIM, TEXT_FAINT, attach_hover,
)

# A full screenshot decode is the expensive step (~100-200 ms for a
# 1920x1080 PNG). The first Images-pane open with N screenshots used to
# fire N concurrent decodes - saturating the CPU and flooding the loop
# with repaints as each one landed. Renders are now disk-cached
# (cubeon/screenshot_gallery.py), and the cache MISSES above stay bounded:
# at most this many decoding threads run at once.
_DECODE_POOL = threading.Semaphore(3)


def build_screenshot_gallery_tab(page: ft.Page) -> tuple[ft.Control, callable]:
    """Build the full-canvas screenshots tab and return its refresh callback."""
    state = {"items": [], "selected": None, "generation": 0,
             "thumb_generation": 0}
    thumb_refs = {}

    selected_image = ft.Image(
        src="icon.svg", width=620, height=430, fit=ft.BoxFit.CONTAIN,
        visible=False,
    )
    selected_empty = ft.Column(
        [
            ft.Icon(ft.Icons.IMAGE_OUTLINED, size=46, color=TEXT_FAINT),
            ft.Text("Select a screenshot", size=14, color=TEXT_DIM),
            ft.Text("Your Minecraft captures appear here", size=11,
                    color=TEXT_FAINT),
        ], spacing=8, tight=True,
        horizontal_alignment=ft.CrossAxisAlignment.CENTER,
    )
    selected_name = ft.Text("No screenshot selected", size=18, color=TEXT,
                            font_family=FONT_DISPLAY, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS)
    selected_meta = ft.Text("", size=11, color=TEXT_DIM)
    status = ft.Text("", size=11, color=TEXT_DIM)
    capture_count = ft.Text("0 captures", size=11, color=TEXT_DIM,
                            font_family=FONT_MONO)
    thumb_column = ft.Column(spacing=8, scroll=ft.ScrollMode.AUTO, expand=True)

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
        "Copy image",
        icon=ft.Icons.CONTENT_COPY_ROUNDED,
        icon_color=ACCENT,
        tooltip="Copy the selected screenshot",
        disabled=True,
        on_click=_copy_selected,
        data="screenshot-copy",
    )

    def _paint_selected_image(filename, generation):
        try:
            with _DECODE_POOL:
                encoded = store.image_base64(filename)
        except Exception as ex:
            if generation != state["generation"]:
                return
            status.value = f"Couldn't preview screenshot: {ex}"
            thread_safe_ui.refresh(status)
            return
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
        filename = item["filename"]
        state["selected"] = filename
        state["generation"] += 1
        generation = state["generation"]
        selected_name.value = item["name"]
        selected_meta.value = (
            f"{item['date']}  ·  {item['width']}×{item['height']}  ·  "
            f"{item['bytes'] / 1024:.0f} KB"
        )
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
                ], spacing=6, tight=True,
                   horizontal_alignment=ft.CrossAxisAlignment.CENTER),
                padding=18, alignment=ft.Alignment.CENTER,
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
            image = ft.Image(src="icon.svg", width=148, height=92,
                             fit=ft.BoxFit.CONTAIN, visible=False)
            loading = ft.ProgressRing(width=18, height=18, stroke_width=2,
                                      color=ACCENT)
            card = attach_hover(ft.Container(
                content=ft.Column([
                    ft.Container(
                        content=ft.Stack([image, loading],
                                         alignment=ft.Alignment.CENTER),
                        width=154, height=98, bgcolor=SURFACE_MAX,
                        alignment=ft.Alignment.CENTER,
                    ),
                    ft.Text(item["name"], size=10, color=TEXT,
                            max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ft.Text(item["date"], size=9, color=TEXT_FAINT,
                            max_lines=1),
                ], spacing=4, tight=True),
                width=170, padding=7, bgcolor=CARD_FILL,
                border=ft.border.Border.all(1, CARD_BORDER),
                border_radius=RADIUS, ink=False,
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

    def _refresh(e=None):
        status.value = "Scanning screenshots…"
        thread_safe_ui.refresh(status)
        items = store.list_screenshots()
        _render_list(items)
        capture_count.value = (f"{len(items)} capture"
                               + ("s" if len(items) != 1 else ""))
        status.value = (f"{len(state['items'])} screenshot"
                        + ("s" if len(state["items"]) != 1 else "")
                        + " found")
        thread_safe_ui.refresh(status)

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
                ft.TextButton("Cancel", on_click=_cancel),
                ft.TextButton("Delete", on_click=_confirm,
                              style=ft.ButtonStyle(color=DANGER)),
            ],
        )
        dialogs.open_dialog(page, confirm)

    def _open_folder(e=None):
        try:
            store.open_screenshots_folder()
            status.value = "Opened the screenshots folder."
        except Exception as ex:
            status.value = f"Couldn't open folder: {ex}"
        thread_safe_ui.refresh(status)

    gallery_header = ft.Row([
        ft.Container(
            content=ft.Row([
                ft.Container(
                    content=ft.Icon(ft.Icons.PHOTO_LIBRARY_OUTLINED,
                                    color=INFO, size=24),
                    width=42, height=42, bgcolor=SURFACE_HI,
                    border=ft.border.Border.all(1, CARD_BORDER),
                    border_radius=RADIUS, alignment=ft.Alignment.CENTER,
                ),
                ft.Column([
                    ft.Text("Minecraft screenshots", size=21, color=TEXT,
                            font_family=FONT_DISPLAY),
                    ft.Text("Your in-game captures, ready to browse.", size=11,
                            color=TEXT_DIM),
                ], spacing=3, expand=True),
                ft.Container(
                    content=ft.Row([
                        ft.Icon(ft.Icons.FILTER_NONE_ROUNDED, size=14,
                                color=ACCENT),
                        capture_count,
                    ], spacing=6, tight=True),
                    bgcolor=CARD_FILL,
                    border=ft.border.Border.all(1, CARD_BORDER),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=10, vertical=7),
                ),
            ], spacing=10),
            bgcolor=SURFACE,
            border=ft.border.Border.all(1, CARD_BORDER),
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
            expand=True,
        ),
        ft.IconButton(icon=ft.Icons.REFRESH_ROUNDED, icon_color=TEXT_DIM,
                      tooltip="Refresh", on_click=_refresh),
        ft.IconButton(icon=ft.Icons.FOLDER_OPEN_ROUNDED, icon_color=TEXT_DIM,
                      tooltip="Open screenshots folder", on_click=_open_folder),
    ])

    gallery_body = ft.Container(
        expand=True,
        content=ft.Row([
            ft.Container(
                width=215,
                content=ft.Column([
                    ft.Text("CAPTURES", size=10, color=ACCENT,
                            weight=ft.FontWeight.W_700,
                            style=ft.TextStyle(letter_spacing=1.0)),
                    thumb_column,
                ], spacing=8, expand=True),
                bgcolor=SURFACE,
                border=ft.border.Border.all(1, CARD_BORDER),
                border_radius=RADIUS,
                padding=ft.padding.Padding.all(12),
            ),
            ft.Container(
                expand=True,
                content=ft.Column([
                    ft.Container(
                        content=ft.Stack([selected_image, selected_empty],
                                         alignment=ft.Alignment.CENTER),
                        bgcolor=SURFACE_MAX,
                        border=ft.border.Border.all(1, CARD_BORDER),
                        border_radius=RADIUS,
                        expand=True,
                        alignment=ft.Alignment.CENTER,
                    ),
                    ft.Container(
                        content=ft.Column([
                            selected_name,
                            selected_meta,
                            ft.Row([
                                copy_button,
                                ft.Container(
                                    content=ft.Row([
                                        ft.Icon(ft.Icons.DELETE_OUTLINE_ROUNDED,
                                                size=15, color=DANGER),
                                        ft.Text("Delete", size=11, color=DANGER),
                                    ], spacing=5, tight=True),
                                    border=ft.border.Border.all(1, DANGER),
                                    border_radius=RADIUS,
                                    padding=ft.padding.Padding.symmetric(horizontal=10, vertical=7),
                                    ink=False, on_click=_delete_selected,
                                ),
                                ft.Container(expand=True),
                                status,
                            ], spacing=8),
                        ], spacing=5),
                        bgcolor=SURFACE,
                        border=ft.border.Border.all(1, CARD_BORDER),
                        border_radius=RADIUS,
                        padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
                    ),
                ], spacing=7, expand=True),
            ),
        ], spacing=14, expand=True),
    )

    gallery_tab = ft.Column(
        [gallery_header, ft.Container(height=12), gallery_body],
        spacing=0, expand=True,
    )
    return gallery_tab, _refresh
