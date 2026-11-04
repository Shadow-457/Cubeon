"""Translation tooling must retain working shared JS and stable sitemap URLs."""
import contextlib
import io
import json
from pathlib import Path
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import xml.etree.ElementTree as ET

import translate_website as translations

ROOT = Path(__file__).resolve().parents[1]


class WebsiteTranslation(unittest.TestCase):
    def test_shared_site_script_parses(self):
        subprocess.run(['node', '--check', str(ROOT / 'web/assets/site.js')], check=True,
                       capture_output=True)

    def test_arabic_catalog_check_runs_and_honors_selection(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            self.assertEqual(translations.check(['ar']), 0)
        count = len(json.loads((translations.I18N / 'source.json').read_text())['strings'])
        self.assertIn(f'ar: {count}/{count} translated', output.getvalue())
        self.assertNotIn('uk:', output.getvalue())

    def test_repeated_sitemap_build_preserves_unique_urls_and_images(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sitemap = folder / 'sitemap.xml'
            sitemap.write_bytes((ROOT / 'web/sitemap.xml').read_bytes())
            with patch.object(translations, 'WEB', folder), contextlib.redirect_stdout(io.StringIO()):
                translations.write_sitemap()
                first = sitemap.read_bytes()
                translations.write_sitemap()
            self.assertEqual(sitemap.read_bytes(), first)
            root = ET.parse(sitemap).getroot()
            urls = [entry.find('{*}loc').text for entry in root]
            count = sum(not page.isdigit() for page in translations.PAGES) * len(translations.translated_languages())
            self.assertEqual(len(urls), count)
            self.assertEqual(len(set(urls)), len(urls))
            self.assertEqual(len(root.findall('.//{http://www.google.com/schemas/sitemap-image/1.1}image')), 12)

    def test_new_public_pages_are_added_to_sitemap_without_manual_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            sitemap = folder / 'sitemap.xml'
            sitemap.write_bytes((ROOT / 'web/sitemap.xml').read_bytes())
            with patch.object(translations, 'WEB', folder), \
                    patch.object(translations, 'PAGES', translations.PAGES + ['new-guide', '599']), \
                    contextlib.redirect_stdout(io.StringIO()):
                translations.write_sitemap()
            urls = [entry.find('{*}loc').text for entry in ET.parse(sitemap).getroot()]
            for language in translations.translated_languages():
                self.assertIn(translations.page_url('new-guide', language), urls)
                self.assertNotIn(translations.page_url('599', language), urls)
            self.assertNotIn(translations.page_url('new-guide', 'uk'), urls)
            self.assertNotIn(translations.page_url('new-guide', 'ru'), urls)

    def test_untranslated_fallbacks_are_not_promoted_as_localized_content(self):
        from test_website_seo import Page
        for language in ('uk', 'ru'):
            source, _ = translations.translate_page('minecraft-launcher', language)
            page = Page(source)
            self.assertEqual(page.canonicals, [translations.page_url('minecraft-launcher', 'en')])
            self.assertIn('noindex', page.meta['robots'][0])
            self.assertIn('<html lang="en">', source)
            self.assertNotIn('hreflang="' + language + '"', source)
            self.assertIn('var names = { en: 1, ar: 1 }', source)

    def test_title_translation_cannot_corrupt_later_attributes(self):
        from test_website_seo import Page
        for name in ('index', 'docs', 'minecraft-launcher', '403', '404', '500', '502'):
            source = translations.strip_generated(translations.read_page(name))
            generated, _ = translations.translate_page(name, 'ar')
            english, arabic = Page(source), Page(generated)
            catalog = translations.load_catalog('ar')
            description = english.meta['description'][0]
            self.assertEqual(arabic.meta['description'], [catalog.get(description, description)])
            if name.isdigit():
                self.assertEqual(arabic.meta['robots'], ['noindex'])
            else:
                self.assertEqual(len(arabic.images), len(english.images))
                self.assertIn('aria-label=', generated)
            if name == 'docs':
                self.assertIn('srcset="/assets/screenshots/previews/', generated)
            if name == 'minecraft-launcher':
                schema, = [json.loads(value) for value in arabic.schemas]
                graph = {node['@type']: node for node in schema['@graph']}
                self.assertEqual(graph['WebPage']['url'], translations.page_url(name, 'ar'))
                self.assertEqual(graph['Article']['headline'], arabic.headings[0])
                self.assertEqual(graph['Article']['about'], {'@id': translations.ORIGIN + '/#launcher'})
                self.assertEqual([entry['item'] for entry in graph['BreadcrumbList']['itemListElement']],
                                 [translations.page_url(p, 'ar') for p in ('index', 'docs', name)])


if __name__ == '__main__':
    unittest.main()
