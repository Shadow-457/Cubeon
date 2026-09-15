"""
Offline regression suite for resource-pack format compatibility
(cubeon/packformat.py) and the all-content doctor (cubeon/doctor.py).

Why this suite exists: users install a resource pack, the launcher says
"Installed", and the game greets them with a red "Incompatible" - because
Minecraft judges a pack by the pack_format inside its own pack.mcmeta against
the format the RUNNING version expects, and every version reads the same shared
resourcepacks/ folder. Nine of fifteen packs on the machine this was written on
were in that state. These tests pin the contract that stops it:

  * the format a version expects comes from its CLIENT JAR (version.json ->
    pack_version.resource_major), so no table can go stale, with the table only
    as a fallback for versions that aren't downloaded yet;
  * a pack is "compatible" only when every installed version accepts it - and
    for versions older than 1.20.2 (format 18) that means pack_format itself,
    because those games ignore supported_formats;
  * repair_pack widens the declared range without dropping what the pack was
    built for, flattens a wrapped zip, and creates a missing pack.mcmeta; it is
    idempotent and leaves every other entry byte-identical;
  * the doctor covers all five content types, and one broken section can never
    take the others down.

No network, no display: HOME is sandboxed (tools/_sandbox_home.py) and every
directory constant is pointed at a scratch tree.
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402

HOME = _sandbox_home.isolate()

from cubeon import doctor  # noqa: E402
from cubeon import packformat as pf  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


# --- scratch tree ----------------------------------------------------------
SCRATCH = tempfile.mkdtemp(prefix="cubeon-doctor-test-")
MINECRAFT = os.path.join(SCRATCH, "minecraft")
PACKS = os.path.join(MINECRAFT, "resourcepacks")
SHADERS = os.path.join(MINECRAFT, "shaderpacks")
VERSIONS = os.path.join(MINECRAFT, "versions")
SERVERS = os.path.join(SCRATCH, "servers")
PROFILES = os.path.join(SCRATCH, "profiles")
for path in (PACKS, SHADERS, VERSIONS, SERVERS, PROFILES):
    os.makedirs(path, exist_ok=True)

# Redirect every constant the two modules read. They import names at module
# level, so patching the module attributes is the only thing that takes effect.
pf.MINECRAFT_DIR = MINECRAFT
doctor.MINECRAFT_DIR = MINECRAFT
doctor.RESOURCEPACKS_DIR = PACKS
doctor.SHADERPACKS_DIR = SHADERS
doctor.SERVERS_DIR = SERVERS

import cubeon.modpacks as modpacks  # noqa: E402
import cubeon.server as server_module  # noqa: E402

modpacks.PROFILES_DIR = PROFILES
# Never touch the host's processes: the plugin section asks whether a server is
# running, and this suite has no servers.
server_module.is_server_running = lambda *a, **k: False


def reset_caches():
    pf._format_cache.clear()
    pf._jar_format_cache.clear()


def fake_version(version_id, resource_format):
    """A version folder with a client jar carrying the pack format, exactly how
    a real install looks (the jar's version.json is the authoritative source)."""
    folder = os.path.join(VERSIONS, version_id)
    os.makedirs(folder, exist_ok=True)
    with zipfile.ZipFile(os.path.join(folder, version_id + ".jar"), "w") as zf:
        zf.writestr("version.json", json.dumps({
            "id": version_id,
            "pack_version": {"resource_major": resource_format,
                             "resource_minor": 0,
                             "data_major": 94},
        }))
        zf.writestr("assets/.mcassetsroot", "")
    reset_caches()


def make_zip(name, entries, *, folder=None):
    """Write a zip into the given content folder. entries maps entry name to
    str/bytes content."""
    target_dir = folder or PACKS
    path = os.path.join(target_dir, name)
    with zipfile.ZipFile(path, "w") as zf:
        for entry, content in entries.items():
            data = content.encode("utf-8") if isinstance(content, str) else content
            zf.writestr(entry, data)
    return path


def meta_bytes(pack_format=None, supported=None, description="Test pack",
               extra=None, section=True):
    pack = {"description": description}
    if pack_format is not None:
        pack["pack_format"] = pack_format
    if supported is not None:
        pack["supported_formats"] = supported
    if extra:
        pack.update(extra)
    return json.dumps({"pack": pack} if section else pack)


def read_meta(zip_path):
    with zipfile.ZipFile(zip_path) as zf:
        return json.loads(zf.read("pack.mcmeta").decode("utf-8"))


# ---------------------------------------------------------------------------
print("\n1. which resource format does a game version expect?")
# ---------------------------------------------------------------------------
check("a plain release parses into comparable numbers",
      pf.version_key("1.21.11") == (1, 21, 11), pf.version_key("1.21.11"))
check("the 26.x scheme (year.major.patch) parses too",
      pf.version_key("26.1.2") == (26, 1, 2), pf.version_key("26.1.2"))
check("short forms compare correctly against longer ones",
      pf.version_key("26.1") == (26, 1) and pf._le((26, 1), (26, 1, 2)),
      (pf.version_key("26.1"),))
check("a snapshot isn't a comparable version",
      pf.version_key("24w14a") is None, pf.version_key("24w14a"))
check("a pre-release isn't either", pf.version_key("1.21-pre1") is None)

# The jar is the authority; the table is only for versions not downloaded yet.
fake_version("1.21.11", 75)
fake_version("26.1.2", 84)
check("the format comes from the client jar (1.21.11 -> 75)",
      pf.resource_format_for("1.21.11") == 75, pf.resource_format_for("1.21.11"))
check("and for 26.1.2 -> 84", pf.resource_format_for("26.1.2") == 84,
      pf.resource_format_for("26.1.2"))
check("a loader profile resolves through its own jar folder",
      pf.resource_format_for("26.1.2", "fabric-loader-0.19.5-26.1.2") == 84,
      pf.resource_format_for("26.1.2", "fabric-loader-0.19.5-26.1.2"))
check("a version with no jar falls back to the table (1.20.1 -> 15)",
      pf.resource_format_for("1.20.1") == 15, pf.resource_format_for("1.20.1"))
check("the table's newest known entry is used for later versions",
      pf.resource_format_for("26.9") == 84, pf.resource_format_for("26.9"))
check("a snapshot with no jar stays unknown (None, never a guess)",
      pf.resource_format_for("24w14a") is None,
      pf.resource_format_for("24w14a"))
check("installed_resource_formats unions every installed version",
      pf.installed_resource_formats() == [75, 84],
      pf.installed_resource_formats())
check("and folds in the version being launched/browsed",
      pf.installed_resource_formats("1.20.1") == [15, 75, 84],
      pf.installed_resource_formats("1.20.1"))

# ---------------------------------------------------------------------------
print("\n2. reading a pack's own declaration")
# ---------------------------------------------------------------------------
check("a list range is understood", pf._range_of([15, 64]) == (15, 64))
check("a reversed list is normalised", pf._range_of([64, 15]) == (15, 64))
check("the dict form is understood",
      pf._range_of({"min_inclusive": 8, "max_inclusive": 69}) == (8, 69))
check("the newer min/max wording is understood",
      pf._range_of({"min": 4, "max": 9}) == (4, 9))
check("a lone int becomes a one-value range", pf._range_of(15) == (15, 15))
check("garbage is not a range", pf._range_of("soon") is None)

wrapped = make_zip("wrapped.zip", {
    "MyPack/pack.mcmeta": meta_bytes(15, [15, 64]),
    "MyPack/assets/minecraft/textures/x.png": b"png",
})
nested_meta, nested_entry, nested_wrapper = pf.read_pack_meta(wrapped)
check("a wrapped zip's meta is found and the wrapper identified",
      nested_meta is not None and nested_wrapper == "MyPack",
      (nested_entry, nested_wrapper))

flat = make_zip("flat.zip", {
    "pack.mcmeta": meta_bytes(15, [15, 64]),
    "assets/minecraft/textures/x.png": b"png",
    "pack.png": b"img",
})
_meta2, entry2, wrapper2 = pf.read_pack_meta(flat)
check("an ordinary pack has no wrapper", wrapper2 is None and entry2 == "pack.mcmeta",
      (entry2, wrapper2))

mac_only = make_zip("macjunk.zip", {
    "pack.mcmeta": meta_bytes(15, [15, 64]),
    "assets/x.png": b"png",
    "__MACOSX/._pack.mcmeta": b"junk",
    ".DS_Store": b"junk",
})
check("OS droppings never make a pack look wrapped",
      pf.read_pack_meta(mac_only)[2] is None, pf.read_pack_meta(mac_only))

json_broken = make_zip("brokenjson.zip", {"pack.mcmeta": "{not json"})
check("an unparseable pack.mcmeta reads as no meta, with the entry kept",
      pf.read_pack_meta(json_broken)[0] is None
      and pf.read_pack_meta(json_broken)[1] == "pack.mcmeta",
      pf.read_pack_meta(json_broken))

unreadable = os.path.join(PACKS, "notazip.zip")
with open(unreadable, "wb") as fh:
    fh.write(b"definitely not a zip")
check("an unreadable zip yields (None, None, None)",
      pf.read_pack_meta(unreadable) == (None, None, None),
      pf.read_pack_meta(unreadable))

# ---------------------------------------------------------------------------
print("\n3. will the game accept it? (the 'Incompatible' verdict)")
# ---------------------------------------------------------------------------
exact = make_zip("exact.zip", {"pack.mcmeta": meta_bytes(75),
                               "assets/x.png": b"png"})
check("a pack built for this exact format is accepted",
      pf.pack_verdict(exact, [75])["ok"] is True, pf.pack_verdict(exact, [75]))
check("a pack built for another format is rejected",
      pf.pack_verdict(exact, [84])["ok"] is False,
      pf.pack_verdict(exact, [84]))
check("the rejection names the format it was built for",
      "75" in pf.pack_verdict(exact, [84])["reason"],
      pf.pack_verdict(exact, [84])["reason"])

ranged = make_zip("ranged.zip", {"pack.mcmeta": meta_bytes(34, [34, 88]),
                                 "assets/x.png": b"png"})
check("a declared range covering the target is accepted",
      pf.pack_verdict(ranged, [46, 75])["ok"] is True,
      pf.pack_verdict(ranged, [46, 75]))
check("and a target just outside it is not",
      pf.pack_verdict(ranged, [32])["ok"] is False,
      pf.pack_verdict(ranged, [32]))
check("one incompatible version among many still fails the pack",
      pf.pack_verdict(ranged, [32, 46, 75])["blocked"] == [32],
      pf.pack_verdict(ranged, [32, 46, 75]))

# Games older than 1.20.2 (format 18) ignore supported_formats and judge a pack
# by pack_format alone - the trap that makes a widened range look fixed when it
# is not.
check("a pre-1.20.2 game ignores the range and wants pack_format itself",
      pf.pack_verdict(ranged, [15])["ok"] is False,
      pf.pack_verdict(ranged, [15]))
legacy_ok = make_zip("legacy.zip", {"pack.mcmeta": meta_bytes(15, [15, 64])})
check("but a pack whose pack_format matches that old game is accepted",
      pf.pack_verdict(legacy_ok, [15])["ok"] is True,
      pf.pack_verdict(legacy_ok, [15]))

check("no determinable target is 'unknown', never a failure",
      pf.pack_verdict(exact, [])["ok"] is None, pf.pack_verdict(exact, []))
check("unknown targets are never listed as blocked",
      pf.pack_verdict(exact, [])["blocked"] == [], pf.pack_verdict(exact, []))

no_meta = make_zip("nometa.zip", {"assets/x.png": b"png"})
check("a pack with no pack.mcmeta is a problem (the game can't read it)",
      pf.pack_verdict(no_meta, [75])["ok"] is False,
      pf.pack_verdict(no_meta, [75]))
check("a pack with no pack_format declared is a problem",
      pf.pack_verdict(json_broken, [75])["ok"] is False,
      pf.pack_verdict(json_broken, [75]))
check("a pack.mcmeta buried in a folder is a problem",
      pf.pack_verdict(wrapped, [75])["ok"] is False
      and "folder" in pf.pack_verdict(wrapped, [75])["reason"],
      pf.pack_verdict(wrapped, [75]))
check("a corrupt file is reported as unreadable, not as missing meta",
      "readable" in pf.pack_verdict(unreadable, [75])["reason"],
      pf.pack_verdict(unreadable, [75]))

# ---------------------------------------------------------------------------
print("\n4. repairing a pack (no texture is ever touched)")
# ---------------------------------------------------------------------------
before_bytes = open(ranged, "rb").read()
dry = pf.repair_pack(ranged, [32], dry_run=True)
check("a dry run says it WOULD change the pack",
      dry["changed"] is True and dry.get("dry_run") is True, dry)
check("a dry run leaves the file byte-identical",
      open(ranged, "rb").read() == before_bytes)

repair = pf.repair_pack(ranged, [32])
check("the repair reports a range that covers the new target",
      repair["changed"] is True
      and repair["after"]["supported_formats"] == [32, 88], repair)
check("pack_format is kept when no pre-1.20.2 game needs it",
      repair["after"]["pack_format"] == 34, repair["after"])
meta_after = read_meta(ranged)
check("supported_formats is written where the game reads it",
      meta_after["pack"]["supported_formats"] == [32, 88], meta_after)
check("the pack now passes the verdict it failed",
      pf.pack_verdict(ranged, [32])["ok"] is True,
      pf.pack_verdict(ranged, [32]))
check("the description is preserved",
      meta_after["pack"]["description"] == "Test pack", meta_after)
check("repairing again is a no-op (idempotent)",
      pf.repair_pack(ranged, [32])["changed"] is False,
      pf.repair_pack(ranged, [32]))

modern = make_zip("modern.zip", {"pack.mcmeta": meta_bytes(75, [75, 75]),
                                 "assets/x.png": b"png"})
pf.repair_pack(modern, [32, 84])
modern_meta = read_meta(modern)["pack"]
check("a modern target also gets the min/max pair",
      modern_meta.get("min_format") == 32
      and modern_meta.get("max_format") == 84, modern_meta)

legacy_fix = make_zip("legacyfix.zip", {"pack.mcmeta": meta_bytes(34, [34, 88])})
pf.repair_pack(legacy_fix, [15, 75])
legacy_meta = read_meta(legacy_fix)["pack"]
check("a pre-1.20.2 target is written into pack_format itself",
      legacy_meta["pack_format"] == 15, legacy_meta)
check("and its range still covers the modern target too",
      legacy_meta["supported_formats"] == [15, 88], legacy_meta)
check("so the old game accepts it now",
      pf.pack_verdict(legacy_fix, [15])["ok"] is True,
      pf.pack_verdict(legacy_fix, [15]))

pf.repair_pack(no_meta, [75, 84])
created = read_meta(no_meta)["pack"]
check("a pack with no pack.mcmeta gets one at the zip root",
      created["pack_format"] == 84 and created["supported_formats"] == [75, 84],
      created)
check("and the freshly created meta satisfies the verdict",
      pf.pack_verdict(no_meta, [75, 84])["ok"] is True,
      pf.pack_verdict(no_meta, [75, 84]))

pf.repair_pack(wrapped, [75])
with zipfile.ZipFile(wrapped) as zf:
    names = sorted(zf.namelist())
check("a wrapped pack is flattened so the game can see it",
      "pack.mcmeta" in names
      and not any(n.startswith("MyPack/") for n in names), names)
check("and its other entries survive the rewrite",
      "assets/minecraft/textures/x.png" in names, names)
check("the flattened pack now passes",
      pf.pack_verdict(wrapped, [75])["ok"] is True,
      pf.pack_verdict(wrapped, [75]))

check("an unreadable file is left alone rather than rewritten",
      pf.repair_pack(unreadable, [75])["changed"] is False
      and open(unreadable, "rb").read() == b"definitely not a zip",
      pf.repair_pack(unreadable, [75]))

# ---------------------------------------------------------------------------
print("\n5. shader packs (structure, not format)")
# ---------------------------------------------------------------------------
good_shader = make_zip("goodshader.zip", {
    "shaders/final.fsh": "void main() {}",
    "shaders/lang/en_us.lang": "name=Good",
}, folder=SHADERS)
check("a shader pack with shaders/ at the root is fine",
      pf.shader_verdict(good_shader)["ok"] is True,
      pf.shader_verdict(good_shader))

deep_shader = make_zip("deepshader.zip", {
    "RayTracing/shaders/final.fsh": "void main() {}",
}, folder=SHADERS)
v = pf.shader_verdict(deep_shader)
check("a shader whose shaders/ is nested is reported, with the folder named",
      v["ok"] is False and v["wrapper"] == "RayTracing", v)
check("flattening it makes the pack valid",
      pf.flatten_pack(deep_shader, v["wrapper"]) is True
      and pf.shader_verdict(deep_shader)["ok"] is True,
      pf.shader_verdict(deep_shader))
with zipfile.ZipFile(deep_shader) as zf:
    check("and the flattened shader still has its files",
          "shaders/final.fsh" in zf.namelist(), zf.namelist())

wrong_folder = make_zip("wrongfolder.zip", {
    "assets/minecraft/textures/x.png": b"png",
    "pack.mcmeta": meta_bytes(75),
}, folder=SHADERS)
check("a resource pack in shaderpacks/ is named as such",
      "resource pack" in pf.shader_verdict(wrong_folder)["reason"],
      pf.shader_verdict(wrong_folder))
check("flatten_pack refuses a pack with no wrapper",
      pf.flatten_pack(good_shader) is False)

not_a_zip = os.path.join(SHADERS, "broken.zip")
with open(not_a_zip, "wb") as fh:
    fh.write(b"nope")
check("an unreadable shader zip is reported, not raised",
      pf.shader_verdict(not_a_zip)["ok"] is False,
      pf.shader_verdict(not_a_zip))

# ===========================================================================
# The doctor itself. Each section gets its own content folders so one test's
# packs can't leak into another's counts.
# ===========================================================================
DOC_PACKS = os.path.join(SCRATCH, "doc-packs")
DOC_SHADERS = os.path.join(SCRATCH, "doc-shaders")
for path in (DOC_PACKS, DOC_SHADERS):
    os.makedirs(path, exist_ok=True)
doctor.RESOURCEPACKS_DIR = DOC_PACKS
doctor.SHADERPACKS_DIR = DOC_SHADERS

# ---------------------------------------------------------------------------
print("\n6. doctor: resource packs (the report the user sees)")
# ---------------------------------------------------------------------------
failing = make_zip("Failing Pack.zip", {"pack.mcmeta": meta_bytes(34, [34, 40]),
                                        "assets/x.png": b"png"}, folder=DOC_PACKS)
fine = make_zip("Fine Pack.zip", {"pack.mcmeta": meta_bytes(75, [75, 84]),
                                  "assets/x.png": b"png"}, folder=DOC_PACKS)
corrupt = os.path.join(DOC_PACKS, "Corrupt Pack.zip")
with open(corrupt, "wb") as fh:
    fh.write(b"not a zip")

rep = doctor.run_doctor("1.21.11", "fabric", auto_fix=False, include=("resourcepacks",))
kinds = {(p["kind"], p["item"]) for p in rep["problems"]}
check("an incompatible pack is reported (detect-only run)",
      ("pack-format", "Failing Pack") in kinds, kinds)
check("a compatible pack is NOT reported",
      not any(item == "Fine Pack" for _kind, item in kinds), kinds)
check("a corrupt pack is reported too",
      any(item == "Corrupt Pack" for _kind, item in kinds), kinds)
check("detect-only really changed nothing",
      pf.pack_verdict(failing, [75])["ok"] is False,
      pf.pack_verdict(failing, [75]))

rep = doctor.run_doctor("1.21.11", "fabric", auto_fix=True, include=("resourcepacks",))
fixed_items = {f["item"] for f in rep["fixed"]}
unfixed = {(p["kind"], p["item"]) for p in rep["unfixed"]}
check("with auto_fix the incompatible pack is repaired and reported fixed",
      "Failing Pack" in fixed_items, rep["fixed"])
check("the repair is described for the user",
      any("widened" in (entry.get("fix") or "") for entry in rep["fixed"]),
      rep["fixed"])
check("the pack the game rejected now passes",
      pf.pack_verdict(failing, [75])["ok"] is True,
      pf.pack_verdict(failing, [75]))
check("a corrupt pack is left for the user (never silently deleted)",
      ("pack-format", "Corrupt Pack") in unfixed and
      os.path.isfile(corrupt), unfixed)
check("the section reports what it checked",
      rep["sections"]["resourcepacks"]["checked"] == 3,
      rep["sections"]["resourcepacks"])
rerun = doctor.run_doctor("1.21.11", "fabric", auto_fix=True,
                          include=("resourcepacks",))
rerun_items = {p["item"] for p in rerun["problems"]}
check("a clean re-run: the repair stuck, the corrupt pack is still reported",
      "Failing Pack" not in rerun_items and
      any(item == "Corrupt Pack" for item in rerun_items), rerun_items)

# ---------------------------------------------------------------------------
print("\n7. doctor: shaders")
# ---------------------------------------------------------------------------
make_zip("Deep Shader.zip", {"RayTracing/shaders/final.fsh": "x"},
         folder=DOC_SHADERS)
make_zip("Good Shader.zip", {"shaders/final.fsh": "x"}, folder=DOC_SHADERS)
make_zip("Not A Shader.zip", {"pack.mcmeta": meta_bytes(75),
                              "assets/x.png": b"png"}, folder=DOC_SHADERS)

rep = doctor.run_doctor("1.21.11", "fabric", auto_fix=True, include=("shaders",))
fixed_items = {f["item"] for f in rep["fixed"]}
unfixed_items = {p["item"] for p in rep["unfixed"]}
check("a nested shader pack is flattened and reported fixed",
      "Deep Shader" in fixed_items, rep["fixed"])
check("the shader really is valid afterwards",
      pf.shader_verdict(os.path.join(DOC_SHADERS, "Deep Shader.zip"))["ok"] is True,
      pf.shader_verdict(os.path.join(DOC_SHADERS, "Deep Shader.zip")))
check("a healthy shader is not reported", "Good Shader" not in fixed_items | unfixed_items)
check("a resource pack in shaderpacks/ is reported, not 'fixed'",
      "Not A Shader" in unfixed_items, rep["unfixed"])
check("all three were checked",
      rep["sections"]["shaders"]["checked"] == 3, rep["sections"]["shaders"])

# ---------------------------------------------------------------------------
print("\n8. doctor: modpacks (marker vs the profile it points at)")
# ---------------------------------------------------------------------------


def make_profile(key, marker):
    profile_dir = os.path.join(PROFILES, key)
    os.makedirs(profile_dir, exist_ok=True)
    path = os.path.join(profile_dir, modpacks.MODPACK_META_FILENAME)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(marker if isinstance(marker, str) else json.dumps(marker))
    return profile_dir


def marker_json(mc_version="1.21.11", loader="fabric", mod_count=0, name="Pack"):
    return {"name": name, "mc_version": mc_version, "loader": loader,
            "version_id": f"fabric-loader-0.19.5-{mc_version}",
            "mod_count": mod_count, "pack_version": "1.0"}


make_profile("healthy", marker_json())
gutted = make_profile("gutted", marker_json(mod_count=12, name="Gutted Pack"))
make_profile("oldversion", marker_json(mc_version="1.6.4", name="Ancient Pack"))
unreadable_marker = make_profile("garbage", "{{{ not json")

rep = doctor.run_doctor("1.21.11", "fabric", auto_fix=False, include=("modpacks",))
by_item = {p["item"]: p for p in rep["problems"]}
check("a pack whose mods vanished is reported",
      by_item.get("Gutted Pack", {}).get("kind") == "pack-mods-missing",
      rep["problems"])
check("and the message says what to do about it",
      "reinstall" in by_item.get("Gutted Pack", {}).get("detail", ""),
      by_item.get("Gutted Pack"))
check("a pack whose Minecraft version isn't installed is reported",
      by_item.get("Ancient Pack", {}).get("kind") == "pack-version-missing",
      rep["problems"])
check("an unreadable tracking file is reported",
      any(p["kind"] == "pack-marker" for p in rep["problems"]),
      rep["problems"])
check("a healthy pack is not reported",
      "Pack" not in by_item, by_item)
check("every installed pack was checked",
      rep["sections"]["modpacks"]["checked"] == 4,
      rep["sections"]["modpacks"])

rep = doctor.run_doctor("1.21.11", "fabric", auto_fix=True, include=("modpacks",))
check("the unreadable tracking file is removed (the pack list stops lying)",
      not os.path.isfile(os.path.join(unreadable_marker,
                                      modpacks.MODPACK_META_FILENAME)),
      os.listdir(unreadable_marker))
check("removing it is reported as a fix",
      any(f["kind"] == "pack-marker" and "removed" in (f.get("fix") or "")
          for f in rep["fixed"]), rep["fixed"])
check("a gutted pack is NOT auto-deleted (only a reinstall can rebuild it)",
      os.path.isdir(gutted) and os.path.isfile(
          os.path.join(gutted, modpacks.MODPACK_META_FILENAME)),
      os.listdir(gutted))
check("and it stays in the unfixed list for the user",
      any(p["kind"] == "pack-mods-missing" for p in rep["unfixed"]),
      rep["unfixed"])
