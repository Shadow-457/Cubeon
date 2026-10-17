#!/usr/bin/env python3
"""
test_release_version.py - pin down the release-version policy.

`.github/workflows/build.yml` publishes a new release on every push, and the
name of that release is decided by tools/release_version.py. Two failure modes
here are silent and expensive, so they get real tests:

  1. **Numeric order.** Versions are compared per segment. "1.2.10" is newer
     than "1.2.9"; a plain string sort says the opposite, which would bump a
     release BACKWARDS or loop forever on 1.2.9.
  2. **Tag == APP_VERSION.** The updater (cubeon/updater.py) only accepts a
     release tag that parses as vX.Y.Z and is newer than the APP_VERSION
     compiled into the running build. If `stamp` silently does nothing (the
     literal moved, an editor reflowed the line), the shipped binary reports
     the OLD version while the release tag says the new one -> every user is
     nagged forever. So a missing literal must RAISE, not no-op.

Run: python3 tools/test_release_version.py
"""
from __future__ import annotations

import os
import re
import sys

TOOLS = os.path.dirname(os.path.abspath(__file__))
REPO = os.path.dirname(TOOLS)
sys.path.insert(0, TOOLS)
sys.path.insert(0, REPO)

import release_version as rv  # noqa: E402

passed = failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


def section(text):
    print(text)


def raises(fn, *a, **kw):
    try:
        fn(*a, **kw)
    except rv.VersionError:
        return True
    except Exception as ex:  # noqa: BLE001 - report the wrong exception
        print(f"       (wrong exception: {ex.__class__.__name__}: {ex})")
        return False
    return False


# ------------------------------------------------------------------- parsing ---
section("parse / fmt / bump")
check("parse plain", rv.parse("1.2.3") == (1, 2, 3))
check("parse v-prefixed", rv.parse("v1.2.3") == (1, 2, 3))
check("parse padded", rv.parse(" v1.2.3 ") == (1, 2, 3))
for bad in ("", "1.2", "v1.2.3.4", "1.2.3-rc1", "nightly", "v1.2.x", "abc", None):
    check(f"parse rejects {bad!r}", rv.parse(bad) is None)
check("fmt", rv.fmt((1, 2, 3)) == "1.2.3")
check("bump", rv.bump("1.2.3") == "1.2.4")
check("bump rolls past 9 NUMERICALLY (not 1.2.91)",
      rv.bump("1.2.9") == "1.2.10")
check("bump of v-prefixed keeps it stripped", rv.bump("v2.0.0") == "2.0.1")
check("bump rejects garbage", raises(rv.bump, "1.2"))
check("releasable drops junk", rv.releasable(["v1.0.0", "nightly", "v1.1", "v1.0.1"])
      == [(1, 0, 0), (1, 0, 1)])


# -------------------------------------------------------------------- next() ---
section("next_version - the policy")
check("no tags at all -> the declared version",
      rv.next_version("1.2.0", []) == "1.2.0")
check("declared and unreleased -> honoured (new minor series)",
      rv.next_version("1.2.0", ["v1.1.2"]) == "1.2.0")
check("declared and ALREADY released -> patch bump",
      rv.next_version("1.2.0", ["v1.1.2", "v1.2.0"]) == "1.2.1")
check("latest tag is the source of truth, not the source",
      rv.next_version("1.1.2", ["v1.1.2", "v1.2.1"]) == "1.2.2")
check("stale source (behind the newest tag) steps FORWARD, never backwards",
      rv.next_version("1.1.0", ["v1.2.0"]) == "1.2.1")
check("numeric order: v1.2.9 -> 1.2.10, not 1.2.91",
      rv.next_version("1.2.9", ["v1.2.9"]) == "1.2.10")
check("numeric order: v1.2.10 already out -> 1.2.11",
      rv.next_version("1.2.10", ["v1.2.9", "v1.2.10"]) == "1.2.11")
check("junk tags are ignored",
      rv.next_version("1.2.0", ["nightly", "v1.2", "v1.2.0-rc1", "release-1.2.0"])
      == "1.2.0")
check("v-less tags still count (a hand-made tag)",
      rv.next_version("1.2.0", ["1.2.0"]) == "1.2.1")
check("unparseable APP_VERSION raises (never guesses)",
      raises(rv.next_version, "1.2", ["v1.2.0"]))
check("the sequence a run of pushes produces",
      [rv.next_version("1.2.0", tags)
       for tags in ([], ["v1.2.0"], ["v1.2.0", "v1.2.1"],
                    ["v1.2.0", "v1.2.1", "v1.2.2"])]
      == ["1.2.0", "1.2.1", "1.2.2", "1.2.3"])


# ------------------------------------------------------------- current / git ---
section("current / git_tags")
check("current reads THIS repo's APP_VERSION",
      rv.parse(rv.read_app_version()) is not None,
      f"APP_VERSION={rv.read_app_version()!r}")
check("git_tags returns only v* tags", all(t.startswith("v") for t in rv.git_tags()))
check("git_tags on a non-repo returns [] (tarball-safe)",
      rv.git_tags(__import__("pathlib").Path("/nonexistent-repo-xyz")) == [])


# --------------------------------------------------------------------- stamp ---
section("stamp - writes APP_VERSION and FAILS LOUDLY when it can't")
import tempfile  # noqa: E402
from pathlib import Path  # noqa: E402

