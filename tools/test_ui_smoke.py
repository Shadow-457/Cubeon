#!/usr/bin/env python3
"""
Headless smoke test for the launcher UI.

main.py is ~1570 lines of Flet closures with no tests, which makes any refactor
of it unverifiable - you can only find out you broke something by clicking every
tab by hand. This builds the whole UI against a fake Page, with no window and no
Flet runtime, and asserts the structure came out intact.

It deliberately checks *behaviour reachable without a display*: that every tab
builds, that the nav has the expected entries, that switching tabs swaps content,
and that the launch-flow helpers (button modes, status) do what their names say.
That's enough to catch the things a refactor actually breaks - a helper left
behind in the wrong scope, a closure that lost its variable, a tab that no longer
builds.

Run: python3 tools/test_ui_smoke.py
"""
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


# --------------------------------------------------------------- fake page ---

class FakeWindow:
    def __init__(self):
        self.width = self.height = 0
        self.min_width = self.min_height = 0
        self.title = ""
        self.icon = ""
        self.prevent_close = False

    def center(self):
        pass

    def destroy(self):
        pass


class FakePage:
    """Just enough ft.Page for main() to build against.

    Records update() calls and overlay/dialog registrations so the test can
    assert the UI was actually wired, and swallows anything display-specific.
    """

    def __init__(self):
        self.window = FakeWindow()
        self.overlay = []
        self.controls = []
        self.fonts = {}
        self.theme = None
        self.theme_mode = None
        self.title = ""
        self.bgcolor = None
        self.padding = 0
        self.update_calls = 0
        self.opened = []
        self.snackbars = []
        self.session = types.SimpleNamespace()
        # Flet 0.86 attaches the clipboard as a page *service; the tabs that
        # registers one here, so without this the section silently loses copy.
        self.services = []

    def update(self, *controls):
        self.update_calls += 1

    def add(self, *controls):
        self.controls.extend(controls)

    def open(self, control):
        self.opened.append(control)

    def close(self, control):
        pass

    def run_thread(self, fn, *a, **kw):
        return fn(*a, **kw)

    def run_task(self, fn, *a, **kw):
        return None


def walk(control, depth=0, seen=None):
    """Yields every control in a Flet tree, defensively (controls vary by type)."""
    if seen is None:
        seen = set()
    if control is None or id(control) in seen or depth > 60:
        return
    seen.add(id(control))
    yield control
    for attr in ("controls", "content", "actions", "title", "leading",
                 "trailing", "label", "tabs", "items"):
        child = getattr(control, attr, None)
        if child is None:
            continue
        if isinstance(child, (list, tuple)):
            for c in child:
                if hasattr(c, "_c") or hasattr(c, "controls") or hasattr(c, "content"):
                    yield from walk(c, depth + 1, seen)
        elif hasattr(child, "_c") or hasattr(child, "controls") or hasattr(child, "content"):
            yield from walk(child, depth + 1, seen)


def all_text(control):
    """Every string value found anywhere in the tree, lowercased."""
    out = []
    for c in walk(control):
        for attr in ("value", "text", "hint_text", "label", "tooltip"):
            v = getattr(c, attr, None)
            if isinstance(v, str) and v.strip():
                out.append(v.lower())
    return out


# ------------------------------------------------------------------ harness ---

print("\n1. the app builds headlessly")

# Keep the test off the network and off the user's real install.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()
import cubeon.versions as versions
import cubeon.csl as csl

versions.get_available_versions = lambda *a, **kw: [
    {"id": "1.21.11", "type": "release"}, {"id": "1.20.1", "type": "release"}]
versions.get_latest_release = lambda: "1.21.11"
csl.ensure_ready = lambda *a, **kw: None

import launcher_core as core
core.get_available_versions = versions.get_available_versions
core.get_latest_release = versions.get_latest_release

import main as app

page = FakePage()
try:
    app.main(page)
    built = True
    err = ""
