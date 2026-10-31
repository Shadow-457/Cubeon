"""Skin opening stays off the raster path; --native probes the pinned desktop UI."""
import asyncio
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common as fz
import flet as ft
from PIL import Image
from app_driver import DriverPage
from cubeon import cosmetics, thread_safe_ui
from cubeon.theme import THEME, section_label, pixel_divider
import ui.skin_tab as skin_ui
import ui.appearance_preview as preview_ui


def build(page):
    return skin_ui.build_skin_section(page, {'active_back_item': 'back_ember_wings'},
        section_label=section_label, pixel_divider=pixel_divider, **THEME,
        mc_version='1.20.1', mc_loader='fabric', assets_dir=str(ROOT / 'assets'),
        file_picker=ft.FilePicker(), cape_file_picker=ft.FilePicker())


def tab(root, name):
    return next(control for control in fz.walk(root)
                if callable(getattr(control, 'on_click', None))
                and any(getattr(child, 'value', None) == name for child in fz.walk(control)))


def regression():
    fz.install_safe_stubs()
    jobs = []
    class QueuedThread:
        def __init__(self, target, args=(), **_):
            self.target = lambda: target(*args)
        def start(self):
            jobs.append(self.target)
    queued = SimpleNamespace(**{**vars(threading), 'Thread': QueuedThread})
    with patch.object(skin_ui, 'threading', queued), patch.object(preview_ui, 'threading', queued), \
         patch.object(thread_safe_ui, 'refresh'), \
         patch.object(cosmetics, 'render_thumbnail', return_value=Image.new('RGBA', (76, 76), 'white')) as raster:
        root = build(DriverPage())
        assert raster.call_count == 0, 'Opening Skin rasterized hidden cosmetic cards.'
        assert not any(getattr(c, 'value', None) == 'Ember Wings' for c in fz.walk(root))
        start = len(jobs)
        tab(root, 'Back').on_click(None)
        assert raster.call_count == 0, 'Switching Back rasterized on the click thread.'
        for job in jobs[start:]:
            job()
        assert raster.call_count == len(cosmetics.items('back'))
        back_images = [c for c in fz.walk(root) if isinstance(c, ft.Image) and c.width == 76]
        assert back_images and all(c.visible for c in back_images)
        cached_count = raster.call_count
        tab(root, 'Skin').on_click(None)
        tab(root, 'Back').on_click(None)
        assert raster.call_count == cached_count, 'Returning Back discarded the cached thumbnails.'
        cards = [c for c in fz.walk(root) if callable(getattr(c, 'on_hover', None))]
        assert cards and all(c.scale is None and c.animate_scale is None for c in cards)
        for card in cards:
            card.on_hover(SimpleNamespace(data='true'))
            card.on_hover(SimpleNamespace(data='false'))
        assert all(c.scale is None for c in cards), 'Hovering installed unnecessary scale matrices.'
    print('Skin opening and pane switches rasterize no thumbnails on the click thread; only the visible cosmetic pane renders, cached returns reuse images, and default cards create no scale matrices.')


async def native(page):
    fz.install_safe_stubs()
    page.title = 'Cubeon Skin Loading Check'
    page.theme_mode = ft.ThemeMode.DARK
    page.bgcolor = THEME['BG']
    page.scroll = ft.ScrollMode.AUTO
    thread_safe_ui.install(page)
    began = time.monotonic()
    root = build(page)
    print('SKIN_BUILD_SECONDS', round(time.monotonic() - began, 3), flush=True)
    page.add(root)
    thread_safe_ui.mark_mounted(page)
    scene = next(c for c in fz.walk(root) if c.data == 'appearance-model')
    deadline = time.monotonic() + 20
    while not scene.controls and time.monotonic() < deadline:
        await asyncio.sleep(.05)
    assert scene.controls, 'No initial character frame appeared.'
    print('FIRST_FRAME_SECONDS', round(time.monotonic() - began, 3), flush=True)
    assert len(scene.controls) == 2, 'Opening baked unrequested orbit frames.'
    for name in ('Back', 'Shoulder', 'Cape', 'Skin'):
        start = time.monotonic()
        tab(root, name).on_click(None)
        print(name, 'CLICK_SECONDS', round(time.monotonic() - start, 3), flush=True)
        await asyncio.sleep(1)
        for c in fz.walk(root):
            if callable(getattr(c, 'on_hover', None)):
                c.on_hover(SimpleNamespace(data='true'))
                c.on_hover(SimpleNamespace(data='false'))
    await asyncio.sleep(2)
    print('NATIVE_SKIN_PASS', flush=True)
    await page.window.close()


if __name__ == '__main__':
    if '--native' in sys.argv:
        os.environ['LIBGL_ALWAYS_SOFTWARE'] = '1'
        os.environ['GALLIUM_DRIVER'] = 'llvmpipe'
        fz.run_app(native, assets_dir=str(ROOT / 'assets'))
    else:
        regression()
