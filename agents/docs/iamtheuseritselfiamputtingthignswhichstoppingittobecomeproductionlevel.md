Good question — the repo already has a full audit (`agents/docs/production-readiness-gaps.md`), and I've since closed a few of its items. Here's the honest list, updated for what's been done, grouped by what actually blocks shipping:

## 🔴 Blockers (would embarrass you on day one)

1. **No auto-update.** Users on v1 forever, silently running bugs you've already fixed. No version check, no release feed, CI builds artifacts but never publishes them. This is the single biggest one.
2. **No CI test job.** You have ~440 checks across test scripts, but CI (`build.yml`) only *builds* — it never runs them. Regressions ship unnoticed. (Effort: low, payoff huge.)
3. **Silent error swallowing.** Lots of `except Exception: pass` across `main.py`, tabs, and `cubeon/`. Plus no file logging — when a user reports "it doesn't work," you have zero diagnostics. Needs: rotating log file + a "Copy diagnostics" button.
4. **No real-world validation of the social layer.** A two-launcher, two-player in-game session has *never* happened. Everything was verified via tests and single-player. The relay also lags the repo (no version handshake between worker and clients).

## 🟠 Serious (hit within the first week of real users)

5. **No download retry/resume.** One flaky Wi-Fi moment during a 500 MB Paper jar or modpack download = corrupted install. (Disk-space pre-check: ✅ done. Concurrency limits on pack installs: missing.)
6. **Friends relay is a trust point.** The worker holds claim/rename state and identity binding; no rate limiting or abuse handling documented. A bad actor squatting names or spamming invites has nothing stopping them.
7. **No crash reporter / telemetry.** Field failures are invisible. Even opt-in crash upload would transform your ability to fix things.
8. **Windows is unsigned.** SmartScreen will scare off every new Windows user with a scary warning. Costs money (~$100–400/yr cert) but it's a real adoption blocker.
9. **No watchdog on the game process** — zombie/crashed MC processes aren't detected or cleaned up.

## 🟡 Polish (matters for reputation, not survival)

10. **No first-run onboarding** — new users see a control-room UI and don't know what to do first.
11. **No macOS / ARM64 builds**; Linux has no deb/Flatpak packaging (AppImage only).
12. **No minimize-to-tray, no background toasts** (download finished, friend online — nothing surfaces until you look).
13. **No i18n / accessibility / keyboard shortcuts.**
14. **Packaging gotcha from today's work:** PyInstaller builds must bundle `assets/` (jars) — if a distributed build ships without it, jar discovery silently degrades.

## What's already off the list (done recently)

✅ Disk-space guards · ✅ Stale-jar detection & self-warning · ✅ Hermetic test suite with ~440 checks · ✅ Human-readable error messages in UI and mod chat · ✅ Orphan process detection on servers · ✅ Single source of truth for MC version brackets

## My recommended order

If you want the shortest path to "safe to give to friends": **CI test job → file logging → auto-update version check → one live two-player test**. Those four are each small-to-medium and eliminate the worst failure modes. Everything else can come after real people are using it.

Want me to start on any of these? The CI test job is probably a 30-minute win I could do right now.