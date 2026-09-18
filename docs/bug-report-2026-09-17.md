All 6 hunts complete. Here is the consolidated report.

---

# CUBEON BUG REPORT — 2026-09-17
**6 parallel agents, read-only hunts, every finding verified by an executed probe or exact source-path evidence. Deduplicated count: ~85 bugs. 3 already fixed during collection (marked ✅).**

Severity: **P0** = data loss / unusable feature • **P1** = wrong behavior, security, crash • **P2** = robustness/cosmetic/race.

---

## A. SOCIAL / IDENTITY LAYER (16 findings)

| # | Sev | Bug | Location | Fix direction |
|---|---|---|---|---|
| S1 | **P0** | Worker caps E2EE envelopes at 2,000 chars → normal 1,400-char messages become unreadable ciphertext; no error to either side | `worker/cubeon-friends.js:575,1041`, `friends_service.py:1276` | envelope-sized wire limit; reject cleanly |
| S2 | **P0** | Fast relay echo beats `_out_pending` registration → sent message vanishes from own transcript | `friends_service.py:1280-87` | register pending before send, correlate by ID |
| S3 | P1 | Service reads roster `metadata` but client persists `peer_metadata` — cached metadata ignored | `friends_service.py:686`, `friends.py:888,923` | consume actual contract, merge |
| S4 | P1 | Roster reorder makes a stale row look "new" → resurrects an old username | `friends_service.py:695-703` | freshness by handle, not list index |
| S5 | P1 | Presence events never update roster online/version until full roster arrives | `friends_service.py:2893-95` | merge presence into roster record |
| S6 | P1 | Conversation with existing history never backfills offline-received messages | `friends_service.py:1301-16` | reconcile on connect regardless of emptiness |
| S7 | P1 | Offline seed attempt burned permanently (marked seeded before send success) | `friends_service.py:1312-16` | mark after success, reset on reconnect |
| S8 | P1 | History dedupe by (sender, plaintext) — two identical "hello again" collapse | `friends_service.py:1184-89` | dedupe by relay message ID |
| S9 | P1 | Read markers never persisted unless another message arrives → unread again after restart | `friends_service.py:1334-40` | mark store dirty on read advance |
| S10 | P1 | Cancel relies on remote `call_end` echo; offline cancel leaves session+transport alive (dup of P7-#3) | `friends_service.py:2476` | local idempotent teardown first |
| S11 | P1 | Worldgate HTTP handlers never registered (`set_worldgate_handler`/`set_joinpassword_handler` don't exist) → 503 | `friends_service.py:224-5,382-5`, `local_api.py:388-402` | add missing setters/bindings |
| S12 | P1 | Whitelist uses relay handle, not Minecraft username → wrong MC account whitelisted | `friends_service.py:2380,2384,788` | resolve validated MC username; refuse unknown |
| S13 | P1 | Offline invite failure: bare `call_end` for unknown room → stuck `ringing_out`, sync waits full timeout | `worker:764-767`, `friends_service.py:2951,3202,3225` | correlated failure (recipient+kind) |
| S14 | P1 | Declining a request doesn't refresh the *requester's* roster | `worker:556-560` | refresh both counterparts |
| S15 | P1 | Cached peer pubkey never refreshes after key rotation → messages to dead key | `friends_service.py:1217-19,1245` | cache expiry + recovery path |
| S16 | P2 | History frames carry no UID/username metadata (bypass `sendTo()` enrichment) | `worker:742-743` | enrich history envelope |

## B. LAUNCH PATH / WATCHDOG (23 verified, 3 suspected)

| # | Sev | Bug | Location |
|---|---|---|---|
| L1 | P1 | Overlapping launches stage shared mods dir → second launch replaces first's profile mid-spawn | `launch.py:573,628` |
| L2 | P1 | Older exit callback clears the newer game's running state | `main.py:2693-2700` |
| L3 | P2 | Overlapping launches overwrite each other's playtime record; exit deletes the other's | `launch.py:689`, `main.py:2690`, `milestones.py:138-174` |
| L4 | P2 | Failed second launch truncates first game's `game.log`; simultaneous games share one log | `launch.py:603-6,629,657` |
| L5 | P1 | Imported profile with `UseParallelGC` + injected `UseG1GC` → JVM refuses to start | `launch.py:210-227,432,441` |
| L6 | P1 | Failed reinstall deletes *intact, unrelated* jars (all pre-captured) | `versions.py:373-404` |
| L7 | P1 | Integrity check validates first arbitrary `.jar` in dir, not the launch target | `versions.py:39-42,196` |
| L8 | P1 | Loader profiles with missing base version marked "installed" (inheritsFrom bypasses check) | `versions.py:36-37,140-143` |
| L9 | P1 | Malformed version JSON (valid JSON, non-object) crashes the whole version scan | `versions.py:130-135,196` |
| L10 | P1 | Client-JSON concurrent writers share one `.cubeon-tmp` name → cross-clobber | `launch.py:289-301` |
| L11 | P1 | Stale/corrupt cache jar always beats valid bundled jar (cache-first, no validation); `mod_stamp` blind to it | `cubeonfriends.py:190-196,239-252` |
| L12 | P2 | Omitting optional `cfg` (None) silently disables friends injection (exception swallowed) | `launch.py:455,510,521-2` |
| L13 | P2 | Version-ID parser: `26.1-pre-1` → `(1,0,0)`; Forge IDs `1.20.1-forge-47.2.0` → bracket 26 | `cubeonfriends.py:93-109` |
| L14 | P1 | Loader lookup substring match: `1.21.1` matches `fabric-loader-...-1.21.11` | `mod_loaders.py:70-74`, `main.py:2636-8` |
| L15 | P2 | Java-min tuples unpatched: 1.17→8 (should be 16), 1.18→16 (should be 17) | `launch.py:56-63,79-82` |
| L16 | P2 | Java-discovery error path: local `import logging` → `UnboundLocalError` in handler | `launch.py:124-8,147` |
| L17 | P1 | Relative `CUBEON_GAME_DIR` → child resolves doubled path (`relative-game/relative-game`) | `paths.py:35-37`, `launch.py:441,631` |
| L18 | P2 | Disk-space check skips when parent dirs missing → no guard | `paths.py:136-141` |
| L19 | P2 | Instant game exit leaves Discord presence "Playing" | `main.py:2693-8,2785-96,2808` |
| L20 | P2 | Failed spawn leaves `running_version` set (delete guard stuck) | `main.py:2739,2817-27` |
| L21 | P2 | "Vanilla fallback" still stages/launches with unsupported loader | `main.py:2643-4,2751-2,2776` |
| L22 | P2 | Two launcher processes lose each other's watchdog sessions (load-once + private lock) | `watchdog.py:48-65,135-149` |
| L23 | P2 | Username regex `$` accepts trailing newline (inconsistent with watchdog validator) | `config.py:385-390` |
| L24-26 | P2* | SUSPECTED: Windows process detachment flags; PyInstaller env contamination; legacy PID-only watchdog records | `launch.py:610-623`, `watchdog.py:73-81` |

## C. MODS / MODPACKS / CONTENT (21 findings)

| # | Sev | Bug | Location |
|---|---|---|---|
| C1 | P1 | Modpack override `open(dest,"wb")` follows symlink → **overwrites shared global-store jar**, other profile changes too, cached SHA now wrong | `modpacks.py:413` |
| C2 | P1 | Profile switch with same filename keeps OLD resourcepack bytes ("A" shown, wanted "B") | `content.py:818,844-856` |
| C3 | P1 | Mod compatibility cached by project only → wrong `compatible` across versions/loaders | `mods.py:1007-22,1039` |
| C4 | P1 | In-flight install rereads mutable UI state → installs into the wrong profile | `ui/mods_tab.py:1673-77,1742` |
| C5 | P1 | Resourcepack/shader detail dialog installs via the MOD installer | `ui/mods_tab.py:1852,1223` |
| C6 | P1 | Concurrent installs share one temp filename → FileNotFoundError, one wins | `global_mod_cache.py:256` |
| C7 | P1 | Folder resourcepacks flattened to loose basenames on modpack import | `modpacks.py:292-296` |
| C8 | P1 | Failed content-store copy leaves final-looking partial files | `content.py:244-247` |
| C9 | P1 | Disabled dependency counted as satisfied → skipped, install "succeeds" incomplete | `mods.py:1573-6,1677-9` |
| C10 | P1 | Capes metadata direct write truncates `capes.json` on failure | `capes.py:76-77` |
| C11 | P2 | Gallery bookkeeping same destructive write pattern | `gallery.py:258-259` |
| C12 | P2 | Installed-content check passes loader as version ID → always `[]`, contradictory UI | `ui/mods_tab.py:270-1,1949-51`, `content.py:280-1` |
| C13 | P2 | Older search completion overwrites newer results (no generation token) | `ui/mods_tab.py:954,995` |
| C14 | P2 | Fast CurseForge results wiped by later Modrinth completion | `ui/modpacks_tab.py:605-16` |
| C15 | P2 | Per-chunk download progress calls `page.update()` (99×) instead of `refresh()` | `ui/mods_tab.py:1705,1739` |
| C16 | P2 | Detail install reports success while required deps failed (result ignored) | `ui/mods_tab.py:1223-45` |
| C17 | P2 | CSL download ignores publisher hashes → no integrity verification | `csl.py:452-455` |
| C18 | P2 | CSL best-effort contract leaks `net.DownloadError` | `csl.py:445,456` |
| C19 | P2 | Read-only list scans create profiles as a side effect | `mods.py:452,169`, `content.py:294,183` |
| C20 | P2 | Sodium Extra satisfies the Sodium requirement (substring match) | `perf_mods.py:52-58` |
| C21 | P2 | Version-art misses not cached (truncated report; same class: memo bug) | `version_art.py:119-129` |

## D. P2P / SERVERS / WORLDGATE (24 findings)

| # | Sev | Bug | Location |
|---|---|---|---|
| P1# | P1 | Host HybridSession constructed without `send_signal` → outbound relay frames silently dropped, still "connected" | `friends_service.py:3110`, `p2p.py:1131` |
| P2# | P1 | Relay fallback sets `connected` before launch → `_maybe_finish_join` (needs `connecting`) never fires; joiner never launches | `friends_service.py:2661,2545` |
| P3# | P1 | Offer-prep exception leaks transport + room (only `_set_failed`) | `friends_service.py:3162` |
| P4# | P1 | Old host callbacks (LAN port / process-exit) mutate the *replacement* session | `friends_service.py:1970,1992` |
| P5# | P2 | Ignored `call_invite` failure → unrecoverable `ringing_out` | `friends_service.py:2059` |
| P6# | P1 | Cancel mid-sync leaves local mods disabled; no sync cancellation signal | `p2p.py:1715`, `friends_service.py:3426,3232` |
| P7# | P1 | Mod-sync timeout never observed by service state machine (stuck `connecting`) | `p2p.py:1746`, `friends_service.py:3426` |
| P8# | P2 | STUN padding `attr_len % 4` wrong → valid odd-length responses unparsed | `p2p.py:265` |
| P9# | P2 | Sync-report eviction forgets rooms without `call_end` | `friends_service.py:1442` |
| P10# | P1 | Delayed reply from an old room overwrites the new comparison | `friends_service.py:1877,1636` |
| P11# | P1 | Truncated 2-byte Paper fixture counts as installed (2-byte + existence checks only) | `server.py:659,419` |
| P12# | P2 | `install_server()` default `progress_cb=None` → `'NoneType' not callable` on known length | `server.py:645` |
| P13# | P1 | Old server exit watcher pops the *replacement's* registry entry | `server.py:942` |
| P14# | P1 | Interrupted local Connect install = partial file classified "installed" (direct copy) | `minekube.py:337,250` |
| P15# | P2 | Minekube address parsing drops explicit `:port` | `minekube.py:394,427` |
| P16# | **P1-SEC** | Legacy fallback path skips worldgate authorization → relay transport created with gate armed but unverified | `friends_service.py:3349,2630` |
| P17# | **P1-SEC** | Worldgate challenge/proof sent as PLAIN signal dicts — not E2EE as documented | `worldgate.py:19`, `friends_service.py:3027,2181` |
| P18# | P2 | Failed proof derivation retains typed password in session memory | `friends_service.py:2172` |
| P19# | P1-SEC | Sync chunks accepted with no request/room/size bounds (100 unsolicited entries, invalid index) | `friends_service.py:1909,1922` |
| P20# | P1-SEC | Chunk-list extended to peer-declared count → 200,000-slot allocation from one declaration | `p2p.py:1784` |
| P21# | P1-SEC | Cache-hit mod install lacks filename containment (path escape) | `p2p.py:1655` |
| P22# | P1-SEC | Asset receiver ignores extension allowlist; symlink escape accepted | `p2p.py:1920,1953` |
| P23# | P1-SEC | `p2p_answer` bypasses room/peer/phase checks | `friends_service.py:3345` |
| P24# | — | Negative controls passed: nonce replay rejected; no password disk persistence; no gate.py escalation defect found | — |

## E. UI / FRAMEWORK (2 verified)

| # | Sev | Bug | Location |
|---|---|---|---|
| U1 ✅ | P1 | Inspector weight Dropdown uses `on_change` → TypeError on use (Flet 0.86 needs `on_select`) — **FIXED & verified** | `inspector.py:301` |
| U2 | P1 | Window events compared lowercase vs enum `RESIZED` → real resize/move never persist geometry | `main.py:4852` |

## F. INFRA / NET / CONFIG (3 verified)

| # | Sev | Bug | Location |
|---|---|---|---|
| F1 ✅ | P1 | Invalid geometry input wiped the saved file (non-atomic write) — **FIXED & verified** | `config.py:232-243` |
| F2 ✅ | P1 | `load_config` raised TypeError on non-object JSON (`[]`/`null`/`42`) — **FIXED & verified** | `config.py:179-194` |
| F3 | P1 | Two concurrent `save_config` writers: older in-flight save overwrites the newer one (last-finisher wins) | probe-verified against `config.py`/`atomicio.py` |

Also: `tools/test_modpacks.py:214` has one outdated assertion (expects resourcepacks in the shared game dir; model changed to profile+staging) — test bug, not product bug.

---

## Priorities for the fix pass

**Wave 1 — security & data loss:** P16–P23 (worldgate auth + P2P input validation), S1, S2, C1, C10, F3, L6, L7.
**Wave 2 — broken features:** S11, P1#/P2#, P6#/P7#, C2, C4, C5, L5, L11, L14, U2, S3–S9.
**Wave 3 — robustness/races/cosmetics:** everything else, L24–26 only after Windows verification.

The report is complete and delivered. Say the word (or just "fix") and I'll start Wave 1 — fixes will each come with a regression probe and the relevant suites re-run, same discipline as the three fixes already landed (all currently green: ui_smoke 124/0, production 50/0, mega-static 12/0).
