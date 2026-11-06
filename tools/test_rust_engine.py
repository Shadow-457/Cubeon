"""Rust beta install safety, native routing and existing instance picker behavior."""
import ast
import contextlib
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import rust_engine as rust, paths, launch, versions, watchdog
from ui.versions import VersionPicker
from app_driver import DriverPage


def bundle(directory):
    directory.mkdir(parents=True)
    files = {}
    for name in (rust._exe("cubeon-rust"), rust._exe("cubeon-rust-prepare"),
                 "research-lock.json", "LICENSE", "exporters/manifest.json"):
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("test fixture")
        files[name] = hashlib.sha256(path.read_bytes()).hexdigest()
    (directory / "cubeon-runtime.json").write_text(json.dumps(
        {"engine": "rust", "build": rust.BUILD, "minecraft": rust.VERSION, "files": files}))


class RustEngineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name)
        self.patch = patch.object(paths, "CUBEON_HOME", str(self.home / "launcher"))
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_paths_are_separate_and_reject_symlinks(self):
        native = Path(paths.game_dir_for(rust.INSTANCE_ID, create=False))
        self.assertEqual(native, rust.root() / "instances/26.3")
        self.assertFalse(native.exists())
        self.assertFalse(native.is_relative_to(Path(paths.MINECRAFT_DIR)))
        Path(rust.game_dir(create=True)).mkdir(exist_ok=True)
        self.assertTrue((native / "saves").is_dir())
        if os.name != "nt":
            (rust.root() / "builds").symlink_to(self.home, target_is_directory=True)
            with self.assertRaises(rust.RustEngineError):
                rust.runtime_dir()

    def test_runtime_hashes_and_required_manifest_members(self):
        directory = self.home / "bundle"
        bundle(directory)
        self.assertTrue(rust._runtime_valid(directory))
        (directory / rust._exe("cubeon-rust")).write_text("damaged")
        self.assertFalse(rust._runtime_valid(directory))
        self.assertTrue(rust._runtime_valid(directory, verify=False))
        info = json.loads((directory / "cubeon-runtime.json").read_text())
        del info["files"]["LICENSE"]
        (directory / "cubeon-runtime.json").write_text(json.dumps(info))
        self.assertFalse(rust._runtime_valid(directory, verify=False))

    def test_rebuilt_local_beta_replaces_an_older_verified_runtime(self):
        target = rust.runtime_dir()
        bundle(target)
        checkout = self.home / "checkout"
        local = checkout / "build/rust-engine" / rust.platform_tag()
        bundle(local)
        executable = local / rust._exe("cubeon-rust")
        executable.write_text("rebuilt offline engine")
        manifest = local / "cubeon-runtime.json"
        info = json.loads(manifest.read_text())
        info["files"][executable.name] = hashlib.sha256(executable.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(info))
        with patch.object(rust, "__file__", str(checkout / "cubeon/rust_engine.py")), \
                patch.object(rust.net, "get_json", side_effect=AssertionError("Local build must stay offline")):
            rust._install_runtime(None, lambda _: None, lambda _: None)
        self.assertEqual((target / executable.name).read_text(), "rebuilt offline engine")
        self.assertTrue(rust._runtime_valid(target))

    def test_missing_release_and_network_failures_are_distinct(self):
        checkout = self.home / "no-local-build"
        failures = [(rust.net.HTTPStatusError("Missing", 404), "not available yet"),
                    (rust.net.HTTPStatusError("Forbidden", 403), "metadata"),
                    (rust.net.DownloadError("Timed out"), "connection")]
        with patch.object(rust, "__file__", str(checkout / "cubeon/rust_engine.py")):
            for error, message in failures:
                with self.subTest(error=error), patch.object(rust.net, "get_json", side_effect=error):
                    with self.assertRaisesRegex(rust.RustEngineError, message):
                        rust._install_runtime(None, lambda _: None, lambda _: None)
        self.assertFalse(rust._runtime_valid(rust.runtime_dir()))

    def test_archive_traversal_and_links_are_rejected(self):
        for name in ("../escape", "/tmp/escape", "C:\\escape"):
            archive = self.home / "bad.zip"
            with zipfile.ZipFile(archive, "w") as z:
                z.writestr(name, b"unsafe")
            with self.assertRaises(rust.RustEngineError):
                rust._extract(archive, self.home / "stage")
        item = zipfile.ZipInfo("link")
        item.external_attr = 0o120777 << 16
        with zipfile.ZipFile(archive, "w") as z:
            z.writestr(item, "../outside")
        with self.assertRaises(rust.RustEngineError):
            rust._extract(archive, self.home / "stage")

    def test_cancellation_never_marks_install_ready(self):
        event = threading.Event()
        event.set()
        with patch.object(rust, "_install_runtime") as download:
            with self.assertRaisesRegex(rust.RustEngineError, "cancelled"):
                rust.install(cancel=event)
            download.assert_not_called()
        self.assertFalse((rust.root() / "instance.json").exists())
        self.assertNotIn(rust.INSTANCE_ID, versions.active_installs())

    def test_ready_install_uses_no_download_and_delete_preserves_worlds(self):
        runtime = rust.runtime_dir()
        bundle(runtime)
        resources = rust.resources_dir()
        resources.mkdir(parents=True)
        (resources / "cubeon-prepare.json").write_text("{}")
        with patch.object(rust, "_run", return_value=0), patch.object(rust.net, "get_json") as get:
            rust.install()
            get.assert_not_called()
        self.assertFalse(rust.installed_entries()[0]["incomplete"])
        world = Path(rust.game_dir()) / "saves/test.txt"
        world.write_text("world survives removal")
        rust.uninstall()
        self.assertEqual(rust.installed_entries(), [])
        self.assertTrue(world.exists())

    def test_earlier_verified_preparer_stamp_installs_and_launches(self):
        runtime = rust.runtime_dir()
        bundle(runtime)
        resources = rust.resources_dir()
        resources.mkdir(parents=True)
        (resources / "horizon-prepare.json").write_text('{"output_version":3}')
        with patch.object(rust, "_run", return_value=0) as check, \
                patch.object(rust.net, "get_json", side_effect=AssertionError("Ready beta must stay offline")):
            rust.install()
            self.assertFalse(rust.installed_entries()[0]["incomplete"])
            command = rust.launch_command("Tester", 854, 480)
        self.assertEqual(command[0], str(runtime / rust._exe("cubeon-rust")))
        self.assertEqual(check.call_count, 2)
        self.assertTrue(all("--check" in call.args[0] for call in check.call_args_list))

    def test_successful_check_without_resource_stamp_never_marks_installed(self):
        runtime = rust.runtime_dir()
        bundle(runtime)
        with patch.object(rust, "_run", return_value=0):
            with self.assertRaisesRegex(rust.RustEngineError, "did not finish"):
                rust.install()
        self.assertFalse((rust.root() / "instance.json").exists())

    def test_recognized_stamp_still_requires_native_resource_validation(self):
        runtime = rust.runtime_dir()
        bundle(runtime)
        resources = rust.resources_dir()
        resources.mkdir(parents=True)
        (resources / "horizon-prepare.json").write_text('{}')
        with patch.object(rust, "_run", return_value=0):
            rust.install()
        with patch.object(rust, "_run", side_effect=rust.RustEngineError("Resources failed validation")):
            with self.assertRaisesRegex(rust.RustEngineError, "failed validation"):
                rust.launch_command("Tester", 854, 480)

    def test_native_launch_skips_all_java_preparation(self):
        with contextlib.ExitStack() as stack:
            stack.enter_context(patch.object(watchdog, "stale_session", return_value=None))
            stack.enter_context(patch.object(rust, "launch_command", return_value=["native"]))
            spawn = stack.enter_context(patch.object(launch, "_spawn_game", return_value="process"))
            java = stack.enter_context(patch.object(launch, "build_launch_command", side_effect=AssertionError("Java called")))
            validation = stack.enter_context(patch.object(versions, "validate_launch_profile", side_effect=AssertionError("Java profile called")))
            result = launch.launch_game(rust.INSTANCE_ID, "Tester", 1024, 854, 480, None,
                                        mc_version="26.3", loader="rust", cfg={})
            self.assertEqual(result, "process")
            self.assertFalse(spawn.call_args.kwargs["stage_java"])
            self.assertEqual(spawn.call_args.args[5], "rust")
            self.assertEqual(spawn.call_args.kwargs["game_env"]["CUBEON_RUST_PLAYER_NAME"], "Tester")
            java.assert_not_called()
            validation.assert_not_called()

    def test_official_input_and_owned_release_hosts(self):
        self.assertTrue(rust._official_url("https://piston-data.mojang.com/v1/objects/hash/server.jar"))
        self.assertFalse(rust._official_url("https://piston-data.mojang.com.attacker.test/file"))
        self.assertFalse(rust._download_url("https://github.com/horizon-rust/horizon/releases/download/v/test"))
        self.assertTrue(rust._download_url(rust.RELEASE_BASE + "/runtime.zip"))
        with patch.dict(os.environ, {"HORIZON_SESSION": "secret", "LIBGL_ALWAYS_SOFTWARE": "1"}):
            env = rust.child_environment()
            self.assertNotIn("HORIZON_SESSION", env)
            self.assertNotIn("LIBGL_ALWAYS_SOFTWARE", env)

    def test_preparer_failure_timeout_and_cancellation(self):
        self.assertEqual(rust._run([sys.executable, "-c", "raise SystemExit(7)"], allow_failure=True), 7)
        with self.assertRaisesRegex(rust.RustEngineError, "failed"):
            rust._run([sys.executable, "-c", "print('fixture error'); raise SystemExit(7)"])
        with self.assertRaisesRegex(rust.RustEngineError, "timed out"):
            rust._run([sys.executable, "-c", "import time; time.sleep(10)"], timeout=0.15)

    def test_local_java_25_and_cached_server_skip_both_downloads(self):
        from cubeon import jre
        runtime = rust.runtime_dir()
        bundle(runtime)
        java_home = self.home / "jdks/jdk-25.0.4.1+1"
        java = java_home / "bin" / rust._exe("java")
        java.parent.mkdir(parents=True)
        java.write_text("local Java 25 fixture")
        (java_home / "release").write_text('JAVA_VERSION="25.0.4.1"\n')
        inputs = self.home / "game-inputs"
        version_dir = inputs / "versions/26.3"
        version_dir.mkdir(parents=True)
        server_jar = rust.root() / "inputs/server-26.3.jar"
        server_jar.parent.mkdir(parents=True)
        server_jar.write_bytes(b"verified cached server")
        (version_dir / "26.3.json").write_text(json.dumps({"downloads": {"server": {
            "url": "https://piston-data.mojang.com/fixture/server.jar",
            "sha1": hashlib.sha1(server_jar.read_bytes()).hexdigest()}}}))
        commands = []

        def prepare(command, **kwargs):
            commands.append(command)
            if "--check" in command:
                stage = Path(command[command.index("--output") + 1])
                return 0 if (stage / "cubeon-prepare.json").is_file() else 1
            stage = Path(command[command.index("--output") + 1])
            stage.mkdir()
            (stage / "cubeon-prepare.json").write_text("{}")
            return 0

        with patch.object(Path, "home", return_value=self.home), \
                patch.dict(os.environ, {"JAVA_HOME": ""}), \
                patch.object(paths, "MINECRAFT_DIR", str(inputs)), \
                patch.object(versions, "install_version"), \
                patch.object(rust, "_install_runtime", return_value=runtime), \
                patch.object(rust, "_run", side_effect=prepare), \
                patch.object(launch, "java_major_version", side_effect=lambda p: 25 if p == str(java) else 26), \
                patch.object(jre, "managed_java", return_value=None), \
                patch.object(jre, "install_jre") as download_java, \
                patch.object(rust.net, "download_to") as download_server:
            rust.install()
        download_java.assert_not_called()
        download_server.assert_not_called()
        command = next(command for command in commands if "--prepare" in command)
        self.assertEqual(command[command.index("--java-home") + 1], str(java_home))
        self.assertFalse(rust.installed_entries()[0]["incomplete"])

    def test_preparation_requires_exact_25_resolves_symlinks_and_cancels(self):
        from cubeon import jre
        binaries = {}
        for major in (21, 25, 26):
            java_home = self.home / f"jdk-{major}"
            java = java_home / "bin" / rust._exe("java")
            java.parent.mkdir(parents=True)
            java.touch()
            binaries[str(java)] = major
        java25 = self.home / "jdk-25/bin" / rust._exe("java")
        configured = self.home / "jdk-26"
        environment_home = self.home / "jdk-25"
        if os.name != "nt":
            environment_home = self.home / "current-jdk"
            environment_home.symlink_to(self.home / "jdk-25", target_is_directory=True)
        with patch.dict(os.environ, {"JAVA_HOME": str(environment_home)}), \
                patch.object(rust.shutil, "which", return_value=str(self.home / "jdk-21/bin" / rust._exe("java"))), \
                patch.object(launch, "java_major_version", side_effect=binaries.get) as probe, \
                patch.object(jre, "managed_java", side_effect=AssertionError("Must reuse JAVA_HOME first")):
            self.assertEqual(rust._find_preparation_java(str(configured)), str(java25))
            event = threading.Event()
            event.set()
            probe.reset_mock()
            with self.assertRaisesRegex(rust.RustEngineError, "cancelled"):
                rust._find_preparation_java(str(configured), cancel=event)
            probe.assert_not_called()

    def test_java_preparation_reports_its_own_progress_and_phase(self):
        from cubeon import jre
        runtime = rust.runtime_dir()
        bundle(runtime)
        inputs = self.home / "game-inputs"
        version_dir = inputs / "versions/26.3"
        version_dir.mkdir(parents=True)
        server_data = b"verified server fixture"
        (version_dir / "26.3.json").write_text(json.dumps({"downloads": {"server": {
            "url": "https://piston-data.mojang.com/fixture/server.jar",
            "sha1": hashlib.sha1(server_data).hexdigest()}}}))
        fractions, messages, maxima = [], [], []

        def download(destination, *args, **kwargs):
            Path(destination).write_bytes(server_data)

        def java_install(major, *, status_cb, progress_cb):
            self.assertEqual(major, 25)
            status_cb("Looking up Java 25")
            status_cb("Downloading Java 25 (58 MB)")
            progress_cb(5, 10)
            status_cb("Unpacking Java 25")
            return str(self.home / "java/bin/java")

        def prepare(command, **kwargs):
            if "--check" in command:
                stage = Path(command[command.index("--output") + 1])
                return 0 if (stage / "cubeon-prepare.json").is_file() else 1
            stage = Path(command[command.index("--output") + 1])
            stage.mkdir()
            (stage / "cubeon-prepare.json").write_text("{}")
            return 0

        with patch.object(paths, "MINECRAFT_DIR", str(inputs)), \
                patch.object(versions, "install_version"), \
                patch.object(rust, "_run", side_effect=prepare), \
                patch.object(rust.net, "download_to", side_effect=download), \
                patch.object(rust, "_find_preparation_java", return_value=None), \
                patch.object(jre, "install_jre", side_effect=java_install):
            rust.install(status_cb=messages.append, progress_cb=fractions.append, max_cb=maxima.append)
        self.assertIn(0.5, fractions)
        self.assertIn("Rust resource preparation · Downloading Java 25 (58 MB)", messages)
        self.assertGreaterEqual(len(maxima), 4)  # download/extraction have separate scales


