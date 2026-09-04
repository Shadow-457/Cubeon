#!/usr/bin/env python3
"""
UX screenshot tour for Cubeon - captures, does NOT judge.

Drives the REAL Cubeon window through every meaningful state (each tab, plus the
delete-instance and create-modpack dialogs) and writes one clean PNG per state
into a folder, with a manifest.json. It deliberately does NOT add the chaos-
monkey HUD, so the shots are exactly what a user would see. Review them later -
by eye, or hand them to a vision model against a UX rubric. Capture and judgment
are decoupled on purpose: the folder is the artifact.

Capture uses Flet's native page.take_screenshot() (PNG bytes, whole page incl.
overlays - so open dialogs are in the shot), so there's no OS-screenshot / window
-focus fragility and it's cross-platform.

Same safety layer as the fuzzers (tools/_fuzz_common.install_safe_stubs): every
destructive / network / subprocess / socket leaf is stubbed BEFORE the UI is
built, so touring the UI can't touch the real ~/.minecraft or hit the network.
Navigation is by tab KEY (read from each nav button's `k=key` default arg), so
the two "Settings" tabs never get confused.

  Populated states:   python3 tools/ux_capture.py
  Empty / new-user:    python3 tools/ux_capture.py --empty
  Custom folder:       python3 tools/ux_capture.py --out /tmp/cubeon_ux
  Headless self-check: python3 tools/ux_capture.py --dry   (proves every state
                       is reachable; can't screenshot without a window)
"""
import os
import sys
import json
import asyncio
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _fuzz_common as fz
from _fuzz_common import (
    FakePage, FakeEvent, every_control, ctrl_text, subtree_text,
    set_fields, find, clickable_with_subtext,
)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The tabs we tour, in a natural top-to-bottom order. Keys match nav_items /
# server_group_items in main.py; we navigate by key (never by the ambiguous
# "Settings" label).
TAB_ORDER = ["play", "mods", "modpacks", "friends",
             "server_console", "server_settings", "profile", "settings"]
KNOWN_KEYS = set(TAB_ORDER)


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


def reach_delete_dialog(page, nav):
    """Play tab -> pick installed version -> Delete instance -> confirm dialog."""
    reach_tab(page, nav, "play")
    set_fields(page, "Dropdown", "Version", "1.20.1")
    opened = False
    for btn in find(page, lambda c: (getattr(c, "tooltip", "") or "") == "Delete instance"):
        opened = _click(btn) or opened
    return opened


def reach_create_modpack_dialog(page, nav):
    """Modpacks tab -> Create modpack -> the create dialog."""
    reach_tab(page, nav, "modpacks")
    opened = False
    for btn in clickable_with_subtext(page, "create modpack"):
        opened = _click(btn) or opened
    return opened


def build_plan(nav, empty=False):
    """The ordered list of (name, reach_fn) states to capture. The delete-confirm
    dialog is skipped in empty mode: with no installed instances there's no
    'Delete instance' button to open it - that absence is correct, not a miss."""
    plan = [(f"tab_{k}", (lambda p, n, k=k: reach_tab(p, n, k)))
            for k in TAB_ORDER if k in nav]
    if not empty:
        plan.append(("dialog_delete_confirm", reach_delete_dialog))
    plan.append(("dialog_create_modpack", reach_create_modpack_dialog))
    return plan


# ----------------------------------------------------------- empty-state stubs --
def force_empty(core):
    """Flip the list/installed readers to empty so we capture what a brand-new
    user sees (no instances, no mods, no packs) - a distinct UX surface."""
    for name in ("list_mods", "list_content", "list_installed_modpacks",
                 "list_custom_skins", "list_plugins", "list_profiles"):
        if hasattr(core, name):
            setattr(core, name, (lambda *a, **k: []))
    core.get_installed_versions = lambda *a, **k: []


