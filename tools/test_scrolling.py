"""Headless checks for native scroll animation and bounded, lazy lists."""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import _sandbox_home
_sandbox_home.isolate()

import flet as ft
from cubeon import motion, scrolling
from _fuzz_common import every_control, walk
import app_driver
from ui.versions import VersionPicker, InstancesManager
from ui.screenshot_gallery import build_screenshot_gallery_tab

passed = 0
failed = 0


def check(label, condition):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'}   {label}")


class ScrollPage:
    def __init__(self):
        self.calls = []

    def run_task(self, handler, **kwargs):
        self.calls.append(kwargs)
        return asyncio.run(handler(**kwargs))


page = ScrollPage()
viewport = ft.ListView()
commands = []


async def record_method(name, args):
    commands.append((name, args))


viewport._invoke_method = record_method
motion.set_level("full")
scrolling.follow_end(page, viewport)
check("following uses one native scroll command, not Python animation frames", len(commands) == 1)
check("normal following has a short ease-out animation",
      commands[0] == ("scroll_to", {"offset": -1, "delta": None, "scroll_key": None,
                                 "duration": 180, "curve": ft.AnimationCurve.EASE_OUT_CUBIC}))
motion.set_level("reduced")
scrolling.follow_end(page, viewport)
check("reduced motion takes effect on the very next scroll", commands[-1][1]["duration"] == 0)
check("automatic following uses the same reduced-motion policy", scrolling.animation().duration == 0)
motion.set_level("full")

picker = VersionPicker(page, get_selected=lambda: None, label_for=None,
                       on_pick=lambda value: None, on_browse_online=lambda: None)
check("version picker builds rows on demand", isinstance(picker.list, ft.ListView) and picker.list.build_controls_on_demand)
check("version picker stays bounded and preloads a small nearby area", picker.list.height == 320 and picker.list.cache_extent == 320)
manager = InstancesManager(page, get_instances=lambda: [], get_selected=lambda: None,
                           on_play=lambda value: None, on_rename=lambda *args: None,
                           on_delete=lambda value: None)
manager._render()
check("instance manager uses a bounded lazy viewport",
      isinstance(manager._body, ft.ListView) and manager._body.build_controls_on_demand and manager._body.height == 420)
gallery, _refresh = build_screenshot_gallery_tab(page)
check("screenshot thumbnails use a lazy native viewport",
      any(isinstance(control, ft.ListView) and control.build_controls_on_demand for control in walk(gallery)))

driver = app_driver.build_headless()
driver.open_tab("server_console")
console = next(control for control in every_control(driver.page)
               if isinstance(control, ft.ListView) and control.auto_scroll)
check("server log follows with client-side animation", console.auto_scroll_animation.duration == 180)
check("server scrolling adds no Python wheel callback", console.on_scroll is None)
driver.open_tab("chat")
transcripts = [control for control in every_control(driver.page)
               if isinstance(control, ft.ListView) and control.on_scroll is not None]
check("chat keeps follow conditional on the reader's scroll position", bool(transcripts) and all(not control.auto_scroll for control in transcripts))
check("chat scroll notifications are throttled without changing native input", bool(transcripts) and all(control.scroll_interval == 50 for control in transcripts))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
