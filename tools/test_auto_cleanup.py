"""Auto-delete of unfinished installs - the 2026-10-18 request: "add another
thing which auto deletes incomplete installs and like we can turn this off and
on in settings, on by default".

Deleting a version folder is NOT reversible, so this feature is deliberately
narrower than the "incomplete" flag the Play list shows. Locked-in behaviors:

  1. a version whose client jar never arrived is an unfinished install
  2. a truncated jar (size != manifest size) is one
  3. a jar that is not a zip at all (an HTML error page, NULL-padded junk) is one
  4. a whole, correctly-sized jar is NOT one
  5. a jar written moments ago is NOT one - a download may be in flight right
     now (another Cubeon instance, a manual copy), so the mtime grace wins
  6. a loader profile (inheritsFrom) is NEVER one, even when its base version
     is missing: the base is a separate install the user may still want
  7. a folder whose metadata is unreadable/invalid is NOT one - that is a
     hand-made or foreign folder, not a download Cubeon interrupted
  8. a jar that cannot even be stat'd (permissions, held open by a running
     game) is NOT one
  9. cleanup deletes exactly the unfinished folders and reports them
 10. `skip` protects an id the caller says is in use
 11. dry_run reports without deleting
 12. one folder that refuses to delete does not abort the pass
 13. everything the predicate flags the Play-list scan ALSO calls incomplete
     (the narrow predicate must stay a subset of the visible one)
 14. wiring: config defaults to ON, main.py gates on it before the first scan,
     and Settings carries the switch
"""
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_home = tempfile.mkdtemp(prefix="cubeon-cleanup-test-")
os.environ["HOME"] = _home
os.environ["USERPROFILE"] = _home
os.environ["CUBEON_GAME_DIR"] = os.path.join(_home, "game")

from cubeon import versions as V  # noqa: E402  (after the env isolation)

passed = failed = 0


def check(label, ok, extra=""):
    global passed, failed
    passed += ok
    failed += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' - ' + extra) if extra and not ok else ''}")


VERSIONS = os.path.join(V.MINECRAFT_DIR, "versions")
MANIFEST = {"downloads": {"client": {"size": 1000, "sha1": "a" * 40}},
            "id": "1.20.1", "type": "release"}
GOOD_JAR = b"PK" + b"\x00" * 998   # exactly the manifest's 1000-byte client


def age(path, seconds):
    """Backdate a file/dir past the cleanup grace period."""
    when = time.time() - seconds
    os.utime(path, (when, when))


def make_version(vid, jar_bytes=None, manifest=None, inherits=None,
                 raw_json=None, age_seconds=None):
    """One versions/<vid> folder. `raw_json` writes metadata verbatim (the
    invalid-json case); `jar_bytes=None` means no jar at all."""
    folder = os.path.join(VERSIONS, vid)
    os.makedirs(folder, exist_ok=True)
    if raw_json is not None:
        with open(os.path.join(folder, vid + ".json"), "w") as fh:
            fh.write(raw_json)
    else:
        data = dict(MANIFEST if manifest is None else manifest)
        data["id"] = vid   # each version json names its own version
        if inherits:
            data["inheritsFrom"] = inherits
        with open(os.path.join(folder, vid + ".json"), "w") as fh:
            json.dump(data, fh)
    if jar_bytes is not None:
        with open(os.path.join(folder, vid + ".jar"), "wb") as fh:
            fh.write(jar_bytes)
    if age_seconds is not None:
        for name in os.listdir(folder):
            age(os.path.join(folder, name), age_seconds)
        age(folder, age_seconds)
    return folder


def reset():
    """Empty versions/ so each section starts from a known set."""
    if os.path.isdir(VERSIONS):
        for name in os.listdir(VERSIONS):
            path = os.path.join(VERSIONS, name)
            if os.path.isdir(path):
                import shutil
                shutil.rmtree(path)
            else:
                os.remove(path)
    os.makedirs(VERSIONS, exist_ok=True)


