#!/usr/bin/env python3
"""Real jar fixtures for missing Cloth Config and the automatic Play repair gate."""
import ast
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

sys.path[:0] = [str(Path(__file__).resolve().parent),
                str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import mod_dependencies as deps, mods, net, perf_mods


def jar(identity, version, depends=None, nested=None, breaks=None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps({
            "schemaVersion": 1, "id": identity, "version": version,
            "name": identity, "depends": depends or {}, "breaks": breaks or {}}))
        for key, child in (nested or {}).items():
            archive.writestr(f"META-INF/jars/{key}.jar", child)
    return buffer.getvalue()


class DependencyTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name) / "profiles"
        self.folder.mkdir()
        self.context = patch.object(mods, "PROFILES_DIR", str(self.folder))
        self.context.start()
        self.addCleanup(self.context.stop)
        self.mc = "1.21.11"
        self.instance = "isolated-test"
        self.sidecars = patch.object(mods, "read_instance_meta", side_effect=lambda vid:
                                    {"profile": vid} if vid else None)
        self.sidecars.start()
        self.addCleanup(self.sidecars.stop)
        self.profile = Path(mods.get_profile_dir(self.mc, "fabric", self.instance))
        self.profile.joinpath("moreculling-1.6.2.jar").write_bytes(jar(
            "moreculling", "1.6.2", {"cloth-config": ">=16.0.0", "minecraft": ">=1.21", "java": ">=21"}))
        self.downloads, self.lookups, self.remote = [], [], {}

    def remote_jar(self, identity, version="16.0.141", **kw):
        blob = jar(identity, version, **kw)
        candidate = {"filename": f"{identity}-{version}.jar",
                     "url": f"https://cdn.modrinth.com/data/{identity}/{version}.jar",
                     "version_number": version,
                     "hashes": {"sha512": hashlib.sha512(blob).hexdigest()}}
        self.remote[identity] = candidate, blob
        return candidate

    def lookup(self, identity, **kwargs):
        self.lookups.append((identity, kwargs))
        return self.remote.get(identity, (None, None))[0]

    def download(self, path, url, **kwargs):
        self.downloads.append(kwargs)
        blob = next(blob for candidate, blob in self.remote.values() if candidate["url"] == url)
        self.assertEqual(kwargs["attempts"], 1)
        self.assertEqual(kwargs["expected_hash"], ("sha512", hashlib.sha512(blob).hexdigest()))
        Path(path).write_bytes(blob)
        return len(blob)

    def run_doctor(self, **kwargs):
        with patch.object(mods, "get_mod_download", side_effect=self.lookup), \
                patch.object(net, "download_to", side_effect=self.download):
            return deps.run_dependency_doctor(self.mc, "fabric", version_id=self.instance, **kwargs)

    def test_reported_failure_repairs_existing_isolated_profile_and_is_idempotent(self):
        candidate = self.remote_jar("cloth-config")
        sibling = Path(mods.get_profile_dir(self.mc, "fabric", "other-instance"))
        sibling.joinpath("cloth-old.jar").write_bytes(jar("cloth-config", "1.0"))
        original = sibling.joinpath("cloth-old.jar").read_bytes()
        report = self.run_doctor()
        self.assertEqual(report["unfixed"], [])
        self.assertEqual(report["fixed"][0]["dependency"], "cloth-config")
        actual = mods.read_mod_metadata(str(self.profile / candidate["filename"]), "fabric")
        self.assertTrue(mods.version_satisfies(actual["version"], ">=16.0.0"))
        self.assertEqual(sibling.joinpath("cloth-old.jar").read_bytes(), original)
        self.assertEqual(len(self.lookups), 1)
        self.assertEqual(self.lookups[0][1]["timeout"], (3, 10))
        self.assertEqual(self.lookups[0][1]["version_predicates"], [">=16.0.0"])
        self.lookups.clear()
        self.assertEqual(self.run_doctor()["fixed"], [])
        self.assertEqual(self.lookups, [])

    def test_outdated_dependency_is_replaced_with_byte_identical_backup(self):
        old = jar("cloth-config", "15.0.1")
        self.profile.joinpath("cloth-old.jar").write_bytes(old)
        self.remote_jar("cloth-config")
        self.assertFalse(self.run_doctor()["unfixed"])
        self.assertFalse(self.profile.joinpath("cloth-old.jar").exists())
        self.assertEqual(self.profile.joinpath("cloth-old.jar.disabled").read_bytes(), old)

    def test_disabled_compatible_copy_is_restored_offline_even_with_old_enabled_copy(self):
        old = jar("cloth-config", "15.0.1")
        self.profile.joinpath("cloth-old.jar").write_bytes(old)
        self.profile.joinpath("cloth-new.jar.disabled").write_bytes(jar("cloth-config", "16.0.141"))
        report = self.run_doctor(check_online=False)
        self.assertFalse(report["unfixed"], report)
        self.assertEqual(self.lookups, [])
        self.assertEqual(self.profile.joinpath("cloth-old.jar.disabled").read_bytes(), old)
        self.assertTrue(self.profile.joinpath("cloth-new.jar").exists())
        enabled = [item for item in mods.list_mods(self.mc, "fabric", self.instance)
                   if item["enabled"] and "cloth" in item["filename"]]
        self.assertEqual(len(enabled), 1)

    def test_transitive_dependencies_are_read_from_downloaded_jar(self):
        self.remote_jar("cloth-config", depends={"helper-library": ">=2"})
        self.remote_jar("helper-library", "2.0")
        report = self.run_doctor()
        self.assertFalse(report["unfixed"], report)
        self.assertEqual([key for key, _ in self.lookups], ["cloth-config", "helper-library"])

    def test_bad_download_cannot_replace_old_dependency_or_disable_requester(self):
        old = jar("cloth-config", "15.0.1")
        self.profile.joinpath("cloth-old.jar").write_bytes(old)
        candidate = self.remote_jar("cloth-config")
        bad = jar("unrelated-mod", "16.0.141")
        candidate["hashes"] = {"sha512": hashlib.sha512(bad).hexdigest()}
        self.remote["cloth-config"] = candidate, bad
        report = self.run_doctor()
        self.assertTrue(report["unfixed"])
        self.assertFalse(report["fixed"])
        self.assertEqual(self.profile.joinpath("cloth-old.jar").read_bytes(), old)
        self.assertTrue(self.profile.joinpath("moreculling-1.6.2.jar").exists())
        self.assertFalse(self.profile.joinpath(candidate["filename"]).exists())

    def test_failed_swap_rolls_back_renamed_dependencies(self):
        old = jar("cloth-config", "15.0.1")
        self.profile.joinpath("cloth-old.jar").write_bytes(old)
        candidate = self.remote_jar("cloth-config")
        replace = os.replace

        def fail_swap(source, destination):
            if Path(destination) == self.profile / candidate["filename"]:
                raise OSError("simulated locked file")
            return replace(source, destination)

        with patch.object(deps.os, "replace", side_effect=fail_swap):
            report = self.run_doctor()
        self.assertTrue(report["unfixed"])
        self.assertEqual(self.profile.joinpath("cloth-old.jar").read_bytes(), old)
        self.assertFalse(self.profile.joinpath("cloth-old.jar.disabled").exists())

    def test_actual_jar_version_and_minecraft_compatibility_are_verified(self):
        for version, requires in (("15.0", "*"), ("16.0.141", "1.20.1")):
            with self.subTest(version=version, requires=requires):
                candidate = self.remote_jar("cloth-config", version, depends={"minecraft": requires})
                # API version metadata can be wrong; the actual jar wins.
                candidate["version_number"] = "16.0.141"
                report = self.run_doctor()
                self.assertTrue(report["unfixed"])
                self.assertFalse(report["fixed"])
                self.assertFalse(self.profile.joinpath(candidate["filename"]).exists())

    def test_repair_budget_stops_before_network_when_expired(self):
        with patch.object(deps, "REPAIR_SECONDS", 0):
            report = self.run_doctor()
        self.assertTrue(report["unfixed"])
        self.assertEqual(self.lookups, [])

    def test_trickling_download_obeys_deadline_and_preserves_destination(self):
        from types import SimpleNamespace
        clock = [0.0]
        reads = []
        closed = []

        def read1(*args, **kwargs):
            reads.append(1)
            clock[0] += 1
            return b"x"  # never fills iter_content's 64 KiB chunk

        response = SimpleNamespace(raw=SimpleNamespace(read1=read1),
                                   headers={"content-length": "1000000"}, status_code=200,
                                   close=lambda:closed.append(True))
        target = self.profile / "existing.jar"
        target.write_bytes(b"previous")
        with patch.object(net, "get_with_retry", return_value=response), \
                patch.object(net.time, "monotonic", side_effect=lambda:clock[0]):
            with self.assertRaisesRegex(net.DownloadError, "time limit"):
                net.download_to(str(target), "https://cdn.modrinth.com/test", attempts=1, deadline=3)
        self.assertEqual(len(reads), 3)
        self.assertEqual(target.read_bytes(), b"previous")
        self.assertEqual(closed, [True])

    def test_deadline_download_still_checks_hash_and_completes(self):
        from types import SimpleNamespace
        blob = b"a verified body"
        chunks = iter((blob, b""))
        response = SimpleNamespace(raw=SimpleNamespace(read1=lambda *a, **kw:next(chunks)),
                                   headers={"content-length": str(len(blob))}, status_code=200,
                                   close=lambda:None)
        target = self.profile / "download.jar"
        expected = ("sha512", hashlib.sha512(blob).hexdigest())
        with patch.object(net, "get_with_retry", return_value=response), \
                patch.object(net.time, "monotonic", return_value=0):
            net.download_to(str(target), "https://cdn.modrinth.com/test", attempts=1,
                            expected_hash=expected, deadline=3)
        self.assertEqual(target.read_bytes(), blob)

    def test_connection_failure_stops_other_probes_and_preserves_mods(self):
        self.profile.joinpath("other.jar").write_bytes(jar("other", "1", {"another-dep": "*"}))
        before = {path.name: path.read_bytes() for path in self.profile.glob("*.jar")}
        with patch.object(mods, "get_mod_download", side_effect=net.DownloadError("no route")) as lookup:
            report = deps.run_dependency_doctor(self.mc, "fabric", version_id=self.instance)
        self.assertEqual(lookup.call_count, 1)
        self.assertEqual(len(report["unfixed"]), 2)
        self.assertEqual(before, {path.name: path.read_bytes() for path in self.profile.glob("*.jar")})

    def test_bundled_api_modules_are_satisfied_without_network(self):
        self.profile.joinpath("moreculling-1.6.2.jar").unlink()
        self.profile.joinpath("sodium.jar").write_bytes(jar("sodium", "0.6", {
            "fabric-rendering-fluids-v1": ">=2", "fabricloader": ">=0.16"}))
        self.profile.joinpath("fabric-api.jar").write_bytes(jar("fabric-api", "0.1", nested={
            "fluids": jar("fabric-rendering-fluids-v1", "2.5")}))
        report = self.run_doctor(check_online=False)
        self.assertFalse(report["unfixed"])
        self.assertEqual(self.lookups, [])

    def test_missing_api_submodule_installs_umbrella_project(self):
        self.profile.joinpath("moreculling-1.6.2.jar").unlink()
        self.profile.joinpath("sodium.jar").write_bytes(jar("sodium", "0.6", {
            "fabric-rendering-fluids-v1": ">=2"}))
        self.remote_jar("fabric-api", "0.1", nested={
            "fluids": jar("fabric-rendering-fluids-v1", "2.5")})
        self.assertFalse(self.run_doctor()["unfixed"])
        self.assertEqual([key for key, _ in self.lookups], ["fabric-api"])

    def test_all_requesters_constraints_are_required(self):
        self.profile.joinpath("pinned-mod.jar").write_bytes(jar("pinned-mod", "1", {
            "cloth-config": "<17"}))
        self.remote_jar("cloth-config", "17.0")
        self.assertTrue(self.run_doctor()["unfixed"])
        self.assertEqual(self.lookups[0][1]["version_predicates"], [">=16.0.0", "<17"])

    def test_version_lookup_can_select_older_compatible_build(self):
        versions = [{"version_number": version,
                     "files": [{"filename": f"cloth-{version}.jar", "url": "https://cdn.modrinth.com/dep.jar"}]}
                    for version in ("17.0", "16.0.141", "15.0")]
        with patch.object(net, "get_json", return_value=versions):
            found = mods.get_mod_download(f"constraint-probe-{id(self)}", self.mc,
                                          version_predicates=[">=16", "<17"], attempts=1)
        self.assertEqual(found["version_number"], "16.0.141")

    def test_perf_installer_repairs_dependencies_of_kept_mods(self):
        self.remote_jar("cloth-config")
        with patch.object(perf_mods, "_present", return_value=set(perf_mods.PERF_MOD_SLUGS)), \
                patch.object(perf_mods, "get_mod_download") as perf_lookup, \
                patch.object(mods, "get_mod_download", side_effect=self.lookup), \
                patch.object(net, "download_to", side_effect=self.download):
            report = perf_mods.ensure_installed(self.mc, "fabric", version_id=self.instance)
        perf_lookup.assert_not_called()
        self.assertIn("repaired dependencies: cloth-config", report["detail"])
        self.assertFalse(self.run_doctor()["unfixed"])

    def test_real_launch_gate_repairs_before_sync_and_blocks_unfixed_before_spawn(self):
        # Execute the actual guarded staging/spawn block with no Java process.
        source = Path(__file__).resolve().parents[1].joinpath("cubeon/launch.py").read_text()
        gate = next(node for node in ast.walk(ast.parse(source)) if isinstance(node, ast.With)
                    and any(isinstance(item.context_expr, ast.Name)
                            and item.context_expr.id == "_spawn_lock" for item in node.items))
        module = ast.Module(body=[gate], type_ignores=[])
        from threading import Lock
        from types import SimpleNamespace
        events = []
        def spawn(*args, **kwargs):
            events.append("spawn")
            return SimpleNamespace(pid=123)
        scope = dict(_spawn_lock=Lock(), mc_version=self.mc, loader="fabric", version_id=self.instance,
                     status_cb=None, command=[], game_dir=str(self.profile), log_fh=None, log_path="unused",
                     popen_kwargs={}, session_id="test", username="test", _active_logs=set(),
                     _prune_game_logs=lambda: None, subprocess=SimpleNamespace(Popen=spawn, DEVNULL=-1, STDOUT=-2),
                     watchdog=SimpleNamespace(register=lambda *a, **kw:None),
                     sync_mods_to_game=lambda *a:events.append("sync"), __name__="cubeon.launch", __package__="cubeon")
        from cubeon import content
        self.remote_jar("cloth-config")
        with patch.object(content, "sync_content_to_game", side_effect=lambda *a:events.append("content")), \
                patch.object(mods, "get_mod_download", side_effect=self.lookup), \
                patch.object(net, "download_to", side_effect=self.download):
            exec(compile(module, "<actual launch gate>", "exec"), scope)
        self.assertEqual(events, ["content", "sync", "spawn"])
        self.assertFalse(self.run_doctor()["unfixed"])
        for path in self.profile.glob("cloth*.jar"):
            path.unlink()
        events.clear()
        with patch.object(mods, "get_mod_download", side_effect=net.DownloadError("offline")):
            with self.assertRaisesRegex(RuntimeError, "cloth-config >=16.0.0"):
                exec(compile(module, "<actual launch gate>", "exec"), scope)
        self.assertEqual(events, [])


if __name__ == "__main__":
    unittest.main()
