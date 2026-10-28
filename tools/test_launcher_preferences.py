#!/usr/bin/env python3
"""Defaults match launch argv, Windows migration, and live-message toasts."""
import base64
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import patch, Mock
import xml.etree.ElementTree as ET
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import config, launch, osnotify, friends_service, theme
from ui.settings_tab import _java_defaults_panel
from ui.settings_tab import _language_picker
from cubeon import atomicio, i18n
import flet as ft

class LanguagePickerTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language('en')

    def build(self, cfg, restart):
        return _language_picker(cfg, on_restart=restart, set_status=lambda _:None,
            **{key:getattr(theme,key) for key in ('BG','BORDER','ACCENT','TEXT','TEXT_DIM')})

    def test_search_save_restart_and_revert(self):
        i18n.set_language('en')
        cfg = {'ui_language':'en','version_labels':{'instance':'My world'}}
        restart = Mock()
        panel = self.build(cfg, restart)
        selector, dropdown, notice = panel.controls[1:]
        search, choices, empty = dropdown.content.controls
        selector.on_click(None)
        self.assertEqual([c.data for c in choices.controls[:4]],
                         ['language-option-ar','language-option-en','language-option-ru','language-option-es'])
        for query, expected in [('العربية','ar'),('russian','ru'),('espanol','es'),('pt-br','pt-br')]:
            search.value=query; search.on_change(None)
            self.assertEqual([c.data for c in choices.controls], ['language-option-'+expected])
        search.value='no such language'; search.on_change(None)
        self.assertTrue(empty.visible)
        self.assertFalse(choices.visible)
        search.value='es'; search.on_change(None)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp)/'config.json'
            with patch.object(config,'save_config',side_effect=lambda data:atomicio.write_json(str(path),data)):
                next(c for c in choices.controls if c.data=='language-option-es').on_click(None)
                saved=json.loads(path.read_text())
                self.assertEqual(saved['ui_language'],'es')
                self.assertEqual(saved['version_labels'],cfg['version_labels'])
                self.assertEqual(i18n.current(),'en')
                self.assertFalse(dropdown.visible)
                self.assertTrue(notice.visible)
                notice.controls[1].on_click(None)
                restart.assert_called_once()
                selector.on_click(None)
                next(c for c in choices.controls if c.data=='language-option-en').on_click(None)
                self.assertFalse(notice.visible)

    def test_failed_save_keeps_choice_and_config_shape(self):
        for cfg in [{'ui_language':'en'}, {}]:
            with self.subTest(cfg=cfg):
                original=cfg.copy()
                panel=self.build(cfg,lambda _:None)
                panel.controls[1].on_click(None)
                choices=panel.controls[2].content.controls[1]
                with patch.object(config,'save_config',side_effect=OSError('disk full')):
                    next(c for c in choices.controls if c.data=='language-option-ar').on_click(None)
                self.assertEqual(cfg,original)
                self.assertTrue(panel.controls[2].visible)
                self.assertFalse(panel.controls[3].visible)

class FlagsTests(unittest.TestCase):
    def test_report_matches_actual_command(self):
        def command(_vid, _folder, opts):
            return ['java', *opts['jvmArguments'], '-cp', 'game.jar', 'game.Main']
        for ram, system_ram, cores, custom in [
            (2048, 4096, 2, ''), (4096, 16384, 8, ''),
            (4096, 16384, 4, '-XX:+UseZGC'),
            (2048, 16384, 8, '-XX:+UseG1GC -XX:MaxGCPauseMillis=77'),
            (4096, 16384, 8, '-XX:-AlwaysPreTouch')]:
            with self.subTest(custom=custom, ram=ram, cores=cores), \
                 patch.object(launch, '_sanitize_client_json'), \
                 patch.object(launch, '_restore_emptied_arguments'), \
                 patch.object(launch, 'stable_uuid', return_value='test'), \
                 patch.object(launch, 'find_java_for_version', return_value=None), \
                 patch.object(launch, '_available_cpus', return_value=cores), \
                 patch.object(launch, 'get_system_ram_mb', return_value=system_ram), \
                 patch.object(launch.mll.command, 'get_minecraft_command', side_effect=command):
                report = launch.default_jvm_flags_report(ram, custom_jvm_flags=custom)
                argv = launch.build_launch_command('test', 'Alex', ram, 854, 480,
                                                    custom_jvm_flags=custom)
                for row in report:
                    if row['source'] == 'dropped':
                        self.assertNotIn(row['flag'], argv)
                    else:
                        self.assertIn(row['flag'], argv)
                if 'UseZGC' in custom:
                    self.assertFalse(any(flag.startswith('-XX:G1') for flag in argv))
                else:
                    self.assertEqual(argv.count('-XX:+UseG1GC'), 1)
                if '-XX:-AlwaysPreTouch' in custom:
                    self.assertGreater(argv.index('-XX:-AlwaysPreTouch'),
                                       argv.index('-XX:+AlwaysPreTouch'))

    def test_expanded_panel_tracks_edits(self):
        saved = []
        slider = ft.Slider(value=2048, on_change=lambda e: saved.append(True))
        custom = ft.TextField(value='')
        panel = _java_defaults_panel(ram_slider=slider, custom_jvm_field=custom,
            **{key: getattr(theme, key) for key in
               ('BORDER','ACCENT','ACCENT_TINT','TEXT','TEXT_DIM','TEXT_FAINT','FONT_MONO')})
        header, rows = panel.content.controls
        header.on_click(None)
        self.assertTrue(rows.visible)
        self.assertIn('-Xmx2048M', [c.content.controls[0].value for c in rows.controls])
        slider.value = 4096
        slider.on_change(None)
        self.assertTrue(saved)
        self.assertIn('-Xmx4096M', [c.content.controls[0].value for c in rows.controls])
        custom.value = '-XX:+UseZGC'
        custom.on_change(None)
        g1 = next(c for c in rows.controls if c.content.controls[0].value == '-XX:+UseG1GC')
        self.assertEqual(len(g1.content.controls[1].controls), 2)

