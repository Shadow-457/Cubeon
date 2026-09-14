# Bugs, Race Conditions & Design Flaws

> A catalog of concrete issues found in the current codebase. Each entry includes the file, line context, severity, and the exact mechanism of failure.

---

## Critical: Config Corruption on Crash — FIXED (2026-09-14)

**File:** `cubeon/config.py`, `save_config()`

```python
def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
```

**Problem:** This writes directly to the config file. If the process crashes or is killed mid-write, the file is left truncated/corrupt. On next launch, `load_config()` catches the `JSONDecodeError` and returns a **fresh default config** - silently losing every setting the user had (RAM, username, version, skin, etc.).

**Why it's critical:** Every other sensitive write in the codebase uses atomic write (temp file + `os.replace()`): `_write_auth_key()`, `invites._save()`, `_save_publish_state()`, `_write_client_json()`. `save_config()` is the one exception, and it's the most frequently written file.

**Fix (2026-09-14):** new shared helper `cubeon/atomicio.py` (`write_json()` =
unique temp file in the target dir + fsync + `os.replace()`), now used by
`config.save_config`, `skins._save_skins_meta`, and `skins._save_publish_state`
- all three writers from this catalog. **Invariant: any new persisted JSON
state file must go through `cubeon/atomicio.write_json` (or an equivalent
tmp+replace), never a direct `open(path, "w")`.**

---

## Critical: Config Shared Across Threads Without Locking

**File:** `main.py`, `state` dict and `cfg` dict

The `cfg` dict is loaded once at startup and mutated by:
- The UI thread (username changes, skin selection, settings)
- Background threads (`_publish_skin_async()` in `cubeon/skins.py` receives a shallow copy, but `launch_game()` in `cubeon/launch.py` receives the live dict)
- The backup scheduler thread

There is no lock, no synchronization, and no copy-on-write. Two threads writing to `cfg` simultaneously can produce a half-written state that `save_config()` persists to disk.

**Concrete scenario:** User changes username (writes `cfg["username"]`) while `_publish_skin_async` is running with a snapshot - but `launch_game()` is called with the live `cfg` and calls `save_config(cfg)` after `sync_local_skin_to_csl()` modifies `cfg["csl_synced_name"]`. If the user changes username at the same moment, one write silently overwrites the other.

---

## High: Server Console Deadlock via Full stdin Pipe — FIXED (2026-08-31)

**File:** `cubeon/server.py`, `send_server_command()` (line ~609)

```python
process.stdin.write(command_text.strip() + "\n")
process.stdin.flush()
```

**Problem:** The server subprocess is started with `stdin=subprocess.PIPE`. If the Minecraft server process isn't reading from stdin (e.g., during startup, GC pause, or if the server is hung), the OS pipe buffer fills up and `flush()` blocks indefinitely. This freezes the thread calling `send_server_command()`, which is typically the UI thread or a click handler - making the entire launcher unresponsive.

**Why it matters:** The Stop button calls `send_server_command(version_id, "stop")`. If the server is mid-startup and not reading stdin, the Stop button deadlocks the UI for up to 45 seconds before the force-kill path kicks in - but the UI thread is already frozen, so the timeout check never runs.

---

## High: User-Agent Strings Contain Profanity — FIXED (2026-09-14)

**Files:** `cubeon/mods.py`, `cubeon/modpacks.py`, `cubeon/icons.py`

```python
MODRINTH_HEADERS = {"User-Agent": f"fuckarch/{APP_NAME.lower()}/1.0"}
```

**Problem:** The User-Agent sent to Modrinth's API contains "fuckarch". Corporate proxies, school networks (the target audience), and Modrinth's own WAF may block or flag requests with profane User-Agent strings. This would silently break mod search/download for users on filtered networks.

**Fix (2026-09-14):** all three now send `Cubeon/<app>/1.0`; `server.py`'s odd
`cubeon-thing/...` was normalized to the same string. If you add a new network
client, never derive its UA from the hostname.

