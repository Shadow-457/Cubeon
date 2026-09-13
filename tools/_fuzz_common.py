#!/usr/bin/env python3
"""
Shared guts for Cubeon's UI fuzzers.

Both the headless chaos monkey (test_fuzz.py) and the windowed "watch fake users
click through it" demo (fuzz_visual.py) build the REAL Cubeon UI and fire its
real handlers. The only thing standing between "a bot clicked Delete" and "the
bot deleted your Minecraft" is the stub layer below: paths.py hard-codes the
real ~/.minecraft / ~/.cubeon_launcher with no env override, so safety is BY
CONSTRUCTION - every destructive / network / subprocess / socket leaf is
replaced before the UI is built. That layer is safety-critical, so it lives HERE
once and both tools import it - the visual demo can never drift into touching
the real install while the headless test stays safe.

Nothing in this module has import-time side effects beyond definitions; call
install_safe_stubs() to actually monkeypatch the process, then `import main`.
"""
import gc
import os
import sys
import types
import asyncio
import inspect
import warnings
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


# ------------------------------------------------------------- hostile input ---
# The strings real users (and attackers) actually produce. Path-traversal,
# reserved Windows device names, empties/whitespace, emoji, RTL/zero-width
# tricks, control chars, oversized, and a few that look like versions so the
# version-y fields get exercised too.
FUZZ = [
    "", " ", "   ", "\t", "\n", "\t \n ",
    "a", "ab", "A" * 300, "x" * 5000,
    "normal name", "my server 😭", "🔥🔥🔥", "café", "他他他",
    "../../etc/passwd", "..\\..\\windows\\system32", "/abs/olute", "C:\\Windows",
    "a/b/c", "foo/../bar", "....//....//", "%2e%2e%2f",
    "con", "PRN", "NUL", "COM1", "LPT1",           # reserved device names
    "name.", ".hidden", "..", ".", "trailing ",
    "'; DROP TABLE users;--", "<script>alert(1)</script>", "${jndi:ldap://x}",
    "null\x00byte", "bell\x07", "\u202eevil", "\u200bzero", "\ufeffbom",
    "1.20.1", "1.21.11", "1.21.11-fabric", "-1", "0", "999999999", "NaN",
    "true", "false", "None", "[]", "{}", "0x00",
]


# on_click / on_result handlers get a fake event that carries the shapes Flet
# hands them (.files for pickers, .data/.control for the rest).
class FakeEvent:
    def __init__(self, control=None, data=""):
        self.control = control
        self.data = data
        self.files = []          # FilePicker result handlers read this
        self.path = None
        self.page = None


# ------------------------------------------------------------------ fake page ---
class FakeWindow:
    def __init__(self):
        self.width = self.height = 0
        self.min_width = self.min_height = 0
        self.title = ""
        self.icon = ""
        self.prevent_close = False

    def center(self):
        pass

    def destroy(self):
        pass


class FakePage:
    """Just enough ft.Page for main() and every dialog to build against."""

    def __init__(self):
        self.window = FakeWindow()
        self.overlay = []
        self.controls = []
        self.fonts = {}
        self.theme = None
        self.theme_mode = None
        self.title = ""
        self.bgcolor = None
        self.padding = 0
        self.update_calls = 0
        self.opened = []          # page.open(dlg) targets - dialogs live here
        self.snackbars = []
        self.session = types.SimpleNamespace()
        self.services = []
        self.dialog = None

    def update(self, *controls):
        self.update_calls += 1

    def add(self, *controls):
        self.controls.extend(controls)

    def open(self, control):
        self.opened.append(control)

    def close(self, control):
        if control in self.opened:
            try:
                self.opened.remove(control)
            except ValueError:
                pass

    def run_thread(self, fn, *a, **kw):
        # Real Flet runs these on a worker; run inline so exceptions surface in
        # the same warnings/except capture as the calling handler.
        return fn(*a, **kw)

    def run_task(self, handler, *a, **kw):
        # Faithfully mirror real Flet: call the coroutine *function* to get the
        # coroutine, then actually run it to completion. If we returned None
        # here (the naive stub) the coroutine would be orphaned and every
        # correct `page.run_task(some_coro)` would look like the "never
        # awaited" bug - a false positive. Running it for real means:
        #   * legitimate scheduled coroutines (run_file_picker's _await_it,
        #     _focus_composer's focus) complete cleanly -> no false alarm, AND
        #   * a GENUINE bare-coroutine bug is still caught, because that kind
        #     of bug never reaches run_task - it's an orphaned coroutine in a
        #     sync handler, surfaced by gc.collect() inside fire().
        try:
            coro = handler(*a, **kw)
        except Exception as ex:
            _classify(ex, ASYNC_DEFECTS, OBSERVATIONS)
            return None
        if inspect.isawaitable(coro):
            loop = asyncio.new_event_loop()
            try:
                # Timeout so a coroutine that (unexpectedly) awaits real IO
                # can't hang the whole run.
                loop.run_until_complete(asyncio.wait_for(coro, timeout=2))
            except Exception as ex:
                _classify(ex, ASYNC_DEFECTS, OBSERVATIONS)
            finally:
                loop.close()
        return None


