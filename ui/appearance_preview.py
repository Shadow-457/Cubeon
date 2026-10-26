"""A textured character preview with button-controlled rotation.

The character is rendered once per skin/cape into cached turntable frames.
Rotation buttons glide between these frames without rebuilding the scene.
"""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
import math
import os
import threading
import time

import flet as ft
from PIL import Image

from cubeon.appearance import CharacterModel
from cubeon.appearance_scene import order_faces
from cubeon import thread_safe_ui
from cubeon.theme import TEXT_DIM

STAGE_W, STAGE_H = 320, 440
STEPS = 60                  # turntable frames per revolution (6 degrees apart)
SUPERSAMPLE = 2             # render at 2x then box-filter down: clean edges
HOME_YAW, PITCH = 25.0, 10.0
TICK = 1 / 60

_AFFINE = getattr(Image, "Transform", Image).AFFINE
_NEAREST = getattr(Image, "Resampling", Image).NEAREST
_BOX = getattr(Image, "Resampling", Image).BOX


def _shade(texture, factor):
    if factor >= 0.999:
        return texture
    red, green, blue, alpha = texture.split()
    table = [min(255, int(i * factor + 0.5)) for i in range(256)]
    return Image.merge("RGBA", (red.point(table), green.point(table), blue.point(table), alpha))


def render_frame(faces, textures, supersample=SUPERSAMPLE):
    """Paint already depth-ordered projected faces into one RGBA stage image."""
    width, height = STAGE_W * supersample, STAGE_H * supersample
    canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    for face in faces:
        texture = textures.get(face.index)
        if texture is None:
            continue
        origin, horizontal, vertical = face.points
        tex_w, tex_h = texture.size
        ox, oy = origin[0] * supersample, origin[1] * supersample
        a = (horizontal[0] - origin[0]) * supersample / tex_w
        c = (horizontal[1] - origin[1]) * supersample / tex_w
        b = (vertical[0] - origin[0]) * supersample / tex_h
        d = (vertical[1] - origin[1]) * supersample / tex_h
        det = a * d - b * c
        if abs(det) < 1e-6:          # edge-on: nothing to see
            continue
        xs = (ox, ox + a * tex_w, ox + b * tex_h, ox + a * tex_w + b * tex_h)
        ys = (oy, oy + c * tex_w, oy + d * tex_h, oy + c * tex_w + d * tex_h)
        x0, x1 = max(0, math.floor(min(xs))), min(width, math.ceil(max(xs)))
        y0, y1 = max(0, math.floor(min(ys))), min(height, math.ceil(max(ys)))
        if x1 <= x0 or y1 <= y0:
            continue
        # PIL wants output -> texture. Invert the texture -> screen matrix, with
        # the crop offset folded in so only the face's own box is sampled.
        coeffs = (d / det, -b / det, (d * (x0 - ox) - b * (y0 - oy)) / det,
                  -c / det, a / det, (-c * (x0 - ox) + a * (y0 - oy)) / det)
        lighting = 0.72 + 0.28 * max(0, face.normal[1] * 0.5 + face.normal[2] * 0.8)
        piece = _shade(texture, lighting).transform(
            (x1 - x0, y1 - y0), _AFFINE, coeffs, _NEAREST)
        canvas.alpha_composite(piece, (x0, y0))
    if supersample > 1:
        canvas = canvas.resize((STAGE_W, STAGE_H), _BOX)
    return canvas


def _png(image):
    buffer = BytesIO()
    image.save(buffer, format="PNG", compress_level=3)
    return buffer.getvalue()


