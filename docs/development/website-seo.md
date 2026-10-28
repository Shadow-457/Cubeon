# Website search visibility

The canonical production site is **https://cubeon.ylet.online**. Public pages
declare clean canonical URLs and matching Open Graph URLs in their HTML.
The homepage and download metadata identify Cubeon as a free Minecraft Java
Edition launcher for Windows and Linux. The homepage keeps its original
“Minecraft, but better.” headline; the visible introduction names the product
and links to installation, mods, modpacks, multiplayer and troubleshooting guides.

`web/sitemap.xml` lists all 18 public HTML pages, using `/` for the homepage and
extensionless paths for other pages. It excludes error pages, API calls,
download redirects and report fragments. `web/robots.txt` allows crawling and
advertises the sitemap; API routes are excluded. Error pages carry `noindex`.
Both Vercel configurations enable clean URLs with no trailing slash.

Homepage JSON-LD describes the WebSite, Ylet publisher and SoftwareApplication,
using the real platforms, free price, download page and bundled screenshot.
Do not add fabricated ratings, reviews, update dates or unsupported features.
Structured data helps identify the product; it does not guarantee rich results.

## After publishing

1. Verify that the live homepage, `/download`, `/robots.txt` and `/sitemap.xml`
   return HTTP 200 on `cubeon.ylet.online`. The deployed static output must
   contain the contents of `web/`, including the two crawl files.
2. Open [Google Search Console](https://search.google.com/search-console).
   Add the URL-prefix property `https://cubeon.ylet.online/`, or a domain
   property for a domain you control. Complete Google's HTML-file or DNS
   verification using the exact value Google supplies. Verification needs the
   site owner's Google account and hosting/DNS access.
3. Under **Sitemaps**, submit `https://cubeon.ylet.online/sitemap.xml`.
4. Use **URL inspection** on the homepage and download page, run the live test,
   and request indexing. Review Google's chosen canonical and any blocked URLs.
5. Monitor indexing and Performance queries such as “Cubeon launcher” and
   “Cubeon Minecraft launcher”. Keep release information and helpful guides
   accurate, and link to the canonical site from the real project profiles.

Do not submit preview deployments for indexing. Keep preview environments
excluded from search through hosting settings and verify their `X-Robots-Tag`.
No Search Console verification, submission or deployment was performed by the
offline checks. Google controls crawling and rankings; these changes cannot
promise first place or immediate indexing.

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
