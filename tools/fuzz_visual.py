#!/usr/bin/env python3
"""
Cubeon Chaos Monkey - the *visual* one. AGGRESSIVE EDITION.

This opens the REAL Cubeon window and turns loose up to TWELVE "bots" that
visibly drive it hard: each bot glides a colored cursor to a real control,
lights that control up, and fires its actual handler. Beyond plain clicking
it runs dedicated stress patterns:

  ⚡ burst        - 4-9 back-to-back handler fires, zero sleep (thread races)
  🧨 sweep        - every mounted TextField/Dropdown gets its own hostile value
                    in one shot, then all handlers fire at once
  💥 dialog storm - fire every button inside any open modal; if none is open,
                    first poke likely openers so there's something to storm
  🎚 thrash       - flip every Switch, slam every Slider to min/max, cycle
                    every Dropdown - all in a single step
  🌀 blitz        - teleport through 3 tabs with no settle time
  double-click    - ~18% of plain clicks fire twice (idempotency probe)

Plus full VALID flows end-to-end (launch / delete instance / export modpack /
install+EULA+start server) because guarded handlers can't be reached by blind
junk. A HUD on top narrates everything and keeps a running defect count.

It shares its ENTIRE safety layer with the headless monkey (tools/test_fuzz.py)
via _fuzz_common.install_safe_stubs(): every destructive / network / subprocess
/ socket leaf is stubbed BEFORE the UI is built, so a bot clicking "Delete
instance" or "PLAY" touches a recording no-op, never the real ~/.minecraft. That
safety is by construction, not the sandbox - it holds the same in a real
windowed session on your machine.

Honest caveat on the cursor: Flet exposes no way to read a control's on-screen
pixel box from Python, so the flying cursor is *flair* that glides to the right
region (sidebar / content / dialog). The truth of "what am I clicking" is the
control itself lighting up - that's exact, because the bot holds the object.

  Windowed (the cool one):   python3 tools/fuzz_visual.py
                             python3 tools/fuzz_visual.py --bots 8 --pace 0.2
  Headless self-check:       python3 tools/fuzz_visual.py --dry
"""
import os
import sys
import time
import random
import argparse
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _fuzz_common as fz
from _fuzz_common import (
    FUZZ, FakePage, walk, every_control, fire,
    ctrl_text, subtree_text, set_fields, find, clickable_with_subtext,
)

# Sidebar nav labels (lowercased) - used both to *navigate* and to decide the
# cursor's sidebar-vs-content zone. Matches nav_items in main.py.
KNOWN_TABS = {"play", "mods", "modpacks", "servers",
              "console", "profile", "settings"}

# ESCALATION payloads - layered on top of _fuzz_common.FUZZ, visual-only so the
# headless regression test keeps a stable corpus. Nastier class of junk: format
# string / template injection, numeric extremes that survive int() parsing,
# unicode abuse (ZWJ emoji clusters, combining chars), quote floods and markup
# that breaks naive label rendering.
ESCALATION_FUZZ = [
    "%s%s%s%n", "{{7*7}}", "${jndi:ldap://${env:x}}", "<img src=x onerror=alert(1)>",
    "9" * 50, "-" + "9" * 50, "1e999", "-0", "0xdeadbeef", "1_000_000",
    " 1.20.1 ", "+1.20", "1 . 2 0", "１.２０.１",                     # fullwidth digits
    "\U0001F468‍\U0001F469‍\U0001F467‍\U0001F466",                    # ZWJ family emoji
    "é̀a̷̛̻̕b̸̼͌̈", "🏳️‍🌈🏳️‍⚧️", "​‌‍⁡⁢⁣",
    "'" * 120, '"' * 120, "\\" * 60, "`; shutdown --now; `",
    "{\"$gt\": \"\"}", "*/*", " UNION SELECT 1,2,3--", "%00%ff%fe",
]

# HUD palette (independent of Cubeon's theme - the HUD sits on top of it).
PANEL = "#0b0f14"
CURSOR_COLORS = ["#22d3ee", "#f472b6", "#a3e635", "#fbbf24"]
C_DIM = "#94a3b8"
C_TXT = "#e2e8f0"
C_ACT = "#38bdf8"
C_ERR = "#f87171"
C_OK = "#4ade80"


