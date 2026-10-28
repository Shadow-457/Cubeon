#!/usr/bin/env python3
"""Offline crawl checks for production canonical URLs and discoverable pages."""
from html.parser import HTMLParser
import json
from pathlib import Path
import unittest
from urllib.parse import urlsplit
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
ORIGIN = 'https://cubeon.ylet.online'


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.meta, self.canonicals, self.links, self.headings, self.schemas = {}, [], [], [], []
        self.title = ''
        self.active = None
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'meta':
            key = attrs.get('name') or attrs.get('property')
            self.meta.setdefault(key, []).append(attrs.get('content', ''))
        if tag == 'link' and attrs.get('rel') == 'canonical':
            self.canonicals.append(attrs.get('href'))
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'title':
            self.active = 'title'
        if tag == 'h1':
            self.headings.append('')
            self.active = 'h1'
        if tag == 'script' and attrs.get('type') == 'application/ld+json':
            self.schemas.append('')
            self.active = 'schema'

    def handle_endtag(self, tag):
        if tag in ('title', 'h1', 'script'):
            self.active = None

    def handle_data(self, data):
        if self.active == 'title':
            self.title += data
        elif self.active == 'h1':
            self.headings[-1] += data
        elif self.active == 'schema':
            self.schemas[-1] += data


class SEOTests(unittest.TestCase):
    def setUp(self):
        self.pages = {path.stem: Page(path.read_text()) for path in WEB.glob('*.html')}

    def test_canonical_inventory_and_sitemap(self):
        expected = set()
        titles, descriptions = [], []
        for key, page in self.pages.items():
            with self.subTest(page=key):
                if key.isdigit():
                    self.assertIn('noindex', ','.join(page.meta.get('robots', [])))
                    continue
                url = ORIGIN + ('/' if key == 'index' else '/' + key)
                expected.add(url)
                self.assertEqual(page.canonicals, [url])
                self.assertEqual(page.meta['og:url'], [url])
                self.assertEqual(page.meta['og:site_name'], ['Cubeon'])
                self.assertNotIn('noindex', ','.join(page.meta.get('robots', [])))
                self.assertEqual(len(page.headings), 1)
                self.assertTrue(page.title.strip())
                self.assertEqual(len(page.meta['description']), 1)
                titles.append(page.title)
                descriptions.append(page.meta['description'][0])
        self.assertEqual(len(titles), len(set(titles)))
        self.assertEqual(len(descriptions), len(set(descriptions)))
        sitemap = ET.parse(WEB / 'sitemap.xml')
        locations = [entry.text for entry in sitemap.findall('.//{*}loc')]
        self.assertEqual(len(locations), len(set(locations)))
        self.assertEqual(set(locations), expected)
        # Error pages, API routes, redirect-only downloads and personal log fragments stay out.
        self.assertTrue(all(not urlsplit(url).query and not urlsplit(url).fragment for url in locations))
        robots = (WEB / 'robots.txt').read_text()
        self.assertIn('User-agent: *\nAllow: /\nDisallow: /api/', robots)
        self.assertIn('Sitemap: ' + ORIGIN + '/sitemap.xml', robots)

    def test_product_data_matches_visible_product(self):
        page = self.pages['index']
        self.assertIn('Cubeon', page.headings[0])
        self.assertIn('Minecraft Launcher', page.headings[0])
        self.assertIn('Minecraft Launcher', self.pages['download'].title)
        schema, = [json.loads(value) for value in page.schemas]
        self.assertEqual(schema['@context'], 'https://schema.org')
        graph = {entry['@type']: entry for entry in schema['@graph']}
        self.assertEqual(graph['WebSite']['url'], page.canonicals[0])
        self.assertIn('Cubeon Launcher', graph['WebSite']['alternateName'])
        product = graph['SoftwareApplication']
        self.assertTrue(product['isAccessibleForFree'])
        self.assertEqual(product['offers']['price'], '0')
        self.assertEqual(product['downloadUrl'], self.pages['download'].canonicals[0])
        self.assertNotIn('aggregateRating', product)
        self.assertNotIn('review', product)
        for asset in ['screenshot', 'image']:
            self.assertTrue((WEB / urlsplit(product[asset]).path.lstrip('/')).is_file())
        for guide in ['getting-started', 'mods', 'modpacks', 'multiplayer', 'troubleshooting']:
            self.assertTrue(any(urlsplit(link).path in [guide + '.html', '/' + guide] for link in page.links))


if __name__ == '__main__':
    unittest.main()
