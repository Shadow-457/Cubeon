"""Compatibility results with explicit resolution or reversible per-mod disabling."""
import logging
import threading

import flet as ft

from cubeon import dialogs, i18n, thread_safe_ui
from cubeon.content_checks import check_content, disable_problem_mod, is_missing_dependency
from cubeon.theme import THEME, RADIUS, ON_ACCENT
from ui.install_feedback import any_busy


def show_content_issues(page, state, target, report, *, on_done=None, on_status=None, runtime_versions=None):
    palette = THEME
    result_rows = ft.Column(spacing=12, scroll=ft.ScrollMode.AUTO)
    status = ft.Text("", size=12, color=palette["TEXT_DIM"], selectable=True)
    action = ft.FilledButton(content=i18n.t("Resolve"), data="content-resolve")
    close = ft.TextButton(content=i18n.t("Close"), data="content-check-close")
    busy = {"value": False}
    action_label = {"value": i18n.t("Resolve")}
    busy_label = ft.Text(i18n.t("Resolving…"), color=ON_ACCENT)
    busy_content = ft.Row([
        ft.ProgressRing(width=16, height=16, stroke_width=2, color=ON_ACCENT,
                        data="content-resolve-progress"),
        busy_label], spacing=8, tight=True, alignment=ft.MainAxisAlignment.CENTER)
    disable_buttons = []
    lock = threading.Lock()

    def sync_actions():
        action.content = busy_content if busy["value"] else action_label["value"]
        action.disabled = close.disabled = busy["value"]
        for button in disable_buttons:
            button.disabled = busy["value"]
            thread_safe_ui.refresh(button)
        thread_safe_ui.refresh(action)
        thread_safe_ui.refresh(close)

    def paint(current):
        problems = current.get("unfixed") or []
        missing = [problem for problem in problems if is_missing_dependency(problem)]
        others = [problem for problem in problems if not is_missing_dependency(problem)]
        result_rows.controls = []
        disable_buttons.clear()
        for title, entries in (("Missing dependencies", missing), ("Conflicts & compatibility", others)):
            if entries:
                result_rows.controls.append(ft.Text(i18n.t(title), color=palette["TEXT"],
                    size=14, weight=ft.FontWeight.W_600))
                for problem in entries:
                    controls = []
                    options = (problem.get('disable_options') or []) if target[0] == 'mod' else []
                    for option in options:
                        label = option['filename'] if problem.get('kind') == 'duplicate' else option['name']
                        button = ft.TextButton(content=i18n.t('Disable mod') if len(options) == 1
                                               else f"Disable {label}",
                            icon=ft.Icons.POWER_SETTINGS_NEW_ROUNDED,
                            tooltip=f"Disable {option['name']} ({option['filename']}) in this instance only. "
                                    "Keeps the JAR; re-enable it in Mods → Installed.",
                            data='content-disable-' + option['filename'], disabled=busy['value'],
                            on_click=lambda event, selected=option: apply(event, disable_option=selected),
                            style=ft.ButtonStyle(color=palette['ACCENT']))
                        disable_buttons.append(button)
                        controls.append(button)
                    result_rows.controls.append(ft.Container(
                        content=ft.Column([
                            ft.Text(problem.get("detail") or problem.get("mod") or problem.get("item") or "Unknown issue",
                                    color=palette["TEXT"], size=12.5, selectable=True),
                            *([ft.Text(problem["error"], color=palette["TEXT_DIM"], size=11.5, selectable=True)]
                              if problem.get("error") and current.get("attempted") else []),
                            *([ft.Row(controls, wrap=True)] if controls else [])], spacing=4),
                        padding=12, border_radius=RADIUS, bgcolor=palette["SURFACE_HI"]))
        action_label["value"] = i18n.t("Install & resolve" if missing and others else "Install" if missing else "Resolve")
        action.visible = bool(problems)
        if not problems:
            status.value = i18n.t("Mod dependencies checked. Runtime will be verified on Play."
                                 if current.get("runtime_unverified") else "Everything is compatible. You can press Play.")
        thread_safe_ui.refresh(result_rows)
        sync_actions()
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

    def apply(event=None, *, disable_option=None):
        with thread_safe_ui.TREE_LOCK:
            if busy["value"] or not lock.acquire(blocking=False):
                return
            from cubeon import storage
            if storage.blocked() or any_busy() or any(state.get(key) for key in ("running_version", "installing_version", "launching_version", "fixing_mods")):
                lock.release()
                update_status("Close the game and finish installs before changing mods.")
                return
            busy["value"] = True
            busy_label.value = i18n.t("Disabling…" if disable_option else "Resolving…")
            state["fixing_mods"] = target[3]
            sync_actions()

        def worker():
            current = None
            try:
                if disable_option:
                    current = disable_problem_mod(target, disable_option, runtime_versions=runtime_versions)
                else:
                    resolved = check_content(target, resolve=True, status_cb=update_status, runtime_versions=runtime_versions)
                    current = dict(check_content(target, runtime_versions=runtime_versions), fixed=resolved.get("fixed") or [], attempted=True)
                    if resolved.get("unfixed"):
                        current["unfixed"] = resolved["unfixed"]
                with thread_safe_ui.TREE_LOCK:
                    paint(current)
                    if disable_option:
                        update_status(f"Disabled {disable_option['name']}. " +
                                      ("Other issues remain; review the list above." if current.get('unfixed')
                                       else "Rechecked locally. Re-enable it in Mods → Installed."))
                    elif current.get("unfixed"):
                        update_status("Some issues remain. Disable an affected mod above, or try Resolve again.")
            except Exception as error:
                logging.getLogger(__name__).warning("content resolution failed", exc_info=True)
                update_status(f"Could not complete this check: {error}")
            finally:
                with thread_safe_ui.TREE_LOCK:
                    if state.get("fixing_mods") == target[3]:
                        state["fixing_mods"] = None
                    busy["value"] = False
                    sync_actions()
                lock.release()
            if current is not None and on_done:
                on_done(current)

        try:
            update_status(f"Disabling {disable_option['name']}…" if disable_option else "Finding a compatible set…")
            threading.Thread(target=worker, daemon=True).start()
        except Exception as error:
            with thread_safe_ui.TREE_LOCK:
                state["fixing_mods"] = None
                busy["value"] = False
                sync_actions()
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
            ft.Text("Nothing changes until you choose an action. Resolve looks for compatible replacements and dependencies. Disable mod keeps its JAR without downloading anything; re-enable it in Mods → Installed."
                    if target[0] == 'mod' else
                    "Nothing changes until you click the action below. It finds a compatible set for all listed issues; replaced files are kept as backups.",
                    color=palette["TEXT_DIM"], size=12),
            ft.Container(content=result_rows, height=min(360, max(140, len(report.get("unfixed") or []) * 120))),
            status], spacing=12, tight=True)), actions=[close, action])
    with thread_safe_ui.TREE_LOCK:
        paint(report)
        dialogs.open_dialog(page, dialog)
    return dialog
