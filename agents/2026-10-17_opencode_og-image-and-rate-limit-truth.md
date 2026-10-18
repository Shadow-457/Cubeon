# OG card for the site, and the rate limiter's real behaviour (measured)

- **Agent:** opencode (DeepSeek V4.1 Flash Free), session on 2026-10-17
- **Task (this note's main job):** the user asked for *"a og image of cubeon i
  added on on root dir like the one that is shown on website thumbnail"*. Two
  things came out of that: the site had **no `og:image` at all** (live and in
  `web/`), and the file the user added at the root is `Ylem.jpg` — a 1920×1080
  Cubeon splash (cube + pixel wordmark + "Minecraft is better with friends" +
  "© 2026 Cubeon. Built by Ylem."). Neither is committed.
- **Second job, carried over:** the live probe of the abuse gate I deployed
  earlier looked like it was not biting. It was. The *comments* were wrong, not
  the code. Corrected below and in `worker/*.js` + `agents/docs/module-map.md`.

## What I did

**1. Built the OG card (`web/assets/og.png`, 1200×630).** Not hand-drawn: the
source is an HTML card that reuses the site's own `web/assets/fonts/*`
(Minecraftia for the wordmark/headline, Inter for body) and the `site.css`
palette (`--paper #050505`, `--ink #DDF6D5`, `--grass #46BA34`, `--dirt #7A4A24`,
zero radius, hard offset shadow) — so it cannot drift away from the brand. It
shows the brand row + the site's own h1, the lede, three chips
(Free / Windows + Linux / No account), the domain, and the launcher window
(`web/assets/cubeon-play.png`) in the same frame treatment the hero uses
(3px `--ink` border, `8px 8px 0 var(--grass)` shadow). No screenshot of a
fabricated UI and no invented numbers.

**2. Wired it up.** `og:image` + `og:image:width/height/alt` +
`twitter:card=summary_large_image` inserted after `og:type` on all nine content
pages (`index`, `download`, `benchmarks`, `help`, `terms`, `refunds`, `privacy`,
`licenses`, `cookies`). The URL is **absolute**
(`https://cubeon.ylet.online/assets/og.png`) because crawlers do not resolve a
relative `og:image`. The 403/404/429/500/502/503 stubs were deliberately left
bare — they carry no `og:` block today.

**3. Corrected the rate-limit story with measurements, not assumptions.**

## The measurement that matters (one fixed IP, production, 2026-10-17)

| rapid POSTs to the waitlist | result |
| --- | --- |
| 8 | 8 × 422 — **zero** 429s |
| 25 | 25 × 422 — **zero** 429s |
| 120 | **95 × 422, then 25 × 429** |

So the Cloudflare Rate Limiting binding is the gate that works — and it works
**late**. Their docs call it "permissive, eventually consistent"; here it
converged only after ~100 requests. That also means the in-isolate fallback can
be **inert live**: requests for a cold Worker need not share an isolate, so the
per-isolate `Map` never accumulates. Earlier I had claimed the fallback was
what caught a burst. It is not, and the docblocks in all four workers
(`cubeon-waitlist.js` is the long one), `worker/README.md`'s prose and the
module map now say the measured thing instead.

Practical effect, which is still the one that matters: a flood gets about **190
writes' worth** of signups through before the binding holds that IP to ~5/min —
after which the account-wide 1k writes/day is hours away, not seconds. The real
fix for an unauthenticated write path is still **Turnstile**, not a per-IP cap.

## Verified

- `web/assets/og.png` is 1200×630 PNG, 319 KB; `/assets/` is definitely the live
  path for `web/assets/` (`/assets/icon.svg` and `/assets/site.css` → 200 on the
  real host). `/assets/og.png` is **404 until the site is deployed**.
- `tools/test_web_download_count.py`, `tools/test_release_pipeline.py`,
  `tools/test_release_version.py`, `tools/test_skins_net.py` all pass.
- `node worker/test-worker.mjs`, `test-waitlist.mjs`, `test-invites.mjs`,
  `test-downloads.mjs`, `test-friends-rooms.mjs` all pass (the four throttle
  tests now include a *passing* binding still being refused by the local gate —
  the regression guard for the `return null`-on-approval mistake).
- Re-checked one real `GET .../windowsdownload` after the throttle deploy:
  HTTP 200, `Content-Disposition: attachment; filename="Cubeon-Windows-x64-Setup.exe"`,
  `content-length: 119843357` (I aborted the body at 30s, so only ~39 MB came
  down). `/health` still answers.

## Traps worth remembering

- **Never render a card with `google-chrome --headless --screenshot
  --window-size=1200,630`.** The window frame eats ~70px of height, so the
  page's own background stops short of the bottom of the frame — while the PNG
  still comes out 2400×1260, so it *looks* like a 1200×630 capture. The symptom
  is a dead black band across the bottom with no grid and no accent bar. Use
  Playwright with an explicit `viewport` + `device_scale_factor=2`, then halve
  it: the 2× source keeps Minecraftia's pixel grid on exact pixels instead of
  blurring it.
- Background layers belong on `body` (multiple `background-image` layers), not
  as absolutely-positioned divs — the first attempt's `radial-gradient(...,
  transparent 46%)` div simply stopped painting, and the "1920×1080 splash"
  reference the user pointed at is **not** an OG ratio (1.78 vs 1.91), so
  cropping it to 1200×630 is not free.

## Not done / the user's call

- **Nothing committed or pushed.** The repo is private and pushing `main` mints
  an auto-release here; the site itself deploys from `web/` on push (Vercel), so
  the OG image is invisible to crawlers until then.
- `Ylem.jpg` (root, untracked) was **not** touched or moved — it looks like the
  user's/designer's splash, not a deliverable.
- Skins' 20/min binding is still a dashboard paste (its toml now mirrors it, so
  `wrangler deploy -c wrangler-skins.toml` would be equivalent).

## Question for the next agent

The card I shipped is the "product" composition (brand + headline + chips +
launcher screenshot). The user's phrasing — *"like the one that is shown on
website thumbnail"* — could equally mean the **text-only splash** look of
`Ylem.jpg` at 1200×630. If they ask for a change, the cheap move is to strip the
right-hand shot from the source card and re-render; the HTML source is the only
thing that needs editing. Which reading did they want, and should the OG card
keep showing the launcher at all?
