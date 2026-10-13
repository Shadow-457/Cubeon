"""Settings -> Import: folder scan + one-click import (cubeon/importer.py).

Locks in:
  1. scan_folder classifies mods / resource packs / shader packs / modpacks /
     worlds correctly - deciding by what is INSIDE each archive, not by
     extension - and prunes libraries/, hidden dirs and world interiors.
  2. A corrupt/locked/odd file never aborts the scan; it lands in errors.
  3. import_item routes each kind to the right installer and the result lands
     in the PER-PROFILE folder (mods/packs) or the shared saves/ (worlds).
  4. An extracted pack folder is zipped before install; a world already in
     saves/ is not duplicated onto itself.

Modpack INSTALL is not exercised end-to-end here because it downloads every
declared mod over the network; only the dispatch is checked (mocked).
"""
import json
import os
import shutil
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_home = tempfile.mkdtemp(prefix="cubeon-importer-test-")
os.environ["HOME"] = _home
os.environ["USERPROFILE"] = _home
os.environ["CUBEON_GAME_DIR"] = os.path.join(_home, "game")

from cubeon import importer          # noqa: E402
from cubeon import mods, content     # noqa: E402

passed = failed = 0


def check(label, ok, extra=""):
    global passed, failed
    passed += ok
    failed += not ok
    print(f"  {'ok  ' if ok else 'FAIL'} {label}{(' - ' + extra) if extra and not ok else ''}")


def mkzip(path, entries):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with zipfile.ZipFile(path, "w") as z:
        for name, data in entries:
            z.writestr(name, data)


# --------------------------------------------------------------------------
# Build a fixture folder that looks like an old .minecraft plus loose files.
# --------------------------------------------------------------------------
src = os.path.join(_home, "old_mc")
mkzip(f"{src}/mods/sodium.jar",
      [("fabric.mod.json", json.dumps({"id": "sodium", "name": "Sodium",
                                       "depends": {"minecraft": "1.21"}}))])
mkzip(f"{src}/mods/forge-mod.jar",
      [("META-INF/mods.toml", 'modLoader="javafml"')])  # real Forge marker
with open(f"{src}/mods/broken.jar", "wb") as f:
    f.write(b"not a zip at all")  # must not crash the scan, must not be listed
mkzip(f"{src}/mods/plain.jar", [("some/Random.class", "x")])  # library jar

mkzip(f"{src}/resourcepacks/pack.zip",
      [("pack.mcmeta", json.dumps({"pack": {"pack_format": 34}}))])
mkzip(f"{src}/resourcepacks/nested.zip",
      [("MyPack/pack.mcmeta", json.dumps({"pack": {"pack_format": 34}}))])
os.makedirs(f"{src}/resourcepacks/extracted", exist_ok=True)
with open(f"{src}/resourcepacks/extracted/pack.mcmeta", "w") as f:
    f.write(json.dumps({"pack": {"pack_format": 34}}))

mkzip(f"{src}/shaderpacks/bsl.zip", [("shaders/composite.fsh", "void main(){}")])
mkzip(f"{src}/modpacks/mr.mrpack", [("modrinth.index.json", "{}")])
mkzip(f"{src}/modpacks/cf.zip", [("manifest.json", "{}")])

os.makedirs(f"{src}/saves/MyWorld", exist_ok=True)
with open(f"{src}/saves/MyWorld/level.dat", "wb") as f:
    f.write(b"\x00")

# Noise that must be pruned or ignored.
open(f"{src}/random.txt", "w").write("x")
mkzip(f"{src}/weird.zip", [("hello.txt", "x")])
mkzip(f"{src}/.hidden/junk.jar", [("x", "y")])
mkzip(f"{src}/libraries/lib.jar", [("x", "y")])
mkzip(f"{src}/versions/1.21/game.jar", [("x", "y")])

print("scan_folder:")
r = importer.scan_folder(src)
c = importer.counts(r)
check("2 mods found (fabric + forge only)", c["mods"] == 2, str(c))
check("3 resource packs (zip, nested zip, folder)",
      c["resourcepacks"] == 3, str(c))