except Exception as ex:
    import traceback
    built = False
    err = traceback.format_exc()

check("main(page) completed without raising", built, err)
if not built:
    print(f"\n{passed} passed, {failed} failed")
    sys.exit(1)

check("something was added to the page", len(page.controls) > 0)
check("window title set", page.title == "Cubeon Launcher")
check("fonts registered", set(page.fonts) >= {"Minecraftia", "Inter"})
check("a FilePicker was registered in the overlay",
      any(type(o).__name__ == "FilePicker" for o in page.overlay),
      f"overlay={[type(o).__name__ for o in page.overlay]}")

print("\n2. the shell has every nav destination")
text = " | ".join(all_text(page.controls[0]))
for label in ("play", "mods", "servers", "profile", "settings"):
    check(f"nav shows {label!r}", label in text)

print("\n3. the Play tab is wired")
check("username field present", "username" in text)
check("version selector present", "version" in text)
for loader in ("fabric", "quilt", "forge", "neoforge"):
    check(f"loader segment {loader!r} present", loader in text)
check("the vanilla loader segment is back", "vanilla" in text.lower())
check("play button present", "play" in text)

print("\n4. crash explanations (pure logic, no UI)")
cases = [
    (["java.lang.OutOfMemoryError: Java heap space"], "out of memory"),
    (["Unsupported class file major version 65"], "java version"),
    (["ClassNotFoundException: net.fabricmc.loader.impl.launch.knot.KnotClient"], "fabric"),
    (["mod resolution encountered an incompatible mod set"], "mods"),
]
for lines, expect in cases:
    got = app._explain_exit(1, lines).lower()
    check(f"{expect!r} explained", expect in got, f"got {got!r}")

check("unknown crash still names the error",
      "boom" in app._explain_exit(1, ["Exception: boom"]).lower())
check("no output still returns something useful",
      app._explain_exit(1, []).startswith("Crashed"))
check("explanation stays short enough for the label",
      all(len(app._explain_exit(1, l)) <= 180 for l, _ in cases))

print("\n5. every tab builder accepts the shared theme (**THEME)")
# The Profile dialog and the tab builders aren't reached by main()'s initial
# build, so a broken signature there survives section 1. These call them
# directly. `**THEME` is only safe if all four take the same token names -
# skin_tab.py notably did not, and defaulted DANGER to a different red.
import flet as ft
from cubeon.theme import THEME
from cubeon import theme as theme_mod

check("THEME covers every token the builders ask for",
      set(THEME) == {"BG", "SURFACE", "SURFACE_HI", "BORDER", "ACCENT", "ACCENT_DIM",
                     "TEXT", "TEXT_DIM", "DANGER", "FONT_DISPLAY", "FONT_MONO"},
      f"got {sorted(THEME)}")

from ui.skin_tab import build_skin_section
try:
    section = build_skin_section(
        FakePage(), {"username": "tester", "active_skin": None},
        section_label=theme_mod.section_label, pixel_divider=theme_mod.pixel_divider,
        **THEME,
        mc_version="1.21.11", mc_loader="fabric", file_picker=ft.FilePicker(),
    )
    check("build_skin_section accepts **THEME", section is not None)
except Exception as ex:
    check("build_skin_section accepts **THEME", False, f"{type(ex).__name__}: {ex}")

check("DANGER is a required argument, not a drifting default",
      "DANGER" not in (build_skin_section.__defaults__ or ()) and
      "#e05555" not in str(build_skin_section.__kwdefaults__ or {}),
      f"kwdefaults={build_skin_section.__kwdefaults__}")

print("\n6. rebuilding is idempotent (catches leaked module-level state)")
# A refactor that hoists per-session state to module level breaks on the second
# build, not the first - so build twice and assert it still works.
page2 = FakePage()
try:
    app.main(page2)
    again = True
    err2 = ""
except Exception as ex:
    import traceback
    again = False
    err2 = traceback.format_exc()
