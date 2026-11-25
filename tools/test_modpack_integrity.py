"""Pack installs preserve working bytes and never silently omit required files."""
import io
import hashlib
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
from cubeon import atomicio, csl, cubeonfriends, modpacks, mods, net, paths, perf_mods, mod_dependencies


def jar(mod_id, version, loader="fabric"):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        if loader in ("fabric", "quilt"):
            archive.writestr(zipfile.ZipInfo("fabric.mod.json"), json.dumps({
                "schemaVersion": 1, "id": mod_id, "version": version,
                "depends": {"minecraft": "1.20.1", "fabricloader": ">=0.15.7"}}))
        else:
            descriptor = "META-INF/neoforge.mods.toml" if loader == "neoforge" else "META-INF/mods.toml"
            archive.writestr(descriptor, f'modLoader="javafml"\nloaderVersion="[1,)"\n'
                             f'[[mods]]\nmodId="{mod_id}"\nversion="{version}"\n')
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
        self.real_skin_setup = csl.ensure_ready
        self.real_client_setup = cubeonfriends.ensure_installed
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

    def pack(self, version="1", *, loader="0.15.7", loader_kind="fabric", mods_spec=None, overrides=None, files=None):
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
                "versionId": version, "dependencies": {"minecraft": "1.20.1",
                    {"fabric": "fabric-loader", "quilt": "quilt-loader", "forge": "forge", "neoforge": "neoforge"}[loader_kind]: loader},
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

    def test_pack_install_and_repeated_preparation_keep_author_files_for_every_loader(self):
        for loader in ("fabric", "quilt", "forge", "neoforge"):
            with self.subTest(loader=loader):
                pinned = [("library-pinned.jar", jar("library", "1", loader)),
                          ("moreculling.jar", jar("moreculling", "1", loader)),
                          ("krypton.jar", jar("krypton", "1", loader))]
                archive = self.pack(loader_kind=loader, mods_spec=pinned)
                with patch.object(csl, "ensure_ready", self.real_skin_setup), \
                        patch.object(cubeonfriends, "ensure_installed", self.real_client_setup), \
                        patch.object(csl, "write_extralist_entries", return_value=[]), \
                        patch.object(csl, "is_registered", return_value=True), \
                        patch.object(csl, "get_mod_download") as skin_lookup, \
                        patch.object(mods, "get_mod_download") as api_lookup, \
                        patch.object(perf_mods, "get_mod_download") as perf_lookup, \
                        patch.object(mod_dependencies, "run_dependency_doctor") as automatic_repair:
                    meta = modpacks.install_modpack_from_file(archive)
                    profile = Path(mods.resolve_profile_dir("1.20.1", loader, meta["version_id"]))
                    # Old provider receipts must not make pack-supplied mods
                    # eligible for Cubeon's legacy deletion/disable migrations.
                    mods._write_meta(str(profile), "moreculling.jar", "moreculling", project_id="51shyZVL")
                    mods._write_meta(str(profile), "krypton.jar", "krypton", project_id="fQEb0iXm")
                    before = snapshot(profile)
                    for _ in range(3):
                        report = perf_mods.ensure_installed("1.20.1", loader, version_id=meta["version_id"])
                        self.assertFalse(report["installed"])
                        self.assertEqual(perf_mods.retire_legacy_more_culling("1.20.1", loader, meta["version_id"]), [])
                        self.assertEqual(perf_mods.prune_retired_perf_mods("1.20.1", loader, meta["version_id"]), [])
                        self.assertFalse(cubeonfriends.ensure_installed("1.20.1", loader, str(profile),
                            automatic=True, version_id=meta["version_id"]))
                        cubeonfriends.ensure_fabric_api("1.20.1", loader, version_id=meta["version_id"])
                        csl.ensure_ready("1.20.1", loader, version_id=meta["version_id"])
                    for call in (skin_lookup, api_lookup, perf_lookup, automatic_repair):
                        call.assert_not_called()
                    self.assertEqual(before, snapshot(profile))
                    self.assertEqual({p.name: p.read_bytes() for p in profile.glob("*.jar")}, dict(pinned))

    def test_pack_ownership_protects_missing_relocated_corrupt_and_hidden_markers(self):
        meta = modpacks.install_modpack_from_file(self.pack())
        profile = Path(mods.resolve_profile_dir("1.20.1", "fabric", meta["version_id"]))
        marker = profile / "_modpack.json"
        marker.unlink()
        self.assertTrue(mods.is_modpack_profile("1.20.1", "fabric", meta["version_id"]))
        relocated = profile.parent / ".cubeon" / "mods" / "_modpack.json"
        relocated.parent.mkdir(parents=True, exist_ok=True)
        with patch.object(mods, "read_instance_meta", return_value=None), \
                patch.object(mods, "metadata_path", return_value=str(relocated)):
            self.assertFalse(mods.is_modpack_profile("1.20.1", "fabric", profile_dir=str(profile)))
            relocated.write_bytes(b"invalid UTF-8: \xff")
            self.assertTrue(mods.is_modpack_profile("1.20.1", "fabric", profile_dir=str(profile)))
            relocated.rename(str(relocated) + ".bak")
            self.assertTrue(mods.is_modpack_profile("1.20.1", "fabric", profile_dir=str(profile)))
            self.assertEqual(Path(str(relocated) + ".bak").read_bytes(), b"invalid UTF-8: \xff")

    def test_explicit_client_install_works_and_automatic_launch_keeps_that_exact_copy(self):
        meta = modpacks.install_modpack_from_file(self.pack())
        profile = Path(mods.resolve_profile_dir("1.20.1", "fabric", meta["version_id"]))
        bundled = self.root / "cubeon-client-test.jar"
        bundled.write_bytes(jar("cubeonclient", "1"))
        with patch.object(cubeonfriends, "ensure_installed", self.real_client_setup), \
                patch.object(cubeonfriends, "find_jar", return_value=str(bundled)) as lookup:
            self.assertFalse(cubeonfriends.ensure_installed("1.20.1", "fabric", str(profile),
                automatic=True, version_id=meta["version_id"]))
            lookup.assert_not_called()
            self.assertTrue(cubeonfriends.ensure_installed("1.20.1", "fabric", str(profile)))
            before = snapshot(profile)
            lookup.reset_mock()
            for _ in range(3):
                self.assertTrue(cubeonfriends.ensure_installed("1.20.1", "fabric", str(profile),
                    automatic=True, version_id=meta["version_id"]))
            lookup.assert_not_called()
            self.assertEqual(before, snapshot(profile))

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

    def test_bad_bundled_jar_rolls_back_the_entire_update(self):
        meta, profile, game = self.initial()
        before = (snapshot(profile), snapshot(game), snapshot(self.game / "versions" / meta["version_id"]))
        corrupt = bytearray(jar("bundled", "2"))
        with zipfile.ZipFile(io.BytesIO(corrupt)) as archive:
            entry = archive.infolist()[0]
            offset = entry.header_offset + 30 + len(entry.filename.encode()) + len(entry.extra)
        corrupt[offset] ^= 1  # Readable ZIP directory, damaged entry CRC.
        empty = io.BytesIO()
        with zipfile.ZipFile(empty, "w"):
            pass
        for payload in (b"<html>blocked</html>", jar("bundled", "2")[:-15], bytes(corrupt), empty.getvalue()):
            with self.subTest(payload=payload[:20]), self.assertRaisesRegex(modpacks.ModpackError, "readable archive"):
                modpacks.install_modpack_from_file(self.pack("2", overrides={"mods/bundled.jar": payload}))
            self.assert_restored(meta, *before)

    def test_cached_non_jar_is_rejected_even_when_its_hash_matches(self):
        payload = b"<html>download blocked</html>"
        hashes = {"sha512": hashlib.sha512(payload).hexdigest()}
        source = self.root / "cached-bad.jar"
        source.write_bytes(payload)
        modpacks.global_mod_cache.put_file(str(source), str(self.root / "cached-link.jar"), hashes)
        files = [{"path": "mods/cached-bad.jar", "downloads": ["https://cdn.modrinth.com/cached-bad.jar"],
                  "hashes": hashes, "fileSize": len(payload)}]
        with self.assertRaisesRegex(modpacks.ModpackError, "readable archive"):
            modpacks.install_modpack_from_file(self.pack(files=files))
        self.assertFalse(any(url.endswith("/cached-bad.jar") for url in self.downloads))
        self.assertFalse(modpacks.list_installed_modpacks())

    def test_passive_pack_check_defers_metadata_to_every_installed_loader(self):
        for loader in ("fabric", "quilt", "forge", "neoforge"):
            with self.subTest(loader=loader):
                unsupported = io.BytesIO()
                with zipfile.ZipFile(unsupported, "w") as archive:
                    descriptor = {"fabric": "fabric.mod.json", "quilt": "quilt.mod.json",
                                  "forge": "META-INF/mods.toml", "neoforge": "META-INF/neoforge.mods.toml"}[loader]
                    archive.writestr(descriptor, "custom metadata Cubeon cannot interpret")
                meta = modpacks.install_modpack_from_file(self.pack(loader_kind=loader,
                    mods_spec=[("opaque.jar", unsupported.getvalue()), ("other.jar", jar("same-id", "2", loader))]))
                profile = Path(mods.resolve_profile_dir("1.20.1", loader, meta["version_id"]))
                (profile / "disabled.jar.disabled").write_bytes(b"not an archive")
                # Legacy marker damage does not change the pack's ownership.
                (profile / "_modpack.json").write_bytes(b"invalid UTF-8: \xff")
                before = snapshot(profile)
                with patch.object(mod_dependencies, "_scan", side_effect=AssertionError("descriptor graph must not run")), \
                        patch.object(mods, "get_mod_download") as lookup:
                    report = mod_dependencies.run_dependency_doctor("1.20.1", loader,
                        version_id=meta["version_id"], auto_fix=False, check_online=False)
                lookup.assert_not_called()
                self.assertTrue(report["loader_managed"])
                self.assertEqual(report["unfixed"], [])
                self.assertEqual(report["checked"], 2)
                self.assertEqual(before, snapshot(profile))

    def test_passive_pack_check_reports_real_broken_files_and_stale_scans(self):
        meta = modpacks.install_modpack_from_file(self.pack())
        profile = Path(mods.resolve_profile_dir("1.20.1", "fabric", meta["version_id"]))
        (profile / "broken.jar").write_bytes(b"<html>blocked</html>")
        (profile / "missing.jar").symlink_to(profile / "absent.jar")
        report = mod_dependencies.run_dependency_doctor("1.20.1", "fabric", version_id=meta["version_id"],
            auto_fix=False, check_online=False)
        self.assertEqual({p["mod"] for p in report["unfixed"]}, {"broken.jar", "missing.jar"})
        self.assertTrue(all(p["kind"] == "unreadable" for p in report["unfixed"]))
        self.assertIn("profile_snapshot", report)
        check_file = mods._jar_read_error
        def changing(path, **kwargs):
            (profile / "new.jar").write_bytes(jar("new", "1"))
            return check_file(path, **kwargs)
        with patch.object(mods, "_jar_read_error", side_effect=changing):
            report = mod_dependencies.run_dependency_doctor("1.20.1", "fabric", version_id=meta["version_id"],
                auto_fix=False, check_online=False)
        self.assertEqual(report["unfixed"][0]["kind"], "profile-changed")

    def test_quilt_optional_integration_is_not_a_missing_pack_dependency(self):
        stream = io.BytesIO()
        with zipfile.ZipFile(stream, "w") as archive:
            archive.writestr("quilt.mod.json", json.dumps({"schema_version": 1,
                "quilt_loader": {"group": "dev.fixture", "id": "optional_user", "version": "1.0.0",
                    "metadata": {"name": "Optional integration"},
                    "depends": [{"id": "optional_integration", "versions": "*", "optional": True}]}}))
        meta = modpacks.install_modpack_from_file(self.pack(loader_kind="quilt",
            mods_spec=[("optional-user.jar", stream.getvalue())]))
        profile = mods.resolve_profile_dir("1.20.1", "quilt", meta["version_id"])
        # Cubeon's flattened descriptor view cannot express Quilt's optional
        # edge. The installed loader owns that rule for the curated pack.
        parsed = mods.read_mod_metadata(os.path.join(profile, "optional-user.jar"), "quilt")
        self.assertIn("optional_integration", parsed["depends"])
        report = mod_dependencies.run_dependency_doctor("1.20.1", "quilt",
            version_id=meta["version_id"], auto_fix=False, check_online=False)
        self.assertTrue(report["loader_managed"])
        self.assertFalse(report["unfixed"])

    def test_pack_crc_checks_reuse_unchanged_files_and_detect_same_size_edits(self):
        meta = modpacks.install_modpack_from_file(self.pack())
        profile = Path(mods.resolve_profile_dir("1.20.1", "fabric", meta["version_id"]))
        check = lambda: mod_dependencies.run_dependency_doctor("1.20.1", "fabric",
            version_id=meta["version_id"], auto_fix=False, check_online=False)
        self.assertFalse(check()["unfixed"])
        with patch.object(zipfile.ZipFile, "testzip", side_effect=AssertionError("verified bytes reread")):
            self.assertFalse(check()["unfixed"])
        path = profile / "same.jar"
        stat = path.stat()
        corrupt = bytearray(path.read_bytes())
        with zipfile.ZipFile(io.BytesIO(corrupt)) as archive:
            entry = archive.infolist()[0]
            offset = entry.header_offset + 30 + len(entry.filename.encode()) + len(entry.extra)
        corrupt[offset] ^= 1
        path.write_bytes(corrupt)
        os.utime(path, ns=(stat.st_atime_ns, stat.st_mtime_ns))
        report = check()
        self.assertEqual(report["unfixed"][0]["mod"], "same.jar")
        self.assertIn("checksum", report["unfixed"][0]["detail"])

    def test_temporary_file_lock_does_not_poison_the_archive_check_cache(self):
        path = self.root / "temporarily-locked.jar"
        path.write_bytes(jar("temporary", "1"))
        before = path.stat()
        with patch.object(zipfile.ZipFile, "testzip", side_effect=[OSError("temporarily locked"), None]) as verify:
            self.assertIn("temporarily locked", mods._jar_read_error(str(path), check_contents=True))
            self.assertEqual(mods._jar_read_error(str(path), check_contents=True), "")
        self.assertEqual(verify.call_count, 2)
        after = path.stat()
        self.assertEqual((before.st_size, before.st_mtime_ns, before.st_ctime_ns),
                         (after.st_size, after.st_mtime_ns, after.st_ctime_ns))

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
