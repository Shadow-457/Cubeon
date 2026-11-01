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


if __name__ == '__main__':
    unittest.main()
