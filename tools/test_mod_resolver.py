"""Actual JAR graphs: joint repair, downgrade, nested constraints and rollback."""
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import unittest
import zipfile
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import test_mod_prelaunch_dependencies as fixtures
from cubeon import mod_dependencies as deps, mods, net
jar = fixtures.jar


class ResolverTests(unittest.TestCase):
    download = fixtures.DependencyTests.download

    def setUp(self):
        fixtures.DependencyTests.setUp(self)
        self.profile.joinpath("moreculling-1.6.2.jar").unlink()
        self.latest, self.releases = {}, {}

    def local(self, identity, version, *, disabled=False, filename=None, **kwargs):
        filename = filename or f"{identity}-{version}.jar" + (".disabled" if disabled else "")
        path = self.profile / filename
        path.write_bytes(jar(identity, version, **kwargs))
        return path

    def remote_mod(self, identity, version, *, project=None, latest=True, filename=None, **kwargs):
        project = project or identity
        blob = jar(identity, version, **kwargs)
        candidate = dict(filename=filename or f"{identity}-{version}.jar",
                         url=f"https://cdn.modrinth.com/data/{identity}/{version}.jar",
                         version_number=version, project_id=project,
                         hashes={"sha512": hashlib.sha512(blob).hexdigest()}, compatible=True,
                         version_type="release", date_published="2026-11-01")
        self.remote[identity + "@" + version] = candidate, blob
        self.releases.setdefault(project, []).append(candidate)
        if latest:
            self.latest[project] = candidate
        return candidate

    def run_doctor(self, *, downloader=None, **kwargs):
        with patch.object(mods, "get_mod_download", side_effect=lambda ref, **kw:self.latest.get(ref)), \
                patch.object(mods, "get_mod_versions", side_effect=lambda ref, **kw:self.releases.get(ref, [])), \
                patch.object(net, "download_to", side_effect=downloader or self.download):
            return deps.run_dependency_doctor(self.mc, "fabric", version_id=self.instance, **kwargs)

    def test_existing_breaks_conflict_updates_target_and_keeps_exact_old_bytes(self):
        self.local("sodium", "0.8.14", breaks={"iris": "<=1.10.7"})
        old = self.local("iris", "1.10.7").read_bytes()
        candidate = self.remote_mod("iris", "1.10.8")
        report = self.run_doctor()
        self.assertEqual(report["unfixed"], [])
        self.assertEqual(report["fixed"][0]["dependency"], "iris")
        self.assertEqual(self.profile.joinpath("iris-1.10.7.jar.disabled").read_bytes(), old)
        self.assertTrue(self.profile.joinpath(candidate["filename"]).exists())

    def test_declarer_can_be_downgraded_without_disabling_the_other_mod(self):
        self.local("sodium", "0.8.14", breaks={"iris": "<=1.10.7"})
        iris = self.local("iris", "1.10.7")
        self.remote_mod("sodium", "0.8.14", breaks={"iris": "<=1.10.7"})
        self.remote_mod("sodium", "0.8.12", latest=False)
        report = self.run_doctor()
        self.assertEqual(report["unfixed"], [], report)
        self.assertTrue(iris.exists())
        self.assertTrue(self.profile.joinpath("sodium-0.8.12.jar").exists())

    def test_two_mods_change_together_and_no_intermediate_set_is_activated(self):
        sodium = self.local("sodium", "0.8.14", breaks={"iris": "<=1.10.7"})
        iris = self.local("iris", "1.10.7")
        before = {path.name:path.read_bytes() for path in (sodium, iris)}
        self.remote_mod("iris", "1.10.8", depends={"sodium": ">=0.8.15"})
        self.remote_mod("sodium", "0.8.15", breaks={"iris": "<1.10.8"})
        def download(*args, **kwargs):
            self.assertEqual(before, {name:self.profile.joinpath(name).read_bytes() for name in before})
            return self.download(*args, **kwargs)
        report = self.run_doctor(downloader=download)
        self.assertEqual(report["unfixed"], [], report)
        self.assertEqual({entry["dependency"] for entry in report["fixed"]}, {"iris", "sodium"})
        self.assertTrue(self.profile.joinpath("iris-1.10.8.jar").exists())
        self.assertTrue(self.profile.joinpath("sodium-0.8.15.jar").exists())

    def test_conflicting_requesters_can_be_updated_to_share_a_library(self):
        self.local("a", "1", depends={"shared": ">=2"})
        self.local("b", "1", depends={"shared": "<2"})
        self.local("shared", "1")
        self.remote_mod("shared", "2")
        self.remote_mod("b", "2", depends={"shared": ">=2"})
        report = self.run_doctor()
        self.assertEqual(report["unfixed"], [], report)
        self.assertTrue(self.profile.joinpath("a-1.jar").exists())
        self.assertTrue(self.profile.joinpath("b-2.jar").exists())
        self.assertTrue(self.profile.joinpath("shared-2.jar").exists())

    def test_failed_transitive_solution_leaves_every_original_enabled(self):
        self.local("requester", "1", depends={"library": ">=2"})
        self.local("library", "1")
        before = {path.name:path.read_bytes() for path in self.profile.glob("*.jar")}
        self.remote_mod("library", "2", depends={"unavailable": ">=3"})
        report = self.run_doctor()
        self.assertTrue(report["unfixed"])
        self.assertEqual(report["fixed"], [])
        self.assertEqual(before, {path.name:path.read_bytes() for path in self.profile.glob("*.jar")})

    def test_failed_second_swap_restores_first_swap_and_both_originals(self):
        self.local("a", "1", depends={"b": ">=2"})
        self.local("b", "1")
        self.remote_mod("b", "2", depends={"a": ">=2"})
        self.remote_mod("a", "2", depends={"b": ">=2"})
        before = {path.name:path.read_bytes() for path in self.profile.glob("*.jar")}
        replace = os.replace
        def fail(source, destination):
            if Path(destination) == self.profile / "a-2.jar":
                raise OSError("locked second replacement")
            return replace(source, destination)
        with patch.object(deps.os, "replace", side_effect=fail):
            report = self.run_doctor()
        self.assertTrue(report["unfixed"])
        self.assertEqual(before, {path.name:path.read_bytes() for path in self.profile.glob("*.jar")})
        self.assertFalse(self.profile.joinpath("b-2.jar.cubeon.json").exists())

    def test_profile_changed_while_downloading_is_not_overwritten(self):
        self.local("a", "1", depends={"concurrent-library": ">=2"})
        self.local("concurrent-library", "1")
        self.remote_mod("concurrent-library", "2")
        def download(*args, **kwargs):
            self.local("user-added", "1")
            return self.download(*args, **kwargs)
        report = self.run_doctor(downloader=download)
        self.assertTrue(report["unfixed"])
        self.assertIn("Mods changed", report["unfixed"][0]["error"])
        self.assertTrue(self.profile.joinpath("user-added-1.jar").exists())
        self.assertTrue(self.profile.joinpath("concurrent-library-1.jar").exists())

    def test_nested_module_requirements_are_checked_and_repaired(self):
        self.local("umbrella", "1", nested={"child": jar("child", "1", {"helper": ">=2"})})
        self.remote_mod("helper", "2")
        report = self.run_doctor()
        self.assertEqual(report["unfixed"], [], report)
        self.assertEqual(report["fixed"][0]["dependency"], "helper")

    def test_duplicate_introduced_during_publication_rolls_back_the_repair(self):
        self.local("a", "1", depends={"library": ">=2"})
        original = self.local("library", "1").read_bytes()
        self.remote_mod("library", "2")
        write_meta = mods._write_meta
        def concurrent_copy(*args, **kwargs):
            write_meta(*args, **kwargs)
            self.local("library", "2", filename="user-added-library.jar")
        with patch.object(mods, "_write_meta", side_effect=concurrent_copy):
            report = self.run_doctor()
        self.assertTrue(report["unfixed"])
        self.assertIn("Duplicate mods", report["unfixed"][0]["error"])
        self.assertEqual(self.profile.joinpath("library-1.jar").read_bytes(), original)
        self.assertTrue(self.profile.joinpath("user-added-library.jar").exists())
        self.assertFalse(self.profile.joinpath("library-2.jar").exists())

    def test_change_during_initial_scan_blocks_even_a_previously_clean_profile(self):
        self.local("a", "1")
        scan = deps._scan
        def changing_scan(*args):
            entries = scan(*args)
            self.local("a", "2", filename="a-1.jar", depends={"missing": "*"})
            return entries
        with patch.object(deps, "_scan", side_effect=changing_scan):
            report = self.run_doctor()
        self.assertTrue(report["unfixed"])
        self.assertEqual(report["unfixed"][0]["kind"], "profile-changed")
        self.assertEqual(self.downloads, [])

    def test_offline_breaks_repair_reuses_disabled_copy(self):
        self.local("a", "2", breaks={"b": "<2"})
        self.local("b", "1")
        self.local("b", "2", disabled=True)
        report = self.run_doctor(check_online=False)
        self.assertEqual(report["unfixed"], [], report)
        self.assertEqual(self.downloads, [])
        self.assertTrue(self.profile.joinpath("b-2.jar").exists())

    def test_duplicate_choice_satisfies_all_requesters_and_keeps_backups(self):
        self.local("a", "1", depends={"library": "<2"})
        self.local("library", "1")
        self.local("library", "2")
        report = self.run_doctor(check_online=False)
        self.assertEqual(report["unfixed"], [], report)
        self.assertTrue(self.profile.joinpath("library-1.jar").exists())
        self.assertTrue(self.profile.joinpath("library-2.jar.disabled").exists())

    def test_fixed_runtime_is_never_requested_as_a_mod_download(self):
        self.local("a", "1", depends={"minecraft": "1.20.1"})
        self.remote_mod("a", "2", depends={"minecraft": self.mc})
        with patch.object(mods, "_doctor_runtime_versions", return_value={"minecraft": self.mc, "java": "21"}):
            report = self.run_doctor()
        self.assertEqual(report["unfixed"], [], report)
        self.assertTrue(self.profile.joinpath("a-2.jar").exists())

    def test_protected_client_identity_cannot_be_replaced(self):
        self.local("cubeon-client", "1", depends={"missing-library": ">=2"}, filename="cubeon-client.jar")
        self.remote_mod("cubeon-client", "2")
        report = self.run_doctor()
        self.assertTrue(report["unfixed"])
        self.assertTrue(self.profile.joinpath("cubeon-client.jar").exists())
        self.assertFalse(self.profile.joinpath("cubeon-client-2.jar").exists())

    def test_forge_and_neoforge_use_their_own_descriptors_and_maven_ranges(self):
        for loader in ("forge", "neoforge"):
            with self.subTest(loader=loader):
                for path in self.profile.glob("*.jar*"):
                    path.unlink()
                descriptor = "META-INF/neoforge.mods.toml" if loader == "neoforge" else "META-INF/mods.toml"
                def forge_jar(identity, version, dependency=""):
                    body = f'modLoader="javafml"\nloaderVersion="[1,)"\n[[mods]]\nmodId="{identity}"\nversion="{version}"\n'
                    if dependency:
                        body += f'[[dependencies.{identity}]]\nmodId="cloth_config"\nmandatory=true\ntype="required"\nversionRange="[2,3)"\nside="BOTH"\n'
                    out = io.BytesIO()
                    with zipfile.ZipFile(out, "w") as archive:
                        archive.writestr(descriptor, body)
                        archive.writestr("fabric.mod.json", json.dumps(dict(id="wrong-loader", version="1", depends={"minecraft": "1.20.1"})))
                    return out.getvalue()
                self.profile.joinpath("requester.jar").write_bytes(forge_jar("requester", "1", "cloth_config"))
                blob = forge_jar("cloth_config", "2")
                candidate = dict(filename="cloth-config-2.jar", url=f"https://cdn.modrinth.com/data/cloth/{loader}.jar",
                                 hashes={"sha512": hashlib.sha512(blob).hexdigest()})
                self.remote[loader] = candidate, blob
                with patch.object(mods, "get_mod_download", return_value=candidate) as lookup, \
                        patch.object(net, "download_to", side_effect=self.download):
                    report = deps.run_dependency_doctor(self.mc, loader, version_id=self.instance)
                self.assertEqual(report["unfixed"], [], report)
                self.assertEqual(lookup.call_args.args[0], "cloth-config")
                self.assertEqual(lookup.call_args.kwargs["loader"], loader)

    def test_java_constraint_can_be_resolved_without_changing_java(self):
        self.local("a", "2", depends={"java": ">=22"})
        self.remote_mod("a", "1", depends={"java": ">=21"})
        report = self.run_doctor(runtime_versions={"java": 21})
        self.assertEqual(report["unfixed"], [], report)
        self.assertTrue(self.profile.joinpath("a-1.jar").exists())

    def test_corrupt_jar_is_reported_instead_of_ignored(self):
        self.profile.joinpath("broken.jar").write_bytes(b"not a zip")
        report = self.run_doctor(check_online=False)
        self.assertTrue(report["unfixed"])
        self.assertEqual(report["unfixed"][0]["kind"], "unreadable")
        self.assertIn("broken", report["unfixed"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
