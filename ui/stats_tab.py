"""A simple seven-day playtime histogram, with optional previous-week comparison."""
from datetime import date

import flet as ft

from cubeon import activity, milestones, thread_safe_ui
from cubeon.theme import INFO
from ui.activity_widgets import ActivityHistogram


def build_stats_tab(page: ft.Page, cfg: dict, state: dict, *,
                    section_label, go_to_tab,
                    BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                    TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO):
    playtime = ft.Text("0.0 h", size=26, color=TEXT, font_family=FONT_DISPLAY)
    note = ft.Text("", size=11, color=TEXT_DIM, visible=False)
    histogram = ActivityHistogram("activity-histogram")
    recent_label = ft.Text("Last 7 days", size=11, color=ACCENT)
    previous_label = ft.Text("Previous 7 days", size=11, color=INFO, visible=False)
    compare = ft.Checkbox(label="Compare with previous week", value=False,
                          on_change=lambda event: refresh_stats())

    def refresh_stats():
        stats = milestones.load_state()
        playtime.value = f"{activity.nonnegative(stats.get('seconds_played')) / 3600:,.1f} h"
        recent = activity.period_summary(stats, "recent_week")
        series = [("Last 7 days", recent["hours"], ACCENT)]
        if compare.value:
            previous = activity.period_summary(stats, "previous_week")
            series.append(("Previous 7 days", previous["hours"], INFO))
        histogram.set_series(series, [date.fromisoformat(day).strftime("%a") for day in recent["dates"]])
        previous_label.visible = bool(compare.value)
        note.value = "Daily history starts with your next session. Your existing total playtime is kept."
        note.visible = not bool(stats.get("activity"))
        for control in (playtime, previous_label, note):
            thread_safe_ui.refresh(control)

    stats_tab = ft.Column([
        ft.Text("Stats", size=28, color=TEXT, font_family=FONT_DISPLAY),
        ft.Text("Your time in game, day by day.", size=13, color=TEXT_DIM),
        ft.Container(height=14),
        playtime,
        ft.Text("Total playtime", size=11, color=TEXT_DIM),
        ft.Container(height=14),
        ft.Row([ft.Text("Last 7 days", size=14, color=TEXT, weight=ft.FontWeight.W_600), compare],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN, wrap=True),
        ft.Row([recent_label, previous_label], spacing=18),
        histogram.control,
        note,
    ], spacing=6, scroll=ft.ScrollMode.AUTO)
    return stats_tab, refresh_stats
