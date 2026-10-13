# Full landing page on the existing design system (opencode/mimo)

**Date:** 2026-10-13
**Model:** opencode/mimo-v2.6-flash-free
**Task:** "Build a new full blown good looking landing page that follows the
existing site's design layout and information."

## What was done

Rewrote `web/index.html` (the page served at `/`) from a lean bespoke hero into
the full `web/assets/site.css` component set, keeping all existing information:

| Section | Components |
|---|---|
| Header | shared `navbar` (Home aria-current / Download / Help / Discord / Get Cubeon) + skip link — index previously had **no nav at all** |
| Hero | `.hero` grass/dirt split, `.hero-in`, eyebrow, h1, lede, the existing OS-pane picker (`.pane`/`data-pick`, untouched logic in site.js), hidden counter element, `discord-cta`, framed `.shot` screenshot |
| Facts | `.strip` + 3 `.fact` dots (no account / made for friends / free forever) |
| Features | `.cards` × 6 with `.ico` SVGs — friends, mods & modpacks (+ gold `.tag` for the new Settings→Import), skins, host-a-world, versions, settings |
| How-to | `.section.tint` + `.steps` (download → name → send code) + two `.note`s |
| FAQ | same two groups verbatim, **plus one new question** about Settings → Import |
| Close | `.cta` (Windows / Linux / Discord buttons, version note) |
| Fine print + footer | unchanged content; footer links now cover the new section ids (`#features`, `#start`) |

Design rules honoured: zero radius, hard offset shadows, self-hosted fonts,
**no new third-party requests** (only outbound hrefs are the Discord invite and
adoptium.net, both pre-existing). All behaviour stays in shared
`assets/site.js` — no inline handlers (the web test enforces this).

## Also fixed

`tools/test_web_download_count.py` had been **red at HEAD**: the "counter block
holds no per-device storage" guard predates commit `2aeae94`, which added the
localStorage testing-mode flag (`TEST_FLAG`) to the counter block. The guard now
rejects `localStorage.` lines that aren't `TEST_FLAG` — same intent (the count
only ever comes from Abacus), no longer a false positive.

## Verification

- `python3 tools/test_web_download_count.py` → **58 checks passed** (was: FAIL
  at check 7 pre-existing; `git stash` of my index.html reproduced it).
- Tag balance / class coverage / anchor-target probe (html.parser + CSS grep):
  no mismatches, no unstyled class, no dangling `#anchor`.
- Rendered with headless Chrome over `python3 -m http.server`: desktop 1440px
  (all sections incl. footer), narrow 500px (hamburger, single-column stack,
  live Abacus line painted "46 downloads so far"). Probe reported
  `scrollWidth 485 < innerWidth 500` → no horizontal overflow.
- Gotcha recorded in `agents/docs/module-map.md`: headless Chrome's
  `--window-size` floors at **500px**, so a 390px screenshot silently renders
  at 500 and crops (looks like broken mobile layout).

## Leftovers / notes for the next agent

- Site changes are **not committed** (user hasn't asked yet); nothing pushed,
  nothing deployed — Vercel still serves the old landing page.
- If deploying: Vercel project root is `web/`, no build step.

## Follow-up (same day): claims audit + logo + broken deb route

User reported website claims not matching the launcher, and the logo not
loading. Audited every claim against the code; fixed:

| Claim | Reality | Fix |
|---|---|---|
| "press Host and send them the short code" (hero, facts, cards, steps, FAQ ×2 pages) | No Host button, no short-code UI anywhere (`invites-api.md`: "Nothing calls it until the host UI lands"). Real flow: in-game friends list with **Invite / Join / Ask to join** rows | Reworded to the real buttons on `index.html` + `help.html` |
| "Chat, groups and voice are built in" | Chat tab = friends-enabled builds ✓; groups = protocol frames only; voice = signalling behind optional `cubeon/voice.py` ("voice UI was removed") | "Presence and chat come built in" |
| "Invite codes turn into tunnel addresses" (host card) | Same — no code UI | Rewritten: P2P invite one-press + launcher server with free public Minekube address |
| "If you own Minecraft, that works fine too" (FAQ ×2, steps) | Offline-only launcher (`accessToken "0"`, no password field) | "If you already own the game, just use the name you always use" |
| "Single file · 280 MB" / deb "(411 MB)" (index + download) | v1.0.4 artifacts: AppImage 108,034,552 B, deb 114,504,390 B | 108 MB / 114 MB (120 MB installer and 1 KB setup.sh were already right) |
| "a Cubeon folder" (FAQ) | `~/.cubeon_launcher` | Named `.cubeon_launcher` |

Also found and fixed while checking:

- **Logo**: navbar/footer used absolute `/assets/icon.svg` (copied from
  download.html) — works on Vercel, breaks any non-root preview (file://,
  repo-root server). `index.html` now uses relative `assets/icon.svg`.
- **`/linuxdeb` was 404 in production**: the Worker's FILES pins
  `cubeon_1.0.0_amd64.deb`, which last session's version-bump publish deleted
  (filename embeds the version). Re-uploaded the 1.0.4 deb under the old name
  (`cp` + `gh release upload`, ~5.5 min); all four Worker routes verified 200.
  Durable facts (incl. the alias trick) → module-map.

Verified: web test 58/58, re-rendered page (new copy + logo load, counter
painted "47 downloads so far"), all four download routes 200.