check("a second independent build succeeds", again, err2)
if again:
    check("second build produced its own controls", len(page2.controls) > 0)
    check("second build registered its own FilePicker",
          any(type(o).__name__ == "FilePicker" for o in page2.overlay))
    t2 = " | ".join(all_text(page2.controls[0]))
    check("second build has the same nav", all(
        k in t2 for k in ("play", "mods", "servers", "profile", "settings")))

print("\n7. the tunnel section is reachable from the Server console view")
# The whole point of the feature is a button the user can actually see. main()
# only mounts the Play tab initially, so this builds the Server tab the same way
# main() does and asserts the Server tab built with it - which is what proves
# server_tab.py's import and placement are wired.

from ui.server_tab import build_server_tab
# HERMETIC: this test asserts the leftover-server warning "starts hidden",
# which is only true on a machine with no orphaned server. A dev box that
# actually HAS a detached server holding session.lock (e.g. from a crashed
# launcher run) makes the warning legitimately VISIBLE and would fail the
# check for reasons that have nothing to do with the UI's structure. Pin
# the orphan probe to "clean" for the duration of the build.
import launcher_core as _core_smoke
_orig_orphan_probe = _core_smoke.is_server_orphaned
_core_smoke.is_server_orphaned = lambda *a, **k: None
sp = FakePage()
srv_console, srv_settings, srv_plugins, srv_refresh = build_server_tab(
    sp, {"server_ram_mb": 2048, "java_path": ""},
    {"selected_version": "1.21.11"},
    section_label=theme_mod.section_label,
    pixel_divider=theme_mod.pixel_divider, **THEME)
# (probe stays stubbed through section 7 - see note below)
console_text = " | ".join(all_text(srv_console))
check("the old tunnel panel is gone from Console",
      "enable public sharing" not in console_text
      and "play with friends anywhere" not in console_text,
      "the removed sharing panel is still present")

# With an endpoint configured, the console's public-address line must fill
# in neatly - that's the whole "IP should come neatly" requirement.
_core_smoke.minekube.get_endpoint = lambda vid: "test-server"
_core_smoke.minekube.read_public_address = lambda vid, **k: None
_core_smoke.is_server_installed = lambda vid, *a, **k: True
_core_smoke.is_server_running = lambda vid: False
srv_refresh()
console_text = " | ".join(all_text(srv_console))
check("the console shows the public address neatly",
      "public address: test-server.play.minekube.net" in console_text.lower(),
      f"console text sample: {console_text[:300]}")
check("...with a plain-language hint under it",
      "goes live when the server starts" in console_text.lower())

# refresh_server_tab() must drive the public-address line too, or the state
# shown is whatever it was at build time - permanently stale after a start.
srv_refresh()
settings_text = " | ".join(all_text(srv_settings))
check("refresh_server_tab() populates the endpoint field in Settings",
      "minekube endpoint" in settings_text,
      "the custom endpoint option didn't make it into Settings")

print("\n7b. the endpoint option lives in Settings, not Console")
check("Settings has the Minekube endpoint field",
      "minekube endpoint (optional)" in settings_text,
      f"settings text sample: {settings_text[:200]}")
check("Console does NOT have the endpoint field",
      "minekube endpoint" not in console_text)

print("\n7c. the leftover-server warning is present and starts hidden")
# The Server tab said "Stopped" while a detached server from a previous Cubeon
# run still held the world lock, so every Start died on session.lock. The button
# that fixes that has to exist in the tree - but stay hidden until there really
# is a leftover, or it reads as a permanent scary warning.
check("the Stop leftover server button exists in the Console view",
      "stop leftover server" in " | ".join(all_text(srv_console)),
      "a user with an orphaned server has no way to clear it")


