"""Real JAR installs with pinned/transitive provider dependencies and local folders."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
import zipfile
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import mods, net, storage, paths, local_mods, mod_dependencies


def jar(identity, version="1.0", depends=None):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({"schemaVersion": 1,
            "id": identity, "version": version, "depends": depends or {}}))
    return buf.getvalue()


class InstallGraphTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.profile = Path(self.temp.name) / "mods"
        self.profile.mkdir()
        self.releases, self.bodies, self.calls = {}, {}, []
        for name in ("get_profile_dir", "resolve_profile_dir"):
            ctx = patch.object(mods, name, return_value=str(self.profile))
            ctx.start()
            self.addCleanup(ctx.stop)
        for target, name, effect in ((net, "get_json", self.fetch),
                                     (net, "download_to", self.download)):
            ctx = patch.object(target, name, side_effect=effect)
            ctx.start()
            self.addCleanup(ctx.stop)
        ctx = patch.object(mods, "get_mod_details", return_value={})
        ctx.start()
        self.addCleanup(ctx.stop)
        mods.local_cache.invalidate("mod_download")
        mods.local_cache.invalidate("mod_versions")

    def release(self, project, ident, version="1.0", dependencies=None, depends=None, loaders=None):
        body = jar(project, version, depends)
        url = f"https://cdn.modrinth.com/data/{project}/{ident}.jar"
        data = {"id": ident, "project_id": project, "version_number": version,
                "game_versions": ["1.21.11"], "loaders": loaders or ["fabric"],
                "dependencies": dependencies or [], "files": [{"filename": ident + ".jar",
                    "url": url, "hashes": {"sha512": hashlib.sha512(body).hexdigest()}}]}
        self.releases.setdefault(project, []).append(data)
        self.bodies[url] = body
        return data

    def fetch(self, url, **kwargs):
        self.calls.append(url)
        if "/project/" in url:
            return self.releases.get(url.split("/project/")[1].split("/")[0], [])
        pin = url.rsplit("/", 1)[-1]
        return next(r for releases in self.releases.values() for r in releases if r["id"] == pin)

    def download(self, path, url, **kwargs):
        Path(path).write_bytes(self.bodies[url])
        return len(self.bodies[url])

    def install(self, release):
        file = release["files"][0]
        return mods.install_mod_with_dependencies(file["url"], file["filename"],
            "1.21.11", "fabric", project_id=release["project_id"], hashes=file["hashes"])

    def test_recursive_pinned_version_only_edge_and_cycle(self):
        main = self.release("main", "main-v1", dependencies=[
            {"version_id": "library-v2", "dependency_type": "required"}], depends={"library": ">=2"})
        self.release("library", "library-v3", "3.0")
        self.release("library", "library-v2", "2.0", dependencies=[
            {"project_id": "helper", "dependency_type": "required"}], depends={"helper": "*"})
        self.release("helper", "helper-v1", dependencies=[
            {"project_id": "main", "dependency_type": "required"}])
        result = self.install(main)
        self.assertEqual(result["failed"], [])
        self.assertEqual(set(result["installed"]), {"main-v1.jar", "library-v2.jar", "helper-v1.jar"})
        self.assertIn(mods.MODRINTH_API + "/version/library-v2", self.calls)
        self.assertFalse((self.profile / "library-v3.jar").exists())

    def test_wrong_installed_version_does_not_satisfy_exact_pin(self):
        main = self.release("main", "main-pin", dependencies=[
            {"project_id": "library", "version_id": "library-pin", "dependency_type": "required"}])
        self.release("library", "library-pin", "2.0")
        (self.profile / "old.jar").write_bytes(jar("library", "1.0"))
        mods.record_mod_source(str(self.profile), "old.jar", project_id="library")
        result = self.install(main)
        self.assertEqual(result["failed"], [])
        self.assertIn("library-pin.jar", result["installed"])
        self.assertFalse((self.profile / "old.jar").exists())

    def test_missing_required_dependency_fails_before_main_publication(self):
        main = self.release("main", "missing", dependencies=[
            {"project_id": "absent", "dependency_type": "required"}])
        with self.assertRaisesRegex(ValueError, "absent.*no compatible file"):
            self.install(main)
        self.assertFalse((self.profile / "missing.jar").exists())

    def test_pinned_other_loader_is_rejected_before_publication(self):
        main = self.release("main", "wrong-loader", dependencies=[
            {"project_id": "library", "version_id": "forge-only", "dependency_type": "required"}])
        self.release("library", "forge-only", loaders=["forge"])
        with self.assertRaisesRegex(ValueError, "no compatible file"):
            self.install(main)
        self.assertFalse((self.profile / "wrong-loader.jar").exists())

    def test_conflicting_pins_fail_before_publication(self):
        main = self.release("main", "conflicting", dependencies=[
            {"project_id": "library", "version_id": pin, "dependency_type": "required"}
            for pin in ("lib-one", "lib-two")])
        self.release("library", "lib-one", "1.0")
        self.release("library", "lib-two", "2.0")
        with self.assertRaisesRegex(ValueError, "Conflicting required versions"):
            self.install(main)
        self.assertFalse((self.profile / "conflicting.jar").exists())

    def test_optional_and_embedded_are_not_downloaded(self):
        main = self.release("main", "optional", dependencies=[
            {"project_id": "absent", "dependency_type": kind} for kind in ("optional", "embedded")])
        self.assertEqual(self.install(main)["failed"], [])
        self.assertEqual(len(self.calls), 1)

    def test_actual_jar_requirements_are_repaired_during_install(self):
        main = self.release("main", "jar-dependency", depends={"library": ">=2"})
        self.release("library", "jar-library", "2.0")
        result = self.install(main)
        self.assertEqual(result["failed"], [])
        self.assertTrue((self.profile / "jar-library.jar").exists())


class InstanceFolderTests(unittest.TestCase):
    def test_local_copy_import_list_and_launch_share_the_game_mods_folder(self):
        storage.initialize()
        version = "fabric-loader-local-copy-1.21.11"
        game = Path(storage.game_dir(version, create=True))
        directory = Path(mods.resolve_profile_dir("1.21.11", "fabric", version))
        self.assertEqual(directory, game / "mods")
        direct = directory / "copied.jar"
        direct.write_bytes(jar("copied"))
        with tempfile.TemporaryDirectory() as temporary:
            source = Path(temporary) / "imported.jar"
            source.write_bytes(jar("imported"))
            review = local_mods.review_files([str(source)], "1.21.11", "fabric", version_id=version)
            local_mods.import_entry(review["entries"][0], "1.21.11", "fabric", version_id=version)
        mods.sync_mods_to_game("1.21.11", "fabric", version)
        self.assertEqual({m["filename"] for m in mods.list_mods("1.21.11", "fabric", version)},
                         {"copied.jar", "imported.jar"})
        self.assertTrue(direct.exists())
        with patch.object(net, "get_json", side_effect=AssertionError("clean profile must stay offline")):
            result = mod_dependencies.run_dependency_doctor("1.21.11", "fabric", version_id=version)
        self.assertEqual(result["unfixed"], [])


if __name__ == "__main__":
    unittest.main()
