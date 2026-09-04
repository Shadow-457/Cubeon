# Production Readiness Gap Analysis

> This document identifies the gaps between Cubeon's current prototype state and a production-grade desktop application. It is a *no-code* audit - meant to guide future work, not prescribe implementation details.

---

## 1. Testing & Quality Assurance

### What exists today
- Hand-rolled test scripts in `tools/` (`test_friends.py`, `test_invites.py`, `test_modpacks.py`, `test_client_json.py`, etc.)
- A fuzz harness (`tools/test_fuzz.py`) and a UI smoke test (`tools/test_ui_smoke.py`)
- No standard test framework (pytest/unittest); tests are standalone scripts with manual `check()` helpers
- No CI test step - `.github/workflows/build.yml` only builds, never runs tests

### What's missing
| Gap | Risk |
|-----|------|
| No pytest/unittest integration | Can't discover tests automatically; no CI gating |
| No CI test job | Regressions ship unnoticed |
| No unit test coverage tracking | No visibility into which modules are exercised |
| No integration tests against real Worker backends | Client↔server contract breakage only caught manually |
| No property-based / fuzz testing in CI | Edge cases found by `test_fuzz.py` only run locally |
| No load/stress tests for WebSocket connections | Friends/voice scale unknown |
| No regression test suite | Bugs that are fixed can re-emerge silently |

### Recommendation
Adopt `pytest` as the standard runner. Add a CI job that runs `pytest` on every PR. Target at minimum 60% line coverage on `cubeon/` modules before shipping.

---

## 2. Error Handling & Observability

### What exists today
- Broad `except Exception: pass` / `except Exception as ex: ...` scattered across `main.py`, all tab modules, and `cubeon/` - many silently swallow errors
- `logging` is imported in ~7 `cubeon/` modules but used sparingly; no centralized log configuration
- Game crash exit codes are translated to human-readable messages in `_explain_exit()`
- No structured error types - everything flows through generic exceptions

### What's missing
| Gap | Risk |
|-----|------|
| No centralized logging configuration (level, format, rotation) | Debugging production issues requires source-code archaeology |
| No crash reporter / telemetry | Silent failures in the field have no signal back to developers |
| Many `except Exception: pass` blocks | Bugs are hidden, not fixed |
| No structured error taxonomy (custom exception classes) | Error handling is inconsistent and hard to search |
| No user-facing error log / diagnostic export | Support is "describe what happened" only |
| No health-check endpoint or self-test on startup | Broken state discovered only when the user hits a button |

### Recommendation
- Define a small set of custom exception classes (`LaunchError`, `SkinUploadError`, `FriendsConnectionError`, etc.) and replace bare `except Exception` at module boundaries with specific catches.
- Add a configurable logging handler that writes to `~/.cubeon_launcher/cubeon.log` with rotation.
- Add a "Copy diagnostics" button in Settings that exports the log + system info.

---

## 3. Auto-Update Mechanism

### What exists today
- No self-update capability whatsoever
- Users must manually download a new AppImage/EXE when a new version ships
- `.github/workflows/build.yml` produces artifacts but doesn't publish release assets

### What's missing
| Gap | Risk |
|-----|------|
| No version check against a release feed | Users stay on stale builds indefinitely |
| No in-app update prompt or download | Bug fixes and security patches don't reach users |
| No release tagging / changelog automation | No structured release process |
| No code-signing (Windows EXE / macOS .app) | SmartScreen / Gatekeeper warnings block installs |

### Recommendation
- Implement a lightweight version-check against a release endpoint (e.g., a JSON file on your distribution site).
- Show a non-blocking banner: "Update available: v1.2.3 - Download" with a link.
- Add a `version` field to the app (currently hardcoded as `"1.0"` in the launch command).

---

## 4. Security

### What exists today
- `auth_key.json` is written with `0o600` permissions (best-effort)
- `identity.json` (Friends secret) is also `0o600`
- The Friends WebSocket authenticates via the secret over WSS (encrypted)
- AuthMe plugin is auto-installed on servers for login security
- Online-mode is `false` by design (cracked accounts)

