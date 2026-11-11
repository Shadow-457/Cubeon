"""Deterministic checks for the Minecraft screenshot gallery backend."""

import os
import inspect
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _sandbox_home
_sandbox_home.isolate()

from PIL import Image

from cubeon import screenshot_gallery as gallery
from cubeon import paths, storage


def check(label, condition):
    print(("PASS " if condition else "FAIL ") + label)
    if not condition:
        raise SystemExit(1)


with tempfile.TemporaryDirectory(prefix="cubeon-screenshots-") as root:
    old_dir = gallery.SCREENSHOTS_DIR
    old_cache = gallery._RENDER_CACHE_DIR
    gallery.SCREENSHOTS_DIR = root
    gallery._RENDER_CACHE_DIR = os.path.join(root, "_renders")
    try:
        Image.new("RGB", (1600, 900), (30, 120, 60)).save(
            os.path.join(root, "latest.png"), "PNG")
        Image.new("RGB", (320, 200), (120, 60, 30)).save(
            os.path.join(root, "older.jpg"), "JPEG")
        os.utime(os.path.join(root, "latest.png"), (20, 20))
        os.utime(os.path.join(root, "older.jpg"), (10, 10))
        with open(os.path.join(root, "notes.txt"), "w") as fh:
            fh.write("not an image")

        items = gallery.list_screenshots()
        check("lists supported screenshots only", [x["filename"] for x in items]
              == ["latest.png", "older.jpg"])
        check("metadata includes dimensions", items[0]["width"] == 1600
              and items[0]["height"] == 900)
        thumb = gallery.image_base64("latest.png", max_size=(320, 220))
        check("preview is bounded and encoded", bool(thumb))
        check("clipboard hand-off stays inside the screenshots folder",
              gallery.clipboard_path("latest.png")
              == os.path.join(root, "latest.png"))

        try:
            gallery.image_base64("../notes.txt")
        except ValueError:
            safe = True
        else:
            safe = False
        check("path traversal is rejected", safe)

        gallery.delete_screenshot("older.jpg")
        check("delete removes the selected screenshot",
              not os.path.exists(os.path.join(root, "older.jpg")))
    finally:
        gallery.SCREENSHOTS_DIR = old_dir
        gallery._RENDER_CACHE_DIR = old_cache

print("6/6 passed")


class FolderTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cubeon-folder-")
        self.addCleanup(self.temp.cleanup)
        self.folder = os.path.join(self.temp.name, "screenshots with spaces")
        self.process = Mock()
        self.process.wait.return_value = 0
        for replacement in (
            patch.object(gallery, "SCREENSHOTS_DIR", self.folder),
            patch.object(storage, "enabled", return_value=False),
            patch.object(gallery.sys, "platform", "linux"),
            patch.object(gallery.sys, "frozen", False, create=True),
        ):
            replacement.start()
            self.addCleanup(replacement.stop)

    def test_windows_uses_shell_folder_association(self):
        with patch.object(gallery.sys, "platform", "win32"), \
             patch.object(gallery.os, "startfile", create=True) as startfile, \
             patch.object(gallery.subprocess, "Popen") as popen:
            self.assertEqual(gallery.open_screenshots_folder(), self.folder)
        startfile.assert_called_once_with(self.folder)
        popen.assert_not_called()
        self.assertTrue(os.path.isdir(self.folder))

    def test_unix_helpers_receive_whole_folder_path(self):
        for platform, helper in (("linux", "xdg-open"), ("darwin", "open")):
            with self.subTest(platform=platform), \
                 patch.object(gallery.sys, "platform", platform), \
                 patch.object(gallery.subprocess, "Popen", return_value=self.process) as popen:
                self.assertEqual(gallery.open_screenshots_folder(), self.folder)
                self.assertEqual(popen.call_args.args[0], [helper, self.folder])

    def test_active_instance_is_used_without_selection(self):
        with patch.object(storage, "enabled", return_value=True), \
             patch.object(paths, "active_game_dir", return_value=self.temp.name), \
             patch.object(gallery.subprocess, "Popen", return_value=self.process):
            self.assertEqual(gallery.open_screenshots_folder(),
                             os.path.join(self.temp.name, "screenshots"))

    def test_selected_capture_opens_its_own_instance(self):
        selected = os.path.join(self.temp.name, "other instance", "screenshots")
        os.makedirs(selected)
        Image.new("RGB", (3, 3)).save(os.path.join(selected, "same.png"))
        with patch.object(gallery, "_folders", return_value={"other": selected}), \
             patch.object(gallery.subprocess, "Popen", return_value=self.process) as popen:
            self.assertEqual(gallery.open_screenshots_folder("@other@same.png"), selected)
            self.assertEqual(popen.call_args.args[0][-1], selected)
            with self.assertRaises(ValueError):
                gallery.open_screenshots_folder("../outside.png")
            with self.assertRaises(FileNotFoundError):
                gallery.open_screenshots_folder("@other@missing.png")
            self.assertEqual(popen.call_count, 1)

    def test_helper_failure_reports_real_stderr(self):
        real_popen = gallery.subprocess.Popen

        def failing_helper(command, **kwargs):
            return real_popen([sys.executable, "-c",
                               "import sys; sys.stderr.write('File manager rejected folder'); sys.exit(4)"],
                              **kwargs)

        with patch.object(gallery.subprocess, "Popen", side_effect=failing_helper):
            with self.assertRaisesRegex(OSError, "File manager rejected folder"):
                gallery.open_screenshots_folder()

    def test_long_lived_manager_is_left_open(self):
        self.process.wait.side_effect = gallery.subprocess.TimeoutExpired("xdg-open", 10)
        with patch.object(gallery.subprocess, "Popen", return_value=self.process):
            self.assertEqual(gallery.open_screenshots_folder(), self.folder)
        self.process.kill.assert_not_called()
        self.process.terminate.assert_not_called()

    def test_frozen_linux_restores_system_libraries_without_mutating_launcher(self):
        for original in (None, "", "/system/lib"):
            with self.subTest(original=original), \
                 patch.dict(os.environ, {}, clear=True), \
                 patch.object(gallery.sys, "frozen", True, create=True), \
                 patch.object(gallery.subprocess, "Popen", return_value=self.process) as popen:
                os.environ["LD_LIBRARY_PATH"] = "/cubeon/bundled/lib"
                if original is not None:
                    os.environ["LD_LIBRARY_PATH_ORIG"] = original
                gallery.open_screenshots_folder()
                child_env = popen.call_args.kwargs["env"]
                self.assertEqual(child_env.get("LD_LIBRARY_PATH"), original)
                self.assertEqual(os.environ["LD_LIBRARY_PATH"], "/cubeon/bundled/lib")

    def test_button_waits_off_ui_thread_and_displays_failures(self):
        from _fuzz_common import FakePage, walk
        from ui import screenshot_gallery as ui

        page = FakePage()
        root, refresh = ui.build_screenshot_gallery_tab(page)
        controls = list(walk(root))
        button = next(c for c in controls if c.data == "screenshot-folder")
        entered = threading.Event()
        release = threading.Event()
        finished = threading.Event()
        scanned = threading.Event()
        ui_thread = threading.get_ident()

        def slow_failure(filename):
            self.assertNotEqual(threading.get_ident(), ui_thread)
            entered.set()
            if not release.wait(3):
                raise RuntimeError("test release timed out")
            raise OSError("File manager rejected folder")

        def repaint(control):
            if getattr(control, "value", "") == "1 screenshot found":
                scanned.set()
            if control is button and not button.disabled:
                finished.set()

        with patch.object(ui.store, "list_screenshots", return_value=[{
            "filename": "@other@same.png", "name": "same", "date": "today",
            "width": 3, "height": 3, "bytes": 1,
        }]), patch.object(ui.store, "image_base64", return_value="image"), \
             patch.object(ui.thread_safe_ui, "refresh", side_effect=repaint), \
             patch.object(ui.store, "open_screenshots_folder", side_effect=slow_failure) as opener:
            refresh()
            self.assertTrue(scanned.wait(3))
            button.on_click(None)
            try:
                self.assertTrue(entered.wait(3))
                self.assertTrue(button.disabled)
                button.on_click(None)
                opener.assert_called_once_with("@other@same.png")
            finally:
                release.set()
            self.assertTrue(finished.wait(3))
            self.assertFalse(button.disabled)
            self.assertTrue(any(getattr(c, "value", "") ==
                                "Couldn't open folder: File manager rejected folder"
                                for c in controls))
        self.assertEqual(page.update_calls, 0)


