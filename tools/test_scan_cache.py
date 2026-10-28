"""The installed-version scan is memoized until versions/ actually changes (B1).

`get_installed_versions()` parsed every version JSON twice on every call, and
the Play tab calls it on each repaint - 100s of ms on a real install. It now
keeps the last result behind a stat fingerprint (folder, json/jar mtime+size,
active installs, and the versions dir itself).

Locked-in behaviour:
  * an unchanged versions/ is served from the cache (the scan body does not
    run again) and returns the same values;
  * touching/adding/removing a json or jar, or an install starting/finishing,
    invalidates the cache and the new state is reported;
  * callers get copies, so mutating a returned entry cannot poison the cache;
  * a different MINECRAFT_DIR never reuses another directory's cache.

Run: python tools/test_scan_cache.py
"""
import json
import os
import sys
import tempfile

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import versions as V  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def make_home(root):
    mc = os.path.join(root, "mc")
    vd = os.path.join(mc, "versions")
    os.makedirs(vd, exist_ok=True)
    V.MINECRAFT_DIR = mc
    V._scan_cache = None
    return mc, vd


def add(vd, vid, jar=True):
    p = os.path.join(vd, vid)
    os.makedirs(p, exist_ok=True)
    with open(os.path.join(p, vid + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"id": vid, "type": "release",
                   "libraries": [{"name": "a"}]}, fh)
    if jar:
        with open(os.path.join(p, vid + ".jar"), "wb") as fh:
            fh.write(b"PK\x03\x04" + b"x" * 64)
    return p


def main():
    root = tempfile.mkdtemp(prefix="cubeon-scan-cache-")
    mc, vd = make_home(root)
    add(vd, "1.20.1")
    add(vd, "1.21.4")

    calls = []
    real_scan = V._scan_installed_versions

    def spy(versions_dir, active):
        calls.append(versions_dir)
        return real_scan(versions_dir, active)

    V._scan_installed_versions = spy
    try:
        first = V.get_installed_versions()
        check("the first call scans", len(calls) == 1, str(calls))
        check("it reports both versions",
              sorted(v["id"] for v in first) == ["1.20.1", "1.21.4"],
              str(first))

        second = V.get_installed_versions()
        check("an unchanged versions/ reuses the cache", len(calls) == 1,
              str(calls))
        check("the cached result has the same values", second == first,
              str(second))

        # Callers must not be able to mutate the cached list/dicts.
        second[0]["display_name"] = "poisoned"
        third = V.get_installed_versions()
        check("a caller's mutation does not poison the cache",
              third[0]["display_name"] != "poisoned", str(third[0]))

        # A new version folder invalidates it.
        add(vd, "1.22")
        after_add = V.get_installed_versions()
        check("adding a version rescans", len(calls) == 2, str(calls))
        check("the new version appears",
              "1.22" in {v["id"] for v in after_add}, str(after_add))

        # Rewriting a jar (same name, new size/mtime) invalidates it too.
        with open(os.path.join(vd, "1.22", "1.22.jar"), "ab") as fh:
            fh.write(b"more-bytes")
        V.get_installed_versions()
        check("a rewritten jar rescans", len(calls) == 3, str(calls))

        # Deleting a folder invalidates it.
        import shutil
        shutil.rmtree(os.path.join(vd, "1.22"))
        after_del = V.get_installed_versions()
        check("deleting a version rescans", len(calls) == 4, str(calls))
        check("the deleted version is gone",
              "1.22" not in {v["id"] for v in after_del}, str(after_del))

        # An active install (even of an existing folder) invalidates the view.
        V._active_installs.add("1.21.4")
        try:
            during = V.get_installed_versions()
            check("starting an install rescans", len(calls) == 5, str(calls))
            check("the installing version is hidden",
                  "1.21.4" not in {v["id"] for v in during}, str(during))
        finally:
            V._active_installs.discard("1.21.4")
        after = V.get_installed_versions()
        check("finishing the install rescans again", len(calls) == 6,
              str(calls))
        check("the finished version is visible again",
              "1.21.4" in {v["id"] for v in after}, str(after))

        # Same folder names in another minecraft dir must not hit the cache.
        other_root = tempfile.mkdtemp(prefix="cubeon-scan-cache-2-")
        other_mc, other_vd = make_home(other_root)
        add(other_vd, "1.20.1")
        other = V.get_installed_versions()
        check("a different MINECRAFT_DIR is scanned", len(calls) == 7,
              str(calls))
        check("it only reports that directory's versions",
              [v["id"] for v in other] == ["1.20.1"], str(other))
        check("the other directory really is different", other_mc != mc)
    finally:
        V._scan_installed_versions = real_scan
        V._active_installs.discard("1.21.4")
        V._scan_cache = None

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
