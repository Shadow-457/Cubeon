"""Capture actual seasonal Play screens using isolated, safe launcher fixtures."""
import asyncio
import io
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))
os.environ.pop("CUBEON_SEASON", None)
os.environ.setdefault("LIBGL_ALWAYS_SOFTWARE", "1")
os.environ.setdefault("GALLIUM_DRIVER", "llvmpipe")
import ux_capture as ux
import flet as ft
import psutil
from PIL import Image

OUT = ROOT / "archive/ui-captures/play-seasons-implemented"


async def run(page):
    stubs = ux._prepare(page, False)
    cfg = stubs.core.load_config()
    cfg.update(seasonal_theme=True, season_overlay=True, season_override="autumn", season_pet=False,
               motion_level="full")
    from cubeon import seasonal
    seasonal.refresh(cfg)
    stubs.core.load_config = lambda: dict(cfg)
    await stubs.app.main(page)
    page.enable_screenshots = True
    await page.window.to_front()
    await asyncio.sleep(2)
    OUT.mkdir(parents=True, exist_ok=True)
    controls = list(ux.every_control(page))
    host = next(c for c in controls if c.data == "play-season-overlay")
    scene = host.content.on_size_change.__self__
    dropdown = next(c for c in controls if getattr(getattr(c, "on_select", None), "__name__", "") == "_on_season_change")
    motion = next(c for c in controls if getattr(getattr(c, "on_change", None), "__name__", "") == "_on_motion_change")
    buddy = next(c for c in controls if getattr(getattr(c, "on_change", None), "__name__", "") == "_on_season_pet_toggle")
    scenery = next(c for c in controls if getattr(getattr(c, "on_change", None), "__name__", "") == "_on_season_overlay_toggle")
    pet_host = next(c for c in controls if c.data == "launcher-roaming-pet")
    pet = pet_host.content.on_size_change.__self__
    nav = ux.discover_nav(page)
    assert not any(getattr(getattr(c, "on_change", None), "__name__", "") == "_on_season_ambience_toggle" for c in controls)

    async def capture(name, *, artwork=True):
        await asyncio.sleep(.6)
        png = await page.take_screenshot(pixel_ratio=1, delay=250)
        (OUT / f"{name}.png").write_bytes(png)
        # A release-mode Flutter ErrorWidget is a featureless gray panel:
        # check actual painted tree colors, not just Python control state.
        from make_play_seasons import STYLES
        palette = {tuple(bytes.fromhex(c[1:])) for c in STYLES[scene.season]["palette"]}
        picture = Image.open(io.BytesIO(png)).convert("RGB")
        painted = sum(n for n, color in picture.getcolors(picture.width * picture.height) if color in palette)
        if artwork:
            assert painted > 2000, f"Seasonal artwork did not render: {painted} pixels"
        else:
            assert painted < 2000, f"Disabled/hidden scenery still rendered: {painted} pixels"
        print(f"Captured {name}: viewport {scene._size}, season {scene.season}", flush=True)

    async def cpu_sample():
        processes = [psutil.Process()]
        processes += [p for p in processes[0].children(recursive=True) if "flet" in p.name().lower()]
        def total():
            return sum(p.cpu_times().user + p.cpu_times().system for p in processes if p.is_running())
        before, stamp = total(), time.monotonic()
        await asyncio.sleep(2)
        return round((total() - before) / (time.monotonic() - stamp) * 100 / (os.cpu_count() or 1), 3)

    try:
        for name in ("spring", "summer", "autumn", "winter"):
            dropdown.value = name
            dropdown.on_select(ux.FakeEvent(dropdown))
            assert scene.season == name
            await capture(name)
        report = {"software_gl": True, "logical_cpus": os.cpu_count(),
                  "visible_motion_cpu_percent": await cpu_sample()}
        motion.value = False
        motion.on_change(ux.FakeEvent(motion))
        assert not scene.animating
        await capture("reduced-motion")
        report["reduced_motion_cpu_percent"] = await cpu_sample()
        motion.value = True
        motion.on_change(ux.FakeEvent(motion))
        ux.reach_tab(page, nav, "mods")
        assert not scene.animating
        tick = scene._tick
        await capture("mods-no-overlay", artwork=False)
        assert scene._tick == tick
        ux.reach_tab(page, nav, "play")
        page.window.width, page.window.height = 1100, 740
        page.update()
        await capture("small-window")
        assert scene._size[0] < 1100, "Rendered resize event never reached the scene"
        page.window.width, page.window.height = 1440, 900
        page.update()
        buddy.value = True
        buddy.on_change(ux.FakeEvent(buddy))
        await asyncio.sleep(.5)
        await page.window.to_front()
        await asyncio.sleep(.3)
        from cubeon import thread_safe_ui
        # Some desktop managers refuse focus-stealing from a capture process.
        # Exercise the real focus handler before advancing the observed route.
        page.window.on_event(SimpleNamespace(type="focus"))
        assert pet.animating, "Native window must be focused for pet motion verification"
        with thread_safe_ui.TREE_LOCK:
            for _ in range(1500):
                pet.step()
                if pet.state == "rest" and pet._rest_kind == "button":
                    break
            assert pet._rest_kind == "button"
            pet.wait = 999
            thread_safe_ui.refresh(pet.particle_layer)
        await capture("pet-on-play")
        scenery.value = False
        scenery.on_change(ux.FakeEvent(scenery))
        assert not scene.enabled and not scene.animating and pet.control.visible
        tick = scene._tick
        await capture("scenery-off", artwork=False)
        assert scene._tick == tick
        scenery.value = True
        scenery.on_change(ux.FakeEvent(scenery))
        ux.reach_tab(page, nav, "mods")
        assert pet.active_tab == "mods" and pet._rest_kind == "floor"
        assert pet.y == pet.size[1] - 32 - 12 and not pet.sprite.rotate
        await capture("pet-tab-switch", artwork=False)
        ux.reach_tab(page, nav, "play")
        with thread_safe_ui.TREE_LOCK:
            pet.wait = 0
            for _ in range(1500):
                pet.step()
                if pet.sprite.rotate and pet.y < 400:
                    break
            assert pet.sprite.rotate
            pet.enabled = False  # Freeze the observed climbing pose for capture.
            thread_safe_ui.refresh(pet.particle_layer)
        await capture("pet-climbing-border")
        motion.value = False
        motion.on_change(ux.FakeEvent(motion))
        assert not pet.animating and pet.sprite.content.src.endswith("-rest.png")
        await capture("pet-reduced-motion")
        (OUT / "verification.json").write_text(json.dumps(report, indent=2))
        print(json.dumps(report), flush=True)
    finally:
        await page.window.close()


if __name__ == "__main__":
    ft.run(run, assets_dir=str(ROOT / "assets"), view=ft.AppView.FLET_APP_HIDDEN)
