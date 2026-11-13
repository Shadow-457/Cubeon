"""Cross-provider discovery and installation, including the 1.21.11 report."""
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import threading
import unittest
from unittest.mock import patch
import zipfile

sys.path[:0] = [os.path.dirname(__file__), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import local_cache, mod_catalogue as catalogue, modpacks, mods, net, thread_safe_ui

MC, LOADER = "1.21.11", "fabric"
PROJECT, FILE = "1511174", "9215662"
FILENAME = "immersive-portals-6.0.7-mc1.21.11-fabric.jar"
PAGE = "https://www.curseforge.com/minecraft/mc-mods/immersive-portal"


def jar(name="immersive_portals", mc=MC):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr(zipfile.ZipInfo("fabric.mod.json", date_time=(2026, 1, 1, 0, 0, 0)), json.dumps(dict(schemaVersion=1, id=name,
            name="Immersive Portals", version="6.0.7", depends={"minecraft": mc})))
    return stream.getvalue()


def project(pid=PROJECT):
    return dict(id=int(pid), classId=6, name="Immersive Portal", slug="immersive-portal",
                allowModDistribution=True, authors=[{"name": "Author"}],
                links={"websiteUrl": PAGE}, logo={"thumbnailUrl": "https://media.forgecdn.net/icon.png"})


def release(pid=PROJECT, fid=FILE, **changes):
    result = dict(id=int(fid), modId=int(pid), fileName=FILENAME, displayName=FILENAME,
                  fileDate="2026-10-16", releaseType=1, isAvailable=True,
                  downloadUrl=f"https://edge.forgecdn.net/files/{fid}/mod.jar",
                  gameVersions=["Fabric", MC], dependencies=[],
                  hashes=[{"algo": 1, "value": hashlib.sha1(jar()).hexdigest()}])
    result.update(changes)
    return result


class CatalogueTests(unittest.TestCase):
    def setUp(self):
        local_cache.invalidate()
        self.projects = {PROJECT: project()}
        self.files = {PROJECT: [release()]}
        self.calls = []
        self.keys = patch.object(modpacks, "curseforge_enabled", return_value=True)
        self.http = patch.object(modpacks, "_cf_request", side_effect=self.request)
        self.keys.start(); self.http.start()
        self.addCleanup(self.keys.stop); self.addCleanup(self.http.stop)

    def request(self, path, params=None, **kwargs):
        self.calls.append((path, dict(params or {})))
        if path == "/mods/search":
            return {"data": list(self.projects.values())}
        pid = path.split("/")[2]
        if path.endswith("/description"):
            return {"data": "<p>See through portals.</p>"}
        if "/files/" in path:
            return {"data": next(f for f in self.files[pid] if str(f["id"]) == path.split("/")[-1])}
        if path.endswith("/files"):
            files = self.files[pid]
            start, size = params["index"], params["pageSize"]
            return {"data": files[start:start + size], "pagination": {"totalCount": len(files)}}
        return {"data": self.projects[pid]}

    def test_reported_search_and_exact_release(self):
        with patch.object(mods.net, "get_json", return_value={"hits": []}):
            self.assertEqual(mods.search_mods("immersive portals", MC, LOADER), [])
        hits = mods.search_mods("immersive portals", MC, LOADER, source="curseforge", limit=24)
        self.assertEqual(hits[0]["project_id"], PROJECT)
        self.assertEqual(hits[0]["compatibility_target"], [MC, LOADER])
        params = self.calls[0][1]
        self.assertEqual((params["classId"], params["gameVersion"], params["modLoaderType"]), (6, MC, 4))
        self.assertEqual(params["searchFilter"], "immersive portals")
        file = mods.get_mod_download("curseforge:" + PROJECT, MC, LOADER)
        self.assertEqual((file["id"], file["filename"]), (FILE, FILENAME))
        self.assertIn("sha1", file["hashes"])
        self.assertEqual(mods.get_mod_details("curseforge:" + PROJECT)["body"], "<p>See through portals.</p>")

    def test_categories_loaders_and_broad_search(self):
        for loader, number in catalogue.LOADERS.items():
            catalogue.search("word", MC, loader, ["optimization"], offset=24)
            params = self.calls[-1][1]
            self.assertEqual(params["modLoaderType"], number)
            self.assertEqual(json.loads(params["categoryIds"]), [6814])
            self.assertEqual(params["index"], 24)
        catalogue.search("word")
        self.assertNotIn("gameVersion", self.calls[-1][1])
        self.assertNotIn("modLoaderType", self.calls[-1][1])

    def test_links_and_sources_do_not_collide(self):
        for suffix in ("", "/files/" + FILE):
            hit = mods.search_mods(PAGE + suffix, MC, LOADER)[0]
            self.assertEqual(hit["source"], "curseforge")
            self.assertEqual(hit.get("file_id"), FILE if suffix else None)
        mr = dict(project_id=PROJECT, title="Same", source="modrinth")
        cf = dict(project_id=PROJECT, title="Same", source="curseforge")
        self.assertEqual(catalogue.interleave([mr, mr], [cf]), [mr, cf])
        self.assertIsNone(catalogue.reference("https://evil.test/minecraft/mc-mods/foo"))

    def test_wrong_version_loader_and_malformed_project_are_rejected(self):
        for tags in (["Fabric", "1.21.1"], ["NeoForge", MC]):
            self.files[PROJECT] = [release(gameVersions=tags)]
            self.assertIsNone(catalogue.download(PROJECT, MC, LOADER, force=True))
        self.files[PROJECT] = [release(pid="123")]
        with self.assertRaisesRegex(ValueError, "another project"):
            catalogue.versions(PROJECT, MC, LOADER, force=True)

    def test_restricted_download_keeps_release_and_external_page(self):
        self.projects[PROJECT]["allowModDistribution"] = False
        versions = catalogue.versions(PROJECT, MC, LOADER)
        self.assertTrue(versions[0]["compatible"])
        self.assertIsNone(versions[0]["url"])
        with self.assertRaises(catalogue.ExternalDownloadRequired) as raised:
            catalogue.download(PROJECT, MC, LOADER)
        self.assertEqual(raised.exception.url, PAGE + "/files/" + FILE)

    def test_release_pagination_and_retry_empty_cache(self):
        self.files[PROJECT] = [release(fid=str(100 + i)) for i in range(51)]
        first = catalogue.versions(PROJECT, MC, LOADER)
        second = catalogue.versions(PROJECT, MC, LOADER, offset=first.next_offset)
        self.assertEqual((len(first), len(second), second.next_offset), (50, 1, None))
        self.files[PROJECT] = []
        self.assertEqual(catalogue.versions(PROJECT, MC, LOADER, force=True), [])
        self.files[PROJECT] = [release()]
        self.assertEqual(catalogue.versions(PROJECT, MC, LOADER), [])
        self.assertEqual(len(catalogue.versions(PROJECT, MC, LOADER, force=True)), 1)

    def test_negative_cache_expires_and_failure_is_not_no_build(self):
        self.files[PROJECT] = []
        with patch.object(local_cache.time, "time", return_value=100):
            self.assertEqual(catalogue.versions(PROJECT, MC, LOADER), [])
        self.files[PROJECT] = [release()]
        with patch.object(local_cache.time, "time", return_value=161):
            self.assertEqual(len(catalogue.versions(PROJECT, MC, LOADER)), 1)
        self.files[PROJECT] = []
        catalogue.versions(PROJECT, MC, LOADER, force=True)
        with patch.object(modpacks, "_cf_request", side_effect=OSError("offline")):
            with self.assertRaisesRegex(OSError, "offline"):
                catalogue.versions(PROJECT, MC, LOADER, force=True)

    def test_missing_credentials_and_cancel(self):
        with patch.object(modpacks, "curseforge_enabled", return_value=False):
            with self.assertRaisesRegex(ValueError, "API key"):
                catalogue.search("portals", MC, LOADER)
        event = threading.Event(); event.set()
        with self.assertRaises(net.DownloadCancelled):
            catalogue.download(PROJECT, MC, LOADER, cancel_event=event)
        self.assertEqual(self.calls, [])

    def test_dependency_cycles_optional_edges_and_missing_build(self):
        self.projects["42"] = project("42")
        self.files["42"] = [release("42", "4242", dependencies=[{"modId": int(PROJECT), "relationType": 3}])]
        self.files[PROJECT][0]["dependencies"] = [{"modId": 42, "relationType": 3}, {"modId": 999, "relationType": 2}]
        root = catalogue.download(PROJECT, MC, LOADER)
        self.assertEqual([d["project_id"] for d in catalogue.required_dependencies(root, MC, LOADER)], ["42"])
        local_cache.invalidate("cf_mod_versions")
        self.files["42"] = []
        with self.assertRaisesRegex(ValueError, "no matching build"):
            catalogue.required_dependencies(root, MC, LOADER)

    def test_install_source_metadata_real_jar_graph_and_hash_validation(self):
        def transfer(path, url, **kwargs):
            payload = jar()
            self.assertEqual(kwargs["expected_hash"], ("sha1", hashlib.sha1(payload).hexdigest()))
            Path(path).write_bytes(payload)
        with patch.object(mods.net, "download_to", side_effect=transfer):
            result = mods.install_mod_with_dependencies("unused", FILENAME, MC, LOADER,
                project_id=PROJECT, source="curseforge", file_id=FILE)
        self.assertEqual(result["installed"], [FILENAME])
        self.assertEqual(result["failed"], [])
        installed = next(m for m in mods.list_mods(MC, LOADER) if m["filename"] == FILENAME)
        self.assertEqual((installed["source"], installed["project_id"], installed["file_id"]), ("curseforge", PROJECT, FILE))
        self.assertEqual(mods._mod_ref(installed), "curseforge:" + PROJECT)
        self.assertIn("curseforge:" + PROJECT, mods.installed_project_ids(MC, LOADER))
        self.assertNotIn(PROJECT, mods.installed_project_ids(MC, LOADER))
        directory = mods.resolve_profile_dir(MC, LOADER)
        mods._write_meta(directory, FILENAME, None, icon_url="new-icon")
        self.assertEqual(mods._read_meta(directory, FILENAME)["source"], "curseforge")

    def test_jar_metadata_rejects_mislabeled_download_before_publication(self):
        name = "wrong-version.jar"
        payload = jar("wrong", "1.21.1")
        with patch.object(mods.net, "download_to", side_effect=lambda path, *a, **k: Path(path).write_bytes(payload)):
            with self.assertRaisesRegex(ValueError, "does not support"):
                mods.download_mod("https://edge.forgecdn.net/wrong.jar", name, mc_version=MC,
                    loader=LOADER, project_id="99", source="curseforge",
                    hashes={"sha1": hashlib.sha1(payload).hexdigest()})
        self.assertFalse(Path(mods.resolve_profile_dir(MC, LOADER), name).exists())

    def test_hash_failure_does_not_publish_and_updates_keep_previous_bytes(self):
        name = "verified-update.jar"
        payload = jar("verified_update")
        with patch.object(mods.net, "download_to", side_effect=lambda path, *a, **k: Path(path).write_bytes(payload)):
            with self.assertRaisesRegex(ValueError, "published content hash"):
                mods.download_mod("https://edge.forgecdn.net/update.jar", name, mc_version=MC,
                    loader=LOADER, project_id=PROJECT, slug="immersive-portal", source="curseforge",
                    hashes={"sha1": "0" * 40})
        directory = mods.get_profile_dir(MC, LOADER)
        self.assertFalse(Path(directory, name).exists())
        Path(directory, name).write_bytes(payload)
        mods._write_meta(directory, name, "immersive-portal", project_id=PROJECT, source="curseforge", file_id="old")
        updated = payload + b"revision"
        with patch.object(mods.net, "download_to", side_effect=lambda path, *a, **k: Path(path).write_bytes(updated)):
            mods.download_mod("https://edge.forgecdn.net/update.jar", name, mc_version=MC,
                loader=LOADER, project_id=PROJECT, slug="immersive-portal", source="curseforge", file_id="new",
                hashes={"sha1": hashlib.sha1(updated).hexdigest()})
        backup = Path(directory, "previous-old-" + name + ".disabled")
        self.assertEqual(backup.read_bytes(), payload)
        self.assertEqual(Path(directory, name).read_bytes(), updated)
        self.assertEqual(mods._read_meta(directory, backup.name)["file_id"], "old")

    def test_legacy_metadata_and_cross_source_same_slug(self):
        directory = mods.get_profile_dir(MC, LOADER)
        for name, source in (("same-1.jar", "modrinth"), ("same-2.jar", "curseforge")):
            Path(directory, name).write_bytes(jar("same"))
            mods._write_meta(directory, name, "same", project_id="22", source=source)
        self.assertEqual(mods.find_other_copies(directory, "same-2.jar", "same", "22"), [])
        Path(directory, "legacy.jar").write_bytes(jar("legacy"))
        mods._write_meta(directory, "legacy.jar", "legacy", project_id="legacy-id")
        item = next(m for m in mods.list_mods(MC, LOADER) if m["filename"] == "legacy.jar")
        self.assertEqual(item["source"], "modrinth")


class QueuedThread:
    jobs = []
    def __init__(self, target, **kwargs):
        self.target = target
    def start(self):
        self.jobs.append(self.target)


class CatalogueUITests(unittest.TestCase):
    def setUp(self):
        import flet as ft
        from _fuzz_common import FakePage
        from cubeon.theme import THEME, section_label
        from test_content_install_feedback import functions, env, ImmediateExecutor
        from ui import mods_tab
        self.ui, self.env = mods_tab, env
        self.patches = [patch.object(mods_tab.threading, "Thread", QueuedThread),
                        patch.object(mods_tab, "ThreadPoolExecutor", ImmediateExecutor),
                        patch.object(thread_safe_ui, "refresh"),
                        patch.object(mods_tab.core, "list_mods", return_value=[]),
                        patch.object(mods_tab, "check_content", return_value={"unfixed": []})]
        for patched in self.patches:
            patched.start(); self.addCleanup(patched.stop)
        self.state = dict(selected_mc_version=MC, mod_loader=LOADER)
        self.tab, refresh, load, profile = mods_tab.build_mods_tab(FakePage(), {}, self.state,
            ft.Dropdown(value=MC), section_label=section_label, **THEME)
        self.fns = functions(refresh, load, profile)
        self.search = env(self.fns["run_mod_search"])["mod_search_field"]
        self.search.value = "immersive portals"
        QueuedThread.jobs.clear()

    def finish_search(self, mr, cf, order=(0, 1)):
        def search(*args, **kwargs):
            response = cf if kwargs.get("source") == "curseforge" else mr
            if isinstance(response, Exception):
                raise response
            return copy.deepcopy(response)
        with patch.object(self.ui.core, "search_mods", side_effect=search):
            self.fns["run_mod_search"]()
            jobs, QueuedThread.jobs = QueuedThread.jobs[:], []
            self.assertEqual(len(jobs), 2)
            for index in order:
                jobs[index]()
        return self.env(self.fns["_render_browse_page"])["browse_state"]

    def test_both_completion_orders_keep_reported_cf_result(self):
        for order in ((0, 1), (1, 0)):
            self.search.value += " " + str(order[0])
            state = self.finish_search([], [dict(project_id=PROJECT, title="Immersive Portal")], order)
            self.assertEqual([(h["source"], h["project_id"]) for h in state["results"]], [("curseforge", PROJECT)])
            self.assertFalse(state["provider_pending"])

    def test_full_pages_interleave_without_dropping_either_source(self):
        hits = [dict(project_id=str(i), title="Same name") for i in range(24)]
        state = self.finish_search(hits, hits)
        self.assertEqual(len(state["results"]), 48)
        self.assertEqual([h["source"] for h in state["results"][:4]], ["modrinth", "curseforge"] * 2)
        self.assertEqual(len({catalogue.identity(h) for h in state["results"]}), 48)

    def test_provider_failures_keep_healthy_results_and_retry(self):
        for mr, cf in (([dict(project_id="a", title="A")], OSError("CF offline")),
                       (OSError("MR offline"), [dict(project_id=PROJECT, title="IP")]),
                       (OSError("MR offline"), OSError("CF offline"))):
            self.search.value += "x"
            state = self.finish_search(mr, cf)
            self.assertTrue(state["provider_errors"])
            self.assertEqual(len(state["results"]), int(isinstance(mr, list) or isinstance(cf, list)))
            scope = self.env(self.fns["_render_browse_page"])
            self.assertFalse(scope["browse_retry"].disabled)

    def test_stale_instance_response_cannot_paint(self):
        with patch.object(self.ui.core, "search_mods", return_value=[dict(project_id="old", title="Old")]):
            self.fns["run_mod_search"]()
            jobs, QueuedThread.jobs = QueuedThread.jobs[:], []
            self.state["selected_mc_version"] = "1.20.1"
            for job in jobs:
                job()
        self.assertNotEqual(self.env(self.fns["_render_browse_page"])["browse_state"]["results"], [dict(project_id="old", title="Old")])

    def test_retry_forces_both_providers_and_negative_session_expires(self):
        self.finish_search([], [])
        with patch.object(self.ui.core, "search_mods", return_value=[]) as search:
            self.fns["_retry_search"]()
            while QueuedThread.jobs:
                QueuedThread.jobs.pop(0)()
            self.assertEqual(search.call_count, 2)
            self.assertTrue(all(call.kwargs.get("force") for call in search.call_args_list))
            state = self.env(self.fns["_render_browse_page"])["browse_state"]
            state["fetched_at"] -= 61
            self.fns["run_mod_search"]()
            self.assertEqual(len(QueuedThread.jobs), 2)

    def test_curseforge_row_detail_and_version_actions_share_source_claim(self):
        hit = dict(source="curseforge", project_id=PROJECT, title="Immersive Portal", slug="immersive-portal")
        row = self.fns["build_browse_row"](hit)
        action = row.content.controls[-1]
        action.on_click(None)
        install_job = QueuedThread.jobs.pop()
        with patch.object(self.ui.core, "get_mod_details", return_value=hit) as details, \
             patch.object(self.ui.core, "get_mod_versions", return_value=[dict(id=FILE, file_id=FILE,
                filename=FILENAME, url="https://edge.forgecdn.net/mod.jar", compatible=True)]):
            row.on_click(None)
            QueuedThread.jobs.pop()()
            self.assertEqual(details.call_args.args[0], "curseforge:" + PROJECT)
        buttons = [control for control in __import__("_fuzz_common").walk(self.tab)
                   if hasattr(control, "_cubeon_install_paint")]
        self.assertTrue(any(control is not action and not control.disabled for control in buttons))
        versions = next(control for control in buttons if control is not action)
        versions.on_click(None)
        with patch.object(self.ui.core, "get_mod_download") as lookup:
            install_job()
            lookup.assert_not_called()


if __name__ == "__main__":
    unittest.main()
