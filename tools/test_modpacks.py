"""
Offline test for cubeon/modpacks.py - the .mrpack installer.

No network, no display, no real Minecraft install: install_version /
install_mod_loader are stubbed to record their calls, requests.get is faked to
serve known bytes for known URLs, and MINECRAFT_DIR / the profile dir are
redirected into a scratch tempdir. What's actually exercised is the real logic
that would only otherwise fail in front of a user: manifest parsing, loader
mapping, the mods->profile / everything-else->game-dir routing, client-env
filtering, host allowlisting, hash verification, and zip-slip refusal.
"""
import hashlib
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

from cubeon import modpacks

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


# --- fake network: URL -> bytes -------------------------------------------
_BLOBS = {}


class _FakeResp:
    def __init__(self, data):
        self._data = data
        self.headers = {"content-length": str(len(data))}
        self.status_code = 200

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False

    def close(self):
        pass

    def raise_for_status(self):
        pass

    def iter_content(self, chunk_size=1):
        for i in range(0, len(self._data), chunk_size):
            yield self._data[i:i + chunk_size]


def _fake_get(url, headers=None, stream=False, timeout=None):
    if url not in _BLOBS:
        raise AssertionError(f"unexpected download URL: {url}")
    return _FakeResp(_BLOBS[url])


# --- build a synthetic .mrpack --------------------------------------------

def build_mrpack(path):
    mod_bytes = b"FAKE SODIUM JAR CONTENT"
    mod_url = "https://cdn.modrinth.com/data/AABBCC/versions/x/sodium.jar"
    _BLOBS[mod_url] = mod_bytes

    rp_bytes = b"FAKE RESOURCEPACK ZIP"
    rp_url = "https://cdn.modrinth.com/data/DDEEFF/versions/y/pack.zip"
    _BLOBS[rp_url] = rp_bytes

    index = {
        "formatVersion": 1,
        "game": "minecraft",
        "versionId": "2.1.0",
        "name": "Test Pack",
        "summary": "a test pack",
        "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.7"},
        "files": [
            {  # a client mod, correct sha512 -> must land in the profile
                "path": "mods/sodium.jar",
                "hashes": {"sha512": hashlib.sha512(mod_bytes).hexdigest()},
                "env": {"client": "required", "server": "unsupported"},
                "downloads": [mod_url],
                "fileSize": len(mod_bytes),
            },
            {  # a resourcepack, no hash -> must land in the shared game dir
                "path": "resourcepacks/pack.zip",
                "downloads": [rp_url],
                "fileSize": len(rp_bytes),
            },
            {  # server-only -> must be SKIPPED on the client
                "path": "mods/server-only.jar",
                "env": {"client": "unsupported", "server": "required"},
                "downloads": ["https://cdn.modrinth.com/data/SERVER/versions/z/s.jar"],
            },
        ],
    }
    with zipfile.ZipFile(path, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(index))
        zf.writestr("overrides/config/sodium-options.json", b"{ }")   # -> game dir
        zf.writestr("overrides/mods/extra-bundled.jar", b"BUNDLED")    # -> profile
        zf.writestr("server-overrides/config/server.txt", b"nope")    # -> ignored


# --- run -------------------------------------------------------------------

