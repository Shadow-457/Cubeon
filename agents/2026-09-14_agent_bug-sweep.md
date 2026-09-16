# Bug sweep — 2026-09-14
glm 5.3 flash and deepseek v4.1 flash and deepseek v4 flash contorbuted in it

Deep-research pass: ran every harness in `tools/`, cross-checked
`agents/docs/bugs-and-flaws.md` against today's code, fixed what was real.

## Found & fixed (all verified by tests below)
1. **Non-atomic JSON writes (critical)** — `save_config`, `skins._save_skins_meta`,
   `skins._save_publish_state` wrote with plain `open(path, "w")`; a crash
   mid-write truncated the file and the loader then silently reset the user's
   settings/skins. New shared helper **`cubeon/atomicio.write_json()`**
   (unique temp file in the target dir + fsync + `os.replace()`). This is now
   an invariant in module-map: ALL persisted JSON goes through it.
2. **Profane User-Agent** — `fuckarch/...` sent to Modrinth from mods.py,
   modpacks.py, icons.py (and `cubeon-thing/...` in server.py). School/corp
   proxies and Modrinth's WAF block that; all now `Cubeon/<app>/1.0`.
3. **`mods.py` hardening** — `toggle_mod`/`delete_mod` guard on
   `os.path.lexists` (stale UI list gave a raw FileNotFoundError from a click);
   `install_local_mod`/`add_mod_file` sanitize the basename via new
   `_safe_jar_filename()` (Windows-illegal chars, trailing dots/spaces).
4. **Worker DM refusals were silent** — `onDm` guard-returned, so a bounced DM
   (bad name / empty text / not friends) evaporated while the UI renders
   optimistically: looked like "sent, being ignored". Now sends `T.ERROR`
   frames `dm_bad_recipient|dm_empty|dm_not_friends` (toasted by
   `friends_service._on_error`). **The worker needs redeploying to take
   effect** (`cd worker && npx wrangler deploy -c wrangler-friends.toml`).
5. **`test_mod_detail.py` was silently network-dependent** — it faked
   `mods.requests`, but since the net refactor metadata goes through
   `net.get_json`; on a cold 24h cache it hit the REAL Modrinth API and 404'd
   (`fresh-download-project` → DownloadError after 3 real retries). Added
   `net_routes()`/`restore_net()` to the harness; 66/66 offline now.
6. **`test_milestones.py` flake** — `drain_sync()` returned before the sync
   thread had been spawned (immediate `threading.enumerate()` saw none), so
   POST-count checks raced the thread. Now observes the thread first, then
   waits for it to vanish.

## Doc updates
- `agents/docs/bugs-and-flaws.md`: entries 1/3/4/7/8/9/10/11 marked fixed with
  mechanism; entry 5 (worker rate limiting) marked STALE — a sliding-window
  limiter already exists in cubeon-friends.js; DM-echo entry corrected (the
  real flaw was the silent drop, the echo was already guarded).
- `agents/docs/module-map.md`: new "Atomic JSON writes + hardening" invariant
  section at the top.

## Not done (left for a future session, listed in the catalog)
- #12 worker friend-request mutual-add race; #13 background threads swallowing
  exceptions; #14 java fallback too old; #15 get_profile_dir creates state;
  #16 Modrinth 24h cache TTL; #17 version_dropdown None before population.

## Verification
- `test_mega_smoke.py` 16/16 (post-change, full runtime)
- friends 49 (new parity check), ui_smoke 115, mod_detail 66, milestones 50
  (×6 runs), mod_matrix 68, capes 14, modpacks 51, mod_store 21, net 21,
  skins_net, production 13, p2p ×6, orphan 16 — all green
- `test_fuzz.py` 13/13 (2036 handler invocations, no defect-class exceptions)
- `node --check worker/cubeon-friends.js` clean; every edited .py compiles

## Visual sweep (same day, UX-first pass)

- Captured fresh screenshots of every tab + both dialogs
  (`tools/ux_capture.py --out /tmp/ux_fresh`, old shots were pre-chat-redesign).
