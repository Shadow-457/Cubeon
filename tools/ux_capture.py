#!/usr/bin/env python3
"""
UX screenshot tour for Cubeon - captures, does NOT judge.

Drives the REAL Cubeon window through every meaningful state and writes one
clean PNG per state into a folder, plus a manifest.json and a README.md index.
It deliberately does NOT add the chaos-monkey HUD, so the shots are exactly what
a user would see. Review them later - by eye, or hand them to a vision model
against a UX rubric. Capture and judgment are decoupled on purpose: the folder
is the artifact.

Coverage is deliberately wide (~34 states): every tab, both settings surfaces,
each content type in BOTH views (browse grid / installed list), the filters
panel, the skins and capes panes, the chat composer with a draft in it, the
"Fix problems" result line, and every dialog we can open (project details for a
mod and a resource pack, pack details with the version picker, plugin details,
create modpack, delete confirm, the sliding Account panel).

Capture uses Flet's native page.take_screenshot() (PNG bytes, whole page incl.
overlays - so open dialogs are in the shot), so there's no OS-screenshot /
window-focus fragility and it's cross-platform.

Same safety layer as the fuzzers (tools/_fuzz_common.install_safe_stubs): every
destructive / network / subprocess / socket leaf is stubbed BEFORE the UI is
built, so touring the UI can't touch the real ~/.minecraft or hit the network.
This tool then layers TOUR-ONLY enrichment on top (seed_rich): fake browse hits
and detail payloads so grids/lists/dialogs have rows to look at instead of
rendering empty. The shared stubs are never modified - only this process's
copies of the functions.

Navigation is by tab KEY (read from each nav button's `k=key` default arg), so
the two "Settings" tabs never get confused. In-page segment tabs are matched the
same way but with a subtree-size guard, so sidebar rows can never be mistaken
for a content tab.

  Populated states:    python3 tools/ux_capture.py
  Empty / new-user:    python3 tools/ux_capture.py --empty
  Custom folder:       python3 tools/ux_capture.py --out /tmp/cubeon_ux
  Just some states:    python3 tools/ux_capture.py --only mods,chat
  Inventory (no run):  python3 tools/ux_capture.py --list
  Headless self-check: python3 tools/ux_capture.py --dry   (proves every state
                       is reachable; can't screenshot without a window)

Software GL: on AMD Polaris + Mesa 26.1 (and similar), the Flutter client can
SIGSEGV on its first frame inside libgallium. The launcher detects that and
relaunches on llvmpipe; this tool can't (it drives one window), so pass
--software-gl to render via llvmpipe from the start. With no flag it tries
hardware GL and AUTO-RETRIES the whole tour on software GL if the run captured
nothing - so `python3 tools/ux_capture.py` is safe on a crashing driver.
"""
import os
import sys
import json
import asyncio
import argparse
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _fuzz_common as fz
from _fuzz_common import (
    FakePage, FakeEvent, every_control, ctrl_text, subtree_text,
    set_fields, find, clickable_with_subtext, walk,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The tabs we tour, in a natural top-to-bottom order. Keys match nav_items /
# server_group_items in main.py; we navigate by key (never by the ambiguous
# "Settings" label).
TAB_ORDER = ["play", "mods", "modpacks", "chat", "profile",
             "server_console", "server_plugins", "server_settings",
             "stats", "settings"]
KNOWN_KEYS = set(TAB_ORDER)

# Segment keys inside the Mods tab (content type) - see ui/mods_tab.py
# CONTENT_TABS. Every one behaves identically apart from its own strings.
CONTENT_KEYS = ["mod", "resourcepack", "shader"]
# --------------------------------------------------------------- reach states ---
def discover_nav(page):
    """Map tab key -> its sidebar nav control. build_nav_button uses
    `on_click=lambda e, k=key: switch_tab(k)`, so the key is the handler's
    single default arg - exact, and immune to the duplicate "Settings" label."""
    out = {}
    for c in every_control(page):
        h = getattr(c, "on_click", None)
        d = getattr(h, "__defaults__", None)
        if callable(h) and isinstance(d, tuple) and len(d) == 1 \
                and isinstance(d[0], str) and d[0] in KNOWN_KEYS:
            out.setdefault(d[0], c)
    # The top bar's Settings gear is `lambda e: switch_tab("settings")` - no
    # key default to discover above, so it was MISSING from every past tour.
    # Match it by control type + tooltip; nav rows (server_settings etc.) are
    # Containers, the gear is an IconButton, so the two "Settings" tooltips
    # can't be confused - and only fall back when the key wasn't found at all.
    if "settings" not in out:
        for c in every_control(page):
            if (type(c).__name__ == "IconButton"
                    and (getattr(c, "tooltip", "") or "") == "Settings"
                    and callable(getattr(c, "on_click", None))):
                out["settings"] = c
                break
    return out


def _click(ctrl):
    """Fire a control's on_click, tolerating both (e)-style and no-arg handlers."""
    h = getattr(ctrl, "on_click", None)
    if not callable(h):
        return False
    try:
        h(FakeEvent(ctrl))
    except TypeError:
        try:
            h()
        except Exception:
            return False
    except Exception:
        return False
    return True


def _expand_servers(page):
    """Fire the 'Servers' group header so its sub-items show in the sidebar for
    the server_* shots (the header has no key default - match it by label)."""
    for c in every_control(page):
        if callable(getattr(c, "on_click", None)) \
                and subtree_text(c).strip().startswith("servers"):
            _click(c)
            return


def dismiss_transient(page, baseline_ids):
    """Close any dialog opened since build (anything in overlay that wasn't
    there at baseline), so it doesn't bleed into the next state's shot."""
    for c in list(getattr(page, "overlay", [])):
        if id(c) in baseline_ids:
            continue
        try:
            if hasattr(c, "open"):
                c.open = False
        except Exception:
            pass
        try:
            page.close(c)
        except Exception:
            pass


def reach_tab(page, nav, key):
    return key in nav and _click(nav[key])


def _subtab(page, key, max_nodes=3):
    """Click an in-page segment tab (content type, browse/installed, skin/cape).

    Identified by handler default arg == key, exactly like nav keys - but a
    sidebar row can share a default with a segment (the Mods nav row is 'mods';
    the content segments are 'mod'/'resourcepack'/'shader'), so we also require
    a tiny subtree. A nav row carries icon + label + the whole hover/active
    chrome (4 nodes); segment tabs are a label inside a padded container (3).
    Verified against the live tree.
    """
    for c in every_control(page):
        h = getattr(c, "on_click", None)
        d = getattr(h, "__defaults__", None)
        if callable(h) and isinstance(d, tuple) and d and d[0] == key \
                and len(list(walk(c))) <= max_nodes:
            if _click(c):
                return True
    return False


def _set_field(page, value, *, hint_contains=None, label=None):
    """Set the first TextField matching a hint substring or label - used to type
    into the mod search box / chat composer so the shot shows real content."""
    for c in every_control(page):
        if type(c).__name__ != "TextField":
            continue
        hint = (getattr(c, "hint_text", "") or "").lower()
        lbl = (getattr(c, "label", "") or "")
        if hint_contains and hint_contains.lower() not in hint:
            continue
        if label and lbl != label:
            continue
        c.value = value
        return True
    return False


def _click_first(page, needle):
    for c in clickable_with_subtext(page, needle):
        if _click(c):
            return True
    return False


def _overlay_signal(page):
    """One number that grows when a dialog/panel opens, on BOTH the real page
    (dialogs are appended to page.overlay) and the dry-run FakePage (which
    records page.opened)."""
    return (len(getattr(page, "opened", []) or [])
            + len(getattr(page, "overlay", []) or []))


def _click_until_dialog(page, candidates, limit=8):
    """Click candidates in order until an overlay opens. Candidates are the row
    controls that carry their target as a handler default arg (mod rows:
    `lambda e, mm=m: open_mod_detail(mm)`; pack rows: `_open_pack_detail`), so
    the FIRST candidate is almost always the right one - the loop is just
    insurance against a row whose dialog was stubbed into a no-op."""
    before = _overlay_signal(page)
    for ctrl in candidates[:limit]:
        if _click(ctrl) and _overlay_signal(page) > before:
            return True
    return False

def _browse_rows(page, handler_name=None):
    """Row controls on the current browse pane: those whose on_click carries a
    project dict as a default arg, or that use a known handler name."""
    rows = []
    for c in every_control(page):
        h = getattr(c, "on_click", None)
        if not callable(h):
            continue
        d = getattr(h, "__defaults__", None)
        if d and isinstance(d[0], dict):
            rows.append(c)
        elif handler_name and getattr(h, "__name__", "") == handler_name:
            rows.append(c)
    return rows

# ------------------------------------------------------------ tour-only seed ---
# The shared stubs return shape-correct but THIN fixtures (one browse hit, one
# version, no artwork), which is right for fuzzing and useless for a screenshot:
# grids show a single tile and dialogs show an empty version list. seed_rich()
# layers richer fixtures on top, in THIS process only.
#
# It patches reads ONLY - every write/network/subprocess leaf stays stubbed by
# _fuzz_common. The shared stubs are never modified, so --dry and the other
# suites are unaffected. Skipped entirely for --empty, which tours a new user.
#
# Note on modules: launcher_core re-exports the backend functions
# (`from cubeon.mods import get_mod_details`), so patching core.X does NOT patch
# cubeon.mods.X - they are separate bindings. ui/detail_dialog.py imports
# `from cubeon import mods as _mods` and calls _mods.get_mod_details directly,
# so a core-only stub would leave the dialog fetching the REAL Modrinth API.
# _stub_all() therefore writes every candidate binding.

_SEED_KINDS = {
    # title, blurb, downloads
    "mod": [
        ("Sodium", "Modern rendering engine with a focus on performance", 41230000),
        ("Lithium", "No-compromises game logic and server optimizations", 18750000),
        ("Iris Shaders", "A modern shader pack loader for Minecraft", 9430000),
        ("JEI", "View items and recipes in-game", 7620000),
        ("Mod Menu", "Adds a mod list screen with config support", 5310000),
        ("Xaero's Minimap", "A clean, fast minimap with waypoints", 4880000),
    ],
    "resourcepack": [
        ("Faithful 64x", "The classic Faithful look, doubled in resolution", 3120000),
        ("Stay True", "A vanilla-faithful pack with subtle hand-picked tweaks", 2410000),
        ("Better Leaves", "Bushier, fuller foliage without the performance cost", 1980000),
        ("Fresh Animations", "Smooth, expressive mob animations", 1730000),
        ("Motschen's Better Leaves", "Fuller leaves that still respect vanilla", 920000),
    ],
    "shader": [
        ("Complementary Reimagined", "A polished, balanced shader for everyday play", 8940000),
        ("BSL Shaders", "Beautiful lighting with a light performance footprint", 6420000),
        ("Photon Shader", "Cinematic lighting with a huge feature set", 3310000),
        ("Sildur's Vibrant", "Vibrant colours, tiered by performance budget", 2280000),
        ("Rethinking Voxels", "Voxel-based lighting and shadows", 1410000),
    ],
    "modpack": [
        ("Fabulously Optimized", "Performance-focused, 4 mods of setup and it just runs", 12500000),
        ("Adrenaline", "Everything you need for a fast, modern experience", 3100000),
        ("Simply Optimized", "Drop-in optimisation pack with no gameplay changes", 2740000),
        ("Fabulous Vanilla", "Vanilla gameplay, modern performance", 1800000),
    ],
    "plugin": [
        ("EssentialsX", "The essential plugin suite for any server", 21000000),
        ("LuckPerms", "A permissions plugin built for scale", 8700000),
        ("WorldEdit", "In-game map editor for fast builds", 6900000),
        ("ViaVersion", "Allow newer clients onto older servers", 5400000),
    ],
}

# Flat-colour placeholder art. Generated rather than committed (keeps the tool
# self-contained and the repo free of binary fixtures) and returned as a data
# URI, which is what Flet's Image can render without any file on disk.
_ART_PALETTE = [
    (34, 92, 66), (58, 88, 40), (92, 62, 34), (44, 62, 104),
    (96, 40, 62), (64, 52, 96), (30, 84, 92), (86, 84, 36),
]
_ART_CACHE = {}


def _png_data_uri(rgb, size=64):
    import base64
    import struct
    import zlib

    r, g, b = rgb
    row = b"\x00" + bytes([r, g, b]) * size
    raw = row * size

    def _chunk(tag, data):
        body = tag + data
        return (struct.pack(">I", len(data)) + body
                + struct.pack(">I", zlib.crc32(body) & 0xFFFFFFFF))

    ihdr = struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0)
    png = (b"\x89PNG\r\n\x1a\n" + _chunk(b"IHDR", ihdr)
           + _chunk(b"IDAT", zlib.compress(raw)) + _chunk(b"IEND", b""))
    return "data:image/png;base64," + base64.b64encode(png).decode("ascii")


