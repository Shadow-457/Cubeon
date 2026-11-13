"""Exercise real browse/detail callbacks while installs remain in flight."""
import inspect
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common as fz
import flet as ft
from app_driver import DriverPage
from cubeon import icons, net, thread_safe_ui
from cubeon.theme import THEME, section_label
from ui.install_feedback import InstallFeedback, progress_text
from ui.project_readme import readme_markdown
from ui import mods_tab as ui_mods
from ui.mods_tab import build_mods_tab
from ui.modpacks_tab import build_modpacks_tab
from ui.server_tab import build_server_tab


class QueuedThread:
    jobs = []
    def __init__(self, target, args=(), kwargs=None, **_):
        self.run = lambda: target(*args, **(kwargs or {}))
    def start(self):
        self.jobs.append(self.run)


class ImmediateFuture:
    def __init__(self, fn):
        self.value = fn()
    def result(self):
        return self.value


class ImmediateExecutor:
    def __init__(self, **_kwargs):
        pass
    def __enter__(self):
        return self
    def __exit__(self, *_args):
        return False
    def submit(self, fn):
        return ImmediateFuture(fn)


def functions(*roots):
    found, seen = {}, set()
    def visit(fn):
        if not inspect.isfunction(fn) or id(fn) in seen:
            return
        seen.add(id(fn))
        found[fn.__name__] = fn
        for value in inspect.getclosurevars(fn).nonlocals.values():
            visit(value)
    for fn in roots:
        visit(fn)
    return found


def env(fn):
    return inspect.getclosurevars(fn).nonlocals


def text(control):
    content = control.content
    return content.value if isinstance(content, ft.Text) else content.controls[1].value


