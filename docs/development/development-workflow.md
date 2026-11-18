[Documentation](../README.md) / Development

# Development workflow

For issue reports and pull requests, start with the
[contribution guide](../../CONTRIBUTING.md). For source work, follow
[Development setup](setup.md). Keep a change focused on one
problem, and include enough information for someone else to reproduce it.

## Making a change

1. Check existing issues and nearby tests before adding new behavior.
2. Follow the surrounding code's style and module boundaries.
3. Add a regression check for a bug fix or changed contract.
4. Update the guide or protocol reference affected by the change.

Avoid unrelated refactors, generated build output, and new dependencies
unless the change needs them. The repository does not currently include a
shared Ruff, mypy, or Pyright configuration.

## Reuse existing work

This rule applies across the entire repository. Before adding code, assets,
UI components, dependencies or tooling, search for an existing implementation
or resource that meets the need. Reuse or extend suitable existing work and
keep shared behavior in its established module.

Use the branding, bundled fonts, theme tokens and interaction patterns already
used by the surface being changed. Launcher visuals use `assets/cube.svg`,
the fonts defined in `cubeon/theme.py`, and matching supplied artwork in
`assets/icons/`. Preserve artwork colors, accessibility, behavior and retained
control identity when integrating it.

Add something new when existing work cannot reasonably meet the requirement
or the user explicitly requests a replacement. Briefly explain the reason
in the change description or completion note.

## Boundaries to preserve

- UI builders live in `ui/`; application wiring lives in `main.py`.
- Background UI writes use `cubeon/thread_safe_ui.py`. Do not call a whole-page
  update from a worker thread to refresh one control.
- Shared downloads must not mix the active content of different instances.
- Persistent state uses the existing atomic-write helpers.
- Client and Worker changes must preserve their protocol contract.
- Mod version routing is defined in `mod/brackets.json`.

See [Architecture](../architecture/overview.md) for the relevant modules.

## Verification

Run the most relevant test first, then the smoke gate:

```bash
python tools/test_ui_smoke.py
python tools/test_mega_smoke.py
```

For a broader regression run, use `python tools/test_mega_smoke.py --suites`.
For Worker changes, run `node worker/test-worker.mjs` and the affected
client contract tests. For mod changes, run the Java compile and version
matrix checks listed in [Testing](testing.md).

Headless tests cannot validate visual smoothness, a platform's window
behavior, or an actual Minecraft launch. Record manual checks separately.

## Pull requests

Describe the problem, the change, and the commands you ran. Include a real
screenshot or short recording for a visible UI change. Note any failing or
skipped checks rather than describing an incomplete run as passing.

Do not include credentials, player identity files, local paths belonging to
one machine, or bundled game downloads.

## Releases

A push to `main` can start the release workflow. Release publication is a
maintainer operation, separate from submitting a change. Follow
the [build guide](../release/build.md) and
[release checklist](../release/release-checklist.md).
