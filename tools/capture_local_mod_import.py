"""Exercise the real Flet batch review in an isolated launcher/window."""
import asyncio
import inspect
import json
import os
from pathlib import Path
import sys
import tempfile
import subprocess
import shutil
from types import SimpleNamespace
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT)]
os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE', '1')
os.environ.setdefault('GALLIUM_DRIVER', 'llvmpipe')
os.environ.setdefault('CUBEON_UX_WIDTH', '1280')
os.environ.setdefault('CUBEON_UX_HEIGHT', '720')
import ux_capture as ux
import flet as ft
from cubeon import local_mods, mods, updater
REAL_PROFILE_DIR = mods.get_profile_dir
NATIVE_POPEN = subprocess.Popen

OUT = ROOT / 'archive/ui-captures/local-mod-import'
OUT.mkdir(parents=True, exist_ok=True)


async def capture(name):
    if shutil.which('xdotool'):
        native_pointer('mousemove', '0', '0')
    await asyncio.sleep(1)
    from PIL import ImageGrab
    prefix = 'narrow-' if ux.CAPTURE_WIDTH < 1280 else 'large-' if ux.CAPTURE_WIDTH > 1280 else ''
    ImageGrab.grab(xdisplay=os.environ['DISPLAY']).crop(
        (0, 0, ux.CAPTURE_WIDTH, ux.CAPTURE_HEIGHT)).save(OUT / f'{prefix}{name}.png')
    print('CAPTURE: ' + prefix + name, flush=True)


def native_pointer(*args):
    # The launcher fixture stubs subprocess.Popen; use the saved class only
    # for this isolated X display's pointer, without undoing its other stubs.
    process = NATIVE_POPEN(['xdotool', *args])
    assert process.wait(timeout=3) == 0


