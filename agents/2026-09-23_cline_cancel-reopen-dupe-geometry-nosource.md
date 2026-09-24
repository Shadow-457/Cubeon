# Cancel requests, reopen dupes, window position, source-free artifacts (2026-09-23, Cline)

- **Agent:** Cline
- **Date:** 2026-09-23
- **Task:** four reports: "theres no way to cancle pending req we sent", chat
  re-dups on every reopen ("close Cubeon open then their chat the last msgs
  they sent comes again duped"), "make sure the exe appimage and .deb cannot
  leak my real source code ... re build them", and "the window of cubeon
  launcher seems to always open to top left no matter where i close".

## What I did

### 1. Cancel a pending outgoing request
The Worker's `onDecline` only deleted `(requester=other, target=me)` — the
receiver declining. A requester withdrawing their OWN request had no server
path at all. Now one DECLINE frame covers both orderings
(`DELETE ... WHERE (requester=? AND target=?) OR (requester=? AND target=?)`),
and the Chat tab's outgoing row has a **Cancel** pill wired to
`service.decline` (same forward helper the incoming Decline uses, with a
"Request to X canceled." status). Parity checks added to tools/test_friends.py.
**The Worker needs redeploying** for the cancel to work in production.

### 2. Chat re-duped on every reopen (the real one)
`_hydrate_chat_store` rebuilt each saved message WITHOUT its `id` or
`envelope`. Those are the dedupe keys `_chat_append` matches against, so the
first history backfill after every restart re-appended the same rows — and it
compounded every restart (the user's "duped again and again"). Fixed:
hydrate keeps both fields, and skips entries already present (key = id → else
envelope → else (dir,text,ts)), seeded from the room BEFORE the loaded rows so
a double hydrate is a no-op (the constructor already hydrates). Old stores
that already accumulated dupes heal on the next load.

### 3. Window always opened top-left
Two bugs: flet's `WindowEventType` spells drags **both** `move`/`moved` (and
`resize`/`resized`) but the save tuple only listed `move`/`resized`, so a drag
was never captured and the session-end save wrote the placeholder geometry;
and `_reveal_window` only re-centered, never re-asserted a SAVED position —
the same late native write that stomps centering stomps a restore on some
Linux clients. Fixed both (tuple + post-map re-assert of left/top/size when a
real saved position exists and the window isn't maximized).

### 4. No source code in shipped artifacts
`templates/*.py` (all the palettes) was copied into every artifact as DATA by
7 build paths (`--add-data templates`), and the macOS script copied the WHOLE
`mod/` tree (Java sources). `apply_template()` imports templates as modules,
so the data copy was pure redundancy — removed from Cubeon.spec and all six
scripts, keeping `--collect-submodules templates` (bytecode in the PYZ).
macOS now bundles only `mod/brackets.json`, matching Windows.

## How I verified
- `tools/test_friends_service.py`: new "S10" block (5 checks) — id/envelope
  survive a reload, the history replay after reopen does NOT duplicate, and an
  already-duplicated store heals on load. Suite 368 passed (4 fails are the
  known pre-existing HEAD failures, verified earlier on a pristine worktree).
- `tools/test_friends.py` 97/0 (incl. the 2 new worker/client parity checks).
- `tools/test_ui_smoke.py` 159/0 — §4c also gained 3 geometry guards
  (both event spellings, the post-map re-assert, the placeholder guard).
- `test_chat_optimistic` 12/0, `test_faces` 11/0, `mega --static` 12/0,
  `test_seasonal` 106/0.
- Linux artifacts rebuilt (AppImage + deb) and then scanned for readable
  `.py`/`.java` — see the rebuild line below.

## Notes for the next agent
- The Worker change is source-only until someone runs `wrangler deploy`
  (`worker/README.md`) — the launcher half is inert without it.
- If a stale `chat_store.json` from before the fix still shows dupes, one
  reopen now collapses them (id-keyed) — no manual deletion needed.
- The geometry fix only helps after ONE clean session: the old file may hold a
  placeholder; the reveal now re-asserts whatever the file says, and a drag +
  close writes the real numbers.

## Question for the next agent
The friends Worker has no runnable test harness (only source-parity checks in
tools/test_friends.py), so the bidirectional DELETE is verified by reading its
text, not by executing it against a DO/SQL stub. Worth porting the skins
worker's stub-KV harness pattern to cubeon-friends.js so request/decline/cancel
semantics get executed rather than grepped?