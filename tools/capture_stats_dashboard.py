"""Capture and exercise the Stats dashboard on an isolated native Flet display."""
import asyncio
from datetime import date, datetime, time as day_time, timedelta
import os
import logging
from pathlib import Path
import sys
from types import SimpleNamespace
import traceback

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
os.environ.setdefault("GALLIUM_DRIVER", "llvmpipe")
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
from PIL import ImageGrab
from cubeon import milestones, thread_safe_ui
from cubeon.theme import THEME, FONT_URLS, section_label
from ui.stats_tab import build_stats_tab
from _fuzz_common import walk

OUT = ROOT / "archive/ui-captures/stats-responsive"


async def main(page):
    page.title = "Cubeon Stats Dashboard Check"
    page.bgcolor = THEME["BG"]
    page.theme_mode = ft.ThemeMode.DARK
    page.fonts = FONT_URLS
    page.theme = ft.Theme(font_family="Inter")
    page.padding = 16
    page.window.width, page.window.height = 1200, 760
    page.window.left, page.window.top = 0, 0
    thread_safe_ui.install(page)
    today = date.today()
    since = datetime.combine(today-timedelta(days=60), day_time.min).timestamp()
    milestones._state = {"first_seen_at": since, "seconds_played": 0, "activity": {}, "session_history": []}
    root, refresh = build_stats_tab(page, {}, {}, section_label=section_label, go_to_tab=lambda *_: None, **THEME)
    root.expand = True
    page.add(root)
    thread_safe_ui.mark_mounted(page)
    page.update()
    OUT.mkdir(parents=True, exist_ok=True)

    async def capture(name):
        await asyncio.sleep(1.2)
        ImageGrab.grab(xdisplay=os.environ["DISPLAY"]).save(OUT / f"{name}.png")
        print("CAPTURE", name, flush=True)

    await asyncio.sleep(3)
    await capture("wide-empty")
    assert not any(isinstance(control, ft.ProgressBar) for control in walk(root))
    history = {(today-timedelta(days=index)).isoformat(): {"seconds_played": hours*3600}
               for index, hours in enumerate([1.6,2.1,.7,0,0,1.2,0,2.8,1.6,2.2,0,0,.5,1.8,2.9,3.2,1.5,0,0,2.6,1.5,0,1.2,2.1,.8,0,0,1.4,2.4,.9])}
    sessions = [{"id": f"fixture-{index}", "started": datetime.combine(today-timedelta(days=index//3), day_time(18-index%3*3)).timestamp(),
                 "seconds": 2100+index%6*720, "profile": "Survival" if index%2 else "Creative",
                 "version": "1.21.11" if index%2 else "26.3",
                 "servers": ["play.example.net"] if index%3 else ["friends.example.net"] if index%2 else []}
                for index in range(67)]
    milestones._state.update(seconds_played=314220, activity=history, session_history=sessions,
                             longest_session_seconds=9120, best_streak_days=8)
    refresh()
    await capture("wide-populated")
    assert root.content.controls[1].controls[0].width > root.content.controls[1].controls[1].width
    controls = list(walk(root))
    chart = next(control for control in controls if control.data == "activity-histogram")
    grouping = next(control for control in controls if control.data == "stats-chart-grouping")
    grouping.selected_index = 1
    grouping.on_change(SimpleNamespace(control=grouping))
    thread_safe_ui.refresh(grouping)
    assert 4 <= len(chart.cubeon_series[0][1]) <= 6
    await capture("wide-week")
    assert len(root.content.controls) == 2
    assert not any(str(control.data).startswith(("stats-session", "stats-most-played", "stats-ranking")) for control in controls)
    grouping.selected_index = 0
    grouping.on_change(SimpleNamespace(control=grouping))
    thread_safe_ui.refresh(grouping)
    page.window.width, page.window.height = 640, 760
    page.update()
    await capture("compact-populated")
    assert root.content.controls[1].controls[0].width == root.content.controls[1].controls[1].width
    page.window.width, page.window.height = 480, 560
    page.update()
    await capture("small-populated")
    assert chart.height >= 170
    page.window.width, page.window.height = 1240, 780
    page.update()
    await capture("large-populated")
    assert chart.height > 450
    print("NATIVE_STATS_PASS: empty/populated, Day/Week, overview/server activity and compact layout.", flush=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    failures, completed = [], []
    async def checked(page):
        try:
            await main(page)
            completed.append(True)
        except Exception:
            failures.append(True)
            traceback.print_exc()
        finally:
            await page.window.close()
    ft.run(checked, assets_dir=str(ROOT / "assets"))
    if not completed:
        print("NATIVE_STATS_FAIL: desktop callback never completed.", flush=True)
    sys.exit(bool(failures) or not completed)
