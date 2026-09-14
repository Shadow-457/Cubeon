"""
Offline regression suite for the mod detail view + the "mod doctor"
(cubeon/mods.py: get_mod_details / get_mod_versions / mod_doctor).

What this protects:
  - the detail dialog's two data calls parse Modrinth correctly (gallery
    ordering, primary file, per-version compatibility) with no network;
  - the doctor really fixes the three classic "my modpack won't load" causes -
    duplicate copies, missing required dependencies, and a jar built for the
    wrong loader/version - and reports each in its result dict;
  - the doctor never raises on a broken profile.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

import cubeon.mods as mods  # noqa: E402
from cubeon.mods import PROFILE_META_FILENAME  # noqa: E402

_passed = _failed = 0


def check(label, cond, detail=""):
    global _passed, _failed
    if cond:
        _passed += 1
        print(f"  ok  {label}")
    else:
        _failed += 1
        print(f"FAIL  {label}  {detail}")


class FakeResp:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        pass

    def json(self):
        return self._payload


class FakeRequests:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def get(self, url, **kw):
        self.calls.append(url)
        for frag, payload in self.routes.items():
            if frag in url:
                return FakeResp(payload)
        raise RuntimeError("no route for " + url)


_NET_GET_JSON_ORIG = mods.net.get_json


def net_routes(routes):
    """Route metadata reads through the fake at the layer mods.py actually
    uses. Since the net refactor, mods.py fetches via net.get_json (retry +
    backoff); `mods.requests` is kept only for its exception types. Faking
    mods.requests alone let these sections silently hit the REAL Modrinth
    API on a cold local_cache (24h TTL) - a 404 for a fake project became a
    DownloadError after 3 real retries and failed the suite."""
    def fake_get_json(url, **kw):
        for frag, payload in routes.items():
            if frag in url:
                return payload
        raise mods.net.DownloadError("no route for " + url)
    mods.net.get_json = fake_get_json
    mods.requests = FakeRequests(routes)  # any legacy direct use


def restore_net():
    mods.net.get_json = _NET_GET_JSON_ORIG


def write_jar(profile_dir, filename, project_id=None, slug=None):
    os.makedirs(profile_dir, exist_ok=True)
    path = os.path.join(profile_dir, filename)
    with open(path, "wb") as f:
        f.write(b"PK\x03\x04 fake jar")
    if project_id or slug:
        mods.record_mod_source(profile_dir, filename, slug=slug,
                               project_id=project_id)


MC = "1.20.1"
LOADER = "fabric"
PROFILE = mods.get_profile_dir(MC, LOADER)


# ---------------------------------------------------------------------------
print("1. get_mod_details() normalizes a Modrinth project")
# ---------------------------------------------------------------------------
DETAIL = {
    "id": "AANobbMI", "slug": "sodium", "title": "Sodium",
    "description": "Modern rendering engine", "body": "# Sodium\nFast.",
    "icon_url": "https://cdn/icon.png",
    "gallery": [
        {"url": "https://cdn/second.png", "featured": False, "title": "b"},
        {"url": "https://cdn/featured.png", "featured": True, "title": "a"},
    ],
    "downloads": 1234, "followers": 10,
    "categories": ["optimization"], "loaders": ["fabric"],
    "game_versions": ["1.20.1"],
    "source_url": "https://github/sodium", "issues_url": "",
    "wiki_url": "", "discord_url": "",
    "license": {"name": "LGPL-3.0"},
    "updated": "2026-09-01", "published": "2020-01-01",
}
net_routes({"/project/sodium": DETAIL})
d = mods.get_mod_details("sodium")
check("title parsed", d and d["title"] == "Sodium", f"{d!r}")
check("license flattened", d and d["license"] == "LGPL-3.0", f"{d!r}")
check("featured gallery image comes first",
      d and d["gallery"][0]["url"].endswith("featured.png"), f"{d!r}")
check("body kept", d and "Fast." in d["body"], f"{d!r}")

# Offline: a project whose name can't be resolved returns None, not a crash.
net_routes({})  # no route -> DownloadError -> cached_call raises
try:
    mods.get_mod_details("does-not-exist-xyz")
    got_none = False
except Exception:
    got_none = True
check("unresolvable project raises for the caller to catch (fresh profile)",
      got_none)

# ---------------------------------------------------------------------------
print("\n2. get_mod_versions() marks compatibility and picks the primary file")
# ---------------------------------------------------------------------------
VERSIONS = [
    {"id": "v2", "version_number": "0.6.0", "name": "0.6.0",
     "version_type": "release", "game_versions": ["1.20.1"],
     "loaders": ["fabric"], "date_published": "2026-01-01",
     "downloads": 50, "changelog": "new",
     "dependencies": [{"project_id": "fabric-api",
                       "dependency_type": "required"}],
     "files": [{"filename": "sodium-0.6.0.jar", "url": "u2",
                "size": 2048, "primary": True, "hashes": {"sha1": "x"}}]},
    {"id": "v1", "version_number": "0.5.0", "name": "0.5.0",
     "version_type": "release", "game_versions": ["1.19.4"],
     "loaders": ["forge"], "date_published": "2025-01-01",
     "downloads": 10, "changelog": "",
     "dependencies": [],
     "files": [{"filename": "sodium-0.5.0.jar", "url": "u1",
                "size": 1024, "primary": True, "hashes": {}}]},
]
net_routes({"/version": VERSIONS})
vs = mods.get_mod_versions("sodium", mc_version="1.20.1", loader="fabric")
check("both versions returned", len(vs) == 2, f"{vs!r}")
check("matching version marked compatible",
      vs[0]["compatible"] is True, f"{vs[0]!r}")
check("non-matching version marked incompatible",
      vs[1]["compatible"] is False, f"{vs[1]!r}")
check("primary filename parsed",
      vs[0]["filename"] == "sodium-0.6.0.jar", f"{vs[0]!r}")

# ---------------------------------------------------------------------------
print("\n2b. get_mod_download() skips a release with no downloadable file")
# ---------------------------------------------------------------------------
# A release whose `files` list is empty must not shadow an older, usable build:
# taking versions[0] blindly returned None and made the doctor wrongly DISABLE
# a mod that does have a downloadable build.
net_routes({"/version": [
    {"version_number": "9.9", "files": []},
    {"version_number": "1.2", "files": [{"filename": "goodmod-1.2.jar",
                                          "url": "dl", "size": 4096,
                                          "primary": True, "hashes": {}}]},
]})
_dl = mods.get_mod_download("fresh-download-project", mc_version=MC, loader=LOADER)
check("an empty-files newest release does not hide the usable build",
      _dl and _dl["filename"] == "goodmod-1.2.jar", f"{_dl!r}")

# ---------------------------------------------------------------------------
print("\n3. doctor: duplicate copies are resolved (newest wins)")
# ---------------------------------------------------------------------------
# Strong duplicate: same Modrinth project id -> older one DELETED.
write_jar(PROFILE, "sodium-fabric-0.5.0.jar", project_id="AANobbMI", slug="sodium")
write_jar(PROFILE, "sodium-fabric-0.6.0.jar", project_id="AANobbMI", slug="sodium")
rep = mods.mod_doctor(MC, LOADER, auto_fix=True, check_online=False)
dups = [p for p in rep["problems"] if p["kind"] == "duplicate"]
check("duplicate reported", len(dups) == 1, f"{rep!r}")
check("duplicate fixed", dups and dups[0]["fixed"], f"{dups!r}")
check("older copy deleted",
      not os.path.exists(os.path.join(PROFILE, "sodium-fabric-0.5.0.jar")))
check("newest copy kept",
      os.path.exists(os.path.join(PROFILE, "sodium-fabric-0.6.0.jar")))

# Stem-only duplicate (no meta) -> older one DISABLED, recoverable.
write_jar(PROFILE, "coolmod-1.0.jar")
write_jar(PROFILE, "coolmod-2.0.jar")
rep = mods.mod_doctor(MC, LOADER, auto_fix=True, check_online=False)
check("stem duplicate fixed",
      any(p["kind"] == "duplicate" and p["fixed"] for p in rep["problems"]),
      f"{rep!r}")
check("older stem copy disabled, not deleted",
      os.path.exists(os.path.join(PROFILE, "coolmod-1.0.jar.disabled")))
check("newest stem copy kept",
      os.path.exists(os.path.join(PROFILE, "coolmod-2.0.jar")))

# ---------------------------------------------------------------------------
print("\n4. doctor: missing required dependencies are installed")
# ---------------------------------------------------------------------------
write_jar(PROFILE, "iris-1.2.jar", project_id="irisPID", slug="iris")
mods.get_mod_download = lambda ref, mc_version=None, loader=None: {
    "filename": "x.jar", "url": "u", "hashes": {}}
mods._required_deps_cached = lambda ref, mc, ld: [
    {"project_id": "fabric-api", "filename": "fabric-api-0.9.jar",
     "url": "dep-url", "hashes": {}}]
mods.installed_project_ids = lambda mc, ld: set()
downloaded = []
mods.download_mod = lambda url, filename, **kw: downloaded.append((url, filename))
rep = mods.mod_doctor(MC, LOADER, auto_fix=True, check_online=True)
deps = [p for p in rep["problems"] if p["kind"] == "missing-dependency"]
check("missing dependency reported", len(deps) == 1, f"{rep!r}")
check("dependency installed", deps and deps[0]["fixed"], f"{deps!r}")
check("download called with the dep file",
      downloaded == [("dep-url", "fabric-api-0.9.jar")], f"{downloaded!r}")

# ---------------------------------------------------------------------------
print("\n5. doctor: a jar with no build for this loader/version is disabled")
# ---------------------------------------------------------------------------
write_jar(PROFILE, "oldmod-3.0.jar", project_id="oldPID", slug="oldmod")
mods.get_mod_download = lambda ref, mc_version=None, loader=None: (
    None if ref == "oldPID" else {"filename": "x.jar", "url": "u", "hashes": {}})
mods._required_deps_cached = lambda ref, mc, ld: []
toggled = []
mods.toggle_mod = lambda mc, ld, fn: toggled.append(fn)
rep = mods.mod_doctor(MC, LOADER, auto_fix=True, check_online=True)
bad = [p for p in rep["problems"] if p["kind"] == "incompatible"]
check("incompatible reported", any(p["mod"].startswith("oldmod") for p in bad),
      f"{rep!r}")
check("incompatible disabled",
      any(p["mod"].startswith("oldmod") and p["fixed"] for p in bad), f"{bad!r}")
check("toggle_mod called", "oldmod-3.0.jar" in toggled, f"{toggled!r}")

# ---------------------------------------------------------------------------
print("\n6. doctor is a clean no-op with no version/loader and never raises")
# ---------------------------------------------------------------------------
empty = mods.mod_doctor(None, None)
check("no version -> empty report", empty["checked"] == 0 and not empty["problems"],
      f"{empty!r}")
rep = mods.mod_doctor(MC, LOADER, auto_fix=True, check_online=True)
check("a second run on a fixed profile finds no duplicates",
      not any(p["kind"] == "duplicate" for p in rep["problems"]), f"{rep!r}")

# ---------------------------------------------------------------------------
print("\n6b. doctor: a Fabric `breaks` version conflict is detected and fixed")
# ---------------------------------------------------------------------------
import zipfile  # noqa: E402


def write_fabric_jar(profile_dir, filename, mod_id, version, *, breaks=None,
                     project_id=None, slug=None):
    """A real, readable jar with a fabric.mod.json - unlike write_jar() above,
    this one can be parsed for `breaks`/`depends`."""
    os.makedirs(profile_dir, exist_ok=True)
    manifest = {"schemaVersion": 1, "id": mod_id, "version": version,
                "name": mod_id}
    if breaks:
        manifest["breaks"] = breaks
    with zipfile.ZipFile(os.path.join(profile_dir, filename), "w") as z:
        z.writestr("fabric.mod.json", json.dumps(manifest))
    if project_id or slug:
        mods.record_mod_source(profile_dir, filename, slug=slug,
                               project_id=project_id)


# Predicate parsing, the heart of conflict detection.
for _v, _expr, _want in [
    ("1.10.7", "<=1.10.7", True), ("1.10.7", "<=1.10.6", False),
    ("0.8.12", "<=1.10.6", True), ("0.8.14", "0.8.x", True),
    ("0.9.0", "0.8.x", False), ("1.0", "[1.0,2.0)", True),
    ("2.0", "[1.0,2.0)", False), ("1.10.7", "<1.8.1", False),
    ("1.0", "*", True), ("1.10.7", "<1.8.1 || >=1.10.0", True),
]:
    check(f"version_satisfies({_v!r}, {_expr!r}) == {_want}",
          mods.version_satisfies(_v, _expr) == _want)

write_fabric_jar(PROFILE, "sodium-test-0.8.14.jar", "sodiumtest", "0.8.14",
                 breaks={"iristest": "<=1.10.7"},
                 project_id="SODIUMTEST", slug="sodiumtest")
write_fabric_jar(PROFILE, "iris-test-1.10.7.jar", "iristest", "1.10.7",
                 project_id="IRISTEST", slug="iristest")

rep = mods.mod_doctor(MC, LOADER, auto_fix=False, check_online=False)
conflict = [p for p in rep["problems"] if p["kind"] == "conflict"]
check("conflict detected from the jars' own fabric.mod.json",
      len(conflict) == 1, f"{rep!r}")
check("conflict names the mod that breaks (its declared name, not filename)",
      conflict and conflict[0]["mod"] == "sodiumtest", f"{conflict!r}")
check("detection alone does not claim a fix",
      conflict and conflict[0]["fixed"] is False, f"{conflict!r}")

# Resolution: update-target finds nothing, so replace the declarer with the
# newest build whose `breaks` no longer matches the installed target.
_GOOD = {"id": "v-sodium-0.8.12", "version_number": "0.8.12",
         "name": "0.8.12", "version_type": "release",
         "game_versions": [MC], "loaders": [LOADER],
         "date_published": "2026-01-01", "downloads": 1, "changelog": "",
         "compatible": True, "dependencies": [],
         "filename": "sodium-test-0.8.12.jar", "url": "new-sodium-url",
         "size_kb": 1.0, "hashes": {}}
# Newer builds for OTHER Minecraft versions must not crowd out the one
# compatible build: the compatibility filter must run before any cap. Seed
# enough of them to overflow any candidate cap.
_INCOMPAT = [dict(_GOOD, id=f"v-new-{i}", version_number=f"0.9.{i}",
                  compatible=False, version_type="release",
                  date_published="2027-01-01",
                  filename=f"sodium-test-0.9.{i}.jar", url="other-url")
             for i in range(30)]
mods.get_mod_versions = lambda ref, mc_version=None, loader=None, **kw: (
    _INCOMPAT + [_GOOD] if ref in ("sodiumtest", "SODIUMTEST") else [])
mods._read_remote_mod_metadata = lambda url: {
    "id": "sodiumtest", "version": "0.8.12", "name": "sodiumtest",
    "depends": {}, "breaks": {"iristest": "<=1.10.6"}}
_replaced = []
mods.download_mod = lambda url, filename, **kw: _replaced.append((url, filename))

rep = mods.mod_doctor(MC, LOADER, auto_fix=True, check_online=False)
conflict = [p for p in rep["problems"] if p["kind"] == "conflict"]
check("conflict still reported on the fix run",
      len(conflict) == 1, f"{rep!r}")
check("conflict marked fixed", conflict and conflict[0]["fixed"], f"{conflict!r}")
check("the replacement build is what gets installed",
      _replaced == [("new-sodium-url", "sodium-test-0.8.12.jar")],
      f"{_replaced!r}")
check("fix carries a user-facing label",
      conflict and "0.8.12" in conflict[0].get("fix", ""), f"{conflict!r}")

# The conflict pass must never raise on an unreadable jar.
with open(os.path.join(PROFILE, "garbage.jar"), "wb") as _f:
    _f.write(b"not a zip")
rep = mods.mod_doctor(MC, LOADER, auto_fix=False, check_online=False)
check("an unreadable jar is ignored, not fatal", isinstance(rep["problems"], list))

# Leave the profile exactly as it was for the UI section below (only the first
# few installed rows render, so extra jars must not push ROWOPEN out of view).
for _j in ("sodium-test-0.8.14.jar", "iris-test-1.10.7.jar", "garbage.jar"):
    for _p in (os.path.join(PROFILE, _j),
               os.path.join(PROFILE, _j + ".cubeon.json")):
        try:
            os.remove(_p)
        except OSError:
            pass

# ---------------------------------------------------------------------------
print("\n7. clicking an installed mod opens its full detail menu")
# ---------------------------------------------------------------------------
# Runtime check of the UI wiring in ui/mods_tab.py: build the tab with one
# installed mod, find that row's click handler, and confirm it mounts a dialog
# and renders the fetched details - with the two network calls stubbed. This is
# the guard against "the menu button silently does nothing".
restore_net()  # the UI section stubs at the core layer; give net back

import importlib  # noqa: E402
import time  # noqa: E402

import flet as ft  # noqa: E402
from cubeon import theme as _theme  # noqa: E402
from cubeon import thread_safe_ui as _tsui  # noqa: E402
import launcher_core as _core  # noqa: E402
importlib.import_module("ui.mods_tab")  # ensure the module is importable
from ui.mods_tab import build_mods_tab  # noqa: E402

write_jar(PROFILE, "rowopen-1.0.jar", project_id="ROWOPEN")

_core.get_mod_details = lambda ref: {
    "project_id": "ROWOPEN", "slug": "rowopen", "title": "Row Open",
    "description": "opens", "body": "hello", "icon_url": None,
    "gallery": [], "downloads": 5, "followers": 0, "categories": [],
    "loaders": ["fabric"], "game_versions": ["1.20.1"], "license": "",
}
_core.get_mod_versions = lambda ref, mc_version=None, loader=None: [{
    "id": "v1", "version_number": "1.0", "name": "1.0", "version_type": "release",
    "game_versions": ["1.20.1"], "loaders": ["fabric"], "date_published": "",
    "downloads": 1, "changelog": "", "compatible": True, "dependencies": [],
    "filename": "rowopen-1.0.jar", "url": "u", "size_kb": 1.0, "hashes": {},
}]


class _FakePage:
    class _Dialogs:
        def __init__(self):
            self.controls = []

    def __init__(self):
        self.overlay = []
        self.controls = []
        self.services = []
        self._dialogs = _FakePage._Dialogs()
        self.update_calls = 0
        self.theme = None
        self.window = None

    def update(self, *a):
        self.update_calls += 1

    def show_dialog(self, c):
        c.open = True
        self._dialogs.controls.append(c)

    def pop_dialog(self):
        while self._dialogs.controls:
            d = self._dialogs.controls.pop()
            if getattr(d, "open", None):
                d.open = False
                return d
        return None

    def add(self, *c):
        self.controls.extend(c)


_uipage = _FakePage()
_uidropdown = ft.Dropdown(value="1.20.1")
_ustate = {"selected_mc_version": MC, "mod_loader": LOADER,
           "mods_recommendations_loaded": False}
_tab, _refresh, _recommend, _browse = build_mods_tab(
    _uipage, {}, _ustate, _uidropdown,
    section_label=_theme.section_label, **_theme.THEME)
check("mods tab builds with the detail wiring", _tab is not None)

_refresh()  # render installed rows (one seeded mod)

def _walk(ctrl):
    yield ctrl
    for child in (getattr(ctrl, "controls", None) or []):
        yield from _walk(child)
    content = getattr(ctrl, "content", None)
    if content is not None:
        yield from _walk(content)

def _opens_rowopen(fn):
    defaults = getattr(fn, "__defaults__", None) or ()
    for v in defaults:
        if isinstance(v, dict) and v.get("project_id") == "ROWOPEN":
            return True
    return False

_row_click = None
for _c in _walk(_tab):
    fn = getattr(_c, "on_click", None)
    if fn is not None and _opens_rowopen(fn):
        _row_click = fn
        break
check("installed mod row has a click handler", _row_click is not None)

# Count detail renders so we can wait for the background fetch to paint.
_rendered = {"n": 0}
_real_refresh = _tsui.refresh
def _spy_refresh(c):
    _rendered["n"] += 1
    _real_refresh(c)
_tsui.refresh = _spy_refresh

if _row_click is not None:
    try:
        _row_click(None)
        _open_ok, _open_err = True, ""
    except Exception as _ex:
        _open_ok, _open_err = False, f"{type(_ex).__name__}: {_ex}"
    check("clicking the row opens a dialog", _open_ok, _open_err)
    check("a mod detail dialog is mounted",
          any(type(d).__name__ == "AlertDialog" for d in _uipage._dialogs.controls),
          f"{[type(d).__name__ for d in _uipage._dialogs.controls]}")

    _deadline = time.time() + 3
    while _rendered["n"] == 0 and time.time() < _deadline:
        time.sleep(0.05)
    check("details rendered from the background fetch", _rendered["n"] > 0,
          f"renders={_rendered['n']}")

    def _texts_of(ctrl):
        out = []
        for c in _walk(ctrl):
            v = getattr(c, "value", None)
            if isinstance(v, str) and v:
                out.append(v)
        return out

    _dialog = _uipage._dialogs.controls[-1]
    _texts = _texts_of(_dialog)
    check("menu shows the installed state at a glance (the rowopen 1.0 build)",
          "You're up to date" in _texts and "1.0 is installed" in _texts,
          f"{_texts[:15]}")
    check("description is collapsed behind 'Read more'",
          "About this mod" in _texts and "Read more" in _texts, f"{_texts[:15]}")
    check("full description is not rendered until expanded",
          not any(type(c).__name__ == "Markdown" for c in _walk(_dialog)),
          f"{[type(c).__name__ for c in _walk(_dialog)]}")

    _toggle = None
    for _c in _walk(_dialog):
        _content = getattr(_c, "content", None)
        if (getattr(_c, "on_click", None) is not None
                and getattr(_content, "value", None) == "Read more"):
            _toggle = _c.on_click
            break
    if _toggle is not None:
        _toggle(None)
    _after = _texts_of(_dialog)
    check("expanding the description reveals the full text",
          any(type(c).__name__ == "Markdown" for c in _walk(_dialog))
          and "Show less" in _after, f"{_after[:15]}")

    # 7b. a mod with hundreds of releases must not render them all at once.
    print("\n7b. a huge version list is grouped behind a 'Show all' control")

    def _mkver(i, compatible):
        return {"id": f"v{i}", "version_number": f"1.{i}", "name": f"1.{i}",
                "version_type": "release", "game_versions": [MC],
                "loaders": [LOADER], "date_published": f"2026-01-{i + 1:02d}",
                "downloads": 0, "changelog": "", "compatible": compatible,
                "dependencies": [], "filename": f"rowopen-1.{i}.jar",
                "url": "u", "size_kb": 1.0, "hashes": {}}

    _core.get_mod_versions = lambda ref, mc_version=None, loader=None: (
        [_mkver(i, True) for i in range(20)]
        + [_mkver(100 + i, False) for i in range(5)])

    _rendered["n"] = 0
    _row_click(None)  # opens a second dialog, now with a big list
    _dialog2 = _uipage._dialogs.controls[-1]
    # Wait for THIS dialog's own content, not the shared refresh counter: a
    # late repaint from the first dialog could otherwise satisfy the counter
    # and have us read the second dialog while it still says "Loading details".
    _dl2 = time.time() + 3
    _t2 = _texts_of(_dialog2)
    while time.time() < _dl2:
        _t2 = _texts_of(_dialog2)
        if "Install latest" in _t2 or "You're up to date" in _t2:
            break
        time.sleep(0.05)
    check("a fresh mod offers the one-click 'Install latest' action",
          "Install latest" in _t2 and "Latest for your setup" in _t2,
          f"{_t2[:15]}")
    check("only a handful of versions render at first",
          _t2.count("match") == 8 and "other version" not in _t2,
          f"match={_t2.count('match')} other={_t2.count('other version')}")
    check("a 'Show all' control exposes the rest",
          any(t.startswith("Show all") and t.endswith("versions") for t in _t2),
          f"{[t for t in _t2 if 'version' in t]}")

    _showmore = None
    for _c in _walk(_dialog2):
        _content = getattr(_c, "content", None)
        if (getattr(_c, "on_click", None) is not None
                and (getattr(_content, "value", "") or "").startswith("Show all")):
            _showmore = _c.on_click
            break
    if _showmore is not None:
        _showmore(None)
    _t2b = _texts_of(_dialog2)
    check("expanding shows every version, incompatible ones marked",
          _t2b.count("match") == 20 and _t2b.count("other version") == 5,
          f"match={_t2b.count('match')} other={_t2b.count('other version')}")
    check("the control flips to 'Show fewer versions'",
          "Show fewer versions" in _t2b,
          f"{[t for t in _t2b if 'version' in t]}")

_tsui.refresh = _real_refresh

# ---------------------------------------------------------------------------
print("\n8. launch runs a fast, network-free repair before the game starts")
# ---------------------------------------------------------------------------
_launch_src = open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "cubeon", "launch.py"), encoding="utf-8").read()
check("launch calls mod_doctor", "mod_doctor(" in _launch_src)
check("launch repair is filesystem-only (check_online=False)",
      "check_online=False" in _launch_src)

# ---------------------------------------------------------------------------
print("\n9. doctor: a conflict with no possible replacement turns one mod off")
# ---------------------------------------------------------------------------
# If neither side has a build that escapes the `breaks` range, the two cannot
# coexist and the declarer refuses to load. The last resort must still get the
# game to launch: turn the clashing mod OFF (reversible), never leave it unfixed.
mods._resolve_mod_conflict = lambda *a, **k: (False, "")
write_fabric_jar(PROFILE, "sodium-x-0.8.14.jar", "sodiumx", "0.8.14",
                 breaks={"irisx": "<=1.10.7"},
                 project_id="SODIUMX", slug="sodiumx")
# A second declarer that breaks the SAME target must not toggle it back on.
write_fabric_jar(PROFILE, "sodium-y-0.8.13.jar", "sodiumy", "0.8.13",
                 breaks={"irisx": "<=1.10.7"},
                 project_id="SODIUMY", slug="sodiumy")
write_fabric_jar(PROFILE, "iris-x-1.10.7.jar", "irisx", "1.10.7",
                 project_id="IRISX", slug="irisx")
_toggled2 = []
mods.toggle_mod = lambda mc, ld, fn: _toggled2.append(fn)
rep = mods.mod_doctor(MC, LOADER, auto_fix=True, check_online=False)
_conflict = [p for p in rep["problems"] if p["kind"] == "conflict"]
check("conflict with no replacement is still reported",
      len(_conflict) == 1, f"{rep!r}")
check("and is resolved by turning the clashing mod off",
      _conflict and _conflict[0]["fixed"], f"{_conflict!r}")
check("the target mod (not the declarer) is disabled exactly once",
      _toggled2 == ["iris-x-1.10.7.jar"], f"{_toggled2!r}")
for _j in ("sodium-x-0.8.14.jar", "sodium-y-0.8.13.jar", "iris-x-1.10.7.jar"):
    for _p in (os.path.join(PROFILE, _j),
               os.path.join(PROFILE, _j + ".cubeon.json")):
        try:
            os.remove(_p)
        except OSError:
            pass

# ---------------------------------------------------------------------------
print("\n10. doctor: a duplicate it couldn't move is not reported as fixed")
# ---------------------------------------------------------------------------
# `fixed` is per loser now, not group-level: if supersede_older_copies does not
# actually clear a copy, the report must not claim success.
write_jar(PROFILE, "dupx-1.0.jar", project_id="DUPX", slug="dupx")
write_jar(PROFILE, "dupx-2.0.jar", project_id="DUPX", slug="dupx")
_real_super = mods.supersede_older_copies
mods.supersede_older_copies = lambda *a, **k: []
rep = mods.mod_doctor(MC, LOADER, auto_fix=True, check_online=False)
_dups = [p for p in rep["problems"] if p["kind"] == "duplicate"]
check("duplicate reported but not falsely marked fixed",
      len(_dups) == 1 and _dups[0]["fixed"] is False, f"{_dups!r}")
mods.supersede_older_copies = _real_super
for _j in ("dupx-1.0.jar", "dupx-2.0.jar"):
    for _p in (os.path.join(PROFILE, _j),
               os.path.join(PROFILE, _j + ".cubeon.json")):
        try:
            os.remove(_p)
        except OSError:
            pass

# ---------------------------------------------------------------------------
print("\n11. selecting a profile repairs mods in the background")
# ---------------------------------------------------------------------------
_main_src = open(os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "main.py"), encoding="utf-8").read()
check("on_version_selected kicks off a proactive repair",
      "_proactive_mod_repair(version_id)" in _main_src)
check("the proactive pass is the full online doctor",
      "check_online=True" in _main_src)
check("proactive repair is once per profile per session",
      '_repair_state = {"done": set()' in _main_src)

print(f"\n{_passed} passed, {_failed} failed")
sys.exit(1 if _failed else 0)
