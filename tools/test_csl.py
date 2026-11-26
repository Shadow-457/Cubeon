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
# CUBEON_GAME_DIR *wins over HOME* in cubeon/paths.py (that is its whole
# purpose), so leaving an ambient one set defeats the sandbox above: this test
# would then write and CONSUME ExtraList files inside the real game dir - which
# is the directory CI sets for the whole job - instead of inside _tmp. That is
# not hypothetical: the first failures here ("nothing registered before first
# run", "only the api file is on disk") are exactly what a warm game dir looks
# like, i.e. the test silently stops testing what it says it tests.
os.environ.pop("CUBEON_GAME_DIR", None)

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
# 1. Fresh install, launch 1: queue ONLY LocalSkin.
#
# Java's File.listFiles() order is unspecified. A single queue file guarantees
# the local PNG wins immediately on every filesystem; once CSL writes its real
# config, managed setup inserts the Worker directly in deterministic order.
# ---------------------------------------------------------------------------
check("nothing registered before first run", csl.registered_names() == set())
check("not registered on a clean machine", not csl.is_registered())

written = csl.write_extralist_entries()
check("launch 1 queues only LocalSkin", written == ["CubeonLocalSkin"], written)
check("only the local source file is on disk",
      os.listdir(CSL_EXTRALIST_DIR) == ["cubeon-localskin.json"],
      os.listdir(CSL_EXTRALIST_DIR))
check("the clean bootstrap has no unordered Worker file",
      csl.pending_names() == {"CubeonLocalSkin"} and not csl.is_registered())

# The API root must keep its trailing slash: CustomSkinAPI.toJsonUrl is bare
# `root + username + ".json"` with no normalization, so dropping it would
# request ".../cubeon-skins.workers.devBlueFox.json".
check("api root ends in a slash", csl.CUBEON_SKIN_API_ROOT.endswith("/"))

# The local entry carries skin AND cape AND elytra. The cape/elytra paths carry
# a "./" segment so LegacyLoader.compare() does not discard it as a duplicate.
local_entry = json.load(open(os.path.join(CSL_EXTRALIST_DIR, "cubeon-localskin.json")))
check("local entry carries skin, cape and elytra",
      bool(local_entry.get("skin")) and bool(local_entry.get("cape"))
      and bool(local_entry.get("elytra")))
check("local cape path uses the './' dedupe-dodge", "/./" in local_entry.get("cape", ""))
check("local entry model starts as auto", local_entry.get("model") == "auto")
check("first-launch sync can set the queued LocalSkin arm model",
      csl.set_localskin_model("slim")
      and json.load(open(os.path.join(CSL_EXTRALIST_DIR,
                                     "cubeon-localskin.json")))["model"] == "slim")

# CSL consumes the one launch-1 file, so LocalSkin is unconditionally first.
merged = simulate_load_extra_list(list(CSL_DEFAULT_LOADLIST))
mnames = [e["name"] for e in merged]
check("LocalSkin merged ahead of Mojang on first launch",
      mnames.index("CubeonLocalSkin") < mnames.index("Mojang"), mnames)
check("Worker is absent from the unordered first-launch queue", "Cubeon" not in mnames, mnames)
write_csl_config(merged)

# ---------------------------------------------------------------------------
# 1b. Launch 2: normalize the persistent order before Minecraft starts.
# ---------------------------------------------------------------------------
written2 = csl.write_extralist_entries()
check("launch 2 queues nothing", written2 == [], written2)
ordered_names = [e["name"] for e in csl._loadlist()]
check("launch 2 normalizes LocalSkin ahead of Worker",
      ordered_names.index("CubeonLocalSkin") < ordered_names.index("Cubeon"), ordered_names)
api_entry = next(e for e in csl._loadlist() if e.get("name") == "Cubeon")
check("launch 2 inserts the Worker directly with the correct API type/root",
      api_entry.get("type") == "CustomSkinAPI"
      and api_entry.get("root") == csl.CUBEON_SKIN_API_ROOT, api_entry)
local_config = next(e for e in csl._loadlist() if e.get("name") == "CubeonLocalSkin")
check("the first-launch explicit arm model survives config normalization",
      local_config.get("model") == "slim", local_config)