def _art(seed):
    key = seed % len(_ART_PALETTE)
    if key not in _ART_CACHE:
        _ART_CACHE[key] = _png_data_uri(_ART_PALETTE[key])
    return _ART_CACHE[key]


_SEED_INDEX = {}   # project_id -> the seeded hit (so details can match the row)


def _hit(kind, i, title, blurb, downloads):
    """One shape-correct browse hit. Keys match cubeon/content.py + mods.py
    search results (project_id, slug, title, description, icon_url, downloads,
    author, plus `versions` which the modpack rows filter on)."""
    pid = f"uxseed{kind[:3]}{i}"
    icon = f"uxseed://{kind}/{i}"
    hit = {
        "project_id": pid, "slug": title.lower().replace(" ", "-").replace("'", ""),
        "title": title, "description": blurb, "icon_url": icon,
        "downloads": downloads, "author": "ux-capture",
        "categories": ["optimization"], "versions": ["1.21.1", "1.20.1"],
        "loaders": ["fabric"],
    }
    _SEED_INDEX[pid] = hit
    return dict(hit)


def _hits(kind, limit=None):
    rows = _SEED_KINDS.get(kind, _SEED_KINDS["mod"])
    if limit:
        rows = rows[:limit]
    return [_hit(kind, i, *row) for i, row in enumerate(rows)]


