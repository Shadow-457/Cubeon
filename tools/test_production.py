"""Tests for the production-pass modules: cubeon/watchdog.py (orphaned-game
tracking). Hermetic: network calls are faked, the watchdog uses a real
short-lived subprocess."""
import json
import os
import subprocess
import sys
import threading
import time
import importlib.util
from unittest.mock import patch
from contextlib import ExitStack

import _sandbox_home
_sandbox_home.isolate()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubeon import watchdog  # noqa: E402

_passed = 0
_failed = 0


def check(cond, msg):
    global _passed, _failed
    if cond:
        _passed += 1
    else:
        _failed += 1
        print(f"  FAIL: {msg}")


# --------------------------------------------------------------- watchdog ---
watchdog.clear()
check(watchdog.stale_session() is None, "no record -> no stale session")

# A live process (python sleeping) counts as a stale leftover.
p = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(5)"])
watchdog.register(p.pid, "1.20.1")
stale = watchdog.stale_session()
check(stale is not None and stale["pid"] == p.pid and stale["version"] == "1.20.1",
      "live recorded pid is reported as a stale session")

# Terminate ends it and the record can be cleared.
check(watchdog.terminate(p.pid) in (True, False), "terminate returns a bool")
p.wait(timeout=5)
watchdog.clear()

# A dead pid is cleaned up silently, not reported.
p2 = subprocess.Popen([sys.executable, "-c", "pass"])
p2.wait(timeout=5)
watchdog.register(p2.pid, "1.20.1")
check(watchdog.stale_session() is None, "dead pid is not a stale session")
check(not os.path.exists(watchdog.RECORD_PATH), "dead-pid record is cleaned up")

# Corrupt record never raises.
with open(watchdog.RECORD_PATH, "w") as fh:
    fh.write("{not json")
check(watchdog.stale_session() is None, "corrupt record is ignored, not fatal")

check(watchdog.effective_username("Configured") == "Configured", "idle uses committed config")
for invalid in (None, 12, "ab", "a" * 17, "White Space", "Valid\n", "Éclair"):
    check(watchdog.effective_username(invalid) == "", "invalid config produces empty username")


def fresh_watchdog():
    spec = importlib.util.spec_from_file_location("cubeon._watchdog_restart", watchdog.__file__)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    module.RECORD_PATH = watchdog.RECORD_PATH
    return module


live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
try:
    first = watchdog.register(live.pid, "1.20.1", "LaunchName", process=live)
    check(watchdog.effective_username("EditedName") == "LaunchName", "live launch wins over renamed config")
    check(not watchdog.clear(first), "cannot clear a still-live session")
    with open(watchdog.RECORD_PATH, encoding="utf-8") as fh:
        persisted = json.load(fh)
    check(persisted["session_id"] == first and persisted["identity"]
          and persisted["username"] == "LaunchName", "identity and username persisted together")
    recovered = fresh_watchdog()
    recovered_names = []
    recovered._reconcile_username = lambda: recovered_names.append(recovered.effective_username("EditedName"))
    check(recovered.effective_username("EditedName") == "LaunchName", "restart recovers live launch name")
    forged = fresh_watchdog()
    with patch.object(forged, "_process_identity", return_value={"created": -1}):
        check(forged.effective_username("EditedName") == "EditedName", "reused PID cannot recover old username")
    watchdog._persist()
    newer = watchdog.register(live.pid, "1.21.1", "NewLaunch", process=live)
    check(newer != first and watchdog.effective_username("EditedName") == "NewLaunch",
          "session identity distinguishes even equal PIDs")
    check(not watchdog.clear(first) and watchdog.effective_username("EditedName") == "NewLaunch",
          "stale exit cannot clear a newer live launch")
    with patch.object(watchdog, "write_json", side_effect=OSError("read-only")):
        third = watchdog.register(live.pid, "1.21.1", "MemoryName", process=live)
        check(third and watchdog.effective_username("EditedName") == "MemoryName",
              "metadata write failure preserves in-process launch name")
    with patch.object(watchdog.psutil, "Process") as reused:
        reused.return_value.create_time.return_value = -1
        check(not watchdog.terminate(live.pid, newer) and live.poll() is None
              and not reused.return_value.terminate.called,
              "termination rejects reused process identity")
    live.terminate()
    live.wait(timeout=5)
    check(watchdog.clear(third), "matching exited session clears")
    check(watchdog.effective_username("EditedName") == "EditedName", "exit restores latest committed name")
    deadline = time.monotonic() + 3
    while not recovered_names and time.monotonic() < deadline:
        time.sleep(0.05)
    check(recovered_names == ["EditedName"], "recovered process exit reconciles without another launch")
