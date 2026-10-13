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
else start with the MC version and keep using the first group.

NeoForge numbers ITSELF after the game ("neoforge-21.1.99" is the 99th
NeoForge build for Minecraft 1.21.1), so the bare number is not an MC
version. It resolves through the install's own inheritsFrom; with no folder
on disk the id is left alone rather than guessed at, since the 1.20.1-era
"neoforge-47.x" numbering cannot be recovered arithmetically.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

from cubeon.mods import profile_key  # noqa: E402
from cubeon.paths import MINECRAFT_DIR  # noqa: E402
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

print("\n3. neoforge resolves via its own inheritsFrom, never by arithmetic")
# NeoForge numbers itself after the game, so "neoforge-21.1.99" is the 99th
# build for 1.21.1. The bare number is NOT a Minecraft version: returning it
# pointed the Mods tab at an empty profile and made find_installed_loader_
# version() fail to see the install at all. The real answer is the install's
# own inheritsFrom.
check("neoforge with no folder on disk is left alone",
      ex("neoforge-21.1.99") == "neoforge-21.1.99",
      f"got {ex('neoforge-21.1.99')!r}")

_nversions = os.path.join(MINECRAFT_DIR, "versions", "neoforge-21.1.99")
os.makedirs(_nversions, exist_ok=True)
with open(os.path.join(_nversions, "neoforge-21.1.99.json"), "w", encoding="utf-8") as _fh:
    json.dump({"id": "neoforge-21.1.99", "inheritsFrom": "1.21.1"}, _fh)
check("neoforge on disk resolves to its inherited base (1.21.1, not 21.1.99)",
      ex("neoforge-21.1.99") == "1.21.1", f"got {ex('neoforge-21.1.99')!r}")
check("neoforge row key == base row key",
      profile_key(ex("neoforge-21.1.99"), "neoforge")
      == profile_key("1.21.1", "neoforge"),
      f"got {profile_key(ex('neoforge-21.1.99'), 'neoforge')!r}")

print("\n4. profile keys agree between the base row and its loader row")
check("fabric row key == base row key",
      profile_key(ex("fabric-loader-0.19.5-26.1.2"), "fabric")
      == profile_key("26.1.2", "fabric"),
      f"got {profile_key(ex('fabric-loader-0.19.5-26.1.2'), 'fabric')!r}")

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
