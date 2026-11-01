"""One Update click downloads, verifies, installs and reopens the launcher."""
import shutil
import re
import logging
import threading
import time
import webbrowser

import flet as ft

from cubeon import dialogs, thread_safe_ui, update_install, updater, theme


class UpdatePrompt:
    def __init__(self, page, info, *, busy, install, target=None):
        self.page, self.info = page, info
        self.busy, self.install = busy, install
        self.target = target or update_install.installation_target()
        self.cancel = threading.Event()
        self.phase = "offered"
        self.download = None
        self._last_progress = 0.0
        asset = update_install.release_asset(info, self.target)
        self.can_install = self.target.can_install
        size = (asset or {}).get("size")
        detail = "Update will download, install and reopen Cubeon automatically."
        if self.target.asset == "linux-deb" and self.can_install:
            detail += " Linux will ask you to authorize the package installation."
        if not self.can_install:
            detail = self.target.reason or "This installation needs a manual update. You can download it below."
        self.status = ft.Text(detail, size=13, color=theme.TEXT)
        self.progress = ft.ProgressBar(value=0, visible=False, color=theme.ACCENT, bgcolor=theme.SURFACE_HI)
        self.skip = ft.TextButton("Skip", on_click=self._skip, data="update-skip")
        self.update = ft.FilledButton("Update", on_click=self._update, data="update-now",
                                     visible=self.can_install, height=44,
                                     style=ft.ButtonStyle(bgcolor=theme.ACCENT, color=theme.ON_ACCENT,
                                                          shape=theme.block()))
        self.manual = ft.TextButton("Download manually", on_click=self._manual_download,
                                    data="update-manual", visible=not self.can_install)
        content = [self.status]
        if isinstance(size, int) and size > 0:
            content.append(ft.Text(f"Download: {size / 1024**2:.0f} MB", size=12, color=theme.TEXT_DIM))
        if info.get("notes"):
            content.append(ft.Container(height=160, bgcolor=theme.BG, border_radius=theme.RADIUS, padding=12,
                                        content=ft.Column([ft.Text(info["notes"], size=12, color=theme.TEXT_DIM,
                                                                   selectable=True)], scroll=ft.ScrollMode.AUTO)))
        content.append(self.progress)
        self.dialog = ft.AlertDialog(
            modal=True, bgcolor=theme.SURFACE, shape=theme.block(),
            content_padding=24, actions_padding=16,
            title=ft.Text(f"Cubeon {info['version']} is available", size=22, color=theme.TEXT,
                          weight=ft.FontWeight.W_600),
            content=ft.Container(width=440, content=ft.Column(content, tight=True, spacing=12)),
            actions=[self.skip, self.update, self.manual],
            on_dismiss=self._skip,
        )

    def open(self):
        with thread_safe_ui.TREE_LOCK:
            dialogs.open_dialog(self.page, self.dialog)
        return self

    def _paint(self):
        thread_safe_ui.refresh(self.dialog)

    def _cleanup(self, path):
        if path:
            shutil.rmtree(path.parent, ignore_errors=True)

    def _skip(self, _e=None):
        with thread_safe_ui.TREE_LOCK:
            if self.phase in {"skipped", "closing"}:
                return
            # An active worker owns its bytes until hashing/downloading ends.
            cleanup = self.download if self.phase == "ready" else None
            self.phase = "skipped"
            self.cancel.set()
            dialogs.close_dialog(self.page, self.dialog)
            if cleanup:
                self.download = None
        if cleanup:
            self._start_worker(lambda: self._cleanup(cleanup), 'cubeon-update-cleanup')

    def _start_worker(self, target, name):
        try:
            threading.Thread(target=target, daemon=True, name=name).start()
        except Exception:
            logging.getLogger(__name__).exception("Could not start update worker")
            self._work_failed("Couldn't start the update. Try again.")

    def _update(self, _e=None):
        with thread_safe_ui.TREE_LOCK:
            if self.phase not in {"offered", "ready"}:
                return
            if not self.can_install:
                self.status.value = self.target.reason or "This installation needs a manual update. Choose Download manually below."
                self._paint()
                return
            asset = update_install.release_asset(self.info, self.target)
            if not re.fullmatch(r"[0-9a-f]{64}", str((asset or {}).get("sha256") or ""), re.I):
                self.status.value = "This release is missing a verified update. Restart Cubeon to check again."
                self._paint()
                return
            ready = self.phase == "ready"
            self.phase = "preparing" if ready else "downloading"
            self.update.disabled = True
            self.skip.content = "Cancel"
            self.progress.visible = True
            self.status.value = "Preparing the update…" if ready else "Checking before download…"
            self._paint()
        self._start_worker(self._prepare if ready else self._begin_download, 'cubeon-update')

    def _idle(self):
        # Process/disk checks must run outside the UI tree lock.
        busy = self.busy()
        with thread_safe_ui.TREE_LOCK:
            if self.cancel.is_set() or self.phase == "skipped":
                return False
            if busy:
                self.phase = "ready" if self.download else "offered"
                self.update.disabled = False
                self.skip.content = "Skip"
                self.progress.visible = bool(self.download)
                self.status.value = "Close Minecraft and stop any active installs or servers, then try again."
                self._paint()
            return not busy

    def _begin_download(self):
        try:
            if self._idle():
                self._download()
        except Exception as error:
            self._work_failed(str(error))

    def _prepare(self):
        try:
            if not self._idle():
                return
            job = update_install.prepare_install(self.info, self.target, self.download)
            if not self._idle():
                return
            with thread_safe_ui.TREE_LOCK:
                if self.phase != "preparing" or self.cancel.is_set():
                    return
                self.phase = "closing"
                self.update.disabled = self.skip.disabled = True
                self.status.value = "Closing Cubeon to install the update…"
                self._paint()
            self.install(job, self.install_failed)
        except Exception as error:
            self._work_failed(str(error))
        finally:
            if self.cancel.is_set():
                self._cleanup(self.download)
                self.download = None

    def _work_failed(self, message):
        with thread_safe_ui.TREE_LOCK:
            if self.phase not in {"downloading", "preparing", "closing"}:
                return
            self.phase = "ready" if self.download else "offered"
            self.update.disabled = self.skip.disabled = False
            self.skip.content = "Skip"
            self.progress.visible = bool(self.download)
            self.status.value = message
            self._paint()

    def _manual_download(self, _e=None):
        with thread_safe_ui.TREE_LOCK:
            if self.can_install or self.phase != "offered":
                return
            asset = update_install.release_asset(self.info, self.target)
            try:
                if not webbrowser.open(asset["url"] if asset else self.info["url"]):
                    raise RuntimeError("No browser opened")
            except Exception:
                self.status.value = "Couldn't open the download. Please try again."
                self._paint()
                return
            self._skip()

    def _progress(self, done, total):
        now = time.monotonic()
        if done < total and now - self._last_progress < 0.2:
            return
        self._last_progress = now
        with thread_safe_ui.TREE_LOCK:
            if self.phase != "downloading":
                return
            self.progress.value = done / total
            self.status.value = f"Downloading update… {done / 1024**2:.1f} / {total / 1024**2:.1f} MB"
            self._paint()

    def _download(self):
        try:
            try:
                path = update_install.download_update(self.info, self.target, self.cancel, self._progress)
            except update_install.UpdateReleaseChanged:
                if self.cancel.is_set():
                    return
                info = updater.check_for_updates(channel=self.info.get("channel", "stable"))
                if not info:
                    raise ValueError("The release changed. Check for updates again in Settings.")
                with thread_safe_ui.TREE_LOCK:
                    if self.phase != "downloading":
                        return
                    self.info = info
                    self.dialog.title.value = f"Updating Cubeon to {info['version']}"
                path = update_install.download_update(info, self.target, self.cancel, self._progress)
            with thread_safe_ui.TREE_LOCK:
                stale = self.phase != "downloading" or self.cancel.is_set()
                if not stale:
                    self.download = path
                    self.phase = "preparing"
                    self.update.content = "Restart"
                    self.progress.value = 1
                    self.status.value = "Download verified. Preparing to restart Cubeon…"
                    self._paint()
            if stale:
                self._cleanup(path)
                return
            self._prepare()
        except update_install.UpdateCancelled:
            return
        except Exception as error:
            logging.getLogger(__name__).info("Update download failed", exc_info=True)
            with thread_safe_ui.TREE_LOCK:
                if self.phase != "downloading":
                    return
                self.phase = "offered"
                self.update.disabled = False
                self.skip.content = "Skip"
                self.progress.visible = False
                self.status.value = (str(error) if isinstance(error, ValueError) else
                                     "Couldn't download the update. Check your connection and try again.")
                self._paint()

    def install_failed(self, message):
        with thread_safe_ui.TREE_LOCK:
            if self.phase not in {"closing", "ready"}:
                return
            self.phase = "ready"
            self.skip.disabled = self.update.disabled = False
            self.status.value = message
            self._paint()
