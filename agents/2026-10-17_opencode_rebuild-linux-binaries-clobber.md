# Rebuilt the Linux binaries and clobbered v1.1.2

> **SUPERSEDED — read `2026-10-17_buffy_rebuild-linux-binaries-clobber-and-push.md`
> for the state of the release.** Another agent rebuilt from a *newer* tree
> (03:10, carrying the Play-area delete fix) and re-uploaded at 03:23. The
> digests below are therefore historical, NOT what GitHub serves: the live
> v1.1.2 Linux assets are AppImage `b4508193…`, deb `6591e0a5…`, Setup.sh
> `2c5839a2…`. Everything below the marker about *how* to verify still holds —
> `tools/verify_linux_artifacts.sh` re-passes against the newer build.

The user had just deployed the hardened skins Worker, and asked: *"now can you
rebuild the linux bunaries especially app image and clobber it"*.

## What was built (all from HEAD `7132ac9`)

`PATH=$PWD/.venv-build/bin:$PATH bash packaging/build_appimage.sh` → then
`… python packaging/build_linux_installers.py`:

| Artifact | Size | sha256 |
|---|---|---|
| `Cubeon-x86_64.AppImage` | 108,866,040 | `4b156ac1…4f4c22a` |
| `cubeon_1.1.2_amd64.deb` | 115,861,962 | `b7dcce57…3860e0d` |
| `Cubeon-Linux-x86_64-Setup.sh` | 1,341 | `2c5839a2…d6edaf` |

All three clobbered to the **latest** release (v1.1.2) with
`gh release upload … --clobber`, in parallel. **Every digest GitHub recorded
matches the local file byte-for-byte**, and the download Worker now serves the
new deb (`content-length: 115861962`) — so the release path is verified end to
end, not just the local file.

`.venv-build` (flet 0.86.5) is the correct build venv; the existing notes say
`$HOME/cubeon-venv`, which no longer exists. System python is flet 1.0.3 and
must not be used.

## What the rebuild contains

Verified by reading the artifacts, not the source tree:

- 25 mod jars including **24 `cubeon-client-*`** and **zero keyhud-named** ones
  (the Phase 3b rename is actually in the shipped AppImage).
- The pre-downloaded `flet-linux-ubuntu24.04-light-amd64.tar.gz`, so first
  launch does not try to fetch a client at runtime.
- `osnotify` present (Phase 7).
- **This cycle's `CUBEON_SKIN_API` change is inside the frozen `cubeon.csl`
  bytecode** — extracted from the PYZ and unmarshalled. Data files prove the
  ASSETS are current; only reading the frozen code proves the CODE is, and a
  stale build otherwise ships silently.

Launching under `xvfb-run` gets as far as creating `~/.cubeon_launcher`, its
identity and `cubeon.log` (which logs `update check: up to date (v1.1.2)`), then
dies on `Timed out waiting for OpenGL frame … (have 1x1)`. That is the headless
box having no GPU — the same reason CI skips `test_wedge_watchdog.py` — **not** a
packaging fault. `LIBGL_ALWAYS_SOFTWARE=1` + `GALLIUM_DRIVER=llvmpipe` does not
rescue it. No human has seen this AppImage with a real window.

## Two CI problems found (reported, NOT fixed)

Both pre-date this session and neither is mine; the user asked for a rebuild, not
a CI repair, so I left them alone rather than silently changing the pipeline:

1. **CI has been red all day, on every push, before my work.** `tools/test_startup.py`
   (22 passed, 3 failed) and `tools/test_winwindow.py` (27 passed, 1 failed) fail
   on the **Windows** runner with
   `AttributeError: 'ProactorEventLoop' object has no attribute '_ssock'` from
   the harness's socket-blocking code, followed by
   `OSError: network disabled by tools/test_startup.py`. A Windows-asyncio
   incompatibility in the TEST HARNESS, not the product. It does not block
   publishing (artifacts ship anyway), but a permanently red CI hides real
   failures.
2. **Concurrent runs race on `--clobber`.** Pushing several commits in quick
   succession started two runs 7 seconds apart (20:51:46 and 20:51:53); both
   `delete`-then-`upload` the same asset names, and one got
   `HTTP 404: Not Found (…/releases/…/assets?…&name=Cubeon-Windows-x64-Setup.exe)`.
   Harmless here — all six assets still ended up present with valid digests — but
   it is a real race, and a `concurrency:` group on the workflow would remove it.

## Note

The Android/Windows-side assets were **not** rebuilt by me (not asked): CI
refreshed `Cubeon-Windows-x64.zip`, `Cubeon-Windows-x64-Setup.exe` and
`Cubeon-macOS.zip` at 20:53–20:54 on 2026-10-16, and the Linux AppImage is
deliberately never built by CI, which is exactly why this was a manual job.
