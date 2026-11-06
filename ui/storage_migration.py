"""One-time, recoverable Minecraft storage migration and restart UI."""
import threading
import time

import flet as ft

from cubeon import dialogs, storage, storage_layout, theme, thread_safe_ui


class StorageMigration:
    def __init__(self, page, *, busy, restart, exit_launcher, set_locked=lambda _: None, instance_labels=None):
        self.page, self.busy = page, busy
        self.restart, self.exit_launcher = restart, exit_launcher
        self.set_locked = set_locked
        self.instance_labels = dict(instance_labels or {})
        self.phase = "offered"
        self.cancel = threading.Event()
        self.scan_cancel = threading.Event()
        self.plan = None
        self._last_progress = 0
        self.status = ft.Text("Keep everything together in Instances, with readable folder names. "
                              "Worlds and settings stay with their own instance. "
                              "Old global content moves into one recovery folder. "
                              "Restart Cubeon when finished.",
                              size=13, color=theme.TEXT)
        self.detail = ft.Text("", size=12, color=theme.TEXT_DIM)
        self.progress = ft.ProgressBar(value=0, visible=False)
        self.later = ft.TextButton("Later", on_click=self._later)
        self.start = ft.FilledButton("Migrate now", on_click=self._start, disabled=True)
        self.pause = ft.TextButton("Pause", on_click=lambda _: self.cancel.set(), visible=False)
        self.restart_button = ft.FilledButton("Restart Launcher", on_click=restart, visible=False)
        self.exit_button = ft.TextButton("Exit", on_click=exit_launcher, visible=False)
        self.dialog = ft.AlertDialog(
            modal=True, title=ft.Text("Organize Minecraft files"),
            content=ft.Container(width=460, content=ft.Column(
                [self.status, self.detail, self.progress], tight=True, spacing=14)),
            actions=[self.later, self.pause, self.start, self.exit_button, self.restart_button])

    def show(self):
        with thread_safe_ui.TREE_LOCK:
            self.phase = "offered"
            dialogs.open_dialog(self.page, self.dialog)
        self._scan()
        return self

    def _paint(self):
        thread_safe_ui.refresh(self.dialog)

    def _scan(self):
        with thread_safe_ui.TREE_LOCK:
            if self.phase == "scanning":
                return
            self.phase = "scanning"
            self.start.disabled = True
            self.progress.visible = True
            self.progress.value = None
            self.detail.value = "Checking files and required disk space…"
            self._paint()
            self.scan_cancel = threading.Event()
            scan_cancel = self.scan_cancel
        def work():
            try:
                plan = storage.inventory(hash_files=False, cancel=scan_cancel)
                plan["organize_instances"] = storage_layout.needed(self.instance_labels)
                plan["instance_labels"] = self.instance_labels
                with thread_safe_ui.TREE_LOCK:
                    if scan_cancel.is_set() or self.phase == "skipped":
                        return
                    self.plan = plan
                    if not plan["instances"] and plan.get("organize_instances"):
                        self.status.value = "Your instances are ready. Put shared game files inside Instances and give instance folders readable names."
                        self.detail.value = "Worlds and settings move with their own instance. Files are moved directly, with no duplicate copies or links."
                        self.start.content = "Organize folders"
                    elif not plan["instances"] and plan.get("cleanup"):
                        self.status.value = "Your instances are already migrated. Finish cleanup to remove the old global mod and pack folders from the main Minecraft directory."
                        self.detail.value = "Original content moves to backups/legacy-content. Worlds and settings stay untouched."
                        self.start.content = "Finish cleanup"
                    elif plan["instances"]:
                        self.detail.value = (f"{len(plan['instances'])} instance(s) · "
                                             f"{plan['bytes'] / (1024 ** 3):.2f} GB extra space before safety margin. "
                                             "Old global content will move to backups/legacy-content after verification.")
                        self.start.content = "Migrate now"
                    else:
                        self.detail.value = "Already organized. Mods, texture packs and shaders live in each instance's folder."
                    self.start.disabled = not bool(plan["instances"] or plan.get("cleanup") or plan.get("organize_instances"))
            except Exception as error:
                with thread_safe_ui.TREE_LOCK:
                    if not scan_cancel.is_set():
                        self.detail.value = str(error)
            finally:
                with thread_safe_ui.TREE_LOCK:
                    if not scan_cancel.is_set() and self.phase != "skipped":
                        self.phase = "offered"
                        self.progress.visible = False
                        self._paint()
        threading.Thread(target=work, name="storage-inventory", daemon=True).start()

    def _later(self, _event=None):
        with thread_safe_ui.TREE_LOCK:
            if self.phase in ("migrating", "restart"):
                return
            self.phase = "skipped"
            self.scan_cancel.set()
            dialogs.close_dialog(self.page, self.dialog)

    def _progress(self, stage, done, total):
        now = time.monotonic()
        if now - self._last_progress < 0.15 and done != total:
            return
        self._last_progress = now
        with thread_safe_ui.TREE_LOCK:
            self.status.value = stage
            self.progress.value = done / total if total else None
            self._paint()

    def _start(self, _event=None):
        with thread_safe_ui.TREE_LOCK:
            if self.phase != "offered":
                return
            if not self.plan:
                self._scan()
                return
            if self.busy():
                self.detail.value = "Close Minecraft and wait for downloads and server jobs to finish, then retry."
                self._paint()
                return
            self.phase = "migrating"
            self.set_locked(True)
            self.cancel.clear()
            self.start.visible = self.later.visible = False
            self.pause.visible = self.progress.visible = True
            self.detail.value = "Keep Minecraft closed. Original files will be preserved."
            self._paint()
        def work():
            try:
                result = storage.migrate(self.plan, progress=self._progress, cancel=self.cancel)
                if result.get("organized"):
                    message = "Organization complete. Instance folders have readable names and shared game files are inside Instances. Restart Cubeon to continue."
                elif result.get("archived"):
                    message = f"Cleanup complete. {len(result['archived'])} old content folders moved out of the main directory. Restart Cubeon to continue."
                else:
                    message = f"Migration complete. {result['migrated']} instance(s) organized. Restart Cubeon to continue."
            except Exception as error:
                message = str(error)
                self.plan = None
            with thread_safe_ui.TREE_LOCK:
                self.status.value = message
                self.pause.visible = self.progress.visible = False
                if storage.restart_required():
                    self.phase = "restart"
                    self.restart_button.visible = self.exit_button.visible = True
                    self.detail.value = "Original files are kept. Restart before using your instances."
                else:
                    self.set_locked(False)
                    self.phase = "offered"
                    self.start.visible = self.later.visible = True
                    self.start.content = "Retry migration"
                    self.detail.value = "Your original setup remains active. You can retry or choose Later."
                self._paint()
        threading.Thread(target=work, name="storage-migration", daemon=True).start()
