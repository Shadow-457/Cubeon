
"""Wardrobe: shared native 3D preview and local Skin / Cape / Store /
Shoulder / Back / Head / Feet / Aura libraries.

Structure (one class per responsibility):

    Tokens             design tokens handed in by main.py
    Throttle/Debouncer small timing helpers (resize + search)
    StatusLine         fixed-height status text (never shifts the layout)
    Card               one tile (artwork, selection rim, manage menu)
    GridGeometry       one shared width/column calculation for every grid
    CardGrid           lazy native grid + thumbnail window
    ThumbnailService   PIL renders + memo      ThumbnailWorker  background drain
    Pane               base category pane
      LibraryPane -> SkinPane, CapePane       StorePane       CosmeticPane
    WardrobeHeader     category tabs + fixed-size action slot
    WardrobeLayout     responsive sizing (throttled, change-only)
    Wardrobe           controller that wires everything together

Uploads are stored locally and applied in-game when the corresponding
skin/cape mod is installed. Shoulder and back items are original Cubeon art
drawn by the Cubeon Client itself (see cubeon/cosmetics.py).
"""
from __future__ import annotations

import base64
import math
import os
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from io import BytesIO
from typing import Callable, Optional

import flet as ft

from cubeon import i18n
from cubeon.theme import (
    RADIUS,
    attach_hover,
    ACCENT_TINT, ACCENT_TINT_HI,
    text_tab,
    keyboard_target,
    CARD_FILL, CARD_BORDER,
    ROW_HOVER,
)
from cubeon import thread_safe_ui
from cubeon import cosmetics, cosmetics_store
from ui.appearance_preview import AppearancePreview
from ui.image_memory import preview_image
from ui.content_states import skeleton_block
from ui.chrome import TabEntryQueue, TabPane
import launcher_core as core

DEFAULT_CAPE_PREVIEW_SRC = "capes/cubeon_cape_preview.png"
DEFAULT_SKIN_PREVIEW_SRC = "skins/steve-preview.png"

# Low-res thumbnails: smaller renders, smaller files, smaller decoded bitmaps.
COSMETIC_THUMB_SIZE = (48, 48)   # was (64, 64)
SKIN_THUMB_SCALE = 2             # was 3
CAPE_THUMB_SCALE = 2             # was 3
THUMB_CACHE_WIDTH = 64           # max decode width Flutter keeps per tile

TILE_FILL = ft.Colors.with_opacity(0.6, ft.Colors.BLACK)
TILE_EDGE = ft.Colors.with_opacity(0.10, ft.Colors.WHITE)


# ---------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------

def tree_lock():
    return thread_safe_ui.TREE_LOCK


def ui_refresh(control):
    thread_safe_ui.refresh(control)


def _valid(value) -> bool:
    return bool(value) and math.isfinite(value) and value > 0


@dataclass(frozen=True)
class Tokens:
    bg: str
    surface: str
    surface_hi: str
    border: str
    accent: str
    accent_dim: str
    text: str
    text_dim: str
    danger: str
    font_display: str


class Throttle:
    """Leading + trailing throttle: runs at once, then at most every `interval`,
    always finishing with the latest state."""

    def __init__(self, interval: float, fn: Callable[[], None]):
        self._interval, self._fn = interval, fn
        self._lock = threading.Lock()
        self._last = 0.0
        self._timer: Optional[threading.Timer] = None

    def __call__(self):
        with self._lock:
            if self._timer is not None:       # a trailing run is already queued
                return
            wait = self._interval - (time.monotonic() - self._last)
            run_now = wait <= 0
            if run_now:
                self._last = time.monotonic()
            else:
                self._timer = threading.Timer(wait, self._fire)
                self._timer.daemon = True
                self._timer.start()
        if run_now:
            self._fn()

    def _fire(self):
        with self._lock:
            self._timer = None
            self._last = time.monotonic()
        self._fn()


