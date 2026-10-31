#!/usr/bin/env python3
"""IndexNow must never announce preview, stale, redirected or blocked pages."""
import unittest
from unittest.mock import patch, MagicMock
import submit_website_indexnow as indexing


class IndexNowTests(unittest.TestCase):
    def setUp(self):
        self.payload = indexing.make_payload([indexing.ORIGIN + '/about'])
        self.responses = {
            self.payload['keyLocation']: (self.payload['key'].encode(), {}),
            indexing.ORIGIN + '/sitemap.xml': ((indexing.WEB / 'sitemap.xml').read_bytes(), {}),
            indexing.ORIGIN + '/robots.txt': ((indexing.WEB / 'robots.txt').read_bytes(), {}),
            indexing.ORIGIN + '/about': ((indexing.WEB / 'about.html').read_bytes(), {}),
        }

    def test_preview_uses_only_canonical_sitemap_pages(self):
        payload = indexing.make_payload()
        self.assertEqual(len(payload['urlList']), 19)
        self.assertEqual(payload['keyLocation'], indexing.ORIGIN + '/indexnow-key.txt')
        for url in ('https://preview.vercel.app/about', indexing.ORIGIN + '/api/doctor',
                    indexing.ORIGIN + '/about#report=private', indexing.ORIGIN + '/404',
                    indexing.ORIGIN + '/windowsdownload', indexing.ORIGIN + '/about?channel=beta'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                indexing.make_payload([url])

    def test_invalid_sitemaps_cannot_expand_submission_scope(self):
        for url in ('https://other.example/about', indexing.ORIGIN + '/../secrets',
                    indexing.ORIGIN + '/about?token=123', indexing.ORIGIN + '/about#private'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                indexing.sitemap_urls(f'<urlset><url><loc>{url}</loc></url></urlset>')

    def test_verified_batch_is_received_once(self):
        response = MagicMock()
        response.__enter__.return_value.status = 202
        with patch.object(indexing, 'fetch', side_effect=lambda url: self.responses[url]), \
                patch.object(indexing, 'urlopen', return_value=response) as network:
            self.assertEqual(indexing.submit(self.payload), 202)
        network.assert_called_once()
        request = network.call_args.args[0]
        self.assertEqual(request.full_url, indexing.ENDPOINT)
        self.assertEqual(request.get_method(), 'POST')

    def test_undeployed_or_blocked_content_prevents_notification(self):
        about = indexing.ORIGIN + '/about'
        failures = [
            (self.payload['keyLocation'], (b'wrong-key', {})),
            (indexing.ORIGIN + '/sitemap.xml', (b'<urlset><url><loc>https://www.ylet.online/</loc></url></urlset>', {})),
            (indexing.ORIGIN + '/robots.txt', (b'User-agent: bingbot\nDisallow: /\n', {})),
            (about, (self.responses[about][0], {'X-Robots-Tag': 'noindex'})),
            (about, (b'<meta name="robots" content="noindex">', {})),
            (about, (self.responses[about][0].replace(b'https://www.ylet.online/about"', b'https://other.example/about"'), {})),
            (about, (self.responses[about][0] + b'<!-- stale deployment -->', {})),
        ]
        for url, value in failures:
            responses = dict(self.responses)
            responses[url] = value
            with self.subTest(url=url, headers=value[1]), \
                    patch.object(indexing, 'fetch', side_effect=lambda target: responses[target]), \
                    patch.object(indexing, 'urlopen') as network, self.assertRaises(ValueError):
                indexing.submit(self.payload)
            network.assert_not_called()

    def test_redirected_production_page_fails_preflight(self):
        response = MagicMock()
        response.__enter__.return_value.status = 200
        response.__enter__.return_value.url = 'https://preview.vercel.app/about'
        with patch.object(indexing, 'urlopen', return_value=response), self.assertRaises(ValueError):
            indexing.fetch(indexing.ORIGIN + '/about')


if __name__ == '__main__':
    unittest.main()
