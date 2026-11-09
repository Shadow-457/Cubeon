"""Shared content-list states. Static placeholders add no idle animation work."""
import flet as ft
from cubeon import i18n
from cubeon.theme import (RADIUS, SURFACE_HI, TEXT, TEXT_DIM, FONT_BODY,
                          SPACE_SM, SPACE_MD, SPACE_LG, SPACE_XXL)


def skeleton_block(width=None, height=12, *, fill=None, expand=None, **kwargs):
    """A quiet, retained placeholder; callers own the real loading lifecycle."""
    return ft.Container(width=width, height=height, expand=expand,
                        bgcolor=fill or SURFACE_HI, border_radius=RADIUS,
                        ignore_interactions=True, data="content-skeleton", **kwargs)


def loading_rows(label="Loading…", count=3, *, fill=None):
    fill = fill or SURFACE_HI
    rows = []
    for _ in range(count):
        lines = ft.Column([
            ft.Row([ft.Container(height=12, expand=3, bgcolor=fill,
                                 border_radius=RADIUS), ft.Container(expand=2)]),
            ft.Row([ft.Container(height=8, expand=4, bgcolor=fill,
                                 border_radius=RADIUS), ft.Container(expand=1)]),
        ], spacing=SPACE_SM, expand=True)
        rows.append(ft.Container(
            content=ft.Row([
                ft.Container(width=48, height=48, bgcolor=fill, border_radius=RADIUS),
                lines,
                ft.Container(width=96, height=32, bgcolor=fill, border_radius=RADIUS),
            ], spacing=SPACE_LG),
            padding=ft.padding.Padding.symmetric(horizontal=SPACE_MD, vertical=SPACE_LG)))
    return ft.Column([ft.Text(i18n.t(label), size=12, color=TEXT_DIM, font_family=FONT_BODY), *rows],
                     spacing=SPACE_SM, data="content-loading")


def empty_state(title, hint, *, icon=ft.Icons.SEARCH_OFF_ROUNDED,
                action_label=None, on_action=None):
    controls = [ft.Icon(icon, size=32, color=TEXT_DIM),
                ft.Text(i18n.t(title), size=14, weight=ft.FontWeight.W_600, color=TEXT,
                        font_family=FONT_BODY, text_align=ft.TextAlign.CENTER),
                ft.Text(i18n.t(hint), size=12, color=TEXT_DIM, font_family=FONT_BODY,
                        text_align=ft.TextAlign.CENTER)]
    if action_label and on_action:
        controls.append(ft.TextButton(i18n.t(action_label), on_click=on_action))
    return ft.Container(
        content=ft.Column(controls, spacing=SPACE_SM,
                          horizontal_alignment=ft.CrossAxisAlignment.CENTER),
        padding=SPACE_XXL, alignment=ft.Alignment.CENTER, data="content-empty")