# ---------------------------------------------------------------------------
# 2. Both survived dedupe and the normalized persistent order keeps local
#    skin/cape/elytra ahead of the Worker.
# ---------------------------------------------------------------------------
merged = csl._loadlist()
names = [e["name"] for e in merged]
check("both sources survived CSL's dedupe",
      "Cubeon" in names and "CubeonLocalSkin" in names, names)

# Mojang resolves skins by username even offline, and mix() is first-wins per
# texture slot, so anything behind Mojang loses the skin.
check("Cubeon is ahead of Mojang", names.index("Cubeon") < names.index("Mojang"), names)
check("CubeonLocalSkin is ahead of Mojang",
      names.index("CubeonLocalSkin") < names.index("Mojang"), names)
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

# An affected older profile can contain only the Worker after its first run.
# Upgrade it in place before Minecraft starts, without another ExtraList race.
write_csl_config([
    dict(csl.EXTRALIST_ENTRIES["cubeon-api.json"]),
] + [dict(e) for e in CSL_DEFAULT_LOADLIST])
check("Worker-only older config is upgraded without queueing",
      csl.write_extralist_entries() == [] and csl.is_registered())
upgraded_names = [e["name"] for e in csl._loadlist()]
check("the upgraded config puts LocalSkin ahead of Worker and Mojang",
      upgraded_names.index("CubeonLocalSkin") < upgraded_names.index("Cubeon")
      < upgraded_names.index("Mojang"), upgraded_names)

# ---------------------------------------------------------------------------
# 4. Self-healing: a wiped CSL config returns to LocalSkin-only bootstrap.
# ---------------------------------------------------------------------------
os.remove(CSL_CONFIG_PATH)
check("wiped CSL config -> not registered", not csl.is_registered())
# Simulate an interrupted older build that left its Worker file pending. The
# new bootstrap must remove that owned file before writing LocalSkin.
os.makedirs(CSL_EXTRALIST_DIR, exist_ok=True)
with open(os.path.join(CSL_EXTRALIST_DIR, "cubeon-api.json"), "w", encoding="utf-8") as f:
    json.dump(csl.EXTRALIST_ENTRIES["cubeon-api.json"], f)
check("wiped config removes an old pending Worker and queues only LocalSkin",
      csl.write_extralist_entries() == ["CubeonLocalSkin"]
      and os.listdir(CSL_EXTRALIST_DIR) == ["cubeon-localskin.json"])

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
    json.dump({**csl.EXTRALIST_ENTRIES["cubeon-localskin.json"], "cape": "old/cape.png", "model": "default"}, f)
rewritten = csl.write_extralist_entries()
check("stale queued entry is rewritten", rewritten == ["CubeonLocalSkin"], rewritten)
check("rewritten entry repairs stale paths and preserves the explicit arm model",
      json.load(open(local_path)) == {**csl.EXTRALIST_ENTRIES["cubeon-localskin.json"], "model": "default"})
before_mtime = os.stat(local_path).st_mtime_ns
check("queued explicit arms are not reset to auto on launch", csl.write_extralist_entries() == []
      and os.stat(local_path).st_mtime_ns == before_mtime)

with open(local_path, "w", encoding="utf-8") as f:
    f.write("{truncated write")
check("corrupt queued entry is rewritten", csl.write_extralist_entries() == ["CubeonLocalSkin"])
check("local bootstrap remains pending after repair",
      csl.pending_names() == {"CubeonLocalSkin"} and not csl.is_registered())

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
check("vanilla prepares deterministic first-launch LocalSkin",
      not result["registered"] and csl.pending_names() == {"CubeonLocalSkin"}, result)
check("vanilla reports it needs a loader", "loader" in result["detail"], result["detail"])
check("vanilla attempts no install", result["installed"] is False)