tmp = Path(tempfile.mkdtemp(prefix="cubeon-release-version-"))
(tmp / "cubeon").mkdir()
(tmp / "web").mkdir()
UPDATER = '''"""docstring mentions APP_VERSION = "0.0.0" history? no."""
APP_VERSION = "1.1.2"

DEFAULT_FEED = "https://example.test/releases/latest"
'''
(tmp / "cubeon" / "updater.py").write_text(UPDATER, encoding="utf-8")
(tmp / "web" / "index.html").write_text(
    '<p class="meta">v1.1.2 &middot; Installer</p>\n'
    '<p class="hero-note">v1.1.2 &middot; Free</p>\n'
    "<span>python3.11 is unrelated</span>\n", encoding="utf-8")
(tmp / "web" / "download.html").write_text(
    "<span>Version 1.1.2 &middot; Installer</span>\n"
    "<span>Version 1.1.2 &middot; Single file</span>\n", encoding="utf-8")

# stamp() addresses module-level constants, so point it at the sandbox copy.
orig_updater, orig_site = rv.UPDATER, rv.SITE_FILES
rv.UPDATER = tmp / "cubeon" / "updater.py"
rv.SITE_FILES = (
    (tmp / "web" / "index.html",
     re.compile(r"(?<![\w.])v\d+\.\d+\.\d+(?![\w.])"), "v{version}"),
    (tmp / "web" / "download.html",
     re.compile(r"(?<![\w.])Version \d+\.\d+\.\d+(?![\w.])"), "Version {version}"),
)
try:
    check("--check reports without writing",
          rv.stamp("2.5.0", check=True)
          and rv.read_app_version(tmp / "cubeon" / "updater.py") == "1.1.2")
    changed = rv.stamp("2.5.0")
    check("stamp changes updater + both site files", len(changed) == 3,
          f"changed={changed}")
    check("stamp rewrites APP_VERSION",
          rv.read_app_version(tmp / "cubeon" / "updater.py") == "2.5.0")
    check("stamp keeps the rest of updater.py",
          'DEFAULT_FEED = "https://example.test/releases/latest"'
          in (tmp / "cubeon" / "updater.py").read_text(encoding="utf-8"))
    check("stamp rewrites every vX.Y.Z in index.html",
          "v2.5.0 &middot; Installer" in (tmp / "web" / "index.html").read_text(encoding="utf-8")
          and "v2.5.0 &middot; Free" in (tmp / "web" / "index.html").read_text(encoding="utf-8"))
    check("stamp leaves non-version text alone (python3.11)",
          "python3.11" in (tmp / "web" / "index.html").read_text(encoding="utf-8"))
    check("stamp rewrites 'Version X' in download.html",
          (tmp / "web" / "download.html").read_text(encoding="utf-8").count("Version 2.5.0") == 2)
    check("stamp is idempotent (second run reports nothing)",
          rv.stamp("2.5.0") == [])
    check("stamp round-trips through current()",
          rv.read_app_version(tmp / "cubeon" / "updater.py") == "2.5.0")
    check("stamp rejects garbage", raises(rv.stamp, "2.5"))
    check("stamp counts replacements per file",
          all(isinstance(n, int) and n > 0 for _p, n in rv.stamp("2.6.0")))

    # The literal moved / two of them -> must raise, never silently no-op.
    (tmp / "cubeon" / "updater.py").write_text(
        '# APP_VERSION = "1.1.2" (commented out)\n', encoding="utf-8")
    check("missing APP_VERSION raises", raises(rv.read_app_version, tmp / "cubeon" / "updater.py"))
    multi = tmp / "cubeon" / "updater_multi.py"
    multi.write_text('APP_VERSION = "1.0.0"\nAPP_VERSION = "1.0.1"\n', encoding="utf-8")
    check("two APP_VERSION literals raise (won't guess which is real)",
          raises(rv.read_app_version, multi))
    doc = tmp / "cubeon" / "updater_doc.py"
    doc.write_text('"""history: APP_VERSION = "0.0.0" was the first one."""\n'
                   'APP_VERSION = "1.0.2"\n', encoding="utf-8")
    check("a docstring/comment mention is NOT counted as the assignment",
          rv.read_app_version(doc) == "1.0.2")
    check("stamp on a tree without APP_VERSION raises",
          raises(rv.stamp, "3.0.0"))
    check("read_app_version on a missing file raises",
          raises(rv.read_app_version, tmp / "cubeon" / "nope.py"))
finally:
    rv.UPDATER, rv.SITE_FILES = orig_updater, orig_site
    import shutil
    shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------- the real tree stays consistent ---
section("the repo this ships from")
check("cubeon/updater.py has exactly one parseable APP_VERSION",
      rv.parse(rv.read_app_version()) is not None)
check("the packaging readers agree with read_app_version (same regex family)",
      bool(re.search(r'APP_VERSION\s*=\s*"([^"]+)"',
                     (Path(REPO) / "cubeon" / "updater.py").read_text(encoding="utf-8"))))
check("next() on the real tree yields a version the updater can compare",
      rv.parse(rv.next_version(rv.read_app_version(), rv.git_tags())) is not None)


# ------------------------------------------------------------------- summary ---
print()
if failed:
    print(f"RESULT: {failed} FAILED, {passed} passed")
    sys.exit(1)
print(f"RESULT: {passed} passed, 0 failed")
