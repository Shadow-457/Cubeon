# tools/ - tests and dev scripts

Everything here runs standalone with no services needed (network calls are
stubbed or pointed at localhost). Run from the repo root:

## Test suites

| Command | What it covers |
|---|---|
| `python3 tools/test_skins_net.py` | client↔Worker contract for skin publishing: Bearer auth, heartbeat/upload gating, write-frugal dedupe, failure handling |
| `node ../worker/test-worker.mjs` *(run from `worker/`)* | Worker routes/KV logic against a stub KV - heartbeat, uploads, CSL profile lookups, moderation |
| `python3 tools/test_csl.py` | CustomSkinLoader ExtraList registration rules: dedupe dodges, two-launch stagger, self-healing rewrites |
| `python3 tools/test_client_json.py` | launch-path repairs: TLauncher-style client.json sanitizing, command construction |
| `python3 tools/test_friends.py` | friends identity/client logic + format parity with `worker/cubeon-friends.js` |
| `python3 tools/test_friends_service.py` | the headless friends service and the localhost bridge, **plus a contract check that reads the mod's `Bridge.java` and fails if the launcher doesn't serve every endpoint/field it calls** |
| `python3 tools/test_invites.py` | invite-code format parity launcher ↔ Worker |
| `python3 tools/test_modpacks.py` | modpack install/version-matching |
| `python3 tools/test_modpacks_cf_keyless.py` | CurseForge packs without an API key: zip→mrpack conversion, the keyless download path |
| `python3 tools/test_p2p_*.py` | P2P transport/session layers (`_stress` variant is long) |
| `python3 tools/test_launch_indicator.py` | the Play tab's launch progress bar: phase ordering, no stalls, no backwards jumps |
| `python3 tools/test_mod_install_progress.py` | install progress for a mod **plus its auto-installed dependencies**: one monotonic 0→100 climb over the whole batch (never restarts per file), a total that's final before the first byte, 100 exactly on success, and the UI's "Downloading… 42% (file 2/3)" label rules |
| `python3 tools/test_ui_smoke.py` | boots the Flet UI headless-ish smoke test |
| `python3 tools/test_mega_smoke.py` | **one-command deep gate**: syntax → imports → type/contract → control flow → headless runtime (`--static` skips runtime, `--suites` also runs the harnesses below, `--json` for machines) |
| `python3 tools/test_fuzz.py` | UI chaos monkey: builds the real UI headless under safe stubs, fires every handler with a hostile corpus, plus directed scenarios (play/delete/export/content-install) |
| `python3 tools/test_orphan_server.py` | server lifecycle cleanup edge cases |
| `python3 tools/test_web_download_count.py` | the website's "N release downloads" line, end to end: runs `web/api/download-count.js` in Node with a stubbed GitHub (allow-list, cache header, 404/403/503/405 paths, junk counters), runs the real `web/assets/site.js` on a DOM stub to prove the committed `download-count.json` fallback fills the count when the Vercel endpoint is unavailable, and checks `tools/refresh_download_count.py`'s arithmetic and its no-op-when-unchanged behaviour |

### The in-game Friends mod (`mod/`)

These need a JDK on PATH (17+); none of them need network or a Minecraft jar.

| Command | What it covers |
|---|---|
| `python3 tools/test_mod_bridge.py` | compiles `Json.java`/`Bridge.java` with `-Werror` and runs 100 assertions over the parsers and the snapshot/session models |
| `python3 tools/test_mod_compile.py` | compiles **all** mod sources against a hand-written stub of the Minecraft API. Doubles as an allowlist: the stub deliberately omits `blit`, `renderBackground`, `LinearLayout` and friends, so reaching for an API that isn't stable across the supported versions fails here instead of at a player's launch |
| `python3 tools/test_mod_matrix.py` | `mod/brackets.json` itself - no overlapping ranges, each jar compiled against the oldest version it claims - and that the installer picks the jar the table promises, including cleaning stale jars out of a profile |

All exit 0 on pass, non-zero on failure.

## Dev utilities

- `make_cape.py` - regenerates the shared Cubeon cape PNG from
  `assets/capes/cubeon_cape.png` and patches the base64 + sha256 constants
  into `worker/cubeon-skins.js`. **Never edit those constants by hand** - a
  single wrong base64 char ships a broken cape that only shows up in-game.
- `refresh_download_count.py` - rewrites `web/assets/download-count.json`, the
  number the public site prints next to the download buttons. Runs on a schedule
  in `.github/workflows/download-count.yml` (and by hand as
  `GH_TOKEN=$(gh auth token) python3 tools/refresh_download_count.py`). It is
  the credential-free side of the counter: the site itself never holds a token,
  because the repo is private and anonymous GitHub requests answer 404. Leaves
  the file untouched (zero commits) when the numbers did not move.
- `debug_run.py` - run the launcher with debug flags.
- `app_driver.py` - **AI-usable driver**: boots the real UI headless under the
  same safe stubs as the fuzzers and *uses* it (open every tab, type every
  field, fire every handler) then reports JSON errors + handler coverage.
  `explore` fires ~822 invocations at **100% of the handler surface** (click /
  change / submit / hover / focus / blur / picker-result); `fuzz` does the same
  across the hostile corpus (~26k invocations, still 100%). The report's
  `handler_coverage` names anything a pass didn't fire. Commands: `explore`,
  `fuzz`, `tabs`, `script <steps.json>`, `shots`. `shots` delegates to the
  windowed `ux_capture.py` tour for real PNGs (Flet has no headless renderer).
- `ux_capture.py` / `fuzz_visual.py` - screenshot/UI capture helpers
  (output lands in `agents/docs/ux_shots/`).
- `_fuzz_common.py` - shared fuzzing fixtures (not a test).
- `build_mod_jars.py` - builds one Cubeon Friends jar per bracket in
  `mod/brackets.json` and copies them to `~/.cubeon_launcher/cache/`, where the
  launcher looks first. `--list` prints the matrix. **Needs network** the first
  time each bracket runs (fabric-loom fetches the Minecraft jar, mappings and
  loader) and the JDK each bracket declares.
