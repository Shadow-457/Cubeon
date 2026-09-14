# 2026-09-13 — chat tab identity area fixed

## What was broken
`_apply_identity()` in `ui/chat_tab.py` wrote `you_id_text.value` — but the
control is `your_id_text`. The poller swallows exceptions, so the 12-digit
Cubeon ID never appeared (the "Your friend ID" box stayed empty forever) and
everything after that line in `_apply_identity` (conn dot/banner, avatar,
empty-state sub) silently never painted either.

## What changed
- Fixed the typo; the ID now renders via `_friends.canonical_uid()` so it is
  always the zero-padded 12-digit form.
- Merged the old "You" row + separate ID card into ONE identity card:
  avatar + mono ID + a copy-to-clipboard icon button (only visible once the
  ID exists). Flet 0.86 clipboard is ASYNC: `page.run_task(
  flet.Clipboard().set, value)` — `page.set_clipboard` no longer exists.
  The copy handler try/excepts so headless harnesses (FakePage has neither
  `run_task` nor a clipboard service) don't fail the mega smoke gate.
- Verified: `tools/test_mega_smoke.py` 16/16, `tools/test_ui_smoke.py` 116/116.

## Update later the same day — ID STILL empty is a SERVER problem
User reported the ID still didn't show. Root cause, verified live:
- `~/.cubeon_launcher/identity.json` has NO `uid` field.
- `wss://...workers.dev/ws` hello_ok reply: `{"t":"hello_ok","name":...,
  "uuid":...}` — NO `uid`.
- `POST /claim` 200 reply: `{"ok":true,"name":...,"uuid":...}` — NO `uid`.
- `GET /uid/000000000001` → 404.
So the DEPLOYED worker predates the 2026-09-12 uid feature. The repo's
`worker/cubeon-friends.js` already assigns + back-fills uids (`ensureUid`,
`hello_ok` line ~430 sends `uid: uidStr(uid)`) — it just needs
`cd worker && npx wrangler deploy -c wrangler-friends.toml` run with a
logged-in wrangler. Until then NO client can show an ID.

## VERIFIED FIXED (user deployed the worker)
User ran `cd worker && npx wrangler deploy -c wrangler-friends.toml`
(version 5d2fd403). Live probes afterwards, all with the user's real identity:
- `POST /claim` → 200 with `"uid":"000000000001"` (their account back-filled)
- WS `hello` → `hello_ok` now carries `"uid":"000000000001"`
- `GET /uid/000000000001` → 200 `{"name":"...","online":false}`
`friends.remember_uid("000000000001")` (the exact hello_ok persistence path)
was run and `~/.cubeon_launcher/identity.json` now has the uid, with
`e2ee_sk`/secret preserved. Mega smoke 16/16 after the name removal.
The chat card shows `000000000001` — user is Cubeon friends user #1.
Gotcha: two probe commands in ONE run_commands call raced (cat saw the
pre-write file) — don't parallelize a write and its own verification read.
- Removed the auto-minted `Player_xxxxxxxx` name from the identity card
  (user request + matches the "identity is the ID" design): the card is now
  avatar + 12-digit ID + copy button; the internal name survives only as the
  avatar's hover tooltip. `you_text` control is gone from chat_tab.py.
