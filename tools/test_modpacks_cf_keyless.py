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
print("browse rows carry the data the UI renders (the '0 downloads' bug)")
# The rows used to hardcode icon_url/author to None and read `downloads` as a
# SCALAR, while cfwidget sends {"monthly": N, "total": N} - so every
# CurseForge row rendered as a blank square saying "0 downloads".
WIDGET = {
    "id": 285109,
    "title": "RLCraft",
    "summary": "hardcore survival",
    "thumbnail": "https://media.forgecdn.net/avatars/thumbnails/468/243/256/256/1.png",
    "downloads": {"monthly": 123, "total": 30174116},
    "members": [{"title": "Owner", "username": "Shivaxi", "id": 11806322}],
    "urls": {"curseforge": "https://www.curseforge.com/minecraft/modpacks/rlcraft"},
    "versions": {
        "1.12.2": [{"id": 4612979, "name": "x.zip", "versions": ["Forge", "1.12.2"]}],
        "1.11.2": [{"id": 2532808, "name": "y.zip", "versions": ["1.11.2"]}],
    },
    "files": [],
}
hit = modpacks._cfwidget_to_hit(WIDGET)
ok(hit is not None and hit["icon_url"] == WIDGET["thumbnail"],
   "browse row: the pack's real thumbnail is used")
ok(hit["downloads"] == 30174116,
   "browse row: downloads.total is read (a scalar read printed 0 for RLCraft's 30M)")
ok(hit["author"] == "Shivaxi", "browse row: the author is filled in")
ok(hit["versions"] == ["1.12.2", "1.11.2"],
   "browse row: MC versions come from the grouped payload, loader tags dropped")
ok(hit["project_id"] == "285109" and hit["slug"] == "rlcraft",
   "browse row: id + slug route the install back to CurseForge")

legacy = modpacks._cfwidget_to_hit({
    "id": 7, "title": "Old shape", "files": [{"versions": ["1.16.5"]}],
    "downloads": 42,
})
ok(legacy["downloads"] == 42 and legacy["versions"] == ["1.16.5"],
   "browse row: the older flat files[] + scalar downloads shape still parses")
ok(modpacks._cfwidget_to_hit({"title": "no id"}) is None,
   "browse row: a payload with no id is skipped, not rendered half-empty")

print()
print("the curated catalogue is id-based (slugs rot and silently 404)")
paths = modpacks.CURATED_CF_PROJECTS
ok(all(p.startswith(("cf/mods/", "modpacks/")) for p in paths),
   "every curated entry is a resolvable cfwidget path")
ok(sum(1 for p in paths if p.startswith("cf/mods/")) >= 8,
   "project IDs are the default (ids survive renames, slugs do not)")
ok(not hasattr(modpacks, "CURATED_CF_SLUGS"),
   "the slug list that rotted from 12 to 7 live entries is gone")

print()
print("the free CurseForge key path: validate, store, clear (offline)")
# These calls must never touch the network in a test.
_orig_request = modpacks._cf_request


def _fake_cf_request(path, params=None, timeout=10, key=None):
    if key == "good-key":
        return {"data": [{"id": 1}, {"id": 2}, {"id": 3}]}
    raise RuntimeError("403 Client Error: Forbidden")


modpacks._cf_request = _fake_cf_request
try:
    ok(modpacks.check_curseforge_api_key("")["ok"] is False,
       "an empty key is refused without a request")
    ok(modpacks.check_curseforge_api_key("bad-key")["ok"] is False,
       "a rejected key is REPORTED, not raised into the UI")
    good = modpacks.check_curseforge_api_key("good-key")
    ok(good["ok"] is True and good["count"] == 3,
       "a working key is confirmed with a real modpack count")
    ok(modpacks.curseforge_enabled() is bool(modpacks._builtin_curseforge_api_key()),
       "validating never stores anything by itself")

    ok(modpacks.set_curseforge_api_key("good-key") is True,
       "the key round-trips through config.json")
    ok(modpacks.curseforge_enabled() is True, "a stored key unlocks the provider")
    ok(modpacks.set_curseforge_api_key("") is True, "the key can be removed again")
    # A build can now carry ONE shipped key (cubeon/_cf_key.py), so "removed"
    # means "back to whatever this build has", not necessarily keyless.
    _builtin = bool(modpacks._builtin_curseforge_api_key())
    ok(modpacks.curseforge_enabled() is _builtin,
       f"removing the override falls back to the build's own key "
       f"(builtin={_builtin})")
