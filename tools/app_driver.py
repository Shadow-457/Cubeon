#!/usr/bin/env python3
"""
app_driver.py - let an AI agent actually *use* the Cubeon app and find bugs.

This is the "hands" half of the verification story. It boots the REAL launcher
UI (all tabs, all dialogs) against a fake page with every destructive/network/
subprocess leaf stubbed by `_fuzz_common.install_safe_stubs`, then behaves like
a user: opens every tab, types into every field, clicks every clickable, and
records every exception a handler raises - so a bug a human would hit in the
first minute of clicking is found without a display or a real install.

It reports machine-readable JSON (for an AI to reason over) plus a human
summary, and supports a small JSON step language so an agent can drive the app
deterministically:

    python3 tools/app_driver.py explore          # full guided usage pass
    python3 tools/app_driver.py explore --json   # machine-readable report
    python3 tools/app_driver.py fuzz             # same, with hostile inputs
    python3 tools/app_driver.py tabs             # list reachable nav keys
    python3 tools/app_driver.py script steps.json
    python3 tools/app_driver.py shots [--empty]  # real window screenshots

Screenshots can't be taken headlessly (Flet has no headless renderer); `shots`
delegates to the proven windowed capture tour in `ux_capture.py`. Everything
else runs with no window at all.

Step language (a JSON list; each step is an object):
    {"action": "open_tab", "tab": "mods"}
    {"action": "click",     "text": "Create modpack"}
    {"action": "type",      "label": "Pack name", "value": "My Pack"}
    {"action": "submit",    "label": "Search"}
    {"action": "snapshot"}
    {"action": "wait"}                 # headless: no-op marker
Each step's result is returned in `steps`; `errors` holds every handler
exception seen. Exit code is non-zero when the pass has errors.
"""
from __future__ import annotations
import os
import sys
import json
import argparse

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

import _fuzz_common as fz
from _fuzz_common import (
    FakeEvent, FakePage, every_control, walk, ctrl_text, subtree_text,
    clickable_with_subtext, set_fields,
)

NAV_KEYS = {
    "play", "mods", "modpacks", "profile", "server", "stats", "chat",
    "server_console", "server_plugins", "server_settings", "settings",
}

HARD_EXC = {
    "NameError", "UnboundLocalError", "AttributeError", "TypeError",
    "KeyError", "IndexError", "ZeroDivisionError", "RecursionError",
    "UnboundLocalError",
}

DEFAULT_VALUE = "CubeonSmoke"

# Handler attributes we *scan* for (coverage) vs the subset we actually drive
# in the sweep. on_result/on_hover/... need a real OS/browser event (a file
# dialog, a pointer) so they can't be fired headlessly - we still count them
# so a pass can honestly report "N handlers seen, N fired, these not fired".
HANDLER_ATTRS = ("on_click", "on_change", "on_submit", "on_hover",
                 "on_focus", "on_blur", "on_result", "on_select", "on_tap")


class DriverPage(FakePage):
    """A FakePage that also speaks Flet 0.86's dialog API (show/pop_dialog).

    `every_control` only knows how to reach dialogs via page.opened, so
    show_dialog records there too - otherwise a dialog opened through
    `cubeon.dialogs.open_dialog` would be invisible to the driver.
    """

    class _Dialogs:
        def __init__(self):
            self.controls = []

    def __init__(self):
        super().__init__()
        self._dialogs = DriverPage._Dialogs()

    def show_dialog(self, control):
        control.open = True
        self._dialogs.controls.append(control)
        self.opened.append(control)
        if type(control).__name__ == "SnackBar":
            self.snackbars.append(control)

    def pop_dialog(self):
        while self._dialogs.controls:
            dlg = self._dialogs.controls.pop()
            if getattr(dlg, "open", None):
                dlg.open = False
                return dlg
        return None


def build_headless():
    """Boot the real UI under safe stubs. Returns a ready Driver.

    HOME is redirected first (before any cubeon import) so even module-level
    state files can't land in the real ~/.cubeon_launcher.
    """
    import _sandbox_home

    _sandbox_home.isolate()
    stubs = fz.install_safe_stubs()
    page = DriverPage()
    stubs.app.main(page)
    return Driver(stubs.app, stubs.core, page, stubs)


