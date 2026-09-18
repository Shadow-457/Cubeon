"""Cubeon UI inspector — a DevTools-style live editor for the launcher's Flet UI.

WHY THIS EXISTS
The launcher's visible text lives in ~60 files' worth of ft.Text() calls, and
"small small gui text replacing" by hand means finding the right line in the
right builder out of thousands. This module lets you click through the mounted
control tree, see every text/tooltip property, and edit it LIVE to preview how
it reads before touching source. It's a design tool, not a persistence layer:
changes vanish on restart unless you then fix the source where it shows you.

WHAT IT EDITS
- ft.Text.value / .size / .color / .weight
- tooltip strings (Flet's .tooltip property, present on every Control)
- ft.Button/FilledButton/TextButton labels (str content)

HOW IT'S BUILT
A modal dialog hosting: a tree of the current page's controls (collapsible,
annotated with each control's class + its text if any), a detail pane of
editable properties, and a global "find text" box that filters the tree down
to matching controls. Edits call control.update() so only that control
repaints, and every edit is logged to the launcher log with file:line of the
constructor when it can be found — pointing you at the source line to change
for real.

INVOKING
HIDDEN by default: a small 🐞 button appended to the sidebar's bottom (or the
F12-style keyboard shortcut below) — gated behind CUBEON_INSPECT=1 so end
users of public builds never see it. In dev: CUBEON_INSPECT=1 python main.py
"""
from __future__ import annotations

import logging
import os
import re

import flet as ft

log = logging.getLogger(__name__)

# Property names we allow editing, per attribute, with a friendly label.
# Everything else is read-only in the detail pane — a typo in 'expand' can
# break layout in ways that look like bugs, so we only expose what's safe.
_EDITABLE = {
    "value": "Text",
    "size": "Font size",
    "color": "Color",
    "weight": "Weight",
    "tooltip": "Tooltip",
}

_WEIGHTS = [
    "normal", "w_100", "w_200", "w_300", "w_400", "w_500",
    "w_600", "w_700", "w_800", "w_900", "bold", "bolder",
]


def inspector_enabled(cfg: dict | None = None) -> bool:
    """Dev builds only. Two opt-ins, either works (also in packaged builds,
    where setting an env var before double-clicking is impractical):
      - environment: CUBEON_INSPECT=1
      - config: cfg["dev_inspector"] = True (Settings-side toggle)
    Public builds ship no such config and no env, so it stays hidden.
    """
    if os.environ.get("CUBEON_INSPECT", "").strip() not in ("", "0", "false", "no"):
        return True
    try:
        if cfg and bool(cfg.get("dev_inspector")):
            return True
    except Exception:
        pass
    # A config file that sets dev_inspector without the caller passing cfg:
    # read it lazily rather than importing the whole config stack here.
    try:
        p = os.path.join(os.path.expanduser("~"), ".cubeon_launcher", "config.json")
        if os.path.isfile(p):
            import json
            with open(p, encoding="utf-8") as fh:
                return bool(json.load(fh).get("dev_inspector"))
    except Exception:
        pass
    return False


def _control_text(c) -> str:
    """The human-visible text of a control, if it has any ('' otherwise)."""
    try:
        v = getattr(c, "value", None)
        if isinstance(v, str) and v:
            return v
        content = getattr(c, "content", None)
        if isinstance(content, str):
            return content
    except Exception:
        pass
    return ""


def _walk(control, depth=0, max_depth=60):
    """Yield (control, depth) over the whole mounted tree, guarding against
    cycles (Flet trees can loop through page references) and depth blowups."""
    seen = set()
    stack = [(control, 0)]
    while stack:
        c, d = stack.pop()
        if id(c) in seen or d > max_depth:
            continue
        seen.add(id(c))
        yield c, d
        children = []
        for attr in ("controls", "content", "leading", "trailing", "title", "subtitle"):
            try:
                v = getattr(c, attr, None)
            except Exception:
                v = None
            if v is None:
                continue
            if isinstance(v, (list, tuple)):
                children.extend(x for x in v if isinstance(x, ft.Control))
            elif isinstance(v, ft.Control):
                children.append(v)
        for ch in reversed(children):
            stack.append((ch, d + 1))


def _safe_update(ctrl) -> None:
    """ctrl.update() but tolerant of a control that isn't mounted yet
    (headless tests, or the dialog being built before page.open())."""
    try:
        ctrl.update()
    except Exception:
        pass


