"""Interrupted-download integrity for Minecraft version installs - the
2026-09-17 report: "if my net goes mid way it still showed installed even
though its half corrupted".

mll's downloader has no resume and no checksums, and the version scan used
to treat ANY jar-bearing folder as complete. Locked-in behaviors:

  1. a truncated client jar (size != manifest size) is flagged incomplete
  2. a jar of garbage bytes (bad magic) is flagged incomplete
  3. a missing jar is flagged incomplete
  4. a good jar (exact size, PK magic, matching sha1) verifies clean
  5. loader profiles (inheritsFrom, no jar of their own) verify clean when
     the base version exists and its jar is whole
  6. install_version raises (instead of returning) when the installer
     "finished" into a corrupted jar, and cleans the partial jar up
  7. install_version cleans partial jars when the installer raises mid-run
  8. the scan checks the CANONICAL <version>.jar, never the first .jar
     os.listdir() happens to yield - a healthy decoy jar cannot mask a
     broken or absent client
  9. a failed install removes only what THAT attempt created or clobbered;
     pre-existing jars (previous valid client, unrelated hand-placed jar)
     survive untouched
  10. a loader profile with a missing or circular inheritsFrom base is
      flagged incomplete, never reported installed
  11. version metadata that is valid JSON but not an object (list/number)
      is tolerated - flagged incomplete, never crashing the scan
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
GOOD_JAR = b"PK" + b"\x00" * 998   # exactly the manifest's 1000-byte client


def make_version(vid, jar_bytes=None, manifest=None, inherits=None):
    os.makedirs(os.path.join(VERSIONS, vid), exist_ok=True)
    data = dict(MANIFEST if manifest is None else manifest)
    data["id"] = vid   # each version json names its own version
    if inherits:
        data["inheritsFrom"] = inherits
    with open(os.path.join(VERSIONS, vid, vid + ".json"), "w") as fh:
        json.dump(data, fh)
    if jar_bytes is not None:
        with open(os.path.join(VERSIONS, vid, vid + ".jar"), "wb") as fh:
            fh.write(jar_bytes)


def scan():
    return {v["id"]: v for v in V.get_installed_versions()}


# 1: truncated jar - the exact reported bug (net died mid-download)
make_version("truncated", jar_bytes=b"PK" + b"\x00" * 500)   # manifest says 1000
# 2: garbage jar - right size, wrong bytes (an HTML error page saved as .jar)
make_version("garbage", jar_bytes=b"<html>not a jar at all" + b"x" * 980)
# 3: missing jar entirely
make_version("nojar", jar_bytes=None)
# 4: good jar - exact size; sha1 checked separately below
make_version("good", jar_bytes=b"PK" + b"\x00" * 998)
# 5: loader profile - inheritsFrom, no jar of its own, base present and whole
make_version("1.20.1", jar_bytes=GOOD_JAR)
make_version("fabric-loader", jar_bytes=None, inherits="1.20.1")

installed = scan()
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
    installed = scan()
    check("and the scan no longer calls it installed",
          installed["netdeath"].get("incomplete") is True)
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

# L7: the integrity check must look at the canonical <version>.jar the
# launcher actually resolves, never the first .jar os.listdir() yields.
make_version("decoy", jar_bytes=b"PK" + b"\x00" * 500)   # canonical broken
with open(os.path.join(VERSIONS, "decoy", "unrelated.jar"), "wb") as fh:
    fh.write(GOOD_JAR)                                    # healthy decoy
make_version("onlydecoy", jar_bytes=None)                 # no canonical at all
with open(os.path.join(VERSIONS, "onlydecoy", "unrelated.jar"), "wb") as fh:
    fh.write(GOOD_JAR)
installed = scan()
check("a healthy decoy jar does not mask a broken canonical jar",
      installed["decoy"].get("incomplete") is True,
      str(installed["decoy"]))
check("a decoy jar cannot stand in for the absent canonical jar",
      installed["onlydecoy"].get("incomplete") is True,
      str(installed["onlydecoy"]))

# L8: loader profiles are only as complete as the base they inherit from.
make_version("fabric-orphan", jar_bytes=None, inherits="9.9.9")
make_version("cycle-a", jar_bytes=None, inherits="cycle-b")
make_version("cycle-b", jar_bytes=None, inherits="cycle-a")
installed = scan()
check("loader profile with a missing base is flagged incomplete",
      installed["fabric-orphan"].get("incomplete") is True,
      str(installed["fabric-orphan"]))
check("missing-base profile carries the human (incomplete) marker",
      installed["fabric-orphan"]["display_name"].endswith("(incomplete)"),
      installed["fabric-orphan"]["display_name"])
check("circular inheritsFrom is flagged, not hung or reported installed",
      installed["cycle-a"].get("incomplete") is True
      and installed["cycle-b"].get("incomplete") is True)

# L9: version metadata that is valid JSON but not an object must never
# crash the scan (it used to die on .get() against a list/int).
os.makedirs(os.path.join(VERSIONS, "listjson"), exist_ok=True)
with open(os.path.join(VERSIONS, "listjson", "listjson.json"), "w") as fh:
    json.dump([1, 2, 3], fh)
with open(os.path.join(VERSIONS, "listjson", "listjson.jar"), "wb") as fh:
    fh.write(GOOD_JAR)
os.makedirs(os.path.join(VERSIONS, "intjson"), exist_ok=True)
with open(os.path.join(VERSIONS, "intjson", "intjson.json"), "w") as fh:
    json.dump(42, fh)
make_version("weirddownloads", jar_bytes=GOOD_JAR,
             manifest={"downloads": ["not", "a", "dict"],
                       "id": "weirddownloads", "type": "release"})
scan_error = None
try:
    installed = scan()
except Exception as ex:
    scan_error = ex
check("non-object version json does not crash the scan", scan_error is None,
      repr(scan_error))
check("list-shaped version json is flagged incomplete",
      scan_error is None
      and installed["listjson"].get("incomplete") is True)
check("number-shaped version json is flagged incomplete",
      scan_error is None and installed["intjson"].get("incomplete") is True)
check("wrong-shape downloads field is flagged incomplete",
      scan_error is None
      and installed["weirddownloads"].get("incomplete") is True,
      str(installed.get("weirddownloads")))

# L6: a failed reinstall must only clean up its OWN files - never the
# previously valid client jar or unrelated hand-placed jars.
make_version("reinstall", jar_bytes=GOOD_JAR)
unrelated_path = os.path.join(VERSIONS, "reinstall", "unrelated.jar")
with open(unrelated_path, "wb") as fh:
    fh.write(b"PK" + b"\x00" * 40)


class _HandsOff:
    """Fake mll: dies mid-install WITHOUT touching the folder's jars."""

    class install:
        @staticmethod
        def install_minecraft_version(vid, mcdir, callback=None):
            os.makedirs(os.path.join(mcdir, "versions", vid), exist_ok=True)
            raise ConnectionError("network went away")


