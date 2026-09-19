# Bugfix: the CI-red test suite (2026-09-18)

`main`'s CI had been red since at least 2026-09-16. The user asked for it
fixed. Three of the failures were **real product bugs** (not test bugs); three
were **flaky tests** (races in the harnesses themselves). Every one reproduced
locally and now has a deterministic regression check.

## 1. P2P: a peer FIN truncated the tail of the stream — PRODUCT BUG

- **Where:** `cubeon/p2p.py`, `PunchSession._handle_frame` (the `_FIN` branch)
  and `_tcp_delivery_loop`; also `_drain_tcp_outbound`'s FIN send.
- **Symptom:** `tools/test_p2p_transport_stress.py` failed ~1 run in 5 with
  `AssertionError: 118535` (a 120000-byte transfer cut short).
- **Root cause (measured, not guessed):** the FIN branch immediately called
  `_stop_with_reason()`, which closes the local TCP socket. Everything the
  peer had already sent but the delivery loop had not yet written - observed
  exactly 2 payloads still in `_tcp_in_queue` when the FIN landed - was
  destroyed. Minecraft's own TCP framing cannot survive a half-delivered
  tail, so this is a real "world stops syncing / client hangs" class bug, not
  just a test artifact.
- **Fix:** a received FIN no longer tears the session down. It sets
  `_remote_eof`; the delivery loop drains the queue, and only then stops the
  session with the honest reason (`"Minecraft TCP connection closed"`), so the
  local side sees a clean end-of-stream. The FIN we *send* is also now held
  back until every DATA frame is ACKed - a FIN overtaking a retransmission
  would tell the receiver an incomplete stream was complete.
  `reconnect()` resets both flags.
- **Verification:** 25/25 stress runs green (was ~4/5). New deterministic
  regression check `fin_drain_check()` in `tools/test_p2p_transport.py`
  delivers the FIN *before* the delivery loop runs; it fails against the old
  code every time and passes now.
- **NOT fixed (documented):** `RelaySession` (the WebSocket relay path) has the
  same shape - `_delivery_loop`/`_outbound_loop` stop immediately on
  `_stop_with_reason("Minecraft closed the connection")` with `_in_queue`
  possibly non-empty. It is NOT the code path the failing test exercised, the
  relay multiplexes over a reliable WebSocket, and the launch path prefers the
  direct UDP transport. Deliberately left alone in this pass; worth the same
  drain-before-close treatment if a relay-mode truncation is ever reported.

## 2. Half-installed versions could vanish from the version list — PRODUCT BUG

- **Where:** `cubeon/versions.py`, `get_installed_versions()` pass 2.
- **Symptom:** CI's `tools/test_version_integrity.py` died with
  `KeyError: 'netdeath'`; the suite passes on most machines.
- **Root cause:** the tolerant scan deduped on the json's *declared id*
  (`if real_id in found: continue`). A half-finished install keeps its
  template manifest, so its folder ("netdeath") declares the id of the version
  it was copied from ("1.20.1"). Whenever `os.listdir()` happened to yield the
  real "1.20.1" folder first, the broken folder was skipped - so the install
  appeared as *neither installed nor incomplete*. It just disappeared from the
  launcher, and any `installed[...]` lookup would KeyError.
- **Fix:** dedupe by **folder**, which is the only thing the strict scan keys
  on. Every physical folder now appears exactly once, deterministically.
- **Verification:** new check forces the colliding `os.listdir` order (via a
  patched `V.os.listdir`) and asserts the half-install still shows as
  incomplete; it fails on the old code and passes now. `39 -> 40` checks, all
  green over 8 consecutive runs.

## 3. `test_content_doctor.py` — TEST BUG

Two faults in the last block of section 10:

- it overrode `CONTENT_TYPES[...]["dir"]` while `list_content`/`delete_content`
  resolve through `["subdir"]`, so the listing looked at the wrong folder and
  came back empty (`FAIL folder packs appear in the installed list  set()`);
- it called both helpers without a loader, which the strict
  `require_loader_and_version` guard (added 2026-09-17) correctly rejects with
  `ValueError: Can't manage resource packs: no Minecraft version selected.`

Fixed by overriding `subdir` and passing `mc_version="1.21.11", loader="fabric"`.
The product behavior was correct; the strict guard did its job.

## 4. `test_milestones.py` — PRODUCT BUG (the test caught a real wart)

`end_play_session()` wrote an empty `{"sessions": {}}` husk instead of removing
`play_session.json`, so "is the record cleared?" read false forever - and the
watchdog/diagnostics ask exactly that. `_write_play_session()` now deletes the
file when the sessions map is empty. 22/22.

## 5. `test_launch_fixes.py` — TEST BUG

Used an `exploding_write` helper that was never defined (`NameError`), and
compared the post-failure file against a `base` snapshot taken before the
sanitize section legitimately rewrote it. Now defines the helper (an `OSError`
raiser, which is what `_write_client_json` documents) and snapshots the file
immediately before the failure. 58/58.

## 6. `test_ui_smoke.py` 5g — TEST BUG (race)

The check asserted "the grid builds around a placeholder, then the worker fills
it in", but the worker could finish *before* the test walked the grid - so on a
loaded CI runner no placeholder Image was found and both checks failed for
correct behavior. The test now gates `core.render_local_skin_preview` for the
`ux-thumb-render` thread only (a synchronous UI-thread render - the actual
regression - would still be caught, because the placeholder is then already
gone), so the assertion is deterministic. 148/148 over repeated runs.

## 7. `test_mod_compile.py` — PRODUCT BUG (Java)

CI's javac 25 flagged a dangling doc comment in `CubeonClientScreen.java`
(a `/** ... */` block orphaned by the doc comment after it) under `-Werror`:
`warning: [dangling-doc-comments]`. Turned the orphaned block into a plain
`/* ... */` comment. Mod jars rebuilt (`assets/jars/`), per the jar invariant.

## Also in this pass

- CI storage: the repo had ~19 GB of stale Actions artifacts against a 500 MB
  quota, so **every** artifact upload failed. All deleted, and
  `retention-days: 7` added to each `upload-artifact` step (as an input under
  `with:` - putting it at step level silently broke the workflow file).
- Repo hygiene: mangled commit message fixed, stray `pi/*` branch removed,
  `v1.0.0` + `clean-baseline` annotated tags, `mod/.gradle/` ignored.
