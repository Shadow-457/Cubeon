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
                    'Wardrobe', 'My items', 'Chat messages', "Cubeon's default flags", 'Check & repair'}
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
                          ('pt_BR.UTF-8', 'pt-br'), ('pt_PT.UTF-8', 'pt-pt'),
                          ('pt_PT@euro', 'pt-pt'), ('pt', 'pt-br'), ('zh_CN', 'zh-cn'),
                          ('Portuguese_Portugal.1252', 'pt-pt'),
                          ('es_MX', 'es'), ('ur_PK', 'ur'),
                          ('Arabic_Saudi Arabia', 'ar'), ('Russian_Russia', 'ru')]:
            self.assertEqual(i18n.resolve_language({}, env={'LANG': raw}), code)
        self.assertEqual(i18n.resolve_language({'ui_language': 'es'},
                         env={'LANG': 'ar_SA'}), 'es')
        self.assertEqual(i18n.resolve_language({'ui_language': 'broken'},
                         env={'LANG': 'ar_SA'}), 'en')
        self.assertEqual(i18n.resolve_language({}, env={'LANGUAGE':'cy:ar'}), 'ar')
        self.assertEqual(i18n.resolve_language({'ui_language': 'pt-br'},
                         env={'LANG': 'pt_PT.UTF-8'}), 'pt-br')

    def test_european_portuguese_has_distinct_labels(self):
        i18n.set_language('pt-pt')
        self.assertEqual(i18n.language_name('pt-pt'), 'Português (Portugal)')
        self.assertFalse(i18n.is_rtl())
        self.assertEqual(i18n.t('Settings'), 'Definições')
        self.assertEqual(i18n.t('Save'), 'Guardar')
        self.assertEqual(i18n.t('Username'), 'Nome de utilizador')
        self.assertEqual(i18n.t('Load more'), 'Carregar mais')
        i18n.set_language('pt-br')
        self.assertEqual(i18n.t('Save'), 'Salvar')

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