check("1 shader pack", c["shaderpacks"] == 1, str(c))
check("2 modpacks", c["modpacks"] == 2, str(c))
check("1 world", c["worlds"] == 1, str(c))
check("fabric loader detected", any(e["loader"] == "fabric" for e in r["mods"]))
check("forge loader detected (mods.toml)",
      any(e["name"] == "forge-mod" and e["loader"] == "forge" for e in r["mods"]))
check("corrupt jar is skipped, not listed",
      not any(e["name"] == "broken" for e in r["mods"]))
check("plain jar (no mod metadata) is skipped",
      not any(e["name"] == "plain" for e in r["mods"]))
check("random zip (no pack.mcmeta) is skipped",
      not any(e["name"] == "weird" for e in r["resourcepacks"]))
check("libraries/ pruned", not any("libraries" in e["rel"] for e in r["mods"]))
check(".hidden/ pruned", not any(".hidden" in e["rel"] for e in r["mods"]))
check("versions/ pruned (game.jar is not a mod)",
      not any("versions" in e["rel"] for e in r["mods"]))
check("world is a dir", r["worlds"][0]["is_dir"] is True)
check("extracted pack is a dir", any(e["is_dir"] for e in r["resourcepacks"]))
check("summary reads naturally", importer.summary_line(r).startswith("Found 2 mods"),
      importer.summary_line(r))
check("total_found", importer.total_found(r) == 9, str(importer.total_found(r)))

print("scan edge cases:")
check("empty folder -> nothing", importer.total_found(
    importer.scan_folder(os.path.join(_home, "nope"))) == 0)
check("missing folder -> error, no crash",
      bool(importer.scan_folder(os.path.join(_home, "nope"))["errors"]))
check("scan of a world root still finds the world", importer.counts(
    importer.scan_folder(f"{src}/saves/MyWorld"))["worlds"] == 1)

# --------------------------------------------------------------------------
# import_item - each kind into the sandboxed game dir.
# --------------------------------------------------------------------------
MC, LOADER, VID = "1.21.11", "fabric", "fabric-loader.0.16.9-1.21.11"

print("import_item:")
mod = next(e for e in r["mods"] if e["name"] == "Sodium")
name = importer.import_item(mod, mc_version=MC, loader=LOADER)
check("mod import returns a message", "Added mod" in name, name)
pdir = mods.get_profile_dir(MC, LOADER)
check("mod landed in the profile folder",
      any(f.endswith(".jar") for f in os.listdir(pdir)), str(os.listdir(pdir)))

rp = next(e for e in r["resourcepacks"] if e["name"] == "pack")
name = importer.import_item(rp, mc_version=MC, loader=LOADER, version_id=VID)
check("resource pack import message", "Added resource pack" in name, name)
lst = [i["filename"] for i in content.list_content("resourcepack", MC, loader=LOADER)]
check("pack visible in the profile", bool(lst), str(lst))

ext = next(e for e in r["resourcepacks"] if e["is_dir"])
name = importer.import_item(ext, mc_version=MC, loader=LOADER, version_id=VID)
check("extracted pack folder import works", "Added resource pack" in name, name)
lst2 = [i["filename"] for i in content.list_content("resourcepack", MC, loader=LOADER)]
check("extracted pack now visible too", len(lst2) == 2, str(lst2))

sh = r["shaderpacks"][0]
name = importer.import_item(sh, mc_version=MC, loader=LOADER, version_id=VID)
check("shader import message", "Added shader" in name, name)

world = r["worlds"][0]
name = importer.import_item(world, mc_version=MC, loader=LOADER)
check("world import message", "Imported world" in name, name)
saves = importer.SAVES_DIR
check("world copied into shared saves/", os.path.isdir(os.path.join(saves, "MyWorld")))

# A world whose SOURCE already sits inside saves/ must not be duplicated
# onto itself (the guard that stops "import" from copying a world over).
dupe_entry = dict(world, path=os.path.join(saves, "MyWorld"), name="MyWorld")
name2 = importer.import_item(dupe_entry, mc_version=MC, loader=LOADER)
check("world already in saves/ is a no-op",
      "already in your worlds" in name2, name2)
check("no duplicate world folder created",
      not any(f.startswith("MyWorld_") for f in os.listdir(saves)),
      str(os.listdir(saves)))

