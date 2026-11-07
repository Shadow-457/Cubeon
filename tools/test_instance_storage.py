"""Storage ownership, migration failure/recovery and offline independence."""
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch
import zipfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import paths, storage, mods, content, global_mod_cache, versions, modpacks, instances, perf_mods
from cubeon.atomicio import write_json


def jar(path, ident="sodium"):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1, "id": ident,
                         "name": ident, "version": "1.0", "environment": "client"}))
    return path


class StorageTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="cubeon-storage-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name) / "game"
        self.profiles = Path(self.temp.name) / "profiles"
        overrides = [(paths, "MINECRAFT_DIR", self.root),
                     (paths, "INSTANCES_GAME_DIR", self.root / "instances"),
                     (paths, "ACTIVE_INSTANCE_PATH", self.root / "instances" / "active.json"),
                     (paths, "PROFILES_DIR", self.profiles),
                     (mods, "PROFILES_DIR", self.profiles),
                     (mods, "MODS_DIR", self.root / "mods"),
                     (global_mod_cache, "GLOBAL_MODS_DIR", self.root / "global_mods"),
                     (global_mod_cache, "_HASH_INDEX_PATH", self.root / "global_mods" / ".hash_index.json")]
        overrides += [(module, "MINECRAFT_DIR", self.root) for module in (mods, versions, modpacks)]
        for module, name, value in overrides:
            p = patch.object(module, name, str(value))
            p.start()
            self.addCleanup(p.stop)
        storage._blocked = storage._restart_required = False
        storage._owner = None
        self.addCleanup(setattr, storage, "_restart_required", False)

    def legacy(self, count=2):
        ids = [f"1.21.1-fabric-survival-{n}" for n in range(count)]
        for vid in ids:
            p = self.root / "versions" / vid
            write_json(str(p / f"{vid}.json"), {"id": vid, "inheritsFrom": "1.21.1"})
            mods.write_instance_meta(vid, {"mc_version": "1.21.1", "loader": "fabric", "profile": "shared"})
            game = Path(paths.game_dir_for(vid))
            (game / "options.txt").write_text("maxFps:0\nrenderDistance:4\n")
            save = game / "saves" / "My world"
            save.mkdir()
            (save / "level.dat").write_bytes(b"world-" + vid.encode())
            (game / "unknown-mod-folder").mkdir()
            (game / "unknown-mod-folder" / "custom.bin").write_bytes(b"keep me")
        source = jar(self.root / "global_mods" / "sodium.jar")
        profile = self.profiles / "shared"
        profile.mkdir(parents=True, exist_ok=True)
        try:
            (profile / "sodium.jar").symlink_to(source)
        except OSError:
            shutil.copyfile(source, profile / "sodium.jar")
        mods.record_mod_source(str(profile), "sodium.jar", "sodium")
        jar(profile / "disabled.jar.disabled", "disabled")
        packs = profile / "resourcepacks"
        packs.mkdir()
        (packs / "manual-pack.zip").write_bytes(b"pack-bytes")
        for folder in ("assets", "libraries"):
            (self.root / folder).mkdir()
            (self.root / folder / "payload").write_bytes(folder.encode())
        storage.initialize()
        return ids, source

    def restart(self):
        storage._restart_required = False

    def test_deleted_instance_metadata_is_visible_and_other_instances_still_work(self):
        from cubeon import storage_layout
        storage.initialize()
        damaged, healthy = "fabric-loader-0.20.1-1.21.11", "1.20.1"
        runtime = Path(storage.runtime_dir())
        for vid in (damaged, healthy):
            write_json(str(runtime / "versions" / vid / (vid + ".json")),
                       {"id": vid, "type": "release"})
            jar(runtime / "versions" / vid / (vid + ".jar"), "client")
            storage.folder_for(vid, create=True)
        damaged_folder = storage.folder_for(damaged)
        metadata = damaged_folder / "instance.json"
        original = metadata.read_bytes()
        healthy_game = storage.game_dir(healthy)
        healthy_meta = storage.manifest(healthy)
        registry_before = storage.registry_path().read_bytes()
        versions._scan_cache = None
        self.assertFalse(any(v.get("incomplete") for v in versions.get_installed_versions()))

        for invalid in (None, b"{", b"[]", b'{"layout":2,"version_id":"wrong"}'):
            with self.subTest(invalid=invalid):
                metadata.unlink()
                if invalid is not None:
                    metadata.write_bytes(invalid)
                storage.initialize()
                entries = {v["id"]: v for v in versions.get_installed_versions()}
                broken = entries[damaged]
                self.assertTrue(broken["incomplete"])
                self.assertTrue(broken["storage_issue"])
                self.assertIn("Restore it before playing", broken["issue"])
                self.assertFalse(entries[healthy].get("incomplete"))
                self.assertTrue(instances.describe(damaged, broken)["incomplete"])
                self.assertFalse(storage_layout.needed())
                with self.assertRaises(storage.InstanceMetadataError):
                    storage_layout.plan()
                with self.assertRaises(storage.InstanceMetadataError):
                    paths.game_dir_for(damaged)
                with self.assertRaises(storage.InstanceMetadataError):
                    mods.resolve_profile_dir("1.21.11", "fabric", damaged)
                with self.assertRaises(storage.InstanceMetadataError):
                    storage.instance_profiles()
                self.assertEqual([p[0] for p in storage.instance_profiles(skip_damaged=True)], [healthy])
                self.assertEqual(mods.profile_dir_for_key(healthy_meta["profile"]), str(Path(healthy_game) / "mods"))
                self.assertEqual(storage.game_dir(healthy), healthy_game)
                paths.set_active_game_dir(healthy_game)
                self.assertEqual(paths.active_game_dir(), healthy_game)
                paths.set_active_game_dir(str(damaged_folder / "minecraft"))
                with self.assertRaises(storage.InstanceMetadataError):
                    paths.active_game_dir()
                self.assertEqual(storage.registry_path().read_bytes(), registry_before)
                self.assertEqual(metadata.read_bytes() if metadata.exists() else None, invalid)
                metadata.write_bytes(original)
                self.assertFalse(any(v.get("incomplete") for v in versions.get_installed_versions()))

        metadata.unlink()
        shutil.rmtree(runtime / "versions" / damaged)
        entries = {v["id"]: v for v in versions.get_installed_versions()}
        self.assertTrue(entries[damaged]["incomplete"])
        self.assertFalse(entries[healthy].get("incomplete"))
        shutil.rmtree(runtime / "versions")
        self.assertEqual({v["id"] for v in versions.get_installed_versions()}, {damaged, healthy})

    def test_new_instances_are_independent_offline(self):
        storage.initialize()
        self.assertEqual(storage.runtime_dir(), str(self.root / "instances/.runtime"))
        a = Path(mods.get_profile_dir("1.21.1", "fabric", "instance-a"))
        b = Path(mods.get_profile_dir("1.21.1", "fabric", "instance-b"))
        source = jar(Path(self.temp.name) / "sodium.jar")
        with patch("os.symlink", side_effect=OSError("not allowed")), patch("os.link", side_effect=OSError("not allowed")):
            global_mod_cache.put_file(str(source), str(a / source.name))
            global_mod_cache.put_file(str(source), str(b / source.name))
        self.assertFalse((a / source.name).is_symlink())
        self.assertNotEqual((a / source.name).stat().st_ino, (b / source.name).stat().st_ino)
        shutil.rmtree(self.root / "cache")
        (a / source.name).unlink()
        storage.reconcile_mod_removals(str(a), "fabric")
        self.assertIn("sodium", perf_mods._read_removals(str(a)))
        self.assertTrue((b / source.name).is_file())
        jar(a / "manual.jar", "manual")
        mods.sync_mods_to_game("1.21.1", "fabric", "instance-a")
        content.sync_content_to_game("1.21.1", "fabric", "instance-a")
        self.assertEqual([m["filename"] for m in mods.list_mods("1.21.1", "fabric", "instance-a")], ["manual.jar"])
        self.assertFalse((self.root / "mods").exists())
        self.assertFalse((self.root / "global_mods").exists())
        self.assertEqual(content.profile_dir("resourcepack", "1.21.1", "fabric", "instance-a"), str(a.parent / "resourcepacks"))

    def test_migration_preserves_originals_and_player_data(self):
        ids, source = self.legacy()
        original = source.read_bytes()
        before = [Path(paths.game_dir_for(vid, create=False)) for vid in ids]
        plan = storage.inventory()
        storage.migrate(plan)
        self.assertTrue(storage.restart_required())
        with self.assertRaises(RuntimeError):
            mods.get_profile_dir("1.21.1", "fabric", ids[0])
        self.restart()
        for old, vid in zip(before, ids):
            new = Path(paths.game_dir_for(vid))
            self.assertEqual(new, old)
            self.assertEqual((new / "saves" / "My world" / "level.dat").read_bytes(), (old / "saves" / "My world" / "level.dat").read_bytes())
            self.assertEqual((new / "options.txt").read_bytes(), (old / "options.txt").read_bytes())
            self.assertEqual((new / "unknown-mod-folder" / "custom.bin").read_bytes(), b"keep me")
            self.assertTrue((new / "mods" / "disabled.jar.disabled").is_file())
            self.assertFalse((new / "mods" / "sodium.jar").is_symlink())
            self.assertTrue((new / ".cubeon" / "mods" / "sodium.jar.cubeon.json").is_file())
            self.assertFalse((new / "mods" / "sodium.jar.cubeon.json").exists())
            self.assertEqual((new / "resourcepacks" / "manual-pack.zip").read_bytes(), b"pack-bytes")
        backup = self.root / storage.registry()["content_backup"]
        self.assertFalse(source.exists())
        self.assertEqual((backup / "global_mods" / source.name).read_bytes(), original)
        self.assertTrue((self.root / "versions" / ids[0]).is_dir())
        self.assertFalse((self.root / "runtime" / "versions" / ids[0]).exists())
        self.assertEqual(storage.runtime_dir(), str(self.root))
        world = Path(storage.game_dir(ids[0])) / "saves" / "My world" / "level.dat"
        world.write_bytes(b"newer player progress")
        storage.migrate(storage.inventory())
        self.assertEqual(world.read_bytes(), b"newer player progress")

    def test_pause_before_switch_is_resumable(self):
        ids, _ = self.legacy(1)
        plan = storage.inventory()
        cancel = threading.Event()
        cancel.set()
        with self.assertRaises(InterruptedError):
            storage.migrate(plan, cancel=cancel)
        self.assertIsNone(storage.manifest(ids[0]))
        self.assertFalse(storage.restart_required())
        storage.migrate(storage.inventory())
        self.assertIsNotNone(storage.manifest(ids[0]))

    def test_partial_success_preserves_later_progress_on_resume(self):
        ids, _ = self.legacy()
        copy = storage._copy_verified
        def fail_second(entries, target, *args):
            if ids[1] in str(target):
                raise OSError("disk disconnected")
            return copy(entries, target, *args)
        with patch.object(storage, "_copy_verified", side_effect=fail_second):
            with self.assertRaises(OSError):
                storage.migrate(storage.inventory())
        self.assertIsNotNone(storage.manifest(ids[0]))
        self.assertIsNone(storage.manifest(ids[1]))
        self.assertTrue(storage.restart_required())
        self.restart()
        world = Path(storage.game_dir(ids[0])) / "saves" / "My world" / "level.dat"
        world.write_bytes(b"played after partial migration")
        storage.migrate(storage.inventory())
        self.assertEqual(world.read_bytes(), b"played after partial migration")
        self.assertFalse(storage.pending_versions())

    def test_disk_full_does_not_switch_and_runtime_is_untouched(self):
        ids, _ = self.legacy(1)
        with patch.object(paths, "ensure_disk_space", side_effect=RuntimeError("Not enough disk space")):
            with self.assertRaisesRegex(RuntimeError, "Not enough"):
                storage.migrate(storage.inventory())
        self.assertIsNone(storage.manifest(ids[0]))
        (self.root / "runtime" / "versions").mkdir(parents=True)
        (self.root / "runtime" / "versions" / "precious-file").write_text("keep")
        storage.migrate(storage.inventory())
        self.assertEqual((self.root / "runtime" / "versions" / "precious-file").read_text(), "keep")
        self.assertIsNotNone(storage.manifest(ids[0]))

    def test_source_changes_abort_before_switch(self):
        ids, _ = self.legacy(1)
        plan = storage.inventory()
        jar(self.profiles / "shared" / "added.jar", "added")
        with self.assertRaisesRegex(RuntimeError, "Folder changed"):
            storage.migrate(plan)
        self.assertIsNone(storage.manifest(ids[0]))

    def test_external_link_and_corrupt_manifest_fail_closed(self):
        ids, _ = self.legacy(1)
        outside = Path(self.temp.name) / "outside.jar"
        outside.write_bytes(b"external")
        bad = self.profiles / "shared" / "external.jar"
        try:
            bad.symlink_to(outside)
        except OSError:
            self.skipTest("This filesystem cannot create a legacy link fixture")
        with self.assertRaisesRegex(ValueError, "Review this link"):
            storage.inventory()
        bad.unlink()
        storage.migrate(storage.inventory())
        self.restart()
        folder = storage.folder_for(ids[0])
        (folder / "instance.json").write_text("{broken")
        with self.assertRaises(RuntimeError):
            paths.game_dir_for(ids[0])

    def test_deletion_archives_only_selected_instance(self):
        ids, _ = self.legacy()
        storage.migrate(storage.inventory())
        self.restart()
        data = storage.manifest(ids[0])
        sibling = Path(storage.game_dir(ids[1]))
        storage.archive_instance(ids[0])
        self.assertTrue(sibling.is_dir())
        self.assertTrue((self.root / "backups" / "deleted-instances" / data["id"] / "saves" / "My world" / "level.dat").is_file())

    def test_local_import_before_first_launch_uses_same_directory(self):
        from cubeon import local_mods
        storage.initialize()
        source = jar(Path(self.temp.name) / "manual.jar", "manual")
        expected = mods.resolve_profile_dir("1.21.1", "fabric", "new-instance")
        self.assertFalse(Path(expected).exists())
        review = local_mods.review_files([str(source)], "1.21.1", "fabric", version_id="new-instance")
        entry = review["entries"][0]
        local_mods.import_entry(entry, "1.21.1", "fabric", version_id="new-instance")
        self.assertTrue((Path(expected) / "manual.jar").is_file())
        self.assertEqual(expected, mods.resolve_profile_dir("1.21.1", "fabric", "new-instance"))

    def test_popup_later_and_complete_restart(self):
        from ui.storage_migration import StorageMigration
        from types import SimpleNamespace
        ids, _ = self.legacy(1)
        (self.root / "saves" / "leftover world").mkdir(parents=True, exist_ok=True)
        (self.root / "options.txt").write_text("keep shared settings")
        class InlineThread:
            def __init__(self, target, **kwargs):
                self.target = target
            def start(self):
                self.target()
        locked, restarted = [], []
        with patch("ui.storage_migration.threading.Thread", InlineThread), \
             patch("ui.storage_migration.dialogs.open_dialog"), \
             patch("ui.storage_migration.dialogs.close_dialog") as closed, \
             patch("ui.storage_migration.thread_safe_ui.refresh"):
            prompt = StorageMigration(SimpleNamespace(), busy=lambda: False,
                                      restart=lambda _: restarted.append(True),
                                      exit_launcher=lambda _: None, set_locked=locked.append).show()
            self.assertFalse(prompt.start.disabled)
            self.assertFalse(hasattr(prompt, "owner"))
            self.assertIn("Worlds and settings stay with their own instance", prompt.status.value)
            prompt._later()
            closed.assert_called_once()
            self.assertIsNone(storage.manifest(ids[0]))
            prompt.show()
            prompt._start()
            self.assertEqual(prompt.phase, "restart")
            self.assertEqual(locked, [True])
            self.assertTrue(prompt.restart_button.visible)
            prompt.restart_button.on_click(None)
            self.assertEqual(restarted, [True])

    def test_backups_include_new_worlds_mods_and_metadata(self):
        from cubeon import backup
        ids, _ = self.legacy(1)
        storage.migrate(storage.inventory())
        self.restart()
        with patch.object(backup, "MINECRAFT_DIR", str(self.root)):
            result = backup.create_backup(include_saves=True, dest_dir=str(Path(self.temp.name) / "backups"))
        self.assertTrue(result.ok, result.message)
        prefix = "instances/" + storage.manifest(ids[0])["id"]
        with zipfile.ZipFile(result.path) as archive:
            self.assertIn(prefix + "/saves/My world/level.dat", archive.namelist())
            self.assertIn(prefix + "/mods/sodium.jar", archive.namelist())
            self.assertIn(prefix + "/instance.json", archive.namelist())
            self.assertEqual(len(archive.namelist()), len(set(archive.namelist())))

    def test_modpack_install_update_and_rollback_in_new_layout(self):
        from cubeon import csl, cubeonfriends
        self.legacy(1)
        blob = jar(Path(self.temp.name) / "pack.jar", "packmod").read_bytes()
        def base(vid, *args, **kwargs):
            write_json(str(self.root / "versions" / vid / (vid + ".json")), {"id": vid})
        def loader(kind, mc, *args, loader_version=None, **kwargs):
            vid = f"fabric-loader-{loader_version}-{mc}"
            write_json(str(self.root / "versions" / vid / (vid + ".json")), {"id": vid, "inheritsFrom": mc})
            return vid
        def download(destination, *args, **kwargs):
            Path(destination).write_bytes(blob)
        pack = Path(self.temp.name) / "pack.mrpack"
        def make_pack(version):
            with zipfile.ZipFile(pack, "w") as archive:
                archive.writestr("modrinth.index.json", json.dumps({
                    "formatVersion": 1, "game": "minecraft", "versionId": version, "name": "Storage test pack",
                    "dependencies": {"minecraft": "1.21.1", "fabric-loader": "0.16.1"},
                    "files": [{"path": f"mods/pack-{version}.jar", "fileSize": len(blob),
                               "downloads": [f"https://cdn.modrinth.com/data/storage/versions/{version}/pack.jar"]}]}))
                archive.writestr("overrides/config/pack.txt", version)
        with patch.object(modpacks, "install_version", side_effect=base), \
             patch.object(modpacks, "install_mod_loader", side_effect=loader), \
             patch.object(modpacks, "_stream_download", side_effect=download), \
             patch.object(csl, "set_enabled"), patch.object(csl, "ensure_ready"), \
             patch.object(cubeonfriends, "ensure_installed", return_value=True):
            make_pack("1")
            result = modpacks.install_modpack_from_file(str(pack))
            vid = result["version_id"]
            game = Path(storage.game_dir(vid))
            original_meta = storage.manifest(vid)
            self.assertTrue((game / "mods" / "pack-1.jar").is_file())
            self.assertEqual((game / "config" / "pack.txt").read_text(), "1")
            self.assertTrue(any(p["version_id"] == vid for p in modpacks.list_installed_modpacks()))
            make_pack("2")
            with patch.object(modpacks, "_stream_download", side_effect=OSError("offline")):
                with self.assertRaises(Exception):
                    modpacks.install_modpack_from_file(str(pack))
            self.assertEqual(storage.manifest(vid), original_meta)
            self.assertTrue((game / "mods" / "pack-1.jar").is_file())
            self.assertEqual((game / "config" / "pack.txt").read_text(), "1")
            modpacks.install_modpack_from_file(str(pack))
            self.assertTrue((game / "mods" / "pack-2.jar").is_file())
            self.assertEqual((game / "config" / "pack.txt").read_text(), "2")

    def test_skin_and_screenshot_paths_follow_instances(self):
        from cubeon import screenshot_gallery
        from PIL import Image
        storage.initialize()
        first = Path(paths.game_dir_for("first"))
        second = Path(paths.game_dir_for("second"))
        paths.set_active_game_dir(str(first))
        with patch.object(paths, "CSL_DIR", str(self.root / "CustomSkinLoader")):
            target = paths.instance_csl_path(str(self.root / "CustomSkinLoader" / "LocalSkin" / "skins"))
        self.assertEqual(target, str(first / "CustomSkinLoader" / "LocalSkin" / "skins"))
        for directory in (first, second):
            Image.new("RGB", (3, 3)).save(directory / "screenshots" / "same.png")
        with patch.object(screenshot_gallery, "SCREENSHOTS_DIR", str(self.root / "screenshots")):
            items = screenshot_gallery.list_screenshots()
            self.assertEqual(len(items), 2)
            selected = next(row for row in items if storage.manifest("first")["id"] in row["filename"])
            screenshot_gallery.delete_screenshot(selected["filename"])
        self.assertFalse((first / "screenshots" / "same.png").exists())
        self.assertTrue((second / "screenshots" / "same.png").exists())

    def test_legacy_java_runtime_is_preserved(self):
        ids, _ = self.legacy(1)
        java = self.root / "runtime" / "old-java" / "bin" / "java"
        java.parent.mkdir(parents=True)
        java.write_bytes(b"old runtime")
        storage.migrate(storage.inventory())
        self.assertEqual(java.read_bytes(), b"old runtime")
        self.assertFalse((self.root / "runtime" / "versions" / ids[0]).exists())
        self.assertEqual(storage.runtime_dir(), str(self.root))

    def test_prompt_inventory_does_not_hash_player_files(self):
        self.legacy(1)
        with patch.object(storage, "_digest", side_effect=AssertionError("eager file hashing")):
            plan = storage.inventory(hash_files=False)
        self.assertFalse(plan["hashed"])
        self.assertGreater(plan["bytes"], 0)
        storage.migrate(plan)
        self.assertTrue(storage.restart_required())

    def test_legacy_downloads_also_survive_cache_deletion(self):
        ids, _ = self.legacy(1)
        source = jar(Path(self.temp.name) / "new.jar", "newmod")
        profile = Path(mods.get_profile_dir("1.21.1", "fabric", ids[0]))
        global_mod_cache.put_file(str(source), str(profile / "new.jar"))
        self.assertFalse((profile / "new.jar").is_symlink())
        shutil.rmtree(self.root / "cache")
        self.assertEqual((profile / "new.jar").read_bytes(), source.read_bytes())

    def test_missing_registry_never_reactivates_legacy_worlds(self):
        ids, _ = self.legacy(1)
        storage.migrate(storage.inventory())
        self.restart()
        game = Path(storage.game_dir(ids[0]))
        storage.registry_path().unlink()
        with self.assertRaisesRegex(RuntimeError, "storage index is missing"):
            paths.game_dir_for(ids[0])
        self.assertTrue((game / "saves" / "My world" / "level.dat").is_file())

    def test_only_content_is_scanned_or_changed(self):
        ids, _ = self.legacy()
        games = [Path(paths.game_dir_for(vid, create=False)) for vid in ids]
        protected = []
        for index, game in enumerate([self.root, *games]):
            for relative in ("saves/other/level.dat", "config/sodium-options.json", "options.txt",
                             "servers.dat", "optionsof.txt", "unknown-mod-folder/data.bin"):
                path = game / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(f"original {index} {relative}".encode())
                protected.append(path)
        protected += [self.root / "assets/payload", self.root / "libraries/payload"]
        snapshots = {path: (path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns) for path in protected}
        links = {game / name: os.readlink(game / name) for game in games
                 for name in ("screenshots", "crash-reports", "CustomSkinLoader") if (game / name).is_symlink()}
        # An unrelated external link must not even be inspected by migration.
        (games[0] / "unrelated-link").symlink_to(Path(self.temp.name) / "missing-world-backup")
        digest = storage._digest
        def content_hash(path, *args):
            self.assertNotIn(Path(path), protected, "Migration read unrelated player/runtime data")
            return digest(path, *args)
        with patch.object(storage, "_digest", side_effect=content_hash):
            plan = storage.inventory()
            self.assertNotIn("runtime", plan)
            self.assertNotIn("shared_owner", plan)
            for item in plan["instances"]:
                self.assertTrue(all(e["relative"].split("/")[0] in (*storage.CONTENT_DIRS, ".cubeon")
                                    for e in item["files"]))
            storage.migrate(plan)
        self.restart()
        for vid, game in zip(ids, games):
            self.assertEqual(Path(paths.game_dir_for(vid)), game)
            self.assertEqual(mods.profile_dir_for_key(storage.manifest(vid)["profile"]), str(game / "mods"))
            for name in storage.CONTENT_DIRS:
                self.assertTrue((game / name).is_dir())
                self.assertFalse((game / name).is_symlink())
            mods.sync_mods_to_game("1.21.1", "fabric", vid)
            content.sync_content_to_game("1.21.1", "fabric", vid)
        self.assertFalse(storage.needs_migration())
        for path, snapshot in snapshots.items():
            self.assertEqual((path.read_bytes(), path.stat().st_ino, path.stat().st_mtime_ns), snapshot)
        for path, target in links.items():
            self.assertEqual(os.readlink(path), target)
        self.assertFalse((self.root / "runtime").exists())

    def test_failed_switch_restores_original_content(self):
        ids, _ = self.legacy(1)
        game = Path(paths.game_dir_for(ids[0], create=False))
        targets = {name: (game / name).resolve() for name in storage.CONTENT_DIRS}
        replace = os.replace
        def locked_shader(source, destination):
            if Path(destination) == game / "shaderpacks" and ".content-migration" in Path(source).parts:
                raise PermissionError("shader folder locked")
            return replace(source, destination)
        with patch.object(storage.os, "replace", side_effect=locked_shader):
            with self.assertRaisesRegex(PermissionError, "locked"):
                storage.migrate(storage.inventory())
        self.assertIsNone(storage.manifest(ids[0]))
        self.assertFalse(storage.restart_required())
        for name, target in targets.items():
            self.assertEqual((game / name).resolve(), target)
        storage.migrate(storage.inventory())
        self.assertIsNotNone(storage.manifest(ids[0]))

    def test_startup_recovers_killed_switch_before_legacy_launch(self):
        ids, _ = self.legacy(1)
        game = Path(paths.game_dir_for(ids[0], create=False))
        original = {name: (game / name).resolve() for name in storage.CONTENT_DIRS}
        replace = os.replace
        def power_loss(source, destination):
            if Path(destination) == game / "resourcepacks" and ".content-migration" in Path(source).parts:
                raise SystemExit("power loss during switch")
            return replace(source, destination)
        with patch.object(storage.os, "replace", side_effect=power_loss), \
             patch.object(storage, "_rollback_switch", side_effect=SystemExit("process gone")):
            with self.assertRaises(SystemExit):
                storage.migrate(storage.inventory())
        self.assertTrue(storage.restart_required())
        self.assertIn("switch", storage._read(self.root / "instances/migration.json"))
        self.restart()
        storage.initialize()
        self.assertIsNone(storage.manifest(ids[0]))
        for name, target in original.items():
            self.assertEqual((game / name).resolve(), target)
        storage.migrate(storage.inventory())
        self.assertIsNotNone(storage.manifest(ids[0]))

    def test_recovery_after_registry_commit_keeps_later_changes(self):
        ids, _ = self.legacy(1)
        write = storage.write_json
        journal_path = str(self.root / "instances/migration.json")
        def fail_final_journal(path, data, *args, **kwargs):
            if str(path) == journal_path and storage.manifest(ids[0]) is not None:
                raise OSError("journal write interrupted")
            return write(path, data, *args, **kwargs)
        with patch.object(storage, "write_json", side_effect=fail_final_journal):
            with self.assertRaisesRegex(OSError, "interrupted"):
                storage.migrate(storage.inventory())
        self.restart()
        game = Path(storage.game_dir(ids[0]))
        jar(game / "mods" / "added-after.jar", "later")
        world = game / "saves/My world/level.dat"
        world.write_bytes(b"latest progress")
        storage.initialize()
        self.assertTrue((game / "mods/added-after.jar").is_file())
        self.assertEqual(world.read_bytes(), b"latest progress")
        self.assertTrue(storage.cleanup_pending())
        storage.migrate(storage.inventory())
        self.assertFalse(storage.needs_migration())

    def test_old_plans_and_journals_cannot_migrate_worlds_or_runtime(self):
        ids, _ = self.legacy(1)
        old_stage = self.root / "instances/.migration/old-stage/minecraft/saves/world/level.dat"
        old_stage.parent.mkdir(parents=True)
        old_stage.write_bytes(b"old uncommitted copy")
        write_json(str(self.root / "instances/migration.json"),
                   {"schema": 1, "pending": {ids[0]: "old-stage"}, "committed": []})
        old_plan = {"instances": [], "runtime": [{"source": "must not be read"}], "shared_owner": ids[0], "bytes": 0}
        storage.migrate(old_plan)
        self.assertEqual(old_stage.read_bytes(), b"old uncommitted copy")
        self.assertEqual(storage.manifest(ids[0])["game_subdir"], ".")
        self.assertFalse((self.root / "runtime").exists())

    def test_prior_nested_instances_keep_their_existing_game_paths(self):
        ids, _ = self.legacy(1)
        nested = Path(paths.game_dir_for("already-migrated"))
        world = nested / "saves/latest/level.dat"
        world.parent.mkdir()
        world.write_bytes(b"already migrated progress")
        snapshot = storage.manifest("already-migrated")
        storage.migrate(storage.inventory())
        self.restart()
        self.assertEqual(Path(paths.game_dir_for("already-migrated")), nested)
        self.assertEqual(storage.manifest("already-migrated"), snapshot)
        self.assertEqual(world.read_bytes(), b"already migrated progress")
        self.assertEqual(storage.manifest(ids[0])["game_subdir"], ".")

    def test_shared_screenshots_are_not_duplicated_after_content_migration(self):
        from cubeon import screenshot_gallery
        from PIL import Image
        self.legacy(2)
        screenshot = self.root / "screenshots" / "shared.png"
        Image.new("RGB", (3, 3)).save(screenshot)
        storage.migrate(storage.inventory())
        self.restart()
        with patch.object(screenshot_gallery, "SCREENSHOTS_DIR", str(screenshot.parent)):
            self.assertEqual(len(screenshot_gallery.list_screenshots()), 1)

    def test_real_local_content_is_preserved_and_conflicts_do_not_switch(self):
        ids, _ = self.legacy(1)
        game = Path(paths.game_dir_for(ids[0], create=False))
        (game / "mods").unlink()
        jar(game / "mods/local.jar", "local")
        jar(game / "mods/sodium.jar", "different-mod")
        with self.assertRaisesRegex(ValueError, "Conflicting files"):
            storage.inventory()
        (game / "mods/sodium.jar").unlink()
        shaders = self.profiles / "shared/shaderpacks"
        shaders.mkdir()
        (shaders / "test.zip").write_bytes(b"shaders")
        storage.migrate(storage.inventory())
        self.restart()
        self.assertTrue((game / "mods/local.jar").is_file())
        self.assertTrue((game / "mods/sodium.jar").is_file())
        self.assertEqual((game / "shaderpacks/test.zip").read_bytes(), b"shaders")
        backups = list((self.root / "backups/legacy-content").glob("*/mods/local.jar"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), (game / "mods/local.jar").read_bytes())

    def test_registry_write_failure_rolls_back_every_folder(self):
        ids, _ = self.legacy(1)
        game = Path(paths.game_dir_for(ids[0], create=False))
        original = {name: (game / name).resolve() for name in storage.CONTENT_DIRS}
        write = storage.write_json
        def fail_registry(path, data, *args, **kwargs):
            if Path(path) == storage.registry_path():
                raise OSError("registry locked")
            return write(path, data, *args, **kwargs)
        with patch.object(storage, "write_json", side_effect=fail_registry):
            with self.assertRaisesRegex(OSError, "registry locked"):
                storage.migrate(storage.inventory())
        self.assertFalse((game / "instance.json").exists())
        self.assertFalse((game / ".cubeon/mods").exists())
        self.assertFalse(storage.restart_required())
        for name, target in original.items():
            self.assertEqual((game / name).resolve(), target)
        storage.migrate(storage.inventory())
        self.assertIsNotNone(storage.manifest(ids[0]))

    def migrated_without_cleanup(self):
        ids, source = self.legacy(1)
        with patch.object(storage, "_archive_legacy_content", return_value={"archived": [], "backup": None}):
            storage.migrate(storage.inventory())
        self.restart()
        return ids, source

    def test_success_cleans_root_and_keeps_exact_recovery_originals(self):
        ids, source = self.legacy(1)
        (self.root / "global_content").mkdir()
        (self.root / "global_content/unused.zip").write_bytes(b"unassigned pack")
        original = {name: (self.root / name).stat().st_ino for name in storage._LEGACY_CONTENT_DIRS}
        source_bytes, source_inode = source.read_bytes(), source.stat().st_ino
        result = storage.migrate(storage.inventory())
        self.assertEqual(set(result["archived"]), set(storage._LEGACY_CONTENT_DIRS))
        backup = self.root / result["backup"]
        for name, inode in original.items():
            self.assertFalse((self.root / name).exists())
            self.assertEqual((backup / name).stat().st_ino, inode)
        self.assertEqual((backup / "global_mods/sodium.jar").read_bytes(), source_bytes)
        self.assertEqual((backup / "global_mods/sodium.jar").stat().st_ino, source_inode)
        self.assertEqual((backup / "global_content/unused.zip").read_bytes(), b"unassigned pack")
        self.assertFalse(storage.needs_migration())
        self.restart()
        game = Path(storage.game_dir(ids[0]))
        self.assertEqual((game / "mods/sodium.jar").read_bytes(), source_bytes)
        mods.sync_mods_to_game("1.21.1", "fabric", ids[0])
        content.sync_content_to_game("1.21.1", "fabric", ids[0])
        global_mod_cache.put_file(str(jar(Path(self.temp.name) / "new.jar", "new")), str(game / "mods/new.jar"))
        self.assertTrue((game / "mods/new.jar").is_file())
        self.assertTrue(all(not (self.root / name).exists() for name in storage._LEGACY_CONTENT_DIRS))

    def test_partial_migration_does_not_clean_shared_content(self):
        ids, source = self.legacy(2)
        copy = storage._copy_verified
        def fail_second(entries, target, *args):
            if ids[1] in str(target):
                raise OSError("second instance copy failed")
            return copy(entries, target, *args)
        with patch.object(storage, "_copy_verified", side_effect=fail_second):
            with self.assertRaises(OSError):
                storage.migrate(storage.inventory())
        self.assertTrue(source.is_file())
        self.assertTrue((self.root / "mods").is_dir())
        self.assertNotEqual(storage.registry().get("content_cleanup"), 1)

    def test_already_migrated_cleanup_does_not_copy_instances_again(self):
        ids, _ = self.migrated_without_cleanup()
        self.assertTrue(storage.needs_migration())
        plan = storage.inventory(hash_files=False)
        self.assertEqual(plan["instances"], [])
        self.assertTrue(plan["cleanup"])
        self.assertEqual(plan["bytes"], 0)
        game = Path(storage.game_dir(ids[0]))
        world = game / "saves/My world/level.dat"
        world.write_bytes(b"new progress after migration")
        with patch.object(storage, "_copy_verified", side_effect=AssertionError("must not remigrate")):
            result = storage.migrate(plan)
        self.assertEqual(result["migrated"], 0)
        self.assertTrue(result["archived"])
        self.assertEqual(world.read_bytes(), b"new progress after migration")
        self.assertFalse(storage.needs_migration())

    def test_cleanup_failure_resumes_from_last_folder_rename(self):
        ids, _ = self.migrated_without_cleanup()
        replace = os.replace
        def fail_mods(source, destination):
            if Path(source) == self.root / "mods":
                raise PermissionError("old mods folder locked")
            return replace(source, destination)
        with patch.object(storage.os, "replace", side_effect=fail_mods):
            with self.assertRaisesRegex(PermissionError, "locked"):
                storage.migrate(storage.inventory())
        self.assertTrue(storage.restart_required())
        self.assertFalse((self.root / "global_mods").exists())
        self.assertTrue((self.root / "mods").exists())
        self.assertTrue(storage.cleanup_pending())
        self.restart()
        storage.initialize()
        result = storage.migrate(storage.inventory())
        self.assertTrue((self.root / result["backup"] / "global_mods/sodium.jar").is_file())
        self.assertFalse(storage.needs_migration())
        self.assertTrue((Path(storage.game_dir(ids[0])) / "mods/sodium.jar").is_file())

    def test_cleanup_commit_failure_still_offers_resume_when_root_is_clean(self):
        self.migrated_without_cleanup()
        write = storage.write_json
        def fail_registry(path, data, *args, **kwargs):
            if Path(path) == storage.registry_path():
                raise OSError("cleanup commit interrupted")
            return write(path, data, *args, **kwargs)
        with patch.object(storage, "write_json", side_effect=fail_registry):
            with self.assertRaisesRegex(OSError, "interrupted"):
                storage.migrate(storage.inventory())
        self.assertTrue(all(not (self.root / name).exists() for name in storage._LEGACY_CONTENT_DIRS))
        self.assertTrue(storage.needs_migration())
        self.restart()
        result = storage.migrate(storage.inventory())
        self.assertTrue((self.root / result["backup"] / "global_mods/sodium.jar").is_file())
        self.assertTrue(storage.restart_required())
        self.assertFalse(storage.needs_migration())

    def test_cleanup_recovers_rename_before_progress_was_saved(self):
        self.migrated_without_cleanup()
        write = storage.write_json
        def interrupt_progress(path, data, *args, **kwargs):
            if (Path(path) == self.root / "instances/migration.json"
                    and data.get("cleanup", {}).get("moved")):
                raise OSError("stopped after rename")
            return write(path, data, *args, **kwargs)
        with patch.object(storage, "write_json", side_effect=interrupt_progress):
            with self.assertRaisesRegex(OSError, "after rename"):
                storage.migrate(storage.inventory())
        journal = storage._read(self.root / "instances/migration.json")
        self.assertEqual(journal["cleanup"]["moved"], [])
        self.assertFalse((self.root / "global_mods").exists())
        self.restart()
        result = storage.migrate(storage.inventory())
        self.assertTrue((self.root / result["backup"] / "global_mods/sodium.jar").is_file())
        self.assertFalse(storage.needs_migration())

    def test_cleanup_refuses_active_content_links(self):
        ids, source = self.migrated_without_cleanup()
        game = Path(storage.game_dir(ids[0]))
        (game / "mods/sodium.jar").unlink()
        (game / "mods/sodium.jar").symlink_to(source)
        with self.assertRaisesRegex(RuntimeError, "still uses a link"):
            storage.migrate(storage.inventory())
        self.assertTrue(source.is_file())
        self.assertTrue((self.root / "mods").exists())
        self.assertFalse(storage.restart_required())

    def test_cleanup_popup_is_enabled_for_previously_migrated_install(self):
        from ui.storage_migration import StorageMigration
        from types import SimpleNamespace
        self.migrated_without_cleanup()
        class InlineThread:
            def __init__(self, target, **kwargs):
                self.target = target
            def start(self):
                self.target()
        with patch("ui.storage_migration.threading.Thread", InlineThread), \
             patch("ui.storage_migration.dialogs.open_dialog"), \
             patch("ui.storage_migration.thread_safe_ui.refresh"):
            prompt = StorageMigration(SimpleNamespace(), busy=lambda: False,
                                      restart=lambda _: None, exit_launcher=lambda _: None).show()
            self.assertFalse(prompt.start.disabled)
            self.assertEqual(prompt.start.content, "Organize folders")
            prompt._start()
            self.assertEqual(prompt.phase, "restart")
            self.assertIn("Organization complete", prompt.status.value)
            self.assertFalse(storage.needs_migration())

    def organize(self, labels=None):
        plan = storage.inventory(hash_files=False)
        plan.update(organize_instances=True, instance_labels=labels or {})
        return storage.migrate(plan)

    def test_combined_layout_moves_runtime_and_preserves_each_world(self):
        from cubeon import storage_layout
        ids, _ = self.legacy(2)
        old_games = [Path(paths.game_dir_for(vid, create=False)) for vid in ids]
        worlds = [(game / "saves/My world/level.dat").stat().st_ino for game in old_games]
        assets_inode = (self.root / "assets/payload").stat().st_ino
        paths.set_active_game_dir(str(old_games[1]))
        java = self.root / "runtime/old-java/bin/java"
        java.parent.mkdir(parents=True)
        java.write_bytes(b"keep java")
        result = self.organize()
        self.assertEqual(result["renamed"], 2)
        self.assertTrue(result["runtime_moved"])
        self.assertTrue(storage.restart_required())
        self.restart()
        runtime = self.root / "instances/.runtime"
        self.assertEqual(storage.runtime_dir(), str(runtime))
        self.assertEqual((runtime / "assets/payload").stat().st_ino, assets_inode)
        for name in ("assets", "libraries", "versions"):
            self.assertFalse((self.root / name).exists())
            self.assertTrue((runtime / name).is_dir())
            self.assertFalse((runtime / name).is_symlink())
        self.assertEqual(java.read_bytes(), b"keep java")
        for index, vid in enumerate(ids):
            game = Path(storage.game_dir(vid))
            self.assertEqual(game.name, "1.21.1-Fabric" + (f"-{index+1}" if index else ""))
            self.assertFalse(old_games[index].exists())
            self.assertEqual((game / "saves/My world/level.dat").stat().st_ino, worlds[index])
            self.assertEqual((game / "saves/My world/level.dat").read_bytes(), b"world-" + vid.encode())
            self.assertEqual((game / "options.txt").read_text(), "maxFps:0\nrenderDistance:4\n")
            self.assertEqual(mods.profile_dir_for_key(storage.manifest(vid)["profile"]), str(game / "mods"))
            self.assertEqual(versions.version_folder(vid), str(runtime / "versions" / vid))
        self.assertEqual(paths.active_game_dir(), storage.game_dir(ids[1]))
        self.assertFalse(storage_layout.needed())
        self.assertEqual(self.organize()["renamed"], 0)

    def test_readable_names_keep_custom_names_and_avoid_collisions(self):
        from cubeon import storage_layout
        ids, _ = self.legacy(2)
        reserved = self.root / "instances/My Survival"
        reserved.mkdir()
        (reserved / "untouched.txt").write_text("not an instance")
        self.organize({vid: "My Survival" for vid in ids})
        self.assertEqual(storage.folder_for(ids[0]).name, "My Survival-2")
        self.assertEqual(storage.folder_for(ids[1]).name, "My Survival-3")
        self.assertEqual((reserved / "untouched.txt").read_text(), "not an instance")
        self.assertEqual(storage_layout.folder_label("fabric-loader-0.20.1-26.3"), "26.3-Fabric")
        self.assertNotIn("/", storage_layout.folder_label("x", label="../bad/name"))
        self.assertEqual(storage_layout.folder_label("x", label="CON"), "Minecraft-CON")

    def test_new_instance_names_are_readable_before_first_install(self):
        storage.initialize()
        vid = "fabric-loader-0.20.1-26.3"
        expected = storage.game_dir(vid)
        self.assertEqual(Path(expected).parent.name, "26.3-Fabric")
        self.assertFalse(Path(expected).exists())
        actual = mods.get_profile_dir("26.3", "fabric", vid)
        self.assertEqual(Path(actual).parent, Path(expected))
        self.assertEqual(storage.game_dir(vid), expected)
        self.assertEqual(storage.runtime_dir(), str(self.root / "instances/.runtime"))

    def test_failed_instance_rename_restores_original_world_path(self):
        from cubeon import storage_layout
        ids, _ = self.legacy(1)
        storage.migrate(storage.inventory())
        self.restart()
        old = Path(storage.game_dir(ids[0]))
        before = storage.manifest(ids[0])
        write = storage_layout.write_json
        def locked_registry(path, data, *args, **kwargs):
            if Path(path) == storage.registry_path():
                raise PermissionError("registry locked")
            return write(path, data, *args, **kwargs)
        with patch.object(storage_layout, "write_json", side_effect=locked_registry):
            with self.assertRaisesRegex(PermissionError, "registry locked"):
                self.organize()
        self.assertEqual(Path(storage.game_dir(ids[0])), old)
        self.assertEqual(storage.manifest(ids[0]), before)
        self.assertTrue((old / "saves/My world/level.dat").is_file())
        self.assertFalse((self.root / "instances/1.21.1-Fabric").exists())
        self.assertFalse(storage.restart_required())

    def test_killed_instance_rename_recovers_before_startup(self):
        from cubeon import storage_layout
        ids, _ = self.legacy(1)
        storage.migrate(storage.inventory())
        self.restart()
        old = Path(storage.game_dir(ids[0]))
        write = storage_layout.write_json
        def power_loss(path, data, *args, **kwargs):
            if Path(path).name == "instance.json":
                raise SystemExit("process gone after rename")
            return write(path, data, *args, **kwargs)
        with patch.object(storage_layout, "write_json", side_effect=power_loss), \
             patch.object(storage_layout, "_rollback_rename", side_effect=SystemExit("no process")):
            with self.assertRaises(SystemExit):
                self.organize()
        self.assertFalse(old.exists())
        self.assertTrue(storage.restart_required())
        self.restart()
        storage.initialize()
        self.assertEqual(Path(storage.game_dir(ids[0])), old)
        self.assertTrue((old / "saves/My world/level.dat").is_file())
        self.organize()
        self.assertEqual(storage.folder_for(ids[0]).name, "1.21.1-Fabric")

    def test_runtime_move_failure_rolls_back_all_runtime_parts(self):
        ids, _ = self.legacy(1)
        replace = os.replace
        def locked_libraries(source, destination):
            if Path(source) == self.root / "libraries":
                raise PermissionError("libraries locked")
            return replace(source, destination)
        with patch.object(storage.os, "replace", side_effect=locked_libraries):
            with self.assertRaisesRegex(PermissionError, "libraries locked"):
                self.organize()
        self.assertEqual(storage.runtime_dir(), str(self.root))
        self.assertEqual((self.root / "assets/payload").read_bytes(), b"assets")
        self.assertTrue((self.root / "versions" / ids[0]).exists())
        self.assertFalse((self.root / "instances/.runtime/assets").exists())
        self.restart()
        self.organize()
        self.assertEqual(storage.runtime_dir(), str(self.root / "instances/.runtime"))

    def test_killed_runtime_move_is_recovered_before_installation(self):
        from cubeon import storage_layout
        self.legacy(1)
        replace = os.replace
        def power_loss(source, destination):
            if Path(source) == self.root / "libraries":
                raise SystemExit("power loss")
            return replace(source, destination)
        with patch.object(storage.os, "replace", side_effect=power_loss), \
             patch.object(storage_layout, "_rollback_runtime", side_effect=SystemExit("no process")):
            with self.assertRaises(SystemExit):
                self.organize()
        self.assertFalse((self.root / "assets").exists())
        self.restart()
        storage.initialize()
        self.assertTrue((self.root / "assets").exists())
        self.assertEqual(storage.runtime_dir(), str(self.root))
        self.organize()
        self.assertTrue((self.root / "instances/.runtime/assets/payload").exists())

    def test_mll_launch_and_installer_lookup_use_hidden_runtime(self):
        import minecraft_launcher_lib as mll
        from cubeon import storage_layout
        ids, _ = self.legacy(1)
        vid = ids[0]
        base = self.root / "versions/1.21.1"
        data = {"id": "1.21.1", "type": "release", "mainClass": "example.Main",
                "libraries": [{"name": "org.example:shared:1.0"}], "assets": "17",
                "arguments": {"game": ["--gameDir", "${game_directory}", "--assetsDir", "${assets_root}"]}}
        write_json(str(base / "1.21.1.json"), data)
        jar(base / "1.21.1.jar", "client")
        jar(self.root / "libraries/org/example/shared/1.0/shared-1.0.jar", "shared")
        child = storage._read(self.root / "versions" / vid / (vid + ".json"))
        child.update(jar="1.21.1", type="release")
        write_json(str(self.root / "versions" / vid / (vid + ".json")), child)
        self.organize()
        self.restart()
        runtime = Path(storage.runtime_dir())
        command = mll.command.get_minecraft_command(vid, str(runtime), {"gameDirectory": storage.game_dir(vid)})
        self.assertEqual(command[command.index("--gameDir") + 1], storage.game_dir(vid))
        self.assertEqual(command[command.index("--assetsDir") + 1], str(runtime / "assets"))
        for p in command[command.index("-cp") + 1].split(os.pathsep):
            self.assertTrue(Path(p).is_file(), p)
        # Existing-profile install reads metadata from the new directory.
        with patch.object(mll.install, "do_version_install") as install:
            mll.install.install_minecraft_version(vid, str(runtime))
            self.assertEqual(install.call_args.args[1], str(runtime))

    def test_pack_rollback_removes_new_readable_folder_registration(self):
        storage.initialize()
        vid = "fabric-loader-0.20.1-26.3"
        mods.get_profile_dir("26.3", "fabric", vid)
        folder = storage.folder_for(vid)
        self.assertNotEqual(folder.name, storage.manifest(vid)["id"])
        shutil.rmtree(folder)
        storage.discard_registration(vid, folder.name)
        self.assertNotIn(vid, storage.registry()["instances"])

    def test_committed_runtime_move_is_kept_after_journal_interruption(self):
        from cubeon import storage_layout
        self.legacy(1)
        write = storage_layout.write_json
        def failed_completion(path, data, *args, **kwargs):
            if Path(path) == storage_layout._journal_path() and storage.registry()["runtime"] == "instances":
                raise OSError("completion interrupted")
            return write(path, data, *args, **kwargs)
        with patch.object(storage_layout, "write_json", side_effect=failed_completion):
            with self.assertRaisesRegex(OSError, "completion interrupted"):
                self.organize()
        runtime = Path(storage.runtime_dir())
        self.assertEqual(runtime, self.root / "instances/.runtime")
        self.restart()
        storage.initialize()
        self.assertEqual(storage.runtime_dir(), str(runtime))
        self.assertFalse((self.root / "versions").exists())
        self.assertTrue((runtime / "assets/payload").is_file())
        self.assertFalse(storage_layout.needed())

    def test_renamed_instance_backup_and_deletion_keep_worlds(self):
        from cubeon import backup
        ids, _ = self.legacy(1)
        self.organize()
        self.restart()
        game = Path(storage.game_dir(ids[0]))
        with patch.object(backup, "MINECRAFT_DIR", str(self.root)):
            result = backup.create_backup(include_saves=True, dest_dir=str(Path(self.temp.name) / "backups"))
        self.assertTrue(result.ok, result.message)
        with zipfile.ZipFile(result.path) as archive:
            self.assertIn("instances/1.21.1-Fabric/saves/My world/level.dat", archive.namelist())
        old_id = storage.manifest(ids[0])["id"]
        versions.delete_version(ids[0])
        self.assertFalse(game.exists())
        self.assertTrue((self.root / "backups/deleted-instances" / old_id / "saves/My world/level.dat").is_file())


if __name__ == "__main__":
    unittest.main(verbosity=2)