# The truncated/garbage fixtures below must be OLDER than the grace period or
# they are (correctly) protected, so they all use PAST.
PAST = V._CLEANUP_GRACE_SECONDS + 60

print("1. what counts as an unfinished install")
reset()
make_version("1.0-missing-jar", jar_bytes=None)
make_version("1.1-truncated", jar_bytes=b"PK" + b"\x00" * 98, age_seconds=PAST)
make_version("1.2-not-a-zip", jar_bytes=b"<html>404</html>" + b"\x00" * 500,
             age_seconds=PAST)
make_version("1.3-good", jar_bytes=GOOD_JAR, age_seconds=PAST)
reasons = {r["id"]: r["reason"] for r in V.find_unfinished_installs()}
check("a client jar that never arrived is unfinished", "1.0-missing-jar" in reasons)
check("a truncated jar is unfinished", "1.1-truncated" in reasons)
check("a jar that is not a zip is unfinished", "1.2-not-a-zip" in reasons)
check("a whole, correctly-sized jar is NOT unfinished", "1.3-good" not in reasons)
check("the reason says what was wrong",
      "truncated" in reasons.get("1.1-truncated", ""),
      repr(reasons))

print("\n2. what is deliberately left alone")
reset()
make_version("2.0-loader-no-base", jar_bytes=None, inherits="1.21.1",
             age_seconds=PAST)
make_version("2.1-bad-json", raw_json="{not json", age_seconds=PAST)
os.makedirs(os.path.join(VERSIONS, "2.2-no-json"), exist_ok=True)
with open(os.path.join(VERSIONS, "2.2-no-json", "readme.txt"), "w") as fh:
    fh.write("not a version")
with open(os.path.join(VERSIONS, "2.3-stray-file"), "w") as fh:
    fh.write("not a folder")
make_version("2.4-just-downloaded", jar_bytes=b"PK" + b"\x00" * 98)
found = {r["id"] for r in V.find_unfinished_installs()}
check("a loader profile with a missing base is left alone",
      "2.0-loader-no-base" not in found)
check("unreadable metadata is left alone", "2.1-bad-json" not in found)
check("a folder with no metadata at all is left alone", "2.2-no-json" not in found)
check("a stray file in versions/ is not a version", "2.3-stray-file" not in found)
check("a jar written moments ago is left alone (download may be live)",
      "2.4-just-downloaded" not in found)
check("...and the same jar is found once it is older than the grace",
      V.unfinished_install_reason("2.4-just-downloaded") is None and
      (age(os.path.join(VERSIONS, "2.4-just-downloaded",
                        "2.4-just-downloaded.jar"), PAST),
       "2.4-just-downloaded" in {r["id"] for r in V.find_unfinished_installs()})[1])
check("a name that escapes versions/ is refused",
      V.unfinished_install_reason("../evil") is None)
check("...and so is a name that does not exist",
      V.unfinished_install_reason("no-such-version") is None)

print("\n3. cleanup deletes exactly the unfinished ones")
reset()
make_version("3.0-broken", jar_bytes=b"PK" + b"\x00" * 98, age_seconds=PAST)
make_version("3.1-good", jar_bytes=GOOD_JAR, age_seconds=PAST)
make_version("3.2-loader-no-base", jar_bytes=None, inherits="1.21.1",
             age_seconds=PAST)
removed = V.cleanup_unfinished_installs()
check("the unfinished folder is gone",
      not os.path.isdir(os.path.join(VERSIONS, "3.0-broken")))
check("the healthy install survives",
      os.path.isdir(os.path.join(VERSIONS, "3.1-good")))
check("the loader profile survives",
      os.path.isdir(os.path.join(VERSIONS, "3.2-loader-no-base")))
check("only the unfinished one is reported",
      [r["id"] for r in removed] == ["3.0-broken"], str(removed))
check("the report names the reason", "truncated" in removed[0]["reason"],
      str(removed))

