#!/usr/bin/env python3
"""Startup behaviour tests - the window/paint ordering and the network budget.

These reproduce, headlessly and on any OS, the two real startup failures the
launcher shipped with:

  * The splash was scheduled with ``page.run_task(_reveal_splash)``. A Flet
    "task" does not run until the coroutine that scheduled it returns, and
    main() built the ENTIRE control tree before returning - so the splash was
    never painted and the hidden window only appeared once everything was done
    (the "process runs but no window shows" report). main() is a coroutine now
    and AWAITS the splash before the build, so the client gets it immediately.

  * The synchronous build opened real sockets on its own thread: Mojang's
    patch-notes feed via ``version_art.meta`` (a 20s-timeout fetch with
    retries). With the network slow or down that added seconds - measured
    0.6s -> 6.9s on a blocked link - before anything painted. version_art is
    disk-only on the UI thread now and refreshes the feed on a worker.

  * The saved window geometry is restored at startup, so a size the user
    dragged LARGER than the desktop (or than the window manager's work area,
    i.e. the screen minus panels) made the flet client wait forever for an
    OpenGL frame at a size that could never arrive - "Timed out waiting for
    OpenGL frame of size 1900x1170 (have 1872x1170)" - and die. That is the
    "if I size it too much it won't open on the second launch" report. The
    geometry is now fitted to the work area (and applied to the still-HIDDEN
    window, so a visible resize never happens either).

The runtime checks here block outbound sockets and assert the build still
finishes quickly AND that NO socket was opened from the main thread.

Run: python3 tools/test_startup.py
"""
import ast
import os
import socket
import subprocess
import sys
import threading
import time

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

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


_main_src = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
_va_src = open(os.path.join(_ROOT, "cubeon", "version_art.py"),
               encoding="utf-8").read()


# ------------------------------------------------------- 1. ordering (static) ---
print("\n1. the splash is painted BEFORE the synchronous build")

# main() must be a coroutine so Flet AWAITS it (flet/app.py awaits a coroutine
# main) and our own `await`s get a chance to hand the loop back.
_main_tree = ast.parse(_main_src)
_main_fn = next((n for n in _main_tree.body
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                 and n.name == "main"), None)
check("main() is declared async (flet awaits it)",
      isinstance(_main_fn, ast.AsyncFunctionDef),
      f"main is {type(_main_fn).__name__}")
check("the app is still handed to ft.run",
      "ft.run(main," in _main_src or "ft.run(main)" in _main_src,
      "main must remain the entry point flet runs")

_i_splash_await = _main_src.find("await _reveal_splash()")
_i_swap = _main_src.find("page.controls.clear()")
check("the reveal of the splash is AWAITED, not a run_task",
      "page.run_task(_reveal_splash)" not in _main_src
      and _i_splash_await != -1,
      "a run_task only runs after main() returns - i.e. after the build")
# 2026-10-16: the launcher "flashed and closed" on the second launch. The
# saved window size is only restored now, so a window the user dragged large
# was resized WHILE VISIBLE on the next start; the desktop client then waits
# for an OpenGL frame at the new size and - on some Mesa/GTK setups - times
# out and dies before the finished UI paints. The geometry must land on the
# window while it is still hidden, i.e. before the splash is revealed.
_i_geometry_call = _main_src.find("\n    _apply_real_geometry()\n")
check("the saved geometry lands on the window BEFORE it is ever shown",
      _i_geometry_call != -1 and 0 <= _i_geometry_call < _i_splash_await,
      f"geometry at {_i_geometry_call}, splash await at {_i_splash_await} - "
      "resizing a visible flet window is the OpenGL-frame timeout")
check("that await precedes the first control-tree swap/mount",
      0 <= _i_splash_await < _i_swap,
      f"await at {_i_splash_await}, swap at {_i_swap}")
check("the finished-UI reveal is awaited too",
      "page.run_task(_reveal_window)" not in _main_src
      and "await _reveal_window()" in _main_src,
      "the swap patch must flush before the window is shown")
check("a sync entry point exists for the test/tool harnesses",
      "def run_sync(page)" in _main_src
      and "asyncio.run(main(page))" in _main_src,
      "harnesses build the UI from a plain script, not flet's loop")


# --------------------------------------------- 2. feed fetch is off-thread ----
print("\n2. the Mojang feed is never fetched on the UI thread")

check("version_art._official_map is disk-only by default",
      "def _official_map(allow_fetch: bool = False)" in _va_src,
      "meta() must never block the UI thread on Mojang's host")
