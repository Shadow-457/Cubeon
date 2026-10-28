#!/usr/bin/env python3
"""Language tables, startup resolution, and fallback contracts (no network)."""
import ast
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import i18n, lang

class LanguageTests(unittest.TestCase):
    def tearDown(self):
        i18n.set_language('en')

    def test_order_and_all_tables(self):
        self.assertEqual(i18n.SUPPORTED[:4], ('ar', 'en', 'ru', 'es'))
        required = {'Play', 'Settings', 'Language', 'PLAY', 'CANCEL',
                    'Chat messages', "Cubeon's default flags", 'Check & repair'}
        for code in i18n.SUPPORTED:
            if code == 'en':
                continue
            with self.subTest(code=code):
                table = lang.table_for(code)
                self.assertTrue(required <= table.keys())
                self.assertTrue(all(isinstance(k, str) and isinstance(v, str)
                                    and v.strip() for k, v in table.items()))
                i18n.set_language(code)
                self.assertEqual(i18n.t('Play'), table['Play'])
                tree = ast.parse((Path(lang.__file__).parent /
                                  (code.replace('-', '_') + '.py')).read_text())
                table_node = next(n.value for n in tree.body if isinstance(n, ast.Assign))
                keys = [ast.literal_eval(k) for k in table_node.keys]
                self.assertEqual(len(keys), len(set(keys)), 'duplicate translation key')

    def test_locale_and_explicit_choice(self):
        for raw, code in [('ar_SA.UTF-8', 'ar'), ('ru_RU', 'ru'),
                          ('pt_BR.UTF-8', 'pt-br'), ('zh_CN', 'zh-cn'),
                          ('es_MX', 'es'), ('ur_PK', 'ur'),
                          ('Arabic_Saudi Arabia', 'ar'), ('Russian_Russia', 'ru')]:
            self.assertEqual(i18n.resolve_language({}, env={'LANG': raw}), code)
        self.assertEqual(i18n.resolve_language({'ui_language': 'es'},
                         env={'LANG': 'ar_SA'}), 'es')
        self.assertEqual(i18n.resolve_language({'ui_language': 'broken'},
                         env={'LANG': 'ar_SA'}), 'en')
        self.assertEqual(i18n.resolve_language({}, env={'LANGUAGE':'cy:ar'}), 'ar')

    def test_rtl_and_fallback(self):
        i18n.set_language('ar')
        self.assertTrue(i18n.is_rtl())
        self.assertTrue(i18n.is_rtl('ur'))
        self.assertFalse(i18n.is_rtl('es'))
        self.assertEqual(i18n.t('Unknown {name}', name='Alex'), 'Unknown Alex')
        self.assertEqual(i18n.set_language('unsupported'), 'en')
        self.assertEqual(i18n.t('Play'), 'Play')
        with patch.object(i18n, '_tables', {}), patch.object(lang, 'table_for', side_effect=ValueError('bad table')):
            i18n.set_language('ar')
            self.assertEqual(i18n.t('Play'), 'Play')

if __name__ == '__main__':
    unittest.main()
