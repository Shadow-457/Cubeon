# Make the website's download count actually appear

- **Agent:** cline (2026-09-22)
- **Task:** the site's "N release downloads" line existed but never rendered on the
  live site; give it a source that works with a private repo and no hosting secret.

## What I did

- Diagnosed the real reason first. The live site is **cubeon.vercel.app** and
  `GET /api/download-count` answers `404 {"error":"release_unavailable"}`: the repo
  is private, GitHub answers anonymous API requests with 404, and no `GITHUB_TOKEN`
  is set in Vercel. `site.js` hid the counter on failure (correct), so visitors saw
  nothing. The endpoint alone can never be the only source here.
- Then found why even a working source would not have shown on the landing page:
  **`web/index.html` never loaded `assets/site.js`**. It kept an inline copy of the
  old OS-detect + FAQ code from the single-file era, so the counter, the cookie
  note and the *mobile menu* were dead on the landing page while `download.html`
  and `help.html` worked. Moved the landing-only pane switching into `site.js`'s
  `markSystem` block, deleted the inline script, and added the missing
  `<script src="assets/site.js" defer>`. There is now one behaviour file, and a
  test fails if a page forgets the tag or keeps a second handler.
- Found and fixed a second live bug while testing the first: `/download`, `/help`
  and `/404` answered **ERR_TOO_MANY_REDIRECTS**, so the site's own nav was dead.
  `web/vercel.json` (and the root copy) redirected `/download` → `/download.html`
  while `cleanUrls: true` rewrote `/download.html` → `/download`. The page rules
  are gone from both `vercel.json`s and from `web/_redirects` (which now explains
  why); the legal pages already proved cleanUrls serves extensionless paths alone.
- Added the credential-free source: `tools/refresh_download_count.py` writes
  `web/assets/download-count.json` (total + per-asset + release + generated_at)
  from `releases/latest`, and `.github/workflows/download-count.yml` runs it every
  6 hours with the runner's own token and commits only when the numbers moved
  (a `generated_at`-only difference is a deliberate no-op, so quiet days cost zero
  commits, and a GITHUB_TOKEN push can't re-trigger `build.yml`).
- Generated the file for real: `v1.0.0`, per-asset 1/1/2/1, **total 5** — committed
  so the count shows on the next deploy without any dashboard work.
- `web/assets/site.js`: `/api/download-count` first (freshest; still worth setting
  a Vercel token one day), then `/assets/download-count.json`, with `cache:'no-cache'`
  so a fresh CI commit isn't hidden behind an edge copy. Still hidden if neither
  answers — never a made-up 0.
- **Fixed a real bug the new test found:** a `null` entry in GitHub's asset array
  threw inside the function, so the catch turned a page view into a `503`. The
  loop now skips non-object entries and accepts whole non-negative numbers only -
  the same rule as the Python side (`"many"`, `-4`, `true`, `2.5` → 0).
- New guard `tools/test_web_download_count.py` (registered in
  `tools/test_mega_smoke.py`'s SUITES, documented in `tools/README.md`): 18 Node
  cases against the function with a stubbed `fetch`, 8 cases that run the **real**
  `site.js` on a DOM stub (endpoint down ⇒ the committed file fills the line; live
  endpoint wins; singular/plural; nonsense total ⇒ fallback; nothing ⇒ still
  hidden), allow-list parity JS↔Python, the committed JSON's self-consistency, and
  the generator's arithmetic/no-op/failure paths. No network anywhere in it.

## How I verified

- `python3 tools/test_web_download_count.py` → **72 checks passed**, exit 0 (18 Node
  cases against the endpoint with a stubbed `fetch`, 8 cases running the real
  `site.js` on a DOM stub, page wiring, allow-list parity, generator paths).
- `python3 tools/test_mega_smoke.py --static` → 12 passed, 0 failed (new files pass
  syntax/imports/control-flow).
- `node --check` on both JS files; the workflow YAML parses; the generator run
  twice in a row prints "unchanged ... file left alone" on the second run.
- **Real browser, locally**: served `web/` on `:8972`, loaded `index.html` in
  headless Chrome - counter reads "5 release downloads" and is visible, only the
  Linux pane shows, clicking macOS switches to it, the FAQ opens on the first
  click, the cookie note is injected, zero page errors, zero 4xx (except the API,
  which is absent locally - that IS the fallback case).
- **Live**: `/assets/download-count.json` → 200 with the real numbers; the same
  browser run against `https://cubeon.vercel.app/` and `/download`.
- Live checks used to find the bugs: `curl cubeon.vercel.app/api/download-count`
  (404), `curl -I` following `/download` (307 → 308 → loop), `grep '<script'` on
  `index.html` (no site.js tag), and
  `gh api repos/Shadow-457/Cubeon/releases/latest` (the 5 downloads).

## Notes for the next agent

- The installer allow-list now lives in TWO places on purpose -
  `web/api/download-count.js` and `tools/refresh_download_count.py` - and the test
  fails if they drift. Add a new installer to both or the count is silently wrong.
- **GitHub Actions cannot run on this repo right now.** Every job (mine and
  `build.yml`, including runs from before I started) fails to *start* with
  "recent account payments have failed or your spending limit needs to be
  increased" - so the 6-hourly refresh will not fire until that is paid for or the
  repo goes public. The committed `download-count.json` (total 5, `v1.0.0`) is
  what the site shows today; refresh it by hand with
  `GH_TOKEN=$(gh auth token) python3 tools/refresh_download_count.py`.
- Fastest way to get the *fresh* path with no Actions at all: add a read-only PAT
  (Contents: read) as `GITHUB_TOKEN` in the Vercel project and redeploy -
  `/api/download-count` then answers and `site.js` prefers it automatically.
- The download routes in `vercel.json` still 404 for anonymous visitors because the
  repo is private - the counter is honest about downloads that really happened, but
  the world cannot download yet. Unrelated to this task, worth deciding on.
- I also corrected three stale site bullets in `agents/docs/module-map.md`: the
  manual is `help.html` (no `docs.html`), downloads are clean routes to release
  assets (no `../dist/<file>`), and the Vercel root is `web/`.

- Heads-up: an auto-committer in the editor committed my work in three chunks
  while I was still editing (commits literally named `web`) and pushed them, so
  `main` briefly held a test file that expected an uncommitted generator fix. I
  finished the change set in one commit; if you see `web` commits in the log, that
  is the editor, not a person.

## Question for the next agent (optional)

The scheduled job costs a private-repo Actions minute every 6 hours to move a
decoration (and today it cannot even start - see above). Once the billing block is
cleared, is that freshness worth the minutes, or would `release: published` plus a
weekly cron be plenty for a number this small?
