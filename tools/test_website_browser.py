"""Optional offline Chromium review of the search-focused homepage/download copy."""
import os
from pathlib import Path
from urllib.parse import urlsplit
from playwright.sync_api import sync_playwright, expect

ROOT = Path(__file__).resolve().parents[1]


def main():
    captures = ROOT / 'archive/ui-captures'
    captures.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        executable = os.environ.get('CUBEON_TEST_CHROMIUM')
        browser = p.chromium.launch(headless=True, **({'executable_path': executable} if executable else {}))

        def route(request):
            url = request.request.url
            if url.startswith('https://cubeon-downloads.'):
                request.fulfill(json={'count': 0})
                return
            if not url.startswith('https://cubeon.test/'):
                request.abort()
                return
            path = urlsplit(url).path.lstrip('/') or 'index.html'
            if not Path(path).suffix:
                path += '.html'
            file = ROOT / 'web' / path
            request.fulfill(path=str(file)) if file.is_file() else request.fulfill(status=404, body='Not found')

        for width in [1440, 768, 390, 320]:
            page = browser.new_page(viewport={'width': width, 'height': 1000}, reduced_motion='reduce')
            errors = []
            page.on('pageerror', lambda error: errors.append(str(error)))
            page.route('**/*', route)
            for path in ['/?time=day', '/download']:
                page.goto('https://cubeon.test' + path)
                page.evaluate('document.fonts.ready')
                expect(page.locator('link[rel="icon"]')).to_have_attribute('href', '/assets/favicon.png')
                assert page.evaluate('''async () => {
                    const icon = new Image();
                    icon.src = document.querySelector('link[rel="icon"]').href;
                    await icon.decode();
                    return icon.naturalWidth === 256 && icon.naturalHeight === 256;
                }'''), (width, path, 'favicon failed to load')
                expect(page.locator('h1')).to_contain_text('Cubeon')
                page.screenshot(path=str(captures / ('seo-' + ('home' if path.startswith('/?') else 'download') + '-' + str(width) + '.png')), full_page=True)
                if page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'):
                    print(page.evaluate('''() => [...document.querySelectorAll('body *')].map(e=>({tag:e.tagName,cls:e.className,text:e.textContent.slice(0,80),right:e.getBoundingClientRect().right})).filter(e=>e.right>innerWidth+1).slice(0,15)'''))
                assert not page.evaluate('document.documentElement.scrollWidth > innerWidth + 1'), (width, path, 'horizontal overflow')
                assert page.locator('h1').evaluate('(e) => e.scrollWidth <= e.clientWidth + 1'), (width, path, 'heading clipped')
                if path.startswith('/?'):
                    expect(page.locator('.sign .lede')).to_contain_text('Minecraft Java Edition launcher')
                    expect(page.locator('link[rel="canonical"]')).to_have_attribute('href', 'https://www.ylet.online/')
                    expect(page.locator('.sign .pane.on .btn')).to_be_visible()
            assert not errors, errors
            page.close()
        page = browser.new_page(java_script_enabled=False)
        page.route('**/*', route)
        page.goto('https://cubeon.test/')
        expect(page.locator('h1')).to_contain_text('Cubeon')
        expect(page.locator('.sign .lede')).to_contain_text('Minecraft Java Edition launcher')
        expect(page.locator('a[href="mods.html"]').first).to_be_visible()
        print('PASS homepage/download at 1440, 768, 390 and 320px, no overflow/errors, crawlable content without JavaScript')
        browser.close()


if __name__ == '__main__':
    main()
