# Network resilience + download throughput (2026-09-13, deepseek-v4-flash)

**Trigger:** user report — "installing resourcepack/modpack/shader shows a
network error, and downloads aren't optimized."

**Root cause:** `cubeon/net.py` already had retry/resume/atomic-replace, but
the resourcepack + shader install path (`content.download_content`) was the
one install site still doing a bare, single-attempt `requests.get` with no
retry, no Range resume, and no `.part` atomicity. One Wi-Fi blip = hard
failure. Separately, the modpack installer downloaded its mod jars in a
serial `for` loop, so the global 4-slot download gate was decorative (one
thread can only hold one slot). Metadata/search calls also had no retry.

## What changed
- `cubeon/net.py`: lazy pooled `requests.Session` (connection/TLS reuse);
  `net.get_json()` for retry-wrapped API/metadata GETs; `get_with_retry`
  gained `params=`; `net._do_get` is now the single transport seam.
- `cubeon/content.py`: `download_content` delegates to `net.download_to`
  (retry+resume+atomic+gate) and verifies Modrinth's `sha512`/`sha1`;
  `get_content_download` now returns `hashes`; search/lookup use `get_json`.
- `cubeon/server.py` + `minekube.py`: plugin downloads go through
  `net.download_to`; plugin/paper metadata lookups use `get_json`.
- `cubeon/modpacks.py`: mod-file downloads run in a 4-worker
  `ThreadPoolExecutor` (matching the gate), `record_mod_source` still runs
  serially afterward to avoid racing the profile metadata; search/version
  lookups use `get_json`.
- `cubeon/global_mod_cache.py`: `_INDEX_LOCK` guards the index
  read-modify-write and the store-name choice (parallel installs would
  otherwise lose index entries / pick colliding names).
- `ui/mods_tab.py`: passes `hashes` through; shows a one-line failure reason
  instead of a bare "Failed".

## Verification
- `tools/test_net.py` 21/21 (added `get_json` retry + clean-failure tests;
  transport seam now `net._do_get`).
- `tools/test_modpacks.py` 51/51 (harness re-pointed at `net._do_get`).
- `tools/test_mega_smoke.py` 16/0; `--suites` 26/0.
- `tools/app_driver.py explore` 0 errors, 100% handler coverage;
  `fuzz` 26,608 actions, 0 errors.
- Live (sandboxed HOME): real Modrinth resourcepack + shader search → lookup
  → hashed download both succeeded.

## Note for the next agent
`net._do_get` is the test seam now. Any harness that fakes `requests.get`
must also route `_do_get` through its fake (see `test_modpacks._net_seam`),
or it will silently hit the real network.
