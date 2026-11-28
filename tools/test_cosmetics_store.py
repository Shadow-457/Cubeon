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
from cubeon import capes, cosmetics_store as store, local_cache, cosmetic_packages, cosmetics


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
        self.stack.enter_context(patch.object(local_cache, "CACHE_DIR", directory))
        local_cache._MEM.clear()
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
                {"offset": ["0"], "kind": ["all"], "models": ["3"]})
        for changes in ({"items": [self.item, self.item]}, {"schema": 2}, {"has_more": "yes"}):
            with patch.object(store, "_bytes", return_value=json.dumps({**page, **changes}).encode()), self.assertRaises(ValueError):
                store.fetch_page()

    def test_saved_pages_survive_restart_and_are_separate_by_page_and_api(self):
        page = {"schema": 1, "offset": 0, "page_size": 12, "has_more": True, "items": [self.item]}
        with patch.object(store, "_bytes", return_value=json.dumps(page).encode()):
            store.fetch_page()
        local_cache._MEM.clear()
        with patch.object(store, "_bytes", side_effect=AssertionError("cache used network")):
            self.assertEqual(store.cached_page(bundled=False), page)
            self.assertIsNone(store.cached_page(12, bundled=False))
            with patch.dict(os.environ, {"CUBEON_COSMETICS_API": "https://another.invalid/api/cosmetics"}):
                self.assertIsNone(store.cached_page())
        with patch.object(local_cache.time, "time", return_value=__import__('time').time() + store.CATALOG_AGE + 1):
            self.assertIsNone(store.cached_page(bundled=False))

    def test_invalid_oversized_or_retired_snapshots_are_not_shown(self):
        page = {"schema": 1, "offset": 0, "page_size": 12, "has_more": False,
                "items": [{**self.item, "id": "cubeon-morpho-orbit"}]}
        key = [store.api_url(), 0]
        local_cache.set(store._CACHE_NS, key, page)
        self.assertEqual(store.cached_page(bundled=False)["items"], [])
        for invalid in ({**page, "schema": 2}, {**page, "items": [{**self.item, "preview_png": "!"}]},
                        {**page, "extra": "x" * store.CATALOG_BYTES}):
            local_cache.set(store._CACHE_NS, key, invalid)
            local_cache._MEM.clear()
            self.assertIsNone(store.cached_page(bundled=False))
        Path(local_cache._path(store._CACHE_NS, key)).write_text('{"time":"broken","value":{}}')
        local_cache._MEM.clear()
        self.assertIsNone(store.cached_page(bundled=False))
        with patch.object(store, "_bytes") as network, self.assertRaises(ValueError):
            store.download({**self.item, "id": "cubeon-morpho-orbit"})
        network.assert_not_called()

    def test_retired_bundled_and_downloaded_models_are_not_in_local_catalog(self):
        retired = dict(id="store_" + "a" * 32, store_id="cubeon-zephyr-sprite", slot="head")
        cosmetics.invalidate_cache()
        with patch.object(cosmetic_packages, "installed_items", return_value=[retired]):
            self.assertFalse(any(item["id"] in {"head_halo", "head_crown", retired["id"]}
                                 for item in cosmetics.items()))
        cosmetics.invalidate_cache()

    def test_first_open_snapshot_works_without_network_or_saved_cache(self):
        items = []
        with patch.object(store, "_bytes", side_effect=AssertionError("first paint waited for network")):
            offset = 0
            while True:
                page = store.cached_page(offset)
                self.assertIsNotNone(page)
                items.extend(page["items"])
                if not page["has_more"]:
                    break
                offset += store.PAGE_SIZE
                self.assertLess(offset, 600)
        ids = {item["id"] for item in items}
        self.assertEqual(len(ids), len(items))
        self.assertFalse(ids & store.STORE_IDS)
        self.assertTrue({"cubeon-midnight-cowl", "cubeon-crimson-web-mask", "cubeon-winter-snowcap"} <= ids)

    def test_bundled_snapshot_and_individual_pages_keep_separate_size_limits(self):
        with patch.object(store, "BUNDLED_CATALOG_BYTES", 1):
            self.assertIsNone(store.cached_page())
        page = {"schema": 1, "offset": 0, "page_size": 12, "has_more": False,
                "items": [self.item], "extra": "x" * store.CATALOG_BYTES}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "store-catalog.json"
            path.write_text(json.dumps({"0": page}))
            self.assertLess(path.stat().st_size, store.BUNDLED_CATALOG_BYTES)
            with patch.object(store, "BUNDLED_CATALOG_PATH", path):
                self.assertIsNone(store.cached_page())

    def test_search_reaches_later_pages_and_reuses_the_complete_catalog(self):
        golden = [{**self.item, "id": f"golden-cape-{i:02}", "name": f"Golden Cape {i:02}"} for i in range(18)]
        other = [{**self.item, "id": f"forest-cape-{i:02}", "name": f"Forest Cape {i:02}"} for i in range(9)]
        entries = other[:8] + golden + other[8:]
        def page(offset):
            return dict(schema=1, offset=offset, page_size=12,
                        items=entries[offset:offset+12], has_more=offset+12 < len(entries))
        with patch.object(store, "cached_page", return_value=None), patch.object(store, "fetch_page", side_effect=page) as fetch:
            catalog = store.fetch_catalog()
            self.assertEqual([call.args[0] for call in fetch.call_args_list], [0, 12, 24])
            first = store.search_page(catalog, "GOLDEN cape")
            second = store.search_page(catalog, "golden cape", 12)
            self.assertEqual(first["total"], 18)
            self.assertTrue(first["has_more"])
            self.assertEqual([item["id"] for item in first["items"] + second["items"]], [item["id"] for item in golden])
            self.assertFalse(second["has_more"])
            self.assertEqual(store.search_page(catalog, "missing")['items'], [])
            self.assertEqual(store.fetch_catalog(), catalog)
            self.assertEqual(fetch.call_count, 3)
            store.fetch_catalog(force=True)
            self.assertEqual(fetch.call_count, 6)

    def test_search_uses_the_entire_offline_bundle_and_marks_partial_saved_pages(self):
        with patch.object(store, "_bytes", side_effect=AssertionError("offline search used network")):
            catalog = store.cached_catalog()
            result = store.search_page(catalog, "sunward halo headwear")
            self.assertTrue(catalog["complete"])
            self.assertEqual([item["id"] for item in result["items"]], ["cubeon-sunward-halo"])
        first = dict(items=[self.item], has_more=True)
        with patch.object(store, "cached_page", side_effect=lambda offset, **kwargs: first if offset == 0 else None):
            partial = store.cached_catalog()
            self.assertFalse(partial["complete"])
            self.assertEqual(store.search_page(partial, "sample")["total"], 1)

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
    def test_search_debounces_paginates_and_discards_an_older_query_response(self):
        import _fuzz_common as fz
        from app_driver import DriverPage
        import flet as ft
        from cubeon import thread_safe_ui
        from cubeon.theme import THEME, section_label, pixel_divider
        import ui.skin_tab as skin_ui
        from ui.appearance_preview import AppearancePreview
        fz.install_safe_stubs()
        jobs, timers = [], []
        class QueuedThread:
            def __init__(self, target, args=(), **kwargs): self.target = lambda: target(*args)
            def start(self): jobs.append(self.target)
        class Timer:
            def __init__(self, delay, target): self.target, self.cancelled = target, False
            def start(self): timers.append(self)
            def cancel(self): self.cancelled = True
            def fire(self):
                if not self.cancelled: self.target()
        item = entry(png(Image.new("RGBA", (64, 32), "green")))
        normal = dict(items=[item], offset=0, has_more=False)
        golden = [{**item, "id": f"golden-cape-{i:02}", "name": f"Golden Cape {i:02}"} for i in range(15)]
        forest = {**item, "id": "forest-cape", "name": "Forest Cape"}
        catalog = dict(schema=1, complete=True, items=golden+[forest])
        calls = []
        def index(**kwargs):
            if kwargs.get("max_age") == 60 and not calls: return None
            return catalog
        def fetch_index(**kwargs):
            calls.append(kwargs)
            # A newer query paints while the first query's transport is delayed.
            field.value = "forest"
            field.on_change(None)
            timers[-1].fire()
            jobs[-1]()
            return catalog
        with patch.object(skin_ui, "threading", SimpleNamespace(**{**vars(threading), "Thread": QueuedThread, "Timer": Timer})), \
                patch.object(thread_safe_ui, "refresh"), patch.object(AppearancePreview, "refresh"), \
                patch.object(store, "cached_page", return_value=normal), patch.object(store, "fetch_page") as fetch_page, \
                patch.object(store, "cached_catalog", side_effect=index), patch.object(store, "fetch_catalog", side_effect=fetch_index), \
                patch.object(store, "has_installed", return_value=False):
            page = DriverPage()
            root = skin_ui.build_skin_section(page, {}, section_label=section_label, pixel_divider=pixel_divider,
                **THEME, assets_dir=str(ROOT / "assets"), mc_version="1.21.11", mc_loader="fabric",
                file_picker=ft.FilePicker(), cape_file_picker=ft.FilePicker())
            next(c for c in fz.walk(root) if callable(getattr(c, "on_click", None))
                 and any(getattr(t, "value", None) == "Store" for t in fz.walk(c))).on_click(None)
            jobs[-1]()
            field = next(c for c in fz.walk(root) if c.data == "cosmetics-store-search")
            field.value = "golden"
            field.on_submit(None)
            jobs[-1]()
            self.assertIn("forest cape", fz.subtree_text(root))
            self.assertNotIn("golden cape 00", fz.subtree_text(root))
            self.assertEqual(len(calls), 1)
            field.value = "GOLDEN"
            field.on_change(None)
            field.value = "Golden"
            field.on_change(None)
            self.assertTrue(timers[-2].cancelled)
            timers[-1].fire()
            jobs[-1]()
            self.assertIn("golden cape 00", fz.subtree_text(root))
            images = [c for c in fz.walk(root) if isinstance(c, ft.Image)]
            field.value = "golden"
            field.on_submit(None)
            jobs[-1]()
            self.assertEqual(images, [c for c in fz.walk(root) if isinstance(c, ft.Image)])
            next(c for c in fz.walk(root) if getattr(c, "tooltip", None) == "Next store page").on_click(None)
            jobs[-1]()
            self.assertIn("golden cape 14", fz.subtree_text(root))
            self.assertNotIn("golden cape 00", fz.subtree_text(root))
            field.value = ""
            field.on_submit(None)
            jobs[-1]()
            self.assertIn("sample cape", fz.subtree_text(root))
            self.assertNotIn("golden cape 14", fz.subtree_text(root))
            fetch_page.assert_not_called()
            self.assertEqual(page.update_calls, 0)

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
                patch.object(store, "cached_page", return_value=None), \
                patch.object(store, "has_installed", return_value=False), \
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
            store_pane = next(c for c in fz.walk(root) if c.data == "cosmetics-store")
            images = [c for c in fz.walk(store_pane) if isinstance(c, ft.Image)]
            primary = next(c for c in fz.walk(root) if isinstance(c, ft.Container)
                and str(c.tooltip).startswith("Download Sample Cape"))
            primary.cubeon_keyboard_button.on_click(None)
            primary.cubeon_keyboard_button.on_click(None)
            jobs[-1]()
            download.assert_called_once_with(item)
            self.assertEqual(cfg["active_cape"], "existing.png")
            self.assertIn("downloaded sample cape", fz.subtree_text(root))
            self.assertEqual(images, [c for c in fz.walk(store_pane) if isinstance(c, ft.Image)])
            tab("Skin")
            tab("Store")
            fetch.assert_called_once()
            self.assertEqual(page.update_calls, 0)

    def test_saved_cards_paint_before_slow_network_and_stale_pages_cannot_overwrite_navigation(self):
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
        item = entry(png(Image.new("RGBA", (64, 32), "green")))
        saved = dict(items=[item], offset=0, has_more=True)
        second_item = {**item, "id": "second-cape", "name": "Second Cape"}
        second = dict(items=[second_item], offset=12, has_more=False)
        def cache(offset, **kwargs):
            return None if kwargs.get("max_age") == 60 else (saved if offset == 0 else second)
        def fetch(offset):
            # This runs where a slow transport would block: saved cards are
            # already mounted and navigation works before the response arrives.
            self.assertIn("sample cape", fz.subtree_text(root))
            images = [c for c in fz.walk(root) if isinstance(c, ft.Image)]
            next(c for c in fz.walk(root) if getattr(c, 'tooltip', None) == 'Next store page').on_click(None)
            jobs[-1]()  # second page's offline refresh
            self.assertIn("second cape", fz.subtree_text(root))
            self.assertNotEqual(images, [c for c in fz.walk(root) if isinstance(c, ft.Image)])
            return saved  # late first-page response must be ignored
        with patch.object(skin_ui, "threading", SimpleNamespace(**{**vars(threading), "Thread": QueuedThread})), \
                patch.object(thread_safe_ui, "refresh"), patch.object(AppearancePreview, "refresh"), \
                patch.object(store, "cached_page", side_effect=cache), patch.object(store, "has_installed", return_value=False), \
                patch.object(store, "fetch_page", side_effect=lambda offset: fetch(offset) if offset == 0 else (_ for _ in ()).throw(OSError("offline"))):
            page = DriverPage()
            root = skin_ui.build_skin_section(page, {}, section_label=section_label,
                pixel_divider=pixel_divider, **THEME, assets_dir=str(ROOT / "assets"),
                mc_version="1.21.11", mc_loader="fabric", file_picker=ft.FilePicker(), cape_file_picker=ft.FilePicker())
            next(c for c in fz.walk(root) if callable(getattr(c, 'on_click', None))
                 and any(getattr(t, 'value', None) == 'Store' for t in fz.walk(c))).on_click(None)
            jobs[-1]()
            self.assertIn("second cape", fz.subtree_text(root))
            self.assertNotIn("sample cape", fz.subtree_text(root))
            self.assertIn("showing saved cosmetics", fz.subtree_text(root))
            self.assertEqual(page.update_calls, 0)


if __name__ == "__main__":
    unittest.main()
