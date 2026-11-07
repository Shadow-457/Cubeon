"""Real ZIP fixtures for Fabric's truncated intermediary runtime dependency."""
from pathlib import Path
import hashlib
import io
import json
import os
import sys
import unittest
from unittest.mock import patch
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import paths, storage, runtime_libraries as libraries


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


if __name__ == "__main__":
    unittest.main()
