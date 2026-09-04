#!/usr/bin/env python3
"""
Tests for detecting a Minecraft server Cubeon lost track of.

THE BUG THIS EXISTS FOR - captured from the owner's machine, 2026-08-22.

Cubeon's Server tab said **"Stopped"** and offered a Start button, but three
consecutive start attempts died in Minecraft's own bootstrap:

    [09:40:30] [ServerMain/ERROR]: Failed to start the minecraft server
    net.minecraft.util.DirectoryLock$LockException:
      .../servers/1.21.11/./world/session.lock: already locked
      (possibly by other Minecraft instance?)

Cause: `start_server()` detaches the server with `start_new_session=True` (so
closing the terminal can't kill it), and `_server_processes` is an in-memory
dict. Restart Cubeon and a *running* server becomes invisible to it -
`is_server_running()` says no, Start is offered, and the world lock rejects it
every time. The user's only clue was a Java stack trace.

WHY THE LOCK MECHANISM MATTERS, AND WHY THIS TEST USES A REAL JVM

Java's `FileChannel.lock()` takes a POSIX **record** lock (fcntl), which on Linux
is a *completely separate mechanism* from `flock()`. Verified here by locking a
file from a real JVM and probing it both ways:

    flock() -> ACQUIRED   (reports the file as free while the JVM holds it)
    fcntl   -> BLOCKED    (correct)

A first version of this detection used `flock` and therefore reported every
locked world as free - it would have shipped as "the fix doesn't work". So the
test locks a file with an actual `java` process rather than simulating it: a
mock would have happily agreed with the broken implementation.

Skips (rather than fails) when no JDK is present, since the lock semantics being
tested are the JVM's, not Cubeon's.

Run: python3 tools/test_orphan_server.py
"""
import os
import shutil
import struct
import subprocess
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

passed = 0
failed = 0
skipped = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


def skip(label, why):
    global skipped
    skipped += 1
    print(f"  skip {label} ({why})")


# --- sandbox: redirect HOME to a scratch dir before cubeon binds its paths at
# import time, so tests never read/write the developer's real game dir/store.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import server  # noqa: E402

scratch = tempfile.mkdtemp(prefix="cubeon-orphan-")
_real_servers_dir = server.SERVERS_DIR
server.SERVERS_DIR = scratch

VERSION = "1.21.11"
world_dir = os.path.join(scratch, VERSION, "world")
os.makedirs(world_dir, exist_ok=True)
lock_path = os.path.join(world_dir, "session.lock")

print("\n1. an unlocked world is free, and never blocks the user")

check("no session.lock at all -> no holder",
      server.world_lock_holder(VERSION) is None)

# Minecraft writes a snowman (U+2603) into session.lock. Present-but-unlocked is
# the normal state after a clean shutdown, and must NOT read as running -
# otherwise Start would refuse forever after the first session.
with open(lock_path, "wb") as handle:
    handle.write("☃".encode("utf-8"))
check("an existing but unlocked session.lock -> no holder",
      server.world_lock_holder(VERSION) is None,
      "a clean shutdown would leave Start permanently disabled")
check("...so is_server_running() is False", server.is_server_running(VERSION) is False)
check("...and nothing is reported as orphaned",
      server.is_server_orphaned(VERSION) is None)

print("\n2. a world locked by a REAL JVM is detected")

javac = shutil.which("javac")
java = shutil.which("java")
jvm = None

if not (javac and java):
    skip("a live JVM lock is detected", "no JDK on this machine")
    skip("...with the JVM's real PID", "no JDK on this machine")
    skip("...and is_server_running() reports True", "no JDK on this machine")
    skip("...and it is reported as ORPHANED, not as tracked", "no JDK on this machine")
    skip("start_server refuses with an actionable message", "no JDK on this machine")
    skip("...naming the leftover process", "no JDK on this machine")
    skip("the lock is released when the JVM exits", "no JDK on this machine")
