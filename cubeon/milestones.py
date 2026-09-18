"""
Activity stats store: playtime, hosted sessions, friends high-water mark.

HISTORY: this module used to also run the hat-milestone engine (unlock
evaluation, the KV unlock ledger synced to the Worker, wear gating). Hats
were removed entirely (2026-09-16 user request) - the unlock/evaluate/sync
half is gone and the hat catalogue lived in the now-deleted cosmetics.py.
What remains is the part the Stats tab actually reads.

WHY A SEPARATE MODULE AND FILE
Counters like "seconds played" update constantly; config.json is rewritten
wholesale on every settings change by whichever thread holds no lock, so
parking a hot counter there would amplify both. skin_net.json and
window_geometry.json already established the precedent: hot or
self-contained state lives in its own tiny file under ~/.cubeon_launcher/.
This one is milestones.json (kept for filename compatibility).
"""
import json
import os
import threading
import time

from .paths import CUBEON_HOME
from .atomicio import write_json

MILESTONES_PATH = os.path.join(CUBEON_HOME, "milestones.json")

# In-flight play session, persisted so a launcher crash/re-exec (the game
# deliberately survives it - see launch.py start_new_session) can still credit
# the time when the launcher comes back. Without this, playtime was only ever
# recorded by the in-process game watcher: a GPU-crash re-exec or a full quit
# killed that watcher, the game ran on unobserved, and "Time in game" stayed 0.
PLAY_SESSION_PATH = os.path.join(CUBEON_HOME, "play_session.json")
_GAME_LOG_PATH = os.path.join(CUBEON_HOME, "game.log")

_lock = threading.Lock()
# Serializes play-session read/credit/clear so on_exit and the startup
# reconciler can't both credit the same record (double-counting playtime).
# Distinct from _lock, which add_play_seconds takes internally.
_session_lock = threading.Lock()
_state = None  # cached dict once loaded


def _defaults() -> dict:
    return {
        "first_seen_at": time.time(),
        "seconds_played": 0,
        "sessions_hosted": 0,
        "friends_count_high": 0,
    }


def load_state() -> dict:
    """Loads (and caches) the stats state, seeding a new file on first run."""
    global _state
    with _lock:
        if _state is not None:
            return _state
        data = None
        try:
            with open(MILESTONES_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError, UnicodeDecodeError):
            data = None
        base = _defaults()
        if isinstance(data, dict):
            for k in base:
                if k in data:
                    base[k] = data[k]
        _state = base
        if data is None:
            _save_state_locked()
        return _state


def save_state() -> None:
    """Persists the cached state. Called by every mutator; cheap (a few
    hundred bytes) and safe to call from any thread (serialized by _lock)."""
    with _lock:
        _save_state_locked()


def _save_state_locked() -> None:
    """Writer half for callers that already hold _lock (load_state's seed
    path) - _lock is NOT reentrant, so save_state() would self-deadlock."""
    if _state is None:
        return
    tmp = MILESTONES_PATH + ".tmp"
    try:
        os.makedirs(CUBEON_HOME, exist_ok=True)
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_state, f, indent=2)
        os.replace(tmp, MILESTONES_PATH)  # atomic, unlike config.json
    except OSError:
        pass


def add_play_seconds(seconds: float) -> None:
    """Credits in-game time. Clamps negatives (a broken clock must not be
    able to subtract playtime) and huge single credits (an absurd record
    must not dominate the stat)."""
    try:
        seconds = float(seconds)
    except (TypeError, ValueError):
        return
    if not (seconds > 0):
        return
    seconds = min(seconds, 86400.0 * 14)  # two weeks of one 'session' is a bug
    st = load_state()
    with _lock:
        st["seconds_played"] += seconds
        _save_state_locked()


# ----------------------------------------------------------- play session

def _read_play_session() -> dict | None:
    try:
        with open(PLAY_SESSION_PATH, "r", encoding="utf-8") as f:
            rec = json.load(f)
        if isinstance(rec, dict) and isinstance(rec.get("started"), (int, float)):
            return rec
    except (OSError, json.JSONDecodeError, UnicodeDecodeError):
        pass
    return None


