"""Content UI actions stay scoped, responsive and retryable under races."""
import inspect
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common as fz
import flet as ft
from app_driver import DriverPage
from cubeon import icons, thread_safe_ui
from cubeon.theme import THEME, section_label
from ui.mods_tab import build_mods_tab
from test_content_install_feedback import QueuedThread, functions, env


class ManagementUI(unittest.TestCase):
    def setUp(self):
        self.stubs = fz.install_safe_stubs()
        self.core = self.stubs.core
        self.page = DriverPage()
        self.state = {'selected_mc_version': '1.21.11', 'mod_loader': 'fabric'}
        self.dropdown = ft.Dropdown(value='instance-A')
        self.items = []
        self.core.list_mods = lambda *a, **k: []
        self.core.list_content = lambda *a, **k: [dict(m) for m in self.items]
        self.patches = [patch('threading.Thread', QueuedThread), patch('cubeon.theme._toggle_pop'), patch.object(icons, 'prefetch'),
                        patch.object(thread_safe_ui, 'refresh')]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        QueuedThread.jobs.clear()
        root, self.refresh, load, browse = build_mods_tab(
            self.page, {}, self.state, self.dropdown, section_label=section_label, **THEME)
        self.root = root
        self.fns = functions(self.refresh, load, browse, *[getattr(c, 'on_click', None) for c in fz.walk(root)])
        self.active = env(self.fns['_ct'])['active_content']
        self.scope = env(self.fns['_render_installed_snapshot'])

    def row(self, kind='resourcepack'):
        self.active['type'] = kind
        self.items[:] = [{'filename': 'test.zip', 'display_name': 'Test', 'size_kb': 1, 'enabled': True}]
        self.refresh()
        return self.scope['mods_list_view'].controls[0]

    def test_resource_and_shader_switches_capture_instance_and_guard_stale_rows(self):
        for kind in ('resourcepack', 'shader'):
            row = self.row(kind)
            switch = row.content.controls[2]
            self.assertTrue(switch.value)
            calls = []
            self.core.toggle_content = lambda *a, **kw: calls.append((a, kw))
            switch.on_change(None)
            self.assertTrue(row.disabled)
            self.assertEqual(calls, [])
            self.dropdown.value = 'instance-B'
            QueuedThread.jobs.pop()()
            self.assertEqual(calls[0][0], (kind, 'test.zip', '1.21.11', 'fabric'))
            self.assertEqual(calls[0][1]['version_id'], 'instance-A')
            switch.on_change(None)
            self.assertEqual(len(calls), 1)
            self.assertEqual(QueuedThread.jobs, [])
            self.dropdown.value = 'instance-A'

    def test_delete_runs_off_the_handler_and_deduplicates(self):
        row = self.row()
        calls = []
        self.core.delete_content = lambda *a, **k: calls.append((a, k))
        button = row.content.controls[-1]
        button.on_click(None); button.on_click(None)
        self.assertEqual(calls, [])
        self.assertEqual(len(QueuedThread.jobs), 1)
        QueuedThread.jobs.pop()()
        self.assertEqual(len(calls), 1)
        self.assertFalse(row.disabled)

    def test_content_toggle_refresh_preserves_row_and_art(self):
        row = self.row()
        icon = row.content.controls[0]
        self.items[0].update(filename='test.zip.disabled', enabled=False)
        self.refresh()
        self.assertIs(self.scope['mods_list_view'].controls[0], row)
        self.assertIs(row.content.controls[0], icon)
        self.assertFalse(row.content.controls[2].value)

    def test_enabled_disabled_collision_has_two_distinct_rows(self):
        self.row()
        self.items.append(dict(self.items[0], filename='test.zip.disabled', enabled=False))
        self.refresh()
        rows = self.scope['mods_list_view'].controls
        self.assertEqual(len(rows), 2)
        self.assertIsNot(rows[0], rows[1])
        self.assertTrue(rows[0].content.controls[2].value)
        self.assertFalse(rows[1].content.controls[2].value)

    def test_row_thread_start_failure_releases_busy_state(self):
        row = self.row()
        self.core.toggle_content = lambda *a, **k: None
        with patch.object(QueuedThread, 'start', side_effect=RuntimeError('no thread')):
            row.content.controls[2].on_change(None)
        self.assertFalse(row.disabled)
        self.assertIn("Couldn't start", env(self.fns['_set_installed_status'])['installed_status'].value)
        row.content.controls[2].on_change(None)
        self.assertEqual(len(QueuedThread.jobs), 1)

    def test_background_refresh_never_scans_under_tree_lock(self):
        calls = []
        def list_mods(*a, **k):
            self.assertFalse(thread_safe_ui.TREE_LOCK._is_owned())
            calls.append(k['version_id']); return []
        self.core.list_mods = list_mods
        with thread_safe_ui.TREE_LOCK:
            self.refresh(background=True)
        self.assertFalse(calls)
        self.dropdown.value = 'instance-B'
        self.refresh(background=True)
        QueuedThread.jobs.pop()()
        self.assertEqual(calls, ['instance-B'])

    def test_cached_filter_and_badges_do_not_read_disk(self):
        self.row()
        self.core.list_content = lambda *a, **k: self.fail('filter read disk')
        self.scope['installed_filter_field'].value = 'test'
        self.fns['_render_installed_snapshot'](self.fns['_cached_installed']())
        self.assertEqual(self.fns['content_installed_tokens'](), {'test'})

    def test_local_install_keeps_original_target_and_does_not_paint_another_type(self):
        self.active['type'] = 'resourcepack'
        installed = []
        self.core.install_local_content = lambda *a, **k: installed.append((a, k))
        self.fns['handle_local_mod_files']([SimpleNamespace(path='test.zip', name='Test')])
        self.active['type'] = 'shader'; self.dropdown.value = 'instance-B'
        status = env(self.fns['handle_local_mod_files'])['local_install_status']
        status.value = 'current surface'
        QueuedThread.jobs.pop()()
        self.assertEqual(installed[0][0], ('resourcepack', 'test.zip', '1.21.11', 'instance-A', 'fabric'))
        self.assertEqual(status.value, 'current surface')
        self.assertFalse(env(self.fns['handle_local_mod_files'])['local_install_busy']['value'])

    def test_browse_completion_does_not_start_duplicate_fetch(self):
        calls = []
        self.core.get_recommended_mods = lambda **kw: calls.append(kw) or []
        self.fns['load_recommended_mods']()
        self.assertEqual(len(QueuedThread.jobs), 1)
        QueuedThread.jobs.pop()()
        self.assertEqual(len(calls), 1)
        self.assertEqual(QueuedThread.jobs, [])

    def test_initial_skeleton_is_enabled_and_lists_are_lazy(self):
        self.fns['_show_browse_loading']()
        browse = env(self.fns['_show_browse_loading'])['browse_results_view']
        self.assertFalse(browse.disabled)
        self.assertEqual(browse.controls[0].data, 'content-loading')
        for control in (browse, self.scope['mods_list_view']):
            self.assertIsInstance(control, ft.ListView)
            self.assertTrue(control.build_controls_on_demand)

    def test_large_installed_list_expands_in_batches(self):
        self.active['type'] = 'resourcepack'
        self.items[:] = [{'filename': f'{i}.zip', 'display_name': str(i), 'size_kb': 1, 'enabled': True} for i in range(300)]
        self.refresh()
        view = self.scope['mods_list_view']
        self.assertEqual(len(view.controls), 6)
        view.controls[-1].on_click(None)
        self.assertLessEqual(len(view.controls), 27)
        view.controls[-2].on_click(None)
        self.assertLessEqual(len(view.controls), 52)

    def test_download_start_failure_is_retryable(self):
        row = self.fns['build_browse_row']({'project_id': 'demo', 'title': 'Demo'})
        button = row.content.controls[-1]
        with patch.object(QueuedThread, 'start', side_effect=RuntimeError('no thread')):
            button.on_click(None)
        self.assertFalse(button.disabled)
        self.assertIn("Couldn't start", button.tooltip)
        button.on_click(None)
        self.assertEqual(len(QueuedThread.jobs), 1)

    def test_detail_versions_build_in_bounded_batches(self):
        self.core.get_mod_details = lambda *a: {'title': 'Many versions', 'project_id': 'many'}
        self.core.get_mod_versions = lambda *a, **k: [
            {'filename': f'{i}.jar', 'url': 'offline', 'version_number': str(i), 'compatible': True}
            for i in range(1000)]
        self.fns['open_mod_detail']({'project_id': 'many'})
        QueuedThread.jobs.pop()()
        dialog = self.page._dialogs.controls[-1]
        def buttons(): return [c for c in fz.walk(dialog) if hasattr(c, '_cubeon_install_paint')]
        self.assertEqual(len(buttons()), 9)
        more = next(c for c in fz.walk(dialog) if callable(getattr(c, 'on_click', None))
                    and isinstance(getattr(c, 'content', None), ft.Text)
                    and c.content.value.startswith('Show more versions'))
        more.on_click(None)
        self.assertEqual(len(buttons()), 34)

    def test_shader_setup_keeps_loader_and_uses_matching_project(self):
        self.active['type'] = 'shader'; self.state['mod_loader'] = 'forge'
        calls = []
        self.core.get_mod_download = lambda *a, **k: calls.append((a, k)) or None
        self.fns['_setup_shaders']()
        QueuedThread.jobs.pop()()
        self.assertEqual(calls[0][0], ('oculus',))
        self.assertEqual(calls[0][1]['loader'], 'forge')
        self.assertEqual(self.state['mod_loader'], 'forge')


if __name__ == '__main__': unittest.main()