check("the feed refresh runs on a daemon worker",
      "def _schedule_feed_refresh(" in _va_src and "daemon=True" in _va_src,
      "a cold cache must warm in the background, not inline")
check("the image downloader is the only fetcher",
      "_official_map(allow_fetch=True)" in _va_src,
      "only the worker path (fetch_async -> _fetch) may hit the network")


# --------------------------------------------------- 3. startup profiler ------
print("\n3. the opt-in startup profiler works and is silent by default")

_probe = (
    "import logging, sys;"
    "logging.basicConfig(level=logging.INFO, stream=sys.stdout);"
    "from cubeon.startup_profile import mark, enabled;"
    "print('enabled', enabled());"
    "mark('probe-mark')"
)
_on = subprocess.run([sys.executable, "-c", _probe], capture_output=True,
                     text=True, cwd=_ROOT,
                     env={**os.environ, "CUBEON_STARTUP_PROFILE": "1"})
check("marks are emitted when CUBEON_STARTUP_PROFILE=1",
      "enabled True" in _on.stdout and "startup-profile" in _on.stdout
      and "probe-mark" in _on.stdout,
      (_on.stdout + _on.stderr)[-300:])
_off = subprocess.run([sys.executable, "-c", _probe], capture_output=True,
                      text=True, cwd=_ROOT,
                      env={k: v for k, v in os.environ.items()
                           if k != "CUBEON_STARTUP_PROFILE"})
check("marks are silent (and cheap) when disabled",
      "enabled False" in _off.stdout and "startup-profile" not in _off.stdout,
      (_off.stdout + _off.stderr)[-300:])


# ------------------------------------------- 4. offline build is fast + safe ---
print("\n4. the real UI builds offline, fast, with no main-thread socket")

# Sandbox HOME / game dir BEFORE importing any cubeon module.
import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

import cubeon.versions as versions  # noqa: E402
import cubeon.csl as csl  # noqa: E402
versions.get_available_versions = lambda *a, **kw: [
    {"id": "1.21.11", "type": "release"}, {"id": "1.20.1", "type": "release"}]
versions.get_latest_release = lambda: "1.21.11"
csl.ensure_ready = lambda *a, **kw: None

# Refuse every outbound connection, recording any made FROM THE MAIN THREAD.
#
# LOOPBACK IS ALLOWED, and that exception is load-bearing ON WINDOWS - this
# section runs on windows-latest too. There, `socket.socketpair()` is a REAL
# loopback TCP pair, and asyncio's ProactorEventLoop builds its self-pipe with
# it, so patching connect unconditionally killed `asyncio.run()` itself: the
# whole build failed with "OSError: network disabled by tools/test_startup.py"
# BEFORE the launcher started ("controls=0" on CI, every run). The invariant
# this file guards is "no blocking NETWORK call on the UI thread", and
# 127.0.0.1/::1 is not the network - a real hostname or a remote address is
# still recorded and refused, which is what the check below asserts.
_main_connects = []
_main_thread = threading.main_thread()

_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_create_connection = socket.create_connection


def _is_loopback(dest) -> bool:
    """True for 127.0.0.0/8 and ::1 - a host string or an (ip, port) tuple."""
    host = dest[0] if isinstance(dest, (tuple, list)) and dest else dest
    host = str(host or "")
    return host in ("localhost", "::1") or host.startswith("127.")


def _refuse_connect(self, *a, **kw):
    dest = a[0] if a else ()
    if _is_loopback(dest):
        return _real_connect(self, *a, **kw)
    if threading.current_thread() is _main_thread:
        _main_connects.append(dest)
    raise OSError("network disabled by tools/test_startup.py")


def _refuse_connect_ex(self, *a, **kw):
    dest = a[0] if a else ()
    if _is_loopback(dest):
        return _real_connect_ex(self, *a, **kw)
    if threading.current_thread() is _main_thread:
        _main_connects.append(dest)
    return 11  # ECONNREFUSED-ish: the old "1" behaviour, without the loopback lie


def _refuse_create_connection(address, *a, **kw):
    # The path a real request takes (urllib3 -> socket.create_connection), so
    # this is where "the UI thread must never fetch" is really enforced.
    if _is_loopback(address):
        return _real_create_connection(address, *a, **kw)
    if threading.current_thread() is _main_thread:
        _main_connects.append(address)
    raise OSError("network disabled by tools/test_startup.py")


