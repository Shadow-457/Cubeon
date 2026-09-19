# KV write budget fix + window launch polish

## KV: steady state now costs ZERO writes (commits f24544c, fe76bc5)

Cloudflare KV free tier = 1,000 writes/day **account-wide** (all workers), but
**100k reads/day**. The old code unconditionally PUT on every heartbeat and
every skin re-upload, so idle launchers burned the budget by themselves.

`putIfChanged(env, key, value, options?)` in `worker/cubeon-skins.js` —
compare-then-write; returns `"quota"` on limit-exceeded (caller → 429).
All former unconditional puts now go through it:
- heartbeat pointer — writes only on a REAL rename
- skin upload — `putSkinRecord`: texture:<id> only when id is new,
  skin:<uuid> record only when changed, face likewise
- report:<uuid> — TTL'd (TTL puts always write; dedupe read stays)
- owner:<uuid> TOFU — raw put, fires once per uuid ever (fine)

Verified against `wrangler dev --local`: repeat heartbeat + identical
re-upload → 200, zero writes; rename → one pointer write. Waitlist and
invites workers were already frugal (dedupe reads). Friends worker uses
Durable Objects — not KV-metered.

**Gotcha**: `git add -A` in `worker/` also committed `.wrangler/` local dev
state (30 sqlite/blob files). Now in `worker/.gitignore`; removed in fe76bc5.
Lesson: never `git add -A` after a `wrangler dev` session.

## Window launch polish (same commits)

User complaint: "launches in different size then resize then weird shit for
~1 sec". Two causes, both fixed in `main.py`:
1. Window showed at default size before Flet applied 1180×760 + before
   controls mounted → `page.window.visible = False` at setup; after
   `thread_safe_ui.mark_mounted(page)` a `page.run_task(_reveal_window)`
   awaits `wait_until_ready_to_show()` (async! sync call = silent no-op)
   then flips visible → one clean paint.
2. Geometry never persisted → size snapped back every launch. New
   `load_window_geometry`/`save_window_geometry` in `cubeon/config.py`
   (separate `window_geometry.json` — config.json is rewritten wholesale on
   settings changes; geometry changes are far more frequent). Restore is
   clamped (width 980–7680, height 640–4320, off-screen guard re-centers);
   saves are debounced 400 ms via `threading.Timer` on resize/move events;
   on close it saves immediately. When maximized, the RESTORED size is kept
   (saving maximized dims would make next launch open maximized-sized but
   not maximized).

Flet 0.86 notes: `Window.visible` is a dataclass field (settable, not a
method); `wait_until_ready_to_show`/`center` are async — call via
`page.run_task(coro_fn)` (returns concurrent Future; runs on the page's
event loop).

Tests: `tools/test_ui_smoke.py` 41/41, `tools/test_skins_net.py` pass,
CI green on f24544c.

## Still pending from earlier today
The production KV budget was still drained at 22:33 UTC (heartbeat → 429).
After 00:00 UTC the next launcher sync republishes `Light_314` + face
automatically (state file's cooldown has expired; hash was invalidated so
the sheet+face upload will fire). Check
`https://cubeon-skins.hamza-457-shahbaz.workers.dev/faces/Light_314.png`.

## Question for the next agent
The user said the launch still "feels cheap" even beyond the flash — is
there a perceived-speed angle left (e.g. cold-start of the Python process
itself in packaged builds, or a splash screen while Friends/fonts load)?
If they raise it again, profile `python -X importtime main.py` first.