else:
    # Locks exactly the way Minecraft does: FileChannel.lock() on session.lock.
    src = os.path.join(scratch, "Holder.java")
    with open(src, "w") as handle:
        handle.write(
            "import java.nio.channels.*; import java.nio.file.*;\n"
            "public class Holder { public static void main(String[] a) throws Exception {\n"
            "  FileChannel ch = FileChannel.open(Paths.get(a[0]),\n"
            "      StandardOpenOption.CREATE, StandardOpenOption.WRITE);\n"
            "  FileLock l = ch.tryLock();\n"
            "  System.out.println(ProcessHandle.current().pid());\n"
            "  System.out.flush();\n"
            "  Thread.sleep(120000); } }\n")
    compiled = subprocess.run([javac, "-d", scratch, src],
                              capture_output=True, text=True)
    if compiled.returncode != 0:
        skip("a live JVM lock is detected", "javac failed")
    else:
        jvm = subprocess.Popen([java, "-cp", scratch, "Holder", lock_path],
                               stdout=subprocess.PIPE, text=True)
        jvm_pid = None
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            line = jvm.stdout.readline()
            if line.strip().isdigit():
                jvm_pid = int(line.strip())
                break
        # The JVM prints its PID only after tryLock() returned, so reaching here
        # means the lock is genuinely held - no sleep-and-hope.
        if jvm_pid is None:
            skip("a live JVM lock is detected", "the JVM never reported its PID")
        else:
            found = server.world_lock_holder(VERSION)
            check("a live JVM lock is detected", found is not None,
                  "flock-based detection returns None here - this is the bug")
            check("...with the JVM's real PID", found == jvm_pid,
                  f"holder={found} jvm={jvm_pid}")
            check("...and is_server_running() reports True",
                  server.is_server_running(VERSION) is True,
                  "this False is what made the UI say 'Stopped'")
            check("...and it is reported as ORPHANED, not as tracked",
                  server.is_server_orphaned(VERSION) == jvm_pid)

            # The real payoff: a clear error instead of a Java stack trace.
            os.makedirs(os.path.join(scratch, VERSION), exist_ok=True)
            try:
                server.start_server(VERSION, 1024)
                check("start_server refuses with an actionable message", False,
                      "it started anyway - the world lock would have killed it")
                check("...naming the leftover process", False)
            except RuntimeError as ex:
                message = str(ex)
                check("start_server refuses with an actionable message",
                      "leftover" in message.lower() or "earlier" in message.lower(),
                      message)
                check("...naming the leftover process", str(jvm_pid) in message,
                      message)

            jvm.terminate()
            jvm.wait(timeout=30)
            # The lock is the kernel's, so it goes the moment the process does.
            released = False
            for _ in range(40):
                if server.world_lock_holder(VERSION) is None:
                    released = True
                    break
                time.sleep(0.25)
            check("the lock is released when the JVM exits", released,
                  "a stale lock would leave Start disabled forever")
            jvm = None

print("\n3. stop_orphaned_server never guesses at what to kill")

_real_kill = os.kill
signals = []


def fake_kill(pid, sig):
    signals.append((pid, sig))


try:
    os.kill = fake_kill
    server.world_lock_holder = lambda v: None
    check("nothing to stop -> False, and no signals sent",
          server.stop_orphaned_server(VERSION) is False and not signals,
          str(signals))

    # A holder that goes away after SIGTERM: the clean path.
    calls = {"n": 0}

    def dying(version_id):
        calls["n"] += 1
        return 4242 if calls["n"] <= 1 else None

    server.world_lock_holder = dying
    signals.clear()
    check("a leftover server is stopped", server.stop_orphaned_server(VERSION) is True)
    import signal as _signal
    check("...with SIGTERM first, so the world saves cleanly",
          signals and signals[0] == (4242, _signal.SIGTERM), str(signals))
    check("...and only the PID the lock reported - never a pkill by name",
          all(pid == 4242 for pid, _ in signals), str(signals))
    check("...and it is not SIGKILLed once it exits cleanly",
          not any(sig == _signal.SIGKILL for _, sig in signals), str(signals))
finally:
    os.kill = _real_kill
    server.world_lock_holder = server.__dict__["world_lock_holder"]

if jvm is not None:
    jvm.terminate()
server.SERVERS_DIR = _real_servers_dir
shutil.rmtree(scratch, ignore_errors=True)

print(f"\n{passed} passed, {failed} failed, {skipped} skipped")
sys.exit(1 if failed else 0)