---

## High: No Rate Limiting on Friends WebSocket Messages — STALE (rate limiter exists)

**File:** `worker/cubeon-friends.js`, `webSocketMessage()`

**Update 2026-09-14:** this entry is stale - the worker now has a per-user
sliding-window rate limiter (see the "Sliding-window rate limiter" helper and
the flood guard that sends `T.ERROR {code: "rate_limited"}` in
`webSocketMessage()`), and `cubeon/friends.py` treats non-200/`rate_limited`
as a cool-off. Original text kept for context:

The Durable Object processes every incoming frame with SQL queries and broadcasts. There is no per-connection or per-user rate limit on:
- Chat messages (`onDm`, `onGroupMsg`)
- Friend requests (`onAdd`)
- Presence updates (`onVersion`, `onStatus`)

A single client can flood the Durable Object with messages, causing:
1. Excessive DO CPU time (billable beyond free tier)
2. Broadcast storms to all connected friends
3. SQLite lock contention degrading all concurrent users

---

## Medium: Race Condition in UUID Ownership (TOCTOU) — FIXED 2026-09-07

**File:** `cubeon/skins.py`, `_publish_skin()` and `cubeon-skins.js`, `ownsUuid()`

The launcher's `_publish_skin()` fires heartbeat + upload as two sequential HTTP requests. Between the heartbeat (which claims the UUID) and the upload (which writes the skin), a second Cubeon install on a different machine could heartbeat the same UUID with a different secret, claiming ownership before the upload arrives.

On the Worker side, `ownsUuid()` checks then writes without a transaction:
```javascript
const owner = await env.SKINS.get(`owner:${uuid}`);
if (owner === null) {
    await env.SKINS.put(`owner:${uuid}`, secretHash);
    return true;
}
```

Two concurrent first-writes for the same UUID can both see `owner === null` and both succeed, leaving the UUID owned by whichever secret wrote last - not the one that was supposed to claim it.

---

## Medium: Non-Atomic Skins Metadata Writes

**File:** `cubeon/skins.py`, `_save_skins_meta()` (line ~68)

```python
def _save_skins_meta(meta: dict) -> None:
    with open(SKINS_META_PATH, "w") as f:
        json.dump(meta, f, indent=2)
```

Same problem as `save_config()` - non-atomic write. If the process crashes mid-write, `skins.json` is corrupt and all custom skin registrations are lost.

---

## Medium: Non-Atomic Publish State Writes

**File:** `cubeon/skins.py`, `_save_publish_state()` (line ~143)

```python
def _save_publish_state(state: dict) -> None:
    try:
        with open(_PUBLISH_STATE_PATH, "w", encoding="utf-8") as f:
            json.dump(state, f, indent=2)
    except OSError:
        pass
```

Non-atomic. A crash here loses the publish state, causing the next launch to re-upload the skin (wasting KV writes on the free tier).

---

## Medium: `install_local_mod()` Doesn't Validate Source Path — FIXED (2026-09-14)

**File:** `cubeon/mods.py`, `install_local_mod()`

**Fix:** new `_safe_jar_filename()` (also used by `add_mod_file`): replaces
`<>:"/\|?*` + control chars with `_` in the stem and strips trailing dots/
spaces (Windows-rejected). Replace, don't reject - the user picked the file,
not its name.

---

## Medium: `toggle_mod()` / `delete_mod()` Don't Check File Exists — FIXED (2026-09-14)

**File:** `cubeon/mods.py`

**Fix:** both guard with `os.path.lexists(full)` first (lexists: a dangling
store link still counts). `toggle_mod` raises a clean "refresh the mod list"
ValueError; `delete_mod` returns - the goal (entry gone) is already achieved.
If the file was deleted externally (antivirus, another process, manual cleanup), these raise an unhandled `FileNotFoundError` that propagates to the UI as a raw traceback.

---

## Medium: DM Conversation Key Ordering Bug

