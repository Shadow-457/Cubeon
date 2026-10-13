"""Settings -> Import: point Cubeon at any folder and it finds every mod,
resource pack, shader pack, modpack and world inside - then imports the ones
you pick into the active instance.

Layout and behaviour:
  * A "Scan a folder" button opens a folder picker. The scan itself runs on a
    background thread (cubeon/importer.scan_folder never raises; it collects
    per-file problems into ``errors``) so a huge or half-broken folder can't
    freeze the UI.
  * Results render as a one-line summary ("Found 12 mods, 3 resource packs...")
    plus one collapsible group per content type. Opening a group lists every
    find with its size / loader / Minecraft version, an "Import" button and a
  * copy-path button. "Import all" imports a whole group in one click.
  * Every import runs on its own thread and reuses the exact installers the
    Mods / Modpacks tabs already trust (cubeon.importer.import_item), so a
    found mod lands in the per-profile folder and a world lands in saves/.

main.py owns the state this pane needs: `get_active_target()` returns the
(mc_version, loader, version_id) currently selected on the Play tab, so
imports always go into the instance the player is about to launch.
"""
import os
import threading

import flet as ft

from cubeon import importer, thread_safe_ui
from cubeon.config import run_dir_picker
from cubeon.theme import RADIUS, attach_hover, TEXT_FAINT


def _copy_text(page, text):
    """Best-effort copy to the clipboard across Flet versions."""
    try:
        page.set_clipboard(text)
        return True
    except Exception:
        pass
    try:
        from flet.controls.services.clipboard import Clipboard
        page.run_task(Clipboard().set, text)
        return True
    except Exception:
        return False


