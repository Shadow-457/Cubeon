"""The mod sidecar merges its fields, and an update is recognised as the same mod (9.6).

`_write_meta()` built a fresh dict from only the arguments it was given, so a
caller that knew the slug but not the project id (browse download) erased a
project id recorded earlier (pack install), and vice versa - and the `url`
needed by `export_mrpack()` disappeared the same way. Once an identical mod in
the profile lost one of its two ids, `find_other_copies()` could no longer match
it strongly, so `supersede_older_copies()` left the old build behind (as a
`.disabled` jar) instead of replacing it.

Locked-in behaviour:
  * `_write_meta` keeps every field it was not given, and updates those it was;
  * a call with nothing new does not touch the file;
  * `download_mod` fills in the missing Modrinth id (best effort) before writing
    and before dedup, so an older copy is recognised via the project id even
    when the download only carried the slug.

Run: python tools/test_mod_meta_merge.py
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


MC, LOADER = "1.20.1", "fabric"


def main():
    profile = mods.get_profile_dir(MC, LOADER)

    # --- merging sidecar fields --------------------------------------------
    with open(os.path.join(profile, "sodium.jar"), "wb") as fh:
        fh.write(b"jar")
    mods.record_mod_source(profile, "sodium.jar", slug="sodium",
                           project_id="AANobbMI", url="https://cdn/sodium")
    # What a slug-only caller (browse download) does.
    mods._write_meta(profile, "sodium.jar", "sodium")
    meta = mods._read_meta(profile, "sodium.jar") or {}
    check("a slug-only write keeps the project id",
          meta.get("project_id") == "AANobbMI", str(meta))
    check("a slug-only write keeps the url",
          meta.get("url") == "https://cdn/sodium", str(meta))
    check("the slug is still recorded", meta.get("slug") == "sodium", str(meta))

    # ...and the reverse: a project-id-only caller must not erase the slug.
    mods._write_meta(profile, "sodium.jar", None, project_id="AANobbMI")
    meta = mods._read_meta(profile, "sodium.jar") or {}
    check("a project-id-only write keeps the slug",
          meta.get("slug") == "sodium", str(meta))

    # Nothing new: leave the file exactly as it is.
    before = open(os.path.join(profile, "sodium.jar.cubeon.json"), "rb").read()
    mods._write_meta(profile, "sodium.jar", None)
    after = open(os.path.join(profile, "sodium.jar.cubeon.json"), "rb").read()
    check("a write with no identity leaves the sidecar alone", before == after)

    # --- the duplicate is recognised through the resolved id ---------------
    # An older pack-installed copy knows only its project id...
    with open(os.path.join(profile, "sodium-0.6.0.jar"), "wb") as fh:
        fh.write(b"old")
    mods.record_mod_source(profile, "sodium-0.6.0.jar", slug=None,
                           project_id="AANobbMI")
    old_meta = mods._read_meta(profile, "sodium-0.6.0.jar") or {}
    check("the old copy has no slug, only a project id",
          old_meta.get("slug") is None and old_meta.get("project_id") == "AANobbMI",
          str(old_meta))

    # ...and the new download carries only the slug.
    def fake_fetch(dest, fetch_fn, hashes):
        with open(dest, "wb") as fh:
            fh.write(b"new")

    asked = []

    def fake_details(ref):
        asked.append(ref)
        return {"slug": "sodium", "project_id": "AANobbMI"}

    with patch.object(mods.global_mod_cache, "get_or_fetch", fake_fetch), \
            patch.object(mods, "get_mod_details", fake_details):
        mods.download_mod("https://cdn.modrinth.com/data/AANobbMI/versions/x/"
                          "sodium-0.5.0.jar", "sodium-0.5.0.jar",
                          slug="sodium", mc_version=MC, loader=LOADER)

    new_meta = mods._read_meta(profile, "sodium-0.5.0.jar") or {}
    check("the new sidecar records both ids",
          new_meta.get("slug") == "sodium"
          and new_meta.get("project_id") == "AANobbMI", str(new_meta))
    check("the missing id is looked up once", asked == ["sodium"], str(asked))
    check("the older copy is replaced, not just disabled",
          not os.path.exists(os.path.join(profile, "sodium-0.6.0.jar"))
          and not os.path.exists(os.path.join(profile, "sodium-0.6.0.jar.disabled")),
          str(sorted(os.listdir(profile))))

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
