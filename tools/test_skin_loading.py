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
from io import BytesIO
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


def build(page, cfg=None, cape_file_picker=None, *, measure_viewport=False):
    return skin_ui.build_skin_section(page, cfg if cfg is not None else {'active_back_item': 'back_ember_wings'},
        section_label=section_label, pixel_divider=pixel_divider, **THEME,
        mc_version='1.20.1', mc_loader='fabric', assets_dir=str(ROOT / 'assets'),
        measure_viewport=measure_viewport,
        file_picker=ft.FilePicker(), cape_file_picker=cape_file_picker or ft.FilePicker())


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
        tab(root, 'Back').on_click(None)
        assert raster.call_count == 0, 'Switching Back rasterized on the click thread.'
        # The open pane can reuse a thumbnail worker queued during construction.
        for job in list(jobs):
            job()
        grid = next(c for c in fz.walk(root) if isinstance(c, ft.GridView) and c.controls
                    and any('ember wings' in fz.subtree_text(card) for card in c.controls))
        assert raster.call_count == len(grid.thumb_window) < len(cosmetics.items('back'))
        stack = next(c for c in fz.walk(root) if c.data == 'cosmetics-panes')
        back_pane = next(c for c in stack.controls if c.visible)
        back_images = [c for c in fz.walk(back_pane) if isinstance(c, ft.Image) and c.width == 76]
        assert back_images and sum(c.visible for c in back_images) == len(grid.thumb_window)
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
    thread_safe_ui.install(page)
    began = time.monotonic()
    root = build(page, measure_viewport=True)
    print('SKIN_BUILD_SECONDS', round(time.monotonic() - began, 3), flush=True)
    page.add(ft.Column([root], expand=True, scroll=ft.ScrollMode.AUTO,
                       on_size_change=lambda event: root.set_viewport_height(event.height)))
    thread_safe_ui.mark_mounted(page)
    scene = next(c for c in fz.walk(root) if c.data == 'appearance-model')
    rotate = next(c for c in fz.walk(root) if getattr(c, 'tooltip', None) == 'Rotate right')
    preview = inspect.getclosurevars(rotate.on_click).nonlocals['self']
    deadline = time.monotonic() + 20
    while (preview._shown is None or root.opacity == 0) and time.monotonic() < deadline:
        await asyncio.sleep(.05)
    assert preview._shown is not None, 'No initial character frame appeared.'
    assert root.opacity == 1, 'The measured Wardrobe never appeared.'
    print('FIRST_FRAME_SECONDS', round(time.monotonic() - began, 3), flush=True)
    assert len(scene.controls) == 3 and scene.controls[-1] is preview.skeleton and not preview.skeleton.visible, 'Preview skeleton did not retire after the first frame.'
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
    entered, release = threading.Event(), threading.Event()
    original_items = cosmetics.items
    def slow_catalogue(slot=None, directory=None):
        if slot == 'back':
            entered.set()
            assert release.wait(3), 'Navigation held the event loop behind catalogue loading.'
        return original_items(slot, directory)
    with patch.object(cosmetics, 'items', side_effect=slow_catalogue):
        start = time.monotonic()
        tab(root, 'Back').on_click(None)
        assert time.monotonic() - start < .25, 'Opening Back read the catalogue on the UI thread.'
        deadline = time.monotonic() + 2
        while not entered.is_set() and time.monotonic() < deadline:
            await asyncio.sleep(.01)
        assert entered.is_set(), 'The catalogue worker did not start.'
        timings = []
        for name in ('Head', 'Feet', 'Pets'):
            start = time.monotonic()
            tab(root, name).on_click(None)
            timings.append(time.monotonic() - start)
        release.set()
        assert max(timings) < .25, 'Rapid categories froze behind the previous catalogue.'
        stack = next(c for c in fz.walk(root) if c.data == 'cosmetics-panes')
        assert sum(pane.visible for pane in stack.controls) == 1
        print('NATIVE_CATEGORY_SWITCH_MAX_SECONDS', round(max(timings), 4), flush=True)
        await asyncio.sleep(.5)
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