# ------------------------------------------------------------- shared driver ---
class Ctx:
    """Everything a bot step needs, so the same step logic runs windowed
    (real Page, real threads, real sleeps) and headless (FakePage, one thread,
    no sleeps) - which is how --dry can verify the driver here."""

    def __init__(self, page, ft, dry, rng):
        self.page = page
        self.ft = ft
        self.dry = dry
        self.rng = rng
        self.W = int(getattr(page.window, "width", 1180) or 1180)
        self.H = int(getattr(page.window, "height", 760) or 760)
        self.hud_ids = set()          # controls that are HUD, never fuzzed
        self.cursors = []             # one cursor control per bot
        self.log_col = None           # ft.Column of activity lines
        self.caption = None           # big "current action" Text
        self.actions_txt = None       # counter Text
        self.defects_txt = None       # counter Text
        self.actions = 0
        self.defects = 0
        self.log_lines = []           # (color, text) tail, for --dry printing
        self._lock = threading.Lock()

    def sleep(self, s):
        if not self.dry:
            time.sleep(s)

    def update(self):
        try:
            self.page.update()
        except Exception:
            pass

    def note(self, color, text):
        """Append one line to the activity log (and stdout in --dry)."""
        with self._lock:
            self.log_lines.append((color, text))
            self.log_lines = self.log_lines[-200:]
        if self.dry:
            print(f"    {text}")
            return
        row = self.ft.Text(text, size=12, color=color, selectable=False)
        self.log_col.controls.append(row)
        if len(self.log_col.controls) > 16:
            del self.log_col.controls[0]
        self.update()

    def set_caption(self, text, color=C_ACT):
        self.actions_txt.value = f"actions {self.actions}"
        self.defects_txt.value = f"defects {self.defects}"
        if self.dry:
            return
        self.caption.value = text
        self.caption.color = color
        self.update()


def _candidates(ctx):
    """Real, fuzzable controls: text-ish or with any handler, minus the HUD."""
    out = []
    for c in every_control(ctx.page):
        if id(c) in ctx.hud_ids:
            continue
        tn = type(c).__name__
        textish = tn in ("TextField", "Dropdown")
        clickable = any(callable(getattr(c, a, None))
                        for a in ("on_click", "on_submit", "on_change"))
        if textish or clickable:
            out.append((c, textish))
    return out


def _nav_buttons(ctx):
    return [c for c in every_control(ctx.page)
            if callable(getattr(c, "on_click", None))
            and subtree_text(c).strip() in KNOWN_TABS]


def _zone(ctx, c):
    """Best-effort screen region for the cursor (flair; not pixel-exact)."""
    W, H, rng = ctx.W, ctx.H, ctx.rng
    opened_ids = set()
    for d in getattr(ctx.page, "opened", []):
        for x in walk(d):
            opened_ids.add(id(x))
    if id(c) in opened_ids:                                  # a dialog is up
        return W * 0.5 - 8 + rng.uniform(-40, 40), H * 0.5 + rng.uniform(-30, 30)
    if subtree_text(c).strip() in KNOWN_TABS:                # sidebar (width ~220)
        return rng.uniform(28, 170), rng.uniform(150, min(H - 120, 470))
    return rng.uniform(250, W - 130), rng.uniform(150, H - 150)  # content area


def _flash(ctx, c):
    """Light up a real control: scale bump (works on ANY control) plus a bright
    ring / tint where the control supports it. Save -> set -> hold -> restore."""
    saved = {}
    for attr in ("scale", "border", "bgcolor", "opacity"):
        if hasattr(c, attr):
            saved[attr] = getattr(c, attr, None)
    ft = ctx.ft
    try:
        if hasattr(c, "animate_scale"):
            c.animate_scale = ft.Animation(180, ft.AnimationCurve.EASE_OUT)
        if "scale" in saved:
            c.scale = 1.07
        if "border" in saved:
            c.border = ft.border.Border.all(2, "#f8fafc")
        if "bgcolor" in saved and type(c).__name__ != "TextButton":
            c.bgcolor = ft.Colors.with_opacity(0.28, C_ACT)
    except Exception:
        pass
    ctx.update()
    ctx.sleep(0.32)
    for attr, val in saved.items():
        try:
            setattr(c, attr, val)
        except Exception:
            pass
    ctx.update()