# ------------------------------------------------------------- tree walking ----
def walk(control, depth=0, seen=None):
    """Yields every control in a Flet tree, defensively."""
    if seen is None:
        seen = set()
    if control is None or id(control) in seen or depth > 80:
        return
    seen.add(id(control))
    yield control
    for attr in ("controls", "content", "actions", "title", "leading",
                 "trailing", "label", "tabs", "items", "action"):
        child = getattr(control, attr, None)
        if child is None:
            continue
        if isinstance(child, (list, tuple)):
            for c in child:
                if hasattr(c, "_c") or hasattr(c, "controls") or hasattr(c, "content"):
                    yield from walk(c, depth + 1, seen)
        elif hasattr(child, "_c") or hasattr(child, "controls") or hasattr(child, "content"):
            yield from walk(child, depth + 1, seen)


def every_control(page):
    """Every control reachable from the page root, its overlay, and any dialog
    that a handler opened (page.open) - so fuzzing reaches dialog buttons like
    Export .mrpack / Delete instance / Create group, not just the base tabs.

    Note `getattr(page, "opened", [])`: our FakePage tracks page.open() targets
    in .opened, but the REAL ft.Page has no such attribute - and on the real
    page main.py appends dialogs to page.overlay before opening them, so they're
    reachable via overlay regardless. The getattr keeps the headless FakePage
    coverage while not exploding on a live window."""
    seen = set()
    out = []
    roots = list(page.controls) + list(page.overlay) + list(getattr(page, "opened", []))
    for r in roots:
        for c in walk(r):
            if id(c) not in seen:
                seen.add(id(c))
                out.append(c)
    return out


def ctrl_text(c):
    """Best-effort visible label of a control (own text/value/tooltip, or its
    content wrapper - a nav button wraps a Row/Text, and in Flet 0.86.5 a
    TextButton/ElevatedButton keeps its label in .content as a plain string)."""
    for attr in ("text", "value", "tooltip", "label"):
        v = getattr(c, attr, None)
        if isinstance(v, str) and v.strip():
            return v
    inner = getattr(c, "content", None)
    if isinstance(inner, str):          # TextButton("Delete") -> content == "Delete"
        return inner
    if inner is not None:
        t = getattr(inner, "value", None) or getattr(inner, "text", None)
        if isinstance(t, str):
            return t
    return ""


def subtree_text(c):
    return " ".join(ctrl_text(x) for x in walk(c)).lower()


def find(pg, pred):
    return [c for c in every_control(pg) if pred(c)]


def clickable_with_subtext(pg, needle):
    n = needle.lower()
    return [c for c in every_control(pg)
            if callable(getattr(c, "on_click", None)) and n in subtree_text(c)]


def set_fields(pg, kind, label, value):
    hits = find(pg, lambda c: type(c).__name__ == kind
                and (getattr(c, "label", "") or "") == label)
    for c in hits:
        c.value = value
    return len(hits)


# -------------------------------------------------------------- fire a handler ---
# Records thread exceptions raised in workers that handlers spin up.
THREAD_ERRORS = []
# Exceptions raised inside coroutines scheduled through page.run_task (file
# picker await, composer refocus). Same defect classes are fatal here too.
ASYNC_DEFECTS = []
# Non-fatal observations - handlers that raised an *expected* error on junk, or
# benign classifications from run_task coroutines. Printed, never failed.
OBSERVATIONS = []

DEFECT_EXC = ("NameError", "UnboundLocalError")


def _thread_hook(args):
    THREAD_ERRORS.append((args.exc_type.__name__, str(args.exc_value)))


def _classify(ex, defects, benign):
    name = type(ex).__name__
    if name in DEFECT_EXC:
        defects.append(f"{name}: {ex}")
    else:
        benign.append(f"{name}: {ex}")


