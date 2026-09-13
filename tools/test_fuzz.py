#!/usr/bin/env python3
"""
Fuzz / chaos monkey for the Cubeon UI (headless).

This is NOT a "drive a live window and click things" test. Flet has no headless
click driver, and a real window would fire real downloads, real deletes and real
subprocesses - a monkey on a live window mostly tests your network and disk, not
your code. Instead this builds the whole UI against a fake Page (same trick as
test_ui_smoke.py), walks the control tree, and *invokes every
on_click/on_change/on_submit handler directly* with hostile input - after
stubbing every destructive leaf, so nothing can touch the real ~/.minecraft or
hit the network. paths.py hard-codes the real install dir with no env override,
so the safety here is by construction (stubbed leaves), never "hope the sandbox
catches it".

The shared machinery (the hostile-input corpus, the FakePage, the tree walkers,
the defect-capturing fire(), and - critically - the safety stub layer) lives in
_fuzz_common.py, so the windowed demo (fuzz_visual.py) reuses the exact same
safe stubs and can never drift into touching the real install.

WHAT IT HARD-FAILS ON - only defect signatures that bad input must never cause:
  * NameError / UnboundLocalError   - a closure lost a variable, or a background
                                       worker read a var set on the other branch
                                       of a mid-fetch race (exactly the
                                       _render_browse_page bug found this session)
  * "coroutine ... was never awaited" RuntimeWarning - a coroutine called bare
                                       from a sync handler (exactly the async
                                       focus() no-op found this session)
These fire in handlers AND in the background threads handlers spawn (captured via
threading.excepthook). Everything else a handler raises on junk - a ValueError
from a validator rejecting "", etc. - is EXPECTED and only listed, never failed.

Plus a pure-input half that hard-asserts the security invariants of the
importable guards: no fuzzed name may escape its folder or crash the validator.

Run: python3 tools/test_fuzz.py
"""
import gc
import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import _fuzz_common as fz
from _fuzz_common import (
    FUZZ, FakePage, walk, every_control, fire, DEFECT_EXC,
    ctrl_text, find, subtree_text, clickable_with_subtext, set_fields,
)

# Shared accumulators (same list/dict objects the stub layer & run_task write to).
observations = fz.OBSERVATIONS
invoked = fz.INVOKED
ASYNC_DEFECTS = fz.ASYNC_DEFECTS
thread_errors = fz.THREAD_ERRORS

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


# ================================================================== STUBS ======
# Everything with a real side effect is replaced BEFORE the UI is built. (All the
# monkeypatching lives in _fuzz_common.install_safe_stubs - see that file for the
# full safety rationale.)
stubs = fz.install_safe_stubs(verbose=True)
app = stubs.app
core = stubs.core


# ================================================================ build UI ====
print("\n1. the app builds headlessly under stubs")

import warnings
page = FakePage()
build_defects = []
with warnings.catch_warnings(record=True) as caught:
    warnings.simplefilter("always")
    try:
        app.main(page)
        gc.collect()
        built, build_err = True, ""
    except Exception:
        import traceback
        built, build_err = False, traceback.format_exc()
for w in caught:
    if issubclass(w.category, RuntimeWarning) and "never awaited" in str(w.message):
        build_defects.append(str(w.message))

check("main(page) built without raising", built, build_err)
check("build raised no un-awaited-coroutine warning", not build_defects,
      "; ".join(build_defects))
if not built:
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)


# ============================================================== the monkey ====
print("\n2. fuzz every handler with hostile input (deletes/downloads stubbed)")

TEXTISH = {"TextField", "Dropdown"}
fired = set()          # (id(control), attr, value) - never fire the same twice
all_defects = []       # hard-fail (accumulated across blind + directed sweeps)
total_fires = 0
MAX_FIRES = 20000      # backstop against a handler that keeps opening dialogs