def _move_cursor(ctx, bot, c, verb):
    if ctx.dry or bot >= len(ctx.cursors):
        return
    left, top = _zone(ctx, c)
    cur = ctx.cursors[bot]
    cur.left = left
    cur.top = top
    lbl = cur.content.controls[1]
    lbl.value = f"bot{bot + 1} · {verb}"
    ctx.update()


def _short(c):
    t = ctrl_text(c).strip().replace("\n", " ")
    return (t[:26] + "…") if len(t) > 26 else (t or type(c).__name__)


def _fire_and_account(ctx, c):
    """Fire every handler on c, folding any defect into the HUD counter."""
    hit = False
    for attr in ("on_change", "on_submit", "on_click"):
        h = getattr(c, attr, None)
        if not callable(h):
            continue
        hit = True
        defects, _benign = fire(h, c)
        for d in defects:
            ctx.defects += 1
            ctx.note(C_ERR, f"  ✗ DEFECT [{type(c).__name__}.{attr}] {d[:90]}")
    return hit


# ------------------------------------------------------------------ one step ---
def _payload(ctx):
    """Hostile corpus = shared FUZZ + this tool's escalation layer."""
    return ctx.rng.choice(FUZZ + ESCALATION_FUZZ)


def do_fuzz(ctx, bot):
    cands = _candidates(ctx)
    if not cands:
        return
    c, textish = ctx.rng.choice(cands)
    if textish:
        val = _payload(ctx)
        try:
            c.value = val
        except Exception:
            pass
        shown = (val[:18] + "…") if len(val) > 18 else (repr(val) if val.strip() == "" else val)
        ctx.set_caption(f"⌨  typing {shown!r} → {_short(c)}")
        _move_cursor(ctx, bot, c, "type")
        _flash(ctx, c)
        hit = _fire_and_account(ctx, c)
        # Double-click / double-fire probe: real users double-tap; handlers
        # that aren't idempotent (double install, dialog opened twice) die here.
        if hit and ctx.rng.random() < 0.18:
            _fire_and_account(ctx, c)
        ctx.note(C_TXT, f"  bot{bot + 1} typed {shown!r} into {_short(c)}")
    else:
        ctx.set_caption(f"🖱  clicking {_short(c)}")
        _move_cursor(ctx, bot, c, "click")
        _flash(ctx, c)
        ctx.note(C_TXT, f"  bot{bot + 1} clicked {_short(c)}")
        hit = _fire_and_account(ctx, c)
        if hit and ctx.rng.random() < 0.18:
            ctx.note(C_ACT, f"  bot{bot + 1} DOUBLE-CLICKED {_short(c)}")
            _fire_and_account(ctx, c)
    ctx.actions += 1


def do_burst(ctx, bot):
    """Rapid-fire salvo: 4-9 actions back-to-back with ZERO sleeps and no
    flashes - the point is to overlap handler threads (each fire can spin a
    worker) and expose races that paced clicks never will."""
    n = ctx.rng.randint(4, 9)
    ctx.set_caption(f"⚡ burst ×{n} from bot{bot + 1}", "#fbbf24")
    for _ in range(n):
        cands = _candidates(ctx)
        if not cands:
            return
        c, textish = ctx.rng.choice(cands)
        if textish:
            try:
                c.value = _payload(ctx)
            except Exception:
                pass
        _fire_and_account(ctx, c)
    ctx.note("#fbbf24", f"  bot{bot + 1} fired a {n}-action burst")
    ctx.actions += 1


def do_field_sweep(ctx, bot):
    """Hit EVERY TextField/Dropdown currently mounted with its own distinct
    hostile payload in one sweep - then fire each one's handlers. Catches
    cross-field state bleed (a value meant for the port field landing in the
    seed field, etc.) far faster than one-field-per-step fuzzing."""
    fields = [(c, t) for c, t in _candidates(ctx) if t]
    if not fields:
        return
    ctx.set_caption(f"🧨 sweeping {len(fields)} fields with hostile input", "#fbbf24")
    corpus = FUZZ + ESCALATION_FUZZ
    picks = [ctx.rng.choice(corpus) for _ in fields]
    if len(fields) <= len(corpus):
        # Prefer all-distinct payloads; sampling can repeat, sample() can't.
        picks = ctx.rng.sample(corpus, k=len(fields))
    for c, val in zip(fields, picks):
        try:
            c.value = val
        except Exception:
            pass
    ctx.update()
    for c, _t in fields:
        _fire_and_account(ctx, c)
    ctx.note("#fbbf24", f"  bot{bot + 1} swept {len(fields)} fields with hostile values")
    ctx.actions += 1


