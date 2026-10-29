# Bugs, Race Conditions & Design Flaws

> A catalog of concrete issues found in the current codebase. Each entry includes the file, line context, severity, and the exact mechanism of failure.

---

## Critical: Config Corruption on Crash: FIXED (2026-09-14)

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

## High: Server Console Deadlock via Full stdin Pipe: FIXED (2026-08-31)

**File:** `cubeon/server.py`, `send_server_command()` (line ~609)

```python
process.stdin.write(command_text.strip() + "\n")
process.stdin.flush()
```

**Problem:** The server subprocess is started with `stdin=subprocess.PIPE`. If the Minecraft server process isn't reading from stdin (e.g., during startup, GC pause, or if the server is hung), the OS pipe buffer fills up and `flush()` blocks indefinitely. This freezes the thread calling `send_server_command()`, which is typically the UI thread or a click handler - making the entire launcher unresponsive.

**Why it matters:** The Stop button calls `send_server_command(version_id, "stop")`. If the server is mid-startup and not reading stdin, the Stop button deadlocks the UI for up to 45 seconds before the force-kill path kicks in - but the UI thread is already frozen, so the timeout check never runs.

---

## High: User-Agent Strings Contain Profanity: FIXED (2026-09-14)

**Files:** `cubeon/mods.py`, `cubeon/modpacks.py`, `cubeon/icons.py`

```python
MODRINTH_HEADERS = {"User-Agent": f"fuckarch/{APP_NAME.lower()}/1.0"}
```

**Problem:** The User-Agent sent to Modrinth's API contains "fuckarch". Corporate proxies, school networks (the target audience), and Modrinth's own WAF may block or flag requests with profane User-Agent strings. This would silently break mod search/download for users on filtered networks.

**Fix (2026-09-14):** all three now send `Cubeon/<app>/1.0`; `server.py`'s odd
`cubeon-thing/...` was normalized to the same string. If you add a new network
client, never derive its UA from the hostname.

---

## High: No Rate Limiting on Friends WebSocket Messages: STALE (rate limiter exists)

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

## Medium: Race Condition in UUID Ownership (TOCTOU): FIXED 2026-09-07

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

## Medium: `install_local_mod()` Doesn't Validate Source Path: FIXED (2026-09-14)

**File:** `cubeon/mods.py`, `install_local_mod()`

**Fix:** new `_safe_jar_filename()` (also used by `add_mod_file`): replaces
`<>:"/\|?*` + control chars with `_` in the stem and strips trailing dots/
spaces (Windows-rejected). Replace, don't reject - the user picked the file,
not its name.

---

## Medium: `toggle_mod()` / `delete_mod()` Don't Check File Exists: FIXED (2026-09-14)

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

## Medium: Friend Request Auto-Accept Race: VERIFIED NON-ISSUE 2026-09-14

**File:** `worker/cubeon-friends.js`, `onAdd()`

The claim was: two simultaneous `add` frames both check `requestExists` before either writes, leaving two pending requests instead of a mutual acceptance.

