# Website search visibility

The canonical production site is **https://www.ylet.online**. Public pages
declare clean canonical URLs and matching Open Graph URLs in their HTML.
The homepage identifies Cubeon as a free, open-source Minecraft Java
Edition launcher for Windows, Linux and macOS. The homepage visibly identifies
**Cubeon Launcher** in its main heading, with Minecraft Java Edition explained
in the introduction, and links to installation, mods, modpacks, multiplayer
and troubleshooting guides.

`web/sitemap.xml` lists all 19 public HTML pages, using `/` for the homepage and
extensionless paths for other pages. It excludes error pages, API calls,
download redirects and report fragments. `web/robots.txt` allows crawling and
advertises the sitemap; API routes are excluded. Error pages carry `noindex`.
Both Vercel configurations enable clean URLs with no trailing slash.

Homepage JSON-LD names **Cubeon Launcher** consistently in WebSite, publisher,
WebPage and SoftwareApplication records,
using the real platforms, free price, download page and bundled screenshot.
Do not add fabricated ratings, reviews, update dates or unsupported features.
Structured data helps identify the product; it does not guarantee rich results.

## Official identity and AI search

`/about` is the official product facts page: spelling, game edition, platforms,
Apache 2.0 source license, local/offline profiles, downloads, repository and
support links. Homepage and AboutPage data share the same SoftwareApplication
ID and connect the official SoftwareSourceCode record to it. The homepage,
docs index and GitHub README link to the facts page. Cubeon and the similarly
named Cubion launcher are separate projects; do not put another product's URL
in Cubeon's `sameAs` data. Keep visible facts and schema in agreement.

The 2026-10-31 live check returned HTTP 200 for the homepage using an
OAI-SearchBot user agent, robots.txt, and the sitemap using a Bingbot user agent,
with no response-level noindex directive. These checks do not prove that real
crawler IP ranges are allowed by a hosting firewall. Search through the research
tool did not surface this official project for the tested name queries, and its
page-fetch tool could not retrieve the homepage; those observations are limited
to that tool and do not establish absence from every search index.

[Official OpenAI crawler guidance](https://developers.openai.com/api/docs/bots)
uses OAI-SearchBot for ChatGPT search. The existing wildcard robots rule already
allows it; permitting GPTBot training is independent of search inclusion.
If hosting adds bot protection, keep the published search crawler IP ranges
allowed. A spoofed user agent alone cannot verify that configuration. Access and
clear identity make discovery possible; they do not force ChatGPT to mention
Cubeon or add it to a model's training data.

[Google's AI search guidance](https://developers.google.com/search/docs/appearance/ai-features)
uses normal indexing, snippet eligibility, useful text, links and accurate
structured data. There is no required special AI file or AI schema. Keep the
facts page useful to visitors rather than creating thin keyword pages.

## Bing and IndexNow

Google Search Console is already verified by the owner. In
[Bing Webmaster Tools](https://www.bing.com/webmasters/), use **Import from Google
Search Console**, authorize the Google account, and select the verified property
covering `https://www.ylet.online/`. Check the imported sitemap or submit
`https://www.ylet.online/sitemap.xml`, then inspect `/`, `/about` and `/download`.
See [Bing's verification guide](https://www.bing.com/webmasters/help/add-and-verify-site-12184f8b).
This owner-account step cannot be performed with repository access alone.

`web/indexnow-key.txt` is the public verification file for
[IndexNow](https://www.indexnow.org/documentation). The submission tool reads
the production sitemap, excludes noncanonical/private/preview URLs, and checks
the live key, sitemap, crawler policy, page indexing directives and exact deployed
HTML before sending a single batch to the participating engines. Run it from a
checkout matching the deployed site. Pending unpublished HTML edits deliberately
fail the content check. The default command is an offline preview:

```bash
python3 tools/submit_website_indexnow.py
python3 tools/submit_website_indexnow.py https://www.ylet.online/ https://www.ylet.online/about https://www.ylet.online/docs --check-live
python3 tools/submit_website_indexnow.py https://www.ylet.online/ https://www.ylet.online/about https://www.ylet.online/docs --submit
```

After a deployment, use `--submit` without URLs to announce the whole sitemap
when every page in the checkout matches production. Do not repeatedly submit
unchanged pages. HTTP 200 acknowledges receipt; 202 means key validation is
pending. Neither response guarantees indexing or rankings. IndexNow is separate
from Google Search Console and ChatGPT's crawler.

## Visibility beyond the website

Use one consistent project name, **Cubeon Launcher**, and the same official
site and repository links on project profiles and genuine software listings.
The `/about` page is the reusable source of facts for those listings and for
reviewers. A concise listing description is:

> Cubeon Launcher is a free, Apache 2.0 open-source desktop launcher for
> Minecraft Java Edition on Windows, Linux and macOS. It manages game versions,
> compatible modded instances, mods, modpacks, skins, friends and local servers.
> It uses local/offline player profiles and does not provide Microsoft sign-in.
> Official website: https://www.ylet.online/ . Source and releases:
> https://github.com/Shadow-457/Cubeon .

Useful independent references include actual installation tutorials, gameplay
demonstrations, release coverage and reviews that link to the official project.
Prepare accurate submissions to relevant open-source directories and Minecraft
communities, following their rules. Public posts, directory submissions and
messages require authorization; none are created by the SEO tests or this tool.
Do not fabricate ratings, reviews or independent coverage.

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
associated with the docs page that visibly displays all of them. Ten public copies from
`archive/ui-captures/seo-images/` live in `web/assets/screenshots/`; the existing
Play PNG and in-game cosmetics WebP are reused. New PNGs have descriptive filenames
and embedded title/description metadata. `tools/prepare_seo_images.py` regenerates
the public copies with Pillow and masks account details, friend IDs and chat previews.
Original captures stay in the ignored archive.

All 12 images are visible at `/docs#docs-screenshots`, with descriptive alt text,
captions, links to the relevant guides and direct links to the full-size originals.
The gallery uses ordinary server-rendered HTML and works without JavaScript.
`tools/prepare_docs_image_previews.py` creates 900-pixel WebP previews from the
already-redacted public assets. Native lazy loading and explicit dimensions reduce
initial traffic and avoid layout shifts. The PNG/WebP originals remain unchanged
as the fallback images and full-size downloads.

Discovery uses the visible docs content and the sitemap, without hidden HTML,
keyword stuffing or crawler-specific responses. Images are publicly accessible
by direct URL: there is no "Google only" access mode. Sitemap submission supports
discovery, not guaranteed indexing or rankings. Google decides which images to index.
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
4. Use **URL inspection** on the homepage, `/about` and download page, run the live test,
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
python3 tools/test_website_indexnow.py
python3 tools/test_website_browser.py
```

The first check uses only the standard library and verifies crawl coverage,
canonical consistency, unique metadata and accurate product data. The optional
Playwright check intercepts all HTTP traffic and checks the homepage/download/about at
1440, 768, 390 and 320 pixels, plus crawlable content with JavaScript disabled.
Set `CUBEON_TEST_CHROMIUM` to an installed Chromium executable if needed.
Screenshots stay under `archive/ui-captures/`.
