"""
Offline test for cubeon/dialogs.py - the shared dialog plumbing.

THE BUG THIS EXISTS FOR (2026-10-18 user report):
    "The application encountered an error: Dialog is already opened"

Flet 0.86's `Page.show_dialog()` raises

    RuntimeError("Dialog is already opened")

for a dialog instance that is ALREADY in the page's stack
(`page._dialogs.controls`), and `cubeon/dialogs.open_dialog()` passed that
straight through. The exception escapes whichever handler mounted the dialog,
so a no-op (the user is looking at the dialog already) surfaced as an
application error. Anything that can fire twice hits it - a double click, a
poll tick racing a button, a retry - which is exactly the "random" the
report described. The repo had already grown a one-off workaround for it
(main.py `_dialog_mounted`) while the 25 call sites going through the shared
helper stayed exposed.

The fix is one guard in the shared helper, so no call site can hit it:
a dialog that is already mounted is refreshed instead of re-shown.

These checks drive a FakePage that reproduces flet's REAL semantics (it
raises the same RuntimeError for a double mount), so the guard is proven
against the behaviour it exists for rather than against our own invention.

Run: python3 tools/test_dialogs.py
"""
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubeon import dialogs  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


class FakeStack:
    """`page._dialogs` - a control list with an update() of its own."""

    def __init__(self):
        self.controls = []
        self.updates = 0

    def update(self):
        self.updates += 1


class FakeDialog:
    def __init__(self, name="Dlg"):
        self.name = name
        self.open = False
        self.update_calls = 0

    def update(self):
        self.update_calls += 1

    def __repr__(self):
        return f"<{self.name}>"


class FakePage:
    """The parts of flet 0.86's Page that dialog plumbing touches.

    `show_dialog`/`pop_dialog` are copies of the real control flow, including
    the RuntimeError - that exception IS the bug being fixed, so faking it
    away would test nothing. Note there is no `page.close()`: 0.86 removed it.
    """

    def __init__(self, explode=None):
        self._dialogs = FakeStack()
        self.update_calls = 0
        self.explode = explode

    def update(self):
        self.update_calls += 1

    def show_dialog(self, dialog):
        if self.explode is not None:
            raise RuntimeError(self.explode)
        if dialog in self._dialogs.controls:
            raise RuntimeError("Dialog is already opened")
        dialog.open = True
        self._dialogs.controls.append(dialog)
        self._dialogs.update()

    def pop_dialog(self):
        # 0.86 pops the topmost OPEN dialog, marks it closed and updates.
        for dialog in reversed(self._dialogs.controls):
            if dialog.open:
                dialog.open = False
                dialog.update()
                self._dialogs.controls.remove(dialog)
                self._dialogs.update()
                return dialog
        self._dialogs.update()
        return None


class LegacyPage:
    """Pre-0.28 flet: no stack, just `page.open` + an overlay list."""

    def __init__(self):
        self.overlay = []
        self.dialog = None
        self.updates = 0

    def open(self, dlg):
        dlg.open = True
        self.dialog = dlg
        if dlg not in self.overlay:
            self.overlay.append(dlg)

    def update(self):
        self.updates += 1


class _Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.messages = []

    def emit(self, record):
        self.messages.append(record.getMessage())


# ---------------------------------------------- 1. the reported failure -------
print("\n1. mounting the same dialog twice no longer reaches the user")

page = FakePage()
dlg = FakeDialog("Confirm")

_contract = FakePage()
_contract_dlg = FakeDialog("Contract")
_contract.show_dialog(_contract_dlg)
try:
    _contract.show_dialog(_contract_dlg)
    _contract_msg = "no error"
except RuntimeError as _ex:
    _contract_msg = str(_ex)
check("the fake reproduces flet's double-mount RuntimeError (so the guard is "
      "tested against the real failure, not an invention)",
      _contract_msg == "Dialog is already opened", _contract_msg)

_page = FakePage()
_d = FakeDialog("Confirm")
dialogs.open_dialog(_page, _d)
check("a fresh dialog mounts once and is marked open",
      _page._dialogs.controls == [_d] and _d.open is True)

try:
    dialogs.open_dialog(_page, _d)
    _raised = False
except RuntimeError:
    _raised = True
check("re-opening the SAME dialog raises nothing (the reported error)",
      not _raised)
check("...and it is still mounted exactly once",
      _page._dialogs.controls == [_d])
check("...and the visible dialog was refreshed instead",
      _d.update_calls == 1, f"update_calls={_d.update_calls}")

_cap = _Capture()
_prev_level = dialogs.log.level
dialogs.log.setLevel(logging.INFO)
dialogs.log.addHandler(_cap)
try:
    dialogs.open_dialog(_page, _d)
finally:
    dialogs.log.removeHandler(_cap)
    dialogs.log.setLevel(_prev_level)
check("the suppression is logged, naming the dialog (so a repeat is traceable)",
      any("re-open suppressed" in m and "FakeDialog" in m for m in _cap.messages),
      str(_cap.messages))