# After CSL consumes LocalSkin and creates its config, the next managed setup
# adds the Worker directly; no second ExtraList file or filesystem order is used.
write_csl_config(simulate_load_extra_list(list(CSL_DEFAULT_LOADLIST)))
result = csl.ensure_ready("1.20.1", "vanilla")
check("the next launch has both ordered sources", result["registered"]
      and [e["name"] for e in csl._loadlist()].index("CubeonLocalSkin")
      < [e["name"] for e in csl._loadlist()].index("Cubeon"), result)
check("the deterministic promotion leaves no queue files",
      os.listdir(CSL_EXTRALIST_DIR) == [], os.listdir(CSL_EXTRALIST_DIR))

# A malformed CustomSkinLoader.json must not raise - CSL quarantines it and
# rebuilds, and we should just treat it as "nothing registered".
with open(CSL_CONFIG_PATH, "w", encoding="utf-8") as f:
    f.write("{not json at all")
check("unparseable CSL config is treated as absent", csl.read_csl_config() is None)
write_csl_config({"loadlist": "not-a-list"})  # wrong shape, still must not raise
check("malformed loadlist shape is tolerated", csl.registered_names() == set())

# Older launchers wrote the bare URL as the root before /skins/ was added.
STALE_ROOT = csl.CUBEON_API_BASE + "/"

from unittest.mock import patch
from cubeon import net
info = {"filename": "csl.jar", "url": "offline", "version_number": "1",
        "hashes": {"sha1": "verified-manifest-hash"}}
with patch.object(csl, "get_mod_download", return_value=info), patch.object(csl, "download_mod") as download:
    check("CSL install succeeds", csl.install("1.20.1", "fabric").startswith("installed"))
    check("CSL forwards download hashes", download.call_args.kwargs["hashes"] == info["hashes"])
for error in (net.DownloadError("offline"), RuntimeError("wrapped download failure"), OSError("disk full"), ValueError("bad metadata")):
    with patch.object(csl, "get_mod_download", side_effect=error):
        check(f"CSL lookup tolerates {type(error).__name__}", "couldn't reach" in csl.install("1.20.1", "fabric"))
    with patch.object(csl, "get_mod_download", return_value=info), patch.object(csl, "download_mod", side_effect=error):
        check(f"CSL download tolerates {type(error).__name__}", "download failed" in csl.install("1.20.1", "fabric"))

# --- the Worker base URL is overridable ------------------------------------
# The deployed URL is public (it is in the shipped launcher and therefore in
# the repo), so a fork can keep its users off the upstream Worker by pointing
# Cubeon at its own deployment - and `wrangler dev` needs the same lever. The
# constants are read at import time, so this is checked the honest way: reload
# the module under a patched environment and read what it produced. csl.py has
# no import-time side effects beyond constant definitions, which is what makes
# reloading it safe here.
import importlib

with patch.dict(os.environ, {"CUBEON_SKIN_API": "https://example.test/base/"}):
    csl = importlib.reload(csl)
    check("CUBEON_SKIN_API overrides the Worker base",
          csl.CUBEON_API_BASE == "https://example.test/base", csl.CUBEON_API_BASE)
    check("...and the CSL root keeps its trailing slash on the override",
          csl.CUBEON_SKIN_API_ROOT == "https://example.test/base/skins/",
          csl.CUBEON_SKIN_API_ROOT)

os.environ.pop("CUBEON_SKIN_API", None)
csl = importlib.reload(csl)
check("...and with no override the deployed Worker is used",
      csl.CUBEON_API_BASE == "https://cubeon-skins.hamza-457-shahbaz.workers.dev",
      csl.CUBEON_API_BASE)

with open(CSL_CONFIG_PATH, "w", encoding="utf-8") as stream:
    json.dump({"cacheExpiry": 30, "enableLocalProfileCache": False,
               "loadlist": [{"name": "CustomProvider", "root": "https://custom.example/"}],
               "custom_option": "keep"}, stream)
check("managed CSL default cache becomes five minutes", csl.configure_request_cache())
configured = csl.read_csl_config()
check("only default expiry changes; custom providers and preferences are preserved",
      configured == {"cacheExpiry": 300, "enableLocalProfileCache": False,
                     "loadlist": [{"name": "CustomProvider", "root": "https://custom.example/"}],
                     "custom_option": "keep"})