print("\n4. skip, dry_run, and one folder that refuses to go")
reset()
make_version("4.0-broken", jar_bytes=b"PK" + b"\x00" * 98, age_seconds=PAST)
make_version("4.1-broken", jar_bytes=b"PK" + b"\x00" * 98, age_seconds=PAST)
check("skip protects an id the caller says is in use",
      [r["id"] for r in V.cleanup_unfinished_installs(
          skip=["4.0-broken"], dry_run=True)] == ["4.1-broken"])
check("...and dry_run deletes nothing",
      os.path.isdir(os.path.join(VERSIONS, "4.0-broken")) and
      os.path.isdir(os.path.join(VERSIONS, "4.1-broken")))
_real_delete = V.delete_version


def _boom(version_id):
    if version_id == "4.0-broken":
        raise ValueError("simulated OS refusal")
    return _real_delete(version_id)


V.delete_version = _boom
try:
    removed = V.cleanup_unfinished_installs()
finally:
    V.delete_version = _real_delete
check("a folder that refuses to delete is reported as not removed",
      "4.0-broken" not in [r["id"] for r in removed], str(removed))
check("...and the rest of the pass still runs",
      "4.1-broken" in [r["id"] for r in removed] and
      not os.path.isdir(os.path.join(VERSIONS, "4.1-broken")))

print("\n5. the predicate stays a subset of what the scan calls incomplete")
reset()
make_version("5.0-missing-jar", jar_bytes=None, age_seconds=PAST)
make_version("5.1-truncated", jar_bytes=b"PK" + b"\x00" * 98, age_seconds=PAST)
make_version("5.2-good", jar_bytes=GOOD_JAR, age_seconds=PAST)
make_version("5.3-loader-no-base", jar_bytes=None, inherits="1.21.1",
             age_seconds=PAST)
scan = {v["id"]: v for v in V.get_installed_versions()}
flagged = {r["id"] for r in V.find_unfinished_installs()}
check("something is flagged (the section is not vacuous)", bool(flagged),
      str(flagged))
check("every flagged folder the scan ALSO marks incomplete",
      all(scan.get(vid, {}).get("incomplete") for vid in flagged),
      str({vid: scan.get(vid, {}).get("incomplete") for vid in flagged}))
check("a healthy install is present in the scan and not incomplete",
      "5.2-good" in scan and not scan["5.2-good"].get("incomplete"),
      str(scan.get("5.2-good")))
check("the loader profile is incomplete in the scan but NOT flagged",
      scan.get("5.3-loader-no-base", {}).get("incomplete") is True and
      "5.3-loader-no-base" not in flagged)

print("\n6. wiring")
from cubeon import config as C  # noqa: E402
check("the setting is ON by default",
      C.DEFAULT_CONFIG.get("auto_delete_incomplete") is True)
import launcher_core as core  # noqa: E402
check("launcher_core re-exports the cleanup",
      callable(getattr(core, "cleanup_unfinished_installs", None)) and
      callable(getattr(core, "find_unfinished_installs", None)))

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
with open(os.path.join(_ROOT, "main.py"), encoding="utf-8") as fh:
    _main = fh.read()
check("main.py gates the pass on the config key",
      'cfg.get("auto_delete_incomplete", True)' in _main)
check("main.py runs it through launcher_core",
      "core.cleanup_unfinished_installs()" in _main)
_scan_at = _main.index("_initial_versions = core.get_installed_versions()")
check("...BEFORE the first version scan (so nothing stranded is listed)",
      _main.index("core.cleanup_unfinished_installs()") < _scan_at)
with open(os.path.join(_ROOT, "ui", "settings_tab.py"), encoding="utf-8") as fh:
    _settings = fh.read()
check("Settings carries the switch",
      '"auto_delete_incomplete"' in _settings and
      "Delete unfinished installs" in _settings)
check("the switch saves to the same key it reads",
      'cfg["auto_delete_incomplete"]' in _settings)

print(f"\n{passed} passed, {failed} failed")
print("Auto-cleanup test: " + ("PASS" if not failed else "FAIL"))
sys.exit(1 if failed else 0)
