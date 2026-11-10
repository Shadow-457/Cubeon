"""Inline Settings controls for reviewing and importing FastClient profiles."""
import logging
import threading

import flet as ft

from cubeon import instance_import, instances, theme, thread_safe_ui
from cubeon.config import run_dir_picker


class FastClientImport:
    def __init__(self, page, *, finished, busy_reason=lambda: None):
        self.page, self.finished, self.busy_reason = page, finished, busy_reason
        self.phase = "choose"
        self._generation = 0
        self.plan = None
        self.cancel_event = threading.Event()
        self.dir_picker = None
        self.path = ft.TextField(label="FastClient folder (optional)", hint_text="Auto-detect installed profiles",
                                 color=theme.TEXT, border_color=theme.BORDER, expand=True, text_size=12)
        self.browse = ft.IconButton(icon=ft.Icons.FOLDER_OPEN_ROUNDED,
                                    tooltip="Choose FastClient settings or game folder", on_click=self._browse)
        self.scan = ft.OutlinedButton("Find profiles", on_click=lambda e: self._scan())
        self.name = ft.TextField(label="New Cubeon instance name", color=theme.TEXT,
                                 border_color=theme.BORDER, visible=False)
        self.rows = ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.status = ft.Text("Find your installed FastClient profiles, or choose its settings folder.",
                              color=theme.TEXT_DIM, size=12, selectable=True)
        self.progress = ft.ProgressBar(color=theme.ACCENT, visible=False)
        self.cancel = ft.TextButton("Clear", on_click=self._reset)
        self.submit = ft.FilledButton("Import as new instance", on_click=self._import, disabled=True)
        self.view = ft.Container(
            bgcolor=theme.SURFACE_HI, border_radius=theme.RADIUS, padding=20,
            content=ft.Column([
                ft.Text("Import from FastClient", color=theme.TEXT, size=18, weight=ft.FontWeight.W_600),
                ft.Text("Bring your mods, configs, worlds, packs, settings and screenshots to Cubeon. "
                        "Your FastClient profile stays intact.", color=theme.TEXT_DIM, size=13),
                ft.Row([self.path, self.browse]), self.scan, self.rows, self.name,
                self.status, self.progress,
                ft.Row([self.submit, self.cancel], spacing=12),
            ], tight=True, spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        )
        self.view.data = "fastclient-import-section"
        self.view.import_model = self
        self._paint()

    def _paint(self):
        busy = self.phase in ("scanning", "reviewing", "importing")
        self.scan.disabled = self.browse.disabled = self.path.disabled = busy
        self.name.disabled = busy
        self.rows.disabled = busy or self.phase == "done"
        self.rows.visible = bool(self.rows.controls)
        self.name.visible = self.phase in ("review", "importing", "done")
        self.submit.visible = self.phase in ("review", "importing")
        self.cancel.visible = bool(self.rows.controls) or busy
        self.cancel.content = "Cancel import" if self.phase == "importing" else "Clear"
        self.submit.disabled = self.phase != "review"
        self.progress.visible = busy
        thread_safe_ui.refresh(self.view)

    def _worker(self, work, success, fallback):
        self._generation += 1
        generation = self._generation
        def run():
            try:
                value = work()
            except Exception as error:
                if not isinstance(error, instance_import.ImportCancelled):
                    logging.getLogger(__name__).exception("FastClient import failed")
                with thread_safe_ui.TREE_LOCK:
                    if generation != self._generation:
                        return
                    self.phase = fallback
                    self.status.value = str(error)
                    self.cancel.disabled = False
                    self._paint()
                return
            with thread_safe_ui.TREE_LOCK:
                if generation == self._generation:
                    success(value)
        try:
            threading.Thread(target=run, daemon=True, name="cubeon-fastclient-import").start()
        except Exception as error:
            with thread_safe_ui.TREE_LOCK:
                self.phase = fallback
                self.status.value = f"Couldn't start: {error}. Try again."
                self.cancel.disabled = False
                self._paint()

    def _browse(self, _event=None):
        if self.phase not in ("choose", "review", "done"):
            return
        if self.dir_picker is None:
            self.dir_picker = ft.FilePicker()
            services = getattr(self.page, "_services", None)
            register = getattr(services, "register_service", None) or getattr(self.page, "register_service", None)
            if callable(register):
                register(self.dir_picker)
            elif self.dir_picker not in self.page.overlay:
                self.page.overlay.append(self.dir_picker)
            self.dir_picker.on_result = lambda e: self._picked(getattr(e, "path", None))
        run_dir_picker(self.page, self.dir_picker, on_path=self._picked,
                       dialog_title="Choose FastClient settings or game folder")

    def _picked(self, path):
        with thread_safe_ui.TREE_LOCK:
            if self.phase not in ("choose", "review", "done") or not path:
                return
            self.path.value = path
        self._scan()

    def _scan(self):
        with thread_safe_ui.TREE_LOCK:
            if self.phase not in ("choose", "review", "done"):
                return
            self.phase = "scanning"
            self.plan = None
            self.name.visible = False
            self.rows.controls.clear()
            self.status.value = "Finding FastClient profiles…"
            self.progress.value = None
            folder = (self.path.value or "").strip() or None
            self._paint()

        def found(result):
            self.phase = "choose"
            profiles = result["profiles"]
            self.rows.controls = [ft.OutlinedButton(
                f"{p['name']} · {p['mc_version']} · {p['loader'].title()}",
                on_click=lambda e, profile=p: self._review(profile),
            ) for p in profiles]
            self.status.value = ("Choose a profile to review." if profiles else
                                 "No profiles found. Choose the FastClient folder containing profiles.json, "
                                 "or its game folder, then find profiles again.")
            if result["errors"]:
                self.status.value += "\n" + "\n".join(result["errors"][:3])
            self._paint()

        self._worker(lambda: instance_import.discover(folder), found, "choose")

    def _review(self, profile):
        with thread_safe_ui.TREE_LOCK:
            if self.phase != "choose":
                return
            self.phase = "reviewing"
            self.status.value = "Checking profile files…"
            self.cancel_event.clear()
            self._paint()

        def reviewed(plan):
            self.plan = plan
            self.phase = "review"
            self.name.value, self.name.visible = profile["name"], True
            details = [f"Minecraft {profile['mc_version']} · {profile['loader'].title()}"
                       + (f" {profile['loader_version']}" if profile["loader_version"] else ""),
                       f"{plan['mods']} mods · {plan['worlds']} worlds · {instances.format_size(plan['bytes'])} game files",
                       f"Local runtime: {instances.format_size(plan['runtime_bytes'])} · No downloads",
                       profile["directory"],
                       "Includes disabled mods, configs, worlds, packs, options, servers and screenshots.",
                       "Uses FastClient's installed game, loader, libraries and assets. No internet downloads.",
                       "Accounts, launcher settings and caches stay behind."]
            if plan["skipped"]:
                details.append("Skipped launcher files: " + ", ".join(plan["skipped"]))
            self.rows.controls = [ft.Text(text, color=theme.TEXT_DIM, size=12, selectable=True) for text in details]
            self.status.value = "Close Minecraft in FastClient before importing. This creates a separate instance."
            self._paint()

        self._worker(lambda: instance_import.review(profile, self.cancel_event), reviewed, "choose")

    def _progress(self, done, total, text):
        with thread_safe_ui.TREE_LOCK:
            if self.phase != "importing":
                return
            self.progress.value = min(1, max(0, done / total)) if total else None
            self.status.value = text
            thread_safe_ui.refresh(self.view)

    def _import(self, _event=None):
        with thread_safe_ui.TREE_LOCK:
            if self.phase != "review" or not self.plan:
                return
            reason = self.busy_reason()
            if reason:
                self.status.value = reason
                self._paint()
                return
            name = (self.name.value or "").strip()
            if not name or len(name) > 200 or any(ord(c) < 32 for c in name):
                self.status.value = "Enter an instance name (1–200 characters)."
                self._paint()
                return
            self.phase = "importing"
            self.cancel_event.clear()
            self._paint()
            plan = self.plan

        def work():
            result = instance_import.import_review(plan, name=name, cancel_event=self.cancel_event,
                                                   progress=self._progress)
            try:
                self.finished(result)
            except Exception:
                logging.getLogger(__name__).exception("Couldn't select the imported instance")
                result["refresh_failed"] = True
            return result

        def imported(result):
            self.phase = "done"
            self.status.value = f"Imported {result['name']}. Your FastClient profile stays intact."
            if result.get("refresh_failed"):
                self.status.value += " Reopen Cubeon to see the new instance."
            self.cancel.disabled = False
            self._paint()

        self._worker(work, imported, "choose")

    def _reset(self, _event=None):
        with thread_safe_ui.TREE_LOCK:
            self.cancel_event.set()
            if self.phase == "importing":
                self.cancel.disabled = True
                self.status.value = "Cancelling import…"
                thread_safe_ui.refresh(self.view)
                return
            self._generation += 1
            self.phase, self.plan = "choose", None
            self.rows.controls.clear()
            self.cancel.disabled = False
            self.status.value = "Find your installed FastClient profiles, or choose its settings folder."
            self._paint()
