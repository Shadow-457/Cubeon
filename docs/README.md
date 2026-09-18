# Cubeon Documentation

This directory contains all project documentation organized by audience and topic.

## Quick Navigation

| If you're... | Start Here |
|--------------|------------|
| A **player** wanting to run Cubeon | [Simple Owner Guide](SIMPLE_OWNER_GUIDE.md) |
| A **developer** setting up the project | [Development Setup](development/setup.md) |
| A **contributor** making changes | [Development Workflow](development/development-workflow.md) |
| An **architect** understanding the system | [Architecture Overview](architecture/overview.md) |
| A **release manager** cutting a release | [Release Checklist](release/release-checklist.md) |

## Documentation Structure

```
docs/
├── README.md                           # This file
├── SIMPLE_OWNER_GUIDE.md               # Player guide (run, build, troubleshoot)
├── bug-report-2026-09-17.md            # Consolidated bug findings
│
├── architecture/                       # System design
│   ├── overview.md                     # High-level architecture
│   ├── launcher.md                     # Launcher modules & entry points
│   ├── friends.md                      # Friends/social system
│   ├── p2p.md                          # P2P worlds & tunneling
│   ├── mod-management.md               # Mods & modpacks
│   ├── content-storage.md              # Global store + profile links model
│   ├── infrastructure.md               # Infrastructure overview
│   ├── data-flow.md                    # Data flow diagrams
│   └── diagrams-flows.md               # Mermaid diagrams
│
├── protocols/                          # Wire protocols
│   ├── skins-api.md                    # Skin/cape CustomSkinAPI
│   ├── invites-api.md                  # Invite codes ↔ tunnel addresses
│   └── friends-api.md                  # Friends WebSocket protocol
│
├── development/                        # Developer guides
│   ├── setup.md                        # Prerequisites, env, running
│   ├── development-workflow.md         # Branching, testing, PRs, releases
│   └── testing.md                      # All test suites, adding tests
│
├── release/                            # Release process
│   ├── build.md                        # Platform builds, PyInstaller
│   └── release-checklist.md            # Pre/post-release verification
│
└── decisions/                          # Design decisions & history
    ├── bugs-and-flaws.md               # Known issues catalog
    ├── production-readiness-gaps.md    # Production gaps
    ├── phase1-skins-capes.md           # Skins/cape design history
    ├── phase2b-batch2.md               # P2P design batches
    ├── phase2b-batch3.md
    ├── phase2b-batch4.md
    ├── phase2b-batch5.md
    ├── phase2b-batch6.md
    ├── skins-identity-workflow.md      # Skin identity deep-dive
    ├── modpack-install-version-matching.md
    ├── discord-server-layout.md
    ├── customskinloader-verified-facts.md
    ├── modpack-providers.md
    ├── cubeon-friends-mod.md
    ├── production-blockers.md
    └── friends-menu-notes.md
```

## Key Reference Files

| File | Purpose |
|------|---------|
| `architecture/launcher.md` | Maps `cubeon/` modules to responsibilities |
| `protocols/skins-api.md` | Worker routes, KV layout, CSL registration |
| `protocols/friends-api.md` | Durable Object design, WebSocket protocol |
| `development/testing.md` | All 40+ test suites with descriptions |
| `release/build.md` | PyInstaller flags, cross-compile recipes |

## Keeping Docs Current

- **Architecture docs** reflect the *current* code - update when modules change
- **Protocol docs** must match Worker source - parity tests enforce this
- **Decision docs** are append-only history - don't rewrite, add new entries
- **Release docs** updated per release cycle

## Related

- [Root README](../README.md) - Project overview & quick links
- [Module Map](../agents/docs/module-map.md) - Durable invariants for AI agents
- [Worker README](../worker/README.md) - Worker deploy/verify commands
- [Tools README](../tools/README.md) - Test suite quick reference