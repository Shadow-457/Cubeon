"""
Offline test for the keyboard shortcuts + F11 fullscreen feature.

Two layers, because they fail in different ways:

  * cubeon/shortcuts.py is the pure decision table, so it is driven directly
    with synthetic key payloads - including the payloads that MUST NOT fire
    (plain digits while typing, Alt combos, Ctrl+F11).
  * main.py's wiring is checked by reading its source, the way the other UI
    suites do it: the dispatcher must use the table, F11 must toggle through
    the always-send window write (a bare `full_screen = False` is dropped by
    flet, leaving the window stuck fullscreen), the geometry save must not
    record the fullscreen rect, and the F1 help must list the table.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from cubeon import shortcuts as keys

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


# --- the decision table ----------------------------------------------------
CASES = (
    # (kwargs, expected action)
    ({"key": "F1"}, keys.HELP),
    ({"key": "F11"}, keys.FULLSCREEN),
    ({"key": "f11"}, keys.FULLSCREEN),
    ({"key": "Escape"}, keys.ESCAPE),
    ({"key": "esc"}, keys.ESCAPE),
    ({"key": "1", "ctrl": True}, "tab:1"),
    ({"key": "Digit3", "ctrl": True}, "tab:3"),
    ({"key": "Numpad9", "meta": True}, "tab:9"),      # Cmd+9 on macOS
    ({"key": "Enter", "ctrl": True}, keys.MAIN_ACTION),
    ({"key": "NumpadEnter", "ctrl": True}, keys.MAIN_ACTION),
    ({"key": ",", "ctrl": True}, keys.SETTINGS),
    ({"key": "Comma", "ctrl": True}, keys.SETTINGS),
    ({"key": "q", "ctrl": True}, keys.QUIT),
    ({"key": "Q", "meta": True}, keys.QUIT),
    # Things that must NOT fire.
    ({"key": "1"}, None),                             # typing in a field
    ({"key": "9"}, None),
    ({"key": "F11", "ctrl": True}, None),             # only the bare key
    ({"key": "F11", "alt": True}, None),              # Alt is never claimed
    ({"key": "q", "alt": True}, None),
    ({"key": "0", "ctrl": True}, None),               # 1..9 only
    ({"key": "F5"}, None),
    ({"key": "Control"}, None),
    ({"key": ""}, None),
    ({"key": None}, None),
    ({"key": None, "ctrl": True}, None),
    ({"key": ["Enter"]}, None),                       # hostile payload
)

for kwargs, expected in CASES:
    got = keys.resolve(**kwargs)
    check(f"resolve({kwargs}) -> {expected!r}", got == expected, f"got {got!r}")

# Shift must not change a command combo (layouts vary), but a shifted digit
# arrives as a symbol on most layouts - that already just doesn't match.
check("resolve: Esc with shift still means escape",
      keys.resolve("Escape", shift=True) == keys.ESCAPE)
check("resolve: Ctrl+Enter with shift still means the main action",
      keys.resolve("Enter", ctrl=True, shift=True) == keys.MAIN_ACTION)
check("resolve: an upper-case key label still matches",
      keys.resolve("Q", ctrl=True) == keys.QUIT)

# --- tab action helpers ----------------------------------------------------
check("tab_action/tab_index round-trip",
      all(keys.tab_index(keys.tab_action(n)) == n for n in range(1, 10)),
      str([keys.tab_index(keys.tab_action(n)) for n in range(1, 10)]))
check("tab_index: rejects non-tab actions",
      all(keys.tab_index(a) is None
          for a in (keys.QUIT, keys.FULLSCREEN, "tab:", "tab:x", "tab:0",
                    "tab:10", None, 5)))
check("tab_action: caps at 9 (Ctrl+0 is not a shortcut)",
      keys.tab_index(keys.tab_action(10)) is None)

# --- the help catalogue and the table agree --------------------------------
covered = {
    keys.resolve("F1"),
    keys.resolve("F11"),
    keys.resolve("Escape"),
    keys.resolve("1", ctrl=True),
    keys.resolve("Enter", ctrl=True),
    keys.resolve(",", ctrl=True),
    keys.resolve("q", ctrl=True),
}
check("catalogue: every action the table can return is listed",
      covered == {keys.HELP, keys.FULLSCREEN, keys.ESCAPE, "tab:1",
                  keys.MAIN_ACTION, keys.SETTINGS, keys.QUIT},
      str(covered))
check("catalogue: one help line per combo",
      len(keys.CATALOGUE) == len(covered), str(keys.CATALOGUE))
check("catalogue: combo column is what resolve() answers",
      all(combo and what for combo, what in keys.CATALOGUE),
      str(keys.CATALOGUE))
check("catalogue: mentions fullscreen, settings and quit",
      any("Fullscreen" in what for _, what in keys.CATALOGUE)
      and any("Settings" in what for _, what in keys.CATALOGUE)
      and any("Quit" in what for _, what in keys.CATALOGUE),
      str(keys.CATALOGUE))

# --- main.py wiring --------------------------------------------------------
root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(root, "main.py"), encoding="utf-8") as fh:
    src = fh.read()

check("wiring: the table is imported, not re-implemented",
      "from cubeon import shortcuts as cubeon_shortcuts" in src
      and "cubeon_shortcuts.resolve(" in src,
      "the decision table must stay testable off-window")
check("wiring: page.on_keyboard_event still installed",
      "page.on_keyboard_event = _on_key" in src)
check("wiring: modifier spelling is version-tolerant",
      'getattr(e, "ctrl", False)' in src and 'getattr(e, "control", False)' in src,
      "flet has spelled it both ways")
check("wiring: F11 toggles fullscreen via the always-send write",
      'def _toggle_fullscreen():' in src
      and '_force_window_bool("full_screen", active)' in src,
      "a bare full_screen=False is DROPPED by flet (it equals the default)")
check("wiring: fullscreen parks the resize hot-zones",
      "not (_chrome_state[\"maximized\"] or _fullscreen[\"active\"])" in src,
      "a fullscreen window has nothing to resize")
check("wiring: the fullscreen rect is never saved as window geometry",
      'maximized = bool(w.maximized) or bool(_fullscreen["active"])' in src,
      "otherwise the next launch opens screen-sized-but-not-fullscreen")
check("wiring: a native fullscreen change is adopted",
      'ev.replace("_", "-") in ("enter-full-screen",' in src
      and "_adopt_fullscreen_state(" in src,
      "the WM can leave fullscreen without us")
check("wiring: Ctrl+Enter can't bypass a disabled Play",
      "if not play_button.disabled:" in src
      and "_main_action_click()" in src,
      "the mouse path is blocked by disabled; the keyboard must be too")
check("wiring: Ctrl+N indexes the LIVE nav list",
      "switch_tab(top_nav_items[n - 1][0])" in src,
      "a hardcoded table would desync when the Chat tab is absent")
check("wiring: Escape closes the help dialog before other things",
      'if _dialog_mounted(_shortcuts_dlg["dlg"]):' in src
      and "cubeon_dialogs.close_dialog(page, _shortcuts_dlg[\"dlg\"])" in src)
check("wiring: F1 opens the shortcut list from the shared catalogue",
      "def _show_shortcuts(e=None):" in src
      and "for combo, what in cubeon_shortcuts.CATALOGUE" in src)
check("wiring: the handler swallows everything (never takes the UI down)",
      "        except Exception:\n            pass\n    try:\n        page.on_keyboard_event = _on_key" in src)
check("wiring: top-nav tooltip stays EXACTLY the label", "tooltip=label," in src,
      "tools/_fuzz_common.ctrl_text reads a nav button's TOOLTIP as its label "
      "(the icon-only button has no visible Text), so a hint suffix breaks "
      "goto()/ux_capture label matching - that regressed test_fuzz.py once")
check("wiring: F12 inspector still handled",
      'if str(key) == "F12" and _inspector_enabled:' in src)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
