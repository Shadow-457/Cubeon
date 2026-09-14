# Bug sweep — 2026-09-14

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