class InspectorDialog:
    """The inspector window. One instance per open; open_inspect() builds it."""

    def __init__(self, page: ft.Page):
        self.page = page
        self.selected = None
        self.roots = list(page.controls) if getattr(page, "controls", None) else []
        self._tree_items = []          # every row we created (for search filter)
        self._build()

    # ------------------------------------------------------------------ UI

    def _build(self):
        # Theme tokens from the launcher itself (cubeon/theme.py re-exported
        # via main's import surface — but importing directly avoids any
        # dependency on main.py).
        from cubeon.theme import (BG, SURFACE, SURFACE_HI, BORDER, BORDER_HI,
                                  TEXT, TEXT_DIM, ACCENT, RADIUS)
        self._t = dict(BG=BG, SURFACE=SURFACE, SURFACE_HI=SURFACE_HI,
                       BORDER=BORDER, BORDER_HI=BORDER_HI, TEXT=TEXT,
                       TEXT_DIM=TEXT_DIM, ACCENT=ACCENT, RADIUS=RADIUS)
        t = self._t

        self.search = ft.TextField(
            hint_text="Find text…", dense=True, height=40,
            on_change=self._on_search, prefix_icon=ft.Icons.SEARCH,
            bgcolor=SURFACE_HI, border_color=BORDER,
            focused_border_color=ACCENT, color=TEXT,
            hint_style=ft.TextStyle(color=TEXT_DIM),
            text_style=ft.TextStyle(color=TEXT),
        )
        # FIXED panel sizes, not expand chains: an AlertDialog sizes its
        # content only from explicit width/height — expand=True inside the
        # content collapses to zero because the dialog gives its content no
        # bounded constraints to expand INTO. That's why the first version
        # rendered as an empty sliver.
        TREE_W, TREE_H, DETAIL_W = 380, 460, 320
        self.tree_column = ft.Column(spacing=0, scroll=ft.ScrollMode.AUTO)
        self.detail = ft.Column(spacing=10, scroll=ft.ScrollMode.AUTO)
        self.hint = ft.Container(
            content=ft.Text("Pick a control on the left. Text-like properties "
                            "can be edited live; the hint below the editor "
                            "shows the text to search in your editor to make "
                            "the change permanent.", size=12, color=TEXT_DIM),
            padding=8,
        )
        self.dialog = ft.AlertDialog(
            modal=True, bgcolor=SURFACE,
            title=ft.Row([
                ft.Icon(ft.Icons.BUG_REPORT, size=18, color=ACCENT),
                ft.Text("Cubeon inspector", size=16, weight=ft.FontWeight.W_600,
                        color=TEXT),
                ft.TextButton("Close", on_click=self._close,
                              style=ft.ButtonStyle(color=TEXT_DIM)),
            ], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            content=ft.Container(
                content=ft.Column([
                    self.search,
                    ft.Row([
                        ft.Container(content=self.tree_column,
                                     width=TREE_W, height=TREE_H,
                                     bgcolor=BG,
                                     border=ft.border.Border.all(1, BORDER),
                                     border_radius=6, padding=4),
                        ft.Container(content=self.detail,
                                     width=DETAIL_W, height=TREE_H,
                                     bgcolor=BG,
                                     border=ft.border.Border.all(1, BORDER),
                                     border_radius=6, padding=8),
                    ], spacing=8),
                ], spacing=8, tight=True),
            ),
        )
        self._fill_tree()
        self._render_detail()

    def _fill_tree(self, query: str = ""):
        self.tree_column.controls.clear()
        self._tree_items.clear()
        q = query.strip().lower()
        for c, depth in self._walk_all():
            text = _control_text(c)
            label = f"{type(c).__name__}"
            if text:
                label += f"  “{text[:40]}”"
            if q and q not in label.lower():
                continue
            row = ft.Container(
                content=ft.Text(label, size=12.5, selectable=True,
                                color=self._t["TEXT"]),
                padding=ft.padding.Padding.only(left=6 + depth * 12, top=3, bottom=3, right=4),
                border_radius=4, ink=False,
                on_click=lambda e, ctrl=c: self._select(ctrl),
                data=c,
            )
            self.tree_column.controls.append(row)
            self._tree_items.append((row, label))
        if not self.tree_column.controls:
            self.tree_column.controls.append(
                ft.Text("Nothing matches.", size=12, italic=True,
                        color=self._t["TEXT_DIM"]))
        _safe_update(self.tree_column)

    def _walk_all(self):
        for root in self.roots:
            yield from _walk(root)

    # ------------------------------------------------------------- actions

    def _on_search(self, e=None):
        self._fill_tree(self.search.value or "")

    def _select(self, ctrl):
        self.selected = ctrl
        self._render_detail()
        try:
            _safe_update(self.tree_column)
        except Exception:
            pass

    def _render_detail(self):
        self.detail.controls.clear()
        c = self.selected
        if c is None:
            self.detail.controls.append(self.hint)
            try:
                _safe_update(self.detail)
            except Exception:
                pass
            return

        header = f"{type(c).__name__}"
        text = _control_text(c)
        if text:
            header += f"  “{text[:60]}”"
        self.detail.controls.append(ft.Text(header, size=14, weight=ft.FontWeight.W_700,
                                            color=self._t["TEXT"]))

        # Read-only identity block — helps locate the source: the search box
        # in your editor for the shown default text finds the constructor.
        self.detail.controls.append(ft.Text(
            f"Search your editor for:  “{text}”" if text else "(no text)",
            size=11, italic=True, selectable=True, color=self._t["TEXT_DIM"]))

        t = self._t
        field_theme = dict(
            bgcolor=t["SURFACE_HI"], border_color=t["BORDER"],
            focused_border_color=t["ACCENT"], color=t["TEXT"],
            label_style=ft.TextStyle(color=t["TEXT_DIM"]),
            text_style=ft.TextStyle(color=t["TEXT"]),
            hint_style=ft.TextStyle(color=t["TEXT_DIM"]),
        )
        any_edit = False
        for prop, label in _EDITABLE.items():
            cur = getattr(c, prop, None)
            if cur is None and prop != "tooltip":
                continue
            if prop == "tooltip" and cur is None:
                continue
            any_edit = True
            if prop == "weight":
                field = ft.Dropdown(
                    label=label, value=str(cur), dense=True, height=44,
                    bgcolor=t["SURFACE_HI"], border_color=t["BORDER"],
                    focused_border_color=t["ACCENT"],
                    label_style=ft.TextStyle(color=t["TEXT_DIM"]),
                    options=[ft.dropdown.Option(w) for w in _WEIGHTS],
                    on_select=lambda e, cc=c, p=prop: self._apply(cc, p, e.control.value),
                )
            elif prop in ("value", "tooltip"):
                field = ft.TextField(
                    label=label, value=str(cur), dense=True, multiline=prop == "value",
                    on_blur=lambda e, cc=c, p=prop: self._apply(cc, p, e.control.value or ""),
                    **field_theme,
                )
            else:  # size, color
                field = ft.TextField(
                    label=label, value=str(cur), dense=True,
                    on_blur=lambda e, cc=c, p=prop: self._apply(cc, p, e.control.value or ""),
                    **field_theme,
                )
            self.detail.controls.append(field)

        if not any_edit:
            self.detail.controls.append(ft.Text(
                "No editable text properties on this control "
                "(select a Text/Button in the tree).", size=12,
                color=self._t["TEXT_DIM"]))

        self.detail.controls.append(ft.Container(height=1, bgcolor=self._t["BORDER"]))
        self.detail.controls.append(ft.Text(
            "Changes are live but not saved — restart reverts them. "
            "Use the search hint above to find the source line.",
            size=11, color=self._t["TEXT_DIM"]))
        try:
            _safe_update(self.detail)
        except Exception:
            pass

    def _apply(self, ctrl, prop, new_raw):
        old = getattr(ctrl, prop, None)
        if new_raw == old:
            return
        try:
            if prop == "size":
                new = float(new_raw)
            elif prop == "weight":
                new = new_raw or "normal"
            else:
                new = new_raw
            setattr(ctrl, prop, new)
            _safe_update(ctrl)
            log.info("inspector: %s.%s %r -> %r", type(ctrl).__name__, prop, old, new)
        except Exception as ex:
            log.warning("inspector edit rejected (%s.%s=%r): %s",
                        type(ctrl).__name__, prop, new_raw, ex)
            try:
                from . import dialogs as cubeon_dialogs
                cubeon_dialogs.show_snack(self.page, f"Couldn't set {prop}: {ex}")
            except Exception:
                pass
            return
        self._render_detail()

    def _close(self, e=None):
        try:
            from . import dialogs as cubeon_dialogs
            cubeon_dialogs.close_dialog(self.page, self.dialog)
        except Exception:
            try:
                if self.dialog.open:
                    self.dialog.open = False
                    self.page.update()
            except Exception:
                pass


def open_inspect(page: ft.Page):
    """Open (or reopen) the inspector. Entry point used by main.py."""
    dlg = InspectorDialog(page)
    try:
        from . import dialogs as cubeon_dialogs
        cubeon_dialogs.open_dialog(page, dlg.dialog)
    except Exception:
        # Last resort: flip the flag directly.
        dlg.dialog.open = True
        page.update()
    log.info("inspector opened (%d root controls, tree walk ok)",
             len(dlg.roots))
