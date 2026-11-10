"""Native Settings import/selection probe using isolated, synthetic game files.

Run with xvfb-run on Linux; installers use test fixtures and no game is launched.
"""
import asyncio
import inspect
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT)]
os.environ['LIBGL_ALWAYS_SOFTWARE'] = '1'
os.environ['GALLIUM_DRIVER'] = 'llvmpipe'
os.environ.setdefault('CUBEON_UX_WIDTH', '1280')
os.environ.setdefault('CUBEON_UX_HEIGHT', '720')
from test_fastclient_import import FastClientImports
import ux_capture as ux
import flet as ft
from cubeon import versions, instance_import
from ui.versions import VersionPicker
OUT = ROOT / 'archive/ui-captures/fastclient-import'
OUT.mkdir(parents=True, exist_ok=True)
REAL_SCAN = versions.get_installed_versions

async def capture(name):
    await asyncio.sleep(.8)
    from PIL import ImageGrab
    prefix = 'narrow-' if ux.CAPTURE_WIDTH < 1280 else ''
    ImageGrab.grab(xdisplay=os.environ['DISPLAY']).crop(
        (0, 0, ux.CAPTURE_WIDTH, ux.CAPTURE_HEIGHT)).save(OUT / (prefix + name + '.png'))
    print('CAPTURE ' + name, flush=True)

async def wait_for(test):
    for _ in range(100):
        if test():
            return
        await asyncio.sleep(.1)
    raise AssertionError('Timed out waiting for import UI')

async def run(page):
    fixture = FastClientImports()
    try:
        stubs = ux._prepare(page, False)
        fixture.setUp()
        await stubs.app.main(page)
        page.window.min_width = 600
        page.window.width, page.window.height = ux.CAPTURE_WIDTH, ux.CAPTURE_HEIGHT
        page.window.left, page.window.top = 0, 0
        page.update()
        await page.window.to_front()
        await asyncio.sleep(2)
        button = next(c for c in ux.every_control(page) if getattr(c, 'tooltip', '') == 'Pick a Minecraft version')
        picker = next(cell.cell_contents for cell in button.on_click.__closure__
                      if isinstance(cell.cell_contents, VersionPicker))
        stubs.core.get_installed_versions = REAL_SCAN
        ux._click(ux.discover_nav(page)['settings'])
        settings = next(c for c in ux.every_control(page) if callable(getattr(c, 'select_section', None)))
        settings.select_section('import')
        view = next(c for c in ux.every_control(page) if getattr(c, 'data', '') == 'fastclient-import-section')
        prompt = view.import_model
        assert not page._dialogs.controls
        await capture('settings-import')
        prompt.scan.on_click(None)
        await wait_for(lambda: prompt.phase == 'choose')
        assert len(prompt.rows.controls) == 1, prompt.status.value
        await capture('profiles')
        prompt.rows.controls[0].on_click(None)
        await wait_for(lambda: prompt.phase == 'review')
        await capture('review')
        prompt.name.value = 'FastClient imported fixture'
        prompt._import()
        await wait_for(lambda: prompt.phase in ('done', 'choose'))
        assert prompt.phase == 'done', prompt.status.value
        scope = inspect.getclosurevars(picker.on_pick).nonlocals
        vid = picker.get_selected()
        assert '-fastclient-' in vid, vid
        assert scope['state']['pending_loader_install'] is None, scope['state']['pending_loader_install']
        assert scope['state']['mod_loader'] == 'fabric', scope['state']['mod_loader']
        assert not scope['state']['installed_meta'][vid].get('incomplete'), scope['state']['installed_meta'][vid]
        assert 'Reopen Cubeon' not in prompt.status.value, prompt.status.value
        await capture('imported')
        assert not page._dialogs.controls
        ux._click(ux.discover_nav(page)['play'])
        await capture('selected-instance')
        print('PASS native Settings importer: profile discovery, review, verified import, refresh and Fabric selection without dialogs', flush=True)
    except BaseException:
        import traceback
        traceback.print_exc()
        raise
    finally:
        fixture.doCleanups()
        await page.window.close()

if __name__ == '__main__':
    ft.run(run, assets_dir=str(ROOT / 'assets'))