class RefreshTests(unittest.TestCase):
    def test_slow_scan_is_off_the_ui_thread_and_only_latest_request_paints(self):
        from _fuzz_common import FakePage
        from ui import screenshot_gallery as ui

        root, refresh = ui.build_screenshot_gallery_tab(FakePage())
        scans = inspect.getclosurevars(refresh).nonlocals["scans"]
        original_apply = scans.apply
        entered, release, done = (threading.Event() for _ in range(3))
        reader_threads, applied = [], []
        ui_thread = threading.get_ident()

        def read():
            reader_threads.append(threading.get_ident())
            if len(reader_threads) == 1:
                entered.set()
                if not release.wait(3):
                    raise RuntimeError("test release timed out")
                return [{"stale": True}]
            return []

        def apply(items):
            applied.append(items)
            original_apply(items)
            done.set()

        with patch.object(ui.store, "list_screenshots", side_effect=read), \
             patch.object(ui.thread_safe_ui, "refresh"), \
             patch.object(scans, "apply", side_effect=apply):
            refresh()
            try:
                self.assertTrue(entered.wait(3))
                self.assertNotEqual(reader_threads[0], ui_thread)
                refresh()
            finally:
                release.set()
            self.assertTrue(done.wait(3))
            self.assertEqual(applied, [[]])

    def test_unchanged_inventory_retains_thumbnails_and_selection(self):
        from _fuzz_common import FakePage
        from ui import screenshot_gallery as ui

        root, refresh = ui.build_screenshot_gallery_tab(FakePage())
        scans = inspect.getclosurevars(refresh).nonlocals["scans"]
        values = inspect.getclosurevars(scans.apply).nonlocals
        render = inspect.getclosurevars(values["_render_list"]).nonlocals
        state, column = values["state"], render["thumb_column"]
        items = [{"filename": "one.png", "name": "one", "date": "today",
                  "width": 3, "height": 3, "bytes": 1}]
        with patch.object(ui.threading.Thread, "start"), \
             patch.object(ui.thread_safe_ui, "refresh"), ui.thread_safe_ui.TREE_LOCK:
            scans.apply(items)
            controls, generation = tuple(column.controls), state["generation"]
            scans.apply(list(items))
            self.assertEqual(tuple(column.controls), controls)
            self.assertEqual(state["selected"], "one.png")
            self.assertEqual(state["generation"], generation)


if __name__ == "__main__":
    unittest.main()
