"""A native textured orbit stage; only asset changes need a background worker."""
from io import BytesIO
import os
import threading

import flet as ft

from cubeon.appearance import CharacterModel
from cubeon.appearance_scene import order_faces
from cubeon import thread_safe_ui
from cubeon.theme import TEXT_DIM


class AppearancePreview:
    def __init__(self, cfg, assets_dir=None):
        self.cfg = cfg
        assets_dir = assets_dir or os.path.join(os.path.dirname(os.path.dirname(__file__)), "assets")
        self.default_cape_path = os.path.join(assets_dir, "capes", "cubeon_cape.png")
        self.yaw, self.pitch = 25.0, 10.0
        self._lock = threading.RLock()
        self._generation = 0
        self._pending = None
        self._running = False
        self._model = None
        self._mesh = {}
        self._draw_order = []
        self.scene = ft.Stack([], width=320, height=440, clip_behavior=ft.ClipBehavior.NONE,
                              data="appearance-model")
        self.note = ft.Text("Loading preview…", size=11, color=TEXT_DIM)
        self.gesture = ft.GestureDetector(content=self.scene, on_pan_update=self._drag,
                                          drag_interval=16, mouse_cursor=ft.MouseCursor.GRAB,
                                          data="appearance-orbit")
        self.control = ft.Column([
            ft.Container(content=self.gesture, width=320, height=440, alignment=ft.Alignment.CENTER,
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

    def _drag(self, event):
        delta = getattr(event, "local_delta", None)
        delta_x = getattr(delta, "x", getattr(event, "delta_x", 0)) or 0
        delta_y = getattr(delta, "y", getattr(event, "delta_y", 0)) or 0
        with self._lock:
            self.yaw = (self.yaw + float(delta_x) * 0.7) % 360
            self.pitch = max(-75, min(75, self.pitch + float(delta_y) * 0.5))
        self.refresh()

    def turn(self, degrees):
        with self._lock:
            self.yaw = (self.yaw + degrees) % 360
        self.refresh()

    def reset(self, event=None):
        with self._lock:
            self.yaw, self.pitch = 25.0, 10.0
        self.refresh()

    def refresh(self, *, invalidate=False):
        start_worker = False
        with self._lock:
            if invalidate or (self._model is None and not self._running):
                self._generation += 1
                self._pending = (self._generation, dict(self.cfg))
                if not self._running:
                    self._running = True
                    start_worker = True
            loaded = self._model is not None
        if loaded:
            self._draw()
        if start_worker:
            threading.Thread(target=self._load, daemon=True, name="ux-appearance-assets").start()

    def _draw_locked(self):
        projected = order_faces(self._model.project(self.yaw, self.pitch), self._draw_order)
        visible = {face.index for face in projected}
        for index, plane in self._mesh.items():
            plane.opacity = 1 if index in visible else 0
        for face in projected:
            origin, horizontal, vertical = face.points
            width, height = face.texture.size
            matrix = (ft.Matrix4.identity()
                      .set_entry(0, 0, (horizontal[0] - origin[0]) / width)
                      .set_entry(1, 0, (horizontal[1] - origin[1]) / width)
                      .set_entry(0, 1, (vertical[0] - origin[0]) / height)
                      .set_entry(1, 1, (vertical[1] - origin[1]) / height)
                      .set_entry(0, 3, origin[0]).set_entry(1, 3, origin[1]))
            plane = self._mesh[face.index]
            plane.transform = ft.Transform(matrix, transform_hit_tests=False, filter_quality=ft.FilterQuality.NONE)
            lighting = 0.72 + 0.28 * max(0, face.normal[1] * 0.5 + face.normal[2] * 0.8)
            shade = min(255, round(lighting * 255))
            plane.content.color = f"#{shade:02X}{shade:02X}{shade:02X}"
        self.scene.controls[:] = ([self._mesh[face.index] for face in projected]
                                 + [plane for index, plane in self._mesh.items() if index not in visible])
        self._draw_order = [face.index for face in projected]

    def _draw(self):
        with thread_safe_ui.TREE_LOCK, self._lock:
            if self._model is None:
                return
            self._draw_locked()
        thread_safe_ui.refresh(self.scene)

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
                mesh = {}
                for index, face in enumerate(model.faces):
                    if not face.texture.getbbox():
                        continue
                    source = BytesIO()
                    face.texture.save(source, format="PNG")
                    width, height = face.texture.size
                    texture = ft.Image(src=source.getvalue(), width=width, height=height,
                                       fit=ft.BoxFit.FILL, gapless_playback=True,
                                       color_blend_mode=ft.BlendMode.MODULATE, filter_quality=ft.FilterQuality.NONE,
                                       data=f"appearance-texture:{index}")
                    mesh[index] = ft.Container(content=texture, left=0, top=0, width=width, height=height,
                                               opacity=0)
                with thread_safe_ui.TREE_LOCK, self._lock:
                    if generation != self._generation:
                        continue
                    self._model, self._mesh = model, mesh
                    self._draw_order = []
                    self._draw_locked()
                    self.note.value = "Drag to rotate · up/down to tilt"
                thread_safe_ui.refresh(self.scene)
                thread_safe_ui.refresh(self.note)
            except Exception:
                with thread_safe_ui.TREE_LOCK, self._lock:
                    if generation != self._generation:
                        continue
                    self.note.value = "Couldn't load preview. Choose another skin or cape."
                thread_safe_ui.refresh(self.note)