def fire(handler, control):
    """Call one handler with a fuzz event, capturing defect signatures.

    Returns (defects, benign) where defects is a list of hard-fail messages
    (NameError / UnboundLocalError / un-awaited coroutine) and benign is a list
    of expected-on-junk exceptions to merely report.
    """
    defects, benign = [], []
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        try:
            handler(FakeEvent(control))
        except TypeError:
            # Handlers written as `lambda e=None: ...` or `def h():` - retry no-arg.
            try:
                handler()
            except Exception as ex:
                _classify(ex, defects, benign)
        except Exception as ex:
            _classify(ex, defects, benign)
        # Force any orphaned coroutine (a bare `x.focus()`) to finalize now so
        # its "never awaited" warning is emitted inside this capture block.
        gc.collect()
    for w in caught:
        if issubclass(w.category, RuntimeWarning) and "never awaited" in str(w.message):
            defects.append(f"un-awaited coroutine: {w.message}")
    return defects, benign


# ================================================================== STUBS ======
# Records which effectful handlers were actually reached, so a run can PROVE it
# exercised the dangerous flows (delete/export/launch/...) instead of clicking
# inert buttons. Shared module-level so both tools read the same coverage.
INVOKED = {}


def install_safe_stubs(verbose=False):
    """Replace every destructive / network / subprocess / socket leaf with a
    safe no-op BEFORE the UI is built, then import & return the main module.

    Returns a namespace: .app (main module), .core (launcher_core),
    .versions, .modpacks_backend, .invoked (coverage dict), .tmpdir.

    This is the whole safety story. It must NOT rely on the sandbox - it runs
    the same in a real windowed session on the user's machine, where nothing is
    read-only.
    """
    if verbose:
        print("0. installing stubs (no writes, no network, no subprocess, no socket)")

    import subprocess
    import webbrowser
    import tempfile
    import flet as ft

    import cubeon.versions as versions
    import cubeon.csl as csl
    versions.get_available_versions = lambda *a, **k: [
        {"id": "1.21.11", "type": "release"}, {"id": "1.20.1", "type": "release"}]
    versions.get_latest_release = lambda: "1.21.11"
    csl.ensure_ready = lambda *a, **k: None

    # No real socket to the (undeployed) friends worker, and don't auto-connect.
    import cubeon.friends as friends_mod
    friends_mod.FriendsClient.connect = lambda self, *a, **k: None
    friends_mod.FriendsClient.disconnect = lambda self, *a, **k: None
    friends_mod.FriendsClient._raw_send = lambda self, *a, **k: False
    friends_mod.FriendsClient._run_loop = lambda self, *a, **k: None
    friends_mod.load_identity = lambda *a, **k: None

    # Backup scheduler thread must not decide it's due and run a real backup.
    import cubeon.backup as backup_mod
    backup_mod.is_due = lambda *a, **k: False

    # Startup update check hits the GitHub releases API - no real request here.
    import cubeon.updater as updater_mod
    updater_mod.check_for_updates = lambda *a, **k: None
    updater_mod.check_in_background = lambda *a, **k: None

    # No launching real processes / opening the browser.
    subprocess.Popen = lambda *a, **k: types.SimpleNamespace(
        pid=0, poll=lambda: 0, wait=lambda *x, **y: 0, terminate=lambda: None, kill=lambda: None)
    webbrowser.open = lambda *a, **k: True

    # Flet control methods that do real IPC are coroutines (pick_files, focus).
    # UI code correctly schedules them via page.run_task; replace with clean
    # async no-ops so no real OS file dialog pops up mid-demo and no IPC is
    # needed. (A GENUINE bare-coroutine bug - one NOT routed through run_task -
    # is still caught, because it orphans a coroutine that gc.collect() flags.)
    async def _async_noop(*a, **k):
        return []

    ft.FilePicker.pick_files = _async_noop
    if hasattr(ft.FilePicker, "save_file"):
        ft.FilePicker.save_file = _async_noop
    if hasattr(ft.FilePicker, "get_directory_path"):
        ft.FilePicker.get_directory_path = _async_noop
    ft.TextField.focus = _async_noop

    import launcher_core as core
    core.get_available_versions = versions.get_available_versions
    core.get_latest_release = versions.get_latest_release

    # Redirect the one profile-dir choke point (which does makedirs + writes a
    # meta file) into a throwaway temp dir, and stub the disk-reading list calls,
    # so nothing fired can create or read anything under the real
    # ~/.cubeon_launcher / ~/.minecraft.
    _tmp = tempfile.mkdtemp(prefix="cubeon_fuzz_")

    def _fake_profile_dir(mc, loader, *a, **k):
        p = os.path.join(_tmp, f"{mc}-{loader}")
        os.makedirs(p, exist_ok=True)   # so callers that listdir it don't error
        return p

    core.get_profile_dir = _fake_profile_dir
    import cubeon.mods as mods_mod
    mods_mod.get_profile_dir = _fake_profile_dir

    # Realistic fixtures (right keys) so the installed-row builders actually
    # build delete/toggle rows to fuzz - more coverage than empty lists.
    core.list_mods = lambda *a, **k: [
        {"filename": "sodium.jar", "display_name": "sodium", "enabled": True,
         "size_kb": 100.0, "slug": "sodium"},
        {"filename": "x.jar.disabled", "display_name": "x", "enabled": False,
         "size_kb": 5.0, "slug": None}]
    core.list_content = lambda *a, **k: [
        {"filename": "faithful.zip", "display_name": "faithful", "size_kb": 2048.0}]
    core.list_installed_modpacks = lambda *a, **k: [
        {"name": "Fabulously", "display_name": "Fabulously", "mc_version": "1.20.1",
         "loader": "fabric", "mod_count": 42}]
    core.list_custom_skins = lambda *a, **k: [
        {"filename": "steve.png", "name": "steve", "slim": False}]
    core.list_plugins = lambda *a, **k: [
        {"filename": "EssentialsX.jar", "display_name": "EssentialsX",
         "enabled": True, "slug": "essentialsx"}]
    core.list_profiles = lambda *a, **k: [
        {"mc_version": "1.20.1", "loader": "fabric", "mod_count": 2,
         "key": "1.20.1-fabric", "mods": ["sodium.jar", "lithium.jar"]}]

    # --- destructive / side-effecting leaves: no-op (benign return) ---------
    invoked = INVOKED

    def _noop_recording(name):
        def _fn(*a, **k):
            invoked[name] = invoked.get(name, 0) + 1
            return None
        return _fn

    _SIDE_EFFECT_NOOP = [
        "delete_content", "delete_custom_skin", "delete_mod", "delete_plugin",
        "delete_version", "delete_server", "download_content", "download_mod", "download_plugin",
        "install_local_content", "install_local_mod", "install_mod_loader",
        "install_modpack_from_file", "install_modpack_from_url", "install_server",
        "install_version", "launch_game", "save_config", "save_server_properties",
        "set_active_skin", "set_eula_accepted", "set_high_ping_optimization",
        "set_profile_picture", "start_server", "stop_orphaned_server", "stop_server",
        "switch_server_type", "sync_local_skin_to_csl", "sync_mods_to_game",
        "toggle_mod", "toggle_plugin", "add_mod_file", "copy_mods_between_profiles",
        "open_mods_folder", "open_content_folder", "open_server_folder",
        "clear_profile_picture", "remove_pending_entries", "write_extralist_entries",
        "install_fabric", "install_skin_mod", "csl_ensure_ready", "export_mrpack",
    ]
    for _name in _SIDE_EFFECT_NOOP:
        if hasattr(core, _name):
            setattr(core, _name, _noop_recording(_name))

    # add_custom_skin returns a dict the UI reads - keep the shape.
    core.add_custom_skin = lambda *a, **k: {"filename": "fuzz.png", "display_name": "fuzz"}
    core.install_local_mod = lambda *a, **k: "fuzz.jar"
    core.install_local_content = lambda *a, **k: "fuzz.zip"
    # Shape-correct so the browse-row mod branch runs safely: it reads
    # result["installed"] / result["failed"], then run_mod_repair() reads the
    # mod_doctor report. Both are real download/repair leaves otherwise.
    core.install_mod_with_dependencies = lambda *a, **k: {
        "installed": ["fuzz.jar"], "failed": []}
    core.mod_doctor = lambda *a, **k: {"problems": [], "fixed": []}

    # --- network readers: shape-correct empties (no Modrinth calls) ---------
    for _name in ("get_recommended_plugins", "search_plugins",
                  "search_modpacks", "get_popular_modpacks"):
        if hasattr(core, _name):
            setattr(core, _name, (lambda *a, **k: []))

    # Browse readers get ONE realistic hit each, not [] - otherwise no result
    # row is ever built, so build_browse_row()'s on_download worker (the
    # resourcepack/shader install path where deps_note was read unbound) is
    # unreachable and the fuzzer runs green while that bug lives on. A real
    # hit makes the Download button exist and be clicked.
    _BROWSE_HIT = {
        "project_id": "fuzz0000", "slug": "fuzz-pack", "title": "Fuzz Pack",
        "description": "a fake browse hit", "icon_url": None,
        "downloads": 42, "author": "fuzzer",
    }
    for _name in ("get_recommended_mods", "search_mods", "get_recommended_content",
                  "search_content"):
        if hasattr(core, _name):
            setattr(core, _name, (lambda *a, **k: [dict(_BROWSE_HIT)]))

    for _name in ("get_mod_download", "get_content_download", "get_plugin_download"):
        if hasattr(core, _name):
            setattr(core, _name, (lambda *a, **k: {
                "filename": "fuzz.jar", "url": "https://cdn.modrinth.com/data/x/fuzz.jar",
                "size_kb": 1, "version_number": "1.0.0"}))
    core.get_modpack_file = lambda *a, **k: {
        "filename": "fuzz.mrpack", "url": "https://cdn.modrinth.com/x.mrpack",
        "size_kb": 1, "version_number": "1.0.0"}
    # The mod detail dialog fetches project metadata + the version list. A
    # browse row is clickable, so this path runs the moment a hit renders -
    # unstubbed it would fetch the real Modrinth API and prefill real state.
    core.get_mod_details = lambda *a, **k: {
        "project_id": "fuzz0000", "slug": "fuzz-pack", "title": "Fuzz Pack",
        "description": "a fake browse hit", "body": "fake body",
        "icon_url": None, "gallery": [], "downloads": 42, "followers": 3,
        "categories": ["adventure"], "loaders": ["fabric"],
        "game_versions": ["1.20.1"], "license": "MIT",
        "source_url": "", "issues_url": "", "wiki_url": "", "discord_url": "",
        "client_side": "required", "server_side": "optional",
    }
    core.get_mod_versions = lambda *a, **k: [{
        "id": "fuzzver0", "version_number": "1.0.0", "name": "fuzz 1.0.0",
        "version_type": "release", "game_versions": ["1.20.1"],
        "loaders": ["fabric"], "date_published": "2024-01-01T00:00:00Z",
        "downloads": 7, "changelog": "", "compatible": True,
        "dependencies": [], "filename": "fuzz.jar",
        "url": "https://cdn.modrinth.com/data/x/fuzz.jar",
        "size_kb": 1, "hashes": {},
    }]
    core.get_skin_face_url = lambda *a, **k: ""
    # Installed-mod rows resolve icons via one bulk Modrinth call, and
    # icons.prefetch() writes the real ~/.cubeon_launcher/cache/icons. Neither
    # may happen in a headless run - stub both (None icon = the placeholder).
    core.get_mod_icons = lambda slugs=None, *a, **k: {s: None for s in (slugs or [])}
    import cubeon.icons as icons_mod
    icons_mod.prefetch = lambda url=None, *a, **k: None
    core.summarize_modpack = lambda *a, **k: {"name": "fuzz", "mods": [], "mc_version": "1.20.1"}

    # Seed one installed version so state["installed"] is non-empty - the delete
    # and launch flows are gated on a selected *installed* version.
    core.get_installed_versions = lambda *a, **k: [
        {"id": "1.20.1", "type": "release", "name": "1.20.1"}]
    core.find_installed_loader_version = lambda *a, **k: None
    core.find_java = lambda *a, **k: "/usr/bin/java"
    core.build_launch_command = lambda *a, **k: ["java", "-jar", "x"]

    # modpacks_tab calls the BACKEND module directly (from cubeon import modpacks
    # as modpacks_backend), not core.export_mrpack - so the real disk-writing
    # export would run on a thread if we only stubbed core. Record it too.
    import cubeon.modpacks as modpacks_backend
    modpacks_backend.export_mrpack = _noop_recording("export_mrpack")
    modpacks_backend.install_modpack_from_file = _noop_recording("install_modpack_from_file")
    modpacks_backend.install_modpack_from_url = _noop_recording("install_modpack_from_url")

    # Catch defect-class exceptions raised in worker threads handlers spin up.
    threading.excepthook = _thread_hook

    import main as app       # imported last, so every stub is already in place
    return types.SimpleNamespace(
        app=app, core=core, versions=versions,
        modpacks_backend=modpacks_backend, invoked=invoked, tmpdir=_tmp)
