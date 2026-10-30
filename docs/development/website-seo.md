# Website search visibility

The canonical production site is **https://www.ylet.online**. Public pages
declare clean canonical URLs and matching Open Graph URLs in their HTML.
The homepage and download metadata identify Cubeon as a free Minecraft Java
Edition launcher for Windows and Linux. The homepage visibly identifies
**Cubeon Launcher** in its main heading, with Minecraft Java Edition explained
in the introduction, and links to installation, mods, modpacks, multiplayer
and troubleshooting guides.

`web/sitemap.xml` lists all 18 public HTML pages, using `/` for the homepage and
extensionless paths for other pages. It excludes error pages, API calls,
download redirects and report fragments. `web/robots.txt` allows crawling and
advertises the sitemap; API routes are excluded. Error pages carry `noindex`.
Both Vercel configurations enable clean URLs with no trailing slash.

Homepage JSON-LD names **Cubeon Launcher** consistently in WebSite, publisher,
WebPage and SoftwareApplication records,
using the real platforms, free price, download page and bundled screenshot.
Do not add fabricated ratings, reviews, update dates or unsupported features.
Structured data helps identify the product; it does not guarantee rich results.

## Domain migration and site name

The bare domain `https://ylet.online/` already redirects to `https://www.ylet.online/`
in hosting. Both Vercel configurations preserve that direction and permanently
redirect the old `cubeon.ylet.online` host to the same paths on www. Keep all
three domains attached to the same hosting project while old links migrate.
Do not add a www-to-apex rule: it would conflict with the existing redirect.
The launcher’s downloads, Doctor and Discord website links use the www origin.

Google chooses the displayed site name automatically. The homepage provides
`WebSite.name = "Cubeon Launcher"` with `Cubeon` and `Cubeon Minecraft Launcher`
as alternatives, matching Open Graph and visible branding. It carries no Ylet
publisher credit. Changing the domain alone cannot set the displayed name.
See [Google’s site-name guidance](https://developers.google.com/search/docs/appearance/site-names).

The search favicon is the existing Cubeon cube in a 256×256 PNG at
`/assets/favicon.png`; all pages declare that stable URL. `/favicon.ico` supplies
the conventional fallback. Regenerate both from the launcher icons with
`python3 tools/prepare_website_favicon.py`. The visible navbar still uses the SVG.
Google's [favicon guidance](https://developers.google.com/search/docs/appearance/favicon-in-search)
lists bitmap formats, so an SVG-only favicon does not supply a supported search
icon. The live site checked on 2026-10-31 already advertised the correct Cubeon
WebSite name but still supplied only the SVG and returned 404 for `/favicon.ico`.
Publish the bitmap files and HTML changes, then request a homepage recrawl in
Search Console. Google can retain an earlier icon or use the domain as a fallback
site name; neither a recrawl nor structured data guarantees an immediate change.

## Google Images

`web/sitemap.xml` includes 12 images using Google's image sitemap namespace,
associated with the existing product and feature pages. Ten public copies from
`archive/ui-captures/seo-images/` live in `web/assets/screenshots/`; the existing
Play PNG and in-game cosmetics WebP are reused. New PNGs have descriptive filenames
and embedded title/description metadata. `tools/prepare_seo_images.py` regenerates
the public copies with Pillow and masks account details, friend IDs and chat previews.
Original captures stay in the ignored archive.

The extra images are not rendered or downloaded by the visible pages. Discovery
uses the sitemap, without hidden HTML, keyword stuffing or crawler-specific responses.
Images are publicly accessible by direct URL: there is no "Google only" access mode.
Sitemap submission supports discovery, not guaranteed indexing or rankings. Google
can choose not to index images, especially ones not embedded in a visible page.
PNG metadata is descriptive asset information, not a promise that Google uses it.
After publishing, submit or resubmit the existing `/sitemap.xml` in Search Console.

## After publishing

1. Verify that the live homepage, `/download`, `/robots.txt` and `/sitemap.xml`
   return HTTP 200 on `www.ylet.online`. The deployed static output must
   contain the contents of `web/`, including the two crawl files.
2. Open [Google Search Console](https://search.google.com/search-console).
   Add the URL-prefix property `https://www.ylet.online/`, or a domain
   property for a domain you control. Complete Google's HTML-file or DNS
   verification using the exact value Google supplies. Verification needs the
   site owner's Google account and hosting/DNS access.
3. Under **Sitemaps**, submit `https://www.ylet.online/sitemap.xml`.
4. Use **URL inspection** on the homepage and download page, run the live test,
   and request indexing. Review Google's chosen canonical and any blocked URLs.
5. In the old subdomain property, use Change of Address when available after
   verifying the permanent redirects. Keep them for at least a year. The previous
   screenshot confirmed only the old homepage was indexed; inspect the www URL
   separately and check Google’s selected canonical after it recrawls.
6. Monitor indexing and Performance queries such as “Cubeon launcher” and
   “Cubeon Minecraft launcher”. Keep release information and helpful guides
   accurate, and link to the canonical site from the real project profiles.

Do not submit preview deployments for indexing. Keep preview environments
excluded from search through hosting settings and verify their `X-Robots-Tag`.
Search Console verification pages are static ownership files; they are excluded
from the sitemap and page instrumentation checks. Offline checks do not submit
URLs to Search Console or deploy the site. Google controls crawling and rankings;
these changes cannot promise first place or immediate indexing.

## Verification

```bash
python3 tools/test_website_seo.py
python3 tools/test_website_browser.py
```

The first check uses only the standard library and verifies crawl coverage,
canonical consistency, unique metadata and accurate product data. The optional
Playwright check intercepts all HTTP traffic and checks the homepage/download at
1440, 768, 390 and 320 pixels, plus crawlable content with JavaScript disabled.
Set `CUBEON_TEST_CHROMIUM` to an installed Chromium executable if needed.
Screenshots stay under `archive/ui-captures/`.
