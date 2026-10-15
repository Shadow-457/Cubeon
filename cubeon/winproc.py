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
                    creationflags is OR-ed, not replaced).

  patch_mll()       minecraft_launcher_lib's FABRIC installer runs its
                    installer jar with plain subprocess.run (its quilt module
                    DOES hide the window - fabric was missed upstream), so the
                    module's subprocess reference is replaced with a shim that
                    injects the hidden flags. Called before any loader
                    install; safe to call repeatedly.
"""
import os
import subprocess

__all__ = ["hidden", "patch_mll"]


def hidden(**extra) -> dict:
    """kwargs for subprocess.run/Popen that never show a console on Windows.

    On posix this returns exactly `extra` (minus nothing) - the flags do not
    exist there and callers pass the dict straight through with **.
    """
    if os.name != "nt":
        return extra
    # A caller-supplied creationflags is OR-ed in (server.py needs
    # CREATE_NEW_PROCESS_GROUP too); CREATE_NO_WINDOW is always included.
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    flags |= extra.pop("creationflags", 0) or 0
    si = subprocess.STARTUPINFO()
    si.dwFlags |= subprocess.STARTF_USESHOWWINDOW
    si.wShowWindow = subprocess.SW_HIDE
    kw = dict(extra)
    kw["creationflags"] = flags
    kw["startupinfo"] = si
    return kw


class _HiddenSubprocess:
    """A subprocess-module stand-in that hides windows on run/Popen.

    Only what minecraft_launcher_lib actually uses is overridden; everything
    else forwards to the real module, so an upstream change can't silently
    break it.
    """

    def __getattr__(self, name):
        return getattr(subprocess, name)

    def run(self, *args, **kwargs):
        return subprocess.run(*args, **hidden(**kwargs))

    def Popen(self, *args, **kwargs):
        return subprocess.Popen(*args, **hidden(**kwargs))


def patch_mll() -> None:
    """Give minecraft_launcher_lib.fabric a window-hiding subprocess module.

    Idempotent (the shim detects itself). Never raises: the shim is polish -
    a missed patch means one console flash, not a broken install.
    """
    if os.name != "nt":
        return
    try:
        import minecraft_launcher_lib.fabric as mll_fabric
    except Exception:
        return
    if isinstance(getattr(mll_fabric, "subprocess", None), _HiddenSubprocess):
        return
    try:
        mll_fabric.subprocess = _HiddenSubprocess()
    except Exception:
        pass