finally:
    if live.poll() is None:
        live.terminate()
        live.wait(timeout=5)
    watchdog.clear()

probe = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
probe_id = watchdog.register(probe.pid, "1.20.1", "ProbeName", process=probe)
probe.terminate()
probe.wait(timeout=5)
check(watchdog.effective_username("Committed") == "Committed", "username read observes completed process")
check(watchdog.clear(probe_id), "username read cannot consume matching exit reconciliation")
check(watchdog.effective_username("Committed") == "Committed", "cleared session restores committed name")

for value in ([], 42, {"pid": os.getpid(), "username": "LegacyName"}):
    watchdog.write_json(watchdog.RECORD_PATH, value)
    check(fresh_watchdog().effective_username("Configured") == "Configured",
          "malformed or PID-only legacy record never pins a name")

from cubeon import launch, content, doctor, milestones
from cubeon.friends_service import FriendsService


class GameProcess:
    def __init__(self, pid):
        self.pid = pid
        self.returncode = None
        self.exited = threading.Event()

    def poll(self):
        return self.returncode

    def wait(self):
        self.exited.wait(5)
        return self.returncode

    def finish(self):
        self.returncode = 0
        self.exited.set()


with ExitStack() as stack:
    for target, attr, value in (
            (launch, "sync_mods_to_game", lambda *a: None),
            (content, "sync_content_to_game", lambda *a: None),
            (doctor, "run_doctor", lambda *a, **kw: {}),
            (milestones, "begin_play_session", lambda *a: None),
            (launch, "build_launch_command", lambda *a: ["java", "--username", a[1]])):
        stack.enter_context(patch.object(target, attr, value))
    published = []
    stack.enter_context(patch.object(FriendsService, "reconcile_username_active",
                                   lambda: published.append(watchdog.effective_username("Committed")),
                                   create=True))
    proc1, proc2 = GameProcess(987654), GameProcess(987655)
    args = ("1.20.1", "FirstName", 1024, 800, 600, None)
    done1, done2 = threading.Event(), threading.Event()
    with patch.object(launch.subprocess, "Popen", return_value=proc1):
        result = launch.launch_game(*args, mc_version="1.20.1", loader="vanilla",
                                    on_exit=lambda code: done1.set())
    check(result is proc1 and published[-1] == "FirstName", "common launch captures spawned username")
    with patch.object(launch.subprocess, "Popen", side_effect=OSError("spawn failed")):
        try:
            launch.launch_game(*args, mc_version="1.20.1", loader="vanilla")
        except OSError:
            pass
        else:
            check(False, "spawn failure raises")
    check(watchdog.effective_username("Committed") == "FirstName" and len(published) == 1,
          "failed spawn leaves prior session and publication untouched")
    with patch.object(launch.subprocess, "Popen", return_value=proc2) as spawn:
        launch.launch_game("1.20.1", "SecondName", 1024, 800, 600, None,
                           mc_version="1.20.1", loader="vanilla",
                           server_address="127.0.0.1", server_port=25565,
                           on_exit=lambda code, lines: done2.set())
        check(spawn.call_args.args[0][-4:] == ["--server", "127.0.0.1", "--port", "25565"],
              "join launch shares captured-name lifecycle")
    proc1.finish()
    check(done1.wait(3) and watchdog.effective_username("Committed") == "SecondName",
          "older concurrent exit does not overwrite newer session")
    check(published[-1] == "SecondName", "stale exit reconciliation reads current effective name")
    proc2.finish()
    check(done2.wait(3) and published[-1] == "Committed", "latest matching exit publishes committed username")
    proc3 = GameProcess(987656)
    done3 = threading.Event()
    with patch.object(launch.subprocess, "Popen", return_value=proc3), \
            patch.object(FriendsService, "reconcile_username_active", side_effect=RuntimeError("offline")):
        check(launch.launch_game(*args, mc_version="1.20.1", loader="vanilla",
                                 on_exit=lambda code: done3.set()) is proc3,
              "publication failure never blocks successful launch")
        proc3.finish()
        check(done3.wait(3), "publication failure never skips exit callback")

