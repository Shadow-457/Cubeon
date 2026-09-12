# 2026-09-12 — Mod detail menu: usability pass

## Why
The menu worked but wasn't friendly: it rendered **every** release (Sodium has
247 rows), dumped the entire README as a wall of Markdown before the versions,
had no obvious primary action, showed one lonely gallery image, quoted dense
metadata (followers/licence/categories), and was cramped.

## What changed (`ui/mods_tab.py:open_mod_detail`)
- **Bigger:** 720px wide; scroll height adapts to `page.height`, capped 640.
- **One clear action at the top:** `_quick_action()` shows the newest
  compatible build with a big **"Install latest"** button, or "You're up to
  date — <ver> is installed", or "No build for your Minecraft version yet."
- **Description collapsed:** `_description_block()` shows a 3-line plain-text
  teaser (markdown stripped) with **"Read more"**; the heavy `ft.Markdown` is
  only built on first expand.
- **Versions grouped:** `_versions_section()` renders at most 8 compatible
  builds, then **"Show all N versions"** reveals the full list (incompatible
  builds tagged "other version") / "Show fewer versions".
- **Gallery** is now a sideways-scrolling strip of up to 8 screenshots.
- **Metadata** reduced to downloads (`_human_count`: 1.2M/34K), loader, and
  Minecraft versions.
- Shared `_install_button()` drives the quick action AND every row; on success
  it fires `quick_state["repaints"]` so the banner and rows update together.

## Verification
`tools/test_mod_detail.py` extended to **58/58** — asserts the installed-state
banner, "Install latest", collapsed description (no Markdown until expanded),
expansion reveals full text, initial 8-version cap, "Show all", and the
expanded count (20 match + 5 other). Sweep: ui_smoke 105, mod_matrix 68,
mod_store 21, modpacks 51, modpacks_cf_keyless 28, capes 14, gallery 38.
Docs updated: `module-map.md`, `guide-ui-modules.md`.

## Q for the next agent
The version cap is a hardcoded 8. If a profile wants bigger/smaller, make it a
module constant rather than editing two literals.
