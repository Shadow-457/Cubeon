"""Worker-thread approval dialogs and background doctor runs for installed content."""
import asyncio
import json
import logging
import threading
import time

import flet as ft
from cubeon import i18n

from . import dialogs, thread_safe_ui
from .theme import ACCENT, DANGER, TEXT, TEXT_DIM

log = logging.getLogger(__name__)


def make_mod_change_approver(page, *, timeout: float = 120):
    existing = getattr(page, "_cubeon_mod_change_approver", None)
    if existing is not None:
        return existing
    prompt_lock = threading.Lock()
    # What the user already said no to (or ignored), and a short quiet period
    # after any "no". A doctor run can propose dozens of changes in a row, and
    # each one used to open its own modal dialog, one after another - a wall of
    # popups that blocked the repair (and the Play button) until every one was
    # answered. One Cancel now settles the rest of that run, and an identical
    # proposal is never shown twice.
    declined = set()
    quiet = {"until": 0.0}
    QUIET_AFTER_NO = 45.0

    def _already_settled(key):
        return key in declined or time.monotonic() < quiet["until"]

    def approve(change):
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            pass
        else:
            return False
        try:
            key = mod_change_key(change)
        except Exception:
            key = None
        if key is not None and _already_settled(key):
            return False
        with prompt_lock:
            # Re-check: this call may have queued behind a prompt the user
            # just cancelled.
            if key is not None and _already_settled(key):
                return False
            answered = threading.Event()
            decision = {"approved": False, "dialog": None}
            replacing = change["action"] == "replace"
            enabling = change["action"] == "enable"
            action = ("Replace build" if replacing
                      else "Enable mod" if enabling else "Disable mods")

            def finish(approved):
                if answered.is_set():
                    return
                decision["approved"] = approved
                answered.set()
                if decision["dialog"] is not None:
                    dialogs.close_dialog(page, decision["dialog"])

            async def show():
                try:
                    if answered.is_set():
                        return
                    rows = [
                        ft.Text(f"{change['loader'].title()} · Minecraft {change['mc_version']}",
                                size=12, color=TEXT_DIM),
                        ft.Text(change["reason"], size=13, color=TEXT),
                    ]
                    for mod in change["mods"]:
                        rows.append(ft.Text(f"{mod['name']}\n{mod['filename']}", size=12, color=TEXT))
                    if change.get("replacement"):
                        rows.append(ft.Text(f"Install: {change['replacement']}", size=12, color=ACCENT))
                    rows.append(ft.Text(
                        ("This turns the disabled file back on; nothing is downloaded. "
                         if enabling else
                         "Old files are kept. You can re-enable them in Mods → Installed. ")
                        + "Keep my mods leaves these files unchanged. Minecraft can still start; "
                        "its loader will check compatibility.",
                        size=12, color=TEXT_DIM))
                    dialog = ft.AlertDialog(
                        modal=True, title=ft.Text("Review mod repair", color=TEXT),
                        content=ft.Container(ft.Column(rows, spacing=12, tight=True,
                                                      scroll=ft.ScrollMode.AUTO), width=470, height=300),
                        actions=[
                            ft.TextButton("Keep my mods", on_click=lambda event: finish(False)),
                            ft.TextButton(action, on_click=lambda event: finish(True),
                                          style=ft.ButtonStyle(color=DANGER)),
                        ],
                        on_dismiss=lambda event: finish(False),
                    )
                    decision["dialog"] = dialog
                    with thread_safe_ui.TREE_LOCK:
                        dialogs.open_dialog(page, dialog)
                except Exception:
                    decision["approved"] = False
                    answered.set()

            async def dismiss():
                if decision["dialog"] is not None:
                    try:
                        dialogs.close_dialog(page, decision["dialog"])
                    except Exception:
                        pass

            def _remember_no():
                if key is not None:
                    declined.add(key)
                quiet["until"] = time.monotonic() + QUIET_AFTER_NO

            try:
                page.run_task(show)
            except Exception:
                return False
            if not answered.wait(timeout):
                answered.set()
                try:
                    page.run_task(dismiss)
                except Exception:
                    pass
                _remember_no()
                return False
            if not decision["approved"]:
                _remember_no()
            return decision["approved"]

    page._cubeon_mod_change_approver = approve
    return approve


def mod_change_key(change):
    return json.dumps({key: change.get(key) for key in (
        "action", "mc_version", "loader", "mods", "replacement", "kept", "files_snapshot",
    )}, sort_keys=True)