def set_all_fields(controls, value):
    """Type the fuzz value into every text-ish field, so the on_click handlers
    (which read field .value, not the event) see hostile input."""
    for c in controls:
        if type(c).__name__ in TEXTISH:
            cur = getattr(c, "value", None)
            if isinstance(cur, (str, type(None))):
                try:
                    c.value = value
                except Exception:
                    pass


def fire_control(c, value):
    """Fire every handler on one control, recording defects/observations."""
    global total_fires
    for attr in ("on_change", "on_submit", "on_click"):
        h = getattr(c, attr, None)
        if not callable(h):
            continue
        key = (id(c), attr, value)
        if key in fired:
            continue
        fired.add(key)
        total_fires += 1
        defects, benign = fire(h, c)
        for d in defects:
            all_defects.append(f"[{type(c).__name__}.{attr} | value={value!r:.40}] {d}")
        for b in benign:
            observations.append(f"{type(c).__name__}.{attr}: {b}")


for value in FUZZ:
    # A few passes: firing a click opens a dialog whose controls only exist
    # afterwards, so re-walk and fuzz the newly-appeared controls too.
    for _pass in range(3):
        controls = every_control(page)
        set_all_fields(controls, value)
        for c in controls:
            fire_control(c, value)
        if total_fires >= MAX_FIRES:
            break
    if total_fires >= MAX_FIRES:
        observations.append(f"hit MAX_FIRES={MAX_FIRES} - stopped early")
        break

print(f"  fired {total_fires} handler invocations across {len(FUZZ)} inputs")


# ================================================== directed scenarios ========
# Blind junk can't reach the guarded flows: delete/launch need a selected
# INSTALLED version, launch needs a valid username, export needs a non-empty
# pack name - every fuzz value fails those gates first. And other tabs' content
# only mounts when you navigate to them, so the Create-modpack button isn't even
# in the tree until then. So: a FRESH build per scenario (no cross-contamination
# - e.g. a Play that marks the version "running" would otherwise block Delete),
# navigate explicitly, set VALID state, fire. Also catches a bug class fuzzing
# can't: a handler that crashes on GOOD input.
print("\n2b. directed scenarios: drive the guarded flows with valid input")


def goto(pg, tab_label):
    """Fire the sidebar nav button for a tab so its content mounts."""
    for c in every_control(pg):
        if callable(getattr(c, "on_click", None)):
            # a nav button's own Row holds exactly the label text
            if any(ctrl_text(x).strip() == tab_label for x in walk(c)):
                fire_control(c, f"__nav_{tab_label}__")
                return True
    return False


def fresh_build():
    pg = FakePage()
    app.main(pg)
    return pg


# --- Scenario A: Play -> launch_game (valid username + installed version) ---
pgA = fresh_build()
set_fields(pgA, "TextField", "Username", "TesterName")
set_fields(pgA, "Dropdown", "Version", "1.20.1")
# The real Play button wraps a "PLAY"/"DOWNLOAD" Text; fire every play-ish
# clickable (firing the nav "Play" too is harmless - it just reselects the tab).
for btn in clickable_with_subtext(pgA, "play"):
    fire_control(btn, "__directed_play__")

# --- Scenario B: Delete instance -> confirm -> delete_version ---
pgB = fresh_build()
set_fields(pgB, "Dropdown", "Version", "1.20.1")
for btn in find(pgB, lambda c: (getattr(c, "tooltip", "") or "") == "Delete instance"):
    fire_control(btn, "__directed_delete_open__")      # opens the confirm dialog
for btn in find(pgB, lambda c: type(c).__name__ == "TextButton"
                and ctrl_text(c).strip().lower() == "delete"):
    fire_control(btn, "__directed_delete_confirm__")

# --- Scenario C: Modpacks tab -> Create -> valid name -> Export ------------
pgC = fresh_build()
goto(pgC, "Modpacks")                                  # mount the modpacks tab
for btn in clickable_with_subtext(pgC, "create modpack"):
    fire_control(btn, "__directed_create_open__")      # opens the create dialog