**File:** `worker/cubeon-friends.js`, `dmConv()` (line ~397)

```javascript
function dmConv(a, b) {
    return "d:" + [a, b].sort().join(":");
}
```

This sorts by **string** comparison, which means `"alice" > "bob"` is true (lexicographic). This is correct for canonical names.

**Update 2026-09-14:** the catalog's original claim ("echo runs unconditionally") is stale - current `onDm()` guard-returns on `!to || !text || !areFriends`, so the echo does NOT run for a rejected DM. But the remaining flaw was the mirror image: the refusal was **completely silent**, so a sender whose message bounced (bad name, empty text, or not friends) saw nothing at all - the UI renders its own message optimistically and only treats it as delivered on the echo. **Fixed:** `onDm` now sends `T.ERROR` frames (`dm_bad_recipient` / `dm_empty` / `dm_not_friends`) to the sender, which `friends_service._on_error` toasts. Parity is asserted by `tools/test_friends.py` ("worker's onDm refuses with an error frame, not silence").

---

## Medium: Friend Request Auto-Accept Race — VERIFIED NON-ISSUE 2026-09-14

**File:** `worker/cubeon-friends.js`, `onAdd()`

The claim was: two simultaneous `add` frames both check `requestExists` before either writes, leaving two pending requests instead of a mutual acceptance.