def do_dialog_storm(ctx, bot):
    """Hammer whatever dialogs are open right now: fire every button/action in
    them (confirm, cancel, X). If none are open, first poke likely openers so
    the NEXT storm has targets. Exercises modal state machines hard."""
    opened = list(getattr(ctx.page, "opened", []))
    targets = [c for d in opened for c in walk(d)
               if any(callable(getattr(c, a, None)) for a in ("on_click",))]
    if not targets:
        # No dialog up - open one via common opener labels, then storm it.
        for needle in ("delete", "create", "add", "export", "new"):
            hits = clickable_with_subtext(ctx.page, needle)
            for h in hits[:2]:
                _fire_and_account(ctx, h)
            opened = list(getattr(ctx.page, "opened", []))
            targets = [c for d in opened for c in walk(d)
                       if callable(getattr(c, "on_click", None))]
            if targets:
                break
    if not targets:
        return
    ctx.set_caption(f"💥 dialog storm ×{len(targets)}", "#fbbf24")
    _move_cursor(ctx, bot, targets[0], "storm")
    for c in targets:
        _fire_and_account(ctx, c)
    ctx.note("#fbbf24", f"  bot{bot + 1} stormed {len(targets)} dialog controls")
    ctx.actions += 1


def do_control_thrash(ctx, bot):
    """Flip EVERY visible Switch to its opposite, slam every Slider between
    extremes (alternating min/max per slider), and cycle every Dropdown to a
    random legal option - all in one step. State-toggle storms kill lazy
    `if flag:` guards that assume toggles are slow."""
    switches, sliders, dropdowns = [], [], []
    for c in every_control(ctx.page):
        tn = type(c).__name__
        if tn == "Switch":
            switches.append(c)
        elif tn == "Slider":
            sliders.append(c)
        elif tn == "Dropdown":
            dropdowns.append(c)
    if not (switches or sliders or dropdowns):
        return
    total = len(switches) + len(sliders) + len(dropdowns)
    ctx.set_caption(f"🎚  thrashing {total} controls", "#fbbf24")
    for s in switches:
        s.value = not bool(s.value)
        _fire_and_account(ctx, s)
    for i, sl in enumerate(sliders):
        lo, hi = getattr(sl, "min", 0), getattr(sl, "max", 100)
        sl.value = hi if i % 2 == 0 else lo
        _fire_and_account(ctx, sl)
    for d in dropdowns:
        opts = [o.key for o in (getattr(d, "options", None) or [])
                if hasattr(o, "key") and o.key is not None]
        if opts:
            d.value = ctx.rng.choice(opts)
            _fire_and_account(ctx, d)
    ctx.note("#fbbf24",
             f"  bot{bot + 1} thrashed {len(switches)} switches, "
             f"{len(sliders)} sliders, {len(dropdowns)} dropdowns")
    ctx.actions += 1


def do_tab_blitz(ctx, bot):
    """Teleport through 3 random tabs back-to-back with no settle time -
    tab-switch code that assumes the previous tab finished mounting breaks."""
    navs = _nav_buttons(ctx)
    if len(navs) < 2:
        return do_fuzz(ctx, bot)
    picks = ctx.rng.sample(navs, k=min(3, len(navs)))
    names = [subtree_text(c).strip() or "?" for c in picks]
    ctx.set_caption(f"🌀 blitz {'→'.join(names)}", "#fbbf24")
    for c in picks:
        _fire_and_account(ctx, c)
    ctx.note("#fbbf24", f"  bot{bot + 1} blitzed {' → '.join(names)}")
    ctx.actions += 1