def build_import_section(page, cfg, *, section_label, get_active_target,
                         show_snack=None, BG, SURFACE, SURFACE_HI, BORDER, ACCENT,
                         ACCENT_DIM, TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO):
    """Builds the Import pane and returns it as an ft.Column.

    `get_active_target()` -> (mc_version, loader, version_id) for the instance
    currently chosen on the Play tab. `show_snack` is optional (falls back to
    the in-pane status line) so the pane still works where a snackbar host is
    absent. Import progress goes to the pane's own status line, not the
    sidebar's persistent READY indicator.
    """
    state = {"result": None, "root": None}

    def snack(msg, *, danger=False):
        if show_snack:
            try:
                show_snack(msg)
                return
            except Exception:
                pass
        _set_status(msg)

    def _set_status(msg):
        status_text.value = msg
        thread_safe_ui.refresh(status_text)

    def _refresh_target():
        mc, loader, _vid = _target()
        if mc:
            target_text.value = f"Imports go into: {mc} ({loader})"
        else:
            target_text.value = "Pick a game version on the Play tab to import into."
        thread_safe_ui.refresh(target_text)

    def _target():
        try:
            return get_active_target() or (None, None, None)
        except Exception:
            return (None, None, None)

    # --- static controls ---------------------------------------------------
    target_text = ft.Text("", size=11.5, color=TEXT_FAINT, font_family=FONT_MONO)
    status_text = ft.Text("", size=12, color=TEXT_DIM)
    results_col = ft.Column(spacing=12)

    scan_btn = ft.FilledButton(
        "Scan a folder", icon=ft.Icons.FOLDER_OPEN_ROUNDED,
        on_click=lambda e: _open_scanner(),
    )
    clear_btn = ft.OutlinedButton(
        "Clear results", icon=ft.Icons.CLOSE_ROUNDED, visible=False,
        on_click=lambda e: _clear_results(),
    )

    # --- folder picker (same version-safe registration dance as mods_tab) ---
    dir_picker = ft.FilePicker()
    dir_picker.on_result = lambda e: _on_dir_chosen(getattr(e, "path", None))

    _reg = False
    _svcs = getattr(page, "_services", None)
    if _svcs is not None and hasattr(_svcs, "_services") and dir_picker in _svcs._services:
        _reg = True
    _reg_fn = getattr(page, "register_service", None)
    if not _reg and callable(_reg_fn):
        try:
            _reg_fn(dir_picker)
            _reg = True
        except Exception:
            _reg = False
    if not _reg:
        try:
            if dir_picker not in page.overlay:
                page.overlay.append(dir_picker)
        except Exception:
            pass

    def _open_scanner(e=None):
        _refresh_target()
        run_dir_picker(page, dir_picker, on_path=_on_dir_chosen,
                       dialog_title="Choose a folder to scan for Minecraft content")

    def _clear_results(e=None):
        state["result"] = None
        state["root"] = None
        results_col.controls.clear()
        clear_btn.visible = False
        status_text.value = ""
        for c in (results_col, clear_btn, status_text):
            thread_safe_ui.refresh(c)

    def _on_dir_chosen(path):
        if not path:
            return
        _refresh_target()
        scan_btn.disabled = True
        thread_safe_ui.refresh(scan_btn)
        _set_status(f"Scanning {os.path.basename(path.rstrip(os.sep))} ...")

        def worker():
            try:
                result = importer.scan_folder(path)
            except Exception as ex:  # importer.scan_folder shouldn't raise, but
                result = None        # never let a scan kill the handler thread
                _set_status(f"Scan failed: {ex}")
            state["result"] = result
            state["root"] = path
            _render(result)
            scan_btn.disabled = False
            thread_safe_ui.refresh(scan_btn)

        threading.Thread(target=worker, daemon=True, name="cubeon-import-scan").start()

    # --- rendering ---------------------------------------------------------
    def _render(result):
        results_col.controls.clear()
        clear_btn.visible = result is not None
        if result is None:
            thread_safe_ui.refresh(results_col)
            return

        total = importer.total_found(result)
        if total == 0:
            results_col.controls.append(ft.Text(
                "Nothing to import here.", size=13.5, color=TEXT,
                weight=ft.FontWeight.W_600))
            results_col.controls.append(ft.Text(
                "Cubeon looks for mod .jar files, resource and shader pack "
                ".zip files, Modrinth/CurseForge modpacks, and world folders "
                "(any folder with a level.dat).",
                size=11.5, color=TEXT_FAINT))
        else:
            results_col.controls.append(ft.Text(
                importer.summary_line(result), size=14, color=TEXT,
                weight=ft.FontWeight.W_700))
            errs = result.get("errors") or []
            if errs:
                results_col.controls.append(ft.Text(
                    f"{len(errs)} item(s) couldn't be read and were skipped.",
                    size=11, color=TEXT_FAINT))
            counts = importer.counts(result)
            for kind in importer.CATEGORIES:
                if counts[kind]:
                    results_col.controls.append(_category_group(kind, result[kind]))

        _set_status(f"Scan complete in {state['root']}.")
        thread_safe_ui.refresh(results_col)
        thread_safe_ui.refresh(clear_btn)

    def _category_group(kind, entries):
        label = importer.LABELS[kind][1]  # plural
        details = ft.Column(spacing=4, visible=False)
        if len(entries) > 10:
            details.height = 300
            details.scroll = ft.ScrollMode.AUTO
        for e in entries:
            details.controls.append(_item_row(kind, e))

        chevron = ft.Icon(ft.Icons.KEYBOARD_ARROW_RIGHT, size=18, color=TEXT_DIM)
        count_badge = ft.Text(str(len(entries)), size=12, color=TEXT_FAINT)
        all_btn = ft.TextButton(
            "Import all", icon=ft.Icons.DOWNLOAD_ROUNDED, height=28,
            on_click=lambda e, k=kind, en=entries: _import_all(k, en),
        )
        header = attach_hover(
            ft.Container(
                content=ft.Row(
                    [
                        chevron,
                        ft.Text(label, size=13.5, color=TEXT,
                                weight=ft.FontWeight.W_600, expand=True),
                        count_badge,
                        all_btn,
                    ],
                    spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                border_radius=RADIUS, padding=ft.padding.Padding.symmetric(
                    horizontal=10, vertical=8),
                ink=False,
                on_click=lambda e, d=details, c=chevron: _toggle(d, c),
            ),
            None, SURFACE_HI,
        )
        return ft.Column([header, details], spacing=4)

    def _toggle(details, chevron):
        open_ = not details.visible
        details.visible = open_
        # ft.Icon's glyph attribute is `.icon` (NOT `.name`) on every Flet
        # version we support - setting .name silently leaves the old arrow.
        chevron.icon = (ft.Icons.KEYBOARD_ARROW_DOWN if open_
                        else ft.Icons.KEYBOARD_ARROW_RIGHT)
        thread_safe_ui.refresh(details)
        thread_safe_ui.refresh(chevron)

    def _item_row(kind, e):
        meta_bits = []
        if e.get("size"):
            meta_bits.append(importer.human_size(e["size"]))
        if e.get("loader"):
            meta_bits.append(e["loader"])
        if e.get("mc_dep"):
            meta_bits.append(f"MC {e['mc_dep']}")
        if e.get("note"):
            meta_bits.append(e["note"])
        meta = "  ·  ".join(meta_bits) or e.get("rel", "")

        import_btn = ft.OutlinedButton(
            "Import", icon=ft.Icons.DOWNLOAD_ROUNDED, height=28,
        )
        # Bind after creation so the handler can disable the button while the
        # (threaded) import runs.
        import_btn.on_click = lambda ev, ent=e, btn=import_btn: _import_one(ent, btn)

        copy_btn = ft.IconButton(
            icon=ft.Icons.CONTENT_COPY_ROUNDED, icon_size=15,
            tooltip="Copy file path",
            on_click=lambda ev, p=e["path"]: _copy_path(p),
        )

        return ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(e["name"], size=13, color=TEXT,
                                weight=ft.FontWeight.W_500,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                        ft.Text(meta, size=11, color=TEXT_FAINT,
                                font_family=FONT_MONO,
                                max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                    ],
                    spacing=1, expand=True,
                ),
                ft.Row([import_btn, copy_btn], spacing=4),
            ],
            spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        )

    def _copy_path(path):
        ok = _copy_text(page, path)
        snack("Path copied." if ok else "Couldn't copy the path.")

    # --- import actions ----------------------------------------------------
    def _import_one(e, btn=None):
        mc, loader, vid = _target()
        if not mc:
            snack("Pick a game version on the Play tab first.", danger=True)
            return
        if btn is not None:
            btn.disabled = True
            thread_safe_ui.refresh(btn)

        def worker():
            try:
                msg = importer.import_item(
                    e, mc_version=mc, loader=loader, version_id=vid,
                    status_cb=lambda s: _set_status(s))
                _set_status(msg)
                snack(msg)
            except ValueError as ve:
                _set_status(str(ve))
                snack(str(ve), danger=True)
            except Exception as ex:
                m = f"Import failed: {ex}"
                _set_status(m)
                snack(m, danger=True)
            if btn is not None:
                btn.disabled = False
                thread_safe_ui.refresh(btn)

        threading.Thread(target=worker, daemon=True, name="cubeon-import-one").start()

    def _import_all(kind, entries):
        mc, loader, vid = _target()
        if not mc:
            snack("Pick a game version on the Play tab first.", danger=True)
            return
        scan_btn.disabled = True
        thread_safe_ui.refresh(scan_btn)
        _set_status(f"Importing {len(entries)} {importer.LABELS[kind][1]} ...")

        def worker():
            ok = fail = 0
            last = ""
            for e in entries:
                try:
                    last = importer.import_item(
                        e, mc_version=mc, loader=loader, version_id=vid,
                        status_cb=lambda s: _set_status(s))
                    ok += 1
                except Exception as ex:
                    last = str(ex)
                    fail += 1
            label = importer.LABELS[kind][1]
            msg = f"Imported {ok} {label}."
            if fail:
                msg += f" {fail} failed: {last}"
            _set_status(msg)
            snack(msg, danger=bool(fail))
            scan_btn.disabled = False
            thread_safe_ui.refresh(scan_btn)

        threading.Thread(target=worker, daemon=True, name="cubeon-import-all").start()

    # --- assemble the pane -------------------------------------------------
    _refresh_target()

    pane = ft.Column(
        [
            section_label("Import"),
            ft.Container(height=2),
            ft.Text(
                "Point Cubeon at any folder - an old .minecraft, a downloads "
                "folder, a backup - and it finds every mod, resource pack, "
                "shader pack, modpack and world inside. Import one with a "
                "click and Cubeon files it into the right place for your "
                "current game version.",
                size=12, color=TEXT_DIM,
            ),
            ft.Container(height=10),
            target_text,
            ft.Container(height=8),
            ft.Row([scan_btn, clear_btn], spacing=12),
            ft.Container(height=4),
            status_text,
            ft.Container(height=4),
            results_col,
        ],
        spacing=8, visible=False,
    )
    # Hooks so another surface (and the test harness) can drive a scan result
    # through the renderer without waiting on a real folder dialog. The pane's
    # own scan flow calls _render itself once scan_folder finishes.
    pane.render_scan_result = _render
    pane.import_item_ui = _import_one
    pane._results_col = results_col
    pane._status_text = status_text
    return pane