- Fixed two user-facing chat glitches in `ui/chat_tab.py`:
  1. Self-avatar was a blank square — `ft.Image(src=<absolute path>)` never
     loads in this Flet version; now base64 bytes with color-chip fallback.
  2. A stray floating hairline crossed the empty right pane — the header
     divider is now `header_rule`, hidden until a conversation is selected
     (toggled in `_select` + `_clear_conversation`, both refresh tuples).
- Verified by re-capturing: line gone, avatar renders (it's a genuinely
  near-black image, brightness ~20/255 — user content, not a bug).
- ui_smoke 115, friends 49, friends_service 268 all green post-change.

## Worker / relay sweep (same day)

Deep-read all four workers + the Python relay client. Fixed:
1. `decodeURIComponent(pathname)` URIError → CF 1101 crash on garbage paths,
   in friends Worker+DO, invites, and skins — `safePathname()` everywhere.
2. **Chat history backfill served the OLDEST page** (`ORDER BY ts ASC LIMIT 50`
   = the stale prefix once a conversation passed 50 msgs) — newest-50
   subquery, `rowid AS rid` projected (caught by a real-SQLite sanity check:
   the first version didn't project rowid and failed with "no such column").
3. Unauth WS hello flood (SHA-256 + permanent claim row per attempt) — IP
   captured into the socket attachment at upgrade, 30/10min per-IP gate; the
   authed attachment re-includes `ip` (serializeAttachment REPLACES).
4. Claim races: concurrent claim-on-connect hellos / double `/claim` hit the
   names PK → socket-killing exception / 500. Both INSERTs now catch, re-read,
   and fall through to row-existed semantics (same secret = ok, else 409).
5. invites' documented `RATE_LIMITER` binding was never referenced by code —
   now gates PUT (degrades to no-limit if absent or failing).
6. waitlist POST parsed an unbounded JSON body — 1KB cap like the siblings.
7. Blocked accounts were addable via the in-game mod's name path; call
   invites minted unbounded `calls` rows — both gated.
Verified NON-issue: the long-listed "mutual-add race" (#12) — DO handlers run
one at a time and `onAdd` has no awaits; doc updated with the mechanism.
- Tests: node --check ×4, node test-worker.mjs + test-invites.mjs, python
  test_friends 49, test_invites 127, test_skins_net, test_production 13,
  test_mega_smoke 16 — all green. Docs: bugs #12/#22–28, module-map relay
  invariants. Deploy: `npx wrangler deploy -c wrangler-friends.toml` etc.

## Landing page rebuild (web/index.html)
- Full rewrite per web/premium-ui-design(skill)/SKILL.md: Minecraft-editorial style,
  pixel-york green/gold palette, Fredoka pixel type, hero with parallax clouds +
  floating blocks, depth meter tracking scroll (Y: 320 -> bedrock), skeleton -> real
  app screenshot swap, live-simulated friends roster, honest-oven roadmap board,
  FAQ accordion, waitlist form with inline validation. Copy written as human dev-diary.
- Verified with Playwright: all 5 sections screenshot-reviewed, FAQ/anchor/waitlist
  interactions exercised, zero console/page errors.
- Fixed post-render bug: `.btn` was inline on <a> elements -> "Get on the list"
  button overlapped its paragraph; `.btn{display:inline-block}`. (Gotcha: styled
  <a class=btn> needs inline-block or padding doesn't push line flow.)

## Minecraftia font wiring (web/index.html) — verified
- Copied `assets/fonts/Minecraftia-Regular.ttf` -> `web/assets/fonts/`, added
  @font-face, applied to h1/h2/h3, .brand, .btn, .q-a. Body stays Fredoka —
  Minecraftia is illegible below ~16px.
- line-height for pixel headings dropped 1.28 -> 1.12 (pixel faces carry lots
  of internal leading; 1.28 made 2-3 line hero headings balloon).
- Verified `document.fonts.check` true, zero console errors, and full-page
  screenshot review at 1440px AND 390px mobile: hero stack, oven board,
  features cards, friends roster, how-it-works steps, FAQ questions (incl.
  wrapping 2-line questions on mobile), CTA/badges — no overflow, no wrap
  regressions. Note: element screenshots of mid-page sections will show the
  sticky nav slicing the heading — screenshot artifact, not a page bug
  (scroll-into-view then element capture overlaps the fixed header).

## Hero type fix + git commit (post-review)
- User flagged hero text looking bad at wide viewports: .h-xl capped at 112px
  pushed Minecraftia past its bitmap grid (glyph strokes merged into mush on
  "with"/"friends."), and line-height 1.12 + the inline-block .pop highlight
  cropped glyphs. Fix: cap .h-xl at clamp(40px,5.6vw,76px), heading line-height
  1.24, letter-spacing .02em, .pop padding .06em/.1em. Re-verified hero at
  1440 / 1828 / 390px — three clean lines, highlight contains full glyphs.
  GOTCHA: Minecraftia must not exceed ~80px display size; it's an 8px-grid
  bitmap face, past ~80px letterforms fuse.
- Committed in 2 commits: 3f53c02 (bug sweep + landing + font) and e97e0c9
  (prior-session skin/gallery/sandbox work). Push FAILED: origin HTTPS auth
  invalid/missing token — needs credentials or SSH remote to publish.
- mod/.gradle/* churn deliberately left uncommitted (build-state noise).

## Skins/Profile: browse area removed (user request)
- ui/skin_tab.py 1139 -> 649 lines: the local-library Browse experience is
  gone - skin gallery, cape gallery, search rows, "Open folder" buttons,
  GET tiles, and the per-pane Browse|Installed view machinery (_view_tabs/
  _view_pane/view_state/view_sync, ensure_gallery() call, _open_folder).
  Each Skin/Cape pane is now: preview box + label + installed card grid +
  upload CTA + status. Skin/Cape underline tabs and the installed-card flow
  are untouched.
- LESSON: when bulk-deleting by anchor line, indented duplicates of the
  anchor (e.g. `refresh_skin_gallery()` inside a handler) match first and
  the deletion silently eats unrelated code - my pass wiped the whole cape
  picker wiring (caught by test_ui_smoke's NameError, restored by hand).
  After any such sweep: py_compile + full test_ui_smoke, not just grep.
- tools/test_ui_smoke.py: 5c/5d/5e rewritten to pin the new reality (no
  search box, no browse copy, no view tabs, installed list always visible,
  seeded library files never surface). 5f+ unchanged. Suite: 114/114 green;
  test_gallery 25/25 green (core library module kept for the forget_file
  bookkeeping + possible future use).

## Workers deployed (2026-09-14)
- All four workers now LIVE with the sweep fixes: friends (28e39df0), skins
  (035a9cf2), waitlist (87605d08), invites (17ab0fc5). Verified: oversized
  waitlist body rejected; legit join returns 200.
- cubeon-invites had NEVER been deployed (no toml existed). Created
  worker/wrangler-invites.toml + KV namespace INVITES
  (837c3f4a586047d69eba373fc6f9f602) and deployed. README updated.
- Gotcha: wrangler hangs silently at its banner when the stored OAuth token
  needs refresh and no TTY - rerun with CI=true and </dev/null; it then
  refreshes and proceeds. Deploy = upload ~10s + triggers ~5s.

## Rough-edges pass (post beta-readiness review)
- #13 (worker-thread exceptions swallowed): worker-path backstops now log
  with exc_info to the central file log (skins publish, mod-repair,
  name-contest, backup scheduler, launch Java scan, p2p session loops,
  local_cache refresh). UI best-effort catches left silent on purpose.
- #14: too-old-Java fallback logs required vs found. #17: skin section
  rebuild falls back to cfg['last_version'] when the dropdown hasn't
  populated. #16: local_cache.invalidate(namespace=None) added (no UI wiring
  yet - a Settings 'clear content cache' button can call it).
- #15 kept (all callers intend creation). #18/#19 left documented.
- Suites green: ui_smoke 114, mod_detail 66, modpacks 51, versions_manifest
  10, net 21.

## Windows builds rebuilt with the launcher-lib fix (wine)
- dist/Cubeon (onedir, 153M) + Cubeon-Windows-x64.zip (128M) +
  Cubeon-Windows-x64-single.exe (127M) rebuilt via the wine recipe with
  --collect-all minecraft_launcher_lib. Verified: lib present in
  _internal/, onedir exe AND single exe boot under wine with zero
  ModuleNotFoundError/tracebacks. Public (Friends-disabled) variants NOT
  rebuilt yet - run build_public_windows.py equivalents before publishing
  those. dist/ is gitignored: binaries live only in dist/ here.

## Download progress visibility (user report)
- Mods/resourcepack/shader browse rows and the mods detail dialog showed a
  static "Downloading..." despite the backend already supporting
  progress_cb(downloaded, total). All row-download paths + _run_install now
  render coalesced whole-percent "Downloading… N%" on the button/status text
  (packs already had a progress bar; plugins a banner with KB counter).
  Callback flood guard: update only on integer percent change.

## Multi-file install progress aggregation (user follow-up)
- Reported: "the 1-100% doesn't work quite good when install multiple mods".
  Root cause: cubeon/mods.py reported progress PER FILE, so a mod with deps
  ran 100% -> 0% -> 100% once per dependency, and dependency downloads passed
  NO progress_cb at all (only the main file reported).
- Fix in cubeon/mods.py:install_mod_with_dependencies(): resolve the full dep
  list (and its total) BEFORE the first byte moves, then report the batch as
  (whole files done + current file's fraction, total files), with a "floor"
  so a grown batch can never jump backwards. Success == exactly 100; a failed
  dep leaves it short of 100 and is named in the result (unchanged).
- Fix in ui/mods_tab.py: one label helper batch_progress_text(value, total) ->
  "Downloading… 42% (file 2/3)" (plain percent when total <= 1), used by BOTH
  the browse-row install and the detail-dialog version rows. The browse row
  now builds two reporters off one shared percent guard: _batch_progress
  (file units, mod path) and _progress/_bytes_label (bytes, resourcepack +
  shader path via content.download_content) - the units differ, so they must
  not share a label.
- New suite tools/test_mod_install_progress.py (39 checks, offline, fakes
  cubeon.mods, sandboxed HOME): pins monotonic percent, final pre-resolved
  total, 100-on-success, skipped deps not inflating the total, dep failure
  reported not raised, plus the label formatting rules.
- GREEN: test_mod_install_progress 39, ui_smoke 114, mega_smoke 16,
  mod_detail 66, mod_store 21, modpacks 51, net 21.

## Pack archive download now shows its own percent
- Same report, modpack half: install_modpack_from_url / install_modpack_from_
  cf sat on a static "Downloading modpack..." for the whole ARCHIVE transfer -
  the one phase whose size the caller doesn't know (tens of MB), with the bar
  indeterminate. New cubeon/modpacks.py:_archive_progress_status(prefix,
  status_cb) is fed to _download_to as progress_cb and emits whole percent
  only (net already throttles >=33ms/1%, and modpacks_tab's status_cb repaints
  the status line + bar per call, so duplicates are wasted repaints).
- test_modpacks.py gained 3 checks (54 now): percent sequence + duplicate
  suppression, the CurseForge prefix, and "unknown total reports nothing".
## Artifacts rebuilt from HEAD + verified (Linux + Windows)
- **AppImage**: rebuilt (build log birth 17:14:10) AFTER the last source edit
  (modpacks.py 17:04:26) - the staleness check that matters, since PyInstaller
  snapshots sources at analysis time. Booted: tray up, `websocket connected`
  at 17:18:39, **0** traceback/ModuleNotFound lines, `RUN_EXIT=124` = our own
  timeout killed a still-running healthy app. The Gtk-Message
  colorreload/xapp/canberra lines are host GTK noise.
- **Windows (wine)**: onedir + zip + onefile rebuilt. `_internal/` carries
  `minecraft_launcher_lib/`, `mod/brackets.json`, `assets/`, and
  `flet_desktop/app/flet-windows.zip` (40 MB, 17:21 = this build). Zip keeps CI
  parity (root entry `Cubeon/`, 128 MB). Both exes boot under wine: fresh
  `websocket connected` + `ui_painted_ok` written (17:24:35 onedir,
  17:26:12 onefile) with thousand(s) of rendered frames. Only build warning is
  `flet.testing` submodule skipped for a missing numpy - harmless.
- **Key discovery**: a frozen Windows launcher writes its state to the WINE
  PREFIX (`~/.wine/drive_c/users/<user>/.cubeon_launcher/`), NOT the Linux
  `~/.cubeon_launcher/` - diffing the Linux log after a wine run shows nothing
  and looks like a failure. Logged in the module map.
- **`wine /unix/path/python.exe` works** - no `Z:\` escaping needed. Two
  earlier attempts at this session's Windows build never even started (log
  never created) while fighting the double-backslash form.
- `main.py`/`ui/mods_tab.py` etc. unchanged during all builds, so the artifacts
  match commit 28a545d exactly.
- **Full batch re-run at HEAD, all green** (9 suites, every exit=0):
  mega_smoke 16, ui_smoke 114, mod_detail 66, mod_store 21, modpacks 54,
  net 21, mod_install_progress 39, fuzz 13, production 13.
- Final `dist/`: Cubeon-x86_64.AppImage 279 MB (17:18),
  Cubeon-Windows-x64/ onedir (17:21), Cubeon-Windows-x64.zip 128 MB (17:22),
  Cubeon-Windows-x64-single.exe 127 MB (17:24). `dist/AppDir` (~280 MB) is
  regenerated by every AppImage build - safe to delete when space is tight
  (disk was at 97%, 7.3 GB free).

## Incompatible-pack complaint -> compat system + unified doctor
User: installed resourcepacks show red "Incompatible" in game, and shouldn't
be listed at all. Built: packformat.py (verdicts + atomic repair),
doctor.py (run_doctor over mods/packs/shaders/modpacks/plugins),
browse-time filtering in content.py, launch-time pre-repair, UI badges
+ one-click fix in mods_tab, facade exposure in launcher_core.
New suite test_content_doctor.py: 88 checks. Two test bugs I had to fix
in my own fixture: a "failing" pack whose supported_formats range actually
COVERED the target (vanilla-correct verdict = compatible; fixture now
[34,40]), and a "clean re-run" assertion that could never pass because the
corrupt pack is intentionally reported forever (now asserts repair-stuck +
corrupt-still-reported). Also updated test_mod_detail's launch check to the
run_doctor contract. Batch: doctor 88, ui 114, mega-static 12, mod_detail
66, mod_store 21, modpacks 54, net 21, install_progress 39 - all green.

## Artifact rebuild with the compat system (0b6d1a9)
All four dist/ artifacts rebuilt from HEAD and boot-verified 2026-09-15
~18:35-18:42: AppImage (websocket x2, 0 errors), Windows onedir + zip
(ui_painted_ok, 2446 frames), single exe (needed an 80s window - onefile
self-extraction eats the first ~20s, so a 40s timeout looks like 'no
websocket'; 3365 frames on the longer run). Sequential builds only: the
AppImage onedir stage and the Windows build share the dist/Cubeon name.

## Bug hunt (second pass, same day)
Full batch green (ui 114, mod_detail 66, mod_store 21, modpacks 54, net 21,
install_progress 39, doctor 88+3, mega-static 12, versions_manifest 10).
Found + fixed 1 real bug in the fresh compat code: _format_from_jar and
resource_format_for cached None results, so a version installed (or a
snapshot jar appearing) mid-session stayed "can't tell" for the whole
process lifetime - packs silently skipped verdicts for it. Both now cache
positive results only; regression section 9 added to test_content_doctor
(proves None -> 88 in-session). Also audited and cleared: _covers legacy
semantics, repair_pack's corrupt-zip guard, _rewrite_zip duplicate/case
cases, plugins-section dedup and running-server guard, search facet
scoping, get_content_download malformed-response guards.
