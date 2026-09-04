"""Keyless CurseForge pack conversion - the path that makes RLCraft installable.

A CurseForge pack is a plain zip of manifest.json + overrides/, where every mod
is only a (projectID, fileID) pair. Converting that into a `.mrpack` is what
lets the existing hardened installer handle it. There are two ways to resolve
those pairs: the API batch endpoint (needs a key) and CF's keyless download
redirect. These tests cover the keyless one, because with no key configured -
the default for every Cubeon user - it is the ONLY one that can run.

Run: python3 tools/test_modpacks_cf_keyless.py
"""
import io
import json
import os
import sys
import tempfile
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# --- sandbox: redirect HOME to a scratch dir before cubeon binds its paths at
# import time, so tests never read/write the developer's real game dir/store.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import modpacks  # noqa: E402

_passed, _failed = 0, 0


def ok(cond, label):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"  FAIL {label}")


def make_cf_pack(path, *, loaders, files, overrides=None, mc="1.12.2"):
    """A minimal but realistic CurseForge pack zip."""
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("manifest.json", json.dumps({
            "manifestType": "minecraftModpack",
            "name": "RLCraft",
            "version": "2.9.3",
            "minecraft": {"version": mc, "modLoaders": loaders},
            "files": files,
            "overrides": "overrides",
        }))
        for rel, data in (overrides or {}).items():
            z.writestr(f"overrides/{rel}", data)


def convert(pack_zip, *, key):
    """Run the converter with the API key forced present/absent."""
    orig = modpacks._curseforge_api_key
    modpacks._curseforge_api_key = lambda: key
    try:
        fd, dest = tempfile.mkstemp(suffix=".mrpack")
        os.close(fd)
        try:
            index = modpacks._cf_manifest_to_mrpack(
                pack_zip, dest, status_cb=lambda *_: None)
            with zipfile.ZipFile(dest) as z:
                names = z.namelist()
                written = json.loads(z.read("modrinth.index.json"))
            return index, names, written
        finally:
            os.remove(dest)
    finally:
        modpacks._curseforge_api_key = orig


tmp = tempfile.mkdtemp(prefix="cf_keyless_")
FORGE = [{"id": "forge-14.23.5.2860", "primary": True}]
FILES = [
    {"projectID": 238222, "fileID": 2765029, "required": True},
    {"projectID": 310111, "fileID": 2739022, "required": True},
]

print("keyless conversion (no API key - the default install)")
pack = os.path.join(tmp, "rlcraft.zip")
make_cf_pack(pack, loaders=FORGE, files=FILES,
             overrides={"config/rlcraft.cfg": b"hardcore=true",
                        "options.txt": b"fov:1.0"})

# The bug: with no key this used to call the key-only batch endpoint, and
# requests refuses a None header value before any network call happens.
index, names, written = convert(pack, key=None)

ok(len(index["files"]) == 2, "keyless: every manifest entry became a file entry")
ok(all(f["path"].startswith("mods/") and f["path"].endswith(".jar")
       for f in index["files"]),
   "keyless: entries route to mods/*.jar so they land in the mod profile")
ok(all(f["downloads"] and modpacks._host_allowed(f["downloads"][0])
       for f in index["files"]),
   "keyless: every download URL passes the host allowlist")
ok(all("curseforge.com" in f["downloads"][0] for f in index["files"]),
   "keyless: resolves via CF's keyless download redirect")
ok(index["dependencies"].get("minecraft") == "1.12.2",
   "keyless: minecraft version carried over")
ok(index["dependencies"].get("forge") == "14.23.5.2860",
   "keyless: forge loader version translated to the mrpack dep key")
ok("overrides/config/rlcraft.cfg" in names and "overrides/options.txt" in names,
   "keyless: pack overrides (configs) are preserved - RLCraft is config-driven")
ok(written == index, "keyless: the written index matches the returned one")

print()
print("the converted pack is valid input to the real installer")
# parse_dependencies is what the installer uses to decide version+loader. If the
# conversion is wrong, this is where it shows up.
mc_v, loader_id, loader_v = modpacks.parse_dependencies(index)
ok((mc_v, loader_id) == ("1.12.2", "forge"),
   "installer reads back mc=1.12.2 / loader=forge")
ok(loader_v == "14.23.5.2860", "installer reads back the forge build")
summary = modpacks.summarize(index)
ok(summary["mod_count"] == 2, "summarize() counts the pack's mods")

print()
print("loader translation (a CF Fabric pack used to convert to a vanilla pack)")
fab = os.path.join(tmp, "fabricpack.zip")
make_cf_pack(fab, loaders=[{"id": "fabric-0.14.9", "primary": True}],
             files=FILES[:1], mc="1.20.1")
fi, _, _ = convert(fab, key=None)
ok(fi["dependencies"].get("fabric-loader") == "0.14.9",
   "fabric -> 'fabric-loader' dep key (was silently dropped => installed vanilla)")
ok(modpacks.parse_dependencies(fi)[1] == "fabric",
   "installer reads back loader=fabric, so the pack's mods can load")

quilt = os.path.join(tmp, "quiltpack.zip")
make_cf_pack(quilt, loaders=[{"id": "quilt-0.20.0", "primary": True}],
             files=FILES[:1], mc="1.20.1")
qi, _, _ = convert(quilt, key=None)
ok(modpacks.parse_dependencies(qi)[1] == "quilt", "quilt -> loader=quilt")

