# 2026-09-20 — exact logo, launcher palette, new tagline

User request: (1) use the real logo instead of the inline SVG cube "effect",
(2) recolor the web to the launcher palette, (3) tagline → "Minecraft is
better with friends".

**Done:**
- Replaced the hand-drawn `<svg class="mark">` cube in ALL 9 html pages (nav +
  footer, 2 per page) with `<img class="mark" src="assets/icon.svg">` — the
  exact launcher logo, no stylized shading.
- `site.css` `:root` palette now mirrors `cubeon/theme.py` exactly:
  paper #050505 (BG), card #0B0D0A (SURFACE), ink/text #DDF6D5 (TEXT),
  text-soft #9DB394 (TEXT_DIM), grass #46BA34 (ACCENT), grass-dark #5FD24B
  (ACCENT_HI, also the hover greens), grass-soft #052400 (ACCENT_DEEP),
  grass-line #39422F (BORDER_HI), line #242B1E (BORDER), btn-line #04120A
  (ON_ACCENT), hint #68755F (TEXT_FAINT), gold #E6B23C (WARNING).
  Note/tip blocks mapped to INFO_DIM/WARNING tints. Dirt tokens kept (still
  on-theme, launcher has no dirt equivalent). Hardcoded hexes swept too.
- index.html h1 + <title> → "Minecraft is better with friends."

**Verified:** python http.server smoke test — all 5 key assets return 200;
grep sweep shows zero leftover old-palette hexes.

## Follow-up: full launcher-palette sweep (same session)

Swept every remaining hardcoded hex out of `site.css` + `404.html`. Every color
now traces to a token in `cubeon/theme.py`:
- #08150C (old ON_ACCENT) -> #04120A (ON_ACCENT): skip link, .btn, .nav-cta,
  .step .num, .dl-badge, .fact .dot
- footer #080C09 -> #050505 (BG); #8B978A/#B7C4AE/#C7D2C1 -> #9DB394 (TEXT_DIM) /
  #DDF6D5 (TEXT); #fff -> var(--ink); footer divider #22322A -> #242B1E (BORDER)
- 404 glitch checkerboard: magenta #F800F8 -> #4FB4C7 (INFO, diamond cyan);
  black -> #050505
- Only non-token colors left: dirt browns (#7A4A24/#3A2410/#1C1209) and the
  gold/info tint washes (#241B04/#5C4718/#0A1A1E/#274F58) — deliberate
  Minecraft-native tints built from the launcher's WARNING/INFO hues.

**Verified:** hex inventory grep across all html+css — every remaining value
maps to a launcher token (or its tint). Nothing from the old web palette left.
