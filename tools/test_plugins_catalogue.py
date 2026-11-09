"""Plugin cards retain geometry, cached status and instance ownership under races."""
import sys
import unittest
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
        self.core.get_recommended_plugins = lambda: calls.append('popular') or [self.hit('popular')]
        self.core.search_plugins = lambda query, **kw: calls.append(query) or [self.hit(query)]
        self.search(); self.search()
        self.assertEqual(len(QueuedThread.jobs), 1)
        popular = QueuedThread.jobs.pop()
        field = env(self.search)['plugin_search_field']
        field.value = 'new'; self.search()
        QueuedThread.jobs.pop()()
        rows = tuple(self.results.controls)
        popular()
        self.assertEqual(tuple(self.results.controls), rows)
        self.search()
        self.assertEqual(tuple(self.results.controls), rows)
        self.assertEqual(calls, ['new', 'popular'])

    def test_failed_refresh_keeps_cards_scrollable_and_retry_visible(self):
        self.core.get_recommended_plugins = lambda: [self.hit()]
        self.search(); QueuedThread.jobs.pop()()
        rows = tuple(self.results.controls)
        self.core.get_recommended_plugins = lambda: (_ for _ in ()).throw(OSError('offline'))
        self.search(force=True)
        self.assertTrue(rows[0].ignore_interactions)
        self.assertFalse(self.results.disabled)
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
        self.core.get_recommended_plugins = lambda: [self.hit('plugin-0')]
        self.search(); QueuedThread.jobs.pop()()
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


if __name__ == '__main__':
    unittest.main()
