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
import build_rust_engine
import fetch_rust_build_inputs
from publish_rust_beta import verify_archive


def bundle(directory, *, manifest=None):
    directory.mkdir(parents=True)
    files = {}
    for name in (rust._exe("cubeon-rust"), rust._exe("cubeon-rust-prepare"),
                 "research-lock.json", "LICENSE", "exporters/manifest.json"):
        path = directory / name
        path.parent.mkdir(parents=True, exist_ok=True)
        if name == "research-lock.json" and manifest is not None:
            path.write_text(json.dumps({"minecraft": {
                "version": rust.VERSION,
                "manifest_sha1": hashlib.sha1(manifest).hexdigest(),
                "accepted_manifest_sha1": [],
            }}))
        else:
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

    def test_packaged_profiles_keep_hashes_notices_and_exclude_game_assets(self):
        binaries = self.home / "binaries"
        binaries.mkdir()
        for name in (rust._exe("cubeon-rust"), rust._exe("cubeon-rust-prepare")):
            (binaries / name).write_bytes(b"owned executable fixture")
        exporters = self.home / "exporters"
        classes = exporters / "client/dev/cubeonlab/parity"
        classes.mkdir(parents=True)
        (classes / "Fixture.class").write_bytes(b"original class fixture")
        (exporters / "manifest.json").write_text("{}")
        (exporters / "minecraft-assets.png").write_bytes(b"must not ship")
        for profile in ("fast", "release"):
            with self.subTest(profile=profile):
                destination = self.home / profile / rust.platform_tag()
                build_rust_engine.package(binaries, exporters, destination, build_profile=profile)
                metadata = json.loads((destination / "cubeon-runtime.json").read_text())
                self.assertEqual(metadata["build_profile"], profile)
                self.assertTrue(rust._runtime_valid(destination))
                for notice in ("LICENSE", "THIRD_PARTY_NOTICES.md"):
                    self.assertEqual((destination / notice).read_bytes(),
                                     (build_rust_engine.SOURCE / notice).read_bytes())
                self.assertFalse((destination / "exporters/minecraft-assets.png").exists())
                item = build_rust_engine.archive_bundle(destination)
                verify_archive(destination.parent / item["url"].rsplit("/", 1)[-1], rust.platform_tag())

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

    def test_launch_refreshes_verified_local_rebuild_without_touching_settings(self):
        target = rust.runtime_dir()
        bundle(target)
        checkout = self.home / "checkout"
        local = checkout / "build/rust-engine" / rust.platform_tag()
        bundle(local)
        executable = local / rust._exe("cubeon-rust")
        executable.write_bytes(b"new native build")
        manifest = local / "cubeon-runtime.json"
        data = json.loads(manifest.read_text())
        data["files"][executable.name] = hashlib.sha256(executable.read_bytes()).hexdigest()
        manifest.write_text(json.dumps(data))
        resources = rust.resources_dir()
        resources.mkdir(parents=True)
        (resources / "cubeon-prepare.json").write_text("{}")
        (rust.root() / "instance.json").write_text(json.dumps(
            {"engine": "rust", "minecraft": rust.VERSION, "build": rust.BUILD}))
        options = Path(rust.game_dir(create=True)) / "options.txt"
        options.write_text("renderDistance:18\nenableVsync:true\n")
        with patch.object(rust, "__file__", str(checkout / "cubeon/rust_engine.py")), \
                patch.object(rust, "_run", return_value=0), \
                patch.object(rust.net, "get_json", side_effect=AssertionError("Launch must stay offline")):
            command = rust.launch_command("Tester", 854, 480)
            self.assertEqual(Path(command[0]).read_bytes(), b"new native build")
            self.assertEqual(options.read_text(), "renderDistance:18\nenableVsync:true\n")
            executable.write_bytes(b"damaged local build")
            self.assertEqual(rust.launch_command("Tester", 854, 480), command)
            self.assertEqual(Path(command[0]).read_bytes(), b"new native build")

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
        self.assertTrue(rust._official_url("https://piston-meta.mojang.com/v1/packages/hash/26.3.json"))
        self.assertFalse(rust._official_url("https://piston-data.mojang.com.attacker.test/file"))
        self.assertFalse(rust._official_url("https://piston-meta.mojang.com.attacker.test/file"))
        self.assertFalse(rust._official_url("http://piston-meta.mojang.com/file"))
        self.assertFalse(rust._official_url("https://user@piston-meta.mojang.com/file"))
        self.assertFalse(rust._official_url("https://piston-meta.mojang.com:444/file"))
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
        bundle(runtime, manifest=(version_dir / "26.3.json").read_bytes())
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

    def test_republished_manifest_uses_pinned_input_and_reuses_its_cache(self):
        runtime = rust.runtime_dir()
        inputs = self.home / "game-inputs"
        version_dir = inputs / "versions/26.3"
        version_dir.mkdir(parents=True)
        server_jar = rust.root() / "inputs/server-26.3.jar"
        server_jar.parent.mkdir(parents=True)
        server_jar.write_bytes(b"verified cached server")
        info = {"id": rust.VERSION, "javaVersion": {"majorVersion": 25},
                "assetIndex": {"id": "34", "sha1": "a" * 40},
                "downloads": {"server": {
                    "url": "https://piston-data.mojang.com/fixture/server.jar",
                    "sha1": hashlib.sha1(server_jar.read_bytes()).hexdigest()}}}
        pinned = json.dumps(info).encode()
        checksum = hashlib.sha1(pinned).hexdigest()
        bundle(runtime, manifest=pinned)
        info["assetIndex"]["sha1"] = "b" * 40  # Mojang's newer translations
        source = version_dir / "26.3.json"
        source.write_text(json.dumps(info))
        newer = source.read_bytes()
        commands = []

        def download(destination, url, **kwargs):
            self.assertEqual(url, f"https://piston-meta.mojang.com/v1/packages/{checksum}/26.3.json")
            self.assertEqual(kwargs["expected_hash"], ("sha1", checksum))
            self.assertTrue(kwargs["url_validator"](url))
            kwargs["cancel_check"]()
            Path(destination).write_bytes(pinned)

        def prepare(command, **kwargs):
            commands.append(command)
            stage = Path(command[command.index("--output") + 1])
            if "--check" in command:
                return 0 if (stage / "cubeon-prepare.json").is_file() else 1
            manifest = Path(command[command.index("--version-json") + 1])
            self.assertEqual(hashlib.sha1(manifest.read_bytes()).hexdigest(), checksum)
            stage.mkdir()
            (stage / "cubeon-prepare.json").write_text("{}")
            return 0

        with patch.object(paths, "MINECRAFT_DIR", str(inputs)), \
                patch.object(versions, "install_version") as install_java, \
                patch.object(rust, "_install_runtime", return_value=runtime), \
                patch.object(rust, "_run", side_effect=prepare), \
                patch.object(rust, "_find_preparation_java", return_value=str(self.home / "jdk/bin/java")), \
                patch.object(rust.net, "download_to", side_effect=download) as fetch:
            rust.install()
            self.assertTrue(install_java.call_args.kwargs["explicit_java"])
            self.assertEqual(fetch.call_count, 1)
            manifest = rust._preparation_manifest(runtime, source)
            self.assertEqual(fetch.call_count, 1, "Verified metadata cache should work offline")
        self.assertEqual(manifest.read_bytes(), pinned)
        self.assertEqual(source.read_bytes(), newer, "Shared Java metadata must stay current")
        self.assertFalse(rust.installed_entries()[0]["incomplete"])
        command = next(command for command in commands if "--prepare" in command)
        self.assertEqual(command[command.index("--minecraft-dir") + 1], str(inputs))

    def test_preparation_reuses_all_accepted_local_manifests_without_network(self):
        runtime = rust.runtime_dir()
        source = self.home / "26.3.json"
        pinned = b'{"id":"26.3","assetIndex":{"id":"34","sha1":"old"}}'
        republished = pinned.replace(b"old", b"new")
        bundle(runtime, manifest=pinned)
        lock = runtime / "research-lock.json"
        info = json.loads(lock.read_text())
        info["minecraft"]["accepted_manifest_sha1"] = [hashlib.sha1(republished).hexdigest()]
        lock.write_text(json.dumps(info))
        with patch.object(rust.net, "download_to", side_effect=AssertionError("Known files must stay offline")):
            for data in (pinned, republished):
                source.write_bytes(data)
                self.assertEqual(rust._preparation_manifest(runtime, source), source)

    def test_failed_preparation_metadata_keeps_existing_resources_and_cancels(self):
        runtime = rust.runtime_dir()
        bundle(runtime, manifest=b'{"id":"26.3"}')
        inputs = self.home / "game-inputs"
        source = inputs / "versions/26.3/26.3.json"
        source.parent.mkdir(parents=True)
        source.write_text('{"id":"26.3","rewritten":true}')
        resources = rust.resources_dir()
        resources.mkdir(parents=True)
        old = resources / "existing-resource.txt"
        old.write_text("preserve on failure")
        with patch.object(paths, "MINECRAFT_DIR", str(inputs)), \
                patch.object(versions, "install_version"), \
                patch.object(rust, "_install_runtime", return_value=runtime), \
                patch.object(rust, "_run", return_value=1) as prepare, \
                patch.object(rust.net, "download_to", side_effect=rust.net.DownloadError("Offline")):
            with self.assertRaisesRegex(rust.net.DownloadError, "Offline"):
                rust.install()
            self.assertEqual(prepare.call_count, 1, "Preparation must wait for verified metadata")
        event = threading.Event()

        def cancel(destination, url, **kwargs):
            event.set()
            kwargs["cancel_check"]()

        with patch.object(rust.net, "download_to", side_effect=cancel):
            with self.assertRaisesRegex(rust.RustEngineError, "cancelled"):
                rust._preparation_manifest(runtime, source, cancel=event)
        self.assertEqual(old.read_text(), "preserve on failure")
        self.assertEqual(source.read_text(), '{"id":"26.3","rewritten":true}')
        self.assertFalse((rust.root() / "instance.json").exists())

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
        inputs = self.home / "game-inputs"
        version_dir = inputs / "versions/26.3"
        version_dir.mkdir(parents=True)
        server_data = b"verified server fixture"
        (version_dir / "26.3.json").write_text(json.dumps({"downloads": {"server": {
            "url": "https://piston-data.mojang.com/fixture/server.jar",
            "sha1": hashlib.sha1(server_data).hexdigest()}}}))
        bundle(runtime, manifest=(version_dir / "26.3.json").read_bytes())
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
                patch.object(rust, "_install_runtime", return_value=runtime), \
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
        online_requests = []
        p = VersionPicker(DriverPage(), get_selected=lambda: None, label_for=lambda v: v,
                          on_pick=lambda _: self.fail("Must commit through New instance"),
                          loaders=[("vanilla", "Vanilla"), ("rust", "Rust · Beta")],
                          on_browse_online=lambda: online_requests.append("fetch"),
                          get_supported_versions=lambda _: self.fail("Rust has no Java loader"),
                          on_create=lambda *args: committed.append(args))
        p._browse()
        self.assertEqual(online_requests, ["fetch"])  # the initial Vanilla catalogue
        p._set_install_loader("rust")
        p._next()
        self.assertEqual(online_requests, ["fetch"], "Rust must stay offline")
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


