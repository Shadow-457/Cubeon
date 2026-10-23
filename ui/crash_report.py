"""The game-crash popup: what happened, the log, and a way to ask for help.

WHY THIS EXISTS (2026-10-23 user report)
----------------------------------------
When Minecraft died, the launcher printed one line under the Play button and
threw the evidence away: the user had no idea whether it was Java, a mod, or
the driver, and no way to show anyone. The game log already exists on disk
(``cubeon/launch.py`` tails ``~/.cubeon_launcher/game-<session>.log``), so this
dialog surfaces it:

* the reason, in the same plain language ``main._explain_exit`` uses;
* the tail of the game's own output, behind a "Show log" expansion (a wall of
  text on first paint would bury the one sentence that matters);
* Copy, so the whole report can be pasted into Discord;
* a direct invite button to the Cubeon Discord, which is where support
  actually happens.

The dialog never raises: a crash path must not be able to break the launcher.
It is also non-modal on purpose - the user can still switch tabs while it is
open, and Close only dismisses the report.
"""
from __future__ import annotations

import webbrowser

import flet as ft

from cubeon import dialogs as cubeon_dialogs
from cubeon.theme import (
    ACCENT, BG, BORDER, DANGER, FONT_DISPLAY, FONT_MONO, ON_ACCENT,
    RADIUS, SURFACE, SURFACE_HI, TEXT, TEXT_DIM, TEXT_FAINT,
)

# The support invite, from the 2026-10-23 report.
DISCORD_INVITE = "https://discord.gg/cvzmrSjUzZ"

# A runaway log (a mod that spams a stack trace every tick) must not build a
# multi-megabyte TextField inside a dialog. The full file stays on disk and its
# path is shown; this is the part we are willing to render.
MAX_LOG_CHARS = 60000


def copy_text(page, text: str) -> bool:
    """Best-effort clipboard write across Flet versions. Never raises."""
    try:
        page.set_clipboard(text)
        return True
    except Exception:
        pass
    try:
        from flet.controls.services.clipboard import Clipboard

        run_task = getattr(page, "run_task", None)
        if callable(run_task):
            run_task(Clipboard().set, text)
            return True
    except Exception:
        pass
    return False


def _pill(text: str) -> ft.Container:
    return ft.Container(
        content=ft.Text(text, size=10.5, color=TEXT_DIM,
                        font_family=FONT_MONO),
        bgcolor=ft.Colors.with_opacity(0.30, SURFACE_HI),
        border=ft.border.Border.all(1, BORDER),
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=9, vertical=4),
    )


