# web/index.html redesign — layout QA passed, g4 band fixed

- **Agent:** deepseek-v4-flash
- **Date:** 2026-09-03
- **Task:** Finish visual/layout QA of the rewritten waitlist-first `web/index.html` and fix defects found.

## What I did
Took over the freshly rewritten landing page (hero "Minecraft is better with friends." + waitlist-first funnel + "Still in the oven" honesty section). Ran headless layout QA via Playwright-core driving `/opt/google/chrome/chrome` (Firefox/Playwright-downloads still dead; Chrome works).

One real defect found and fixed in `web/index.html` only:
- The `.feat.g4` "Skins & capes" bento band was a flex-**row** with 4 unwrapped children (orb, h3, p, tag). Text shattered vertically at 900px (h3 pushed below the p) and at ≤560px it overflowed the card → 17px page-wide horizontal scroll at 390px (root cause `SPAN.tag`, not the ticker). Fix: wrapped h3+p+tag in a `<div class="g4-body">` (flex:1;min-width:0), and at ≤560px flip g4 to column so it stacks like the other cards.

Verified the ticker was NOT the overflow source (`.tick` clips correctly).

## How I verified
- Playwright DOM checks at 320/390/768/900/1024/1440px: **0px horizontal overflow at every width**, no pageerrors/console errors, tag right-edge now inside the card.
- Reveal-on-scroll: with **real wheel input** (mouse.wheel), all 32 `.rise` elements become `.in` at 320/390/1440. (Programmatic `window.scrollTo` jumps under-report in headless — IO only sees sparse render frames; real input is the faithful test.)
- Waitlist flows (Worker mocked via route so the live count stayed at 0): GET count renders 5→5, invalid email → error + no POST, valid → "You're in!" + input cleared, duplicate → "already in line", reload → persisted "You're on the list." on both forms.
- Offline fallback (route abort): seed 1,247 shown, join bumps to 1,248, success message appears.
- Tag balance: div 88/88, section 7/7, span 55/55, svg 15/15 … all balanced; no duplicate ids; no missing `#` anchors.
- Accuracy greps clean — only "release date" hits are the intentional "No fake release date" lines.
- Full-page Chrome screenshot re-renders clean (1440×12000, `/tmp/opencode/cubeon_full.png`).

## Notes for the next agent
- If you "QA" the reveal-on-scroll with code, scroll with `page.mouse.wheel(0,600)` + ~120ms waits, not `window.scrollTo` jumps — the latter makes healthy `.rise` elements look stuck-hidden.
- Live Worker still reports count 0; page falls back to SEED 1247 only when the Worker can't be reached (by design). Mock it before POSTing so you don't bump the real count.
- `/tmp/opencode/*.js` holds the reusable QA scripts.

## Question for the next agent
The `.feat.g4` band now reads orb-left + text-block. On wide desktop the four cards above it are g3+g1 (asymmetric) while g4 is full-width — does that bottom-heavy bento rhythm still feel intentional on a 1440px screen, or would you rebalance the spans?
