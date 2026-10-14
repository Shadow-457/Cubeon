# 2026-10-14 — Play tab gets per-version banner art + "Jump back in" cards

## What the user asked for
"can you edit the main page to make it look better with images we fetch for
each version and make it better please it looks so dry rn". Clarified via
question: **launcher Play tab** (not the website), using the **big hero banner**
and **instance cards**.

## The gap found
`cubeon/version_art.py` already fetches each release's official wiki banner
(Java_Edition_<v> page image / `<v>_banner.jpg`), caches it under
`~/.cubeon_launcher/cache/version_art/`, and exposes `get_version_art()` /
`fetch_async()` — **but nothing in the UI ever called it**. The Play tab showed
a single static `titleimg.jpg` and a bare-text version picker. Exactly the
"dry" the user described.

## Changes

### `cubeon/version_art.py` — Flet-facing helpers (the missing consumer API)
- `cached_path(version)` — disk-only path, no network.
- `src(version)` — **base64** of the cached banner, or None. Flet's
  `ft.Image.src` resolves a non-URL string against the app's assets folder and
  cannot read an absolute path, so a cached banner must be inlined base64 (the
  same discovery as `cubeon/icons.py` and `ui/skin_tab.py`). Mirrors
  `icons.src`.
- `prefetch(version, on_ready)` — cache, then hand `on_ready` a
  `ft.Image.src`-safe value (fires immediately on-thread if already cached,
  else on the download thread). Mirrors `icons.prefetch`.
- `_plausible_version()` guard — every real MC release/snapshot id starts with
  a digit (`1.21.11`, `25w14craftmine`); custom/junk instance ids (`fgdg`) do
  not, so junk ids now skip the wiki lookup entirely instead of doing a
  404 + retry on every launch.

### `main.py` — Play tab
- `import version_art`.
- `hero_banner` (the full-width image under the instance card) now shows the
  **selected version's** banner; falls back to `titleimg.jpg` until cached / for
  versions with no wiki art.
- `_refresh_hero_banner(version)` — cached art instantly, else `prefetch` and
  repaint via `thread_safe_ui`. Guards against a late download landing after
  the user switched versions (`_hero_art_uid`), and skips the repaint when the
  src is unchanged (update_hero is called frequently).
- **"Jump back in"** section: `instance_cards_row`, one banner-headed card per
  installed version (banner + friendly name + raw id), the selected card
  tinted/bordered. Clicking a card selects that instance (`_select_instance` →
  `version_dropdown.value` + `on_version_selected`).
- `_rebuild_instance_cards()` — rebuilt only when the installed set or the
  selection changes (signature guard), so `update_hero()`'s frequent calls don't
  churn controls. Empty-state text when nothing is installed.
- Hooked both into `update_hero()` (which `on_version_selected` and
  `refresh_version_list` already call).

## Verification
- **Full suite green: 49/49 suites, 0 failures** (run after the final edit),
  including `test_ui_smoke`, `test_mega_smoke`, `test_net` (the module-scan
  test lists `version_art`), `test_mod_detail`, `test_production`.
- **Headless end-to-end render** — ran the real app under `xvfb-run` with the
  repo's `.venv-build` (flet 0.86.5, the pinned version): the Play tab built
  with no traceback, and the selected version's banner **actually downloaded**
  (`~/.cubeon_launcher/cache/version_art/1.21.11.jpg`, 1170x500 JPEG), proving
  the fetch → base64 → `ft.Image` path works. Junk id `fgdg` produced **no**
  wiki request after the guard was added. Update check also logged
  "up to date (v1.1.2)", confirming the release bump.
- Helper-level probe: `src()` returns base64 of the cached bytes; `prefetch()`
  fires `on_ready` synchronously when cached and returns None (no network) for
  junk ids.

## Gotchas for the next agent
- **Flet images outside `assets/` must be base64.** An absolute path silently
  renders blank. Use `version_art.src()` / `icons.src()` — never pass a
  `~/.cubeon_launcher/...` path as `ft.Image.src`.
- Instance cards prefetch art for **every** installed version on first build;
  after the first download each version is cached forever, so it's a one-time
  burst. If a profile ever holds many dozens of instances, consider capping the
  prefetches per rebuild.
- `image_cache` is disk-backed at `~/.cubeon_launcher/cache/version_art/`;
  winners are `.jpg`/`.png`; a miss is cached in memory only for the session.
- **Shared repo:** another agent had uncommitted edits to `web/index.html` (the
  website, not this work) while this was in flight; I stayed out of it.

## Not done / not asked
- No website change (user chose the launcher).
- No new tests added for the Play tab art (no existing Play-tab render harness
  that isn't a stub); relied on the headless render + full suite.
- Nothing committed — the tree also holds other agents' overlapping work.
