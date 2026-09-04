#!/usr/bin/env python3
"""
Tests for cubeon/csl.py - run with:

    python tools/test_csl.py

Needs nothing installed and touches nothing real: it points HOME at a temp
directory and stubs minecraft_launcher_lib, so no .minecraft folder, no
network, and no Modrinth call is involved.

The part worth keeping is CSL_dedupe below. Cubeon's two ExtraList entries
have to survive CustomSkinLoader's own duplicate detection, and both of its
comparators are traps - a dropped entry means the load list silently keeps
Mojang ahead of the user's own skin, which looks like "my skin just doesn't
work" and is invisible from Python. So the comparators are reimplemented here
straight from CSL's source and asserted against, rather than assumed.
"""
import json
import os
import sys
import tempfile
import types

# --- Sandbox: temp HOME + stubbed mll, before importing anything of ours ----
_tmp = tempfile.mkdtemp(prefix="cubeon-csl-test-")
os.environ["HOME"] = _tmp
os.environ["USERPROFILE"] = _tmp  # Windows equivalent, for Path.home()

_fake_mc = os.path.join(_tmp, ".minecraft")
_mll = types.ModuleType("minecraft_launcher_lib")
_mll.utils = types.SimpleNamespace(get_minecraft_directory=lambda: _fake_mc)
sys.modules["minecraft_launcher_lib"] = _mll

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from cubeon import csl                                              # noqa: E402
from cubeon.paths import CSL_CONFIG_PATH, CSL_EXTRALIST_DIR         # noqa: E402

failures = 0


def check(label, ok, extra=""):
    global failures
    print(f"{'  ok  ' if ok else ' FAIL '} {label}{'  ' + str(extra) if extra else ''}")
    if not ok:
        failures += 1


# ---------------------------------------------------------------------------
# CSL's own duplicate detection, reimplemented from its source so we can prove
# our entries survive it. Both are quoted in the functions below.
# ---------------------------------------------------------------------------

def legacy_compare(ssp0: dict, ssp1: dict) -> bool:
    """LegacyLoader.compare - Objects.equals on skin AND cape AND elytra."""
    return (ssp0.get("skin") == ssp1.get("skin")
            and ssp0.get("cape") == ssp1.get("cape")
            and ssp0.get("elytra") == ssp1.get("elytra"))


def jsonapi_compare(ssp0: dict, ssp1: dict) -> bool:
    """JsonAPILoader.compare -
    `!StringUtils.isNoneEmpty(ssp0.root) || ssp0.root.equalsIgnoreCase(ssp1.root)`
    """
    root0 = ssp0.get("root")
    if not root0:  # isNoneEmpty(null/"") is false, so this short-circuits true
        return True
    return root0.lower() == (ssp1.get("root") or "").lower()


# CSL's shipped defaults, with the priorities read out of its source.
CSL_DEFAULT_LOADLIST = [
    {"name": "Mojang", "type": "MojangAPI", "apiRoot": "https://api.mojang.com/",
     "sessionRoot": "https://sessionserver.mojang.com/", "_priority": 100},
    {"name": "LittleSkin", "type": "CustomSkinAPI",
     "root": "https://littleskin.cn/csl/", "_priority": 200},
    {"name": "BlessingSkin", "type": "CustomSkinAPI",
     "root": "https://skin.prinzeugen.net/", "_priority": 300},
    {"name": "LocalSkin", "type": "Legacy", "checkPNG": False, "model": "auto",
     "skin": "LocalSkin/skins/{USERNAME}.png",
     "cape": "LocalSkin/capes/{USERNAME}.png",
     "elytra": "LocalSkin/elytras/{USERNAME}.png", "_priority": 710},
    {"name": "OptiFine", "type": "Legacy",
     "cape": "https://optifine.net/capes/{USERNAME}.png", "_priority": 810},
    {"name": "CloakPlus", "type": "Legacy",
     "cape": "http://161.35.130.99/capes/{USERNAME}.png", "_priority": 840},
]

COMPARATORS = {"legacy": legacy_compare, "customskinapi": jsonapi_compare}


