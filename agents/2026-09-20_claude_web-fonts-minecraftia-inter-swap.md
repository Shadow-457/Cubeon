# 2026-09-20 — web font swap: Minecraftia + Inter (user request)

User asked to actually use `Inter.ttf` and `Minecraftia-Regular.ttf` instead of
the just-downloaded Fredoka/Nunito.

**Done:**
- `site.css`: `@font-face` now points at `fonts/Minecraftia-Regular.ttf` (declared
  `font-weight: 400 700` — the range trick suppresses faux-bold synthesis on the
  pixel outlines) and `fonts/Inter.ttf` (variable, `100 900`). All `font-family`
  stacks swapped: display text (headings, brand, btn, badges, FAQ, footer) =
  `'Minecraftia','Inter'`; body = `'Inter'`. `404.html` inline styles updated too.
- Deleted now-unused `fredoka.woff2` / `nunito.woff2`.
- `licenses.html` fonts section updated: Inter = SIL OFL 1.1 (Rasmus Andersson);
  Minecraftia 2.0 = CC BY-SA (Andrew Tyler) — verified from the TTFs' name
  tables (nameID 13/14), NOT from memory.

**Gotchas:** Minecraftia is a pixel font designed on an 8px grid — crispest at
multiples of 8px if sizes ever get retuned. It has no true italic or other
weights; anything non-400 relies on the weight-range @font-face declaration.
Fonts dir now contains ONLY the two fonts the site actually loads.
