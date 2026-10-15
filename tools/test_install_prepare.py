"""
Offline suite for "it prepares for a long time" when installing an instance.

Two silent waits sat between clicking DOWNLOAD and the first progress callback:

  1. mll's own install_minecraft_version() checks for
     versions/<id>/<id>.json and, when it is missing, starts with a bare,
     un-timed requests.get() of Mojang's ~4 MB version_manifest_v2.json - no
     status, no progress, no timeout, no retry. On a slow link that is a long
     frozen "Preparing" on the first install of every version, and on a flaky
     one it can hang outright. cubeon/versions.py now seeds that one small file
     from the manifest Cubeon already keeps cached (mirrored, retried, served
     stale), where progress and cancellation work, so mll goes straight to the
     libraries/assets phases.

  2. A version selected in the dropdown is prefetched invisibly in the
     background, and a Play click shares that install lock - so the click waited
     behind a frozen "Preparing" for the whole remaining download. The prefetch
     now publishes its progress (main.py _prefetch_view) and the click paints
     from it while it waits.

The contract pinned here is only about (1): the json is on disk BEFORE mll is
called, the fetch uses the cached manifest's url + sha1, the user is told what
is happening first, and every failure mode falls back to mll rather than
failing the install.
"""
import hashlib
import json
import os
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_home = tempfile.mkdtemp(prefix="cubeon-prepare-test-")
os.environ["HOME"] = _home
os.environ["USERPROFILE"] = _home
os.environ["CUBEON_GAME_DIR"] = os.path.join(_home, "game")

from cubeon import versions as V  # noqa: E402  (after the env isolation)
from cubeon import net as net_mod  # noqa: E402

passed = failed = 0


def check(label, ok, extra=""):
    global passed, failed
    passed += ok
    failed += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not ok else ''}")


# --- fixtures --------------------------------------------------------------
JAR = b"PK\x03\x04" + b"\x00" * 4092          # a client jar the post-check accepts
JAR_SHA = hashlib.sha1(JAR).hexdigest()
JSON_BODY = json.dumps({
    "id": "1.20.1",
    "downloads": {"client": {"size": len(JAR), "sha1": JAR_SHA,
                             "url": "https://example.invalid/client.jar"}},
}).encode()
JSON_SHA = hashlib.sha1(JSON_BODY).hexdigest()
JSON_URL = "https://piston-meta.mojang.com/v1/packages/abc/1.20.1.json"

CALLS = {"downloads": [], "status": [], "mll_saw_json": None}


def fake_manifest():
    CALLS["status"].append("<manifest lookup>")
    return {"versions": [{"id": "1.20.1", "url": JSON_URL, "sha1": JSON_SHA}]}


def fake_download_to(dest_path, url, **kw):
    CALLS["downloads"].append((url, kw.get("expected_hash")))
    with open(dest_path, "wb") as fh:
        fh.write(JSON_BODY)
    return len(JSON_BODY)


def fake_install_minecraft_version(version, mcdir, callback=None):
    """Stands in for mll: records whether the version json was already there
    (the whole point) and writes the client jar the post-check verifies."""
    folder = os.path.join(mcdir, "versions", version)
    CALLS["mll_saw_json"] = os.path.isfile(os.path.join(folder,
                                                       version + ".json"))
    with open(os.path.join(folder, version + ".jar"), "wb") as fh:
        fh.write(JAR)


# ---------------------------------------------------------------------------
print("\n1. install_version hands mll a version json that is already on disk")
# ---------------------------------------------------------------------------
_real_mll, _real_manifest, _real_download_to = V.mll, V._manifest, net_mod.download_to
V.mll = types.SimpleNamespace(
    install=types.SimpleNamespace(
        install_minecraft_version=fake_install_minecraft_version))
V._manifest = fake_manifest
net_mod.download_to = fake_download_to
try:
    V.install_version("1.20.1", lambda v: None, CALLS["status"].append,
                      lambda m: None)
finally:
    V.mll, V._manifest, net_mod.download_to = (_real_mll, _real_manifest,
                                               _real_download_to)

check("mll never has to fetch Mojang's manifest itself - the json is waiting",
      CALLS["mll_saw_json"] is True, f"mll_saw_json={CALLS['mll_saw_json']}")
check("the json came from the cached manifest's own url + sha1",
      CALLS["downloads"] == [(JSON_URL, ("sha1", JSON_SHA))],
      f"{CALLS['downloads']}")
check("the user is told what is happening before the manifest lookup",
      "Fetching the version files" in CALLS["status"]
      and CALLS["status"].index("Fetching the version files")
      < CALLS["status"].index("<manifest lookup>"),
      f"{CALLS['status']}")

# ---------------------------------------------------------------------------
print("\n2. every failure mode falls back to mll instead of breaking the install")
# ---------------------------------------------------------------------------
status = []
tmp = tempfile.mkdtemp(prefix="cubeon-seed-")
folder = os.path.join(tmp, "1.20.1")
json_path = os.path.join(folder, "1.20.1.json")
os.makedirs(folder)


def _seed(manifest_result, download):
    global V
    real_m, real_d = V._manifest, net_mod.download_to
    V._manifest = lambda: manifest_result
    net_mod.download_to = download
    try:
        V._seed_version_json("1.20.1", folder, json_path, status.append,
                             lambda m: None, lambda v: None)
    finally:
        V._manifest, net_mod.download_to = real_m, real_d


# (a) a version the cached manifest doesn't know (a snapshot, a renamed id)
_calls = []


def _never(dest, url, **kw):
    _calls.append(url)
    raise AssertionError("must not download an unknown version")


_seed({"versions": [{"id": "1.20.5", "url": "x"}]}, _never)
check("an unknown version is left entirely to mll", not _calls)

# (b) the download itself fails (offline, bad checksum, ...)
def _failing(dest, url, **kw):
    with open(dest + ".part", "wb") as fh:
        fh.write(b"half")
    raise net_mod.DownloadError("simulated transfer failure")


_seed({"versions": [{"id": "1.20.1", "url": JSON_URL, "sha1": JSON_SHA}]}, _failing)
check("a failed seed doesn't raise into the install",
      not os.path.isfile(json_path))
check("a failed seed leaves no .part file for mll to read",
      not os.path.isfile(json_path + ".part"),
      f"{os.listdir(folder)}")

# (c) the json is already there - don't touch the network at all
with open(json_path, "wb") as fh:
    fh.write(JSON_BODY)
_seed({"versions": [{"id": "1.20.1", "url": JSON_URL, "sha1": JSON_SHA}]},
      _never)
check("an already-seeded version is not re-fetched",
      os.path.isfile(json_path))

print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
