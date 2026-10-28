"""Copying mods between two isolated instances uses their own profiles (9.4).

`copy_mods_between_profiles` called `list_mods(src_mc, src_loader)` and
`download_mod(... mc_version=dst_mc, loader=dst_loader)` without version ids,
so for modpack clones / isolated instances it read and wrote the legacy shared
profile instead of the instance's private one. One mod whose download raised a
ValueError also aborted every mod after it.

Run: python tools/test_mods_copy_instances.py
"""
import os
import sys
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import mods  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def run(src_mc, src_loader, dst_mc, dst_loader, **ids):
    records = {"downloads": []}

    def fake_list(mc, loader, version_id=None, *, profile_key=None):
        records["list"] = (mc, loader, version_id, profile_key)
        return [{"display_name": "Sodium", "slug": "sodium", "filename": "sodium.jar"},
                {"display_name": "Broken", "slug": "broken", "filename": "broken.jar"},
                {"display_name": "Lithium", "slug": "lithium", "filename": "lithium.jar"}]

    def fake_info(slug, mc_version=None, loader=None):
        return {"url": f"https://cdn.modrinth.com/data/{slug}", "filename": slug + ".jar",
                "version_number": "1.0", "hashes": {}}

    def fake_download(url, filename, progress_cb=None, slug=None, mc_version=None,
                      loader=None, hashes=None, project_id=None,
                      superseded_cb=None, preserve_existing=False,
                      version_id=None):
        records["downloads"].append({"slug": slug, "version_id": version_id})
        if slug == "broken":
            raise ValueError("A copy of this mod with that state already exists")
        return os.path.join("nowhere", filename)

    with patch.object(mods, "list_mods", fake_list), \
            patch.object(mods, "get_mod_download", fake_info), \
            patch.object(mods, "download_mod", fake_download):
        results = mods.copy_mods_between_profiles(
            src_mc, src_loader, dst_mc, dst_loader, **ids)

    return records, results


def main():
    # --- isolated instances: ids forwarded to both sides -------------------
    records, results = run("1.20.1", "fabric", "1.21", "fabric",
                           src_version_id="pack-src", dst_version_id="pack-dst")
    check("the SOURCE instance profile is read",
          records["list"][2] == "pack-src", str(records["list"]))
    check("the DESTINATION instance profile is written",
          [d["version_id"] for d in records["downloads"]]
          == ["pack-dst"] * 3, str(records["downloads"]))
    check("a broken download does not abort the rest",
          [r["status"] for r in results] == ["copied", "no_match", "copied"],
          str(results))

    # --- legacy callers keep working unchanged ----------------------------
    records, results = run("1.20.1", "fabric", "1.21", "fabric")
    check("the legacy shared profile is still the default",
          records["list"][2] is None
          and all(d["version_id"] is None for d in records["downloads"]),
          str(records))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
