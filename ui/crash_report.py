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
* **Check & fix**, which runs the launcher's own Doctor on the instance that
  crashed and shows every error + action inline;
* a direct invite button to the Cubeon Discord, which is where support
  actually happens.

The dialog never raises: a crash path must not be able to break the launcher.
It is also non-modal on purpose - the user can still switch tabs while it is
open, and Close only dismisses the report.
"""
from __future__ import annotations

import threading
import webbrowser

import flet as ft
from cubeon import i18n

from cubeon import dialogs as cubeon_dialogs
from cubeon import thread_safe_ui
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
                       show_snack=None, on_close=None,
                       mc_version: "str | None" = None,
                       loader: "str | None" = None,
                       version_id: "str | None" = None) -> ft.AlertDialog:
    """Build (but do not open) the crash report. See ``show_crash_dialog``.

    ``mc_version``/``loader``/``version_id`` identify the instance that just
    crashed; when they are known the dialog can run the launcher's own Doctor
    in place and report *why* each fix was applied, without leaving the report.
    """
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

    def _doctor(e=None):
        from cubeon.webdoctor import open_doctor
        if not open_doctor(log_text, reason=reason, version_label=version_label):
            if callable(show_snack):
                show_snack("Couldn't open Doctor. Visit www.ylet.online/doctor "
                           "and use Copy log to paste this report.", duration=8000)

    # --- local Doctor (same sections as Settings) ---------------------------
    # The website Doctor reads the log; this one looks at the INSTALLATION that
    # just failed (corrupt jars, bad RAM, missing dependencies...) and can fix
    # it in place. Both are offered: the log tells you what happened, the local
    # check is what can actually change the files for the next launch.
    doctor_status = ft.Text("", size=11.5, color=TEXT_DIM, visible=False,
                            selectable=True, data="crash-doctor-status")
    doctor_spinner = ft.ProgressRing(width=13, height=13, stroke_width=2,
                                     color=ACCENT, visible=False)
    doctor_results = ft.ListView(spacing=6, padding=0, height=210)
    doctor_results_host = ft.Container(
        content=doctor_results, visible=False,
        border=ft.border.Border.all(1, BORDER), border_radius=RADIUS,
        bgcolor=BG, padding=ft.padding.Padding.symmetric(horizontal=10,
                                                          vertical=8),
        data="crash-doctor-results",
    )
    doctor_lock = threading.Lock()

    def _doctor_row(entry):
        from cubeon.doctor import format_problem
        if entry.get("fixed"):
            icon, color = ft.Icons.CHECK_CIRCLE_ROUNDED, ACCENT
        elif entry.get("kind") == "section-failed":
            icon, color = ft.Icons.ERROR_OUTLINE_ROUNDED, DANGER
        else:
            icon, color = ft.Icons.WARNING_AMBER_ROUNDED, TEXT_DIM
        return ft.Row(
            [ft.Icon(icon, size=14, color=color),
             ft.Text(format_problem(entry), size=11.5, selectable=True,
                     color=TEXT if entry.get("fixed") else TEXT_DIM,
                     expand=True)],
            spacing=6, vertical_alignment=ft.CrossAxisAlignment.START)

    def _render_report(report):
        with thread_safe_ui.TREE_LOCK:
            doctor_results.controls[:] = [
                _doctor_row(entry)
                for entry in (list(report.get("fixed") or [])
                              + list(report.get("unfixed") or []))]
            doctor_results_host.visible = bool(doctor_results.controls)
            doctor_status.value = report.get("summary") or ""
            doctor_status.visible = bool(doctor_status.value)
            thread_safe_ui.refresh(doctor_results)
            thread_safe_ui.refresh(doctor_results_host)
            thread_safe_ui.refresh(doctor_status)

    def _run_local_doctor(e=None):
        if not doctor_lock.acquire(blocking=False):
            return
        with thread_safe_ui.TREE_LOCK:
            local_doctor_btn.disabled = True
            doctor_spinner.visible = True
            doctor_status.value = "Checking for problems…"
            doctor_status.visible = True
            thread_safe_ui.refresh(local_doctor_btn)
            thread_safe_ui.refresh(doctor_spinner)
            thread_safe_ui.refresh(doctor_status)

        def done(report):
            try:
                _render_report(report)
            except Exception:
                pass
            finally:
                doctor_lock.release()
                with thread_safe_ui.TREE_LOCK:
                    local_doctor_btn.disabled = False
                    doctor_spinner.visible = False
                    thread_safe_ui.refresh(local_doctor_btn)
                    thread_safe_ui.refresh(doctor_spinner)

        from cubeon.doctor_ui import start_doctor_worker
        started = start_doctor_worker(
            mc_version=mc_version, loader=loader or "vanilla",
            version_id=version_id, include=None, check_online=True,
            on_done=done, approve_all=True, crash_text=log_text)
        if started is None:
            doctor_lock.release()
            with thread_safe_ui.TREE_LOCK:
                local_doctor_btn.disabled = False
                doctor_spinner.visible = False
                doctor_status.value = "Couldn't start the check - see the log."
                thread_safe_ui.refresh(local_doctor_btn)
                thread_safe_ui.refresh(doctor_spinner)
                thread_safe_ui.refresh(doctor_status)

    local_doctor_available = bool(mc_version and version_id)
    local_doctor_btn = ft.TextButton(
        "Check & fix", icon=ft.Icons.BUILD_CIRCLE_ROUNDED,
        on_click=_run_local_doctor, data="crash-local-doctor",
        disabled=not local_doctor_available,
        tooltip=("Run the launcher's Doctor on this instance. It reports why "
                 "each problem happened and fixes what is safe to fix; "
                 "disabled files are kept."
                 if local_doctor_available else
                 "Cubeon couldn't tell which instance crashed, so the local "
                 "check has nothing to inspect."),
        style=ft.ButtonStyle(color=ACCENT, icon_color=ACCENT),
    )

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
                ft.Row(
                    [doctor_spinner, ft.Container(content=doctor_status,
                                                  expand=True)],
                    spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER),
                doctor_results_host,
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
            local_doctor_btn,
            ft.TextButton(
                i18n.t("Doctor"), icon=ft.Icons.MEDICAL_SERVICES_ROUNDED,
                on_click=_doctor, data="crash-web-doctor",
                tooltip="Open the website Doctor with a redacted log excerpt. "
                        "AI analysis shares that excerpt with Kilo.",
                style=ft.ButtonStyle(color=ACCENT, icon_color=ACCENT),
            ),
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
                      show_snack=None, on_close=None,
                      mc_version: "str | None" = None,
                      loader: "str | None" = None,
                      version_id: "str | None" = None):
    """Build + mount the crash report. Returns the dialog, or None.

    Safe from any thread: mounting goes through ``cubeon.dialogs``, the same
    idempotent plumbing every other dialog uses, and the whole thing is
    wrapped - a failed report must never take the launcher down.
    """
    try:
        dlg = build_crash_dialog(
            page, reason=reason, log_text=log_text,
            version_label=version_label, log_path=log_path,
            show_snack=show_snack, on_close=on_close,
            mc_version=mc_version, loader=loader, version_id=version_id)
        cubeon_dialogs.open_dialog(page, dlg)
        return dlg
    except Exception:
        return None