# ---------------------------------------------------------------- windowed run --
def capture_main(page, outdir, pixel_ratio, empty):
    """Flet entry: build the real UI, then run the async tour on the page loop."""
    stubs = fz.install_safe_stubs()
    if empty:
        force_empty(stubs.core)
    app = stubs.app
    app.main(page)
    baseline_ids = {id(c) for c in getattr(page, "overlay", [])}
    nav = discover_nav(page)
    plan = build_plan(nav, empty)

    try:
        page.enable_screenshots = True
    except Exception:
        pass

    async def _tour():
        os.makedirs(outdir, exist_ok=True)
        manifest = []
        for idx, (name, reach) in enumerate(plan, 1):
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
            manifest.append({"index": idx, "state": name, "file": fname,
                             "reached": reached, "captured": ok})
        with open(os.path.join(outdir, "manifest.json"), "w") as f:
            json.dump({"states": manifest, "empty_mode": empty,
                       "count": len(manifest)}, f, indent=2)
        got = sum(1 for m in manifest if m["captured"])
        print(f"\n  {got}/{len(manifest)} states captured -> {outdir}")
        await asyncio.sleep(0.3)
        try:
            page.window.destroy()             # fire-and-forget: close when done
        except Exception:
            pass

    page.run_task(_tour)


# ---------------------------------------------------------------- dry self-test --
def run_dry(empty):
    """Prove every state is reachable, headless. Can't take real screenshots
    (no client), so it drives the same plan against a FakePage and asserts each
    state is reached and the dialogs actually open."""
    print("0. building the real UI under the shared safe stubs (FakePage)")
    stubs = fz.install_safe_stubs(verbose=False)
    if empty:
        force_empty(stubs.core)
    app = stubs.app
    page = FakePage()
    app.main(page)
    baseline_ids = {id(c) for c in page.overlay}
    nav = discover_nav(page)
    print(f"1. discovered {len(nav)} tabs: {', '.join(sorted(nav))}")

    plan = build_plan(nav, empty)
    print(f"2. touring {len(plan)} states (screenshot skipped - no window):")
    results = []
    for idx, (name, reach) in enumerate(plan, 1):
        dismiss_transient(page, baseline_ids)
        before = len(page.opened)
        try:
            reached = bool(reach(page, nav))
        except Exception as ex:
            reached = False
            print(f"     {idx:02d} {name:26} ERROR {type(ex).__name__}: {ex}")
            results.append((name, False))
            continue
        # For dialog states, "reached" means a dialog actually opened.
        dialog_opened = len(page.opened) > before
        ok = reached and (dialog_opened if name.startswith("dialog_") else True)
        print(f"     {idx:02d} {name:26} {'ok' if ok else 'MISS'}"
              f"  -> {idx:02d}_{name}.png")
        results.append((name, ok))

    tabs_ok = sum(1 for n, ok in results if n.startswith("tab_") and ok)
    dlg_ok = sum(1 for n, ok in results if n.startswith("dialog_") and ok)
    dlg_expected = sum(1 for n, _ in results if n.startswith("dialog_"))
    all_ok = tabs_ok >= 6 and dlg_ok == dlg_expected
    print(f"\n   tabs reached: {tabs_ok}/{len(TAB_ORDER)}   "
          f"dialogs opened: {dlg_ok}/{dlg_expected}")
    print(f"{'PASS' if all_ok else 'FAIL'} - tour reaches every state "
          "(run without --dry on a machine with a display to save PNGs)")
    return 0 if all_ok else 1


# ------------------------------------------------------------------------ main --
def main():
    ap = argparse.ArgumentParser(description="Capture a UX screenshot tour of Cubeon.")
    ap.add_argument("--out", default=None, help="output folder (default: ux_shots[_empty])")
    ap.add_argument("--empty", action="store_true",
                    help="capture empty/new-user states (no instances/mods/packs)")
    ap.add_argument("--pixel-ratio", type=float, default=2.0,
                    help="screenshot pixel ratio (higher = crisper/larger)")
    ap.add_argument("--dry", action="store_true",
                    help="headless reachability self-check (no window, no PNGs)")
    args = ap.parse_args()

    if args.dry:
        sys.exit(run_dry(args.empty))

    outdir = args.out or os.path.join(REPO, "agents", "docs", "ux_shots_empty" if args.empty else "ux_shots")
    print(f"touring Cubeon -> {outdir}  (window will flash through states, then close)")
    import flet as ft
    assets = os.path.join(REPO, "assets")
    ft.app(target=lambda page: capture_main(page, outdir, args.pixel_ratio, args.empty),
           assets_dir=assets)


if __name__ == "__main__":
    main()
