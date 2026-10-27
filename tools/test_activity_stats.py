"""Offline activity migration, daily credit, badges, and visual comparison tests."""
from datetime import date, datetime, time as day_time, timedelta
import inspect
import json
import os
import sys
import time
import types

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import activity, milestones
from cubeon.atomicio import write_json

passed = 0
failed = 0


def check(label, condition, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label} {detail}")


today = date.today()
legacy = {"first_seen_at": time.time(), "seconds_played": 9000,
          "sessions_hosted": 8, "friends_count_high": 3}
write_json(milestones.MILESTONES_PATH, legacy)
milestones._state = None
state = milestones.load_state()
check("old playtime and hosting totals survive", state["seconds_played"] == 9000 and state["sessions_hosted"] == 8)
check("old totals never become invented daily history", not state["activity"] and state["sessions_played"] == 0)
check("reading old data leaves the original file intact",
      json.load(open(milestones.MILESTONES_PATH, encoding="utf-8")) == legacy)

started = datetime.combine(today - timedelta(days=1), day_time(23, 30)).timestamp()
milestones.add_play_seconds(7200, started, completed=True)
check("a midnight-spanning session credits yesterday correctly",
      state["activity"][(today - timedelta(days=1)).isoformat()]["seconds_played"] == 1800)
check("a midnight-spanning session credits today correctly",
      state["activity"][today.isoformat()]["seconds_played"] == 5400)
check("a spanning session counts once, not once per day", state["sessions_played"] == 1)
check("lifetime counters still include historical time", state["seconds_played"] == 16200)
milestones.add_hosted_session()
check("hosting records one real daily event without backfilling old hosts",
      state["sessions_hosted"] == 9 and state["activity"][today.isoformat()]["sessions_hosted"] == 1)

session_started = time.time() - 1200
session_id = "activity-test"
milestones.begin_play_session(0, session_started, session_id)
log_path = os.path.join(milestones.CUBEON_HOME, f"game-{session_id}.log")
with open(log_path, "w", encoding="utf-8") as log_file:
    log_file.write("session ended\n")
os.utime(log_path, (session_started + 600, session_started + 600))
credited = milestones.end_play_session(session_id=session_id)
check("real session close credits log-bounded duration", abs(credited - 600) < 0.001)
check("real session close increments recorded sessions", state["sessions_played"] == 2)
check("a duplicate close cannot credit another session",
      milestones.end_play_session(session_id=session_id) == 0 and state["sessions_played"] == 2)
check("daily credit excludes legacy totals",
      abs(sum(bucket["seconds_played"] for bucket in state["activity"].values()) - 7800) < 0.001)

dirty = {"bad-date": {"seconds_played": 8}, today.isoformat(): {"seconds_played": float("nan"),
         "sessions_hosted": -2, "sessions_played": "bad"}}
cleaned = activity.clean_history(dirty)
check("malformed dates and counts never reach charts",
      list(cleaned) == [today.isoformat()] and all(value == 0 for value in cleaned[today.isoformat()].values()))
long_history = {(today - timedelta(days=index)).isoformat(): {"seconds_played": 1} for index in range(800)}
bounded = activity.clean_history(long_history)
check("history stays bounded to 400 days", len(bounded) == activity.HISTORY_DAYS)
check("retention keeps the most recent days", today.isoformat() in bounded)

fixture = dict(legacy, sessions_played=4, activity={
    today.isoformat(): {"seconds_played": 7200, "sessions_played": 2, "sessions_hosted": 2},
    (today - timedelta(days=7)).isoformat(): {"seconds_played": 3600, "sessions_played": 1, "sessions_hosted": 1},
})
first = activity.period_summary(fixture, "recent_week", today=today)
second = activity.period_summary(fixture, "previous_week", today=today)
check("comparison windows have equal, non-overlapping spans",
      len(first["dates"]) == len(second["dates"]) == 7 and not set(first["dates"]) & set(second["dates"]))
check("period comparisons use daily history, not lifetime totals",
      first["seconds_played"] == 7200 and second["seconds_played"] == 3600)
check("daily lines use hours with real zero days", first["hours"][-1] == 2 and sum(first["hours"]) == 2)
check("active days derive from recorded play", first["active_days"] == 1)
check("unknown periods fall back safely", activity.period_summary(fixture, "bad", today=today) == first)
check("30-day comparison is a real 30-day window",
      len(activity.period_summary(fixture, "recent_month", today=today)["hours"]) == 30)
check("no activity means no invented badges", activity.earned_badges({}) == [])
badges = activity.earned_badges({"seconds_played": 360000, "sessions_hosted": 50, "friends_count_high": 20})
check("badges show only the highest earned tier per track",
      [badge["label"] for badge in badges] == ["Veteran", "Community host", "Community"])