class AppearancePreview:
    def __init__(self, cfg, assets_dir=None):
        self.cfg = cfg
        assets_dir = assets_dir or os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
        self.default_cape_path = os.path.join(assets_dir, "capes", "cubeon_cape.png")
        self.yaw, self.pitch = HOME_YAW, PITCH
        self._lock = threading.RLock()
        self._generation = 0
        self._pending = None
        self._running = False
        self._frames = []          # one Container per turntable step
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
        """Flip visibility between two pre-rendered frames; nothing else moves."""
        with thread_safe_ui.TREE_LOCK, self._lock:
            frames = self._frames
            if not frames or step == self._shown:
                return
            old = frames[self._shown] if self._shown is not None and self._shown < len(frames) else None
            new = frames[step]
            new.opacity = 1          # show the new one first so there is never a blank frame
            if old is not None:
                old.opacity = 0
            self._shown = step
        thread_safe_ui.refresh(new)
        if old is not None:
            thread_safe_ui.refresh(old)

    def _cancel_motion(self):
        with self._lock:
            self._motion += 1
            return self._motion

    def _glide(self, delta, duration=0.3):
        token = self._cancel_motion()
        if not self._frames:
            self.yaw = (self.yaw + delta) % 360
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
                if not self._running:
                    self._running = True
                    start_worker = True
            loaded = bool(self._frames)
        if loaded:
            self._show(self._step_for(self.yaw))
        if start_worker:
            threading.Thread(target=self._load, daemon=True, name="ux-appearance-assets").start()

    def _stale(self, generation):
        with self._lock:
            return generation != self._generation

    def _load(self):
        while True:
            with self._lock:
                request = self._pending
                self._pending = None
                if request is None:
                    self._running = False
                    return
            generation, cfg = request
            try:
                model = CharacterModel.from_config(cfg, self.default_cape_path)
                textures = {}
                for index, face in enumerate(model.faces):
                    if face.texture.getbbox():
                        textures[index] = face.texture.convert("RGBA")
                project_lock = threading.Lock()

                def frame(step):
                    if self._stale(generation):
                        return None
                    with project_lock:
                        faces = order_faces(model.project(step * 360 / STEPS, PITCH), [])
                    return render_frame([f for f in faces if f.index in textures], textures)

                # First paint: only the frame the user is looking at, right away.
                if not self._frames:
                    first = self._step_for(self.yaw)
                    quick = frame(first)
                    if quick is None:
                        continue
                    stage = ft.Container(
                        content=ft.Image(src=_png(quick), width=STAGE_W, height=STAGE_H, fit=ft.BoxFit.FILL,
                                         gapless_playback=True, filter_quality=ft.FilterQuality.MEDIUM),
                        left=0, top=0, width=STAGE_W, height=STAGE_H)
                    with thread_safe_ui.TREE_LOCK, self._lock:
                        if generation != self._generation:
                            continue
                        self.scene.controls[:] = [stage]
                    thread_safe_ui.refresh(self.scene)

                workers = max(1, min(4, os.cpu_count() or 2))
                with ThreadPoolExecutor(max_workers=workers) as pool:
                    images = list(pool.map(frame, range(STEPS)))
                if any(image is None for image in images) or self._stale(generation):
                    continue

                # Crop every frame to the same box (the model's footprint) so the
                # whole ring costs a fraction of 60 full stages in GPU memory.
                boxes = [image.getchannel("A").getbbox() for image in images]
                boxes = [box for box in boxes if box]
                if not boxes:
                    raise ValueError("empty model")
                left = max(0, min(b[0] for b in boxes) - 2)
                top = max(0, min(b[1] for b in boxes) - 2)
                right = min(STAGE_W, max(b[2] for b in boxes) + 2)
                bottom = min(STAGE_H, max(b[3] for b in boxes) + 2)
                width, height = right - left, bottom - top
                frames = [ft.Container(
                    content=ft.Image(src=_png(image.crop((left, top, right, bottom))), width=width, height=height,
                                     fit=ft.BoxFit.FILL, gapless_playback=True,
                                     filter_quality=ft.FilterQuality.MEDIUM, data=f"appearance-frame:{step}"),
                    left=left, top=top, width=width, height=height, opacity=0)
                    for step, image in enumerate(images)]
                # Soft contact shadow under the feet grounds the figure.
                shadow = ft.Container(
                    left=(left + right) / 2 - 42, top=bottom - 12, width=84, height=10, border_radius=42,
                    bgcolor="#22000000",
                    shadow=ft.BoxShadow(blur_radius=16, spread_radius=2, color="#55000000"))

                with thread_safe_ui.TREE_LOCK, self._lock:
                    if generation != self._generation:
                        continue
                    step = self._step_for(self.yaw)
                    frames[step].opacity = 1
                    self._frames, self._shown = frames, step
                    self.scene.controls[:] = [shadow] + frames
                    self.note.value = "Use the arrows to rotate"
                thread_safe_ui.refresh(self.scene)
                thread_safe_ui.refresh(self.note)
            except Exception:
                with thread_safe_ui.TREE_LOCK, self._lock:
                    if generation != self._generation:
                        continue
                    self.note.value = "Couldn't load preview. Choose another skin or cape."
                thread_safe_ui.refresh(self.note)
