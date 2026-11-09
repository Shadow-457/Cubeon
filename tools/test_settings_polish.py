"""Settings resize retention, failed saves and background backup recovery."""
import inspect
import json
from pathlib import Path
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT/'tools'),str(ROOT)]
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
import app_driver
from _fuzz_common import walk
from cubeon import atomicio, backup, thread_safe_ui
from test_content_install_feedback import QueuedThread


def scope(function):
    return inspect.getclosurevars(function).nonlocals


class SettingsPolish(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with patch.object(threading.Thread, 'start'):
            cls.driver=app_driver.build_headless()
            cls.driver.open_tab('settings')
        switch=scope(cls.driver.tabs()['settings'].on_click)['switch_tab']
        cls.root=scope(switch)['tabs']['settings']
        cls.controls=list(walk(cls.root))
        cls.core=cls.driver.core

    def setUp(self):
        QueuedThread.jobs.clear()
        p=patch.object(thread_safe_ui,'refresh')
        self.repaint=p.start();self.addCleanup(p.stop)

    def control(self,handler=None,data=None):
        return next(c for c in self.controls if (data and c.data==data) or (
            handler and any(getattr(getattr(c,name,None),'__name__',None)==handler
                            for name in ('on_change','on_select','on_blur','on_click'))))

    def test_navigation_reflows_without_rebuilding_or_duplicate_controls(self):
        layout=scope(self.root.on_size_change)
        targets=tuple(layout['rail'].controls)
        panes=scope(scope(self.root.select_section)['_rebuild_rail'])['rail_items']
        for width, compact in ((440,True),(690,True),(1100,False),(500,True),(1200,False)):
            self.root.on_size_change(SimpleNamespace(width=width,height=600))
            self.assertEqual(layout['compact_host'].visible,compact)
            self.assertEqual(tuple(layout['compact_rail'].controls if compact else layout['rail'].controls),targets)
            self.assertEqual(sum(len(c.controls) for c in (layout['compact_rail'],layout['rail'])),len(targets))
            self.assertTrue(all(item.width==(144 if compact else None) for item in panes.values()))
            self.root.select_section('game')
            self.repaint.reset_mock()
            self.root.select_section('theme')
            active=scope(self.root.select_section)['panes']
            self.assertEqual([key for key,pane in active.items() if pane.visible],['seasonal'])
            self.assertEqual([id(c) for c in walk(self.root) if isinstance(c,ft.TextField)],
                             [id(c) for c in self.controls if isinstance(c,ft.TextField)])
            navigation=layout['compact_rail'] if compact else layout['rail']
            self.assertTrue(any(call.args[0] is navigation for call in self.repaint.call_args_list))

    def test_account_username_error_is_visible_and_failed_publish_can_retry(self):
        field=next(c for c in self.controls if isinstance(c,ft.TextField) and c.label=='Username')
        keystroke=scope(field.on_change)['on_name_keystroke']
        values=scope(keystroke)
        publish=values['_publish_username'];cfg=scope(publish)['cfg'];old=dict(cfg)
        original=field.value
        with patch.object(threading.Timer,'start'):
            field.value='invalid name'
            field.on_change(None)
            self.assertTrue(field.error)
            field.on_submit(None)
            self.assertEqual(cfg,old)
            field.value='SettingsTester'
            field.on_change(None)
        with patch.object(self.core,'save_config',side_effect=OSError('fixture')):
            field.on_submit(None)
        self.assertEqual(cfg,old)
        self.assertEqual(field.value,'SettingsTester')
        self.assertIn("Couldn't save",field.error)
        self.assertIsNotNone(values['_name_state']['pending'])
        with patch.object(self.core,'save_config') as save, \
             patch.object(threading.Thread,'start'), \
             patch.object(self.core,'sync_local_skin_to_csl'), \
             patch.object(self.core,'sync_local_cape_to_csl'):
            field.on_submit(None)
            calls=save.call_count
            field.on_blur(None)
            self.assertEqual(save.call_count,calls)
            self.assertEqual(cfg['username'],'SettingsTester')
            self.assertIsNone(field.error)
            field.value=original
            with patch.object(threading.Timer,'start'):
                field.on_change(None)
            field.on_submit(None)

    def test_picture_upload_failure_releases_buttons_and_repaints_account(self):
        upload=self.control(handler='open_pfp_picker')
        handle=scope(upload.on_click)['handle_pfp_files']
        values=scope(handle);cfg=scope(values['refresh_avatars'])['cfg'];old=dict(cfg)
        account=scope(values['_refresh_account_picture'])['account_pane']
        remove=values['profile_pfp_remove_btn']
        update_count=self.driver.page.update_calls
        with patch('threading.Thread',QueuedThread):
            handle([SimpleNamespace(path='/tmp/fixture.png')])
            handle([SimpleNamespace(path='/tmp/fixture.png')])
        self.assertEqual(len(QueuedThread.jobs),1)
        self.assertTrue(upload.disabled and remove.disabled)
        self.assertTrue(upload.cubeon_keyboard_button.disabled)
        with patch.object(self.core,'set_profile_picture'), \
             patch.object(self.core,'save_config',side_effect=OSError('fixture')):
            QueuedThread.jobs.pop()()
        self.assertEqual(cfg,old)
        self.assertFalse(upload.disabled or remove.disabled)
        self.assertFalse(upload.cubeon_keyboard_button.disabled)
        self.assertIn('Upload failed',values['profile_pfp_status'].value)
        self.assertIn(account,[call.args[0] for call in self.repaint.call_args_list])
        self.assertEqual(self.driver.page.update_calls,update_count)
        with patch.object(threading.Thread,'start',side_effect=RuntimeError('fixture')):
            handle([SimpleNamespace(path='/tmp/fixture.png')])
        self.assertFalse(upload.disabled or values['_pfp_busy']['value'])

    def test_appearance_saves_restore_value_and_key_presence(self):
        for handler in ('on_glass_change','on_custom_chrome_change'):
            control=self.control(handler=handler)
            helper=scope(control.on_change)['_save_launcher_preferences']
            cfg=scope(helper)['cfg']
            old=dict(cfg);display=control.value
            control.value=not display
            with patch.object(self.core,'save_config',side_effect=OSError('fixture')):
                control.on_change(None)
            self.assertEqual(cfg,old)
            self.assertEqual(control.value,display)
            with patch.object(self.core,'save_config') as save:
                control.value=not display
                control.on_change(None)
                save.assert_called_once()
            control.value=display
            with patch.object(self.core,'save_config'):
                control.on_change(None)

    def test_season_failure_cannot_apply_runtime_or_claim_success(self):
        for data,handler in (('settings-seasonal-enabled','_on_seasonal_toggle'),
                             ('settings-buddy-enabled','_on_season_pet_toggle'),
                             ('settings-scenery-enabled','_on_season_overlay_toggle')):
            control=self.control(data=data)
            values=scope(control.on_change)
            cfg=values['cfg'];old=dict(cfg);display=control.value
            with patch.object(self.core,'save_config',side_effect=OSError('fixture')):
                control.value=not display
                control.on_change(None)
            self.assertEqual(cfg,old)
            self.assertEqual(control.value,display)
        dropdown=self.control(handler='_on_season_change')
        values=scope(dropdown.on_select);cfg=values['cfg'];old=dict(cfg)
        before=dropdown.value
        dropdown.value='winter' if before!='winter' else 'summer'
        with patch.object(self.core,'save_config',side_effect=OSError('fixture')):
            dropdown.on_select(None)
        self.assertEqual(dropdown.value,before)
        self.assertEqual(cfg,old)

    def test_dimensions_save_is_atomic_and_failed_edit_is_retryable(self):
        width=next(c for c in self.controls if isinstance(c,ft.TextField) and c.label=='Width')
        save=scope(width.on_submit)['_save_on_blur']
        cfg=scope(save)['cfg'];old=dict(cfg);old_value=width.value
        width.value='-100'
        with patch.object(self.core,'save_config',side_effect=OSError('fixture')):
            width.on_submit(SimpleNamespace(control=width))
        self.assertEqual(width.value,'-100')
        self.assertEqual(cfg,old)
        self.assertTrue(width.error)
        with patch.object(self.core,'save_config') as persist:
            width.on_submit(SimpleNamespace(control=width))
            width.on_blur(SimpleNamespace(control=width))
            self.assertEqual(persist.call_count,1)
        self.assertEqual(width.value,'320')
        self.assertIsNone(width.error)
        width.value=old_value
        with patch.object(self.core,'save_config'):
            width.on_blur(SimpleNamespace(control=width))

    def test_failed_ram_save_restores_last_committed_allocation(self):
        slider=next(c for c in self.controls if isinstance(c,ft.Slider))
        finished=slider.on_change_end.__defaults__[0]
        values=scope(finished)
        cfg=values['cfg'];old=values['_ram_saved']['value']
        slider.value=old-256 if old>slider.min else old+256
        slider.on_change(None)
        with patch.object(self.core,'save_config',side_effect=OSError('fixture')):
            slider.on_change_end(None)
        self.assertEqual(cfg['ram_mb'],old)
        self.assertEqual(slider.value,old)

    def test_backup_preferences_roll_back_and_retention_enter_saves_once(self):
        enabled=self.control(handler='on_backup_enabled_change')
        persist=scope(enabled.on_change)['_persist_backup_settings']
        values=scope(persist);settings=values['backup_settings'];old=dict(settings)
        enabled.value=not settings['enabled']
        with patch.object(self.core.backup_module,'save_backup_settings',side_effect=OSError('fixture')):
            enabled.on_change(None)
        self.assertEqual(settings,old)
        self.assertEqual(enabled.value,old['enabled'])
        self.assertEqual(values['frequency_dropdown'].disabled,not old['enabled'])
        field=values['keep_last_field'];field.value='0'
        with patch.object(self.core.backup_module,'save_backup_settings') as save:
            field.on_submit(None);field.on_blur(None)
            self.assertEqual(save.call_count,1)
        self.assertEqual(settings['keep_last'],0)
        self.assertEqual(field.value,'0')
        field.value='not-a-number'
        with patch.object(self.core.backup_module,'save_backup_settings') as save:
            field.on_blur(None);save.assert_not_called()
        self.assertTrue(field.error)
        field.value=str(old['keep_last'])
        with patch.object(self.core.backup_module,'save_backup_settings'):
            field.on_blur(None)

    def test_backup_worker_captures_options_and_clears_busy_after_failure(self):
        button=self.control(handler='run_backup_now')
        values=scope(button.on_click)
        options=values['include_saves_switch'];before=options.value
        options.value=True
        with patch('threading.Thread',QueuedThread):
            button.on_click(None);button.on_click(None)
        self.assertEqual(len(QueuedThread.jobs),1)
        self.assertTrue(button.disabled)
        self.assertTrue(button.cubeon_keyboard_button.disabled)
        options.value=False
        with patch.object(self.core.backup_module,'create_backup',side_effect=OSError('fixture')) as create:
            with self.assertLogs(level='WARNING'):
                QueuedThread.jobs.pop()()
        create.assert_called_once_with(include_saves=True)
        self.assertFalse(button.disabled)
        self.assertFalse(button.cubeon_keyboard_button.disabled)
        self.assertEqual(button.content.value,'Back up now')
        self.assertFalse(values['backup_busy']['value'])
        options.value=before

    def test_restore_worker_failure_and_thread_start_failure_release_actions(self):
        restore=self.control(handler='pick_restore_file')
        do_restore=scope(restore.on_click)['do_restore']
        with patch('threading.Thread',QueuedThread):
            do_restore([SimpleNamespace(path='/tmp/fixture-backup.zip')])
        self.assertTrue(restore.disabled)
        with patch.object(self.core.backup_module,'restore_backup',side_effect=OSError('fixture')):
            with self.assertLogs(level='WARNING'):
                QueuedThread.jobs.pop()()
        self.assertFalse(restore.disabled)
        self.assertFalse(restore.cubeon_keyboard_button.disabled)
        with patch.object(threading.Thread,'start',side_effect=RuntimeError('fixture')):
            do_restore([SimpleNamespace(path='/tmp/fixture-backup.zip')])
        self.assertFalse(restore.disabled)

    def test_backup_settings_atomic_failure_keeps_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'backup_settings.json'
            path.write_text(json.dumps({'enabled':False}))
            with patch.object(backup,'BACKUPS_DIR',folder),patch.object(backup,'BACKUP_META_PATH',str(path)), \
                 patch.object(atomicio.os,'replace',side_effect=OSError('fixture')):
                with self.assertRaises(OSError):backup.save_backup_settings({'enabled':True})
            self.assertEqual(json.loads(path.read_text()),{'enabled':False})
            self.assertEqual(list(Path(folder).iterdir()),[path])

if __name__=='__main__':unittest.main()
