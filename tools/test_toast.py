"""Launcher toast delivery/lifecycle checks; no network or real home writes.

--native-child captures the actual Flet cards in /tmp and closes its own view.
Run it with the pinned Flet interpreter under Xvfb for desktop verification.
"""
import asyncio
import logging
from pathlib import Path
import subprocess
import sys
import threading
import time
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import flet as ft
from cubeon import dialogs, thread_safe_ui
from ui import toast


def wait_for(predicate, timeout=2):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(.01)
    raise AssertionError('toast lifecycle did not settle')


class Page:
    def __init__(self):
        self.overlay = []
        self._overlay = object()
        self.updates = 0

    def update(self):
        self.updates += 1


class ToastTests(unittest.TestCase):
    def setUp(self):
        self.pages = []
        self.paints = []
        self.original_snack = dialogs.show_snack
        self.patches = [patch.object(thread_safe_ui, 'refresh', self.paints.append),
                        patch.object(toast, 'SLIDE_MS', 1)]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for page in self.pages:
            toast.uninstall(page)
        for thread in threading.enumerate():
            if thread.name == 'ux-toast':
                thread.join(timeout=1)
        dialogs.show_snack = self.original_snack
        for item in reversed(self.patches):
            item.stop()

    def page(self):
        page = Page()
        self.pages.append(page)
        return page

    def cards(self, page):
        with thread_safe_ui.TREE_LOCK:
            host = next(c for c in page.overlay if c.data == 'toast-host')
            return list(host.content.controls)

    def test_worker_delivery_mounts_overlay_without_whole_page_diff(self):
        page = self.page()
        thread = threading.Thread(target=toast.show, args=(page, 'Settings saved'),
                                  kwargs={'duration': 0})
        thread.start()
        thread.join()
        wait_for(lambda: bool(self.cards(page)) and self.cards(page)[0].opacity == 1)
        self.assertIn(page._overlay, self.paints)
        self.assertEqual(page.updates, 0)

    def test_same_message_is_deduplicated_per_window(self):
        first, second = self.page(), self.page()
        toast.show(first, 'Settings saved', duration=0)
        toast.show(first, 'Settings saved', duration=0)
        toast.show(second, 'Settings saved', duration=0)
        wait_for(lambda: len(self.cards(first)) == len(self.cards(second)) == 1)

    def test_expiry_and_close_allow_the_message_again(self):
        page = self.page()
        toast.show(page, 'Copied', duration=20)
        wait_for(lambda: (id(page), 'Copied') not in toast._active)
        self.assertEqual(self.cards(page), [])
        toast.show(page, 'Copied', duration=0)
        wait_for(lambda: bool(self.cards(page)))
        close = self.cards(page)[0].content.content.controls[1].content.controls[2]
        close.on_click(None)
        wait_for(lambda: self.cards(page) == [])

    def test_action_receives_click_and_dismisses(self):
        page = self.page()
        clicks = []
        toast.show(page, 'Update ready', duration=0, action=clicks.append,
                   action_label='Open')
        wait_for(lambda: bool(self.cards(page)))
        body = self.cards(page)[0].content.content.controls[1].content.controls[1]
        event = object()
        body.controls[1].on_click(event)
        self.assertEqual(clicks, [event])
        wait_for(lambda: self.cards(page) == [])

    def test_eviction_releases_persistent_notice_and_daemon(self):
        page = self.page()
        for i in range(5):
            toast.show(page, f'Notice {i}', duration=0)
            wait_for(lambda: (id(page), f'Notice {i}') in toast._active
                     and len(self.cards(page)) == min(i + 1, toast.MAX_VISIBLE))
        wait_for(lambda: (id(page), 'Notice 0') not in toast._active)
        toast.show(page, 'Notice 0', duration=0)
        wait_for(lambda: len(self.cards(page)) == toast.MAX_VISIBLE
                 and (id(page), 'Notice 0') in toast._active)

    def test_host_is_unique_and_above_later_launcher_panels(self):
        page = self.page()
        toast.install(page)
        host = page.overlay[0]
        page.overlay.append(object())
        toast.show(page, 'Copied', duration=0)
        self.assertIs(page.overlay[-1], host)
        self.assertEqual(sum(c is host for c in page.overlay), 1)
        self.assertIs(dialogs.show_snack, toast.show)

    def test_uninstall_clears_persistent_session_without_replay(self):
        page = self.page()
        toast.show(page, 'Notice', duration=0)
        wait_for(lambda: bool(self.cards(page)))
        toast.uninstall(page)
        self.assertEqual(page.overlay, [])
        self.assertNotIn((id(page), 'Notice'), toast._active)
        toast.install(page)
        self.assertEqual(self.cards(page), [])


def native_child():
    logging.basicConfig(level=logging.INFO)

    async def main(page):
        page.title = 'Cubeon notification verification'
        page.bgcolor = '#0e1015'
        thread_safe_ui.install(page)
        toast.install(page)
        page.add(ft.Text('Cubeon launcher notifications', color='#ffffff'))
        thread_safe_ui.mark_mounted(page)
        await asyncio.sleep(.4)
        # Late mount, as well as the normal startup-mounted host.
        toast.uninstall(page)
        thread = threading.Thread(target=toast.show,
                                  args=(page, 'Settings saved'),
                                  kwargs={'duration': 0})
        thread.start()
        toast.show(page, "Couldn't install this pack. Try again when your connection is ready.",
                   duration=0)
        toast.show(page, 'An update is ready to install.', duration=0,
                   action=lambda e: print('NATIVE_ACTION', flush=True),
                   action_label='Open update')
        await asyncio.sleep(1)
        subprocess.run(['import', '-window', 'root', '/tmp/cubeon-toast-native.png'],
                       check=True)
        print('NATIVE_TOAST_CAPTURED', flush=True)
        toast.uninstall(page)
        await page.window.close()

    ft.run(main)


if __name__ == '__main__':
    if '--native-child' in sys.argv:
        native_child()
    else:
        unittest.main()
