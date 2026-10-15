# 2026-10-15 — Crash message no longer claims a fix that never happened

## What the user asked for
"when the game crashes and cubeon says game crashed cubeon doctor fixed it run
it again but it isnt actually fixed thats confusing please fix"

## Root cause
The three-part message matched `main.py::_explain_exit()`'s Fabric branch
exactly:

> Crashed: this version's config was incomplete, so Fabric couldn't start.
> Cubeon repaired it. Press Play again.

It fired on ANY `KnotClient`/`KnotServer` `ClassNotFoundException`. But the
client.json repair it referred to (`_sanitize_client_json` +
`_restore_emptied_arguments`) runs in `build_launch_command`, i.e. BEFORE the
spawn of the very launch that crashed. So when the message appeared the repair
had already been attempted and failed, and the promise was simply untrue — the
user kept pressing Play on a broken install because Cubeon told them it was
fixed.

## Fix
Reworded the branch to be honest and actionable, and explained why in a comment:

> Crashed: Fabric couldn't start - this version's files look incomplete. If
> pressing Play again still crashes, reinstall this version from the Play tab.

No "repaired"/"fixed"/"doctor" wording. Kept the word "Fabric" (a test asserts
it) and stayed under the 180-char label cap.

## Verification
- `python3 tools/test_ui_smoke.py` → 196 passed, 0 failed. Added two checks in
  §4: the Fabric message contains no "repaired"/"fixed", and it names
  "reinstall". Confirmed they exercise the new wording.
- `python3 tools/test_launch_indicator.py` → 11/11.
- `python3 tools/test_launch_fixes.py` → 113/113.
- `python3 -m py_compile main.py tools/test_ui_smoke.py` OK.

## Note for the next agent
Scope was deliberately messaging-only: the launch path already attempts the
config repair every time, and the honest instruction for a still-broken install
is to reinstall the version. If you ever want Cubeon to *actually* repair the
KnotClient classpath case, it has to happen during launch (where the classpath
is built) and be *verified* before any UI text calls it fixed.