# Modpack dispatch (install itself is network-bound, so it's mocked).
import cubeon.modpacks  # noqa: E402  (import_item imports it lazily)
called = {}
real = cubeon.modpacks.install_modpack_from_file


def _fake_modpack(path, **kw):
    called["path"] = path
    return {"name": "Pack", "version_id": "v1"}


cubeon.modpacks.install_modpack_from_file = _fake_modpack
try:
    mp = r["modpacks"][0]
    name = importer.import_item(mp, mc_version=MC, loader=LOADER)
finally:
    cubeon.modpacks.install_modpack_from_file = real
check("modpack routed to install_modpack_from_file", called.get("path") == mp["path"])
check("modpack message", "Installed modpack" in name, name)

# --------------------------------------------------------------------------
# Duplicate detection: re-scanning the same folder must flag what's already
# in the profile, and re-importing must refuse instead of creating twins
# (foo_xxxxxx.jar, MyWorld_xxxxxx/, a second pack link).
# --------------------------------------------------------------------------
print("mark_installed:")
scan2 = importer.scan_folder(src)
marked = importer.mark_installed(scan2, mc_version=MC, loader=LOADER)
check("mark_installed reports the flagged count", marked >= 3, str(marked))

sodium2 = next(e for e in scan2["mods"] if e["name"] == "Sodium")
check("already-imported mod is flagged", bool(sodium2.get("already")),
      str(sodium2.get("already")))
forge2 = next(e for e in scan2["mods"] if e["name"] == "forge-mod")
check("not-yet-imported mod stays unflagged", not forge2.get("already"))
pack2 = next(e for e in scan2["resourcepacks"]
             if e["name"] == "pack" and not e["is_dir"])
check("already-imported pack is flagged", bool(pack2.get("already")),
      str(pack2.get("already")))
world2 = next(e for e in scan2["worlds"])
check("already-imported world is flagged", bool(world2.get("already")),
      str(world2.get("already")))
mp2 = scan2["modpacks"][0]
check("modpacks are never flagged", not mp2.get("already"))
check("summary mentions the already count", "already added" in
      importer.summary_line(scan2), importer.summary_line(scan2))
check("caches the source hash for the import guard",
      bool(sodium2.get("_src_sha")), str(sodium2.get("_src_sha")))

print("import refuses duplicates:")
name = importer.import_item(sodium2, mc_version=MC, loader=LOADER)
check("re-import of the same jar bytes is refused",
      "already in this profile" in name, name)
jars = [f for f in os.listdir(mods.get_profile_dir(MC, LOADER))
        if f.endswith(".jar")]
check("no suffixed twin jar created", jars == ["sodium.jar"], str(jars))

name = importer.import_item(pack2, mc_version=MC, loader=LOADER, version_id=VID)
check("re-import of the same pack bytes is refused",
      "already in this profile" in name, name)
check("still exactly two packs in the profile",
      len(content.list_content("resourcepack", MC, loader=LOADER)) == 2,
      str(content.list_content("resourcepack", MC, loader=LOADER)))

name = importer.import_item(world2, mc_version=MC, loader=LOADER)
check("re-import of the same world name is refused",
      "already in your worlds" in name, name)
check("no suffixed twin world folder created",
      not any(f.startswith("MyWorld_") for f in os.listdir(importer.SAVES_DIR)),
      str(os.listdir(importer.SAVES_DIR)))

# A clean scan of a fresh target finds nothing flagged.
scan3 = importer.scan_folder(src)
check("no flags without a version/loader target",
      importer.mark_installed(scan3, mc_version=None, loader=None) == 0 and
      not any(e.get("already") for c in importer.CATEGORIES
              for e in scan3[c]))

print("import error paths:")
try:
    importer.import_item(mod, mc_version=None, loader=None)
    check("no version/loader -> ValueError", False)
except ValueError:
    check("no version/loader -> ValueError", True)
try:
    importer.import_item({"kind": "nope", "path": "/x", "name": "x"},
                         mc_version=MC, loader=LOADER)
    check("unknown kind -> ValueError", False)
except ValueError:
    check("unknown kind -> ValueError", True)

shutil.rmtree(_home, ignore_errors=True)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