set_fields(pgC, "TextField", "Pack name", "My Test Pack")   # the gate that blocks export
set_fields(pgC, "TextField", "Version", "1.0.0")
for btn in clickable_with_subtext(pgC, "export .mrpack"):
    fire_control(btn, "__directed_export__")           # starts the export worker

# --- Scenario D: Mods -> Resource Packs -> Download (the deps_note bug) -----
# Navigating to Mods loads recommended *mods*; switching the content-type
# segment to Resource Packs instead loads packs, so build_browse_row() runs
# its non-mod branch and its on_download worker calls download_content(). That
# worker used to read deps_note with no binding on the resourcepack path ->
# UnboundLocalError, swallowed by the generic except and shown to the user as
# a dead "Failed" install. Drive it deliberately: mount Mods, switch segment,
# let the browse worker render rows, then click Download.
pgD = fresh_build()
goto(pgD, "Mods")
for seg in clickable_with_subtext(pgD, "resource packs"):
    fire_control(seg, "__directed_content_seg__")
for t in list(threading.enumerate()):
    if t is not threading.current_thread() and t.daemon:
        t.join(timeout=0.5)
gc.collect()
for btn in clickable_with_subtext(pgD, "download"):
    fire_control(btn, "__directed_content_download__")
for t in list(threading.enumerate()):
    if t is not threading.current_thread() and t.daemon:
        t.join(timeout=0.5)
gc.collect()
# Every install leaf is stubbed to SUCCEED, so a row that ends up saying
# "Failed" is a defect the generic except swallowed - exactly how the unbound
# deps_note read (resourcepack/shader install) reached the user as a dead
# "Failed" while every other test stayed green.
d_failed = [ctrl_text(c) for c in every_control(pgD)
            if "failed" in ctrl_text(c).lower()]
check("content install under stubbed success never reports Failed",
      not d_failed, "; ".join(d_failed))

print(f"  total after directed: {total_fires} invocations")

# Give any spun-up worker threads a moment, then fold their exceptions in.
for t in list(threading.enumerate()):
    if t is not threading.current_thread() and t.daemon:
        t.join(timeout=0.5)
gc.collect()
thread_defects = [f"thread {n}: {m}" for (n, m) in thread_errors if n in DEFECT_EXC]
thread_benign = [f"thread {n}: {m}" for (n, m) in thread_errors if n not in DEFECT_EXC]
observations.extend(thread_benign)

print(f"  fired {total_fires} handler invocations across {len(FUZZ)} inputs")
check("no NameError / UnboundLocalError / un-awaited coroutine in any handler",
      not all_defects, "\n       ".join(all_defects[:25]))
check("no defect-class exception in any background worker thread",
      not thread_defects, "\n       ".join(thread_defects[:25]))

async_defects = [d for d in ASYNC_DEFECTS
                 if any(d.startswith(k) for k in DEFECT_EXC)]
check("no defect-class exception in any run_task coroutine (picker/refocus)",
      not async_defects, "\n       ".join(async_defects[:25]))

# Coverage: prove the monkey actually reached the dangerous handlers. A green
# run that never fired delete/export/launch would be meaningless.
print("  reached effectful handlers: " +
      (", ".join(f"{k}×{v}" for k, v in sorted(invoked.items())) or "NONE"))
CRITICAL = ["delete_version", "export_mrpack", "launch_game", "save_config"]
missed = [c for c in CRITICAL if c not in invoked]
check("fuzz reached the critical destructive handlers "
      f"({', '.join(CRITICAL)})", not missed,
      f"never reached: {missed}")


# ===================================================== pure-input invariants ==
# The security guards, hit directly with the same corpus. These are hard
# assertions: a fuzzed name must never escape its folder or crash the validator.
print("\n3. input guards hold under the same corpus")