class Driver:
    def __init__(self, app, core, page, stubs):
        self.app = app
        self.core = core
        self.page = page
        self.stubs = stubs
        self.actions = []
        self.errors = []
        self.warnings = []
        self.screenshots = []
        self._fired = set()
        self.handlers_seen = {}     # (id(ctrl), attr) -> label, union over the pass
        self._tab_state = {}

    # ---------------------------------------------------------------- nav ---
    def tabs(self):
        """Map a nav key to the control that switches to it.

        The switch handlers are `lambda e, k=key: switch_tab(k)`, so the key is
        the handler's single default arg. That's exact and immune to the two
        controls labelled "Settings".
        """
        out = {}
        for c in every_control(self.page):
            h = getattr(c, "on_click", None)
            d = getattr(h, "__defaults__", None)
            if callable(h) and isinstance(d, tuple) and len(d) == 1 \
                    and isinstance(d[0], str) and d[0] in NAV_KEYS:
                out.setdefault(d[0], c)
        return out

    def open_tab(self, key):
        for c in every_control(self.page):
            h = getattr(c, "on_click", None)
            d = getattr(h, "__defaults__", None)
            if isinstance(d, tuple) and d and d[0] == key:
                return self._fire_named(c, "on_click", f"open_tab:{key}")
        # Fallback: a clickable whose visible text is the tab key.
        for c in clickable_with_subtext(self.page, key):
            return self._fire_named(c, "on_click", f"open_tab:{key}")
        return False

    # ------------------------------------------------------------- actions ---
    def click(self, text):
        hits = clickable_with_subtext(self.page, text)
        if not hits:
            return False
        return self._fire_named(hits[0], "on_click", f"click:{text}")

    def set_field(self, label, value):
        hits = [c for c in every_control(self.page)
                if getattr(c, "label", None) == label
                or getattr(c, "hint_text", None) == label]
        for c in hits:
            try:
                c.value = value
            except Exception:
                pass
            h = getattr(c, "on_change", None)
            if callable(h):
                self._fire_named(c, "on_change", f"set_field:{label}")
        return len(hits)

    def submit(self, label):
        hits = [c for c in every_control(self.page)
                if getattr(c, "label", None) == label
                or getattr(c, "hint_text", None) == label]
        ok = False
        for c in hits:
            h = getattr(c, "on_submit", None)
            if callable(h):
                ok = self._fire_named(c, "on_submit", f"submit:{label}") or ok
        return ok

    def type_fields(self, value=DEFAULT_VALUE):
        """Type a plausible value into every text-ish control and fire change."""
        typed = 0
        for c in every_control(self.page):
            if type(c).__name__ not in ("TextField", "Dropdown"):
                continue
            cur = getattr(c, "value", None)
            if not isinstance(cur, (str, type(None))):
                continue
            hint = " ".join(str(getattr(c, "label", "") or
                                getattr(c, "hint_text", "")).lower().split())
            v = _plausible(hint, value)
            try:
                c.value = v
            except Exception:
                continue
            typed += 1
            if callable(getattr(c, "on_change", None)):
                self._fire_named(c, "on_change", f"type:{hint}")
            if callable(getattr(c, "on_submit", None)):
                self._fire_named(c, "on_submit", f"submit:{hint}")
        return typed

    def fire_all(self, value="__click__"):
        """Fire every handler on every reachable control once. Safe by stubs.

        Covers the input handlers (change/submit/click) plus the event handlers
        a synthetic event *can* stand in for: hover in/out, focus/blur, and a
        picker result. Only real OS events (pointer motion, a file dialog's
        selection) have no headless analogue.
        """
        n = 0
        for c in list(every_control(self.page)):
            self._scan_handlers(c)
            for attr in ("on_change", "on_submit", "on_click"):
                if callable(getattr(c, attr, None)):
                    if self._fire_named(c, attr, value):
                        n += 1
            if callable(getattr(c, "on_hover", None)):
                if self._fire_named(c, "on_hover", f"{value}|hover:true", "true"):
                    n += 1
                if self._fire_named(c, "on_hover", f"{value}|hover:false", "false"):
                    n += 1
            for attr in ("on_focus", "on_blur"):
                if callable(getattr(c, attr, None)):
                    if self._fire_named(c, attr, f"{value}|{attr}"):
                        n += 1
            if callable(getattr(c, "on_result", None)):
                # FakeEvent.files == [] exercises the "cancelled" picker path.
                if self._fire_named(c, "on_result", f"{value}|on_result"):
                    n += 1
        return n

    def _scan_handlers(self, ctrl):
        """Record every handler binding we can see, so the report can show
        which ones a pass never fired (not just the ones it did)."""
        for attr in HANDLER_ATTRS:
            if callable(getattr(ctrl, attr, None)):
                where = f"{type(ctrl).__name__}.{attr}"
                label = ctrl_text(ctrl)
                if label:
                    where += f"({label[:40]!r})"
                self.handlers_seen[(id(ctrl), attr)] = where

    # -------------------------------------------------------------- record ---
    def _fire_named(self, ctrl, attr, action, data=""):
        h = getattr(ctrl, attr, None)
        if not callable(h):
            return False
        where = f"{type(ctrl).__name__}.{attr}"
        label = ctrl_text(ctrl)
        if label:
            where += f"({label[:40]!r})"
        self.handlers_seen[(id(ctrl), attr)] = where
        key = (id(ctrl), attr, action)
        if key in self._fired:
            return False
        self._fired.add(key)
        self.actions.append(action)
        try:
            try:
                h(FakeEvent(ctrl, data))
            except TypeError:
                h()
        except Exception as ex:
            self._classify(ex, where, action)
        return True

    # Headless artifacts: real in a live window, meaningless here. A hover
    # handler that calls container.update() or a focus() that needs a live
    # view raises these - not bugs, so don't even warn.
    _ARTIFACT_PATTERNS = (
        "Control must be added to the page first",
        "Event loop is closed",
    )

    def _classify(self, ex, where, action):
        name = type(ex).__name__
        msg = str(ex)
        if name == "RuntimeError" and any(p in msg for p in self._ARTIFACT_PATTERNS):
            return
        rec = {"where": where, "action": action, "type": name,
               "message": msg[:400]}
        if name in HARD_EXC:
            rec["severity"] = "error"
            self.errors.append(rec)
        else:
            rec["severity"] = "info"
            self.warnings.append(rec)

    # --------------------------------------------------------------- checks ---
    def none_children(self):
        """Every None sitting in a Flet controls list - the gray-box bug."""
        bad = []
        for c in every_control(self.page):
            lst = getattr(c, "controls", None)
            if isinstance(lst, list):
                for i, x in enumerate(lst):
                    if x is None:
                        bad.append(f"{type(c).__name__}[{i}]")
        return bad

    def visible_text(self):
        return " | ".join(
            str(v) for c in every_control(self.page)
            for v in (getattr(c, "value", None), getattr(c, "text", None),
                      getattr(c, "label", None), getattr(c, "tooltip", None))
            if isinstance(v, str) and v.strip())

    # --------------------------------------------------------------- report ---
    def handler_coverage(self):
        """How much of the app's handler surface a pass actually fired."""
        seen = self.handlers_seen
        fired = {(cid, attr) for (cid, attr, _action) in self._fired}
        never = [(k, v) for k, v in seen.items() if k not in fired]
        total = len(seen)
        n_fired = len(seen) - len(never)
        return {
            "handlers_seen": total,
            "handlers_fired": n_fired,
            "percent": round(100.0 * n_fired / total, 1) if total else 0.0,
            "not_fired": [v for _k, v in sorted(never, key=lambda kv: kv[1])],
        }

    def report(self, mode="explore"):
        none_bad = self.none_children()
        return {
            "mode": mode,
            "ok": not self.errors and not none_bad,
            "errors": self.errors,
            "none_children": none_bad,
            "warnings": self.warnings[:120],
            "warning_count": len(self.warnings),
            "action_count": len(self.actions),
            "coverage": dict(getattr(self.stubs, "invoked", {})),
            "handler_coverage": self.handler_coverage(),
            "screenshots": self.screenshots,
        }


