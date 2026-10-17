"""
Offline test for cubeon/incident.py - the crash forensics record.

The 2026-10-18 report was "it got crashes on user and me too" plus a KDE
screenshot: "~/.flet/client/flet-desktop-light-0.86.5/flet/flet has
encountered a fatal error and was closed." That is the FLET CLIENT dying to a
signal, and main.py's recovery ladder already handles it - but NOTHING about
it reached cubeon.log, because every message was a print() to stdout and
setup_logging() was only reached from main() (which never runs on a pre-paint
crash). So the crash could not be diagnosed from a user's log at all.

These checks pin the two halves of the fix:
  * the pure record builders that turn the facts into a log line (driven
    directly), and
  * main.py's wiring: logging configured before the session loop, a record
    for EVERY session end, the tail fed from the client's own output, and the
    give-up logged in both recovery branches.

Run: python3 tools/test_incident.py
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubeon import incident as inc  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


# --------------------------------------------------------- describe_exit() ----
print("\n1. describe_exit names the exit status")

check("0 is a clean exit", inc.describe_exit(0) == "0 (clean exit)",
      inc.describe_exit(0))
check("a positive code is a nonzero exit",
      inc.describe_exit(1) == "1 (nonzero exit)", inc.describe_exit(1))
check("SIGSEGV (-11) is named - the documented Mesa client crash",
      "SIGSEGV" in inc.describe_exit(-11)
      and "-11" in inc.describe_exit(-11), inc.describe_exit(-11))
check("SIGABRT (-6) is named", "SIGABRT" in inc.describe_exit(-6),
      inc.describe_exit(-6))
check("SIGKILL (-9) is named", "SIGKILL" in inc.describe_exit(-9),
      inc.describe_exit(-9))
check("None is 'unobserved', never 'clean'",
      inc.describe_exit(None) == "unobserved", inc.describe_exit(None))
check("a code that is not a known signal still says signal death",
      "unknown signal 999" in inc.describe_exit(-999),
      inc.describe_exit(-999))
check("junk is reported, not raised",
      "unparseable" in inc.describe_exit("nonsense"),
      inc.describe_exit("nonsense"))
check("a numeric string is understood",
      inc.describe_exit("0") == "0 (clean exit)", inc.describe_exit("0"))


# --------------------------------------------------------- environment_facts --
print("\n2. environment_facts records what decides the crash class")

_facts = inc.environment_facts({"XDG_SESSION_TYPE": "wayland",
                                "XDG_CURRENT_DESKTOP": "KDE",
                                "LIBGL_ALWAYS_SOFTWARE": "1",
                                "CUBEON_GPU_RESTARTS": "2"})
check("session type is recorded", "session=wayland" in _facts, _facts)
check("desktop is recorded", "desktop=KDE" in _facts, _facts)
check("the software-GL retry is recorded as ON",
      "software_gl=on" in _facts, _facts)
check("the restart budget is recorded", "gpu_restarts=2" in _facts, _facts)
check("the flet versions are recorded", "flet=" in _facts and "client=" in _facts,
      _facts)

_off = inc.environment_facts({})
check("an empty environment renders without raising",
      "software_gl=off" in _off and "session=?" in _off, _off)
check("DESKTOP_SESSION is used when XDG_CURRENT_DESKTOP is absent",
      "desktop=plasma"
      in inc.environment_facts({"DESKTOP_SESSION": "plasma"}))
check("flet_version() never returns empty",
      bool(inc.flet_version().strip()) and "flet=" in inc.flet_version())


# ---------------------------------------------------------- client_binary ----
print("\n3. client_binary spots a PARTIAL client unpack (the one client-side\n"
      "   fault we could actually repair)")

import shutil      # noqa: E402
import tempfile    # noqa: E402

_tmp_home = tempfile.mkdtemp(prefix="cubeon-incident-")
try:
    _empty = inc.client_binary({"HOME": os.path.join(_tmp_home, "nope")})
    check("a missing ~/.flet/client is reported, not raised",
          "no ~/.flet/client" in _empty, _empty)

    _root = os.path.join(_tmp_home, ".flet", "client")
    _bundle = os.path.join(_root, "flet-desktop-light-9.9.9", "flet")
    os.makedirs(os.path.join(_bundle, "lib"))
    _bad = inc.client_binary({"HOME": _tmp_home})
    check("a client directory with NO binary is flagged",
          "NO flet binary" in _bad and "9.9.9" in _bad, _bad)

    with open(os.path.join(_bundle, "flet"), "wb") as _fh:
        _fh.write(b"x" * 1234)
    _no_engine = inc.client_binary({"HOME": _tmp_home})
    check("a binary with no engine library is flagged 'engine=NO'",
          "engine=NO" in _no_engine, _no_engine)

    with open(os.path.join(_bundle, "lib", "libflutter_linux_gtk.so"),
              "wb") as _fh:
        _fh.write(b"y" * 10)
    _good = inc.client_binary({"HOME": _tmp_home})
    check("a complete client reports its size and engine=yes",
          "engine=yes" in _good and "1234 B" in _good, _good)
    check("the client dir is named in the record (which version crashed)",
          "9.9.9" in _good, _good)
    check("a non-dict environment cannot raise",
          inc.client_binary(5) == "client_bin=?")
    check("the crash record carries the client facts",
          "client_bin=" in inc.crash_record("pre_paint_crash", -11, False, [],
                                            {"HOME": _tmp_home}))
finally:
    shutil.rmtree(_tmp_home, ignore_errors=True)


# ------------------------------------------------------------- crash_record --
print("\n4. crash_record is one greppable line, plus the client's last words")

_rec = inc.crash_record("pre_paint_crash", -11, False,
                        ["** (flet:1): WARNING **: boom", "line two"],
                        {"XDG_SESSION_TYPE": "x11"})
check("it says what ended", "flet session ended:" in _rec, _rec)
check("it names the kind", "kind=pre_paint_crash" in _rec, _rec)
check("it names the signal", "SIGSEGV" in _rec, _rec)
check("it records that the UI never painted", "ui_painted=False" in _rec, _rec)
check("the client's own output is included", "WARNING **: boom" in _rec, _rec)
check("tail lines are quoted so they can't be mistaken for our own log",
      "\n    | " in _rec, repr(_rec))
check("a mid-session crash records ui_painted=True",
      "ui_painted=True"
      in inc.crash_record("mid_session_crash", -6, True, [], {}))
check("a clean close carries NO tail (it would be pure noise)",
      "last flet client output"
      not in inc.crash_record("clean_close", 0, True, ["noise"], {}))
check("a clean close still records the facts",
      inc.crash_record("clean_close", 0, True, [], {}).startswith(
          "flet session ended: kind=clean_close client_exit=0 (clean exit)"))
check("no tail at all is fine",
      "last flet client output"
      not in inc.crash_record("pre_paint_crash", -11, False, [], {}))
# Built as a variable on purpose: the tail only carries decoded strings in
# production, but the record runs on a crash path and must survive junk. A
# `None` inside a list literal passed straight to a call is exactly what
# test_mega_smoke's Flet-children lint greps for (it is a real UI bug class
# there), so this deliberately does not look like one.
_junk_tail = ["", "\n", None]
check("blank/junk tail lines are skipped",
      "    | " not in inc.crash_record("pre_paint_crash", -11, False,
                                      _junk_tail, {}))
# A crash path must not be able to raise - ever.
for _junk in [(None, None, None, None, None), ("x", "y", "z", 5, 5)]:
    try:
        inc.crash_record(*_junk)
        _ok = True
    except Exception as _ex:   # pragma: no cover
        _ok = False
check("junk input never raises", _ok)


# --------------------------------------------------------- ClientOutputTail --
print("\n5. ClientOutputTail: bounded, and it survives a line storm")

_t = inc.ClientOutputTail(3)
for _line in ["a", "a", "a", "b", "", "c", "d"]:
    _t.add(_line)
check("consecutive repeats collapse to one", _t.lines() == ["b", "c", "d"],
      str(_t.lines()))
check("the cap holds (oldest dropped first)", len(_t.lines()) == 3)
_t.clear()
check("clear() empties it", _t.lines() == [] and len(_t) == 0,
      str(_t.lines()))
_t.add(None)
_t.add(1234)
check("non-strings are tolerated", _t.lines() == ["None", "1234"],
      str(_t.lines()))
check("a silly maxlen does not break it",
      inc.ClientOutputTail(0).lines() == []
      and inc.ClientOutputTail("x").lines() == [])
check("a long line storm keeps the LAST lines (newest last)",
      (lambda: (lambda t: [t.add(f"l{i}") for i in range(100)] and
                t.lines()[-1] == "l99" and t.lines()[0] == "l75")(
                    inc.ClientOutputTail(25)))())
check("TAIL_LINES is the documented cap", inc.ClientOutputTail()._maxlen
      == inc.TAIL_LINES == 25)


# ------------------------------------------------------- wayland_x11_fallback --
print("\n6. wayland_x11_fallback is narrow on purpose")

check("a Wayland session with XWayland available switches to x11",
      inc.wayland_x11_fallback(
          {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}) ==
      {"GDK_BACKEND": "x11"})
check("an X11 session changes nothing",
      inc.wayland_x11_fallback(
          {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}) == {})
check("no X server -> no change (forcing x11 would break the start)",
      inc.wayland_x11_fallback(
          {"XDG_SESSION_TYPE": "wayland"}) == {})
check("a user-chosen GDK_BACKEND is never overridden",
      inc.wayland_x11_fallback(
          {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0",
           "GDK_BACKEND": "wayland"}) == {})
check("WAYLAND_SESSION type matching is case-insensitive",
      inc.wayland_x11_fallback(
          {"XDG_SESSION_TYPE": "Wayland", "DISPLAY": ":0"}) ==
      {"GDK_BACKEND": "x11"})
check("a non-dict environment cannot raise",
      inc.wayland_x11_fallback(5) == {})


# ------------------------------------------------- the retry ENVIRONMENT ladder --
print("\n7. the retry ladder picks a DIFFERENT rasterizer on the last attempt")

check("the first retry uses llvmpipe (the fast software driver)",
      inc.driver_for_attempt(1) == "llvmpipe")
check("the second retry uses softpipe - the reference C rasterizer with no "
      "LLVM JIT, i.e. a genuinely different code path",
      inc.driver_for_attempt(2) == "softpipe")
check("more failures stay on softpipe", inc.driver_for_attempt(9) == "softpipe")
check("a junk attempt count falls back to llvmpipe, not an exception",
      inc.driver_for_attempt(None) == "llvmpipe"
      and inc.driver_for_attempt("x") == "llvmpipe")
check("a retry forces software GL and names the driver",
      inc.retry_environment(1)["LIBGL_ALWAYS_SOFTWARE"] == "1"
      and inc.retry_environment(1)["GALLIUM_DRIVER"] == "llvmpipe"
      and inc.retry_environment(2)["GALLIUM_DRIVER"] == "softpipe")
check("a retry env never forces a display backend on X11",
      "GDK_BACKEND" not in inc.retry_environment(
          1, {"XDG_SESSION_TYPE": "x11", "DISPLAY": ":0"}))
check("...but carries the Wayland->X11 roll on a Wayland session",
      inc.retry_environment(
          2, {"XDG_SESSION_TYPE": "wayland", "DISPLAY": ":0"}
      )["GDK_BACKEND"] == "x11")

# The one Mesa fact that decides whether this crash can be worked around at all.
_gallium = inc.gallium_driver()
check("gallium_driver() reports a Mesa library or '?', never raises",
      _gallium == "gallium=?" or _gallium.startswith("gallium="))
check("the crash record carries the Mesa/gallium library",
      "gallium=" in inc.crash_record("pre_paint_crash", -11, False, [], {}))


# ------------------------------------------------------------- main.py wiring --
print("\n8. main.py records the crash instead of only printing it")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(_ROOT, "main.py"), encoding="utf-8") as _fh:
    _main = _fh.read()

_dunder = _main.index('if __name__ == "__main__":')
_loop_call = _main.index("\n    _session_loop()")

check("the crash path configures logging (setup_logging before the loop)",
      _main.index("_setup_logging()") > _dunder
      and _main.index("_setup_logging()") < _loop_call,
      "a pre-paint crash used to leave cubeon.log EMPTY: main() never ran, "
      "so setup_logging() was never reached")
check("incident is imported in the __main__ block",
      "from cubeon import incident as _incident" in _main[_dunder:])
check("EVERY session end is recorded, whatever the kind",
      "_incident.record_session_end(" in _main
      and "_session_end_kind," in _main)
check("the record gets the client's exit status",
      '_last_client_exit["code"], ui_painted' in _main)
check("the record gets the client's own output tail",
      "_client_tail.lines()" in _main)
check("the tail is fed from the client's output filter",
      "_client_tail.add(line)" in _main)
check("the tail is cleared for each new client",
      "_client_tail.clear()" in _main)
check("the tail is defined before the session loop",
      _main.index("_client_tail = _incident.ClientOutputTail()")
      < _main.index("def _session_loop()"))
check("both recovery branches log the give-up",
      _main.count("_incident.record_giving_up(") == 2,
      f"{_main.count('_incident.record_giving_up(')} call sites")
check("the mid-session give-up names its kind",
      'record_giving_up(\n                        _MAX_MIDSESSION_RESTARTS, '
      '"mid_session_crash")' in _main)
check("the pre-paint give-up names its kind",
      'record_giving_up(_retries, "pre_paint_crash")' in _main)
check("the XWayland fallback is applied ONLY on a retry, after software GL",
      "_incident.retry_environment(" in _main
      and _main.index("if os.path.exists(_gl_fallback_marker):")
      < _main.index("_incident.retry_environment("))
check("the failed-attempt count (in-process retries + CUBEON_GPU_RESTARTS) "
      "decides the driver",
      "_incident.retry_environment(\n                            _failed_attempts)"
      in _main and 'os.environ.get(\n                                "CUBEON_GPU_RESTARTS"' in _main)
check("the retry env actually reaches the client",
      'os.environ[_fk] = _fv' in _main)
check("no retry driver is hardcoded any more",
      'os.environ["GALLIUM_DRIVER"] = "llvmpipe"' not in _main)
check("no crash message was left as print-only",
      'print("cubeon: client keeps dying before the window "' in _main
      and "_incident.record_giving_up(_retries" in _main,
      "the print stays for a terminal, but the log now has the record")

print(f"\n{_passed} passed, {_failed} failed")
if _failed:
    print("Incident test: FAIL")
    sys.exit(1)
print("Incident test: PASS")
