# Site split into landing / download / docs

- **Agent:** cline (session 2026-09-20, follow-up to the waitlist removal)
- **Date:** 2026-09-20
- **Task:** Split the one-page site into three pages: `index.html` (landing),
  `download.html`, `docs.html`, with shared `site.css` + `site.js`.

## What I did

- **Extracted the design system** out of `web/index.html` into
  `web/assets/site.css` (all the CSS, +350 new lines of inner-page furniture:
  `.pagehead`, `.crumbs`, `.jump`, `.toc`, `.doc-grid`, `.prose`, `.cmd`,
  `.calnote`, `.tbl`, `.stepstrip`, `.chip`, `aria-current` nav marker) and
  `web/assets/site.js` (the two behaviour blocks, unchanged except for a
  header). Every block in `site.js` already early-returned when its elements
  are missing, so one file drives all three pages (the sky canvas + roster only
  exist on the landing page).
- **`index.html`** (340 lines) keeps the story: hero + download buttons, facts
  band, app/features bento, "how" steps, live roster, `#release` board, a new
  docs CTA band, final CTA.
- **`download.html`** (new, 162 lines) owns the binaries: page head with jump
  chips, the same three `.dl-card`s with the real `../dist/<file>` links and
  byte sizes, "which file?", the unsigned-build note, and a four-step "after you
  download" strip.
- **`docs.html`** (new, 257 lines) is the manual: sticky contents + stacked
  sections — install per platform (incl. FUSE fallback and the `CUBEON_INSTALL_DIR`
  override), first launch (username, identity key, Java picking), friends &
  worlds (Modrinth mods, hosting via Paper + Minekube Connect, offline-mode
  players), when-things-break table, the FAQ moved off the landing page (8
  entries, now including "Do I need Java installed?"), and a source-tree list.
- Docs copy is written against real code/doc facts, not vibes: `find_java` /
  `required_java_major` (Cubeon picks the *lowest* sufficient Java and ships no
  JRE), `~/.cubeon_launcher/auth_key.json` + `cubeon.log`, `packformat.repair_pack`
  widening declared formats, the "Fix problems" button (`run_doctor`), Paper +
  Connect with `allow-offline-mode-players: true`, and the real build scripts'
  output paths.
- **The repo is private** — anonymous `github.com/Shadow-457/Cubeon` and
  `/releases/latest` both return 404. The macOS card is therefore an honest
  "not public yet" card with no link (the old GitHub release link would have
  been dead for every visitor), and `docs.html#repo` lists paths as text.
- Fixed a real bug the extraction introduced: `@font-face` in `site.css` pointed
  at `assets/fonts/...`, which resolves to `web/assets/assets/fonts/...` and
  404'd the Minecraftia font on all three pages. It's `fonts/...` now.
- Fixed `.calnote b` → `.calnote > b` after seeing inline `<b>More info</b>`
  turned into `display:block` headings mid-sentence in the rendered docs.

## How I verified

- `node --check web/assets/site.js` OK; HTML tag balance checked on all three
  pages with a strict HTMLParser pass (no unclosed/stray tags).
- Served the repo root on `:8765` and loaded all three pages in headless
  Chromium: **zero** console errors and **zero** 404s in the server log (that's
  how the font bug surfaced — one 404 per page).
- A static pass over every `href` in all three pages: every internal link
  resolves to a real file and every `#fragment` exists as an `id` in its target
  page (cross-page links like `docs.html#faq`, `index.html#release` included).
- All six `../dist/*` links still answer **HTTP 200** with the byte sizes shown
  in the card text.
- OS-detect still works per page: landing stars both hero buttons, download page
  stars the Linux card, docs page has nothing to star.
- Screenshots reviewed at 1440px: download head + cards + after-strip, docs head
  + install + troubleshooting table, landing hero.

## Notes for the next agent

- The previous note (`2026-09-20_cline_landing-page-downloads.md`) says the site
  is "a single self-contained file (no build, inline CSS/JS)" — **superseded**
  by this entry: it's three pages sharing `assets/site.css` + `assets/site.js`.
- Sizes and file names in `download.html#files` are still hard-coded from the
  2026-09-20 build. Re-check on every rebuild.
- Serving: `python3 -m http.server 8000` from the repo root, then
  `/web/index.html`; or open the file straight off disk (`../dist` works either
  way).

## Question for the next agent

Still no test guards the site: a `tools/test_web_site.py` could (a) check every
`href`/fragment resolves, (b) assert each `../dist/<file>` exists and matches the
size printed in the link text, and (c) assert the three pages share one CSS/JS
pair. Cheap to write, and it would have caught the font 404 and any future
"forgot to update the size" rebuild. Worth it before the site is ever promoted?
