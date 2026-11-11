"""Explicit, cancellable Java verification using the same setup path as Play."""
import logging
import threading

import flet as ft

from cubeon import i18n, instances, jre, status_text, storage, theme, thread_safe_ui, versions

log = logging.getLogger(__name__)


def build_java_runtime_pane(page, *, cfg, launcher_state, get_version, get_java_path,
                            on_ready=None, on_busy_change=None):
    model = JavaRuntimePane(page, launcher_state, get_version, get_java_path,
                            on_ready, on_busy_change)
    return model.view


class JavaRuntimePane:
    def __init__(self, page, state, get_version, get_java_path, on_ready, on_busy_change):
        self.page, self.state = page, state
        self.get_version, self.get_java_path = get_version, get_java_path
        self.on_ready, self.on_busy_change = on_ready, on_busy_change
        self.busy = False
        self.cancel_event = threading.Event()
        self.check = ft.FilledButton(i18n.t("Check & repair Java"), on_click=self._start,
                                     data="java-runtime-check")
        self.cancel = ft.TextButton(i18n.t("Cancel"), on_click=self._cancel, visible=False,
                                    disabled=True, data="java-runtime-cancel")
        self.spinner = ft.ProgressRing(width=16, height=16, stroke_width=2,
                                       visible=False, color=theme.ACCENT)
        self.progress = ft.ProgressBar(value=None, visible=False, color=theme.ACCENT,
                                       data="java-runtime-progress")
        self.status = ft.Text(i18n.t("Checks Java for the selected instance. Downloads a verified runtime if needed."),
                              size=12, color=theme.TEXT_DIM, selectable=True,
                              data="java-runtime-status")
        self.view = ft.Column([
            ft.Row([self.check, self.spinner, self.cancel], wrap=True, spacing=10),
            self.status, self.progress,
        ], spacing=8, tight=True, data="java-runtime-pane")
        self.view.java_runtime_model = self

    def _paint(self):
        self.check.content = (i18n.t("Cancelling…") if self.busy and self.cancel_event.is_set()
                              else i18n.t("Checking Java…") if self.busy
                              else i18n.t("Check & repair Java"))
        self.check.disabled = self.busy
        self.cancel.visible = self.spinner.visible = self.progress.visible = self.busy
        self.cancel.disabled = not self.busy or self.cancel_event.is_set()
        try:
            thread_safe_ui.refresh(self.view)
        except Exception:
            log.exception("Couldn't repaint Java setup controls")

    def _busy_changed(self):
        if self.on_busy_change:
            try:
                self.on_busy_change()
            except Exception:
                log.exception("Couldn't refresh Java setup availability")

    def _check_cancel(self):
        if self.cancel_event.is_set():
            raise InterruptedError()

    def _status(self, text):
        self._check_cancel()
        with thread_safe_ui.TREE_LOCK:
            self._check_cancel()
            self.status.value = i18n.t(status_text.human(text))
            self.status.color = theme.TEXT_DIM
            self._paint()

    def _progress(self, done, total):
        self._check_cancel()
        with thread_safe_ui.TREE_LOCK:
            self._check_cancel()
            self.progress.value = min(1, max(0, done / total)) if total else None
            self._paint()

    def _cancel(self, _event=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if not self.busy or self.cancel_event.is_set():
                return
            self.cancel_event.set()
            self.status.value = i18n.t("Cancelling Java setup…")
            self._paint()

    def _finish(self, text, *, failed=False, path=None):
        with thread_safe_ui.TREE_LOCK:
            if self.busy and self.cancel_event.is_set():
                text = i18n.t("Java setup cancelled. You can check again.")
                failed, path = False, None
            self.status.value = text
            self.status.color = theme.DANGER if failed else theme.TEXT_DIM
            self.busy = False
            self.state["java_runtime_busy"] = False
            self._busy_changed()
            if path and self.on_ready:
                try:
                    self.on_ready(path)
                except Exception:
                    log.exception("Couldn't refresh the verified Java label")
            self._paint()

    def _start(self, _event=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if self.busy or self.state.get("java_runtime_busy"):
                return
            try:
                version_id = self.get_version()
                java_path = (self.get_java_path() or "").strip() or None
                if not version_id:
                    self.status.value = i18n.t("Select an instance on Play first.")
                    self._paint()
                    return
                # Play claims this same tree lock. Check before our own claim;
                # application_busy also covers recovered games and live servers.
                if storage.application_busy(self.state):
                    self.status.value = i18n.t("Close Minecraft and servers, and wait for installations or file organization to finish first.")
                    self._paint()
                    return
            except Exception:
                log.exception("Couldn't check Java setup availability")
                self.status.value = i18n.t("Couldn't check whether Java setup is available. Try again.")
                self.status.color = theme.DANGER
                self._paint()
                return
            self.busy = True
            self.state["java_runtime_busy"] = True
            self.cancel_event.clear()
            self.progress.value = None
            self.status.value = i18n.t("Checking Java…")
            self.status.color = theme.TEXT_DIM
            self._busy_changed()
            self._paint()

        def work():
            message = i18n.t("Couldn't prepare Java. Try again.")
            failed = True
            path = None
            try:
                self._check_cancel()
                info = instances.describe(version_id, with_mods=False)
                if info.get("engine") == "rust" or info.get("loader") == "rust":
                    self._check_cancel()
                    message = i18n.t("The Rust client does not use Java. Select a Java Minecraft instance on Play.")
                    failed = False
                    return
                mc_version = versions.resolve_mc_version(version_id)
                java_version = (mc_version + "-forge" if mc_version == "1.8.9"
                                and info.get("loader") == "forge" else mc_version)
                self._check_cancel()
                path = jre.ensure_java_for_version(java_version, java_path,
                    status_cb=self._status, progress_cb=self._progress,
                    cancel_check=self._check_cancel)
                self._check_cancel()
                if not path:
                    raise jre.JreError(i18n.t("No verified Java runtime was returned."))
                message = i18n.t("Java verified and ready for {version}.").format(version=mc_version)
                failed = False
            except Exception as error:
                path = None
                if self.cancel_event.is_set():
                    message = i18n.t("Java setup cancelled. You can check again.")
                    failed = False
                else:
                    log.exception("Java verification/setup failed")
                    message = i18n.t("Couldn't prepare Java. {error} Try again.").format(
                        error=status_text.human(error)[:220])
            finally:
                self._finish(message, failed=failed, path=path)

        try:
            threading.Thread(target=work, name="cubeon-java-repair", daemon=True).start()
        except Exception:
            log.exception("Couldn't start Java verification")
            self._finish(i18n.t("Couldn't start checking Java. Try again."), failed=True)