def do_navigate(ctx, bot):
    navs = _nav_buttons(ctx)
    if not navs:
        return do_fuzz(ctx, bot)
    c = ctx.rng.choice(navs)
    label = subtree_text(c).strip() or "tab"
    ctx.set_caption(f"🧭 opening the {label.title()} tab", C_OK)
    _move_cursor(ctx, bot, c, f"→{label}")
    _flash(ctx, c)
    ctx.note(C_OK, f"  bot{bot + 1} navigated to {label.title()}")
    _fire_and_account(ctx, c)
    ctx.actions += 1


def _goto_tab(ctx, name):
    """Fire the sidebar nav button for a tab so its content actually mounts -
    the play/delete controls only exist while the Play tab is showing, and a
    demo that's wandered to another tab wouldn't otherwise find them."""
    for c in _nav_buttons(ctx):
        if subtree_text(c).strip() == name:
            _fire_and_account(ctx, c)
            return True
    return False


def do_directed(ctx, bot, kind):
    """Run one full VALID flow end-to-end so the guarded, effectful handlers
    (launch_game / delete_version / export_mrpack) actually get exercised -
    blind junk can't reach them (they're gated on valid input). Mirrors the
    directed scenarios in test_fuzz.py, but narrated."""
    pg = ctx.page
    if kind == "launch":
        _goto_tab(ctx, "play")                       # mount the Play tab first
        set_fields(pg, "TextField", "Username", f"Speedy{bot + 1}")
        set_fields(pg, "Dropdown", "Version", "1.20.1")
        ctx.set_caption("🎮 valid flow: launching the game", C_OK)
        for btn in clickable_with_subtext(pg, "play"):
            _move_cursor(ctx, bot, btn, "PLAY")
            _flash(ctx, btn)
            _fire_and_account(ctx, btn)
        ctx.note(C_OK, f"  bot{bot + 1} ran a valid launch flow")
    elif kind == "delete":
        _goto_tab(ctx, "play")                       # the instance card lives here
        set_fields(pg, "Dropdown", "Version", "1.20.1")
        ctx.set_caption("🗑  valid flow: delete instance → confirm", C_OK)
        for btn in find(pg, lambda c: (getattr(c, "tooltip", "") or "") == "Delete instance"):
            _move_cursor(ctx, bot, btn, "delete")
            _flash(ctx, btn)
            _fire_and_account(ctx, btn)          # opens confirm dialog
        for btn in find(pg, lambda c: type(c).__name__ == "TextButton"
                        and ctrl_text(c).strip().lower() == "delete"):
            _flash(ctx, btn)
            _fire_and_account(ctx, btn)          # confirm
        ctx.note(C_OK, f"  bot{bot + 1} ran a valid delete flow")
    elif kind == "export":
        ctx.set_caption("📦 valid flow: create modpack → export", C_OK)
        for c in _nav_buttons(ctx):
            if subtree_text(c).strip() == "modpacks":
                _fire_and_account(ctx, c)
        for btn in clickable_with_subtext(pg, "create modpack"):
            _fire_and_account(ctx, btn)
        set_fields(pg, "TextField", "Pack name", "Chaos Pack")
        set_fields(pg, "TextField", "Version", "1.0.0")
        for btn in clickable_with_subtext(pg, "export .mrpack"):
            _move_cursor(ctx, bot, btn, "export")
            _flash(ctx, btn)
            _fire_and_account(ctx, btn)
        ctx.note(C_OK, f"  bot{bot + 1} ran a valid export flow")
    elif kind == "server":
        # Dedicated-server path: install -> accept EULA -> start. Each stage
        # is a guarded handler the blind fuzz can't reach (gated on installed
        # jar / EULA / stopped state), so it takes a VALID walk to hit them.
        _goto_tab(ctx, "servers")
        ctx.set_caption("🖥  valid flow: install → EULA → start server", C_OK)
        for cb in find(pg, lambda c: type(c).__name__ == "Checkbox"):
            try:
                cb.value = True
            except Exception:
                pass
            _fire_and_account(ctx, cb)
        for needle in ("install",):
            for btn in clickable_with_subtext(pg, needle)[:2]:
                _flash(ctx, btn)
                _fire_and_account(ctx, btn)
        for needle in ("start",):
            for btn in clickable_with_subtext(pg, needle)[:2]:
                _move_cursor(ctx, bot, btn, "start")
                _flash(ctx, btn)
                _fire_and_account(ctx, btn)
        ctx.note(C_OK, f"  bot{bot + 1} ran a valid server install/start flow")
    ctx.actions += 1


