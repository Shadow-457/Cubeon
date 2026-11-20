"""Horizon content installs, native-code gates and captured launcher targets."""
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import stat
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import weakref
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import global_mod_cache, local_cache, mod_catalogue, mods, net, rust_engine, rust_mods

INSTANCE = rust_engine.INSTANCE_ID
ART = b"\x89PNG\r\n\x1a\noriginal artwork\x00\xff"


def package(version="1.0", *, manifest=None, files=None):
    text = manifest or f'''id = "demo"
name = "Demo"
version = "{version}"
api = "0.2"
side = "both"
capabilities = ["registries"]
'''
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("horizon-mod.toml", text)
        for name, content in (files if files is not None else [
            ("assets/demo/textures/block/lamp.png", ART),
            ("data/demo/horizon/block/lamp.json", json.dumps({"id": "demo:lamp", "template": "minecraft:stone",
                "components": {"horizon:fixture": ["horizon:example", "demo:lamp"]}})),
            ("assets/demo/lang/en_us.json", '{"block.demo.lamp": "My lamp"}'),
            ("LICENSE", "Original license and copyright")]):
            archive.writestr(name, content)
    return stream.getvalue()


def project(data=None, version="1.0", ident="demo", **extra):
    data = data or package(version)
    return dict(id=ident, kind="mod", name="Demo", summary="A content mod", description="A content mod with original artwork.",
                authors=["Author"], categories=["decoration"], source="https://github.com/author/demo#readme",
                icon="https://horizon-rust.github.io/horizon-mods/icons/demo.png", downloads=10,
                versions=[dict(version=version, game="26.3", api="0.2", side="both", capabilities=["registries"],
                    published="2026-11-20", file=dict(name=ident + ".hmod",
                        url=f"https://github.com/horizon-rust/horizon-mods/releases/download/{ident}-{version}/{ident}.hmod",
                        size=len(data), sha256=hashlib.sha256(data).hexdigest()))], **extra)


def index(*projects):
    return {"schema": 1, "projects": list(projects) or [project()], "revoked": []}


