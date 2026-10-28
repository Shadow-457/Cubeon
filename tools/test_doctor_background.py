#!/usr/bin/env python3
"""Background doctor runs without dialogs, batches clicks, and scopes repairs."""
import ast
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
        # Execute the actual tab closures with queued workers to reproduce a
        # double click while a scan has not completed. No page/dialog API is
        # provided: any popup would fail this test.
        source = (Path(__file__).resolve().parents[1] / 'ui/mods_tab.py').read_text()
        tree = ast.parse(source)
        wanted = {'_start_repair', 'run_mod_repair', 'auto_check'}
        functions = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name in wanted]
        jobs, calls, statuses = [], [], []
        class Worker:
            def __init__(self, target, **kw): self.target = target
            def start(self): jobs.append(self.target)
        state = {'selected_mc_version':'1.21.1', 'mod_loader':'fabric'}
        def doctor(*a, **kw):
            calls.append(kw)
            return {'fixed': [], 'unfixed': [{'detail':'Needs Fabric API'}]}
        scope = dict(state=state, version_dropdown=types.SimpleNamespace(value='instance'),
                     check_repair_btn=types.SimpleNamespace(disabled=False),
                     repair_lock=threading.Lock(), auto_check_state={'last':{}},
                     AUTO_CHECK_SECONDS=900, _ct=lambda:'mod', _is_mod=lambda:True,
                     _repair_sections=lambda:['mods'],
                     _set_repair_status=lambda *a:statuses.append(a),
                     core=types.SimpleNamespace(run_doctor=doctor),
                     refresh_mods_list=lambda:None, i18n=i18n,
                     thread_safe_ui=types.SimpleNamespace(TREE_LOCK=threading.RLock(), refresh=lambda c:None),
                     threading=types.SimpleNamespace(Thread=Worker),
                     time=__import__('time'), logging=__import__('logging'))
        exec(compile(ast.Module(body=functions, type_ignores=[]), '<doctor closures>', 'exec'), scope)
        scope['auto_check']()
        scope['auto_check']()
        self.assertEqual(len(jobs), 1)
        jobs.pop()()
        self.assertIsNone(calls[-1]['approve_cb'])
        self.assertFalse(calls[-1]['check_online'])
        self.assertIn('need attention', statuses[-1][0])
        scope['run_mod_repair']()
        scope['run_mod_repair']()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(state['fixing_mods'], 'instance')
        jobs.pop()()
        self.assertIsNone(state['fixing_mods'])
        self.assertTrue(calls[-1]['approve_cb']({'action':'disable'}))
        self.assertTrue(calls[-1]['check_online'])
        self.assertEqual(calls[-1]['include'], ['mods'])
        self.assertFalse(scope['check_repair_btn'].disabled)
        state['running_version'] = 'instance'
        scope['run_mod_repair']()
        self.assertFalse(jobs)

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
                      if isinstance(getattr(c, 'options', None), list)
                      and [getattr(o, 'key', None) for o in c.options[:4]] == ['ar','en','ru','es'])
        picker.value = 'es'
        picker.on_select(None)
        self.assertEqual(i18n.current(), 'ar', 'language changes after restart')
        self.assertFalse(driver.errors, driver.errors)
        self.assertFalse(any(getattr(c, 'data', None) == 'play-fix-crash'
                             for c in app_driver.every_control(driver.page)))
        i18n.set_language('en')

if __name__ == '__main__':
    unittest.main()
