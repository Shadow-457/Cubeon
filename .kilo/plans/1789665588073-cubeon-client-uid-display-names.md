# Cubeon Client: Minecraft display names, stable Cubeon IDs

## Agreed outcome
- Every player shown in Cubeon Client uses their Minecraft username as a display name. Duplicate usernames are allowed.
- The permanent, zero-padded 12-digit Cubeon ID identifies an account and is how users add/distinguish friends.
- No separate in-game name editor. Username editing stays in the launcher and must not change the Cubeon account, UID, friends, or messages.
- While a game is running, its launch-time Minecraft username wins. Launcher edits apply socially after that game exits, and to subsequent launches.
- Update shared launcher social labels where necessary so the launcher and mod agree; no unrelated UI redesign.

## Verified defects
- The committed mod source already removes Account rename controls and reads the Minecraft session username (`mod/src/main/java/com/cubeon/client/CubeonClientScreen.java:828`, `:1275`). An older deployed or already-loaded jar likely explains the reported editor; artifact freshness remains unverified.
- `FriendsService.roster_payload()` supplies `you_uid`, but `cubeon/local_api.py:238–255` drops it and `mod_stamp` from the actual `/friends` response.
- Remote roster/request/session labels still reuse internal relay handles. The protocol does not publish a separate Minecraft username.
- Legacy service rename calls claim a different handle; the worker creates a new row/UID without migrating relationships. This must not become the username-update mechanism.
- Working-tree changes observed before planning are only tracked Gradle cache files. Preserve them; do not stage or revert them incidentally.

## Architecture and boundaries
Keep existing relay handles as immutable internal keys. This is a public identity/display correction, not a database-wide rekey. Preserve friend graph, request targets, chat/history keys, room IDs, encryption inputs, secrets and existing UIDs. Never derive an account from a display name or silently merge duplicate names.

Add optional `minecraft_username` metadata beside existing `name` (internal handle) and `uid`. Use this explicit username as the display label; do not create another editable nickname field or reinterpret the worker's existing `names.display` column. For requests, retain existing string arrays and add parallel rich detail arrays. For sessions retain `peer` and add peer metadata. Missing metadata displays `Cubeon ID <uid>`, or a neutral `Player`/unavailable state when UID is also absent—never a hidden relay handle, including tooltips and notices.

Minecraft usernames are display metadata, not proof of ownership of a Minecraft profile. Verified game-account linking, server access-policy changes, historical account merging/recovery and a wholesale UID-based wire-protocol rewrite are out of scope. Do not repurpose new display labels as whitelist or authorization inputs; existing related identity-matching shortcomings are not solved by this task.

## Ordered implementation
1. **Close legacy rename and bridge gaps.**
   - In `cubeon/friends_service.py` and `cubeon/local_api.py`, make legacy rename entry points return a friendly instruction to change the Minecraft username in the launcher, without claiming/reconnecting/mutating identity. Audit `cubeon/friends.py` callers so existing identities are never replaced by username edits; retain initial account creation and same-handle authentication.
   - Explicitly forward self UID, `mod_stamp`, self metadata and request detail fields through the real `/friends` HTTP response. Maintain old response fields and token checks.
2. **Publish separate username metadata.**
   - In `worker/cubeon-friends.js`, add an idempotent nullable username schema migration with no uniqueness constraint and no UID/graph changes.
   - Extend authenticated hello and a metadata-update message in `cubeon/friends.py` and the worker. Validate using current Minecraft username rules, update only the authenticated account, skip unchanged writes, persist last-known usernames for offline rows and resend on reconnect.
   - Include metadata and UID in presence, roster, UID lookup, request details, invite and other identity-bearing events. Notify pending-request counterparts as well as friends when labels change. Keep protocol constants and legacy fields compatible.
3. **Use one effective Minecraft username source.**
   - Reconcile from validated committed config while no game is running; while running use the exact username captured by the common `cubeon/launch.py:launch_game` path, including host/join launches.
   - Reuse `cubeon/watchdog.py` session persistence rather than a second competing session tracker. Capture successful process launch, session identity and username atomically; clear only a matching exited session and recover live-session metadata on launcher restart. Do not treat an unrelated/reused PID as sufficient evidence.
   - Wire startup, committed name edits in `main.py`, successful launches, matching exits and relay reconnects to metadata reconciliation. Failed launches must not pin a new username; publishing failures must not block gameplay. Preserve existing supported launch concurrency behavior and ensure stale exit callbacks cannot overwrite a newer session.
