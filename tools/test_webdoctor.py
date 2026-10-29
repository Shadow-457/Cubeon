"""Offline launcher handoff checks, plus the browser's pure diagnosis contracts."""
import base64
import json
from pathlib import Path
import random
import shutil
import string
import subprocess
import sys
import unittest
from unittest.mock import patch
from urllib.parse import urlsplit
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from cubeon import webdoctor

def unpack(url):
    encoded = urlsplit(url).fragment.removeprefix('report=')
    return json.loads(zlib.decompress(base64.urlsafe_b64decode(encoded + '=' * (-len(encoded) % 4))))

class WebDoctorTests(unittest.TestCase):
    def test_redacted_roundtrip(self):
        text = ('--accessToken secret-token --username Alice --server secret.example\n'
                'Authorization: Bearer private-token\n'
                'password="dontshare" api_key=hidden\n'
                'C:\\Users\\Alice\\game /home/alice/game alice@example.com\n'
                'java.lang.OutOfMemoryError: Java heap space\nالعربية Русский')
        url = webdoctor.doctor_url(text, reason='password=reasonsecret', version_label='Pack 1.21')
        self.assertEqual(urlsplit(url).path, '/doctor')
        self.assertEqual(urlsplit(url).query, '')
        report = unpack(url)
        for private in ('secret-token','Alice','secret.example','private-token','dontshare','hidden','alice@example.com','/home/alice','reasonsecret'):
            self.assertNotIn(private, json.dumps(report))
        self.assertIn('OutOfMemoryError', report['log'])
        self.assertIn('العربية Русский', report['log'])
        self.assertFalse(report['truncated'])

    def test_bounds_and_bad_origins(self):
        rng = random.Random(32)
        source = ''.join(rng.choices(string.ascii_letters + string.digits, k=150000)) + '\nGLFW error 65542'
        url = webdoctor.doctor_url(source)
        self.assertLessEqual(len(url), webdoctor.MAX_URL_CHARS)
        self.assertTrue(unpack(url)['truncated'])
        self.assertTrue(unpack(url)['log'].endswith('GLFW error 65542'))
        unicode_url = webdoctor.doctor_url('😀' * 70000)
        self.assertLessEqual(len(unpack(unicode_url)['log']), 64000)
        for origin in ('http://example.com','file:///tmp','javascript:alert(1)','https://user:pass@example.com'):
            with self.assertRaises(ValueError): webdoctor.doctor_url('error', base_url=origin)
        self.assertTrue(webdoctor.doctor_url('error',base_url='http://localhost:8080').startswith('http://localhost:8080/doctor#'))

    def test_click_handoff_and_failure(self):
        with patch.object(webdoctor.webbrowser, 'open', return_value=True) as opened:
            self.assertTrue(webdoctor.open_doctor('error'))
            self.assertEqual(unpack(opened.call_args.args[0])['log'], 'error')
        with patch.object(webdoctor.webbrowser, 'open', side_effect=OSError()):
            self.assertFalse(webdoctor.open_doctor('error'))

    def test_crash_button(self):
        from cubeon import dialogs, i18n
        from ui.crash_report import show_crash_dialog
        class Page:
            pass
        with patch.object(dialogs, 'open_dialog') as opened, patch.object(webdoctor, 'open_doctor', return_value=False) as browser:
            snack = []
            i18n.set_language('ar')
            show_crash_dialog(Page(), reason='Error', log_text='OutOfMemoryError',
                              version_label='1.21', show_snack=lambda *a, **k: snack.append(a))
            dlg = opened.call_args.args[1]
            self.assertEqual(len(dlg.actions), 5, 'Crash report has Check & fix, Doctor, Copy, Discord and Close')
            import flet as ft
            self.assertFalse(any(getattr(a, 'icon', None) == ft.Icons.BUILD_ROUNDED for a in dlg.actions))
            buttons = [a for a in dlg.actions if getattr(a,'data',None) == 'crash-web-doctor']
            self.assertEqual(len(buttons),1)
            self.assertEqual(buttons[0].content, 'الطبيب')
            buttons[0].on_click(None)
            browser.assert_called_once_with('OutOfMemoryError',reason='Error',version_label='1.21')
            self.assertIn('Copy log',snack[0][0])
            i18n.set_language('en')

    def test_javascript_core(self):
        node = shutil.which('node')
        if not node: self.skipTest('Node is required for website checks')
        subprocess.run([node, str(ROOT / 'tools/test_webdoctor_core.cjs')], check=True, cwd=ROOT, timeout=30)
        subprocess.run([node, str(ROOT / 'tools/test_webdoctor_endpoint.cjs')], check=True, cwd=ROOT, timeout=30)

if __name__ == '__main__':
    unittest.main()
