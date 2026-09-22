# AuthMe "exceeded the maximum number of registrations" on tunneled servers (2026-09-22, Cline)

- **Agent:** Cline
- **Date:** 2026-09-22
- **Task:** Fix AuthMe's per-IP registration limit blocking friends joining a
  Cubeon-hosted (Minekube-tunneled) server.

## What I did
Two bugs, both in `cubeon/server.py`:
1. **The real bug:** AuthMe's stock `settings.restrictions.maxRegPerIp: 1`
   limits registrations per IP, but every player arriving through the
   Minekube Connect tunnel shares ONE apparent IP (the tunnel's local
   connection) — so the first registrant blocks everyone with
   "exceeded the maximum number of registrations (1/1 ...) for your
   connection". Fix: `AUTHME_TUNING` now sets
   `restrictions.maxRegPerIp = 0` (AuthMe source confirms: "The value 0
   means an unlimited number of registrations!"). The password layer still
   protects accounts; only the shared-IP dial is disabled.
2. **Found while testing:** `_tune_authme_config` only recognized section
   headers at `indent <= 2`, but AuthMe 6.x (ConfigMe) writes sections at
   indent 4 (`settings:` 0, `restrictions:` 4, keys 8) — so the tuner was a
   NO-OP on current AuthMe configs (which is why the stock 1/1 limit was
   live at all). Replaced the single `section` variable with an indent
   stack; works for both 2-space (legacy) and 4-space (modern) configs.

## How I verified
- Temp-file simulation with a realistic AuthMe 6.x config: all four dials
  patch exactly (`maxRegPerIp: 0`, `restrictions.timeout: 300`,
  `sessions.enabled: true`), the duplicate `timeout:` under both sections
  each gets its own value, idempotent on second run, missing file → `[]`.
- Same for a legacy 2-space config. `py_compile` clean.
- `python3 tools/test_server_integrity.py` → 59 passed, 0 failed.
- `python3 tools/test_orphan_server.py` → 16 passed, 0 failed.

## Notes for the next agent
- Answering the opencode baton: the "second part" of their cut-off message
  was (this session) the AuthMe registration-limit complaint above — fixed.
- Existing servers converge on the NEXT server start (the tuner never
  creates config.yml, it only patches an already-generated one) — that's
  pre-existing design, unchanged.

## Question for the next agent
AuthMe never sees real player IPs through the tunnel. A deeper fix would be
enabling proxy forwarding (spigot.yml `bungeecord: true` + Connect's real-IP
support) so per-IP bans/limits work again — is that supported by
connect-spigot.jar today, and is it worth pursuing?