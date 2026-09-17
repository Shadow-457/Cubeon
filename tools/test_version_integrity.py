"""Interrupted-download integrity for Minecraft version installs - the
2026-09-17 report: "if my net goes mid way it still showed installed even
though its half corrupted".

mll's downloader has no resume and no checksums, and the version scan used
to treat ANY jar-bearing folder as complete. Locked-in behaviors:

  1. a truncated client jar (size != manifest size) is flagged incomplete
  2. a jar of garbage bytes (bad magic) is flagged incomplete
  3. a missing jar is flagged incomplete
  4. a good jar (exact size, PK magic, matching sha1) verifies clean
  5. loader profiles (inheritsFrom, no jar of their own) verify clean
  6. install_version raises (instead of returning) when the installer
     "finished" into a corrupted jar, and cleans the partial jar up
  7. install_version cleans partial jars when the installer raises mid-run
"""
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_home = tempfile.mkdtemp(prefix="cubeon-versions-test-")
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


def make_version(vid, jar_bytes=None, manifest=None, inherits=None):
    os.makedirs(os.path.join(VERSIONS, vid), exist_ok=True)
    data = dict(MANIFEST if manifest is None else manifest)
    if inherits:
        data["inheritsFrom"] = inherits
    with open(os.path.join(VERSIONS, vid, vid + ".json"), "w") as fh:
        json.dump(data, fh)
    if jar_bytes is not None:
        with open(os.path.join(VERSIONS, vid, vid + ".jar"), "wb") as fh:
            fh.write(jar_bytes)


# 1: truncated jar - the exact reported bug (net died mid-download)
make_version("truncated", jar_bytes=b"PK" + b"\x00" * 500)   # manifest says 1000
# 2: garbage jar - right size, wrong bytes (an HTML error page saved as .jar)
make_version("garbage", jar_bytes=b"<html>not a jar at all" + b"x" * 980)
# 3: missing jar entirely
make_version("nojar", jar_bytes=None)
# 4: good jar - exact size; sha1 checked separately below
make_version("good", jar_bytes=b"PK" + b"\x00" * 998)
# 5: loader profile - inheritsFrom, no jar of its own
make_version("fabric-loader", jar_bytes=None, inherits="1.20.1")

installed = {v["id"]: v for v in V.get_installed_versions()}
check("truncated jar is flagged incomplete",
      installed["truncated"].get("incomplete") is True,
      str(installed["truncated"]))
check("truncated issue mentions the interruption",
      "interrupted" in installed["truncated"].get("issue", "").lower())
check("garbage jar is flagged incomplete",
      installed["garbage"].get("incomplete") is True)
check("missing jar is flagged incomplete",
      installed["nojar"].get("incomplete") is True)
check("good jar is NOT flagged", installed["good"].get("incomplete") is None)
check("loader profile (inheritsFrom) is NOT flagged",
      installed["fabric-loader"].get("incomplete") is None)

# The integrity checker directly, including the sha1 leg.
import hashlib
ok = V._client_jar_problem(os.path.join(VERSIONS, "good"), MANIFEST,
                           want_sha1=True)
check("sha1 leg: mismatching hash is caught", ok is not None, str(ok))
good_manifest = {"downloads": {"client": {"size": 1000,
                 "sha1": hashlib.sha1(b"PK" + b"\x00" * 998).hexdigest()}},
                 "id": "good", "type": "release"}
ok = V._client_jar_problem(os.path.join(VERSIONS, "good"), good_manifest,
                           want_sha1=True)
check("sha1 leg: matching hash verifies clean", ok is None, str(ok))


class _Boom:
    """Fake mll: the downloader dies mid-install (net death)."""

    class install:
        @staticmethod
        def install_minecraft_version(vid, mcdir, callback=None):
            os.makedirs(os.path.join(mcdir, "versions", vid), exist_ok=True)
            with open(os.path.join(mcdir, "versions", vid, vid + ".json"),
                      "w") as fh:
                json.dump(MANIFEST, fh)
            with open(os.path.join(mcdir, "versions", vid, vid + ".jar"),
                      "wb") as fh:
                fh.write(b"PK" + b"\x00" * 300)   # dies at 300/1000 bytes
            raise ConnectionError("network went away")


_real_mll = V.mll
try:
    V.mll = _Boom
    raised = None
    try:
        V.install_version("netdeath", lambda v: None, lambda t: None,
                          lambda m: None)
    except Exception as ex:
        raised = ex
    check("net death mid-install raises instead of 'succeeding'",
          raised is not None, "no exception!")
    check("the error is human-readable",
          raised is not None and "interrupted" in str(raised).lower(),
          str(raised))
    check("partial jar is cleaned up after the failure",
          not os.path.isfile(os.path.join(VERSIONS, "netdeath",
                                          "netdeath.jar")))
    scan = {v["id"]: v for v in V.get_installed_versions()}
    check("and the scan no longer calls it installed",
          scan["netdeath"].get("incomplete") is True)
finally:
    V.mll = _real_mll


class _Liar:
    """Fake mll: the downloader returns 'success' but wrote a corrupt jar."""

    class install:
        @staticmethod
        def install_minecraft_version(vid, mcdir, callback=None):
            os.makedirs(os.path.join(mcdir, "versions", vid), exist_ok=True)
            with open(os.path.join(mcdir, "versions", vid, vid + ".json"),
                      "w") as fh:
                json.dump(MANIFEST, fh)
            with open(os.path.join(mcdir, "versions", vid, vid + ".jar"),
                      "wb") as fh:
                fh.write(b"PK" + b"\x00" * 999)   # wrong size, no error


V.mll = _Liar
try:
    raised = None
    try:
        V.install_version("liar", lambda v: None, lambda t: None,
                          lambda m: None)
    except Exception as ex:
        raised = ex
    check("corrupted-but-'successful' install is rejected", raised is not None)
    check("and its partial jar is removed too",
          not os.path.isfile(os.path.join(VERSIONS, "liar", "liar.jar")))
finally:
    V.mll = _real_mll

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
