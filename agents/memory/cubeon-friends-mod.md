# Cubeon Session Memory - In-Game Friends Button (Fabric Mod)

Date: 2026-08-29. Feature: a "Friends" button injected into Minecraft's own
pause menu (Escape) by a Fabric mod the launcher auto-injects at launch.
Everything below was verified live against MC **26.1.2 (Fabric, loader 0.19.3,
mixin 0.17.3)**.

## Feature architecture (all pieces in place & working)
- `cubeon/local_api.py` - local bridge: HTTP on 127.0.0.1, credentials in
  `~/.cubeon_launcher/local_api.json` (`{"port":…, "token":…}`), endpoints
  `/friends` `/invite` `/status` `/cancel`, token via `X-Cubeon-Token` header.
  Started in `main.py` (`local_api.start()`), stopped at exit.
- `friends_tab.py` providers wire the `/invite` endpoint into the existing
  `start_hosting_p2p` flow - P2P backend unchanged.
- `mod/` - Fabric mod `cubeon-friends-1.0.0.jar`:
  - `mixin/PauseScreenMixin.java` - injects at `init()` TAIL of
    `PauseScreen` (26.x renamed GameMenuScreen→PauseScreen). Adds a "Friends"
    button below the lowest existing widget by scanning `children()` for
    `AbstractWidget.getY()+getHeight()`. Deliberately NO `@Shadow` members -
    only public `Screen` API → version-universal.
  - `CubeonFriendsScreen.java` - **widget-only** screen (see the 2026-09-01
    round below): `Screen` lifecycle + `addRenderableWidget` +
    Button/EditBox/StringWidget only, no `render`/`mouseClicked`/`keyPressed`
    override and no graphics class, which is what lets ONE source tree build
    both namespace eras. (Earlier rounds used LinearLayout/FrameLayout/
    repositionElements - those are gone, they don't exist in 1.20.1.)
  - `Bridge.java` - talks to the launcher bridge; reads the token file,
    hand-parses JSON with regexes (no JSON lib shipped).
- `cubeon/cubeonfriends.py` - Phase 3: auto-injects the jar at launch
  (fabric+quilt only), copying from `~/.cubeon_launcher/cache/`.

## Hard-won build knowledge (26.x, no gradle on this machine)
- **MC 26.x is unobfuscated** - no mappings. Compile the mod **directly
  against the real jar** `~/.minecraft/versions/26.1.2/26.1.2.jar` instead of
  hand-written stubs:
  `javac -proc:none -nowarn -cp "26.1.2.jar:sponge-mixin-0.17.3.jar:fabric-loader-0.19.3.jar:brigadier-1.3.10.jar" -d out $(find mod/src/main/java -name '*.java')`
- **Must use JDK 25 javac** (`/tmp/jdks/jdk-25.0.4.1+1/bin/javac`) - the game
  jar is class-file version 69 (Java 25); `javac --release 21` cannot read it.
  brigadier is needed on the cp because `Component` superinterface chain pulls
  in `com.mojang.brigadier.Message`.
- **Stub approach (previous rounds) caused 3 crashes** - JVM resolution is
  name+descriptor, so every stub signature must match the runtime *exactly*:
  1. `LocalPlayer` package: real is `net.minecraft.client.player`, NOT
     `net.minecraft.client.multiplayer` (→ `NoSuchFieldError` on `Minecraft.player`).
  2. `GuiEventListener` lives in `net.minecraft.client.gui.components.events`,
     NOT `...components` (→ `NoClassDefFoundError`).
  3. `Component.literal()/empty()` return `MutableComponent` (not `Component`),
     and `Screen.addRenderableWidget` erases to
     `(Lnet/minecraft/client/gui/components/events/GuiEventListener;)...`.
  **Lesson: skip stubs entirely; compile against the real jar.**
- Verify any fix by extracting the class from the jar and
  `javap -c -p` - compare Field/Method refs against `javap -s` of the real
  runtime classes. Useful inspection commands:
  `unzip -l 26.1.2.jar | grep <Name>`; `unzip -p jar path/Class.class | javap -s -p /dev/stdin` (note: javap can't read /dev/stdin - extract to a file first).
- Deploy target jars (keep all 4 in sync, verify with md5sum):
  `mod/build/libs/`, `~/.cubeon_launcher/cache/`,
  `~/.minecraft/mods/`, `~/.cubeon_launcher/mod_profiles/26.1.2-fabric/`
  (last one is a SEPARATE file from ~/.minecraft/mods, not a link).
  Update with `jar uf <jar> -C out com/`.
- Game jar's `fabric.mod.json` has no `minecraft` constraint (universal),
  `environment: client`. Known cosmetic warning: "broken icon, loading default
  icon" - no icon in fabric.mod.json (deferred).

## Bridge/UX robustness fixes (final round)
- Mod read the token file exactly once per screen open → race when launcher
  was mid-rewrite or just restarted → showed "Cubeon launcher isn't running".
- Fix: `Bridge.reload()` = fast single read (render-thread safe);
  `Bridge.reloadWithRetry(10, 500)` = background retry loop (~5 s), logs
  `[Cubeon] local bridge not found after retries` to STDERR on final failure.
- Screen shows "Looking for the Cubeon launcher..." and probes on a daemon
  thread; on success calls `minecraft.execute(() -> { clearWidgets(); init(); })`
  to rebuild - never block/sleep on the render thread.
- Verified bridge live: `ss -tlnp` shows listener; `curl -H "X-Cubeon-Token: …"
  http://127.0.0.1:port/friends` returns `{"friends": []}` (empty list is
  expected until a friend is online).
- **GOTCHA:** `local_api.json` writes numbers UNQUOTED (`{"port": 42043, ...}`).
  The mod's tiny regex JSON parser originally only matched `"key": "value"`
  (quoted) → the port was never found → mod permanently said "launcher isn't
  running" even though the bridge was up (found via the game-log line
  `[Cubeon] local bridge not found after retries`). Fixed with a second
  NUMBER pattern `"(\w+)"\s*:\s*([0-9]+)` tried as fallback in
  `Bridge.extract()`. Lesson: when hand-parsing the launcher's JSON, always
  handle both quoted strings and bare numbers.

## In-game friend adding / request handling (2026-08-30 round)
- New bridge endpoints in `local_api.py`: `POST /add`, `POST /accept`,
  `POST /decline` (body `{"name": ...}` → `{"ok": bool, "error": str|None}`);
  handlers registered in `friends_tab.py` via
  `local_api.set_add_handler / set_accept_handler / set_decline_handler`
  (thin lambdas forwarding to the existing `FriendsClient` WebSocket senders
  `client.add_friend / accept_request / decline_request` - friends backend
  untouched). `/friends` now also returns `"requests_in": [...]` (list of
  names, filtered to strings).
- Mod `Bridge.java`: `addFriend/acceptRequest/declineRequest(name)` (POST,
  return null on success or an error string), `extractBool(body, key)` helper,
  and `requestsIn()` (parses the `"requests_in": ["A", "B"]` array from
  /friends).
- Mod `CubeonFriendsScreen.java`: add-friend row (26.1 `EditBox` +
  "Add Friend" button; `new EditBox(minecraft.font, 0,0,w,h,Component)`,
  `setHint`, `setInitialFocus` all exist in 26.1.2) plus per-request rows with
  Accept/Decline. Actions run on a daemon thread → `minecraft.execute`
  rebuild (`clearWidgets(); init();`) after ~700 ms so the roster refreshes.
  Status line gives feedback ("Request sent to X", "X is now your friend", …).
- Compile toolchain gotcha (survives reboots now): JDK 25 lives at
  **`~/jdks/jdk-25.0.4.1+1`** (home, NOT /tmp) - but that copy is BROKEN
  (missing `libjli.so` and most of lib/). If network is down, use this
  fallback: patch class-file major version 69→65 in a COPY of the game jar
  (python zipfile: rewrite bytes 6:8 of each .class) → `/tmp/game65.jar`,
  then compile with system **javac 21** against it. Verified working
  (GUI classes use nothing beyond Java 21). sponge-mixin jar needed no patch.

## In-game rename (2026-08-30 round 2)
- The Friends screen now shows "You: <name>" with a prefilled EditBox +
  Rename button. Rename = `friends.claim(new_name)` - the claim endpoint
  re-claims any name under this machine's stable secret/uuid, so the account
  (friends list, uuid) survives; no dedicated rename protocol message exists.
- Bridge plumbing: `local_api.py` `POST /rename` (handler fn returns the
  claim dict incl. human-readable `message` on failure; the endpoint relays
  dicts verbatim) + `set_rename_handler(fn)`; `/friends` now also returns
  `"you"` (from `friends.current_name()` merged into the roster provider in
  `friends_tab.py`).
- `friends_tab.py` rename handler calls `friends.claim(name)` (blocking HTTP,
  fine on local_api's HTTP thread) and on success reconnects the FriendsClient
  on a daemon thread (`client.connect()`) so presence re-hellos under the new
  name.
- Mod: `Bridge.rename(name)` (POST /rename) and `Bridge.currentName()`
  (parses `"you"` from /friends). `Bridge.action()` now prefers the server's
  `"message"` sentence over the raw error code, so the in-game status line
  shows e.g. "That Cubeon name is already taken…". `CubeonFriendsScreen`'s
  `runAction` ResultText callback now receives `(ok, error)` so rename errors
  pass through verbatim; add/accept/decline keep friendly generic text.

## All-versions support (2026-09-01 round)

Goal: the Friends button on every version the launcher can launch, not just
26.1.2. Verified findings:

- **The blocker is the namespace, not the API.** MC <=1.21.x ships obfuscated,
  so Fabric's production runtime is the *intermediary* namespace and mod jars
  must be remapped there by loom. 26.x ships unobfuscated (its Fabric profile
  has no intermediary library at all). Fabric remaps nothing at runtime -> one
  jar can never cover both. **Two jars is the floor.**
- `mod/brackets.json` is now exactly two brackets:
  `1.20-1.21` = `>=1.20.1 <26`, mappings official, gradle+loom, jdk 21; and
  `26` = `>=26` with **`below: null`** (open-ended, so 26.2/26.3 still get a
  jar), mappings none, javac. Jar keys avoid a second `+` because Fabric parses
  the mod version as semver.
- One *source* tree covers both because the screen is now widget-only. It never
  overrides `render`, `mouseClicked`, `mouseScrolled` or `keyPressed` - all of
  which changed shape in 26.x, and an override whose signature no longer exists
  silently stops being an override. `tools/test_mod_compile.py`'s stub is the
  enforcement: those members are deliberately absent from it now, as are
  `GuiGraphics`, `ChatComponent`, `Gui.getChat` and `GLFW`.
  Cost: page buttons instead of wheel scroll, no Enter-to-submit, no drawing.
- `StringWidget` alignment differs by version (1.20.1 centres text in its box;
  later versions gained `alignLeft`, which 26.x dropped; newer ones scroll
  overflow). Fix: the `Label` helper sizes each widget to
  `font.width(text) + 1` and positions it, so centred/left/right coincide.
- Notifications use `Gui.setOverlayMessage(Component, boolean)`: in 26.1.2
  `displayClientMessage` is gone and `ChatComponent.addMessage` is private/4-arg.
- `tools/build_mod_jars.py` now builds `mappings: none` brackets with **plain
  javac, no gradle and no network**, against
  `~/.minecraft/versions/26.1.2/26.1.2.jar` (scratch copy with class-file
  versions stepped down to `javacFeature+44`), stages `src/main/resources` with
  `${version}/${minecraft_range}/${loader_range}` expanded, packs with
  python zipfile, then **verifies** the jar contains fabric.mod.json,
  cubeon-friends.mixins.json and the screen+mixin classes and that no
  placeholder survived. Built jar: `cubeon-friends-1.0.0+mc26.jar`, 42 KB,
  17 entries, `depends.minecraft = ">=26"`.
- Probing for a usable javac must require exit 0 **and** the literal
  `javac <n>` banner: the broken `~/jdks/jdk-25.0.4.1+1` fails with a message
  quoting its own path, so a looser regex reads "25" out of the path and picks a
  compiler that cannot run.
- `find_jar` no longer falls back to the unbracketed `cubeon-friends-1.0.0.jar`.
  Across two namespaces that fallback is a crash on class load, not a degraded
  button. Absent is the correct answer.
- **Still outstanding:** the `1.20-1.21` jar. It needs one online
  `gradle`+loom run (`python3 tools/build_mod_jars.py 1.20-1.21`); there is no
  gradle on this machine and the sandbox has no network. It cannot be done
  offline - the local `intermediary-*.jar` mappings are obf->intermediary, and
  named->obf (Mojang's proguard file) is download-only.

## Environment facts

- Gradle 9.7.1 at `/tmp/gradle-9.7.1`; portable JDK 25 at
  `/tmp/jdks/jdk-25.0.4.1+1` (both in /tmp - may vanish on reboot; recompile
  path above needs them re-fetched).
- No pytest in the default shell env → `tools/test_ui_smoke.py` (40 tests)
  can't run from this shell directly; not a code regression.
- Real MC jars live under `~/.minecraft/versions/`, libraries under
  `~/.minecraft/libraries/` (sponge-mixin, fabric-loader, brigadier all there).

## Status / Next
- User confirmed the Friends button now appears (yay) and connects to the
  launcher. Remaining: end-to-end invite → friend join test with an online
  friend; deferred: Forge/NeoForge port, mod icon, multi-version mod builds.

## CRITICAL packaging gotcha (2026-08-30): jar must include resources
A deploy that does `jar cf new.jar com` (or copies such a jar over the 4
targets) WIPES fabric.mod.json + cubeon-friends.mixins.json → Fabric doesn't
load the mod at all → the Friends button silently vanishes (no crash). This
happened once; the fix is to always build from a staging dir that contains
BOTH the compiled `com/` tree AND `mod/src/main/resources/*`:

    javac ... -d out $(find mod/src/main/java -name '*.java')
    cp -r mod/src/main/resources/* out/
    (cd out && jar cf ../cubeon-friends.jar .)

Then verify BEFORE declaring success:
    unzip -l <target jar> | grep -E 'fabric.mod.json|mixins.json'

A healthy jar is ~29 KB with 15 entries (13 class/dir + 2 resource files).
If the button disappears after a deploy, check for the resources FIRST.
