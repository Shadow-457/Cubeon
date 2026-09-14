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
    Mirrors Flet 0.86's dialog API (show_dialog/pop_dialog + a _dialogs
    stack) so the app's dialog plumbing is exercised the same way it runs
    for real - the old fake exposed open()/close(), which 0.86 removed, and
    so hid the "dialogs never close" bug entirely.
    """

    class _Dialogs:
        def __init__(self):
            self.controls = []

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
        self._dialogs = FakePage._Dialogs()
        self.session = types.SimpleNamespace()
        # Flet 0.86 attaches the clipboard as a page *service; the tabs that
        # registers one here, so without this the section silently loses copy.
        self.services = []

    def update(self, *controls):
        self.update_calls += 1

    def add(self, *controls):
        self.controls.extend(controls)

    def show_dialog(self, control):
        control.open = True
        self._dialogs.controls.append(control)
        self.opened.append(control)
        if type(control).__name__ == "SnackBar":
            self.snackbars.append(control)

    def pop_dialog(self):
        while self._dialogs.controls:
            dlg = self._dialogs.controls.pop()
            if getattr(dlg, "open", None):
                dlg.open = False
                return dlg
        return None

    def open(self, control):
        # Pre-0.28 API - must NOT be preferred by the app on 0.86.
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
check("window title set", page.title == "Cubeon")
check("fonts registered", set(page.fonts) >= {"Minecraftia", "Inter"})
check("a FilePicker was registered in the overlay",
      any(type(o).__name__ == "FilePicker" for o in page.overlay),
      f"overlay={[type(o).__name__ for o in page.overlay]}")

def all_tooltips(ctrl):
    """Tooltips across the tree - the top nav is icon-only by design, so the
    destinations are named in tooltips, not Text controls."""
    out = []
    tip = getattr(ctrl, "tooltip", None)
    if tip:
        out.append(str(tip))
    for c in getattr(ctrl, "controls", None) or []:
        out.extend(all_tooltips(c))
    content = getattr(ctrl, "content", None)
    if content is not None:
        out.extend(all_tooltips(content))
    for a in getattr(ctrl, "actions", None) or []:
        out.extend(all_tooltips(a))
    return out

print("\n2. the shell has every nav destination")
text = " | ".join(all_text(page.controls[0])).lower()
nav_labels = ("play", "mods", "modpacks", "cosmetics", "servers", "account", "settings")
for label in nav_labels:
    check(f"nav shows {label!r}", label in text)
check("update-version button present", "update game version" in text)
# The Legacy toggle and the snapshots checkbox live in Settings now (this
# fake page only mounts the Play tab), so their ABSENCE here is the check.
check("legacy toggle not on the play tab", "show snapshots" not in text)

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

print("\n4b. session end classification (close vs GPU crash)")
# Regression for the "closing the window reopens it" bug: flet 0.86 reaps its
# client inside ft.run, so a live child can never be observed afterwards. The
# old live-child test called every normal close a crash and relaunched. The
# exit status is the only reliable signal: 0 = user close, negative = signal.
_end_cases = [
    ((False, None), "pre_paint_crash"),
    ((False, -11), "pre_paint_crash"),
    ((True, 0), "clean_close"),
    ((True, None), "clean_close"),
    ((True, 1), "clean_close"),
    ((True, -11), "mid_session_crash"),
    ((True, -6), "mid_session_crash"),
]
for args, expect in _end_cases:
    got = app._classify_session_end(*args)
    check(f"session end {args} -> {expect}", got == expect, f"got {got!r}")
check("a normal close never relaunches (exit 0 is clean, not a crash)",
      app._classify_session_end(True, 0) == "clean_close",
      "closing the window must park/exit, never re-exec with software GL")

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

# Hats were removed with the Mojang browse system (2026-09-13 user request:
# "remove the hat BROWSE shit too"). What must remain true headless: the
# section builds, the Cosmetics tab is GONE, and no hat tiles leak through.
try:
    import cubeon.milestones as _mile
    _mile.load_state()
    _sec_txt = " | ".join(all_text(section)).lower()
    check("hat browse is gone (no cosmetics tab, no hat tiles)",
          "cosmetics" not in _sec_txt
          and "veteran" not in _sec_txt and "party" not in _sec_txt,
          _sec_txt[:200])
except Exception as ex:
    check("hat browse is gone (no cosmetics tab, no hat tiles)", False,
          f"{type(ex).__name__}: {ex}")

check("DANGER is a required argument, not a drifting default",
      "DANGER" not in (build_skin_section.__defaults__ or ()) and
      "#e05555" not in str(build_skin_section.__kwdefaults__ or {}),
      f"kwdefaults={build_skin_section.__kwdefaults__}")

print("\n5b. an uploaded (non-animated) cape builds a real row - no gray box")
# Regression for the "white thing on uploaded capes" report: the cape row's
# name column was built as `ft.Text(...) if c.get("animated") else None`
# INSIDE ft.Column(controls=[...]). A None child serializes as a null entry;
# the Flet client then fails to build that row and Flutter paints its
# release-mode error widget - the big gray/white box users saw exactly where
# each uploaded cape's row should have been. Python never raised, so nothing
# reached the log. Two guards here: (a) the built Cape pane's tree contains
# zero None entries in any controls list, (b) the uploaded cape's row text
# actually exists. A real (non-animated) cape is planted in the sandboxed
# CAPES_DIR so refresh_capes_list() reads genuine data.
import json as _json
from PIL import Image as _PILImage

os.makedirs(core.CAPES_DIR, exist_ok=True)
_PILImage.new("RGBA", (64, 32), (10, 200, 90, 255)).save(
    os.path.join(core.CAPES_DIR, "regress_cape.png"), "PNG")
with open(os.path.join(core.CAPES_DIR, "capes.json"), "w", encoding="utf-8") as _f:
    _json.dump({"capes": [{"filename": "regress_cape.png",
                           "name": "Regress Cape"}]}, _f)

try:
    _cape_cfg = {"username": "tester", "active_skin": None,
                 "active_cape": "regress_cape.png"}
    _cape_section = build_skin_section(
        FakePage(), _cape_cfg,
        section_label=theme_mod.section_label, pixel_divider=theme_mod.pixel_divider,
        **THEME,
        mc_version="1.21.11", mc_loader="fabric", file_picker=ft.FilePicker(),

    )
    # The Cape pane only hangs off the tab bar's click until switched to;
    # click it (same trick as the Cosmetics check above) so it's walkable.
    for _c in walk(_cape_section):
        if getattr(_c, "on_click", None) is not None and \
                " ".join(all_text(_c)).strip() == "cape":
            _c.on_click(None)
            break
    _nones = []
    for _c in walk(_cape_section):
        _lst = getattr(_c, "controls", None)
        if isinstance(_lst, list):
            _nones.extend(f"{type(_c).__name__}[{_i}]"
                          for _i, _x in enumerate(_lst) if _x is None)
    check("no None child in any controls list", not _nones,
          f"null entries at: {_nones[:5]}")
    # Installed capes render as a card grid, not pages: both the built-in
    # Cubeon cape and the uploaded one are in the tree at once, and there is
    # no "n / m" pager label anywhere.
    _cape_txt = " | ".join(all_text(_cape_section))
    check("uploaded cape row renders its name",
          "regress cape" in _cape_txt, _cape_txt[:200])
    check("installed lists no longer paginate (no page indicator)",
          not any("/" in (_lbl.value or "")
                  for _c in walk(_cape_section) if isinstance(_c, ft.Row)
                  for _lbl in _c.controls if isinstance(_lbl, ft.Text)),
          "found a leftover 'n / m' pager label")
except Exception as ex:
    import traceback
    check("uploaded cape row builds", False, traceback.format_exc())

print("\n5c. no browse/gallery area (removed; the section is upload + installed only)")
# The Browse panes (searchable local-library galleries with GET tiles) were
# removed 2026-09-14 - the section is now just upload + installed management.
# Pin that: no search field, no gallery copy, and the old fetch-player flow
# (removed earlier) still never comes back.
try:
    _skin_section = build_skin_section(
        FakePage(), {"username": "tester", "active_skin": None},
        section_label=theme_mod.section_label, pixel_divider=theme_mod.pixel_divider,
        **THEME,
        mc_version="1.21.11", mc_loader="fabric", file_picker=ft.FilePicker(),

    )
    _fields = [c for c in walk(_skin_section) if isinstance(c, ft.TextField)]
    _hints = " | ".join((getattr(f, "hint_text", "") or "").lower() for f in _fields)
    check("no search box remains (no browse pane to filter)",
          not _fields and "search skins" not in _hints and "search capes" not in _hints,
          _hints)
    _txt_all = " | ".join(all_text(_skin_section)).lower()
    check("no gallery/browse copy remains",
          "library folder" not in _txt_all and "results for" not in _txt_all
          and "browse" not in _txt_all,
          _txt_all[:200])
    check("no fetch-player copy or Get button remains",
          "get player" not in _txt_all and "fetch" not in _txt_all
          and "on mojang" not in _txt_all,
          _txt_all[:200])
except Exception as ex:
    import traceback
    check("no browse/gallery area", False, traceback.format_exc())

print("\n5d. no Browse|Installed tabs; the installed list is always shown")
# The Browse | Installed split only existed to host the gallery views; with
# browse removed the tab rows are gone too and the installed grid IS the pane.
try:
    _skin_section = build_skin_section(
        FakePage(), {"username": "tester", "active_skin": None},
        section_label=theme_mod.section_label, pixel_divider=theme_mod.pixel_divider,
        **THEME,
        mc_version="1.21.11", mc_loader="fabric", file_picker=ft.FilePicker(),

    )
    _tabs = [" ".join(all_text(c)).strip().lower()
             for c in walk(_skin_section)
             if getattr(c, "on_click", None) is not None
             and " ".join(all_text(c)).strip().lower() in ("browse", "installed")]
    check("no Browse/Installed view tabs", not _tabs, str(_tabs))
    _txt = " | ".join(all_text(_skin_section)).lower()
    check("installed empty-state is visible without any tab click",
          "no uploaded skins yet" in _txt and "upload skin" in _txt,
          _txt[:200])
except Exception as ex:
    import traceback
    check("installed list always shown", False, traceback.format_exc())

print("\n5e. library files are never surfaced (browse fully removed)")
# Files dropped into the local skin_library folder once appeared as GET tiles
# in the Browse grid. The browse area is gone - pin that a seeded library file
# shows up nowhere in the section (no tile, no name, no gallery row).
_seed = []
try:
    import cubeon.gallery as _gal
    _gal.ensure_gallery()
    for _n in ("jeb_test", "zed_test"):
        _p = os.path.join(_gal.SKIN_LIBRARY_DIR, _n + ".png")
        _PILImage.new("RGBA", (64, 64), (120, 120, 220, 255)).save(_p, "PNG")
        _seed.append(_p)
    _skin_section = build_skin_section(
        FakePage(), {"username": "tester", "active_skin": None},
        section_label=theme_mod.section_label, pixel_divider=theme_mod.pixel_divider,
        **THEME,
        mc_version="1.21.11", mc_loader="fabric", file_picker=ft.FilePicker(),
    )
    _txt_all = " | ".join(all_text(_skin_section)).lower()
    check("library file names never appear", "jeb_test" not in _txt_all
          and "zed_test" not in _txt_all, _txt_all[:200])
    _tiles = [c for c in walk(_skin_section)
              if isinstance(getattr(c, "data", None), dict)
              and "skin_gid" in c.data]
    check("no gallery tiles are built", not _tiles, f"tiles={len(_tiles)}")
    check("no 'Look up ... on Mojang' button remains",
          "look up" not in _txt_all and "on mojang" not in _txt_all,
          _txt_all[:200])
except Exception as ex:
    import traceback
    check("library files never surfaced", False, traceback.format_exc())
finally:
    for _p in _seed:
        try:
            os.remove(_p)
        except OSError:
            pass

print("\n5f. Installed skin cards show a real preview in a wrapping grid")
# The Installed pane used to render a generic icon chip per row (and later a
# one-row-per-page pager). It now shows a wrapping card grid where every card
# carries a rendered preview and the active item is highlighted.
_inst_skin = None
try:
    _src_png = os.path.join(core.SKINS_DIR, "_regress_src.png")
    _PILImage.new("RGBA", (64, 64), (200, 60, 60, 255)).save(_src_png, "PNG")
    _inst_skin = core.add_custom_skin(_src_png, "Regress Inst Skin")
    os.remove(_src_png)
    _sec = build_skin_section(
        FakePage(), {"username": "tester", "active_skin": None},
        section_label=theme_mod.section_label, pixel_divider=theme_mod.pixel_divider,
        **THEME, mc_version="1.21.11", mc_loader="fabric",
        file_picker=ft.FilePicker())

    for _c in walk(_sec):
        if getattr(_c, "on_click", None) is not None and \
                " ".join(all_text(_c)).strip().lower().startswith("installed"):
            _c.on_click(None)
            break
    _grid = None
    for _c in walk(_sec):
        if isinstance(_c, ft.Row) and getattr(_c, "wrap", False) and \
                "regress inst skin" in " ".join(all_text(_c)).lower():
            _grid = _c
            break
    _has_preview = _grid is not None and any(
        isinstance(x, ft.Image) for x in walk(_grid))
    _card = next((x for x in (_grid.controls if _grid else [])
                  if isinstance(x, ft.Container)), None)
    check("installed skin card shows a real preview image", _has_preview)
    check("installed skins flow as a wrapping card grid",
          _grid is not None and _card is not None and _card.width,
          f"grid={type(_grid).__name__ if _grid else None} "
          f"children={[type(x).__name__ for x in (_grid.controls if _grid else [])]}")
except Exception as ex:
    import traceback
    check("installed skin card shows a real preview image", False, traceback.format_exc())
finally:
    if _inst_skin:
        try:
            core.delete_custom_skin(_inst_skin["filename"])
        except Exception:
            pass

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
    t2 = " | ".join(all_text(page2.controls[0])).lower()
    check("second build has the same nav", all(
        k in t2 for k in ("play", "mods", "modpacks", "cosmetics",
                          "servers", "account", "settings")),
        f"text={t2[:400]!r}")

print("\n6b. the Update game version button really updates")

# Drive the actual button handler. It is a nested function, so we reach it
# through the control tree: the update control is the one with on_click whose
# subtree contains "update game version". Everything network- or
# thread-spawning is stubbed so the test stays hermetic. Status messages are
# not mounted (there is no visible status chip by design), so we capture them
# by spying on thread_safe_ui.refresh, which set_status() calls.
import cubeon.thread_safe_ui as _tsui_smoke
import threading as _threading
_saved_install_version = core.install_version
_saved_is_loader_supported = core.is_loader_supported
_saved_mod_doctor = core.mod_doctor
_saved_is_server_running = core.is_server_running
_saved_get_installed = core.get_installed_versions
_saved_tsui_refresh = _tsui_smoke.refresh
# Block the prefetch install so it can't flip the version to "installed"
# mid-assertion (the real install takes long enough that it never does).
_release_install = _threading.Event()
core.install_version = lambda *a, **k: _release_install.wait(3)
core.is_loader_supported = lambda *a, **k: False
core.mod_doctor = lambda *a, **k: {"checked": 0, "problems": [],
                                  "fixed": [], "unfixed": []}
core.is_server_running = lambda *a, **k: False
_statuses = []


def _cap_refresh(ctrl):
    v = getattr(ctrl, "value", None)
    if isinstance(v, str):
        _statuses.append(v)
    return _saved_tsui_refresh(ctrl)


_tsui_smoke.refresh = _cap_refresh


def _control_with_click(control, needle):
    for c in walk(control):
        if getattr(c, "on_click", None) is not None \
                and needle in " | ".join(all_text(c)).lower():
            return c
    return None


try:
    _update_btn = _control_with_click(page.controls[0], "update game version")
    check("the update-version button has a click handler",
          _update_btn is not None)
    if _update_btn is not None:
        # Case A: newest release is not installed -> selecting it starts the
        # download and says so (before, a non-installed latest could hit
        # "pick it from the list" even though it was already picked).
        _update_btn.on_click(None)
        _txt = " | ".join(all_text(page.controls[0])).lower()
        check("update selects the newest release",
              "minecraft 1.21.11" in _txt and "1.21.11" in _txt,
              f"txt={_txt[:400]!r}")
        _joined_status = " || ".join(s.lower() for s in _statuses)
        check("update never dead-ends on 'pick it from the list'",
              "pick it from the list" not in _joined_status,
              f"statuses={_statuses[-6:]!r}")
        check("update reports the download for the newest release",
              "getting 1.21.11" in _joined_status
              or "updating to 1.21.11" in _joined_status,
              f"statuses={_statuses[-6:]!r}")

        # Case B: newest release already selected AND installed -> a clear
        # "already latest" message, not a confusing no-op.
        core.get_installed_versions = lambda: [
            {"id": "1.21.11", "display_name": "1.21.11", "incomplete": False}]
        page3 = FakePage()
        app.main(page3)
        _btn3 = _control_with_click(page3.controls[0], "update game version")
        check("second app instance also has the update button",
              _btn3 is not None)
        if _btn3 is not None:
            _btn3.on_click(None)
            _txt3 = " | ".join(all_text(page3.controls[0])).lower()
            check("update keeps the latest installed release selected",
                  "minecraft 1.21.11" in _txt3, f"txt={_txt3[:400]!r}")
            check("update on the latest installed release reports it",
                  any("already on the latest release" in s.lower()
                      for s in _statuses),
                  f"statuses={_statuses[-6:]!r}")
finally:
    _release_install.set()
    _tsui_smoke.refresh = _saved_tsui_refresh
    core.install_version = _saved_install_version
    core.is_loader_supported = _saved_is_loader_supported
    core.mod_doctor = _saved_mod_doctor
    core.is_server_running = _saved_is_server_running
    core.get_installed_versions = _saved_get_installed

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

# --- playtime must actually be recorded on game exit --------------------------
# The 2026-09-11 stats bug: on_exit called `core.add_play_seconds`, but
# launcher_core re-exports it as `milestones_add_play_seconds` - so every
# session raised AttributeError, silently swallowed by the except, and "Time
# in game" stayed 0. Pin that the symbol main.py calls actually exists, and
# that the stale name is gone.
import launcher_core as _lc
check("launcher_core exposes the playtime accumulator",
      hasattr(_lc, "milestones_add_play_seconds"),
      "re-export milestones.add_play_seconds so main.py can call it")
check("on_exit ends the durable play session through a real attribute",
      "core.milestones_end_play_session(" in _src
      and "core.add_play_seconds(" not in _src,
      "main.py on_exit must call core.milestones_end_play_session")
# The game outlives the launcher, and a GPU-crash re-exec kills the in-process
# on_exit watcher - so the session start must be persisted and reconciled on
# the next start, or time played across a launcher restart is silently lost.
_src_launch = open(os.path.join(os.path.dirname(app.__file__),
                                "cubeon/launch.py"), encoding="utf-8").read()
check("launch pastes the play session to disk",
      "begin_play_session(" in _src_launch,
      "launch.py must call milestones.begin_play_session after Popen")
check("startup reconciles a play session orphaned by a launcher restart",
      "core.milestones_reconcile_play_session(" in _src,
      "main.py must call core.milestones_reconcile_play_session")
from cubeon import milestones as _mile
_mile.load_state()
_before = _mile._state["seconds_played"]
_lc.milestones_add_play_seconds(3661.0)
_after = _mile._state["seconds_played"]
check("the re-exported accumulator really credits playtime",
      abs((_after - _before) - 3661.0) < 0.001,
      f"seconds_played {_before} -> {_after}")

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

# --- dialogs actually close on the Flet 0.86 API -----------------------------
# The real bug (2026-09-08): Flet 0.86 removed Page.open()/close() in favor of
# show_dialog()/pop_dialog(); the app's helpers fell back to a pre-0.28 branch
# (page.dialog + overlay append) that 0.86 ignores, so the Legacy dialog and
# the version picker opened and then NEVER closed. These checks run the real
# helpers against a FakePage exposing the real 0.86 API surface.
print("\n9. dialog plumbing works on the Flet 0.86 API")
from cubeon import dialogs as _cd

_dlgpage = FakePage()
_dlg = ft.AlertDialog(title=ft.Text("legacy?"))
_cd.open_dialog(_dlgpage, _dlg)
check("open_dialog mounts into the 0.86 dialog stack",
      _dlg in _dlgpage._dialogs.controls and _dlg.open,
      f"stack={[type(c).__name__ for c in _dlgpage._dialogs.controls]}")
_cd.close_dialog(_dlgpage, _dlg)
check("close_dialog dismisses and unmounts it",
      not _dlg.open and _dlg not in _dlgpage._dialogs.controls,
      f"open={_dlg.open} stack={[type(c).__name__ for c in _dlgpage._dialogs.controls]}")

# A dialog buried under another one must still close (flag flip, no stack pop).
_d1, _d2 = ft.AlertDialog(title=ft.Text("a")), ft.AlertDialog(title=ft.Text("b"))
_cd.open_dialog(_dlgpage, _d1)
_cd.open_dialog(_dlgpage, _d2)
_cd.close_dialog(_dlgpage, _d1)
check("a buried dialog closes without popping the one above",
      not _d1.open and _d2.open and _d2 in _dlgpage._dialogs.controls)

_cd.show_snack(_dlgpage, "toast test", bgcolor="#123456")
check("show_snack mounts a SnackBar via the same stack",
      len(_dlgpage.snackbars) == 1 and _dlgpage.snackbars[0].open)

# And the app must not call the removed APIs anywhere.
_src_all = ""
for _f in ("main.py", "ui/modpacks_tab.py", "ui/server_tab.py"):
    _src_all += open(os.path.join(os.path.dirname(app.__file__), _f),
                     encoding="utf-8").read()
_bad = [ln for ln in _src_all.splitlines()
        if "page.open(" in ln or "page.close(" in ln]
check("no raw page.open()/page.close() calls in the UI layer", not _bad,
      f"{len(_bad)} stale call(s), first: {_bad[0] if _bad else ''}")

# --- the Cubeon Client mod off-switch lives in Settings -----------------------
# cfg["client_mod_enabled"]: when off, launch removes the injected client jar
# instead of installing it (cubeon/launch.py reads the same key).
_src_main = open(app.__file__, encoding="utf-8").read()
check("Settings exposes the client-mod off-switch",
      "client_mod_enabled" in _src_main and "client_mod_cb" in _src_main,
      "the checkbox must exist in main.py")
import cubeon.config as _cfgmod
check("config ships a default for the client mod",
      _cfgmod.DEFAULT_CONFIG.get("client_mod_enabled") is True)
import cubeon.launch as _launchmod
_launch_src = open(_launchmod.__file__, encoding="utf-8").read()
check("launch path honors the off-switch (and removes stale jars)",
      "client_mod_enabled" in _launch_src,
      "launch.py must read cfg['client_mod_enabled']")

# --- the version picker's search must not mutate the live dropdown ------------
# The old filter rewrote version_dropdown.options (and could reassign .value +
# call on_version_selected) on every keystroke, so typing in the picker's
# search box silently changed the selected version and kicked off a
# prefetch/download, and closing the dialog left the dropdown on a narrowed
# list. The search now filters its own snapshot (pick_source) only.
check("version picker filters its own list, not the live dropdown",
      'for o in pick_source["value"]' in _src_main
      and "version_dropdown.options = all_online_options" not in _src_main,
      "filter must read pick_source and leave version_dropdown.options alone")

# --- no ripple/click animations ------------------------------------------------
# The user hates the Material ink splash on every clickable Container.
# ink=False is the explicit off; nothing in the live UI may set ink=True.
_app_root = os.path.dirname(os.path.abspath(app.__file__))
_ui_files = ["main.py", "ui/modpacks_tab.py", "ui/server_tab.py",
             "ui/mods_tab.py", "ui/skin_tab.py", "cubeon/theme.py",
             "cubeon/inspector.py"]
_offenders = []
for _f in _ui_files:
    try:
        for _i, _ln in enumerate(open(os.path.join(_app_root, _f),
                                      encoding="utf-8"), 1):
            if "ink=True" in _ln or "ink=not " in _ln:
                _offenders.append(f"{_f}:{_i}")
    except OSError:
        pass
check("no Material ink ripples in the live UI", not _offenders,
      f"ripple sites: {_offenders[:3]}")

# --- keyboard must not register as a gamepad -----------------------------------
# Real case on this box: "Baseus K03 Keyboard" exposes /dev/input/js0 (media
# keys). The watcher must gate devices by shape/name (_looks_like_gamepad).
from cubeon.controller import _looks_like_gamepad as _is_pad
check("gamepad gate: keyboard-shaped js device refused",
      not _is_pad("Baseus K03 Keyboard", {0, 1, 2}, {0})
      and not _is_pad("AT Translated Set 2 Keyboard", set(), set()))
check("gamepad gate: real pads accepted",
      _is_pad("Microsoft Xbox Series S|X Controller", set(range(11)), set(range(6)))
      and _is_pad("Sony Interactive Entertainment DualSense Wireless Controller",
                  set(range(14)), set(range(7)))
      and _is_pad("Generic USB Joystick", set(range(12)), set(range(6))))
check("gamepad gate: named-but-tiny device still refused",
      not _is_pad("Xbox 360 Keyboard Adapter", set(range(2)), set()))
_src_ctrl = open(os.path.join(_app_root, "cubeon", "controller.py"),
                 encoding="utf-8").read()
check("watcher probes device shape before accepting",
      "_looks_like_gamepad" in _src_ctrl and "_probe_shape" in _src_ctrl
      and "_rejected" in _src_ctrl)

# --- the game must not inherit the launcher's software-GL fallback -------------
# main.py arms LIBGL_ALWAYS_SOFTWARE=1 + GALLIUM_DRIVER=llvmpipe when the
# flet client dies pre-paint; the game inherits env -> Minecraft on llvmpipe
# ran at ~4 FPS (verified live: /proc/<java>/environ had both vars).
_src_launch = open(os.path.join(_app_root, "cubeon", "launch.py"),
                   encoding="utf-8").read()
check("game env strips LIBGL_ALWAYS_SOFTWARE/GALLIUM_DRIVER",
      "LIBGL_ALWAYS_SOFTWARE" in _src_launch
      and "GALLIUM_DRIVER" in _src_launch
      and "popen_kwargs[\"env\"]" in _src_launch)
check("software-GL marker clears once the UI paints",
      "use_software_gl" in _src_main
      and _src_main.find("use_software_gl", _src_main.find("_reveal_window"))
      != -1)

# --- account panel must not re-sync the whole page ------------------------------
# Real jank (2026-09-08): opening/closing the account sidebar called
# page.update(), which diffs EVERY control in the tree - reads as the whole
# app reloading. The handlers must diff only the two overlay controls
# (thread_safe_ui.refresh(account_scrim/account_panel)), like _retire_scrim.
import re as _re
def _fn_body(source, name):
    seg = source[source.find(name):]
    m = _re.search(r"\n    def |\n\ndef ", seg[1:])
    return seg[:m.start() + 1] if m else seg
_open_src = _fn_body(_src_main, "def _open_account_panel")
_close_src = _fn_body(_src_main, "def _close_account_panel")
check("account panel open/close use per-control diffs, not page.update()",
      not _re.search(r"^\s*page\.update\(\)", _open_src, _re.M)
      and not _re.search(r"^\s*page\.update\(\)", _close_src, _re.M)
      and "thread_safe_ui.refresh(account_scrim)" in _open_src
      and "thread_safe_ui.refresh(account_panel)" in _open_src,
      "a page.update() call in the panel handlers is the full-app-reload jank")

# --- Browse/Installed view tabs on every content surface ------------------------
# User request (2026-09-09): mods/resourcepacks/shaders, modpacks and plugins
# each show ONE thing at a time - a Browse view (catalog) and an Installed
# view, switched by underline tabs, instead of the installed list living a
# full catalog-scroll below the results.
def _fn_src(source, name):
    i = source.find(f"def {name}")
    if i < 0:
        return ""
    m = _re.search(r"\n    def |\n\ndef ", source[i+1:])
    return source[i:i+1+m.start()] if m else source[i:]

_mods_src = open(os.path.join(_app_root, "ui", "mods_tab.py"), encoding="utf-8").read()
check("mods tab has Browse/Installed view tabs",
      "view_segment_row" in _mods_src and "on_view_change" in _mods_src
      and "browse_pane" in _mods_src and "installed_pane" in _mods_src
      and '"Installed"' in _mods_src,
      "the mods tab must toggle between browse and installed panes")
_mp_src = open(os.path.join(_app_root, "ui", "modpacks_tab.py"), encoding="utf-8").read()
check("modpacks tab has Browse/Installed view tabs",
      "view_segment_row" in _mp_src and "on_view_change" in _mp_src,
      "the modpacks tab must toggle between browse and installed panes")
_srv_src = open(os.path.join(_app_root, "ui", "server_tab.py"), encoding="utf-8").read()
check("plugins view has Browse/Installed view tabs",
      "plugins_view_segment_row" in _srv_src and "_on_plugins_view_change" in _srv_src
      and "plugins_browse_pane" in _srv_src and "plugins_installed_pane" in _srv_src,
      "the plugins view must toggle between market and installed panes")
# The toggle must not rebuild the whole tab: panes stay mounted, visibility flips.
check("view toggle flips pane visibility only",
      "browse_pane.visible" in _mods_src and "installed_pane.visible" in _mods_src,
      "toggling views must not re-create the panes")

# --- Stats tab (2026-09-09) ----------------------------------------------------
_stats_src = open(os.path.join(_app_root, "ui", "stats_tab.py"), encoding="utf-8").read()
_main_src = open(os.path.join(_app_root, "main.py"), encoding="utf-8").read()
check("stats tab exists and is wired into nav + lazy builders",
      "def build_stats_tab" in _stats_src
      and '("stats", ft.Icons.QUERY_STATS_ROUNDED, "Stats")' in _main_src
      and '"stats": _build_stats_tab' in _main_src
      and '"stats": stats_tab_host' in _main_src,
      "the Stats tab must be reachable from the top nav")
def _code_lines(source):
    """Source minus comment lines and docstring bodies - for checks that
    must not be fooled by prose mentioning a function name."""
    out, in_doc = [], False
    for line in source.splitlines():
        s = line.strip()
        if s.startswith('"""') or s.startswith("'''"):
            if not (s.count('"""') > 2 or s.count("'''") > 2):
                in_doc = not in_doc
            continue
        if in_doc or s.startswith("#"):
            continue
        out.append(line)
    return "\n".join(out)

