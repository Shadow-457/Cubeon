"""Retained, black frosted chrome without live backdrop filters."""
import flet as ft
import logging
import threading

from cubeon import motion, thread_safe_ui, version_art

BAR_HEIGHT = 44
BAR_WIDTH = 56
SIDEBAR_WIDTH = 64

HORIZONTAL_EDGES = ("top", "bottom")


def _place_band(control, edge, thickness, insets):
    for side, offset in insets.items():
        setattr(control, side, None if side == _OPPOSITE[edge] else offset)
    horizontal = edge in HORIZONTAL_EDGES
    control.width = None if horizontal else thickness
    control.height = thickness if horizontal else None


_OPPOSITE = {"top": "bottom", "bottom": "top", "left": "right", "right": "left"}


class LauncherLayout:
    """Position retained chrome around the content, with the title bar outermost."""

    def __init__(self, bar, rail, content, *, bar_art, rail_art,
                 orient_bar, orient_rail, slider, positions, viewport):
        self.bar = ft.Container(bar, data="launcher-bar")
        self.rail = ft.Container(rail, data="launcher-sidebar")
        self.content = ft.Container(content, data="launcher-content")
        self.bar_art, self.rail_art = bar_art, rail_art
        self.orient_bar, self.orient_rail = orient_bar, orient_rail
        self.slider = slider
        self.viewport = viewport
        self.control = ft.Stack([self.bar, self.rail, self.content], fit=ft.StackFit.EXPAND,
                                expand=True, data="launcher-shell")
        self.control._shell_only = True
        self.place(positions)

    def place(self, positions):
        bar_edge, rail_edge = positions["top_bar"], positions["sidebar"]
        bar_horizontal = bar_edge in HORIZONTAL_EDGES
        rail_horizontal = rail_edge in HORIZONTAL_EDGES
        bar_thickness = BAR_HEIGHT if bar_horizontal else BAR_WIDTH
        gutter = dict.fromkeys(_OPPOSITE, 0)
        _place_band(self.bar, bar_edge, bar_thickness, gutter)
        gutter[bar_edge] = bar_thickness
        _place_band(self.rail, rail_edge, SIDEBAR_WIDTH, gutter)

        for artwork, edge, insets in (
            (self.bar_art, bar_edge, dict.fromkeys(_OPPOSITE, 0)),
            (self.rail_art, rail_edge, gutter),
        ):
            # Crop the same window-sized image at this band's screen position.
            for near, far in (("left", "right"), ("top", "bottom")):
                setattr(artwork, near, None if edge == far else -insets[near])
                setattr(artwork, far, -insets[far] if edge == far else None)

        self.rail_edge = rail_edge
        self.rail_cross_inset = sum(gutter[side] for side in (
            ("left", "right") if rail_horizontal else ("top", "bottom")))
        gutter[rail_edge] += SIDEBAR_WIDTH
        for edge, offset in gutter.items():
            setattr(self.content, edge, offset)
        self.orient_bar(bar_horizontal)
        self.orient_rail(rail_horizontal)
        self.resize(*self.viewport)

    def content_size(self):
        width, height = self.viewport
        return (max(1, width - self.content.left - self.content.right),
                max(1, height - self.content.top - self.content.bottom))

    def resize(self, width, height):
        self.viewport = width, height
        rail_length = (width if self.rail_edge in HORIZONTAL_EDGES else height) - self.rail_cross_inset
        return self.slider.resize(max(1, rail_length), edge=self.rail_edge)

    def apply(self, positions):
        with thread_safe_ui.TREE_LOCK:
            self.place(positions)
            thread_safe_ui.refresh(self.control)


