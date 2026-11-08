"""Named compatibility results with one explicit, reversible resolution action."""
import logging
import threading

import flet as ft

from cubeon import dialogs, i18n, thread_safe_ui
from cubeon.content_checks import check_content, is_missing_dependency
from cubeon.theme import THEME, RADIUS, ON_ACCENT


def show_content_issues(page, state, target, report, *, on_done=None, on_status=None, runtime_versions=None):
    palette = THEME
    result_rows = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO)
    status = ft.Text("", size=12, color=palette["TEXT_DIM"], selectable=True)
    action = ft.FilledButton(content=i18n.t("Resolve"), data="content-resolve")
    close = ft.TextButton(content=i18n.t("Close"), data="content-check-close")
    busy = {"value": False}
    lock = threading.Lock()

    def paint(current):
        problems = current.get("unfixed") or []
        missing = [problem for problem in problems if is_missing_dependency(problem)]
        others = [problem for problem in problems if not is_missing_dependency(problem)]
        result_rows.controls = []
        for title, entries in (("Missing dependencies", missing), ("Conflicts & compatibility", others)):
            if entries:
                result_rows.controls.append(ft.Text(i18n.t(title), color=palette["TEXT"],
                    size=14, weight=ft.FontWeight.W_600))
                for problem in entries:
                    result_rows.controls.append(ft.Container(
                        content=ft.Column([
                            ft.Text(problem.get("detail") or problem.get("mod") or problem.get("item") or "Unknown issue",
                                    color=palette["TEXT"], size=12.5, selectable=True),
                            *([ft.Text(problem["error"], color=palette["TEXT_DIM"], size=11.5, selectable=True)]
                              if problem.get("error") and current.get("attempted") else [])], spacing=4),
                        padding=12, border_radius=RADIUS, bgcolor=palette["SURFACE_HI"]))
        action.content = i18n.t("Install & resolve" if missing and others else "Install" if missing else "Resolve")
        action.visible = bool(problems)
        if not problems:
            status.value = i18n.t("Mod dependencies checked. Runtime will be verified on Play."
                                 if current.get("runtime_unverified") else "Everything is compatible. You can press Play.")
        thread_safe_ui.refresh(result_rows)
        thread_safe_ui.refresh(action)
        thread_safe_ui.refresh(status)

    def dismiss(event=None):
        if not busy["value"]:
            dialogs.close_dialog(page, dialog)

    def update_status(text):
        with thread_safe_ui.TREE_LOCK:
            status.value = str(text)
            thread_safe_ui.refresh(status)
        if on_status:
            on_status(text)

    def apply(event=None):
        with thread_safe_ui.TREE_LOCK:
            if busy["value"] or not lock.acquire(blocking=False):
                return
            if any(state.get(key) for key in ("running_version", "installing_version", "launching_version", "fixing_mods", "updating_launcher")):
                lock.release()
                update_status("Close the game and finish installs before changing mods.")
                return
            busy["value"] = True
            state["fixing_mods"] = target[3]
            action.disabled = True
            close.disabled = True
            thread_safe_ui.refresh(action)
            thread_safe_ui.refresh(close)
        update_status("Finding a compatible set…")

        def worker():
            current = None
            try:
                resolved = check_content(target, resolve=True, status_cb=update_status, runtime_versions=runtime_versions)
                current = dict(check_content(target, runtime_versions=runtime_versions), fixed=resolved.get("fixed") or [], attempted=True)
                if resolved.get("unfixed"):
                    current["unfixed"] = resolved["unfixed"]
                with thread_safe_ui.TREE_LOCK:
                    paint(current)
                    if current.get("unfixed"):
                        update_status("Some issues remain. Review the details and try again.")
            except Exception as error:
                logging.getLogger(__name__).warning("content resolution failed", exc_info=True)
                update_status(f"Could not complete this check: {error}")
            finally:
                with thread_safe_ui.TREE_LOCK:
                    if state.get("fixing_mods") == target[3]:
                        state["fixing_mods"] = None
                    busy["value"] = False
                    action.disabled = False
                    close.disabled = False
                    thread_safe_ui.refresh(action)
                    thread_safe_ui.refresh(close)
                lock.release()
            if current is not None and on_done:
                on_done(current)

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as error:
            with thread_safe_ui.TREE_LOCK:
                state["fixing_mods"] = None
                busy["value"] = False
                action.disabled = close.disabled = False
                thread_safe_ui.refresh(action)
                thread_safe_ui.refresh(close)
            lock.release()
            update_status(f"Could not start this check: {error}")

    action.on_click = apply
    action.style = ft.ButtonStyle(bgcolor=palette["ACCENT"], color=ON_ACCENT)
    close.on_click = dismiss
    dialog = ft.AlertDialog(
        modal=True, bgcolor=palette["SURFACE"], data="content-compatibility-results",
        title=ft.Text(i18n.t("Compatibility check"), color=palette["TEXT"], size=20),
        content=ft.Container(width=640, content=ft.Column([
            ft.Text(f"{target[1]} · {(target[2] or 'vanilla').title()} · {target[3]}",
                    color=palette["TEXT_DIM"], size=11.5),
            ft.Text("Nothing changes until you click the action below. It finds a compatible set for all listed issues; replaced mods are kept as backups.",
                    color=palette["TEXT_DIM"], size=12),
            ft.Container(content=result_rows, height=min(360, max(100, len(report.get("unfixed") or []) * 85))),
            status], spacing=12, tight=True)), actions=[close, action])
    with thread_safe_ui.TREE_LOCK:
        paint(report)
        dialogs.open_dialog(page, dialog)
    return dialog
