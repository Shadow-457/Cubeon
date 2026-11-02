"""Windows: children must never flash a console window.

Cubeon.exe is a --windowed (no-console) app, but every child process it
spawns - a `java -version` probe, the Fabric installer jar, `tzutil`, a
local server - gets its OWN console window on Windows unless it is started
with CREATE_NO_WINDOW / STARTF_USESHOWWINDOW(SW_HIDE). The user sees a black
cmd box pop for a second on every click ("cmd opens and closes" - reported
2026-10-15). Linux/macOS need none of this; everything here degrades to a
no-op there.

Two halves:

  hidden(**extra)   subprocess kwargs that hide the child window, merged with
                    whatever the caller already passes (a caller-supplied
                    creationflags is preserved except CREATE_NEW_CONSOLE).

  patch_mll()       wraps subprocess references in minecraft_launcher_lib,
                    including its current mod_loader adapters and Java helpers.
                    Called before loader installation; safe to repeat.
"""
import copy
import importlib
import os
import subprocess
import sys

__all__ = ["hidden", "patch_mll"]


def hidden(**extra) -> dict:
    """kwargs for subprocess.run/Popen that never show a console on Windows.

    On posix this returns exactly `extra` (minus nothing) - the flags do not
    exist there and callers pass the dict straight through with **.
    """
    if os.name != "nt":
        return extra
    # CREATE_NO_WINDOW is ignored alongside CREATE_NEW_CONSOLE on Windows.
    # Remove that conflicting flag; preserve grouping/job/lifecycle flags.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    flags |= (extra.pop("creationflags", 0) or 0) & ~getattr(subprocess, "CREATE_NEW_CONSOLE", 0)
    supplied_info = extra.pop("startupinfo", None)
    si = copy.copy(supplied_info) if supplied_info is not None else subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    kw = dict(extra)
    kw["creationflags"] = flags
    kw["startupinfo"] = si
    return kw


class _HiddenSubprocess:
    """A subprocess-module stand-in that hides all child-launch helpers.

    Standard launch helpers enforce the same policy. Constants and everything
    else forward to the real module.
    """

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def run(self, *args, **kwargs):
        return subprocess.run(*args, **hidden(**kwargs))

    def Popen(self, *args, **kwargs):
        return subprocess.Popen(*args, **hidden(**kwargs))

    def call(self, *args, **kwargs):
        return subprocess.call(*args, **hidden(**kwargs))

    def check_call(self, *args, **kwargs):
        return subprocess.check_call(*args, **hidden(**kwargs))

    def check_output(self, *args, **kwargs):
        return subprocess.check_output(*args, **hidden(**kwargs))


def patch_mll() -> None:
    """Hide subprocesses in loaded legacy/current mll modules, without
    changing Python's shared subprocess module.

    Idempotent (the shim detects itself). Never raises: the shim is polish -
    a missed patch means one console flash, not a broken install.
    """
    if os.name != "nt":
        return
    try:
        importlib.import_module("minecraft_launcher_lib")
    except Exception:
        return
    for name, module in tuple(sys.modules.items()):
        if not name.startswith("minecraft_launcher_lib.") or module is None:
            continue
        if getattr(module, "subprocess", None) is subprocess:
            module.subprocess = _HiddenSubprocess()
