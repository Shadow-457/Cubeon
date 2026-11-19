"""Neon store downloads through the real cape importer and retained picker UI."""
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "tools")]
import _sandbox_home
_sandbox_home.isolate()
from PIL import Image
from cubeon import capes, cosmetics_store as store


def png(image):
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


def entry(data):
    return {"id": "sample-cape", "kind": "cape", "name": "Sample Cape", "description": "A sample",
        "mime_type": "image/png", "byte_size": len(data), "sha256": hashlib.sha256(data).hexdigest(),
        "preview_png": base64.b64encode(png(Image.new("RGBA", (80, 128), "green"))).decode()}


class Downloads(unittest.TestCase):
    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.addCleanup(self.stack.close)
        directory = self.stack.enter_context(tempfile.TemporaryDirectory())
        self.stack.enter_context(patch.object(capes, "CAPES_DIR", directory))
        self.stack.enter_context(patch.object(capes, "CAPES_META_PATH", str(Path(directory) / "capes.json")))
        self.data = png(Image.new("RGBA", (64, 32), "green"))
        self.item = entry(self.data)

    def test_real_import_and_repeat_download_and_deletion(self):
        with patch.object(store, "_bytes", return_value=self.data) as fetch:
            saved = store.download(self.item)
            self.assertEqual(saved["store_id"], self.item["id"])
            self.assertEqual(saved["store_sha256"], self.item["sha256"])
            self.assertEqual(store.download(self.item), saved)
            self.assertEqual(fetch.call_count, 1)
            with Image.open(capes.get_custom_cape_path(saved["filename"])) as image:
                self.assertEqual(image.size, (64, 32))
            capes.delete_custom_cape(saved["filename"])
            store.download(self.item)
            self.assertEqual(fetch.call_count, 2)
            self.assertEqual(len(capes.list_custom_capes()), 1)

    def test_corrupt_or_changed_download_does_not_import(self):
        for payload in (b"", self.data[:-1], b"x" * len(self.data)):
            with patch.object(store, "_bytes", return_value=payload), self.assertRaises(ValueError):
                store.download(self.item)
        self.assertEqual(capes.list_custom_capes(), [])

    def test_untrusted_catalog_and_preview_bounds(self):
        for changes in ({"id": "../../escape"}, {"kind": "executable"}, {"byte_size": True},
                {"sha256": "bad"}, {"preview_png": "!"}, {"name": " "},
                {"preview_png": base64.b64encode(png(Image.new("RGBA", (1024, 1024)))).decode()}):
            with self.assertRaises(ValueError):
                store.download({**self.item, **changes})
        self.assertEqual(capes.list_custom_capes(), [])

    def test_page_validates_duplicates_and_schema(self):
        page = {"schema": 1, "offset": 0, "page_size": 12, "has_more": False, "items": [self.item]}
        with patch.object(store, "_bytes", return_value=json.dumps(page).encode()) as fetch:
            self.assertEqual(store.fetch_page()["items"], [self.item])
            from urllib.parse import parse_qs, urlsplit
            self.assertEqual(parse_qs(urlsplit(fetch.call_args.args[0]).query),
                {"offset": ["0"], "kind": ["all"], "models": ["2"]})
        for changes in ({"items": [self.item, self.item]}, {"schema": 2}, {"has_more": "yes"}):
            with patch.object(store, "_bytes", return_value=json.dumps({**page, **changes}).encode()), self.assertRaises(ValueError):
                store.fetch_page()

    def test_gif_animation_survives_import(self):
        stream = io.BytesIO()
        Image.new("RGBA", (64, 32), "red").save(stream, "GIF", save_all=True,
            append_images=[Image.new("RGBA", (64, 32), "blue")], duration=[100, 200], loop=0)
        data = stream.getvalue()
        item = {**entry(data), "mime_type": "image/gif"}
        with patch.object(store, "_bytes", return_value=data):
            saved = store.download(item)
        self.assertTrue(saved["animated"])
        self.assertEqual(capes.animation_info(saved["filename"])["count"], 2)

    def test_concurrent_download_imports_one_cape(self):
        with patch.object(store, "_bytes", return_value=self.data):
            threads = [threading.Thread(target=store.download, args=(self.item,)) for _ in range(4)]
            for thread in threads: thread.start()
            for thread in threads: thread.join(10)
            self.assertTrue(all(not thread.is_alive() for thread in threads))
        self.assertEqual(len(capes.list_custom_capes()), 1)

    def test_import_failure_preserves_files_and_metadata(self):
        with patch.object(store, "_bytes", return_value=self.data), patch.object(capes, "_save_capes_meta", side_effect=OSError("disk full")):
            with self.assertRaises(OSError): store.download(self.item)
        self.assertEqual(list(Path(capes.CAPES_DIR).iterdir()), [])

    def test_source_publisher_uses_existing_art_and_validates_upload(self):
        spec = importlib.util.spec_from_file_location("publish_capes", ROOT / "worker/manage-cosmetics.py")
        publisher = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(publisher)
        source = ROOT / "assets/capes/cubeon_cape.png"
        prepared = publisher.prepare_cape(source, "cubeon-cape-sample", "Sample", "")
        self.assertEqual(base64.b64decode(prepared[4]), source.read_bytes())
        self.assertEqual(len(base64.b64decode(prepared[-1])) < 24576, True)