V.mll = _HandsOff
try:
    raised = None
    try:
        V.install_version("reinstall", lambda v: None, lambda t: None,
                          lambda m: None)
    except Exception as ex:
        raised = ex
    check("failed reinstall over an existing install still raises",
          raised is not None)
    check("failed reinstall keeps the previously valid client jar",
          os.path.getsize(os.path.join(VERSIONS, "reinstall",
                                       "reinstall.jar")) == 1000)
    check("failed reinstall keeps unrelated hand-placed jars",
          os.path.isfile(unrelated_path))
    check("failed reinstall leaves the version installed",
          scan()["reinstall"].get("incomplete") is None)
finally:
    V.mll = _real_mll


class _Clobber:
    """Fake mll: overwrites the existing client jar with a partial file
    before the net dies - the pre-attempt bytes are gone either way."""

    class install:
        @staticmethod
        def install_minecraft_version(vid, mcdir, callback=None):
            with open(os.path.join(mcdir, "versions", vid, vid + ".jar"),
                      "wb") as fh:
                fh.write(b"PK" + b"\x00" * 300)   # 300/1000 bytes, then death
            raise ConnectionError("network went away")


V.mll = _Clobber
try:
    try:
        V.install_version("reinstall", lambda v: None, lambda t: None,
                          lambda m: None)
    except Exception:
        pass
    check("a jar clobbered by the failed attempt is not left half-written",
          not os.path.isfile(os.path.join(VERSIONS, "reinstall",
                                          "reinstall.jar")))
    check("the unrelated hand-placed jar still survives the clobber",
          os.path.isfile(unrelated_path))
    check("and the clobbered version scans as incomplete",
          scan()["reinstall"].get("incomplete") is True)
finally:
    V.mll = _real_mll

for label, metadata in [
    ("client list", {"downloads": {"client": [1]}}),
    ("size list", {"downloads": {"client": {"size": [1000]}}}),
    ("size boolean", {"downloads": {"client": {"size": True}}}),
    ("sha1 number", {"downloads": {"client": {"sha1": 42}}}),
    ("url object", {"downloads": {"client": {"url": {}}}}),
    ("inherits list", {"inheritsFrom": []}),
]:
    check(f"malformed {label} is rejected without crashing",
          V._client_jar_problem(os.path.join(VERSIONS, "good"), metadata)
          is not None)

make_version("fabric-broken-base", inherits="truncated")
make_version("fabric-nested", inherits="fabric-loader")
for depth in range(V._MAX_INHERITS_DEPTH + 2):
    make_version(f"depth-{depth}", inherits=f"depth-{depth + 1}")
installed = scan()
check("loader verifies the truncated base rather than its own jar",
      installed["fabric-broken-base"].get("incomplete") is True)
check("nested loader chain with a valid base is complete",
      installed["fabric-nested"].get("incomplete") is None)
check("inheritance depth is bounded",
      installed["depth-0"].get("incomplete") is True)

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
