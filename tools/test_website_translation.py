"""Translation tooling must retain working shared JS and stable sitemap URLs."""
import contextlib
import io
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
        self.assertIn('ar: 1211/1211 translated', output.getvalue())
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
            self.assertEqual(len(urls), 76)
            self.assertEqual(len(set(urls)), len(urls))
            self.assertEqual(len(root.findall('.//{http://www.google.com/schemas/sitemap-image/1.1}image')), 12)

    def test_title_translation_cannot_corrupt_later_attributes(self):
        from test_website_seo import Page
        for name in ('index', 'docs', '403', '404', '500', '502'):
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


if __name__ == '__main__':
    unittest.main()