class WindowsTests(unittest.TestCase):
    def test_legacy_and_explicit_choices(self):
        for chosen, value, expected in [(False, False, True), (True, False, False),
                                        (True, True, True), (False, None, None)]:
            with self.subTest(chosen=chosen, value=value), tempfile.TemporaryDirectory() as tmp:
                path = str(Path(tmp) / 'config.json')
                Path(path).write_text(json.dumps({'custom_window_chrome': value,
                    'custom_window_chrome_chosen': chosen}))
                with patch.object(config, 'CONFIG_PATH', path), patch.object(sys, 'platform', 'win32'):
                    self.assertIs(config.load_config()['custom_window_chrome'], expected)

class MessageTests(unittest.TestCase):
    def setUp(self):
        self.service = friends_service.FriendsService({}, {},
            types.SimpleNamespace(is_connected=False))
        self.service._schedule_chat_save = lambda: None
        self.service._remember_event = lambda p: None
        self.service._ensure_e2ee = lambda: ('private', 'public')
        self.service._my_name = lambda: 'Steve'
        self.service.peer_label = lambda name: name
        self.service._changed = lambda: None
        self.service._notify = lambda *a, **kw: None
        self.payload = {'from': 'Alex', 'to': 'Steve', 'text': '{"ts": 1234}', 'id': 'live'}

    def test_live_dedupe_and_history_silence(self):
        with patch.object(friends_service.e2ee, 'decrypt_dm', return_value='Hello'), \
             patch.object(osnotify, 'chat_message') as notify:
            self.service._on_dm(self.payload)
            self.service._on_dm(self.payload)
            self.assertEqual(notify.call_count, 1)
            self.service._on_history({'peer':'Alex', 'messages':[
                {'from':'Alex', 'text':'{"ts": 1233}', 'id':'history'}]})
            self.assertEqual(notify.call_count, 1)

    def test_separate_viewers_and_expiry(self):
        with patch.object(osnotify, 'chat_message') as notify:
            self.service.set_open_conversation('Alex', viewer='bridge')
            self.service.set_open_conversation('Alex', viewer='launcher')
            self.service.set_open_conversation('Alex', open_=False, viewer='launcher')
            self.service._notify_incoming_message('alex', 'Alex', 'Hello')
            notify.assert_not_called()
            self.service._chat_open[('bridge', 'alex')] = 0
            self.service._notify_incoming_message('alex', 'Alex', 'Hello')
            notify.assert_called_once()

    def test_hidden_poll_keeps_unread(self):
        self.service._chat_append('alex','in','Alex','Hello',1234,mid='unread')
        self.service.chat_payload('Alex', -1, viewing=False, viewer='launcher')
        self.assertEqual(self.service._chat_read.get('alex', 0), 0)
        self.service.chat_payload('Alex', -1, viewing=True, viewer='launcher')
        self.assertEqual(self.service._chat_read['alex'], 1)

    def test_preview_and_windows_payload(self):
        with patch.object(osnotify, 'notify', return_value=True) as notify:
            self.assertTrue(osnotify.chat_message('Alex', ' hi\n' + 'x' * 180))
            self.assertEqual(notify.call_args.args[0], 'message')
            self.assertLessEqual(len(notify.call_args.args[2]), 140)
        text = "مرحبا ' ` $()\n<&>"
        with patch.object(osnotify, '_run', return_value=True) as run:
            osnotify._send_powershell(text, text)
            argv = run.call_args.args[0]
            script = base64.b64decode(argv[-1]).decode('utf-16-le')
            encoded_xml = script.split('FromBase64String("')[1].split('"')[0]
            root = ET.fromstring(base64.b64decode(encoded_xml).decode('utf-8'))
            self.assertEqual([n.text for n in root.iter('text')], [text, text])
            self.assertNotIn(text, script)
        self.assertFalse(osnotify.enabled('message', {'notify_message': False}))

if __name__ == '__main__':
    unittest.main()
