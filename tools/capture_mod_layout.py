"""Verify Mods loading, card grids and toggles in an isolated native window."""
import asyncio
import base64
import io
import os
from pathlib import Path
import subprocess
import sys
import time
import traceback
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'tools'), str(ROOT)]
os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE', '1')
os.environ.setdefault('GALLIUM_DRIVER', 'llvmpipe')
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
from PIL import ImageGrab
from PIL import Image
from cubeon import thread_safe_ui
from cubeon.theme import THEME, FONT_URLS, section_label, apply_page_theme
from test_content_install_feedback import functions, env
from ui.mods_tab import build_mods_tab
import _fuzz_common

NATIVE_POPEN = subprocess.Popen
OUT = ROOT / 'archive/ui-captures/mod-layout'
completed = []


async def main(page):
    stubs = _fuzz_common.install_safe_stubs()
    items = [dict(filename=f'mod-{i}.jar', slug=f'mod-{i}', display_name=f'Mod {i + 1} with a longer name',
                  size_kb=120, enabled=True) for i in range(60)]
    stubs.core.list_mods = lambda *a, **k: [dict(item) for item in items]
    stubs.core.get_mod_icons = lambda *a, **k: {}
    gate = __import__('threading').Event()
    def catalogue(**kwargs):
        assert gate.wait(15), 'catalogue fixture was not released'
        return [dict(project_id=f'mod-{i}', slug=f'mod-{i}', title=f'Mod {i + 1} with a longer name',
                     author='Community project author', downloads=12345) for i in range(24)]
    stubs.core.get_recommended_mods = catalogue
    def toggle(mc, loader, filename, **kwargs):
        time.sleep(.5)
        item = next(item for item in items if item['filename'] == filename)
        item['enabled'] = not item['enabled']
        item['filename'] = filename + '.disabled' if not item['enabled'] else filename.removesuffix('.disabled')
    stubs.core.toggle_mod = toggle
    import ui.mods_tab as mods_ui
    mods_ui.check_content = lambda target: dict(unfixed=[], elapsed=.01)
    page.title = 'Cubeon Mods Layout Check'
    page.bgcolor = THEME['BG']
    page.fonts = FONT_URLS
    apply_page_theme(page)
    page.padding = 24
    page.window.width, page.window.height = 1280, 720
    page.window.left = page.window.top = 0
    page.window.frameless = True
    thread_safe_ui.install(page)
    state = dict(selected_mc_version='1.21.11', mod_loader='fabric')
    root, refresh, load, profile = build_mods_tab(
        page, {}, state, ft.Dropdown(value='fixture'), section_label=section_label, **THEME)
    fns = functions(refresh, load, profile)
    page.add(root)
    thread_safe_ui.mark_mounted(page)
    OUT.mkdir(parents=True, exist_ok=True)
    await asyncio.sleep(1)
    load()
    await asyncio.sleep(.4)
    async def capture(name):
        await asyncio.sleep(.3)
        ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(OUT / f'{name}.png')
        print('CAPTURE:', name, flush=True)
    await capture('wide-loading')
    browse = env(fns['_render_browse_page'])['browse_results_view']
    loading_geometry = (browse.runs_count, browse.child_aspect_ratio)
    gate.set()
    await asyncio.sleep(.7)
    assert (browse.runs_count, browse.child_aspect_ratio) == loading_geometry
    await capture('wide-browse')
    fns['on_view_change']('installed')
    await asyncio.sleep(.7)
    installed = env(fns['_render_installed_snapshot'])['mods_list_view']
    assert (installed.runs_count, installed.child_aspect_ratio) == loading_geometry
    await capture('wide-installed')
    row = installed.controls[0]
    switch = row.content.controls[2]
    switch.value = False
    switch.on_change(SimpleNamespace(control=switch))
    await capture('toggle-pending')
    await asyncio.sleep(.5)
    assert not switch.value and not switch.disabled and installed.controls[0] is row
    await capture('toggle-finished')
    # Native wheel input must move the retained viewport, including after feedback.
    offsets = []
    installed.on_scroll = lambda event: offsets.append(event.pixels)
    thread_safe_ui.refresh(installed)
    await asyncio.sleep(.3)
    def pointer(*args):
        process = NATIVE_POPEN(['xdotool', *args])
        assert process.wait(timeout=3) == 0
    pointer('mousemove', '800', '430')
    pointer('click', '--repeat', '8', '--delay', '80', '5')
    await asyncio.sleep(.5)
    assert offsets and max(offsets) > 0, offsets
    await capture('installed-scrolled')
    for width in (800, 480):
        page.window.width = width
        page.update()
        await asyncio.sleep(.6)
        await capture(f'installed-{width}')
        fns['on_view_change']('browse')
        await asyncio.sleep(.6)
        assert (installed.runs_count, installed.child_aspect_ratio) == (browse.runs_count, browse.child_aspect_ratio)
        await capture(f'browse-{width}')
        fns['on_view_change']('installed')
    page.window.width = 1280
    page.update()
    await asyncio.sleep(.5)
    detail_gate = __import__('threading').Event()
    def details(ref):
        assert detail_gate.wait(15)
        return dict(title='Mod detail artwork', description='Artwork loaded from project metadata',
                    body='This is the full mod description.', icon_url='https://example.invalid/fixture.png')
    stubs.core.get_mod_details = details
    stubs.core.get_mod_versions = lambda *a, **kw: [
        dict(filename=items[0]['filename'], url='offline', compatible=True, version_number='1.0')]
    stream = io.BytesIO()
    Image.new('RGB', (64, 64), '#4aa849').save(stream, 'PNG')
    source = base64.b64encode(stream.getvalue()).decode('ascii')
    env(fns['_art_image'])['artwork'].read = lambda url: source
    fns['open_mod_detail'](items[0])
    detail_host = env(fns['open_mod_detail'])['detail_host']
    hero = detail_host.controls[1]
    icon = hero.content.controls[0]
    await capture('detail-loading')
    detail_gate.set()
    await asyncio.sleep(.7)
    assert icon.src == source and hero.content.controls[0] is icon and hero.height == 120
    await capture('detail-icon')
    root.close_detail()
    from ui.plugins_catalogue import build_plugins_catalogue
    plugin_items = [dict(filename=f'plugin-{i}.jar', slug=f'plugin-{i}',
                         display_name=f'Plugin {i + 1} with a longer name', enabled=True) for i in range(60)]
    stubs.core.list_plugins = lambda version: [dict(item) for item in plugin_items]
    stubs.core.get_recommended_plugins = lambda: [
        dict(project_id=f'plugin-{i}', slug=f'plugin-{i}', title=f'Plugin {i + 1} with a longer name',
             author='Community author', downloads=23456) for i in range(30)]
    plugin_root, refresh_plugins, search_plugins, plugin_results = build_plugins_catalogue(
        page, {'value': 'fixture'}, section_label=section_label, **THEME)
    plugin_fns = functions(refresh_plugins, search_plugins, *[
        getattr(control, 'on_click', None) for control in _fuzz_common.walk(plugin_root)])
    refresh_plugins({'plugins': plugin_items})
    page.controls.clear()
    page.add(plugin_root)
    search_plugins()
    await asyncio.sleep(.6)
    await capture('plugins-wide-browse')
    plugin_fns['_on_plugins_view_change']('installed')
    await asyncio.sleep(.07)
    ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(OUT / 'plugins-crossfade.png')
    await capture('plugins-wide-installed')
    plugin_grid = env(plugin_fns['render_installed'])['installed_plugins_list']
    assert (plugin_grid.runs_count, plugin_grid.child_aspect_ratio) == (
        plugin_results.runs_count, plugin_results.child_aspect_ratio)
    for width in (800, 480):
        page.window.width = width
        page.update()
        await capture(f'plugins-installed-{width}')
        plugin_fns['_on_plugins_view_change']('browse')
        await capture(f'plugins-browse-{width}')
        plugin_fns['_on_plugins_view_change']('installed')
    completed.append(True)
    print('NATIVE_MOD_LAYOUT_PASS: Mods/Plugins grids, crossfade, toggles, native wheel and late artwork', flush=True)


async def checked(page):
    try:
        await main(page)
    except BaseException:
        traceback.print_exc()
    finally:
        await page.window.close()


if __name__ == '__main__':
    ft.run(checked, assets_dir=str(ROOT / 'assets'))
    sys.exit(0 if completed else 1)
