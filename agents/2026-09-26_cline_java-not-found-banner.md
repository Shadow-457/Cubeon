# "Java N+ wasn't found" false banner (2026-09-26, cline)

## The report
Two screenshots, same build, one under the Play button:
- `Error: RuntimeError: Java 21+ wasn't found, so the Fabric installer can't run...`
- `... Java 17+ wasn't found ...` (GAME VERSION = **1.20.1**, Fabric, 1.20.1)

## First: the 17-vs-21 is NOT a bug
The `N` is `required_java_major(mc_version)` — the *selected Minecraft version*'s
requirement, not the user's Java. 1.20.1 → 17; ≥1.20.5 → 21. Different dropdown
selection, different message, same launcher. Don't "fix" this.

## What was actually broken (3 things, all fixed)
1. **`JAVA_HOME` was never read.** Resolution was Settings `java_path` → PATH →
   `mll.java_utils.find_system_java_versions()`. A user who installed Temurin
   and exported `JAVA_HOME` — the single most reliable signal that a machine
   has a JDK — was told no Java existed. → `launch._java_home_binaries()`,
   consulted by both `find_java()` (after PATH) and `find_java_for_version()`.
2. **A JDK *folder* pasted into Settings failed the same way.** A directory is
   not a file, so the `os.path.isfile()` guard reported "not found" on a
   machine that has Java. Found while writing the end-to-end sim (my helper
   returned the JDK home, and the guard correctly refused it — correct code,
   wrong UX). → `launch._normalize_java_path()` resolves a directory to
   `bin/java`; applied to the `java_path` arg AND the fallback.
3. **A too-old Java was accepted, contradicting the message.** The old check
   was `if java and (isfile or which): return java` — existence only.
   `find_java_for_version()` deliberately falls back to a too-old Java (so
   LAUNCH can show Minecraft's own clearer error), so a Java 8 on PATH reached
   the installer jar, which is *executed* and so died on a raw
   `UnsupportedClassVersionError` instead of the actionable banner. The
   docstring already claimed this fallback "is rejected" — it wasn't.
   → `loader_java` now probes `java_major_version()` and requires
   `>= required`, appending "Only Java N was found, which is too old for X."
   An **unprobeable** binary (major `None`) is still accepted, deliberately —
   a path we can't run must not become a new way to fail.

## Verification
`python3 tools/test_launch_fixes.py` → **85 passed, 0 failed**. New sections
§8c (too-old rejected; message honest; happy path unchanged; N tracks the MC
version), §8d (JAVA_HOME), §8e (JDK folder in java_path) — 16 new checks, using
executable stub JVMs that answer `-version` like a real one. Also
`tools/test_server_integrity.py` 59/59. `tools/test_mega_smoke.py` has 1
pre-existing failure (`open_cf_key_dialog` lambda missing arg `e`, a Flet API
thing) — confirmed identical on a `git stash` of my changes, so it is NOT mine.

Note for the next agent: `startupinfo=None` in `java_major_version()` is
Windows-only but harmless — CPython only raises when it's non-`None`. Not a
portability bug; don't "fix" it.

## Q for whoever picks this up
Does the **Settings → java_path** field in the UI say "path to the java
executable" anywhere? It now also accepts a JDK folder, but nothing tells the
user that. A one-line placeholder/hint would close the loop.