async def native_gif(page):
    """Upload through the real UI and inspect animated native card pixels."""
    from PIL import ImageGrab
    from cubeon import capes, paths
    fz.install_safe_stubs()
    page.title = 'Cubeon GIF Cape Check'
    page.bgcolor = THEME['BG']
    page.theme_mode = ft.ThemeMode.DARK
    page.scroll = ft.ScrollMode.AUTO
    page.window.width = 1000
    page.window.height = 740
    thread_safe_ui.install(page)
    cfg = {'username': 'GifUiTester'}
    picker = ft.FilePicker()
    root = build(page, cfg, picker)
    page.add(root)
    thread_safe_ui.mark_mounted(page)
    tab(root, 'Cape').on_click(None)
    source = Path(paths.CUBEON_HOME) / 'Native GIF.gif'
    source.parent.mkdir(parents=True, exist_ok=True)
    frames = [Image.new('RGBA', (20, 32), color) for color in ('magenta', 'cyan', 'yellow')]
    frames[0].save(source, 'GIF', save_all=True, append_images=frames[1:], duration=200, loop=0)
    picked = SimpleNamespace(name=source.name, path=str(source))
    picker.on_result(SimpleNamespace(files=[picked]))
    deadline = time.monotonic() + 15
    while not cfg.get('active_cape') and time.monotonic() < deadline:
        await asyncio.sleep(.05)
    assert cfg.get('active_cape'), 'GIF upload did not select a cape.'
    assert capes.animation_info(cfg['active_cape'])['count'] == 3
    await asyncio.sleep(4)
    # Uploaded capes follow the bundled collection; lazy cells deliberately
    # wait offscreen. Bring this card into view before inspecting its frames.
    stack = next(c for c in fz.walk(root) if c.data == 'cosmetics-panes')
    pane = next(c for c in stack.controls if c.visible)
    grid = next(c for c in fz.walk(pane) if isinstance(c, ft.GridView))
    await grid.scroll_to(offset=-1)
    await asyncio.sleep(2)
    out = ROOT / 'archive/ui-captures/gif-capes-launcher'
    out.mkdir(parents=True, exist_ok=True)
    seen = set()
    for index in range(12):
        await asyncio.sleep(.13)
        capture = ImageGrab.grab(xdisplay=os.environ['DISPLAY']).convert('RGB')
        counts = capture.getcolors(capture.width*capture.height) or []
        for count, rgb in counts:
            if count > 200 and rgb in ((255,0,255), (0,255,255), (255,255,0)):
                seen.add(rgb)
        if index < 3:
            capture.save(out / f'frame-{index}.png')
    assert len(seen) == 3, f'Native cape card did not paint all GIF colors: {seen}'
    apply_none = next(c for c in fz.walk(root) if isinstance(c, ft.Container)
                      and c.tooltip == 'Apply None (No cape on your screen)')
    apply_none.cubeon_keyboard_button.on_click(None)
    assert cfg.get('hide_cubeon_cape') and cfg.get('active_cape') is None
    print('NATIVE_GIF_PASS: upload, saved animation, all three painted GIF frames and hide.', flush=True)
    await page.window.close()


