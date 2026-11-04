"""Skin opening stays off the raster path; --native probes the pinned desktop UI."""
import asyncio
import inspect
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
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
from cubeon import skins
from cubeon.appearance import CharacterModel
from cubeon.theme import THEME, section_label, pixel_divider
import ui.skin_tab as skin_ui
import ui.appearance_preview as preview_ui

NATIVE_POPEN = subprocess.Popen


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
    rotate = next(c for c in fz.walk(root) if getattr(c, 'tooltip', None) == 'Rotate right')
    preview = inspect.getclosurevars(rotate.on_click).nonlocals['self']
    deadline = time.monotonic() + 20
    while preview._shown is None and time.monotonic() < deadline:
        await asyncio.sleep(.05)
    assert preview._shown is not None, 'No initial character frame appeared.'
    print('FIRST_FRAME_SECONDS', round(time.monotonic() - began, 3), flush=True)
    assert len(scene.controls) == 2, 'Opening baked unrequested orbit frames.'
    assert len(preview._model.faces) < 150, 'The turntable loaded the full Giant feather mesh.'
    for _ in range(3):
        target = (preview.yaw + 30) % 360
        step = preview._step_for(target)
        start = time.monotonic()
        rotate.on_click(None)
        deadline = start + 3
        while (preview._shown != step or abs(preview.yaw - target) > .001) and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        assert preview._shown == step and abs(preview.yaw - target) < .001, 'The Giant-wing rotation did not finish.'
        print('WING_ROTATION_SECONDS', round(time.monotonic() - start, 3), flush=True)
    for name in ('Back', 'Pets', 'Cape', 'Skin'):
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


