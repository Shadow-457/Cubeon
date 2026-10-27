"""Offline checks for cubeon/crash_doctor.py - the "Fix crash" engine.

No display and no network: the crash evidence is passed as text, mod metadata
is read from locally built jars, and HOME is redirected into a scratch dir
before cubeon binds its paths. What is exercised is the part that matters in
front of a user: a recognised signature maps to the right repair, the repair
is verified (not just attempted), an unknown crash is reported honestly, and
the newest crash evidence wins.
"""
import json
import os
import sys
import tempfile
import time
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home

_sandbox_home.isolate()

from cubeon import crash_doctor, mods  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


def _jar(path, identity, version="1.0", extra=None):
    payload = {"id": identity, "name": identity, "version": version}
    if extra:
        payload.update(extra)
    with zipfile.ZipFile(path, "w") as archive:
        archive.writestr("fabric.mod.json", json.dumps(payload))


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-crashdoctor-")
    crash_doctor.MINECRAFT_DIR = scratch
    crash_doctor.CUBEON_HOME = scratch
    os.makedirs(os.path.join(scratch, "crash-reports"), exist_ok=True)
    os.makedirs(os.path.join(scratch, "logs"), exist_ok=True)

    # --- classification -----------------------------------------------------
    cases = [
        ("java.lang.OutOfMemoryError: Java heap space",
         "out-of-memory", 0.9),
        ("java.lang.UnsupportedClassVersionError: net/minecraft/client/main/Main",
         "wrong-java", 0.9),
        ("Unrecognized option: -XX:+NotARealFlag", "bad-jvm-option", 0.9),
        ("DuplicateModsFoundException: found duplicate mod sodium",
         "duplicate-mods", 0.9),
        ("Missing or unsupported mandatory dependencies: mod 'x' requires y",
         "missing-dependency", 0.9),
        ("Incompatible mod set! Mod resolution encountered an incompatible mod set",
         "incompatible-mods", 0.8),
        ("Mixin apply failed: mixin.example.json", "mod-conflict", 0.8),
        ("java.util.zip.ZipException: invalid LOC header (bad signature)",
         "corrupt-jar", 0.9),
        ("GLFW error 65542: WGL: The driver does not appear to support OpenGL",
         "graphics-driver", 0.8),
    ]
    for text, signature, minimum in cases:
        result = crash_doctor.classify(text)
        check(f"classify: {signature}",
              result["signature"] == signature
              and result["confidence"] >= minimum
              and result["recognised"],
              str(result))

    unknown = crash_doctor.classify("something odd happened with a widget")
    check("classify: unknown stays unknown instead of guessing",
          unknown["signature"] == "unknown" and not unknown["recognised"])

    # --- newest evidence wins ----------------------------------------------
    old_path = os.path.join(scratch, "crash-reports", "crash-old.txt")
    new_path = os.path.join(scratch, "crash-reports", "crash-new.txt")
    with open(old_path, "w", encoding="utf-8") as fh:
        fh.write("java.lang.OutOfMemoryError: Java heap space")
    with open(new_path, "w", encoding="utf-8") as fh:
        fh.write("Unrecognized option: -XX:+Bogus")
    past = time.time() - 600
    os.utime(old_path, (past, past))
    found_path, found_text = crash_doctor.latest_crash_log()
    check("evidence: the newest crash report is chosen",
          found_path == new_path and "Bogus" in found_text,
          f"{found_path!r}")
    _, old_text = crash_doctor.latest_crash_log(after=past + 1)
    check("evidence: `after` filters out an older failure",
          "Bogus" in old_text and "OutOfMemory" not in old_text,
          old_text[:80])

    # --- OOM repair actually raises and stores RAM -------------------------
    from cubeon import config
    cfg = config.load_config()
    cfg["ram_mb"] = 2048
    config.save_config(cfg)
    result = crash_doctor.repair(text="java.lang.OutOfMemoryError: Java heap space")
    stored = int((config.load_config() or {}).get("ram_mb") or 0)
    check("repair: out-of-memory raises the stored RAM allocation",
          result["fixed"] and stored > 2048,
          f"{result} stored={stored}")

    # --- bad JVM flag repair removes only the rejected token ---------------
    cfg = config.load_config()
    cfg["custom_jvm_flags"] = "-XX:+UseG1GC -XX:+BogusFlag"
    config.save_config(cfg)
    result = crash_doctor.repair(
        text="Unrecognized option: -XX:+BogusFlag")
    stored_flags = (config.load_config() or {}).get("custom_jvm_flags") or ""
    check("repair: bad JVM option is removed, valid flag kept",
          result["fixed"] and "BogusFlag" not in stored_flags
          and "UseG1GC" in stored_flags,
          f"{result} stored={stored_flags!r}")

    # --- corrupt jar: disable the named mod, keep the file -----------------
    mc, loader = "1.20.1", "fabric"
    profile = mods.get_profile_dir(mc, loader)
    os.makedirs(profile, exist_ok=True)
    bad = os.path.join(profile, "badmod.jar")
    with open(bad, "wb") as fh:
        fh.write(b"not a zip")
    result = crash_doctor.repair(
        mc, loader,
        text="java.util.zip.ZipException: invalid LOC header (bad signature) "
             "in badmod.jar")
    check("repair: corrupt jar is disabled (renamed, not deleted)",
          result["fixed"] and os.path.isfile(bad + ".disabled")
          and not os.path.isfile(bad),
          str(result))
    if os.path.isfile(bad + ".disabled"):
        os.remove(bad + ".disabled")

    # --- duplicate mods: the dependency/conflict pass runs and fixes it ----
    first = os.path.join(profile, "sodium-1.jar")
    second = os.path.join(profile, "sodium-2.jar")
    _jar(first, "sodium", "0.5.0")
    _jar(second, "sodium", "0.6.0")
    result = crash_doctor.repair(
        mc, loader,
        text="DuplicateModsFoundException: found duplicate mod sodium",
        allow_online=False, approve_cb=lambda change: True)
    disabled = [name for name in os.listdir(profile)
                if name.startswith("sodium-") and name.endswith(".disabled")]
    check("repair: duplicate mods pass runs and disables one copy",
          result["report"] is not None and result["fixed"] and disabled,
          f"{result.get('fixed')} disabled={disabled}")
    for name in os.listdir(profile):
        if name.startswith("sodium-"):
            os.remove(os.path.join(profile, name))

    # --- unknown crash is honest, not a fake fix ---------------------------
    result = crash_doctor.repair(text="the widget exploded mysteriously")
    check("repair: unknown crash reports no fix and keeps the evidence",
          not result["recognised"] and not result["fixed"]
          and result["evidence"],
          str(result))

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