def start_doctor_worker(*, mc_version, loader, version_id=None, include=None,
                        check_online=True, status_cb=None, cancel_event=None,
                        on_done=None, approve_all=True, crash_text=None):
    """Run the launcher's doctor on a daemon thread for an explicit action.

    Used by the Settings Doctor section and the crash report's Check & fix.
    The caller owns the controls and renders the finished report in
    ``on_done``. Clicking the action IS the consent for reversible repairs
    (``approve_all``), exactly like Mods -> Installed's Check & repair; pass
    ``approve_all=False`` for a read-only scan.

    Returns the thread, or None when a worker could not start. Never raises.
    """
    def worker():
        report = {}
        try:
            from .doctor import run_doctor
            report = run_doctor(
                mc_version, loader, auto_fix=bool(approve_all),
                check_online=check_online, version_id=version_id,
                include=include, status_cb=status_cb,
                approve_cb=(lambda change: True) if approve_all else None,
                cancel_event=cancel_event, crash_text=crash_text)
        except Exception as error:
            log.warning("background doctor failed", exc_info=True)
            report = {"checked": 0, "problems": [], "fixed": [], "unfixed": [],
                      "sections": {}, "changes": [], "cancelled": False,
                      "summary": f"Could not complete this check: {error}"}
        finally:
            if callable(on_done):
                try:
                    on_done(report)
                except Exception:
                    log.warning("doctor result rendering failed", exc_info=True)

    try:
        thread = threading.Thread(target=worker, name="cubeon-doctor",
                                  daemon=True)
        thread.start()
        return thread
    except Exception:
        log.warning("could not start the doctor worker", exc_info=True)
        return None


