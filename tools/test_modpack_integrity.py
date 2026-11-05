"""Pack installs preserve working bytes and never silently omit required files."""
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from contextlib import ExitStack
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import atomicio, csl, cubeonfriends, modpacks, mods, net, paths


def jar(mod_id, version):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(zipfile.ZipInfo("fabric.mod.json"), json.dumps({
            "schemaVersion": 1, "id": mod_id, "version": version,
            "depends": {"minecraft": "1.20.1", "fabricloader": ">=0.15.7"}}))
    return stream.getvalue()


def snapshot(root):
    result = {}
    for directory, folders, files in os.walk(root):
        for name in folders[:] + files:
            path = Path(directory) / name
            key = str(path.relative_to(root))
            if path.is_symlink():
                result[key] = ("link", os.readlink(path), path.read_bytes() if path.is_file() else None)
                if name in folders:
                    folders.remove(name)
            elif path.is_file():
                result[key] = ("file", path.read_bytes())
    return result


class PackIntegrity(unittest.TestCase):
    def setUp(self):
        self.context = ExitStack()
        self.addCleanup(self.context.close)
        self.root = Path(self.context.enter_context(tempfile.TemporaryDirectory()))
        self.game = self.root / "minecraft"
        self.profiles = self.root / "profiles"
        (self.game / "versions").mkdir(parents=True)
        self.profiles.mkdir()
        for module in (modpacks, mods):
            self.context.enter_context(patch.object(module, "MINECRAFT_DIR", str(self.game)))
            self.context.enter_context(patch.object(module, "PROFILES_DIR", str(self.profiles)))
        self.context.enter_context(patch.object(net, "MAX_CONCURRENT_DOWNLOADS", 1))
        self.context.enter_context(patch.object(modpacks, "install_version", self.install_base))
        self.context.enter_context(patch.object(modpacks, "install_mod_loader", self.install_loader))
        self.context.enter_context(patch.object(modpacks, "_pack_game_dir", self.game_dir))
        self.original_stream = modpacks._stream_download
        self.context.enter_context(patch.object(modpacks, "_stream_download", self.download))
        self.context.enter_context(patch.object(csl, "set_enabled"))
        self.context.enter_context(patch.object(csl, "ensure_ready"))
        self.context.enter_context(patch.object(cubeonfriends, "ensure_installed", return_value=True))
        self.blobs = {}
        self.fail_url = None
        self.downloads = []
        # Force a private instance, and verify this unrelated profile survives.
        shared = self.profiles / "1.20.1-fabric"
        shared.mkdir()
        (shared / "user.jar").write_bytes(jar("user", "1"))

    def install_base(self, version_id, *args, **kwargs):
        directory = self.game / "versions" / version_id
        directory.mkdir(exist_ok=True)
        atomicio.write_json(directory / (version_id + ".json"), {"id": version_id})

    def install_loader(self, loader, mc, *args, loader_version=None, **kwargs):
        version_id = f"{loader}-loader-{loader_version}-{mc}"
        directory = self.game / "versions" / version_id
        directory.mkdir(exist_ok=True)
        atomicio.write_json(directory / (version_id + ".json"), {
            "id": version_id, "inheritsFrom": mc, "libraries": [{"name": f"loader:{loader_version}"}]})
        return version_id

    def game_dir(self, version_id):
        directory = self.game / "instances" / version_id
        directory.mkdir(parents=True, exist_ok=True)
        return str(directory)

    def download(self, destination, urls, hashes=None, *args):
        url = urls[0]
        self.downloads.append(url)
        if url == self.fail_url:
            raise modpacks.ModpackError("simulated network outage")
        Path(destination).write_bytes(self.blobs[url])

    def pack(self, version="1", *, loader="0.15.7", mods_spec=None, overrides=None, files=None):
        entries = []
        for filename, payload in (mods_spec or [("same.jar", jar("same", version))]):
            url = f"https://cdn.modrinth.com/data/integrity/versions/{version}/{filename}"
            self.blobs[url] = payload
            entries.append({"path": "mods/" + filename, "downloads": [url], "fileSize": len(payload)})
        if files:
            entries += files
        archive = self.root / "pack.mrpack"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.writestr("modrinth.index.json", json.dumps({
                "formatVersion": 1, "game": "minecraft", "name": "Integrity Pack",
                "versionId": version, "dependencies": {"minecraft": "1.20.1", "fabric-loader": loader},
                "files": entries}))
            for name, payload in (overrides or {}).items():
                zf.writestr("overrides/" + name, payload)
        return str(archive)

    def initial(self):
        meta = modpacks.install_modpack_from_file(self.pack(overrides={
            "mods/old-only.jar": jar("old", "1"), "config/pack.txt": b"old config",
            "resourcepacks/pack.zip": jar("resources", "1")}))
        profile = self.profiles / meta["profile"]
        game = Path(self.game_dir(meta["version_id"]))
        (profile / "user-added.jar.disabled").write_bytes(jar("disabled", "1"))
        (game / "saves" / "world").mkdir(parents=True)
        (game / "saves" / "world" / "level.dat").write_bytes(b"player world")
        return meta, profile, game

    def assert_restored(self, meta, before_profile, before_game, before_version):
        self.assertEqual(snapshot(self.profiles / meta["profile"]), before_profile)
        self.assertEqual(snapshot(Path(self.game_dir(meta["version_id"]))), before_game)
        self.assertEqual(snapshot(self.game / "versions" / meta["version_id"]), before_version)
        self.assertFalse(modpacks.active_pack_installs())
        self.assertEqual(mods.read_instance_meta(meta["version_id"])["pack_version"], "1")

    def test_failed_download_restores_same_named_mod_new_mod_and_loader(self):
        meta, profile, game = self.initial()
        before = (snapshot(profile), snapshot(game), snapshot(self.game / "versions" / meta["version_id"]))
        archive = self.pack("2", loader="0.16.0", mods_spec=[
            ("same.jar", jar("same", "2")), ("new.jar", jar("new", "2")), ("fail.jar", jar("fail", "2"))])
        self.fail_url = next(url for url in self.blobs if url.endswith("/2/fail.jar"))
        with self.assertRaisesRegex(modpacks.ModpackError, "outage"):
            modpacks.install_modpack_from_file(archive)
        self.assert_restored(meta, *before)

    def test_failed_marker_restores_pruned_mod_overrides_resources_and_config(self):
        meta, profile, game = self.initial()
        before = (snapshot(profile), snapshot(game), snapshot(self.game / "versions" / meta["version_id"]))
        archive = self.pack("2", loader="0.16.0", overrides={
            "config/pack.txt": b"new config", "config/new.txt": b"new",
            "resourcepacks/pack.zip": jar("resources", "2"), "mods/bundled.jar": jar("bundled", "2")})
        real_write = atomicio.write_json
        def fail_marker(path, data):
            if str(path).endswith("_modpack.json"):
                raise OSError("disk full")
            return real_write(path, data)
        with patch.object(atomicio, "write_json", side_effect=fail_marker), self.assertRaises(modpacks.ModpackError):
            modpacks.install_modpack_from_file(archive)
        self.assert_restored(meta, *before)

    def test_cancel_after_all_downloads_restores_previous_files(self):
        meta, profile, game = self.initial()
        before = (snapshot(profile), snapshot(game), snapshot(self.game / "versions" / meta["version_id"]))
        def cancel(text):
            if text == "Applying pack config":
                raise InterruptedError("cancelled")
        with self.assertRaises(InterruptedError):
            modpacks.install_modpack_from_file(self.pack("2"), status_cb=cancel)
        self.assert_restored(meta, *before)

    def test_client_overrides_win_regardless_of_archive_order(self):
        archive = self.pack(overrides={"config/pack.txt": b"shared", "options.txt": b"shared"})
        # Rewrite with client overrides listed first, as some pack exporters do.
        with zipfile.ZipFile(archive) as source:
            members = [(member, source.read(member)) for member in source.namelist()]
        with zipfile.ZipFile(archive, "w") as target:
            target.writestr("client-overrides/config/pack.txt", b"client")
            target.writestr("client-overrides/options.txt", b"client")
            for name, payload in members:
                target.writestr(name, payload)
        meta = modpacks.install_modpack_from_file(archive)
        game = Path(self.game_dir(meta["version_id"]))
        self.assertEqual((game / "config/pack.txt").read_bytes(), b"client")
        self.assertEqual((game / "options.txt").read_bytes(), b"client")
        (game / "options.txt").write_bytes(b"user's settings")
        modpacks.install_modpack_from_file(archive)
        self.assertEqual((game / "options.txt").read_bytes(), b"user's settings")

    def test_low_disk_space_refuses_and_restores_the_update(self):
        meta, profile, game = self.initial()
        before = (snapshot(profile), snapshot(game), snapshot(self.game / "versions" / meta["version_id"]))
        with patch.object(paths, "ensure_disk_space", side_effect=RuntimeError("Not enough disk space")), self.assertRaisesRegex(RuntimeError, "disk space"):
            modpacks.install_modpack_from_file(self.pack("2"))
        self.assert_restored(meta, *before)

    def test_cancel_at_final_status_restores_even_committed_marker(self):
        meta, profile, game = self.initial()
        before = (snapshot(profile), snapshot(game), snapshot(self.game / "versions" / meta["version_id"]))
        def cancel(text):
            if text.startswith("Installed "):
                raise InterruptedError("cancelled")
        with self.assertRaises(InterruptedError):
            modpacks.install_modpack_from_file(self.pack("2"), status_cb=cancel)
        self.assert_restored(meta, *before)

    def test_failed_first_install_removes_partial_clone_and_profile_content(self):
        archive = self.pack("2", mods_spec=[("same.jar", jar("same", "2")), ("fail.jar", jar("fail", "2"))])
        self.fail_url = next(url for url in self.blobs if url.endswith("/fail.jar"))
        with self.assertRaises(modpacks.ModpackError):
            modpacks.install_modpack_from_file(archive)
        self.assertFalse(modpacks.list_installed_modpacks())
        self.assertFalse(list((self.game / "versions").glob("1.20.1-fabric-integrity*")))
        self.assertEqual(set(snapshot(self.profiles)), {"1.20.1-fabric/user.jar"})

    def test_success_updates_exact_loader_and_keeps_user_mod_and_world(self):
        meta, profile, game = self.initial()
        result = modpacks.install_modpack_from_file(self.pack("2", loader="0.16.0"))
        self.assertEqual(result["version_id"], meta["version_id"])
        self.assertEqual((profile / "same.jar").read_bytes(), jar("same", "2"))
        self.assertFalse((profile / "old-only.jar").exists())
        self.assertTrue((profile / "user-added.jar.disabled").is_file())
        self.assertEqual((game / "saves/world/level.dat").read_bytes(), b"player world")
        self.assertIn("0.16.0", mods.read_instance_meta(result["version_id"])["source_version_id"])
        launch = json.loads((self.game / "versions" / result["version_id"] / (result["version_id"] + ".json")).read_text())
        self.assertEqual(launch["libraries"], [{"name": "loader:0.16.0"}])

    def test_rollback_preserves_bytes_when_symlinks_are_unavailable(self):
        with patch.object(os, "symlink", side_effect=OSError("symlinks unavailable")):
            meta, profile, game = self.initial()
            self.assertFalse((profile / "same.jar").is_symlink())
            before = (snapshot(profile), snapshot(game), snapshot(self.game / "versions" / meta["version_id"]))
            archive = self.pack("2", mods_spec=[("same.jar", jar("same", "2")), ("fail.jar", jar("fail", "2"))])
            self.fail_url = next(url for url in self.blobs if url.endswith("/2/fail.jar"))
            with self.assertRaises(modpacks.ModpackError):
                modpacks.install_modpack_from_file(archive)
            self.assert_restored(meta, *before)

    def test_instance_sidecar_save_failure_blocks_install(self):
        with patch.object(modpacks, "write_instance_meta", return_value=False), self.assertRaisesRegex(modpacks.ModpackError, "instance profile"):
            modpacks.install_modpack_from_file(self.pack())
        self.assertFalse(self.downloads)
        self.assertFalse(modpacks.list_installed_modpacks())

    def test_html_or_truncated_download_cannot_enter_profile(self):
        for payload in (b"<html>Download blocked</html>", jar("broken", "1")[:-15]):
            with self.subTest(payload=payload[:20]):
                with self.assertRaisesRegex(modpacks.ModpackError, "readable archive"):
                    modpacks.install_modpack_from_file(self.pack(mods_spec=[("bad.jar", payload)]))
                self.assertFalse(modpacks.list_installed_modpacks())

    def test_invalid_manifest_fails_before_game_install(self):
        for bad in ({"path": []}, {"path": "mods/a.jar", "downloads": "https://cdn.modrinth.com/a"},
                    {"path": "../config.txt", "downloads": ["https://cdn.modrinth.com/a"]},
                    {"path": "mods/a.jar", "downloads": ["https://cdn.modrinth.com/a"], "hashes": []},
                    {"path": "mods/a.jar", "downloads": ["https://cdn.modrinth.com/a"], "hashes": {"sha1": 12}}):
            with self.subTest(bad=bad), self.assertRaises(modpacks.ModpackError):
                modpacks.install_modpack_from_file(self.pack(files=[bad]))
        self.assertFalse(self.downloads)
        self.assertFalse(list((self.game / "versions").iterdir()))

    def test_non_list_file_blocks_and_ambiguous_loaders_have_readable_errors(self):
        for files in (42, {"mods/a.jar": "url"}, "mods/a.jar", None):
            archive = self.pack()
            with zipfile.ZipFile(archive) as source:
                index = json.loads(source.read("modrinth.index.json"))
            index["files"] = files
            with zipfile.ZipFile(archive, "w") as target:
                target.writestr("modrinth.index.json", json.dumps(index))
            with self.subTest(files=files), self.assertRaises(modpacks.ModpackError):
                modpacks.install_modpack_from_file(archive)
        for dependencies in ({"minecraft": "1.20.1", "fabric-loader": None},
                             {"minecraft": "1.20.1", "fabric-loader": "0.15.7", "quilt-loader": "0.20.0"}):
            with self.assertRaises(modpacks.ModpackError):
                modpacks.parse_dependencies({"dependencies": dependencies})
        self.assertFalse(self.downloads)

    def test_flattened_duplicate_names_are_refused(self):
        with self.assertRaisesRegex(modpacks.ModpackError, "overwrite"):
            modpacks.install_modpack_from_file(self.pack(files=[{
                "path": "mods/sub/SAME.jar", "downloads": ["https://cdn.modrinth.com/a"]}]))
        self.assertFalse(self.downloads)

    def test_linked_config_parent_is_refused_and_external_file_untouched(self):
        meta, profile, game = self.initial()
        outside = self.root / "external"
        outside.mkdir()
        (outside / "secret.txt").write_bytes(b"keep")
        os.symlink(outside, game / "linked", target_is_directory=True)
        with self.assertRaisesRegex(modpacks.ModpackError, "linked folder"):
            modpacks.install_modpack_from_file(self.pack("2", overrides={"linked/secret.txt": b"wrong"}))
        self.assertEqual((outside / "secret.txt").read_bytes(), b"keep")

    def test_redirect_validation_is_passed_to_downloader(self):
        with patch.object(net, "download_to") as download:
            self.original_stream(str(self.root / "unused"), ["https://cdn.modrinth.com/a"], {})
            validator = download.call_args.kwargs["url_validator"]
            self.assertTrue(validator("https://edge.forgecdn.net/a"))
            self.assertFalse(validator("https://example.com/a"))


