"""A collector the player chose in Settings must not be replaced by G1 (11.3).

`launch.build_launch_command` removed EVERY `-XX:+Use*GC` argument from the
final command (including the player's own custom JVM flag) and inserted
`-XX:+UseG1GC`, so choosing ZGC/Shenandoah/Parallel in Settings silently did
nothing - and the JVM also kept Cubeon's `-XX:G1*` tuning flags, which are not
valid for those collectors.

Locked-in behaviour:
  * no custom flag: exactly one `-XX:+UseG1GC`, G1 tuning intact (unchanged);
  * `-XX:+UseZGC`: theirs survives, no `-XX:+UseG1GC`, no `-XX:G1*`;
  * `-XX:+UseShenandoahGC`: same;
  * the player writing `-XX:+UseG1GC` behaves like the default.

Run: python tools/test_launch_gc_flags.py
"""
import os
import sys
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import launch  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


VERSION = "gc-flag-test"


def fake_command(vid, directory, opts):
    # What minecraft_launcher_lib would hand back: the jvmArguments Cubeon
    # built, plus a profile-level collector the old code used to strip.
    return ["java", *opts["jvmArguments"], "-XX:+UseParallelGC",
            "-XX:ParallelGCThreads=4", "-cp", "x",
            "net.minecraft.client.main.Main"]


def build(custom=None):
    with patch.object(launch.mll.command, "get_minecraft_command",
                      side_effect=fake_command):
        return launch.build_launch_command(VERSION, "tester", 2048, 854, 480,
                                           None, custom)


def collectors(cmd):
    return [arg for arg in cmd
            if arg.startswith("-XX:") and arg.endswith("GC")
            and "Use" in arg and "DisableExplicit" not in arg]


def g1_flags(cmd):
    return [arg for arg in cmd if arg.startswith("-XX:G1")]


def main():
    # A version JSON is all build_launch_command needs on disk.
    import json
    vdir = os.path.join(launch.MINECRAFT_DIR, "versions", VERSION)
    os.makedirs(vdir, exist_ok=True)
    with open(os.path.join(vdir, VERSION + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"id": VERSION, "type": "release",
                   "mainClass": "net.minecraft.client.main.Main",
                   "arguments": {"game": [], "jvm": []}}, fh)

    # --- default: unchanged -------------------------------------------------
    cmd = build()
    check("default: exactly one G1 collector",
          collectors(cmd) == ["-XX:+UseG1GC"], str(collectors(cmd)))
    check("default: Cubeon's G1 tuning is still there", bool(g1_flags(cmd)),
          str(g1_flags(cmd)))

    # --- the player chose ZGC ----------------------------------------------
    cmd = build("-XX:+UseZGC")
    check("zgc: the player's collector is kept",
          collectors(cmd) == ["-XX:+UseZGC"], str(collectors(cmd)))
    check("zgc: no forced G1 collector", "-XX:+UseG1GC" not in cmd,
          str(collectors(cmd)))
    check("zgc: no G1-only tuning flags", not g1_flags(cmd), str(g1_flags(cmd)))
    check("zgc: unrelated profile flags still survive",
          "-XX:ParallelGCThreads=4" in cmd)

    # --- the player chose Shenandoah ---------------------------------------
    cmd = build("-XX:+UseShenandoahGC")
    check("shenandoah: the player's collector is kept",
          collectors(cmd) == ["-XX:+UseShenandoahGC"], str(collectors(cmd)))
    check("shenandoah: no forced G1 collector", "-XX:+UseG1GC" not in cmd)
    check("shenandoah: no G1-only tuning flags", not g1_flags(cmd))

    # --- the player explicitly asks for G1 ---------------------------------
    cmd = build("-XX:+UseG1GC")
    check("explicit G1: one G1 collector, not two",
          collectors(cmd) == ["-XX:+UseG1GC"], str(collectors(cmd)))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