check("the old hats/unlock state never returns", "hats" not in state and "unlocks" not in state)

import flet as ft
import app_driver
from _fuzz_common import every_control, walk
from ui.activity_widgets import ActivityHistogram, build_badges
from cubeon import library_stats

chart = ActivityHistogram("test-compare")
chart.set_series([("A", [1, 0], "#46BA34"), ("B", [2, 0], "#4FB4C7")], ["Day 1", "Day 2"])
check("histogram bars share one vertical scale", chart.canvas.cubeon_chart_maximum == 2)
check("both comparison series draw real bars", {shape.data for shape in chart.canvas.shapes if shape.data} == {"A", "B"})
chart._resize(types.SimpleNamespace(width=240))
check("charts adapt to a narrow viewport", chart.width == 240)
chart.set_series([], [])
check("empty charts remain finite", chart.canvas.cubeon_chart_maximum == 1)

milestones._state = fixture
driver = app_driver.build_headless()
switch = inspect.getclosurevars(driver.tabs()["stats"].on_click).nonlocals["switch_tab"]
switch("stats")
controls = every_control(driver.page)
charts = {control.data: control for control in controls if hasattr(control, "cubeon_series")}
check("Stats contains one simple histogram", list(charts) == ["activity-histogram"])
histogram = charts["activity-histogram"]
check("the default histogram is exactly seven days", len(histogram.cubeon_series) == 1 and len(histogram.cubeon_series[0][1]) == 7)
stats_root = inspect.getclosurevars(switch).nonlocals["_tab_views"]["stats"]
stats_controls = list(walk(stats_root))
check("Library and Cosmetics sections are gone from Stats",
      not any(getattr(control, "value", None) in ("LIBRARY", "COSMETICS", "Library", "Cosmetics") for control in stats_controls))
check("Stats has no period dropdowns or collection progress bars",
      not any(isinstance(control, (ft.Dropdown, ft.ProgressBar)) for control in stats_controls))
toggle = next((control for control in controls
               if isinstance(control, ft.Checkbox)
               and "previous" in (control.label or "").lower()), None)
check("the old previous-week comparison toggle stays gone", toggle is None)
check("the simple seven-day histogram is the only series",
      len(histogram.cubeon_series) == 1)

collections = {"versions": 4, "mods": 93, "packs": 0, "content": 0, "plugins": 6, "skins": 1, "capes": 6}
collection_badges = activity.earned_badges(fixture, collections)
check("collection statistics become badges",
      {"versions", "mods", "plugins", "skins", "capes", "member"}
      <= {badge["key"] for badge in collection_badges})
check("zero collections do not award empty badges",
      not {"packs", "content"} & {badge["key"] for badge in collection_badges})
check("counts remain available in badge tooltips",
      any(badge["detail"] == "93 mods installed" for badge in collection_badges))
compact_badges = build_badges(legacy, collections)
check("Account badges fit in one row of at most four icons", len(compact_badges) == 4)
check("badges have no filled pills or visible labels",
      all(isinstance(badge.content, ft.Icon) and badge.bgcolor is None and badge.border is None
          and badge.width == 26 and badge.height == 26 for badge in compact_badges))
library_badge = next(badge for badge in compact_badges if badge.data == "activity-badge:library")
check("one Library badge preserves all collection details on hover",
      all(detail in library_badge.tooltip for detail in ("4 versions installed", "93 mods installed", "6 server plugins", "Playing since")))
check("membership alone does not add badge clutter", build_badges({"first_seen_at": time.time()}) == [])
check("empty accounts have no badge placeholder", build_badges({}) == [])
library_stats.collect_library = lambda: collections

for control in controls:
    handler = getattr(control, "on_click", None)
    if callable(handler) and "_open_account_panel" in inspect.getclosurevars(handler).nonlocals:
        handler(None)
        break
deadline = time.monotonic() + 2
while time.monotonic() < deadline:
    account_badges = [control for control in every_control(driver.page)
                      if isinstance(getattr(control, "data", None), str) and control.data.startswith("activity-badge:")]
    if any(control.data == "activity-badge:library" for control in account_badges):
        break
    time.sleep(0.01)
check("compact collection badge appears in Account", any(control.data == "activity-badge:library" for control in account_badges))
check("Account never renders individual collection or Member pills",
      len(account_badges) <= 4 and not any(control.data in ("activity-badge:mods", "activity-badge:member") for control in account_badges))
check("Stats itself contains no badge or collection clutter",
      not any(isinstance(getattr(control, "data", None), str) and control.data.startswith("activity-badge:") for control in stats_controls))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
