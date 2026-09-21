# Fixed friends add-by-ID connectivity (stale worker deploy)

- **Agent:** Cline
- **Date:** 2026-09-20
- **Task:** "Fix the connectivity of Cubeon friends chat and overall" — both
  clients adding each other by ID got "No Cubeon user with ID 00000001/2".

## What I did

1. **No repo code was wrong.** Traced the whole path: `ui/chat_tab.py` →
   `FriendsService.add_friend` → `_add_friend_uid` → WS `add {uid}` +
   `_verify_add_uid` REST `check_uid` → `worker/cubeon-friends.js`
   `onAdd`/`nameByUid`/`httpUidLookup`. All consistent on 8-digit IDs.
2. **Probed production** (`cubeon-friends.hamza-457-shahbaz.workers.dev`):
   `/uid/00000001` → 404 but `/uid/000000000001` → 200 — the DEPLOYED worker
   was still the pre-2026-09-19 twelve-digit build. The 8-digit-ID change
   (agents/2026-09-19_codex-eight-digit-cubeon-ids.md) was never deployed.
3. **Deployed the current worker** with
   `npx wrangler deploy -c wrangler-friends.toml` (installed wrangler
   temporarily, removed `worker/node_modules` afterwards). Version
   ec009763-aae7-4b66-b407-b62b0d6579a0.
4. **Fixed stale tests**: `tools/test_friends.py` still fed fake server
   payloads legacy 12-digit UIDs and expected them persisted verbatim; the
   8-digit change made `canonical_uid()` migrate them, so 6 checks failed
   (claim-persists-uid, roster metadata ×5). Rewrote the literals to their
   canonical 8-digit forms ("000000000042"→"00000042", etc.).

## How I verified

- Production: `/uid/00000001` → 200 `{"name":"Player_33416699","uid":"00000001"}`
  and `/uid/00000002` → 200; legacy 12-digit form now 404s (as designed).
- `worker/test-worker.mjs` ALL CHECKS PASSED; `tools/test_friends.py` 95/95.
- `git status` clean except this note + the test fix (pet gifs are
  pre-existing untracked seasonal assets, not mine).

## Q for the next agent

Both accounts' UIDs were already sequential (1, 2) in the DO, so nothing
re-issues on first contact — but if any user reports a WRONG friend pairing,
check `ensureUid()`'s legacy reissue path in the worker.