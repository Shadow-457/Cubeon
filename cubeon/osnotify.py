"""
Local OS notifications (Phase 7, 2026-10-16).

A desktop toast - Windows / Linux / macOS - when something finishes or
something you care about happens. Deliberately LOCAL and dumb: there is no
server, no push, no account, and this module never sends anything anywhere.
It shells out to the platform's own notifier (or winotify on Windows) and
gives up quietly if there isn't one.

WHAT CAN NOTIFY
    Seven kinds, each with its own Settings switch (KINDS, below). The user
    asked for a toggle per type, and these are the types.

    install-finished: instance, mod, modpack, resourcepack, texturepack
    friend online:    friend  - and ONLY the friend you talk to most
    Cubeon update:    update

DESIGN RULES (each one is a bug that would be reportable)

  * Never raise, never block the caller. `notify()` hands the actual send to
    a daemon thread: `notify-send` and PowerShell both take 100-300ms to
    start, and several call sites are UI handlers or the friends event loop.
  * Never notify while notifications are OFF. `enabled(kind, cfg)` is checked
    BEFORE anything else, from the live config dict when the caller has one
    (the Settings toggles must take effect without a restart).
  * Collapse duplicates. A pack install fires several success callbacks; a
    friend's presence flaps. Identical (kind, title) inside `_MIN_GAP`
    seconds is dropped.
  * A notification is never the only evidence something worked: every call
    site already shows the result in the launcher. Losing a toast is cosmetic.
  * `CUBEON_OSNOTIFY_OFF=1` disables the module entirely (tests, CI, and
    anyone who wants the old silence back without hunting for toggles).
"""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
import sys
import threading
import time
from xml.sax.saxutils import escape as _xml_escape

log = logging.getLogger(__name__)

APP_NAME = "Cubeon"

# (kind, config key, Settings label, one-line what-it-means).
# A LIST, not a dict: this is also the Settings display order, and the toggles
# read better grouped installs-first.
KINDS = [
    ("instance",     "notify_instance",
     "Game versions", "A version or its mod loader finishes installing"),
    ("mod",          "notify_mod",
     "Mods", "A mod finishes installing"),
    ("modpack",      "notify_modpack",
     "Modpacks", "A modpack finishes installing"),
    ("resourcepack", "notify_resourcepack",
     "Resource packs", "A resource pack finishes installing"),
    ("texturepack",  "notify_texturepack",
     "Texture packs & shaders",
     "A texture pack or shader finishes installing"),
    ("friend",       "notify_friend",
     "Friend online", "Only your most-talked-to friend, not every friend"),
    ("update",       "notify_update",
     "Cubeon updates", "A new Cubeon version is available"),
]

# kind -> config key / label / subtitle, for callers and the Settings pane.
KIND_KEYS = {kind: key for kind, key, _label, _sub in KINDS}
KIND_LABELS = {kind: (label, sub) for kind, _key, label, sub in KINDS}

# Two identical notifications inside this many seconds collapse into one.
_MIN_GAP = 1.5
_recent: dict[tuple, float] = {}
_recent_lock = threading.Lock()


# ---------------------------------------------------------------------------
# availability
# ---------------------------------------------------------------------------

def backend_name() -> str:
    """Which notifier this box would use: 'winotify', 'powershell',
    'notify-send', 'osascript' or '' (nothing available).

    Never raises: `notify()` calls this on the caller's thread, and the whole
    contract of this module is that a missing or broken notifier costs the
    caller nothing.
    """
    try:
        if os.environ.get("CUBEON_OSNOTIFY_OFF"):
            return ""
        if os.name == "nt":
            try:
                import winotify  # noqa: F401
                return "winotify"
            except Exception:
                return "powershell" if shutil.which("powershell") else ""
        if sys.platform == "darwin":
            return "osascript" if shutil.which("osascript") else ""
        return "notify-send" if shutil.which("notify-send") else ""
    except Exception:
        log.debug("could not detect a notifier", exc_info=True)
        return ""


def available() -> bool:
    return bool(backend_name())