class Debouncer:
    """Trailing-edge timer: only the last call inside `delay` runs."""

    def __init__(self, delay: float, fn: Callable[[], None]):
        self._delay, self._fn = delay, fn
        self._lock = threading.Lock()
        self._timer: Optional[threading.Timer] = None

    def __call__(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
            self._timer = threading.Timer(self._delay, self._fn)
            self._timer.daemon = True
            self._timer.start()

    def cancel(self):
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None


def make_action_button(tokens: Tokens, label, on_click, tooltip=None,
                       icon=ft.Icons.ADD_ROUNDED):
    return attach_hover(ft.Container(
        content=ft.Row([
            ft.Icon(icon, color=tokens.accent, size=18),
            ft.Text(label, color=tokens.accent, weight=ft.FontWeight.W_700, size=13),
        ], alignment=ft.MainAxisAlignment.CENTER, spacing=8, tight=True),
        bgcolor=ACCENT_TINT, border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(vertical=8, horizontal=12),
        alignment=ft.Alignment.CENTER, ink=False, tooltip=tooltip,
        on_click=on_click,
    ), ACCENT_TINT, ACCENT_TINT_HI)


class StatusLine:
    """Status text in a fixed-height slot: showing/hiding a message can never
    resize the grid below it (this was a source of the layout jumps)."""
    HEIGHT = 20

    def __init__(self, tokens: Tokens):
        self.text = ft.Text("", size=12, color=tokens.text_dim, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS)
        self.control = ft.Container(self.text, height=self.HEIGHT,
                                    alignment=ft.Alignment.CENTER_LEFT)

    @property
    def value(self) -> str:
        return self.text.value or ""

    def set(self, message: str = ""):
        with tree_lock():
            self.text.value = message or ""
            self.text.tooltip = message or None
        ui_refresh(self.text)


# ---------------------------------------------------------------------------
# cards
# ---------------------------------------------------------------------------

@dataclass
class ThumbJob:
    grid: "CardGrid"
    pane: str
    kind: str
    filename: str
    card: Optional["Card"] = None


class Card:
    """One tile. Clicking the artwork applies; the "..." menu manages."""
    WIDTH = 148

    def __init__(self, tokens: Tokens, *, label, sublabel="", active=False,
                 on_use, on_delete=None, src=None, thumb=None, icon=None,
                 preview_size=(88, 128), model_label=None, on_model=None,
                 action_label="Apply"):
        t = self.tokens = tokens
        w, h = preview_size
        decode_width = min(w, THUMB_CACHE_WIDTH)
        self.selected: Optional[bool] = None
        self.entry: Optional[dict] = None
        self._on_use = on_use
        if src:
            self.image = preview_image(src=src, width=w, height=h,
                                       fit=ft.BoxFit.CONTAIN,
                                       cache_width=decode_width,
                                       filter_quality=ft.FilterQuality.LOW)
            self.placeholder = None
        elif thumb:
            self.image = preview_image(src="icon.svg", width=w, height=h,
                                       fit=ft.BoxFit.CONTAIN,
                                       cache_width=decode_width,
                                       filter_quality=ft.FilterQuality.LOW,
                                       visible=False)
            self.placeholder = skeleton_block(w, h, fill=t.border)
        else:
            self.image = None
            self.placeholder = ft.Icon(icon or ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED,
                                       color=t.text_dim, size=22)
        self.thumb_job = ThumbJob(*thumb, card=self) if thumb and not src else None
        self._name = ft.Text(label, size=12, color=t.text, weight=ft.FontWeight.W_500,
                             max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                             text_align=ft.TextAlign.CENTER)
        self._subtitle = ft.Text(sublabel, size=10, color=t.text_dim, max_lines=1,
                                 overflow=ft.TextOverflow.ELLIPSIS,
                                 text_align=ft.TextAlign.CENTER, visible=bool(sublabel))
        self._check = ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, color=t.accent, size=16,
                              left=2, top=2, visible=active)
        stack = [c for c in (self.image, self.placeholder) if c is not None]
        artwork = ft.Stack([
            ft.Container(content=ft.Row(stack, spacing=0,
                                        alignment=ft.MainAxisAlignment.CENTER),
                         height=h + 12, alignment=ft.Alignment.CENTER),
            self._check,
        ])
        primary = ft.Container(
            content=ft.Column([artwork, self._name, self._subtitle], spacing=5,
                              horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            padding=8, border_radius=RADIUS, ink=False,
            tooltip=f"{action_label} {label}" + (f" ({sublabel})" if sublabel else ""),
            on_click=self._apply,
            on_hover=lambda e: self.control.on_hover(e),
        )
        menu = []
        if model_label:
            menu.append(ft.PopupMenuItem(
                content=ft.Text(f"Arms: {model_label}", size=12, color=t.text),
                icon=ft.Icons.ACCESSIBILITY_NEW_ROUNDED, on_click=on_model,
                tooltip="Change arms: Auto → Alex (3 px) → Steve (4 px)"))
        if on_delete is not None:
            menu.append(ft.PopupMenuItem(
                content=ft.Text(i18n.t("Delete"), size=12, color=t.danger),
                icon=ft.Icons.DELETE_OUTLINE_ROUNDED, on_click=on_delete,
                tooltip=i18n.t("Delete")))
        contents = [keyboard_target(primary, primary.tooltip)]
        if menu:
            contents.append(ft.PopupMenuButton(
                items=menu, icon=ft.Icons.MORE_HORIZ_ROUNDED, icon_size=16,
                icon_color=t.text_dim, bgcolor=t.surface_hi, width=30, height=30,
                padding=4, right=4, top=4, tooltip=f"Manage {label}"))
        self.control = ft.Container(
            content=ft.Stack(contents), width=self.WIDTH,
            bgcolor=ACCENT_TINT if active else TILE_FILL,
            border=ft.border.Border.all(1, t.accent if active else TILE_EDGE),
            border_radius=RADIUS, padding=4)
        self.set_selected(active)

    def _apply(self, e):
        ft.context.disable_auto_update()
        with tree_lock():
            already = self.selected
        if not already:
            self._on_use(e)

    def set_selected(self, value) -> bool:
        value = bool(value)
        if self.selected is value:
            return False
        self.selected = value
        t = self.tokens
        self._check.visible = value
        self._name.color = t.accent if value else t.text
        c = self.control
        c.bgcolor = ACCENT_TINT if value else TILE_FILL
        c.border = ft.border.Border.all(1, t.accent if value else TILE_EDGE)
        attach_hover(c, c.bgcolor, ACCENT_TINT_HI if value else ROW_HOVER)
        return True

    def set_sublabel(self, value) -> bool:
        value = value or ""
        if self._subtitle.value == value and self._subtitle.visible == bool(value):
            return False
        self._subtitle.value = value
        self._subtitle.visible = bool(value)
        return True

    def set_thumb(self, b64):
        self.image.src = b64
        self.image.visible = True
        self.placeholder.visible = False

    def mark_failed(self):
        ph = self.placeholder
        ph.bgcolor = None
        ph.data = "content-artwork-unavailable"
        ph.content = ft.Icon(ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED,
                             color=self.tokens.text_dim, size=22)
        ph.alignment = ft.Alignment.CENTER


# ---------------------------------------------------------------------------
# grids
# ---------------------------------------------------------------------------

class GridGeometry:
    """One width for every grid in the picker. A pane that was hidden while the
    window resized (or never shown) already has the right columns when it opens."""
    DEFAULT_WIDTH = 480

    def __init__(self):
        self.width = self.DEFAULT_WIDTH
        self.grids: list[CardGrid] = []
        self.measured = False
        self.on_measured: Optional[Callable[[], None]] = None
        self.on_window_change: Optional[Callable[[], None]] = None

    def register(self, grid: "CardGrid"):
        self.grids.append(grid)

    def set_width(self, width, source: "CardGrid") -> bool:
        """Share a measured width; True when `source` needs a repaint."""
        if self.measured and width == self.width:
            return False
        self.width = width
        repaint = False
        for grid in self.grids:
            changed = grid.fit(width)
            if grid is source:
                repaint = changed
        if not self.measured:
            self.measured = True
            if self.on_measured:
                self.on_measured()
        return repaint

    def window_changed(self):
        if self.on_window_change:
            self.on_window_change()


class CardGrid:
    """Native lazy grid with fixed-height cards and a thumbnail window."""
    CELL_MIN, GAP, MAX_COLUMNS = 168, 12, 6
    RATIO_TOLERANCE = 0.004      # ignore sub-pixel ratio changes while dragging

    def __init__(self, geometry: GridGeometry, card_height=224):
        self.geometry = geometry
        self.card_height = card_height
        self.viewport_height = 320
        self.scroll_pixels = 0
        self.thumb_window: set[int] = set()
        self._cards: list[Card] = []
        self._by_id: dict[int, Card] = {}
        self.view = ft.GridView(
            spacing=self.GAP, run_spacing=self.GAP, expand=True, padding=0,
            scroll=ft.ScrollMode.AUTO, cache_extent=card_height + self.GAP,
            build_controls_on_demand=True, scroll_interval=80,
            on_scroll=self._scrolled, on_size_change=self._resized,
            size_change_interval=60, data="cosmetics-picker-scroll")
        self.fit()

    # -- contents ---------------------------------------------------------
    @property
    def cards(self) -> list[Card]:
        return self._cards

    def contains(self, card: Card) -> bool:
        return id(card) in self._by_id

    def _sync(self):
        self._by_id = {id(c): c for c in self._cards}
        self.view.controls = [c.control for c in self._cards]

    def set_cards(self, cards):
        self._cards = list(cards)
        self._sync()
        self.update_window()

    def append(self, card: Card):
        self._cards.append(card)
        self._by_id[id(card)] = card
        self.view.controls.append(card.control)

    def remove(self, card: Card):
        self._cards.remove(card)
        self._sync()
        self.update_window()

    def clear(self):
        self._cards = []
        self._by_id.clear()
        self.view.controls = []
        self.thumb_window = set()

    def refresh(self):
        ui_refresh(self.view)

    def window_cards(self) -> tuple[Card, ...]:
        if not self.thumb_window:
            return ()
        by_id = self._by_id
        return tuple(by_id[i] for i in self.thumb_window if i in by_id)

    # -- geometry ---------------------------------------------------------
    def fit(self, width=None) -> bool:
        """Recompute columns/ratio. True only if something visible changed."""
        width = width if _valid(width) else self.geometry.width
        if not _valid(width):
            return False
        columns = max(1, min(self.MAX_COLUMNS,
                             int((width + self.GAP) / (self.CELL_MIN + self.GAP))))
        card_width = (width - self.GAP * (columns - 1)) / columns
        ratio = round(card_width / self.card_height, 3)
        current = self.view.child_aspect_ratio or 0
        changed = (self.view.runs_count != columns
                   or abs(current - ratio) > self.RATIO_TOLERANCE)
        if changed:
            self.view.runs_count = columns
            self.view.child_aspect_ratio = ratio
        self.update_window()
        return changed

    def update_window(self) -> bool:
        """Visible rows plus one neighbouring row get thumbnails.
        O(visible window) — never walks the full card list."""
        stride = self.card_height + self.GAP
        columns = self.view.runs_count or 1
        first = max(0, int(self.scroll_pixels // stride) - 1) * columns
        stop = (math.ceil((self.scroll_pixels + self.viewport_height) / stride) + 1) * columns
        # Cards are never hidden in this picker, so slicing is equivalent to
        # filtering by `control.visible` but avoids the full-list walk.
        window = {id(c) for c in self._cards[first:stop]}
        changed = window != self.thumb_window
        if changed:
            self.thumb_window = window
        return changed

    # -- events -----------------------------------------------------------
    def _resized(self, event):
        ft.context.disable_auto_update()
        with tree_lock():
            if _valid(getattr(event, "height", None)):
                self.viewport_height = event.height
            repaint = (self.geometry.set_width(event.width, self)
                       if _valid(getattr(event, "width", None)) else False)
            window = self.update_window()
        if repaint:
            ui_refresh(self.view)
        if repaint or window:
            self.geometry.window_changed()

    def _scrolled(self, event):
        ft.context.disable_auto_update()
        with tree_lock():
            self.scroll_pixels = max(0, event.pixels)
            changed = self.update_window()
        if changed:
            self.geometry.window_changed()


# ---------------------------------------------------------------------------
# thumbnails
# ---------------------------------------------------------------------------

class ThumbnailService:
    """Low-res thumbnail rendering with a small bounded in-memory memo."""
    MEMO_LIMIT = 96              # was 192 (plus a second 96-entry file cache)

    def __init__(self, cosmetics_dir):
        self._dir = cosmetics_dir
        self._memo: OrderedDict[tuple, str] = OrderedDict()
        self._lock = threading.Lock()

    def cached(self, kind, key):
        memo_key = (kind, key)
        with self._lock:
            value = self._memo.get(memo_key)
            if value is not None:
                self._memo.move_to_end(memo_key)
            return value

    def forget(self, kind, key):
        with self._lock:
            self._memo.pop((kind, key), None)

    def _remember(self, kind, key, b64):
        memo_key = (kind, key)
        with self._lock:
            self._memo[memo_key] = b64
            self._memo.move_to_end(memo_key)
            while len(self._memo) > self.MEMO_LIMIT:
                self._memo.popitem(last=False)

    @staticmethod
    def _read_b64(path):
        try:
            with open(path, "rb") as f:
                return base64.b64encode(f.read()).decode("ascii")
        except Exception:
            return None

    def render(self, kind, key):
        hit = self.cached(kind, key)
        if hit is not None:
            return hit
        if kind == "cosmetic":
            return self._render_cosmetic(key)
        if kind == "skin":
            folder = core.SKINS_DIR
            entry = next(
                (s for s in core.list_custom_skins() if s.get("filename") == key),
                {},
            )
            scale = SKIN_THUMB_SCALE
            variant = f"s{scale}_" + ("alex_" if entry.get("slim") else "steve_")
            suffix = "png"
            src = os.path.join(folder, key)
        else:
            folder = core.CAPES_DIR
            entry = next(
                (c for c in core.list_capes() if c.get("filename") == key),
                {},
            )
            scale = CAPE_THUMB_SCALE
            variant = f"s{scale}_"
            suffix = "gif" if entry.get("animated") else "png"
            src = core.get_cape_path(key)

        # Keep the "_thumb_" prefix (the library listing may filter on it).
        # The "s2_" tag forces a one-time re-render at the smaller scale
        # instead of reusing the old 3x files.
        out = os.path.join(folder, f"_thumb_{variant}{key}.{suffix}")
        try:
            # An up-to-date thumb file on disk IS the render.
            fresh = os.path.exists(out) and os.path.getmtime(out) >= os.path.getmtime(src)
            if not fresh:
                if kind == "skin":
                    core.render_local_skin_preview(key, out, scale=scale)
                else:
                    core.render_cape_preview(key, out, scale=scale)
            b64 = self._read_b64(out)
            if b64:
                self._remember(kind, key, b64)
            return b64
        except Exception:
            return None

    def _render_cosmetic(self, item_id):
        item = cosmetics.get(item_id, self._dir)
        if item is None:
            return None
        try:
            image = cosmetics.render_thumbnail(item, self._dir,
                                               size=COSMETIC_THUMB_SIZE, simplify=True)
            buffer = BytesIO()
            image.save(buffer, format="PNG", compress_level=1)   # faster encode
            b64 = base64.b64encode(buffer.getvalue()).decode("ascii")
        except Exception:
            return None
        self._remember("cosmetic", item_id, b64)
        return b64


class ThumbnailWorker:
    """One draining thread; only currently visible thumbnails are queued."""

    def __init__(self, geometry: GridGeometry, service: ThumbnailService,
                 active_pane: Callable[[], str]):
        self._geometry, self._service = geometry, service
        self.active_pane = active_pane
        self._pending: list[ThumbJob] = []
        self._running = False

    def _attached(self, job):
        return job.grid.contains(job.card)

    def _visible(self, job):
        return (
            job.pane == self.active_pane()
            and job.card.control.visible
            and id(job.card) in job.grid.thumb_window
        )

    def _collect(self):
        # tree lock held. Queue only the visible window of the open pane.
        active = self.active_pane()
        for grid in self._geometry.grids:
            for card in grid.window_cards():
                job = card.thumb_job
                if job is not None and job.pane == active and card.control.visible:
                    card.thumb_job = None
                    self._pending.append(job)
        if self._pending:
            self._pending[:] = [j for j in self._pending if self._attached(j)]

    def _restore_pending(self):
        # tree lock held. Put unfinished visible jobs back on their cards so
        # a later flush() picks them up; nothing invisible stays queued in RAM.
        for job in self._pending:
            if self._attached(job) and job.card.thumb_job is None:
                job.card.thumb_job = job
        self._pending.clear()

    def flush(self):
        with tree_lock():
            self._collect()
            if self._running:
                return
            if not any(self._visible(j) for j in self._pending):
                return
            self._running = True
        threading.Thread(target=self._drain, daemon=True,
                         name="ux-thumb-render").start()

    def _drain(self):
        try:
            while True:
                with tree_lock():
                    index = next(
                        (i for i, j in enumerate(self._pending)
                         if self._attached(j) and self._visible(j)),
                        None,
                    )
                    if index is None:
                        self._restore_pending()
                        self._running = False
                        return
                    job = self._pending.pop(index)
                b64 = self._service.render(job.kind, job.filename)
                with tree_lock():
                    if not self._attached(job):
                        continue
                    if b64:
                        job.card.set_thumb(b64)
                    else:
                        job.card.mark_failed()
                    repaint = self._visible(job)
                if repaint:
                    ui_refresh(job.card.control)
        except Exception:
            pass
        finally:
            with tree_lock():
                if self._running:
                    self._restore_pending()
                    self._running = False


# ---------------------------------------------------------------------------
# shared context
# ---------------------------------------------------------------------------

class Context:
    """Everything a pane needs; passed instead of closing over 40 locals."""

    def __init__(self, page, cfg, tokens, appearance, mc_version, mc_loader):
        self.page, self.cfg, self.tokens = page, cfg, tokens
        self.appearance = appearance
        self.mc_version, self.mc_loader = mc_version, mc_loader
        self.geometry = GridGeometry()
        self.thumbs = ThumbnailService(appearance.cosmetics_dir)
        self.worker: ThumbnailWorker  # set by Wardrobe (needs the active pane)
        self.on_header_changed: Callable[[], None] = lambda: None

    def new_grid(self, card_height=224) -> CardGrid:
        grid = CardGrid(self.geometry, card_height)
        self.geometry.register(grid)
        return grid

    def repaint_preview(self):
        self.appearance.refresh(invalidate=True)


# ---------------------------------------------------------------------------
# panes
# ---------------------------------------------------------------------------

class Pane:
    id = ""
    label = ""
    target_yaw: Optional[float] = None   # preview rotation on entry (None = keep)

    def __init__(self, ctx: Context):
        self.ctx = ctx
        self.view: ft.Control = None
        self.header_action: Optional[ft.Control] = None

    def load(self) -> bool:
        """Called on tab entry. Return False if nothing changed (skip repaint)."""
        return False


class LibraryPane(Pane):
    """Local file library with upload: shared by Skin and Cape."""
    kind = ""
    config_key = ""
    fixed_keys: tuple = ()
    upload_label = ""
    picker_title = ""
    extensions: tuple = ()

    def __init__(self, ctx: Context, picker):
        super().__init__(ctx)
        self.id = self.kind
        self.picker = picker
        self.grid = ctx.new_grid()
        self.status = StatusLine(ctx.tokens)
        self.cards: dict = {}
        self.upload_button = make_action_button(
            ctx.tokens, self.upload_label, self.open_picker, self.tooltip())
        self.header_action = keyboard_target(self.upload_button, self.upload_label)
        picker.on_result = lambda e: self.handle_files(e.files)
        self.view = ft.Column([self.grid.view, self.status.control], spacing=12,
                              expand=True,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    # -- hooks ------------------------------------------------------------
    def tooltip(self) -> str: return ""
    def entries(self) -> list: raise NotImplementedError
    def is_current(self, filename) -> bool: raise NotImplementedError
    def is_selected(self, key) -> bool: raise NotImplementedError
    def set_active_backend(self, filename): raise NotImplementedError
    def add_backend(self, path, name): raise NotImplementedError
    def delete_backend(self, filename): raise NotImplementedError
    def make_fixed_card(self, key) -> Card: raise NotImplementedError
    def make_entry_card(self, entry) -> Card: raise NotImplementedError

    def thumb_args(self, filename):
        cached = self.ctx.thumbs.cached(self.kind, filename)
        return dict(src=cached,
                    thumb=None if cached else (self.grid, self.kind, self.kind, filename))

    # -- lifecycle --------------------------------------------------------
    def load(self):
        first = not self.cards
        if first:
            self.refresh_cards()
        return first

    def refresh_cards(self):
        entries = self.entries()
        names = {e["filename"] for e in entries}
        with tree_lock():
            for key in [k for k in self.cards
                        if k not in self.fixed_keys and k not in names]:
                del self.cards[key]
            for key in self.fixed_keys:
                if key not in self.cards:
                    self.cards[key] = self.make_fixed_card(key)
            for entry in entries:
                name = entry["filename"]
                card = self.cards.get(name)
                if card is None or card.entry != entry:
                    card = self.make_entry_card(entry)
                    card.entry = dict(entry)
                    self.cards[name] = card
            self.grid.set_cards([self.cards[k] for k in self.fixed_keys]
                                + [self.cards[e["filename"]] for e in entries])
            self.sync_selection()
            self.grid.fit()
        self.ctx.worker.flush()

    def sync_selection(self):
        with tree_lock():
            for key, card in self.cards.items():
                card.set_selected(self.is_selected(key))

    # -- actions ----------------------------------------------------------
    def activate(self, filename) -> bool:
        if self.is_current(filename):
            return True
        try:
            self.set_active_backend(filename)
        except Exception as ex:
            self.status.set(f"Couldn't switch {self.kind}: {ex}")
            return False
        self.ctx.repaint_preview()
        self.sync_selection()
        self.grid.refresh()
        self.status.set("")
        return True

    def delete(self, filename):
        ft.context.disable_auto_update()
        try:
            if self.ctx.cfg.get(self.config_key) == filename:
                self.set_active_backend(None)
                self.ctx.repaint_preview()
            self.delete_backend(filename)
            core.forget_file(self.kind, filename)
        except Exception as ex:
            self.status.set(f"Couldn't delete: {ex}")
            return
        self.ctx.thumbs.forget(self.kind, filename)
        self.refresh_cards()
        self.grid.refresh()

    def open_picker(self, e=None):
        core.run_file_picker(
            self.ctx.page, self.picker, on_files=self.handle_files,
            dialog_title=self.picker_title, allow_multiple=False,
            allowed_extensions=list(self.extensions))

    def handle_files(self, files):
        if not files:
            return
        picked = files[0]
        with tree_lock():
            if self.upload_button.disabled:
                return
            self.upload_button.disabled = True
        self.status.set("Uploading...")
        ui_refresh(self.upload_button)
        threading.Thread(target=self._upload, args=(picked,), daemon=True,
                         name=f"ux-{self.kind}-upload").start()

    def _upload(self, picked):
        try:
            entry = self.add_backend(picked.path, os.path.splitext(picked.name)[0])
            applied = self.activate(entry["filename"])
            self.refresh_cards()
            self.grid.refresh()
            message = (f"Uploaded and set '{entry['name']}' as active {self.kind}."
                       if applied else self.status.value)
        except ValueError as error:
            message = str(error)
        except Exception as error:
            message = f"Upload failed: {error}"
        with tree_lock():
            self.upload_button.disabled = False
        self.status.set(message)
        ui_refresh(self.upload_button)


class SkinPane(LibraryPane):
    kind, label, config_key = "skin", "Skin", "active_skin"
    fixed_keys = (None,)
    upload_label = "Upload skin"
    picker_title = "Choose a skin PNG (64x64)"
    extensions = ("png",)

    def tooltip(self):
        loader, version = self.ctx.mc_loader, self.ctx.mc_version
        if loader not in core.MOD_CAPABLE_LOADERS or not version:
            return ("Pick a mod loader (Fabric) on the Play tab. Offline "
                    "Minecraft can't show a custom skin without one.")
        if core.skin_mod_installed(version, loader):
            return ("Working. Only you see your own skin for now. Your Cubeon "
                    "cape is what other Cubeon players see.")
        return ("Skin support installs automatically the next time you press "
                "Play, then your skin shows up in-game.")

    def entries(self): return core.list_custom_skins()
    def is_current(self, fn): return self.ctx.cfg.get("active_skin") == fn
    def is_selected(self, key): return self.ctx.cfg.get("active_skin") == key
    def set_active_backend(self, fn): core.set_active_skin(self.ctx.cfg, fn)
    def add_backend(self, path, name): return core.add_custom_skin(path, name, model="auto")
    def delete_backend(self, fn): core.delete_custom_skin(fn)

    def make_fixed_card(self, key):
        return Card(self.ctx.tokens, src=DEFAULT_SKIN_PREVIEW_SRC, label="Steve",
                    sublabel="Default Minecraft skin",
                    active=not self.ctx.cfg.get("active_skin"),
                    on_use=lambda e: self.activate(None), on_delete=None)

    def make_entry_card(self, entry):
        fn = entry["filename"]
        model = entry.get("model")
        model_label = ("Alex · 3 px" if model == "slim" else
                       "Steve · 4 px" if model == "classic" else
                       "Auto · " + ("Alex" if entry.get("slim") else "Steve"))
        return Card(
            self.ctx.tokens, label=entry["name"] + (" (slim)" if entry.get("slim") else ""),
            active=self.is_selected(fn),
            on_use=lambda e, f=fn: self.activate(f),
            on_delete=lambda e, f=fn: self.delete(f),
            model_label=model_label, on_model=lambda e, f=fn: self.change_arms(f),
            **self.thumb_args(fn))

    def change_arms(self, filename):
        ft.context.disable_auto_update()
        entry = next((s for s in core.list_custom_skins()
                      if s.get("filename") == filename), None)
        if entry is None:
            return
        choices = ("auto", "slim", "classic")
        current = entry.get("model", "auto")
        wanted = choices[(choices.index(current) + 1) % 3] if current in choices else "auto"
        try:
            if not core.set_skin_model(self.ctx.cfg, filename, wanted):
                raise ValueError("Skin no longer exists")
            self.ctx.thumbs.forget("skin", filename)
            if self.ctx.cfg.get("active_skin") == filename:
                self.ctx.repaint_preview()
            self.refresh_cards()
            message = "Arm model updated. Restart Minecraft to apply it in-game."
        except Exception as ex:
            message = f"Couldn't change arms: {ex}"
        self.status.set(message)
        self.grid.refresh()


class CapePane(LibraryPane):
    kind, label, config_key = "cape", "Cape", "active_cape"
    fixed_keys = ("__hidden__", None)
    target_yaw = 180
    upload_label = "Upload cape"
    picker_title = "Choose a cape image or GIF"
    extensions = ("png", "jpg", "jpeg", "webp", "gif", "bmp")

    def tooltip(self):
        return ("Upload an image or animated GIF up to 8 MB.\n"
                "Your custom cape replaces the shared Cubeon cape in-game; "
                "friends still see the shared one on you for now.")

    def entries(self): return core.list_capes()
    def _hidden(self): return bool(self.ctx.cfg.get("hide_cubeon_cape"))

    def is_current(self, fn):
        return self.ctx.cfg.get("active_cape") == fn and not self._hidden()

    def is_selected(self, key):
        if key == "__hidden__":
            return self._hidden()
        return not self._hidden() and self.ctx.cfg.get("active_cape") == key

    def set_active_backend(self, fn): core.set_active_cape(self.ctx.cfg, fn)
    def add_backend(self, path, name): return core.add_custom_cape(path, name)
    def delete_backend(self, fn): core.delete_custom_cape(fn)

    def make_fixed_card(self, key):
        t = self.ctx.tokens
        if key == "__hidden__":
            return Card(t, icon=ft.Icons.BLOCK_ROUNDED, label="None",
                        sublabel="No cape on your screen", active=self._hidden(),
                        on_use=lambda e: self.hide(), on_delete=None)
        return Card(t, src=DEFAULT_CAPE_PREVIEW_SRC, label="Cubeon Cape",
                    sublabel="Default",
                    active=not self.ctx.cfg.get("active_cape") and not self._hidden(),
                    on_use=lambda e: self.activate(None), on_delete=None)

    def make_entry_card(self, entry):
        fn = entry["filename"]
        animated = entry.get("animated")
        sub = (("Built-in · Animated" if animated else "Built-in") if entry.get("builtin")
               else "Animated GIF" if animated else "")
        return Card(
            self.ctx.tokens, label=entry["name"], sublabel=sub,
            active=self.is_selected(fn),
            on_use=lambda e, f=fn: self.activate(f),
            on_delete=None if entry.get("builtin") else (lambda e, f=fn: self.delete(f)),
            **self.thumb_args(fn))

    def hide(self):
        try:
            core.set_hide_cubeon_cape(self.ctx.cfg, True)
        except Exception as ex:
            self.status.set(f"Couldn't hide the cape: {ex}")
            return
        self.ctx.repaint_preview()
        self.sync_selection()
        self.grid.refresh()
        # The shared cape is assigned server-side, so this only hides it locally.
        self.status.set("Cape hidden on your screen. Friends still see "
                        "your shared Cubeon cape.")


class StorePane(Pane):
    """Public cosmetics catalogue. Fetched on first open or Refresh only."""
    id, label = "store", "Store"
    DESTINATION = {"cape": "Cape", "pet": "Pets", "wing": "Back", "head": "Head",
                   "feet": "Feet", "aura": "Aura"}

    def __init__(self, ctx: Context, capes: CapePane):
        super().__init__(ctx)
        t = ctx.tokens
        self.capes = capes
        self.grid = ctx.new_grid()
        self.status = StatusLine(t)
        self.page_label = ft.Text("Page 1", size=12, color=t.text_dim)
        self.loaded = self.loading = self.more = False
        self.offset = self.request = 0
        self.signature = None
        self.query = ""
        self.downloads: set = set()
        self.cards: dict[str, Card] = {}
        self.items: dict[str, dict] = {}
        self._search_timer = Debouncer(.2, lambda: self.fetch(0))
        self.search = ft.TextField(
            hint_text="Search cosmetics…", prefix_icon=ft.Icons.SEARCH_ROUNDED,
            border_color=CARD_BORDER, focused_border_color=t.accent_dim, color=t.text,
            hint_style=ft.TextStyle(color=t.text_dim, size=13),
            text_style=ft.TextStyle(size=13), bgcolor=CARD_FILL, border_radius=RADIUS,
            height=40, dense=True,
            content_padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
            on_change=self._search_changed, on_submit=self._search_submitted,
            expand=True, data="cosmetics-store-search")
        self.refresh_button = ft.IconButton(
            ft.Icons.REFRESH_ROUNDED, tooltip="Refresh cosmetics",
            on_click=lambda e: self.fetch(force=True))
        self.previous = ft.IconButton(
            ft.Icons.CHEVRON_LEFT_ROUNDED, tooltip="Previous store page", disabled=True,
            on_click=lambda e: self.fetch(self.offset - cosmetics_store.PAGE_SIZE))
        self.next = ft.IconButton(
            ft.Icons.CHEVRON_RIGHT_ROUNDED, tooltip="Next store page", disabled=True,
            on_click=lambda e: self.fetch(self.offset + cosmetics_store.PAGE_SIZE))
        self.toolbar = ft.Column(
            [ft.Row([self.search, self.refresh_button], spacing=8),
             ft.Row([self.page_label, ft.Container(expand=True), self.previous, self.next],
                    spacing=4)],
            spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.view = ft.Column([self.toolbar, self.grid.view, self.status.control],
                              spacing=8, expand=True, data="cosmetics-store",
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def load(self):
        self.fetch()
        return False

    # -- state ------------------------------------------------------------
    def _sync_buttons(self):
        busy = self.loading or bool(self.downloads)
        self.refresh_button.disabled = busy
        self.previous.disabled = busy or self.offset == 0
        self.next.disabled = busy or not self.more
        self.search.disabled = bool(self.downloads)
        self.page_label.value = f"Page {self.offset // cosmetics_store.PAGE_SIZE + 1}"

    def sync_ownership(self, store_id):
        """Re-evaluate a card's Downloaded state (after a delete elsewhere)."""
        meta, card = self.items.get(store_id), self.cards.get(store_id)
        if meta is None or card is None:
            return None
        owned = cosmetics_store.installed(meta) is not None
        with tree_lock():
            card.set_selected(owned)
            card.set_sublabel("Downloaded" if owned else "Free cosmetic")
        return card.control

    # -- search -----------------------------------------------------------
    def _search_changed(self, e=None):
        ft.context.disable_auto_update()
        with tree_lock():
            self.request += 1          # invalidate any in-flight result
            self.loading = False
            self._sync_buttons()
        self._search_timer()
        ui_refresh(self.toolbar)

    def _search_submitted(self, e=None):
        ft.context.disable_auto_update()
        self._search_timer.cancel()
        self.fetch(0)

    # -- download ---------------------------------------------------------
    def download(self, item):
        with tree_lock():
            if self.loading or item["id"] in self.downloads:
                return
            self.request += 1          # a background refresh must not replace cards
            self.downloads.add(item["id"])
            card = self.cards[item["id"]]
            card.control.disabled = True
            card.set_sublabel("Downloading…")
            self._sync_buttons()
        ui_refresh(card.control)
        ui_refresh(self.toolbar)
        self.status.set(f"Downloading {item['name']}…")
        threading.Thread(target=self._download_worker, args=(item, card), daemon=True,
                         name="cubeon-store-download").start()

    def _download_worker(self, item, card):
        try:
            cosmetics_store.download(item)
            destination = self.DESTINATION[item["kind"]]
            message, success = f"Downloaded {item['name']}. Open {destination} to equip it.", True
        except Exception as error:
            message, success = f"Couldn't download this cosmetic: {error}", False
        if success and item["kind"] == "cape":
            self.capes.refresh_cards()
        with tree_lock():
            self.downloads.discard(item["id"])
            card.control.disabled = False
            card.set_selected(success)
            card.set_sublabel("Downloaded" if success else "Free cosmetic")
            self._sync_buttons()
        ui_refresh(card.control)
        ui_refresh(self.toolbar)
        if success and item["kind"] == "cape":
            self.capes.grid.refresh()
        self.status.set(message)

    # -- catalogue --------------------------------------------------------
    def fetch(self, offset=None, *, force=False):
        with tree_lock():
            query = (self.search.value or "").strip()
            if self.downloads or (self.loading and query == self.query):
                return
            if self.loaded and offset is None and not force and query == self.query:
                return
            requested = (0 if query != self.query
                         else self.offset if offset is None else offset)
            self.request += 1
            request = self.request
            self.query = query
            self.loading = True
            self._sync_buttons()
        ui_refresh(self.toolbar)
        self.status.set("Loading cosmetics…")
        threading.Thread(target=self._fetch_worker,
                         args=(request, requested, query, force), daemon=True,
                         name="cubeon-store-catalog").start()

    def _fetch_worker(self, request, requested, query, force):
        try:
            if query:
                saved = cosmetics_store.cached_catalog()
                recent = None if force else cosmetics_store.cached_catalog(max_age=60, bundled=False)
                cached = cosmetics_store.search_page(saved, query, requested) if saved else None
                fresh = cosmetics_store.search_page(recent, query, requested) if recent else None
            else:
                cached = cosmetics_store.cached_page(requested)
                fresh = None if force else cosmetics_store.cached_page(
                    requested, max_age=60, bundled=False)
        except Exception:
            cached = fresh = None
        if cached is not None:
            self._paint(request, requested, query, cached,
                        "" if fresh is not None else "Updating cosmetics…")
        if fresh is not None:
            return
        try:
            data = (cosmetics_store.search_page(
                        cosmetics_store.fetch_catalog(force=force), query, requested)
                    if query else cosmetics_store.fetch_page(requested))
        except Exception:
            if cached is not None:
                self._paint(request, requested, query, cached,
                            "Showing matches from saved pages. Refresh when online to "
                            "search the full collection."
                            if query and not cached["complete"] else
                            "Showing saved cosmetics. Try Refresh for the latest collection.")
            else:
                self._paint(request, requested, query, None)
        else:
            self._paint(request, requested, query, data)

    def _paint(self, request, requested, query, data, message=""):
        owned = ({i["id"]: cosmetics_store.has_installed(i) for i in data["items"]}
                 if data else {})
        dirty: list = []
        rebuild = False
        with tree_lock():
            if request != self.request:
                return
            self.loading = False
            if data is not None:
                signature = (requested, tuple(
                    (i["id"], i["sha256"], i["name"], i["description"], i["preview_png"])
                    for i in data["items"]))
                if signature != self.signature:
                    rebuild = True
                    self.grid.clear()
                    self.cards.clear()
                    for item in data["items"]:
                        card = Card(
                            self.ctx.tokens, src=item["preview_png"], label=item["name"],
                            sublabel="Downloaded" if owned[item["id"]] else "Free cosmetic",
                            active=bool(owned[item["id"]]),
                            on_use=lambda e, v=item: self.download(v),
                            on_delete=None, action_label="Download")
                        card.control.tooltip = item["description"]
                        self.cards[item["id"]] = card
                        self.grid.append(card)
                    self.grid.fit()
                    self.signature = signature
                else:
                    # Ownership only changed: touch just the affected cards.
                    for item_id, card in self.cards.items():
                        owned_now = bool(owned.get(item_id))
                        a = card.set_selected(owned_now)
                        b = card.set_sublabel(
                            "Downloaded" if owned_now else "Free cosmetic")
                        if a or b:
                            dirty.append(card.control)
                self.items = {i["id"]: i for i in data["items"]}
                self.loaded = True
                self.offset = requested
                self.more = data["has_more"]
                message = message or ("" if data["items"]
                                      else f"No cosmetics match “{query}”." if query
                                      else "No cosmetics are available yet.")
            else:
                message = message or "The cosmetics store is unavailable. Try Refresh."
            self._sync_buttons()
        if rebuild:
            self.grid.refresh()
        else:
            for control in dirty:
                ui_refresh(control)
        ui_refresh(self.toolbar)
        self.status.set(message)


class CosmeticPane(Pane):
    """Shoulder / Back / Head / Feet / Aura: one equipped item per slot."""
    YAW = {"shoulder": 25, "hand": 25, "waist": 25, "trail": 25, "back": 180}
    _UNSET = object()

    def __init__(self, ctx: Context, slot: str, store: StorePane):
        super().__init__(ctx)
        self.slot, self.store = slot, store
        self.id, self.label = slot, cosmetics.SLOT_LABELS[slot]
        self.target_yaw = self.YAW.get(slot, 0)
        self.key = f"active_{slot}_item"
        self.grid = ctx.new_grid()
        self.status = StatusLine(ctx.tokens)
        self.cards: dict[str, Card] = {}
        self.metadata: dict[str, dict] = {}
        self._revision = 0
        self._selected = self._UNSET
        self._loaded = False
        self._dir_stamp = None
        self.remove = make_action_button(
            ctx.tokens, "Remove",
            lambda e: self.choose(None),
            icon=ft.Icons.CLOSE_ROUNDED,
        )
        self.remove.disabled, self.remove.opacity = True, 0.4
        self.remove.tooltip = "Remove the equipped item\n\n" + self._tip()
        self.header_action = keyboard_target(self.remove, "Remove equipped item")
        self.view = ft.Column([self.grid.view, self.status.control], spacing=12,
                              expand=True,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH)

    def _tip(self):
        ctx = self.ctx
        if ctx.mc_loader not in core.MOD_CAPABLE_LOADERS or not ctx.mc_version:
            tip = ("Pick Fabric or Quilt on the Play tab: the Cubeon Client draws these "
                   "in-game, and vanilla Minecraft cannot load it.")
        elif not ctx.cfg.get("client_mod_enabled", True):
            tip = ("Cubeon Client is switched off in Settings, so this item shows in "
                   "the preview but not in-game.")
        else:
            tip = ("Drawn by Cubeon Client in-game. Wearables follow your character; "
                   "trails appear briefly while walking.")
        if self.slot == "back":
            tip += ("\nSmall wings move gently. Press N in Minecraft for a Giant-wing "
                    "flare; K → Cosmetic motion turns movement off.")
        elif self.slot == "trail":
            tip += ("\nA few short-lived particles while walking. Cosmetic motion turns "
                    "them off; Minecraft's particle limit still applies.")
        return tip

    def _cosmetics_stamp(self):
        try:
            return os.stat(self.ctx.appearance.cosmetics_dir).st_mtime_ns
        except OSError:
            return 0

    def _sync_selection(self) -> bool:
        active = self.ctx.cfg.get(self.key)
        # Remove is enabled whenever ANY active id exists.
        # A stale/deleted id must still be clearable.
        new_disabled = not bool(active)
        changed = self.remove.disabled != new_disabled
        self.remove.disabled = new_disabled
        self.remove.opacity = 0.4 if new_disabled else 1.0
        previous = self._selected
        if previous is not self._UNSET and previous == active:
            return changed
        self._selected = active
        if previous is self._UNSET:
            for item_id, card in self.cards.items():
                changed = card.set_selected(active == item_id) or changed
        else:
            if previous:
                card = self.cards.get(previous)
                if card is not None:
                    changed = card.set_selected(False) or changed
            if active:
                card = self.cards.get(active)
                if card is not None:
                    changed = card.set_selected(True) or changed
        return changed

    def load(self) -> bool:
        cfg = self.ctx.cfg
        stamp = self._cosmetics_stamp()
        with tree_lock():
            if self._loaded and stamp == self._dir_stamp:
                return self._sync_selection()
            self._revision += 1
            request = self._revision
        items = cosmetics.items(self.slot, self.ctx.appearance.cosmetics_dir)
        ids = {i["id"] for i in items}
        with tree_lock():
            if request != self._revision:
                return False
            changed = ids != set(self.cards)
            self.metadata = {i["id"]: i for i in items}
            if not changed:
                self._dir_stamp = stamp
                self._loaded = True
                return self._sync_selection()
            for item_id in [k for k in self.cards if k not in ids]:
                self.grid.remove(self.cards.pop(item_id))
            if not self.cards:
                items.sort(key=lambda i: i["id"] != cfg.get(self.key))
        for item in items:
            # Release the lock between cards so a big library can't stall input.
            with tree_lock():
                if request != self._revision:
                    return False
                if item["id"] in self.cards:
                    continue
                self.cards[item["id"]] = card = self._make_card(item)
                self.grid.append(card)
        with tree_lock():
            if request != self._revision:
                return False
            self._dir_stamp = stamp
            self._loaded = True
            self.grid.fit()
            return self._sync_selection() or changed

    def _make_card(self, item) -> Card:
        wing = bool(item.get("feathers"))
        small = item["id"].endswith("_small") or (wing and item.get("wing_flare") is False)
        label = item["name"]
        if wing:
            label = label.removesuffix(" (Small)").removesuffix(" (Giant)")
        cached = self.ctx.thumbs.cached("cosmetic", item["id"])
        card = Card(
            self.ctx.tokens, src=cached,
            thumb=None if cached else (self.grid, self.slot, "cosmetic", item["id"]),
            label=label,
            sublabel=("Small" if small else "Giant") if wing else "",
            active=self.ctx.cfg.get(self.key) == item["id"],
            on_use=lambda e, i=item["id"]: self.choose(i),
            on_delete=((lambda e, i=item["id"]: self.delete(i))
                       if item.get("_store_directory") else None))
        card.control.tooltip = item["blurb"]
        return card

    def choose(self, item_id):
        ft.context.disable_auto_update()
        cfg = self.ctx.cfg
        item_id = item_id or None
        if cfg.get(self.key) == item_id:
            return
        previous = cfg.get(self.key)
        try:
            core.set_active_cosmetic(cfg, self.slot, item_id)
        except Exception as ex:
            self.status.set(f"Couldn't change this cosmetic: {ex}")
            return
        with tree_lock():
            self.ctx.repaint_preview()
            self._sync_selection()
        # Only two cards changed: don't diff the whole grid.
        for key in (previous, item_id):
            card = self.cards.get(key) if key else None
            if card is not None:
                ui_refresh(card.control)
        self.ctx.on_header_changed()
        self.status.set("")

    def delete(self, item_id):
        ft.context.disable_auto_update()
        item = cosmetics.get(item_id, self.ctx.appearance.cosmetics_dir)
        try:
            core.delete_downloaded_cosmetic(self.ctx.cfg, item_id)
        except Exception as error:
            self.status.set(f"Couldn't delete this cosmetic: {error}")
            return
        with tree_lock():
            self._loaded = False
        self.ctx.thumbs.forget("cosmetic", item_id)
        self.load()
        store_id = item.get("store_id") if item else None
        store_card = self.store.sync_ownership(store_id) if store_id else None
        self.ctx.repaint_preview()
        self.grid.refresh()
        self.ctx.on_header_changed()
        if store_card is not None:
            ui_refresh(store_card)
        self.status.set("")


# ---------------------------------------------------------------------------
# header + layout
# ---------------------------------------------------------------------------

class WardrobeHeader:
    """Category tabs plus a FIXED-SIZE action slot. The slot keeps its size when
    a pane has no action (Store), so switching panes never moves the layout."""
    HEIGHT, ACTION_WIDTH = 40, 150

    def __init__(self, panes: list[Pane], selected: str, on_select):
        self.tabs = {p.id: text_tab(p.label, selected=p.id == selected,
                                    on_click=lambda e, k=p.id: on_select(k))
                     for p in panes}
        tab_row = ft.Row(list(self.tabs.values()), spacing=12, wrap=True,
                         run_spacing=6, data="wardrobe-categories")
        self.slot = ft.Container(width=self.ACTION_WIDTH, height=self.HEIGHT,
                                 alignment=ft.Alignment.CENTER_RIGHT)
        self.view = ft.Row([ft.Container(content=tab_row, expand=True), self.slot],
                           vertical_alignment=ft.CrossAxisAlignment.CENTER,
                           data="wardrobe-header")

    def select(self, pane: Pane):
        self.slot.content = pane.header_action
        for pid, tab in self.tabs.items():
            tab.set_selected(pid == pane.id)


class WardrobeLayout:
    """Responsive sizing. Event handlers only record measurements; a throttled
    apply() computes the target and touches only what actually changed."""
    COMPACT_BELOW, WIDE_FROM = 760, 1050
    SPACING, PANEL_PADDING = 24, 16

    def __init__(self, ctx: Context, holder: ft.Control, measure_viewport: bool):
        self.ctx = ctx
        page = ctx.page
        self.viewport_height = (None if measure_viewport
                                else getattr(page, "height", None) or 660)
        self.row_width = self.preview_measured = None
        self.compact: Optional[bool] = None
        self.grid_measured = False
        self.section: Optional[ft.Control] = None
        self._applied: Optional[tuple] = None
        self._apply = Throttle(0.05, self.apply)
        self.picker = ft.Container(
            content=ft.Column([holder], expand=True, spacing=0,
                              horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            padding=0, height=260, col={"xs": 12, "md": 8, "lg": 9},
            data="cosmetics-picker")
        self.preview = ft.Container(
            content=ft.Container(content=ctx.appearance.control,
                                 alignment=ft.Alignment.CENTER, expand=True),
            col={"xs": 12, "md": 4, "lg": 3},
            padding=ft.padding.Padding.symmetric(horizontal=8),
            height=260, data="wardrobe-preview")
        self.row = ft.ResponsiveRow(
            [self.preview, self.picker],
            breakpoints={"xs": 0, "md": self.COMPACT_BELOW, "lg": self.WIDE_FROM},
            spacing=self.SPACING, run_spacing=16,
            on_size_change=self._row_resized, size_change_interval=60,
            data="cosmetics-layout")
        self.view = ft.Container(content=self.row, data="wardrobe-panel")
        ctx.appearance.viewport.on_size_change = self._preview_resized
        ctx.appearance.viewport.size_change_interval = 60
        ctx.geometry.on_measured = self._grid_measured

    # -- inputs -----------------------------------------------------------
    def _row_resized(self, event):
        ft.context.disable_auto_update()
        if _valid(event.width):
            with tree_lock():
                self.row_width = event.width
                self.compact = event.width < self.COMPACT_BELOW
            self._apply()

    def _preview_resized(self, event):
        ft.context.disable_auto_update()
        if _valid(event.width):
            with tree_lock():
                self.preview_measured = event.width
            self._apply()

    def _grid_measured(self):
        self.grid_measured = True
        self._apply()

    def set_viewport_height(self, height):
        if _valid(height):
            with tree_lock():
                self.viewport_height = height
            self._apply()

    def follow_window(self, page):
        """Keep the picker height tied to the window even if main.py never calls
        set_viewport_height. Chains any existing handler."""
        previous = getattr(page, "on_resize", None)

        def handler(event):
            if previous:
                previous(event)
            self.set_viewport_height(getattr(page, "height", None))
        try:
            page.on_resize = handler
        except Exception:
            pass

    # -- computation ------------------------------------------------------
    def _target(self):
        if self.compact is None or self.viewport_height is None:
            return None
        h = self.viewport_height
        picker = (max(132, min(320, h - 400)) if self.compact
                  else max(200, min(900, h - 190)))
        cap = 176 if self.compact else 320
        width = cap
        if self.row_width is not None:
            span = 12 if self.compact else (3 if self.row_width >= self.WIDE_FROM else 4)
            gap = 0 if span == 12 else self.SPACING
            estimate = self.row_width * span / 12 - gap - self.PANEL_PADDING
            # estimate lets the preview GROW; measurement keeps it honest.
            width = min(cap, max(self.preview_measured or 0, estimate))
        return int(picker), int(max(width, 1))

    def _ready(self):
        return (self.compact is not None and self.viewport_height is not None
                and self.preview_measured is not None and self.grid_measured)

    def apply(self):
        with tree_lock():
            target = self._target()
            changed = target is not None and target != self._applied
            if changed:
                previous, self._applied = self._applied, target
                height, width = target
                self.picker.height = self.preview.height = height
                if previous is None or previous[1] != width:
                    self.ctx.appearance.resize(width)
            reveal = (self.section is not None and self._ready()
                      and self.section.opacity == 0)
            if reveal:
                self.section.opacity = 1
        if changed:
            ui_refresh(self.row)       # one refresh covers picker + preview
        if reveal:
            ui_refresh(self.section)

    def force_reveal(self):
        try:
            with tree_lock():
                if self.section.opacity == 0:
                    self.section.opacity = 1
            ui_refresh(self.section)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# controller
# ---------------------------------------------------------------------------

class Wardrobe:
    SLOTS = ("shoulder", "back", "head", "feet", "aura")

    def __init__(self, page, cfg, tokens: Tokens, *, mc_version, mc_loader,
                 file_picker, cape_file_picker, assets_dir, measure_viewport):
        appearance = AppearancePreview(cfg, assets_dir, page=page)
        self.ctx = ctx = Context(page, cfg, tokens, appearance, mc_version, mc_loader)
        self.active_id = "skin"
        ctx.worker = ThumbnailWorker(ctx.geometry, ctx.thumbs, lambda: self.active_id)
        ctx.geometry.on_window_change = ctx.worker.flush

        # A throwaway picker only when none was supplied (e.g. headless smoke test).
        skin = SkinPane(ctx, file_picker or ft.FilePicker())
        cape = CapePane(ctx, cape_file_picker or ft.FilePicker())
        store = StorePane(ctx, cape)
        wearables = [CosmeticPane(ctx, slot, store) for slot in self.SLOTS]
        self.panes: dict[str, Pane] = {p.id: p for p in [skin, cape, store, *wearables]}
        skin.refresh_cards()

        self.views = {pid: TabPane(p.view, visible=pid == self.active_id, expand=True)
                      for pid, p in self.panes.items()}
        holder = ft.Stack(list(self.views.values()), expand=True,
                          fit=ft.StackFit.EXPAND, data="cosmetics-panes")
        holder._shell_only = True
        self.holder = holder

        self.header = WardrobeHeader(list(self.panes.values()), self.active_id, self.switch)
        self.header.select(skin)
        ctx.on_header_changed = lambda: ui_refresh(self.header.view)
        self.queue = TabEntryQueue(page, self._prepare)

        self.layout = WardrobeLayout(ctx, holder, measure_viewport)
        self.view = ft.Column([
            ft.Text(i18n.t("Wardrobe"), size=24, color=tokens.text,
                    font_family=tokens.font_display),
            self.header.view,
            self.layout.view,
        ], spacing=14, opacity=0)      # revealed once everything is measured
        self.layout.section = self.view
        self.view.set_viewport_height = self.layout.set_viewport_height
        self.view.wardrobe = self
        if not measure_viewport:
            self.layout.follow_window(page)

        timer = threading.Timer(2.0, self.layout.force_reveal)
        timer.daemon = True
        timer.start()
        appearance.refresh()

    def switch(self, pid):
        ft.context.disable_auto_update()
        with tree_lock():
            pane = self.panes.get(pid)
            if pane is None or pid == self.active_id:
                return
            self.active_id = pid
            for key, view in self.views.items():
                view.visible = key == pid
            self.header.select(pane)
        # Paint the retained shell before any catalogue read or card build.
        ui_refresh(self.header.view)
        ui_refresh(self.holder)
        if pane.target_yaw is not None:
            self.ctx.appearance.turn(pane.target_yaw - self.ctx.appearance.yaw)
        self.queue.request(pid)

    def _prepare(self, pid, generation):
        changed = self.panes[pid].load()
        with tree_lock():
            current = self.queue.is_current(generation) and self.active_id == pid
        if current:
            if changed is not False:
                ui_refresh(self.panes[pid].view)
            ui_refresh(self.header.view)   # action enabled-state may have changed
            self.ctx.worker.flush()


def build_skin_section(page: ft.Page, cfg: dict, *, section_label, pixel_divider,
                       BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                       TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO=None,
                       mc_version=None, mc_loader=None, file_picker=None,
                       cape_file_picker=None, assets_dir=None, measure_viewport=False):
    """Build the Wardrobe. Same signature as before; returns the section Column
    (with `.set_viewport_height`). `file_picker` / `cape_file_picker` must be the
    single pickers registered once by main.py."""
    tokens = Tokens(bg=BG, surface=SURFACE, surface_hi=SURFACE_HI, border=BORDER,
                    accent=ACCENT, accent_dim=ACCENT_DIM, text=TEXT,
                    text_dim=TEXT_DIM, danger=DANGER, font_display=FONT_DISPLAY)
    return Wardrobe(page, cfg, tokens, mc_version=mc_version, mc_loader=mc_loader,
                    file_picker=file_picker, cape_file_picker=cape_file_picker,
                    assets_dir=assets_dir, measure_viewport=measure_viewport).view