neo = os.path.join(tmp, "neopack.zip")
make_cf_pack(neo, loaders=[{"id": "neoforge-21.1.1", "primary": True}],
             files=FILES[:1], mc="1.21.1")
ni, _, _ = convert(neo, key=None)
ok(modpacks.parse_dependencies(ni)[1] == "neoforge", "neoforge -> loader=neoforge")

print()
print("the `primary` loader wins when a manifest lists several")
multi = os.path.join(tmp, "multi.zip")
make_cf_pack(multi, loaders=[{"id": "fabric-0.14.9", "primary": False},
                             {"id": "forge-14.23.5.2860", "primary": True}],
             files=FILES[:1])
mi, _, _ = convert(multi, key=None)
ok(modpacks.parse_dependencies(mi)[1] == "forge",
   "primary loader chosen, not just the first listed")

print()
print("refusals stay refusals")
bad = os.path.join(tmp, "bad.zip")
with zipfile.ZipFile(bad, "w") as z:
    z.writestr("manifest.json", json.dumps({"manifestType": "somethingElse"}))
try:
    convert(bad, key=None)
    ok(False, "unexpected manifest type refused")
except modpacks.ModpackError:
    ok(True, "unexpected manifest type refused")

nomc = os.path.join(tmp, "nomc.zip")
with zipfile.ZipFile(nomc, "w") as z:
    z.writestr("manifest.json", json.dumps({
        "manifestType": "minecraftModpack", "minecraft": {}, "files": []}))
try:
    convert(nomc, key=None)
    ok(False, "missing minecraft version refused")
except modpacks.ModpackError:
    ok(True, "missing minecraft version refused")

# A pack whose every file is unresolvable must fail loudly, not install empty.
unresolvable = os.path.join(tmp, "unres.zip")
make_cf_pack(unresolvable, loaders=FORGE, files=FILES)
_orig_url = modpacks._cf_download_url
modpacks._cf_download_url = lambda p, f: "http://evil.example.com/x.jar"
try:
    convert(unresolvable, key=None)
    ok(False, "a pack with no resolvable mods fails loudly")
except modpacks.ModpackError:
    ok(True, "a pack with no resolvable mods fails loudly")
finally:
    modpacks._cf_download_url = _orig_url

# _cf_batch_files must refuse without a key rather than raise InvalidHeader.
_orig = modpacks._curseforge_api_key
modpacks._curseforge_api_key = lambda: None
try:
    modpacks._cf_batch_files([{"projectID": 1, "fileID": 2}])
    ok(False, "_cf_batch_files refuses cleanly with no key")
except modpacks.ModpackError:
    ok(True, "_cf_batch_files refuses cleanly with no key")
except Exception as ex:
    ok(False, f"_cf_batch_files refuses cleanly with no key (got {type(ex).__name__})")
finally:
    modpacks._curseforge_api_key = _orig

print()
print("importing a pack file from disk detects the format by content")
# The one import route that needs no metadata service at all: download the pack
# from the website, import the zip. Format is decided by what's inside, since a
# .mrpack is itself a zip and browsers/users rename files freely.
ok(modpacks.install_modpack_from_file.__doc__ is not None,
   "install_modpack_from_file is documented")

notazip = os.path.join(tmp, "notazip.mrpack")
with open(notazip, "wb") as fh:
    fh.write(b"this is not a zip at all")
try:
    modpacks.install_modpack_from_file(notazip)
    ok(False, "a non-archive is refused with a readable message")
except modpacks.ModpackError as ex:
    ok("readable archive" in str(ex), "a non-archive is refused with a readable message")

neither = os.path.join(tmp, "neither.zip")
with zipfile.ZipFile(neither, "w") as z:
    z.writestr("random.txt", b"nope")
try:
    modpacks.install_modpack_from_file(neither)
    ok(False, "a zip with no pack manifest is refused")
except modpacks.ModpackError as ex:
    ok("neither" in str(ex).lower(), "a zip with no pack manifest is refused")

try:
    modpacks.install_modpack_from_file(os.path.join(tmp, "does_not_exist.zip"))
    ok(False, "a missing file is refused")
except modpacks.ModpackError:
    ok(True, "a missing file is refused")

# A CurseForge zip is now recognised and routed to the converter. Stop right
# after conversion (install_version would hit the network / real disk).
_orig_install = modpacks._install_from_zip
_seen = {}


def _capture(zip_path, **kw):
    with zipfile.ZipFile(zip_path) as z:
        _seen["index"] = json.loads(z.read("modrinth.index.json"))
        _seen["names"] = z.namelist()
    return {"name": "stopped"}


modpacks._install_from_zip = _capture
_origkey = modpacks._curseforge_api_key
modpacks._curseforge_api_key = lambda: None
try:
    modpacks.install_modpack_from_file(pack)
    ok(_seen.get("index") is not None,
       "a CurseForge .zip on disk is converted, not rejected for its extension")
    ok(_seen["index"]["dependencies"].get("forge") == "14.23.5.2860",
       "the disk-imported CF pack keeps its loader")
    ok(len(_seen["index"]["files"]) == 2,
       "the disk-imported CF pack keeps its mods")
    ok("overrides/config/rlcraft.cfg" in _seen["names"],
       "the disk-imported CF pack keeps its configs")
finally:
    modpacks._install_from_zip = _orig_install
    modpacks._curseforge_api_key = _origkey

print()
print(f"{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
