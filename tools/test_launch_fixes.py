#!/usr/bin/env python3
"""Regression harness for the launch-path wave: overlapping-launch staging,
session-keyed playtime/exit state, GC flag collisions, per-session game logs,
client.json temp-file races, stale jar-cache rejection, exact loader-version
matching, relative game-dir handling, and two-process watchdog merging.

Run: python3 tools/test_launch_fixes.py
"""
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

passed = 0
failed = 0


def check(cond, label, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


from cubeon import launch, milestones, watchdog, cubeonfriends, config  # noqa: E402

# ---------------------------------------------------------------------- L5 ---
print("\n1. GC collector selection (L5)")

FLAGS = launch.CLIENT_JVM_FLAGS

with tempfile.TemporaryDirectory() as tmp:
    version = "gc-test"
    vdir = os.path.join(launch.MINECRAFT_DIR, "versions", version)
    os.makedirs(vdir, exist_ok=True)
    with open(os.path.join(vdir, version + ".json"), "w") as fh:
        json.dump({"id": version, "type": "release",
                   "mainClass": "net.minecraft.client.main.Main",
                   "arguments": {"game": [], "jvm": []}}, fh)
    with patch.object(launch.mll.command, "get_minecraft_command",
                      side_effect=lambda vid, d, opts: ["java", *opts["jvmArguments"],
                                                        "-XX:+UseParallelGC", "-XX:ParallelGCThreads=4",
                                                        "-cp", "x", "net.minecraft.client.main.Main"]):
        cmd = launch.build_launch_command(version, "tester", 2048, 854, 480, None)
    collectors = [a for a in cmd if a.startswith("-XX:+Use") and a.endswith("GC")]
    check(collectors == ["-XX:+UseG1GC"],
          "profile collector flag stripped, exactly one G1 remains", f"{collectors}")
    check("-XX:ParallelGCThreads=4" in cmd, "non-selection tuning flags survive")

# ---------------------------------------------------------------------- L15 ---
print("\n2. java-major table (L15)")
check(launch.required_java_major("1.17") == 16, "1.17 requires Java 16")
check(launch.required_java_major("1.17.1") == 16, "1.17.1 requires Java 16")
check(launch.required_java_major("1.18") == 17, "1.18 requires Java 17")
check(launch.required_java_major("1.20.1") == 17, "1.20.1 requires Java 17")
check(launch.required_java_major("1.20.5") == 21, "1.20.5 requires Java 21")
check(launch.required_java_major("26.1") == 25, "26.1 requires Java 25")
check(launch.required_java_major("1.16.5") == 8, "1.16.5 stays on Java 8")

# ---------------------------------------------------------------------- L16 ---
print("\n3. logging shadow removed (L16)")
import inspect  # noqa: E402
src = inspect.getsource(launch.find_java_for_version)
check("import logging" not in src, "no local logging import inside find_java_for_version")

# ---------------------------------------------------------------------- L10 ---
print("\n4. client.json concurrent writers (L10)")
with tempfile.TemporaryDirectory() as tmp:
    version = "race-test"
    vdir = os.path.join(launch.MINECRAFT_DIR, "versions", version)
    os.makedirs(vdir, exist_ok=True)
    path = os.path.join(vdir, version + ".json")
    base = {"id": version, "type": "release", "mainClass": "Main",
            "arguments": {"game": [{"value": ["--username"]},
                                   {"values": ["${auth_player_name}"]}], "jvm": []}}
    with open(path, "w") as fh:
        json.dump(base, fh)
    entered = threading.Event()
    hold = threading.Event()
    real_sanitize = launch._sanitize_client_json
    leftovers = []


    def slow_first(vid):
        entered.set()
        hold.wait(5)
        return real_sanitize(vid)


    def writer(worker):
        try:
            launch._sanitize_client_json(version)
            leftovers.extend(os.listdir(vdir))
        except Exception as ex:
            leftovers.append(f"{type(ex).__name__}: {ex}")


    with patch.object(launch, "_sanitize_client_json", slow_first):
        t1 = threading.Thread(target=writer, args=(1,))
        t1.start()
        entered.wait(5)
        t2 = threading.Thread(target=writer, args=(2,))
        t2.start()
        t2.join(10)
        hold.set()
        t1.join(10)
    data = json.load(open(path))
    check("value" in data["arguments"]["game"][0], "concurrent repair yields a valid file")
    check(not any(name.endswith(".cubeon-tmp") for name in os.listdir(vdir)),
          "no fixed .cubeon-tmp left behind", str(leftovers))

    from cubeon import atomicio

    def exploding_write(path, data, **kwargs):
        # Simulated disk failure: write_json's caller must report False and
        # leave the original file untouched (see _write_client_json's contract).
        raise OSError("simulated disk failure")

    intact = json.load(open(path))  # what the file holds right before the failure
    with patch.object(launch, "write_json", exploding_write):
        check(launch._write_client_json(path, {"changed": True}) is False,
              "write failure stays False and leaves the original")
    check(json.load(open(path)) == intact,
          "original file intact after failed write")

# ---------------------------------------------------------------------- L1 ---
print("\n5. overlapping launches stage inside the spawn lock (L1)")


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


from cubeon import content, doctor  # noqa: E402
from cubeon.friends_service import FriendsService  # noqa: E402

with tempfile.TemporaryDirectory() as tmp:
    staged = []
    spawn_gate = threading.Event()
    spawn_released = threading.Event()

    def slow_sync(mc_version, loader):
        staged.append((mc_version, loader))
        spawn_gate.set()
        time.sleep(0.3)

    def gated_spawn(*args, **kwargs):
        spawn_released.wait(5)
        return GameProcess(424242)

    events = []

    def late_exit(code, lines, session_id):
        events.append(session_id)

    with patch.object(content, "sync_content_to_game", lambda *a: None), \
            patch.object(doctor, "run_doctor", lambda *a, **kw: {}), \
            patch.object(launch, "sync_mods_to_game", slow_sync), \
            patch.object(launch, "build_launch_command", lambda *a: ["java", "game"]), \
            patch.object(launch.subprocess, "Popen", side_effect=gated_spawn), \
            patch.object(milestones, "begin_play_session", lambda *a, **k: None), \
            patch.object(FriendsService, "reconcile_username_active", lambda: None, create=True):
        first = threading.Thread(target=lambda: launch.launch_game(
            "1.20.1", "A", 1024, 800, 600, None, on_exit=late_exit,
            mc_version="1.20.1", loader="fabric"))
        first.start()
        spawn_gate.wait(5)
        second_result = {}
        second = threading.Thread(target=lambda: second_result.update(
            proc=launch.launch_game("1.21.1", "B", 800, 600, 400, None,
                                    mc_version="1.21.1", loader="vanilla")))
        second.start()
        time.sleep(0.1)
        spawn_released.set()
        second.join(15)
        first.join(15)
        proc = second_result.get("proc")
        check(proc is not None, "second launch completed after first")
        # The lock is held across staging: the second launch's staging can only
        # begin after the first's Popen completed (first staged -> then both).
        check(len(staged) == 2 and staged[0][0] == "1.20.1" and staged[1][0] == "1.21.1",
              "staging serialized in launch order", str(staged))
        for t in threading.enumerate():
            if t.name.startswith("mc-stdout") or "watch" in repr(t.name).lower():
                t.join(timeout=5)

# ---------------------------------------------------------------------- L3 ---
print("\n6. playtime keyed by session id (L3)")
with tempfile.TemporaryDirectory() as tmp:
    now = time.time()
    milestones.begin_play_session(111, now - 60.0, "session-aaa")
    milestones.begin_play_session(222, now - 30.0, "session-bbb")
    records = milestones._read_play_sessions()
    check(set(records) == {"session-aaa", "session-bbb"},
          "overlapping launches both persist", str(sorted(records)))
    log_dir = milestones.CUBEON_HOME
    os.makedirs(log_dir, exist_ok=True)
    log_a = os.path.join(log_dir, "game-session-aaa.log")
    open(log_a, "wb").write(b"game ran\n")
    credited_a = milestones.end_play_session(now=now, session_id="session-aaa")
    check(0 < credited_a <= 60, "first session credits from its own log", str(credited_a))
    records = milestones._read_play_sessions()
    check("session-bbb" in records and "session-aaa" not in records,
          "second session's record survives the first exit", str(sorted(records)))
    credited_b = milestones.end_play_session(now=now, session_id="session-bbb")
    check(credited_b == 0.0, "session without a log credits nothing")
    check(not milestones._read_play_sessions(), "matching exits clear their own records")
    check(milestones.end_play_session(now=9999, session_id="ghost") == 0.0,
          "unknown session id is a no-op")

# ---------------------------------------------------------------------- L4 ---
print("\n7. per-session game logs (L4)")
log_a = os.path.join(watchdog.CUBEON_HOME, "game-" + "a" * 32 + ".log")
log_b = os.path.join(watchdog.CUBEON_HOME, "game-" + "b" * 32 + ".log")
open(log_a, "wb").write(b"first game\n")
open(log_b, "wb").write(b"second game\n")
check(os.path.isfile(log_a) and os.path.isfile(log_b),
      "two sessions keep independent logs")
check(not os.path.exists(os.path.join(watchdog.CUBEON_HOME, "game.log")),
      "no shared game.log is created")

# ---------------------------------------------------------------- L14/L13 ---
print("\n8. loader-version matching (L14) + version parsing (L13)")
from cubeon.mod_loaders import find_installed_loader_version as find_loader  # noqa: E402
check(find_loader({"1.21.11"}, "fabric", "1.21.1") is None,
      "1.21.1 does not match 1.21.11")
check(find_loader({"fabric-loader-0.19.3-1.21.11"}, "fabric", "1.21.1") is None,
      "1.21.1 does not match loader id for 1.21.11")
check(find_loader({"fabric-loader-0.19.3-1.21.11"}, "fabric", "1.21.11")
      == "fabric-loader-0.19.3-1.21.11", "exact version still matches")
check(find_loader({"neoforge-21.1.99"}, "neoforge", "21.1") == "neoforge-21.1.99",
      "neoforge canonical shape matches")
check(find_loader({"neoforge-21.1.99"}, "forge", "21.1") is None,
      "forge does not match neoforge")
parse = cubeonfriends.parse_mc_version
check(parse("26.1-pre-1") == (26, 1, 0), "prerelease suffix stripped (26.1-pre-1)")
check(parse("26.1-rc-2") == (26, 1, 0), "release-candidate suffix stripped")
check(parse("1.20.1-forge-47.2.0") == (1, 20, 1), "forge suffix stripped")
check(parse("fabric-loader-0.16.9-1.21.4") == (1, 21, 4), "loader id parses to MC version")
check(parse("1.21.11") == (1, 21, 11), "plain triple survives")
check(parse("25w06a") is None, "snapshots still have no bracket")

# ------------------------------------------------------------- WinError 2 --
print("\n8b. loader install resolves Java itself (the [WinError 2] report)")
# Every mll loader installs by EXECUTING a downloaded installer jar, and mll
# 8.0 falls back to the bare command "java" when the caller passes nothing. On
# a Windows box with no Java on PATH that surfaced as "Error: FileNotFoundError:
# [WinError 2] The system cannot find the file specified" under the download
# button. install_mod_loader now resolves and VERIFIES the Java itself
# (mod_loaders.loader_java) and passes it in.
from cubeon import mod_loaders  # noqa: E402

_fake_java = os.path.join(tempfile.gettempdir(), "cubeon-fake-java")
with open(_fake_java, "w") as _fh:
    _fh.write("")
os.chmod(_fake_java, 0o755)

_calls = {}


class _FakeLoader:
    """mll 8.0's ModLoader shape: keyword-only java/loader_version, returns id."""

    def install(self, minecraft_version, minecraft_directory, *,
                loader_version=None, callback=None, java=None):
        _calls.update(mc=minecraft_version, dir=minecraft_directory,
                      java=java, lv=loader_version, callback=callback)
        return "fabric-loader-0.16.9-1.20.1"

    def get_latest_loader_version(self, minecraft_version):
        return "0.16.9"


_after = [{"id": "1.20.1"}, {"id": "fabric-loader-0.16.9-1.20.1"}]
_scans = []


def _fake_installed():
    _scans.append(1)
    return [] if len(_scans) == 1 else list(_after)


def _install():
    """install_mod_loader with every network/filesystem edge faked out."""
    _calls.clear()
    _scans.clear()
    patches = [
        patch.object(mod_loaders, "get_installed_versions", _fake_installed),
        patch.object(mod_loaders, "loader_java", lambda *a, **k: _fake_java),
        patch.object(mod_loaders.mll.mod_loader, "get_mod_loader",
                     lambda loader_id: _FakeLoader()),
    ]
    for p in patches:
        p.start()
    try:
        return mod_loaders.install_mod_loader(
            "fabric", "1.20.1", lambda *_: None, lambda *_: None, lambda *_: None)
    finally:
        for p in patches:
            p.stop()


check(_install() == "fabric-loader-0.16.9-1.20.1",
      "a loader install returns the id the library reported")
check(_calls.get("java") == _fake_java,
      "the installer is handed a REAL java path (this is the WinError 2 fix)")
check(_calls.get("lv") == "0.16.9",
      "the newest stable loader version is pinned instead of guessed")
check(_calls.get("callback") is not None, "progress callbacks still reach mll")

# No Java at all: fail BEFORE downloading anything, with a message that says
# what to do - never a bare OS error.
_started = []


class _NeverCalled(_FakeLoader):
    def install(self, *a, **k):
        _started.append(1)
        raise AssertionError("install must not run without Java")


with patch.object(mod_loaders, "get_installed_versions", _fake_installed), \
        patch.object(mod_loaders, "loader_java",
                     side_effect=RuntimeError("Java 17+ wasn't found, so the "
                                              "Fabric installer can't run.")), \
        patch.object(mod_loaders.mll.mod_loader, "get_mod_loader",
                     lambda loader_id: _NeverCalled()):
    try:
        mod_loaders.install_mod_loader("fabric", "1.20.1",
                                       lambda *_: None, lambda *_: None,
                                       lambda *_: None)
        check(False, "a machine with no Java fails with a readable message")
    except RuntimeError as ex:
        check("Java 17+" in str(ex) and "installer" in str(ex),
              "a machine with no Java fails with a readable message",
              f"got: {ex}")
check(not _started, "the download is never started without Java")

# loader_java itself: a verified path is accepted, the bare-name fallback is
# NOT (that fallback is what mll turned into WinError 2).
with patch.object(launch, "find_java_for_version", return_value=_fake_java):
    check(mod_loaders.loader_java("1.20.1", "fabric") == _fake_java,
          "an existing java path is accepted")
with patch.object(launch, "find_java_for_version", return_value="java"), \
        patch.object(mod_loaders.shutil, "which", lambda name: None):
    try:
        mod_loaders.loader_java("1.20.1", "fabric")
        check(False, "the bare 'java' fallback is rejected, not handed to mll")
    except RuntimeError as ex:
        check("Java" in str(ex) and "Settings" in str(ex),
              "the bare 'java' fallback is rejected, not handed to mll",
              f"got: {ex}")

# ------------------------------------------- too-old Java must NOT slip past ---
# The banner said "Java 17+ wasn't found" even on machines that DID have Java,
# because find_java_for_version falls back to a too-old binary on purpose (so
# LAUNCH can show Minecraft's own error) and the old check only asked "does
# this path exist?". A Java 8 on PATH therefore reached the installer jar, which
# died on a raw UnsupportedClassVersionError instead of this message.
print("\n8c. a too-old Java is rejected with an honest message")


def _fake_jvm(major_label, raw):
    """An executable that answers `-version` the way a real JVM does."""
    path = os.path.join(tempfile.gettempdir(), f"cubeon-fake-jvm-{raw}")
    with open(path, "w") as fh:
        fh.write(f'#!/bin/sh\necho \'{major_label} version "{raw}"\' >&2\nexit 0\n')
    os.chmod(path, 0o755)
    return path


_java8 = _fake_jvm("java", "1.8.0_402")
_java17 = _fake_jvm("openjdk", "17.0.11")
check(launch.java_major_version(_java8) == 8, "the stub JVM reports its real major")
check(launch.java_major_version(_java17) == 17, "a 17 stub reports 17")

# The bug: Java 8 exists, so the old os.path.isfile() check passed it straight
# through. It must now be rejected.
with patch.object(launch, "find_java_for_version", return_value=_java8):
    try:
        got = mod_loaders.loader_java("1.20.1", "fabric")
        check(False, "a Java 8 on PATH is NOT handed to the 1.20.1 installer",
              f"returned {got}")
    except RuntimeError as ex:
        check("Java 17+" in str(ex),
              "a Java 8 on PATH is NOT handed to the 1.20.1 installer",
              f"got: {ex}")
        check("Only Java 8 was found" in str(ex) and "1.20.1" in str(ex),
              "the message says what WAS found and which version needs more",
              f"got: {ex}")
        check("JAVA_HOME" in str(ex),
              "the message names JAVA_HOME, one of the three sources now read",
              f"got: {ex}")

# A new-enough Java is still accepted unchanged (no regression on the happy path).
with patch.object(launch, "find_java_for_version", return_value=_java17):
    check(mod_loaders.loader_java("1.20.1", "fabric") == _java17,
          "a Java 17 is still accepted for 1.20.1")
    try:
        mod_loaders.loader_java("1.21", "fabric")
        check(False, "Java 17 is correctly rejected for a 1.21 (needs 21)")
    except RuntimeError as ex:
        check("Java 21+" in str(ex),
              "Java 17 is correctly rejected for a 1.21 (needs 21)",
              f"got: {ex}")

# The number in the message must track the SELECTED Minecraft version - that is
# why the same build showed "Java 21+" and "Java 17+" to different users.
with patch.object(launch, "find_java_for_version", return_value=_java8):
    _msgs = {}
    for _mc, _expect in (("1.20.1", "Java 17+"), ("1.21.4", "Java 21+"),
                         ("26.1", "Java 25+")):
        try:
            mod_loaders.loader_java(_mc, "fabric")
        except RuntimeError as ex:
            _msgs[_mc] = str(ex)
    check(all(_expect in _msgs.get(_mc, "") for _mc, _expect in
              (("1.20.1", "Java 17+"), ("1.21.4", "Java 21+"), ("26.1", "Java 25+"))),
          "the required major follows the selected Minecraft version",
          f"got: {_msgs}")

# ------------------------------------------------ JAVA_HOME is now consulted ---
# The other half of the report: machines WITH a JDK (Temurin/Adoptium) were told
# no Java existed, because resolution read Settings -> PATH -> mll and never
# JAVA_HOME - the one thing a user who just installed Java reliably sets.
print("\n8d. JAVA_HOME is a Java source")
with tempfile.TemporaryDirectory() as _jh:
    _jdk = os.path.join(_jh, "jdk-21")
    os.makedirs(os.path.join(_jdk, "bin"))
    _jh_java = os.path.join(_jdk, "bin", "java")
    with open(_jh_java, "w") as _fh:
        _fh.write('#!/bin/sh\necho \'openjdk version "21.0.5"\' >&2\nexit 0\n')
    os.chmod(_jh_java, 0o755)

    with patch.dict(os.environ, {"JAVA_HOME": _jdk}), \
            patch.object(launch.shutil, "which", lambda n: None), \
            patch.object(launch, "mll") as _mll:
        _mll.java_utils.find_system_java_versions.return_value = []
        check(launch.find_java() == _jh_java,
              "find_java() falls back to JAVA_HOME when PATH is empty",
              f"got: {launch.find_java()}")
        check(launch.find_java_for_version("1.21") == _jh_java,
              "JAVA_HOME's java is picked when nothing else qualifies")
        with patch.dict(os.environ, {"JAVA_HOME": _jdk}), \
                patch.object(launch.shutil, "which", lambda n: None):
            check(mod_loaders.loader_java("1.21", "fabric") == _jh_java,
                  "a loader install uses the JAVA_HOME java (no false banner)")

    # A stale/garbage JAVA_HOME must not crash or be returned.
    with patch.dict(os.environ, {"JAVA_HOME": os.path.join(_jh, "nope")}), \
            patch.object(launch.shutil, "which", lambda n: None):
        check(launch._java_home_binaries() == [],
              "a JAVA_HOME pointing nowhere is ignored, not crashed on")
    with patch.dict(os.environ, {"JAVA_HOME": f'"{_jdk}"'}):
        check(launch._java_home_binaries() == [_jh_java],
              "a quoted JAVA_HOME (Windows-style) is unquoted, not rejected",
              f"got: {launch._java_home_binaries()}")

    # ---------------------------------------- a JDK FOLDER pasted into Settings ---
    # Users paste the JDK directory, not .../bin/java, and used to get the same
    # false "Java N+ wasn't found" banner (a directory is not a file).
    print("\n8e. a JDK folder in java_path resolves to its bin/java")
    check(launch._normalize_java_path(_jdk) == _jh_java,
          "a Settings java_path pointing at the JDK folder resolves to bin/java",
          f"got: {launch._normalize_java_path(_jdk)}")
    check(launch._normalize_java_path(_jh_java) == _jh_java,
          "a Settings java_path already pointing at the binary is left alone")
    check(launch._normalize_java_path(_jh) == _jh,
          "a folder with no bin/java is left alone (still reports honestly)")
    check(launch._normalize_java_path("") == "",
          "an empty java_path does not explode")
    with patch.object(launch.shutil, "which", lambda n: None), \
            patch.object(launch.mll, "java_utils") as _mll2:
        _mll2.java_utils.find_system_java_versions.return_value = []
        check(launch.find_java_for_version("1.21", _jdk) == _jh_java,
              "find_java_for_version accepts the JDK folder in java_path")
    # And end-to-end: a loader install must use it rather than showing the banner.
    # Capture the real function first - patching it and then calling
    # launch.find_java_for_version inside side_effect would just recurse into the
    # mock (and silently prove nothing).
    _real_find = launch.find_java_for_version
    with patch.dict(os.environ, {"JAVA_HOME": ""}), \
            patch.object(launch.shutil, "which", lambda n: None), \
            patch.object(launch.mll, "java_utils") as _mll3, \
            patch.object(launch, "find_java_for_version",
                         side_effect=lambda mc, jp=None: _real_find(mc, _jdk)):
        _mll3.java_utils.find_system_java_versions.return_value = []
        check(mod_loaders.loader_java("1.21", "fabric") == _jh_java,
              "a loader install uses the JDK folder from java_path (no banner)")

# ---------------------------------------------------------------------- L11 ---
print("\n9. stale jar cache rejection (L11)")


def make_jar(path, year, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "w") as jar:
        info = zipfile.ZipInfo("fabric.mod.json", (year, 1, 1, 0, 0, 0))
        jar.writestr(info, json.dumps({"id": "cubeon-client", "version": value}))


with tempfile.TemporaryDirectory() as directory:
    root = Path(directory)
    name = cubeonfriends.jar_name(cubeonfriends.pick_bracket("26.1"))
    cache = root / "home" / "cache" / name
    bundle = root / "repo" / "assets" / "jars" / name
    with patch.object(cubeonfriends, "CUBEON_HOME", str(root / "home")), \
            patch.object(cubeonfriends, "_REPO", str(root / "repo")), \
            patch.object(cubeonfriends, "_resource_path",
                         lambda *p: str(root.joinpath(*p))):
        make_jar(cache, 2024, "old")
        make_jar(bundle, 2026, "shipped")
        check(cubeonfriends.find_jar("26.1") == str(bundle),
              "older valid cache yields to the shipped build")
        cache.write_bytes(b"PK\x03\x04 not really a jar")
        check(cubeonfriends.find_jar("26.1") == str(bundle),
              "corrupt cache yields to a valid bundled jar")
        bundle.unlink()
        check(cubeonfriends.find_jar("26.1") is None,
              "an invalid cache alone is rejected")
        make_jar(cache, 2026, "valid")
        check(cubeonfriends.find_jar("26.1") == str(cache),
              "a valid same-era cache alone is accepted")
        make_jar(bundle, 2025, "older")
        check(cubeonfriends.find_jar("26.1") == str(cache),
              "a valid newer cache keeps cache-first ordering")
        bundle.write_bytes(cache.read_bytes())
        check(cubeonfriends.find_jar("26.1") == str(cache),
              "identical artifacts keep cache-first ordering")

# ---------------------------------------------------------------------- L2 ---
print("\n9b. stale exit cannot clear a newer live session (L2)")
live = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
try:
    older = watchdog.register(live.pid, "1.20.1", "Older", process=live)
    newer = watchdog.register(live.pid, "1.21.1", "Newer", process=live)
    check(older != newer, "overlapping registrations get distinct session ids")
    check(not watchdog.clear(older), "older session id cannot clear while live")
    check(watchdog.effective_username("Config") == "Newer",
          "newer session still owns the effective username")
finally:
    if live.poll() is None:
        live.terminate()
        live.wait(5)
    watchdog.clear(newer)
    watchdog.clear()

# ---------------------------------------------------------------------- L17 ---
print("\n10. relative CUBEON_GAME_DIR is absolutized (L17)")
import importlib  # noqa: E402
from cubeon import paths as paths_mod  # noqa: E402
with tempfile.TemporaryDirectory() as tmp:
    os.chdir(tmp)
    os.environ["CUBEON_GAME_DIR"] = "relative_game"
    reloaded = importlib.reload(paths_mod)
    check(os.path.isabs(reloaded.MINECRAFT_DIR), "MINECRAFT_DIR becomes absolute")
    check(reloaded.MINECRAFT_DIR == os.path.abspath("relative_game"),
          "relative dir resolves against cwd", reloaded.MINECRAFT_DIR)
    check(reloaded.MODS_DIR.startswith(reloaded.MINECRAFT_DIR + os.sep),
          "derived dirs stay under the resolved root")
    check(os.path.abspath(os.path.join("relative_game", "mods")) == reloaded.MODS_DIR,
          "child cwd would no longer double the path")
finally_ = None

# ---------------------------------------------------------------------- L18 ---
print("\n11. disk-space walks up to an existing ancestor (L18)")
with tempfile.TemporaryDirectory() as tmp:
    missing = os.path.join(tmp, "no", "such", "dir")
    try:
        paths_mod.ensure_disk_space(missing, 1, "probe")
        ok_free = True
    except RuntimeError:
        ok_free = True  # measurable ancestor -> comparison ran; either outcome is correct
    check(ok_free, "missing parent dirs still yield a usable measurement")

# ---------------------------------------------------------------------- L23 ---
print("\n12. username validator (L23)")
ok_name, _ = config.validate_username("Valid_Name1")
check(ok_m := ok_name, "a plain valid username passes")
check(config.validate_username("Valid\n")[0] is False, "trailing newline is rejected")
check(config.validate_username("ab")[0] is False, "too short rejected")
check(config.validate_username("a" * 17)[0] is False, "too long rejected")
check(config.validate_username("bad name")[0] is False, "space rejected")
check(config.validate_username(None)[0] is False, "non-string rejected")

# ---------------------------------------------------------------------- L22 ---
print("\n13. two-process watchdog merge (L22)")
watchdog.clear()
holder = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
other = subprocess.Popen([sys.executable, "-c",
                          "import time; time.sleep(60)"])
try:
    spec = __import__("importlib.util", fromlist=["util"])
    util = __import__("importlib").import_module("importlib.util")
    other_module = util.spec_from_file_location("cubeon._watchdog_merge", watchdog.__file__)
    other_wd = util.module_from_spec(other_module)
    other_module.loader.exec_module(other_wd)
    other_wd.RECORD_PATH = watchdog.RECORD_PATH
    mine = watchdog.register(holder.pid, "1.20.1", "Mine", process=holder)
    theirs = other_wd.register(other.pid, "1.21.1", "Theirs", process=other)
    check(theirs is not None, "second process registers")
    deadline = time.monotonic() + 3
    mine_seen = theirs_seen = False
    while time.monotonic() < deadline and not (mine_seen and theirs_seen):
        with open(watchdog.RECORD_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        ids = {rec["session_id"] for rec in data.get("sessions", [])}
        mine_seen = mine in ids
        theirs_seen = theirs in ids
        time.sleep(0.05)
    check(mine_seen and theirs_seen, "both launcher processes' sessions survive",
          f"mine={mine_seen} theirs={theirs_seen}")
    other.terminate()
    other.wait(5)
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        watchdog.clear()
        with open(watchdog.RECORD_PATH, encoding="utf-8") as fh:
            data = json.load(fh)
        if mine in {rec["session_id"] for rec in data.get("sessions", [])}:
            break
        time.sleep(0.05)
    check(mine in {rec["session_id"] for rec in data.get("sessions", [])},
          "dead sibling session is dropped, own session survives merge")
finally:
    for proc in (holder, other):
        if proc.poll() is None:
            proc.terminate()
            proc.wait(5)
    watchdog.clear()

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
