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
        self.path = ft.TextField(label="Selected FastClient folder", visible=False,
                                 color=theme.TEXT, border_color=theme.BORDER, text_size=12)
        self.browse = ft.TextButton("Choose folder", icon=ft.Icons.FOLDER_OPEN_ROUNDED,
                                    tooltip="Choose your FastClient folder", on_click=self._browse)
        self.scan = ft.FilledButton("Find instances", icon=ft.Icons.SEARCH_ROUNDED,
                                    on_click=lambda e: self._scan())
        self.name = ft.TextField(label="Name in Cubeon", color=theme.TEXT,
                                 border_color=theme.BORDER, visible=False)
        self.rows = ft.Column(spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.status = ft.Text("We'll look for FastClient on this computer. You can choose its folder if needed.",
                              color=theme.TEXT_DIM, size=12, selectable=True)
        self.stage = ft.Text("FROM FASTCLIENT", color=theme.TEXT_DIM, size=10,
                             weight=ft.FontWeight.W_600)
        self.progress = ft.ProgressBar(color=theme.ACCENT, visible=False)
        self.cancel = ft.TextButton("Start over", on_click=self._reset)
        self.submit = ft.FilledButton("Import to Cubeon", icon=ft.Icons.ARROW_FORWARD_ROUNDED,
                                      on_click=self._import, disabled=True)
        self.heading = ft.Text("Bring your worlds with you.", color=theme.TEXT, size=24,
                               weight=ft.FontWeight.W_600)
        self.intro = ft.Text("Copy an instance to Cubeon, including your worlds, mods and packs. "
                             "Your FastClient files stay where they are.", color=theme.TEXT_DIM, size=13)
        self.source_actions = ft.Row([self.scan, self.browse], spacing=8, wrap=True)

        def destination(label, src):
            return ft.Column([
                ft.Container(ft.Image(src=src, width=64, height=64, fit=ft.BoxFit.CONTAIN),
                             width=88, height=88, bgcolor=theme.SURFACE,
                             border_radius=20, alignment=ft.Alignment.CENTER),
                ft.Text(label, color=theme.TEXT, size=13, weight=ft.FontWeight.W_600),
            ], spacing=10, tight=True, horizontal_alignment=ft.CrossAxisAlignment.CENTER)

        self.view = ft.Container(
            bgcolor=theme.SURFACE_HI, border_radius=theme.RADIUS, padding=24,
            content=ft.Column([
                ft.Container(ft.Row([
                    destination("FastClient", "import/launcher-folder.svg"),
                    ft.Icon(ft.Icons.ARROW_FORWARD_ROUNDED, color=theme.ACCENT, size=28),
                    destination("Cubeon", "cube.svg"),
                ], spacing=24, tight=True, alignment=ft.MainAxisAlignment.CENTER),
                    padding=ft.Padding(0, 4, 0, 8)),
                self.stage,
                self.heading, self.intro, self.source_actions, self.path,
                self.rows, self.name,
                self.status, self.progress,
                ft.Row([self.submit, self.cancel], spacing=8, wrap=True),
            ], tight=True, spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        )
        self.view.data = "fastclient-import-section"
        self.view.import_model = self
        self._paint()

    def _paint(self):
        busy = self.phase in ("scanning", "reviewing", "importing")
        choosing = self.phase in ("choose", "scanning")
        self.heading.visible = self.intro.visible = self.source_actions.visible = choosing
        self.scan.disabled = self.browse.disabled = self.path.disabled = busy
        self.path.visible = choosing and bool(self.path.value)
        self.name.disabled = busy or self.phase == "done"
        self.rows.disabled = busy or self.phase == "done"
        self.rows.visible = bool(self.rows.controls)
        self.name.visible = self.phase in ("review", "importing", "done")
        self.submit.visible = self.phase in ("review", "importing")
        self.cancel.visible = bool(self.rows.controls) or busy
        self.cancel.content = "Cancel import" if self.phase == "importing" else "Start over"
        self.submit.disabled = self.phase != "review"
        self.progress.visible = busy
        self.stage.value = {
            "choose": "FROM FASTCLIENT", "scanning": "FINDING YOUR INSTANCES",
            "reviewing": "CHECKING YOUR INSTANCE", "review": "READY TO IMPORT",
            "importing": "COPYING TO CUBEON", "done": "IMPORTED",
        }[self.phase]
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
                       dialog_title="Choose your FastClient folder")

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
            self.status.value = "Looking for your FastClient instances…"
            self.progress.value = None
            folder = (self.path.value or "").strip() or None
            self._paint()

        def found(result):
            self.phase = "choose"
            profiles = result["profiles"]
            self.rows.controls = [ft.OutlinedButton(
                content=ft.Row([
                    ft.Icon(ft.Icons.SPORTS_ESPORTS_ROUNDED, color=theme.TEXT_DIM, size=24),
                    ft.Column([
                        ft.Text(p['name'], color=theme.TEXT, size=14, weight=ft.FontWeight.W_600),
                        ft.Text(f"Minecraft {p['mc_version']} · {p['loader'].title()}",
                                color=theme.TEXT_DIM, size=12),
                    ], spacing=3, tight=True, expand=True),
                    ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, color=theme.TEXT_DIM, size=20),
                ], spacing=12),
                style=ft.ButtonStyle(shape=ft.RoundedRectangleBorder(radius=theme.RADIUS),
                                     padding=ft.Padding(16, 12, 16, 12)),
                on_click=lambda e, profile=p: self._review(profile),
            ) for p in profiles]
            self.status.value = ("Choose the instance you'd like to bring over." if profiles else
                                 "We couldn't find any instances. Use Choose folder to locate your FastClient installation.")
            if result["errors"]:
                self.status.value += "\n" + "\n".join(result["errors"][:3])
            self._paint()

        self._worker(lambda: instance_import.discover(folder), found, "choose")

    def _review(self, profile):
        with thread_safe_ui.TREE_LOCK:
            if self.phase != "choose":
                return
            self.phase = "reviewing"
            self.status.value = "Checking that your instance is ready to copy…"
            self.cancel_event.clear()
            self._paint()

        def reviewed(plan):
            self.plan = plan
            self.phase = "review"
            self.name.value, self.name.visible = profile["name"], True
            details = [profile["directory"],
                       "Also copies disabled mods, game settings, server lists and screenshots.",
                       f"Game files: {instances.format_size(plan['bytes'])}. "
                       f"Installed Minecraft files: {instances.format_size(plan['runtime_bytes'])}.",
                       "Uses the Minecraft files already on this computer. No downloads.",
                       "FastClient accounts, launcher settings and caches aren't copied."]
            if plan["skipped"]:
                details.append("Left behind: " + ", ".join(plan["skipped"]))
            self.rows.controls = [
                ft.Container(content=ft.Column([
                    ft.Text(profile['name'], color=theme.TEXT, size=17, weight=ft.FontWeight.W_600),
                    ft.Text(f"Minecraft {profile['mc_version']} · {profile['loader'].title()}",
                            color=theme.TEXT_DIM, size=12),
                    ft.Row([
                        ft.Text(f"{plan['worlds']} {'world' if plan['worlds'] == 1 else 'worlds'}",
                                color=theme.TEXT, size=13),
                        ft.Text(f"{plan['mods']} {'mod' if plan['mods'] == 1 else 'mods'}",
                                color=theme.TEXT, size=13),
                        ft.Text("Packs & settings", color=theme.TEXT, size=13),
                    ], spacing=20, wrap=True),
                ], spacing=12, tight=True), bgcolor=theme.SURFACE, padding=16, border_radius=theme.RADIUS),
                ft.ExpansionTile(title=ft.Text("What gets copied", color=theme.TEXT_DIM, size=12),
                                 controls=[ft.Container(ft.Column([
                                     ft.Text(text, color=theme.TEXT_DIM, size=12, selectable=True)
                                     for text in details
                                 ], spacing=8, tight=True), padding=ft.Padding(16, 0, 16, 12))]),
            ]
            self.status.value = "Close Minecraft in FastClient before importing. Your original instance will stay intact."
            self._paint()

        self._worker(lambda: instance_import.review(profile, self.cancel_event), reviewed, "choose")

    def _progress(self, done, total, text):
        with thread_safe_ui.TREE_LOCK:
            if self.phase != "importing":
                return
            self.progress.value = min(1, max(0, done / total)) if total else None
            self.status.value = ("Copying installed Minecraft files…" if "runtime" in text.lower()
                                 else "Copying your worlds, mods and settings…")
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
            self.status.value = f"{result['name']} is ready in Cubeon. Choose Play to open it. Your FastClient files are unchanged."
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
            self.status.value = "We'll look for FastClient on this computer. You can choose its folder if needed."
            self._paint()
