"""Keyboard shortcuts: one pure mapping from a key event to an action id.

WHY A TABLE, NOT A HANDLER FULL OF if/elif

The handler in main.py has to run on flet's event loop and must stay tiny and
unable-to-raise, so the *decision* ("what does this key mean?") lives here as a
pure function. That makes the shortcut set testable without a window (see
tools/test_keyboard_shortcuts.py) and lets the same table label the on-screen
help (main.py's F1 dialog) - a shortcut nobody can discover is folklore.

THE COMBOS (kept deliberately small and conventional)

  F1                   the shortcut list itself
  F11                  fullscreen on / off
  Esc                  leave fullscreen, else close the account panel
  Ctrl+1 … Ctrl+9      jump to that tab in the top bar
  Ctrl+,               Settings
  Ctrl+Enter           the big button: Play / Cancel / Quit
  Ctrl+Q               quit Cubeon

RULES OF THE ROAD

* Ctrl or Cmd (meta) both count as "the command modifier", so the macOS build
  gets Cmd+Q / Cmd+, without a second table.
* Alt/Meta-only combos are never claimed: Alt belongs to menus/the OS, and
  swallowing it would break real input.
* Plain keys are only claimed when they are function keys / Escape - typing
  "1" in the username field must never switch tabs.
"""
import re

__all__ = [
    "FULLSCREEN", "ESCAPE", "SETTINGS", "MAIN_ACTION", "QUIT", "HELP",
    "TAB_PREFIX", "tab_action", "tab_index", "CATALOGUE", "resolve",
]

FULLSCREEN = "fullscreen"
ESCAPE = "escape"
SETTINGS = "settings"
MAIN_ACTION = "main_action"
QUIT = "quit"
HELP = "help"

# Tab jumps are parameterised: "tab:1" … "tab:9" (1-based, top-bar order).
TAB_PREFIX = "tab:"

# What the F1 help dialog shows, in the order it reads best. Keep this in step
# with resolve() below - tools/test_keyboard_shortcuts.py pins every entry to
# the combo resolve() actually answers.
CATALOGUE = (
    ("F1", "Show this shortcut list"),
    ("F11", "Fullscreen on / off"),
    ("Esc", "Leave fullscreen, or close the account panel"),
    ("Ctrl + 1 … 9", "Jump to that tab in the top bar"),
    ("Ctrl + ,", "Settings"),
    ("Ctrl + Enter", "Play / cancel / quit the selected instance"),
    ("Ctrl + Q", "Quit Cubeon"),
)

# Plain (no command modifier) key -> action. Function keys are compared
# case-insensitively, so both "F11" and "f11" land here.
_PLAIN = {
    "f1": HELP,
    "f11": FULLSCREEN,
    "escape": ESCAPE,
    "esc": ESCAPE,
}

_ENTER = ("enter", "return", "numpadenter", "numpad_enter")
# "," is Flutter's keyLabel for the comma key; older/newer builds spell it out.
_COMMA = (",", "comma")

# Flutter reports digit keys as "1", "Digit1" or "Numpad1" depending on the
# client build; all three mean the same shortcut.
_DIGIT = re.compile(r"(?:digit|numpad)?([1-9])")


def tab_action(index: int) -> str:
    """The action id for the Nth top-bar tab (1-based)."""
    return f"{TAB_PREFIX}{int(index)}"


def tab_index(action: str) -> "int | None":
    """The 1-based tab number in a "tab:N" action, or None if it isn't one."""
    if not isinstance(action, str) or not action.startswith(TAB_PREFIX):
        return None
    try:
        n = int(action[len(TAB_PREFIX):])
    except (TypeError, ValueError):
        return None
    return n if 1 <= n <= 9 else None


def _normalise(key) -> str:
    """Lower-case, trimmed key label. Never raises on odd payloads."""
    try:
        return str(key or "").strip().lower()
    except Exception:
        return ""


def resolve(key, *, ctrl: bool = False, alt: bool = False,
            shift: bool = False, meta: bool = False) -> "str | None":
    """What action (if any) a key event means.

    ``key`` is flet's human-readable label (``KeyboardEvent.key``). Modifier
    flags are passed explicitly rather than read off the event so this stays
    testable and version-tolerant (flet has spelled them both ``ctrl`` and
    ``control`` across releases - main.py normalises that for us).
    """
    k = _normalise(key)
    if not k:
        return None
    # Alt belongs to menus and the OS; never claim it.
    if alt:
        return None
    cmd = bool(ctrl or meta)

    if not cmd:
        return _PLAIN.get(k)

    if k in _ENTER:
        return MAIN_ACTION
    if k == "q":
        return QUIT
    if k in _COMMA:
        return SETTINGS
    m = _DIGIT.fullmatch(k)
    if m:
        return tab_action(m.group(1))
    return None
