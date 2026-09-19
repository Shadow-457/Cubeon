# Regression guard for the content-install "Failed" bug (2026-09-13, deepseek-v4-flash)

**Context:** continuation of the network-resilience work. The user's real
symptom — installing a resourcepack/shader showed a bare "Failed" — was
`ui/mods_tab.py`'s `on_download` worker reading `deps_note` unbound on the
non-mod branch (`UnboundLocalError`, swallowed by the generic `except` and
misreported as a failed install). It was already fixed (`deps_note = ""` at
mods_tab.py:1529). This session made sure the harness can actually CATCH it.

## Why the old harness missed it
`_fuzz_common.install_safe_stubs` stubbed the browse readers
(`get_recommended_mods`/`search_mods`/`get_recommended_content`/`search_content`)
to return `[]`. With no hit there is no result row, so `build_browse_row()`'s
`on_download` worker never ran — the exact path with the bug was unreachable,
and the suite stayed green.

## What changed
- `tools/_fuzz_common.py`: browse readers now return one realistic hit; added
  shape-correct stubs for `get_mod_details`, `get_mod_versions`,
  `install_mod_with_dependencies`, `mod_doctor`. Also closed two real-network
  leaks the seeded rows exposed: `updater.check_for_updates`/
  `check_in_background` and `core.get_mod_icons` + `icons.prefetch`.
- `tools/test_fuzz.py`: scenario D mounts Mods → switches to Resource Packs →
  joins the browse worker → clicks Download; then asserts NO control shows
  "Failed". A statically-successful install that says "Failed" is the defect.
- `tools/test_mega_smoke.py`: `test_fuzz.py` added to `SUITES` so the gate
  runs it.
- `cubeon/mods.py`: the last bare `requests.get` metadata reads
  (`get_recommended_mods`, `search_mods`, `get_mod_icons`, `get_mod_download`,
  `get_mod_details`, `get_mod_versions`, `_required_deps_cached`) now go
  through `net.get_json`. `cubeon/server.py::_get_paper_download_url` too.

## Verification
- Guard proven to bite: reverting `deps_note = ""` makes
  `test_fuzz.py` fail "content install under stubbed success never reports
  Failed"; restoring it passes (13/13).
- Network-leak probe with `net._do_get` trapped: 0 leaks after the stubs.
- `tools/test_mega_smoke.py --suites` 27/0, fully offline (no
  `api.modrinth.com` in stderr).
- `tools/app_driver.py explore`: 822 actions, 352/352 handlers (100%), 0 errors,
  0 warnings.

## Note for the next agent
Do not "optimize" the browse stubs back to `[]`. Returning no hits silently
disables the whole content/mod install + detail-dialog surface, and the
generic `except` in those workers converts real defects into UI text the
detectors can't see. Stub install leaves to succeed and assert on the UI
status instead.
