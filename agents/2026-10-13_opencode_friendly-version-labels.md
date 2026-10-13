# 2026-10-13 — opencode: friendly version labels + scan junk-skip + site eyebrow

## What the user asked for
Screenshots of the version dropdown and the Import-to picker showing raw ids
(`fabric-loader-0.19.5-26.1.2`, `fgdg`, `nga`, `(incomplete)` entries) — "the
instances versions are completely cooked, it feels so complicated like a
separate vanilla then a fabric". Also: "remove this tag quickly from the web
— Free launcher · Windows & Linux". Earlier in the session: the scan listed
useless non-Minecraft files (random zips / library jars from Downloads).

Note: the user did NOT want the Import-to picker removed (a previous turn had
started toward that) — keep the picker, fix the LABELS.

## What changed
1. `cubeon/importer.py` — scan junk-skip:
   - `_read_mod_info` now returns `None` for a jar that declares no mod
     metadata (fabric.mod.json / quilt.mod.json / META-INF/mods.toml /
     META-INF/neoforge.mods.toml / mcmod.info). Library jars and corrupt
     files are skipped instead of listed with `loader=None`.
   - `_classify_archive` drops the "unrecognised zip = resource pack"
     fallback; unknown archives return `(None, None)`.
2. `cubeon/versions.py` — friendly labels at the source:
   - `get_installed_versions` pass 1 (mll strict scan) now sets
     `display_name = suggest_friendly_name(id, id)` instead of the raw id.
   - `suggest_friendly_name` routes the version number through
     `extract_mc_version`, so `fabric-loader-0.19.5-26.1.2` → `26.1.2
     (Fabric)` (was `0.19.5 (Fabric)` — the LOADER version, wrong).
   - The returned list is sorted newest-first, complete before incomplete,
     un-decodable custom ids last — vanilla + Fabric of one game version sit
     next to each other.
3. `main.py` — the ONLINE version list falls back to the installed entry's
   `display_name` for installed rows (was raw `v['id']`).
4. `web/index.html` — hero eyebrow "Free launcher · Windows & Linux" removed
   (it was also wrong on the download-count test's page? no — just the hero).
5. `tools/test_importer.py` — fixtures updated to the new contract:
   forge-mod.jar carries a real `META-INF/mods.toml`; new `plain.jar` (no
   metadata) and `weird.zip` (hello.txt only) must NOT be listed; counts
   3 mods/4 packs/11 total → 2 mods/3 packs/9 total; corrupt `broken.jar`
   skipped. 50 checks now.
6. `agents/docs/module-map.md` — durable facts: friendly-label contract
   (never show raw ids in any version list), updated Import scan contract
   (junk-skip), test counts, header note.

## Verified
- `tools/test_importer.py` 50/0, `tools/test_import_ui.py` 45/0,
  `tools/test_ui_smoke.py` 177/0, `tools/test_mega_smoke.py` 20/20,
  `tools/test_version_integrity.py` 40/0, `tools/test_launch_fixes.py` 106/0,
  `tools/test_client_json.py` 40/0, `tools/test_modpacks.py` 70/0,
  `tools/test_modpacks_cf_keyless.py` 47/0, `tools/test_wedge_watchdog.py` 9/0.
- Manual check of `suggest_friendly_name` on 9 id shapes (fabric/quilt/forge/
  neoforge/vanilla/custom) — all print the game version + loader tag.

## Baton for the next agent
- The live Vercel site still serves the OLD index.html — the web/ changes
  (v1.0.4 buttons, claims audit, now the eyebrow) are committed but NOT
  deployed. Ask the user before deploying.
- `ft.Icon .name` bug in main.py/ui/mods_tab.py still unfixed (user never
  answered).