async def run(page):
    try:
        stubs = ux._prepare(page, False)
        stubs.core.get_installed_versions = lambda *args, **kwargs: [
            {'id': '1.21.11', 'type': 'release', 'name': '1.21.11'},
            {'id': 'fabric-loader-0.18.4-1.21.11', 'type': 'release', 'loader': 'fabric', 'inheritsFrom': '1.21.11'},
        ]
        stubs.core.list_content = lambda kind, *a, **kw: [
            {'filename': 'with-art.zip', 'display_name': 'Pack with artwork', 'enabled': True, 'size_kb': 12,
             'icon_source': ux._png_data_uri((58, 126, 90))},
            {'filename': 'no-art.zip', 'display_name': 'Pack without artwork', 'enabled': True, 'size_kb': 10},
            {'filename': 'broken-art.zip', 'display_name': 'Pack with unreadable artwork', 'enabled': False, 'size_kb': 9,
             'icon_source': 'aW52YWxpZA=='},
        ]
        await stubs.app.main(page)
        mods.get_profile_dir = REAL_PROFILE_DIR
        page.window.left, page.window.top = 0, 0
        page.update()
        await page.window.to_front()
        await asyncio.sleep(1)
        from ui.versions import VersionPicker
        pick_control = next(c for c in ux.every_control(page) if getattr(c, 'tooltip', '') == 'Pick a Minecraft version')
        picker = next(cell.cell_contents for cell in pick_control.on_click.__closure__
                      if isinstance(cell.cell_contents, VersionPicker))
        fabric = next(item['id'] for item in picker.get_instances()
                      if item.get('loader') == 'fabric' or 'fabric' in item['id'].lower())
        picker.on_pick(fabric)
        ux._click(ux.discover_nav(page)['mods'])
        await asyncio.sleep(1)
        await capture('mods-search')
        content = next(c for c in ux.every_control(page) if callable(getattr(c, 'select_content_type', None)))
        search = next(c for c in ux.every_control(page)
                      if isinstance(c, ft.TextField) and (c.hint_text or '').startswith('Search mods or'))
        original_search = stubs.core.search_mods
        stubs.core.search_mods = lambda *a, **kw: [
            dict(ux._hits('mod')[i % 6], project_id=f'capacity-{i}', title=f'Mod {i + 1}')
            for i in range(kw.get('limit', 12))]
        search.value = 'capacity'; search.on_submit(None)
        await capture('screen-capacity')
        from ui.content_tiles import tile_capacity
        grid = next(c for c in ux.every_control(page)
                    if isinstance(c, ft.GridView) and c.visible and c.controls
                    and getattr(c.controls[0], 'on_click', None))
        assert len(grid.controls) == 24, len(grid.controls)
        stubs.core.search_mods = original_search
        search.value = ''; search.on_submit(None)
        for kind in ('modpack', 'resourcepack', 'shader', 'mod'):
            content.select_content_type(kind)
            await capture('content-' + kind)
            if kind in ('resourcepack', 'shader'):
                toggle = next(c for c in ux.every_control(page) if getattr(c, 'data', '') == 'mods-installed-toggle')
                toggle.on_click(None)
                await capture('installed-' + kind)
                toggle = next(c for c in ux.every_control(page) if getattr(c, 'data', '') == 'mods-installed-toggle')
                toggle.on_click(None)
        filter_button = next(c for c in ux.every_control(page) if getattr(c, 'data', '') == 'mods-filters')
        filter_button.on_click(None)
        await capture('filters')
        filter_button.on_click(None)
        toggle = next(c for c in ux.every_control(page) if getattr(c, 'data', '') == 'mods-installed-toggle')
        toggle.on_click(None)
        await capture('mods-installed')
        toggle = next(c for c in ux.every_control(page) if getattr(c, 'data', '') == 'mods-installed-toggle')
        toggle.on_click(None)
        if os.environ.get('CUBEON_CONTENT_ONLY') == '1':
            print('PASS: native unified content, search, switching, filters and installed views', flush=True)
            return
        trigger = next(c for c in ux.every_control(page)
                       if getattr(getattr(c, 'on_click', None), '__name__', '') == 'open_local_mod_picker')
        scope = inspect.getclosurevars(trigger.on_click).nonlocals
        handler = scope['handle_local_mod_files']
        target = scope['_installed_target']()
        with tempfile.TemporaryDirectory(prefix='local-mod-capture-') as temp:
            def jar(filename, identity='samplemod', version='1.0', depends=None):
                path = Path(temp) / filename
                with zipfile.ZipFile(path, 'w') as archive:
                    archive.writestr('fabric.mod.json', json.dumps({
                        'id': identity, 'name': identity.title(), 'version': version,
                        'depends': depends or {'minecraft': '*'},
                    }))
                return SimpleNamespace(path=str(path), name=filename)
            old = jar('sample-old.jar')
            review = local_mods.review_files([old.path], target[1], target[2], version_id=target[3])
            old_result = local_mods.import_review(review, review['entries'])
            assert old_result[0]['status'] == 'imported', old_result
            ready = jar('helper.jar', identity='helper')
            new = jar('sample-new.jar', version='2.0', depends={'minecraft': '*', 'helper': '>=1'})
            wrong = jar('wrong-version.jar', identity='wrong', depends={'minecraft': '1.8.9'})
            broken = Path(temp) / 'broken.jar'; broken.write_bytes(b'broken')
            handler([new, ready, old, wrong, SimpleNamespace(path=str(broken), name='broken.jar')])
            for _ in range(100):
                await asyncio.sleep(.1)
                matches = [c for dialog in page._dialogs.controls for c in ux.walk(dialog)
                           if getattr(c, 'data', None) == 'local-import-submit']
                if matches:
                    break
            status = inspect.getclosurevars(handler).nonlocals['local_install_status'].value
            assert matches, f'Review did not appear ({target}; {status})'
            button = matches[0]
            prompt = button.on_click.__self__
            assert prompt.choices[0][0]['status'] == 'replace', [(e['filename'], e['status'], e['detail']) for e, _ in prompt.choices]
            assert not prompt.choices[0][1].value
            assert prompt.choices[2][0]['status'] == 'duplicate'
            await capture('review')
            prompt.choices[0][1].value = True
            prompt._selection_changed()
            prompt._import()
            for _ in range(100):
                await asyncio.sleep(.1)
                if prompt.phase == 'done':
                    break
            assert prompt.phase == 'done'
            directory = mods.resolve_profile_dir(target[1], target[2], target[3])
            assert (Path(directory) / 'sample-old.jar.disabled').is_file()
            assert (Path(directory) / 'sample-new.jar').is_file()
            assert (Path(directory) / 'helper.jar').is_file()
            await capture('imported')
            prompt._close()
            from ui.update_prompt import UpdatePrompt
            before = len(page._dialogs.controls)
            assert UpdatePrompt(page, {'version': updater.APP_VERSION}, busy=lambda: False, install=lambda *a: None).open() is None
            assert len(page._dialogs.controls) == before
            ux._click(ux.discover_nav(page)['settings'])
            await asyncio.sleep(.5)
            settings = next(c for c in ux.every_control(page) if callable(getattr(c, 'select_section', None)))
            for key in ('account', 'versions', 'memory', 'appearance'):
                settings.select_section(key)
                await capture('settings-' + key)
            print('PASS: unified content selectors/tiles, native batch review, opt-in replacement, import results, latest-version popup suppression, four Settings sections', flush=True)
    except BaseException:
        import traceback
        traceback.print_exc()
        raise
    finally:
        await page.window.close()


if __name__ == '__main__':
    ft.run(run, assets_dir=str(ROOT / 'assets'))
