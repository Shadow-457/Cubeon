"""Responsive pixel-art furniture for Play, using bundled RGBA assets.

The host ignores pointer events and lives behind the real Play controls. Trees
scale uniformly; particles stay between the header and launch controls. Only
the shared SeasonalAnimator advances motion, never a timer owned by this view.
"""
from __future__ import annotations

import math
import random

import flet as ft

from cubeon import motion, seasonal, thread_safe_ui

TREE_SIZES = ((201, 565), (210, 601), (329, 214))
COUNTS = {"spring": 9, "summer": 8, "autumn": 9, "winter": 12}


def _image(**kwargs):
    return ft.Image(src="", fit=ft.BoxFit.FILL, filter_quality=ft.FilterQuality.NONE,
                    gapless_playback=True, exclude_from_semantics=True, **kwargs)


class PlaySeasonOverlay:
    def __init__(self, info, *, width=1259, height=772):
        self.season = None
        self.enabled = False
        self.weather = False
        self.active = True
        self._size = (0, 0)
        self._tick = 0
        self._frame_gate = 0
        self.trees = [_image(left=0, bottom=0), _image(right=0, bottom=0),
                      _image(right=0, bottom=0)]
        self.ground = _image(left=0, bottom=0)
        self.art = ft.Stack([*self.trees, self.ground], fit=ft.StackFit.EXPAND)
        rng = random.Random(46)
        self.particles = [
            {"x": rng.uniform(.04, .94), "y": rng.random(),
             "phase": rng.uniform(0, math.tau), "speed": rng.uniform(.7, 1.2),
             "image": _image(width=20, height=20, left=0, top=0)}
            for _ in range(12)
        ]
        self.particle_layer = ft.Stack([p["image"] for p in self.particles],
                                       fit=ft.StackFit.EXPAND, visible=False)
        self.control = ft.Container(
            # Pinned Flet wraps on_size_change controls in a size notifier.
            # Attach it INSIDE the positioned host, or Flutter rejects the
            # Positioned parent data and renders a gray ErrorWidget.
            content=ft.Stack([self.art, self.particle_layer], fit=ft.StackFit.EXPAND,
                             on_size_change=self._on_size, size_change_interval=100),
            left=0, top=0, right=0, bottom=0, ignore_interactions=True,
            visible=False, data="play-season-overlay",
        )
        self.configure(info, weather=False)
        self.resize(width, height)

    @property
    def animating(self):
        return (self.enabled and self.weather and self.active
                and motion.transforms() and self._size[1] >= 440)

    def configure(self, info, *, weather=True, active=True, enabled=True):
        """Reuse controls when toggling the season, decoration or motion."""
        with thread_safe_ui.TREE_LOCK:
            name = info.season if info.season in seasonal.SEASONS else "autumn"
            changed = name != self.season
            self.enabled = bool(info.seasonal and enabled)
            self.weather = bool(weather)
            self.active = bool(active)
            self.control.visible = self.enabled
            self.particle_layer.visible = self.animating
            if changed:
                self.season = name
                prefix = f"play-seasons/{name}"
                for image, filename in zip(self.trees, ("left-tree", "right-tree", "tilted-tree")):
                    image.src = f"{prefix}/{filename}.png"
                self.ground.src = f"{prefix}/ground.png"
                self._tick = 0
            self._place_particles()
        thread_safe_ui.refresh(self.control)

    def _on_size(self, event):
        self.resize(event.width, event.height)

    def resize(self, width, height):
        """Fit the actual Play viewport, without rebuilding or reading disk."""
        if not (math.isfinite(width) and math.isfinite(height)) or width <= 0 or height <= 0:
            return False
        size = (round(width), round(height))
        with thread_safe_ui.TREE_LOCK:
            if size == self._size:
                return False
            self._size = size
            # Keep the tallest crown below the 150px header at small sizes.
            scale = max(.05, min(1.35, width / 1259, max(0, height - 150) / 601))
            for image, (w, h) in zip(self.trees, TREE_SIZES):
                image.width, image.height = w * scale, h * scale
            self.ground.width, self.ground.height = width, 58 * scale
            self.particle_layer.visible = self.animating
            self._place_particles()
        thread_safe_ui.refresh(self.control)
        return True

    def _place_particles(self):
        w, h = self._size
        span = max(1, h - 150 - 315)
        prefix = f"play-seasons/{self.season}"
        for i, particle in enumerate(self.particles):
            image = particle["image"]
            image.visible = i < COUNTS[self.season]
            if not image.visible:
                continue
            phase = particle["phase"] + self._tick * .09
            tone = i % 3
            butterfly = self.season == "summer" and i >= 5
            if butterfly:
                wing = "open" if (self._tick // 2 + i) % 2 else "closed"
                image.src = f"{prefix}/butterfly-{tone}-{wing}.png"
                image.width, image.height = 24, 20
            else:
                image.src = f"{prefix}/particle-{tone}.png"
                image.width = image.height = 20 if i % 3 == 0 else 12
            left = min(max(0, w - image.width),
                             max(0, particle["x"] * w + 12 * math.sin(phase)))
            if self.season == "summer":
                top = 150 + particle["y"] * span + 10 * math.sin(phase)
                image.opacity = 1 if butterfly else .45 + .45 * (.5 + .5 * math.sin(phase * 2))
            else:
                progress = (particle["y"] + self._tick * .01 * particle["speed"]) % 1
                top = 150 + progress * span
                image.opacity = .85 * min(1, progress * 12, (1 - progress) * 12)

            image.left, image.top = left, top

    def step(self):
        """One bounded particle diff; inactive/reduced views do no work."""
        if not self.animating:
            return False
        self._frame_gate ^= 1
        if not self._frame_gate:
            return False
        self._tick += 1
        self._place_particles()
        return True
