"""Compact catalogue tiles with a lazy, width-aware native grid."""
import flet as ft
from cubeon import thread_safe_ui
from cubeon.theme import RADIUS, attach_hover, BORDER, SURFACE


def tile_grid(*, rows=False):
    grid = ft.GridView(runs_count=3, child_aspect_ratio=3.6, spacing=12,
                       run_spacing=12, expand=True, cache_extent=384,
                       build_controls_on_demand=True, padding=0)
    grid._tile_width = 1080
    grid._tile_height = 432
    grid._tile_mode = True
    grid._row_mode = rows
    grid.on_capacity_change = None

    def resized(event):
        ft.context.disable_auto_update()
        width = event.width
        height = event.height
        if not width or not height or (abs(width - grid._tile_width) < 1 and abs(height - grid._tile_height) < 1):
            return
        with thread_safe_ui.TREE_LOCK:
            previous = tile_capacity(grid)
            grid._tile_width = width
            grid._tile_height = height
            layout_tiles(grid, grid._tile_mode)
            capacity = tile_capacity(grid)
            if capacity != previous and grid.on_capacity_change:
                grid.on_capacity_change(capacity)
        thread_safe_ui.refresh(grid)

    grid.on_size_change = resized
    grid.size_change_interval = 100
    layout_tiles(grid)
    return grid


def layout_tiles(grid, compact=True):
    """Keep catalogue tiles 96 px and installed rows 76 px; notices span the viewport."""
    grid._tile_mode = compact
    width = grid._tile_width
    columns = max(1, int((width + 12) // 352)) if compact and not grid._row_mode else 1
    grid.runs_count = columns
    height = (76 if grid._row_mode else 96) if compact else 400
    grid.child_aspect_ratio = max(1, (width - 12 * (columns - 1)) / columns) / height


def tile_capacity(grid):
    columns = 1 if grid._row_mode else max(1, int((grid._tile_width + 12) // 352))
    rows = max(1, int((grid._tile_height + 12) // (88 if grid._row_mode else 108)))
    return min(100, columns * rows)


def loading_tiles(grid):
    """Reserve the same cells as real content, without a loading-only layout."""
    tiles = []
    for _ in range(tile_capacity(grid)):
        tile = ft.Container(
            ft.Row([
                ft.Container(width=44, height=44, bgcolor=BORDER, border_radius=RADIUS),
                ft.Column([
                    ft.Container(height=12, bgcolor=BORDER, border_radius=RADIUS),
                    ft.Container(height=8, width=96, bgcolor=BORDER, border_radius=RADIUS),
                ], spacing=8, expand=True, alignment=ft.MainAxisAlignment.CENTER),
                ft.Container(width=104, height=30, bgcolor=BORDER, border_radius=RADIUS),
            ], vertical_alignment=ft.CrossAxisAlignment.CENTER),
            data='content-loading', ignore_interactions=True,
        )
        tiles.append(style_tile(tile, SURFACE, BORDER, SURFACE,
                                height=76 if grid._row_mode else 96))
    return tiles


def style_tile(tile, surface, border, hover, *, height=96):
    tile.bgcolor = surface
    tile.border = ft.border.Border.all(1, border)
    tile.border_radius = RADIUS
    tile.padding = 12
    tile.height = height
    tile.content.spacing = 12
    return attach_hover(tile, surface, hover)


def downloads_label(count):
    count = count or 0
    for unit, divisor in (("B", 1_000_000_000), ("M", 1_000_000), ("K", 1_000)):
        if count >= divisor:
            return f"{count / divisor:.1f}{unit}"
    return f"{count:,}"


def content_header(subtitle, view_action, *actions):
    """One toolbar layout for every retained content destination."""
    return ft.Row([ft.Container(subtitle, expand=True), view_action, *actions],
                  spacing=12, height=46, vertical_alignment=ft.CrossAxisAlignment.CENTER)


def update_view_action(row, view, count, on_change, *, data, color):
    """Update the same action control; refreshes never remount the toolbar."""
    destination = 'installed' if view == 'browse' else 'browse'
    if not row.controls:
        row.controls.append(ft.TextButton(data=data, width=154, height=40))
    button = row.controls[0]
    button.content = f'Installed ({count})' if destination == 'installed' else 'Browse'
    button.icon = ft.Icons.INVENTORY_2_OUTLINED if destination == 'installed' else ft.Icons.SEARCH_ROUNDED
    button.style = ft.ButtonStyle(color=color)
    button.on_click = lambda event: on_change(destination)
    thread_safe_ui.refresh(row)
