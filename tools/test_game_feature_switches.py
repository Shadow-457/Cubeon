"""Independent client/CSL opt-outs, reversible JARs and actual launch staging."""
from contextlib import ExitStack
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import atomicio, capes, cosmetics, csl, cubeonfriends, launch, mods, paths, perf_mods, storage, versions, watchdog


class GameFeatureSwitches(unittest.TestCase):
    def setUp(self):
        self.work = tempfile.TemporaryDirectory()
        self.addCleanup(self.work.cleanup)
        self.root = Path(self.work.name)
        self.profile = self.root / "profile"
        self.profile.mkdir()
        self.game = self.root / "staged-mods"
        self.patches = ExitStack()
        self.addCleanup(self.patches.close)
        for name in ("get_profile_dir", "resolve_profile_dir"):
            self.patches.enter_context(patch.object(mods, name, return_value=str(self.profile)))
        self.patches.enter_context(patch.object(mods, "MODS_DIR", str(self.game)))

    def jar(self, name, identity="customskinloader", *, directory=None, version="1.0"):
        dest = (directory or self.profile) / name
        with zipfile.ZipFile(dest, "w") as jar:
            jar.writestr("fabric.mod.json", json.dumps({"id": identity, "version": version}))
        return dest

    def toggle(self, enabled):
        return csl.set_enabled("1.20", "fabric", enabled, version_id="selected")

    def test_existing_and_renamed_csl_stop_loading_and_restore_with_identical_bytes(self):
        for name in ("CustomSkinLoader-1.0.jar", "renamed.jar"):
            with self.subTest(name=name):
                jar = self.jar(name)
                original = jar.read_bytes()
                self.assertTrue(csl.is_installed("1.20", "fabric", "selected"))
                self.assertEqual(self.toggle(False), 1)
                self.assertFalse(csl.is_installed("1.20", "fabric", "selected"))
                self.assertEqual(self.toggle(False), 0)
                self.assertEqual(self.toggle(True), 1)
                self.assertEqual(jar.read_bytes(), original)
                jar.unlink()

    def test_manual_disabled_csl_and_other_mods_remain_untouched(self):
        manual = self.jar("CustomSkinLoader-manual.jar.disabled")
        other = self.jar("sodium.jar", "sodium")
        stamps = [file.stat().st_mtime_ns for file in (manual, other)]
        self.assertEqual(self.toggle(False), 0)
        self.assertEqual(self.toggle(True), 0)
        self.assertEqual(stamps, [file.stat().st_mtime_ns for file in (manual, other)])

    def test_disabled_filename_collision_preserves_both_copies(self):
        old = self.jar("CustomSkinLoader.jar.disabled", version="old").read_bytes()
        new = self.jar("CustomSkinLoader.jar", version="new").read_bytes()
        self.toggle(False)
        self.toggle(True)
        self.assertEqual((self.profile / "CustomSkinLoader.jar.disabled").read_bytes(), old)
        self.assertEqual((self.profile / "CustomSkinLoader.jar").read_bytes(), new)

    def test_reinstall_while_off_restores_latest_copy_without_overwriting_old_backup(self):
        old = self.jar("CustomSkinLoader.jar", version="old").read_bytes()
        self.toggle(False)
        new = self.jar("CustomSkinLoader.jar", version="new").read_bytes()
        self.toggle(False)
        self.toggle(False)
        self.toggle(True)
        self.assertEqual((self.profile / "CustomSkinLoader.jar").read_bytes(), new)
        self.assertEqual((self.profile / "CustomSkinLoader.jar.disabled").read_bytes(), old)

    def test_new_active_csl_prevents_restoring_an_obsolete_duplicate(self):
        self.jar("CustomSkinLoader-old.jar")
        self.toggle(False)
        self.jar("new.jar", version="2.0")
        self.assertEqual(self.toggle(True), 0)
        self.assertFalse((self.profile / "CustomSkinLoader-old.jar").exists())
        self.assertTrue((self.profile / "new.jar").exists())

    def test_move_failure_rolls_back_and_retry_can_disable(self):
        first = self.jar("CustomSkinLoader-a.jar")
        second = self.jar("CustomSkinLoader-b.jar")
        replace = os.replace

        def fail_second(source, target):
            if str(source) == str(second):
                raise PermissionError("file locked")
            return replace(source, target)

        with patch.object(csl.os, "replace", side_effect=fail_second):
            with self.assertRaises(PermissionError):
                self.toggle(False)
        self.assertTrue(first.exists() and second.exists())
        self.assertEqual(self.toggle(False), 2)

    def test_bad_marker_refuses_paths_before_any_mutation(self):
        for record in ([{"enabled": "../other.jar", "disabled": "other.jar.disabled"}],
                       [{"enabled": "C:other.jar", "disabled": "other.jar.disabled"}], "wrong"):
            with self.subTest(record=record):
                atomicio.write_json(str(self.profile / ".cubeon-csl-disabled.json"), {"jars": record})
                jar = self.jar("CustomSkinLoader.jar")
                with self.assertRaises(ValueError):
                    self.toggle(False)
                self.assertTrue(jar.exists())

    def test_only_selected_profile_and_links_change(self):
        other = self.root / "other"
        other.mkdir()
        source = self.jar("shared.jar", directory=other)
        linked = self.profile / "renamed.jar"
        try:
            linked.symlink_to(source)
        except OSError:
            os.link(source, linked)
        original = source.read_bytes()
        self.toggle(False)
        self.toggle(True)
        self.assertEqual(source.read_bytes(), original)
        self.assertEqual(linked.read_bytes(), original)

    def test_client_opt_out_finds_legacy_and_renamed_copies(self):
        self.jar("cubeon-client-1.jar", "cubeon-client")
        self.jar("cubeon-friends-1.jar", "cubeon-friends")
        self.jar("renamed-client.jar", "cubeon-client")
        other = self.jar("other.jar", "other")
        cubeonfriends.remove_installed(str(self.profile), strict=True)
        self.assertEqual(list(self.profile.glob("*.jar")), [other])

    def play(self, cfg, *, skin_order=None, real_client=False, version="selected", mc_version="1.20"):
        with ExitStack() as stack:
            sync_skin = (lambda _cfg: skin_order.append("sync")) if skin_order is not None else None
            for obj, name, value in ((versions, "validate_launch_profile", None),
                                     (watchdog, "stale_session", None),
                                     (launch, "game_dir_for", str(self.root)),
                                     (launch, "save_config", None),
                                     (capes, "sync_local_cape_to_csl", None),
                                     (cosmetics, "sync_to_game", None),
                                     (perf_mods, "retire_legacy_more_culling", []),
                                     (perf_mods, "ensure_installed", {"installed": [], "failed": [], "detail": ""}),
                                     (perf_mods, "prune_retired_perf_mods", []),
                                     (perf_mods, "seed_renderer_options", []),
                                     (launch, "build_launch_command", ["java"])):
                stack.enter_context(patch.object(obj, name, return_value=value))
            stack.enter_context(
                patch.object(launch, "sync_local_skin_to_csl", side_effect=sync_skin)
                if sync_skin is not None
                else patch.object(launch, "sync_local_skin_to_csl", return_value=None))
            if skin_order is not None:
                stack.enter_context(patch.object(
                    csl, "ensure_ready",
                    side_effect=lambda *args, **kwargs: (
                        skin_order.append("setup") or
                        {"installed": True, "registered": True, "detail": ""})))
            client = stack.enter_context(patch.object(cubeonfriends, "ensure_installed",
                **({"wraps": cubeonfriends.ensure_installed} if real_client else {"return_value": True})))
            api = stack.enter_context(patch.object(cubeonfriends, "ensure_fabric_api", return_value="installed"))
            download = stack.enter_context(patch.object(csl, "install", side_effect=AssertionError("Unexpected CSL download")))
            def stage(_command, _game_dir, version, _username, mc, loader, **_kwargs):
                mods.sync_mods_to_game(mc, loader, version_id=version)
            spawn = stack.enter_context(patch.object(launch, "_spawn_game", side_effect=stage))
            launch.launch_game(version, "Tester", 2048, 854, 480, None,
                               mc_version=mc_version, loader="fabric", cfg=cfg)
            self.assertEqual(spawn.call_args.kwargs["configured_java"], cfg.get("java_path"))
            return client.call_count, api.call_count, download.call_count, spawn.call_count

    def test_both_off_removes_previously_staged_jars_and_does_not_install_them(self):
        self.jar("CustomSkinLoader.jar")
        self.jar("cubeon-client-1.jar", "cubeon-client")
        self.jar("other.jar", "other")
        mods.sync_mods_to_game("1.20", "fabric", version_id="selected")
        self.assertEqual(self.play({"csl_enabled": False, "client_mod_enabled": False,
                                    "java_path": "configured-java"}), (0, 0, 0, 1))
        self.assertEqual([p.name for p in self.game.glob("*.jar")], ["other.jar"])
        self.assertTrue((self.profile / "CustomSkinLoader.jar.disabled").exists())

    def test_switches_are_independent_on_launch(self):
        self.jar("CustomSkinLoader.jar")
        self.jar("cubeon-client-1.jar", "cubeon-client")
        client, api, _, _ = self.play({"csl_enabled": False, "client_mod_enabled": True,
                                      "perf_mods_enabled": False})
        self.assertEqual((client, api), (1, 1))
        self.assertTrue((self.game / "cubeon-client-1.jar").exists())
        self.assertFalse((self.game / "CustomSkinLoader.jar").exists())
        self.play({"csl_enabled": True, "client_mod_enabled": False})
        self.assertTrue((self.game / "CustomSkinLoader.jar").exists())
        self.assertFalse((self.game / "cubeon-client-1.jar").exists())

    def test_settings_backup_does_not_override_a_manual_disabled_copy(self):
        self.jar("CustomSkinLoader.jar")
        self.toggle(False)
        self.assertTrue(csl.disabled_by_setting(str(self.profile)))
        self.jar("CustomSkinLoader-manual.jar.disabled")
        self.assertFalse(csl.disabled_by_setting(str(self.profile)))
        self.play({"csl_enabled": True, "client_mod_enabled": False})
        self.assertFalse((self.game / "CustomSkinLoader.jar").exists())

    def test_pack_skin_opt_in_restores_only_cubeon_settings_backups(self):
        atomicio.write_json(str(self.profile / "_modpack.json"), {"name": "Curated Pack"})
        skin = self.jar("CustomSkinLoader-pinned.jar")
        library = self.jar("library-pinned.jar", "library")
        before = {p.name: p.read_bytes() for p in (skin, library)}
        self.play({"csl_enabled": False, "client_mod_enabled": False})
        self.assertFalse(skin.exists())
        self.play({"csl_enabled": True, "client_mod_enabled": False})
        self.assertEqual(before, {p.name: p.read_bytes() for p in (skin, library)})
        self.assertEqual((self.game / skin.name).read_bytes(), before[skin.name])
        self.toggle(False)
        manual = self.jar("CustomSkinLoader-manual.jar.disabled")
        manual_bytes = manual.read_bytes()
        self.play({"csl_enabled": True, "client_mod_enabled": False})
        self.assertFalse(skin.exists())
        self.assertEqual(manual.read_bytes(), manual_bytes)

    def test_locked_jar_blocks_spawn_instead_of_ignoring_opt_out(self):
        for name, identity, message in (("CustomSkinLoader.jar", "customskinloader", "CustomSkinLoader setting"),
                                        ("cubeon-client-1.jar", "cubeon-client", "disable Cubeon Client")):
            with self.subTest(identity=identity):
                jar = self.jar(name, identity)
                if identity == "customskinloader":
                    failure = patch.object(csl, "set_enabled", side_effect=PermissionError("locked"))
                else:
                    original_replace = os.replace
                    def replace_client(source, target):
                        if Path(source) == jar:
                            raise PermissionError("locked")
                        return original_replace(source, target)
                    failure = patch.object(cubeonfriends.os, "replace", side_effect=replace_client)
                with failure, patch.object(launch, "_spawn_game") as spawn:
                    with self.assertRaisesRegex(RuntimeError, message):
                        self.play({"csl_enabled": False, "client_mod_enabled": False})
                    spawn.assert_not_called()
                self.assertTrue(jar.exists())
                jar.unlink()

    def test_skin_setup_precedes_the_final_first_launch_sync(self):
        self.jar("CustomSkinLoader.jar")
        order = []
        self.play({"csl_enabled": True, "client_mod_enabled": False,
                   "manage_skin_mod": True}, skin_order=order)
        self.assertEqual(order, ["setup", "sync"])

    def test_client_switch_restores_appearance_support_in_registered_26_3_instance(self):
        with patch.object(paths, "MINECRAFT_DIR", str(self.root / "registered")):
            storage.initialize()
            version = "fabric-loader-0.20.1-26.3"
            profile = Path(storage.game_dir(version, create=True)) / "mods"
            client = self.jar("cubeon-client-pinned.jar", "cubeon-client", directory=profile)
            original = client.read_bytes()
            storage.record_installed_file(str(client))
            marker = storage.metadata_path(str(profile), "_modpack.json")
            atomicio.write_json(marker, {"name": "Curated Pack"})
            with patch.object(mods, "get_profile_dir", return_value=str(profile)), \
                    patch.object(mods, "resolve_profile_dir", return_value=str(profile)):
                cfg = {"csl_enabled": False, "perf_mods_enabled": False, "fps_boost_enabled": False}
                self.play({**cfg, "client_mod_enabled": False}, version=version, mc_version="26.3")
                self.assertFalse(client.exists())
                self.play({**cfg, "client_mod_enabled": True}, version=version, mc_version="26.3",
                          real_client=True)
            self.assertEqual(client.read_bytes(), original)

    def test_explicit_client_install_repairs_a_legacy_removal_receipt(self):
        with patch.object(paths, "MINECRAFT_DIR", str(self.root / "registered")):
            storage.initialize()
            version = "fabric-loader-0.20.1-26.3"
            profile = Path(storage.game_dir(version, create=True)) / "mods"
            client = self.jar("cubeon-client-old.jar", "cubeon-client", directory=profile)
            storage.record_installed_file(str(client))
            client.unlink()
            self.assertFalse(cubeonfriends.ensure_installed("26.3", "fabric", str(profile),
                                                            automatic=True, version_id=version))
            self.assertTrue(cubeonfriends.ensure_installed("26.3", "fabric", str(profile),
                                                           version_id=version))
            self.assertFalse(storage.managed_removed(str(profile), "cubeon-client-"))

    def test_renamed_client_restore_keeps_one_copy_and_manual_disable(self):
        profile = str(self.profile)
        client = self.jar("my-client.jar", "cubeon-client")
        cubeonfriends.set_enabled(profile, "fabric", False)
        self.assertFalse(client.exists())
        cubeonfriends.set_enabled(profile, "fabric", True)
        self.assertTrue(cubeonfriends.ensure_installed("26.3", "fabric", profile, automatic=True))
        self.assertEqual(list(self.profile.glob("*.jar")), [client])

        disabled = client.with_suffix(".jar.disabled")
        client.rename(disabled)
        cubeonfriends.set_enabled(profile, "fabric", True)
        self.assertFalse(cubeonfriends.ensure_installed("26.3", "fabric", profile, automatic=True))
        self.assertTrue(disabled.exists())

    def test_disabled_fabric_api_does_not_count_as_loaded(self):
        self.jar("fabric-api-0.167.0+26.3.jar.disabled", "fabric-api")
        self.jar("fabric-api-base-2.0.6.jar", "fabric-api-base")
        self.assertFalse(cubeonfriends.fabric_api_installed("26.3", "fabric", "selected"))
        detail = cubeonfriends.ensure_fabric_api("26.3", "fabric", version_id="selected")
        self.assertIn("disabled", detail)
        self.assertFalse((self.profile / "fabric-api-0.167.0+26.3.jar").exists())


if __name__ == "__main__":
    unittest.main()