def _stub_all(name, fn):
    """Patch EVERY binding of a backend function: launcher_core re-exports by
    assignment, so core.X and module.X are different callables."""
    import launcher_core as core
    hit = False
    for mod in (core, _mods_mod(), _content_mod()):
        if mod is not None and hasattr(mod, name):
            setattr(mod, name, fn)
            hit = True
    return hit


def _mods_mod():
    import cubeon.mods as m
    return m


def _content_mod():
    import cubeon.content as m
    return m


def _detail(ref, kind="mod"):
    """Rich project payload for the detail dialogs: markdown body with headings
    and bullets (exercises the markdown renderer), pills, and a hero icon."""
    base = dict(_SEED_INDEX.get(ref) or _hit(kind, 0, *_SEED_KINDS[kind][0]))
    base.update({
        "followers": 12000,
        "license": "LGPL-3.0",
        "source_url": "https://github.com/example/dev",
        "issues_url": "https://github.com/example/dev/issues",
        "wiki_url": "", "discord_url": "https://discord.gg/example",
        "client_side": "required", "server_side": "optional",
        "gallery": [{"url": f"uxseed://{kind}/g{i}", "title": f"screenshot {i}"}
                    for i in range(3)],
        "loaders": ["fabric", "quilt", "neoforge"],
        "game_versions": ["1.21.1", "1.21", "1.20.6", "1.20.1"],
        "body": (
            "## About\n\n"
            "A fast, configurable mod that does exactly what it says. "
            "No dependencies, no telemetry, and a config screen you can "
            "actually read.\n\n"
            "### Features\n\n"
            "- Rewrites the hot path for a measurable FPS gain\n"
            "- Works on Fabric, Quilt and NeoForge from one jar\n"
            "- Per-world config via `config/example.json`\n\n"
            "### Compatibility\n\n"
            "Tested against the most popular optimisation stacks. "
            "If you find a conflict, open an [issue](https://example.com).\n"
        ),
    })
    return base


