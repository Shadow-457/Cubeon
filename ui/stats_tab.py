"""Playtime overview, day/week timeline, and server activity."""
from collections import Counter
from datetime import date, datetime, timedelta

import flet as ft

from cubeon import activity, milestones, thread_safe_ui
from cubeon.theme import FONT_BODY
from ui.stats_chart import PlaytimeChart

DAYS = 30


def _chart_values(summary, weekly=False):
    dates = [date.fromisoformat(value) for value in summary["dates"]]
    if weekly:
        groups = {}
        for day, hours in zip(dates, summary["hours"]):
            monday = day - timedelta(days=day.weekday())
            groups[monday] = groups.get(monday, 0) + hours
        return list(groups.values()), [day.strftime("%d %b") for day in groups]
    labels = [day.strftime("%d %b") if index in (0, 10, 20) else "" for index, day in enumerate(dates)]
    labels[-1] = "Today"
    return summary["hours"], labels


def build_stats_tab(page: ft.Page, cfg: dict, state: dict, *,
                    section_label, go_to_tab,
                    BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                    TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO):
    selected = {"weekly": False}
    layout = {"width": 1000, "height": 600, "overview": 112, "server_count": 0}
    cached = {"stats": {}}
    rim = ft.Colors.with_opacity(.65, BORDER)

    def text(value, size=12, muted=False, **kwargs):
        return ft.Text(value, size=size, color=TEXT_DIM if muted else TEXT, font_family=FONT_BODY, **kwargs)

    def panel(content, **kwargs):
        return ft.Container(content=content, bgcolor=SURFACE, border=ft.border.Border.all(1, rim),
                            border_radius=12, padding=16, **kwargs)

    metric_values, metric_details, metrics = [], [], []
    for index, label in enumerate(("Total playtime", "Last 7 days", "Longest session", "Current streak")):
        value = text("—", size=25, weight=ft.FontWeight.W_700, max_lines=1,
                     overflow=ft.TextOverflow.ELLIPSIS, data=f"stats-metric:{index}")
        detail = text("", size=11, muted=True, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
        metric_values.append(value)
        metric_details.append(detail)
        metrics.append(ft.Container(
            content=ft.Column([text(label, size=11, muted=True), value, detail], spacing=5),
            padding=ft.padding.Padding.symmetric(horizontal=18, vertical=16), col={"xs": 6, "md": 3},
            border=ft.border.Border(left=ft.border.BorderSide(1, rim)) if index else None))
    overview = ft.Container(content=ft.ResponsiveRow(metrics, spacing=0, run_spacing=0), bgcolor=SURFACE,
                            border=ft.border.Border.all(1, rim), border_radius=12, data="stats-overview")
    chart = PlaytimeChart(ACCENT, rim, TEXT_DIM)

    def draw_chart():
        summary = activity.range_summary(cached["stats"], DAYS)
        chart.set_values(*_chart_values(summary, selected["weekly"]))

    def change_group(event):
        with thread_safe_ui.TREE_LOCK:
            selected["weekly"] = event.control.selected_index == 1
            draw_chart()

    grouping = ft.CupertinoSlidingSegmentedButton(
        selected_index=0, thumb_color=SURFACE_HI, bgcolor=BG, padding=2,
        controls=[ft.Container(text(label, size=11), padding=ft.padding.Padding.symmetric(horizontal=10, vertical=4))
                  for label in ("Day", "Week")], on_change=change_group, data="stats-chart-grouping")
    timeline = panel(ft.Column([
        ft.ResponsiveRow([
            ft.Container(ft.Row([text("Hours played", weight=ft.FontWeight.W_600),
                                 text("Last 30 days", size=11, muted=True)], spacing=8), col={"xs": 12, "sm": 6}),
            ft.Container(ft.Row([grouping], alignment=ft.MainAxisAlignment.END), col={"xs": 12, "sm": 6}),
        ], spacing=0, run_spacing=6), chart.control,
    ], spacing=8), data="stats-timeline")
    servers = ft.Column([], spacing=14, data="stats-servers")
    server_panel = panel(ft.Column([text("Where you play", weight=ft.FontWeight.W_600), servers], spacing=16),
                         height=264, data="stats-server-panel")

    panels = ft.Row([timeline, server_panel], wrap=True, spacing=14, run_spacing=14,
                    vertical_alignment=ft.CrossAxisAlignment.START)
    body = ft.Column([overview, panels],
                     spacing=14, scroll=ft.ScrollMode.AUTO, data="stats-content")
    root = ft.Container(content=body, expand=True, data="stats-dashboard")

    def apply_layout():
        stacked = layout["width"] < 900 or not layout["server_count"]
        server_height = max(92, 64 + min(5, layout["server_count"]) * 28) if stacked else None
        available = layout["height"] - layout["overview"] - 14
        timeline_height = max(280, available - (server_height + 14 if stacked else 0))
        # The toolbar wraps below 576px of chart width, independent of window width.
        chart_width = layout["width"] if stacked else (layout["width"] - 14) * .75
        toolbar_height = 60 if chart_width - 32 < 576 else 32
        timeline.width = layout["width"] if stacked else (layout["width"] - 14) * .75
        server_panel.width = layout["width"] if stacked else (layout["width"] - 14) * .25
        timeline.height = timeline_height
        server_panel.height = server_height if stacked else timeline_height
        chart.set_height(timeline_height - 32 - toolbar_height - 8)
        thread_safe_ui.refresh(body)

    def layout_changed(event):
        with thread_safe_ui.TREE_LOCK:
            width, height = float(event.width or 1000), float(event.height or 600)
            if (width, height) != (layout["width"], layout["height"]):
                layout.update(width=width, height=height, overview=112 if width >= 768 else 224)
                apply_layout()
    root.on_size_change = layout_changed

    def overview_changed(event):
        with thread_safe_ui.TREE_LOCK:
            height = float(event.height or layout["overview"])
            if abs(height - layout["overview"]) > 1:
                layout["overview"] = height
                apply_layout()
    overview.on_size_change = overview_changed

    def refresh_stats():
        stats = milestones.snapshot()
        records = activity.clean_sessions(stats.get("session_history"))
        with thread_safe_ui.TREE_LOCK:
            cached["stats"] = stats
            recent = activity.period_summary(stats, "recent_week")
            prior = activity.period_summary(stats, "previous_week")["seconds_played"]
            current, best = activity.streaks(stats)
            longest = max(activity.nonnegative(stats.get("longest_session_seconds")),
                          max((row["seconds"] for row in records), default=0))
            values = [activity.duration_label(stats.get("seconds_played")),
                      activity.duration_label(recent["seconds_played"]),
                      activity.duration_label(longest) if longest else "—", f"{current} day{'s' if current != 1 else ''}"]
            stamp = activity.nonnegative(stats.get("first_seen_at"))
            try:
                since = "Since " + datetime.fromtimestamp(stamp).strftime("%d %b") if stamp else "All recorded playtime"
            except (ValueError, OverflowError, OSError):
                since = "All recorded playtime"
            change = (recent["seconds_played"] - prior) / prior * 100 if prior else None
            comparison = (f"{abs(change):.0f}% {'more' if change >= 0 else 'less'} than the week before" if change else
                          "Same as the week before" if recent["seconds_played"] == prior else "No playtime the week before")
            details = [since, comparison, "Across recorded sessions", f"Best: {best} day{'s' if best != 1 else ''}"]
            for control, value, detail, caption in zip(metric_values, values, metric_details, details):
                control.value, detail.value = value, caption
            cutoff = date.today() - timedelta(days=DAYS-1)
            counts = Counter(server for row in records if cutoff <= datetime.fromtimestamp(row["started"]+row["seconds"]).date() <= date.today()
                             for server in row["servers"])
            servers.controls[:] = [text("No servers in this range.", size=11, muted=True)] if not counts else [
                ft.Row([ft.Container(content=text(server, size=11, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                     expand=True, tooltip=server),
                        text(f"{count} session{'s' if count != 1 else ''}", size=10, muted=True)], spacing=8)
                for server, count in counts.most_common(5)]
            layout["server_count"] = len(counts)
            apply_layout()
            draw_chart()
            thread_safe_ui.refresh(overview)
            thread_safe_ui.refresh(servers)

    refresh_stats()
    return root, refresh_stats