def simulate_load_extra_list(loadlist: list[dict]) -> list[dict]:
    """CSL's Config.loadExtraList(), as far as ordering and dedupe go.

    Reads every *.json in ExtraList/, drops duplicates, PREPENDS the rest, and
    deletes each file whether it was used or not.
    """
    adds = []
    if os.path.isdir(CSL_EXTRALIST_DIR):
        for filename in sorted(os.listdir(CSL_EXTRALIST_DIR)):
            if not filename.lower().endswith((".json", ".txt")):
                continue
            path = os.path.join(CSL_EXTRALIST_DIR, filename)
            with open(path, "r", encoding="utf-8") as f:
                ssp = json.load(f)
            os.remove(path)  # CSL deletes the file either way

            kind = (ssp.get("type") or "").lower()
            if kind not in COMPARATORS:
                continue  # unknown type -> ignored, file already gone
            compare = COMPARATORS[kind]
            existing = [e for e in loadlist + adds
                        if (e.get("type") or "").lower() == kind]
            if any(compare(e, ssp) for e in existing):
                continue  # duplicate -> logged and dropped
            adds.append(ssp)
    return adds + loadlist


def write_csl_config(loadlist: list[dict]) -> None:
    os.makedirs(os.path.dirname(CSL_CONFIG_PATH), exist_ok=True)
    with open(CSL_CONFIG_PATH, "w", encoding="utf-8") as f:
        json.dump({"version": "14.20", "forceLoadAllTextures": True,
                   "loadlist": loadlist}, f, indent=2)


# ---------------------------------------------------------------------------
# 1. Fresh install, launch 1: the STAGGER queues only the Worker entry.
#
# The local entry is deliberately withheld until the Worker entry is merged, so
# it is always prepended AFTER (=> ahead of) the Worker entry - which is how the
# local source wins the cape slot. See the ORDER CONTRACT in cubeon/csl.py.
# ---------------------------------------------------------------------------
check("nothing registered before first run", csl.registered_names() == set())
check("not registered on a clean machine", not csl.is_registered())

written = csl.write_extralist_entries()
check("launch 1 queues only the Worker entry (stagger)", written == ["Cubeon"], written)
check("only the api file is on disk",
      os.listdir(CSL_EXTRALIST_DIR) == ["cubeon-api.json"], os.listdir(CSL_EXTRALIST_DIR))
check("local entry is withheld until the Worker is merged", not csl.is_registered())

# The API root must keep its trailing slash: CustomSkinAPI.toJsonUrl is bare
# `root + username + ".json"` with no normalization, so dropping it would
# request ".../cubeon-skins.workers.devBlueFox.json".
check("api root ends in a slash", csl.CUBEON_SKIN_API_ROOT.endswith("/"))
api_entry = json.load(open(os.path.join(CSL_EXTRALIST_DIR, "cubeon-api.json")))
check("api entry type is exactly CustomSkinAPI", api_entry["type"] == "CustomSkinAPI",
      api_entry["type"])

# CSL consumes launch 1's file, merging the Worker entry into the loadlist.
merged = simulate_load_extra_list(list(CSL_DEFAULT_LOADLIST))
mnames = [e["name"] for e in merged]
check("Worker entry merged ahead of Mojang",
      mnames.index("Cubeon") < mnames.index("Mojang"), mnames)
write_csl_config(merged)

# ---------------------------------------------------------------------------
# 1b. Launch 2: with the Worker entry now registered, the local entry queues.
# ---------------------------------------------------------------------------
written2 = csl.write_extralist_entries()
check("launch 2 queues the local entry", written2 == ["CubeonLocalSkin"], written2)
check("both sources now registered-or-queued", csl.is_registered())

# The local entry carries skin AND cape AND elytra. The cape/elytra paths carry
# a "./" segment ("LocalSkin/./capes/...") so LegacyLoader.compare() - which is
# Objects.equals on skin+cape+elytra - does NOT treat it as a duplicate of the
# built-in LocalSkin entry, while still resolving to the same files. Declaring
# the cape is what lets this entry win the cape slot for a custom local cape.
local_entry = json.load(open(os.path.join(CSL_EXTRALIST_DIR, "cubeon-localskin.json")))
check("local entry carries skin, cape and elytra",
      bool(local_entry.get("skin")) and bool(local_entry.get("cape"))
      and bool(local_entry.get("elytra")))
check("local cape path uses the './' dedupe-dodge", "/./" in local_entry.get("cape", ""))
check("local entry model is auto (reads slim arms from the PNG)",
      local_entry.get("model") == "auto")

