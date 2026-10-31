"""A textured character preview with button-controlled rotation.

Only requested camera angles are rendered, then cached for subsequent turns.
One worker coalesces camera and appearance changes instead of baking a full orbit.
"""
from io import BytesIO
import logging
import os
import threading
import time

import flet as ft
from PIL import Image

from cubeon.appearance import CharacterModel, render_faces
from cubeon import thread_safe_ui
from cubeon.theme import TEXT_DIM

STAGE_W, STAGE_H = 320, 440
STEPS = 60                  # turntable frames per revolution (6 degrees apart)
SUPERSAMPLE = 2             # render at 2x then box-filter down: clean edges
HOME_YAW, PITCH = 25.0, 10.0
TICK = 1 / 60

def render_frame(faces, textures, supersample=SUPERSAMPLE):
    """Render cached turntable frames with per-pixel skin-layer occlusion."""
    return render_faces(faces, textures, size=(STAGE_W, STAGE_H), supersample=supersample)


def _png(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG", compress_level=3)
    return buffer.getvalue()


class AppearancePreview:
    def __init__(self, cfg, assets_dir=None):
        self.cfg = cfg
        assets_dir = assets_dir or os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
        self.default_cape_path = os.path.join(assets_dir, "capes", "cubeon_cape.png")
        self.cosmetics_dir = os.path.join(assets_dir, "cosmetics")
        self.yaw, self.pitch = HOME_YAW, PITCH
        self._lock = threading.RLock()
        self._generation = 0
        self._pending = None
        self._running = False
        self._frames = {}          # visited turntable steps only
        self._frames_generation = -1
        self._model = None
        self._textures = {}
        self._requested_step = None
        self._shown = None
        self._motion = 0           # bumped to cancel glide / fling threads
        self.scene = ft.Stack([], width=STAGE_W, height=STAGE_H, clip_behavior=ft.ClipBehavior.NONE,
                              data="appearance-model")
        self.note = ft.Text("Loading preview…", size=11, color=TEXT_DIM)
        self.gesture = ft.Container(content=self.scene, data="appearance-orbit")
        self.control = ft.Column([
            ft.Container(content=self.gesture, width=STAGE_W, height=STAGE_H, alignment=ft.Alignment.CENTER,
                         clip_behavior=ft.ClipBehavior.HARD_EDGE),
            ft.Row([
                ft.IconButton(ft.Icons.ARROW_BACK_ROUNDED, icon_size=18, tooltip="Rotate left",
                              on_click=lambda event: self.turn(-30)),
                ft.IconButton(ft.Icons.RESTART_ALT_ROUNDED, icon_size=18, tooltip="Reset view",
                              on_click=self.reset),
                ft.IconButton(ft.Icons.ARROW_FORWARD_ROUNDED, icon_size=18, tooltip="Rotate right",
                              on_click=lambda event: self.turn(30)),
            ], alignment=ft.MainAxisAlignment.CENTER, spacing=8),
            self.note,
        ], spacing=4, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

    # ------------------------------------------------------------ rotation
    def _step_for(self, yaw):
        return int(round((yaw % 360) / (360 / STEPS))) % STEPS

    def _set_yaw(self, yaw):
        with self._lock:
            self.yaw = yaw % 360
            step = self._step_for(self.yaw)
        self._show(step)

    def _show(self, step):
        """Use a cached frame or request the latest angle without blocking input."""
        start_worker = False
        old = new = None
        with thread_safe_ui.TREE_LOCK, self._lock:
            if self._frames_generation == self._generation:
                new = self._frames.get(step)
            if new is not None:
                if step == self._shown:
                    return
                old = self._frames.get(self._shown)
                new.opacity = 1
                if old is not None:
                    old.opacity = 0
                self._shown = step
            elif self._model is not None or self._pending is not None:
                self._requested_step = step
                if not self._running:
                    self._running = True
                    start_worker = True
        if new is not None:
            thread_safe_ui.refresh(new)
        if old is not None:
            thread_safe_ui.refresh(old)
        if start_worker:
            self._start_worker()

    def _cancel_motion(self):
        with self._lock:
            self._motion += 1
            return self._motion

    def _glide(self, delta, duration=0.3):
        token = self._cancel_motion()
        if not self._frames:
            self._set_yaw(self.yaw + delta)
            return
        threading.Thread(target=self._glide_run, args=(token, self.yaw, delta, duration),
                         daemon=True, name="ux-appearance-glide").start()

    def _glide_run(self, token, start, delta, duration):
        began = time.monotonic()
        while token == self._motion:
            t = min(1.0, (time.monotonic() - began) / duration)
            self._set_yaw(start + delta * (1 - (1 - t) ** 3))   # ease-out
            if t >= 1.0:
                return
            time.sleep(TICK)

    def turn(self, degrees):
        self._glide(float(degrees))

    def reset(self, event=None):
        delta = ((HOME_YAW - self.yaw + 180) % 360) - 180      # shortest way round
        self.pitch = PITCH
        self._glide(delta, 0.4)

    # ------------------------------------------------------------- loading
    def refresh(self, *, invalidate=False):
        start_worker = False
        with self._lock:
            if invalidate or (not self._frames and not self._running):
                self._generation += 1
                self._pending = (self._generation, dict(self.cfg))
                self._requested_step = self._step_for(self.yaw)
                if not self._running:
                    self._running = True
                    start_worker = True
            loaded = bool(self._frames)
        if loaded:
            self._show(self._step_for(self.yaw))
        if start_worker:
            self._start_worker()

    def _start_worker(self):
        threading.Thread(target=self._load, daemon=True, name="ux-appearance-assets").start()

    def _stale(self, generation):
        with self._lock:
            return generation != self._generation

    def _load(self):
        while True:
            with self._lock:
                request = self._pending
                self._pending = None
                step = self._requested_step
                self._requested_step = None
                if request is None and step is None:
                    self._running = False
                    return
                generation = self._generation
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
                        step = self._step_for(self.yaw)
                else:
                    model, textures = self._model, self._textures
                if model is None or self._stale(generation):
                    continue
                with self._lock:
                    cached = self._frames_generation == generation and step in self._frames
                if cached:
                    self._show(step)
                    continue
                faces = model.project(step * 360 / STEPS, PITCH)
                image = render_frame([face for face in faces if face.index in textures], textures)
                box = image.getchannel("A").getbbox()
                if not box:
                    raise ValueError("empty model")
                left, top = max(0, box[0] - 2), max(0, box[1] - 2)
                right, bottom = min(STAGE_W, box[2] + 2), min(STAGE_H, box[3] + 2)
                width, height = right - left, bottom - top
                stage = ft.Container(
                    content=ft.Image(src=_png(image.crop((left, top, right, bottom))), width=width, height=height,
                                     fit=ft.BoxFit.FILL, gapless_playback=True,
                                     filter_quality=ft.FilterQuality.MEDIUM, data=f"appearance-frame:{step}"),
                    left=left, top=top, width=width, height=height, opacity=0)
                with thread_safe_ui.TREE_LOCK, self._lock:
                    if generation != self._generation:
                        continue
                    if self._frames_generation != generation:
                        self._frames = {}
                        self._frames_generation = generation
                        self._shown = None
                        shadow = ft.Container(
                            left=STAGE_W / 2 - 42, top=bottom - 12, width=84, height=10, border_radius=42,
                            bgcolor="#22000000",
                            shadow=ft.BoxShadow(blur_radius=16, spread_radius=2, color="#55000000"))
                        self.scene.controls[:] = [shadow]
                    self._frames[step] = stage
                    self.scene.controls.append(stage)
                    if self._shown is None or step == self._step_for(self.yaw):
                        old = self._frames.get(self._shown)
                        if old is not None:
                            old.opacity = 0
                        stage.opacity = 1
                        self._shown = step
                    self.note.value = "Use the arrows to rotate"
                thread_safe_ui.refresh(self.scene)
                thread_safe_ui.refresh(self.note)
            except Exception:
                logging.getLogger(__name__).exception("Could not render appearance preview")
                with thread_safe_ui.TREE_LOCK, self._lock:
                    if generation != self._generation:
                        continue
                    self.note.value = "Couldn't load preview. Choose another skin or cape."
                thread_safe_ui.refresh(self.note)