def _versions(ref, mc_version=None, loader=None, *a, **k):
    """Version list for the pickers: newest first, a mix of release/beta, the
    first two marked compatible with the selected version so the badge states
    ('compatible' vs 'works but untested') both show."""
    out = []
    for i in range(6):
        vn = f"{2 - i // 3}.{4 - i % 4}.{i}"
        out.append({
            "id": f"uxver{i}", "version_number": vn,
            "name": f"{vn} - {'release' if i < 4 else 'beta'}",
            "version_type": "release" if i < 4 else "beta",
            "game_versions": ["1.21.1", "1.20.1"],
            "loaders": [loader or "fabric"],
            "date_published": f"2025-0{(i % 9) + 1}-1{i % 9}T12:00:00Z",
            "downloads": 9000 - i * 700, "changelog": "",
            "compatible": i < 2, "dependencies": [],
            "filename": f"example-{vn}.jar",
            "url": "https://cdn.modrinth.com/data/uxseed/example.jar",
            "size_kb": 512 - i * 40, "hashes": {},
        })
    if mc_version:   # keep the shape the UI expects when it scopes by version
        out[0]["game_versions"] = [mc_version]
    return out


def seed_rich():
    """Swap the thin shared fixtures for rich ones. Returns the list of things
    seeded, for the run log. Read-only: no write/network leaf is un-stubbed."""
    seeded = []

    # Browse readers, per content type. cubeon/content.py dispatches on the
    # content_type argument, so read it back out and answer per kind.
    def _content_hits(content_type, *a, **k):
        return _hits(content_type if content_type in _SEED_KINDS else "resourcepack")

    def _mod_hits(*a, **k):
        return _hits("mod")

    for name in ("search_content", "get_recommended_content"):
        if _stub_all(name, _content_hits):
            seeded.append(name)
    for name in ("search_mods", "get_recommended_mods"):
        if _stub_all(name, _mod_hits):
            seeded.append(name)

    # Modpacks + plugins (their own readers).
    for name in ("search_modpacks", "get_popular_modpacks"):
        if _stub_all(name, lambda *a, **k: _hits("modpack")):
            seeded.append(name)
    for name in ("search_plugins", "get_recommended_plugins"):
        if _stub_all(name, lambda *a, **k: _hits("plugin")):
            seeded.append(name)

    # Detail payloads + version lists - BOTH bindings (see the module note at
    # the top of this section): the dialog path reads cubeon.mods directly.
    for name in ("get_mod_details", "get_content_details"):
        if _stub_all(name, lambda ref, *a, **k: _detail(ref)):
            seeded.append(name)
    if _stub_all("get_mod_versions", _versions):
        seeded.append("get_mod_versions")

    # A downloadable file for the pickers/install buttons (still never fetched -
    # core.download_mod / download_content stay stubbed).
    if _stub_all("get_mod_download", lambda *a, **k: {
            "filename": "example-2.4.0.jar",
            "url": "https://cdn.modrinth.com/data/uxseed/example.jar",
            "size_kb": 512, "version_number": "2.4.0", "hashes": {}}):
        seeded.append("get_mod_download")
    if _stub_all("get_content_download", lambda *a, **k: {
            "filename": "example-pack.zip",
            "url": "https://cdn.modrinth.com/data/uxseed/pack.zip",
            "size_kb": 8192, "version_number": "3.1.0", "hashes": {}}):
        seeded.append("get_content_download")
    if _stub_all("get_modpack_file", lambda *a, **k: {
            "filename": "example.mrpack",
            "url": "https://cdn.modrinth.com/data/uxseed/example.mrpack",
            "size_kb": 4096, "version_number": "1.9.0", "hashes": {}}):
        seeded.append("get_modpack_file")

    # Real PNG bytes for every seeded icon, so tiles and dialog heroes render
    # art instead of a broken image.
    try:
        import cubeon.icons as icons_mod
        _orig_src = icons_mod.src

        def _src(url=None, *a, **k):
            if isinstance(url, str) and url.startswith("uxseed://"):
                return _art(abs(hash(url)) % len(_ART_PALETTE))
            return _orig_src(url) if callable(_orig_src) else url

        icons_mod.src = _src
        seeded.append("icons.src")
    except Exception:
        pass

    return seeded
# ------------------------------------------------------------- state reach fns ---
# Each reach_* navigates the UI into one state and returns True if it got there.
# They are intentionally tolerant: a state that can't be reached is reported as
# MISS by the tour (and by --dry) instead of crashing the run.
def reach_delete_dialog(page, nav):
    """Play tab -> pick an installed version -> Delete instance -> confirm."""
    reach_tab(page, nav, "play")
    set_fields(page, "Dropdown", "Version", "1.20.1")
    opened = False
    for btn in find(page, lambda c: (getattr(c, "tooltip", "") or "") == "Delete instance"):
        opened = _click(btn) or opened
    return opened


def reach_create_modpack_dialog(page, nav):
    """Modpacks tab -> Create modpack -> the create dialog."""
    reach_tab(page, nav, "modpacks")
    return _click_first(page, "create modpack")


def reach_account_panel(page, nav):
    """Play tab -> the top bar's person icon -> the sliding Account panel."""
    reach_tab(page, nav, "play")
    opened = False
    for btn in find(page, lambda c: (getattr(c, "tooltip", "") or "") == "Account"):
        opened = _click(btn) or opened
    return opened


def close_account_panel(page):
    """Close the Account panel via its X. It is NOT an overlay dialog, so
    dismiss_transient can't retire it - the panel lives in the overlay from
    build time. Its Close button calls the same path as the scrim."""
    for btn in find(page, lambda c: (getattr(c, "tooltip", "") or "") == "Close"):
        if _click(btn):
            return True
    return False


