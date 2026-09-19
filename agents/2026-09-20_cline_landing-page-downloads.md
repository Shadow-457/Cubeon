# Landing page: waitlist → download hub

- **Agent:** cline (session 2026-09-20)
- **Date:** 2026-09-20
- **Task:** Turn `web/index.html` from a waitlist page into a "Cubeon is out, here
  are the files" page, pointing at the binaries in `dist/`.

## What I did

Single-file rewrite of `web/index.html` (still no build step, inline CSS/JS):

- **Hero** now carries two real download buttons (Windows installer / Linux
  AppImage) instead of the email form, plus a line linking to the full list.
- **New `#download` section** (right under the facts band): three cards
  (Windows 10/11, Linux, macOS) with the *exact* files and byte sizes from
  `dist/` — `Cubeon-Windows-x64-Setup.exe` (120 MB),
  `Cubeon-Windows-x64-single.exe` (128 MB), `Cubeon-Windows-x64.zip` (128 MB),
  `Cubeon-x86_64.AppImage` (280 MB), `cubeon_1.0.0_amd64.deb` (411 MB),
  `Cubeon-Linux-x86_64-Setup.sh` (1 KB); macOS points at the GitHub release page
  since there is no Mac artifact in `dist/`. Two honesty notes below the cards:
  which file to pick (incl. `apt install ./cubeon_1.0.0_amd64.deb`) and the
  unsigned-build warnings (SmartScreen / Gatekeeper).
- **Copy** de-waitlisted everywhere: ticker, nav CTA ("Download"), hero eyebrow
  ("v1.0.0 is out"), grass fact (`v1.0.0` instead of "1 email"), the 3 "how"
  steps, the final CTA, the footer, `<title>`/meta/OG, and the "still in the
  oven" section, which is now an honest **release board** (`#release`): works
  today / still rough / what we won't do.
- **FAQ**: dropped "What do you do with my email?" → added "Which file should I
  download?" and "Why does my OS warn me about the download?".
- **JS**: deleted the whole waitlist block (endpoint, counter animation, form
  submit, `localStorage`), replaced with a ~12-line `markSystem()` that adds
  `.rec` to the button/card matching the visitor's OS (phones get none). The
  page is fully usable with JS off — every download is a plain `<a href>`.
- **CSS**: `.wl*`/`.countline`/`.countbar` replaced by `.dl-hero*`/`.dl-note`/
  `.dl-*`; `.oven*`/`.trays`/`.tray*` renamed to `.board*`/`.tiles`/`.tile*`
  (flame keyframes deleted). `.btn` keeps `display:inline-block` per the
  module-map invariant.
- Links are relative (`../dist/<file>`) on purpose: they work when the repo root
  is served (`python3 -m http.server 8000` → `/web/`) **and** when
  `web/index.html` is opened straight from disk. `dist/` is gitignored, so a
  public deploy has to repoint them at release assets — flagged in an HTML
  comment and in `agents/docs/module-map.md`.

## How I verified

- `node --check` on all three extracted `<script>` blocks: syntax OK; a headless
  Chromium run of the page reported **zero** console/page errors.
- Served the repo root on `:8765` and loaded `/web/`: the 6 `../dist/...` links
  all returned **HTTP 200** with content-length matching `ls -l dist/` exactly
  (119955405 / 127622924 / 127557780 / 279615992 / 411214660 / 1341 bytes).
- Same run asserted: 3 download cards, 7 FAQ entries, no `[data-wl]`/
  `[data-count]`/email input left, and on this Linux box `.rec` landed on the
  Linux card + both Linux hero buttons (mobile viewport too).
- Screenshots (desktop 1440 + mobile 390) of `#download`, `#release`, `#how`,
  the final CTA and the FAQ: layout, badges, button alignment and the ★ all
  render as intended.
- `grep` for `waitlist|wl-|countline|countbar|#join|oven|tray|flame` in the page:
  no leftovers.

## Notes for the next agent

- Sizes in `#download` are hard-coded from this build (2026-09-20). Rebuild =>
  re-check the numbers, they are the only "data" on the page.
- `worker/cubeon-waitlist.js` + `wrangler-waitlist.toml` are untouched and still
  deployable, but the site no longer calls the Worker — nothing emails anyone
  any more.

## Question for the next agent

`package.json`-free static HTML means the sizes drift silently after a rebuild —
worth a `tools/test_web_downloads.py` that parses the page's `../dist/` hrefs and
asserts each file exists and matches the size in the link text? That would have
caught nothing today, but it would catch the next rebuild that changes them.
