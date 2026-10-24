# Contributing to Cubeon

Bug reports, focused fixes, and proposals are welcome. Start by checking
existing issues so related work stays in one place.

For a security vulnerability, use the [private reporting channel](SECURITY.md)
instead of opening a public issue.

## Report a bug

Use the bug-report template and include:

- Cubeon version, operating system, and how the app was installed.
- Minecraft version and loader, if the issue concerns a game instance.
- The shortest sequence of steps that reproduces the problem.
- Expected behavior and what happened instead.
- Relevant log lines or a screenshot, with private information removed.

The launcher log is `~/.cubeon_launcher/cubeon.log`. Do not upload your entire
launcher data folder, identity files, credentials, or private server details.

For rendering or navigation problems, a short recording is often more useful
than a description of the animation alone.

## Propose a feature

Describe the task you cannot complete, who needs it, and the proposed
behavior. Include alternatives or constraints where they help. Discuss
large architectural changes before building them.

## Work on the source

1. Follow [Development setup](docs/development/setup.md).
2. Read the [architecture overview](docs/architecture/overview.md) and the
   guide for the component you are changing.
3. Keep the patch focused and preserve the surrounding conventions.
4. Add a regression test for changed behavior or a fixed bug.
5. Update the affected documentation.

The [development workflow](docs/development/development-workflow.md) describes
storage, UI-thread, protocol, and mod-version boundaries. Do not include
build output, downloaded game files, or unrelated cleanup in a pull request.

## Verify a change

Run the relevant regression script first, then:

```bash
python tools/test_mega_smoke.py
```

Use `--suites` for the registered extended regression run. Worker changes
also need `node worker/test-worker.mjs`; mod changes need the relevant Java
and version-matrix checks. See [Testing](docs/development/testing.md) for
prerequisites and test isolation.

List the commands and results in the pull request. Record failures and
skips explicitly. For UI changes, attach an actual screenshot or recording
and identify the platform you tested. Headless checks are not visual tests.

## Submit a pull request

Explain the problem, the approach, and any compatibility implications.
Link the relevant issue and keep the diff small enough to review.

Avoid adding dependencies without a concrete need. Credentials and private
identity data must not appear in code, fixtures, logs, or screenshots.

Release tags, hosted-service deployment, and publishing are maintainer
operations. See [Builds and releases](docs/release/build.md) for that process.