# ---------------------------------------------------------------------------
# the per-kind switch
# ---------------------------------------------------------------------------

def enabled(kind: str, cfg: dict | None = None) -> bool:
    """Is this kind allowed to notify?

    `cfg` is the LIVE config dict when the caller has one - the Settings
    switches mutate it in place, so a toggle takes effect immediately rather
    than at the next start. Without one, the config is read from disk.
    """
    if os.environ.get("CUBEON_OSNOTIFY_OFF"):
        return False
    key = KIND_KEYS.get(kind)
    if not key:
        return False
    if cfg is None:
        try:
            from cubeon import config as _config
            cfg = _config.load_config()
        except Exception:
            # An unreadable config means "we can't know the user's choice".
            # Default to ON: the toggles default to on, and losing the toast
            # is worse than one the user then turns off.
            return True
    try:
        return bool(cfg.get(key, True))
    except Exception:
        return True


def _throttled(kind: str, title: str, now: float | None = None) -> bool:
    """True when this exact notification went out a moment ago."""
    key = (kind, title)
    now = time.monotonic() if now is None else now
    with _recent_lock:
        last = _recent.get(key)
        if last is not None and (now - last) < _MIN_GAP:
            return True
        _recent[key] = now
        # Bound the dict: this process can run for days.
        if len(_recent) > 64:
            cutoff = now - 60.0
            for k in [k for k, t in _recent.items() if t < cutoff]:
                del _recent[k]
        return False


# ---------------------------------------------------------------------------
# sending
# ---------------------------------------------------------------------------

def _send(title: str, body: str) -> bool:
    """The actual OS call. Blocking, best-effort, never raises."""
    backend = backend_name()
    try:
        if backend == "winotify":
            from winotify import Notification
            Notification(app_id=APP_NAME, title=title, msg=body).show()
            return True
        if backend == "powershell":
            return _send_powershell(title, body)
        if backend == "notify-send":
            return _send_notify_send(title, body)
        if backend == "osascript":
            script = (f'display notification "{_as_escape(body)}" '
                      f'with title "{_as_escape(title)}"')
            return _run(["osascript", "-e", script])
    except Exception:
        log.debug("os notification failed", exc_info=True)
    return False


def _spawn_kwargs() -> dict:
    """Hidden-window subprocess flags on Windows (see cubeon/winproc.py).

    Without these a PowerShell toast flashes a console window at the player -
    the exact thing winproc exists to prevent.
    """
    try:
        from cubeon import winproc
        return winproc.hidden()
    except Exception:
        return {}


def _run(argv, **kwargs) -> bool:
    proc = subprocess.run(argv, capture_output=True, timeout=15,
                          **{**_spawn_kwargs(), **kwargs})
    return proc.returncode == 0


def _send_notify_send(title: str, body: str) -> bool:
    return _run(["notify-send", "-a", APP_NAME, "-u", "normal", title, body])


# Windows' WinRT toasts, no dependency. Same visuals as winotify, just more
# typing. Kept as the fallback so a frozen build without winotify bundled
# still notifies.
_PS_TOAST = (
    '$ErrorActionPreference="Stop";'
    '[Windows.UI.Notifications.ToastNotificationManager,'
    'Windows.UI.Notifications,ContentType=WindowsRuntime]>$null;'
    '[Windows.Data.Xml.Dom.XmlDocument,Windows.Data.Xml.Dom,'
    'ContentType=WindowsRuntime]>$null;'
    '$t=@\'<toast><visual><binding template="ToastGeneric"><text>{title}</text>'
    '<text>{body}</text></binding></visual></toast>\'@;'
    '$x=New-Object Windows.Data.Xml.Dom.XmlDocument;$x.LoadXml($t);'
    '$n=New-Object Windows.UI.Notifications.ToastNotification $x;'
    '[Windows.UI.Notifications.ToastNotificationManager]'
    '::CreateToastNotifier("{app}").Show($n)'
)


def _send_powershell(title: str, body: str) -> bool:
    script = _PS_TOAST.format(title=_xml_escape(title), body=_xml_escape(body),
                              app=APP_NAME)
    return _run(["powershell", "-NoProfile", "-NonInteractive", "-Command", script])