finally:
    modpacks._cf_request = _orig_request

# Pasting/removing a key swaps providers, so the CF cache must not serve the
# other provider's page (it used to, for up to a day).
_captured = {}
_orig_cached_call = modpacks.local_cache.cached_call
modpacks.local_cache.cached_call = lambda ns, key, fetch, **kw: (
    _captured.setdefault("key", key) and [] or [])
try:
    modpacks.search_modpacks_curseforge("x", limit=5)
finally:
    modpacks.local_cache.cached_call = _orig_cached_call
ok(isinstance(_captured.get("key"), dict) and "keyed" in _captured["key"],
   "the CF search cache key records whether a key is configured")

print()
print("one shared key ships with the build (no per-user key)",
      "(offline)")
# The key is injected at PACKAGE time as cubeon/_cf_key.py (gitignored, written
# by tools/write_cf_key.py from the CURSEFORGE_API_KEY secret). Precedence is
# env > local override file > config.json > builtin, so a build can be pointed
# elsewhere without rebuilding, and a source checkout with no generated module
# behaves like a build made without the secret.
import types as _types

FAKE = "$2a$10$builtin-test-key"
_fake_module = _types.ModuleType("cubeon._cf_key")
_fake_module.BUILTIN_KEY = FAKE
import cubeon as _pkg
_real_module = sys.modules.get("cubeon._cf_key")
_had_attr = hasattr(_pkg, "_cf_key")
_attr_was = getattr(_pkg, "_cf_key", None)
sys.modules["cubeon._cf_key"] = _fake_module
_pkg._cf_key = _fake_module
_orig_env = os.environ.pop("CURSEFORGE_API_KEY", None)
_orig_home = modpacks.CUBEON_HOME if hasattr(modpacks, "CUBEON_HOME") else None
try:
    ok(modpacks._builtin_curseforge_api_key() == FAKE,
       "the packaged key is read from cubeon/_cf_key.py")
    # No env, no local file, no config -> the builtin one is used.
    import cubeon.config as _cfgmod
    _orig_load = _cfgmod.load_config
    _cfgmod.load_config = lambda *a, **k: {}
    _orig_join = os.path.join
    _real_exists = os.path.exists

    def _no_override_file(path):
        # Hide only the ~/.cubeon_launcher/curseforge_api_key override.
        if str(path).endswith(os.path.join(".cubeon_launcher",
                                           "curseforge_api_key")):
            return False
        return _real_exists(path)
    _orig_isfile = os.path.isfile
    try:
        os.path.isfile = _no_override_file
        ok(modpacks._curseforge_api_key() == FAKE,
           "with nothing configured, the shipped key is the provider's gate")
        ok(modpacks.curseforge_enabled() is True,
           "so a stock build has the full catalogue with no user action")

        os.environ["CURSEFORGE_API_KEY"] = "env-wins"
        ok(modpacks._curseforge_api_key() == "env-wins",
           "an environment variable still overrides the shipped key")
    finally:
        os.environ.pop("CURSEFORGE_API_KEY", None)
        os.path.isfile = _orig_isfile
        _cfgmod.load_config = _orig_load

    # Missing generated module (a source checkout, or a build made without the
    # secret) must degrade, never raise.
    sys.modules.pop("cubeon._cf_key", None)
    sys.modules["cubeon._cf_key"] = None      # forces ImportError on `from .` import
    delattr(_pkg, "_cf_key")
    ok(modpacks._builtin_curseforge_api_key() == "",
       "no generated module -> no builtin key, and no exception")
finally:
    if _real_module is not None:
        sys.modules["cubeon._cf_key"] = _real_module
    else:
        sys.modules.pop("cubeon._cf_key", None)
    if _had_attr:
        _pkg._cf_key = _attr_was
    elif hasattr(_pkg, "_cf_key"):
        delattr(_pkg, "_cf_key")
    if _orig_env is not None:
        os.environ["CURSEFORGE_API_KEY"] = _orig_env

print()
print("a key CurseForge REFUSES for /mods/search must not empty the tab")
# Seen live 2026-10-18 with a valid key: /v1/mods/{id}, /v1/games and
# /v1/mods/{id}/files all answer 200, but /v1/mods/search answers 403 "API Key
# missing or invalid". Before this guard the keyed path returned [] there, so
# adding a key made the CurseForge half of the tab EMPTIER than having none.
_orig_key = modpacks._curseforge_api_key
_orig_req = modpacks._cf_request
_orig_widget = modpacks._cfwidget_search
_calls = {"widget": 0}