### What's missing
| Gap | Risk |
|-----|------|
| No HTTPS enforcement on all Worker endpoints | Man-in-the-middle on API calls |
| No certificate pinning for Worker backends | Compromised CDN/proxy can intercept traffic |
| No input sanitization on server motd / commands sent to subprocess | Potential injection in server console |
| No rate limiting on name-claim / skin-upload APIs | Abuse vector |
| No content security policy for the marketing web page | XSS if the page ever allows user content |
| No signed builds (Windows Authenticode, macOS notarization) | SmartScreen / Gatekeeper warnings; tamper detection |
| No secrets scanning in CI | Leaked keys could go unnoticed |
| No dependency vulnerability scanning (Snyk, pip-audit) | Known CVEs in pinned deps |

### Recommendation
- Enforce HTTPS everywhere; add a startup check.
- Add `pip-audit` or Snyk to the CI pipeline.
- Sanitize all user-supplied strings before passing to `subprocess.Popen` or server console.

---

## 5. Configuration & Data Migration

### What exists today
- `config.json` uses a `DEFAULT_CONFIG` dict with `{**DEFAULT, **loaded}` merge
- `auth_key.json` has a legacy migration path (`{uuid, secret}` → `{public_uuid, secret_token}`)
- Mod profiles have a one-time migration from the old shared `mods/` folder
- `server.jar` → `server-paper.jar` migration exists

### What's missing
| Gap | Risk |
|-----|------|
| No versioned config schema | A config format change silently drops unknown keys |
| No forward-compatible migration system | Upgrading breaks older data formats |
| No backup-before-migrate pattern for all migrations | A failed migration can lose data |
| No config validation on load | Corrupt configs silently revert to defaults |
| No export/import of full launcher state | Moving machines = manual file copying |

### Recommendation
- Add a `config_version` integer to `config.json`. On load, run migrations forward from the stored version to the current version.
- Add a "Reset to defaults" button with a confirmation dialog in Settings.
- The existing backup system (`cubeon/backup.py`) should be promoted to a first-class "Export / Import" feature in the UI.

---

## 6. Documentation

### What exists today
- `README.md` is thorough (features, layout, build instructions)
- `docs/` contains design history, workflow docs, and a tunneling guide
- `tools/README.md` documents the test suite
- `packaging/BUILDING.md` covers build steps
- `worker/README.md` covers Worker deployment

### What's missing
| Gap | Risk |
|-----|------|
| No API contract documentation for Worker endpoints | Client↔server changes require reading JS source |
| No internal developer setup guide (IDE, linting, test commands) | New team members can't bootstrap |
| No architecture decision records (ADRs) | Design rationale is scattered in commit messages |
| No user-facing help / FAQ | Support burden falls on Discord |
| No changelog / release notes | Users don't know what changed between versions |

