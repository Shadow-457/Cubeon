[Cubeon](../README.md) / Documentation

# Cubeon documentation

Installation and development guides, followed by the architecture and
protocol references. Choose a starting point below; the remaining sections
provide the implementation details.

## Getting started

- [Using Cubeon](SIMPLE_OWNER_GUIDE.md): install, launch, update, and troubleshoot.
- [Development setup](development/setup.md): run the source and configure tools.
- [Contributing](development/development-workflow.md): make and verify changes.
- [Testing](development/testing.md): smoke checks, regression suites, and UI checks.
- [Security reporting](../SECURITY.md): report a vulnerability privately.

## Architecture

- [Overview](architecture/overview.md): components, boundaries, and launch flow.
- [Launcher](architecture/launcher.md): modules and entry points.
- [Content storage](architecture/content-storage.md): shared storage and instance isolation.
- [Mod management](architecture/mod-management.md): installation and dependencies.
- [Friends](architecture/friends.md): service ownership and chat integration.
- [Networking](architecture/p2p.md): sessions, tunnels, and world sharing.
- [Infrastructure](architecture/infrastructure.md): hosted services.
- [Data flow](architecture/data-flow.md) and [diagrams](architecture/diagrams-flows.md).

## Backend

Protocol references describe the client/Worker boundary. Check the linked
source and contract tests when changing a route or message format.

- [Skins and capes](protocols/skins-api.md)
- [Invite codes](protocols/invites-api.md)
- [Friends WebSocket](protocols/friends-api.md)
- [Worker deployment](../worker/README.md)

## Builds and releases

- [Build guide](release/build.md)
- [Release checklist](release/release-checklist.md)
- [Windows smoke test](WINDOWS_SMOKE_TEST.md)

## Technical records

The [decision records](decisions/) and [performance reports](performance/)
document investigations and earlier design choices. They are historical
records, not a guarantee of current behavior or deployment status.

Other dated reports:

- [September 17 bug report](bug-report-2026-09-17.md)
- [September 18 CI investigation](bugfix-2026-09-18-ci-red-suite.md)
- [Community rules](community/discord-rules.md)

When behavior changes, update its guide and relevant protocol reference.
Keep dated investigations intact rather than rewriting their conclusions.

[Project README](../README.md) · [Contribution guide](../CONTRIBUTING.md) ·
[Tool reference](../tools/README.md)