def _plausible(hint, fallback):
    if not hint:
        return fallback
    if "username" in hint or "player" in hint or "name" in hint:
        if "pack" in hint or "server" in hint or "group" in hint:
            return "Smoke Pack"
        return "SmokePilot"
    if "search" in hint or "find" in hint or "filter" in hint:
        return "sodium"
    if "version" in hint:
        return "1.20.1"
    if "port" in hint:
        return "25565"
    if "ram" in hint or "memory" in hint:
        return "2048"
    return fallback


# ------------------------------------------------------------------ commands ---
def cmd_explore(args):
    d = build_headless()
    return _run_usage(d, hostile=args.hostile, mode="fuzz" if args.hostile else "explore")


def _run_usage(d, hostile=False, mode="explore"):
    nav = d.tabs()
    corpus = fz.FUZZ if hostile else [DEFAULT_VALUE, "1.20.1", "Smoke Pack"]
    tabs_opened = {}
    for key in sorted(nav):
        ok = d.open_tab(key)
        tabs_opened[key] = ok
        for value in corpus:
            if hostile:
                _type_all_hostile(d, value)
            else:
                d.type_fields(value)
            d.fire_all(value)
    # dialogs opened above become reachable now; one more sweep.
    for value in corpus:
        d.fire_all(value)

    rep = d.report(mode)
    rep["nav_discovered"] = sorted(nav)
    rep["tabs_opened"] = tabs_opened
    return rep


def _type_all_hostile(d, value):
    for c in every_control(d.page):
        if type(c).__name__ in ("TextField", "Dropdown"):
            try:
                c.value = value
            except Exception:
                pass


def cmd_tabs(args):
    d = build_headless()
    nav = d.tabs()
    rep = d.report("tabs")
    rep["nav_discovered"] = sorted(nav)
    return rep


