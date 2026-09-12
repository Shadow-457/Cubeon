"""
Offline regression suite for the version-list network path
(cubeon/versions.py MANIFEST_URLS / _download_manifest / _manifest).

The bug: the version list came straight from minecraft_launcher_lib's
get_version_list(), a single bare requests.get with no timeout, no retry and
no mirror. On a machine where one Mojang hostname was DNS-blocked or the TLS
handshake stalled, the whole list failed and the user was told "No internet"
while every other app worked. Two fixes are pinned here:

  1. Both Mojang hostnames are tried (piston-meta first, launchermeta as the
     alias) before anything is declared offline.
  2. The last good manifest is cached on disk and served when both mirrors
     fail, so a transient outage doesn't empty the list.

No real network: versions.net.get_with_retry is stubbed.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

import cubeon.versions as versions  # noqa: E402
from cubeon import local_cache  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


MANIFEST = {
    "latest": {"release": "1.21.11", "snapshot": "26w45a"},
    "versions": [
        {"id": "1.21.11", "type": "release"},
        {"id": "1.20.1", "type": "release"},
        {"id": "26w45a", "type": "snapshot"},
        {"id": "a1.2.6", "type": "old_alpha"},
    ],
}


class FakeResp:
    def __init__(self, data):
        self._data = data

    def json(self):
        return self._data

    def close(self):
        pass


def _clear_cache():
    local_cache._MEM.clear()
    local_cache._INFLIGHT.clear()


print("1. both Mojang mirrors are tried before giving up")
seen = []


def _net_second_only(url, **kw):
    seen.append(url)
    if url == versions.MANIFEST_URLS[0]:
        raise ConnectionError("primary host blocked")
    return FakeResp(MANIFEST)


versions.net.get_with_retry = _net_second_only
got = versions._download_manifest()
check("fell through to the alias mirror", got == MANIFEST, f"got {got!r}")
check("tried the primary first", seen and seen[0] == versions.MANIFEST_URLS[0],
      f"seen={seen}")
check("tried the alias second",
      len(seen) == 2 and seen[1] == versions.MANIFEST_URLS[1], f"seen={seen}")

print("\n2. a manifest with no versions is rejected, not returned")


def _net_empty(url, **kw):
    return FakeResp({"latest": {}, "versions": []})


versions.net.get_with_retry = _net_empty
try:
    versions._download_manifest()
    check("empty manifest raises", False)
except Exception as ex:
    check("empty manifest raises", True, f"got {ex!r}")

print("\n3. get_available_versions filters by type from the cached manifest")
_clear_cache()
versions._download_manifest = lambda: MANIFEST


def _raise(*a, **kw):
    raise AssertionError("network should not be touched")


versions.net.get_with_retry = _raise
releases = versions.get_available_versions()
check("release list default", [v["id"] for v in releases] == ["1.21.11", "1.20.1"],
      f"got {releases!r}")
snaps = versions.get_available_versions(include_snapshots=True)
check("snapshots opt-in includes the snapshot",
      "26w45a" in [v["id"] for v in snaps], f"got {snaps!r}")
olds = versions.get_available_versions(include_old=True)
check("old versions opt-in includes the alpha",
      "a1.2.6" in [v["id"] for v in olds], f"got {olds!r}")
check("latest release reads from the manifest",
      versions.get_latest_release() == "1.21.11")

print("\n4. a failed fetch falls back to the last cached manifest")


def _boom(*a, **kw):
    raise ConnectionError("both mirrors down")


versions._download_manifest = _boom
versions.net.get_with_retry = _boom
_clear_cache()
# Seed a STALE on-disk copy (time 0 == 1970 -> older than the 1h max_age).
path = local_cache._path("mojang_manifest", "v2")
os.makedirs(os.path.dirname(path), exist_ok=True)
with open(path, "w", encoding="utf-8") as fh:
    json.dump({"time": 0, "value": MANIFEST}, fh)

got = versions.get_available_versions()
check("stale manifest served instead of an error",
      [v["id"] for v in got] == ["1.21.11", "1.20.1"], f"got {got!r}")

print("\n5. no cache and no network raises (caller shows the offline notice)")
_clear_cache()
try:
    os.unlink(path)
except OSError:
    pass
try:
    versions.get_available_versions()
    check("raises with nothing cached", False)
except Exception:
    check("raises with nothing cached", True)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
