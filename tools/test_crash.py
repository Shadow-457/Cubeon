"""Offline checks for cubeon/crash.py - the minimal "Fix crash" flow.

No display and no network: crash evidence is passed as text, mod metadata is
read from locally built jars, and HOME is redirected into a scratch dir before
cubeon binds its paths. The test covers the part that matters in front of a
user: a crash is explained in plain language, the dependency/conflict/launch
checks run, fixes are verified on disk, and an unknown crash is reported
honestly instead of guessed at.
"""
import json
import os
import sys
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home

_sandbox_home.isolate()

from cubeon import config, crash, mods, paths  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


def _jar(path, identity, version="1.0"):
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps(
            {"id": identity, "name": identity, "version": version}))


def main():
    print("1. plain-language explanation")
    cases = [
        ("java.lang.OutOfMemoryError: Java heap space", "memory"),
        ("java.lang.UnsupportedClassVersionError: net/minecraft/client/main/Main",
         "java"),
        ("Unrecognized option: -XX:+NotARealFlag", "jvm"),
        ("DuplicateModsFoundException: found duplicate mod sodium", "mods"),
        ("Missing or unsupported mandatory dependencies: mod 'x' requires y",
         "mods"),
        ("Incompatible mod set! Mod resolution encountered an incompatible mod set",
         "mods"),
        ("Mixin apply failed: mixin.example.json", "mods"),
        ("java.util.zip.ZipException: invalid LOC header (bad signature)",
         "mods"),
        ("GLFW error 65542: WGL: The driver does not appear to support OpenGL",
         "graphics"),
    ]
    for text, kind in cases:
        result = crash.explain(text)
        check(f"explain: {kind}", result["kind"] == kind, str(result))
        check(f"explain: {kind} has advice and evidence",
              bool(result["advice"]) and bool(result["evidence"]), str(result))

    unknown = crash.explain("something odd happened with a widget")
    check("explain: unknown stays unknown instead of guessing",
          unknown["kind"] == "unknown" and unknown["evidence"],
          str(unknown))

    print("\n2. newest evidence wins")
    reports = os.path.join(paths.MINECRAFT_DIR, "crash-reports")
    os.makedirs(reports, exist_ok=True)
    old_path = os.path.join(reports, "crash-old.txt")
    new_path = os.path.join(reports, "crash-new.txt")
    with open(old_path, "w", encoding="utf-8") as fh:
        fh.write("java.lang.OutOfMemoryError: Java heap space")
    with open(new_path, "w", encoding="utf-8") as fh:
        fh.write("Unrecognized option: -XX:+Bogus")
    past = time.time() - 600
    os.utime(old_path, (past, past))
    found_path, found_text = crash.latest_log()
    check("evidence: the newest crash report is chosen",
          found_path == new_path and "Bogus" in found_text, f"{found_path!r}")
    _, old_text = crash.latest_log(after=past + 1)
    check("evidence: `after` filters out an older failure",
          "Bogus" in old_text and "OutOfMemory" not in old_text,
          old_text[:80])

    print("\n3. out-of-memory raises the stored RAM allocation")
    cfg = config.load_config()
    cfg["ram_mb"] = 2048
    config.save_config(cfg)
    result = crash.diagnose_and_fix(
        text="java.lang.OutOfMemoryError: Java heap space")
    stored = int((config.load_config() or {}).get("ram_mb") or 0)
    check("repair: RAM is raised and verified",
          result["kind"] == "memory" and result["fixed"] and stored > 2048,
          f"{result} stored={stored}")

    print("\n4. the JVM option Java rejected is removed, valid flags kept")
    cfg = config.load_config()
    cfg["custom_jvm_flags"] = "-XX:+UseG1GC -XX:+BogusFlag"
    config.save_config(cfg)
    result = crash.diagnose_and_fix(text="Unrecognized option: -XX:+BogusFlag")
    stored_flags = (config.load_config() or {}).get("custom_jvm_flags") or ""
    check("repair: rejected option removed, valid flag kept",
          result["kind"] == "jvm" and result["fixed"]
          and "BogusFlag" not in stored_flags and "UseG1GC" in stored_flags,
          f"{result} stored={stored_flags!r}")

    print("\n5. corrupt jar is disabled (renamed, not deleted)")
    mc, loader = "1.20.1", "fabric"
    profile = mods.get_profile_dir(mc, loader)
    os.makedirs(profile, exist_ok=True)
    bad = os.path.join(profile, "badmod.jar")
    with open(bad, "wb") as fh:
        fh.write(b"not a zip")
    result = crash.diagnose_and_fix(
        mc, loader, allow_online=False,
        text="java.util.zip.ZipException: invalid LOC header (bad signature) "
             "in badmod.jar")
    check("repair: corrupt jar disabled, file kept",
          result["fixed"] and os.path.isfile(bad + ".disabled")
          and not os.path.isfile(bad), str(result))
    if os.path.isfile(bad + ".disabled"):
        os.remove(bad + ".disabled")

    print("\n6. dependency/conflict pass fixes duplicate mods")
    first = os.path.join(profile, "sodium-1.jar")
    second = os.path.join(profile, "sodium-2.jar")
    _jar(first, "sodium", "0.5.0")
    _jar(second, "sodium", "0.6.0")
    result = crash.diagnose_and_fix(
        mc, loader, allow_online=False,
        text="DuplicateModsFoundException: found duplicate mod sodium")
    disabled = [name for name in os.listdir(profile)
                if name.startswith("sodium-") and name.endswith(".disabled")]
    check("repair: doctor runs and disables one duplicate",
          result["report"] is not None and result["fixed"] and disabled,
          f"{result.get('fixed')} disabled={disabled}")
    for name in os.listdir(profile):
        if name.startswith("sodium-"):
            os.remove(os.path.join(profile, name))

    print("\n7. unknown crash is honest, not a fake fix")
    result = crash.diagnose_and_fix(
        allow_online=False, text="the widget exploded mysteriously")
    check("repair: unknown crash reports no fix and keeps the evidence",
          result["kind"] == "unknown" and not result["fixed"]
          and result["evidence"], str(result))

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
