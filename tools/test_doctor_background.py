#!/usr/bin/env python3
"""Background doctor runs without dialogs, batches clicks, and scopes repairs."""
from pathlib import Path
import sys
import threading
import types
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import i18n, thread_safe_ui
import app_driver

class BackgroundDoctorTests(unittest.TestCase):
    def test_background_and_explicit_policy(self):
        # Execute the actual tab methods with queued workers to reproduce a
        # double click while a scan has not completed. No page/dialog API is
        # provided: any popup would fail this test.
        from unittest.mock import patch
        from ui import mods_tab
        from ui.mods_tab import ModsView
        self.addCleanup(patch.stopall)
        jobs, calls, statuses, popups = [], [], [], []
        class Worker:
            def __init__(self, target, **kw): self.target = target
            def start(self): jobs.append(self.target)
        state = {'selected_mc_version':'1.21.1', 'mod_loader':'fabric'}
        def check(target, **kw):
            calls.append((target, kw))
            return {'fixed': [], 'unfixed': [{'mod':'Example Mod', 'detail':'Example Mod: Needs Fabric API'}]}
        view = ModsView.__new__(ModsView)
        view.state = state
        view.version_dropdown = types.SimpleNamespace(value='instance')
        view.check_repair_btn = types.SimpleNamespace(disabled=False)
        view.repair_lock = threading.Lock()
        view.auto_check_state = {'last': {}}
        view.AUTO_CHECK_SECONDS = 900
        view._ct = lambda: 'mod'
        view._is_mod = lambda: True
        view._repair_sections = lambda: ['mods']
        view._set_repair_status = lambda *a: statuses.append(a)
        view.page = object()
        view.refresh_mods_list = lambda **kw: None
        patch.object(mods_tab, 'check_content', side_effect=check).start()
        patch.object(mods_tab, 'show_content_issues', side_effect=lambda *a, **kw: popups.append((a, kw))).start()
        patch.object(mods_tab.threading, 'Thread', Worker).start()
        patch.object(thread_safe_ui, 'refresh', lambda c: None).start()
        view.auto_check()
        view.auto_check()
        self.assertEqual(len(jobs), 1)
        jobs.pop()()
        self.assertEqual(calls[-1], (('mod', '1.21.1', 'fabric', 'instance'), {}))
        self.assertEqual(len(popups), 1)
        self.assertIn('need attention', statuses[-1][0])
        self.assertIn('Example Mod: Needs Fabric API', statuses[-1][1])
        view.run_mod_repair()
        view.run_mod_repair()
        self.assertEqual(len(jobs), 1)
        self.assertIsNone(state.get('fixing_mods'))
        jobs.pop()()
        self.assertIsNone(state.get('fixing_mods'))
        self.assertEqual(calls[-1][1], {})
        self.assertEqual(len(popups), 2)
        self.assertFalse(view.check_repair_btn.disabled)
        mods_tab.check_content.side_effect = lambda *a, **kw: {'fixed':[], 'unfixed':[], 'elapsed':.005}
        view.run_mod_repair()
        jobs.pop()()
        self.assertEqual(statuses[-1], ('Compatible · 5 ms',))
        state['running_version'] = 'instance'
        view.run_mod_repair()
        self.assertFalse(jobs)

    def test_named_results_are_visible_inline(self):
        # Run the actual UI mutation method, rather than just checking tooltip
        # strings, and verify both regions repaint without opening a dialog.
        from unittest.mock import patch
        from ui.mods_tab import ModsView
        status = types.SimpleNamespace(value='', visible=False, tooltip=None)
        details = types.SimpleNamespace(value='', visible=False)
        view = ModsView.__new__(ModsView)
        view.repair_status, view.repair_details = status, details
        refreshed = []
        with patch.object(thread_safe_ui, 'refresh', refreshed.append):
            view._set_repair_status('Fixed 1; 1 need attention', 'Sodium: needs Fabric API')
        self.assertTrue(details.visible)
        self.assertEqual(details.value, 'Sodium: needs Fabric API')
        self.assertEqual(refreshed, [status, details])
        with patch.object(thread_safe_ui, 'refresh', refreshed.append):
            view._set_repair_status('Checking…')
        self.assertFalse(details.visible)
        self.assertEqual(details.value, '')

    def test_settings_does_not_expose_the_removed_doctor(self):
        # Settings removal must leave the automatic and crash-report doctors
        # independent of the Settings control tree.
        driver = app_driver.build_headless()
        driver.open_tab('settings')
        self.assertFalse(driver.errors, driver.errors)
        controls = list(app_driver.every_control(driver.page))
        self.assertFalse(any(getattr(c, 'data', None) == 'settings-doctor-summary'
                             for c in controls))
        self.assertFalse(any('Run full check' in str(getattr(c, 'value', ''))
                             or 'Fix problems' in str(getattr(c, 'value', '')) for c in controls))

    def test_arabic_launcher_build_and_picker_save(self):
        import os
        from unittest.mock import patch
        with patch.dict(os.environ, {'CUBEON_LANG':'ar'}):
            driver = app_driver.build_headless()
        self.assertTrue(driver.page.rtl)
        self.assertIn(i18n.t('PLAY'), driver.visible_text())
        driver.open_tab('mods')
        self.assertFalse(driver.errors, driver.errors)
        driver.open_tab('settings')
        picker = next(c for c in app_driver.every_control(driver.page)
                      if getattr(c, 'data', None) == 'language-picker-toggle')
        picker.on_click(None)
        spanish = next(c for c in app_driver.every_control(driver.page)
                       if getattr(c, 'data', None) == 'language-option-es')
        spanish.on_click(None)
        self.assertEqual(i18n.current(), 'ar', 'language changes after restart')
        notice = next(c for c in app_driver.every_control(driver.page)
                      if getattr(c, 'data', None) == 'language-restart-notice')
        self.assertTrue(notice.visible)
        restart = next(c for c in app_driver.every_control(driver.page)
                       if getattr(c, 'data', None) == 'language-restart')
        previous_request = driver.app._relaunch['request']
        request = threading.Event()
        driver.app._relaunch['request'] = request
        try:
            restart.on_click(None)
            self.assertTrue(request.is_set(), 'The language button must arm the real launcher restart')
        finally:
            driver.app._relaunch['request'] = previous_request
        self.assertFalse(driver.errors, driver.errors)
        self.assertFalse(any(getattr(c, 'data', None) == 'play-fix-crash'
                             for c in app_driver.every_control(driver.page)))
        i18n.set_language('en')

if __name__ == '__main__':
    unittest.main()
