# 2026-09-12 — Doctor hardening + proactive background repair

## Why
`mod_doctor` could still fail to fix, or falsely claim success, in edge cases,
and the only network-complete repair ran *after* install or via a button - never
before the user clicks Play on an existing profile.

## What changed
`cubeon/mods.py`
- `get_mod_download` now skips a newest release whose `files` list is empty and
  uses the next version that actually has a file. Before, `versions[0]` with no
  files returned `None`, and the doctor interpreted that as "no release for this
  loader/version" and **disabled a perfectly good mod**.
- Duplicate check: `fixed` is now computed **per loser** (its enabled file is
  really gone after `supersede_older_copies`), not group-level. A partial failure
  can no longer be reported as success.
- Conflict check: if `_resolve_mod_conflict` cannot find a compatible build on
  either side, the last resort disables the clashing **target** (`toggle_mod`,
  reversible) so the game still launches. A `disabled_targets` set means a
  second declarer breaking the same target reports it fixed without toggling it
  back on. Never deletes.
- Status messages added for duplicate removal / incompatible disable / last-resort
  disable, so a "Fix problems" run narrates what it touches.

`main.py`
- New `_proactive_mod_repair(version_id)`: when an (mc_version, loader) profile is
  selected in `on_version_selected`, run the FULL `check_online=True` doctor in a
  background thread - once per profile per session, silent unless it fixed
  something. This covers the dependency and loader/version passes the launch-time
  pass deliberately skips for speed, so existing profiles are clean before Play.
  The cached doctor calls mean repeat runs make no network requests.

## Verification
- `tools/test_mod_detail.py` extended to **66/66**: empty-files download guard;
  per-loser duplicate truth (supersede stubbed to a no-op => not fixed); conflict
  last-resort disables the target exactly once with a second declarer; proactive
  repair wiring in `main.py`. Also made 7b robust against a latent race (it
  waited on a shared refresh counter that a late repaint from the first dialog
  could satisfy - now it polls the second dialog's own text).
- Sweep green: ui_smoke 105, perf_mods 15, mod_bridge 119, mod_matrix 68,
  mod_compile clean, production 13, mod_store 21, modpacks 51,
  modpacks_cf_keyless 28, launch_indicator 11. `py_compile` OK.
- Docs: `module-map.md` mod_doctor bullet (four wirings, last-resort disable,
  66 checks), `guide-ui-modules.md` automatic-repair bullet.

## Q for the next agent
The proactive pass fires on **every** profile selection the first time in a
session. If a 300-mod profile ever makes the first selection feel heavy, gate it
behind "profile actually changed since last run" using the mod folder mtime
instead of the in-memory session set.
