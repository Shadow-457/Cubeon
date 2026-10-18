# Auto-release per push (2026-10-17)

## What the user asked for
"can you automate git so whenever a new push happens it makes a new release
1.2.x and so on."

They picked, from the options I laid out: **seeded patch bump** (I seeded
`APP_VERSION = "1.2.0"`, so the next push is `v1.2.0` and then `v1.2.1`, …),
**build Linux in CI too** (every release complete), and **draft → publish**
(never visible half-built).

## What I actually did

Before this, a push to main rebuilt Windows + macOS and refreshed the *latest*
release in place with `--clobber` — no new version, and the Linux AppImage was a
manual local build. Now:

- **`tools/release_version.py`** (new) owns the version policy and is the only
  supported way to set it:
  `next` = APP_VERSION if its tag doesn't exist yet (that is how a new series is
  declared), else patch+1 of the highest of (APP_VERSION, all `v*` tags),
  compared numerically per segment. `stamp <version>` rewrites
  `APP_VERSION` + the site's display text, and **raises** if the literal can't
  be found (a silent no-op ships a build whose own version contradicts its tag).
- **`.github/workflows/build.yml`** gained a `release` job (decide version →
  stamp → commit back as `release: vX.Y.Z [skip ci]` → push the tag as the
  version lock → open a DRAFT release), the three build jobs now
  `needs: release`, check out `ref: ${needs.release.outputs.tag}`, re-stamp and
  upload to the draft, and a `publish` job verifies all six assets exist before
  `gh release edit --draft=false`. Added
  `concurrency: release-${github.ref}` (`cancel-in-progress: false`).
- **Tests**: `tools/test_release_version.py` (50 checks, the policy) and
  `tools/test_release_pipeline.py` (49 checks, which extracts the real `run:`
  scripts out of the workflow and exercises them offline against a throwaway
  repo + a `gh` stub). Both registered in `test_mega_smoke.py`'s `SUITES`.
