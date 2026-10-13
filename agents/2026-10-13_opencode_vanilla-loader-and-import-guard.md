# 2026-10-13 — Vanilla can gain a loader; mods can't import to vanilla; playful error pages

## What the user asked for
1. "if i installed vanilla then i want to fabric or quilt there no option to
   install it it just gives error that you must have installed earlier."
2. "how the heck i can import to vannila" (mods silently landing in the
   useless vanilla profile).
3. "i need a 403 500 and common code pages for cubeon too and a bit playfull".

## 1. Vanilla gains a loader (`main.py`)
The Play-tab loader toggle used to dead-end: picking Fabric on an installed
vanilla version snapped the pill back with "Fabric isn't installed for this
version - pick it before installing." There was nothing to pick, so a vanilla
install could never gain Fabric. The install machinery already supported it
(`do_install_and_launch` skips the MC install when the version is present and
calls `install_mod_loader` for a missing loader) — only the UI blocked it.

- `state["pending_loader_install"] = {"version_id", "loader"}` is the arm.
  `on_loader_toggle_change` sets it when the chosen loader isn't on disk yet;
  Play switches to button mode `"install_loader"` (cyan, `INSTALL <LOADER> &
  PLAY`).
- `lock_loader_to_installed` respects a matching pending arm instead of
  snapping the switcher back to the on-disk truth — otherwise every version
  re-selection undid the pick.
- Cleared in exactly three places: version change (`on_version_selected`),
  after the loader install (`do_install_and_launch`, only when the armed
  version matches the launching one), and switching the toggle to
  vanilla/an-installed loader.
- `on_play_click` treats a matching pending arm as `needs_install` so the
  Java check still runs (the loader installer needs Java even though the base
  version is present).

## 2. Mods can never import to vanilla (`cubeon/importer.py`)
`_import_target()` can hand `loader="vanilla"` to `import_item`, which passed
`require_loader_and_version` ("vanilla" is truthy) and dropped the jar in the
`(mc, vanilla)` profile folder the game never reads — a silent no-op. Both
layers now refuse: `import_item` raises ValueError with an actionable message
("switch the loader on the Play tab … and press Play to add it"), and
`instance_compatibility` returns `(False, "vanilla can't load mods …")` so the
picker greys the row with the same guidance. Packs/worlds/modpacks still
import to vanilla fine.

## 3. Playful error pages (`web/`)
Added `403.html` (locked chest), `429.html` (rate-limit), `500.html` (server
exploded), `502.html` (bad gateway), `503.html` (overloaded), each a
self-contained `noindex` stub reusing the shared navbar/footer + the `.void`
layout from `404.html`, in the site's Minecraft-themed voice. No `vercel.json`
rewrites: `cleanUrls` already serves them at the extensionless path, and a
rewrite would recreate the `/x` → `/x.html` → `/x` redirect loop the
`_redirects` header warns about (2026-09-22 incident).

## Verification
- `tools/test_importer.py` 52/52 (+ vanilla-refusal + no-jar-in-profile),
  `tools/test_import_ui.py` 48/48 (+ vanilla picker row greyed, refusal path),
  `tools/test_ui_smoke.py` 182/182 (+ §4c: 5 checks driving the REAL
  `on_loader_toggle_change`/`lock_loader_to_installed` closures through
  vanilla→Fabric arm / no-snap / disarm), `tools/test_mega_smoke.py` 20/20,
  modpacks 70+47, launch_fixes 106, version_integrity 40, client_json 40,
  wedge_watchdog 9, faces 12, chat_optimistic 16, production 51, net 42,
  local_api_gate 5, web_download_count 73. All green.
- `tools/test_friends_service.py` has 4 failures (routing/presence/username),
  confirmed pre-existing: the same 4 fail on a clean worktree of `4fbeb97`.

## Q&A baton
- `tools/test_ui_smoke.py` §4c builds closures with `_ui_functions`, which
  `exec`s into a scope and RETURNS the probe's own `locals()`. A stub placed
  in that returned dict is invisible to nested calls (they resolve the
  enclosing scope). The only reliable place for a stub is the `prelude`, and
  the stubbed function must NOT also be in the extracted `names` list —
  otherwise the real def shadows it.
- The 4 `test_friends_service` failures are a real bug someone should look at;
  they are NOT from this session.