async def native_drag(page):
    """Drive real desktop pointer events, then check painted frames during motion."""
    assert os.environ.get('DISPLAY'), 'Run this probe on its own Xvfb display.'
    fz.install_safe_stubs()
    page.title = 'Cubeon Preview Drag Check'
    page.padding = 20
    page.bgcolor = THEME['BG']
    page.theme_mode = ft.ThemeMode.DARK
    thread_safe_ui.install(page)
    preview = preview_ui.AppearancePreview({'active_back_item': 'back_ember_wings'},
        assets_dir=str(ROOT / 'assets'), page=page)
    page.add(ft.Container(width=400, content=preview.control))
    thread_safe_ui.mark_mounted(page)
    preview.refresh()
    deadline = time.monotonic() + 10
    while preview._shown is None and time.monotonic() < deadline:
        await asyncio.sleep(.01)
    assert preview._shown is not None
    await asyncio.sleep(.5)
    inputs, paints = [], []
    full_updates = []
    original_page_update = type(page).update
    def record_update(self, *controls):
        if self is page and not controls:
            full_updates.append(time.monotonic())
        return original_page_update(self, *controls)
    type(page).update = record_update
    original_update, original_publish = preview.gesture.on_pan_update, preview._publish

    def record_input(event):
        inputs.append(time.monotonic())
        original_update(event)
        assert not ft.context.auto_update_enabled(), 'Dragging requested a whole-page automatic diff.'

    def record_paint(*args):
        before = preview.image.src
        original_publish(*args)
        if before is not preview.image.src:
            paints.append((time.monotonic(), preview._shown))

    preview.gesture.on_pan_update, preview._publish = record_input, record_paint
    thread_safe_ui.refresh(preview.gesture)

    async def pointer(*args):
        process = NATIVE_POPEN(['xdotool', *map(str, args)], stdout=subprocess.PIPE,
                               stderr=subprocess.PIPE)
        stdout, stderr = await asyncio.to_thread(process.communicate, timeout=3)
        assert process.returncode == 0, stderr.decode()
        return stdout.decode().strip()

    window = (await pointer('search', '--name', '^Cubeon Preview Drag Check$')).splitlines()[-1]
    await pointer('windowmove', window, 0, 0)
    await asyncio.sleep(.5)  # Allow the X expose event to paint the moved window.
    from PIL import ImageGrab
    out = ROOT / 'archive/ui-captures/preview-drag'
    out.mkdir(parents=True, exist_ok=True)
    initial = ImageGrab.grab(xdisplay=os.environ['DISPLAY'])
    initial.save(out / 'before.png')
    crop = (70, 25, 365, 360)
    assert sum(count for count, color in initial.crop(crop).getcolors(295 * 335)
               if max(color[:3]) > 100) > 500, 'The initial skin was not painted.'
    async def drag_case(name, points):
        screenshots = []
        before_inputs = len(inputs)
        await pointer('mousemove', '--window', window, *points[0])
        await pointer('mousedown', 1)
        began = time.monotonic()
        try:
            for position in points[1:]:
                await pointer('mousemove', '--window', window, *position)
                await asyncio.sleep(.016)
                screenshots.append(ImageGrab.grab(xdisplay=os.environ['DISPLAY']).crop(crop))
        finally:
            await pointer('mouseup', 1)
        end = time.monotonic()
        await asyncio.sleep(.1)  # Deliver the final native pan event.
        target = preview._camera_key()
        deadline = end + 3
        while (preview._shown != target or preview._running) and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        await asyncio.sleep(.1)
        ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(out / f'{name}-after.png')
        frame_colors = [sum(count for count, color in frame.getcolors(frame.width * frame.height)
                            if max(color[:3]) > 100) for frame in screenshots]
        distinct = len({frame.tobytes() for frame in screenshots})
        live_paints = [stamp for stamp, key in paints if began < stamp < end]
        full_diffs = sum(began < stamp < end for stamp in full_updates)
        print('NATIVE_DRAG', name, 'INPUTS', len(inputs) - before_inputs,
              'PAINTS', len(live_paints), 'SCREEN_FRAMES', distinct,
              'SECONDS', round(end - began, 3), 'FULL_DIFFS', full_diffs, flush=True)
        assert len(inputs) - before_inputs >= 10, 'Native pan events did not reach the preview.'
        assert len(live_paints) >= 8 and distinct >= 8, 'The skin froze during continuous native dragging.'
        assert min(frame_colors) > 500, 'A painted drag frame lost the skin.'
        assert full_diffs == 0, 'Native dragging performed a whole-page diff.'
        assert preview._shown == target and preview._quality[target] == 2, 'Release did not refine the final camera.'
        assert len(preview.scene.controls) == 2 and len(preview._frames) <= 64

    await drag_case('wings', [(150 + i * 5, 230 - i * 2) for i in range(37)])
    sheet = skins.default_base_skin()
    for y in range(64):
        for x in range(64):
            if sheet.getpixel((x, y))[3] == 0 and (x + y) % 2:
                sheet.putpixel((x, y), (255, 150, 50, 255))
    detailed = CharacterModel(sheet, cosmetics_faces=cosmetics.preview_faces(
        cosmetics.get('back_ember_wings'), simplify=True))
    assert len(detailed.faces) > 3000
    with patch.object(CharacterModel, 'from_config', return_value=detailed):
        preview.refresh(invalidate=True)
        deadline = time.monotonic() + 3
        while preview._model is not detailed and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        assert preview._model is detailed
    await drag_case('detailed-skin-orbit', [(150 + i * 14, 220 + i % 10 * 2) for i in range(41)])
    await drag_case('reverse', [(150 - i * 6, 220 - i * 3) for i in range(25)])
    # Shrink the native host and verify the existing model fits without remounting.
    page.controls[0].width = 220
    thread_safe_ui.refresh(page.controls[0])
    await asyncio.sleep(.2)
    assert preview.scene.width <= 220 and preview.image.visible
    ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(out / 'compact.png')
    print('NATIVE_DRAG_PASS', flush=True)
    await page.window.close()


if __name__ == '__main__':
    if '--native' in sys.argv or '--native-drag' in sys.argv:
        os.environ['LIBGL_ALWAYS_SOFTWARE'] = '1'
        os.environ['GALLIUM_DRIVER'] = 'llvmpipe'
        failures = []
        async def checked_native(page):
            try:
                await (native_drag if '--native-drag' in sys.argv else native)(page)
            except Exception:
                failures.append(True)
                traceback.print_exc()
            finally:
                await page.window.close()
        fz.run_app(checked_native, assets_dir=str(ROOT / 'assets'))
        sys.exit(bool(failures))
    else:
        regression()
