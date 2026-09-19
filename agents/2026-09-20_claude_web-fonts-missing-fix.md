# 2026-09-20 — web fonts fix

**Problem:** `web/assets/site.css` declared `@font-face` for Fredoka and Nunito
pointing at `fonts/fredoka.woff2` / `fonts/nunito.woff2`, but those files did not
exist in `web/assets/fonts/` (only Inter.ttf and Minecraftia-Regular.ttf were
there). Browsers silently fell back to system-ui, so Fredoka/Nunito were never
rendered.

**Fix:** Downloaded the Google Fonts latin-subset *variable* woff2 files:
- `fredoka.woff2` (weight range 300–700, covers the CSS's `font-weight: 500 700`)
- `nunito.woff2` (weight range 200–1000, covers the CSS's `font-weight: 400 900`)

Verified with `file` (both valid WOFF2 v2 TrueType).

**Gotcha for next agent:** CSS only loads the *latin* subset; if a translated
locale is added, latin-ext/other subsets need extra unicode-range @font-face
rules. `Inter.ttf`/`Minecraftia-Regular.ttf` sit unused in the same dir.