class Picker(unittest.TestCase):
    def test_store_is_lazy_downloads_without_equipping_and_retains_images(self):
        import _fuzz_common as fz
        from app_driver import DriverPage
        import flet as ft
        from cubeon import thread_safe_ui
        from cubeon.theme import THEME, section_label, pixel_divider
        import ui.skin_tab as skin_ui
        from ui.appearance_preview import AppearancePreview
        fz.install_safe_stubs()
        jobs = []
        class QueuedThread:
            def __init__(self, target, args=(), **kwargs): self.target = lambda: target(*args)
            def start(self): jobs.append(self.target)
        cfg = {"username": "Tester", "active_cape": "existing.png"}
        item = entry(png(Image.new("RGBA", (64, 32), "green")))
        data = {"items": [item], "offset": 0, "has_more": False}
        with patch.object(skin_ui, "threading", SimpleNamespace(**{**vars(threading), "Thread": QueuedThread})), \
                patch.object(thread_safe_ui, "refresh"), patch.object(AppearancePreview, "refresh"), \
                patch.object(store, "fetch_page", return_value=data) as fetch, \
                patch.object(store, "installed", return_value=None), \
                patch.object(store, "download", return_value={"filename": "new.png"}) as download:
            page = DriverPage()
            root = skin_ui.build_skin_section(page, cfg, section_label=section_label,
                pixel_divider=pixel_divider, **THEME, assets_dir=str(ROOT / "assets"),
                mc_version="1.21.11", mc_loader="fabric",
                file_picker=ft.FilePicker(), cape_file_picker=ft.FilePicker())
            fetch.assert_not_called()
            def tab(label):
                next(c for c in fz.walk(root) if callable(getattr(c, "on_click", None))
                    and any(getattr(t, "value", None) == label for t in fz.walk(c))).on_click(None)
            tab("Store")
            fetch.assert_not_called()
            jobs[-1]()
            fetch.assert_called_once_with(0)
            images = [c for c in fz.walk(root) if isinstance(c, ft.Image)]
            primary = next(c for c in fz.walk(root) if isinstance(c, ft.Container)
                and str(c.tooltip).startswith("Download Sample Cape"))
            primary.cubeon_keyboard_button.on_click(None)
            primary.cubeon_keyboard_button.on_click(None)
            jobs[-1]()
            download.assert_called_once_with(item)
            self.assertEqual(cfg["active_cape"], "existing.png")
            self.assertIn("downloaded sample cape", fz.subtree_text(root))
            self.assertEqual(images, [c for c in fz.walk(root) if isinstance(c, ft.Image)])
            tab("Skin")
            tab("Store")
            fetch.assert_called_once()
            self.assertEqual(page.update_calls, 0)


if __name__ == "__main__":
    unittest.main()