# ---------------------------------------- 2. the semantics that must survive --
print("\n2. nothing else about dialogs changed")

pair = FakePage()
first, second = FakeDialog("First"), FakeDialog("Second")
dialogs.open_dialog(pair, first)
dialogs.open_dialog(pair, second)
check("two DIFFERENT dialogs both mount, in order",
      pair._dialogs.controls == [first, second])

# A barrier-dismissed dialog leaves the stack with .open STILL True.
pair._dialogs.controls.remove(first)
check("a barrier-dismissed dialog (.open True, off the stack) can be re-opened",
      (dialogs.open_dialog(pair, first),
       pair._dialogs.controls == [second, first])[1])
check("...which is why membership decides, not the .open flag",
      first.open is True)

fresh = FakePage()
right = FakeDialog()
dialogs.open_dialog(fresh, right)
dialogs.close_dialog(fresh, right)
check("closing the top dialog pops it", fresh._dialogs.controls == []
      and right.open is False)

mid = FakePage()
a, b = FakeDialog("A"), FakeDialog("B")
dialogs.open_dialog(mid, a)
dialogs.open_dialog(mid, b)
dialogs.close_dialog(mid, a)
check("closing a dialog UNDER another flips its flag but keeps the stack order",
      mid._dialogs.controls == [a, b] and a.open is False and b.open is True
      and a.update_calls == 1)

lonely = FakeDialog("NotMounted")
try:
    dialogs.close_dialog(mid, lonely)
    _closed = True
except Exception as _ex:   # pragma: no cover
    _closed = False
check("closing something that was never mounted cannot raise", _closed)

legacy = LegacyPage()
legacy_dlg = FakeDialog("Old")
dialogs.open_dialog(legacy, legacy_dlg)
check("a pre-0.28 page without show_dialog still uses page.open()",
      legacy.dialog is legacy_dlg and legacy_dlg.open is True)
dialogs.close_dialog(legacy, legacy_dlg)
check("...and closing it there cannot raise either",
      legacy_dlg.open is False and legacy.updates == 1)


# ------------------------------------------------- 3. best-effort contract ----
print("\n3. a dialog failure never breaks its caller")

boom = FakePage(explode="the transport fell over")
try:
    dialogs.open_dialog(boom, FakeDialog())
    _re_raised = False
except RuntimeError:
    _re_raised = True
check("an UNRELATED RuntimeError is not swallowed (real bugs still surface)",
      _re_raised)

try:
    dialogs.show_snack(boom, "hello")
    _snack_ok = True
except Exception:   # pragma: no cover
    _snack_ok = False
check("...but a snackbar call absorbs it (a toast must never break its caller)",
      _snack_ok)

one = FakePage()
dialogs.show_snack(one, "just once")
check("a normal snackbar mounts", len(one._dialogs.controls) == 1)


# --------------------------------------------------------------- 4. wiring ----
print("\n4. the guard cannot be bypassed")

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
# Only the SHIPPED surface: a test/fake is allowed to simulate flet's own
# show_dialog (that is how the failure is reproduced above).
_offenders = []
for _rel in ("main.py", "launcher_core.py", "cubeon", "ui"):
    _start = os.path.join(_ROOT, _rel)
    _paths = [_start] if os.path.isfile(_start) else []
    for _dir, _subdirs, _files in os.walk(_start):
        _subdirs[:] = [d for d in _subdirs if d != "__pycache__"]
        _paths += [os.path.join(_dir, n) for n in _files if n.endswith(".py")]
    for _path in _paths:
        if os.path.relpath(_path, _ROOT) == os.path.join("cubeon", "dialogs.py"):
            continue
        with open(_path, encoding="utf-8", errors="replace") as _fh:
            if ".show_dialog(" in _fh.read():
                _offenders.append(os.path.relpath(_path, _ROOT))
check("every dialog goes through the guarded helper (no direct show_dialog)",
      not _offenders, str(_offenders))

_MAIN = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
check("main.py's shared _open_dialog uses the helper",
      "cubeon_dialogs.open_dialog(page, dlg)" in _MAIN)
check("...and its snackbars do too",
      "cubeon_dialogs.show_snack(page, msg" in _MAIN)

# The upstream contract the guard exists for. Skipped (with a note) only if a
# different flet is installed, so a future flet that stops raising will be
# noticed here rather than in a user's error banner.
try:
    import flet
    _base = os.path.join(os.path.dirname(flet.__file__), "controls",
                         "base_page.py")
    with open(_base, encoding="utf-8") as _fh:
        _src = _fh.read()
    check("flet's show_dialog still raises 'Dialog is already opened'",
          'RuntimeError("Dialog is already opened")' in _src,
          f"read {_base}")
except Exception as _ex:
    print(f"  info  upstream check skipped ({_ex})")

print(f"\n{_passed} passed, {_failed} failed")
if _failed:
    print("Dialogs test: FAIL")
    sys.exit(1)
print("Dialogs test: PASS")
