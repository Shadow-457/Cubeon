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

import threading


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
            import pystray
            from PIL import Image
        except Exception:
            return False  # not installed / no PIL: tray is simply off

        try:
            image = Image.open(self.icon_path)
        except Exception:
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
            # default=True marks "Open" as the left-click/double-click action
            # on platforms that distinguish (Windows, some Linux DEs).
            threading.Thread(target=self._icon.run, daemon=True,
                             name="cubeon-tray").start()
            self._started.set()
            return True
        except Exception:
            self._icon = None
            return False

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
