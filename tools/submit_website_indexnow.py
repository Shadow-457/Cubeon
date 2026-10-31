#!/usr/bin/env python3
"""Preview an IndexNow batch; --submit verifies production before notifying engines."""
import argparse
import hashlib
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / 'web'
ORIGIN = 'https://www.ylet.online'
ENDPOINT = 'https://api.indexnow.org/indexnow'
KEY_PATH = '/indexnow-key.txt'
LIMIT = 2 * 1024 * 1024


class CrawlPage(HTMLParser):
    def __init__(self, source):
        super().__init__()
        self.canonicals, self.robots = [], []
        self.feed(source)

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'link' and attrs.get('rel', '').lower() == 'canonical':
            self.canonicals.append(attrs.get('href'))
        if tag == 'meta' and attrs.get('name', '').lower() in ('robots', 'bingbot'):
            self.robots.append(attrs.get('content', '').lower())


def sitemap_urls(source):
    tree = ET.fromstring(source)
    urls = [item.text for item in tree.findall('./{*}url/{*}loc')]
    if not urls or len(urls) != len(set(urls)):
        raise ValueError('The sitemap must contain unique public URLs.')
    for url in urls:
        parsed = urlsplit(url)
        if (parsed.scheme + '://' + parsed.netloc != ORIGIN or parsed.query or parsed.fragment
                or not re.fullmatch(r'/|/[a-z][a-z0-9-]*', parsed.path)):
            raise ValueError('The sitemap contains a noncanonical URL: ' + str(url))
    return urls


def local_page(url):
    name = urlsplit(url).path.lstrip('/') or 'index'
    return WEB / (name + '.html')


def make_payload(selected=()):
    urls = sitemap_urls((WEB / 'sitemap.xml').read_bytes())
    requested = list(dict.fromkeys(selected)) or urls
    for url in requested:
        if url not in urls:
            raise ValueError('Only production sitemap URLs can be submitted: ' + url)
        source = local_page(url).read_text()
        page = CrawlPage(source)
        if page.canonicals != [url] or any(re.search(r'\b(noindex|none)\b', r) for r in page.robots):
            raise ValueError('Local page is not indexable with its canonical URL: ' + url)
    key = (WEB / KEY_PATH.lstrip('/')).read_text().strip()
    if not re.fullmatch(r'[A-Za-z0-9-]{8,128}', key):
        raise ValueError('Invalid IndexNow key.')
    return {'host': urlsplit(ORIGIN).netloc, 'key': key,
            'keyLocation': ORIGIN + KEY_PATH, 'urlList': requested}


def fetch(url):
    with urlopen(Request(url, headers={'User-Agent': 'Cubeon-IndexNow/1.0'}), timeout=20) as response:
        if response.status != 200 or response.url != url:
            raise ValueError('Production URL must return 200 without redirect: ' + url)
        data = response.read(LIMIT + 1)
        if len(data) > LIMIT:
            raise ValueError('Production response exceeded the size limit: ' + url)
        return data, response.headers


def verify_live(payload):
    key, _ = fetch(payload['keyLocation'])
    if key.decode('utf-8').strip() != payload['key']:
        raise ValueError('The production IndexNow key has not been deployed.')
    sitemap, _ = fetch(ORIGIN + '/sitemap.xml')
    if set(sitemap_urls(sitemap)) != set(sitemap_urls((WEB / 'sitemap.xml').read_bytes())):
        raise ValueError('The production sitemap differs from this checkout.')
    robots, _ = fetch(ORIGIN + '/robots.txt')
    policy = RobotFileParser()
    policy.parse(robots.decode('utf-8').splitlines())
    for url in payload['urlList']:
        for crawler in ('bingbot', 'Googlebot', 'OAI-SearchBot'):
            if not policy.can_fetch(crawler, url):
                raise ValueError(crawler + ' is blocked for ' + url)
        data, headers = fetch(url)
        if re.search(r'\b(noindex|none)\b', headers.get('X-Robots-Tag', '').lower()):
            raise ValueError('Production response is excluded from indexing: ' + url)
        page = CrawlPage(data.decode('utf-8'))
        if page.canonicals != [url] or any(re.search(r'\b(noindex|none)\b', r) for r in page.robots):
            raise ValueError('Production page has an indexing or canonical error: ' + url)
        if hashlib.sha256(data).digest() != hashlib.sha256(local_page(url).read_bytes()).digest():
            raise ValueError('Production content differs from this checkout: ' + url)


def submit(payload):
    verify_live(payload)
    request = Request(ENDPOINT, data=json.dumps(payload).encode('utf-8'),
                      headers={'Content-Type': 'application/json; charset=utf-8',
                               'User-Agent': 'Cubeon-IndexNow/1.0'}, method='POST')
    with urlopen(request, timeout=20) as response:
        if response.status not in (200, 202):
            raise ValueError('IndexNow returned HTTP ' + str(response.status))
        return response.status


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('urls', nargs='*', help='Canonical sitemap URLs; default: all pages')
    parser.add_argument('--check-live', action='store_true', help='Verify deployment without submitting')
    parser.add_argument('--submit', action='store_true', help='Verify deployment and send the batch')
    args = parser.parse_args()
    try:
        payload = make_payload(args.urls)
        if args.submit:
            status = submit(payload)
            print(f'IndexNow received {len(payload["urlList"])} URLs (HTTP {status}). '
                  'Receipt does not guarantee crawling, indexing or rankings.')
        elif args.check_live:
            verify_live(payload)
            print(f'PASS production key, sitemap and {len(payload["urlList"])} crawlable pages match.')
        else:
            print(json.dumps(payload, indent=2))
            print('Preview only. After publishing, use --submit to notify participating engines.', file=sys.stderr)
    except (ValueError, OSError, ET.ParseError, UnicodeError) as error:
        parser.exit(1, str(error) + '\n')


if __name__ == '__main__':
    main()
