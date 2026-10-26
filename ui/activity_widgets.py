"""Small, dependency-free activity charts and earned account badges."""
import flet as ft
import flet.canvas as canvas

from cubeon import activity, thread_safe_ui
from cubeon.theme import CARD_BORDER, FONT_MONO, TEXT_DIM


def build_badges(state, collections=None):
    icons = {"playtime": ft.Icons.SPORTS_ESPORTS_ROUNDED,
             "hosting": ft.Icons.DNS_ROUNDED, "friends": ft.Icons.PEOPLE_ROUNDED,
             "library": ft.Icons.INVENTORY_2_OUTLINED}
    earned = activity.earned_badges(state, collections)
    badges = [badge for badge in earned if badge["key"] in icons]
    library = [badge for badge in earned if badge["key"] not in icons and badge["key"] != "member"]
    if library:
        details = [badge["detail"] for badge in library]
        details.extend(badge["detail"] for badge in earned if badge["key"] == "member")
        badges.append({"key": "library", "label": "Library", "detail": "\n".join(details)})
    return [ft.Container(
        content=ft.Icon(icons[badge["key"]], size=17, color=TEXT_DIM),
        width=26, height=26, alignment=ft.Alignment.CENTER,
        tooltip=f"{badge['label']}\n{badge['detail']}", data=f"activity-badge:{badge['key']}",
    ) for badge in badges]


class ActivityHistogram:
    def __init__(self, name):
        self.width = 560
        self.height = 176
        self.series = []
        self.labels = []
        self.canvas = canvas.Canvas(
            height=self.height, content=ft.Container(height=self.height),
            on_resize=self._resize, resize_interval=100, data=name)
        self.control = ft.Container(content=self.canvas, height=self.height)

    def set_series(self, series, labels):
        self.series = series
        self.labels = labels
        self._draw()

    def _resize(self, event=None):
        width = getattr(event, "width", self.width) or self.width
        self.width = max(180, float(width))
        self._draw()

    def _draw(self):
        left, right, top, bottom = 44, self.width - 12, 14, self.height - 28
        maximum = max(1.0, max((max(values, default=0) for _label, values, _color in self.series), default=0))
        self.canvas.cubeon_chart_maximum = maximum
        self.canvas.cubeon_series = self.series
        shapes = []
        for fraction in (0, 0.5, 1):
            height = bottom - (bottom - top) * fraction
            shapes.append(canvas.Line(left, height, right, height,
                                      paint=ft.Paint(color=CARD_BORDER, stroke_width=1)))
            shapes.append(canvas.Text(0, height, f"{maximum * fraction:.1f}h",
                                      style=ft.TextStyle(size=10, color=TEXT_DIM, font_family=FONT_MONO),
                                      alignment=ft.Alignment.CENTER_LEFT))
        count = max((len(values) for _label, values, _color in self.series), default=0)
        slot = (right - left) / max(1, count)
        series_count = max(1, len(self.series))
        bar_width = slot * 0.68 / series_count
        for series_index, (label, values, color) in enumerate(self.series):
            for index, value in enumerate(values):
                height = (bottom - top) * value / maximum
                position = left + slot * index + slot * 0.16 + series_index * bar_width
                if height:
                    shapes.append(canvas.Rect(position, bottom - height, max(1.0, bar_width - (2 if bar_width > 6 else 1)), height,
                                              border_radius=min(3, max(0.5, bar_width / 3)), paint=ft.Paint(color=color), data=label))
        if self.labels:
            for index, label in enumerate(self.labels):
                if not label:  # long ranges label only every few bars
                    continue
                position = left + slot * (index + 0.5)
                shapes.append(canvas.Text(position, self.height - 10, self.labels[index],
                                          style=ft.TextStyle(size=10, color=TEXT_DIM), alignment=ft.Alignment.CENTER))
        self.canvas.shapes[:] = shapes
        thread_safe_ui.refresh(self.canvas)