DIRECTED_KINDS = ("launch", "delete", "export", "server")

# Step mix. Aggression budget: over half of all steps are now some form of
# stress pattern (burst/sweep/storm/thrash/blitz), directed flows run 3x as
# often as before, and only the remainder is plain one-control fuzzing.
STRESS_STEPS = (
    ("burst", do_burst),
    ("sweep", do_field_sweep),
    ("storm", do_dialog_storm),
    ("thrash", do_control_thrash),
    ("blitz", do_tab_blitz),
)


def step(ctx, bot):
    """One bot action, guarded so a bot thread never dies silently."""
    try:
        roll = ctx.rng.random()
        if roll < 0.10:
            do_navigate(ctx, bot)
        elif roll < 0.22:
            do_directed(ctx, bot, ctx.rng.choice(DIRECTED_KINDS))
        elif roll < 0.62:
            name, fn = ctx.rng.choice(STRESS_STEPS)
            fn(ctx, bot)
        else:
            do_fuzz(ctx, bot)
    except Exception as ex:
        # An error in the DRIVER itself (not a handler defect) - surface it, but
        # keep the bot alive.
        ctx.note(C_ERR, f"  ! driver error: {type(ex).__name__}: {ex}")


# ------------------------------------------------------------------- the HUD ---
def build_hud(ctx, n_bots):
    ft = ctx.ft
    page = ctx.page
    W, H = ctx.W, ctx.H

    ctx.caption = ft.Text("warming up…", size=16, weight=ft.FontWeight.W_700, color=C_ACT)
    ctx.actions_txt = ft.Text("actions 0", size=13, color=C_DIM)
    ctx.defects_txt = ft.Text("defects 0", size=13, color=C_OK)

    banner = ft.Container(
        content=ft.Row(
            [
                ft.Text("🤖 CUBEON CHAOS MONKEY", size=15,
                        weight=ft.FontWeight.W_800, color=C_TXT),
                ft.Container(ctx.caption, expand=True,
                             padding=ft.padding.Padding.only(left=18)),
                ctx.actions_txt,
                ft.Container(width=14),
                ctx.defects_txt,
            ],
            alignment=ft.MainAxisAlignment.START,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        bgcolor=ft.Colors.with_opacity(0.90, PANEL),
        padding=ft.padding.Padding.symmetric(horizontal=18, vertical=12),
        border=ft.border.Border.only(bottom=ft.border.BorderSide(2, C_ACT)),
        left=0, top=0, width=W,
    )

    ctx.log_col = ft.Column([], spacing=1, scroll=ft.ScrollMode.AUTO,
                            width=520, height=210)
    log_panel = ft.Container(
        content=ft.Column(
            [ft.Text("ACTIVITY", size=11, weight=ft.FontWeight.W_700, color=C_DIM),
             ctx.log_col],
            spacing=6),
        bgcolor=ft.Colors.with_opacity(0.86, PANEL),
        padding=ft.padding.Padding.symmetric(horizontal=14, vertical=12),
        border=ft.border.Border.all(1, ft.Colors.with_opacity(0.25, C_ACT)),
        border_radius=12,
        left=14, top=H - 268, width=540,
    )

    # A colored cursor per bot: a dot + a little label, glides via animate_position.
    ctx.cursors = []
    hud_roots = [banner, log_panel]
    for i in range(n_bots):
        color = CURSOR_COLORS[i % len(CURSOR_COLORS)]
        cur = ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=16, height=16, bgcolor=color, border_radius=10,
                                 border=ft.border.Border.all(2, "#0b0f14")),
                    ft.Container(
                        content=ft.Text(f"bot{i + 1}", size=11, color="#0b0f14",
                                        weight=ft.FontWeight.W_700),
                        bgcolor=color, border_radius=6,
                        padding=ft.padding.Padding.symmetric(horizontal=6, vertical=1)),
                ],
                spacing=6, tight=True),
            left=90 + i * 30, top=200 + i * 40,
            animate_position=ft.Animation(420, ft.AnimationCurve.EASE_OUT),
        )
        ctx.cursors.append(cur)
        hud_roots.append(cur)

    for root in hud_roots:
        page.overlay.append(root)
        for c in walk(root):
            ctx.hud_ids.add(id(c))
    ctx.update()