class ContentInstallTests(unittest.TestCase):
    def setUp(self):
        self.stubs = fz.install_safe_stubs()
        self.page = DriverPage()
        self.state = {"selected_mc_version": "1.20.1", "mod_loader": "fabric"}
        self.drop = ft.Dropdown(value="1.20.1")
        self.patches = [patch("threading.Thread", QueuedThread),
                        patch.object(ui_mods, "ThreadPoolExecutor", ImmediateExecutor),
                        patch.object(icons, "prefetch"),
                        patch.object(thread_safe_ui, "refresh")]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        QueuedThread.jobs.clear()
        self.core = self.stubs.core
        self.core.list_mods = lambda *a, **kw: []
        self.core.list_content = lambda *a, **kw: []
        self.core.mod_doctor = lambda *a, **kw: {"fixed": []}
        self.core.get_mod_details = lambda ref: {"project_id": ref, "title": ref, "slug": ref}
        self.core.get_mod_versions = lambda *a, **kw: [{
            "filename": "demo.jar", "url": "offline", "compatible": True, "version_number": "1",
            "game_versions": ["1.20.1"], "loaders": ["fabric"]}]

    def build_mods(self):
        root, refresh, load, reload = build_mods_tab(
            self.page, {}, self.state, self.drop, section_label=section_label, **THEME)
        self.mods_root = root
        return functions(refresh, load, reload)

    def detail_buttons(self):
        detail = None
        for attribute, kind in (('mods_root', 'mod'), ('modpacks_root', 'modpack')):
            root = getattr(self, attribute, None)
            if root is not None and root.controls[1].visible:
                versions = next(c for c in fz.walk(root)
                                if getattr(c, 'data', None) == kind + '-detail-tab-versions')
                versions.on_click(None)
                detail = root.controls[1]
                break
        if detail is None:
            detail = self.page._dialogs.controls[-1]
        return [c for c in fz.walk(detail)
                if hasattr(c, "_cubeon_install_paint")]

    def test_browse_detail_and_rebuild_share_claim_and_progress(self):
        fns = self.build_mods()
        project = {"project_id": "demo", "title": "Demo", "slug": "demo"}
        row = fns["build_browse_row"](project)
        button = row.content.controls[-1]
        button.on_click(None)
        installer = QueuedThread.jobs.pop()
        row.on_click(None)
        QueuedThread.jobs.pop()()
        details = self.detail_buttons()
        self.assertEqual(len(details), 2)  # Latest and version-row controls.
        self.assertTrue(all(not c.disabled and text(c) == "Cancel" for c in details))
        self.assertIs(fns["build_browse_row"](dict(project)), row)
        self.assertFalse(button.disabled)
        self.assertEqual(QueuedThread.jobs, [])
        def install(*a, **kw):
            kw["progress_cb"](.42, 1)
            self.assertTrue(all(text(c) == "Cancel · 42%" and not c.disabled for c in [button, *details]))
            self.assertTrue(all("42%" in c.tooltip for c in [button, *details]))
            self.assertEqual(kw["mc_version"], "1.20.1")
            return {"installed": ["demo.jar"], "failed": []}
        self.core.get_mod_download = lambda *a, **kw: {"filename": "demo.jar", "url": "offline"}
        self.core.install_mod_with_dependencies = install
        installer()
        self.assertTrue(all(text(c) == "Installed" and c.disabled for c in [button, *details]))

    def test_detail_install_locks_other_buttons_and_browse(self):
        fns = self.build_mods()
        row = fns["build_browse_row"]({"project_id": "demo", "title": "Demo"})
        row.on_click(None)
        QueuedThread.jobs.pop()()
        details = self.detail_buttons()
        details[0].on_click(None)
        self.assertTrue(all(not c.disabled and text(c) == "Cancel" for c in [row.content.controls[-1], *details]))
        self.assertEqual(len(QueuedThread.jobs), 1)
        def fail(*a, **kw):
            raise RuntimeError("offline")
        self.core.install_mod_with_dependencies = fail
        QueuedThread.jobs.pop()()
        self.assertTrue(all(not c.disabled and text(c) == "Try again" for c in [row.content.controls[-1], *details]))
        details[1].on_click(None)
        self.assertEqual(len(QueuedThread.jobs), 1)

    def test_pack_and_shader_unknown_sizes_and_clamped_percent(self):
        for kind in ("resourcepack", "shader"):
            fns = self.build_mods()
            env(fns["_ct"])["active_content"]["type"] = kind
            row = fns["build_browse_row"]({"project_id": kind, "title": kind})
            button = row.content.controls[-1]
            self.core.get_content_download = lambda *a, **kw: {"filename": "demo.zip", "url": "offline"}
            def install(*a, **kw):
                kw["progress_cb"](128 * 1024, 0)
                self.assertEqual(text(button), "Cancel · 128 KB")
                kw["progress_cb"](120, 100)
                self.assertEqual(text(button), "Cancel · 100%")
                kw["fix_cb"]({"reason": "Pack format widened for this Minecraft version."})
            self.core.download_content = install
            button.on_click(None)
            QueuedThread.jobs.pop()()
            self.assertEqual(text(button), "Installed")
            self.assertEqual(button.tooltip, "Pack format widened for this Minecraft version.")
            self.assertIs(fns["build_browse_row"]({"project_id": kind, "title": kind}, True), row)
            self.assertEqual(button.tooltip, "Pack format widened for this Minecraft version.")

    def test_modpack_lookup_does_not_release_install_button(self):
        self.modpacks_root, refresh, load = build_modpacks_tab(self.page, {}, self.state,
            section_label=section_label, go_to_pack=lambda m: None, **THEME)
        fns = functions(refresh, load)
        row = fns["build_pack_row"]({"project_id": "pack", "provider": "modrinth", "title": "Pack"})
        button = row.content.controls[-1]
        self.core.get_modpack_file = lambda *a, **kw: {"url": "offline"}
        button.on_click(None)
        QueuedThread.jobs.pop()()  # File lookup starts the longer install worker.
        self.assertTrue(button.disabled)
        self.assertEqual(len(QueuedThread.jobs), 1)
        row.on_click(None)
        QueuedThread.jobs.pop()()
        details = self.detail_buttons()
        self.assertTrue(all(c.disabled for c in details))
        def install(*a, **kw):
            kw["max_cb"](10)
            kw["progress_cb"](4)
            self.assertTrue(all(text(c) == "40%" for c in [button, *details]))
            return {"name": "Pack"}
        self.core.install_modpack_from_url = install
        QueuedThread.jobs.pop()()
        self.assertEqual(text(button), "Installed")

    def test_detail_keeps_filtered_empty_release_and_html_overview(self):
        fns = self.build_mods()
        self.core.get_mod_details = lambda ref: {'title': 'Resourceful Config',
            'body': '<center>Readable configuration docs</center><a href="https://example.com">Docs</a>'}
        self.core.get_mod_versions = lambda *args, **kwargs: []
        with patch.object(self.core, 'get_mod_download') as fallback:
            fns['build_browse_row']({'project_id': 'config', 'title': 'Resourceful Config'}).on_click(None)
            QueuedThread.jobs.pop()()
            fallback.assert_not_called()
        readme = next(control for control in fz.walk(self.mods_root)
                      if getattr(control, 'data', None) == 'mod-detail-readme')
        self.assertIn('Readable configuration docs', readme.value)
        self.assertIn('[Docs](<https://example.com>)', readme.value)
        self.assertNotIn('<center>', readme.value)
        labels = [control.value for control in fz.walk(self.mods_root) if isinstance(control, ft.Text)]
        self.assertIn('No matching build for this Minecraft version and loader.', labels)

    def test_failed_release_lookup_is_retryable_not_incompatible(self):
        fns = self.build_mods()
        def offline(*args, **kwargs):
            raise RuntimeError('Offline')
        self.core.get_mod_versions = offline
        self.core.get_mod_download = offline
        fns['build_browse_row']({'project_id': 'offline', 'title': 'Offline'}).on_click(None)
        QueuedThread.jobs.pop()()
        labels = [control.value for control in fz.walk(self.mods_root) if isinstance(control, ft.Text)]
        self.assertIn("Couldn't check compatible releases.", labels)
        self.assertFalse(any('No build for' in str(label) for label in labels))
        self.assertTrue(any(isinstance(control, ft.TextButton) and control.content == 'Retry'
                            for control in fz.walk(self.mods_root)))

    def test_successful_incompatible_version_list_does_not_trigger_fallback(self):
        fns = self.build_mods()
        self.core.get_mod_versions = lambda *args, **kwargs: [{
            'filename': 'older.jar', 'url': 'offline', 'compatible': False,
            'version_number': '1', 'game_versions': ['1.21.1'], 'loaders': ['fabric']}]
        with patch.object(self.core, 'get_mod_download') as fallback:
            fns['build_browse_row']({'project_id': 'older', 'title': 'Older'}).on_click(None)
            QueuedThread.jobs.pop()()
            fallback.assert_not_called()
        labels = [control.value for control in fz.walk(self.mods_root) if isinstance(control, ft.Text)]
        self.assertIn('No matching build for this Minecraft version and loader.', labels)
        self.assertNotIn("Couldn't check compatible releases.", labels)

    def test_html_readme_keeps_images_text_and_safe_links(self):
        body = '<img src="https://example.com/header.png"/><center>Easy config</center>' \
               '<script>unwanted content</script><a href="javascript:alert(1)">Text</a>'
        normalized = readme_markdown(body)
        self.assertIn('![](<https://example.com/header.png>)', normalized)
        self.assertIn('Easy config', normalized)
        self.assertNotIn('unwanted content', normalized)
        self.assertNotIn('javascript:', normalized)
        markdown = '# Plain Markdown\n\n[Docs](https://example.com)'
        self.assertEqual(readme_markdown(markdown), markdown)

    def test_cancel_from_detail_stops_queued_browse_job_before_lookup(self):
        fns = self.build_mods()
        row = fns['build_browse_row']({'project_id': 'cancel', 'title': 'Cancel'})
        button = row.content.controls[-1]
        button.on_click(None)
        installer = QueuedThread.jobs.pop()
        row.on_click(None)
        QueuedThread.jobs.pop()()
        details = self.detail_buttons()
        details[0].on_click(None)
        self.assertTrue(all(control.disabled and text(control) == 'Cancelling…'
                            for control in [button, *details]))
        with patch.object(self.core, 'get_mod_download') as lookup:
            installer()
            lookup.assert_not_called()
        self.assertFalse(button.disabled)
        self.assertEqual(text(button), 'Install')
        self.assertEqual(QueuedThread.jobs, [])

    def test_cancel_during_transfer_releases_all_actions_for_retry(self):
        fns = self.build_mods()
        row = fns['build_browse_row']({'project_id': 'cancel-transfer', 'title': 'Cancel'})
        row.on_click(None)
        QueuedThread.jobs.pop()()
        details = self.detail_buttons()
        button = row.content.controls[-1]
        def install(*args, **kwargs):
            kwargs['progress_cb'](.5, 1)
            button.on_click(None)
            net.check_cancelled(kwargs['cancel_event'])
        self.core.install_mod_with_dependencies = install
        details[0].on_click(None)
        QueuedThread.jobs.pop()()
        self.assertTrue(all(not control.disabled and text(control) == 'Install'
                            for control in [button, *details]))

    def test_plugin_detail_install_invokes_handler_and_shares_state(self):
        from cubeon.theme import pixel_divider
        console, settings, plugins, refresh = build_server_tab(self.page, {}, self.state,
            section_label=section_label, pixel_divider=pixel_divider, **THEME)
        fns = functions(refresh, *(getattr(c, "on_click", None) for root in (console, settings, plugins) for c in fz.walk(root)))
        QueuedThread.jobs.clear()  # Ignore the separately stubbed public-address watcher.
        env(fns["_plugin_result_row"])["active_version"]["value"] = "1.20.1"
        row = fns["_plugin_result_row"]({"project_id": "plugin", "slug": "plugin", "title": "Plugin"})
        button = row.content.controls[-1]
        row.on_click(None)
        QueuedThread.jobs.pop()()
        details = self.detail_buttons()
        details[0].on_click(None)
        self.assertEqual(len(QueuedThread.jobs), 1)
        self.assertTrue(button.disabled and details[0].disabled)
        self.core.get_plugin_download = lambda *a, **kw: {"url": "offline", "filename": "plugin.jar"}
        def download(*a, **kw):
            kw["progress_cb"](63, 100)
            self.assertEqual(text(button), "63%")
            self.assertEqual(text(details[0]), "63%")
        self.core.download_plugin = download
        QueuedThread.jobs.pop()()
        self.assertEqual(text(button), "Installed")

    def test_cached_files_advance_batch_to_completion(self):
        # Use the real dependency orchestrator, with disk/network leaves isolated.
        from cubeon import mods
        with patch.object(mods, "installed_project_ids", return_value=set()), \
             patch.object(mods, "required_dependencies", return_value=[{"project_id": "dep", "filename": "dep.jar", "url": "offline"}]), \
             patch.object(mods, "download_mod"):
            progress = []
            mods.install_mod_with_dependencies("offline", "demo.jar", "1.20.1", "fabric", project_id="demo",
                progress_cb=lambda done, total: progress.append((done, total)))
        self.assertEqual(progress, [(1, 2), (2, 2)])
        self.assertIn("100%", progress_text(*progress[-1], batch=True))


if __name__ == "__main__":
    unittest.main()
