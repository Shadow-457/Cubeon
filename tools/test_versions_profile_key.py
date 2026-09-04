"""
Offline regression suite for launch-id -> (numeric MC version, profile key)
resolution (cubeon/versions.py extract_mc_version + cubeon/mods.py profile_key).

The bug: a canonical loader install id like "fabric-loader-0.19.5-26.1.2"
appears as its own row in the Play-tab version dropdown. extract_mc_version()
grabbed the FIRST numeric group (0.19.5 - the FABRIC loader version, not the
MC version), so selecting that row pointed the Mods tab and launch-time sync
at profile "0.19.5-fabric" - an empty folder - while the real mods lived in
"26.1.2-fabric". The wrong key even persisted via cfg["last_version"], so
every later launch kept syncing from the empty profile.

Fabric/Quilt loader ids lead with the loader's own version, so the MC version
is the TRAILING numeric group. Forge ids ("1.20.1-forge-47.2.0") and everything
else start with the MC version and keep using the first group. NeoForge's
own versioning ("neoforge-21.1.99") has no decodable MC number and is left
untouched.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

from cubeon.mods import profile_key  # noqa: E402
from cubeon.versions import extract_mc_version as ex  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


print("1. canonical loader rows resolve to the MC version (trailing group)")
for raw, expected in [
    ("fabric-loader-0.19.5-26.1.2", "26.1.2"),
    ("fabric-loader-0.19.3-1.21.11", "1.21.11"),
    ("quilt-loader-0.25.0-1.20.1", "1.20.1"),
]:
    got = ex(raw)
    check(f"{raw!r} -> {expected!r}",
          got == expected, f"got {got!r}")

print("\n2. MC-first ids keep first-group behaviour")
for raw, expected in [
    ("1.20.1-forge-47.2.0", "1.20.1"),
    ("26.1.2", "26.1.2"),
    ("1.21.8", "1.21.8"),
    ("1.21.1-neoforge-21.1.99", "1.21.1"),
    ("Boosted FPS Fabric-26.2-1.7.4", "26.2"),
    ("", ""),
]:
    got = ex(raw)
    check(f"{raw!r} -> {expected!r}",
          got == expected, f"got {got!r}")

print("\n3. neoforge's own versioning is preserved (not decodable)")
check("neoforge-21.1.99 -> 21.1.99 (unchanged)",
      ex("neoforge-21.1.99") == "21.1.99", f"got {ex('neoforge-21.1.99')!r}")

print("\n4. profile keys agree between the base row and its loader row")
check("fabric row key == base row key",
      profile_key(ex("fabric-loader-0.19.5-26.1.2"), "fabric")
      == profile_key("26.1.2", "fabric"),
      f"got {profile_key(ex('fabric-loader-0.19.5-26.1.2'), 'fabric')!r}")

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
