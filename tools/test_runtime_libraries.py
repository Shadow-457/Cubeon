"""Real ZIP fixtures for Fabric's truncated intermediary runtime dependency."""
from pathlib import Path
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import paths, storage, launch, versions, runtime_libraries as libraries


def jar_bytes(content=b"runtime class"):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("net/fabricmc/Fixture.class", content)
    return buffer.getvalue()


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        libraries._CACHE.clear()
        self.runtime = Path(storage.runtime_dir(paths.MINECRAFT_DIR))
        self.version = "fabric-loader-0.20.1-1.21.11"
        self.folder = self.runtime / "versions" / self.version
        self.folder.mkdir(parents=True, exist_ok=True)
        self.relative = "net/fabricmc/intermediary/1.21.11/intermediary-1.21.11.jar"
        self.jar = self.runtime / "libraries" / self.relative
        self.jar.parent.mkdir(parents=True, exist_ok=True)
        self.good = jar_bytes()
        self.jar.write_bytes(self.good[:-30])  # PK header intact, ZIP end absent.
        self.metadata = {"id": self.version, "libraries": [{
            "name": "net.fabricmc:intermediary:1.21.11", "url": "https://maven.fabricmc.net/"}]}
        self.write_metadata()
        self.command = ["java", "-cp", str(self.jar), "net.fabricmc.loader.impl.launch.knot.KnotClient"]

    def write_metadata(self):
        (self.folder / (self.version + ".json")).write_text(json.dumps(self.metadata))

    def download(self, path, url, **kwargs):
        self.assertEqual(url, "https://maven.fabricmc.net/" + self.relative)
        self.assertTrue(kwargs["url_validator"](url))
        Path(path).write_bytes(self.good)

    def test_zip_end_missing_repairs_without_checksum_then_stays_offline(self):
        with self.assertRaises(zipfile.BadZipFile):
            zipfile.ZipFile(self.jar)
        statuses = []
        with patch.object(libraries.net, "download_to", side_effect=self.download) as fetch:
            self.assertEqual(libraries.ensure(self.version, self.command, statuses.append), 1)
            self.assertEqual(self.jar.read_bytes(), self.good)
            self.assertEqual(libraries.ensure(self.version, self.command), 0)
        self.assertEqual(fetch.call_count, 1)
        self.assertIn(self.jar.name, statuses[0])

    def test_interrupted_or_invalid_replacement_preserves_old_bytes(self):
        before = self.jar.read_bytes()
        for response in (b"<html>bad gateway</html>", self.good[:-20]):
            with patch.object(libraries.net, "download_to", side_effect=lambda path, *a, **kw: Path(path).write_bytes(response)):
                with self.assertRaisesRegex(RuntimeError, "Couldn't repair intermediary"):
                    libraries.ensure(self.version, self.command)
            self.assertEqual(self.jar.read_bytes(), before)
        with patch.object(libraries.net, "download_to", side_effect=OSError("offline")):
            with self.assertRaisesRegex(RuntimeError, "Reconnect"):
                libraries.ensure(self.version, self.command)
        self.assertEqual(self.jar.read_bytes(), before)
        self.assertFalse(list(self.jar.parent.glob(".cubeon-library-*")))

    def test_classifier_only_library_has_no_plain_jar_to_fetch(self):
        # Mojang ships jinput-platform 2.0.5 with natives classifiers only: the plain
        # coordinate has no JAR at all, so the classpath entry must be left alone.
        self.jar.unlink()
        self.metadata["libraries"] = [{
            "name": "net.java.jinput:jinput-platform:2.0.5",
            "downloads": {"classifiers": {"natives-linux": {
                "path": "net/java/jinput/jinput-platform/2.0.5/jinput-platform-2.0.5-natives-linux.jar",
                "url": "https://libraries.minecraft.net/net/java/jinput/jinput-platform/2.0.5/jinput-platform-2.0.5-natives-linux.jar"}}}}]
        self.write_metadata()
        with patch.object(libraries.net, "download_to",
                          side_effect=AssertionError("fetched a coordinate with no artifact")):
            self.assertEqual(libraries.ensure(self.version, self.command), 0)
        self.assertFalse(self.jar.exists())

    def test_declared_empty_artifact_with_matching_checksum_is_intact(self):
        # Real Mojang artifact: lwjgl-platform 2.9.4-nightly-20150209 is 22 bytes, zero entries.
        empty = b"PK\x05\x06" + b"\x00" * 18
        self.assertEqual(len(empty), 22)
        self.jar.write_bytes(empty)
        self.metadata["libraries"][0]["downloads"] = {"artifact": {
            "url": "https://maven.fabricmc.net/" + self.relative,
            "sha1": hashlib.sha1(empty).hexdigest(), "size": len(empty)}}
        self.write_metadata()
        with patch.object(libraries.net, "download_to",
                          side_effect=AssertionError("repair fetched a declared artifact")):
            self.assertEqual(libraries.ensure(self.version, self.command), 0)
        self.assertEqual(self.jar.read_bytes(), empty)

    def test_checksum_detects_readable_but_wrong_library(self):
        self.metadata["libraries"][0]["downloads"] = {"artifact": {
            "url": "https://maven.fabricmc.net/" + self.relative,
            "sha1": hashlib.sha1(self.good).hexdigest(), "size": len(self.good)}}
        self.write_metadata()
        self.jar.write_bytes(jar_bytes(b"wrong content"))
        with patch.object(libraries.net, "download_to", side_effect=self.download):
            self.assertEqual(libraries.ensure(self.version, self.command), 1)

    def test_corruption_after_cached_success_is_rechecked(self):
        self.jar.write_bytes(self.good)
        self.assertEqual(libraries.ensure(self.version, self.command), 0)
        self.jar.write_bytes(self.good[:-5])
        with patch.object(libraries.net, "download_to", side_effect=self.download):
            self.assertEqual(libraries.ensure(self.version, self.command), 1)

    def test_crc_damage_with_intact_zip_directory_is_repaired(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w", zipfile.ZIP_STORED) as archive:
            archive.writestr("runtime.class", b"CRC test payload")
        data = buffer.getvalue().replace(b"CRC test payload", b"BAD test payload")
        self.jar.write_bytes(data)
        with zipfile.ZipFile(self.jar) as archive:
            self.assertEqual(archive.testzip(), "runtime.class")
        with patch.object(libraries.net, "download_to", side_effect=self.download):
            self.assertEqual(libraries.ensure(self.version, self.command), 1)

    def test_external_symlink_and_untrusted_sources_are_refused(self):
        outside = Path(paths.CUBEON_HOME) / "user.jar"
        outside.write_bytes(b"user data")
        self.jar.unlink()
        self.jar.symlink_to(outside)
        with patch.object(libraries.net, "download_to") as fetch:
            with self.assertRaisesRegex(RuntimeError, "outside"):
                libraries.ensure(self.version, self.command)
        fetch.assert_not_called()
        self.assertEqual(outside.read_bytes(), b"user data")
        self.jar.unlink()
        self.jar.write_bytes(b"damaged")
        self.metadata["libraries"][0]["url"] = "https://untrusted.example/"
        self.write_metadata()
        with patch.object(libraries.net, "download_to") as fetch:
            with self.assertRaisesRegex(RuntimeError, "not trusted"):
                libraries.ensure(self.version, self.command)
        fetch.assert_not_called()

    def test_missing_dependency_and_inherited_metadata(self):
        base = self.runtime / "versions" / "1.21.11"
        base.mkdir(parents=True, exist_ok=True)
        (base / "1.21.11.json").write_text(json.dumps(self.metadata))
        self.metadata = {"id": self.version, "inheritsFrom": "1.21.11", "libraries": []}
        self.write_metadata()
        self.jar.unlink()
        with patch.object(libraries.net, "download_to", side_effect=self.download):
            self.assertEqual(libraries.ensure(self.version, self.command), 1)
        external = Path(paths.CUBEON_HOME) / "custom-user.jar"
        external.write_bytes(b"user content")
        with patch.object(libraries.net, "download_to") as fetch:
            self.assertEqual(libraries.ensure(self.version, ["java", "-cp", str(external), "Custom"]), 0)
        fetch.assert_not_called()
        self.assertEqual(external.read_bytes(), b"user content")


class InheritedClient(unittest.TestCase):
    def setUp(self):
        work = tempfile.TemporaryDirectory()
        self.addCleanup(work.cleanup)
        self.runtime = Path(work.name)
        for module in (launch, versions):
            context = patch.object(module, "runtime_dir", return_value=str(self.runtime))
            context.start()
            self.addCleanup(context.stop)
        for name, value in (("find_java_for_version", "java"), ("java_major_version", 21),
                            ("required_java_major", 21), ("exact_java_major", None)):
            context = patch.object(launch, name, return_value=value)
            context.start()
            self.addCleanup(context.stop)
        self.base = self.profile("1.21.11", jar=True)
        self.ident = "fabric-loader-0.20.1-1.21.11"
        self.child = self.profile(self.ident, parent="1.21.11")

    def profile(self, ident, *, parent=None, jar=False, reference=None):
        directory = self.runtime / "versions" / ident
        directory.mkdir(parents=True)
        data = {"id": ident, "type": "release", "libraries": [],
                "mainClass": "net.fabricmc.loader.impl.launch.knot.KnotClient" if parent
                             else "net.minecraft.client.main.Main",
                "arguments": {"jvm": [] if parent else ["-cp", "${classpath}"],
                              "game": [] if parent else ["--version", "${version_name}"]}}
        if parent:
            data["inheritsFrom"] = parent
            data["libraries"] = [{"name": "net.fabricmc:fabric-loader:0.20.1"}]
        if reference is not None:
            data["jar"] = reference
        metadata = directory / (ident + ".json")
        metadata.write_text(json.dumps(data))
        if jar:
            with zipfile.ZipFile(directory / (ident + ".jar"), "w") as archive:
                archive.writestr("net/minecraft/client/main/Main.class", b"fixture")
        return metadata

    def command(self, ident=None):
        return launch.build_launch_command(ident or self.ident, "Fixture", 2048, 854, 480,
                                           game_dir=str(self.runtime / "game"))

    def entries(self, command):
        return command[command.index("-cp") + 1].split(os.pathsep)

    def test_real_fabric_command_uses_base_jar_and_preserves_loader_and_identity(self):
        before = self.child.read_bytes()
        command = self.command()
        entries = self.entries(command)
        self.assertEqual(entries[-1], str(self.base.with_suffix(".jar")))
        self.assertTrue(entries[0].endswith("fabric-loader-0.20.1.jar"))
        self.assertIn("net.fabricmc.loader.impl.launch.knot.KnotClient", command)
        self.assertEqual(command[command.index("--version") + 1], self.ident)
        self.assertEqual(self.child.read_bytes(), before)

    def test_quilt_and_nested_instance_without_own_jar(self):
        for ident, parent in (("quilt-loader-0.29-1.21.11", "1.21.11"),
                              ("1.21.11-fabric-private", self.ident)):
            with self.subTest(ident=ident):
                self.profile(ident, parent=parent)
                if parent == self.ident:
                    # mll's one-level merge uses these inherited JVM arguments.
                    data = json.loads(self.child.read_text())
                    data["arguments"]["jvm"] = ["-cp", "${classpath}"]
                    self.child.write_text(json.dumps(data))
                self.assertEqual(self.entries(self.command(ident))[-1], str(self.base.with_suffix(".jar")))

    def test_vanilla_and_dedicated_child_jar_are_preserved(self):
        self.assertEqual(self.entries(self.command("1.21.11"))[-1], str(self.base.with_suffix(".jar")))
        self.child.with_suffix(".jar").write_bytes(self.base.with_suffix(".jar").read_bytes())
        self.assertEqual(self.entries(self.command())[-1], str(self.child.with_suffix(".jar")))

    def test_explicit_jar_reference_is_preserved(self):
        alternate = self.profile("custom-client", jar=True)
        data = json.loads(self.child.read_text())
        data["jar"] = "custom-client"
        self.child.write_text(json.dumps(data))
        self.assertEqual(self.entries(self.command())[-1], str(alternate.with_suffix(".jar")))
        data["jar"] = self.ident  # Explicit missing dedicated jar is not a fallback request.
        self.child.write_text(json.dumps(data))
        self.assertEqual(self.entries(self.command())[-1], str(self.child.with_suffix(".jar")))

    def test_modern_forge_ignored_profile_jar_does_not_become_a_second_minecraft_module(self):
        ident = '1.20.1-forge-all-the-mods-9-no-frills'
        base = self.profile('1.20.1', jar=True)
        metadata = self.profile(ident, parent='1.20.1')
        data = json.loads(metadata.read_text())
        data['mainClass'] = 'cpw.mods.bootstraplauncher.BootstrapLauncher'
        data['libraries'] = [{'name':'net.minecraftforge:fmlloader:1.20.1-47.4.0'}]
        data['arguments']['jvm'] = ['-DignoreList=bootstraplauncher,client-extra,${version_name}.jar']
        metadata.write_text(json.dumps(data))
        command = self.command(ident)
        self.assertNotIn(str(metadata.with_suffix('.jar')), self.entries(command))
        self.assertNotIn(str(base.with_suffix('.jar')), self.entries(command))
        self.assertIn('cpw.mods.bootstraplauncher.BootstrapLauncher', command)
        self.assertIn('-DignoreList=bootstraplauncher,client-extra,' + ident + '.jar', command)
        self.assertTrue(any('fmlloader-1.20.1-47.4.0.jar' in entry for entry in self.entries(command)))

    def test_missing_base_fails_before_java(self):
        self.base.with_suffix(".jar").unlink()
        with self.assertRaisesRegex(RuntimeError, "inherited Minecraft client JAR is missing"):
            self.command()

    def test_paths_and_cycles_are_still_rejected(self):
        for parent in ("../outside", self.ident):
            data = json.loads(self.child.read_text())
            data["inheritsFrom"] = parent
            self.child.write_text(json.dumps(data))
            with self.assertRaises(ValueError):
                self.command()

    def test_only_jvm_classpath_entries_are_changed(self):
        profile = str(self.child.with_suffix(".jar"))
        base = str(self.base.with_suffix(".jar"))
        for flag in ("-cp", "-classpath", "--class-path"):
            command = ["java", flag, os.pathsep.join(["custom.jar", profile]), "Main",
                       "--class-path", profile]
            result = launch._normalize_inherited_client_jar(command, self.ident)
            self.assertEqual(result[2], os.pathsep.join(["custom.jar", base]))
            self.assertEqual(result[-1], profile)
            self.assertEqual(command[2], os.pathsep.join(["custom.jar", profile]))


if __name__ == "__main__":
    unittest.main()
