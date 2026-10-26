"""Playtime histogram with a 7 / 30 / 60 / 90 day range selector."""
from datetime import date

import flet as ft

from cubeon import activity, milestones, thread_safe_ui
from cubeon.theme import ACCENT_TINT_HI
from ui.activity_widgets import ActivityHistogram

RANGES = (7, 30, 60, 90)
MAX_BARS = 30  # longer ranges group days so the chart never gets crowded


def _grouped(summary, days):
    """-> (bar_hours, labels, days_per_bar). Daily up to 30 days, then 2 / 3-day bars."""
    step = max(1, -(-days // MAX_BARS))
    hours, labels = [], []
    for index in range(0, days, step):
        hours.append(sum(summary["hours"][index:index + step]))
        start = date.fromisoformat(summary["dates"][index])
        if days == 7:
            labels.append(start.strftime("%a"))
        elif (index // step) % 5 == 0:
            labels.append(f"{start.strftime('%b')} {start.day}")
        else:
            labels.append("")
    return hours, labels, step


def build_stats_tab(page: ft.Page, cfg: dict, state: dict, *,
                    section_label, go_to_tab,
                    BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                    TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO):
    selected = {"days": RANGES[0]}
    playtime = ft.Text("0.0 h", size=26, color=TEXT, font_family=FONT_DISPLAY)
    chart_title = ft.Text("Last 7 days", size=14, color=TEXT, weight=ft.FontWeight.W_600)
    range_summary_text = ft.Text("", size=12, color=TEXT_DIM)
    bar_note = ft.Text("", size=11, color=TEXT_DIM)
    note = ft.Text("", size=11, color=TEXT_DIM, visible=False)
    histogram = ActivityHistogram("activity-histogram")

    def refresh_stats():
        stats = milestones.load_state()
        days = selected["days"]
        playtime.value = f"{activity.nonnegative(stats.get('seconds_played')) / 3600:,.1f} h"
        summary = activity.range_summary(stats, days)
        hours, labels, step = _grouped(summary, days)
        histogram.set_series([(summary["label"], hours, ACCENT)], labels)

        total = sum(summary["hours"])
        active = summary["active_days"]
        chart_title.value = summary["label"]
        range_summary_text.value = (
            f"{total:,.1f} h played · {active} active day{'s' if active != 1 else ''}"
            + (f" · avg {total / active:,.1f} h on days you played" if active else ""))
        bar_note.value = "Hours per day" if step == 1 else f"Each bar = {step} days"
        note.value = "Daily history starts with your next session. Your existing total playtime is kept."
        note.visible = not bool(stats.get("activity"))
        for control in (playtime, chart_title, range_summary_text, bar_note, note):
            thread_safe_ui.refresh(control)

    def set_range(index):
        selected["days"] = RANGES[max(0, min(int(index), len(RANGES) - 1))]
        refresh_stats()

    range_picker = ft.CupertinoSlidingSegmentedButton(
        selected_index=0,
        thumb_color=ACCENT_TINT_HI,
        bgcolor=SURFACE_HI,
        padding=3,
        controls=[ft.Container(ft.Text(f"{days} days", size=12, color=TEXT,
                                       weight=ft.FontWeight.W_600),
                               padding=ft.padding.Padding.symmetric(horizontal=8, vertical=2))
                  for days in RANGES],
        on_change=lambda event: set_range(event.control.selected_index),
    )

    stats_tab = ft.Column([
        ft.Text("Stats", size=28, color=TEXT, font_family=FONT_DISPLAY),
        ft.Text("Your time in game, day by day.", size=13, color=TEXT_DIM),
        ft.Container(height=14),
        playtime,
        ft.Text("Total playtime", size=11, color=TEXT_DIM),
        ft.Container(height=14),
        ft.Row([chart_title, range_picker],
               alignment=ft.MainAxisAlignment.SPACE_BETWEEN,
               vertical_alignment=ft.CrossAxisAlignment.CENTER, wrap=True),
        range_summary_text,
        histogram.control,
        bar_note,
        note,
    ], spacing=6, scroll=ft.ScrollMode.AUTO)
    return stats_tab, refresh_stats