4. **Normalize metadata without changing routing.**
   - Add a centralized handle-keyed peer metadata/label resolver in `cubeon/friends_service.py` and extend existing roster cache parsing in `cubeon/friends.py`.
   - Carry metadata through roster, requests, players and session payloads. Use safe labels in generated request/invite/sync/chat notices and confirmations. Preserve original action recipients and E2EE key derivation in `cubeon/e2ee.py` unchanged.
   - Do not infer missing usernames from legacy custom handles. Atomically persist any modified cache state.
5. **Update all social display surfaces.**
   - In `Bridge.java`, parse rich friend/request/player/session models, retaining internal action keys and canonical UID strings. Tolerate older payloads.
   - In `CubeonClientScreen.java`, separate row key from label; update friend/request rows, selected details, play/sync headings, session banners, tooltips and action feedback. Keep username and read-only ID in Account, with no rename control. Add friends by UID only in the new UI.
   - Show UID as a secondary identifier in lists/details and recipient confirmations so duplicate usernames remain distinguishable. Sorting or metadata refresh must never change the selected account/action target.
   - Apply the same label resolver to `ui/chat_tab.py`; preserve handle-keyed conversations and unread state. Refresh local identity and selected conversation headers on metadata changes and remove internal-handle tooltips.
   - Audit world-player/badge consumers for assumptions that a label is an account key. Cosmetic matching must not route account actions or alter Minecraft whitelist behavior. Leave verified world identity mapping out of scope.
6. **Validate and deliver the actual artifacts.**
   - Add regression coverage before rebuilding. Then run both mod-era builds through the existing build script, which refreshes bundled and cache jars. Inspect script destinations first; do not touch `~/.minecraft`.
   - Verify the selected cache/assets/staged jar hashes against the rebuilt artifacts. Minecraft must fully restart to load new classes.
   - New worker metadata must be deployed for full remote-name support. Keep deployment as an explicit release step, not a silent live-service mutation. Backward-compatible clients must still work with an older worker using the documented safe fallbacks.
   - The desktop entry launches `~/.local/opt/Cubeon/cubeon`, not this source tree. After mod jars are bundled, rebuild the launcher with the existing PyInstaller spec and arrange installation of the validated build, preserving a rollback copy. Do not report source-only edits as a deployed fix.

## Regression coverage and gates
- Exercise the **actual authenticated `/friends` HTTP route**, not only Java JSON fixtures: self UID, leading zeros, freshness stamp, rich requests and metadata survive end to end.
- Two accounts with identical usernames remain distinct; add/accept/remove/invite/chat target the intended existing identity. Username changes preserve UID, handles, secrets, E2EE keys, friendship/request graph, unread state and history.
- Legacy rename requests do not mutate identity; initial creation still works. Test metadata persistence against actual worker SQL semantics, including repeat schema migration and duplicate names.
- Verify remote name updates during an open conversation/request list, offline cached labels, reconnect replay, missing UID/metadata, older worker payloads, invalid usernames and metadata-publication failure.
- Verify running-session precedence, launcher rename during play, failed launch, exit, restart recovery and stale exit callbacks. Test both menu and in-world Account displays.
- Audit user-facing text from new payloads for leaked internal handles; confirm no in-game rename controls and no name-based adding in updated UI.
- Run `python3 tools/test_friends_service.py`, `python3 tools/test_friends.py`, `python3 tools/test_mod_bridge.py`, `python3 tools/test_client_json.py`, `python3 tools/test_mod_compile.py`, `python3 tools/test_mod_matrix.py`, `python3 tools/test_ui_smoke.py`, `python3 tools/test_production.py`, and `node worker/test-worker.mjs`, plus focused new worker tests. Extend existing harnesses where possible.
- Run `python3 tools/test_mega_smoke.py --static` and the full mega smoke gate. The mod compile harness uses `javac -Xlint:all -Werror`; run any additional lint/typecheck commands found in repository configuration.
- Run `python3 tools/build_mod_jars.py` after mod edits; perform a two-client in-game check using duplicate usernames and distinct UIDs against the intended compatible relay. If live deployment/testing is unavailable, report that limitation explicitly.

## Rollout and completion
Deploy additive worker support first, then the matching launcher plus rebuilt mod jars; restart the game and verify the installed path. Older clients remain wire-compatible but can still show old handles until updated. Rollback must preserve the additive database fields and existing identities. No automatic account recovery or destructive migration.

Implementation is complete when both clients show Minecraft usernames, UIDs are visible and stable, name editing never changes identity, duplicates route correctly, legacy fallback is honest, and the tested artifacts—not merely source—are available for installation. No implementation or tests were performed during this planning session.
