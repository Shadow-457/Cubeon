"""Offline regressions for Modrinth discovery, filters, links, and pagination."""
import json
import os
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home

_sandbox_home.isolate()

from cubeon import mods
from ui.mods_tab import mod_compatibility_note


def hit(project="durabilitywarner", versions=None, loader="fabric"):
    return {
        "project_id": project, "slug": project, "title": project,
        "description": "Warns before armor breaks.", "downloads": 351,
        "versions": versions if versions is not None else ["1.21.11"],
        "categories": ["utility", loader],
    }


class ModSearchTests(unittest.TestCase):
    def setUp(self):
        mods.local_cache.invalidate("search_mods")
        mods.local_cache.invalidate("mod_details")
        self.calls = []
        self.routes = {}
        self.network = patch.object(mods.net, "get_json", side_effect=self.fetch)
        self.network.start()
        self.addCleanup(self.network.stop)

    def fetch(self, url, **kwargs):
        params = dict(kwargs.get("params") or {})
        self.calls.append((url, params))
        if url.endswith("/search"):
            return {"hits": self.routes.get((params["query"], int(params["offset"])), [])}
        return self.routes[url.rsplit("/", 1)[-1]]

    def test_exact_match_preserves_relevance_and_filters(self):
        self.routes["armor durability warner", 0] = [hit("exact"), hit("popular")]
        results = mods.search_mods("armor durability warner", "1.21.11", "fabric",
                                    categories=["equipment"])
        self.assertEqual([result["slug"] for result in results], ["exact", "popular"])
        self.assertEqual(len(self.calls), 1)
        params = self.calls[0][1]
        self.assertEqual(params["index"], "relevance")
        self.assertEqual(json.loads(params["facets"]), [
            ["project_type:mod"], ["categories:fabric"],
            ["versions:1.21.11"], ["categories:equipment"],
        ])

    def test_descriptive_name_falls_back_without_removing_filters(self):
        self.routes["durability warner", 0] = [hit()]
        results = mods.search_mods("armor durability warner", "1.21.11", "fabric")
        self.assertEqual(results[0]["slug"], "durabilitywarner")
        self.assertEqual(results[0]["search_query"], "durability warner")
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0][1]["facets"], self.calls[1][1]["facets"])
        self.assertEqual(results[0]["game_versions"], ["1.21.11"])
        self.assertEqual(results[0]["loaders"], ["fabric"])

    def test_british_spelling_can_match_american_title(self):
        self.routes["armor hud", 0] = [hit()]
        result = mods.search_mods("armour hud")[0]
        self.assertEqual(result["search_query"], "armor hud")
        self.assertEqual(len(self.calls), 2)

    def test_cached_related_search_keeps_the_same_query_on_later_pages(self):
        self.routes["durability warner", 0] = [hit("first"), hit("second")]
        self.routes["durability warner", 2] = [hit("third")]
        self.routes["armor durability", 4] = [hit("unrelated")]
        first = mods.search_mods("armor durability warner", limit=2)
        second = mods.search_mods("armor durability warner", limit=2, offset=2)
        last = mods.search_mods("armor durability warner", limit=2, offset=4)
        self.assertEqual([result["slug"] for result in first], ["first", "second"])
        self.assertEqual(second[0]["slug"], "third")
        self.assertEqual(last, [])
        self.assertEqual([params["query"] for _, params in self.calls], [
            "armor durability warner", "durability warner", "durability warner", "durability warner",
        ])
        before = len(self.calls)
        mods.search_mods("armor durability warner", limit=2)
        self.assertEqual(len(self.calls), before)

    def test_short_and_empty_queries_do_not_fan_out(self):
        for query in ("", "durabilitywarner"):
            mods.search_mods(query)
        self.assertEqual(len(self.calls), 2)
        self.assertEqual(self.calls[0][1]["index"], "downloads")

    def test_no_matches_are_bounded_and_do_not_start_new_search_on_later_pages(self):
        self.assertEqual(mods.search_mods("armor durability warner"), [])
        self.assertEqual(len(self.calls), 3)
        self.assertEqual(mods.search_mods("armor durability warner", offset=10), [])
        self.assertEqual(len(self.calls), 3)

    def test_all_modrinth_search_only_removes_explicit_compatibility_filters(self):
        self.routes["durabilitywarner", 0] = [hit(versions=["1.20.1"], loader="forge")]
        result = mods.search_mods("durabilitywarner", mc_version=None, loader=None)[0]
        self.assertEqual(json.loads(self.calls[0][1]["facets"]), [["project_type:mod"]])
        self.assertIn("No build for Minecraft", mod_compatibility_note(result, "1.21.11", "fabric"))

    def test_pasted_project_link_resolves_without_search_index_or_category_filters(self):
        self.routes["durabilitywarner"] = {
            "id": "lFB7eEeE", "slug": "durabilitywarner", "project_type": "mod",
            "title": "DurabilityWarner", "game_versions": ["1.21.11"], "loaders": ["fabric"],
        }
        query = "https://modrinth.com/mod/durabilitywarner/version/build?from=search#about"
        result = mods.search_mods(query, "1.20.1", "forge", categories=["performance"])[0]
        self.assertEqual(result["project_id"], "lFB7eEeE")
        self.assertEqual(result["game_versions"], ["1.21.11"])
        self.assertEqual(len(self.calls), 1)
        self.assertEqual(self.calls[0][0], mods.MODRINTH_API + "/project/durabilitywarner")
        self.assertEqual(mods.search_mods(query, offset=10), [])

    def test_only_trusted_modrinth_project_links_are_resolved(self):
        for query in ("https://modrinth.com.evil.test/mod/demo", "https://evil.test/mod/demo",
                      "https://modrinth.com/user/demo", "https://modrinth.com/mod/..", "[broken"):
            self.assertIsNone(mods._mod_project_reference(query))
        self.assertEqual(mods._mod_project_reference("modrinth.com/project/lFB7eEeE"), "lFB7eEeE")

    def test_other_project_types_are_not_offered_as_mods(self):
        self.routes["pack"] = {"id": "pack", "project_type": "resourcepack"}
        self.assertEqual(mods.search_mods("https://modrinth.com/project/pack"), [])

    def test_discovery_never_downloads_or_installs_content(self):
        self.routes["durabilitywarner", 0] = [hit()]
        with patch.object(mods, "get_mod_download") as download, \
                patch.object(mods, "install_mod_with_dependencies") as install:
            mods.search_mods("durabilitywarner", mc_version=None, loader=None)
        download.assert_not_called()
        install.assert_not_called()

    def test_unknown_metadata_still_requires_install_time_file_resolution(self):
        self.assertEqual(mod_compatibility_note({}, "1.21.11", "fabric"), "")
        self.assertIn("Choose a mod loader", mod_compatibility_note(hit(), "1.21.11", "vanilla"))
        self.assertIn("No Forge build", mod_compatibility_note({"loaders": ["fabric"]}, "1.21.11", "forge"))
        self.assertEqual(mod_compatibility_note({"game_versions": ["1.21.11"], "loaders": ["fabric"]},
                                                "1.21.11", "fabric"), "")

    def test_empty_results_refresh_after_one_minute_instead_of_remaining_hidden(self):
        with patch.object(mods.local_cache.time, "time", return_value=1000) as clock:
            self.assertEqual(mods.search_mods("durabilitywarner"), [])
            self.routes["durabilitywarner", 0] = [hit()]
            clock.return_value = 1030
            self.assertEqual(mods.search_mods("durabilitywarner"), [])
            self.assertEqual(len(self.calls), 1)
            clock.return_value = 1061
            self.assertEqual(mods.search_mods("durabilitywarner")[0]["slug"], "durabilitywarner")
            self.assertEqual(len(self.calls), 2)

    def test_memory_cache_honors_each_callers_freshness_window(self):
        cache = mods.local_cache
        with patch.object(cache.time, "time", return_value=1000) as clock:
            cache.set("search_mods", "freshness", [hit()])
            self.assertIsNotNone(cache.get("search_mods", "freshness", max_age=3600))
            clock.return_value = 1061
            self.assertIsNone(cache.get("search_mods", "freshness", max_age=60))
            self.assertIsNotNone(cache.get("search_mods", "freshness", max_age=3600))
            clock.return_value = 22601
            self.assertIsNone(cache.get("search_mods", "freshness", max_age=6 * 3600))

    def test_disk_stale_reads_do_not_make_expired_results_fresh_again(self):
        cache = mods.local_cache
        with patch.object(cache.time, "time", return_value=1000) as clock:
            cache.set("search_mods", "stale", [hit()])
            cache._MEM.clear()
            clock.return_value = 1061
            self.assertIsNotNone(cache.get_stale("search_mods", "stale"))
            self.assertIsNone(cache.get("search_mods", "stale", max_age=60))
            with patch.object(cache, "get_stale", return_value=[hit()]):
                self.assertEqual(cache.cached_call("search_mods", "stale", lambda: [],
                                                  max_age=60, background_refresh=False), [])

    def test_old_project_cache_schema_cannot_break_direct_link_lookup(self):
        mods.local_cache.set("mod_details", {"project": "durabilitywarner"}, {
            "project_id": "old", "slug": "durabilitywarner", "title": "DurabilityWarner",
        })
        self.routes["durabilitywarner"] = {
            "id": "lFB7eEeE", "slug": "durabilitywarner", "project_type": "mod",
            "title": "DurabilityWarner", "game_versions": ["1.21.11"], "loaders": ["fabric"],
        }
        result = mods.search_mods("https://modrinth.com/mod/durabilitywarner")[0]
        self.assertEqual(result["project_id"], "lFB7eEeE")
        self.assertEqual(len(self.calls), 1)


if __name__ == "__main__":
    unittest.main()