stamp = os.stat(CSL_CONFIG_PATH).st_mtime_ns
check("cache configuration is idempotent without rewriting",
      not csl.configure_request_cache() and os.stat(CSL_CONFIG_PATH).st_mtime_ns == stamp)
for expiry in (60, 600):
    configured["cacheExpiry"] = expiry
    with open(CSL_CONFIG_PATH, "w", encoding="utf-8") as stream:
        json.dump(configured, stream)
    check("a hand-tuned cache value is preserved", not csl.configure_request_cache()
          and csl.read_csl_config()["cacheExpiry"] == expiry)
configured["cacheExpiry"] = 30
with open(CSL_CONFIG_PATH, "w", encoding="utf-8") as stream:
    json.dump(configured, stream)
csl.ensure_ready(None, None, manage=False)
check("management OFF does not change cache settings", csl.read_csl_config()["cacheExpiry"] == 30)
os.unlink(CSL_CONFIG_PATH)
check("no partial config is created before CSL writes its defaults",
      not csl.configure_request_cache() and not os.path.exists(CSL_CONFIG_PATH))

# --- Launcher skins before official fallback, through managed launch --------
local = {**csl.EXTRALIST_ENTRIES["cubeon-localskin.json"], "model": "slim"}
worker = dict(csl.EXTRALIST_ENTRIES["cubeon-api.json"])
tlauncher, elyby, mojang = [dict(e) for e in csl.FALLBACK_ENTRIES]
tlauncher.update(name="My TLauncher", custom_option="preserve")
elyby.update(name="My ElyBy", root="http://skinsystem.ely.by/textures/")
custom = {"name": "Private auth", "type": "MojangAPI", "apiRoot": "https://custom.example/"}
gameprofile = {"name": "Server textures", "type": "GameProfile"}
other = {"name": "Other source", "type": "Legacy", "skin": "custom/{USERNAME}.png"}
initial = {"version": "15.1", "loadlist": [mojang, other, worker, gameprofile, elyby, local, tlauncher, custom],
           "forceLoadAllTextures": False, "cacheExpiry": 600, "enableLocalProfileCache": True,
           "unknown_setting": {"keep": True}}
with open(CSL_CONFIG_PATH, "w", encoding="utf-8") as stream:
    json.dump(initial, stream)
csl.ensure_ready(None, None)
ordered = csl.read_csl_config()
check("managed launch uses local Cubeon, Cubeon API, TLauncher, ElyBy, other sources, server textures, Mojang",
      ordered["loadlist"] == [local, worker, tlauncher, elyby, other, custom, gameprofile, mojang])
check("cape-only results keep searching for a skin", ordered["forceLoadAllTextures"] is True)
check("source fields, explicit slim arms, custom auth roots and other settings survive",
      {k:v for k,v in ordered.items() if k not in ("loadlist", "forceLoadAllTextures")} ==
      {k:v for k,v in initial.items() if k not in ("loadlist", "forceLoadAllTextures")})
stamp = os.stat(CSL_CONFIG_PATH).st_mtime_ns
check("priority normalization is idempotent and duplicates no renamed provider",
      not csl.configure_source_order() and os.stat(CSL_CONFIG_PATH).st_mtime_ns == stamp
      and len(ordered["loadlist"]) == len(initial["loadlist"]))

# Exercise CSL's actual first-wins, per-slot merge contract: cape-only Cubeon
# still reaches TLauncher/ElyBy/Mojang; server textures remain available.
def mix_profiles(sources, profiles):
    result = {}
    for source in sources:
        for slot, value in profiles.get(source["name"], {}).items():
            if value and not result.get(slot):
                result[slot] = value
        if result.get("skin") and result.get("cape"):
            break
    return result

for provider in (tlauncher, elyby, gameprofile, mojang):
    check(f"cape-only Cubeon merges with {provider['name']}'s skin",
          mix_profiles(ordered["loadlist"], {"Cubeon": {"cape": "cubeon"},
                       provider["name"]: {"skin": "peer"}}) == {"cape": "cubeon", "skin": "peer"})
