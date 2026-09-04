# Bugs, Race Conditions & Design Flaws

> A catalog of concrete issues found in the current codebase. Each entry includes the file, line context, severity, and the exact mechanism of failure.

---

## Critical: Config Corruption on Crash

**File:** `cubeon/config.py`, `save_config()` (line ~87)

```python
def save_config(cfg: dict) -> None:
    with open(CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
```

**Problem:** This writes directly to the config file. If the process crashes or is killed mid-write, the file is left truncated/corrupt. On next launch, `load_config()` catches the `JSONDecodeError` and returns a **fresh default config** - silently losing every setting the user had (RAM, username, version, skin, etc.).

**Why it's critical:** Every other sensitive write in the codebase uses atomic write (temp file + `os.replace()`): `_write_auth_key()`, `invites._save()`, `_save_publish_state()`, `_write_client_json()`. `save_config()` is the one exception, and it's the most frequently written file.

**Fix:** Write to a `.tmp` file, then `os.replace()` - same pattern as `_write_auth_key()`.

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

## High: User-Agent Strings Contain Profanity

**Files:** `cubeon/mods.py` (line ~27), `cubeon/modpacks.py` (line ~29)

```python
MODRINTH_HEADERS = {"User-Agent": f"fuckarch/{APP_NAME.lower()}/1.0"}
```

**Problem:** The User-Agent sent to Modrinth's API contains "fuckarch". Corporate proxies, school networks (the target audience), and Modrinth's own WAF may block or flag requests with profane User-Agent strings. This would silently break mod search/download for users on filtered networks.

---

## High: No Rate Limiting on Friends WebSocket Messages

**File:** `worker/cubeon-friends.js`, `webSocketMessage()`

The Durable Object processes every incoming frame with SQL queries and broadcasts. There is no per-connection or per-user rate limit on:
- Chat messages (`onDm`, `onGroupMsg`)
- Friend requests (`onAdd`)
- Presence updates (`onVersion`, `onStatus`)

A single client can flood the Durable Object with messages, causing:
1. Excessive DO CPU time (billable beyond free tier)
2. Broadcast storms to all connected friends
3. SQLite lock contention degrading all concurrent users

---

## Medium: Race Condition in UUID Ownership (TOCTOU)

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

## Medium: `install_local_mod()` Doesn't Validate Source Path

**File:** `cubeon/mods.py`, `install_local_mod()` (line ~220)

```python
def install_local_mod(src_path: str, mc_version: str | None, loader: str | None) -> str:
    ...
    filename = os.path.basename(src_path)
    dest = os.path.join(profile_dir, filename)
```

**Problem:** `src_path` is user-supplied (from a file picker). If the filename contains characters that are valid on one OS but not another (e.g., colons on Windows, null bytes), the copy can fail silently or write to an unexpected location. The function doesn't sanitize the basename.

---

## Medium: `toggle_mod()` / `delete_mod()` Don't Check File Exists

**File:** `cubeon/mods.py`, `toggle_mod()` (line ~196), `delete_mod()` (line ~202)

```python
def toggle_mod(mc_version, loader, filename):
    profile_dir = get_profile_dir(mc_version, loader)
    full = os.path.join(profile_dir, filename)
    new_name = ...
    os.rename(full, os.path.join(profile_dir, new_name))  # FileNotFoundError if missing
```

If the file was deleted externally (antivirus, another process, manual cleanup), these raise an unhandled `FileNotFoundError` that propagates to the UI as a raw traceback.

---

## Medium: DM Conversation Key Ordering Bug

**File:** `worker/cubeon-friends.js`, `dmConv()` (line ~397)

```javascript
function dmConv(a, b) {
    return "d:" + [a, b].sort().join(":");
}
```

This sorts by **string** comparison, which means `"alice" > "bob"` is true (lexicographic). This is correct for canonical names. However, if a client sends a non-canonical name that `canonName()` rejects (returns null), the DM silently drops because `onDm` checks `if (!to || ...)` - but the error isn't surfaced to the sender. The sender sees their message echoed back via `sendTo(me, T.DM, frame)` even if the recipient never received it, because the echo runs unconditionally:

```javascript
this.sendTo(to, T.DM, frame);   // may be a no-op if to is null
this.sendTo(me, T.DM, frame);   // always runs - sender sees "sent"
```

---

## Medium: Friend Request Auto-Accept Race

**File:** `worker/cubeon-friends.js`, `onAdd()` (line ~254)

```javascript
if (this.requestExists(other, me)) return this.onAccept(me, myDisplay, { name: msg.name });
```

If Alice sends a friend request to Bob, and Bob simultaneously sends one to Alice, both `onAdd` calls check `requestExists` before either writes. Both see no existing request, both insert, and the result is two pending requests instead of a mutual acceptance. The friends never become friends until one of them manually accepts.

---

## Medium: Background Thread Exceptions Silently Swallowed

**Files:** `main.py`, `cubeon/skins.py`, `cubeon/launch.py`, `cubeon/p2p.py`

Throughout the codebase, daemon threads catch `Exception` at the top level and discard it:

```python
# skins.py
except Exception:
    pass  # "Backstop only"

# main.py
except Exception:
    pass
```

While this prevents crashes, it also means bugs in background threads (skin publish failures, WebSocket errors, P2P transport errors) are completely invisible. There is no log output, no metric, no way to know something went wrong.

---

## Low: `find_java_for_version()` May Return Too-Old Java

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

## Low: Modrinth Cache Never Invalidates

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

## Low: `version_dropdown.value` Used Before Population

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
| 1 | 🔴 Critical | Config corruption on crash (non-atomic write) | `config.py` |
| 2 | 🔴 Critical | Config dict shared across threads without locking | `main.py` |
| 3 | 🟠 High | Server console deadlock via full stdin pipe | `server.py` |
| 4 | 🟠 High | User-Agent contains profanity | `mods.py`, `modpacks.py` |
| 5 | 🟠 High | No rate limiting on Friends WebSocket | `cubeon-friends.js` |
| 6 | 🟡 Medium | UUID ownership TOCTOU race | `skins.py`, `cubeon-skins.js` |
| 7 | 🟡 Medium | Non-atomic skins metadata writes | `skins.py` |
| 8 | 🟡 Medium | Non-atomic publish state writes | `skins.py` |
| 9 | 🟡 Medium | `install_local_mod()` doesn't sanitize basename | `mods.py` |
| 10 | 🟡 Medium | `toggle_mod()` / `delete_mod()` no existence check | `mods.py` |
| 11 | 🟡 Medium | DM echo runs even when recipient lookup fails | `cubeon-friends.js` |
| 12 | 🟡 Medium | Friend request mutual-add race condition | `cubeon-friends.js` |
| 13 | 🟡 Medium | Background thread exceptions silently discarded | Multiple files |
| 14 | 🟢 Low | `find_java_for_version()` fallback may return too-old Java | `launch.py` |
| 15 | 🟢 Low | `get_profile_dir()` creates state as side effect | `mods.py` |
| 16 | 🟢 Low | Modrinth cache never invalidates (24h TTL) | `local_cache.py` |
| 17 | 🟢 Low | Version dropdown used before population | `main.py` |
| 18 | 🟢 Low | Circular import workaround in cosmetics | `cosmetics.py` |
| 19 | 🟢 Low | P2P hybrid handover incomplete | `p2p.py` |