class RustBuildInputTests(unittest.TestCase):
    def setUp(self):
        import minecraft_launcher_lib as mll
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.manifest = self.root / "build/rust-inputs/versions/26.3/26.3.json"
        self.server = b"pinned server resource fixture"
        self.server_url = "https://piston-data.mojang.com/fixture/server.jar"
        self.original = json.dumps({"id": "26.3", "assetIndex": {"id": "34"}, "downloads": {"server": {
            "url": self.server_url, "sha1": hashlib.sha1(self.server).hexdigest()}}}).encode()
        self.pinned = hashlib.sha1(self.original).hexdigest()
        self.accepted = self.original.replace(b'"34"', b'"35"')
        lock = self.root / "native/cubeon-rust/research-lock.json"
        lock.parent.mkdir(parents=True)
        lock.write_text(json.dumps({"minecraft": {"version": "26.3", "manifest_sha1": self.pinned,
            "accepted_manifest_sha1": [hashlib.sha1(self.accepted).hexdigest()],
            "server_sha1": hashlib.sha1(self.server).hexdigest()}}))
        for context in (patch.object(fetch_rust_build_inputs, "ROOT", self.root),
                        patch.object(mll.install, "install_minecraft_version", side_effect=self.install)):
            context.start()
            self.addCleanup(context.stop)

    def install(self, version, directory, **kwargs):
        self.assertEqual(version, "26.3")
        self.assertEqual(Path(directory), self.root / "build/rust-inputs")
        self.assertIn(self.manifest.read_bytes(), (self.original, self.accepted),
                      "Libraries and assets must resolve from an accepted manifest")

    def download(self, destination, url, **kwargs):
        data = self.server if url == self.server_url else self.original
        self.assertEqual(kwargs["expected_hash"], ("sha1", hashlib.sha1(data).hexdigest()))
        self.assertTrue(kwargs["url_validator"](url))
        Path(destination).write_bytes(data)

    def test_fresh_and_republished_inputs_use_the_pin_before_installing(self):
        for existing in (None, b'{"id":"26.3","rewritten":true}'):
            with self.subTest(existing=existing):
                if self.manifest.exists():
                    self.manifest.unlink()
                if existing is not None:
                    self.manifest.parent.mkdir(parents=True, exist_ok=True)
                    self.manifest.write_bytes(existing)
                with patch.object(fetch_rust_build_inputs.net, "download_to", side_effect=self.download) as download:
                    fetch_rust_build_inputs.main()
                self.assertEqual([call.args[1] for call in download.call_args_list], [
                    f"https://piston-meta.mojang.com/v1/packages/{self.pinned}/26.3.json", self.server_url])
                self.assertEqual(self.manifest.read_bytes(), self.original)

    def test_all_accepted_cached_inputs_skip_the_manifest_download(self):
        self.manifest.parent.mkdir(parents=True)
        for data in (self.original, self.accepted):
            with self.subTest(checksum=hashlib.sha1(data).hexdigest()):
                self.manifest.write_bytes(data)
                with patch.object(fetch_rust_build_inputs.net, "download_to", side_effect=self.download) as download:
                    fetch_rust_build_inputs.main()
                self.assertEqual([call.args[1] for call in download.call_args_list], [self.server_url])
                self.assertEqual(self.manifest.read_bytes(), data)

    def test_an_installer_rewrite_cannot_bypass_the_source_pin(self):
        import minecraft_launcher_lib as mll
        def rewrite(*args, **kwargs):
            self.manifest.write_bytes(b'{"id":"26.3","rewritten":true}')
        with patch.object(fetch_rust_build_inputs.net, "download_to", side_effect=self.download) as download, \
                patch.object(mll.install, "install_minecraft_version", side_effect=rewrite):
            with self.assertRaisesRegex(RuntimeError, "Mojang manifest changed"):
                fetch_rust_build_inputs.main()
        self.assertEqual(download.call_count, 1, "Unverified inputs cannot publish a server JAR")


if __name__ == "__main__":
    unittest.main()
