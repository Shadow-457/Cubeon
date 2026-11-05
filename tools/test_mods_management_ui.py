"""Content UI actions stay scoped, responsive and retryable under races."""
import inspect
import base64
import io
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
        self.cfg = {}
        self.core.list_mods = lambda *a, **k: []
        self.core.list_content = lambda *a, **k: [dict(m) for m in self.items]
        self.patches = [patch('threading.Thread', QueuedThread), patch('cubeon.theme._toggle_pop'), patch.object(icons, 'prefetch'),
                        patch.object(thread_safe_ui, 'refresh')]
        for p in self.patches: p.start(); self.addCleanup(p.stop)
        QueuedThread.jobs.clear()
        root, self.refresh, load, browse = build_mods_tab(
            self.page, self.cfg, self.state, self.dropdown, section_label=section_label, **THEME)
        self.root = root
        self.fns = functions(self.refresh, load, browse, *[getattr(c, 'on_click', None) for c in fz.walk(root)])
        self.active = env(self.fns['_ct'])['active_content']
        self.scope = env(self.fns['_render_installed_snapshot'])

    def row(self, kind='resourcepack'):
        self.active['type'] = kind
        self.items[:] = [{'filename': 'test.zip', 'display_name': 'Test', 'size_kb': 1, 'enabled': True}]
        self.refresh()
        return self.scope['mods_list_view'].controls[0]

    def client_row(self, name='cubeon-client-1.jar'):
        self.active['type'] = 'mod'
        self.core.list_mods = lambda *a, **k: [{'filename': name, 'display_name': 'Cubeon Client',
                                             'size_kb': 10, 'enabled': True, 'protected': True}]
        self.refresh()
        return self.scope['mods_list_view'].controls[0]

    def test_client_current_and_legacy_rows_save_preference_without_toggling_jar(self):
        for name in ('cubeon-client-1.jar', 'cubeon-friends-1.jar'):
            with self.subTest(name=name):
                self.cfg.clear()
                row = self.client_row(name)
                switch = row.content.controls[2]
                self.assertIsInstance(switch, ft.Switch)
                self.assertEqual(len(row.content.controls), 3)  # no delete action
                with patch.object(self.core, 'save_config') as save, patch.object(self.core, 'toggle_mod') as toggle:
                    switch.value = False
                    switch.on_change(None)
                    save.assert_called_once_with(self.cfg)
                    toggle.assert_not_called()
                self.assertFalse(self.cfg['client_mod_enabled'])
                self.assertFalse(switch.value)
                self.assertIn('Next launch', row.content.controls[1].controls[1].value)
                self.assertTrue(self.fns['_cached_installed']()[0]['enabled'])
                self.refresh()
                self.assertIs(self.scope['mods_list_view'].controls[0], row)
                self.assertFalse(switch.value)
                with patch.object(self.core, 'save_config'):
                    switch.value = True
                    switch.on_change(None)
                self.assertTrue(self.cfg['client_mod_enabled'])

    def test_client_failed_save_rolls_back_switch_and_remains_retryable(self):
        row = self.client_row()
        switch = row.content.controls[2]
        with patch.object(self.core, 'save_config', side_effect=OSError('disk full')):
            switch.value = False
            switch.on_change(None)
        self.assertNotIn('client_mod_enabled', self.cfg)
        self.assertTrue(switch.value)
        self.assertIn('disk full', env(self.fns['_set_installed_status'])['installed_status'].value)
        with patch.object(self.core, 'save_config'):
            switch.value = False
            switch.on_change(None)
        self.assertFalse(switch.value)

    def test_client_active_disabled_and_legacy_copies_show_one_switch(self):
        self.core.list_mods = lambda *a, **k: [
            {'filename': name, 'display_name': name.removesuffix('.disabled').removesuffix('.jar'),
             'size_kb': 10, 'enabled': not name.endswith('.disabled'), 'protected': True}
            for name in ('cubeon-friends-old.jar.disabled', 'cubeon-client-1.jar.disabled', 'cubeon-client-1.jar')]
        self.refresh()
        rows = self.scope['mods_list_view'].controls
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].content.controls[1].controls[0].value, 'Cubeon Client')
        self.assertEqual(len(self.fns['_cached_installed']()), 3)
        self.assertFalse(self.scope['client_preference_row'].visible)
        switch = rows[0].content.controls[2]
        with patch.object(self.core, 'save_config'):
            switch.value = False
            switch.on_change(None)
        self.assertFalse(switch.value)
        self.assertIs(self.scope['mods_list_view'].controls[0], rows[0])
        self.assertEqual(len(self.fns['_cached_installed']()), 3)

    def test_client_opt_in_stays_available_after_jar_is_removed_and_across_views(self):
        self.cfg['client_mod_enabled'] = False
        self.refresh()
        fallback = self.scope['client_preference_row']
        switch = self.scope['client_preference_switch']
        self.assertTrue(fallback.visible)
        self.assertFalse(switch.value)
        self.root.select_content_type('resourcepack')
        self.assertFalse(fallback.visible)
        self.root.select_content_type('mod')
        self.assertTrue(fallback.visible)
        with patch.object(self.core, 'save_config'):
            switch.value = True
            switch.on_change(None)
        self.assertTrue(self.cfg['client_mod_enabled'])
        self.assertTrue(fallback.visible)
        self.assertTrue(switch.value)

    def test_client_switch_uses_shared_settings_callback_and_ignores_stale_instance_row(self):
        settings = ft.Switch(value=True)
        calls = []
        def changed(enabled):
            calls.append(enabled)
            self.cfg['client_mod_enabled'] = enabled
            settings.value = enabled
            return True
        root, refresh, *_ = build_mods_tab(self.page, self.cfg, self.state, self.dropdown,
                                         section_label=section_label, on_client_mod_change=changed, **THEME)
        self.core.list_mods = lambda *a, **k: [{'filename': 'cubeon-client-1.jar', 'display_name': 'Client',
                                             'size_kb': 10, 'enabled': True, 'protected': True}]
        refresh()
        scope = env(functions(refresh)['_render_installed_snapshot'])
        switch = scope['mods_list_view'].controls[0].content.controls[2]
        with patch.object(self.core, 'save_config') as save:
            switch.value = False
            switch.on_change(None)
            save.assert_not_called()  # main owns persistence when wired
        self.assertFalse(settings.value)
        self.assertEqual(calls, [False])
        self.cfg['client_mod_enabled'] = True
        root.refresh_client_preference()
        self.assertTrue(switch.value)
        self.dropdown.value = 'instance-B'
        switch.on_change(None)
        self.assertEqual(calls, [False])

    def test_other_managed_mods_keep_lock_and_regular_mods_keep_disk_switch(self):
        self.core.list_mods = lambda *a, **k: [
            {'filename': 'CustomSkinLoader.jar', 'display_name': 'CSL', 'size_kb': 10,
             'enabled': True, 'protected': True},
            {'filename': 'other.jar', 'display_name': 'Other', 'size_kb': 10, 'enabled': True}]
        self.refresh()
        rows = self.scope['mods_list_view'].controls
        self.assertFalse(any(isinstance(c, ft.Switch) for c in fz.walk(rows[0])))
        switch = rows[1].content.controls[2]
        with patch.object(self.core, 'toggle_mod') as toggle, patch.object(self.core, 'save_config') as save:
            switch.on_change(None)
            QueuedThread.jobs.pop()()
            toggle.assert_called_once_with('1.21.11', 'fabric', 'other.jar', version_id='instance-A')
            save.assert_not_called()

    def test_content_selectors_keep_instance_and_update_import_and_search_labels(self):
        selector = next(c for c in fz.walk(self.root) if getattr(c, 'data', None) == 'content-resourcepack')
        header = env(self.fns['_apply_type_labels'])
        selector.on_click(None)
        self.assertEqual(self.dropdown.value, 'instance-A')
        self.assertEqual(header['header_title'].value, 'Resource Packs')
        self.assertEqual(header['local_install_label'].value, 'Import packs')
        self.assertFalse(any(isinstance(c, ft.PopupMenuButton) for c in fz.walk(self.root)))
        self.assertIn('resource packs', header['mod_search_field'].hint_text)

    def test_filters_are_closed_by_default_and_installed_is_one_action(self):
        filters = env(self.fns['on_filters_toggle'])
        self.assertFalse(filters['category_chips_container'].visible)
        self.fns['on_filters_toggle']()
        self.assertTrue(filters['category_chips_container'].visible)
        toggle = next(c for c in fz.walk(self.root) if getattr(c, 'data', None) == 'mods-installed-toggle')
        toggle.on_click(None)
        view = env(self.fns['on_view_change'])
        self.assertFalse(view['browse_pane'].visible)
        self.assertTrue(view['installed_pane'].visible)
        toggle = next(c for c in fz.walk(self.root) if getattr(c, 'data', None) == 'mods-installed-toggle')
        toggle.on_click(None)
        self.assertTrue(view['browse_pane'].visible)
        self.assertFalse(view['installed_pane'].visible)

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

    def test_installed_pack_and_shader_art_have_cubeon_fallback(self):
        from PIL import Image
        stream = io.BytesIO()
        Image.new('RGB', (16, 16), 'green').save(stream, 'PNG')
        source = base64.b64encode(stream.getvalue()).decode('ascii')
        for kind in ('resourcepack', 'shader'):
            row = self.row(kind)
            self.assertEqual(row.content.controls[0].content.src, 'icon_64.png')
            self.items[0]['icon_source'] = source
            self.refresh()
            image = self.scope['mods_list_view'].controls[0].content.controls[0].content
            self.assertEqual(image.src, source)
            self.assertIsInstance(image.error_content, ft.Image)
            self.assertEqual(image.error_content.src, 'icon_64.png')
            self.items[0]['icon_source'] = 'aW52YWxpZA=='
            self.refresh()
            image = self.scope['mods_list_view'].controls[0].content.controls[0].content
            self.assertEqual(image.src, 'icon_64.png')

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

    def test_popular_mods_load_one_page_at_a_time_and_reuse_rows_on_switch(self):
        calls = []
        def popular(**kw):
            calls.append(kw)
            return [{'project_id': f"mod-{kw['offset'] + i}",
                     'title': f"Mod {kw['offset'] + i}", 'downloads': 1}
                    for i in range(kw['limit'])]
        self.core.get_recommended_mods = popular
        self.fns['load_recommended_mods']()
        self.assertEqual(calls, [])
        self.assertEqual(len(QueuedThread.jobs), 1)
        QueuedThread.jobs.pop(0)()
        view = env(self.fns['_render_browse_page'])['browse_results_view']
        self.assertEqual(len(view.controls), 24)
        first_rows = tuple(view.controls)
        self.assertTrue(view.build_controls_on_demand)
        self.assertEqual([(c['limit'], c['offset']) for c in calls], [(24, 0)])
        self.assertEqual(QueuedThread.jobs, [])

        with patch.object(ft.context, 'disable_auto_update') as disable_auto_update:
            self.fns['_browse_page_next']()
            disable_auto_update.assert_called_once()
        self.assertEqual(tuple(view.controls), first_rows)
        self.assertEqual(len(QueuedThread.jobs), 1)
        QueuedThread.jobs.pop(0)()
        second_rows = tuple(view.controls)
        self.assertEqual([(c['limit'], c['offset']) for c in calls], [(24, 0), (24, 24)])
        self.assertEqual(QueuedThread.jobs, [])
        with patch.object(ft.context, 'disable_auto_update') as disable_auto_update:
            self.root.select_content_type('resourcepack')
            self.root.select_content_type('mod')
            self.assertEqual(tuple(view.controls), second_rows)
            self.fns['_browse_page_prev']()
            self.assertEqual(disable_auto_update.call_count, 3)
        self.assertEqual(tuple(view.controls), first_rows)
        self.assertEqual(len(calls), 2)
        self.assertEqual(self.page.update_calls, 0)

    def test_titles_appear_before_installed_file_scan_and_survive_scan_failure(self):
        project = {'project_id': 'immediate', 'title': 'Immediate title'}
        self.core.get_recommended_mods = lambda **kw: [project]
        def slow_scan(*a, **kw):
            visible = [c.value for c in fz.walk(self.root) if isinstance(c, ft.Text)]
            self.assertIn('Immediate title', visible)
            raise OSError('fixture scan unavailable')
        self.core.list_mods = slow_scan
        self.fns['load_recommended_mods']()
        QueuedThread.jobs.pop(0)()
        visible = [c.value for c in fz.walk(self.root) if isinstance(c, ft.Text)]
        self.assertIn('Immediate title', visible)
        self.assertNotIn('Search unavailable', visible)

    def test_initial_skeleton_is_enabled_and_lists_are_lazy(self):
        self.fns['_show_browse_loading']()
        browse = env(self.fns['_show_browse_loading'])['browse_results_view']
        self.assertFalse(browse.disabled)
        self.assertEqual(browse.controls[0].data, 'content-loading')
        for control in (browse, self.scope['mods_list_view']):
            self.assertIsInstance(control, ft.GridView)
            self.assertTrue(control.build_controls_on_demand)

    def test_modpacks_selector_keeps_both_engines_mounted_and_instance_unchanged(self):
        pack_host = ft.Container(expand=True)
        opened = []
        root, *_ = build_mods_tab(self.page, {}, self.state, self.dropdown,
                                section_label=section_label, modpacks_content=pack_host,
                                on_modpacks_open=lambda: opened.append(True), **THEME)
        before = tuple(root.controls)
        root.select_content_type('modpack')
        self.assertTrue(pack_host.visible)
        self.assertEqual(opened, [True])
        self.assertEqual(self.dropdown.value, 'instance-A')
        root.select_content_type('resourcepack')
        self.assertFalse(pack_host.visible)
        self.assertEqual(tuple(root.controls), before)

    def test_large_installed_list_expands_in_batches(self):
        self.active['type'] = 'resourcepack'
        self.items[:] = [{'filename': f'{i}.zip', 'display_name': str(i), 'size_kb': 1, 'enabled': True} for i in range(300)]
        self.refresh()
        view = self.scope['mods_list_view']
        self.assertEqual(len(view.controls), 13)
        view.controls[-1].on_click(None)
        self.assertEqual(len(view.controls), 39)
        view.controls[-2].on_click(None)
        self.assertEqual(len(view.controls), 64)

    def test_resizing_only_changes_layout_and_preserves_request_offsets(self):
        scope = env(self.fns['_render_browse_page'])
        grid = scope['browse_results_view']
        field = env(self.fns['_browse_key'])['mod_search_field']
        field.value = 'animation'
        old_token = self.fns['_begin_browse']()
        old_key = old_token[1]
        grid.on_size_change(SimpleNamespace(width=1500, height=900))
        new_key = self.fns['_browse_key']()
        self.assertEqual(new_key, old_key)
        self.assertEqual(grid.runs_count, 4)
        calls = []
        self.core.search_mods = lambda *a, **kw: calls.append(kw) or []
        self.fns['_browse_fetch'](1, old_key)
        self.fns['_browse_fetch'](1, new_key)
        self.assertEqual([(kw['limit'], kw['offset']) for kw in calls], [(24, 24), (24, 24)])

    def test_type_switch_restores_query_rows_and_does_not_refetch(self):
        field = env(self.fns['_browse_key'])['mod_search_field']
        calls = []
        self.core.search_mods = lambda query, **kw: calls.append(query) or [
            {'project_id': 'saved', 'slug': 'saved', 'title': 'Saved search', 'downloads': 1}]
        field.value = 'saved query'
        self.fns['run_mod_search']()
        QueuedThread.jobs.pop(0)()
        scope = env(self.fns['_render_browse_page'])
        saved_rows = tuple(scope['browse_results_view'].controls)
        saved_token = scope['browse_state']['token']
        self.root.select_content_type('resourcepack')
        self.root.select_content_type('mod')
        current = env(self.fns['_render_browse_page'])
        self.assertEqual(field.value, 'saved query')
        self.assertEqual(current['browse_state']['token'], saved_token)
        self.assertEqual(tuple(current['browse_results_view'].controls), saved_rows)
        self.assertEqual(calls, ['saved query'])
        self.fns['run_mod_search']()
        self.assertEqual(calls, ['saved query'])

    def test_hidden_search_completion_is_cached_without_painting_wrong_type(self):
        field = env(self.fns['_browse_key'])['mod_search_field']
        self.core.search_mods = lambda *a, **kw: [
            {'project_id': 'late', 'title': 'Late mod', 'downloads': 1}]
        field.value = 'late query'
        self.fns['run_mod_search']()
        late = QueuedThread.jobs.pop(0)
        self.root.select_content_type('resourcepack')
        grid = env(self.fns['_render_browse_page'])['browse_results_view']
        before = tuple(grid.controls)
        late()
        self.assertEqual(tuple(grid.controls), before)
        self.root.select_content_type('mod')
        self.assertEqual(field.value, 'late query')
        self.assertEqual(env(self.fns['_render_browse_page'])['browse_state']['results'][0]['title'], 'Late mod')

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