def build_crash_dialog(page, *, reason: str, log_text: str,
                       version_label: str = "", log_path: "str | None" = None,
                       show_snack=None, on_close=None) -> ft.AlertDialog:
    """Build (but do not open) the crash report. See ``show_crash_dialog``."""
    log_text = (log_text or "").strip()
    trimmed = False
    if len(log_text) > MAX_LOG_CHARS:
        log_text = log_text[-MAX_LOG_CHARS:]
        trimmed = True
    if not log_text:
        log_text = "The game wrote no output before it closed."

    def _copy(e=None):
        payload = [reason.strip() or "Minecraft crashed"]
        if version_label:
            payload.append(version_label)
        payload.append("")
        payload.append(log_text)
        ok = copy_text(page, "\n".join(payload))
        if callable(show_snack):
            show_snack(
                "Crash log copied - paste it in Discord." if ok else
                "Couldn't copy automatically - select the log text instead.",
                duration=5000)

    def _discord(e=None):
        try:
            if webbrowser.open(DISCORD_INVITE):
                return
        except Exception:
            pass
        if callable(show_snack):
            show_snack(f"Join the Cubeon Discord: {DISCORD_INVITE}",
                       duration=9000)

    def _close(e=None):
        try:
            cubeon_dialogs.close_dialog(page, dlg)
        except Exception:
            pass
        if callable(on_close):
            try:
                on_close()
            except Exception:
                pass

    log_field = ft.TextField(
        value=log_text,
        read_only=True,
        multiline=True,
        min_lines=8,
        max_lines=14,
        text_size=10.5,
        text_style=ft.TextStyle(font_family=FONT_MONO, color=TEXT_DIM),
        color=TEXT_DIM,
        bgcolor=BG,
        border=ft.InputBorder.NONE,
        content_padding=ft.padding.Padding.symmetric(
            horizontal=10, vertical=8),
        # Selection is the manual fallback if the clipboard is unavailable.
        selection_color=ft.Colors.with_opacity(0.35, ACCENT),
    )

    meta_row = ft.Row(
        [_pill(version_label)] if version_label else [],
        spacing=6, wrap=True,
    )

    log_tile = ft.ExpansionTile(
        title=ft.Text("Show log", size=12.5, color=TEXT,
                      weight=ft.FontWeight.W_600),
        subtitle=ft.Text(
            ("Last part of the game log" if not trimmed
             else "Last part of the game log (older lines trimmed)"),
            size=10.5, color=TEXT_FAINT, font_family=FONT_MONO),
        controls=[log_field],
        tile_padding=ft.padding.Padding.symmetric(horizontal=8, vertical=2),
        controls_padding=ft.padding.Padding.only(left=8, right=8, bottom=8),
        affinity=ft.TileAffinity.LEADING,
    )

    footer_bits = []
    if log_path:
        footer_bits.append(
            ft.Text(f"Full log: {log_path}", size=10, color=TEXT_FAINT,
                    font_family=FONT_MONO, max_lines=2,
                    overflow=ft.TextOverflow.ELLIPSIS))
    footer_bits.append(
        ft.Text("No account needed - the log is plain text from your game.",
                size=10, color=TEXT_FAINT))

    content = ft.Container(
        width=620,
        content=ft.Column(
            [
                ft.Text(reason, size=13, color=TEXT, selectable=True),
                ft.Container(height=10),
                meta_row,
                ft.Container(height=6),
                log_tile,
                ft.Container(height=8),
                ft.Column(footer_bits, spacing=3, tight=True),
            ],
            spacing=0, tight=True,
        ),
    )

    dlg = ft.AlertDialog(
        modal=False,
        bgcolor=SURFACE,
        title=ft.Row(
            [
                ft.Icon(ft.Icons.REPORT_PROBLEM_ROUNDED, size=22,
                        color=DANGER),
                ft.Text("Minecraft crashed", size=19, color=TEXT,
                        font_family=FONT_DISPLAY,
                        weight=ft.FontWeight.W_600),
            ],
            spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        content=content,
        actions=[
            ft.TextButton(
                "Copy log", icon=ft.Icons.CONTENT_COPY_ROUNDED,
                on_click=_copy,
                style=ft.ButtonStyle(color=ACCENT, icon_color=ACCENT),
            ),
            ft.TextButton(
                "Get help on Discord", icon=ft.Icons.FORUM_ROUNDED,
                on_click=_discord,
                style=ft.ButtonStyle(color=ACCENT, icon_color=ACCENT),
            ),
            ft.FilledButton(
                "Close",
                on_click=_close,
                style=ft.ButtonStyle(
                    color=ON_ACCENT, bgcolor=ACCENT,
                    shape=ft.RoundedRectangleBorder(radius=RADIUS),
                    padding=ft.padding.Padding.symmetric(
                        horizontal=18, vertical=14),
                ),
            ),
        ],
        actions_alignment=ft.MainAxisAlignment.END,
    )
    return dlg


def show_crash_dialog(page, *, reason: str, log_text: str,
                      version_label: str = "", log_path: "str | None" = None,
                      show_snack=None, on_close=None):
    """Build + mount the crash report. Returns the dialog, or None.

    Safe from any thread: mounting goes through ``cubeon.dialogs``, the same
    idempotent plumbing every other dialog uses, and the whole thing is
    wrapped - a failed report must never take the launcher down.
    """
    try:
        dlg = build_crash_dialog(
            page, reason=reason, log_text=log_text,
            version_label=version_label, log_path=log_path,
            show_snack=show_snack, on_close=on_close)
        cubeon_dialogs.open_dialog(page, dlg)
        return dlg
    except Exception:
        return None