def _write_play_session(rec: dict) -> None:
    try:
        # An empty sessions map means "no session record": delete the file
        # instead of leaving an empty husk, so "was the record cleared?"
        # (watchdog, tests, diagnostics) reads the filesystem truthfully.
        sessions = rec.get("sessions")
        if isinstance(sessions, dict) and not sessions:
            try:
                os.unlink(PLAY_SESSION_PATH)
            except OSError:
                pass
            return
        write_json(PLAY_SESSION_PATH, rec)
    except OSError:
        pass


def _read_play_sessions():
    try:
        with open(PLAY_SESSION_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if isinstance(data, dict):
            if isinstance(data.get("sessions"), dict):
                return data["sessions"]
            if isinstance(data.get("started"), (int, float)):
                return {"legacy": data}
    except (OSError, ValueError):
        pass
    return {}


def begin_play_session(pid: int, started_at: float | None = None,
                       session_id: str | None = None) -> None:
    with _session_lock:
        records = _read_play_sessions()
        records[session_id or "legacy"] = {"started": float(started_at or time.time()),
                                           "pid": int(pid or 0), "session_id": session_id}
        _write_play_session({"sessions": records})


def _play_session_elapsed(rec: dict, now: float) -> float:
    """Seconds to credit for `rec`, bounded by the game log's last write.

    game.log is truncated per launch and only the game writes it, so its mtime
    is a good stand-in for when the game stopped. That bound is what keeps a
    launcher left off overnight from crediting idle hours as playtime. If the
    log is missing or predates the session (instant crash / unwritable HOME),
    credit nothing rather than the entire idle gap - under-crediting is
    preferable to minting hours from idle time."""
    end = rec["started"]  # no log evidence -> no credit
    try:
        session_id = rec.get("session_id")
        log_path = os.path.join(CUBEON_HOME, f"game-{session_id}.log") if session_id else _GAME_LOG_PATH
        mtime = os.path.getmtime(log_path)
        if mtime > rec["started"]:
            end = min(now, mtime)
    except OSError:
        pass
    return max(0.0, end - rec["started"])


def end_play_session(now: float | None = None, session_id: str | None = None) -> float:
    """Credit and clear the on-disk play session. Idempotent: the first caller
    wins, the second finds no record and credits nothing. Returns seconds."""
    with _session_lock:
        records = _read_play_sessions()
        rec = records.pop(session_id or "legacy", None)
        if rec is None:
            return 0.0
        _write_play_session({"sessions": records})
        seconds = _play_session_elapsed(rec, time.time() if now is None else now)
    if seconds > 0:
        add_play_seconds(seconds)
    return seconds


def reconcile_play_session(pid_alive=None) -> None:
    """Called once at launcher startup. Credits a session left behind by a
    launcher that crashed or was re-exec'd while the game ran, and - if that
    game is somehow STILL running - watches its pid so the rest is credited
    when it finally exits. Never raises."""
    try:
        with _session_lock:
            records = _read_play_sessions()
        if pid_alive is None:
            from .watchdog import _pid_alive as pid_alive

        def _poll(rec, session_id):
            while True:
                time.sleep(30.0)
                try:
                    if not pid_alive(rec["pid"]):
                        break
                except Exception:
                    break
            end_play_session(session_id=session_id)

        for session_id, rec in records.items():
            alive = False
            if rec["pid"] > 0:
                try:
                    alive = bool(pid_alive(rec["pid"]))
                except Exception:
                    pass
            if not alive:
                end_play_session(session_id=session_id)
            else:
                threading.Thread(target=_poll, args=(rec, session_id), daemon=True,
                                 name="cubeon-playtime-reconcile").start()
    except Exception:
        pass  # best-effort - never block startup on it


def add_hosted_session() -> None:
    """A world hosted for friends (P2P) or a server started on the Server
    tab counted once per (start -> clean exit) cycle."""
    st = load_state()
    with _lock:
        st["sessions_hosted"] += 1
        _save_state_locked()


def note_friends_count(count: int) -> None:
    """Records the high-water mark of the roster size (high-water, not
    current, so unfriending doesn't claw back the record)."""
    if not isinstance(count, int) or count <= 0:
        return
    st = load_state()
    with _lock:
        if count > st["friends_count_high"]:
            st["friends_count_high"] = count
            _save_state_locked()