def _as_escape(text: str) -> str:
    """AppleScript string literal escaping (backslash first, then quote)."""
    return str(text).replace("\\", "\\\\").replace('"', '\\"')


# ---------------------------------------------------------------------------
# public entry point
# ---------------------------------------------------------------------------

def notify(kind: str, title: str, body: str, *, cfg: dict | None = None,
           force: bool = False, thread_factory=threading.Thread) -> bool:
    """Show an OS notification. Returns True when one was QUEUED.

    `force=True` skips the user's toggle (used by the Settings "Send a test
    notification" button, which would otherwise be a no-op whenever
    notifications are switched off - exactly when you'd want to test them).
    """
    if not title:
        return False
    if not force and not enabled(kind, cfg):
        return False
    if not available():
        return False
    if _throttled(kind, title):
        return False

    def _work():
        try:
            _send(title, body)
        except Exception:
            log.debug("os notification worker failed", exc_info=True)

    try:
        thread_factory(target=_work, name="osnotify", daemon=True).start()
        return True
    except Exception:
        log.debug("os notification thread could not start", exc_info=True)
        return False


def install_finished(kind: str, what: str, *, cfg: dict | None = None) -> bool:
    """The shared shape for every finished download."""
    try:
        what = str(what or "").strip()
    except Exception:
        what = ""
    what = what or KIND_LABELS.get(kind, ("That", ""))[0]
    return notify(kind, f"{what} is ready",
                  "Cubeon finished installing it.", cfg=cfg)


def content_kind(content_type: str) -> str:
    """Map the launcher's content type to a notification kind.

    cubeon/content.py knows exactly two non-mod content types - 'resourcepack'
    and 'shader' - and a texture pack and a resource pack are the same thing in
    modern Minecraft, so the 'texturepack' switch (the user's fifth type) is
    what the launcher's other visual-content type rides on. Anything unknown
    falls back to 'mod' rather than inventing a kind with no switch.
    """
    if content_type in ("mod", "modpack", "resourcepack", "shader"):
        return "texturepack" if content_type == "shader" else content_type
    return "mod"


def top_friend(counts: dict | None) -> str | None:
    """The friend with the most messages exchanged, or None.

    Ties break on the case-folded name, so "alex" beats "Sam" and the answer is
    STABLE: a "most talked to" friend that reshuffles itself between calls
    would make the notification feel random, which is worse than not sending it.
    """
    scored = []
    try:
        items = list((counts or {}).items())
    except Exception:
        # A caller handed us something that isn't a mapping. "No history" is the
        # safe reading, and the alternative is raising out of a notification.
        return None
    for name, count in items:
        if not name:
            continue
        try:
            n = int(count)
        except (TypeError, ValueError):
            continue
        if n <= 0:
            continue
        scored.append((n, str(name).casefold(), str(name)))
    if not scored:
        return None
    scored.sort(key=lambda row: (-row[0], row[1], row[2]))
    return scored[0][2]


def friend_came_online(name: str, counts: dict | None, *, cfg: dict | None = None) -> bool:
    """Notify when the MOST-TALKED-TO friend comes online. Nobody else.

    `counts` is {friend name: messages exchanged}. With no history at all the
    answer is "stay quiet" rather than "notify for everyone": the user asked
    for one friend, not for the roster.
    """
    name = str(name or "").strip()
    if not name:
        return False
    top = top_friend(counts)
    if top is None or top.casefold() != name.casefold():
        return False
    return notify("friend", f"{name} is online",
                  "Say hi in the Friends tab.", cfg=cfg)


def update_available(new_version: str, *, cfg: dict | None = None) -> bool:
    """A newer Cubeon exists. Called at most once per version (see the
    caller's `state` marker), and again throttled here."""
    try:
        version = str(new_version or "").strip()
    except Exception:
        version = ""
    if not version:
        return False
    return notify("update", "A new Cubeon is available",
                  f"Version {version} is ready to download.", cfg=cfg)
