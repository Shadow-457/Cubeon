# Rebuilt the Linux binaries, clobbered v1.1.2, pushed the delete fix

Asked: *"rebuild the linux binaries clobber them and push to code too on git"*.
All three artifacts were built from the tree that carries the Play-area delete
fix (`ui/versions.py` at 03:01:53, AppImage built 03:11:14 - newer, so not the
silent-stale-build trap).

| Artifact | Size | sha256 (== GitHub digest) |
|---|---|---|
| `Cubeon-x86_64.AppImage` | 108,870,136 | `b4508193…cfc4f1` |
| `cubeon_1.1.2_amd64.deb` | 115,869,898 | `6591e0a5…41553f` |
| `Cubeon-Linux-x86_64-Setup.sh` | 1,341 | `2c5839a2…d6edaf` |

Build: `PATH=$PWD/.venv-build/bin:$PATH bash packaging/build_appimage.sh`, then
`… python packaging/build_linux_installers.py`, then
`bash tools/verify_linux_artifacts.sh` → **ALL ARTIFACT CHECKS PASSED** (25 mod
jars, 24 cubeon-client, no keyhud, flet client tarball bundled, osnotify in the
TOC, and `CUBEON_SKIN_API` read back out of the frozen `cubeon.csl` bytecode).

## A clobber is a DELETE first - and a killed upload leaves a hole

The first upload was run as a foreground command and the tool killed it at its
600 s timeout. **Both the AppImage and the deb were gone from the v1.1.2 release
afterwards**: `--clobber` deletes the existing asset before uploading the new
one, so an interruption in between removes the downloadable file entirely. The
API listing (`.assets[]`) is what caught it - the local files were fine the
whole time, so anything less than reading the release back would have missed a
release with no Linux downloads at all.

Re-uploaded via `logs/upload_linux_assets.sh` as a BACKGROUND process (three
parallel `gh release upload … --clobber`, each with its own log + exit status),
polled to completion, then compared every `sha256` with the API's `digest`.
**Next time: never run a release `--clobber` upload in a command that can be
timed out, and always re-read the release afterwards.**

## Pushed

`9b98508 play: deleting the last instance now clears the whole Play area`
(main.py, ui/versions.py, tools/test_version_ui.py, the module map, and
`tools/verify_linux_artifacts.sh`) → `origin/main`. CI run 38975760420:
**Test suite (ubuntu, the whole tools/test_*.py loop) SUCCESS**, Windows and
macOS builds SUCCESS (so those two assets were refreshed at 22:27-22:29Z - that
is the workflow's contract on a main push), **Build Linux AppImage skipped**
(branch pushes never build it, which is why this was a manual job - and why the
push did not disturb the assets I had just uploaded).

`Startup tests (Windows)` failed again with
`AttributeError: 'ProactorEventLoop' object has no attribute '_ssock'` - the
same pre-existing harness bug as the last three runs, not this commit.

## Not done

Not launched under a real window (headless box, no GPU - same limitation as the
previous rebuild), and the Windows/macOS artifacts were not rebuilt by hand.
