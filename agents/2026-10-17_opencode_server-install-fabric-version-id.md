# "Install server" failed on Fabric profiles — a launch id was sent to Paper

- **Agent:** opencode (DeepSeek V4.1 Flash Free), session on 2026-10-17
- **Task:** Fix the server-install bug the user hit: *"Install failed: Couldn't
  reach https://fill.papermc.io/v3/projects/paper/versions/fabric-loader-0.19.5-1.21.11/builds
  after 3 tries: 404 Client Error."* They play a Fabric profile, so this was
  never going to work.

## What was actually wrong (two separate bugs, one symptom)

**1. The wrong version was asked for.** `install_server` passed the raw launch
id straight into `_get_paper_download_url`, so Fill was asked for the Paper
version `fabric-loader-0.19.5-1.21.11`. No such Paper version exists — Paper
publishes per *Minecraft release*, never per loader id. `cubeon/versions.py`
already ships `extract_mc_version()` for exactly this ("This MUST be used
anywhere a version id is ... passed to a loader installer"), and the server
path just wasn't using it.

**2. The 404 was retried and then blamed on the network.** `net.get_with_retry`
retried *every* `requests.RequestException`, `raise_for_status()`'s
`HTTPError` included — even though its own docstring said "a 404 will never
succeed by waiting, so it fails through immediately". So the user waited
1.5s + 3s of backoff and got "Couldn't reach ... after 3 tries", which is not
what happened: the server answered, plainly. Worse, this made the friendly
404 handler in `_get_paper_download_url` **dead code** — it caught
`requests.HTTPError`, which `net.get_json` never raises.

**The trap worth remembering:** `tools/test_net.py::_no_retry_on_404` already
asserted the correct behaviour and had done since it was written — but the
function was **never called**, so the regression shipped with a green suite.
I only found it because the passing test looked impossible. When you add a
test here, check it's actually invoked.

## What I changed

| File | Change |
|---|---|
| `cubeon/net.py` | New `HTTPStatusError(DownloadError)` carrying `.status_code`. `get_with_retry` now closes the response and raises it on the **first** 4xx (except 429, still retried), instead of retrying and mislabelling. |
| `cubeon/server.py` | New public `minecraft_version(version_id)` (= `extract_mc_version` + id fallback). `install_server` reduces the id before the Paper lookup, and the status line now says "…for Minecraft 1.21.11" when that differs from the profile name, so a Fabric user isn't surprised their mods didn't come along. `_get_paper_download_url(mc_version)` catches `net.HTTPStatusError`. |
| `cubeon/server.py` | **The same bug, three more places:** `ensure_default_plugins`, `ensure_smooth_mode_plugins`, and `ui/server_tab.py`'s `search_plugins` / `get_plugin_download` all passed `version_id` as Modrinth's `game_versions` facet, where a loader id matches **nothing**. |
| `launcher_core.py` | Re-export `minecraft_version` for the UI facade. |
| `tools/test_net.py` | Wired up the dead `_no_retry_on_404()`; added `_retry_on_429_never_on_403`; strengthened `_get_json_failure_is_clean` (it now has a healthy response queued behind the 404, so a retry would "succeed" and hide the bug). |
| `tools/test_server_integrity.py` | End-to-end hermetic install of a `fabric-loader-…` profile asserting the bare MC version reaches Fill; the no-build refusal naming the Minecraft version; and the plugin lookup asking Modrinth for `1.21.11`. |

## How I verified

- **Live, through the fixed code path** (not just mocks): the old call returns a
  clean immediate refusal; `1.21.11` resolves to **Paper build 67** and a real
  download URL. Plugin search: loader id → **0 hits**, `1.21.11` → **27 hits**.
- `tools/test_net.py` 54 ✓ (was 46 — the newly-invoked checks), 
  `tools/test_server_integrity.py` 71 ✓, `test_mod_detail` 81 ✓,
  `test_faces` 12 ✓, `test_invites` 127 ✓, `test_modpacks` 70 ✓,
  `test_mega_smoke` 22 ✓, `test_ui_smoke` 246 ✓ (PASS).
- What the user will now see on their Fabric profile: *"Downloading Paper 67
  server.jar for Minecraft 1.21.11"*, then the progress bar — and for a version
  Paper genuinely lacks, one plain sentence instead of a network complaint.

## Notes for the next agent

- `today`'s map (I updated it): the launch-id rule now covers Paper's Fill API
  and Modrinth's version facet, plus the 4xx-fails-fast contract. Read the two
  bullets I added before touching anything else per-version.
- **Paper ≠ Fabric.** The install now succeeds for a Fabric profile by
  installing a *vanilla* Paper server for the base MC version. The user's client
  mods do not come with it. If someone asks for a real Fabric server, that's a
  new feature (fabric-installer + mod sync), not a fix — the status line and the
  Install button's tooltip ("Paper server - works with normal Minecraft and
  supports plugins") are the current, deliberate answer.
- I did not commit or push: pushing `main` mints an auto-release here. That's
  the user's call. The working tree is dirty with exactly the 7 files above.
- Unrelated, still unfinished from before the restart: the launch-video rebuild
  in `/tmp/opencode/cubeon_video/` was wiped by a `/tmp` clean. The delivery
  folder `~/Downloads/cubeon-launch-video/` survived (first cut + README + the
  user's real screenshots in `incoming/`), so the re-cut can be rebuilt from
  `incoming/` whenever the user wants it.

## Question for the next agent

When `net.get_with_retry` exhausts its attempts on a *5xx*, the message still
says "Couldn't reach … after 3 tries" — but the server was demonstrably reached
(we got a 503). Should an exhausted 5xx report a status-flavoured message too
(so "we couldn't reach it" stops appearing for servers that answered), or is it
fine because a retried-and-failed request is genuinely "not reached"? I left it
alone deliberately — the transient-retry tests pin the current wording — but
it's the one place the old misleading phrasing still survives.
