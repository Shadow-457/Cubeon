# Fix problems ate Sodium, a skin back view, and "Java not found" when Java worked (2026-10-18)

**Model:** DeepSeek V4.1 Flash Free (OpenCode) · one session, three user reports,
one release (v1.2.11).

Three reports, three unrelated places, one theme: **the launcher asserted
something it had not actually established.** The doctor decided a mod couldn't
load from a failed *lookup*; the launch-failure text decided Java was missing
from a substring that always appears; the skin preview only ever showed a
mirrored back. All three are now based on evidence.

## 1. "whenever i press fix problems it just disables my sodium and some mods" 🔴→✅

Reproduced on the maintainer's real profile
(`~/.cubeon_launcher/mod_profiles/26.1.2-fabric`). `Fix problems` → the mod
doctor's pass 4b (`mod_doctor` in `cubeon/mods.py`) reported problems for
**sodium, modmenu and c2me** and then **toggled all three off** — every single
run, even though nothing was wrong with them.

Root cause: the `depends` pass. Each mod declares required dependency **ids**
in its own metadata, and the doctor checked those ids against the set of
*top-level* jars it could see. It could not see them because **mods ship other
mods inside themselves**:

* Fabric API ships **43 jar-in-jar modules** — that is where
  `fabric-block-getter-api-v2`, `fabric-rendering-fluids-v1` and
  `fabric-resource-loader-v0` (Sodium's three declared deps) actually live;
* Mod Menu bundles 4 more of its own;
* c2me bundles `c2me-base`, which it also declares.

So the lookup failed for every one of them, the pass treated "I couldn't find
the id" as "the declaring mod can't load", and disabled the mod that was
perfectly fine. The fix is two rules:

1. **Index bundled modules.** `_nested_mod_metadata()` reads the nested
   `fabric.mod.json` files (depth 2), and pass 4b builds a `provided` index of
   every id any installed jar supplies — **highest version wins** when several
   jars carry the same module (Fabric API's own copy vs. a separately-installed
   one).
2. **Never auto-disable on an unresolved dependency.** A dependency the doctor
   cannot find is reported, never acted on. Guessing from absence is what broke
   this; a human decides. (The `breaks` conflict auto-disable stays — it is
   decided from jar metadata that is actually present.)

`tools/test_doctor_bundled_deps.py` (19 checks) pins both, using the real
profile's shapes: a nested provider satisfies a top-level declarer, highest
version wins, an unresolved dep is reported with **0 toggles**, and the
old-behaviour simulation (nested index stubbed out) still reports 8 deps but
disables nothing.

## 2. Front/Back view in the skin area

Request: *"creating a option in skin area which lets us see the skin from back."*

`cubeon/skins.py::render_local_skin_preview(..., view="front")` now renders a
real **180° turn**, not a cosmetic flip: for `view="back"` it crops the
**back faces** from the 64×64 sheet (head +16, torso +12, limbs +8) and the two
sides swap places (the model's left becomes the viewer's left). A legacy 64×32
sheet has no back faces at all, so the back view mirrors the front — the only
honest thing to do with data that isn't there. Default stays `view="front"`, so
gallery/thumbnail callers are untouched.

`ui/skin_tab.py` gets a small `CupertinoSlidingSegmentedButton` (`Front`/
`Back`), hidden until a skin is active. The preview is single-flight
(`_preview_state` / `_preview_lock` / generation guard) and the view is read
**at render time**, so a switch mid-render can't paint a stale face; previews
are cached per view (`_preview_<view>_<filename>.png`); box height 354→392.

Tests: `tools/test_skin_preview.py` gains back-view geometry + legacy-sheet +
unknown-view cases; `tools/test_ui_smoke.py` §probe gains "the selected skin
view reaches the renderer" (the probe extracts the functions by source, so its
scope had to define `_view_state` / `_sync_view_toggle`).

Worth knowing, not changed: the **existing front render is itself mirrored**
relative to a true front-facing view. The front/back pair is still a valid
rotation of each other, so the switch is correct as a *pair*; fixing the global
mirror is a separate (visual) decision.

