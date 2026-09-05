"""Feature switches for development and public builds."""
from __future__ import annotations

import os
import sys


def _bundled_public_marker() -> bool:
    """True when a packaged public build contains its no-Friends marker."""
    roots = []
    meipass = getattr(sys, "_MEIPASS", None)
    if meipass:
        roots.append(meipass)
    if getattr(sys, "frozen", False):
        exe = os.path.dirname(os.path.abspath(sys.executable))
        roots.extend((exe, os.path.join(exe, "_internal")))
    appdir = os.environ.get("APPDIR")
    if appdir:
        roots.extend((os.path.join(appdir, "usr", "bin"),
                      os.path.join(appdir, "usr", "bin", "_internal")))
    return any(os.path.isfile(os.path.join(root, "assets", "cubeon_no_friends"))
               for root in roots)


def friends_enabled() -> bool:
    """Whether this launcher should use the in-game Friends feature.

    Development/source builds are enabled by default. Public builds contain a
    marker file and are permanently disabled without requiring users to set an
    environment variable. The environment override is useful for testing.
    """
    override = os.environ.get("CUBEON_FRIENDS")
    if override is not None:
        return override.strip().lower() not in {"0", "false", "no", "off"}
    return not _bundled_public_marker()