# ---------------------------------------------------------------------------
# 2. CSL consumes launch 2: both survive dedupe, land ahead of Mojang, AND the
#    local source sits ahead of the Worker so its cape wins the cape slot.
# ---------------------------------------------------------------------------
merged = simulate_load_extra_list(merged)
names = [e["name"] for e in merged]
check("both sources survived CSL's dedupe",
      "Cubeon" in names and "CubeonLocalSkin" in names, names)

# Mojang resolves skins by username even offline, and mix() is first-wins per
# texture slot, so anything behind Mojang loses the skin.
check("Cubeon is ahead of Mojang", names.index("Cubeon") < names.index("Mojang"), names)
check("CubeonLocalSkin is ahead of Mojang",
      names.index("CubeonLocalSkin") < names.index("Mojang"), names)
# The whole point of the stagger: the local source is prepended LAST, so it
# sits ahead of the Worker and its (possibly custom) cape wins the cape slot.
check("CubeonLocalSkin is ahead of the Worker entry (wins the cape slot)",
      names.index("CubeonLocalSkin") < names.index("Cubeon"), names)
check("ExtraList files consumed (deleted) by CSL",
      not os.path.isdir(CSL_EXTRALIST_DIR) or os.listdir(CSL_EXTRALIST_DIR) == [])

write_csl_config(merged)

# ---------------------------------------------------------------------------
# 3. Idempotent: a second launch must not re-queue anything
# ---------------------------------------------------------------------------
check("reads back both as registered",
      csl.registered_names() == {"Cubeon", "CubeonLocalSkin"}, csl.registered_names())
check("second launch queues nothing", csl.write_extralist_entries() == [])
check("no leftover files", os.listdir(CSL_EXTRALIST_DIR) == [])

# ...and even if it did, CSL would drop them, so a double-run can't duplicate.
csl.write_extralist_entries()  # ignored return: forcing a redundant write
merged2 = simulate_load_extra_list(list(merged))
check("re-running never duplicates an entry",
      [e["name"] for e in merged2].count("Cubeon") == 1)
check("re-running never duplicates the local entry",
      [e["name"] for e in merged2].count("CubeonLocalSkin") == 1)

# ---------------------------------------------------------------------------
# 4. Self-healing: a wiped .minecraft re-registers - Worker first, then local,
#    exactly like a first install. The stagger is not a one-time thing.
# ---------------------------------------------------------------------------
os.remove(CSL_CONFIG_PATH)
check("wiped CSL config -> not registered", not csl.is_registered())
check("wiped CSL config -> re-queues the Worker entry first",
      csl.write_extralist_entries() == ["Cubeon"])
# CSL consumes it; the local entry then re-queues behind the merged Worker.
write_csl_config(simulate_load_extra_list(list(CSL_DEFAULT_LOADLIST)))
check("then re-queues the local entry", csl.write_extralist_entries() == ["CubeonLocalSkin"])

# ---------------------------------------------------------------------------
# 4b. Already queued: an identical file is left alone, a drifted or corrupt one
# is rewritten.
#
# CSL deletes ExtraList files when it consumes them, so between the launch that
# writes one and the launch after CSL runs, it just sits there. Writing it again
# every launch would work but churns the disk and makes the status line claim it
# "registered" something it didn't. Content that has DRIFTED is a different case:
# a future Cubeon release changing an entry's fields must not leave a queued file
# pointing at the old definition. The local entry is the one sitting queued here.
# ---------------------------------------------------------------------------
local_path = os.path.join(CSL_EXTRALIST_DIR, "cubeon-localskin.json")
before_mtime = os.stat(local_path).st_mtime_ns
check("queued-and-correct is not re-queued", csl.write_extralist_entries() == [])
check("queued-and-correct file untouched", os.stat(local_path).st_mtime_ns == before_mtime)

with open(local_path, "w", encoding="utf-8") as f:
    json.dump({**csl.EXTRALIST_ENTRIES["cubeon-localskin.json"], "model": "default"}, f)
rewritten = csl.write_extralist_entries()
check("stale queued entry is rewritten", rewritten == ["CubeonLocalSkin"], rewritten)
check("rewritten entry matches the current definition",
      json.load(open(local_path)) == csl.EXTRALIST_ENTRIES["cubeon-localskin.json"])

with open(local_path, "w", encoding="utf-8") as f:
    f.write("{truncated write")
check("corrupt queued entry is rewritten", csl.write_extralist_entries() == ["CubeonLocalSkin"])
check("still registered after repair", csl.is_registered())

