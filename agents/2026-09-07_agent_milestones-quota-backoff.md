# Milestones quota handling, startup evaluate, re-sync gap — 2026-09-07

Context: yesterday's session (kv-quota-storm) shipped the milestone hats
feature (cubeon/milestones.py, Worker /api/unlocks route, cosmetics hats).
Today I chased the "why does prod ignore my unlocks" mystery to ground and
closed three follow-up gaps.

## The mystery and its answer
Prod `POST /api/unlocks` returned `{"milestones":[]}` for every valid id
while local stub tests passed. Root cause: **the account-wide KV daily
write budget was already exhausted** (fallout of the same quota history).
`putIfChanged` swallows the limit-exceeded error and returns "quota", the
Worker answers 200 with the un-persisted old set — so a quota failure is
indistinguishable from success on the wire. Verified by probing heartbeat
with a fresh name: 429 `kv_write_budget_exhausted`. Deployed bundle was
confirmed correct via `wrangler deploy --dry-run --outdir` + grep.

## What I changed (all in cubeon/milestones.py + call sites)
1. **Quota backoff**: 429 (and the ambiguous 200-with-empty-server-set
   shape) now record `retry_not_before` = next 00:00 UTC + 15 min.
   `sync_unlocks()` refuses to fire before it. Test covered.
2. **Startup evaluate**: main.py calls `core.milestones_evaluate()` once
   after friends-service init, so thresholds crossed yesterday (10h, 3
   friends) surface on next launch, not after the next session.
   friends.py also seeds `note_friends_count` from the cached roster.
3. **Re-sync gap**: evaluate() previously only synced on a *fresh*
   unlock — an unlock whose POST died on the quota would never re-sync.
   Now it syncs whenever `unlocked - synced_unlocked` is non-empty.
   Still write-frugal: one merge write total, retries quota-gated.

## Verification
- tools/test_milestones.py: 41 passed, 0 failed (new: 429 backoff,
  200-empty backoff, unconfirmed re-sync, confirmed-set-no-POST).
- tools/test_ui_smoke.py: 46 passed, 0 failed.
- test_skins_net.py / test-worker.mjs / test-invites.mjs: all pass.
- Live launcher (real HOME): paints, zero tracebacks, and the full
  loop observed: startup evaluate → unconfirmed founder → sync attempt →
  quota hit → backoff written (00:15 UTC next day) in milestones.json.

## Q&A baton for the next agent
The Worker's quota path returns **200 with the stale set** — if you ever
touch worker/cubeon-skins.js, consider making `putIfChanged`-quota return
an explicit 429 from /api/unlocks (the client now handles both shapes).
Also: `retry_not_before` is epoch-UTC; don't compare it to local time.
