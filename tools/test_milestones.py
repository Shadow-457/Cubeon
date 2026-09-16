#!/usr/bin/env python3
"""
Tests for cubeon/milestones.py (the activity-stats store feeding the Stats
tab) - run with:

    python tools/test_milestones.py

No network, no real HOME: the sandbox points HOME (and thus
~/.cubeon_launcher) at a temp dir.

Contracts worth keeping pinned here:
  * the counters never go backwards (friend count is a high-water mark),
  * playtime is clamped (a broken clock can't mint hours),
  * a persisted play session survives a launcher restart (the game
    deliberately outlives the launcher) and is credited exactly once -
    the startup reconciler and the on_exit watcher can't both win.
"""
import json
import os
import sys
import tempfile
import time

# --- Sandbox: temp HOME before importing anything of ours --------------------
_tmp = tempfile.mkdtemp(prefix="cubeon-milestones-test-")
os.environ["HOME"] = _tmp
os.environ["USERPROFILE"] = _tmp

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"  [{detail}]" if detail else ""))


from cubeon import milestones

MILESTONES_PATH = os.path.join(_tmp, ".cubeon_launcher", "milestones.json")


def fresh_state(**over):
    milestones._state = {
        "first_seen_at": time.time(),
        "seconds_played": 0,
        "sessions_hosted": 0,
        "friends_count_high": 0,
    }
    milestones._state.update(over)
    milestones.save_state()
    return milestones._state


print("1. state file lifecycle")
fresh_state()
check("save_state wrote the seeded file", os.path.isfile(MILESTONES_PATH))
on_disk = json.load(open(MILESTONES_PATH, encoding="utf-8"))
check("on-disk state carries the counters", on_disk["seconds_played"] == 0.0
      and "friends_count_high" in on_disk)
loaded = milestones.load_state()
check("load_state returns the cached singleton", loaded is milestones._state)
check("atomic write left no .tmp behind",
      not os.path.exists(MILESTONES_PATH + ".tmp"))

print("\n2. counters")
milestones.add_play_seconds(3600)
check("playtime accumulates", milestones.load_state()["seconds_played"] == 3600)
milestones.add_play_seconds(999 * 3600)
st = milestones.load_state()
check("one absurd session clamped to 14 days",
      st["seconds_played"] == 3600 + 86400.0 * 14, str(st["seconds_played"]))
milestones.add_play_seconds(-5)
check("negative playtime ignored",
      milestones.load_state()["seconds_played"] == 3600 + 86400.0 * 14)
milestones.note_friends_count(3)
check("friend count records",
      milestones.load_state()["friends_count_high"] == 3)
milestones.note_friends_count(1)
check("friend count is high-water (can't go backwards)",
      milestones.load_state()["friends_count_high"] == 3)
milestones.note_friends_count(0)
milestones.note_friends_count("many")
check("nonsense roster counts ignored",
      milestones.load_state()["friends_count_high"] == 3)
milestones.add_hosted_session()
check("hosted session counts",
      milestones.load_state()["sessions_hosted"] == 1)

print("\n3. play session: crash survival + double-credit guard")
# game.log is the credit bound; the launcher truncates it per launch, the
# game writes it. Seed it empty - tests below stamp its mtime.
os.makedirs(os.path.dirname(milestones._GAME_LOG_PATH), exist_ok=True)
open(milestones._GAME_LOG_PATH, "wb").close()
# No game-log evidence -> nothing credited (under-credit, never mint hours).
milestones.begin_play_session(pid=4242, started_at=100.0)
check("session record persisted", os.path.isfile(milestones.PLAY_SESSION_PATH))
if os.path.exists(milestones._GAME_LOG_PATH):
    os.unlink(milestones._GAME_LOG_PATH)  # no evidence at all this time
credited = milestones.end_play_session(now=100.0 + 10 * 3600)
check("no log evidence -> zero credit", credited == 0.0)
check("session record cleared after credit",
      not os.path.isfile(milestones.PLAY_SESSION_PATH))
check("end_play_session is idempotent",
      milestones.end_play_session(now=100.0 + 10 * 3600) == 0.0)

# Log mtime before the session start -> no credit either.
open(milestones._GAME_LOG_PATH, "wb").close()  # fresh log again
milestones.begin_play_session(pid=4242, started_at=5000.0)
os.utime(milestones._GAME_LOG_PATH, (50.0, 50.0))
check("stale log can't credit",
      milestones.end_play_session(now=5000.0 + 10 * 3600) == 0.0)

# The happy path: log written after the start, bounded by 'now'.
milestones.begin_play_session(pid=4242, started_at=100.0)
os.utime(milestones._GAME_LOG_PATH, (700.0, 700.0))
before = milestones.load_state()["seconds_played"]
credited = milestones.end_play_session(now=1000.0)
check("log-bounded playtime credited",
      abs(credited - 600.0) < 0.001, str(credited))
check("credited time landed in the store",
      abs(milestones.load_state()["seconds_played"] - before - 600.0) < 0.001)

# Reconciler: a session orphaned by a dead launcher gets credited.
milestones.begin_play_session(pid=4242, started_at=100.0)
os.utime(milestones._GAME_LOG_PATH, (700.0, 700.0))
before = milestones.load_state()["seconds_played"]
milestones.reconcile_play_session(pid_alive=lambda pid: False)
check("reconciler credits an orphaned session",
      abs(milestones.load_state()["seconds_played"] - before - 600.0) < 0.001)
check("reconciler cleared the record",
      not os.path.exists(milestones.PLAY_SESSION_PATH))

# Reconciler with the game STILL running: record must survive (the polling
# watcher credits it later) and nothing may be credited yet.
milestones.begin_play_session(pid=4242, started_at=1000.0)
milestones.reconcile_play_session(pid_alive=lambda pid: True)
check("live game keeps its session record",
      os.path.exists(milestones.PLAY_SESSION_PATH))
_live_before = milestones.load_state()["seconds_played"]
check("live game not credited yet",
      milestones.load_state()["seconds_played"] == _live_before)
if os.path.exists(milestones.PLAY_SESSION_PATH):
    os.unlink(milestones.PLAY_SESSION_PATH)


print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
