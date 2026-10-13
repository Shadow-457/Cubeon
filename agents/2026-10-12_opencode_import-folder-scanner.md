# Settings → Import: scan any folder for Minecraft content, import in one click (opencode/mimo)

**Date:** 2026-10-12
**Model:** opencode/mimo-v2.6-flash-free
**Task:** "implement a thing in settings which checks for the whole folder the
user selects — scan for mods, resources, shaders, modpacks and worlds — make
sure it cleanly searches and does not crash, shows 'found XX mods', collapses to
see details, and the user can copy with 1 click and Cubeon handles everything."

## What was built

A new **Settings → Import** rail section (second entry in
`ui/settings_tab.py:SECTIONS`). Two new files plus small wires:

| File | Role |
|---|---|
| `cubeon/importer.py` (new) | All logic — Flet-free so it unit-tests with temp folders |
| `ui/import_section.py` (new) | The pane: scan button, summary, collapsible groups, per-item Import + copy-path |
| `cubeon/config.py` | Added `run_dir_picker(...)` — the `get_directory_path` sibling of `run_file_picker` |
| `launcher_core.py` | Re-exports `run_dir_picker` |
| `ui/settings_tab.py` | New `("import", ...)` section + accepts `import_pane` |
| `main.py` | Builds the pane, defines `_import_target()` from Play-tab state |

### The scan

`scan_folder(root)` walks the chosen folder and classifies, **by what is inside
each archive rather than by extension**:

- **mods** — `.jar`; loader read from `fabric.mod.json` / `quilt.mod.json`.
  Forge/NeoForge jars carry neither, so `loader=None` (still listed — the player
  may be on that loader).
- **resource packs** — `.zip` *or* a folder with `pack.mcmeta`, including the
  nested `MyPack/pack.mcmeta` shape.
- **shader packs** — `.zip`/folder with `.fsh/.vsh/.glsl` or a `shaders/` dir.
- **modpacks** — `.mrpack` / zip containing `modrinth.index.json` or CurseForge
  `manifest.json`.
- **worlds** — any folder with `level.dat` (recorded, then **not** descended
  into — a world's region files would drown the scan).

Robustness was the priority: prunes `libraries/`, `versions/`, `assets/`, hidden
dirs and `node_modules`; a realpath-set guards symlink loops; a file-count cap
stops pathological trees; and **it never raises** — a locked/corrupt file lands
in `result["errors"]` and the walk continues. An unrecognised `.zip` is surfaced
as a best-effort resource pack (the game ignores a bad pack, so nothing is
silently hidden).

### The import

`import_item(entry, mc_version, loader, version_id, ...)` reuses the installers
the Mods/Modpacks tabs already trust, so nothing is reinvented:

- mods → `mods.install_local_mod` → **per-profile** folder (not the staging
  `MINECRAFT_DIR/mods`, which is wiped every launch).
- packs → `content.install_local_content` with content_type
  **`"resourcepack"` / `"shader"`** (singular — not the plural category name).
  An extracted pack *folder* is zipped to a temp `.zip` first, because
  `install_local_content` only accepts a `.zip`.
- modpacks → `modpacks.install_modpack_from_file`.
- worlds → `shutil.copytree` into the shared `SAVES_DIR`, with a guard so a
  world already under `saves/` is never duplicated onto itself.

The **target** is whatever the player picked on the Play tab
(`main.py:_import_target()` → `(extract_mc_version(...), state["mod_loader"],
version_id)`). No version selected ⇒ every import refuses with *"Pick a game
version on the Play tab first."* rather than landing in the throwaway
`unknown-vanilla` profile.

All scans and imports run on daemon threads; UI repaints go through
`cubeon.thread_safe_ui.refresh`.

## A real bug found along the way (not fixed — flagged)

`ft.Icon` swaps its glyph via **`.icon`**, never `.name`. Verified on both the
pinned **0.86.5** and current **1.0.3**: the glyph lives in `_values["icon"]`,
and assigning `.name` just sets an unrelated instance attribute, so the rendered
icon never changes. The codebase uses the broken pattern in at least two places:

- `main.py` (~:2438) — `play_button_icon.name = ...` (the play/install button
  icon state swaps are silently no-ops).
- `ui/mods_tab.py` (:1452) — `icon.name = ft.Icons.CHECK_ROUNDED`.

The Import section's expand/collapse chevron correctly uses `chevron.icon = ...`.
I did **not** touch main/mods_tab (out of scope and not visually verifiable in
this sandbox) — recorded in `agents/docs/module-map.md` so the next agent can
repair it (`.name` → `.icon`) if the user wants.

## How it was verified

Two new test files, plus the existing suites re-run:

- `tools/test_importer.py` — **32/0**. Pure scan/import logic against a temp
  fixture: classification of all five types, loader detection, `libraries/` and
  hidden-dir pruning, corrupt-file resilience, the empty/missing-folder paths,
  and a real import of a mod / pack / extracted-folder pack / shader / world
  into a **sandboxed `CUBEON_GAME_DIR`** (so the test never touches the real
  game dir). Modpack install is dispatched-checked with a mock (it downloads
  every declared mod, so it is network-bound).
- `tools/test_import_ui.py` — **25/0**. Drives the Flet render path the smoke
  test never reaches: builds the pane, renders a real scan result, asserts the
  summary + five collapsible groups + one Import/copy button per item, **clicks
  a group header and asserts the chevron flips `.icon`**, clicks an Import
  button and asserts the jar lands in the profile folder, runs Import-all, and
  confirms the no-version refusal. Uses the pane's exposed hooks
  (`render_scan_result`, `import_item_ui`) to bypass the OS folder dialog.
- Full suite green: `test_ui_smoke` 176/0, `test_launch_fixes` 106/0,
  `test_production` 51/0, `test_content_instance` 21/0, `test_mod_matrix` 68/0,
  `test_client_json` 40/0, `test_seasonal` 106/0, `test_wedge_watchdog` 9/0,
  `test_mega_smoke --static` 16/0.

Note for whoever tests interactively: the folder dialog opens via
`run_dir_picker`, which on 0.86.5 awaits `get_directory_path` through
`page.run_task` (confirmed present). `page.set_clipboard` does **not** exist on
0.86.5, so the copy-path button falls back to the `Clipboard` service — the same
pattern `ui/chat_tab.py` already uses.

## Known limitations (deliberate, for a later pass)

- A **Forge/NeoForge** mod shows `loader unknown`; importing it into a Fabric
  profile is the player's call (Cubeon lists it and lets the import run rather
  than hiding it). `mod_doctor` still catches a mismatched jar at launch.
- Resource packs nested **two or more** folders deep inside a zip are not
  recognised as packs (the single-folder `MyPack/pack.mcmeta` case is).
- The scan's file-count default is 50 000 and depth 8 — enough for a real
  `.minecraft`, tunable via `scan_folder` kwargs.