# ---------------------------------------------------------------------------
# 5. Opt-out: manage=False withdraws anything still queued
# ---------------------------------------------------------------------------
result = csl.ensure_ready("1.20.1", "fabric", manage=False)
check("manage=False withdraws queued entries", os.listdir(CSL_EXTRALIST_DIR) == [],
      os.listdir(CSL_EXTRALIST_DIR))
check("manage=False reports why", "off" in result["detail"], result["detail"])
check("manage=False never downloads", result["installed"] is False)

# ---------------------------------------------------------------------------
# 6. Vanilla: registration still happens, no download is attempted
# ---------------------------------------------------------------------------
result = csl.ensure_ready("1.20.1", "vanilla")
check("vanilla still registers the sources", result["registered"], result)
check("vanilla reports it needs a loader", "loader" in result["detail"], result["detail"])
check("vanilla attempts no install", result["installed"] is False)

# A malformed CustomSkinLoader.json must not raise - CSL quarantines it and
# rebuilds, and we should just treat it as "nothing registered".
with open(CSL_CONFIG_PATH, "w", encoding="utf-8") as f:
    f.write("{not json at all")
check("unparseable CSL config is treated as absent", csl.read_csl_config() is None)
write_csl_config({"loadlist": "not-a-list"})  # wrong shape, still must not raise
check("malformed loadlist shape is tolerated", csl.registered_names() == set())

# ---------------------------------------------------------------------------
# 7. Drifted Worker root heal.
#
# The /skins/ migration moved the Worker's CustomSkinAPI route under /skins/,
# but is_registered() / write_extralist_entries() key only on the entry NAME -
# so an install that merged the "Cubeon" entry before the migration keeps a
# bare-URL root forever. CSL then builds lookups as `root + name + ".json"`
# against a path the Worker 404s: no network skin, and (the visible symptom)
# the shared Cubeon cape silently never loads. refresh_stale_worker_entry()
# corrects just that one field, in place, without disturbing load order.
# ---------------------------------------------------------------------------
STALE_ROOT = csl.CUBEON_API_BASE + "/"  # the pre-/skins/ root, as shipped then
write_csl_config([
    {"name": "CubeonLocalSkin", "type": "Legacy", "checkPNG": False,
     "skin": "LocalSkin/skins/{USERNAME}.png", "model": "auto",
     "cape": "LocalSkin/./capes/{USERNAME}.png",
     "elytra": "LocalSkin/./elytras/{USERNAME}.png"},
    {"name": "Cubeon", "type": "CustomSkinAPI", "root": STALE_ROOT},
] + [dict(e) for e in CSL_DEFAULT_LOADLIST])

check("drifted (bare) Worker root is detected as stale",
      csl._worker_root_stale(csl._loadlist()))
check("heal reports it corrected the root", csl.refresh_stale_worker_entry())
healed = next(e for e in csl._loadlist() if e.get("name") == "Cubeon")
check("root now matches the current /skins/ definition",
      healed.get("root") == csl.CUBEON_SKIN_API_ROOT, healed.get("root"))
check("healed root is no longer flagged stale",
      not csl._worker_root_stale(csl._loadlist()))
check("heal is idempotent (no second rewrite)", not csl.refresh_stale_worker_entry())
hnames = [e["name"] for e in csl._loadlist()]
check("heal preserves load order (local still wins the cape slot)",
      hnames.index("CubeonLocalSkin") < hnames.index("Cubeon"), hnames)
check("heal touches nothing but the root",
      all(e.get("name") in ("CubeonLocalSkin", "Cubeon")
          or e in CSL_DEFAULT_LOADLIST for e in csl._loadlist()))

# A correct install is left completely alone.
check("a current /skins/ root is not flagged stale",
      not csl._worker_root_stale(csl._loadlist()))
check("heal is a no-op on a correct install", not csl.refresh_stale_worker_entry())

# And the heal fires through the real launch path, not just when called directly.
write_csl_config([
    {"name": "Cubeon", "type": "CustomSkinAPI", "root": STALE_ROOT},
] + [dict(e) for e in CSL_DEFAULT_LOADLIST])
csl.write_extralist_entries()
via_launch = next(e for e in csl._loadlist() if e.get("name") == "Cubeon")
check("write_extralist_entries() heals a drifted root at launch",
      via_launch.get("root") == csl.CUBEON_SKIN_API_ROOT, via_launch.get("root"))

print(f"\n{failures} CHECK(S) FAILED" if failures else "\nALL CSL CHECKS PASSED")
sys.exit(1 if failures else 0)