def reach_mod_detail_dialog(page, nav):
    """Mods tab (mod content) -> click a browse tile -> project detail dialog."""
    reach_tab(page, nav, "mods")
    _subtab(page, "mod")
    _subtab(page, "browse")
    return _click_until_dialog(page, _browse_rows(page))


def reach_resourcepack_detail_dialog(page, nav):
    """Same dialog, reached from the Resource Packs content type - proves the
    shared dialog renders a non-mod kind (different pills/loader set)."""
    reach_tab(page, nav, "mods")
    _subtab(page, "resourcepack")
    _subtab(page, "browse")
    return _click_until_dialog(page, _browse_rows(page))


def reach_modpack_detail_dialog(page, nav):
    """Modpacks tab -> click a pack row -> detail dialog with version picker."""
    reach_tab(page, nav, "modpacks")
    _subtab(page, "browse")
    rows = _browse_rows(page, handler_name="_open_pack_detail")
    return _click_until_dialog(page, rows)


def reach_plugin_detail_dialog(page, nav):
    """Servers -> Plugins -> click a plugin row -> detail dialog."""
    reach_tab(page, nav, "server_plugins")
    _subtab(page, "browse")
    rows = _browse_rows(page, handler_name="_open_plugin_detail")
    return _click_until_dialog(page, rows)


def reach_content_page(page, nav, kind, view):
    """Mods tab -> content type `kind` -> view `view` (browse/installed)."""
    reach_tab(page, nav, "mods")
    ok_kind = _subtab(page, kind)
    ok_view = _subtab(page, view)
    return ok_kind and ok_view


def reach_cape_pane(page, nav):
    """Cosmetics tab -> the Cape segment (the Skin pane is the default)."""
    reach_tab(page, nav, "profile")
    return _subtab(page, "cape")


def reach_plugin_installed(page, nav):
    """Servers -> Plugins -> Installed view (upload/refresh affordances)."""
    reach_tab(page, nav, "server_plugins")
    return _subtab(page, "installed")


def reach_filters_open(page, nav):
    """Mods tab -> expand the category filter chips behind the tune icon."""
    reach_tab(page, nav, "mods")
    return _click_first(page, "filters") or _click_first(page, "filter")


def reach_fix_problems(page, nav):
    """Mods tab -> Installed -> the 'Fix problems' doctor line. The doctor is
    fast on an empty profile, and whatever it reports (all-clear or a repaired
    row) is exactly the surface we want in the shot."""
    reach_tab(page, nav, "mods")
    _subtab(page, "installed")
    return _click_first(page, "fix problems")


def reach_search_typed(page, nav):
    """Mods tab -> type a query (not submitted) so the field shows real input
    and the placeholder/hint styling is visible next to live values."""
    reach_tab(page, nav, "mods")
    return _set_field(page, "sodium", hint_contains="search mods")


def reach_chat_draft(page, nav):
    """Chat tab -> type a draft into the composer (kept unsent, so nothing
    network-visible happens) to show the multi-line composer with content."""
    reach_tab(page, nav, "chat")
    # The composer is a TextField with hint_text="Message..." (no label), so we
    # match on the hint. Kept unsent: no network behaviour, just a draft in the
    # box so the composer's multiline layout + send affordance are visible.
    return _set_field(page, "hey, does the server work for you?",
                      hint_contains="message")


def reach_modpacks_installed(page, nav):
    """Modpacks tab -> Installed view: the second list contract of that tab."""
    reach_tab(page, nav, "modpacks")
    return _subtab(page, "installed")


def reach_plugin_browse(page, nav):
    """Server > Plugins -> Browse view (search + grid), as opposed to the
    installed list. Both views of the plugins tab, so density/empty states of
    each can be compared."""
    reach_tab(page, nav, "server_plugins")
    return _subtab(page, "browse")


def reach_mod_browse(page, nav):
    """Mods tab -> Mods content type in Browse (the default landing view, made
    explicit so the mod grid is its own shot rather than folded into tab_mods)."""
    reach_tab(page, nav, "mods")
    return _subtab(page, "mod") and _subtab(page, "browse")