async def native_picker(page):
    """Exercise long native item lists while the character renderer is paused."""
    from PIL import ImageGrab
    from cubeon.theme import FONT_URLS, apply_page_theme
    fz.install_safe_stubs()
    apply_page_theme(page)
    page.fonts = FONT_URLS
    page.bgcolor = THEME['BG']
    page.padding = 24
    page.window.width, page.window.height = 1000, 760
    page.window.left = page.window.top = 0
    thread_safe_ui.install(page)
    original_items, original_get = cosmetics.items, cosmetics.get
    entries = {slot: [{**item, 'id': f'fixture_{slot}_{index}', 'name': f'{item["name"]} {index}'}
                      for index, item in enumerate((original_items(slot) * 200)[:200])]
               for slot in ('back', 'head')}
    lookup = {item['id']: item for items in entries.values() for item in items}
    def items(slot=None, directory=None):
        return entries[slot] if slot in entries else original_items(slot, directory)
    def get(key, directory=None):
        return lookup.get(key) or original_get(key, directory)
    with patch.object(preview_ui.AppearancePreview, 'refresh'), \
            patch.object(preview_ui.AppearancePreview, 'turn'), \
            patch.object(cosmetics, 'items', side_effect=items), \
            patch.object(cosmetics, 'get', side_effect=get), \
            patch.object(cosmetics, 'render_thumbnail', wraps=cosmetics.render_thumbnail) as raster, \
            patch.object(skin_ui.core, 'set_active_cosmetic',
                         side_effect=lambda cfg, slot, key: cfg.update({f'active_{slot}_item': key})):
        root = build(page, {})
        page.add(root)
        thread_safe_ui.mark_mounted(page)
        await asyncio.sleep(1.2)
        full_diffs = 0
        original_update = type(page).update
        def counted(self, *controls):
            nonlocal full_diffs
            if not controls:
                full_diffs += 1
                print('NATIVE_FULL_DIFF', ''.join(traceback.format_stack(limit=5)), flush=True)
            return original_update(self, *controls)
        async def ready(grid):
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                near = [card for card in grid.controls if id(card) in grid.thumb_window]
                if near and all(any(isinstance(c, ft.Image) and c.visible for c in fz.walk(card)) for card in near):
                    return
                await asyncio.sleep(.03)
            states = [(card.tooltip, [(c.visible, c.data) for c in fz.walk(card)
                       if isinstance(c, ft.Image) or c.data == 'content-artwork-unavailable'])
                      for card in grid.controls if id(card) in grid.thumb_window]
            raise AssertionError(f'Nearby thumbnails did not finish: {raster.call_count=}, {states=}')
        def current_grid():
            stack = next(c for c in fz.walk(root) if c.data == 'cosmetics-panes')
            pane = next(c for c in stack.controls if c.visible)
            return next(c for c in fz.walk(pane) if isinstance(c, ft.GridView))
        with patch.object(type(page), 'update', counted):
            delays = []
            stop = asyncio.Event()
            async def heartbeat():
                previous = time.monotonic()
                while not stop.is_set():
                    await asyncio.sleep(.02)
                    now = time.monotonic()
                    delays.append(now - previous)
                    previous = now
            pulse = asyncio.create_task(heartbeat())
            timings = []
            out = ROOT / 'archive/ui-captures/wardrobe'
            out.mkdir(parents=True, exist_ok=True)
            for name in ('Back', 'Head'):
                start = time.monotonic()
                tab(root, name).on_click(None)
                timings.append(time.monotonic() - start)
                deadline = time.monotonic() + 5
                while len(current_grid().controls) != 200 and time.monotonic() < deadline:
                    await asyncio.sleep(.02)
                grid = current_grid()
                assert len(grid.controls) == 200
                await ready(grid)
                cards = [id(c) for c in fz.walk(grid)]
                painted = sum(any(isinstance(c, ft.Image) and c.visible for c in fz.walk(card)) for card in grid.controls)
                assert painted < 40, f'Opening {name} rendered the entire list: {painted}'
                before = raster.call_count
                # Real desktop wheel events must reach the inner viewport.
                wheel = NATIVE_POPEN(['xdotool', 'mousemove', '700', '420', 'click', '--repeat', '12', '--delay', '30', '5'])
                assert await asyncio.to_thread(wheel.wait, timeout=5) == 0
                deadline = time.monotonic() + 3
                while grid.scroll_pixels < 300 and time.monotonic() < deadline:
                    await asyncio.sleep(.02)
                assert grid.scroll_pixels >= 300, 'Native wheel did not scroll the item grid.'
                await ready(grid)
                assert raster.call_count > before, 'Scrolling did not load the new rows.'
                assert cards == [id(c) for c in fz.walk(grid)], 'Scrolling remounted cards.'
                first = next(card for card in grid.controls if id(card) in grid.thumb_window)
                apply = next(c for c in fz.walk(first) if isinstance(c, ft.Container) and callable(c.on_click))
                apply.cubeon_keyboard_button.on_click(None)
                ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(out / f'large-{name.lower()}-scrolled.png')
                print('NATIVE_LIST', name, 'items', len(grid.controls), 'initial_thumbnails', painted,
                      'scroll_pixels', round(grid.scroll_pixels), flush=True)
            tab(root, 'Back').on_click(None)
            tab(root, 'Small wings').on_click(None)
            await asyncio.sleep(.2)
            ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(out / 'large-back-filtered.png')
            stop.set()
            await pulse
            assert full_diffs == 0, f'Item interaction caused {full_diffs} whole-page diffs.'
            assert max(timings) < .25, 'A category click blocked behind item work.'
            # Includes synthetic catalogue construction and real raster work.
            assert max(delays) < .5, f'The event loop stalled: {max(delays):.3f}s'
            print('NATIVE_PICKER_PASS: preview paused; click max', round(max(timings), 4),
                  'heartbeat max', round(max(delays), 4), 'full page diffs', full_diffs, flush=True)
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
        assert preview._shown == target and not preview._running, 'Release did not settle on the final camera.'
        with Image.open(BytesIO(preview.image.src)) as frame:
            assert frame.size == preview_ui.RENDER_SIZE, 'Release increased the preview resolution.'
        assert len(preview.scene.controls) == 3 and len(preview._frames) <= 64

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
    if any(flag in sys.argv for flag in ('--native', '--native-drag', '--native-gif', '--native-picker')):
        os.environ['LIBGL_ALWAYS_SOFTWARE'] = '1'
        os.environ['GALLIUM_DRIVER'] = 'llvmpipe'
        failures = []
        async def checked_native(page):
            try:
                callback = native_picker if '--native-picker' in sys.argv else native_gif if '--native-gif' in sys.argv else native_drag if '--native-drag' in sys.argv else native
                await callback(page)
            except Exception:
                failures.append(True)
                traceback.print_exc()
            finally:
                await page.window.close()
        fz.run_app(checked_native, assets_dir=str(ROOT / 'assets'))
        sys.exit(bool(failures))
    else:
        regression()
