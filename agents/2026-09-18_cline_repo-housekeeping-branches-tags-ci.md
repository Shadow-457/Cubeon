# Repo housekeeping: branches, tags, releases, CI (2026-09-18)

- **Agent:** Cline (GLM)
- **Date:** 2026-09-18
- **Task:** organise git branches, releases, and CI hygiene.

## What I did

1. **Fixed the mangled commit message** — the smoothness-pass commit had
   literal `\n` sequences glued into one line (shell quoting bug). Amended to
   a proper multi-line message and force-pushed with `--force-with-lease`
   (safe: only rewrote our own just-pushed commit). New hash: `f31f214`.
2. **Branches** — deleted the stray local branch
   `pi/cubeon-tab-1789558797844-1gitmd` (old ancestor of main, already
   contained in history). Remote is `main`-only by design: trunk-based,
   single-developer repo; feature work happens on main behind tests.
3. **Tags** (all pushed to origin):
   - `v1.0.0` — annotated release tag on `f31f214`, matches
     `APP_VERSION = "1.0.0"` in `cubeon/updater.py`. Triggers
     `build.yml` (`tags: ["v*"]`), which builds AppImage/Win/macOS artifacts.
   - `clean-baseline` — renamed from the ad-hoc `cubeon-clean-baseline-2026-09-18`
     lightweight tag to an annotated tag (same commit, `a04515b`): the known
     good state before the smoothness pass.
   - `latest` tag — LEFT ALONE: a GitHub Release (2026-09-05) is attached to
     it and `cubeon/updater.py` serves updates from the `releases/latest` API.
     Deleting/retargeting would break user updates.
4. **CI storage** — the repo had ~19 GB of stale Actions artifacts (quota is
   500 MB), which made every artifact upload fail with
   "Artifact storage quota has been hit". Deleted all of them; usage now 0.
   The `v1.0.0` build was re-run afterwards (`gh run rerun`) so fresh
   artifacts can actually upload.
5. **Dropped a stash** that contained only `mod/.gradle` build-cache churn
   (zero code value).

## PRE-EXISTING CI failure (documented, NOT fixed — per pass rules)

`tools/test_content_doctor.py` fails deterministically on main:
`ValueError: Can't manage resource packs: no Minecraft version selected.`
(raised from `cubeon/mods.py:191 require_loader_and_version`). Verified it
fails IDENTICALLY on the previous commit `929138c` via a worktree — it is NOT
caused by the smoothness pass. It also fails in CI on every run since at
least 2026-09-16, which is why main's CI has been red for days.

Additionally CI flakily fails a rotating set of other suites
(`test_launch_fixes`, `test_milestones`, `test_mod_compile`,
`test_version_integrity`, `test_modpacks`) — different ones each run, all
pass locally; looks like runner contention/ordering, worth a look but not
diagnosed here.

## Follow-up recommendations (not done)

- Fix `test_content_doctor.py` / the missing selected-version guard in a
  dedicated pass, then re-tag.
- The `latest` GitHub Release (2026-09-05) serves old binaries; once CI is
  green, attach the fresh v1.0.0 artifacts to a proper `v1.0.0` release and
  mark it latest (updater will then serve it).
- Consider `retention-days` on `actions/upload-artifact` (~7) so the quota
  can't fill up again.

## Question for the next agent

`test_content_doctor.py` expects a selected version to exist when the
resource-pack doctor runs, but the harness never selects one. Is the fix to
seed the version in the test, or should `require_loader_and_version` accept
an explicit version param at that call site? Check git blame on
`fd6e7dc` where the doctor scans were added.