- **Docs**: new module-map section "Auto-release per push (2026-10-17)";
  rewrote the stale release process in `docs/release/build.md`,
  `docs/release/release-checklist.md` and `docs/SIMPLE_OWNER_GUIDE.md` ("pushing
  is the release").

## Verified, and how

- `python3 tools/test_release_version.py` → 50/0.
- `python3 tools/test_release_pipeline.py` → 50/0. This is the one that matters:
  it runs the *shipped* script text through: first push → v1.1.3 (in the tag, in
  the tree, in the site text), **re-run of the same push reuses v1.1.3 and mints
  nothing**, re-running an *already published* release puts it back into draft
  while `--clobber` replaces assets, next push → v1.1.4, a **lost tag race** →
  v1.1.5 (v1.1.4 untouched), a bad `APP_VERSION` aborts without tagging, a human
  tag push is released verbatim, `publish` refuses a release missing any asset
  (including a `cubeon_*.tar.gz` masquerading as the `.deb`), and `latest` only
  moves forwards.
- `python3 tools/test_mega_smoke.py --static` → 16/0, and the full
  `python3 tools/test_mega_smoke.py --suites` (all 28 sub-suites + the headless
  UI layer, including the Windows custom-frame branch) → **50 passed, 0 failed**.
- Every `run:` block in the workflow passes `bash -n`, and the YAML parses with
  the jobs/needs/outputs I expect.

## Hard-won facts (also in the module-map section)

- **The updater contract is the sharp edge.** `cubeon/updater.py` only accepts a
  `vX.Y.Z` tag newer than the APP_VERSION compiled into the running build. Tag
  ahead of the binary = every user sees "update available" forever. Same literal
  feeds `build_deb.py` (deb version) and `build_windows_installer.py` via regex
  on the SOURCE, which is why `stamp` is mandatory in every build job.
- **`gh release upload --clobber` DELETES the asset before re-uploading it**, so
  a re-run of an already-published release is put back into draft first (and
  `publish` re-publishes it).
- **Re-run idempotency needs a parent check**: on a re-run `GITHUB_SHA` is the
  pushed commit, but the tag points at the bump commit we pushed — so the job
  looks for a tag at our commit *or* at a child whose subject is
  `release: vX.Y.Z [skip ci]`. Without that, every re-run mints a spare version
  (I watched it happen in the dry-run before adding it).
- **`github.ref` is the TRIGGERING ref**, unaffected by `actions/checkout`'s
  `ref:` — that is why the tag-only `upload-artifact` steps (free-quota rule,
  ~500 MB per run) stay tag-only even though the branch build now checks out a
  tag.
- **Deliberately not test-gated.** `test_fuzz.py` / `test_install_cancel.py` are
  load-flaky on CI (documented in the previous note too), and a flaky red test
  silently dropping a release is worse than shipping one. Flipping it is one
  line: `needs: [test, test-windows]` on `release`.

## Notes for the next agent

### What the real runs taught us (2026-10-17)
The automation is live on `main` and has released for real: **v1.2.0 and v1.2.1
are public**, each with all six assets, each un-drafted only after the `publish`
job had verified every asset was already on the (invisible) draft. Five failures
showed up on real runners, none reachable locally:

1. **`[skip ci]` in my own commit message skipped the run entirely.** GitHub
   scans the whole message for the token and the message merely *described* the
   release job's trailer. Amended + force-pushed; the prose says "skip-ci
   trailer" now.
2. **`GET /releases/tags/<tag>` returns 404 for a DRAFT.** It was the release
   job's reuse check, so a re-run would have concluded "no release yet" and died
   on "already exists". `gh release view/upload/edit` list-and-match, so they DO
   see drafts. Fixed; the stub now 404s drafts too (the buggy form reports 3
   failures).
3. **`tools/test_release_pipeline.py` died with exit 128 on the runner**: its
   first `git commit` used the inherited env and a runner has no git identity
   configured. Every git call now carries the sandbox `HOME` +
   `GIT_AUTHOR_*`/`GIT_COMMITTER_*`; reproduce the CI condition locally with
   `HOME=/tmp/opencode/nohome GIT_CONFIG_NOSYSTEM=1`.
4. **`gh` could not tell the publish job which repo to talk to** — it resolves
   that from a git remote, and the publish job has no checkout (it needs nothing
   but the API), so the job died with `fatal: not a git repository` *after*
   verifying all six assets and before un-drafting. Safe failure: the release
   stayed an invisible draft. Fixed with a workflow-level `GH_REPO`.
5. **`gh release view --json isLatest` does not exist** (it is a `release list`
   field), so `publish` un-drafted `v1.2.1` correctly and *then* failed the job
   on its closing summary line. Ask
   `gh api repos/{o}/{r}/releases/latest --jq .tag_name` instead.

Four and five share a lesson the test now enforces: **the `gh` stub models the
tool's refusals, not just its successes.** Both bugs passed 50/0 locally because
the stub was easier to satisfy than real gh.

State of the world: `APP_VERSION` on `main` always tracks the newest release,
because the `release` job commits it back as `release: vX.Y.Z [skip ci]`, so each
push mints the next patch. **v1.2.0 through v1.2.3 are public** (six assets
each); after the four fixes above, two consecutive runs went fully green - the
last one from a docs-only push, which is the whole point: push, wait, release.

Two consequences worth knowing:
- A docs-only push also mints a release (that is what "every push" means). If
  that gets annoying, add `paths-ignore` for `**/*.md` to the push trigger -
  do NOT reach for a skip-ci token in the message, because a message that merely
  mentions the token skips the run too (see bug 1).
- `test-windows` is red on `main` independently of all this (it was red before my
  first commit too) and it deliberately does not gate releases.

- If they dislike a release per push, the off-switch is removing `needs:
  release`/the `release` job and going back to tag-driven publishing — but do
  NOT let a tag exist without a matching `APP_VERSION` in the tree it points at.
- The release notes come from `--generate-notes` and the updater's snackbar
  shows the first ~400 characters, so commit subjects are user-facing.
- Left alone on purpose: `tools/verify_linux_artifacts.sh`'s `MARKER` constant
  still has to be bumped by hand for a *local* AppImage verification. It is a
  cycle-specific staleness probe, not a version, so it is not part of `stamp`.