That can't happen. A Durable Object runs one event handler at a time, and `onAdd`/`onAccept` are fully synchronous, `this.sql.exec()` is sync, and there is no `await` between the `requestExists` check and the write. Whichever `add` frame the DO processes second therefore always observes the first's request row and takes the auto-accept path. Interleaving is only possible across an `await` (e.g. `onHello`'s `sha256Hex`, whose claim-on-connect INSERT is separately guarded by the PRIMARY KEY re-read). Lesson for future audits: only await-crossing sections in a DO handler are race candidates.

---

## Medium: Background Thread Exceptions Silently Swallowed: FIXED 2026-09-14 (worker paths)

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

## Low: `find_java_for_version()` May Return Too-Old Java: FIXED 2026-09-14 (logged)

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

## Low: Modrinth Cache Never Invalidates: FIXED 2026-09-14 (`local_cache.invalidate()`)

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

## Low: `version_dropdown.value` Used Before Population: FIXED 2026-09-14 (falls back to cfg last_version)

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

## High: Installs "completed" with holes, and the launcher said nothing: FIXED (2026-10-17)

**File:** `cubeon/versions.py` (`_make_resilient_download_file`, `_PatchedMllDownloads`)

mll 8.0's `_helper.download_file` is the only thing that fetches the ~4000 files
a version install needs. It opens the request with **no timeout**, copies the
body with no checksum, and answers a bad HTTP status with `return False`:

```python
r = requests.get(url, stream=True, headers=headers)   # no timeout
if r.status_code != 200:
    return False                                       # caller ignores this
```

Every call site ignores that return value. So a CDN answering **429** to a burst
of asset requests, or a proxy dropping a connection mid-jar, produced an install
that reported success with **files missing**, the game then failed at launch
with nothing in the UI to explain it (the 2026-10-17 report: "download on
instances isn't working on some users"). Cubeon's patched downloader was only
installed when the user could cancel, so an ordinary install had none of it.

**Fix (2026-10-17):** the patch is now installed for **every** install, and the
downloader it installs retries (3 attempts, 1.5s/3s backoff, honouring
`Retry-After` capped at 30s) on network errors, timeouts, 429 and 5xx; **resumes**
with a `Range` request from the bytes already on disk; verifies sha1 and takes
the whole file again on a mismatch; and raises `_MllDownloadError` naming the
file on a permanent 4xx, with `install_version` surfacing that text. Two further
install-wide shortcuts came with it: `install_minecraft_version` is memoised per
version within one install (a loader install used to walk the base two or three
times, see row 31) and a process-wide 32-connection pool replaces mll's
per-phase session of 10, which had made most of its ~32 asset threads build and
discard a TCP+TLS connection per file. Regression:
`tools/test_install_download.py`, `tools/test_install_cancel.py` (rewritten: it
had been passing by accident, because "http://x" failed fast and *that* was the
"abort" it measured).

---

## High: A loader install re-installed the whole base version: FIXED (2026-10-17)

**File:** `cubeon/versions.py`; `minecraft_launcher_lib/mod_loader/__init__.py`

`ModLoader.install` calls `install_minecraft_version` for the base version and
then again for the loader profile, whose json `inheritsFrom`s the base, so
mll's own inheritsFrom branch calls `install_minecraft_version` on the base a
**second** time from inside that call. Forge adds another. Three full passes
over the same ~4000 files, each re-hashing ~1 GB of libraries and assets: the
"installing an instance takes forever" half of the 2026-10-17 report.

**Fix (2026-10-17):** per-install memoisation of `install_minecraft_version`
(the loader profile's own libraries still install, that is real work) plus a
per-process `size+mtime` verified-file cache, so a repeat pass is a `stat()`
rather than a re-read. `install_jvm_runtime` (a second JDK, tens of MB) is also
skipped when `config.launch_java_path()` proves the launch passes its own
`executablePath`, with a comment on why it must NOT be skipped unconditionally.

---

## High: "Not connected to Cubeon" on a perfectly good connection: FIXED (2026-10-17)

**File:** `main.py` (startup friends block), `cubeon/friends.py` (`_run_loop`)

Startup connected to the friends relay only when an identity **predated** the
launch:

```python
had_identity = friends.load_identity() is not None
...
if had_identity:
    friends_client.connect()
```

The theory was that a brand-new identity connects when the Chat tab first opens.
But the Chat tab is only one way in, in-game chat does not trigger the
launcher's connect, so a first-run player stayed "not connected" for their
whole first session while their network was fine. `_on_open` also never reset
the reconnect ladder, so a connection that had been up and then blipped waited
the maximum 30 s to come back.

**Fix (2026-10-17):** connect as soon as an identity exists (minted or
pre-existing); `FriendsClient.connect()` already restarts instead of doubling
up. `_opened_this_round` (set in `_on_open`) resets the backoff after any round
that reached the server. Headless harnesses stub `FriendsClient.connect`, so
they still open no socket.

---

## High: Play appeared mid-install, and pressing it broke the instance: FIXED (2026-10-18)

**File:** `cubeon/modpacks.py` (in-flight registry), `main.py` (`set_button_mode`,
`_sync_play_button`, `on_play_click`, `_begin_install_and_launch`, `prefetch_version`,
`_proactive_mod_repair`)

A modpack install writes the **base Minecraft version and its loader first**, then
downloads the pack's mods into the `(mc_version, loader)` profile, and only writes
`_modpack.json` at the very end. The Play tab's button is derived from a **disk
scan**, and after step 1 that scan already calls the instance installed, so for
the whole mod-download phase the button offered **PLAY on a half-written profile**
(the report: "it isn't fully installed, still it says the Play button while it's
installing mods… that will result in broken stuff"). The install ran entirely in
the Modpacks tab and never touched `state["installing_version"]`, the one claim
the button knew about, and Import reached the same installer by another route, so
a UI flag set only by the Modpacks tab could not have fixed it either.

**Fix (2026-10-18):** `cubeon/modpacks.py` keeps a process-local, refcounted
in-flight registry keyed by **mc_version**, raised in `_install_from_zip` *before*
the first byte lands and released in a `finally` (success, failure and cancel all
clear it; a malformed archive claims nothing). The Play button maps that claim to
a disabled `INSTALLING…` mode, deliberately **not** a Cancel, because the
Modpacks tab owns that install's progress and its cancel. The same claim is
honoured by `on_play_click` and `_begin_install_and_launch` (the Java dialog calls
the latter directly), by the Instances manager's row Play, by the invisible
prefetch (two mll installers on one version folder race on the same jars) and by
the background mod doctor (which would otherwise prune jars still downloading).
A listener (`add_pack_install_listener`) repaints the button the moment the claim
changes, so it can neither outlive a cancel nor linger after success. Regression:
`tools/test_pack_install_guard.py`.

**Later change (2026-10-27):** the background `_proactive_mod_repair` was
removed, so selecting an instance no longer starts a full mod scan. The claim
is also keyed by the exact instance now (`pack_install_for_instance`), not only
by base Minecraft version, so installing a pack for 26.2 cannot lock an
unrelated 26.3 instance. The guard's purpose is unchanged.

---

## High: "A new Cubeon is available" nagged on every launch: FIXED (2026-10-18)

**Current behavior (2026-10-29):** the user requested a startup **Skip / Update**
prompt on later launches while an update is available. Downloads require Update;
the once-per-version marker now limits only OS notifications. The earlier
snackbar behavior below is historical. See `tools/test_launcher_updates.py`.

**File:** `main.py` (startup update check), `cubeon/updater.py` (`should_announce`)

Report: *"the notification of new cubeon release is just spamming and not
stopping like it's just coming up again and again."* Two independent defects,
both about the same message:

1. **The in-app snackbar had no memory whatsoever.** `_offer_update` ran from
   the background check and showed `"Cubeon 1.2.6 is available: Get it"` on
   **every single start** for as long as the user was behind, with no marker
   anywhere. The only "once per version" gate in the tree belonged to the OS
   toast (`osnotify_last_update`), and it also *failed open*: `update_available`
   returns False whenever the toast kind is switched off or no notifier exists,
   so its marker was never written on those machines.
2. **The check ran TWICE per start.** One call passed `cfg["update_token"]`
   (snackbar), the second passed nothing and existed only to fire the OS toast.
   Two GETs against the releases API on every start, and on a private repo the
   token-less one 404s, so the same release could be "up to date" to one handler
   and "newer" to the other.

**Fix (2026-10-18):** one check, one announcement, two channels.
`updater.should_announce(cfg, version)` is the gate: it is a **total function**
(a blank version announces nothing; a non-dict or hostile config still answers
True, because a missed notice is worse than a repeated one) and it **marks the
version in the config in place**, which the caller saves. The call happens
*before* either notice goes out, so a muted notifier or a closed window costs
one message, never a nag on the next start. `main.py::_announce_update` is the
single callback, it saves the marker, fires the optional OS toast, then the
snackbar, and the second check is gone. Regression:
`tools/test_update_notice.py`.

---

## High: the Windows startup job never actually ran the app: FIXED (2026-10-18)

**File:** `tools/test_startup.py`, `tools/test_winwindow.py`

The `Startup tests (Windows)` job was red on **every run since it was added**,
so CI had never once built the launcher's UI on Windows, a green-looking
pipeline with a permanently red gate, and no signal at all on the platform most
users are on. Two Linux-shaped assumptions:

* `test_startup.py` refused **every** outbound connect, to prove the UI thread
  never blocks on the network. But on Windows `socket.socketpair()` is a real
  TCP pair on 127.0.0.1 (CPython's fallback: bind to `_LOCALHOST`, then
  `csock.connect((addr, port))`) and `ProactorEventLoop` builds its self-pipe
  with it, so the patch killed `asyncio.run()` itself. The suite died with
  `OSError: network disabled by tools/test_startup.py` **before `main()`** and
  reported `controls=0` (the UI was never mounted) plus one bogus
  main-thread connect: asyncio's own self-pipe.
* `test_winwindow.py` §1 asserted "returns immediately" for
  `ensure_client_window_visible`, which describes the **off-Windows** no-op
  branch, but the file runs on `windows-latest`, where the module is the real
  thing: with no flet client window it probes until the timeout and answers
  False (4.44 s).

**Fix (2026-10-18):** loopback is now allowed through the connect blocker
(`127.0.0.0/8`, `::1`), while any real host is still recorded **and refused**,
and `socket.create_connection` (the call urllib3 actually makes) is now patched
too, so the invariant is stronger than before. The winwindow timing assertion
is branched on `os.name`. The job now genuinely builds the UI on Windows, which
is where a Windows-only startup crash will finally be visible.

---

## High: the launcher's crashes left no evidence anywhere: FIXED (2026-10-18)

**File:** `main.py` (`__main__`), `cubeon/incident.py` (new)

Report: *"it got crashes on user and me too"*, delivered as a KDE screenshot,
KDE's Crash Reporting System showing **two** dialogs for
`~/.flet/client/flet-desktop-light-0.86.5/flet/flet has encountered a fatal
error and was closed.` That binary is the **flet desktop client** (the
Flutter/GTK window process) dying to a signal; two dialogs mean attempt 1
(hardware GL) and the software-OpenGL retry both died, after which the recovery
ladder gives up and the launcher disappears without a word.

The recovery itself was already correct and deliberate (pre-paint death →
in-process retry with `use_software_gl`; mid-session death → re-exec bounded by
`CUBEON_GPU_RESTARTS`). What was broken was that **no crash could ever be
diagnosed**, for two reasons:

1. every crash message was a `print()` to **stdout**, a user launching Cubeon
   from a desktop menu has no console, so there was nothing they could send;
2. `setup_logging()` was only reached from `main()`, the flet **session**
   callback. A pre-paint crash means `main()` never runs, so logging was never
   configured and `~/.cubeon_launcher/cubeon.log` stayed **completely empty**.
   The only evidence in existence was the screenshot.

**Fix (2026-10-18):** `__main__` configures logging before the session loop, and
every session end is now recorded through `cubeon/incident.py`: INFO for a
clean close (so "the log stops here" is distinguishable from "the user closed
it"), WARNING for a crash with `describe_exit(-11)` → `SIGSEGV`, whether the UI
painted, whether the software-GL fallback was in effect, the session/desktop/
flet versions, and the **tail of the client's own output** (`ClientOutputTail`
keeps the last 25 non-noise lines, collapsing repeats so a frame-timeout storm
cannot bury the earlier context). Both exhausted ladder branches log
`record_giving_up` at ERROR. `incident.client_binary()` additionally names
WHICH client bundle is being spawned, its stub size and whether the Flutter
engine library is present, a PARTIAL unpack of `~/.flet/client/flet-desktop-*`
(flet unpacks once, then trusts it forever) dies on every launch and looks
identical to a driver crash, but is the one client-side fault that is ours to
fix. The module is deliberately **total** (never
raises, never reports a signal death as clean) because it runs where the
launcher is already dying.

Also a second retry dice roll for the OTHER documented flet-client crash class
on Linux, the GTK/Wayland path: `incident.wayland_x11_fallback()` sets
`GDK_BACKEND=x11` **only** on a retry, only on a Wayland session, only when
`DISPLAY` exists (no XWayland → forcing x11 would fail the start outright), and
never when the user chose a backend themselves. Native Wayland stays native for
everyone it works for today. Regression: `tools/test_incident.py`.

**Root cause confirmed the same day, from the maintainer's own core dumps**
(same report, the KDE screenshot came from a friend's machine, the maintainer's
box turned out to have the crash too): Arch, `mesa 1:26.1.6-1`, AMD Polaris
(Ellesmere, RX 470–590). `coredumpctl info` on a run whose `cubeon.log` simply
stops gives

```
#0      libc.so.6                (SEGV_ACCERR)
#1-#7   libgallium-26.1.6-arch1.1.so
#8-#9   libflutter_linux_gtk.so
#10-#18 libgtk-3.so.0 → g_signal_emit → gtk_container_propagate_draw
```

, a Mesa driver fault during a GTK/Flutter paint, three layers below any Python,
in the 26.1.x series that the Mesa release notes and bug reports describe as a
radeonsi/gallivm SIGSEGV regression train (26.1.8 closed the series; 26.2 carries
the fixes, and `mesa 1:26.2.4-1` was already available on the crashing box). So
the honest fix for an affected user is **the Mesa update**, and Cubeon's part is
to (a) name the library in the log, the record now prints `gallium=<lib>`, so
`gallium=libgallium-26.1.6-…` identifies the known bug in one grep, and
(b) survive it: because llvmpipe shares the failing LLVM JIT path with radeonsi,
the retry ladder now escalates `GALLIUM_DRIVER=llvmpipe` → `softpipe` (Mesa's
reference C rasterizer, no JIT at all) on its final attempt, with the attempt
count taken as `max(_retries, CUBEON_GPU_RESTARTS)` so a re-exec'd mid-session
restart escalates too.

---

## Medium: "Dialog is already opened" error banner: FIXED (2026-10-18)

**File:** `cubeon/dialogs.py`

User report: *"The application encountered an error: Dialog is already opened,
this error just came upon a users, they are so random."*

Flet 0.86's `Page.show_dialog()` raises `RuntimeError("Dialog is already
opened")` when the instance is already in `page._dialogs.controls`, and
`cubeon/dialogs.open_dialog()` passed that straight through. The exception
escapes whichever event handler mounted the dialog, so a **no-op**, the user is
looking at that dialog already, surfaced as an application error banner. That
is the "random": anything that can fire twice hits it (a double click, a poll
tick racing a button, a retry). The repo had already grown two one-off
workarounds for exactly this (main.py `_dialog_mounted`, ui/versions.py
`InstancesManager._is_mounted`) while the 25 call sites going through the shared
helper stayed exposed.

**Fix (2026-10-18):** `open_dialog` is now idempotent. Membership in the stack
(not the `.open` flag, flet removes a barrier-dismissed dialog from the stack
*without* clearing it) is checked first and the mounted case is refreshed in
place; a lost race between the check and the call is swallowed only when the
message is the known `already open` one, so any *other* RuntimeError still
surfaces. The suppression is logged at INFO naming the dialog class, so if it
repeats we can find which dialog double-opens. Regression:
`tools/test_dialogs.py`, whose FakePage reproduces flet's real double-mount
raise, and which fails if any shipped module calls `show_dialog` directly.

---

---

## High: "Fix problems" disabled working mods: FIXED (2026-10-18)

**Files:** `cubeon/mods.py`

User report: *"whenever I press fix problems it just disables my sodium and
some mods."*

Exactly what happened: `mod_doctor`'s `depends` pass resolves every dependency a
jar declares against Modrinth, and when a lookup came back empty it treated
that as proof the declaring mod could never load and switched it off
(`toggle_mod`) as a "the game would hard-fail anyway" last resort. But a
profile provides far more mod ids than it has jar files, because Fabric mods
ship other mods **inside** themselves (`META-INF/jars/*.jar`). On the reporting
player's own profile: Fabric API is 43 bundled modules, and Sodium declares
`fabric-block-getter-api-v2`, `fabric-rendering-fluids-v1` and
`fabric-resource-loader-v0`; Modmenu declares four more; c2me declares
`c2me-base`, which it bundles itself. None of those is a Modrinth project, so
every lookup 404'd, and **Sodium, Modmenu and c2me were silently disabled every
single time the button was pressed** - eight "unresolved dependency" hits, three
working mods turned off, no explanation. The user then had to notice and
re-enable them.

**Fix (2026-10-18), two rules:**

1. `_nested_mod_metadata(jar)` indexes every mod id a jar **provides**,
   including jar-in-jar children (depth 2, never raises). A dependency
   satisfied by a bundled module is satisfied - version predicates included,
   with the highest bundled copy winning, because that is the one the loader
   registers. Sodium/Modmenu/c2me now resolve locally with zero network calls.
2. An id that is still unresolved is **reported, never auto-disabled**. Not
   resolving is not evidence of anything: bundled modules, CurseForge-only
   mods, a 404, a rate limit and a renamed project all look identical from
   here. The declarer stays enabled and the report says the dependency
   "isn't installed and couldn't be fetched automatically", so the player
   decides. The game's own dependency screen names a genuinely missing mod far
   more precisely than the launcher can.

The one auto-disable that remains is the `breaks` conflict last resort, which
is decided from two installed jars' own metadata rather than from a failed
lookup.

Regression: `tools/test_doctor_bundled_deps.py` - 19 checks, including the
reported profile end to end (Fabric API + Sodium + Modmenu + a self-bundling
mod, with every network call failing: nothing disabled, nothing reported), a
bundled module that is too old for the predicate (reported, still enabled), a
genuinely missing dependency (reported, still enabled) and a fetchable one
(still installed).

---

## High: "Crashed: Java not found" on a launch where Java plainly worked: FIXED (2026-10-18)

**Files:** `main.py` (`_explain_exit`)

User report: *"it says crashed: no java found bla bla…. minecraft crashes with
this error even if java fine bcz it ran minecraft in first place."*

The user was right on both counts. `_explain_exit` chooses the sentence the
launcher shows after a game exit, and its Java branch read:

```python
if "cannot run program" in low or "no such file or directory" in low and "java" in low:
```

`and` binds tighter than `or`, so this is
`A or (B and C)`, **any** `Cannot run program` line in the game's output was
reported as "Java not found". Worse, `B and C` is almost always true: the launch
command itself, JVM path included (`/usr/lib/jvm/java-21-openjdk/...`), is part
of the output the launcher reads, so the word "java" is present on *every*
launch. Any stray `No such file or directory`, a mod's config, a shader
include, a missing native, a mod shelling out to `xdg-open`, was therefore
reported as a missing JDK, and the actual error line was thrown away. The user
was sent to reinstall Java for a game that had just started a JVM.

**Fix (2026-10-18):** the Java branch now needs a Java-SPECIFIC **line** (not a
substring of the whole log, which is what let the JVM path count as evidence):
`Cannot run program "java"`/`"javaw"`, `Could not create the Java Virtual
Machine`, or `No such file or directory` on a line that also names Java. A
rejected JVM option (`Unrecognized option` + the JVM's own
`Could not create...` line) gets its own message pointing at the JVM arguments
rather than at installing Java. Everything else falls through to the real error
line, and when there is genuinely nothing to go on the message says so and
points at Fix problems, it no longer guesses "check that Java matches", which
the game it just launched had already disproved.

Regression: `tools/test_ui_smoke.py` now drives the reported log shape (JVM
path present + an unrelated missing file) and the genuine cases (`java`,
`javaw`, bad option, wrong class-file version).

---

## Summary Table

| # | Severity | Issue | File(s) |
|---|----------|-------|---------|
| 1 | ✅ Fixed 2026-09-14 | Config corruption on crash (non-atomic write), `cubeon/atomicio.write_json` | `config.py` |
| 2 | ⚠️ Known | Config dict shared across threads without locking (mitigated: skins publish uses a snapshot; skin_net.json exists specifically so background threads never write config) | `main.py` |
| 3 | ✅ Fixed | Server console deadlock via full stdin pipe (2026-08-31) | `server.py` |
| 4 | ✅ Fixed 2026-09-14 | User-Agent contained profanity | `mods.py`, `modpacks.py`, `icons.py`, `server.py` |
| 5 | ✅ Already implemented | (stale entry) sliding-window rate limiter exists in the worker | `cubeon-friends.js` |
| 6 | ✅ Fixed | UUID ownership TOCTOU race (fixed 2026-09-07: re-read after put) | `skins.py`, `cubeon-skins.js` |
| 7 | ✅ Fixed 2026-09-14 | Non-atomic skins metadata writes, `cubeon/atomicio.write_json` | `skins.py` |
| 8 | ✅ Fixed 2026-09-14 | Non-atomic publish state writes, `cubeon/atomicio.write_json` | `skins.py` |
| 9 | ✅ Fixed 2026-09-14 | `install_local_mod()` doesn't sanitize basename, `_safe_jar_filename()` | `mods.py` |
| 10 | ✅ Fixed 2026-09-14 | `toggle_mod()` / `delete_mod()` no existence check, `lexists` guards | `mods.py` |
| 11 | ✅ Fixed 2026-09-14 | DM refusal was a silent drop, now `T.ERROR` frames to the sender (parity-tested) | `cubeon-friends.js` |
| 12 | ✅ Verified non-issue 2026-09-14 (stale claim) | Mutual-add "race": a DO runs message handlers one at a time and `onAdd`/`onAccept` are fully synchronous (no awaits), so the second add always sees the first's request row and auto-accepts | `cubeon-friends.js` |
| 13 | ✅ Fixed 2026-09-14 (worker paths log; UI best-effort left silent by design) | Background thread exceptions silently discarded | Multiple files |
| 14 | ✅ Fixed 2026-09-14 (fallback now logs required-vs-found to the launcher log) | `find_java_for_version()` fallback may return too-old Java | `launch.py` |
| 15 | 🟢 Low (kept) | `get_profile_dir()` creates state as side effect, every current caller intends creation; changing the contract buys nothing pre-beta | `mods.py` |
| 16 | ✅ Fixed 2026-09-14 (`invalidate()` API added; SWR already self-heals) | Modrinth cache never invalidates (24h TTL) | `local_cache.py` |
| 17 | ✅ Fixed 2026-09-14 (rebuild falls back to cfg last_version) | Version dropdown used before population | `main.py` |
| 18 | 🟢 Low | Circular import workaround in cosmetics | `cosmetics.py` |
| 19 | 🟢 Low | P2P hybrid handover incomplete | `p2p.py` |
| 20 | ✅ Fixed 2026-09-14 (visual) | Chat self-avatar rendered as a blank square, `ft.Image(src=<absolute path>)` never loads in Flet 0.86; now base64 bytes with chip fallback | `chat_tab.py` |
| 21 | ✅ Fixed 2026-09-14 (visual) | Stray floating hairline across the chat empty-state pane, header divider is now hidden until a conversation is selected | `chat_tab.py` |
| 22 | ✅ Fixed 2026-09-14 (relay) | Chat history backfill served the OLDEST page, `ORDER BY ts ASC LIMIT ?` returns the stale prefix once a conversation outgrows the 50-message window; now a newest-50 subquery re-ordered chronologically (rowid tiebreak, projected as `rid`) | `cubeon-friends.js` |
| 23 | ✅ Fixed 2026-09-14 (relay) | `decodeURIComponent(pathname)` throws URIError on malformed %-escapes → CF error 1101, in all four workers, `safePathname()` fallback | `cubeon-friends.js`, `cubeon-invites.js`, `cubeon-skins.js` |
| 24 | ✅ Fixed 2026-09-14 (relay) | Unauthenticated WS hello flood: each attempt cost a SHA-256 and each unknown name burned a permanent claim row: IP captured into the attachment at upgrade, 30/10min per-IP pre-auth gate | `cubeon-friends.js` |
| 25 | ✅ Fixed 2026-09-14 (relay); **superseded 2026-10-17, see 29** | invites `RATE_LIMITER` binding was documented ("uses it when present") but never referenced by the code, now gates PUT. The "degrades to no-limit if absent/failing" part of that fix is gone: it degrades to the always-on in-isolate gate | `cubeon-invites.js` |
| 26 | ✅ Fixed 2026-09-14 (relay) | waitlist POST parsed an unbounded JSON body (`request.json()`, no cap, the only worker without one), 1KB Content-Length + decoded-length cap | `cubeon-waitlist.js` |
| 27 | ✅ Fixed 2026-09-14 (relay) | Blocked accounts were still addable via the in-game mod's name path (the `/name/`+`/uid/` HTTP lookups 404 them), both `onAdd` paths now treat blocked as nonexistent | `cubeon-friends.js` |
| 28 | ✅ Fixed 2026-09-14 (relay) | Call invites minted an unbounded `calls` room row per invite, 10/min per-user budget with a visible message | `cubeon-friends.js` |
| 29 | ✅ Fixed 2026-10-17 | **The waitlist had no effective rate limit.** The code was a bare `if (env.RATE_LIMITER)` and the binding was commented out of `wrangler-waitlist.toml`, so the live Worker was open, probed: 9 rapid signups, zero 429s. Two KV writes per signup against the **account-wide** 1k/day budget meant 500 POSTs could break the tally, every real signup, and the skins Worker (same budget). Now an in-isolate 5/min/IP fallback **always** runs and the binding is enabled. Same audit: invites' gate was re-keyed from the caller-chosen `code` (a fresh bucket per request, it limited nothing) to the IP; downloads gained the always-on fallback for the shared 100k/day **request** budget the edge cache cannot refund; skins' cap tightened 60→20/min | `cubeon-waitlist.js`, `cubeon-invites.js`, `cubeon-downloads.js`, `cubeon-skins.js`, `wrangler-waitlist.toml`, `wrangler-invites.toml`, `wrangler-downloads.toml`, `wrangler-skins.toml` |
| 30 | ✅ Fixed 2026-10-17 | **Installs "completed" with holes.** mll 8.0's downloader has no timeout, no retry, no resume and no checksum, and reports a bad status by *returning* `False`, which every caller ignores, so a 429 from the asset CDN or a dropped connection mid-jar was silently skipped and the version list called it installed. Cubeon's patch also ran only for a *cancellable* install. Now every install uses the resilient downloader (timeouts, 3 retries honouring `Retry-After`, `Range` resume, sha1 verify, a hard error naming the file), plus a shared 32-connection pool instead of mll's per-phase 10 | `cubeon/versions.py` |
| 31 | ✅ Fixed 2026-10-17 | A loader install walked the base version **two or three times**, `ModLoader.install` installs the base, then the loader profile whose json `inheritsFrom`s it (and mll's inheritsFrom branch re-installs the base *inside* that call); each pass re-hashed ~1 GB for an answer already known. Now `install_minecraft_version` is memoised per install and a per-process size+mtime cache makes repeat passes `stat()`-only; mll's unused second JDK is skipped when the launch passes its own `executablePath` | `cubeon/versions.py`, `cubeon/config.py`, `cubeon/mod_loaders.py`, `cubeon/modpacks.py`, `main.py` |
| 32 | ✅ Fixed 2026-10-17 | **"Not connected to Cubeon" on a good connection.** Startup connected only when an identity *predated* the launch, so a first-run player who never opened the launcher's Chat tab (in-game chat does not trigger it) stayed offline for their whole first session; a reconnect after a connection that was up also kept the 30 s backoff. Now it connects as soon as an identity exists and resets the ladder after any round that reached the server | `main.py`, `cubeon/friends.py` |
| 33 | ✅ Fixed 2026-10-18 | **Play appeared while a modpack install was still writing the instance.** A pack installs the base version + loader first and its mods last, so a disk scan called it installed for the whole mod-download phase and the button offered PLAY, pressing it launched a half-written profile. The claim was `state["installing_version"]`, which only the Play-tab installer ever set. Now `cubeon/modpacks.py` keeps a refcounted in-flight registry (keyed by mc_version) raised before the first write and released on success/failure/cancel; the button shows a disabled `INSTALLING…` (never a lying Cancel), and the click path, prefetch, Instances manager and mod doctor all stand down while it holds | `cubeon/modpacks.py`, `main.py`, `launcher_core.py` |
| 34 | ✅ Fixed 2026-10-18 | **"A new Cubeon is available" nagged on every launch** ("spamming … coming up again and again"). The snackbar had NO memory at all, so an available update was announced on every start until the user updated; the only once-per-version marker belonged to the OS toast and failed open when toasts were off. A SECOND background check ran without the update token purely for that toast, two GETs per start and two answers about the same release. Now one check, one `_announce_update` callback, gated by the total function `updater.should_announce(cfg, version)`, which marks the version in the config before either notice goes out | `main.py`, `cubeon/updater.py` |
| 35 | ✅ Fixed 2026-10-18 | **The Windows startup job was red on every run, so CI had never built the UI on Windows.** `test_startup.py` banned every connect to prove "no network on the UI thread", but Windows `socket.socketpair()` is a real 127.0.0.1 TCP pair and `ProactorEventLoop`'s self-pipe uses it, so `asyncio.run()` died before `main()` (`controls=0`). `test_winwindow.py` §1 asserted the off-Windows no-op ("returns immediately") while running on windows-latest, where the module is real. Loopback is allowed and real hosts are still recorded+refused (plus `socket.create_connection`, the call urllib3 makes); the timing check is branched on `os.name` | `tools/test_startup.py`, `tools/test_winwindow.py` |
| 36 | ✅ Fixed 2026-10-18 | **A launcher "crash" left no evidence anywhere.** The report was a KDE crash-reporter screenshot: the flet desktop client (`~/.flet/client/flet-desktop-light-0.86.5/flet/flet`) dying to a signal, twice, attempt 1 and the software-GL retry, after which the ladder gives up silently. Recovery was already right; the diagnosis was impossible: every message was a `print()` to a stdout no desktop-launch user sees, and `setup_logging()` was only reached from `main()`, so a PRE-PAINT crash left cubeon.log completely EMPTY. `__main__` now configures logging before the session loop, `cubeon/incident.py` records every session end (kind, signal via `describe_exit`, ui_painted, software-GL state, session/desktop/flet versions, and the client's own last 25 output lines), both give-up branches log at ERROR, and a retry-only `GDK_BACKEND=x11` dice roll covers the GTK/Wayland crash class. Root cause confirmed the same day from the maintainer's own core dumps: SIGSEGV in `libgallium-26.1.6` ← `libflutter_linux_gtk` ← `gtk_container_propagate_draw`, i.e. a **Mesa 26.1.x radeonsi/gallivm regression** (26.2 fixes it), so the record now prints `gallium=<lib>` and the ladder escalates `llvmpipe` → `softpipe` (no LLVM JIT) on its last attempt | `main.py`, `cubeon/incident.py` |
| 37 | ✅ Fixed 2026-10-18 | **"Dialog is already opened" reached users as an application error.** Flet 0.86's `show_dialog()` raises for an instance already in `page._dialogs.controls`, and the shared `dialogs.open_dialog()` passed it through, so any path that could fire twice (double click, poll tick racing a button, retry) turned a no-op into a user-visible error banner. The helper is now idempotent: a mounted dialog is refreshed in place, and only the known `already open` RuntimeError is swallowed, logged at INFO with the dialog class | `cubeon/dialogs.py`, `tools/test_dialogs.py` |
| 38 | ✅ Fixed 2026-10-18 | **"Fix problems" disabled working mods.** The doctor's `depends` pass resolved each dependency id against Modrinth and, when the lookup failed, switched the DECLARING mod off. Mods ship other mods inside themselves (Fabric API = 43 bundled modules; c2me bundles `c2me-base`), so Sodium, Modmenu and c2me were disabled on every run - the lookups could never succeed. Bundled modules now satisfy their dependency (`_nested_mod_metadata`, highest version wins) and an unresolved dependency is reported, never auto-disabled | `cubeon/mods.py`, `tools/test_doctor_bundled_deps.py` |
| 39 | ✅ Fixed 2026-10-18 | **"Crashed: Java not found" when Java was fine.** `_explain_exit`'s Java branch read `"cannot run program" in low or "no such file or directory" in low and "java" in low` - `and` binds tighter, so ANY "Cannot run program" line blamed Java; and since the launch command (JVM path included) is in the log, the word "java" is present on every launch, so any stray "No such file or directory" was reported as a missing JDK and the real error was discarded. Now requires a Java-SPECIFIC line (`Cannot run program "java"`, `Could not create the Java Virtual Machine`, bad JVM option) | `main.py`, `tools/test_ui_smoke.py` |