check("stats scans are read-only (no create-on-read helpers)",
      "get_profile_dir(" not in _code_lines(_stats_src)
      and "get_plugins_dir(" not in _code_lines(_stats_src)
      and "content_dir(" not in _code_lines(_stats_src),
      "get_profile_dir/get_plugins_dir/content_dir CREATE folders on read - "
      "a stats pass must never leave empty folders behind")

# --- Chat tab (2026-09-11) -----------------------------------------------------
# The social layer moved out of the mod into the launcher: a nav entry, a lazy
# builder, and a tab module that must survive a public (no-Friends) build.
_chat_path = os.path.join(_app_root, "ui", "chat_tab.py")
check("chat tab exists and is wired into nav + lazy builders",
      os.path.exists(_chat_path)
      and "def build_chat_tab" in open(_chat_path, encoding="utf-8").read()
      and '("chat", ft.Icons.CHAT_BUBBLE_ROUNDED, "Chat")' in _main_src
      and '"chat": _build_chat_tab' in _main_src
      and '"chat": chat_tab_host' in _main_src,
      "the Chat tab must be reachable from the top nav and build lazily")
_chat_src = open(_chat_path, encoding="utf-8").read() if os.path.exists(_chat_path) else ""
check("chat tab degrades to a notice with no FriendsService",
      "if service is None" in _chat_src,
      "a public build passes friends_service=None and must not crash")
