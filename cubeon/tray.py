"""
System-tray ("background process") mode for Cubeon.

Closing the launcher window doesn't have to end the session - like AI-agent
apps and chat clients, the X button just hides the window while the process
keeps running with a small icon in the system tray (notification area /
status bar). The Friends connection stays up, Discord presence stays
announced, the skin keeps showing, and clicking the tray icon (or "Open")
brings the window back exactly as it was.

Why pystray and not Flet: Flet 0.86 has no tray API of its own. pystray is
pure Python (plus PIL, which Cubeon already ships for skins) and backs onto
the platform's native tray: appindicator on Linux/X11, Win32 on Windows,
AppKit on macOS.

Failure-safety mirrors discord_rpc.py: if pystray isn't installed, the
desktop has no tray, or any tray call fails, every method here is a silent
no-op and the launcher behaves exactly like before (X = quit). The module
must never be the reason the app doesn't start or doesn't exit.

Threading: pystray runs its own event loop on a thread it creates. Every
callback it fires arrives on that thread, so anything touching Flet goes
through run_thread-safe wrappers supplied by the caller (Flet page updates
from a foreign thread need thread_safe_ui - see that module).
"""
from __future__ import annotations

import logging
import os
import sys
import threading

log = logging.getLogger(__name__)


def _pick_linux_backend() -> None:
    """Pins pystray to a backend that a modern Linux desktop actually shows.

    Left to itself, pystray falls back to its **xorg** backend whenever the
    appindicator import raises for any reason. That backend draws an old
    XEmbed tray icon, which KDE Plasma 6 doesn't show at all (the legacy
    systray applet is gone) and Wayland can't show ever - so the launcher
    looked like it had "no tray" while pystray reported success. The
    icon existed; nothing on screen could display it.

    So: if AppIndicator (Ayatana or the older AppIndicator3) is importable,
    say so explicitly via PYSTRAY_BACKEND, which must be set BEFORE pystray
    is imported. StatusNotifierItem is what KDE, GNOME+extension, and
    wlroots panels all understand.
    """
    if not sys.platform.startswith("linux") or os.environ.get("PYSTRAY_BACKEND"):
        return
    try:
        import gi
        gi.require_version("Gtk", "3.0")
        for name, ver in (("AyatanaAppIndicator3", "0.1"),
                          ("AppIndicator3", "0.1")):
            try:
                gi.require_version(name, ver)
            except ValueError:
                continue
            __import__("gi.repository", fromlist=[name])
            os.environ["PYSTRAY_BACKEND"] = "appindicator"
            return
        os.environ["PYSTRAY_BACKEND"] = "gtk"  # GtkStatusIcon: still beats xorg
    except Exception:
        pass  # no gi at all: let pystray choose, tray may simply be off


class TrayController:
    """Owns the tray icon lifecycle. One instance per app run.

    The controller is deliberately dumb: it shows/hides the icon and calls
    caller-supplied callbacks. All decisions (what "close" means, whether the
    window hides or quits) stay in main.py where the rest of the window
    policy lives."""

    def __init__(self, *, icon_path: str, tooltip: str,
                 on_activate, on_quit):
        """on_activate: called when the user left-clicks the icon or picks
        "Open" - should bring the window back. on_quit: user picked "Quit" -
        should exit the app (cleanup + os._exit or equivalent). Both fire on
        pystray's thread."""
        self.icon_path = icon_path
        self.tooltip = tooltip
        self.on_activate = on_activate
        self.on_quit = on_quit
        self._icon = None
        self._started = threading.Event()

    # ------------------------------------------------------------------ api

    def start(self) -> bool:
        """Creates and shows the tray icon. Returns True when running.
        Idempotent; safe to call when pystray is unavailable."""
        if self._icon is not None:
            return True
        try:
            _pick_linux_backend()
            import pystray
            from PIL import Image
        except Exception as ex:
            log.warning("tray: unavailable (%s: %s)", ex.__class__.__name__, ex)
            return False  # not installed / no PIL: tray is simply off

        try:
            image = Image.open(self.icon_path)
            image.load()  # decode now: a lazy failure inside pystray is silent
        except Exception as ex:
            log.warning("tray: icon %s unusable (%s)", self.icon_path, ex)
            return False  # missing/corrupt icon file: off, not an error

        def _activate(icon=None, item=None):
            try:
                self.on_activate()
            except Exception:
                pass

        def _quit(icon=None, item=None):
            try:
                self.stop()
            finally:
                try:
                    self.on_quit()
                except Exception:
                    pass

        try:
            self._icon = pystray.Icon(
                "Cubeon",
                icon=image,
                title=self.tooltip,
                menu=pystray.Menu(
                    pystray.MenuItem("Open Cubeon", _activate, default=True),
                    pystray.Menu.SEPARATOR,
                    pystray.MenuItem("Quit", _quit),
                ),
            )
        except Exception as ex:
            log.warning("tray: icon creation failed (%s)", ex)
            self._icon = None
            return False

        # default=True marks "Open" as the left-click/double-click action
        # on platforms that distinguish (Windows, some Linux DEs).
        #
        # The setup callback is the ONLY honest proof the tray came up: it
        # fires from inside pystray's own loop once the icon is registered
        # with the desktop. The old code assumed success as soon as the
        # thread was started, so a backend that failed a moment later still
        # left close_to_tray ON - and then closing the window parked the
        # process headless with no icon to reopen or quit it. An invisible
        # un-killable launcher is far worse than no tray, so failure to
        # confirm within the timeout counts as "no tray".
        def _setup(icon):
            try:
                icon.visible = True
            except Exception:
                pass
            self._started.set()

        def _loop():
            try:
                self._icon.run(setup=_setup)
            except Exception as ex:
                log.warning("tray: loop ended (%s: %s)", ex.__class__.__name__, ex)
                self._icon = None
                self._started.set()  # unblock start(); running turns False

        threading.Thread(target=_loop, daemon=True, name="cubeon-tray").start()
        if not self._started.wait(timeout=5.0) or self._icon is None:
            log.warning("tray: backend %s never became visible",
                        os.environ.get("PYSTRAY_BACKEND", "auto"))
            self.stop()
            self._started.clear()
            return False
        log.info("tray: running (backend=%s)",
                 os.environ.get("PYSTRAY_BACKEND", "auto"))
        return True

    def set_tooltip(self, text: str) -> None:
        """Updates the hover text. Used to acknowledge "Open" instantly -
        reopening restarts the launcher, which takes a couple of seconds,
        and a tray icon that reacts to nothing reads as a dead one."""
        icon = self._icon
        if icon is None:
            return
        try:
            icon.title = text
        except Exception:
            pass

    def stop(self) -> None:
        """Removes the icon and ends pystray's loop. Idempotent, never
        raises - called both from the menu's Quit and from app shutdown."""
        icon, self._icon = self._icon, None
        if icon is None:
            return
        try:
            icon.stop()
        except Exception:
            pass

    @property
    def running(self) -> bool:
        return self._icon is not None and self._started.is_set()