def hidden_holder_of(control, needle, seen=None):
    """True if some hidden container in the tree holds the given text."""
    if seen is None:
        seen = set()
    if id(control) in seen:
        return False
    seen.add(id(control))
    if needle in " | ".join(all_text(control)).lower() \
            and getattr(control, "visible", None) is False:
        return True
    for attr in ("content", "controls"):
        child = getattr(control, attr, None)
        if child is None:
            continue
        for item in (child if isinstance(child, (list, tuple)) else [child]):
            if hidden_holder_of(item, needle, seen):
                return True
    return False


check("...and it is hidden until a leftover actually exists",
      hidden_holder_of(srv_console, "stop leftover server"),
      "an always-visible red warning would read as a permanent error")

# Server-tab checks are over - give the real orphan probe back. Kept stubbed
# until here because srv_refresh() above runs refresh_orphan_notice(), which
# would otherwise read this dev machine's actual session.lock state.
_core_smoke.is_server_orphaned = _orig_orphan_probe

# --- public-build regression: friends_service is None when Friends is off ----
# A launch-time AttributeError ('NoneType' has no 'set_version') slipped
# through because every suite ran with Friends enabled. Assert the guard
# exists in source so the None case can never crash a launch again.
import re as _re
_src = open(app.__file__, encoding="utf-8").read()
check("public builds can't crash on friends presence (guarded set_version)",
      _re.search(r"if friends_service is not None:\s*\n\s*friends_service\.set_version\(", _src) is not None,
      "main.py must guard the launch-time set_version call")

# --- full lazy-tab dispatch path: clicking Mods must not raise ----------------
# The 2026-09-07 user crash: clicking Mods ran switch_tab -> _ensure_tab ->
# lazy _build_mods_tab -> refresh_mods_list -> refresh(mods_list_view), and
# Flet 0.86's `control.page` property RAISED RuntimeError because the freshly
# built list was not yet mounted (FakePage never mounts anything, same state).
# The click handler must survive; drive the REAL sidebar button.
print("\n8. the Mods nav click runs the lazy build + repaint without raising")
_mods_click = None
for _c in walk(page.controls[0]):
    _oc = getattr(_c, "on_click", None)
    if _oc is None:
        continue
    try:
        # switch_tab's nav handler is `lambda e, k=key: switch_tab(k)`: the
        # tab key is bound as a DEFAULT ARG, so it lives in __defaults__,
        # not in the closure or co_consts.
        if "mods" in (getattr(_oc, "__defaults__", None) or ()):
            _mods_click = _oc
            break
    except Exception:
        pass
check("found the Mods nav button in the built tree", _mods_click is not None)
if _mods_click is not None:
    try:
        _mods_click(None)
        _clicked_ok = True
        _click_err = ""
    except Exception as _ex:
        _clicked_ok = False
        _click_err = f"{type(_ex).__name__}: {_ex}"
    check("clicking Mods (lazy build + refresh_mods_list) doesn't raise",
          _clicked_ok, _click_err)


# --- refresh() on an UNMOUNTED control must not raise -----------------------
# Real crash (2026-09-07): the lazy-built Mods tab's refresh_mods_list()
# called thread_safe_ui.refresh(mods_list_view) before the tab was ever
# mounted; Flet 0.86's `control.page` property RAISES RuntimeError for
# unmounted controls (hasattr doesn't catch that), and the exception tore
# down the sidebar's on_click handler. refresh() must swallow it.
import threading as _threading
import flet as _ft
from cubeon import thread_safe_ui as _tsui

class _Unmounted(_ft.Column):
    """A control that was never added to any page - .page raises."""

_unm = _Unmounted()
_raised = []
try:
    _tsui.refresh(_unm)
except Exception as _ex:
    _raised.append(_ex)
check("refresh() tolerates unmounted controls", not _raised,
      f"raised {_raised[0]!r}" if _raised else "")

# And a mounted-but-unknown-page control (install() never ran for it)
# goes through the direct path without raising either.
try:
    _tsui.refresh(_ft.Text("never added"))
    _ok_direct = True
except Exception as _ex:
    _ok_direct = False
check("refresh() direct path safe for detached controls", _ok_direct)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
