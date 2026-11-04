"""A click-through seasonal pet that follows launcher edges and Play perches."""
from __future__ import annotations

import math
import random

import flet as ft

from cubeon import motion, thread_safe_ui
from ui.seasonal_ui import pet_src

SIZE = 32


class LauncherPet:
    def __init__(self, info):
        self.info = info
        self.enabled = False
        self.paused = False
        self.active_tab = "play"
        self.size = (1380, 836)
        self.x, self.y = 108.0, 836.0 - SIZE - 12
        self.wait = 22
        self.state = "rest"
        self._rest_kind = "floor"
        self._gate = 0
        self._index = 0
        self._rng = random.Random(86)
        self.sprite = ft.Container(
            content=ft.Image(src=self._source(), width=SIZE, height=SIZE,
                             fit=ft.BoxFit.CONTAIN, filter_quality=ft.FilterQuality.NONE,
                             gapless_playback=True, exclude_from_semantics=True),
            width=SIZE, height=SIZE, left=self.x, top=self.y,
        )
        self.pet = {"ctrl": self.sprite, "season": info.season}
        self.particle_layer = ft.Stack([self.sprite], fit=ft.StackFit.EXPAND)
        self.control = ft.Container(
            content=ft.Stack([self.particle_layer], fit=ft.StackFit.EXPAND,
                             on_size_change=self._on_size, size_change_interval=100),
            left=0, right=0, top=0, bottom=0, ignore_interactions=True,
            visible=False, data="launcher-roaming-pet",
        )
        self.route = self._route()
        self._paint()

    def _source(self):
        source = pet_src(self.info)
        if self.state == "walk" and not self.paused and motion.transforms():
            return source
        return source.removesuffix(".gif") + "-rest.png"

    def _route(self):
        w, h = self.size
        left, right, floor = min(104, w - SIZE), max(0, w - SIZE - 12), max(44, h - SIZE - 12)
        points = [(left, floor, "floor"), (right, floor, "floor")]
        if self.active_tab == "play" and w >= 1120 and h >= 700:
            # Play's 64px frame is above its reserved footer/progress area.
            y = h - 287 - SIZE
            points.extend([(right, y, "climb"), (w - 226, y, "button"),
                           (w - 344, y, "button"), (right, y, "button")])
        points.extend([(right, 52, "climb"), (max(left, right - 140), 52, "border"),
                       (left, 52, "border"), (left, floor, "climb")])
        return points

    def _on_size(self, event):
        self.resize(event.width, event.height)

    def resize(self, width, height):
        if width <= 0 or height <= 0 or not (math.isfinite(width) and math.isfinite(height)):
            return False
        size = (round(width), round(height))
        with thread_safe_ui.TREE_LOCK:
            if size == self.size:
                return False
            previous = self.size
            self.size = size
            self.route = self._route()
            if abs(self.x - (previous[0] - SIZE - 12)) < 9:
                self.x = max(0, width - SIZE - 12)
            if abs(self.y - (previous[1] - SIZE - 12)) < 9:
                self.y = max(0, height - SIZE - 12)
            if self.state == "rest":
                if self._rest_kind == "floor":
                    self.y = max(0, height - SIZE - 12)
                elif self._rest_kind == "button":
                    if any(kind == "button" for _, _, kind in self.route):
                        self.y = max(0, height - 287 - SIZE)
                        self.x += width - previous[0]
                    else:
                        self.y = self.route[0][1]
                        self._rest_kind = "floor"
                        self._index = 0
                        self.sprite.rotate = 0
            self.x = min(max(0, self.x), max(0, width - SIZE))
            self.y = min(max(0, self.y), max(0, height - SIZE))
            self._index %= len(self.route)
            self._paint()
        thread_safe_ui.refresh(self.particle_layer)
        return True

    def configure(self, info, *, enabled, active_tab):
        with thread_safe_ui.TREE_LOCK:
            self.info = info
            self.pet["season"] = info.season
            self.enabled = bool(enabled)
            self.control.visible = self.enabled
            self.tab_changed(active_tab, repaint=False)
            if not motion.transforms():
                self.state = "rest"
            self._paint()
        thread_safe_ui.refresh(self.control)

    def tab_changed(self, active_tab, *, repaint=True):
        """Retire page-specific perches before painting a different page."""
        with thread_safe_ui.TREE_LOCK:
            if active_tab == self.active_tab:
                return False
            self.active_tab = active_tab
            self.route = self._route()
            left, right = self.route[0][0], self.route[1][0]
            self.x = min(right, max(left, self.x))
            self.y = self.route[0][1]
            self.state = 'rest'
            self._rest_kind = 'floor'
            self.wait = 8
            self._index = 0 if self.x - left < right - self.x else 1
            self.sprite.rotate = 0
            self._paint()
        if repaint:
            thread_safe_ui.refresh(self.control)
        return True

    @property
    def animating(self):
        return self.enabled and not self.paused and motion.transforms()

    def set_paused(self, paused):
        with thread_safe_ui.TREE_LOCK:
            self.paused = bool(paused)
            self._paint()
        thread_safe_ui.refresh(self.particle_layer)

    def _paint(self):
        self.sprite.left, self.sprite.top = round(self.x), round(self.y)
        self.sprite.content.src = self._source()

    def step(self):
        if not self.animating:
            return False
        self._gate ^= 1
        if not self._gate:
            return False
        if self.state == "rest":
            self.wait -= 1
            if self.wait > 0:
                return False
            self.state = "walk"
        tx, ty, kind = self.route[self._index]
        dx, dy = tx - self.x, ty - self.y
        distance = math.hypot(dx, dy)
        if distance <= 8:
            self.x, self.y = tx, ty
            self._index = (self._index + 1) % len(self.route)
            self.state = "rest"
            self._rest_kind = kind
            self.wait = self._rng.randint(12, 32) if kind == "button" else self._rng.randint(3, 12)
            self.sprite.rotate = 0
        else:
            self.x += dx / distance * 8
            self.y += dy / distance * 8
            # Rotate only while climbing; explicit axes avoid NaN mirrors.
            self.sprite.rotate = (-math.pi / 2 if dy < 0 else math.pi / 2) if abs(dy) > abs(dx) else 0
            self.sprite.scale = ft.Scale(scale_x=-1 if dx < -1 else 1, scale_y=1)
        self._paint()
        return True