socket.socket.connect = _refuse_connect
socket.socket.connect_ex = _refuse_connect_ex
socket.create_connection = _refuse_create_connection

# disk-only meta(): with no feed cache and the network refused this must return
# instantly ({}) instead of blocking on the 20s-timeout fetch.
import cubeon.version_art as version_art  # noqa: E402
try:
    os.remove(version_art._FEED_CACHE)
except OSError:
    pass
_t0 = time.perf_counter()
_meta = version_art.meta("1.21.11")
_meta_ms = (time.perf_counter() - _t0) * 1000
check("version_art.meta() returns instantly with a cold cache + no network",
      _meta == {} and _meta_ms < 1000,
      f"returned {_meta!r} in {_meta_ms:.0f} ms")

import launcher_core as core  # noqa: E402
core.get_available_versions = versions.get_available_versions
core.get_latest_release = versions.get_latest_release

import app_driver  # noqa: E402
import main as app  # noqa: E402

page = app_driver.DriverPage()
_t0 = time.perf_counter()
try:
    app.run_sync(page)
    _build_err = ""
except Exception:
    import traceback
    _build_err = traceback.format_exc()
_build_ms = (time.perf_counter() - _t0) * 1000

check("the full UI builds offline without raising", not _build_err, _build_err)
check("the control tree was mounted", len(page.controls) > 0,
      f"controls={len(page.controls)}")
check("NO socket was opened from the main thread during startup",
      not _main_connects, f"{len(_main_connects)} connects: {_main_connects[:3]}")
# A blocked link used to make this ~7s (6 retried feed connects, each timing
# out). The budget is generous to stay reliable on a slow CI box while still
# failing if a blocking fetch-creep comes back.
check("the offline build finishes well under the old blocking-network cost",
      _build_ms < 15000, f"build took {_build_ms:.0f} ms")


# ------------------------------------ 5. the window fits the work area -------
print("\n5. a saved window too big for the desktop is fitted to the WORK AREA")

# 2026-10-16, user report: "when i size it too much it doesnt open on second
# launch, it needs to be a specific size to launch". A window manager clamps a
# window to _NET_WORKAREA (the screen MINUS its panels/docks): asking for
# 1900x1170 on this 1920x1200 KDE desktop yields a 1872-wide window, and the
# flet client then waits forever for an OpenGL frame at 1900x1170 - "Timed out
# waiting for OpenGL frame of size 1900x1170 (have 1872x1170)" - and dies
# before the UI paints. The saved size is only restored on the NEXT start,
# which is why the failure is a *second launch* failure.
_fit = getattr(app, "fit_geometry_to_area", None)
check("main exposes a pure geometry fitter (testable off an X server)",
      callable(_fit), "fit_geometry_to_area() missing from main")
check("_apply_real_geometry() actually fits the saved geometry to the area",
      "_fit_geometry_to_work_area()" in _main_src
      and "def _work_area()" in _main_src,
      "the clamp must be wired into the geometry path, not just defined")
if callable(_fit):
    _kde = (0, 0, 1872, 1200)  # KDE keeps 48px on this 1920x1200 screen
    check("a saved width bigger than the work area is shrunk",
          _fit(1900, 1170, 10, 10, _kde) == (1872, 1170, 0, 10),
          f"got {_fit(1900, 1170, 10, 10, _kde)}")
    check("a saved height bigger than the work area is shrunk",
          _fit(800, 5000, 0, 0, _kde) == (800, 1200, 0, 0),
          f"got {_fit(800, 5000, 0, 0, _kde)}")
    check("a geometry that already fits is returned untouched",
          _fit(1360, 808, 193, 154, _kde) == (1360, 808, 193, 154),
          f"got {_fit(1360, 808, 193, 154, _kde)}")
    check("an off-screen saved position is pulled back inside the area",
          _fit(400, 300, 9000, 9000, _kde) == (400, 300, 1472, 900),
          f"got {_fit(400, 300, 9000, 9000, _kde)}")
    check("a centered window (no saved position) only gets its size fitted",
          _fit(1900, 1170, None, None, _kde) == (1872, 1170, None, None),
          f"got {_fit(1900, 1170, None, None, _kde)}")
    check("with no work area to probe (no xprop) the geometry is left alone",
          _fit(1900, 1170, 10, 10, None) == (1900, 1170, 10, 10),
          f"got {_fit(1900, 1170, 10, 10, None)}")

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("Startup test: FAIL")
    sys.exit(1)
print("Startup test: PASS")