from cubeon.config import validate_username
from cubeon import friends
from cubeon.modpacks import _safe_relpath, ModpackError
from cubeon.server import _sanitize

# validate_username: total function, only ever (bool, str), never raises.
uv_ok = True
for v in FUZZ:
    try:
        r = validate_username(v)
        if not (isinstance(r, tuple) and len(r) == 2 and isinstance(r[0], bool)):
            uv_ok = False
            observations.append(f"validate_username({v!r:.30}) -> {r!r}")
    except Exception as ex:
        uv_ok = False
        observations.append(f"validate_username raised on {v!r:.30}: {ex}")
check("validate_username never raises and always returns (bool, str)", uv_ok)

# accepted usernames must actually be safe (ascii word chars, 3-16).
import re
uv_safe = all(
    (not validate_username(v)[0]) or re.fullmatch(r"[A-Za-z0-9_]{3,16}", v)
    for v in FUZZ)
check("validate_username only accepts [A-Za-z0-9_]{3,16}", uv_safe)

# canonical_name: None or a safe lowercased token, never raises.
cn_ok = True
for v in FUZZ:
    try:
        r = friends.canonical_name(v)
        if r is not None and (not isinstance(r, str) or r != r.lower()):
            cn_ok = False
            observations.append(f"canonical_name({v!r:.30}) -> {r!r}")
    except Exception as ex:
        cn_ok = False
        observations.append(f"canonical_name raised on {v!r:.30}: {ex}")
check("canonical_name never raises; returns None or a lowercased token", cn_ok)

# _safe_relpath: every fuzzed name stays inside base, or raises ModpackError.
# It must NEVER return a path outside base.
base = os.path.abspath(os.path.join(os.sep, "tmp", "cubeon_fuzz_base"))
escapes = []
for v in FUZZ:
    try:
        dest = _safe_relpath(base, v)
        if dest != base and not dest.startswith(base + os.sep):
            escapes.append((v, dest))
    except ModpackError:
        pass          # refusing a traversal is the correct behavior
    except Exception as ex:
        escapes.append((v, f"unexpected {type(ex).__name__}: {ex}"))
check("_safe_relpath never resolves outside its base dir", not escapes,
      "; ".join(f"{v!r}->{d}" for v, d in escapes[:10]))

# server _sanitize: output is always a safe path segment (no separators/dots-run).
san_ok = all(
    re.fullmatch(r"[A-Za-z0-9.+_]+", _sanitize(v)) and _sanitize(v) not in ("", ".", "..")
    for v in FUZZ)
check("server._sanitize always yields a safe, non-empty segment", san_ok)

# The modpack filename builder (built this session) - reproduce it and prove no
# fuzzed pack name yields a path separator or an empty stem.
def _pack_filename(name, version):
    stem = "".join(c if (c.isalnum() or c in "-_.") else "_"
                   for c in f"{name}-{version}").strip("_.")
    return (stem or "modpack") + ".mrpack"

pf_ok = all(
    (os.sep not in _pack_filename(v, "1.0.0"))
    and ("/" not in _pack_filename(v, "1.0.0"))
    and (os.path.basename(_pack_filename(v, "1.0.0")) == _pack_filename(v, "1.0.0"))
    and _pack_filename(v, "1.0.0").endswith(".mrpack")
    for v in FUZZ)
check("_pack_filename yields a single safe .mrpack filename for any name", pf_ok)


# ===================================================================== report ==
if observations:
    print(f"\n   {len(observations)} non-fatal observations "
          f"(handlers rejecting junk as designed - review, not failures):")
    # De-dupe and cap so the tail stays readable.
    seen_obs = []
    for o in observations:
        if o not in seen_obs:
            seen_obs.append(o)
    for o in seen_obs[:40]:
        print(f"     - {o}")
    if len(seen_obs) > 40:
        print(f"     ... and {len(seen_obs) - 40} more")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
