# Installs: fastest possible, and never silently incomplete — plus the chat that said "not connected"

The report, verbatim: *"quick fix the donwload on instances isnt working on some
users and chat showing nto connected ot cubeon even if their net ocming good and
fast the install is just too slow and freeze make installation the fastest
possible"*. Three separate causes, three separate fixes. The durable facts are in
`agents/docs/module-map.md` (2026-10-17 install + friends sections); this is the
history of how I got there.

## What was actually wrong

1. **"Downloads don't work on some users."** mll 8.0's `_helper.download_file`
   is the only thing that fetches the ~4000 files an install needs. It has no
   request timeout, no retry, no resume and no checksum, and it answers a bad
   HTTP status with `return False` — **which every call site ignores**. So a CDN
   answering 429 to a burst of asset requests, or a proxy dropping a connection
   mid-jar, produced an install that reported success with files missing. Cubeon
   already had a patched downloader, but it was installed **only when the user
   could cancel** — an ordinary install ran mll's.
2. **"Install is too slow."** A loader install runs `install_minecraft_version`
   for the base version and then again for the loader profile whose json
   `inheritsFrom`s it — and mll's inheritsFrom branch re-installs the base
   *inside* that call. Three full passes over the same files, each re-hashing
   ~1 GB of assets and libraries. On top of that mll fans the asset phase across
   ~32 threads while handing them `requests`' default pool of **10**, so most
   threads built and threw away a TCP+TLS connection per file, and every install
   also downloaded Mojang's own JDK (a second Java, tens of MB) that Cubeon's
   launch never uses.
3. **"It freezes."** Progress arrives once per FILE and each one did a
   control-level repaint on the UI thread — ~4000 marshalled repaints per
   install, enough queued work to stop the window answering input. Separately,
   `jre.java_status` (which probes every JVM with `java -version`) ran **on the
   UI thread** on the Play click: measured **1.46 s cold** on this machine.
4. **"Chat says not connected."** Startup connected to the friends relay only
   when an identity **predated** the launch (`had_identity`). A first-run player
   who never opened the launcher's Chat tab — in-game chat does not trigger a
   connect — stayed offline for their whole first session. And `_on_open` never
   reset the reconnect ladder, so a connection that had been up and blipped
   waited the full 30 s.

## What I changed

- `cubeon/versions.py`: `_make_resilient_download_file()` (timeouts 15 s/60 s;
  3 attempts with 1.5 s/3 s backoff honouring `Retry-After` capped at 30 s;
  `Range` resume from the bytes on disk; sha1 verify with a full re-fetch on
  mismatch; a `416` on a stale partial restarts clean; a permanent 4xx raises
  `_MllDownloadError` **naming the file**, whose text `install_version`
  surfaces). It is now installed for **every** install, and into **every** mll
  module that imported the name itself (`_mll_modules()` — fabric/forge/quilt/
  mrpack/`_helper`/install/runtime), not just `mll.install` + `mll.runtime`.
  Assets and libraries resume; the version folder's own jars are still dropped
  on failure/cancel by `_drop_attempt_jars` (a truncated client jar must never
  look launchable). Plus: `install_minecraft_version` memoised per install, a
  process-wide 32-connection session (`_install_session()`, deliberately NOT
  `net.DOWNLOAD_GATE`), a `size+mtime` verified-file cache, and
  `explicit_java=True` to skip mll's JDK.
- `cubeon/config.py` (`launch_java_path()`), `cubeon/mod_loaders.py`,
  `cubeon/modpacks.py`, `main.py`: pass `explicit_java` **only** when the launch
  hands mll its own `executablePath`. This is deliberate and documented: mll's
  `command.py` falls back to its runtime directory when no `executablePath` is
  given, so on a machine with no system Java that JDK is the only Java there is,
  and Cubeon's own managed Adoptium JRE is not one of
  `find_java_for_version`'s candidates. A future agent can make this
  unconditional *only* by also resolving and passing Java in
  `launch.build_launch_command` — that is the real fix, and it is out of scope
  for a quick fix.
- `main.py`: progress repaints gated to 10 fps with a forced paint at each phase
  end; `java_status` warmed off the UI thread at startup; friends connect at
  startup as soon as an identity exists.
- `cubeon/friends.py`: `_opened_this_round` resets the backoff after any round
  that reached the server.
- `tools/test_install_download.py` (new, 26 checks) and a **rewritten**
  `tools/test_install_cancel.py`. The old cancel test had been passing by
  accident: it pointed the installer at `http://x` and measured the *connection
  failing* in milliseconds — which proves nothing about cancelling, and my
  retry work would have turned it into a 5 s sleep. It now drives a fake
  streaming transport, so the per-chunk cancel is what is actually timed.
- `docs/decisions/bugs-and-flaws.md`: entries 30-32 (+ byte-identical copy in
  `agents/docs/`).
- OG cleanup from the previous session: the card source moved out of the served
  root to `tools/og-card.html` (every `web/*.html` is published, and
  `tools/test_web_download_count.py` asserts each one wires `assets/site.js` —
  a stray card source **failed that suite**), and the module-map OG bullet now
  names the generator.

## How I verified it

- Full CI-equivalent suite (`for t in tools/test_*.py`, minus the manual
  `test_visual_*` / wedge-watchdog ones, each with its own `CUBEON_GAME_DIR`):
  **61/61 test files green** — the first run had exactly one failure,
  `test_web_download_count.py`, caused by the OG card source sitting in the
  served root; moving it fixed it (89/89 checks in that file now).
- The new/changed install tests green standalone: `test_install_download.py`
  26/26, `test_install_cancel.py` 8/8, `test_version_integrity.py` 40/40,
  `test_install_prepare.py` 7/7, `test_launch_fixes.py` 113/113.
- Measured, not assumed: `jre.java_status('1.21')` = **1.46 s cold / 0.23 s
  warm** (that number is in the module map); `python3 -c "dir(mll)"` on the
  LazyModule to prove the dynamic module enumeration finds all 8 patchable mll
  modules.
- I did **not** run a real ~1 GB Minecraft install from here, so the end-to-end
  download path is covered by fakes + the mechanism tests rather than by a live
  install. If you have network, `python3 tools/debug_run.py`-style manual test
  of "install 1.21 + Fabric on a fresh game dir" is the one gap worth closing.

## Baton / open questions

- The `RATE_LIMITER` binding for the **skins** Worker (20/min) still is not live:
  the code + `wrangler-skins.toml` are ready, but either the dashboard binding or
  `npx wrangler deploy -c wrangler-skins.toml` is needed (carried over from the
  worker-abuse session).
- **Nothing is committed.** The working tree also holds the earlier worker
  abuse-protection work, the site `og:image` tags, `web/assets/og.png`,
  `tools/make_og_card.py` and the pre-existing uncommitted "Install server"
  Fabric-profile fix. Nothing has been pushed, so nothing has minted an
  auto-release.
- Open question for the user (still unanswered): the OG card uses the shipped
  launcher screenshot in its hero frame; they dropped `Ylem.jpg` (1920×1080) as
  the visual reference, which is a text-only splash look. If they want the card
  re-read from that reference, `tools/make_og_card.py` is the one place to
  change.
