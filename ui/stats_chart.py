"""Responsive playtime timeline for the Stats dashboard."""
import math

import flet as ft
import flet.canvas as canvas

from cubeon import activity, thread_safe_ui


class PlaytimeChart:
    def __init__(self, accent, border, muted):
        self.accent, self.border, self.muted = accent, border, muted
        self.width, self.height = 620, 190
        self.hours, self.labels = [], []
        self.canvas = canvas.Canvas(
            height=self.height, content=ft.Container(height=self.height),
            on_resize=self._resize, resize_interval=100, data="activity-histogram")
        self.control = ft.Container(content=self.canvas, height=self.height)

    def set_height(self, height):
        with thread_safe_ui.TREE_LOCK:
            height = max(170, float(height))
            if height == self.height:
                return
            self.height = height
            self.control.height = self.canvas.height = self.canvas.content.height = height
            self._draw()
            thread_safe_ui.refresh(self.control)

    def set_values(self, hours, labels):
        with thread_safe_ui.TREE_LOCK:
            self.hours = [activity.nonnegative(value) for value in hours]
            self.labels = labels
            self._draw()

    def _resize(self, event):
        with thread_safe_ui.TREE_LOCK:
            self.width = max(180, float(event.width or self.width))
            self._draw()

    def _draw(self):
        left, right, top, bottom = 30, self.width - 8, 12, self.height - 27
        peak = max(4, max(self.hours, default=0))
        step = 2 if peak <= 12 else 5 if peak <= 30 else 10 ** max(1, int(math.log10(peak)) - 1)
        maximum = math.ceil(peak / step) * step
        self.canvas.cubeon_chart_maximum = maximum
        self.canvas.cubeon_series = [("Hours played", self.hours, self.accent)]
        shapes = []
        for fraction in (1, .5, 0):
            y = bottom - (bottom - top) * fraction
            shapes.extend([
                canvas.Line(left, y, right, y, paint=ft.Paint(color=self.border, stroke_width=1)),
                canvas.Text(0, y, f"{maximum * fraction:g}h", style=ft.TextStyle(size=10, color=self.muted),
                            alignment=ft.Alignment.CENTER_LEFT),
            ])
        count = len(self.hours)
        slot = (right - left) / max(1, count - 1)
        points = [(left + index * slot, bottom - (bottom - top) * value / maximum)
                  for index, value in enumerate(self.hours)]
        if any(self.hours):
            path = [canvas.Path.MoveTo(left, bottom)]
            path.extend(canvas.Path.LineTo(x, y) for x, y in points)
            path.extend([canvas.Path.LineTo(points[-1][0], bottom), canvas.Path.Close()])
            shapes.append(canvas.Path(path, paint=ft.Paint(color=ft.Colors.with_opacity(.08, self.accent))))
            shapes.extend(canvas.Line(x, y, next_x, next_y,
                                      paint=ft.Paint(color=self.accent, stroke_width=2), data="Hours played")
                          for (x, y), (next_x, next_y) in zip(points, points[1:]))
            if count == 1:
                shapes.append(canvas.Circle(points[0][0], points[0][1], 3, paint=ft.Paint(color=self.accent)))
        for index, label in enumerate(self.labels):
            if label:
                x = left + index * slot
                alignment = ft.Alignment.CENTER_LEFT if index == 0 else ft.Alignment.CENTER_RIGHT if index == count-1 else ft.Alignment.CENTER
                shapes.append(canvas.Text(x, self.height - 9, label, style=ft.TextStyle(size=10, color=self.muted),
                                          alignment=alignment))
        self.canvas.shapes[:] = shapes
        thread_safe_ui.refresh(self.canvas)
