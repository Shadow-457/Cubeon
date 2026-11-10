"""FastClient imports preserve source content and own all rollback paths."""
import json
import hashlib
import os
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest.mock import Mock, patch
import zipfile

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
test_home = _sandbox_home.isolate()
os.environ["CUBEON_GAME_DIR"] = str(Path(test_home) / "game")

from cubeon import instance_import as importer, mod_loaders, modpacks, mods, paths, storage, versions
from ui.instance_import import FastClientImport
from ui.import_section import build_import_section
from app_driver import DriverPage


class FastClientImports(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.catalogue = self.root / "FastClient settings"
        self.catalogue.mkdir()
        self.source = self.root / "custom game" / "profiles" / "26.3-Fabric"
        self.source.mkdir(parents=True)
        self.game = self.root / "cubeon"
        for module in (paths, mods, mod_loaders, versions):
            p = patch.object(module, "MINECRAFT_DIR", str(self.game))
            p.start(); self.addCleanup(p.stop)
        p = patch.object(importer, "catalogue_roots", lambda: [self.catalogue])
        p.start(); self.addCleanup(p.stop)
        storage.initialize()
        self.runtime = Path(storage.runtime_dir(str(self.game))) / "versions"
        self.record = {"id": "26.3-Fabric", "name": "My FastClient", "version": "26.3",
                       "modLoader": "fabric", "loaderVersion": "0.20.1", "memory": 4608,
                       "javaPath": "/private/java", "accountId": "private-account"}
        self.write_catalogue()
        (self.catalogue / "settings.json").write_text(json.dumps({"gameDirectory": str(self.source.parent.parent),
                                                                   "extraJavaArgs": "private-args"}))
        self.put("config/mod.json", '{"enabled":true}')
        self.put("saves/A World/level.dat", "world-data")
        self.put("saves/A World/region/r.0.0.mca", "region-data")
        self.put("options.txt", "gamma:0.5\n")
        self.put("servers.dat", "server-data")
        self.put("shaderpacks/shader.zip", "shader-data")
        self.put("resourcepacks/pack.zip", "pack-data")
        self.put("screenshots/screenshot.png", "pixels")
        self.put("data/player.dat", "mod-data")
        self.put("accounts.json", "secret-auth")
        self.put(".fastclient/cache.json", "private-cache")
        self.put("logs/latest.log", "old-log")
        self.jar("sodium.jar", "sodium")
        self.jar("iris.jar.disabled", "iris")
        self.jar("renamed-hud.jar", "fastclient-hud")
        self.fast_runtime = self.root / "shared runtime"
        self.fast_runtime.mkdir()
        for entry in ("assets", "libraries", "versions"):
            (self.fast_runtime / entry).mkdir()
            (self.source / entry).symlink_to(self.fast_runtime / entry, target_is_directory=True)
        self.install_base("26.3", _root=self.fast_runtime / "versions")
        self.install_loader("fabric", "26.3", loader_version="0.20.1", _root=self.fast_runtime / "versions")
        self.base_install = Mock(side_effect=AssertionError("Importer must not install or download Minecraft"))
        self.loader_install = Mock(side_effect=AssertionError("Importer must not install or download a loader"))
        for module, attr, value in ((versions, "install_version", self.base_install),
                                    (mod_loaders, "install_mod_loader", self.loader_install)):
            p = patch.object(module, attr, value)
            p.start(); self.addCleanup(p.stop)
        for target in ("requests.sessions.Session.request", "socket.create_connection", "cubeon.net.download_to"):
            p = patch(target, side_effect=AssertionError("Import must be offline"))
            p.start(); self.addCleanup(p.stop)

    def write_catalogue(self):
        (self.catalogue / "profiles.json").write_text(json.dumps({"profiles": [self.record]}))

    def put(self, rel, data):
        target = self.source / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(data)

    def jar(self, name, identity):
        target = self.source / "mods" / name
        target.parent.mkdir(exist_ok=True)
        with zipfile.ZipFile(target, "w") as jar:
            jar.writestr("fabric.mod.json", json.dumps({"id": identity, "version": "1.0"}))

    def install_base(self, mc, *_args, **_kwargs):
        directory = _kwargs.get("_root", self.runtime) / mc
        directory.mkdir(parents=True, exist_ok=True)
        if not (directory / f"{mc}.json").exists():
            with zipfile.ZipFile(directory / f"{mc}.jar", "w") as jar:
                jar.writestr("net/minecraft/client/Main.class", b"fixture-only")
            client = (directory / f"{mc}.jar").read_bytes()
            asset = b"local-asset"
            digest = hashlib.sha1(asset).hexdigest()
            obj = self.fast_runtime / "assets/objects" / digest[:2] / digest
            obj.parent.mkdir(parents=True, exist_ok=True); obj.write_bytes(asset)
            index = self.fast_runtime / "assets/indexes/34.json"
            index.parent.mkdir(parents=True, exist_ok=True)
            index.write_text(json.dumps({"objects": {"minecraft/sounds/test.ogg": {"hash": digest, "size": len(asset)}}}))
            (directory / f"{mc}.json").write_text(json.dumps({
                "id": mc, "type": "release", "mainClass": "net.minecraft.client.Main", "libraries": [],
                "minecraftArguments": None, "arguments": {"game": [], "jvm": ["-cp", "${classpath}"]},
                "downloads": {"client": {"size": len(client), "sha1": hashlib.sha1(client).hexdigest()}},
                "assetIndex": {"id": "34", "size": index.stat().st_size, "sha1": hashlib.sha1(index.read_bytes()).hexdigest()}}))

    def install_loader(self, loader, mc, *_args, **kwargs):
        build = kwargs["loader_version"]
        vid = f"{loader}-loader-{build}-{mc}"
        directory = kwargs.get("_root", self.runtime) / vid
        directory.mkdir(parents=True, exist_ok=True)
        coordinate = {"fabric": f"net.fabricmc:fabric-loader:{build}", "quilt": f"org.quiltmc:quilt-loader:{build}",
                      "forge": f"net.minecraftforge:forge:{mc}-{build}", "neoforge": f"net.neoforged:neoforge:{build}"}[loader]
        from minecraft_launcher_lib._helper import get_library_path
        lib = Path(get_library_path(coordinate, str(self.fast_runtime)))
        lib.parent.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(lib, "w") as jar:
            jar.writestr("Loader.class", b"fixture-loader")
        (directory / f"{vid}.json").write_text(json.dumps({"id": vid, "inheritsFrom": mc,
                                                          "mainClass": "fabric.KnotClient",
                                                          "libraries": [{"name": coordinate, "rules": None,
                                                                         "natives": None, "sha1": hashlib.sha1(lib.read_bytes()).hexdigest()}]}))
        (directory / "support.json").write_text('{"runtime":true}')
        return vid

    def plan(self):
        return importer.review(importer.discover()["profiles"][0])

    def snapshot(self, root):
        return {p.relative_to(root).as_posix(): (p.read_bytes(), p.stat().st_mtime_ns)
                for p in root.rglob("*") if p.is_file() and not p.is_symlink()}

    def assert_clean(self):
        self.assertEqual(storage.registry()["instances"], {})
        self.assertFalse(any(p.name.startswith(".fastclient-import-") for p in (self.game / "instances").iterdir()))
        self.assertFalse(any("fastclient-" in p.name for p in self.runtime.iterdir()) if self.runtime.exists() else False)
        self.assertFalse(modpacks.active_pack_installs())
        folders = [p for p in (self.game / "instances").iterdir() if p.is_dir() and p.name != ".runtime"]
        self.assertEqual(folders, [])

    def test_discovery_and_review_match_actual_format(self):
        found = importer.discover()
        self.assertFalse(found["errors"])
        self.assertEqual(found["profiles"][0]["loader_version"], "0.20.1")
        self.assertNotIn("private", json.dumps(found))
        for directory in (self.catalogue, self.source.parent.parent, self.source):
            self.assertEqual(importer.discover(str(directory))["profiles"], found["profiles"])
        plan = self.plan()
        self.assertEqual((plan["mods"], plan["worlds"]), (2, 1))
        self.assertIn("mods/renamed-hud.jar", plan["skipped"])
        self.assertFalse(any(rel.startswith(("assets/", "libraries/", "versions/", ".fastclient/", "logs/"))
                             or rel == "accounts.json" for rel, _info in plan["files"]))

    def test_import_is_launchable_isolated_and_copy_only(self):
        plan = self.plan()
        before = self.snapshot(self.source)
        result = importer.import_review(plan, name="Imported performance")
        vid = result["version_id"]
        game = Path(storage.game_dir(vid))
        for rel, _stamp in plan["files"]:
            self.assertEqual((game / rel).read_bytes(), (self.source / rel).read_bytes(), rel)
        self.assertFalse((game / "mods/renamed-hud.jar").exists())
        self.assertFalse((game / "accounts.json").exists())
        self.assertEqual(self.snapshot(self.source), before)
        self.assertEqual(mods.resolve_profile_dir("26.3", "fabric", vid), str(game / "mods"))
        meta = storage.manifest(vid)
        self.assertEqual(meta["name"], "Imported performance")
        self.assertEqual(meta["loader_version"], "0.20.1")
        self.assertNotIn("private", json.dumps(meta))
        launch = json.loads((self.runtime / vid / f"{vid}.json").read_text())
        self.assertEqual(launch["id"], vid)
        self.assertIn("vanilla-fastclient-runtime", launch["inheritsFrom"])
        self.assertTrue((self.runtime / vid / "support.json").is_file())
        self.loader_install.assert_not_called()
        self.base_install.assert_not_called()
        self.assertNotIn("rules", launch["libraries"][0])
        from minecraft_launcher_lib.command import get_minecraft_command
        command = get_minecraft_command(vid, str(self.runtime.parent),
                                         {"username": "Fixture", "uuid": "0", "token": "0", "executablePath": "java"})
        classpath = command[command.index("-cp") + 1].split(os.pathsep)
        self.assertTrue(all(Path(entry).is_file() for entry in classpath), classpath)
        self.assertFalse(next(v for v in versions.get_installed_versions() if v["id"] == vid).get("incomplete"))

    def test_duplicate_imports_and_existing_instances_stay_separate(self):
        self.install_base("26.3")
        existing = storage.folder_for("26.3", create=True)
        sentinel = Path(storage.game_dir("26.3")) / "options.txt"
        sentinel.write_text("existing settings")
        before = self.snapshot(existing)
        one = importer.import_review(self.plan())["version_id"]
        two = importer.import_review(self.plan())["version_id"]
        self.assertNotEqual(one, two)
        self.assertNotEqual(storage.game_dir(one), storage.game_dir(two))
        self.assertEqual(self.snapshot(existing), before)
        self.assertNotIn("26.3", storage.manifest(one)["built_from"])

    def test_missing_local_asset_never_falls_back_to_download(self):
        file = next(p for p in (self.fast_runtime / "assets/objects").rglob("*") if p.is_file())
        file.unlink()
        with self.assertRaisesRegex(ValueError, "Nothing will be downloaded"):
            self.plan()
        self.base_install.assert_not_called()
        self.loader_install.assert_not_called()
        self.assert_clean()

    def test_unused_overridden_base_library_is_not_required(self):
        path = self.fast_runtime / "versions/26.3/26.3.json"
        data = json.loads(path.read_text())
        data["libraries"] = [{"name": "net.fabricmc:fabric-loader:0.19.0", "rules": None}]
        path.write_text(json.dumps(data))
        result = importer.import_review(self.plan())
        self.assertFalse(next(v for v in versions.get_installed_versions()
                              if v["id"] == result["version_id"]).get("incomplete"))

    def test_existing_runtime_cache_is_reused_and_conflicts_are_preserved(self):
        first = importer.import_review(self.plan())["version_id"]
        cached = self.snapshot(self.runtime.parent / "assets")
        importer.import_review(self.plan())
        self.assertEqual(self.snapshot(self.runtime.parent / "assets"), cached)
        index = self.runtime.parent / "assets/indexes/34.json"
        index.write_text("existing conflicting data")
        registry = storage.registry()
        with self.assertRaisesRegex(ValueError, "different runtime file"):
            importer.import_review(self.plan())
        self.assertEqual(storage.registry(), registry)
        self.assertEqual(index.read_text(), "existing conflicting data")
        self.assertTrue(Path(storage.game_dir(first)).is_dir())

    def test_cancel_during_local_runtime_copy_removes_private_attempt(self):
        event = threading.Event()
        original = importer._copy_runtime_file
        def copying(*args):
            original(*args)
            event.set()
        with patch.object(importer, "_copy_runtime_file", side_effect=copying):
            with self.assertRaises(importer.ImportCancelled):
                importer.import_review(self.plan(), cancel_event=event)
        self.assert_clean()
        self.assertFalse(list(self.game.rglob(".fastclient-copy-*")))

    def test_loader_import_materializes_local_natives_under_launch_id(self):
        native = self.fast_runtime / "versions/26.3/natives/local.so"
        native.parent.mkdir()
        native.write_bytes(b"local-native")
        result = importer.import_review(self.plan())
        self.assertEqual((self.runtime / result["version_id"] / "natives/local.so").read_bytes(), b"local-native")

    def test_vanilla_and_other_exact_loader_builds(self):
        for loader in ("vanilla", "quilt", "forge", "neoforge"):
            with self.subTest(loader=loader):
                self.record["modLoader"] = loader
                self.record["loaderVersion"] = "21.1.2"
                self.write_catalogue()
                if loader != "vanilla":
                    self.install_loader(loader, "26.3", loader_version="21.1.2", _root=self.fast_runtime / "versions")
                result = importer.import_review(self.plan())
                self.assertEqual(storage.manifest(result["version_id"])["loader"], loader)
                self.assertFalse(next(v for v in versions.get_installed_versions()
                                      if v["id"] == result["version_id"]).get("incomplete"))
                if loader != "vanilla":
                    self.assertEqual(storage.manifest(result["version_id"])["loader_version"], "21.1.2")

    def test_changed_files_or_metadata_require_new_review(self):
        for change in (lambda: self.put("config/mod.json", "changed"),
                       lambda: self.put("mods/new.jar", "new"),
                       lambda: (self.source / "options.txt").unlink(),
                       lambda: self.record.update(loaderVersion="0.20.2")):
            plan = self.plan()
            change()
            self.write_catalogue()
            with self.assertRaisesRegex(ValueError, "changed"):
                importer.import_review(plan)
            self.assert_clean()

    def test_symlinks_inside_content_are_rejected(self):
        for rel in ("config/external", "saves/linked"):
            target = self.source / rel
            target.symlink_to(self.catalogue, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "linked game content"):
                self.plan()
            target.unlink()

    def test_malicious_and_missing_version_identities_are_not_imported(self):
        for key, bad in (("id", "../../outside"), ("version", "26.3/evil"),
                         ("id", "CON"), ("loaderVersion", "../../bad"),
                         ("loaderVersion", None), ("modLoader", "unknown")):
            original = self.record[key]
            self.record[key] = bad
            self.write_catalogue()
            found = importer.discover()
            self.assertEqual(found["profiles"], [])
            self.assertTrue(found["errors"])
            self.record[key] = original

    def test_cancel_before_and_during_copy(self):
        event = threading.Event()
        event.set()
        with self.assertRaises(importer.ImportCancelled):
            importer.import_review(self.plan(), cancel_event=event)
        self.assert_clean()
        event.clear()
        def progress(_done, _total, text):
            if text.startswith("Copying"):
                event.set()
        with self.assertRaises(importer.ImportCancelled):
            importer.import_review(self.plan(), cancel_event=event, progress=progress)
        self.assert_clean()

    def test_source_changes_during_copy_roll_back(self):
        changed = False
        def progress(_done, _total, text):
            nonlocal changed
            if text.startswith("Copying") and not changed:
                changed = True
                self.put("options.txt", "edited while copying")
        with self.assertRaisesRegex(ValueError, "changed"):
            importer.import_review(self.plan(), progress=progress)
        self.assert_clean()

    def test_missing_runtime_refuses_download_and_keeps_original(self):
        before = self.snapshot(self.source)
        (self.fast_runtime / "versions/fabric-loader-0.20.1-26.3/fabric-loader-0.20.1-26.3.json").unlink()
        with self.assertRaisesRegex(ValueError, "Nothing will be downloaded"):
            self.plan()
        self.assertEqual(self.snapshot(self.source), before)
        self.assert_clean()

    def test_incomplete_runtime_is_never_registered_as_success(self):
        client = self.fast_runtime / "versions/26.3/26.3.jar"
        raw = client.read_bytes()
        client.write_bytes(raw[:-1] + b"!")
        with self.assertRaisesRegex(ValueError, "checksum"):
            importer.import_review(self.plan())
        self.assert_clean()

    def test_existing_destination_collision_is_never_removed(self):
        existing = storage.folder_for("manual", create=True)
        sentinel = Path(storage.game_dir("manual")) / "options.txt"
        sentinel.write_text("user settings")
        original = storage.folder_for
        def resolving(vid, **kwargs):
            return existing if "-fastclient-" in vid else original(vid, **kwargs)
        with patch.object(storage, "folder_for", side_effect=resolving):
            with self.assertRaisesRegex(RuntimeError, "fresh instance folder"):
                importer.import_review(self.plan())
        self.assertEqual(sentinel.read_text(), "user settings")
        self.assertEqual(set(storage.registry()["instances"]), {"manual"})

    def test_manifest_and_registry_write_failures_remove_new_paths(self):
        original = storage.write_json
        for which in ("instance.json", "storage.json"):
            with self.subTest(which=which):
                failed = False
                def writing(path, data):
                    nonlocal failed
                    if Path(path).name == which and not failed:
                        failed = True
                        raise OSError("simulated disk failure")
                    return original(path, data)
                with patch.object(storage, "write_json", side_effect=writing):
                    with self.assertRaisesRegex(OSError, "simulated disk failure"):
                        importer.import_review(self.plan())
                self.assert_clean()

    def test_failure_after_registration_and_cancel_during_save_roll_back(self):
        real_replace = os.replace
        def replacing(src, dest):
            if ".fastclient-import-" in str(src):
                raise OSError("move failed")
            return real_replace(src, dest)
        with patch.object(importer.os, "replace", side_effect=replacing):
            with self.assertRaisesRegex(OSError, "move failed"):
                importer.import_review(self.plan())
        self.assert_clean()
        event = threading.Event()
        def progress(_done, _total, text):
            if text == "Saving imported instance":
                event.set()
        with self.assertRaises(importer.ImportCancelled):
            importer.import_review(self.plan(), cancel_event=event, progress=progress)
        self.assert_clean()

    def test_active_pair_claim_prevents_competing_import(self):
        modpacks._mark_pack_install("26.3", "other", loader="fabric", exclusive=True)
        try:
            with self.assertRaisesRegex(modpacks.ModpackError, "already installing"):
                importer.import_review(self.plan())
        finally:
            modpacks._unmark_pack_install("26.3", "fabric")
        self.assert_clean()


class QueuedThread:
    queue = []
    def __init__(self, target, **_kwargs):
        self.target = target
    def start(self):
        self.queue.append(self.target)
    @classmethod
    def run(cls):
        cls.queue.pop(0)()


class ImportUI(unittest.TestCase):
    def setUp(self):
        QueuedThread.queue.clear()
        for target, value in (("ui.instance_import.threading.Thread", QueuedThread),
                               ("ui.instance_import.thread_safe_ui.refresh", lambda _c: None)):
            p = patch(target, value); p.start(); self.addCleanup(p.stop)
        self.finished = Mock()
        self.page = DriverPage()
        self.ui = FastClientImport(self.page, finished=self.finished)
        self.profile = {"name": "Example", "directory": "/test/profile", "mc_version": "26.3",
                        "loader": "fabric", "loader_version": "0.20.1"}
        self.plan = {"profile": self.profile, "mods": 8, "worlds": 1, "bytes": 1024, "runtime_bytes": 2048, "skipped": []}

    def review(self):
        with patch.object(importer, "discover", return_value={"profiles": [self.profile], "errors": []}):
            self.ui._scan()
            self.assertEqual(self.ui.phase, "scanning")
            QueuedThread.run()
        with patch.object(importer, "review", return_value=self.plan):
            self.ui.rows.controls[0].on_click(None)
            self.assertEqual(self.ui.phase, "reviewing")
            QueuedThread.run()
        self.assertEqual(self.ui.phase, "review")
        self.assertFalse(self.ui.submit.disabled)

    def test_review_import_refresh_and_reset(self):
        self.review()
        self.ui.name.value = "Custom name"
        result = {"name": "Custom name", "version_id": "new-id"}
        with patch.object(importer, "import_review", return_value=result) as importing:
            self.ui._import()
            self.ui._import()
            self.assertEqual(len(QueuedThread.queue), 1)
            QueuedThread.run()
            self.assertEqual(importing.call_args.kwargs["name"], "Custom name")
        self.assertEqual(self.ui.phase, "done")
        self.finished.assert_called_once_with(result)
        self.ui._reset()
        self.assertEqual(self.ui.phase, "choose")
        self.assertEqual(self.ui.rows.controls, [])

    def test_cancel_waits_for_cleanup_then_allows_retry(self):
        self.review()
        self.ui._import()
        self.ui._reset()
        self.assertEqual(self.ui.phase, "importing")
        self.assertTrue(self.ui.cancel_event.is_set())
        with patch.object(importer, "import_review", side_effect=importer.ImportCancelled("Cancelled")):
            QueuedThread.run()
        self.assertEqual(self.ui.phase, "choose")
        self.assertFalse(self.ui.scan.disabled)
        self.assertFalse(self.ui.rows.disabled)
        self.finished.assert_not_called()

    def test_cleared_scan_cannot_restore_stale_results(self):
        with patch.object(importer, "discover", return_value={"profiles": [self.profile], "errors": []}):
            self.ui._scan()
            self.ui._reset()
            QueuedThread.run()
        self.assertEqual(self.ui.phase, "choose")
        self.assertEqual(self.ui.rows.controls, [])

    def test_settings_contains_inline_importer_and_busy_gate(self):
        from cubeon import theme
        pane = build_import_section(self.page, {}, section_label=theme.section_label,
                                    get_active_target=lambda: (None, None, None),
                                    on_instance_imported=self.finished, **theme.THEME)
        self.assertIn(pane.fastclient_import.view, pane.controls)
        self.assertFalse(hasattr(pane.fastclient_import, "dialog"))
        self.assertEqual(QueuedThread.queue, [])  # No scan while Settings is hidden.
        self.review()
        self.ui.busy_reason = lambda: "Finish the game first."
        self.ui._import()
        self.assertEqual(self.ui.phase, "review")
        self.assertEqual(self.ui.status.value, "Finish the game first.")
        self.assertEqual(QueuedThread.queue, [])


if __name__ == "__main__":
    unittest.main()
