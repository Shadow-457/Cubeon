"""The launch path must not wait out the interactive network policy.

Every ensure-step in `launch_game` that can reach Modrinth resolves a version
file first. That lookup used the UI policy (10 s per try, 3 tries, 1.5 s + 3 s
backoff). Measured on a blackholed route with an empty cache:

    one lookup, old policy   34.68 s
    one lookup, launch path   3.14 s   (3 s connect, one attempt)
    perf mods (6 lookups)     3.14 s   after the dead-route short-circuit
    csl + fabric api + perf   9.15 s   total, was ~278 s

Locked-in behaviour:
  1. get_mod_download() forwards timeout/attempts, defaults unchanged
  2. the cache key is unaffected - both policies share one cache entry
  3. csl.install / ensure_fabric_api / perf_mods use LAUNCH_LOOKUP_*
  4. perf_mods stops probing after a connection-level failure, but a server
     that answered (HTTP error) does not stop it
  5. nothing is skipped that decides whether the game can start

Run: python tools/test_launch_lookup_budget.py
"""
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


import cubeon.mods as mods  # noqa: E402

# The lookup cache is 24 h on disk, so a fixed probe id would be a cache HIT on
# the second run of this script and no request would reach the fake transport.
PROBE = f"probe-{os.getpid()}"
import cubeon.net as net  # noqa: E402
import cubeon.perf_mods as perf_mods  # noqa: E402
import cubeon.csl as csl  # noqa: E402
import cubeon.cubeonfriends as cubeonfriends  # noqa: E402

print("1. get_mod_download forwards its network policy")
seen = []


def fake_get_json(url, **kw):
    seen.append(kw)
    return []


real_get_json = net.get_json
net.get_json = fake_get_json
try:
    mods.get_mod_download(PROBE + "-a", mc_version="1.21.11", loader="fabric")
    check("defaults keep the interactive policy",
          seen[-1]["timeout"] == 10 and seen[-1]["attempts"] == net.DEFAULT_ATTEMPTS,
          repr(seen[-1]))
    mods.get_mod_download(PROBE + "-b", mc_version="1.21.11", loader="fabric",
                          timeout=mods.LAUNCH_LOOKUP_TIMEOUT,
                          attempts=mods.LAUNCH_LOOKUP_ATTEMPTS)
    check("the launch policy reaches net.get_json",
          seen[-1]["timeout"] == mods.LAUNCH_LOOKUP_TIMEOUT
          and seen[-1]["attempts"] == 1, repr(seen[-1]))
    check("the launch policy is one short connect, generous read",
          mods.LAUNCH_LOOKUP_TIMEOUT == (3, 10)
          and mods.LAUNCH_LOOKUP_ATTEMPTS == 1)

    # Both policies must see ONE cache entry, or a launch lookup would miss the
    # UI's cached answer (and vice versa) for the same mod.
    calls = []
    net.get_json = lambda url, **kw: (calls.append(kw), [])[1]
    mods.get_mod_download(PROBE + "-c", mc_version="1.21.11", loader="fabric",
                          timeout=mods.LAUNCH_LOOKUP_TIMEOUT, attempts=1)
    mods.get_mod_download(PROBE + "-c", mc_version="1.21.11", loader="fabric")
    check("the cache key ignores the policy (one shared entry)",
          len(calls) == 1, f"{len(calls)} fetches")
finally:
    net.get_json = real_get_json

print()
print("2. every launch-path caller asks for the bounded lookup")
grabbed = {}


def recorder(name):
    def call(slug, **kw):
        grabbed[name] = kw
        return None                      # "no build": stop before any download
    return call


real_csl = csl.get_mod_download
csl.get_mod_download = recorder("csl")
try:
    csl.install("1.21.11", "fabric")
finally:
    csl.get_mod_download = real_csl
check("csl.install passes the launch policy",
      grabbed.get("csl", {}).get("timeout") == mods.LAUNCH_LOOKUP_TIMEOUT
      and grabbed.get("csl", {}).get("attempts") == mods.LAUNCH_LOOKUP_ATTEMPTS,
      repr(grabbed.get("csl")))

real_cf = cubeonfriends.fabric_api_installed
cubeonfriends.fabric_api_installed = lambda *a, **k: False
real_mods_dl = mods.get_mod_download
mods.get_mod_download = recorder("fabric_api")
try:
    cubeonfriends.ensure_fabric_api("1.21.11", "fabric", version_id="x")
finally:
    mods.get_mod_download = real_mods_dl
    cubeonfriends.fabric_api_installed = real_cf
check("ensure_fabric_api passes the launch policy",
      grabbed.get("fabric_api", {}).get("timeout") == mods.LAUNCH_LOOKUP_TIMEOUT
      and grabbed.get("fabric_api", {}).get("attempts") == mods.LAUNCH_LOOKUP_ATTEMPTS,
      repr(grabbed.get("fabric_api")))

real_pp = perf_mods.get_mod_download
real_present = perf_mods._present
calls = 0


def counted(slug, **kw):
    global calls
    calls += 1
    grabbed["perf"] = kw
    return None


perf_mods.get_mod_download = counted
perf_mods._present = lambda *a, **k: set()
try:
    result = perf_mods.ensure_installed("1.21.11", "fabric", version_id="x")
finally:
    perf_mods.get_mod_download = real_pp
    perf_mods._present = real_present
check("perf_mods.ensure_installed passes the launch policy",
      grabbed.get("perf", {}).get("timeout") == mods.LAUNCH_LOOKUP_TIMEOUT
      and grabbed.get("perf", {}).get("attempts") == mods.LAUNCH_LOOKUP_ATTEMPTS,
      repr(grabbed.get("perf")))
check("a lookup that finds no build still marks the mod failed",
      len(result["failed"]) == len(perf_mods.PERF_MODS)
      and result["installed"] == [],
      repr(result["failed"]))

print()
print("3. a dead route is probed once, not once per mod")


def raising(exc):
    def call(slug, **kw):
        raise exc
    return call


perf_mods._present = lambda *a, **k: set()
perf_mods.get_mod_download = raising(net.DownloadError("no route"))
try:
    result = perf_mods.ensure_installed("1.21.11", "fabric", version_id="x")
finally:
    perf_mods._present = real_present
    perf_mods.get_mod_download = real_pp
check("one connection failure marks every mod failed",
      sorted(result["failed"]) == sorted(s for s, _p, _l in perf_mods.PERF_MODS),
      repr(result["failed"]))
check("... and the launch still returns a normal result dict",
      set(result) == {"installed", "kept", "failed", "detail"})

tabulated = []


def raise302(slug, **kw):
    tabulated.append(slug)
    raise net.HTTPStatusError("HTTP 404 for x", 404, "u")


perf_mods._present = lambda *a, **k: set()
perf_mods.get_mod_download = raise302
try:
    result = perf_mods.ensure_installed("1.21.11", "fabric", version_id="x")
finally:
    perf_mods._present = real_present
    perf_mods.get_mod_download = real_pp
check("an HTTP error (server answered) does NOT stop the other lookups",
      len(tabulated) == len(perf_mods.PERF_MODS), f"{len(tabulated)} lookups")
check("... and all of them are reported failed",
      len(result["failed"]) == len(perf_mods.PERF_MODS),
      repr(result["failed"]))

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
