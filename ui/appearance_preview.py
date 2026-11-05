"""A responsive drag orbit with one persistent, gapless character image.

A single worker coalesces camera/appearance requests. Drag frames render at native
resolution; release refines the current angle. Cached angles never render again.
"""
from collections import OrderedDict
from io import BytesIO
import logging
import math
import os
import threading
import weakref

import flet as ft
from PIL import Image

from cubeon.appearance import CharacterModel, RenderCancelled, render_faces
from cubeon import thread_safe_ui
from cubeon.theme import TEXT_DIM

STAGE_W, STAGE_H = 320, 440
STEPS = 360
SUPERSAMPLE = 2
HOME_YAW, PITCH = 25.0, 10.0
MAX_FRAMES = 64


def render_frame(faces, textures, supersample=SUPERSAMPLE, *, cancel=None):
    """Keep the reference renderer's skin-layer and transparent-texel depth tests."""
    return render_faces(faces, textures, size=(STAGE_W, STAGE_H), supersample=supersample, cancel=cancel)


def _png(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG", compress_level=1)
    return buffer.getvalue()


EMPTY_FRAME = _png(Image.new("RGBA", (1, 1)))


class AppearancePreview:
    def __init__(self, cfg, assets_dir=None, page=None):
        self.cfg = cfg
        assets_dir = assets_dir or os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
        self.default_cape_path = os.path.join(assets_dir, "capes", "cubeon_cape.png")
        self.cosmetics_dir = os.path.join(assets_dir, "cosmetics")
        self.yaw, self.pitch = HOME_YAW, PITCH
        self._lock = threading.RLock()
        self._generation = 0
        self._pending = None
        self._running = False
        self._frames = OrderedDict()
        self._quality = {}
        self._frames_generation = -1
        self._model = None
        self._textures = {}
        self._requested_step = None
        self._shown = None
        self._revision = 0
        self._shown_revision = -1
        self._target_key = self._camera_key()
        self._refine_cancel = None
        self._drag = None
        self._page = page
        self._available_width = STAGE_W
        self._display_scale = 1.0
        if page is not None:
            previews = getattr(page, "_cubeon_appearance_previews", None)
            if previews is None:
                previews = page._cubeon_appearance_previews = weakref.WeakSet()
            previews.add(self)
        self.image = ft.Image(
            src=EMPTY_FRAME, width=STAGE_W, height=STAGE_H,
            fit=ft.BoxFit.FILL, gapless_playback=True,
            filter_quality=ft.FilterQuality.MEDIUM, data="appearance-image",
        )
        self.shadow = ft.Container(
            left=STAGE_W / 2 - 42, top=STAGE_H - 30, width=84, height=10,
            border_radius=42, bgcolor="#22000000",
            shadow=ft.BoxShadow(blur_radius=16, spread_radius=2, color="#55000000"),
        )
        self.scene = ft.Stack([self.shadow, self.image], width=STAGE_W, height=STAGE_H,
                              clip_behavior=ft.ClipBehavior.NONE, data="appearance-model")
        self.note = ft.Text("Loading preview…", size=11, color=TEXT_DIM, text_align=ft.TextAlign.CENTER)
        self.gesture = ft.GestureDetector(
            content=self.scene, data="appearance-orbit", mouse_cursor=ft.MouseCursor.GRAB,
            drag_interval=16, on_pan_start=self._drag_start,
            on_pan_update=self._drag_update, on_pan_end=self._drag_end,
        )
        self.viewport = ft.Container(
            content=self.gesture, height=STAGE_H, alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
            on_size_change=self._resize_event,
        )
        self.control = ft.Column([
            self.viewport,
            ft.Row([
                ft.IconButton(ft.Icons.ARROW_BACK_ROUNDED, icon_size=18, tooltip="Rotate left",
                              on_click=lambda event: self._turn_click(event, -30)),
                ft.IconButton(ft.Icons.RESTART_ALT_ROUNDED, icon_size=18, tooltip="Reset view",
                              on_click=self._reset_click),
                ft.IconButton(ft.Icons.ARROW_FORWARD_ROUNDED, icon_size=18, tooltip="Rotate right",
                              on_click=lambda event: self._turn_click(event, 30)),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=8),
            self.note,
        ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.resize(STAGE_W, repaint=False)

    def _step_for(self, yaw):
        return int(round((yaw % 360) / (360 / STEPS))) % STEPS

    def _camera_key(self, step=None):
        step = self._step_for(self.yaw) if step is None else step
        pitch = round(self.pitch)
        return step if pitch == PITCH else (step, pitch)

    def _set_yaw(self, yaw):
        with self._lock:
            self.yaw = yaw % 360
            key = self._camera_key()
        self._show(key)

    def _show(self, key):
        """Keep the last image visible while requesting the latest camera angle."""
        start = False
        data = None
        with self._lock:
            if key != self._target_key:
                self._target_key = key
                self._revision += 1
                self._requested_step = None
                if self._refine_cancel is not None:
                    self._refine_cancel.set()
            if self._frames_generation == self._generation:
                data = self._frames.get(key)
            if data is not None:
                self._frames.move_to_end(key)
            if data is None or self._drag is None and self._quality.get(key, 0) < SUPERSAMPLE:
                if self._model is not None or self._pending is not None:
                    self._requested_step = key
                    if not self._running:
                        self._running = True
                        start = True
            generation = self._generation
            revision = self._revision
        if data is not None:
            self._publish(generation, key, data, revision)
        if start:
            self._start_worker()

    def _publish(self, generation, key, data, revision):
        with thread_safe_ui.TREE_LOCK, self._lock:
            if generation != self._generation or revision < self._shown_revision:
                return
            # During motion, present completed frames while the next is rendering.
            # Rejecting every frame behind the pointer would freeze a busy drag.
            if key != self._camera_key() and self._drag is None:
                return
            if self.image.src is data:
                self._shown_revision = revision
                return
            # One image, one fixed rectangle, no hiding the old frame. Flutter's
            # gapless playback retains its decoded image until the new one is ready.
            first = self._shown is None
            self.image.src = data
            self._shown = key
            self._shown_revision = revision
            if first:
                self.note.value = "Drag to rotate · arrows to turn · reset to center"
        thread_safe_ui.refresh(self.image)
        if first:
            thread_safe_ui.refresh(self.note)

    def turn(self, degrees):
        with self._lock:
            self._drag = None
        self._set_yaw(self.yaw + float(degrees))

    def _turn_click(self, event, degrees):
        ft.context.disable_auto_update()
        self.turn(degrees)

    def _reset_click(self, event):
        ft.context.disable_auto_update()
        self.reset(event)

    def reset(self, event=None):
        with self._lock:
            self._drag = None
            self.pitch = PITCH
        self._set_yaw(HOME_YAW)

    def _drag_start(self, event):
        ft.context.disable_auto_update()
        position = event.local_position
        with self._lock:
            self._drag = (position.x, position.y, self.yaw, self.pitch)
            if self._refine_cancel is not None:
                self._refine_cancel.set()
        with thread_safe_ui.TREE_LOCK:
            self.gesture.mouse_cursor = ft.MouseCursor.GRABBING
        thread_safe_ui.refresh(self.gesture)

    def _drag_update(self, event):
        # An uncached camera request paints later from the worker. Otherwise
        # Flet auto-updates the whole launcher after every pointer event.
        ft.context.disable_auto_update()
        with self._lock:
            if self._drag is None:
                return
            x, y, yaw, pitch = self._drag
            position = event.local_position
            if not (math.isfinite(position.x) and math.isfinite(position.y)):
                return
            self.pitch = max(-35, min(35, pitch + (position.y - y) * .4))
        self._set_yaw(yaw + (position.x - x) * .65)

    def _drag_end(self, event=None):
        ft.context.disable_auto_update()
        with self._lock:
            self._drag = None
            key = self._camera_key()
        with thread_safe_ui.TREE_LOCK:
            self.gesture.mouse_cursor = ft.MouseCursor.GRAB
        self._show(key)
        thread_safe_ui.refresh(self.gesture)

    def resize(self, width, repaint=True):
        """Scale existing image geometry; a resize never rerenders the skin."""
        if not width or width <= 0 or not math.isfinite(width):
            return
        height = max(220, (getattr(self._page, "height", None) or 680) - 240)
        scale = min(1, width / STAGE_W, height / STAGE_H)
        with thread_safe_ui.TREE_LOCK, self._lock:
            if self._available_width == width and self._display_scale == scale:
                return
            self._available_width, self._display_scale = width, scale
            self.scene.width, self.scene.height = STAGE_W * scale, STAGE_H * scale
            self.image.width, self.image.height = self.scene.width, self.scene.height
            self.viewport.height = self.scene.height
            self.shadow.left, self.shadow.top = (STAGE_W / 2 - 42) * scale, (STAGE_H - 30) * scale
            self.shadow.width, self.shadow.height = 84 * scale, 10 * scale
        if repaint:
            thread_safe_ui.refresh(self.viewport)

    def _resize_event(self, event):
        ft.context.disable_auto_update()
        self.resize(event.width)

    def refresh(self, *, invalidate=False):
        start = False
        with self._lock:
            if invalidate or not self._frames and not self._running:
                if self._refine_cancel is not None:
                    self._refine_cancel.set()
                self._generation += 1
                self._shown_revision = -1
                self._pending = (self._generation, dict(self.cfg))
                self._requested_step = self._camera_key()
                if not self._running:
                    self._running = True
                    start = True
            key = self._camera_key()
            loaded = bool(self._frames)
        if loaded:
            self._show(key)
        if start:
            self._start_worker()

    def _start_worker(self):
        threading.Thread(target=self._load, daemon=True, name="ux-appearance-assets").start()

    def _load(self):
        while True:
            with self._lock:
                request, key = self._pending, self._requested_step
                self._pending = self._requested_step = None
                if request is None and key is None:
                    self._running = False
                    return
                generation = self._generation
                revision = self._revision
            try:
                if request is not None:
                    generation, cfg = request
                    model = CharacterModel.from_config(cfg, self.default_cape_path, self.cosmetics_dir)
                    textures = {index: face.texture.convert("RGBA")
                                for index, face in enumerate(model.faces) if face.texture.getbbox()}
                    with self._lock:
                        if generation != self._generation:
                            continue
                        self._model, self._textures = model, textures
                        self._frames.clear()
                        self._quality.clear()
                        self._frames_generation = generation
                        key = self._camera_key()
                        revision = self._revision
                else:
                    model, textures = self._model, self._textures
                with self._lock:
                    if model is None or generation != self._generation:
                        continue
                    quality = 1 if request is not None or self._drag is not None else SUPERSAMPLE
                    cached = self._frames.get(key) if self._quality.get(key, 0) >= quality else None
                    cancel = threading.Event() if quality > 1 else None
                    self._refine_cancel = cancel
                if cached is not None:
                    self._publish(generation, key, cached, revision)
                    continue
                step, pitch = key if isinstance(key, tuple) else (key, PITCH)
                # Preserve raised skin caps, texture alpha, cape and cosmetics;
                # tiny voxel side walls return when the camera settles.
                faces = model.project(step * 360 / STEPS, pitch, detail=quality > 1)
                frame = render_frame([face for face in faces if face.index in textures], textures, quality, cancel=cancel)
                if not frame.getchannel("A").getbbox():
                    raise ValueError("empty model")
                data = _png(frame)
                with self._lock:
                    if generation != self._generation:
                        continue
                    self._frames[key] = data
                    self._frames.move_to_end(key)
                    self._quality[key] = quality
                    while len(self._frames) > MAX_FRAMES:
                        oldest = next(candidate for candidate in self._frames if candidate != self._camera_key())
                        self._frames.pop(oldest)
                        self._quality.pop(oldest, None)
                    if quality == 1 and self._drag is None and self._requested_step is None:
                        self._requested_step = self._camera_key()
                self._publish(generation, key, data, revision)
            except RenderCancelled:
                continue
            except Exception:
                logging.getLogger(__name__).exception("Could not render appearance preview")
                with thread_safe_ui.TREE_LOCK, self._lock:
                    if generation != self._generation:
                        continue
                    self.note.value = "Couldn't load preview. Choose another skin or cape."
                thread_safe_ui.refresh(self.note)
            finally:
                with self._lock:
                    self._refine_cancel = None