### Recommendation
- Create `docs/api-contracts.md` documenting every Worker route, request/response shape, and error code.
- Create an internal dev setup doc (IDE config, linting, test commands) for team onboarding.
- Add a CHANGELOG and adopt [Keep a Changelog](https://keepachangelog.com/) format.

---

## 7. CI/CD Pipeline

### What exists today
- `.github/workflows/build.yml` builds Linux AppImage and Windows EXE on push to main/master and on tags
- Artifacts are uploaded but not published to a distribution channel

### What's missing
| Gap | Risk |
|-----|------|
| No CI test job (only build) | Regressions ship with every build |
| No linting / type-checking in CI | Code style drifts silently |
| No release automation (tag → build → publish) | Manual process is error-prone |
| No macOS build | macOS users are excluded |
| No Worker deployment automation | Manual paste into dashboard |

### Recommendation
- Add a `test` job to the workflow that runs `pytest` before the build jobs.
- Add `ruff` or `flake8` as a lint step.
- Create a release workflow: tag → build all platforms → publish to your distribution channel with changelog.

---

## 8. Performance & Reliability

### What exists today
- Game crash exit codes are translated to user-friendly messages
- Server orphan detection via `session.lock` / `F_GETLK`
- WebSocket reconnection with exponential backoff
- Thread-safe UI updates via `cubeon/thread_safe_ui.py`

### What's missing
| Gap | Risk |
|-----|------|
| No download retry with backoff for mod/paper downloads | A network blip permanently fails the download |
| No download resume (HTTP Range) for large files | Paper jar / mod downloads restart from zero |
| No concurrency limits on parallel downloads | A modpack install can open hundreds of connections |
| No disk-space check before download/install | Half-written files on full disk |
| No watchdog for the game process | Zombie processes if the game crashes uncleanly |
| No memory/CPU usage monitoring in the launcher itself | The launcher itself can become unresponsive |

### Recommendation
- Implement HTTP 206 Range-based resume for large downloads (Paper jar, mod jars).
- Add a disk-space pre-check before downloading.
- Add a periodic health-check thread that detects unresponsive Flet UI and offers a restart.

---

## 9. Platform & Compatibility

### What exists today
- Linux AppImage build
- Windows EXE/ZIP build
- macOS is mentioned in code (path detection, `open` command) but has no build pipeline

### What's missing
| Gap | Risk |
|-----|------|
| No macOS build (DMG / .app) | macOS users must run from source |
| No ARM64 builds (Apple Silicon, Linux aarch64) | Growing platform share excluded |
| No Windows code signing | SmartScreen blocks the EXE on fresh installs |
| No Linux package (deb, rpm, Flatpak, Snap) | Linux users must use AppImage or run from source |
| No FHS-compliant install path | AppImage is the only option |
| Flet version pinned tightly (`>=0.86,<0.87`) | Dependency on a single Flet release |

### Recommendation
- Add macOS to the CI build matrix (GitHub Actions `macos-latest`).
- Explore PyInstaller `--target-arch` for ARM64 builds.
- Consider Flatpak or AppImage as the long-term Linux distribution strategy.

---

## 10. User Experience Polish

### What exists today
- Custom dark "control-room" theme with consistent design tokens
- Sidebar navigation with hover states
- Avatar with animated parrot
- Crash explanations in plain English

### What's missing
| Gap | Risk |
|-----|------|
| No first-run / onboarding flow | New users don't know what to do first |
| No keyboard shortcuts / accessibility (screen readers) | Exclusion of power users and disabled users |
| No internationalization (i18n) | English-only limits global reach |
| No toast / notification system for background events | Users don't know when a download finishes or a friend comes online |
| No search / command palette | Discoverability of features is low |
| No minimize-to-tray | Closing the window is ambiguous (minimize or quit?) |

### Recommendation
- Add a one-time onboarding screen on first launch (username + version selection).
- Implement a simple toast notification system for background events (download complete, friend online).
- Add an "About" dialog with version, license, and links.

---

## Summary: Priority Matrix

| Priority | Area | Effort | Impact |
|----------|------|--------|--------|
| 🔴 P0 | CI test job (pytest in GitHub Actions) | Low | Catches regressions before ship |
| 🔴 P0 | Structured logging to file | Low | Debugging production issues |
| 🔴 P0 | Auto-update version check | Medium | Users get bug fixes |
| 🟠 P1 | Worker API documentation | Low | Enables parallel client/server work |
| 🟠 P1 | Download resume + retry | Medium | Reliable installs on bad networks |
| 🟠 P1 | macOS build in CI | Medium | Doubles the supported platform |
| 🟠 P1 | CHANGELOG + release automation | Low | Users know what's new |
| 🟡 P2 | Custom exception classes | Medium | Consistent error handling |
| 🟡 P2 | Disk-space pre-check | Low | Prevents partial installs |
| 🟡 P2 | First-run onboarding | Medium | Better first impression |
| 🟢 P3 | i18n framework | High | Global reach |
| 🟢 P3 | Accessibility audit | High | Inclusive design |
| 🟢 P3 | ARM64 builds | Medium | Future-proofing |
