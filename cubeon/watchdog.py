"""
Game process watchdog.

The gap this closes: launch_game() spawns Minecraft and reports "Running",
but if the launcher window is closed mid-session (or the launcher crashes),
nothing remembers the game was ours - a crashed-or-orphaned java process
could linger forever, holding locks on the mods folder while the user
reinstalls everything trying to fix a "corrupt" install.

The contract is simple and crash-safe:
  - register() writes {pid, version, started} to ~/.cubeon_launcher BEFORE
    the game is considered running;
  - clear() removes it when the process is confirmed dead (on_exit);
  - stale_session() at next startup reads the record: if the pid is gone,
    the previous session ended fine and the record is just litter (cleared
    silently); if the pid is ALIVE, it's an orphan worth telling the user
    about, and terminate() can end it.

Every step tolerates a missing/unreadable/corrupt record - this is a
diagnostic aid, never a launch blocker.
"""
import json
import logging
import os
import time

from .paths import CUBEON_HOME

log = logging.getLogger(__name__)

RECORD_PATH = os.path.join(CUBEON_HOME, "running_game.json")


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists, owned by someone else - alive as far as we care
    except OSError:
        return False


def register(pid: int, version_id: str = "") -> None:
    """Record a running game. Never raises."""
    try:
        os.makedirs(CUBEON_HOME, exist_ok=True)
        with open(RECORD_PATH, "w", encoding="utf-8") as fh:
            json.dump({"pid": int(pid), "version": version_id,
                       "started": time.time()}, fh)
    except (OSError, ValueError, TypeError) as ex:
        log.warning("watchdog: couldn't record game pid %s (%s)", pid,
                    ex.__class__.__name__)


def clear() -> None:
    """Forget the recorded game (normal exit or confirmed death)."""
    try:
        os.unlink(RECORD_PATH)
    except OSError:
        pass


def stale_session() -> dict | None:
    """{'pid', 'version', 'started'} when a recorded game is STILL alive,
    else None (and the record is cleaned up). The launcher calls this once
    at startup."""
    try:
        with open(RECORD_PATH, "r", encoding="utf-8") as fh:
            rec = json.load(fh)
        pid = int(rec.get("pid", 0))
    except (OSError, ValueError, TypeError):
        return None
    if pid <= 0 or not _pid_alive(pid):
        clear()
        return None
    # A pid being alive isn't proof it's still our Minecraft (pids recycle),
    # but within a normal reboot cycle it's a strong signal, and the worst
    # case of a wrong guess is one extra "close it?" prompt.
    rec["pid"] = pid
    return rec


def terminate(pid: int) -> bool:
    """Politely end an orphaned game. Returns whether we believe it worked."""
    import signal
    # SIGKILL doesn't exist on Windows; there os.kill(pid, SIGTERM) already
    # terminates unconditionally, so escalating further is meaningless.
    signals = [signal.SIGTERM]
    if hasattr(signal, "SIGKILL"):
        signals.append(signal.SIGKILL)
    for sig in signals:
        try:
            os.kill(pid, sig)
        except OSError:
            return not _pid_alive(pid)
        for _ in range(20):  # up to 2s for SIGTERM to land
            if not _pid_alive(pid):
                return True
            time.sleep(0.1)
    return not _pid_alive(pid)