That can't happen. A Durable Object runs one event handler at a time, and `onAdd`/`onAccept` are fully synchronous — `this.sql.exec()` is sync, and there is no `await` between the `requestExists` check and the write. Whichever `add` frame the DO processes second therefore always observes the first's request row and takes the auto-accept path. Interleaving is only possible across an `await` (e.g. `onHello`'s `sha256Hex`, whose claim-on-connect INSERT is separately guarded by the PRIMARY KEY re-read). Lesson for future audits: only await-crossing sections in a DO handler are race candidates.

---

## Medium: Background Thread Exceptions Silently Swallowed — FIXED 2026-09-14 (worker paths)

**Files:** `main.py`, `cubeon/skins.py`, `cubeon/launch.py`, `cubeon/p2p.py`

Throughout the codebase, daemon threads catch `Exception` at the top level and discard it:

**Fix (2026-09-14):** the worker-path backstops now log with full traceback
via the central `logging_setup` file log (console only at WARNING):
`skins._publish_skin` ("best-effort, will retry"), main.py's name-contest
check / mod-repair / late window worker / backup scheduler, `launch.py`'s
system-Java scan, and `p2p.py`'s session loops. Intentionally-silent UI
best-effort catches (window geometry, dev toggles, scrim hide) were left as
`pass` - they fail on machines without xrandr etc. by design, and logging
them would be noise. `local_cache.cached_call`'s background refresh also
logs its failures now instead of a bare pass.

---

## Low: `find_java_for_version()` May Return Too-Old Java — FIXED 2026-09-14 (logged)

**File:** `cubeon/launch.py`, `find_java_for_version()` (line ~88)

The function prefers the **lowest** Java that satisfies the version requirement, but falls back to `java_path or sys_java or "java"` when no candidate meets the requirement. The fallback path returns whatever `java` resolves to, which may be too old - the caller then launches Minecraft with it, which prints a cryptic Java version error instead of the clear message the function was supposed to provide.

---

## Low: Profile Metadata Created as Side Effect

**File:** `cubeon/mods.py`, `get_profile_dir()` (line ~112)

```python
def get_profile_dir(mc_version, loader):
    ...
    if not os.path.isfile(meta_path):
        with open(meta_path, "w", encoding="utf-8") as f:
            json.dump({"mc_version": mc_version, "loader": loader}, f)
    return path
```

A "get" function that creates state as a side effect. Any code that calls `get_profile_dir()` to *check* whether a profile exists will inadvertently create it, including the metadata file. This makes it impossible to distinguish "profile existed" from "profile was just created."

---

## Low: Modrinth Cache Never Invalidates — FIXED 2026-09-14 (`local_cache.invalidate()`)

**File:** `cubeon/local_cache.py`, `get()` (line ~12)

```python
def get(namespace, key, max_age=86400):
    ...
    if max_age and time.time() - payload.get("time", 0) > max_age:
        return None
    return payload.get("value")
```

The default `max_age` is 86400 (24 hours). This means:
- A mod that was removed from Modrinth stays "available" for 24 hours
- A new version of a mod isn't seen for 24 hours
- A search result set is stale for 24 hours

There is no manual cache invalidation mechanism and no way for the user to force a refresh.

---

## Low: `version_dropdown.value` Used Before Population — FIXED 2026-09-14 (falls back to cfg last_version)

**File:** `main.py`, `rebuild_skin_section()` (line ~620)

```python
def rebuild_skin_section():
    skin_section_container.content = build_skin_section(
        page, cfg,
        ...
        mc_version=version_dropdown.value, mc_loader=state.get("mod_loader"),
        ...
    )
```

`version_dropdown.value` is `None` until the version list is populated (which happens on a background thread after startup). If `rebuild_skin_section()` runs before that thread completes (e.g., the user clicks Profile immediately on launch), the skin section is built with `mc_version=None`, which may cause CSL status to report incorrectly.

---

## Low: `cosmetics.py` Circular Import Workaround

**File:** `cubeon/cosmetics.py`, `set_hat()` (line ~163)

```python
def set_hat(cfg, hat_id):
    ...
    from . import skins  # lazy: skins imports this module at the top
```

This is a runtime import to avoid a circular dependency (`skins.py` imports `cosmetics.py` at module level). While it works, it means:
1. The import happens on every `set_hat()` call (negligible but unnecessary)
2. If `skins.py` ever fails to import, the error surfaces here in an unexpected place
3. Static analysis tools and IDEs can't resolve the reference

---

## Low: `p2p.py` Incomplete Hybrid Handover

**File:** `cubeon/p2p.py`, `HybridSession`

The relay-first hybrid handover strategy is partially implemented. The `HybridSession` class exists but several methods referenced in the docstring (`p2p_punch_plan`, `p2p_direct_up`) are called but the class is very large (~1500+ lines) with multiple TODO-style comments about edge cases that aren't fully handled:

- The spray coordination assumes clocks are within a few hundred milliseconds
- `HANDOVER_UDP_CONFIRM_S` is a fixed timeout that doesn't adapt to measured RTT
- Legacy peer compatibility (`p2p_direct_up`) has a fixed 5-second window

---

## Summary Table

| # | Severity | Issue | File(s) |
|---|----------|-------|---------|
| 1 | ✅ Fixed 2026-09-14 | Config corruption on crash (non-atomic write) — `cubeon/atomicio.write_json` | `config.py` |
| 2 | ⚠️ Known | Config dict shared across threads without locking (mitigated: skins publish uses a snapshot; skin_net.json exists specifically so background threads never write config) | `main.py` |
| 3 | ✅ Fixed | Server console deadlock via full stdin pipe (2026-08-31) | `server.py` |
| 4 | ✅ Fixed 2026-09-14 | User-Agent contained profanity | `mods.py`, `modpacks.py`, `icons.py`, `server.py` |
| 5 | ✅ Already implemented | (stale entry) sliding-window rate limiter exists in the worker | `cubeon-friends.js` |
| 6 | ✅ Fixed | UUID ownership TOCTOU race (fixed 2026-09-07: re-read after put) | `skins.py`, `cubeon-skins.js` |
| 7 | ✅ Fixed 2026-09-14 | Non-atomic skins metadata writes — `cubeon/atomicio.write_json` | `skins.py` |
| 8 | ✅ Fixed 2026-09-14 | Non-atomic publish state writes — `cubeon/atomicio.write_json` | `skins.py` |
| 9 | ✅ Fixed 2026-09-14 | `install_local_mod()` doesn't sanitize basename — `_safe_jar_filename()` | `mods.py` |
| 10 | ✅ Fixed 2026-09-14 | `toggle_mod()` / `delete_mod()` no existence check — `lexists` guards | `mods.py` |
| 11 | ✅ Fixed 2026-09-14 | DM refusal was a silent drop — now `T.ERROR` frames to the sender (parity-tested) | `cubeon-friends.js` |
| 12 | ✅ Verified non-issue 2026-09-14 (stale claim) | Mutual-add "race": a DO runs message handlers one at a time and `onAdd`/`onAccept` are fully synchronous (no awaits), so the second add always sees the first's request row and auto-accepts | `cubeon-friends.js` |
| 13 | ✅ Fixed 2026-09-14 (worker paths log; UI best-effort left silent by design) | Background thread exceptions silently discarded | Multiple files |
| 14 | ✅ Fixed 2026-09-14 (fallback now logs required-vs-found to the launcher log) | `find_java_for_version()` fallback may return too-old Java | `launch.py` |
| 15 | 🟢 Low (kept) | `get_profile_dir()` creates state as side effect — every current caller intends creation; changing the contract buys nothing pre-beta | `mods.py` |
| 16 | ✅ Fixed 2026-09-14 (`invalidate()` API added; SWR already self-heals) | Modrinth cache never invalidates (24h TTL) | `local_cache.py` |
| 17 | ✅ Fixed 2026-09-14 (rebuild falls back to cfg last_version) | Version dropdown used before population | `main.py` |
| 18 | 🟢 Low | Circular import workaround in cosmetics | `cosmetics.py` |
| 19 | 🟢 Low | P2P hybrid handover incomplete | `p2p.py` |
| 20 | ✅ Fixed 2026-09-14 (visual) | Chat self-avatar rendered as a blank square — `ft.Image(src=<absolute path>)` never loads in Flet 0.86; now base64 bytes with chip fallback | `chat_tab.py` |
| 21 | ✅ Fixed 2026-09-14 (visual) | Stray floating hairline across the chat empty-state pane — header divider is now hidden until a conversation is selected | `chat_tab.py` |
| 22 | ✅ Fixed 2026-09-14 (relay) | Chat history backfill served the OLDEST page — `ORDER BY ts ASC LIMIT ?` returns the stale prefix once a conversation outgrows the 50-message window; now a newest-50 subquery re-ordered chronologically (rowid tiebreak, projected as `rid`) | `cubeon-friends.js` |
| 23 | ✅ Fixed 2026-09-14 (relay) | `decodeURIComponent(pathname)` throws URIError on malformed %-escapes → CF error 1101, in all four workers — `safePathname()` fallback | `cubeon-friends.js`, `cubeon-invites.js`, `cubeon-skins.js` |
| 24 | ✅ Fixed 2026-09-14 (relay) | Unauthenticated WS hello flood: each attempt cost a SHA-256 and each unknown name burned a permanent claim row — IP captured into the attachment at upgrade, 30/10min per-IP pre-auth gate | `cubeon-friends.js` |
| 25 | ✅ Fixed 2026-09-14 (relay) | invites `RATE_LIMITER` binding was documented ("uses it when present") but never referenced by the code — now gates PUT, degrades to no-limit if absent/failing | `cubeon-invites.js` |
| 26 | ✅ Fixed 2026-09-14 (relay) | waitlist POST parsed an unbounded JSON body (`request.json()`, no cap — the only worker without one) — 1KB Content-Length + decoded-length cap | `cubeon-waitlist.js` |
| 27 | ✅ Fixed 2026-09-14 (relay) | Blocked accounts were still addable via the in-game mod's name path (the `/name/`+`/uid/` HTTP lookups 404 them) — both `onAdd` paths now treat blocked as nonexistent | `cubeon-friends.js` |
| 28 | ✅ Fixed 2026-09-14 (relay) | Call invites minted an unbounded `calls` room row per invite — 10/min per-user budget with a visible message | `cubeon-friends.js` |