class CurseForgeCompleteness(unittest.TestCase):
    def convert(self, manifest, rows, *, failure=None):
        with tempfile.TemporaryDirectory() as directory:
            source, target = Path(directory) / "pack.zip", Path(directory) / "pack.mrpack"
            with zipfile.ZipFile(source, "w") as zf:
                zf.writestr("manifest.json", json.dumps(manifest))
            with patch.object(modpacks, "curseforge_enabled", return_value=True), patch.object(modpacks, "_cf_batch_files", return_value=rows, side_effect=failure):
                return modpacks._cf_manifest_to_mrpack(str(source), str(target), status_cb=lambda text: None)

    def manifest(self):
        return {"minecraft": {"version": "1.20.1", "modLoaders": [{"id": "forge-47.2.0", "primary": True}]},
                "files": [{"projectID": 1, "fileID": 11}, {"projectID": 2, "fileID": 22}]}

    def test_partial_metadata_uses_exact_keyless_file(self):
        result = self.convert(self.manifest(), [{"modId": 1, "id": 11, "fileName": "first.jar", "downloadUrl": "https://edge.forgecdn.net/first.jar"}])
        self.assertEqual(len(result["files"]), 2)
        self.assertEqual(result["files"][1]["downloads"], [modpacks._cf_download_url(2, 22)])

    def test_empty_or_unsafe_metadata_does_not_omit_files(self):
        for rows in ([], [{"modId": 1, "id": 11, "downloadUrl": "https://example.com/mod.jar"}]):
            with self.subTest(rows=rows):
                self.assertEqual(len(self.convert(self.manifest(), rows)["files"]), 2)

    def test_rejected_metadata_api_still_uses_exact_manifest_files(self):
        result = self.convert(self.manifest(), [], failure=modpacks.ModpackError("CurseForge rejected the API key"))
        self.assertEqual(len(result["files"]), 2)
        self.assertEqual(result["files"][0]["downloads"], [modpacks._cf_download_url(1, 11)])

    def test_bad_required_ids_and_unknown_primary_loader_are_refused(self):
        for change in ("ids", "loader", "body", "minecraft"):
            manifest = self.manifest()
            if change == "ids":
                manifest["files"].append({"projectID": 3})
            elif change == "loader":
                manifest["minecraft"]["modLoaders"] = [{"id": "unknown-1", "primary": True}]
            elif change == "body":
                manifest = []
            else:
                manifest["minecraft"] = "1.20.1"
            with self.subTest(change=change), self.assertRaises(modpacks.ModpackError):
                self.convert(manifest, [])


if __name__ == "__main__":
    unittest.main()
