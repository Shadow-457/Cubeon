"""Modpack rows render without icon I/O; artwork and installed lists stay bounded."""
import inspect
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import icons, thread_safe_ui
from cubeon.icon_loader import IconLoader
from cubeon.theme import THEME, section_label
from _fuzz_common import FakePage
from ui import modpacks_tab as packs
import flet as ft


def functions(*roots):
    found={}
    def visit(fn):
        if not inspect.isfunction(fn) or fn.__name__ in found:
            return
        found[fn.__name__]=fn
        for value in inspect.getclosurevars(fn).nonlocals.values():
            visit(value)
    for root in roots:
        visit(root)
    return found


class ModpackPerformance(unittest.TestCase):
    def build(self):
        with patch.object(thread_safe_ui,'refresh'):
            tab, refresh, load = packs.build_modpacks_tab(FakePage(),{}, {}, section_label=section_label,
                                                         go_to_pack=lambda meta:None,**THEME)
        return tab,functions(refresh,load)

    def test_icon_workers_are_bounded_coalesced_and_do_not_block_ui_lock(self):
        release=threading.Event()
        condition=threading.Condition()
        reads=[]
        active=peak=0
        def read(url):
            nonlocal active,peak
            with condition:
                active+=1
                peak=max(active,peak)
                reads.append(url)
                condition.notify_all()
            release.wait(3)
            with condition:
                active-=1
            return 'encoded image'
        loader=IconLoader(workers=4,read=read)
        applied=[]
        for i in range(20):
            loader.request(str(i),applied.append)
        loader.request('0',applied.append)
        with condition:
            condition.wait_for(lambda:len(reads)>=4,timeout=2)
        try:
            self.assertEqual(len(reads),4)
            self.assertTrue(thread_safe_ui.TREE_LOCK.acquire(timeout=.5))
            thread_safe_ui.TREE_LOCK.release()
        finally:
            release.set()
        deadline=time.monotonic()+3
        while loader._running and time.monotonic()<deadline:
            time.sleep(.01)
        self.assertEqual(peak,4)
        self.assertEqual(len(reads),20)
        self.assertEqual(len(applied),21)
        self.assertFalse(loader._callbacks)

    def test_building_rows_never_reads_icon_files_and_stale_icons_cannot_replace_new(self):
        _,fn=self.build()
        scope=inspect.getclosurevars(fn['_load_pack_icon']).nonlocals
        callbacks=[]
        art=scope['pack_art']
        with patch.object(art,'request',side_effect=lambda url,callback:callbacks.append((url,callback))), \
                patch.object(icons,'src',side_effect=AssertionError('icon disk I/O on UI')), \
                patch.object(icons,'prefetch',side_effect=AssertionError('download on UI')), \
                patch.object(thread_safe_ui,'refresh'):
            hit={'title':'Pack','project_id':'p','provider':'modrinth','icon_url':'https://test/a.png'}
            row=fn['build_pack_row'](hit)
            image=row.content.controls[0]
            self.assertIsInstance(image,ft.Image)
            fn['build_pack_row'](dict(hit,icon_url='https://test/b.png'))
            callbacks[0][1]('old source')
            self.assertNotEqual(image.src,'old source')
            callbacks[1][1]('new source')
            self.assertEqual(image.src,'new source')

    def test_installed_list_builds_only_first_batch_and_loads_more_on_request(self):
        _,fn=self.build()
        snapshot=[{'version_id':str(i),'name':f'Pack {i}'} for i in range(1000)]
        scope=inspect.getclosurevars(fn['_render_installed_rows']).nonlocals
        scope['installed_cache']['packs']=snapshot
        with patch.object(thread_safe_ui,'refresh'):
            fn['_render_installed_rows'](snapshot)
            view=scope['installed_view']
            self.assertTrue(view.build_controls_on_demand)
            self.assertEqual(len(view.controls),26)
            view.controls[-1].on_click(None)
            self.assertEqual(len(view.controls),51)
        self.assertLessEqual(len(inspect.getclosurevars(fn['build_installed_row']).nonlocals['installed_rows']),50)

    def test_first_load_has_visible_skeleton_before_provider_reads(self):
        _,fn=self.build()
        jobs=[]
        class DeferredThread:
            def __init__(self,target,**kwargs): self.target=target
            def start(self): jobs.append(self.target)
        with patch.object(packs.threading,'Thread',DeferredThread), patch.object(thread_safe_ui,'refresh'):
            fn['load_popular']()
        scope=inspect.getclosurevars(fn['_render_page']).nonlocals
        view=scope['results_view']
        self.assertEqual(len(jobs),2)
        self.assertEqual(view.controls[0].data,'content-loading')
        self.assertFalse(view.disabled,'Flet must not dim a placeholder')
        self.assertTrue(view.expand and view.build_controls_on_demand)

    def test_installer_flag_forces_green_before_seasonal_modules_load(self):
        env=dict(os.environ,CUBEON_SEASON='autumn')
        script="import sys; from cubeon import theme; assert theme.ACTIVE_TEMPLATE=='green'; assert 'cubeon.seasonal' not in sys.modules"
        subprocess.run([sys.executable,'-c',script,'--cubeon-installer','--color8'],env=env,check=True,
                       capture_output=True,timeout=10,cwd=ROOT)


if __name__=='__main__':
    unittest.main()
