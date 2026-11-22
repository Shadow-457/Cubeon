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

    def forge_blob(self, identity, version, depends=None, *, loader="forge", extra="", manifest="", nested=None):
        body = f'modLoader="javafml"\nloaderVersion="[1,)"\n[[mods]]\nmodId="{identity}"\nversion="{version}"\n'
        for dependency, predicate in (depends or {}).items():
            body += f'[[dependencies.{identity}]]\nmodId="{dependency}"\nmandatory=true\ntype="required"\nversionRange="{predicate}"\nside="BOTH"\n'
        output = io.BytesIO()
        with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            descriptor = "META-INF/neoforge.mods.toml" if loader == "neoforge" else "META-INF/mods.toml"
            archive.writestr(descriptor, body + extra)
            if manifest:
                archive.writestr("META-INF/MANIFEST.MF", manifest)
            for name, blob in (nested or {}).items():
                archive.writestr("META-INF/jarjar/" + name + ".jar", blob)
        return output.getvalue()

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

    def test_java_25_requester_resolves_to_a_java_21_build_without_removing_it(self):
        original = self.local('c2me', '3', depends={'java': '>=25'})
        original_bytes = original.read_bytes()
        self.remote_mod('c2me', '3', depends={'java': '>=25'})
        compatible = self.remote_mod('c2me', '2', latest=False, depends={'java': '>=21'})
        report = self.run_doctor(runtime_versions={'java': '21'})
        self.assertEqual(report['unfixed'], [])
        self.assertTrue(self.profile.joinpath(compatible['filename']).exists())
        self.assertEqual(self.profile.joinpath('c2me-3.jar.disabled').read_bytes(), original_bytes)

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

    def test_forge_fixed_builds_satisfy_maven_ranges_offline(self):
        for loader in ('forge', 'neoforge'):
            with self.subTest(loader=loader):
                for path in self.profile.glob('*.jar*'):
                    path.unlink()
                descriptor = 'META-INF/neoforge.mods.toml' if loader == 'neoforge' else 'META-INF/mods.toml'
                for identity, version, dependency in (
                        ('cataclysm', '2.0', '[[dependencies.cataclysm]]\nmodId="lionfishapi"\nmandatory=true\ntype="required"\nversionRange="[2.4,)"\nside="BOTH"\n'),
                        ('lionfishapi', '2.4-Fix', '')):
                    with zipfile.ZipFile(self.profile / (identity + '.jar'), 'w') as archive:
                        archive.writestr(descriptor, 'modLoader="javafml"\nloaderVersion="[1,)"\n'
                            + f'[[mods]]\nmodId="{identity}"\nversion="{version}"\n' + dependency)
                before = mods._doctor_profile_snapshot(str(self.profile))
                with patch.object(mods, 'get_mod_download', side_effect=AssertionError('network')), \
                        patch.object(net, 'download_to', side_effect=AssertionError('download')):
                    report = deps.run_dependency_doctor(self.mc, loader, version_id=self.instance,
                                                        auto_fix=False, check_online=False)
                self.assertEqual(report['unfixed'], [])
                self.assertEqual(before, mods._doctor_profile_snapshot(str(self.profile)))

    def test_maven_qualifiers_ranges_and_fabric_prereleases_stay_distinct(self):
        for version in ('2.4-Fix', '2.4-fix', '2.4-sp', '2.4-final', '2.4-release', '2.4.0'):
            self.assertTrue(mods.version_satisfies(version, '[2.4,)'), version)
        for version in ('2.4-alpha1', '2.4-beta2', '2.4-rc1', '2.4-SNAPSHOT', '2.3-Fix'):
            self.assertFalse(mods.version_satisfies(version, '[2.4,)'), version)
        self.assertFalse(mods.version_satisfies('2.4-Fix', '[2.4]'))
        self.assertFalse(mods.version_satisfies('2.4-Fix', '[2.3,2.4]'))
        self.assertTrue(mods.version_satisfies('1.20-2.13.82', '[1.20-2.11.33,)'))
        self.assertFalse(mods.version_satisfies('2.4-Fix', '>=2.4'))
        self.assertFalse(mods.version_satisfies('2.4-rc.1', '^2.4'))

    def test_screenshot_forge_graph_is_clean_without_downloads_or_replacements(self):
        for loader in ("forge", "neoforge"):
            with self.subTest(loader=loader):
                for path in self.profile.glob("*.jar*"):
                    path.unlink()
                # Same rules and versions as the reported ATM9 No Frills pack.
                specifications = [
                    ("cataclysm", "2", {"lionfishapi": "[2.4,)"}),
                    ("lionfishapi", "2.4-Fix", {}),
                    ("amendments", "1", {"moonlight": "1.20-2.11.33"}),
                    ("moonlight", "1.20-2.13.82", {}),
                    ("ars_creo", "1", {"create": "[0.5.1,)"}),
                    ("ponderjs", "1", {"create": "[0.5.1,)"}),
                ]
                for identity, version, depends in specifications:
                    self.profile.joinpath(identity + ".jar").write_bytes(
                        self.forge_blob(identity, version, depends, loader=loader))
                self.profile.joinpath("create.jar").write_bytes(self.forge_blob(
                    "create", "${file.jarVersion}", {"flywheel": "[0.6.11,0.6.12)"}, loader=loader,
                    manifest="Manifest-Version: 1.0\r\nImplementation-Version: 0.5.1.j\r\n\r\n",
                    nested={"flywheel": self.forge_blob("flywheel", "0.6.11-13", loader=loader)}))
                # IE's signed manifest is 1,204,740 bytes; only its main header
                # is metadata. Ars's unscoped array is ignored by Forge itself.
                self.profile.joinpath("immersiveengineering.jar").write_bytes(self.forge_blob(
                    "immersiveengineering", "1.20.1-10.2.0-183", {"minecraft": "[1.20.1]"}, loader=loader,
                    manifest="Manifest-Version: 1.0\r\n\r\n" + "Name: asset\r\nSHA-256-Digest: fixture\r\n\r\n" * 40000))
                self.profile.joinpath("arseng.jar").write_bytes(self.forge_blob(
                    "arseng", "1.2.0", loader=loader,
                    extra='[[dependencies]]\nmodId="ae2"\nmandatory=true\nversionRange="[15,)"\n'))
                before = mods._doctor_profile_snapshot(str(self.profile))
                with patch.object(mods, "get_mod_download", side_effect=AssertionError("network")), \
                        patch.object(net, "download_to", side_effect=AssertionError("download")):
                    for auto_fix in (False, True):
                        report = deps.run_dependency_doctor("1.20.1", loader, version_id=self.instance,
                                                            auto_fix=auto_fix, check_online=False)
                        self.assertEqual(report["unfixed"], [], report)
                        self.assertEqual(report["fixed"], [])
                self.assertEqual(before, mods._doctor_profile_snapshot(str(self.profile)))
                self.assertEqual(report["checked"], 9)

    def test_forge_recommendations_still_require_presence_and_exact_pins_remain_strict(self):
        for loader in ("forge", "neoforge"):
            with self.subTest(loader=loader):
                for path in self.profile.glob("*.jar*"):
                    path.unlink()
                requester = self.profile / "requester.jar"
                requester.write_bytes(self.forge_blob("requester", "1", {"library": "2.11"}, loader=loader))
                report = deps.run_dependency_doctor(self.mc, loader, version_id=self.instance,
                                                    auto_fix=False, check_online=False)
                self.assertEqual(report["unfixed"][0]["dependency"], "library")
                self.assertTrue(report["unfixed"][0]["missing"])
                self.profile.joinpath("library.jar").write_bytes(self.forge_blob("library", "2.13", loader=loader))
                report = deps.run_dependency_doctor(self.mc, loader, version_id=self.instance,
                                                    auto_fix=False, check_online=False)
                self.assertEqual(report["unfixed"], [])
                for predicate in ("[2.11]", "[2.0,2.12)"):
                    requester.write_bytes(self.forge_blob("requester", "1", {"library": predicate}, loader=loader))
                    report = deps.run_dependency_doctor(self.mc, loader, version_id=self.instance,
                                                        auto_fix=False, check_online=False)
                    self.assertEqual(report["unfixed"][0]["kind"], "required")
                self.assertFalse(mods.version_satisfies("2.13", "2.11", loader="fabric"))

    def test_manifest_uses_only_bounded_main_attributes_and_unfolds_versions(self):
        path = self.profile / "manifest.jar"
        path.write_bytes(self.forge_blob("manifest", "${file.jarVersion}",
            manifest="Manifest-Version: 1.0\r\nImplementation-Version: 0.5.\r\n 1.j\r\n\r\n"
                     "Name: example.class\r\nImplementation-Version: 999\r\n\r\n"))
        self.assertEqual(mods.read_mod_metadata(str(path), "forge")["version"], "0.5.1.j")
        path.write_bytes(self.forge_blob("manifest", "${file.jarVersion}",
            manifest="Manifest-Version: 1.0\n\nName: example.class\nImplementation-Version: 999\n\n"))
        self.assertEqual(mods.read_mod_metadata(str(path), "forge")["version"], "")
        path.write_bytes(self.forge_blob("manifest", "1",
            manifest="Manifest-Version: 1.0\nOversized: " + "x" * 65536 + "\n\n"))
        report = deps.run_dependency_doctor(self.mc, "forge", version_id=self.instance,
                                            auto_fix=False, check_online=False)
        self.assertEqual(report["unfixed"][0]["kind"], "unreadable")

    def test_scoped_secondary_forge_requirements_survive_unscoped_array_fix(self):
        path = self.profile / "multiple.jar"
        path.write_bytes(self.forge_blob("primary", "1", {"required_primary": "[2,)"}, extra=
            '[[mods]]\nmodId="secondary"\nversion="1"\n'
            '[[dependencies.secondary]]\nmodId="required_secondary"\nmandatory=true\nversionRange="[3,)"\n'
            '[[dependencies.secondary]]\nmodId="server_only"\nmandatory=true\nside="SERVER"\n'
            '[[dependencies.secondary]]\nmodId="optional"\nmandatory=false\n'))
        report = deps.run_dependency_doctor(self.mc, "forge", version_id=self.instance,
                                            auto_fix=False, check_online=False)
        self.assertEqual({p["dependency"] for p in report["unfixed"]}, {"required_primary", "required_secondary"})

    def test_forge_provider_selection_keeps_maven_fixed_build_order(self):
        self.profile.joinpath("umbrella.jar").write_bytes(self.forge_blob("umbrella", "1", nested={
            "release": self.forge_blob("library", "2.4"),
            "fixed": self.forge_blob("library", "2.4-Fix")}))
        metadata, provided = mods._doctor_metadata(str(self.profile / "umbrella.jar"), "forge")
        self.assertEqual(provided["library"], "2.4-Fix")

    def test_forge_resolve_chooses_pinned_older_jar_over_latest(self):
        for loader in ("forge", "neoforge"):
            with self.subTest(loader=loader):
                for path in self.profile.glob("*.jar*"):
                    path.unlink()
                self.profile.joinpath("requester.jar").write_bytes(
                    self.forge_blob("requester", "1", {"create": "[0.5.1]"}, loader=loader))
                original = self.forge_blob("create", "0.6", loader=loader)
                self.profile.joinpath("create-0.6.jar").write_bytes(original)
                releases = []
                for version in ("0.6", "0.5.1"):
                    blob = self.forge_blob("create", version, loader=loader)
                    candidate = dict(filename=f"create-{version}.jar", version_number=version,
                        url=f"https://cdn.modrinth.com/data/create/{loader}/{version}.jar",
                        hashes={"sha512": hashlib.sha512(blob).hexdigest()}, compatible=True)
                    self.remote[loader + version] = candidate, blob
                    releases.append(candidate)
                with patch.object(mods, "get_mod_download", return_value=releases[0]), \
                        patch.object(mods, "get_mod_versions", side_effect=lambda project, **kw: releases if project == "create" else []), \
                        patch.object(net, "download_to", side_effect=self.download):
                    report = deps.run_dependency_doctor(self.mc, loader, version_id=self.instance)
                self.assertEqual(report["unfixed"], [], report)
                self.assertTrue(self.profile.joinpath("create-0.5.1.jar").exists())
                self.assertEqual(self.profile.joinpath("create-0.6.jar.disabled").read_bytes(), original)

    def test_forge_lookup_drops_cached_false_rejection_of_recommended_version(self):
        from cubeon import local_cache
        project = "forge-recommendation-cache-probe"
        predicates = ["1.20-2.11.33"]
        old_key = dict(project=project, mc_version="1.20.1", loader="forge", revision=4,
                       file_id=None, predicates=predicates)
        local_cache.set("mod_download", old_key, {"file": None})
        releases = [dict(id="newer", version_number="1.20-2.13.82", game_versions=["1.20.1"],
                        loaders=["forge"], files=[dict(filename="moonlight.jar",
                        url="https://cdn.modrinth.com/moonlight.jar")])]
        with patch.object(net, "get_json", return_value=releases) as lookup:
            selected = mods.get_mod_download(project, "1.20.1", "forge", version_predicates=predicates)
        lookup.assert_called_once()
        self.assertEqual(selected["version_number"], "1.20-2.13.82")

    def test_universal_forge_bootstrap_ignores_fabric_entrypoint_requirements(self):
        path = self.profile / "universal.jar"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("fabric.mod.json", json.dumps(dict(id="bootstrap", version="15.1",
                              depends={"fabricloader": ">=0.16", "java": ">=21"})))
            archive.writestr("META-INF/MANIFEST.MF", "Manifest-Version: 1.0\r\n"
                              "Automatic-Module-Name: bootstrap\r\nImplementation-Version: 15.1\r\n"
                              "FMLCorePlugin: example.\r\n LoadingPlugin\r\n\r\n")
            archive.writestr("example/LoadingPlugin.class", b"fixture")
        before = path.read_bytes()
        with patch.object(mods, "get_mod_download", side_effect=AssertionError("Clean Forge profile requested network")):
            report = deps.run_dependency_doctor("1.8.9", "forge", version_id=self.instance,
                                                runtime_versions={"java": 8})
        self.assertEqual(report, {"checked": 1, "fixed": [], "unfixed": []})
        self.assertEqual(path.read_bytes(), before)
        self.assertEqual(mods.read_mod_metadata(str(path), "fabric")["depends"]["fabricloader"], ">=0.16")

    def test_forge_bootstrap_requires_the_manifest_plugin_class(self):
        for manifest in ("Manifest-Version: 1.0\nFMLCorePlugin: example.Missing\n\n",
                         "Manifest-Version: 1.0\n\nName: example/Plugin.class\nFMLCorePlugin: example.Plugin\n"):
            with self.subTest(manifest=manifest):
                path = self.profile / "fabric-only.jar"
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("fabric.mod.json", json.dumps(dict(id="fabric-only", version="1")))
                    archive.writestr("META-INF/MANIFEST.MF", manifest)
                    archive.writestr("example/Plugin.class", b"fixture")
                report = deps.run_dependency_doctor("1.8.9", "forge", version_id=self.instance,
                                                    check_online=False, auto_fix=False)
                self.assertTrue(report["unfixed"])
                self.assertEqual(report["unfixed"][0]["kind"], "incompatible")

    def test_legacy_forge_modlist_identity_and_compile_target(self):
        for wrapped in (False, True):
            with self.subTest(wrapped=wrapped):
                path = self.profile / "legacy.jar"
                entries = [dict(modid="legacy", name="Legacy", version="1", mcversion="1.8"),
                           dict(modid="bundled", version="2")]
                with zipfile.ZipFile(path, "w") as archive:
                    archive.writestr("mcmod.info", json.dumps({"modList": entries} if wrapped else entries))
                    archive.writestr("fabric.mod.json", json.dumps(dict(id="wrong-entrypoint", version="1")))
                metadata, provided = mods._doctor_metadata(str(path), "forge")
                self.assertEqual(metadata["id"], "legacy")
                self.assertEqual(provided["bundled"], "2")
                report = deps.run_dependency_doctor("1.8.9", "forge", version_id=self.instance, check_online=False)
                self.assertEqual(report["unfixed"], [])

    def test_malformed_legacy_descriptor_is_reported(self):
        path = self.profile / "broken-legacy.jar"
        with zipfile.ZipFile(path, "w") as archive:
            archive.writestr("mcmod.info", "invalid JSON")
        report = deps.run_dependency_doctor("1.8.9", "forge", version_id=self.instance,
                                            check_online=False, auto_fix=False)
        self.assertEqual(report["unfixed"][0]["kind"], "unreadable")

    def test_corrupt_jar_is_reported_instead_of_ignored(self):
        self.profile.joinpath("broken.jar").write_bytes(b"not a zip")
        report = self.run_doctor(check_online=False)
        self.assertTrue(report["unfixed"])
        self.assertEqual(report["unfixed"][0]["kind"], "unreadable")
        self.assertIn("broken", report["unfixed"][0]["detail"])


if __name__ == "__main__":
    unittest.main()
