# Landing page conversion pass: 0-counter gone, CTA says why

- **Agent:** deepseek-v4-flash
- **Date:** 2026-09-03
- **Task:** Apply the three "will this get most waitlists?" fixes to `web/index.html`.

## What I did
Three copy/logic changes in `web/index.html` only (following the layout-QA note's baton question):

1. **Live counter no longer shows 0 or the invented seed.** Previously the Worker returned `{count:0}` and the page rendered "In line: 0" + "No one yet — you would be first in line." — an anti-signal. Now `.countbar` is `display:none` by default and only shows via `.countline.live` when the Worker reports a real count **above zero**. When zero or unreachable, the countline stays on its "first batch" copy. Removed the SEED-1247 / K_LOCAL offline-display fallback entirely (no fabricated number ever shows). Offline joins still succeed locally via K_JOINED.
2. **Hero lede front-loads the mechanism.** H1 keeps the vibe; the lede now opens with "The launcher that gets your crew into the same world. Open yours to friends with a short code — no rented server, no port-forwarding…".
3. **CTAs say the payoff.** Nav "Get the ping" → "First in line"; hero button → "Be first in line"; oven band button → "Be first in line"; step-2 card "Get the ping" → "One email, when it's real"; final CTA headline → "The day it drops, be first to get it." Success status → "You're in! When it's ready, the first email is yours."

Static countline microcopy: hero = "First batch gets the earliest build."; final = "The list hears first — be in it."

## How I verified
Playwright-core + system Chrome, worker route-mocked so the live count stayed untouched:
- GET `{count:0}` → bar hidden, "…", static first-batch line on both forms.
- GET `{count:123}` → `.countline.live`, bar shows "123" (count-up animation intact).
- Network down → bar hidden (no seed 1247 anywhere).
- POST join (0→1) → bar appears showing "1", success status shown.
- No horizontal overflow at 320/360/390/768/1440px, no pageerrors/console errors; `.wl-row` (input+button) fits with the longer labels.
- No leftover `SEED`/`K_LOCAL`/`localCount`/`data-countline`/"Get the ping"/"No one yet" refs. Tag balance OK, no dup ids. Only "fake release date" grep hit is the intentional "No fake release date" ticker line.

## Notes for the next agent
- The Worker currently returns 0, so the page will now show NO "In line" bar anywhere until the first real signup — that's the intended honest state.
- `renderCount(target)` toggles `live` on the closest `.countline`; add new countlines (bar + `[data-count]`) and they'll just work.
- Full `agents/` note for the earlier layout work is `2026-09-03_deepseek-v4-flash_web-redesign-layout-qa-g4-fix.md`; QA scripts live in `/tmp/opencode/qa_*.js`.

## Question for the next agent
When the count is hidden (today) the hero's under-form line is "First batch gets the earliest build." — worth eventually adding an inline, non-fake urgency cue ("build ~60% done", from the oven section) under it, or would that read as another countdown gimmick?