def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-mp-")
    game_dir = os.path.join(scratch, "minecraft")
    profile_dir = os.path.join(scratch, "profile")
    os.makedirs(game_dir)
    os.makedirs(profile_dir)

    calls = {"version": None, "loader": None}
    modpacks.MINECRAFT_DIR = game_dir
    modpacks.requests.get = _fake_get
    modpacks.install_version = lambda v, *a, **k: calls.__setitem__("version", v)
    modpacks.install_mod_loader = lambda lid, v, *a, **k: (calls.__setitem__("loader", (lid, v)) or "fabric-loader-0.15.7-1.20.1")
    modpacks.get_profile_dir = lambda mc, loader: profile_dir

    # --- pure helpers ---
    idx = {"dependencies": {"minecraft": "1.20.1", "quilt-loader": "1.2"}}
    check("parse deps: quilt-loader -> quilt", modpacks.parse_dependencies(idx)[1] == "quilt")
    check("parse deps: neoforge -> neoforge",
          modpacks.parse_dependencies({"dependencies": {"minecraft": "1.21", "neoforge": "21"}})[1] == "neoforge")
    check("parse deps: no loader -> vanilla",
          modpacks.parse_dependencies({"dependencies": {"minecraft": "1.21"}})[1] == "vanilla")
    try:
        modpacks.parse_dependencies({"dependencies": {}})
        check("parse deps: missing minecraft raises", False)
    except modpacks.ModpackError:
        check("parse deps: missing minecraft raises", True)

    # Future-proofing regression: an unrecognized loader key (a future
    # Modrinth loader, or just an unfamiliar spelling) must refuse rather
    # than silently default to vanilla - silently dropping mod-loader
    # requirements is a worse failure than a clear error, since the pack's
    # mods would then just never load with no indication why.
    try:
        modpacks.parse_dependencies({"dependencies": {"minecraft": "1.22", "some-future-loader": "1.0"}})
        check("parse deps: unrecognized loader key raises, not silent vanilla", False)
    except modpacks.ModpackError as ex:
        check("parse deps: unrecognized loader key raises, not silent vanilla",
              "some-future-loader" in str(ex), str(ex))

    check("host allow: cdn.modrinth.com", modpacks._host_allowed("https://cdn.modrinth.com/a.jar"))
    check("host allow: raw.githubusercontent.com", modpacks._host_allowed("https://raw.githubusercontent.com/a/b.jar"))
    check("host deny: http (not https)", not modpacks._host_allowed("http://cdn.modrinth.com/a.jar"))
    check("host deny: untrusted host", not modpacks._host_allowed("https://evil.example.com/a.jar"))
    check("host deny: lookalike suffix", not modpacks._host_allowed("https://modrinth.com.evil.net/a.jar"))

    try:
        modpacks._safe_relpath(game_dir, "../../etc/passwd")
        check("zip-slip: ../ refused", False)
    except modpacks.ModpackError:
        check("zip-slip: ../ refused", True)
    check("safe path: absolute is clamped into base",
          modpacks._safe_relpath(game_dir, "/config/x.json").startswith(os.path.abspath(game_dir) + os.sep))

    # --- full install ---
    mrpack = os.path.join(scratch, "test.mrpack")
    build_mrpack(mrpack)
    meta = modpacks.install_modpack_from_file(mrpack)

    check("install: version installed", calls["version"] == "1.20.1", calls["version"])
    check("install: loader installed", calls["loader"] == ("fabric", "1.20.1"), calls["loader"])
    check("install: returns launchable version_id",
          meta.get("version_id") == "fabric-loader-0.15.7-1.20.1", meta.get("version_id"))
    check("install: meta name/loader/mc",
          meta["name"] == "Test Pack" and meta["loader"] == "fabric" and meta["mc_version"] == "1.20.1")

    sodium = os.path.join(profile_dir, "sodium.jar")
    check("route: declared mod -> profile", os.path.isfile(sodium))
    check("route: declared mod content intact",
          os.path.isfile(sodium) and open(sodium, "rb").read() == b"FAKE SODIUM JAR CONTENT")
    check("route: server-only mod SKIPPED",
          not os.path.isfile(os.path.join(profile_dir, "server-only.jar")))
    check("route: resourcepack -> game dir",
          os.path.isfile(os.path.join(game_dir, "resourcepacks", "pack.zip")))
    check("route: override config -> game dir",
          os.path.isfile(os.path.join(game_dir, "config", "sodium-options.json")))
    check("route: override mod -> profile",
          os.path.isfile(os.path.join(profile_dir, "extra-bundled.jar")))
    check("route: server-overrides ignored",
          not os.path.isfile(os.path.join(game_dir, "config", "server.txt")))
    check("meta: modpack manifest written",
          os.path.isfile(os.path.join(profile_dir, modpacks.MODPACK_META_FILENAME)))

    # --- reinstall: stale _modpack.json is dropped the moment a rebuild starts ---
    # Regression coverage: reinstalling a pack that was already installed (an
    # update/repair, or a different pack sharing the same version+loader
    # profile) used to leave the old marker on disk for the whole download, so
    # the Modpacks tab listed it as "Installed" - Play button included - while
    # the progress bar was still running a half-rebuilt instance underneath.
    # The marker must be removed before the first "Installing Minecraft"
    # status fires (which is the first status _install_from_zip emits) and only
    # re-written once the rebuild actually finishes.
    marker = os.path.join(profile_dir, modpacks.MODPACK_META_FILENAME)
    check("reinstall: pack is marked installed before reinstalling",
          os.path.isfile(marker))
    seen = {}

    def reinstall_status(text):
        if "first" not in seen:
            seen["first"] = text
            seen["marker_gone_at_first_status"] = not os.path.isfile(marker)

    meta2 = modpacks.install_modpack_from_file(mrpack, status_cb=reinstall_status)
    check("reinstall: first status is the MC-version step",
          seen.get("first") == "Installing Minecraft 1.20.1", seen.get("first"))
    check("reinstall: stale marker removed BEFORE the first status callback",
          seen.get("marker_gone_at_first_status") is True, seen)
    check("reinstall: marker rewritten once the rebuild succeeded",
          os.path.isfile(marker))
    check("reinstall: returned meta reflects the pack",
          meta2.get("name") == "Test Pack" and meta2.get("version_id") == "fabric-loader-0.15.7-1.20.1")

    # --- forget_modpack_for_version: cleans up the tracking record only ---
    # Regression coverage: deleting a version used to leave this pack listed
    # as "installed" forever, since versions.delete_version() only touches
    # .minecraft/versions/<id> and has no reason to know about modpacks.
    modpacks.PROFILES_DIR = scratch  # profile_dir ("<scratch>/profile") is a child of this
    with open(os.path.join(profile_dir, modpacks.MODPACK_META_FILENAME), "r", encoding="utf-8") as fh:
        written_meta = json.load(fh)
    real_version_id = written_meta["version_id"]

    installed_before = modpacks.list_installed_modpacks()
    check("forget_modpack_for_version: pack is listed before forgetting",
          any(p.get("version_id") == real_version_id for p in installed_before), installed_before)

    forgot_wrong_id = modpacks.forget_modpack_for_version("some-other-version-id-entirely")
    check("forget_modpack_for_version: no-op / False for an unrelated version id",
          forgot_wrong_id is False)
    check("forget_modpack_for_version: unrelated call didn't remove anything",
          os.path.isfile(os.path.join(profile_dir, modpacks.MODPACK_META_FILENAME)))

    forgot = modpacks.forget_modpack_for_version(real_version_id)
    check("forget_modpack_for_version: returns True when a record was removed", forgot is True)
    check("forget_modpack_for_version: _modpack.json is actually gone",
          not os.path.isfile(os.path.join(profile_dir, modpacks.MODPACK_META_FILENAME)))
    check("forget_modpack_for_version: mod jars are left untouched (not a delete)",
          os.path.isfile(sodium))
    check("forget_modpack_for_version: the profile folder itself is left untouched",
          os.path.isdir(profile_dir))

    installed_after = modpacks.list_installed_modpacks()
    check("forget_modpack_for_version: pack no longer listed as installed",
          not any(p.get("version_id") == real_version_id for p in installed_after), installed_after)

    check("forget_modpack_for_version: forgetting again is a safe no-op",
          modpacks.forget_modpack_for_version(real_version_id) is False)

    # --- hash mismatch is caught ---
    bad = os.path.join(scratch, "bad.mrpack")
    bad_url = "https://cdn.modrinth.com/data/BAD/versions/x/bad.jar"
    _BLOBS[bad_url] = b"actual bytes"
    bad_index = {
        "formatVersion": 1, "game": "minecraft", "name": "Bad", "versionId": "1",
        "dependencies": {"minecraft": "1.20.1", "fabric-loader": "0.15.7"},
        "files": [{"path": "mods/bad.jar",
                   "hashes": {"sha512": hashlib.sha512(b"different bytes").hexdigest()},
                   "downloads": [bad_url]}],
    }
    with zipfile.ZipFile(bad, "w") as zf:
        zf.writestr("modrinth.index.json", json.dumps(bad_index))
    try:
        modpacks.install_modpack_from_file(bad)
        check("hash mismatch: install fails", False)
    except modpacks.ModpackError as ex:
        check("hash mismatch: install fails", "integrity" in str(ex).lower(), str(ex))

    # --- rejects a file that isn't a pack at all ---
    try:
        modpacks.install_modpack_from_file(os.path.join(scratch, "nope.txt"))
        check("reject: not a pack archive", False)
    except modpacks.ModpackError:
        check("reject: not a pack archive", True)

    # A CurseForge-style zip (manifest.json, no modrinth.index.json) is no
    # longer rejected outright - it's converted and installed, which is what
    # makes the CF-exclusive classics (RLCraft, ...) reachable. A *malformed*
    # one must still fail loudly, and now does so with a CF-specific message.
    curse = os.path.join(scratch, "curse.mrpack")
    with zipfile.ZipFile(curse, "w") as zf:
        zf.writestr("manifest.json", b"{}")  # CurseForge-style, but says nothing
    try:
        modpacks.install_modpack_from_file(curse)
        check("reject: CurseForge zip with an empty manifest", False)
    except modpacks.ModpackError as ex:
        check("reject: CurseForge zip with an empty manifest",
              "curseforge" in str(ex).lower(), str(ex))

    # A zip that is neither format is refused, naming both.
    neither = os.path.join(scratch, "neither.mrpack")
    with zipfile.ZipFile(neither, "w") as zf:
        zf.writestr("readme.txt", b"hello")
    try:
        modpacks.install_modpack_from_file(neither)
        check("reject: zip with no pack manifest of either kind", False)
    except modpacks.ModpackError as ex:
        check("reject: zip with no pack manifest of either kind",
              "modrinth.index.json" in str(ex) and "manifest.json" in str(ex), str(ex))

    # --- get_modpack_file: must not hand back a version-mismatched file ---
    # Regression coverage for the bug where the newest published version was
    # used unconditionally, regardless of whether it actually targeted the
    # requested Minecraft version - which is how an install could end up
    # feeding mll a totally unrelated version/loader-build number and
    # blowing up with a raw "UnsupportedVersion: Version 26.2 is not
    # supported" instead of a clear "no version for 1.20.1" message.
    cache_dir = os.path.join(scratch, "cache")
    os.makedirs(cache_dir, exist_ok=True)
    modpacks.local_cache.CACHE_DIR = cache_dir

    class _FakeApiResp:
        def __init__(self, payload):
            self._payload = payload

        def raise_for_status(self):
            pass

        def json(self):
            return self._payload

    def _fake_versions_get(url, params=None, headers=None, timeout=None):
        # Modrinth's own filter is advisory - simulate it being loose: the
        # newest entry does NOT match the requested game_versions, an older
        # one does. get_modpack_file must not just take versions[0].
        payload = [
            {  # newest overall, but for a totally different MC version
                "version_number": "3.0.0",
                "game_versions": ["1.21.4"],
                "loaders": ["neoforge"],
                "files": [{"primary": True, "filename": "pack-3.0.0.mrpack",
                           "url": "https://cdn.modrinth.com/data/X/versions/3/pack.mrpack",
                           "size": 1024}],
            },
            {  # older, but actually matches what was asked for
                "version_number": "2.1.0",
                "game_versions": ["1.20.1"],
                "loaders": ["fabric"],
                "files": [{"primary": True, "filename": "pack-2.1.0.mrpack",
                           "url": "https://cdn.modrinth.com/data/X/versions/2/pack.mrpack",
                           "size": 900}],
            },
        ]
        return _FakeApiResp(payload)

    modpacks.requests.get = _fake_versions_get

    matched = modpacks.get_modpack_file("some-pack", mc_version="1.20.1")
    check("get_modpack_file: matches requested mc_version, not newest overall",
          matched is not None and matched["version_number"] == "2.1.0", matched)
    check("get_modpack_file: returns the matching file's url",
          matched is not None and matched["url"].endswith("pack.mrpack") and "/2/" in matched["url"],
          matched)

    no_match = modpacks.get_modpack_file("some-pack", mc_version="1.19.2")
    check("get_modpack_file: refuses rather than falling back when nothing matches",
          no_match is None, no_match)

    unfiltered = modpacks.get_modpack_file("some-pack", mc_version=None)
    check("get_modpack_file: no mc_version given -> newest overall is fine",
          unfiltered is not None and unfiltered["version_number"] == "3.0.0", unfiltered)

    # --- get_modpack_file: resilience against a drifting/malformed API ---
    # This hits a third-party endpoint Cubeon doesn't control - a future
    # schema change, an error body, or a single odd entry shouldn't crash
    # the installer, just yield "nothing usable" instead of raising.

    def _resp_of(payload):
        return _FakeApiResp(payload)

    modpacks.requests.get = lambda *a, **k: _resp_of({"error": "rate limited"})
    check("get_modpack_file: non-list response treated as no versions",
          modpacks.get_modpack_file("weird-pack-1", mc_version="1.20.1") is None)

    modpacks.requests.get = lambda *a, **k: _resp_of([])
    check("get_modpack_file: empty list response treated as no versions",
          modpacks.get_modpack_file("weird-pack-2", mc_version="1.20.1") is None)

    modpacks.requests.get = lambda *a, **k: _resp_of([
        "not even a dict",
        {"version_number": "1.0", "game_versions": ["1.20.1"]},  # missing "files" entirely
    ])
    check("get_modpack_file: malformed entries are skipped, not fatal",
          modpacks.get_modpack_file("weird-pack-3", mc_version="1.20.1") is None)

    # A version entry whose file URL isn't on the allowlist must be refused
    # here too, not just later at actual download time - a future response
    # shape shouldn't be able to hand an unvetted host to the Install button.
    modpacks.requests.get = lambda *a, **k: _resp_of([
        {"version_number": "1.0", "game_versions": ["1.20.1"], "date_published": "2026-01-01",
         "files": [{"primary": True, "filename": "sus.mrpack",
                    "url": "https://evil.example.com/sus.mrpack", "size": 10}]},
    ])
    check("get_modpack_file: refuses a file whose host isn't allowlisted",
          modpacks.get_modpack_file("weird-pack-4", mc_version="1.20.1") is None)

    # Ordering must come from date_published, not API/list order.
    modpacks.requests.get = lambda *a, **k: _resp_of([
        {"version_number": "OLD-BUT-FIRST", "game_versions": ["1.20.1"], "date_published": "2020-01-01",
         "files": [{"primary": True, "filename": "old.mrpack",
                    "url": "https://cdn.modrinth.com/data/Y/old.mrpack", "size": 10}]},
        {"version_number": "NEW-BUT-SECOND", "game_versions": ["1.20.1"], "date_published": "2026-06-01",
         "files": [{"primary": True, "filename": "new.mrpack",
                    "url": "https://cdn.modrinth.com/data/Y/new.mrpack", "size": 10}]},
    ])
    ordered = modpacks.get_modpack_file("weird-pack-5", mc_version="1.20.1")
    check("get_modpack_file: sorts by date_published, not list position",
          ordered is not None and ordered["version_number"] == "NEW-BUT-SECOND", ordered)

    print(f"\n{_passed} passed, {_failed} failed")
    return 1 if _failed else 0


if __name__ == "__main__":
    sys.exit(main())