class RegistryTests(unittest.TestCase):
    def test_content_search_and_native_links_keep_their_actual_reason(self):
        native = project(ident="native_demo")
        native.update(kind="native-mod")
        native["versions"][0].update(api="native-1/newer/engine", capabilities=[])
        with patch.object(rust_mods, "catalogue", return_value=rust_mods._parse_index(index(project(), native))):
            self.assertEqual([p["project_id"] for p in mods.search_mods("", "26.3", "rust")], ["demo"])
            blocked = mods.search_mods("https://playhorizon.dev/mods/native_demo", "26.3", "rust")[0]
            self.assertFalse(blocked["compatible"])
            self.assertIn("native-code", blocked["compatibility_reason"])
            self.assertIsNone(mods.get_mod_download("horizon:native_demo", "26.3", "rust"))
            self.assertEqual(mods.get_mod_details("horizon:demo")["author"], "Author")
            self.assertEqual(mods.get_mod_versions("horizon:demo", "26.3", "rust")[0]["file_id"], "1.0")
            self.assertEqual(mods.search_mods("", "1.21.1", "fabric", source="horizon"), [])
            with self.assertRaisesRegex(ValueError, "Horizon content mod"):
                mods.search_mods("https://modrinth.com/mod/sodium", "26.3", "rust")

    def test_malformed_entries_do_not_hide_healthy_projects(self):
        for field, value in (("authors", "someone"), ("categories", None), ("downloads", "10"),
                             ("screenshots", [None]), ("versions", None), ("key", 4)):
            bad = project(ident="bad")
            bad[field] = value
            with self.subTest(field=field):
                self.assertEqual([p["id"] for p in rust_mods._parse_index(index(project(), bad))["projects"]], ["demo"])
        for value in (None, [], "a file"):
            bad = project(ident="bad")
            bad["versions"][0]["file"] = value
            self.assertEqual(len(rust_mods._parse_index(index(project(), bad))["projects"]), 1)
        self.assertEqual(rust_mods._parse_index(index(project(), project()))["projects"], [])
        for malformed in ({}, {"schema": 2, "projects": []}, {"schema": 1, "projects": [], "revoked": {}}):
            with self.assertRaises(ValueError):
                rust_mods._parse_index(malformed)

    def test_release_download_hosts_are_restricted(self):
        p = project()
        self.assertTrue(rust_mods.download_url(p["versions"][0]["file"]["url"], p))
        self.assertTrue(rust_mods.download_url("https://github.com/author/demo/releases/download/v1/demo.hmod", p))
        self.assertTrue(rust_mods.download_url("https://release-assets.githubusercontent.com/asset?token=x", p))
        for url in ("http://github.com/author/demo/releases/download/v1/demo.hmod",
                    "https://github.com/other/repo/releases/download/v1/demo.hmod",
                    "https://github.com@evil.test/author/demo/releases/download/v1/demo.hmod",
                    "https://github.com/author/demo/blob/main/demo.hmod",
                    "https://github.com/author/demo/releases/download/v1/demo.hmod#fragment"):
            self.assertFalse(rust_mods.download_url(url, p), url)
        self.assertEqual(mod_catalogue.reference("https://playhorizon.dev/mods/demo")["source"], "horizon")
        self.assertEqual(mod_catalogue.SOURCES, ("modrinth", "curseforge"))

    def test_registry_cache_offline_retry_limits_and_cancellation(self):
        class Response:
            status_code = 200
            headers = {}
            closed = False
            def iter_content(self, _size):
                yield json.dumps(index()).encode()
            def close(self):
                self.closed = True
            def raise_for_status(self):
                pass
        with tempfile.TemporaryDirectory() as temporary, patch.object(local_cache, "CACHE_DIR", temporary):
            response = Response()
            with patch.object(net, "_do_get", return_value=response) as get:
                first = rust_mods.catalogue(force=True)
                self.assertEqual(first["projects"][0]["id"], "demo")
                self.assertIs(rust_mods.catalogue(), first)
                self.assertIs(rust_mods.catalogue(allow_network=False), first)
                self.assertEqual(get.call_count, 1)
                self.assertTrue(response.closed)
            with patch.object(net, "_do_get", side_effect=net.DownloadError("offline")):
                self.assertIs(rust_mods.catalogue(), first)
                with self.assertRaisesRegex(net.DownloadError, "offline"):
                    rust_mods.catalogue(force=True)
            with patch.object(net, "_do_get", return_value=Response()), patch.object(rust_mods, "MAX_INDEX", 10):
                with self.assertRaisesRegex(ValueError, "too large"):
                    rust_mods.catalogue(force=True)
            cancel = threading.Event(); cancel.set()
            with patch.object(net, "_do_get") as get:
                with self.assertRaises(net.DownloadCancelled):
                    rust_mods.catalogue(cancel_event=cancel)
                get.assert_not_called()


class RustModsTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.data = package()
        self.index = rust_mods._parse_index(index(project(self.data)))
        for context in (patch.object(rust_engine.paths, "CUBEON_HOME", str(self.root / "launcher")),
                        patch.object(rust_mods, "catalogue", side_effect=lambda **_: self.index),
                        patch.object(global_mod_cache, "_store_root", return_value=str(self.root / "store")),
                        patch.object(global_mod_cache, "_index_path", return_value=str(self.root / "store/index.json"))):
            context.start(); self.addCleanup(context.stop)
        self.directory = rust_mods.mods_dir(INSTANCE, create=True)
        self.settings = Path(rust_engine.game_dir()) / rust_mods.MOD_LIST
        self.settings.write_text("key.mod_menu:key.keyboard.m\nother:preserved\n")
        self.receipt = Path(mods._meta_path(str(self.directory), "demo.hmod"))

    def local(self, data=None, *, replace=False):
        source = self.root / "custom-name.hmod"
        source.write_bytes(data or self.data)
        return mods.install_local_mod(str(source), "26.3", "rust", version_id=INSTANCE, replace=replace)

    def fake_download(self, dest, url, **kwargs):
        self.assertTrue(kwargs["url_validator"](url))
        Path(dest).write_bytes(self.data)
        if kwargs.get("progress_cb"):
            kwargs["progress_cb"](len(self.data), len(self.data))

    def online(self):
        with patch.object(net, "download_to", side_effect=self.fake_download):
            return mods.install_mod_with_dependencies("ignored", "ignored.hmod", "26.3", "rust",
                project_id="demo", source="horizon", version_id=INSTANCE)

    def test_local_import_adapts_declarations_preserves_art_and_enables(self):
        self.assertEqual(self.local(), "demo.hmod")
        installed = self.directory / "demo.hmod"
        self.assertTrue(installed.is_file()); self.assertFalse(installed.is_symlink())
        with zipfile.ZipFile(installed) as archive:
            self.assertIn("cubeon-mod.toml", archive.namelist())
            self.assertNotIn("horizon-mod.toml", archive.namelist())
            self.assertEqual(archive.read("assets/demo/textures/block/lamp.png"), ART)
            self.assertEqual(archive.read("LICENSE"), b"Original license and copyright")
            self.assertEqual(archive.read("assets/demo/lang/en_us.json"), b'{"block.demo.lamp": "My lamp"}')
            self.assertEqual(json.loads(archive.read("data/demo/cubeon/block/lamp.json"))["components"],
                             {"cubeon:fixture": ["cubeon:example", "demo:lamp"]})
        self.assertIn("key.mod_menu:key.keyboard.m", self.settings.read_text())
        self.assertIn("mod.demo:true", self.settings.read_text())
        self.assertTrue(mods.list_mods("26.3", "rust", INSTANCE)[0]["enabled"])
        self.assertEqual(mods.resolve_profile_dir("wrong", "fabric", INSTANCE), str(self.directory))

    def test_download_reuses_original_bytes_and_pins_the_receipt(self):
        with patch.object(net, "download_to", side_effect=self.fake_download) as fetch:
            for _ in range(2):
                rust_mods.install("demo", INSTANCE)
            self.assertEqual(fetch.call_count, 1)
        raw = global_mod_cache.cache_path_if_present(hashlib.sha256(self.data).hexdigest())
        self.assertEqual(Path(raw).suffix, ".hmod")
        self.assertEqual(Path(raw).read_bytes(), self.data)
        receipt = json.loads(self.receipt.read_text())
        self.assertEqual((receipt["source"], receipt["file_id"], receipt["source_sha256"]),
                         ("horizon", "1.0", hashlib.sha256(self.data).hexdigest()))
        self.assertNotEqual((self.directory / "demo.hmod").read_bytes(), self.data)

    def test_updates_keep_disabled_state_and_local_replacements_clear_online_identity(self):
        self.online()
        mods.toggle_mod("26.3", "rust", "demo.hmod", INSTANCE)
        self.data = package("2.0")
        self.index = rust_mods._parse_index(index(project(self.data, "2.0")))
        self.online()
        installed = rust_mods.list_mods(INSTANCE)[0]
        self.assertEqual(installed["version"], "2.0")
        self.assertFalse(installed["enabled"])
        before = (self.directory / "demo.hmod").read_bytes()
        with self.assertRaisesRegex(ValueError, "already installed"):
            self.local(package("3.0"))
        self.assertEqual((self.directory / "demo.hmod").read_bytes(), before)
        self.local(package("3.0"), replace=True)
        self.assertIsNone(rust_mods.list_mods(INSTANCE)[0]["source"])
        self.assertNotIn("signature_key", json.loads(self.receipt.read_text()))

    def test_new_install_after_remove_is_enabled_and_other_settings_survive(self):
        self.local()
        mods.delete_mod("26.3", "rust", "demo.hmod", INSTANCE)
        self.assertFalse(self.receipt.exists())
        self.local()
        self.assertTrue(rust_mods.list_mods(INSTANCE)[0]["enabled"])
        self.assertIn("other:preserved", self.settings.read_text())

    def test_java_targets_and_java_packages_never_reach_the_rust_folder(self):
        with patch.object(net, "download_to") as get:
            for target in (("demo", "java-instance"), ("demo", None)):
                with self.assertRaises(ValueError):
                    rust_mods.install(*target)
            with self.assertRaises(ValueError):
                mods.install_mod_with_dependencies("ignored", "demo.jar", "26.3", "fabric", version_id=INSTANCE)
            get.assert_not_called()
        source = self.root / "mod.jar"; source.write_bytes(self.data)
        with self.assertRaises(ValueError):
            mods.install_local_mod(str(source), "26.3", "rust", version_id=INSTANCE)
        self.assertFalse((self.directory / "demo.hmod").exists())

    def test_corrupt_download_and_size_overrun_do_not_replace_an_install(self):
        self.local()
        previous = (self.directory / "demo.hmod").read_bytes()
        with patch.object(net, "download_to", side_effect=lambda path, *_a, **_k: Path(path).write_bytes(b"corrupt")):
            with self.assertRaises(ValueError):
                rust_mods.install("demo", INSTANCE)
        def oversized(_path, _url, **kwargs):
            kwargs["progress_cb"](len(self.data) + 1, len(self.data))
        with patch.object(net, "download_to", side_effect=oversized):
            with self.assertRaisesRegex(ValueError, "exceeds its published size"):
                rust_mods.install("demo", INSTANCE)
        self.assertEqual((self.directory / "demo.hmod").read_bytes(), previous)

    def test_package_receipt_and_settings_all_roll_back_on_publication_failure(self):
        self.online()
        for failure in (self.directory / "demo.hmod", self.receipt, self.settings):
            with self.subTest(failure=failure.name):
                before = {p: p.read_bytes() for p in (self.directory / "demo.hmod", self.receipt, self.settings)}
                original_replace = os.replace
                failed = False
                def replace(source, destination):
                    nonlocal failed
                    if Path(destination) == failure and not failed:
                        failed = True
                        raise OSError("disk full")
                    return original_replace(source, destination)
                with patch.object(os, "replace", side_effect=replace):
                    with self.assertRaisesRegex(OSError, "disk full"):
                        self.local(package("2.0"), replace=True)
                self.assertEqual({p: p.read_bytes() for p in before}, before)
                self.assertEqual(rust_mods.list_mods(INSTANCE)[0]["file_id"], "1.0")

    def test_failed_first_install_and_cancellation_leave_no_published_mod(self):
        before = self.settings.read_bytes()
        original_replace = os.replace
        def replace(source, destination):
            if Path(destination) == self.receipt:
                raise OSError("receipt failed")
            return original_replace(source, destination)
        with patch.object(os, "replace", side_effect=replace), self.assertRaises(OSError):
            self.local()
        self.assertFalse((self.directory / "demo.hmod").exists())
        self.assertFalse(self.receipt.exists()); self.assertEqual(self.settings.read_bytes(), before)
        cancel = threading.Event(); cancel.set()
        with patch.object(net, "download_to") as get, self.assertRaises(net.DownloadCancelled):
            rust_mods.install("demo", INSTANCE, cancel_event=cancel)
        get.assert_not_called()
        counter = 0
        cancel.clear()
        original = net.check_cancelled
        def during(event):
            nonlocal counter
            counter += 1
            if counter == 3: cancel.set()
            original(event)
        with patch.object(net, "check_cancelled", side_effect=during):
            with self.assertRaises(net.DownloadCancelled):
                rust_mods._publish(self.data, INSTANCE, cancel_event=cancel)
        self.assertFalse((self.directory / "demo.hmod").exists())
        self.assertEqual(self.settings.read_bytes(), before)

    def test_revoked_original_hash_disables_an_adapted_copy_and_blocks_reenable(self):
        self.online()
        self.index["revoked"] = [{"id": "demo", "sha256": hashlib.sha256(self.data).hexdigest(), "reason": "Withdrawn release"}]
        installed = rust_mods.list_mods(INSTANCE)[0]
        self.assertFalse(installed["enabled"])
        self.assertIn("Withdrawn release", installed["issue"])
        with self.assertRaisesRegex(ValueError, "Withdrawn release"):
            rust_mods.toggle(INSTANCE, "demo.hmod")
        with self.assertRaisesRegex(ValueError, "Withdrawn release"):
            self.local(replace=True)
        self.assertIn("key.mod_menu:key.keyboard.m", self.settings.read_text())

    def test_changed_signing_key_keeps_the_existing_release(self):
        self.online()
        receipt = json.loads(self.receipt.read_text())
        receipt["signature_key"] = "previous-key"
        self.receipt.write_text(json.dumps(receipt)); mods._forget_sidecar(str(self.receipt))
        before = (self.directory / "demo.hmod").read_bytes()
        with self.assertRaisesRegex(ValueError, "signing key changed"):
            self.online()
        self.assertEqual((self.directory / "demo.hmod").read_bytes(), before)

    def test_unsafe_or_code_packages_are_refused_before_publication(self):
        variants = [package(files=[("../escape", "bad")]), package(files=[("assets/demo/../escape", "bad")]),
                    package(files=[("assets/other/textures/a.png", ART)]), package(files=[("mod.wasm", b"code")]),
                    package(files=[("cubeon-native.json", "{}")]), package(files=[("Cargo.toml", "[package]")]),
                    package(files=[("data/demo/cubeon/item/bad.json", "broken json")]),
                    package(manifest='id="demo"\nname="Demo"\nversion="1"\napi="0.2"\ncapabilities="registries"'),
                    package(manifest='id="demo"\nname="Demo"\nversion="1"\napi="0.2"\ncapabilities=["registries"]\n[native]\ngame="26.3"')]
        for data in variants:
            with self.subTest(size=len(data)), self.assertRaises(ValueError):
                self.local(data)
        stream = io.BytesIO(self.data)
        with zipfile.ZipFile(stream, "a") as archive:
            link = zipfile.ZipInfo("assets/demo/link"); link.external_attr = (stat.S_IFLNK | 0o777) << 16
            archive.writestr(link, "/tmp/elsewhere")
        with self.assertRaises(ValueError): self.local(stream.getvalue())
        self.assertFalse((self.directory / "demo.hmod").exists())


