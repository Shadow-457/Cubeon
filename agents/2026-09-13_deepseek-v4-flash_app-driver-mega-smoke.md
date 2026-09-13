# App driver + one-command mega smoke gate

- **Agent:** deepseek-v4-flash
- **Date:** 2026-09-13
- **Task:** give an AI a reusable way to *use* the app and find bugs, plus a
  single deep health check (syntax / type-contract / control flow / runtime).

## What I did

Added two tools under `tools/`, both built on the existing safe-stub layer so
they can never touch the real `~/.minecraft` / `~/.cubeon_launcher`:

- **`tools/app_driver.py`** - the "hands". Boots the real UI headless
  (`_sandbox_home.isolate()` + `_fuzz_common.install_safe_stubs`) into a
  `Driver` exposing `tabs()`, `open_tab()`, `click()`, `set_field()`,
  `submit()`, `type_fields()`, `fire_all()`, `none_children()`, `report()`.
  Subcommands: `explore`, `fuzz` (hostile corpus), `tabs`, `script <json>`
  (small step language: open_tab/click/type/submit/snapshot/wait), `shots`
  (delegates to the windowed `ux_capture.py` - Flet has no headless renderer).
  A `DriverPage` adds the Flet 0.86 `show_dialog`/`pop_dialog` stack that
  `_fuzz_common.FakePage` still lacks, so dialogs opened via `cubeon.dialogs`
  are reachable by the walker. Report is JSON with errors / None-child sites /
  warning counts / coverage of effectful handlers.
- **Full handler coverage** (added after reviewing a first cut that only drove
  clicks): `fire_all()` now also fires `on_hover` (data "true"/"false"),
  `on_focus`/`on_blur`, and `on_result` (cancelled-picker path), and
  `report()["handler_coverage"]` reports fired/seen + any missed names.
  `explore` = 325/325, `fuzz` = 4371/4371 (100%), 0 errors, 0 warnings.
  Unmounted-control `.update()` RuntimeErrors are filtered as headless noise.
- **`tools/test_mega_smoke.py`** - the one-command gate, cheapest layer first:
  1. syntax - `compile()` every shippable `.py` (112 found);
  2. imports - all 62 `cubeon`/`ui` modules import under a sandboxed HOME;
  3. type/contract - `launcher_core` exposes every `core.*` referenced from
     `main.py`+`ui/`, forbidden/removed Flet APIs absent, no None children in
     controls lists (AST), THEME key set + tab-builder signatures in parity,
     public type hints resolve;
  4. control flow - AST pass for unreachable code, duplicate top-level defs,
     bare `except:`, mutable default args (swallowed `except: pass` and
     `while True` are info-only - the repo has intentional ones);
  5. runtime - build the UI headless, open every nav tab, fire every handler,
     assert no errors / no None children, and a second build is idempotent.
  Flags: `--static` (skip runtime), `--suites` (also chain the repo's own
  harnesses), `--json`, `--out`.
- Updated `tools/ux_capture.py`'s stale `TAB_ORDER`/`KNOWN_KEYS` to the live
  nav keys, so its windowed tour now captures chat/plugins/stats too
  (9 tabs + 2 dialogs reachable headless; `--dry` passes).
- Documented both in `tools/README.md` and `agents/docs/module-map.md`.

## How I verified

- `python3 tools/test_mega_smoke.py --static` -> **12 passed, 0 failed**.
- `python3 tools/test_mega_smoke.py` -> **16 passed, 0 failed** (runtime layer
  included: every tab opens, no handler raises, no None children, rebuild ok).
- `python3 tools/app_driver.py explore` -> 10 tabs opened, 766 actions fired,
  handler coverage 325/325 (100%), 0 errors, 0 warnings, 0 None children;
  effectful coverage lists real destructive handlers reached (`delete_version`,
  `launch_game`, `delete_plugin`, ...).
- `python3 tools/app_driver.py fuzz` -> 26,557 invocations across the hostile
  corpus, handler coverage 4371/4371 (100%), still 0 errors.
- `python3 tools/app_driver.py shots --dry` -> PASS (9 tabs + 2 dialogs).
- Sanity-checked the detectors are not vacuously green: fed a planted
  None-child and a function with unreachable code / bare except / mutable
  default through `_flet_none_in_controls` / `_control_flow_findings`; both
  caught every planted case.

## Notes for the next agent

- Prefer extending `app_driver.Driver` over hand-rolling another FakePage
  harness. `every_control` only walks `page.controls + overlay + page.opened`,
  which is why `DriverPage` records `show_dialog` targets in `.opened`.
- On the real `ft.Page`, dialogs live in `page._dialogs.controls`, not
  `page.opened` - the driver is headless-only by design; real-window work
  goes through `ux_capture.py`.
- `test_mega_smoke --suites` is the heavier CI-style run; keep it opt-in so
  the default gate stays fast.