class RustPickerTests(unittest.TestCase):
    def test_incomplete_rust_can_retry_from_the_selected_instance(self):
        tree = ast.parse((ROOT / "main.py").read_text())
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_sync_play_button")
        state = {"installed_meta": {
            rust.INSTANCE_ID: {"incomplete": True}, "26.3": {"incomplete": True}},
            "installed": {rust.INSTANCE_ID, "26.3"}}
        selected = SimpleNamespace(value=rust.INSTANCE_ID)
        modes = []
        scope = {"state": state, "version_dropdown": selected, "rust_engine": rust,
                 "set_button_mode": modes.append, "_pack_installing_selected": lambda: False,
                 "_fixing_selected": lambda: False}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<selected instance recovery>", "exec"), scope)
        scope["_sync_play_button"]()
        self.assertEqual(modes[-1], "download")
        selected.value = "26.3"
        scope["_sync_play_button"]()
        self.assertEqual(modes[-1], "incomplete")

    def test_existing_picker_offers_26_3_offline_and_commits_only_at_finish(self):
        committed = []
        p = VersionPicker(DriverPage(), get_selected=lambda: None, label_for=lambda v: v,
                          on_pick=lambda _: self.fail("Must commit through New instance"),
                          loaders=[("vanilla", "Vanilla"), ("rust", "Rust · Beta")],
                          on_browse_online=lambda: self.fail("Rust must not fetch loader versions"),
                          get_supported_versions=lambda _: self.fail("Rust has no Java loader"),
                          on_create=lambda *args: committed.append(args))
        p._browse()
        p._set_install_loader("rust")
        p._next()
        self.assertEqual([e["id"] for e in p._available_entries()], ["26.3"])
        self.assertFalse(p.filter_field.visible)
        self.assertFalse(p.retry_link.visible)
        self.assertTrue(p.install_hint.visible)
        p.set_offline()  # delayed Java request must not disable the native choice
        p._pick("1.21.1")
        self.assertIsNone(p._new_version)
        p._pick("26.3")
        self.assertFalse(p.next_button.disabled)
        p._next()
        self.assertEqual(committed, [])
        p._next()
        self.assertEqual(committed[0][:2], ("26.3", "rust"))

    def test_server_actions_guard_selected_native_and_restore_java(self):
        tree = ast.parse((ROOT / "ui/server_tab.py").read_text())
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == "_hosting_allowed")
        state = {"selected_version": rust.INSTANCE_ID}
        scope = {"state": state, "rust_engine": rust}
        exec(compile(ast.Module(body=[node], type_ignores=[]), "<server capability>", "exec"), scope)
        self.assertFalse(scope["_hosting_allowed"]("26.3"))
        state["selected_version"] = "26.3"
        self.assertTrue(scope["_hosting_allowed"]("26.3"))
        self.assertFalse(scope["_hosting_allowed"](rust.INSTANCE_ID))


if __name__ == "__main__":
    unittest.main()