def _refusing_request(path, params=None, timeout=10, key=None):
    raise RuntimeError("403 Forbidden: API Key missing or invalid")


def _fake_widget(query, limit):
    _calls["widget"] += 1
    return [{"source": "curseforge", "project_id": "285109",
             "title": "RLCraft", "downloads": 1}]


try:
    modpacks._curseforge_api_key = lambda: "a-valid-but-refused-key"
    modpacks._cf_request = _refusing_request
    modpacks._cfwidget_search = _fake_widget

    first = modpacks._curseforge_search("rlcraft", None, 5, 0)
    ok(len(first) == 1 and first[0]["title"] == "RLCraft"
       and _calls["widget"] == 1,
       f"a refused search falls back to the keyless curated hits: {first!r}")
    later = modpacks._curseforge_search("rlcraft", None, 5, 40)
    ok(later == [] and _calls["widget"] == 1,
       f"but only on the first page (cfwidget cannot paginate): {later!r}")

    # And a working key still uses the API, never the fallback.
    def _working_request(path, params=None, timeout=10, key=None):
        return {"data": [{"id": 1, "name": "From API", "slug": "from-api",
                          "summary": "s", "downloadCount": 5}]}
    modpacks._cf_request = _working_request
    api_hits = modpacks._curseforge_search("x", None, 5, 0)
    ok(len(api_hits) == 1 and api_hits[0]["title"] == "From API"
       and _calls["widget"] == 1,
       f"a healthy keyed search does not touch cfwidget: {api_hits!r}")
finally:
    modpacks._curseforge_api_key = _orig_key
    modpacks._cf_request = _orig_req
    modpacks._cfwidget_search = _orig_widget

print()
print("the build-time key writer (tools/write_cf_key.py)")
import importlib.util as _ilu
_writer_path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "write_cf_key.py")
_spec = _ilu.spec_from_file_location("write_cf_key", _writer_path)
_writer = _ilu.module_from_spec(_spec)
_spec.loader.exec_module(_writer)
with tempfile.TemporaryDirectory() as _tmp:
    target = os.path.join(_tmp, "_cf_key.py")
    _orig_target = _writer.TARGET
    _writer.TARGET = __import__("pathlib").Path(target)
    try:
        _orig_wenv = os.environ.pop("CURSEFORGE_API_KEY", None)
        ok(_writer.main() == 0 and not os.path.exists(target),
           "no secret -> no module, and the build still succeeds")
        with open(target, "w") as _fh:
            _fh.write("BUILTIN_KEY = 'stale'\n")
        _writer.main()
        ok(not os.path.exists(target),
           "a stale generated key is removed when the secret is gone")
        os.environ["CURSEFORGE_API_KEY"] = "  secret-key  "
        ok(_writer.main() == 0, "with a secret it writes the module")
        text = open(target).read()
        ok("BUILTIN_KEY = 'secret-key'" in text,
           f"the value is written verbatim, whitespace trimmed: {text[-40:]!r}")
        ok("Do not commit" in text, "and the file says it must not be committed")
    finally:
        _writer.TARGET = _orig_target
        if _orig_wenv is not None:
            os.environ["CURSEFORGE_API_KEY"] = _orig_wenv
        else:
            os.environ.pop("CURSEFORGE_API_KEY", None)

_repo = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_gi = open(os.path.join(_repo, ".gitignore"), encoding="utf-8").read()
ok("cubeon/_cf_key.py" in _gi,
   "the generated key module is gitignored (this repo is public)")
_wf = open(os.path.join(_repo, ".github", "workflows", "build.yml"),
           encoding="utf-8").read()
ok(_wf.count("tools/write_cf_key.py") == 3,
   f"all three build jobs inject the key before packaging "
   f"(found {_wf.count('tools/write_cf_key.py')})")
ok("secrets.CURSEFORGE_API_KEY" in _wf,
   "from the CURSEFORGE_API_KEY secret, never from the tree")
_mp_src = open(os.path.join(_repo, "ui", "modpacks_tab.py"),
               encoding="utf-8").read()
ok("cf_key_btn" not in _mp_src and "open_cf_key_dialog" not in _mp_src,
   "the per-user 'paste your key' control is gone by design")

print()
print(f"{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
