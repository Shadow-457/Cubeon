# 2026-09-12 — Mod version conflicts (`breaks`) + Sodium/Iris fix

## The report
Launching 1.21.11-fabric warned:
`Mod 'Sodium' 0.8.14+mc1.21.11 is incompatible with version 1.10.7 or
earlier of mod 'Iris' (iris), yet a conflicting version is present:
1.10.7+mc1.21.11`. The doctor handled duplicates / missing deps /
wrong-loader, but not conflicts.

## Why it needed a new mechanism
Fabric's `breaks`/`conflicts` rules live in each jar's own
`fabric.mod.json`. I confirmed against the Modrinth API that version
`dependencies` only list required/optional/embedded/incompatible
PROJECTS — never version ranges — so the API cannot see this. The jar is
the only source of truth.

## What I built (`cubeon/mods.py`)
- `read_mod_metadata(jar_path)` — unzips `fabric.mod.json` /
  `quilt.mod.json` locally (offline, no network) and returns
  `{id, version, name, depends, breaks}`. Returns None for unreadable /
  non-Fabric jars, never raises.
- `version_satisfies(version, predicate)` + `_cmp_versions` /
  `_match_wildcard` / `_satisfies_range` / `_satisfies_term` — Fabric/
  Maven ranges: `<=1.10.7`, `0.8.x`, `[1.0,2.0)`, `*`, `||`, whitespace
  AND.
- `mod_doctor` check 4: builds an id→installed-version map from the local
  jars and reports `kind="conflict"` when a jar's `breaks` matches an
  installed mod. Detection is local; resolution needs network.
- `_resolve_mod_conflict`: (1) update the TARGET if a compatible build
  escapes the predicate; else (2) replace the DECLARER with the newest
  compatible build (stable before beta) whose own `breaks` no longer
  matches. Remote candidates are inspected with a temp download
  (`_read_remote_mod_metadata`, discarded).
- `get_mod_versions(..., allow_network=False)` reads only the cached list
  (added for offline callers).
- `_report`/status now use the mod's declared `name` ("Sodium", "Iris"),
  not the filename.

## The actual fix
For 1.21.11, the newest Iris is **1.10.7**, which Sodium 0.8.14 still
breaks (`breaks.iris <=1.10.7`) — so updating Iris cannot help. Sodium
0.8.12 declares `breaks.iris <=1.10.6`, so the resolver downgrades
Sodium. Verified end-to-end on the real profile: 0.8.14 deleted, 0.8.12
installed, conflict gone. On next launch the doctor repairs it on its
own.

## Gotcha found while testing
The candidate list must be filtered by `compatible` BEFORE any cap/limit
— the version list spans every Minecraft version, so newest-15 were all
mc26.x and the compatible 1.21.11 build was never reached. Regression
test seeds 30 incompatible newer builds to catch exactly that.

## Verification
- `tools/test_mod_detail.py` extended to **49/49** (predicate table,
  detection from synthetic jars, resolver picks the replacement, an
  unreadable jar is ignored, real profile cleanup for the UI section).
- Full sweep green: ui_smoke 105, perf_mods 15, mod_bridge 119,
  mod_compile clean, production 13, launch_indicator 11, capes 14,
  client_json 40, csl, friends 37, friends_service 213, fuzz 12,
  gallery 38, invites 127, milestones 50, mod_matrix 68,
  modpacks_cf_keyless 28, modpacks 51, mod_store 21, net 19,
  orphan_server 16, skins_net, versions_manifest 10,
  versions_profile_key 11.
- Docs updated: `agents/docs/module-map.md`,
  `agents/docs/guide-ui-modules.md`.

## Q for the next agent
The resolver downloads candidate jars (a few hundred KB–few MB each) to
read their `breaks` at launch. It is bounded to 12 candidates and
usually stops at the 2nd–3rd, but should it be limited to the "Fix
problems" action only, or is once-per-launch until resolved acceptable?