class SignatureTests(unittest.TestCase):
    def test_minisign_legacy_and_prehashed_signatures_and_tampering(self):
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
        from cryptography.hazmat.primitives.serialization import Encoding, PublicFormat
        private = Ed25519PrivateKey.generate()
        key_id = b"fixture1"
        key = base64.b64encode(b"Ed" + key_id + private.public_key().public_bytes(Encoding.Raw, PublicFormat.Raw)).decode()
        data = package()
        for algorithm in (b"Ed", b"ED"):
            signature = private.sign(data if algorithm == b"Ed" else hashlib.blake2b(data).digest())
            comment = "timestamp:1\tfile:demo.hmod"
            text = "\n".join(["untrusted comment: fixture", base64.b64encode(algorithm + key_id + signature).decode(),
                "trusted comment: " + comment, base64.b64encode(private.sign(signature + comment.encode())).decode()])
            rust_mods._signature(data, key, text)
            with self.assertRaisesRegex(ValueError, "signature did not verify"):
                rust_mods._signature(data + b"changed", key, text)
            with self.assertRaises(ValueError): rust_mods._signature(data, key, text.replace("timestamp:1", "timestamp:2"))
            with self.assertRaises(ValueError): rust_mods._signature(data, key, "incomplete")


class ZRustModsUITests(unittest.TestCase):
    def setUp(self):
        import _fuzz_common as fz
        import flet as ft
        from app_driver import DriverPage
        from cubeon import icons, thread_safe_ui
        from cubeon.theme import THEME, section_label
        from test_content_install_feedback import ImmediateExecutor, QueuedThread
        from ui import mods_tab as ui_mods
        self.fz, self.ft, self.queued = fz, ft, QueuedThread
        self.core = fz.install_safe_stubs().core
        self.page = DriverPage()
        # Canonical instance identity must win over a stale Java switcher.
        self.state = {"selected_mc_version": "1.21.11", "mod_loader": "fabric", "installed": {INSTANCE}}
        self.drop = ft.Dropdown(value=INSTANCE)
        self.items = []
        self.core.list_mods = lambda *a, **k: [dict(m) for m in self.items]
        self.core.list_content = lambda *a, **k: []
        for context in (patch("threading.Thread", QueuedThread),
                        patch.object(ui_mods, "ThreadPoolExecutor", ImmediateExecutor),
                        patch.object(icons, "prefetch"), patch.object(thread_safe_ui, "refresh"),
                        patch("ui.install_feedback._active_feedback", weakref.WeakSet())):
            context.start(); self.addCleanup(context.stop)
        QueuedThread.jobs.clear()
        self.view = ui_mods.ModsView(self.page, {}, self.state, self.drop, section_label=section_label, **THEME)
        self.view.artwork.request = lambda *_: None
        self.view._apply_type_labels()
        self.hit = dict(project_id="demo", slug="demo", title="Demo", source="horizon",
                        compatible=True, facet_compatible=True, compatibility_target=["26.3", "rust"])

    def drain(self):
        while self.queued.jobs:
            self.queued.jobs.pop(0)()

    def buttons(self):
        return [control for control in self.fz.walk(self.view.detail_host)
                if hasattr(control, "_cubeon_install_paint")]

    def test_rust_context_and_hmod_picker_do_not_enable_java_content(self):
        self.assertEqual(self.view._installed_target(), ("mod", "26.3", "rust", INSTANCE))
        self.assertTrue(self.view._can_install())
        self.assertFalse(self.view._can_install("shader"))
        self.assertFalse(self.view._can_install("resourcepack"))
        self.assertIn("Horizon", self.view.mod_search_field.hint_text)
        self.assertIn("Content mods", self.view.header_subtitle.value)
        self.assertFalse(self.view.check_repair_btn.visible)
        self.assertFalse(self.view.client_preference_row.visible)
        with patch.object(self.core, "run_file_picker") as picker:
            self.view.open_local_mod_picker(None)
        self.assertEqual(picker.call_args.kwargs["allowed_extensions"], ["hmod"])
        self.assertEqual(self.view.picker_target, ("mod", "26.3", "rust", INSTANCE))
        self.drop.value = "java-instance"; self.state["mod_loader"] = "rust"
        self.assertFalse(self.view._can_install())

    def test_paging_fetches_horizon_once_and_restores_the_same_cached_rows(self):
        calls = []
        def search(_query, **kwargs):
            calls.append(kwargs)
            return [dict(self.hit, project_id=f"mod_{i}", slug=f"mod_{i}", title=f"Mod {i}")
                    for i in range(kwargs["offset"], min(30, kwargs["offset"] + kwargs["limit"]))]
        self.core.search_mods = search
        self.view.load_recommended_mods()
        self.assertEqual(len(self.queued.jobs), 1)
        self.drain()
        rows = tuple(self.view.browse_results_view.controls)
        self.assertEqual(len(rows), 24)
        self.assertEqual((calls[0]["source"], calls[0]["loader"], calls[0]["mc_version"]), ("horizon", "rust", "26.3"))
        self.view._browse_page_next()
        self.drain()
        self.assertEqual(len(self.view.browse_results_view.controls), 6)
        self.view._browse_page_prev()
        self.assertEqual(tuple(self.view.browse_results_view.controls), rows)
        self.assertEqual([(c["limit"], c["offset"]) for c in calls], [(24, 0), (24, 24)])
        self.assertEqual(self.queued.jobs, [])
        self.assertEqual(self.page.update_calls, 0)

    def test_a_stale_rust_fetch_caches_without_painting_the_java_instance(self):
        calls = []
        self.core.search_mods = lambda _q, **k: calls.append(k) or [self.hit]
        self.core.get_recommended_mods = lambda **_: []
        self.view.load_recommended_mods()
        rust_token = self.view.browse_state["token"]
        self.drop.value = "java-instance"
        self.view.load_recommended_mods()
        self.queued.jobs.pop(0)()
        self.assertEqual(calls[0]["source"], "horizon")
        self.assertEqual(self.view.browse_sessions[rust_token[1]]["pages"][0][0]["source"], "horizon")
        self.assertNotEqual(self.view.browse_state["token"], rust_token)
        self.assertNotIn("Demo", [c.value for c in self.fz.walk(self.view.browse_results_view) if isinstance(c, self.ft.Text)])
        self.drain()

    def test_browse_install_keeps_source_release_and_captured_rust_target(self):
        calls = []
        self.core.get_mod_download = lambda *a, **k: dict(filename="demo.hmod", url="offline", file_id="2.0")
        self.core.install_mod_with_dependencies = lambda *a, **k: calls.append(k) or {"installed": ["demo.hmod"], "failed": []}
        row = self.view.build_browse_row(self.hit)
        row.content.controls[-1].on_click(None)
        self.assertEqual(len(self.queued.jobs), 1)
        self.drop.value = "java-instance"
        with patch("ui.mods_tab.check_content", side_effect=AssertionError("Java check ran for Rust")):
            self.drain()
        self.assertEqual((calls[0]["version_id"], calls[0]["loader"], calls[0]["mc_version"],
                          calls[0]["source"], calls[0]["file_id"]), (INSTANCE, "rust", "26.3", "horizon", "2.0"))

    def test_hidden_toggle_and_removal_update_the_cached_rust_inventory(self):
        from cubeon import thread_safe_ui
        self.items[:] = [dict(filename="demo.hmod", display_name="Demo", enabled=True, size_kb=1,
                             mod_id="demo", source="horizon", slug="demo", project_id="demo", file_id="1.0",
                             icon_url="https://horizon-rust.github.io/horizon-mods/icons/demo.png")]
        java_items = [dict(filename="java.jar", display_name="Java mod", enabled=True, size_kb=1)]
        self.core.list_mods = lambda *a, **k: [dict(m) for m in
                                              (self.items if k["version_id"] == INSTANCE else java_items)]
        calls = []

        def change(name, *args, **kwargs):
            calls.append((name, args, kwargs))
            if name == "toggle":
                self.items[0]["enabled"] = False
            else:
                self.items.clear()

        self.core.toggle_mod = lambda *a, **k: change("toggle", *a, **k)
        self.core.delete_mod = lambda *a, **k: change("remove", *a, **k)
        self.view.active_view["value"] = "installed"
        with patch.object(self.view, "auto_check"):
            self.view.refresh_mods_list()
            rust_target = self.view._installed_target()
            self.assertIn("horizon:demo", self.view.installed_slugs())
            for name in ("toggle", "remove"):
                with self.subTest(action=name):
                    row = self.view.mods_list_view.controls[0]
                    if name == "toggle":
                        row.content.controls[2].value = False
                        row.content.controls[2].on_change(None)
                    else:
                        row.content.controls[-1].on_click(None)
                    self.assertEqual(len(self.queued.jobs), 1)
                    self.drop.value = "java-instance"
                    self.view.refresh_mods_list()
                    java_target = self.view._installed_target()
                    java_snapshot = self.view._cached_installed()
                    java_rows = tuple(self.view.mods_list_view.controls)
                    self.view._set_installed_status("Java instance status")
                    self.view.refresh_mods_list(background=True, force=True)
                    self.assertEqual(self.view._installed_pending_target, java_target)
                    with patch.object(self.view.installed_refresh, "invalidate") as invalidate, \
                            patch.object(thread_safe_ui, "refresh") as repaint:
                        self.queued.jobs.pop(0)()
                        invalidate.assert_not_called()
                        repaint.assert_not_called()
                    self.assertEqual(self.view.installed_status.value, "Java instance status")
                    self.assertIs(self.view._cached_installed(), java_snapshot)
                    self.assertEqual(tuple(self.view.mods_list_view.controls), java_rows)
                    self.assertEqual(self.view._installed_pending_target, java_target)
                    expected = [dict(self.items[0])] if self.items else []
                    self.assertEqual(self.view.installed_snapshots[rust_target], expected)
                    self.drain()
                    self.drop.value = INSTANCE
                    with patch.object(self.core, "list_mods", side_effect=AssertionError("Cached return rescanned mods")):
                        self.view.refresh_mods_list(background=True)
                    self.assertEqual(self.queued.jobs, [])
                    self.assertEqual(self.view._cached_installed(), expected)
                    if name == "toggle":
                        self.assertIs(self.view.mods_list_view.controls[0], row)
                        self.assertFalse(row.content.controls[2].value)
                    else:
                        self.assertNotIn("horizon:demo", self.view.installed_slugs())
                        self.assertNotIn(row, self.view.mods_list_view.controls)
        self.assertEqual(calls, [(name, ("26.3", "rust", "demo.hmod"), {"version_id": INSTANCE})
                                 for name in ("toggle", "remove")])

    def test_details_allow_an_update_when_hmod_filename_stays_the_same(self):
        calls = []
        self.items = [dict(filename="demo.hmod", display_name="Demo", enabled=False, size_kb=1,
                           mod_id="demo", source="horizon", slug="demo", project_id="demo", file_id="1.0")]
        def details(ref, **_):
            calls.append(("details", ref))
            return dict(self.hit, description="A content mod", downloads=1)
        def releases(ref, **kwargs):
            calls.append(("releases", ref))
            self.assertEqual(kwargs["loader"], "rust")
            return [dict(filename="demo.hmod", url="offline", file_id=v, version_number=v,
                         compatible=True, game_versions=["26.3"], loaders=["rust"], date_published="2026-11-" + d)
                    for v, d in (("2.0", "21"), ("1.0", "20"))]
        self.core.get_mod_details, self.core.get_mod_versions = details, releases
        installed = []
        self.core.install_mod_with_dependencies = lambda *a, **k: installed.append(k) or {"installed": ["demo.hmod"], "failed": []}
        self.view.open_mod_detail(self.hit)
        self.drain()
        self.assertEqual(calls, [("details", "horizon:demo"), ("releases", "horizon:demo")])
        latest = self.buttons()[0]
        self.assertFalse(latest.disabled)
        tabs = [c for c in self.fz.walk(self.view.detail_host) if getattr(c, "data", None) == "mod-detail-tab-versions"]
        tabs[0].on_click(None)
        controls = self.buttons()
        self.assertEqual([c.disabled for c in controls], [False, False, True])
        latest.on_click(None)
        self.drain()
        self.assertEqual(installed[0]["file_id"], "2.0")
        self.assertEqual(installed[0]["source"], "horizon")
        self.assertEqual([c.disabled for c in self.buttons()], [True, False])
        self.assertIn("You're up to date", [c.value for c in self.fz.walk(self.view.detail_host) if isinstance(c, self.ft.Text)])

    def test_native_mod_details_explain_the_block_and_cannot_start_an_install(self):
        reason = "This native-code mod needs a newer Rust engine."
        blocked = dict(self.hit, compatible=False, facet_compatible=False, compatibility_reason=reason)
        row = self.view.build_browse_row(blocked)
        button = row.content.controls[-1]
        self.assertTrue(button.disabled); self.assertEqual(button.tooltip, reason)
        self.core.get_mod_details = lambda *a, **k: blocked
        self.core.get_mod_versions = lambda *a, **k: [dict(filename="demo.hmod", url="offline", compatible=False,
            compatibility_reason=reason, file_id="1", version_number="1")]
        self.view.open_mod_detail(blocked); self.drain()
        self.assertIn(reason, [c.value for c in self.fz.walk(self.view.detail_host) if isinstance(c, self.ft.Text)])
        tab = next(c for c in self.fz.walk(self.view.detail_host) if getattr(c, "data", None) == "mod-detail-tab-versions")
        tab.on_click(None)
        self.assertTrue(self.buttons()[0].disabled)
        self.buttons()[0].on_click(None)
        self.assertEqual(self.queued.jobs, [])

    def test_local_hmod_import_bypasses_jar_review_and_keeps_its_original_target(self):
        calls = []
        self.core.install_local_mod = lambda *a, **k: calls.append((a, k)) or "demo.hmod"
        with patch("cubeon.local_mods.review_files", side_effect=AssertionError("JAR review ran for Rust")):
            self.view.handle_local_mod_files([SimpleNamespace(path="local.hmod", name="Local")])
            self.drop.value = "java-instance"
            self.view.local_install_status.value = "Java instance status"
            self.drain()
        self.assertEqual(calls, [(("local.hmod", "26.3", "rust"), {"version_id": INSTANCE})])
        self.assertEqual(self.view.local_install_status.value, "Java instance status")
        self.assertFalse(self.view.local_install_busy)


if __name__ == "__main__":
    unittest.main()
