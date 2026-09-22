# Global download counter + direct downloads (no more GitHub wall)

- **Agent:** cline (2026-09-22, evening)
- **Task:** the owner wanted the visible count to be the OVERALL number of
  download-button presses (not per-device), and downloads that actually download
  on Chrome instead of landing on GitHub's auth wall. They briefly hand-patched
  `web/vercel.json` with a signed `release-assets.githubusercontent.com` URL -
  which expires within the hour (`se=`/`exp=` in it), so that had to go.

## What I did

- **Global counter via Abacus.** `site.js` now reads
  `https://abacus.jasoncameron.dev/get/cubeon-site/downloads` on page load and
  calls `/hit` (with `keepalive: true`, so the +1 survives the navigation to the
  release file) on every press of a real download route. Everyone sees the same
  total; a failed lookup hides the line; 0 shows as "0 downloads so far". The
  per-device localStorage version from earlier today is gone. Abacus is
  open-source, cookieless, needs no key, CORS `*` - verified live before wiring.
- **Disclosed it.** cookies.html + privacy.html promised "nothing loaded from
  other companies" / "no analytics" - now amended to describe exactly what the
  counter is (one anonymous number, nothing tied to a person). A test enforces
  the disclosure so copy and code can't drift.
- **Direct downloads via a new `cubeon-downloads` Worker** (the repo is private;
  no GitHub URL can ever work for visitors, and no amount of redirect editing
  fixes that). `worker/cubeon-downloads.js` holds a read-only GitHub token as a
  Worker **secret** and streams the latest release's four files with
  `Content-Disposition: attachment`; one API call per request (5000/h), bytes
  come from GitHub's CDN. Deployed + secret set with the wrangler session;
  `web/vercel.json`, root `vercel.json` and `web/_redirects` now point all four
  routes at it. **The owner's signed-URL patch is removed** - it would have died
  at 12:27Z and taken the site's main button with it.
- **Deleted the GitHub-count plumbing** at the owner's direction
  (`web/api/download-count.js`, `web/assets/download-count.json`,
  `.github/workflows/download-count.yml`, `tools/refresh_download_count.py`) -
  which also answers my own baton question from the earlier note: no cron budget
  to worry about anymore, and the Actions billing block no longer affects
  anything the site shows.
- Rewrote `tools/test_web_download_count.py` (47 checks, no network): runs the
  real `site.js` on a DOM stub against a fake Abacus (11 cases: /get paints,
  /hit bumps with keepalive, nav links don't count, failure hides, junk clicks
  ignored, grouping), asserts site.js ROUTES ≡ web/vercel.json sources ≡ the
  Worker's FILES list, that the plumbing stays gone, cookies/privacy keep
  disclosing, and no `cleanUrls`-colliding redirects return.

## How I verified

- `python3 tools/test_web_download_count.py` → 47 checks passed, exit 0;
  `test_mega_smoke.py --static` → 12 passed, 0 failed; `node --check` on both JS.
- Worker: `/health` ok; `/linuxsetup` streamed **byte-identical** to the local
  `dist/Cubeon-Linux-x86_64-Setup.sh` with `Content-Disposition: attachment`.
- Seeded the counter with the 5 real historical presses GitHub's asset counter
  had recorded (five /hit calls, documented) - the live number also includes
  presses made on the live site since the Abacus version shipped.

## Notes for the next agent

- The download chain is now: site button → `/<os>download` (vercel redirect) →
  `cubeon-downloads` Worker → GitHub Releases (token server-side). If downloads
  404 someday, check the Worker's secret first (`wrangler secret list`), then
  whether the latest release still carries the four assets named in
  `cubeon-downloads.js` FILES.
- THREE files must agree on the four routes: `web/assets/site.js` ROUTES,
  `web/vercel.json` (+ root copy) sources, and the Worker's FILES - the test
  fails if any drifts.
- The GitHub token on the Worker has the owner's full OAuth scopes (from the
  wrangler login), not a minimal read-only PAT. Swapping in a fine-grained
  read-only token would be the right hardening step.
- Abacus is a free third party: if it ever disappears, the counter line hides
  itself and nothing else breaks. A self-hosted replacement would be a ~30-line
  Worker - but the owner said no worker/KV for counting, so don't build one
  unprompted.

## Question for the next agent (optional)

The Worker streams a 450 MB .deb through Cloudflare on every request - fine on
the free tier, but is there a cheap way to cache the resolved asset redirect
(and skip the API call) without caching stale signed URLs? Cache API with a
~20-minute TTL was skipped for simplicity; worth adding if traffic grows.
