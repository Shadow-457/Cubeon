"""Startup Skip / Update prompt. Downloading always requires a click."""
import shutil
import re
import logging
import threading
import time
import webbrowser

import flet as ft

from cubeon import dialogs, thread_safe_ui, update_install


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
        detail = "Download the update now, or skip and keep using Cubeon."
        if not self.can_install:
            detail = self.target.reason or "This installation needs a manual update. You can download it below."
        self.status = ft.Text(detail, size=13)
        self.progress = ft.ProgressBar(value=0, visible=False)
        self.skip = ft.TextButton("Skip", on_click=self._skip, data="update-skip")
        self.update = ft.FilledButton("Update", on_click=self._update, data="update-now")
        self.manual = ft.TextButton("Download manually", on_click=self._manual_download,
                                    data="update-manual", visible=not self.can_install)
        content = [self.status]
        if isinstance(size, int) and size > 0:
            content.append(ft.Text(f"Download: {size / 1024**2:.0f} MB", size=12))
        if info.get("notes"):
            content.append(ft.Text(info["notes"], size=12, selectable=True))
        content.append(self.progress)
        self.dialog = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Cubeon {info['version']} is available"),
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

    def _skip(self, _e=None):
        with thread_safe_ui.TREE_LOCK:
            if self.phase in {"skipped", "closing"}:
                return
            self.phase = "skipped"
            self.cancel.set()
            dialogs.close_dialog(self.page, self.dialog)
            if self.download:
                shutil.rmtree(self.download.parent, ignore_errors=True)
                self.download = None

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
            if self.busy():
                self.status.value = "Close Minecraft and stop any active installs or servers, then try again."
                self._paint()
                return
            if self.phase == "ready":
                try:
                    job = update_install.prepare_install(self.info, self.target, self.download)
                    self.phase = "closing"
                    self.update.disabled = self.skip.disabled = True
                    self.status.value = "Closing Cubeon to install the update…"
                    self._paint()
                    self.install(job, self.install_failed)
                except Exception as error:
                    self.install_failed(str(error))
                return
            self.phase = "downloading"
            self.update.disabled = True
            self.skip.content = "Cancel"
            self.progress.visible = True
            self.status.value = "Downloading update…"
            self._paint()
            threading.Thread(target=self._download, daemon=True, name="cubeon-update-download").start()

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
            path = update_install.download_update(self.info, self.target, self.cancel, self._progress)
            with thread_safe_ui.TREE_LOCK:
                if self.phase != "downloading":
                    shutil.rmtree(path.parent, ignore_errors=True)
                    return
                self.download = path
                self.phase = "ready"
                self.update.content = "Restart"
                self.update.disabled = False
                self.skip.content = "Skip"
                self.progress.value = 1
                self.status.value = "Download verified. Restart to install the update and reopen Cubeon."
                self._paint()
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
            if self.phase != "closing":
                return
            self.phase = "ready"
            self.skip.disabled = self.update.disabled = False
            self.status.value = message
            self._paint()
