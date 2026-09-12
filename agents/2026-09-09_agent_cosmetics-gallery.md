# 2026-09-09 — Cosmetics gallery (SUPERSEDED 2026-09-10 → real-player gallery)

> **Outdated.** This note described the procedural, self-drawn gallery. On
> 2026-09-10 it was replaced by a REAL-player gallery (cubeon/remotes.py +
> reworked cubeon/gallery.py). See `agents/2026-09-10_agent_real-gallery.md`
> and module-map **Follow-up 21**. History kept for context only.

## What I did
The user asked for the skin/cape/hat area to work "like a browser and
installed area like mods", with pre-made capes so nobody has to upload PNGs
by hand.

- **New `cubeon/gallery.py`**: an offline, generated catalog of 14 ready-made
  skins (palette remaps of `cosmetics.default_base_skin()`) and 16 capes
  (pixel painters over the 10x16 panel, tools/make_cape.py layout). Files are
  generated once per `GALLERY_VERSION` into `~/.cubeon_launcher/gallery/`
  (sheets + previews + installed.json + manifest.json) — no bundled assets,
  no packaging changes, no network. Installs go through the exact upload
  pipeline (`skins.add_custom_skin` / `capes.add_custom_cape`) and wear the
  item immediately.
- **`cubeon/skins.py`**: `render_local_skin_preview` gained an optional
  `src_path=` kwarg so the gallery renders body previews from its own dir.
- **`ui/skin_tab.py`**: Skin and Cape panes now have the Mods tab's
  Browse | Installed split (underline `text_tab` rows with live
  "Installed (N)" counts; both sub-panes stay mounted, `.visible` flips).
  Browse = searchable gallery grid (search field + tiles with GET/INSTALLED
  states). The Cosmetics/hat pane got a search box over the hat grid.
  Deleting an installed item calls `gallery.forget_file` so Browse stops
  advertising it.

## Verification
- `tools/test_gallery.py` (new): 22 checks — generation, layout/validity of
  every sheet, preview crops, install→active+CSL sync, bookkeeping round-trip,
  idempotent regeneration. All green.
- `tools/test_ui_smoke.py` 74/74 (incl. the cosmetics/cape pane click-throughs
  and no-null-children cape row regression).
- `tools/test_capes.py` 14/14, `tools/test_skins_net.py` all green.
- `tools/test_milestones.py` showed one flaky failure once, then 41/41 twice
  with and without my changes — time-based flake, not related.

## Gotchas for the next agent
- `view_state`/`view_sync` dicts in `ui/skin_tab.py`: `refresh_skins_list` /
  `refresh_capes_list` run during the build *before* the view-tab rows exist,
  so they ping `view_sync["fn"]` only when set (it re-renders the Installed
  counts). Don't make them call the view rebuilds directly.
- Gallery regeneration is keyed on `GALLERY_VERSION` in the manifest — bump it
  if you change any painter/palette or users keep stale art.
- ft.Image.src can't load files from ~/.cubeon_launcher (assets_dir-relative
  or URL only) — gallery tiles base64 their preview bytes, same as the
  existing skin/cape previews.