# ------------------------------------------------------------- run: windowed ---
def visual_main(page, n_bots, pace, seed):
    import flet as ft
    app = fz.install_safe_stubs().app
    app.main(page)                                  # build the REAL Cubeon UI

    ctx = Ctx(page, ft, dry=False, rng=random.Random(seed))
    build_hud(ctx, n_bots)
    ctx.note(C_DIM, "  chaos monkey armed - all destructive actions are stubbed no-ops")

    def bot_loop(bot):
        # Stagger so cursors don't move in lockstep - but barely, so overlap
        # is the norm, not the exception.
        time.sleep(0.15 + bot * 0.12)
        while True:
            step(ctx, bot)
            time.sleep(pace * ctx.rng.uniform(0.4, 1.1))

    for b in range(n_bots):
        threading.Thread(target=bot_loop, args=(b,), daemon=True).start()


# ------------------------------------------------------------------ run: dry ---
def run_dry(n_bots, steps, seed):
    """Headless verification of the driver itself: build against FakePage, run
    a fixed plan (random fuzz + one of each directed flow so the guarded handlers
    are provably reached), assert no defects, print coverage. No window."""
    import flet as ft
    print("0. building the real UI under the shared safe stubs (FakePage)")
    app = fz.install_safe_stubs(verbose=False).app
    page = FakePage()
    app.main(page)

    ctx = Ctx(page, ft, dry=True, rng=random.Random(seed))
    build_hud(ctx, n_bots)      # exercises the HUD-build path too (no display)

    print("1. driving {n} random steps across {b} bots".format(n=steps, b=n_bots))
    for i in range(steps):
        step(ctx, i % n_bots)

    print("2. forcing each valid guarded flow at least once (fresh build each,")
    print("   like test_fuzz's scenarios - a launched instance can't be deleted,")
    print("   so re-using one page would let launch block the delete flow)")
    for kind in DIRECTED_KINDS:
        fresh = FakePage()
        app.main(fresh)
        ctx.page = fresh
        do_directed(ctx, 0, kind)

    invoked = fz.INVOKED
    print("\n   reached effectful handlers: " +
          (", ".join(f"{k}×{v}" for k, v in sorted(invoked.items())) or "NONE"))
    print(f"   actions fired: {ctx.actions}   defects: {ctx.defects}")

    ok = True
    if ctx.defects:
        ok = False
        print(f"   FAIL: {ctx.defects} defect(s) surfaced (see ✗ lines above)")
    thread_defects = [f"{n}: {m}" for (n, m) in fz.THREAD_ERRORS if n in fz.DEFECT_EXC]
    if thread_defects:
        ok = False
        print(f"   FAIL: worker-thread defects: {thread_defects[:10]}")
    CRITICAL = ["launch_game", "delete_version", "export_mrpack",
                "install_server", "start_server"]
    missed = [c for c in CRITICAL if c not in invoked]
    if missed:
        ok = False
        print(f"   FAIL: directed flows never reached: {missed}")
    else:
        print(f"   ok: directed flows reached {CRITICAL}")

    print(f"\n{'PASS' if ok else 'FAIL'} - visual driver verified headlessly")
    return 0 if ok else 1


# ----------------------------------------------------------------------- main ---
def main():
    ap = argparse.ArgumentParser(description="Visual UI chaos monkey for Cubeon.")
    ap.add_argument("--dry", action="store_true",
                    help="headless self-check of the driver (no window)")
    ap.add_argument("--bots", type=int, default=4, help="number of bots (1-12)")
    ap.add_argument("--pace", type=float, default=0.35,
                    help="base seconds between a bot's actions (lower = wilder)")
    ap.add_argument("--steps", type=int, default=400, help="--dry: steps to run")
    ap.add_argument("--seed", type=int, default=7, help="RNG seed (reproducible)")
    args = ap.parse_args()
    n_bots = max(1, min(12, args.bots))

    if args.dry:
        sys.exit(run_dry(n_bots, args.steps, args.seed))

    import flet as ft
    assets = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")
    ft.app(target=lambda page: visual_main(page, n_bots, args.pace, args.seed),
           assets_dir=assets)


if __name__ == "__main__":
    main()