def cmd_script(args):
    d = build_headless()
    with open(args.file, encoding="utf-8") as f:
        steps = json.load(f)
    results = []
    for step in steps:
        action = step.get("action")
        try:
            if action == "open_tab":
                ok = d.open_tab(step.get("tab", ""))
            elif action == "click":
                ok = d.click(step.get("text", ""))
            elif action == "type":
                ok = d.set_field(step.get("label", ""), step.get("value", "")) > 0
            elif action == "submit":
                ok = d.submit(step.get("label", ""))
            elif action == "snapshot":
                d.screenshots.append({"name": step.get("name", "snap"),
                                      "note": "headless - run `shots` for a PNG"})
                ok = True
            elif action == "wait":
                ok = True
            else:
                ok = False
                d.warnings.append({"where": "script", "type": "UnknownAction",
                                   "message": f"unknown action {action!r}",
                                   "severity": "info"})
            results.append({"step": action, "ok": bool(ok)})
        except Exception as ex:
            d._classify(ex, f"script:{action}", action)
            results.append({"step": action, "ok": False,
                            "type": type(ex).__name__, "message": str(ex)})
    rep = d.report("script")
    rep["steps"] = results
    return rep


def cmd_shots(args):
    """Real window screenshots - delegates to the proven ux_capture tour."""
    import ux_capture
    argv = ["ux_capture"]
    if args.empty:
        argv.append("--empty")
    if args.out:
        argv += ["--out", args.out]
    if args.dry:
        argv.append("--dry")
    sys.argv = argv
    rc = ux_capture.main()
    return None if rc is None else rc


# ----------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser(description="Drive the Cubeon app and report bugs.")
    sub = ap.add_subparsers(dest="cmd")

    for name in ("explore", "fuzz"):
        p = sub.add_parser(name, help=f"guided usage pass ({name})")
        p.add_argument("--json", action="store_true", help="print JSON report")
        p.add_argument("--out", help="also write the JSON report here")
        p.set_defaults(_cmd=cmd_explore, hostile=(name == "fuzz"))

    p = sub.add_parser("tabs", help="list reachable nav keys")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out")
    p.set_defaults(_cmd=cmd_tabs, hostile=False)

    p = sub.add_parser("script", help="run a JSON step script")
    p.add_argument("file")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out")
    p.set_defaults(_cmd=cmd_script)

    p = sub.add_parser("shots", help="real windowed screenshot tour")
    p.add_argument("--out")
    p.add_argument("--empty", action="store_true")
    p.add_argument("--dry", action="store_true")
    p.set_defaults(_cmd=cmd_shots)

    args = ap.parse_args()
    if not getattr(args, "_cmd", None):
        args._cmd = cmd_explore
        args.hostile = False
        args.json = False
        args.out = None

    rep = args._cmd(args)
    if rep is None:
        sys.exit(0)

    if getattr(args, "out", None):
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(rep, f, indent=2)

    if getattr(args, "json", False):
        print(json.dumps(rep, indent=2))
    else:
        _print_summary(rep)

    sys.exit(0 if rep.get("ok") else 1)


def _print_summary(rep):
    print(f"mode: {rep.get('mode')}")
    if rep.get("nav_discovered") is not None:
        opened = rep.get("tabs_opened") or {}
        bad = [k for k, v in opened.items() if not v]
        print(f"tabs discovered: {len(rep['nav_discovered'])}"
              + (f"  NOT opened: {bad}" if bad else "  (all opened)"))
    print(f"actions fired: {rep.get('action_count', 0)}")
    hc = rep.get("handler_coverage") or {}
    if hc.get("handlers_seen"):
        never = hc.get("not_fired") or []
        print(f"handler coverage: {hc['handlers_fired']}/{hc['handlers_seen']} "
              f"({hc['percent']}%) fired"
              + (f"  not fired: {', '.join(never[:6])}" if never else ""))
    cov = rep.get("coverage") or {}
    if cov:
        print("effectful handlers reached: "
              + ", ".join(f"{k}x{v}" for k, v in sorted(cov.items())))
    errs = rep.get("errors") or []
    nones = rep.get("none_children") or []
    print(f"\n{'OK' if rep.get('ok') else 'FAILED'}: "
          f"{len(errs)} error(s), {len(nones)} None-child site(s), "
          f"{rep.get('warning_count', 0)} info")
    for e in errs[:20]:
        print(f"  ERROR {e['where']} [{e['action']}] {e['type']}: {e['message']}")
    for n in nones[:10]:
        print(f"  NULL  {n}")
    for w in (rep.get("warnings") or [])[:8]:
        print(f"  info  {w.get('where')} {w.get('type')}: {w.get('message')}")


if __name__ == "__main__":
    main()