# ---------------------------------------------------------------- state plan ---
# (name, category, note, reach_fn_or_None). `note` is what a reviewer should look
# at in that shot - it lands in README.md so the folder is self-explaining.
# reach_fn=None means "just a tab" (tab_* states are generated separately).
STATE_PLAN = [
    # ---- core tabs
    ("tab_mods", "Core tabs",
     "Mods tab default: content type tabs, search, browse grid density.", None),
    ("tab_modpacks", "Core tabs",
     "Modpacks browse: pack rows with install affordances.", None),
    ("tab_chat", "Core tabs",
     "Chat with no conversation: empty-state copy and the friends rail.", None),
    ("tab_profile", "Core tabs",
     "Cosmetics: skin pane, live preview, installed cards.", None),
    ("tab_server_console", "Core tabs",
     "Server console with no instance: honest empty state vs. fake controls.", None),
    ("tab_server_settings", "Core tabs",
     "Server settings form: does it read as a form, are units/hints present?", None),
    ("tab_stats", "Core tabs",
     "Stats: counters and card rhythm; do zero-values look broken?", None),
    ("tab_settings", "Core tabs",
     "Settings (gear): grouped options, destructive items clearly separated.", None),

    # ---- mods tab, deep
    ("mods_browse_mods", "Mods tab",
     "Mods browse grid: tile art, name/description truncation, install CTA.", None),
    ("mods_browse_resourcepack", "Mods tab",
     "Resource Packs browse: is the pack's purpose obvious from the tile?", None),
    ("mods_browse_shader", "Mods tab",
     "Shaders browse: same grid with a different domain's labels.", None),
    ("mods_installed_mods", "Mods tab",
     "Installed mods: enabled/disabled chips, size, remove action.", None),
    ("mods_installed_resourcepacks", "Mods tab",
     "Installed packs: compatibility badges (the 'Incompatible' hint lives here).",
     None),
    ("mods_installed_shaders", "Mods tab",
     "Installed shaders: same list contract for a third content type.", None),
    ("mods_search_typed", "Mods tab",
     "Search field with a real query: contrast of hint vs. value, clear button.",
     None),
    ("mods_filters_open", "Mods tab",
     "Expanded category chips: wrapping, tap targets, selected state.", None),
    ("mods_fix_problems", "Mods tab",
     "'Fix problems' result line: is the doctor's outcome legible and calm?",
     None),

    # ---- modpacks tab
    ("modpacks_installed", "Modpacks tab",
     "Installed packs list: the second view of that tab, after a pack exists.",
     None),

    # ---- server tab
    ("server_plugins_browse", "Server tab",
     "Plugins browse: search + grid for a server-side domain.", None),
    ("server_plugins_installed", "Server tab",
     "Plugins installed: protected-plugin notes and the remove control.", None),

    # ---- chat
    ("chat_composer_draft", "Chat",
     "Composer with an unsent draft: multiline growth, send affordance.", None),

    # ---- cosmetics
    ("profile_pane_cape", "Cosmetics",
     "Cape pane: does the pane switch read clearly against the skin pane?", None),

    # ---- dialogs & panels
    ("dialog_mod_detail", "Dialogs",
     "Mod detail: hero, pills, markdown body, version list, install CTA.", None),
    ("dialog_resourcepack_detail", "Dialogs",
     "Resource pack detail: same dialog, non-mod kind (pills/versions differ).", None),
    ("dialog_modpack_detail", "Dialogs",
     "Pack detail: version picker with per-version Install (the new feature).", None),
    ("dialog_plugin_detail", "Dialogs",
     "Plugin detail reached from the server tab.", None),
    ("dialog_delete_confirm", "Dialogs",
     "Destructive confirm: is the risk stated, is Cancel the safe default?", None),
    ("dialog_create_modpack", "Dialogs",
     "Create modpack form: validation affordances, obvious primary action.", None),
    ("panel_account", "Dialogs",
     "Account slide-over: avatar, username fields, pfp upload/remove states.", None),
]

# Deep states: name -> (reach function, extra positional args for it).
_DEEP = {
    "mods_browse_mods": (reach_mod_browse, ()),
    "mods_browse_resourcepack": (reach_content_page, ("resourcepack", "browse")),
    "mods_browse_shader": (reach_content_page, ("shader", "browse")),
    "mods_installed_mods": (reach_content_page, ("mod", "installed")),
    "mods_installed_resourcepacks": (reach_content_page,
                                     ("resourcepack", "installed")),
    "mods_installed_shaders": (reach_content_page, ("shader", "installed")),
    "mods_search_typed": (reach_search_typed, ()),
    "mods_filters_open": (reach_filters_open, ()),
    "mods_fix_problems": (reach_fix_problems, ()),
    "modpacks_installed": (reach_modpacks_installed, ()),
    "server_plugins_browse": (reach_plugin_browse, ()),
    "server_plugins_installed": (reach_plugin_installed, ()),
    "chat_composer_draft": (reach_chat_draft, ()),
    "profile_pane_cape": (reach_cape_pane, ()),
    "dialog_mod_detail": (reach_mod_detail_dialog, ()),
    "dialog_resourcepack_detail": (reach_resourcepack_detail_dialog, ()),
    "dialog_modpack_detail": (reach_modpack_detail_dialog, ()),
    "dialog_plugin_detail": (reach_plugin_detail_dialog, ()),
    "dialog_delete_confirm": (reach_delete_dialog, ()),
    "dialog_create_modpack": (reach_create_modpack_dialog, ()),
    "panel_account": (reach_account_panel, ()),
}


def build_plan(nav, empty=False):
    """Ordered list of (name, category, note, reach_fn).

    The opening state is the Play tab, then the rest of the tabs, then the deep
    states. In --empty mode the dialog states are dropped (a fresh profile has
    no instance to delete and no rows to click) - those absences are correct,
    not MISSes."""
    plan = [("tab_play", "Core tabs",
             "First paint: hero, version picker, PLAY affordance.",
             lambda p, n: reach_tab(p, n, "play"))]
    deep = []
    for name, cat, note, _ in STATE_PLAN:
        if name.startswith("tab_"):
            # tab_<key> states navigate by KEY; the "tab_" prefix is only a
            # naming convention, so strip it before looking the nav control up
            # (STATE_PLAN says tab_mods, the nav key is "mods").
            key = name[len("tab_"):]
            if key in nav:
                plan.append((name, cat, note,
                             (lambda p, n, k=key: reach_tab(p, n, k))))
            continue
        deep.append((name, cat, note))
    for name, cat, note in deep:
        fn, extra = _DEEP.get(name, (None, ()))
        if fn is None:
            continue
        if empty and (name.startswith("dialog_")
                      or name.startswith("mods_installed_")
                      or name in ("mods_fix_problems", "modpacks_installed",
                                  "server_plugins_installed")):
            continue      # no installed content / nothing to open
        plan.append((name, cat, note, (lambda p, n, f=fn, x=extra: f(p, n, *x))))
    return plan