check("chat tab polls on a daemon thread, not the UI thread",
      "threading.Thread(" in _chat_src and "daemon=True" in _chat_src
      and "thread_safe_ui" in _chat_src,
      "FriendsService reads block on the websocket; they must not run on the UI thread")
check("chat tab shows the 12-digit ID and adds friends by ID",
      "your_id_text" in _chat_src and "canonical_uid" in _chat_src
      and "Add a friend by ID" in _chat_src
      and "name_field" not in _chat_src and "rename_unique" not in _chat_src,
      "chat identity is the server-assigned ID; names/secrets are not the add flow")
check("chat composer sends on Enter",
      "shift_enter=True" in _chat_src and "on_submit=lambda e: _do_send()" in _chat_src,
      "a multiline composer without shift_enter makes Enter insert a newline, "
      "so the only way to send is the tiny button - a chat that looks broken")
check("chat roster rail previews the last message and unread count",
      "last_text" in _chat_src and "unread" in _chat_src
      and "_unread_badge" in _chat_src,
      "a chat roster without a last-line preview / unread badge reads as a "
      "bare contact list")
check("chat transcript groups by day",
      "_day_key" in _chat_src and "_day_separator" in _chat_src
      and "Yesterday" in _chat_src,
      "long conversations need day separators instead of an undated stream")
check("chat marks a conversation read while it is open",
      "mark_read" in _chat_src,
      "without mark_read the unread badge never clears when a friend is selected")

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
