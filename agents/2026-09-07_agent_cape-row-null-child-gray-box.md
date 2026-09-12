# Cape row null child -> gray error box (2026-09-07)

## What I did

User report: "white thing on the capes I upload" in the Profile > Cape tab
(screenshot: a large gray rectangle exactly where each uploaded cape's list
row should render, while the built-in Cubeon Cape row above it rendered fine).

Root cause: `ui/skin_tab.py`'s `refresh_capes_list()` built the uploaded
cape row's name column as `ft.Column([ft.Text(name), ft.Text(caption) if
c.get("animated") else None])`. For every NON-animated cape that put a
`None` inside a Flet controls list. Flet does not raise Python-side; it
serializes the null child, the Dart client fails to build that row, and
Flutter's release-mode ErrorWidget paints the gray box in its place
(silently - nothing reaches cubeon.log or the client stderr filter).

Fix: build the name column's controls list so only real controls go in
(concat a one-element list for the animated caption instead of `else None`).

Also added `tools/test_ui_smoke.py` section 5b: plants a real non-animated
cape in the sandboxed CAPES_DIR, builds the section, clicks the Cape tab,
then asserts (a) no `None` entry in ANY controls list in the built tree and
(b) the uploaded cape's name text exists. Verified the test FAILS with
`null entries at: ['Column[1]']` when the bug is reintroduced, and passes
with the fix.

## Verification

- `python3 tools/test_ui_smoke.py` - 48/48 (incl. new 5b checks)
- `python3 tools/test_capes.py` - 29/29
- Confirmed against the user's real data on this machine: their uploaded
  `cape_6a4329c2.png` is a valid 64x32 cape texture (renders fine); the gray
  box was purely the list row, not the cape or its preview.
- Durable fact added to agents/docs/module-map.md (Flet 0.86 hard rules).

## Baton

Carried over from the flexible-animated-capes note: in-game animation
verification is still todo-by-user. Nothing else open from this fix.
