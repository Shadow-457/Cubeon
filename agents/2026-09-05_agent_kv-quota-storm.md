# 2026-09-05 — KV write quota storm: diagnosis and fix

## What happened
User asked about the `web/` folder for social-media funnel planning. While
checking the waitlist Worker end-to-end I found `POST /` returning **HTTP 500
"error code: 1101"** — and the tail log showed `KV put() limit exceeded for
the day.` The account-wide free-tier budget (1k writes/day, **shared across
ALL workers**) was exhausted.

## Root cause (found via wrangler tail, live)
`cubeon-skins` was receiving `/api/heartbeat` POSTs **every ~0.9s** from
`python-requests` — the launcher itself (PID confirmed running + Minecraft
under it). Chain:

1. `main.py` username field: `on_change` fires **per keystroke**.
2. Each fires `sync_local_skin_to_csl` → `_publish_skin_async` → heartbeat POST.
3. `~/.cubeon_launcher/skin_net.json` was stale (username `Shadoww___4577` vs
   config `Light_314`) → `identity_changed` always true → always POSTs.
4. Heartbeat failed (quota) → state never saved → infinite retry.

So one person typing a rename could burn the entire day's KV budget, killing
the waitlist for everyone.

## Fixes (commit 0c47d01)
- **main.py**: rename publish debounced 1.2s after last keystroke / on blur;
  reads the field at fire time (no stale-name closure bug).
- **cubeon/skins.py**: `_record_publish_failure()` writes a 10-min cooldown
  (`retry_not_before`) into skin_net.json; syncs during cooldown are no-ops;
  success clears it.
- **workers**: quota-thrown puts caught → clean `429 kv_write_budget_exhausted`
  (waitlist join, skins heartbeat + TOFU claim + upload). Waitlist reports
  `joined: true` if the email write landed and only the tally count failed.
- **worker/wrangler-skins.toml** added (skins worker had no repo config — was
  deployed ad-hoc; deploy is `npx wrangler deploy -c wrangler-skins.toml`).

Both workers redeployed and verified live: waitlist POST → 429 with honest
message, heartbeat → 429.

## Tests
- `tools/test_skins_net.py` updated for the new failure contract (cooldown
  recorded, identity NOT recorded, no POST during cooldown) — ALL PASS.
- `tools/test_ui_smoke.py` — 41/41.

## Gotcha for next agent
KV writes are **account-wide across all workers** (waitlist, skins, invites).
A spammy client of ANY worker starves them all. The daily budget resets at
00:00 UTC. Deploy commands for all three live workers are now in
`worker/wrangler-*.toml` files.

## Q&A baton
The user wants to do social media to attract users. Funnel blockers before
posting: repo is private (no public releases), and the Friends feature is
disabled in public builds. The web/ waitlist site is DONE and good — it just
needs the KV quota to reset (works again 00:00 UTC) to accept its first
signup.
