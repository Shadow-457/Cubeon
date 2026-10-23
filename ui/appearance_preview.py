"""A drag-to-orbit skin and cape stage with one coalescing render worker."""
from collections import OrderedDict
import os
import threading

import flet as ft

from cubeon.appearance import CharacterModel
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
        self._asset_generation = 0
        self._pending = None
        self._running = False
        self._model_key = None
        self._model = None
        self._frames = OrderedDict()
        self.image = ft.Image(src="icon.svg", width=320, height=440, fit=ft.BoxFit.CONTAIN,
                              visible=False, gapless_playback=True, data="appearance-model")
        self.note = ft.Text("Loading preview…", size=11, color=TEXT_DIM)
        self.gesture = ft.GestureDetector(content=self.image, on_pan_update=self._drag,
                                          drag_interval=32, mouse_cursor=ft.MouseCursor.GRAB,
                                          data="appearance-orbit")
        self.control = ft.Column([
            ft.Container(content=self.gesture, height=440, alignment=ft.Alignment.CENTER),
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
        with self._lock:
            self._generation += 1
            if invalidate:
                self._asset_generation += 1
            self._pending = (self._generation, dict(self.cfg), self.yaw, self.pitch, self._asset_generation)
            if self._running:
                return
            self._running = True
        threading.Thread(target=self._render, daemon=True, name="ux-appearance-preview").start()

    def _render(self):
        while True:
            with self._lock:
                request = self._pending
                self._pending = None
                if request is None:
                    self._running = False
                    return
            generation, cfg, yaw, pitch, asset_generation = request
            try:
                model_key = (cfg.get("active_skin"), cfg.get("active_cape"), asset_generation)
                if self._model is None or model_key != self._model_key:
                    self._model = CharacterModel.from_config(cfg, self.default_cape_path)
                    self._model_key = model_key
                    self._frames.clear()
                frame_key = (round(yaw, 1), round(pitch, 1))
                source = self._frames.get(frame_key)
                if source is None:
                    source = self._model.png(yaw, pitch)
                    self._frames[frame_key] = source
                    if len(self._frames) > 48:
                        self._frames.popitem(last=False)
                else:
                    self._frames.move_to_end(frame_key)
                with thread_safe_ui.TREE_LOCK, self._lock:
                    if generation != self._generation:
                        continue
                    self.image.src = source
                    self.image.visible = True
                    self.note.value = "Drag to rotate · up/down to tilt"
                thread_safe_ui.refresh(self.image)
                thread_safe_ui.refresh(self.note)
            except Exception:
                with thread_safe_ui.TREE_LOCK, self._lock:
                    if generation != self._generation:
                        continue
                    self.note.value = "Couldn't load preview. Choose another skin or cape."
                thread_safe_ui.refresh(self.note)
