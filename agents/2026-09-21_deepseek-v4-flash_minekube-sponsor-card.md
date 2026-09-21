# 2026-09-21 — Minekube badge becomes a credit card

User request: the Settings>Minekube icon should open a panel explaining
who Minekube is with a button to the website, instead of jumping straight
to the browser.

CORRECTION from the user (same day): the relationship is Cubeon backing
Minekube, NOT Minekube sponsoring Cubeon — because Minekube is open source
and gives EVERYONE (not just Cubeon) a free public address for a
home-hosted server. Copy updated accordingly; the button keeps the user's
wording: "Open their website".

## Change (main.py)
- `_open_minekube` (direct browser open) replaced by `_open_minekube_info`:
  a modal AlertDialog via the established `_open_dialog`/`_close_dialog`
  helpers — DNS icon + "Minekube Connect" / "Why Cubeon backs them", two
  plain paragraphs (open source; free public addresses for everyone's
  home-hosted server; Cubeon's server sharing runs on their network, so
  Cubeon backs them), then a "Open their website" FilledButton (closes
  dialog -> webbrowser.open connect.minekube.com) with the snackbar
  fallback when no browser opens, and a Close button.
- Badge tooltip now: "We back Minekube - open source, free addresses".
- Copy follows the plain-language rule (no "tunnel/IP/endpoint" jargon).

## Verification
- `python3 -m py_compile main.py` OK; FilledButton/RoundedRectangleBorder/
  OPEN_IN_NEW_ROUNDED all exist on this Flet build.
- `tools/test_ui_smoke.py` 148/148; `tools/test_mega_smoke.py` 16/16
  (hermetic HOME + PYTHONUSERBASE).
