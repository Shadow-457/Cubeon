# 2026-09-07 — Agent: skins security patches (4)

## What I did

Implemented the four user-approved security patches for the skins worker
(`worker/cubeon-skins.js`), client (`cubeon/skins.py`, `main.py`,
`launcher_core.py`), plus tests, then deployed to prod.

1. **Name-flip spam guard.** `handleHeartbeat` now rate-limits pointer
   MOVES per identity: `lastmove:<uuid>` (KV, one write per real move)
   records the second of the last move; a second move within
   `POINTER_MOVE_COOLDOWN_S` (3600s) → `429 name_move_cooldown`.
   Design notes learned the hard way (tests caught it):
   - The FIRST move an identity ever makes (initial claim, no prior
     stamp) is free — otherwise fresh-install + typo-fix rename got
     throttled. `ownsUuid` now returns `"claimed"` (vs `true`) on
     first contact so the heartbeat can distinguish claim from move.
   - Steady-state heartbeats (pointer already ours) consume zero writes
     and no cooldown.
   - A victim reclaiming a hijacked name stays fast: the cooldown is
     per-identity, and the HIJACKER's move is what got stamped.
2. **Name-in-use warning.** Heartbeat response now carries
   `name_contested: bool` (true = a different identity held the name
   within the cooldown window; computed from the PRE-move holder + their
   `lastmove` stamp; pure read). Client persists it in
   `skin_net.json` (`name_contested` key, cleared on next clean
   success), exposes `skins.name_contested()`, and `main.py`
   (`on_profile_username_change`) surfaces a status-bar note 3s after a
   rename (daemon thread, cosmetic/best-effort).
3. **First-claim race fix (bugs-and-flaws.md #6).** `ownsUuid` TOFU
   path now re-reads `owner:<uuid>` after the put and returns honest
   `false` (→ 403) if a concurrent racer's hash settled instead. One
   free read, once per identity, ever.
4. **Unlocks 429 clarity.** `handleUnlocksPost` on KV quota now returns
   `problem(429, "kv_write_budget_exhausted")` instead of
   200-with-stale-set. `cubeon/milestones.py` already handled the 429
   shape (retry at next daily window) — its 200-ambiguous fallback stays
   as belt-and-braces for old workers.

Also fixed `ownsUuid` quota-put translation to re-raise non-quota errors.

## How I verified

- `node worker/test-worker.mjs` — ALL PASS (new checks: rename stamps
  move, second rename → 429, throttled rename moves nothing, repeat
  same-name heartbeat → 200 steady-state, other identity takes name →
  contested, victim reclaim → contested, fresh name → uncontested).
- `node worker/test-invites.mjs` — ALL PASS (unrelated suite, sanity).
- `python tools/test_skins_net.py` — ALL PASS (new section 8:
  contested recorded/cleared/absent-key, 429 name_move_cooldown →
  cooldown recorded + identity half NOT saved).
- `python tools/test_milestones.py` — 41/41. `python tools/test_ui_smoke.py` — 46/46.
- Deployed: `cd worker && npx -y wrangler deploy -c wrangler-skins.toml`
  (version 41b76984-d455-4aec-b039-0fb9d0502772). Live probe with real
  `~/.cubeon_launcher/auth_key.json`: steady-state heartbeat → 200
  `{"status":"ok","name_contested":false}`; immediate rename → 429
  `{"error":"name_move_cooldown"}`; unlocks GET → 200; /health ok.
  (Probe took the name "Hamza" for our uuid — was uncontested, harmless.)

## Gotchas for the next agent

- `ownsUuid` returns `"quota" | "claimed" | true | false` now — check
  quota FIRST, `"claimed"` is truthy so old callers are safe, but only
  the heartbeat distinguishes it.
- `nameContested(current, uuidLower, env)` takes the PRE-move holder,
  not the key — passing the post-write holder makes it always false.
- KV write cost per rename: 2 writes now (pointer + lastmove stamp).
  First claim: 2 (owner + pointer; no stamp).

## Baton question

The unlock-429 change means the client no longer needs its
200-ambiguous-set fallback (`milestones.py`) once every worker is
deployed. Worth deleting it to simplify, or keep as belt-and-braces?
I kept it — KV quirks are older than this deploy.
