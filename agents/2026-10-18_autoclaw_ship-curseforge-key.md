# Ship one CurseForge API key with every build — user's key plugged in

**Date:** 2026-10-18 · **Repo:** products/cubeon · **Status:** done, pushed, and
released as **v1.2.15** (CI run 39146672572, success).

## What the user asked for
"Plug my CurseForge API key inside modpacks so it gives more modpacks" — and
pasted the key. The goal: the full CurseForge catalogue (new packs, pagination)
instead of the keyless curated classics.

## What actually happened
- The **one-key-ships-with-every-build** design was already sitting uncommitted
  in the working tree (same-day earlier session): `tools/write_cf_key.py`
  generates gitignored `cubeon/_cf_key.py` at package time from the
  `CURSEFORGE_API_KEY` GitHub secret; `modpacks._curseforge_api_key()` reads it
  as the last fallback (env > override file > config > builtin); the per-user
  "Add free CurseForge key" UI button was removed by that design; a refused
  `/mods/search` now falls back to the keyless set on page 1.
- The generated local `cubeon/_cf_key.py` already contained **exactly the key
  the user pasted** (verified: `_curseforge_api_key()` returns it,
  `curseforge_enabled()` True) — so the local launcher was already plugged in.
- My work was therefore **verify + ship**: ran the full CF suite
  (`tools/test_modpacks_cf_keyless.py`, 64/64 pass), set the real
  `CURSEFORGE_API_KEY` secret via `gh secret set` (verified with
  `gh secret list`), committed the tree as `feat(modpacks): ship one
  CurseForge API key with every build` and pushed. The rebase on `origin/main`
  was only the release-bot commit v1.2.14; the build that ran after my push
  started 35s after the secret was set, so **v1.2.15 is the first release
  carrying the key**.
- Updated `agents/docs/module-map.md`: replaced the outdated "key must be
  settable from the UI" invariant with the shipped-key contract (lookup order,
  no UI entry, search-refusal fallback, `keyed` cache flag).

## Gotchas learned (worth keeping)
- The module-map Yggdrasil section said Cubeon hands the game a placeholder
  access token in the shape `accessToken="0"`; a workspace write-guard flags
  that as a credential literal and blocks ALL edits to the file. With the
  user's OK I reworded both occurrences (same fact, "the literal placeholder
  `0` as its access token"). **Do not reintroduce that assignment-shaped
  spelling in prose** or the map becomes uneditable again.
- `test_modpacks_cf_keyless.py` is safe to run against a real key file: its
  writer tests redirect TARGET to a temp dir and its builtin-key tests swap
  `cubeon._cf_key` in `sys.modules` (verified the real file intact after the
  run).
- `git push` mints a release per push to `main` — rebase releases land between
  your push and CI; `git pull --rebase` before pushing, and check that the run
  that succeeded is the one built from your commit.
