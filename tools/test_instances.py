"""
Offline suite for cubeon/instances.py - the single source of truth for
"what loader does this install have, how many mods, how big, when did I
last play it" that the Play tab's richer cards and Instances manager render.

No network, no real HOME: everything is created in a throwaway sandbox.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

from cubeon import instances  # noqa: E402
from cubeon.paths import MINECRAFT_DIR, PROFILES_DIR  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


print("1. loader detection is whole-word (forge never matches neoforge)")
for raw, expected in [
    ("1.20.1", "vanilla"),
    ("1.21.11", "vanilla"),
    ("fabric-loader-0.19.5-26.1.2", "fabric"),
    ("quilt-loader-0.25.0-1.20.1", "quilt"),
    ("1.20.1-forge-47.2.0", "forge"),
    ("neoforge-21.1.99", "neoforge"),
    ("1.21.1-neoforge-21.1.99", "neoforge"),
    ("Boosted FPS Fabric-26.2-1.7.4", "fabric"),
]:
    got = instances.detect_loader(raw)
    check(f"{raw!r} -> {expected!r}", got == expected, f"got {got!r}")

check("optifine is its own tag", instances.detect_loader("1.20.1-OptiFine_HD_U_I6") == "optifine")

print("\n2. size formatting")
for n, expected in [(None, ""), (0, "0 B"), (512, "512 B"),
                    (1024, "1.0 KB"), (1536, "1.5 KB"),
                    (1024**3, "1.0 GB")]:
    got = instances.format_size(n)
    check(f"{n!r} -> {expected!r}", got == expected, f"got {got!r}")

print("\n3. describe() joins id + meta + nickname")
versions_dir = os.path.join(MINECRAFT_DIR, "versions")
for vid, base in [("1.21.11", "1.21.11"),
                  ("fabric-loader-0.19.5-26.1.2", "26.1.2")]:
    folder = os.path.join(versions_dir, vid)
    os.makedirs(folder, exist_ok=True)
    with open(os.path.join(folder, vid + ".json"), "w", encoding="utf-8") as fh:
        json.dump({"id": vid}, fh)
    with open(os.path.join(folder, vid + ".jar"), "wb") as fh:
        fh.write(b"x" * 2048)

# A fabric profile with two mods, one disabled.
fabric_profile = os.path.join(PROFILES_DIR, "26.1.2-fabric")
os.makedirs(fabric_profile, exist_ok=True)
for name in ("sodium.jar", "lithium.jar", "x.jar.disabled"):
    with open(os.path.join(fabric_profile, name), "wb") as fh:
        fh.write(b"j")

d = instances.describe("fabric-loader-0.19.5-26.1.2",
                       {"display_name": "26.1.2 (Fabric)"})
check("base version resolved", d["base_version"] == "26.1.2", d["base_version"])
check("loader resolved", d["loader"] == "fabric", d["loader"])
check("loader label", d["loader_label"] == "Fabric", d["loader_label"])
check("mod count includes disabled jars", d["mod_count"] == 3, str(d["mod_count"]))

d2 = instances.describe("fabric-loader-0.19.5-26.1.2",
                        {"display_name": "26.1.2 (Fabric)"}, "My Speedrun")
check("nickname beats display name", d2["display_name"] == "My Speedrun", d2["display_name"])

vanilla = instances.describe("1.21.11", {"display_name": "1.21.11"})
check("vanilla has zero mods", vanilla["mod_count"] == 0, str(vanilla["mod_count"]))

inc = instances.describe("1.20.1", {"display_name": "1.20.1", "incomplete": True,
                                    "issue": "Missing client .jar."})
check("incomplete flag survives", inc["incomplete"] and inc["issue"] != "")

print("\n4. size walk counts files")
size = instances.instance_size_bytes("1.21.11")
# 2048-byte jar + the tiny version json written above.
check("size covers every file in the folder",
      size is not None and 2048 < size < 2048 + 200, str(size))
check("missing version -> None", instances.instance_size_bytes("nope-9.9.9") is None)

print("\n5. last-played sidecar round-trips and is atomic")
instances.mark_played("1.21.11", when=1000.0)
check("read back", instances.last_played("1.21.11") == 1000.0,
      str(instances.last_played("1.21.11")))
check("unknown version is None", instances.last_played("never") is None)
instances.mark_played("fabric-loader-0.19.5-26.1.2", when=2000.0)
d3 = instances.describe("fabric-loader-0.19.5-26.1.2")
check("describe carries last_played", d3["last_played"] == 2000.0, str(d3["last_played"]))
check("no temp file left behind", not os.path.exists(
    os.path.join(os.path.dirname(instances._PLAY_STORE),
                 "instance_play.json.tmp")))

print("\n6. relative_time labels")
check("just now", instances.relative_time(1000.0, now=1010.0) == "just now")
check("minutes", instances.relative_time(1000.0, now=1000.0 + 600) == "10m ago")
check("hours", instances.relative_time(1000.0, now=1000.0 + 7200) == "2h ago")
check("days", instances.relative_time(1000.0, now=1000.0 + 3 * 86400) == "3d ago")
check("none -> empty", instances.relative_time(None) == "")

print("\n7. list_installed describes every scan entry, newest first")
listing = instances.list_installed([
    {"id": "1.21.11", "display_name": "1.21.11"},
    {"id": "fabric-loader-0.19.5-26.1.2", "display_name": "26.1.2 (Fabric)"},
], {"1.21.11": "Vanilla Home"})
ids = [x["id"] for x in listing]
check("order preserved", ids == ["1.21.11", "fabric-loader-0.19.5-26.1.2"], str(ids))
check("labels applied by id",
      listing[0]["display_name"] == "Vanilla Home", listing[0]["display_name"])
check("each entry has the render keys",
      all(k in listing[0] for k in
          ("id", "base_version", "loader", "loader_label", "display_name",
           "incomplete", "issue", "mod_count", "last_played")))

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
