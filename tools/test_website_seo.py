#!/usr/bin/env python3
"""Offline crawl checks for production canonical URLs and discoverable pages."""
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import struct
import unittest
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
ORIGIN = 'https://www.ylet.online'


class Page(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.meta, self.canonicals, self.links, self.headings, self.schemas = {}, [], [], [], []
        self.favicons = []
        self.images = []
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
        if tag == 'link' and attrs.get('rel') == 'icon':
            self.favicons.append(attrs)
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'img':
            self.images.append(attrs)
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
        self.pages = {path.stem: Page(path.read_text()) for path in WEB.glob('*.html')
                      if not re.fullmatch(r'google[0-9a-f]+', path.stem)}

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
                self.assertEqual(page.meta['og:site_name'], ['Cubeon Launcher'])
                self.assertNotIn('noindex', ','.join(page.meta.get('robots', [])))
                self.assertEqual(len(page.headings), 1)
                self.assertTrue(page.title.strip())
                self.assertEqual(len(page.meta['description']), 1)
                titles.append(page.title)
                descriptions.append(page.meta['description'][0])
        self.assertEqual(len(titles), len(set(titles)))
        self.assertEqual(len(descriptions), len(set(descriptions)))
        sitemap = ET.parse(WEB / 'sitemap.xml')
        locations = [entry.text for entry in sitemap.findall('./{*}url/{http://www.sitemaps.org/schemas/sitemap/0.9}loc')]
        self.assertEqual(len(locations), len(set(locations)))
        self.assertEqual(set(locations), expected)
        # Error pages, API routes, redirect-only downloads and personal log fragments stay out.
        self.assertTrue(all(not urlsplit(url).query and not urlsplit(url).fragment for url in locations))
        robots = (WEB / 'robots.txt').read_text()
        self.assertIn('User-agent: *\nAllow: /\nDisallow: /api/', robots)
        self.assertIn('Sitemap: ' + ORIGIN + '/sitemap.xml', robots)

    def test_image_discovery_matches_visible_page_content(self):
        """Every sitemap image appears in ordinary HTML on its associated page."""
        namespace = {'s': 'http://www.sitemaps.org/schemas/sitemap/0.9',
                     'image': 'http://www.google.com/schemas/sitemap-image/1.1'}
        sitemap = ET.parse(WEB / 'sitemap.xml')
        images = []
        for page in sitemap.findall('s:url', namespace):
            page_url = page.find('s:loc', namespace).text
            page_key = urlsplit(page_url).path.strip('/') or 'index'
            html = self.pages[page_key]
            for image in page.findall('image:image', namespace):
                location = image.find('image:loc', namespace)
                self.assertIsNotNone(location)
                url = urlsplit(location.text)
                self.assertEqual(url.scheme + '://' + url.netloc, ORIGIN)
                self.assertFalse(url.query or url.fragment)
                file = WEB / url.path.lstrip('/')
                self.assertTrue(file.is_file(), location.text)
                self.assertIn(file.suffix, ('.png', '.webp'))
                matches = [img for img in html.images if urljoin(page_url, img.get('src', '')) == location.text]
                self.assertEqual(len(matches), 1, (page_url, location.text))
                displayed, = matches
                self.assertGreater(len(displayed.get('alt', '').strip()), 25)
                self.assertGreater(int(displayed['width']), 0)
                self.assertGreater(int(displayed['height']), 0)
                self.assertEqual(displayed['loading'], 'lazy')
                self.assertIn(displayed['src'], html.links, 'A full-size image link must be available')
                # Deprecated caption/title tags are no longer read by Google.
                self.assertEqual([child.tag for child in image], ['{' + namespace['image'] + '}loc'])
                if '/screenshots/' in url.path:
                    self.assertRegex(file.name, r'^cubeon-[a-z-]+\.png$')
                    data = file.read_bytes()
                    self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
                    width, height = struct.unpack('>II', data[16:24])
                    self.assertGreaterEqual(width, 1000)
                    self.assertGreaterEqual(height, 500)
                    self.assertIn(b'Title\x00', data)
                    self.assertIn(b'Description\x00', data)
                    self.assertNotIn(b'eXIf', data)
                images.append(location.text)
        self.assertEqual(len(images), 12)
        self.assertEqual(len(images), len(set(images)))
        public_copies = {ORIGIN + '/' + str(file.relative_to(WEB))
                         for file in (WEB / 'assets/screenshots').glob('*.png')}
        self.assertTrue(public_copies.issubset(set(images)), 'Every public copy must be discoverable')
        self.assertEqual(len(self.pages['docs'].images) - 2, 12)  # Two brand icons outside the gallery.
        for url in images:
            preview = WEB / 'assets/screenshots/previews' / (Path(urlsplit(url).path).stem + '.webp')
            data = preview.read_bytes()
            self.assertEqual(data[:4], b'RIFF')
            self.assertEqual(data[8:12], b'WEBP')

    def test_search_favicon_is_a_crawlable_cube_bitmap(self):
        # Google Search's favicon formats exclude SVG. Every page supplies
        # the same stable PNG URL, and the conventional ICO fallback exists.
        for key, page in self.pages.items():
            with self.subTest(page=key):
                self.assertEqual(len(page.favicons), 1)
                icon, = page.favicons
                self.assertEqual(icon['href'], '/assets/favicon.png')
                self.assertEqual(icon['type'], 'image/png')
                self.assertEqual(icon['sizes'], '256x256')
        data = (WEB / 'assets/favicon.png').read_bytes()
        self.assertEqual(data[:8], b'\x89PNG\r\n\x1a\n')
        self.assertEqual(struct.unpack('>II', data[16:24]), (256, 256))
        self.assertEqual(data, (ROOT / 'assets/icon_256.png').read_bytes())
        fallback = (WEB / 'favicon.ico').read_bytes()
        self.assertEqual(fallback[:4], b'\x00\x00\x01\x00')
        self.assertEqual(fallback, (ROOT / 'assets/icon.ico').read_bytes())
        self.assertNotIn('Disallow: /assets', (WEB / 'robots.txt').read_text())

    def test_product_data_matches_visible_product(self):
        page = self.pages['index']
        self.assertIn('Cubeon', page.headings[0])
        self.assertIn('Launcher', page.headings[0])
        self.assertIn('Cubeon Launcher', page.title)
        self.assertIn('Minecraft Launcher', self.pages['download'].title)
        schema, = [json.loads(value) for value in page.schemas]
        self.assertEqual(schema['@context'], 'https://schema.org')
        graph = {entry['@type']: entry for entry in schema['@graph']}
        self.assertEqual(graph['WebSite']['url'], page.canonicals[0])
        self.assertEqual(graph['WebSite']['name'], 'Cubeon Launcher')
        self.assertIn('Cubeon', graph['WebSite']['alternateName'])
        self.assertEqual(graph['Organization']['name'], 'Cubeon Launcher')
        self.assertEqual(graph['Organization']['url'], page.canonicals[0])
        self.assertEqual(graph['WebPage']['mainEntity'], {'@id': graph['SoftwareApplication']['@id']})
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

    def test_domain_migration_preserves_paths_and_identity(self):
        for config in [ROOT / 'vercel.json', WEB / 'vercel.json']:
            rules = json.loads(config.read_text())['redirects']
            hosts = {}
            for rule in rules:
                for condition in rule.get('has', []):
                    if condition['type'] == 'host':
                        hosts[condition['value']] = rule
            for host in ['ylet.online', 'cubeon.ylet.online']:
                with self.subTest(config=config, host=host):
                    self.assertEqual(hosts[host]['source'], '/:path*')
                    self.assertEqual(hosts[host]['destination'], ORIGIN + '/:path*')
                    self.assertTrue(hosts[host]['permanent'])
            self.assertNotIn('www.ylet.online', hosts, 'Canonical host must not redirect to itself')
        for key in self.pages:
            source = (WEB / f'{key}.html').read_text()
            with self.subTest(page=key):
                self.assertNotIn('https://cubeon.ylet.online', source)
                self.assertNotRegex(source, r'>Ylet<|operated by Ylet|Ylet.*product')

    def test_official_product_identity_is_connected_across_pages(self):
        graphs = {}
        for key in ('index', 'about'):
            page = self.pages[key]
            schema, = [json.loads(value) for value in page.schemas]
            graphs[key] = {entry['@type']: entry for entry in schema['@graph']}
        home, about = graphs['index'], graphs['about']
        self.assertEqual(home['SoftwareApplication'], about['SoftwareApplication'])
        self.assertEqual(home['SoftwareApplication']['sameAs'], 'https://github.com/Shadow-457/Cubeon')
        self.assertEqual(about['AboutPage']['mainEntity'], {'@id': home['SoftwareApplication']['@id']})
        self.assertEqual(about['AboutPage']['url'], self.pages['about'].canonicals[0])
        self.assertEqual(home['SoftwareSourceCode']['targetProduct'], home['WebPage']['mainEntity'])
        self.assertEqual(home['SoftwareSourceCode']['codeRepository'], home['SoftwareApplication']['sameAs'])
        self.assertIn('LICENSE', home['SoftwareApplication']['license'])
        for page in ('index', 'docs'):
            self.assertIn('about.html', self.pages[page].links)
        for link in ('https://www.ylet.online/', 'https://github.com/Shadow-457/Cubeon',
                     'https://github.com/Shadow-457/Cubeon/releases/latest'):
            self.assertIn(link, self.pages['about'].links)

    def test_search_crawlers_can_read_pages_but_not_private_api(self):
        policy = RobotFileParser()
        policy.parse((WEB / 'robots.txt').read_text().splitlines())
        for crawler in ('Googlebot', 'bingbot', 'OAI-SearchBot', 'ChatGPT-User'):
            for page in ('/', '/about', '/download', '/assets/favicon.png'):
                self.assertTrue(policy.can_fetch(crawler, ORIGIN + page), (crawler, page))
            self.assertFalse(policy.can_fetch(crawler, ORIGIN + '/api/doctor'))


    def test_analytics_is_disclosed_and_wired(self):
        """Every content page loads the counter; the policy pages explain it.

        Status pages (403/404/...) are numeric and served during outages, so
        they are not instrumented. Adding a page without the snippet would make
        its traffic invisible; dropping the disclosure would make the privacy
        page untrue - both are regressions worth failing on.
        """
        snippet = '/_vercel/insights/script.js'
        for key in self.pages:
            if key.isdigit():
                continue
            with self.subTest(page=key):
                source = (WEB / f'{key}.html').read_text()
                self.assertEqual(source.count(snippet), 1)
                self.assertIn('window.vaq', source)
        for policy in ('privacy', 'cookies'):
            text = (WEB / f'{policy}.html').read_text()
            with self.subTest(policy=policy):
                self.assertIn('Vercel Web Analytics', text)
                self.assertIn('24 hours', text)


if __name__ == '__main__':
    unittest.main()
