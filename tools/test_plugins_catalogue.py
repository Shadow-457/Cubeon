"""Plugin cards retain geometry, cached status and instance ownership under races."""
import sys
import unittest
import flet as ft
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common
from app_driver import DriverPage
from cubeon import thread_safe_ui
from cubeon.theme import THEME, section_label
from test_content_install_feedback import QueuedThread, env, functions
from ui.plugins_catalogue import build_plugins_catalogue


class PluginsCatalogue(unittest.TestCase):
    def setUp(self):
        self.core = _fuzz_common.install_safe_stubs().core
        self.page, self.active = DriverPage(), {'value': 'server-A'}
        self.items = [dict(filename=f'{i}.jar', display_name=f'Plugin {i}', slug=f'plugin-{i}', enabled=True)
                      for i in range(60)]
        self.core.list_plugins = lambda version: [dict(item) for item in self.items]
        self.core.minecraft_version = lambda version: '1.20.1'
        self.core.get_plugin_details = lambda ref, **kwargs: dict(
            title=ref, body='<h2>Plugin guide</h2><p>Full description.</p>',
            gallery=[{'url': 'https://example.invalid/image.png'}], loaders=['paper'])
        self.releases = [dict(filename='older.jar', url='offline', compatible=True,
                              version_number='1.0', game_versions=['1.20.1'], loaders=['spigot'])]
        self.core.get_plugin_versions = lambda *args, **kwargs: self.releases
        self.patches = [patch('threading.Thread', QueuedThread), patch.object(thread_safe_ui, 'refresh')]
        for p in self.patches:
            p.start(); self.addCleanup(p.stop)
        QueuedThread.jobs.clear()
        self.root, self.refresh, self.search, self.results = build_plugins_catalogue(
            self.page, self.active, section_label=section_label, **THEME)
        self.fns = functions(self.refresh, self.search, *[
            getattr(c, 'on_click', None) for c in _fuzz_common.walk(self.root)])
        self.refresh({'plugins': self.items})
        self.installed = env(self.fns['render_installed'])['installed_plugins_list']

    def hit(self, name='demo'):
        return dict(project_id=name, slug=name, title=name, downloads=10)

    def test_same_grid_and_cached_rows_across_refreshes_and_batches(self):
        self.assertEqual(self.installed.runs_count, self.results.runs_count)
        self.assertEqual(self.installed.child_aspect_ratio, self.results.child_aspect_ratio)
        first = tuple(self.installed.controls[:50])
        self.installed.controls[-1].on_click(None)
        self.assertEqual(len(self.installed.controls), 60)
        self.refresh({'plugins': self.items})
        self.assertEqual(tuple(self.installed.controls[:50]), first)
        self.assertTrue(all(row.height == 96 for row in first))

    def test_switching_reuses_snapshot_without_filesystem_reads(self):
        with patch.object(self.core, 'list_plugins') as read, patch.object(self.page, 'update') as update:
            for _ in range(3):
                self.fns['_on_plugins_view_change']('installed')
                self.fns['_on_plugins_view_change']('browse')
            read.assert_not_called()
            update.assert_not_called()

    def test_toggle_captures_server_and_preserves_card_and_art(self):
        row = self.installed.controls[0]
        image, switch = row.content.controls[0], row.content.controls[2]
        calls = []
        def toggle(version, filename, enabled):
            calls.append((version, filename, enabled))
            self.items[0].update(filename='0.jar.disabled', enabled=False)
        self.core.toggle_plugin = toggle
        switch.value = False
        switch.on_change(SimpleNamespace(control=switch))
        self.assertTrue(switch.disabled)
        self.active['value'] = 'server-B'
        QueuedThread.jobs.pop()()
        self.assertEqual(calls, [('server-A', '0.jar', False)])
        self.active['value'] = 'server-A'
        self.refresh({'plugins': self.items})
        self.assertIs(self.installed.controls[0], row)
        self.assertIs(row.content.controls[0], image)
        self.assertFalse(switch.value)

    def test_failed_toggle_rolls_back_and_protected_plugins_have_no_actions(self):
        switch = self.installed.controls[0].content.controls[2]
        with patch.object(self.core, 'toggle_plugin', side_effect=OSError('disk full')):
            switch.value = False
            switch.on_change(SimpleNamespace(control=switch))
            QueuedThread.jobs.pop()()
        self.assertTrue(switch.value)
        self.assertFalse(switch.disabled)
        row = self.fns['_plugin_row'](dict(filename='managed.jar', display_name='Managed', enabled=True, protected=True))
        self.assertEqual(len(row.content.controls), 3)
        self.assertFalse(callable(getattr(row.content.controls[2], 'on_change', None)))

    def test_search_coalesces_duplicates_caches_results_and_rejects_stale_completion(self):
        calls = []
        self.core.get_recommended_plugins = lambda **kw: [] if kw['source'] == 'curseforge' else calls.append('popular') or [self.hit('popular')]
        self.core.search_plugins = lambda query, **kw: [] if kw['source'] == 'curseforge' else calls.append(query) or [self.hit(query)]
        self.search(); self.search()
        self.assertEqual(len(QueuedThread.jobs), 2)
        popular = list(QueuedThread.jobs)
        QueuedThread.jobs.clear()
        field = env(self.search)['plugin_search_field']
        field.value = 'new'; self.search()
        while QueuedThread.jobs:
            QueuedThread.jobs.pop()()
        rows = tuple(self.results.controls)
        for job in popular:
            job()
        self.assertEqual(tuple(self.results.controls), rows)
        self.search()
        self.assertEqual(tuple(self.results.controls), rows)
        self.assertEqual(calls, ['new', 'popular'])

    def test_failed_refresh_keeps_cards_scrollable_and_retry_visible(self):
        self.core.get_recommended_plugins = lambda **kw: [] if kw['source'] == 'curseforge' else [self.hit()]
        self.search()
        while QueuedThread.jobs:
            QueuedThread.jobs.pop()()
        rows = tuple(self.results.controls)
        self.core.get_recommended_plugins = lambda **kw: (_ for _ in ()).throw(OSError('offline'))
        self.search(force=True)
        self.assertTrue(rows[0].ignore_interactions)
        self.assertFalse(self.results.disabled)
        while QueuedThread.jobs:
            QueuedThread.jobs.pop()()
        self.assertEqual(tuple(self.results.controls), rows)
        self.assertFalse(rows[0].ignore_interactions)
        retry = env(self.search)['retry']
        self.assertFalse(retry.disabled)
        self.assertEqual(retry.opacity, 1)

    def test_failed_initial_snapshot_clears_skeletons_and_can_retry(self):
        self.active['value'] = 'new-server'
        self.refresh(force=True)
        self.assertTrue(all(row.data == 'content-loading' for row in self.installed.controls))
        with patch.object(self.core, 'list_plugins', side_effect=OSError('fixture')):
            with self.assertLogs('cubeon.background_refresh', level='WARNING'):
                QueuedThread.jobs.pop()()
        self.assertEqual(self.installed.controls[0].data, 'content-empty')
        self.refresh(force=True)
        QueuedThread.jobs.pop()()
        self.assertTrue(all(row.height == 96 for row in self.installed.controls[:50]))

    def test_install_and_remove_invalidate_installed_badge_in_place(self):
        self.core.get_recommended_plugins = lambda **kw: [] if kw['source'] == 'curseforge' else [self.hit('plugin-0')]
        self.search()
        while QueuedThread.jobs:
            QueuedThread.jobs.pop()()
        row = self.results.controls[0]
        action = row.content.controls[-1]
        self.assertTrue(action.disabled)
        self.items.pop(0)
        self.refresh({'plugins': self.items})
        self.assertIs(self.results.controls[0], row)
        self.assertFalse(action.disabled)
        self.assertEqual(action.content.controls[1].value, 'Install')
        self.active['value'] = 'server-B'
        with patch.object(self.core, 'get_plugin_download') as lookup:
            action.on_click(None)
            lookup.assert_not_called()
        self.assertEqual(QueuedThread.jobs, [])

    def control(self, data):
        return next(c for c in _fuzz_common.walk(self.root) if getattr(c, 'data', None) == data)

    def open_detail(self, hit=None):
        self.fns['_plugin_result_row'](hit or self.hit()).on_click(None)
        QueuedThread.jobs.pop()()

    def test_detail_and_back_retain_search_and_cards_without_dialogs(self):
        field = env(self.search)['plugin_search_field']
        field.value = 'demo'
        self.open_detail()
        self.assertFalse(self.root.controls[0].visible)
        self.assertTrue(self.root.controls[1].visible)
        self.assertEqual(self.page._dialogs.controls, [])
        self.assertIn('Plugin guide', self.control('plugin-detail-readme').value)
        for name in ('overview', 'versions', 'gallery'):
            self.control('plugin-detail-tab-' + name)
        self.control('plugin-detail-back').on_click(None)
        self.assertTrue(self.root.controls[0].visible)
        self.assertIs(env(self.search)['plugin_search_field'], field)
        self.assertEqual(field.value, 'demo')

    def test_detail_back_and_new_project_reject_stale_lookups(self):
        row = self.fns['_plugin_result_row'](self.hit('first'))
        row.on_click(None)
        old = QueuedThread.jobs.pop()
        self.assertTrue(self.root.close_detail())
        old()
        self.assertEqual(self.root.controls[1].controls, [])
        row.on_click(None)
        old = QueuedThread.jobs.pop()
        self.open_detail(self.hit('second'))
        old()
        self.assertEqual(self.root.controls[1].controls[1].content.controls[1].controls[0].value, 'second')
        self.active['value'] = 'server-B'
        self.refresh({'plugins': self.items})
        self.assertFalse(self.root.controls[1].visible)

    def test_specific_release_keeps_older_file_and_captured_server(self):
        self.open_detail()
        self.control('plugin-detail-tab-versions').on_click(None)
        with patch.object(self.core, 'get_plugin_download') as latest, \
                patch.object(self.core, 'download_plugin') as download:
            self.control('plugin-detail-version-install').on_click(None)
            self.active['value'] = 'server-B'
            QueuedThread.jobs.pop()()
            latest.assert_not_called()
            download.assert_called_once()
            self.assertEqual(download.call_args.args[:3], ('server-A', 'offline', 'older.jar'))

    def test_only_paper_compatible_releases_have_install_actions(self):
        self.releases.extend([
            dict(self.releases[0], filename='fabric.jar', loaders=['fabric']),
            dict(self.releases[0], filename='wrong.jar', compatible=False, game_versions=['1.21'])])
        self.open_detail()
        self.control('plugin-detail-tab-versions').on_click(None)
        actions = [c for c in _fuzz_common.walk(self.root) if getattr(c, 'data', None) == 'plugin-detail-version-install']
        self.assertEqual(len(actions), 1)
        self.root.close_detail()
        self.releases.clear()
        self.open_detail()
        self.assertTrue(self.control('plugin-detail-install').disabled)

    def test_popular_catalogue_uses_server_version_and_multiple_pages(self):
        def catalogue(**kwargs):
            self.assertEqual(kwargs['mc_version'], '1.20.1')
            return [self.hit(str(i)) for i in range(60)] if kwargs['source'] == 'modrinth' else []
        self.core.get_recommended_plugins = catalogue
        self.search()
        while QueuedThread.jobs:
            QueuedThread.jobs.pop()()
        self.assertEqual(len(self.results.controls), 24)
        pager = env(self.search)['plugin_pager_row']
        self.assertEqual(pager.controls[2].content.value, 'Page 1 of 3')
        pager.controls[3].on_click(None)
        self.assertEqual(pager.controls[2].content.value, 'Page 2 of 3')

    def test_provider_failures_keep_healthy_results_and_source_badges(self):
        self.core.get_recommended_plugins = lambda **kw: [dict(self.hit('same'), source=kw['source'])]
        self.search()
        for job in list(QueuedThread.jobs):
            job()
        QueuedThread.jobs.clear()
        self.assertEqual(len(self.results.controls), 2)
        self.assertIsNot(self.results.controls[0], self.results.controls[1])
        def catalogue(**kwargs):
            if kwargs['source'] == 'curseforge':
                raise OSError('provider offline')
            return [self.hit('healthy')]
        self.core.get_recommended_plugins = catalogue
        self.search(force=True)
        while QueuedThread.jobs:
            QueuedThread.jobs.pop()()
        self.assertEqual(len(self.results.controls), 1)
        self.assertFalse(self.results.controls[0].ignore_interactions)
        self.assertFalse(env(self.search)['retry'].disabled)
        self.assertIn('CurseForge unavailable', env(self.search)['plugin_search_status'].value)

    def test_provider_identity_separates_installed_badges(self):
        hit = self.hit('plugin-0')
        self.assertTrue(self.fns['project_installed'](hit))
        self.assertFalse(self.fns['project_installed'](dict(hit, source='curseforge')))


if __name__ == '__main__':
    unittest.main()