older, latest = GameProcess(987657), GameProcess(987658)
older_id = watchdog.register(older.pid, "1.20.1", "OlderName", process=older)
latest_id = watchdog.register(latest.pid, "1.20.1", "LatestName", process=latest)
latest.finish()
check(watchdog.clear(latest_id) and watchdog.effective_username("Committed") == "OlderName",
      "latest exit restores older still-live session rather than edited config")
check(not watchdog.clear(latest_id) and watchdog.effective_username("Committed") == "OlderName",
      "duplicate exit callback leaves remaining session intact")
older.finish()
watchdog.clear(older_id)
invalid = GameProcess(987659)
invalid_id = watchdog.register(invalid.pid, "1.20.1", "Bad Name", process=invalid)
check(watchdog.effective_username("Committed") == "", "invalid live username never falls back to edited config")
invalid.finish()
watchdog.clear(invalid_id)

from cubeon import atomicio, config

older_entered = threading.Event()
release_older = threading.Event()
newer_started = threading.Event()
newer_entered = threading.Event()
newer_done = threading.Event()
write_order = []
write_errors = []
real_write_json = atomicio.write_json


def paused_write(path, payload, **kwargs):
    if payload["generation"] == 1:
        older_entered.set()
        if not release_older.wait(5):
            raise TimeoutError("older writer was not released")
    else:
        newer_entered.set()
    real_write_json(path, payload, **kwargs)
    write_order.append(payload["generation"])


def save_generation(generation):
    if generation == 2:
        newer_started.set()
    try:
        config.save_config({"generation": generation})
    except Exception as ex:
        write_errors.append(ex)
    finally:
        if generation == 2:
            newer_done.set()


with patch.object(atomicio, "write_json", paused_write):
    older = threading.Thread(target=save_generation, args=(1,), daemon=True)
    newer = threading.Thread(target=save_generation, args=(2,), daemon=True)
    try:
        older.start()
        check(older_entered.wait(2), "older config writer is in flight")
        newer.start()
        check(newer_started.wait(2), "newer config save starts while older is in flight")
        newer_done.wait(0.2)
        check(not newer_entered.is_set(), "newer config writer waits for older save")
    finally:
        release_older.set()
        older.join(5)
        newer.join(5)
check(not older.is_alive() and not newer.is_alive() and not write_errors,
      "both config saves finish without errors")
check(write_order == [1, 2], "config writers finish in original order")
check(config.load_config().get("generation") == 2, "newest config payload wins")
try:
    config.save_config({"generation": object()})
except TypeError:
    pass
config.save_config({"generation": 3})
check(config.load_config().get("generation") == 3, "failed save releases config lock")
cancelled = threading.Timer(0.4, config.save_config, args=({"generation": 4},))
latest = threading.Timer(0.4, config.save_config, args=({"generation": 5},))
cancelled.start()
cancelled.cancel()
latest.start()
cancelled.join(2)
latest.join(2)
check(not latest.is_alive() and config.load_config().get("generation") == 5,
      "400ms timer cancel/restart pattern saves latest config")

print(f"{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
