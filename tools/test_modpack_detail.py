"""Modpack card navigation, stale lookups and shared installs without network or disk writes."""
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "tools"), str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
import _fuzz_common as fz
from app_driver import DriverPage
from cubeon import icons, thread_safe_ui
from cubeon.theme import THEME, section_label
from test_content_install_feedback import QueuedThread, env, functions, text
from ui.modpacks_tab import build_modpacks_tab
from ui.mods_tab import build_mods_tab


class ModpackDetailTests(unittest.TestCase):
    def setUp(self):
        self.stubs = fz.install_safe_stubs()
        self.core = self.stubs.core
        self.page = DriverPage()
        self.state = {"selected_mc_version": "1.20.1", "mod_loader": "fabric"}
        self.played = []
        for patcher in (patch("threading.Thread", QueuedThread), patch.object(icons, "prefetch"),
                        patch.object(thread_safe_ui, "refresh")):
            patcher.start()
            self.addCleanup(patcher.stop)
        self.core.get_mod_details = lambda ref: {
            "title": ref.title(), "body": "<h2>Pack guide</h2><p>Full description.</p>",
            "gallery": [{"url": "https://example.com/screenshot.png", "title": "A world"}],
            "downloads": 1234, "game_versions": ["1.12.2"], "loaders": ["forge"]}
        self.versions = [{"version_number": "2.0", "game_versions": ["1.12.2"],
                          "loaders": ["forge"], "compatible": False,
                          "url": "https://cdn.modrinth.com/pack.mrpack"}]
        self.core.get_mod_versions = Mock(side_effect=lambda *a, **kw: self.versions)
        self.core.get_modpack_file = Mock(return_value={"url": "https://cdn.modrinth.com/latest.mrpack"})
        self.core.list_installed_modpacks = lambda: []
        self.pack_root, refresh, load = build_modpacks_tab(
            self.page, {}, self.state, section_label=section_label,
            go_to_pack=self.played.append, embedded=True, **THEME)
        self.fns = functions(refresh, load)
        self.mods_root, _, _, _ = build_mods_tab(
            self.page, {}, self.state, ft.Dropdown(value="1.20.1"), section_label=section_label,
            modpacks_content=ft.Container(self.pack_root, expand=True), **THEME)
        self.mods_root.select_content_type("modpack")
        QueuedThread.jobs.clear()
        self.row = self.fns["build_pack_row"]({
            "source": "modrinth", "project_id": "pack", "title": "Pack",
            "description": "Search description", "author": "Pack maker"})
        self.results = env(self.fns["_render_page"])["results_view"]
        self.results.controls = [self.row]

    def control(self, data):
        return next(c for c in fz.walk(self.mods_root) if getattr(c, "data", None) == data)

    def open(self, row=None):
        (row or self.row).on_click(None)
        QueuedThread.jobs.pop()()

    def test_card_opens_page_and_back_restores_retained_catalogue(self):
        search = next(c for c in fz.walk(self.pack_root) if isinstance(c, ft.TextField)
                      and (c.hint_text or "").startswith("Search modpacks"))
        search.value = "my pack"
        state = env(self.fns["_render_page"])["browse_state"]
        state["page"] = 2
        updates = self.page.update_calls
        self.open()
        self.assertTrue(self.pack_root.controls[1].visible)
        self.assertFalse(self.pack_root.controls[0].visible)
        selector = self.mods_root.controls[0].controls[0]
        self.assertFalse(selector.visible)
        self.assertEqual(self.page._dialogs.controls, [])
        readme = self.control("modpack-detail-readme")
        self.assertIn("Pack guide", readme.value)
        self.assertNotIn("<h2>", readme.value)
        self.assertIn("Full description.", readme.value)
        for name in ("overview", "versions", "gallery"):
            self.assertIsNotNone(self.control("modpack-detail-tab-" + name))
        self.control("modpack-detail-back").on_click(None)
        self.assertTrue(self.pack_root.controls[0].visible)
        self.assertFalse(self.pack_root.controls[1].visible)
        self.assertTrue(selector.visible)
        self.assertIs(self.results.controls[0], self.row)
        self.assertEqual(search.value, "my pack")
        self.assertEqual(state["page"], 2)
        self.assertEqual(self.page.update_calls, updates)

    def test_escape_close_hook_rejects_late_lookup_after_back(self):
        self.row.on_click(None)
        lookup = QueuedThread.jobs.pop()
        self.assertTrue(self.mods_root.close_detail())
        self.assertFalse(self.mods_root.close_detail())
        lookup()
        self.assertFalse(self.pack_root.controls[1].visible)
        self.assertEqual(self.pack_root.controls[1].controls, [])
        self.assertTrue(self.pack_root.controls[0].visible)

    def test_late_lookup_cannot_overwrite_another_pack(self):
        self.row.on_click(None)
        old_lookup = QueuedThread.jobs.pop()
        other = self.fns["build_pack_row"]({"source": "modrinth", "project_id": "other", "title": "Other"})
        self.open(other)
        controls = list(self.pack_root.controls[1].controls)
        old_lookup()
        self.assertEqual(self.pack_root.controls[1].controls, controls)
        labels = [c.value for c in fz.walk(self.pack_root.controls[1]) if isinstance(c, ft.Text)]
        self.assertIn("Other", labels)
        self.assertNotIn("Pack", labels)

    def test_type_switch_closes_modpack_detail(self):
        self.open()
        self.mods_root.select_content_type("resourcepack")
        self.assertFalse(self.pack_root.controls[1].visible)
        self.assertTrue(self.mods_root.controls[0].controls[0].visible)
        self.assertEqual(self.pack_root.controls[1].controls, [])

    def test_curseforge_uses_cached_description_and_install_flow(self):
        self.core.get_mod_details = Mock(side_effect=AssertionError("Modrinth lookup for CurseForge"))
        self.core.get_mod_versions = Mock(side_effect=AssertionError("Modrinth versions for CurseForge"))
        row = self.fns["build_pack_row"]({"source": "curseforge", "project_id": "123",
            "title": "Classic pack", "description": "CurseForge description", "slug": "classic"})
        self.open(row)
        self.assertEqual(self.page._dialogs.controls, [])
        self.assertIn("CurseForge description", self.control("modpack-detail-readme").value)
        self.core.get_mod_details.assert_not_called()
        self.core.get_mod_versions.assert_not_called()
        self.control("modpack-detail-install").on_click(None)
        self.assertTrue(self.pack_root.controls[1].visible)
        QueuedThread.jobs.pop()()
        self.assertEqual(self.core.get_modpack_file.call_args.args[0], "123")

    def test_install_actions_share_progress_and_keep_detail_open(self):
        self.open()
        self.control("modpack-detail-tab-versions").on_click(None)
        primary = self.control("modpack-detail-install")
        version = self.control("modpack-detail-version-install")
        browse = self.row.content.controls[-1]
        primary.on_click(None)
        self.assertTrue(self.pack_root.controls[1].visible)
        self.assertTrue(all(c.disabled for c in (primary, version, browse)))
        QueuedThread.jobs.pop()()

        def install(*args, **kwargs):
            kwargs["max_cb"](10)
            kwargs["progress_cb"](4)
            self.assertEqual([text(c) for c in (primary, version, browse)], ["40%"] * 3)
            return {"name": "Pack"}
        self.core.install_modpack_from_url = install
        QueuedThread.jobs.pop()()
        self.assertTrue(all(c.disabled and text(c) == "Installed" for c in (primary, version, browse)))

    def test_specific_version_uses_pack_version_and_identity(self):
        self.open()
        self.core.get_mod_versions.assert_called_once_with("pack")
        self.control("modpack-detail-tab-versions").on_click(None)
        button = self.control("modpack-detail-version-install")
        self.assertFalse(button.disabled)
        button.on_click(None)
        self.core.install_modpack_from_url = Mock(return_value={"name": "Pack"})
        QueuedThread.jobs.pop()()
        call = self.core.install_modpack_from_url.call_args
        self.assertEqual(call.args[0], self.versions[0]["url"])
        self.assertEqual(call.kwargs["source_id"], "modrinth:pack")
        self.core.get_modpack_file.assert_not_called()


if __name__ == "__main__":
    unittest.main()
