# 2026-09-20 — lazy browse paging, installed thumbnails, shader notice, full date

Four requests from the same session, all user-facing.

**Lazy page-by-page browse (Mods + Modpacks).** The tabs advertised ~20/10
pages but fetched every page up front. Now each Next/Prev fetches only that
page's `offset`; an already-fetched page renders from the cache in
`browse_state`. `offset` was added to every search/recommend cache key in
`cubeon/mods.py`, `cubeon/content.py`, `cubeon/modpacks.py`. A short page
clamps `total_pages` down (Modrinth over-reports counts for filtered
queries). The curated no-category mod list ignores `offset`, so it sets
`browse_state["paged"] = False` and slices client-side. Modpacks fetch
Modrinth + CurseForge in parallel per offset and merge with
`merge_modpack_hits`; keyless cfwidget returns `[]` for `offset > 0`.

**Installed thumbnails.** `download_content()` now takes
`icon_url`/`slug`/`title`, recorded via `content.remember_content_meta()` in
the `content_meta.json` sidecar under `CUBEON_HOME`; `list_content()`
re-attaches it and `delete_content()` forgets it. Modpacks persist
`icon_url` in `_modpack.json` through new `icon_url` kwargs on
`install_modpack_from_url` / `install_modpack_from_cf` -> `_install_from_zip`.
`build_installed_row` (packs) and the installed mods/packs row draw
`icons.src` / `_icon_image` when art exists, else the old quiet glyph.

**Shader notice.** `shader_requirement_installed()` scans installed mods'
display names for iris/optifine; `shader_notice.visible` is now false once
the requirement is present.

**Stats "Playing since".** `ui/stats_tab.py` now uses `%b %d, %Y` (full
date), not just month+year.

**Verified:** `py_compile` on all touched modules; `tools/test_modpacks.py`
66, `tools/test_content_instance.py` 21 (both gained icon/meta regression
checks), `tools/test_mod_detail.py` 81, `tools/test_modpacks_cf_keyless.py`
28, `tools/test_ui_smoke.py` 142, `tools/test_mega_smoke.py` 16, and
`tools/app_driver.py fuzz` -> 0 errors / 0 None-child sites (28k actions,
install_modpack_from_url hit 1088×, download_content 161×). Durable facts
added to `agents/docs/module-map.md`.