check("TLauncher skin wins ahead of ElyBy and Mojang",
      mix_profiles(ordered["loadlist"], {tlauncher["name"]: {"skin": "tlauncher"},
                   elyby["name"]: {"skin": "elyby"}, "Mojang": {"skin": "official"}})["skin"] == "tlauncher")

initial["loadlist"] = [custom, local, worker]
with open(CSL_CONFIG_PATH, "w", encoding="utf-8") as stream:
    json.dump(initial, stream)
check("older configs gain only supported TLauncher, ElyBy and official fallback entries",
      csl.configure_source_order() and [e["name"] for e in csl.read_csl_config()["loadlist"]] ==
      ["CubeonLocalSkin", "Cubeon", "TLauncher", "ElyBy", "Private auth", "Mojang"])

with open(CSL_CONFIG_PATH, "w", encoding="utf-8") as stream:
    json.dump(initial, stream)
before = open(CSL_CONFIG_PATH, "rb").read()
with patch("cubeon.atomicio.os.replace", side_effect=OSError("disk full")):
    check("failed atomic priority writes report failure", not csl.configure_source_order())
check("a failed priority write preserves the exact previous config", open(CSL_CONFIG_PATH, "rb").read() == before)
csl.ensure_ready(None, None, manage=False)
check("management OFF leaves priority and fallback preferences untouched", open(CSL_CONFIG_PATH, "rb").read() == before)

instance_config = os.path.join(_tmp, "another-instance", "CustomSkinLoader.json")
os.makedirs(os.path.dirname(instance_config))
with open(instance_config, "w", encoding="utf-8") as stream:
    json.dump(initial, stream)
with patch.object(csl, "instance_csl_path", return_value=instance_config):
    check("priority writes target the active instance", csl.configure_source_order())
check("another instance's priority never modifies shared config", open(CSL_CONFIG_PATH, "rb").read() == before)

# Upgrade registered entries from older releases through the normal launch path.
older_local = {"name": "CubeonLocalSkin", "type": "Legacy", "skin": "old/{USERNAME}.png",
               "model": "slim", "custom_option": "keep"}
older_worker = {**worker, "root": STALE_ROOT, "custom_option": "keep"}
write_csl_config([older_worker, custom, older_local])
result = csl.ensure_ready(None, None)
repaired = csl.read_csl_config()["loadlist"]
check("older LocalSkin texture paths are repaired in place on the next launch",
      repaired[0] == {**local, "custom_option": "keep"} and result["registered"])
check("repair keeps third-party sources and unknown managed fields",
      custom in repaired and repaired[1] == {**worker, "custom_option": "keep"})
check("upgraded CSL config needs no ExtraList files", not os.listdir(CSL_EXTRALIST_DIR))
stamp = os.stat(CSL_CONFIG_PATH).st_mtime_ns
csl.ensure_ready(None, None)
check("migrated CSL sources are stable on restart", os.stat(CSL_CONFIG_PATH).st_mtime_ns == stamp)

for invalid in ("{bad json", "[]", "{}", '{"loadlist":null}', '{"loadlist":"wrong shape"}'):
    with open(CSL_CONFIG_PATH, "w", encoding="utf-8") as stream:
        stream.write(invalid)
    check("malformed configs are left for CSL to repair", not csl.configure_source_order()
          and open(CSL_CONFIG_PATH, encoding="utf-8").read() == invalid)
    with open(os.path.join(CSL_EXTRALIST_DIR, "cubeon-api.json"), "w", encoding="utf-8") as stream:
        json.dump(worker, stream)
    csl.ensure_ready(None, None)
    check("an unusable config only queues LocalSkin without rewriting CSL's file",
          csl.pending_names() == {"CubeonLocalSkin"}
          and open(CSL_CONFIG_PATH, encoding="utf-8").read() == invalid)
os.unlink(CSL_CONFIG_PATH)
check("priority setup does not seed an incomplete first-run config",
      not csl.configure_source_order() and not os.path.exists(CSL_CONFIG_PATH))

print(f"\n{failures} CHECK(S) FAILED" if failures else "\nALL CSL CHECKS PASSED")
sys.exit(1 if failures else 0)
