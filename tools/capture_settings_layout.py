"""Inspect retained Settings at native wide/compact sizes using isolated data."""
import asyncio
import inspect
import os
from pathlib import Path
import sys
import threading
import traceback
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
os.environ.setdefault('LIBGL_ALWAYS_SOFTWARE','1')
os.environ.setdefault('GALLIUM_DRIVER','llvmpipe')
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
from PIL import ImageGrab
from cubeon import thread_safe_ui, scrolling
from cubeon.theme import THEME,FONT_URLS,apply_page_theme
from _fuzz_common import walk
import app_driver
OUT=ROOT/'archive/ui-captures/settings-layout'
completed=[]
async def main(page):
    page.title='Cubeon Settings Layout Check'
    apply_page_theme(page)
    page.bgcolor=THEME['BG'];page.fonts=FONT_URLS;page.padding=20
    page.window.width,page.window.height=1200,760
    page.window.left,page.window.top=0,0
    def build_driver():
        with patch.object(threading.Thread,'start'):
            driver=app_driver.build_headless()
            driver.open_tab('settings')
        return driver
    driver=await asyncio.to_thread(build_driver)
    switch=inspect.getclosurevars(driver.tabs()['settings'].on_click).nonlocals['switch_tab']
    settings=inspect.getclosurevars(switch).nonlocals['tabs']['settings']
    page.add(settings)
    thread_safe_ui.install(page);thread_safe_ui.mark_mounted(page)
    OUT.mkdir(parents=True,exist_ok=True)
    async def capture(name):
        await asyncio.sleep(.8)
        ImageGrab.grab(xdisplay=os.environ['DISPLAY']).save(OUT/f'{name}.png')
        print('CAPTURE',name,flush=True)
    await asyncio.sleep(3)
    for width in (1200,800,480,360):
        page.window.width=width;page.update()
        await asyncio.sleep(.5)
        for section in ('account','versions','appearance','notifications','import','about'):
            settings.select_section(section)
            if section=='account':
                field=next(c for c in walk(settings) if isinstance(c,ft.TextField) and c.label=='Username')
                field.error="Couldn't save the username. Try again."
                thread_safe_ui.refresh(field)
            if section in ('versions','account'):
                tile=next(c for c in walk(settings) if c.data==('settings-java-advanced' if section=='versions' else 'settings-backup-schedule'))
                tile.expanded=True
                thread_safe_ui.refresh(tile)
            await capture(f'{section}-{width}')
    page.window.width,page.window.height=480,400
    settings.select_section('account')
    page.update()
    await capture('account-short')
    pane=next(c for c in walk(settings) if c.data=='settings-pane-account')
    scrolling.follow_end(page,pane)
    await capture('account-short-end')
    settings.select_section('versions')
    settings.select_section('account')
    await capture('account-short-retained')
    completed.append(True)
    print('NATIVE_SETTINGS_PASS: retained sections, disclosures, wide/tablet/compact layout.',flush=True)
if __name__=='__main__':
    async def checked(page):
        try:await main(page)
        except Exception:traceback.print_exc()
        finally:await page.window.close()
    ft.run(checked,assets_dir=str(ROOT/'assets'))
    sys.exit(not completed)