def open_crash_check(page, *, mc_version, loader, version_id, diagnose,
                     on_status=None, on_done=None):
    """The Play card's **Fix crash** flow: explain the crash, fix what we can.

    ``diagnose`` is injected by main.py (``cubeon/crash.diagnose_and_fix``);
    this module owns only the small result dialog. Clicking Fix crash is the
    consent for the reversible mod repairs, so there is no second review wall.
    """
    session = {"closed": False, "working": False, "last_status": 0.0}
    status = ft.Text("Reading the latest crash log\u2026", size=13, color=TEXT_DIM)
    cause = ft.Text("", size=14, color=TEXT, weight=ft.FontWeight.W_600)
    advice = ft.Text("", size=12, color=TEXT_DIM, selectable=True)
    spinner = ft.ProgressRing(width=18, height=18, stroke_width=2, color=ACCENT)
    results = ft.ListView(spacing=10, height=260)
    log_path = ft.Text("", size=10, color=TEXT_DIM, font_family="monospace",
                       max_lines=2, overflow=ft.TextOverflow.ELLIPSIS)
    evidence = ft.Text("", size=10.5, color=TEXT_DIM, font_family="monospace",
                       selectable=True)
    dialog = ft.AlertDialog(
        modal=False,
        title=ft.Text(i18n.t("Fix crash"), color=TEXT),
        content=ft.Container(ft.Column([
            ft.Text(f"{loader.title()} \u00b7 Minecraft {mc_version}", size=12,
                    color=TEXT_DIM),
            ft.Row([spinner, status], spacing=10),
            cause, advice, results, log_path,
            ft.ExpansionTile(
                title=ft.Text("Show log", size=12, color=TEXT),
                controls=[ft.Container(evidence, padding=8)],
                visible=False,
            ),
        ], spacing=10, tight=True), width=620),
        actions=[ft.TextButton("Stop"),
                 ft.TextButton("Check again", visible=False)],
    )
    evidence_tile = dialog.content.content.controls[-1]
    close_button, rescan_button = dialog.actions

    def close(event=None):
        session["closed"] = True
        dialogs.close_dialog(page, dialog)

    def dismissed(event=None):
        session["closed"] = True

    def progress(text):
        now = time.monotonic()
        if session["closed"] or now - session["last_status"] < 0.1:
            return
        session["last_status"] = now
        status.value = text
        thread_safe_ui.refresh(status)

    def _row(text, color, icon):
        return ft.Row([
            ft.Icon(icon, size=15, color=color),
            ft.Text(text, size=12, color=color, selectable=True, expand=True),
        ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START)

    def render(result):
        if session["closed"]:
            return
        cause.value = result.get("cause") or "No crash cause identified."
        cause.color = (DANGER if result.get("kind") in ("unknown", "none")
                       else ACCENT)
        advice.value = result.get("advice") or ""
        rows = [_row(item, ACCENT, ft.Icons.CHECK_CIRCLE_ROUNDED)
                for item in result.get("fixed") or []]
        rows.extend(_row(item, DANGER, ft.Icons.ERROR_OUTLINE_ROUNDED)
                    for item in result.get("unfixed") or [])
        if not rows:
            rows.append(ft.Text("Nothing needed changing.", size=12,
                                color=TEXT_DIM))
        results.controls[:] = rows
        path = result.get("log_path")
        log_path.value = f"Log: {path}" if path else ""
        ev = result.get("evidence") or ""
        evidence.value = ev
        evidence_tile.visible = bool(ev)
        spinner.visible = False
        rescan_button.visible = True
        close_button.content = ft.Text(i18n.t("Close"))
        if callable(on_status):
            try:
                on_status(cause.value)
            except Exception:
                pass
        thread_safe_ui.refresh(dialog)

    def run(event=None):
        if session["working"]:
            return
        session["working"] = True
        spinner.visible = True
        rescan_button.visible = False
        close_button.content = ft.Text("Stop")
        status.value = "Reading the latest crash log\u2026"
        thread_safe_ui.refresh(dialog)

        def worker():
            result = {}
            try:
                result = diagnose(mc_version, loader, version_id=version_id,
                                  status_cb=progress) or {}
            except Exception as error:
                result = {"kind": "unknown", "cause": "The crash check failed.",
                          "advice": str(error), "fixed": [], "unfixed": []}
            finally:
                session["working"] = False
                if not session["closed"]:
                    render(result)
                if callable(on_done):
                    try:
                        on_done()
                    except Exception:
                        pass

        threading.Thread(target=worker, name="cubeon-crash-check",
                         daemon=True).start()

    close_button.on_click = close
    rescan_button.on_click = run
    dialog.on_dismiss = dismissed
    dialogs.open_dialog(page, dialog)
    run()
    return dialog


def open_repair_review(page, *, mc_version, loader, version_id, include,
                       run_doctor, on_status, on_done):
    cancelled = threading.Event()
    session = {"closed": False, "working": False, "report": None, "last_status": 0.0,
               "choices": [], "safe_fixed": 0}
    status = ft.Text("Checking installed content…", size=13, color=TEXT_DIM)
    summary = ft.Text("", size=13, color=TEXT)
    spinner = ft.ProgressRing(width=18, height=18, stroke_width=2, color=ACCENT)
    results = ft.ListView(spacing=12, height=330)
    select_all = ft.Checkbox(label="Select all suggested changes", value=True, visible=False)
    apply_button = ft.TextButton("Apply selected changes", disabled=True)
    rescan_button = ft.TextButton("Check again", visible=False)
    close_button = ft.TextButton("Stop")
    dialog = ft.AlertDialog(
        modal=False,
        title=ft.Text(i18n.t("Check & repair"), color=TEXT),
        content=ft.Container(ft.Column([
            ft.Text(f"{loader.title()} · Minecraft {mc_version}", size=12, color=TEXT_DIM),
            ft.Row([spinner, status], spacing=10), summary, select_all, results,
        ], spacing=12, tight=True), width=620),
        actions=[close_button, rescan_button, apply_button],
    )

    def close(event=None):
        cancelled.set()
        session["closed"] = True
        dialogs.close_dialog(page, dialog)

    def dismissed(event=None):
        cancelled.set()
        session["closed"] = True

    def progress(text):
        now = time.monotonic()
        if session["closed"] or now - session["last_status"] < 0.1:
            return
        session["last_status"] = now
        status.value = text
        thread_safe_ui.refresh(status)

    def update_selection(event=None):
        apply_button.disabled = session["working"] or not any(box.value for box, change in session["choices"])
        thread_safe_ui.refresh(apply_button)

    def choose_all(event=None):
        for box, change in session["choices"]:
            box.value = select_all.value
        thread_safe_ui.refresh(results)
        update_selection()

    def render(report):
        from .doctor import format_problem
        if session["closed"]:
            return
        session["report"] = report
        changes = list({mod_change_key(change): change for change in report.get("changes") or []
                        if not change.get("approved")}.values())
        unresolved = report.get("unfixed") or []
        status.value = "Check cancelled; some checks are incomplete." if report.get("cancelled") else "Check complete."
        summary.value = (f"Checked {report.get('checked', 0)} items · "
                         f"{session['safe_fixed']} fixed · {len(unresolved)} need attention")
        session["choices"] = []
        rows = []
        changed_names = set()
        for change in changes:
            names = ", ".join(mod["name"] for mod in change["mods"])
            changed_names.update(mod["name"] for mod in change["mods"])
            label = ("Replace build" if change["action"] == "replace"
                     else "Enable mod" if change["action"] == "enable"
                     else "Disable (keep files)")
            # Pre-selected: opening "Fix problems" is already the user asking
            # for repairs, and every proposed change keeps the old file so it
            # is reversible. A 300-mod profile can produce dozens of safe
            # fixes; making the user tick each one was the main reason the
            # button felt useless. They can still untick anything.
            checkbox = ft.Checkbox(label=f"{label}: {names}", value=True,
                                   active_color=ACCENT, label_style=ft.TextStyle(color=TEXT, size=12),
                                   on_change=update_selection)
            session["choices"].append((checkbox, change))
            details = change["reason"]
            if change.get("replacement"):
                details += f"\nReplacement: {change['replacement']}"
            rows.append(ft.Column([checkbox, ft.Text(details, size=12, color=TEXT_DIM)], spacing=2))
        # Fixed rows keep their reason, so "fixed 3" is never the only trace
        # of what was changed and why.
        for problem in report.get("fixed") or []:
            name = problem.get("item") or problem.get("mod") or "Content"
            if name in changed_names:
                continue
            rows.append(ft.Row([
                ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=14, color=ACCENT),
                ft.Text(format_problem(problem), size=12, color=TEXT_DIM,
                        selectable=True, expand=True),
            ], spacing=6, vertical_alignment=ft.CrossAxisAlignment.START))
        for problem in unresolved:
            name = problem.get("item") or problem.get("mod") or "Content"
            if name in changed_names:
                continue
            rows.append(ft.Column([
                ft.Text(name, size=12, color=TEXT),
                ft.Text(problem.get("detail") or "This needs manual attention.", size=12, color=TEXT_DIM),
            ], spacing=3))
        if not rows:
            rows.append(ft.Text("No unresolved problems found." if not report.get("cancelled")
                                else "Run the check again when you are ready.", color=TEXT_DIM, size=13))
        with thread_safe_ui.TREE_LOCK:
            results.controls[:] = rows
            spinner.visible = False
            select_all.visible = bool(changes)
            select_all.value = bool(changes)
            apply_button.disabled = not bool(changes)
            apply_button.text = (f"Apply all {len(changes)} changes" if changes
                                 else "Apply selected changes")
            rescan_button.visible = True
            close_button.content = ft.Text(i18n.t("Close"))
        on_status(summary.value)
        thread_safe_ui.refresh(dialog)

    def run(allowed=None):
        if session["working"]:
            return
        session["working"] = True
        cancelled.clear()
        spinner.visible = True
        apply_button.disabled = True
        select_all.visible = False
        rescan_button.visible = False
        status.value = "Applying selected changes…" if allowed is not None else "Checking installed content…"
        close_button.content = ft.Text("Stop")
        thread_safe_ui.refresh(dialog)

        def review(change):
            return not cancelled.is_set() and allowed is not None and mod_change_key(change) in allowed

        def worker():
            try:
                report = run_doctor(mc_version, loader, auto_fix=True, check_online=True,
                                    version_id=version_id, include=include, status_cb=progress,
                                    approve_cb=review, cancel_event=cancelled)
                session["safe_fixed"] += len(report.get("fixed") or [])
                session["working"] = False
                render(report)
            except Exception as error:
                session["working"] = False
                if not session["closed"]:
                    status.value = f"Could not complete this check: {error}"
                    spinner.visible = False
                    close_button.content = ft.Text(i18n.t("Close"))
                    thread_safe_ui.refresh(dialog)
            finally:
                on_done()

        threading.Thread(target=worker, name="cubeon-repair-review", daemon=True).start()

    def apply(event=None):
        allowed = {mod_change_key(change) for box, change in session["choices"] if box.value}
        if allowed:
            run(allowed)

    select_all.on_change = choose_all
    apply_button.on_click = apply
    rescan_button.on_click = lambda event: run()
    close_button.on_click = close
    dialog.on_dismiss = dismissed
    dialogs.open_dialog(page, dialog)
    run()
    return dialog