## 3. "Crashed: Java not found" on a launch that had just run a JVM

User report: *"it says crashed: no java found bla bla…. minecraft crashes with
this error even if java fine bcz it ran minecraft in first place."* The user was
right, twice over.

`main.py::_explain_exit` picks the sentence shown after a game exits. Its Java
branch read:

```python
if "cannot run program" in low or "no such file or directory" in low and "java" in low:
```

Two bugs in one line:

* `and` binds tighter than `or`, so this is `A or (B and C)` — **any**
  `Cannot run program` line in the game's output blamed Java.
* `B and C` is true on (almost) **every** launch: the launch command itself,
  JVM path included (`/usr/lib/jvm/java-21-openjdk/...`), is part of the output
  the launcher reads. So the word "java" is always present and any stray
  `No such file or directory` — a mod's config, a shader include, a missing
  native, a mod shelling out to `xdg-open` — became "Java not found", discarding
  the real error line. Users were sent to reinstall a JDK for a game that had
  demonstrably started one.

Fix: Java evidence is now matched per **LINE**, which is what stops the JVM path
in the launch command from counting. Accepted: `Cannot run program "java"` /
`"javaw"`, `Could not create the Java Virtual Machine`, or a
`No such file or directory` line that also names Java. A rejected JVM option
gets its own message ("Java rejected one of the launch options — reset the JVM
arguments"), because the JVM prints the option on one line and
`Could not create the Java Virtual Machine` on another. Everything else falls
through to the real error line; when there is genuinely nothing to go on, the
message now **says so** and points at Fix problems instead of guessing "check
that Java matches".

`tools/test_ui_smoke.py` §4 drives the exact reported shape (JVM path in the log
+ an unrelated missing file) and the genuine cases (missing `java`, missing
`javaw`, bad JVM option, wrong class-file version).

## 4. Repo cleanup (conservative)

* `git worktree prune` — 5 stale registrations from long-gone worktrees.
* `__pycache__` dirs removed.
* `Ylem.jpg` (the maintainer's 1920×1080 source image at the repo root) added to
  `.gitignore` — kept on disk, never committed, can't ride along in a
  `git add -A`.
* **Nothing regenerable-and-large was deleted**: `dist/` (614M), `build/` (38M),
  `archive/` (1.8G) and `.venv-build/` (120M) are all still there. They are
  rebuildable, but "clean up without deleting or ruining anything" was the ask,
  so they were left alone.

## Verified
Full CI-equivalent suite (`bash /tmp/opencode/run_suite.sh`, skips the manual
`test_visual_*` and `test_wedge_watchdog.py`): **SUITE_DONE failed=0**.
Focused: `test_ui_smoke.py` 256/0, `test_doctor_bundled_deps.py` 19/0,
`test_skin_preview.py` PASS, `test_mod_detail.py` 81/0, `test_auto_cleanup.py`
33/0, `test_launch_fixes.py` 113/0. The doctor fix was additionally reproduced
against the real profile (12 checked, 0 problems, 0 toggles) and against a
simulated old build (8 deps reported, still 0 toggles) — the second run proves
the auto-disable is gone, not merely that lookups now succeed.

## Open thread for the next agent
* **Mesa**: unchanged from the previous note — the crash is in Mesa 26.1.x
  `libgallium`, fixed user-side by updating Mesa. The launcher only diagnoses.
* **Skin front render is mirrored.** A true front view is the natural next
  polish; the Front/Back rotation pair is already consistent.
* **The gate log flood**: one run showed `gate: password set for 1.20.1` ~40
  times in 50 seconds (`ui/server_tab.py::on_gate_set`). Every call there
  succeeded, so it wasn't a rejected password — something invoked the handler
  repeatedly. Not chased (no reproduction, and the handler is a plain
  `on_click`); if a report appears, start from whether the click is being
  re-delivered or the field submitted on every keystroke.
