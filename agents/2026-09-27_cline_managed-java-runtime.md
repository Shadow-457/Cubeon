# Ship Java with the launcher: offer a managed JRE on install (2026-09-27)

- **Agent:** Cline
- **Date:** 2026-09-27
- **Task:** "can we ship java with the launcher too - when it goes to install a
  version it sees if java is there, and if not prompts the user that java is
  missing and offers to install it alongside, then installs if they say so"

## What it does
New `cubeon/jre.py` (paths: `RUNTIMES_DIR = ~/.cubeon_launcher/runtimes/<major>/`).
`on_play_click` now checks Java **before** painting the busy state and, if the
selected version needs a Java this machine doesn't have, shows a dialog:
"Install Java N" / "Not now". Yes fetches a Temurin **JRE** from the Adoptium
API and installs it, then proceeds with the normal install. No (or dismissing
the dialog) cancels the whole install.

## Decisions worth knowing
- **JRE, not JDK.** Minecraft runs the game; it never compiles. A JRE is ~1/3
  the size. Verified live: the Temurin 17 JRE is 44 MB.
- **Offered, never forced, and never a replacement.** Managed runtimes are
  appended to the candidates in `find_java_for_version` *after* Settings ->
  PATH -> JAVA_HOME -> the mll scan, so a user who already has Java keeps
  running exactly what they had. Confirmed on this machine (has Java 21):
  1.21.4 still resolves to `/usr/bin/java` and never prompts.
- **Only when it matters.** The check is skipped when the version is already
  installed - a machine that ran it before doesn't get nagged on every launch.
- **Only majors `required_java_major` can return** (8/16/17/21/25), so a
  version can never demand a Java the launcher can't supply. Guarded by §14.
- **Prompt is BEFORE the busy paint** - otherwise the button would show a
  spinner for a question the user hadn't been asked yet, and "No" would leave
  it stuck. Hence the new `_begin_install_and_launch()` helper, which the
  dialog's actions call into.

## The bug this actually caught
First real end-to-end run failed with `Java 17 did not install correctly` -
**with a working JVM sitting on disk**. The Temurin archive nests the runtime
one level deep (`jdk-17.0.20.1+1-jre/bin/java`), and `managed_java()` looks
for `runtimes/17/bin/java`. The unpack was fine; the move was wrong.
`install_jre` now promotes the inner home out via a `.part.home` staging dir
before `os.replace`. This is exactly why I ran a real download rather than
only unit tests - the unit tests all passed while the feature was broken.
Regression pinned in §14 ("_extract returns the JRE home, not the extraction
root").

## Verification
- **Real end-to-end install**, sandboxed to /tmp: downloaded Temurin 17,
  sha256 verified, unpacked to the right path, and **actually ran it** ->
  `openjdk version "17.0.20.1" / OpenJDK Runtime Environment Temurin-17.0.20.1+1`.
  Second call returned the same path with no network (idempotent), and no
  `.part` dirs left behind.
- Resolution proven both ways: with system Java stubbed out, 1.20.1 resolves
  to the managed runtime and `java_status` is ok; 1.21.4 correctly reports
  Java 21 missing (so the prompt would fire).
- `tools/test_launch_fixes.py` **98/0** (85 before, +13 new in §14).
- `tools/test_ui_smoke.py` 166/0. `test_friends.py` 104/0.
  `test_server_integrity.py` 59/0. `test_mega_smoke --static` 15/0.
- `tools/test_mega_smoke.py` runtime: 18/1 - the same pre-existing
  `open_cf_key_dialog` lambda `TypeError` in `ui/modpacks_tab.py` confirmed
  earlier by `git stash`. Still not mine; still unfixed.

## For the next agent
- **I could not test the dialog visually** (no display this session). The
  source-level checks confirm the prompt fires before the busy paint and that
  the worker's Java step precedes both `install_version` and
  `install_mod_loader`, but nobody has SEEN the dialog. Worth a manual click
  on a machine with no Java.
- The dialog is wired to `_open_dialog`/`_close_dialog`; a user dismissing it
  with Escape routes through Flet's own close, which does NOT call `_not_now`
  - so the button keeps its pre-click state. That is the intended outcome
  (nothing was started), but it is unverified.
- Not wired: **servers** (`cubeon/server.py`) and the **modpack** installer can
  also need Java and still show the old error text. The Server tab has its own
  install path. Left alone deliberately - it is a separate flow with its own
  progress UI, and bolting the same prompt on there needs its own care.
- Durable invariants went into `agents/docs/module-map.md` ("Managed Java
  runtimes"), not into this note.