# ----------------------------------------------------------- empty-state stubs --
def force_empty(core):
    """Flip the list/installed readers to empty so we capture what a brand-new
    user sees (no instances, no mods, no packs) - a distinct UX surface."""
    for name in ("list_mods", "list_content", "list_installed_modpacks",
                 "list_custom_skins", "list_plugins", "list_profiles"):
        if hasattr(core, name):
            setattr(core, name, (lambda *a, **k: []))
    if hasattr(core, "get_installed_versions"):
        core.get_installed_versions = lambda *a, **k: []


# ---------------------------------------------------------------- windowed run --
def _write_readme(outdir, manifest, empty):
    """Human index for the folder: one line per shot, grouped by category, with
    the review note. This is the artifact a reviewer (or a vision model fed the
    PNGs) reads first."""
    groups = {}
    for m in manifest:
        groups.setdefault(m.get("category", "Other"), []).append(m)
    lines = ["# Cubeon UX shots",
             "",
             f"Mode: **{'empty / new user' if empty else 'populated'}** - "
             f"{sum(1 for m in manifest if m.get('captured'))}/{len(manifest)} "
             "captured by `tools/ux_capture.py`.",
             "",
             "Review by eye or feed the PNGs to a vision model against a UX "
             "rubric. `manifest.json` has the machine-readable list.",
             ""]
    # Preferred reading order, then anything else the plan invented (keeping
    # the README complete even when a new category is added to STATE_PLAN).
    order = ["Core tabs", "Mods tab", "Modpacks tab", "Server tab", "Chat",
             "Cosmetics", "Dialogs", "Other"]
    cats = [c for c in order if c in groups]
    cats += [c for c in sorted(groups) if c not in order]
    for cat in cats:
        rows = groups.get(cat)
        if not rows:
            continue
        lines += [f"## {cat}", ""]
        for m in rows:
            flag = "" if m.get("captured") else "  _(NOT captured)_"
            lines.append(f"- `{m['file']}` - {m.get('note', '')}{flag}")
        lines.append("")
    with open(os.path.join(outdir, "README.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def capture_main(page, outdir, pixel_ratio, empty, only=None):
    """Flet entry: build the real UI, then run the async tour on the page loop."""
    stubs = fz.install_safe_stubs()
    if empty:
        force_empty(stubs.core)
    else:
        seeded = seed_rich()
        if seeded:
            print(f"   seeded tour fixtures: {', '.join(seeded)}")
    app = stubs.app
    app.main(page)
    baseline_ids = {id(c) for c in getattr(page, "overlay", [])}
    nav = discover_nav(page)
    plan = build_plan(nav, empty)
    if only:
        plan = [s for s in plan if any(t in s[0] for t in only)]

    for attr, val in (("enable_screenshots", True), ("window.width", 1440),
                      ("window.height", 900)):
        try:
            if attr == "enable_screenshots":
                page.enable_screenshots = val
            else:
                setattr(page.window, attr.split(".")[1], val)
        except Exception:
            pass

    async def _tour():
        os.makedirs(outdir, exist_ok=True)
        manifest = []
        for idx, (name, cat, note, reach) in enumerate(plan, 1):
            dismiss_transient(page, baseline_ids)
            if name.startswith("tab_server"):
                _expand_servers(page)
            reached = False
            try:
                reached = bool(reach(page, nav))
            except Exception as ex:
                print(f"  ! reach {name}: {type(ex).__name__}: {ex}")
            try:
                page.update()
            except Exception:
                pass
            await asyncio.sleep(0.5)          # let the tab fade / dialog settle
            fname = f"{idx:02d}_{name}.png"
            path = os.path.join(outdir, fname)
            ok = False
            try:
                png = await page.take_screenshot(pixel_ratio=pixel_ratio, delay=300)
                with open(path, "wb") as f:
                    f.write(png)
                ok = True
                print(f"  captured {fname}  ({len(png) // 1024} KB)")
            except Exception as ex:
                print(f"  ! screenshot {name}: {type(ex).__name__}: {ex}")
            manifest.append({"index": idx, "state": name, "category": cat,
                             "note": note, "file": fname,
                             "reached": reached, "captured": ok})
            if name == "panel_account":
                close_account_panel(page)
                try:
                    page.update()
                except Exception:
                    pass
                await asyncio.sleep(0.4)   # let the slide-out finish
        with open(os.path.join(outdir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump({
                "tool": "tools/ux_capture.py",
                "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
                "empty_mode": empty,
                "pixel_ratio": pixel_ratio,
                "count": len(manifest),
                "captured": sum(1 for m in manifest if m["captured"]),
                "reached": sum(1 for m in manifest if m["reached"]),
                "states": manifest,
            }, f, indent=2)
        _write_readme(outdir, manifest, empty)
        got = sum(1 for m in manifest if m["captured"])
        miss = [m["state"] for m in manifest if m["reached"] is False]
        print(f"\n  {got}/{len(manifest)} states captured -> {outdir}")
        if miss:
            print(f"  not reached: {', '.join(miss)}")
        await asyncio.sleep(0.3)
        try:
            page.window.destroy()             # fire-and-forget: close when done
        except Exception:
            pass

    page.run_task(_tour)
def _run_windowed(outdir, pixel_ratio, empty, only, software):
    """Launch the real Flet window and run the tour. `software=True` forces
    llvmpipe (the AMD Polaris + Mesa 26.1 first-frame SIGSEGV workaround)."""
    if software:
        # Same pair the launcher's crash-recovery path uses. Set before flet
        # imports the client so the renderer is chosen at window creation.
        os.environ["LIBGL_ALWAYS_SOFTWARE"] = "1"
        os.environ.setdefault("GALLIUM_DRIVER", "llvmpipe")
    import flet as ft
    ft.app(target=lambda page: capture_main(page, outdir, pixel_ratio,
                                           empty, only))


def _count_new_pngs(outdir, since):
    try:
        return sum(1 for f in os.listdir(outdir)
                   if f.endswith(".png")
                   and os.path.getmtime(os.path.join(outdir, f)) >= since)
    except OSError:
        return 0


def _dry_run(outdir, empty, only):
    """Headless self-check: build the UI against FakePage (no window, no GL) and
    fire every state's reach function, reporting which states are reachable.
    Same approach the fuzzers use, so it runs green on a headless box and on a
    box whose GPU driver can't render the real window."""
    stubs = fz.install_safe_stubs()
    if empty:
        force_empty(stubs.core)
    page = FakePage()
    stubs.app.main(page)
    baseline = {id(c) for c in getattr(page, "overlay", [])}
    nav = discover_nav(page)
    plan = build_plan(nav, empty)
    if only:
        plan = [s for s in plan if any(t in s[0] for t in only)]
    print(f"   dry run: {len(plan)} states, nav keys found: "
          f"{', '.join(sorted(nav)) or 'NONE'}")
    hit = miss = 0
    for name, _cat, _note, reach in plan:
        dismiss_transient(page, baseline)
        if name.startswith("tab_server"):
            _expand_servers(page)
        try:
            ok = bool(reach(page, nav))
        except Exception as ex:
            print(f"   MISS {name}: {type(ex).__name__}: {ex}")
            ok = False
        if ok:
            hit += 1
        else:
            miss += 1
            print(f"   MISS {name} (reach function returned False)")
    print(f"\n   {hit}/{len(plan)} states reachable"
          + (f", {miss} not reachable" if miss else " - PASS"))
    return 0 if miss == 0 else 1


def main():
    ap = argparse.ArgumentParser(
        description="Capture Cubeon UX screenshots (captures, does not judge).")
    ap.add_argument("--out", default=None,
                    help="output folder (default: agents/docs/ux_shots[_empty])")
    ap.add_argument("--empty", action="store_true",
                    help="tour the new-user/empty state instead of populated")
    ap.add_argument("--only", default=None,
                    help="comma-separated substrings to keep (e.g. mods,chat)")
    ap.add_argument("--dry", action="store_true",
                    help="headless self-check: prove every state is reachable")
    ap.add_argument("--list", action="store_true",
                    help="print the state inventory and exit (no window)")
    ap.add_argument("--pixel-ratio", type=float, default=1.0,
                    help="screenshot scale (2.0 = retina, bigger files)")
    ap.add_argument("--software-gl", action="store_true",
                    help="force llvmpipe rendering (AMD Polaris/Mesa crash fix)")
    ap.add_argument("--_child", action="store_true", help=argparse.SUPPRESS)
    args = ap.parse_args()

    only = tuple(t.strip().lower() for t in args.only.split(",") if t.strip()) \
        if args.only else None
    outdir = args.out or os.path.join(
        REPO, "agents", "docs",
        "ux_shots_empty" if args.empty else "ux_shots")

    if args.list:
        stubs = fz.install_safe_stubs()
        page = FakePage()
        stubs.app.main(page)
        nav = discover_nav(page)
        for i, (name, cat, note, _r) in enumerate(build_plan(nav, args.empty), 1):
            print(f"{i:02d}  {cat:<14} {name:<32} {note}")
        return 0

    if args.dry:
        return _dry_run(outdir, args.empty, only)

    if args._child:
        _run_windowed(outdir, args.pixel_ratio, args.empty, only,
                      args.software_gl)
        return 0

    # Parent path. A GPU/driver crash on the first frame kills the process
    # outright (SIGSEGV inside libgallium on AMD Polaris + Mesa 26.1), which
    # this process cannot catch - so run the window in a CHILD and use "did any
    # PNG appear?" as the health signal. Nothing captured => retry on llvmpipe.
    import subprocess
    os.makedirs(outdir, exist_ok=True)
    base = [sys.executable, os.path.abspath(__file__),
            "--out", outdir, "--pixel-ratio", str(args.pixel_ratio)]
    if args.empty:
        base.append("--empty")
    if args.only:
        base += ["--only", args.only]
    if args.software_gl:
        base.append("--software-gl")

    start = time.time()
    print(f"  UX tour -> {outdir}")
    env = dict(os.environ)
    env.pop("_CUBEON_UX_CHILD", None)
    rc = subprocess.run(base + ["--_child"], env=env).returncode
    got = _count_new_pngs(outdir, start)
    if got == 0 and not args.software_gl:
        print("  nothing captured (GPU/driver crash on first frame?) - "
              "retrying on software GL...")
        start = time.time()
        rc = subprocess.run(base + ["--software-gl", "--_child"],
                            env=env).returncode
        got = _count_new_pngs(outdir, start)
    print(f"  {'OK' if got else 'FAILED'}: {got} screenshot(s) written "
          f"(child exit {rc})")
    return 0 if got else 1


if __name__ == "__main__":
    sys.exit(main())

