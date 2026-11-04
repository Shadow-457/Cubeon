"""Compact catalogue tiles with a lazy, width-aware native grid."""
import flet as ft
from cubeon import thread_safe_ui
from cubeon.theme import RADIUS, attach_hover


def tile_grid():
    grid = ft.GridView(runs_count=3, child_aspect_ratio=3.6, spacing=12,
                       run_spacing=12, expand=True, cache_extent=128,
                       build_controls_on_demand=True, padding=0)
    grid._tile_width = 1080
    grid._tile_height = 432
    grid._tile_mode = True
    grid.on_capacity_change = None

    def resized(event):
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
    return grid


def layout_tiles(grid, compact=True):
    """Keep tiles 96 px high; empty/loading panels span the viewport."""
    grid._tile_mode = compact
    width = grid._tile_width
    columns = max(1, int((width + 12) // 352)) if compact else 1
    grid.runs_count = columns
    grid.child_aspect_ratio = max(1, (width - 12 * (columns - 1)) / columns) / (96 if compact else 400)


def tile_capacity(grid):
    columns = max(1, int((grid._tile_width + 12) // 352))
    rows = max(1, int((grid._tile_height + 12) // 108))
    return min(100, columns * rows)


def style_tile(tile, surface, border, hover):
    tile.bgcolor = surface
    tile.border = ft.border.Border.all(1, border)
    tile.border_radius = RADIUS
    tile.padding = 12
    tile.height = 96
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
        row.controls.append(ft.TextButton(data=data))
    button = row.controls[0]
    button.content = f'Installed ({count})' if destination == 'installed' else 'Browse'
    button.icon = ft.Icons.INVENTORY_2_OUTLINED if destination == 'installed' else ft.Icons.SEARCH_ROUNDED
    button.style = ft.ButtonStyle(color=color)
    button.on_click = lambda event: on_change(destination)
    thread_safe_ui.refresh(row)
