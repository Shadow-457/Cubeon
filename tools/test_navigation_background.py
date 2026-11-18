"""Blocked backend reads cannot stall navigation or paint stale selections."""
import builtins
import logging
from pathlib import Path
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon.background_refresh import BackgroundRefresh
from cubeon import thread_safe_ui, minekube


class NavigationBackground(unittest.TestCase):
    def finished(self, refresh):
        deadline = time.monotonic() + 3
        while refresh._running and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertFalse(refresh._running)

    def test_blocked_read_coalesces_to_latest_without_holding_ui_lock(self):
        entered, release = threading.Event(), threading.Event()
        reads, applied = [], []
        def read(value):
            reads.append(value)
            if value == 1:
                entered.set()
                self.assertTrue(release.wait(3))
            return value
        def apply(value):
            self.assertTrue(thread_safe_ui.TREE_LOCK._is_owned())
            applied.append(value)
        refresh = BackgroundRefresh(read, apply, name='test-navigation')
        refresh.request(1)
        self.assertTrue(entered.wait(2))
        try:
            with thread_safe_ui.TREE_LOCK:
                refresh.request(2)
                refresh.request(3)
        finally:
            release.set()
        self.finished(refresh)
        self.assertEqual(reads, [1, 3])
        self.assertEqual(applied, [3])

    def test_invalidation_and_failure_feedback_cannot_wedge_worker(self):
        entered, release = threading.Event(), threading.Event()
        applied = []
        def read(value):
            if value == 1:
                entered.set()
                release.wait(3)
            if value == 2:
                raise OSError('unreadable data')
            return value
        refresh = BackgroundRefresh(read, applied.append, name='test-navigation',
                                     failed=lambda error: (_ for _ in ()).throw(RuntimeError('closed UI')))
        refresh.request(1)
        self.assertTrue(entered.wait(2))
        refresh.invalidate()
        release.set()
        self.finished(refresh)
        self.assertEqual(applied, [])
        with self.assertLogs('cubeon.background_refresh', logging.WARNING):
            refresh.request(2)
            self.finished(refresh)
        refresh.request(3)
        self.finished(refresh)
        self.assertEqual(applied, [3])

    def test_real_tab_navigation_returns_while_disk_reads_are_blocked(self):
        import _fuzz_common as fz
        import app_driver
        stubs = fz.install_safe_stubs()
        page = app_driver.DriverPage()
        stubs.app.run_sync(page)
        driver = app_driver.Driver(stubs.app, stubs.core, page, stubs)
        for tab, method in [('modpacks', 'list_installed_modpacks'), ('server', 'is_server_installed')]:
            entered, release, returned = threading.Event(), threading.Event(), threading.Event()
            original = getattr(stubs.core, method)
            def blocked(*args, **kwargs):
                entered.set()
                release.wait(4)
                return original(*args, **kwargs)
            with patch.object(stubs.core, method, side_effect=blocked):
                navigation = threading.Thread(target=lambda: (driver.open_tab(tab), returned.set()))
                navigation.start()
                try:
                    self.assertTrue(entered.wait(2), tab)
                    self.assertTrue(returned.wait(0.5), f'{tab} navigation waited for disk')
                    # Other clicks/animations can acquire the UI lock too.
                    self.assertTrue(thread_safe_ui.TREE_LOCK.acquire(timeout=0.5))
                    thread_safe_ui.TREE_LOCK.release()
                finally:
                    release.set()
                    navigation.join(4)
                    time.sleep(0.05)
        # No network or user game data was touched by the driver.

    def test_large_server_log_reads_only_bounded_tail(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            (folder / 'logs').mkdir()
            log = folder / 'logs/latest.log'
            log.write_bytes(b'[old] stale.play.minekube.net\n' + b'x' * (4 * 1024**2) +
                            b'\n[Connect] fresh.play.minekube.net\n')
            sizes = []
            real_open = builtins.open
            class Reader:
                def __enter__(self):
                    self.file = real_open(log, 'rb')
                    return self
                def __exit__(self, *args):
                    self.file.close()
                def seek(self, *args):
                    return self.file.seek(*args)
                def tell(self):
                    return self.file.tell()
                def read(self):
                    data = self.file.read()
                    sizes.append(len(data))
                    return data
            with patch.object(minekube, 'get_server_dir', return_value=str(folder)), \
                 patch('cubeon.minekube.open', side_effect=lambda *a, **k: Reader(), create=True):
                self.assertEqual(minekube.read_public_address('1.21.11'), 'fresh.play.minekube.net')
            self.assertEqual(sizes, [256 * 1024])

    def test_shell_diff_skips_retained_content_but_delivers_visibility(self):
        import flet as ft
        import msgpack
        from flet.controls.base_control import BaseControl
        from flet.controls.object_patch import ObjectPatch, DiffBuilder
        from flet.messaging.protocol import configure_encode_object_for_msgpack
        from ui.chrome import TabPane

        image = ft.Image(src='original.png')
        content = ft.Column([image, *[ft.Text(f'Message {i}') for i in range(2000)]])
        pane = TabPane(content)
        host = ft.Stack([pane])
        host._shell_only = True
        encode = configure_encode_object_for_msgpack(BaseControl)
        initial, added, removed = ObjectPatch.from_diff(None, host, BaseControl)
        encoded = msgpack.packb(initial.to_message(), default=encode)
        self.assertIn(b'Message 1999', encoded)
        self.assertIn(b'original.png', encoded)
        self.assertFalse(removed)
        self.assertTrue(added)

        image.src = 'changed.png'
        original = DiffBuilder._compare_dataclasses
        walks = []
        def count(builder, *args, **kwargs):
            walks.append(args)
            return original(builder, *args, **kwargs)
        for visible in (False, True):
            pane.visible = visible
            walks.clear()
            with thread_safe_ui.update_scope(host), \
                 patch.object(DiffBuilder, '_compare_dataclasses', count):
                changes, added, removed = ObjectPatch.from_diff(host, host, BaseControl)
            encoded = msgpack.packb(changes.to_message(), default=encode)
            self.assertIn(b'visible', encoded)
            self.assertNotIn(b'src', encoded)
            self.assertFalse(added or removed)
            self.assertLess(len(walks), 10, 'navigation traversed the transcript')
        self.assertIs(host.controls[0], pane)
        changes, added, removed = ObjectPatch.from_diff(image, image, BaseControl)
        encoded = msgpack.packb(changes.to_message(), default=encode)
        self.assertIn(b'changed.png', encoded, 'scoped content repaint was swallowed')
        self.assertFalse(added or removed)
        image.src = 'legacy-full-page.png'
        with thread_safe_ui.update_scope():
            changes, added, removed = ObjectPatch.from_diff(host, host, BaseControl)
        encoded = msgpack.packb(changes.to_message(), default=encode)
        self.assertIn(b'legacy-full-page.png', encoded)
        self.assertFalse(added or removed)
        self.assertFalse(pane.is_isolated(), 'navigation isolation leaked into later updates')

    def test_shell_scope_is_applied_when_worker_updates_and_retries_execute(self):
        import asyncio
        from types import SimpleNamespace

        async def exercise():
            states = []
            class Page:
                def __init__(self):
                    self.loop = asyncio.get_running_loop()
                    self.fail_once = False
                def update(self, *controls):
                    self_test.assertTrue(thread_safe_ui.TREE_LOCK._is_owned())
                    states.append(thread_safe_ui.shell_update_active())
                    if self.fail_once:
                        self.fail_once = False
                        raise RuntimeError('retry this diff')
            self_test = self
            page = Page()
            host = SimpleNamespace(_shell_only=True)
            with patch.object(thread_safe_ui, '_installed', False), \
                 patch.object(thread_safe_ui, '_loops', {}), \
                 patch.object(thread_safe_ui, '_mounted_pages', set()):
                self.assertTrue(thread_safe_ui.install(page))
                thread_safe_ui.mark_mounted(page)
                page.update(host)
                page.update()
                worker = threading.Thread(target=lambda: page.update(host))
                worker.start()
                worker.join(1)
                self.assertFalse(worker.is_alive())
                for _ in range(100):
                    if len(states) == 3:
                        break
                    await asyncio.sleep(.01)
                self.assertEqual(states, [True, False, True])
                page.fail_once = True
                page.update(host)
                for _ in range(100):
                    if len(states) == 5:
                        break
                    await asyncio.sleep(.01)
                page.update()
                self.assertEqual(states, [True, False, True, True, True, False])
                self.assertFalse(thread_safe_ui.shell_update_active())
        asyncio.run(exercise())

    def test_worker_repaint_flood_coalesces_and_keeps_latest_state(self):
        import asyncio
        from types import SimpleNamespace

        async def exercise():
            loop = asyncio.get_running_loop()
            page = SimpleNamespace()
            values = []
            class Control:
                value = 0
                def update(control):
                    self.assertTrue(thread_safe_ui.TREE_LOCK._is_owned())
                    values.append(control.value)
            control = Control()
            control.page = page
            with patch.dict(thread_safe_ui._loops, {id(page): loop}):
                def flood():
                    for value in range(5000):
                        control.value = value
                        thread_safe_ui.refresh(control)
                worker = threading.Thread(target=flood)
                worker.start()
                worker.join(2)
                self.assertFalse(worker.is_alive())
                self.assertEqual(values, [])
                await asyncio.sleep(0)
                self.assertEqual(values, [4999])
                self.assertNotIn(loop, thread_safe_ui._refresh_pending)
                # Removing the pending key before diffing permits a new paint
                # for a mutation that arrives during the current update.
                def mutate_during_paint():
                    values.append(control.value)
                    if control.value == 5000:
                        def mutation():
                            control.value = 5001
                            thread_safe_ui.refresh(control)
                        next_worker = threading.Thread(target=mutation)
                        next_worker.start()
                        next_worker.join(1)
                control.update = mutate_during_paint
                control.value = 5000
                thread_safe_ui.refresh(control)
                await asyncio.sleep(0)
                self.assertEqual(values[-2:], [5000, 5001])
                self.assertNotIn(loop, thread_safe_ui._refresh_pending)
        asyncio.run(exercise())

    def test_closed_loop_repaint_does_not_leave_a_pending_key(self):
        import asyncio
        from types import SimpleNamespace
        loop = asyncio.new_event_loop()
        loop.close()
        page = SimpleNamespace()
        control = SimpleNamespace(page=page)
        with patch.dict(thread_safe_ui._loops, {id(page): loop}):
            thread_safe_ui.refresh(control)
            self.assertNotIn(loop, thread_safe_ui._refresh_pending)

    def test_real_shell_responds_while_cold_tab_builder_is_blocked(self):
        import inspect
        import _fuzz_common as fz
        import app_driver
        stubs = fz.install_safe_stubs()
        page = app_driver.DriverPage()
        stubs.app.run_sync(page)
        driver = app_driver.Driver(stubs.app, stubs.core, page, stubs)
        switch = inspect.getclosurevars(driver.tabs()['mods'].on_click).nonlocals['switch_tab']
        scope = inspect.getclosurevars(switch).nonlocals
        queue = scope['entry_queue']
        queue.deferred = True
        builders = inspect.getclosurevars(scope['_ensure_tab']).nonlocals['_TAB_BUILDERS']
        callbacks = inspect.getclosurevars(scope['_ensure_tab']).nonlocals['_tab_cbs']
        entered, release = threading.Event(), threading.Event()
        workers, built = [], []
        original = builders['mods']
        def blocked():
            self.assertFalse(thread_safe_ui.TREE_LOCK._is_owned())
            entered.set()
            release.wait(3)
            original()
            built.append('mods')
        def run_thread(fn):
            worker = threading.Thread(target=fn, daemon=True)
            workers.append(worker)
            worker.start()
        with patch.object(page, 'run_thread', side_effect=run_thread), \
             patch.dict(builders, {'mods': blocked}):
            try:
                switch('mods')
                self.assertTrue(entered.wait(1))
                self.assertTrue(scope['_tab_views']['mods'].visible)
                self.assertFalse(scope['_tab_views']['mods']._content_ready)
                switch('chat')
                switch('stats')
                switch('play')
                self.assertTrue(scope['_tab_views']['play'].visible)
                self.assertTrue(thread_safe_ui.TREE_LOCK.acquire(timeout=.2))
                thread_safe_ui.TREE_LOCK.release()
            finally:
                release.set()
                for worker in workers:
                    worker.join(3)
            self.assertEqual(built, ['mods'])
            self.assertFalse(queue._running)
            self.assertNotIn('chat', callbacks)
            self.assertNotIn('stats', callbacks)
            self.assertFalse(scope['_tab_views']['mods'].visible)
            self.assertFalse(scope['_tab_views']['mods']._content_ready)
            switch('mods')
            for worker in workers:
                worker.join(3)
            self.assertEqual(built, ['mods'], 'cached return rebuilt the tab')
            self.assertTrue(scope['_tab_views']['mods']._content_ready)
            self.assertIs(scope['_tab_views']['mods'].content, scope['tabs']['mods'])

    def test_cosmetics_resize_accepts_the_loading_placeholder(self):
        import inspect
        from types import SimpleNamespace
        import app_driver
        driver = app_driver.build_headless()
        switch = inspect.getclosurevars(driver.tabs()['mods'].on_click).nonlocals['switch_tab']
        profile = inspect.getclosurevars(switch).nonlocals['tabs']['profile']
        profile.on_size_change(SimpleNamespace(height=500))
        heights = []
        profile.controls[0].content = SimpleNamespace(set_viewport_height=heights.append)
        profile.on_size_change(SimpleNamespace(height=600))
        self.assertEqual(heights, [600])


if __name__ == '__main__':
    unittest.main()
