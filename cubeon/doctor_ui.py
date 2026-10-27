"""Worker-thread approval dialogs for changes to installed mods."""
import asyncio
import json
import threading
import time

import flet as ft

from . import dialogs, thread_safe_ui
from .theme import ACCENT, DANGER, TEXT, TEXT_DIM


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
            action = "Replace build" if replacing else "Disable mods"

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
                        "Old files are kept. You can re-enable them in Mods → Installed. "
                        "Keep my mods leaves these files unchanged. Minecraft can still start; "
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


def open_crash_review(page, *, mc_version, loader, version_id,
                      repair_crash, run_doctor, include=("mods",),
                      on_status=None, on_done=None):
    """The Play card's **Fix crash** flow: read the crash log, repair it.

    Unlike the general repair review, this is a one-click action: the user
    already told us the game crashed, so the fixes that are safe and
    reversible are applied without a second wall of checkboxes. Every change
    is still listed, and old mod jars are renamed rather than deleted.

    The flow is deliberately two-stage:

    1. ``repair_crash`` diagnoses the newest crash log and applies the fix it
       proves (RAM, Java, JVM flags, corrupt jar, or a dependency/conflict
       pass).
    2. If that pass did not already run the mod doctor, ``run_doctor`` does a
       dependency/conflict pass so a crash caused by a mod set that the log
       only hinted at still gets cleaned up.

    Both callbacks are injected by ``main.py``; this module owns only the UI.
    """
    cancelled = threading.Event()
    session = {"closed": False, "working": False, "last_status": 0.0}
    status = ft.Text("Reading the latest crash log…", size=13, color=TEXT_DIM)
    summary = ft.Text("", size=13, color=TEXT)
    cause = ft.Text("", size=14, color=TEXT, weight=ft.FontWeight.W_600)
    evidence = ft.Text("", size=11, color=TEXT_DIM, font_family="monospace",
                       selectable=True)
    spinner = ft.ProgressRing(width=18, height=18, stroke_width=2, color=ACCENT)
    results = ft.ListView(spacing=10, height=330)
    close_button = ft.TextButton("Stop")
    rescan_button = ft.TextButton("Check again", visible=False)
    dialog = ft.AlertDialog(
        modal=False,
        title=ft.Text("Fix crash", color=TEXT),
        content=ft.Container(ft.Column([
            ft.Text(f"{loader.title()} · Minecraft {mc_version}", size=12,
                    color=TEXT_DIM),
            ft.Row([spinner, status], spacing=10),
            cause, summary, results,
            ft.ExpansionTile(
                title=ft.Text("What the log said", size=12, color=TEXT),
                controls=[ft.Container(evidence, padding=8)],
                visible=False,
            ),
        ], spacing=10, tight=True), width=640),
        actions=[close_button, rescan_button],
    )
    evidence_tile = dialog.content.content.controls[-1]

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

    def _row(title, detail, color=TEXT, icon=None):
        controls = []
        if icon is not None:
            controls.append(ft.Icon(icon, size=15, color=color))
        controls.append(ft.Text(title, size=12.5, color=color,
                                weight=ft.FontWeight.W_600))
        return ft.Column([
            ft.Row(controls, spacing=6, tight=True),
            ft.Text(detail, size=12, color=TEXT_DIM, selectable=True),
        ], spacing=2)

    def render(crash, report):
        if session["closed"]:
            return
        recognised = bool((crash or {}).get("recognised"))
        cause.value = (crash or {}).get("cause") or "No crash cause identified."
        cause.color = ACCENT if recognised else DANGER
        confidence = float((crash or {}).get("confidence") or 0.0)
        summary.value = (f"Identified with {int(round(confidence * 100))}% "
                         f"confidence · {len((crash or {}).get('fixed') or [])} fix(es) applied")
        if not recognised:
            summary.value = "Couldn't identify this crash from the log"
        rows = []
        for item in (crash or {}).get("fixed") or []:
            rows.append(_row("Fixed", item, ACCENT, ft.Icons.CHECK_CIRCLE_ROUNDED))
        for item in (crash or {}).get("unfixed") or []:
            rows.append(_row("Needs attention", item, DANGER,
                             ft.Icons.ERROR_OUTLINE_ROUNDED))
        for problem in (report or {}).get("fixed") or []:
            label = problem.get("mod") or problem.get("item") or "Mod"
            detail = problem.get("fix") or problem.get("detail") or "fixed"
            rows.append(_row(f"Fixed: {label}", detail, ACCENT,
                             ft.Icons.CHECK_CIRCLE_ROUNDED))
        for problem in (report or {}).get("unfixed") or []:
            if problem.get("kind") == "verification-unavailable":
                continue
            label = problem.get("mod") or problem.get("item") or "Mod"
            detail = problem.get("detail") or "needs attention"
            rows.append(_row(f"Needs attention: {label}", detail, DANGER,
                             ft.Icons.ERROR_OUTLINE_ROUNDED))
        if not rows:
            rows.append(ft.Text(
                "No repairs were needed, or nothing could be fixed from this "
                "log. The evidence below is what Minecraft reported.",
                size=12, color=TEXT_DIM))
        log_path = (crash or {}).get("log_path")
        if log_path:
            rows.append(ft.Text(f"Log: {log_path}", size=10, color=TEXT_DIM,
                                font_family="monospace", max_lines=2,
                                overflow=ft.TextOverflow.ELLIPSIS))
        ev = (crash or {}).get("evidence") or ""
        evidence.value = ev or "No log lines were captured."
        evidence_tile.visible = bool(ev)
        with thread_safe_ui.TREE_LOCK:
            results.controls[:] = rows
            spinner.visible = False
            rescan_button.visible = True
            close_button.content = ft.Text("Close")
        if callable(on_status):
            try:
                on_status(summary.value)
            except Exception:
                pass
        thread_safe_ui.refresh(dialog)

    def run(event=None):
        if session["working"]:
            return
        session["working"] = True
        cancelled.clear()
        spinner.visible = True
        rescan_button.visible = False
        close_button.content = ft.Text("Stop")
        status.value = "Reading the latest crash log…"
        thread_safe_ui.refresh(dialog)

        def worker():
            crash = {}
            report = None
            try:
                crash = repair_crash(
                    mc_version, loader, version_id=version_id,
                    status_cb=progress) or {}
                # Only fall back to the dependency/conflict pass when the crash
                # could plausibly be a mod-set problem. Running it after an
                # OutOfMemoryError or a bad JVM option would add a long scan
                # that cannot help - and could change mods the log never
                # implicated.
                signature = crash.get("signature")
                mod_related = signature in (
                    "unknown", "duplicate-mods", "missing-dependency",
                    "incompatible-mods", "mod-conflict", "corrupt-jar")
                if (not crash.get("report") and run_doctor is not None
                        and mod_related):
                    progress("Checking mod dependencies and conflicts…")
                    report = run_doctor(
                        mc_version, loader, auto_fix=True, check_online=True,
                        version_id=version_id, include=include,
                        status_cb=progress,
                        approve_cb=lambda change: not cancelled.is_set(),
                        cancel_event=cancelled)
            except Exception as error:
                crash.setdefault("unfixed", []).append(
                    f"the crash check failed: {error}")
            finally:
                session["working"] = False
                if not session["closed"]:
                    render(crash, report)
                if callable(on_done):
                    try:
                        on_done()
                    except Exception:
                        pass

        threading.Thread(target=worker, name="cubeon-crash-review",
                         daemon=True).start()

    rescan_button.on_click = run
    close_button.on_click = close
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
        title=ft.Text("Check & repair", color=TEXT),
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
            label = "Replace build" if change["action"] == "replace" else "Disable (keep files)"
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
            close_button.content = ft.Text("Close")
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
                    close_button.content = ft.Text("Close")
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