class NavSlider:
    """Use a paint transform to move the accent marker along the rail."""

    ANIMATION = ft.Animation(120, motion.EASE)
    MARKER_LENGTH = 22
    START, END = 24, 12

    def __init__(self, keys, length, accent, *, tile_width=48, tile_height=44,
                 gap=6, footer_extra=0):
        self.indices = {key: index for index, key in enumerate(keys)}
        self.tile_width, self.tile_height = tile_width, tile_height
        self.gap, self.footer_extra, self.scroll_offset = gap, footer_extra, 0
        self.key = next(iter(self.indices))
        self.edge, self.length = None, 0
        self.marker = ft.Container(
            bgcolor=accent, border_radius=2, ignore_interactions=True,
            offset=ft.Offset(0, 0, transform_hit_tests=False),
            animate_offset=self.ANIMATION, data="nav-marker",
        )
        # One noninteractive native viewport supplies the paint boundary.
        self.paint_area = ft.Container(ft.Stack([self.marker]))
        self.layer = ft.Container(
            ft.ListView([self.paint_area], padding=0, spacing=0),
            left=0, top=0, right=0, bottom=0, ignore_interactions=True,
            data="nav-marker-layer",
        )
        self.resize(length, edge="left")

    def select(self, key, *, animate=True):
        with thread_safe_ui.TREE_LOCK:
            self.key = key
            horizontal = self.edge in HORIZONTAL_EDGES
            tile = self.tile_width if horizontal else self.tile_height
            inset = (tile - self.MARKER_LENGTH) / 2
            settings_start = self.length - self.END - tile - self.footer_extra
            index = self.indices.get(key)
            if key == "settings":
                position, shown = settings_start + inset, True
            elif index is not None:
                position = self.START + index * (tile + self.gap) + inset - self.scroll_offset
                shown = self.START <= position and position + self.MARKER_LENGTH <= settings_start - 8
            else:
                position, shown = 0, False
            along = position / self.MARKER_LENGTH
            x, y = (along, 0) if horizontal else (0, along)
            if (self.marker.offset.x, self.marker.offset.y, self.marker.opacity) == (x, y, int(shown)):
                return False
            self.marker.animate_offset = self.ANIMATION if animate and motion.transforms() else ft.Animation(0)
            self.marker.offset = ft.Offset(x, y, transform_hit_tests=False)
            self.marker.opacity = int(shown)
            return True

    def resize(self, length, *, edge):
        with thread_safe_ui.TREE_LOCK:
            if edge == self.edge and abs(length - self.length) < .5:
                return False
            self.edge, self.length = edge, length
            horizontal = edge in HORIZONTAL_EDGES
            self.paint_area.height = SIDEBAR_WIDTH if horizontal else length
            self.marker.width, self.marker.height = ((self.MARKER_LENGTH, 3) if horizontal
                                                     else (3, self.MARKER_LENGTH))
            self.marker.left = 5 if edge == "left" else 0 if horizontal else None
            self.marker.right = 5 if edge == "right" else None
            self.marker.top = 5 if edge == "top" else 0 if not horizontal else None
            self.marker.bottom = 5 if edge == "bottom" else None
            self.marker.animate_offset = ft.Animation(0)
            self.select(self.key, animate=False)
            return True

    def scroll(self, pixels):
        with thread_safe_ui.TREE_LOCK:
            if abs(pixels - self.scroll_offset) < .5:
                return False
            self.scroll_offset = pixels
            return self.select(self.key, animate=False)


class TabEntryQueue:
    """Run tab preparation off the event loop, coalescing rapid navigation.

    The shell paints immediately. One page-context worker finishes the current
    preparation, then takes the latest request. Prepared hidden tabs stay cached;
    the callback checks the generation before publishing or refreshing content.
    """

    def __init__(self, page, prepare):
        self.page, self.prepare = page, prepare
        self.deferred = thread_safe_ui.has_ui_loop(page)
        self._lock = threading.Lock()
        self._generation = 0
        self._pending = None
        self._running = False

    def is_current(self, generation):
        with self._lock:
            return generation == self._generation

    def request(self, key):
        with self._lock:
            self._generation += 1
            generation = self._generation
            if self.deferred:
                self._pending = key, generation
                if self._running:
                    return
                self._running = True
        if not self.deferred:
            self.prepare(key, generation)
            return
        try:
            self.page.run_thread(self._work)
        except Exception:
            with self._lock:
                self._running = False
            raise

    def _work(self):
        while True:
            with self._lock:
                pending, self._pending = self._pending, None
                if pending is None:
                    self._running = False
                    return
            try:
                self.prepare(*pending)
            except Exception:
                logging.getLogger(__name__).exception('tab preparation failed: %s', pending[0])


@ft.control("Container")
class TabPane(ft.Container):
    """Keep shell diffs out of retained tab content.

    Navigation updates the parent Stack, which sends pane visibility without
    walking its library/transcript. Content owners repaint their own controls;
    the initial mount still serializes the complete tree.
    """

    def is_isolated(self):
        return thread_safe_ui.shell_update_active()


class ChromeBackdrop:
    def __init__(self, version, width, height):
        self.source = version_art.key_art_blurred_src(version)
        self.width, self.height = width, height
        self.images = []

    def panel(self, content, *, width=None, height=None):
        artwork = ft.Image(
            src=self.source, width=self.width, height=self.height,
            left=0, top=0, fit=ft.BoxFit.COVER,
            gapless_playback=True, filter_quality=ft.FilterQuality.LOW,
        )
        self.images.append(artwork)
        panel = ft.Container(
            ft.Stack([
                artwork,
                ft.Container(left=0, top=0, right=0, bottom=0,
                             bgcolor=ft.Colors.with_opacity(.66, '#000000'),
                             ignore_interactions=True),
                ft.Container(content, left=0, top=0, right=0, bottom=0),
            ], fit=ft.StackFit.EXPAND),
            width=width, height=height,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        return panel, artwork

    def set_version(self, version):
        source = version_art.key_art_blurred_src(version)
        if source == self.source:
            return
        with thread_safe_ui.TREE_LOCK:
            self.source = source
            for artwork in self.images:
                artwork.src = source
        for artwork in self.images:
            thread_safe_ui.refresh(artwork)

    def resize(self, width, height):
        if width < 160 or height < 160 or (width, height) == (self.width, self.height):
            return
        with thread_safe_ui.TREE_LOCK:
            self.width, self.height = width, height
            for artwork in self.images:
                artwork.width, artwork.height = width, height
        for artwork in self.images:
            thread_safe_ui.refresh(artwork)
