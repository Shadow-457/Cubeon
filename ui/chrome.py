"""Retained, black frosted chrome without live backdrop filters."""
import flet as ft
import logging
import threading

from cubeon import motion, thread_safe_ui, version_art


class NavSlider:
    """Move the small rail marker with a paint transform, never rail layout.

    Native offset tweening owns every animation frame. Window resizing uses
    the shell's existing event; scrolling only paints when the target changes.
    """

    ANIMATION = ft.Animation(120, motion.EASE)

    def __init__(self, keys, height, accent, *, tile_height=44, gap=6, footer_extra=0):
        self.positions = {key: index * (tile_height + gap) for index, key in enumerate(keys)}
        self.height, self.tile_height = height, tile_height
        self.footer_extra, self.scroll_offset = footer_extra, 0
        self.key = next(iter(self.positions))
        self.marker = ft.Container(
            width=3, height=22, left=5, top=0,
            bgcolor=accent, border_radius=2, ignore_interactions=True,
            offset=ft.Offset(0, 0, transform_hit_tests=False),
            animate_offset=self.ANIMATION, data='nav-marker',
        )
        # Flet has no public RepaintBoundary control. A single, noninteractive
        # viewport supplies Flutter's native paint boundary, keeping marker
        # frames inside the 64px rail instead of repainting the tab/backdrop.
        self.paint_area = ft.Container(ft.Stack([self.marker]), height=height)
        self.layer = ft.Container(
            ft.ListView([self.paint_area], padding=0, spacing=0),
            left=0, top=0, right=0, bottom=0, ignore_interactions=True,
            data='nav-marker-layer',
        )
        self.select(self.key, animate=False)

    def select(self, key, *, animate=True):
        with thread_safe_ui.TREE_LOCK:
            self.key = key
            inset = (self.tile_height - self.marker.height) / 2
            settings_top = self.height - 12 - self.tile_height - self.footer_extra
            if key == 'settings':
                top, shown = settings_top + inset, True
            elif key in self.positions:
                top = 24 + self.positions[key] + inset - self.scroll_offset
                shown = 24 <= top and top + self.marker.height <= settings_top - 8
            else:
                top, shown = self.marker.offset.y * self.marker.height, False
            offset = top / self.marker.height
            if self.marker.offset.y == offset and self.marker.opacity == int(shown):
                return False
            self.marker.animate_offset = self.ANIMATION if animate and motion.transforms() else ft.Animation(0)
            self.marker.offset = ft.Offset(0, offset, transform_hit_tests=False)
            self.marker.opacity = int(shown)
            return True

    def resize(self, height):
        with thread_safe_ui.TREE_LOCK:
            if height <= 0 or abs(height - self.height) < .5:
                return False
            self.height = height
            self.paint_area.height = height
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

    def panel(self, content, *, width=None, height=None, top=0):
        artwork = ft.Image(
            src=self.source, width=self.width, height=self.height,
            left=0, top=-top, fit=ft.BoxFit.COVER,
            gapless_playback=True, filter_quality=ft.FilterQuality.LOW,
        )
        self.images.append(artwork)
        return ft.Container(
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
