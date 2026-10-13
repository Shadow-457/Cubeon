"""Settings -> Import: point Cubeon at any folder and it finds every mod,
resource pack, shader pack, modpack and world inside - then imports the ones
you pick into the instance YOU pick.

Layout and behaviour:
  * A "Scan a folder" button opens a folder picker. The scan itself runs on a
    background thread (cubeon/importer.scan_folder never raises; it collects
    per-file problems into ``errors``) so a huge or half-broken folder can't
    freeze the UI.
  * Results render as a one-line summary ("Found 12 mods, 3 resource packs...")
    plus one collapsible group per content type, each find showing its size /
    loader / Minecraft version. A search field filters the finds live.
  * Every find has an "Import to..." button: it lists every installed
    instance, greys out the incompatible ones (a Fabric jar in a Forge
    instance, a mod that needs another Minecraft version) and the ones that
    already contain this exact content, and installs into the instance you
    click. "Import all" is gone on purpose - targeting is per item now.
  * Duplicate detection (cubeon.importer.mark_installed) greys scan-time
    finds that are already in the ACTIVE profile, and import_item refuses
    exact duplicates per target, so re-scanning an old backup never piles
    up foo_xxxxxx.jar / MyWorld_xxxxxx twins.
  * Every import runs on its own thread and reuses the exact installers the
    Mods / Modpacks tabs already trust (cubeon.importer.import_item), so a
    found mod lands in the per-profile folder and a world lands in saves/.

main.py owns the state this pane needs:
  * `get_active_target()` returns the (mc_version, loader, version_id)
    currently selected on the Play tab - the default target and the basis
    of the scan-time duplicate flags.
  * `get_instances()` returns every installed instance as
    [{"version_id", "mc_version", "loader", "label"}, ...] for the
    Import-to picker. Without it the picker falls back to the active target.
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
                         get_instances=None, show_snack=None,
                         BG, SURFACE, SURFACE_HI, BORDER, ACCENT,
                         ACCENT_DIM, TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO):
    """Builds the Import pane and returns it as an ft.Column.

    `get_active_target()` -> (mc_version, loader, version_id) for the instance
    currently chosen on the Play tab. `get_instances()` -> the instance list
    for the Import-to picker (see the module docstring; optional). `show_snack`
    is optional (falls back to the in-pane status line) so the pane still
    works where a snackbar host is absent. Import progress goes to the pane's
    own status line, not the sidebar's persistent READY indicator.
    """
    state = {"result": None, "root": None, "open": set(), "query": "",
             "groups": []}

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

    def _instances():
        """Every installed instance for the Import-to picker."""
        try:
            raw = get_instances() if get_instances else []
        except Exception:
            raw = []
        out = []
        for v in raw or []:
            vid = v.get("version_id") or v.get("id")
            if not vid:
                continue
            out.append({
                "version_id": vid,
                "mc_version": v.get("mc_version"),
                "loader": v.get("loader") or importer.loader_of(vid),
                "label": v.get("label") or v.get("display_name") or vid,
            })
        if not out:  # no callback / nothing installed: the active target only
            mc, loader, vid = _target()
            if vid:
                out.append({"version_id": vid, "mc_version": mc,
                            "loader": loader or importer.loader_of(vid),
                            "label": vid})
        return out

    def _remark():
        """Re-run duplicate detection on the current scan result for the
        active target. Swallows errors: a failed remark just means the list
        stays un-flagged (import_item's own guards still refuse the import)."""
        result = state.get("result")
        if not result:
            return 0
        mc, loader, _vid = _target()
        try:
            return importer.mark_installed(result, mc_version=mc, loader=loader)
        except Exception:
            return 0

    # --- static controls ---------------------------------------------------
    target_text = ft.Text("", size=11.5, color=TEXT_FAINT, font_family=FONT_MONO)
    status_text = ft.Text("", size=12, color=TEXT_DIM)
    results_col = ft.Column(spacing=12)

    search_field = ft.TextField(
        hint_text="Search found items...",
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        on_change=lambda e: _on_search(getattr(e, "control", None)),
        visible=False, height=42, text_size=12.5,
        color=TEXT, hint_style=ft.TextStyle(size=12.5, color=TEXT_FAINT),
        bgcolor=SURFACE, border_color=BORDER, border_radius=RADIUS,
        dense=True, content_padding=ft.padding.Padding.symmetric(
            horizontal=12, vertical=8),
    )

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
        state["open"].clear()
        state["groups"] = []
        state["query"] = ""
        search_field.value = ""
        search_field.visible = False
        results_col.controls.clear()
        clear_btn.visible = False
        status_text.value = ""
        for c in (results_col, clear_btn, status_text, search_field):
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
            if result is not None:
                _remark()
            _render(result)
            scan_btn.disabled = False
            thread_safe_ui.refresh(scan_btn)

        threading.Thread(target=worker, daemon=True, name="cubeon-import-scan").start()

    # --- search -------------------------------------------------------------
    def _on_search(field):
        state["query"] = (getattr(field, "value", "") or "").strip().lower()
        _apply_filter()

    def _matches(e, q):
        if not q:
            return True
        hay = " ".join(str(e.get(k) or "") for k in ("name", "rel", "loader", "note"))
        return q in hay.lower()

    def _apply_filter():
        q = state["query"]
        for g in state["groups"]:
            any_match = False
            for e, row in g["rows"]:
                show = _matches(e, q)
                row.visible = show
                any_match = any_match or show
            g["group_col"].visible = bool(any_match) if q else True
            if q:
                # Filtering implies "show me what matches" - force open.
                g["details"].visible = any_match
                g["chevron"].icon = (ft.Icons.KEYBOARD_ARROW_DOWN if any_match
                                     else ft.Icons.KEYBOARD_ARROW_RIGHT)
        thread_safe_ui.refresh(results_col)

    # --- rendering ---------------------------------------------------------
    def _render(result, status=None):
        results_col.controls.clear()
        state["groups"] = []
        clear_btn.visible = result is not None
        if result is None:
            search_field.visible = False
            thread_safe_ui.refresh(results_col)
            thread_safe_ui.refresh(search_field)
            return

        total = importer.total_found(result)
        search_field.visible = total > 0
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
            _apply_filter()

        _set_status(status if status else f"Scan complete in {state['root']}.")
        thread_safe_ui.refresh(results_col)
        thread_safe_ui.refresh(clear_btn)
        thread_safe_ui.refresh(search_field)

    def _category_group(kind, entries):
        label = importer.LABELS[kind][1]  # plural
        is_open = kind in state["open"]
        details = ft.Column(spacing=4, visible=is_open)
        if len(entries) > 10:
            details.height = 300
            details.scroll = ft.ScrollMode.AUTO
        rows = []
        for e in entries:
            row = _item_row(kind, e)
            rows.append((e, row))
            details.controls.append(row)

        chevron = ft.Icon(
            ft.Icons.KEYBOARD_ARROW_DOWN if is_open else ft.Icons.KEYBOARD_ARROW_RIGHT,
            size=18, color=TEXT_DIM)
        count_badge = ft.Text(str(len(entries)), size=12, color=TEXT_FAINT)
        header = attach_hover(
            ft.Container(
                content=ft.Row(
                    [
                        chevron,
                        ft.Text(label, size=13.5, color=TEXT,
                                weight=ft.FontWeight.W_600, expand=True),
                        count_badge,
                    ],
                    spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                border_radius=RADIUS, padding=ft.padding.Padding.symmetric(
                    horizontal=10, vertical=8),
                ink=False,
                on_click=lambda e, d=details, c=chevron, k=kind: _toggle(d, c, k),
            ),
            None, SURFACE_HI,
        )
        group_col = ft.Column([header, details], spacing=4)
        state["groups"].append({
            "kind": kind, "rows": rows, "details": details,
            "chevron": chevron, "group_col": group_col,
        })
        return group_col

    def _toggle(details, chevron, kind):
        open_ = not details.visible
        details.visible = open_
        if open_:
            state["open"].add(kind)
        else:
            state["open"].discard(kind)
        # ft.Icon's glyph attribute is `.icon` (NOT `.name`) on every Flet
        # version we support - setting .name silently leaves the old arrow.
        chevron.icon = (ft.Icons.KEYBOARD_ARROW_DOWN if open_
                        else ft.Icons.KEYBOARD_ARROW_RIGHT)
        thread_safe_ui.refresh(details)
        thread_safe_ui.refresh(chevron)

    def _item_row(kind, e):
        already = e.get("already")
        meta_bits = []
        if already:
            meta_bits.append(already.rstrip(".").lower())
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
            "Import to...", icon=ft.Icons.DOWNLOAD_ROUNDED, height=28,
        )
        # Bind after creation so the handler can disable the button while the
        # (threaded) import runs.
        import_btn.on_click = lambda ev, ent=e, btn=import_btn: _open_picker(ent, btn)

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

    # --- Import-to picker --------------------------------------------------
    def _picker_model(entry):
        """Per-instance rows for the picker: (instance, ok, reason)."""
        out = []
        for inst in _instances():
            ok, reason = importer.instance_compatibility(
                entry, inst["mc_version"], inst["loader"])
            already = False
            if ok:
                try:
                    already = importer.already_in_profile(
                        entry, inst["mc_version"], inst["loader"])
                except Exception:
                    already = False
            if already:
                out.append((inst, False, "Already installed"))
            else:
                out.append((inst, ok, reason))
        return out

    def _open_picker(entry, btn=None):
        model = _picker_model(entry)
        if not model:
            snack("No installed instances yet - install a version on the "
                  "Play tab first.", danger=True)
            return

        dlg_holder = {"dlg": None}

        rows = []
        for inst, ok, reason in model:
            sub_bits = [inst["mc_version"] or "?", inst["loader"]]
            if reason:
                sub_bits.append(reason)
            row = ft.Container(
                content=ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text(inst["label"], size=13, color=TEXT,
                                        weight=ft.FontWeight.W_500,
                                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text("  ·  ".join(sub_bits), size=11,
                                        color=TEXT_FAINT, font_family=FONT_MONO,
                                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                            ],
                            spacing=1, expand=True,
                        ),
                        ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, size=16, color=TEXT_DIM)
                        if ok else
                        ft.Icon(ft.Icons.LOCK_ROUNDED, size=16, color=TEXT_FAINT),
                    ],
                    spacing=10, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=10, vertical=8),
                opacity=1.0 if ok else 0.45,
                on_click=(lambda ev, ent=entry, i=inst:
                          _pick_and_install(ent, i, dlg_holder.get("dlg"), btn))
                if ok else None,
                ink=False,
            )
            rows.append(row)

        dlg = ft.AlertDialog(
            modal=True,
            title=ft.Text(f"Import '{entry['name']}' to...",
                          size=15, weight=ft.FontWeight.W_600, color=TEXT),
            content=ft.Container(
                content=ft.Column(rows, spacing=4, scroll=ft.ScrollMode.AUTO),
                width=420, height=min(360, 56 + 52 * len(rows)),
            ),
            actions=[ft.TextButton("Cancel", on_click=lambda e: _close_picker(dlg, btn))],
            actions_alignment=ft.MainAxisAlignment.END,
            bgcolor=SURFACE,
        )
        dlg_holder["dlg"] = dlg
        try:
            from cubeon import dialogs as cubeon_dialogs
            cubeon_dialogs.open_dialog(page, dlg)
        except Exception:
            snack("Couldn't open the instance list.", danger=True)
            if btn is not None:
                btn.disabled = False
                thread_safe_ui.refresh(btn)

    def _close_picker(dlg, btn=None):
        try:
            from cubeon import dialogs as cubeon_dialogs
            if hasattr(cubeon_dialogs, "close_dialog"):
                cubeon_dialogs.close_dialog(page, dlg)
            elif hasattr(dlg, "open"):
                dlg.open = False
                thread_safe_ui.refresh(dlg)
        except Exception:
            pass
        if btn is not None:
            btn.disabled = False
            thread_safe_ui.refresh(btn)

    def _pick_and_install(entry, inst, dlg=None, btn=None):
        if dlg is not None:
            _close_picker(dlg, btn)
        _import_one(entry, btn=btn, inst=inst)

    # --- import actions ----------------------------------------------------
    def _import_one(e, btn=None, inst=None):
        if inst is not None:
            mc = inst.get("mc_version")
            loader = inst.get("loader")
            vid = inst.get("version_id")
        else:
            mc, loader, vid = _target()
        if not mc:
            snack("Pick a game version on the Play tab first.", danger=True)
            return
        if not loader:
            loader = importer.loader_of(vid)
        if btn is not None:
            btn.disabled = True
            thread_safe_ui.refresh(btn)

        def worker():
            try:
                msg = importer.import_item(
                    e, mc_version=mc, loader=loader, version_id=vid,
                    status_cb=lambda s: _set_status(s))
                snack(msg)
                # Flip this row to "already in this profile" now that it is,
                # without collapsing groups the player had opened.
                _remark()
                if state.get("result") is not None:
                    _render(state["result"], status=msg)
                else:
                    _set_status(msg)
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

    # --- assemble the pane -------------------------------------------------
    _refresh_target()

    pane = ft.Column(
        [
            section_label("Import"),
            ft.Container(height=2),
            ft.Text(
                "Point Cubeon at any folder - an old .minecraft, a downloads "
                "folder, a backup - and it finds every mod, resource pack, "
                "shader pack, modpack and world inside. Search the finds, "
                "then Import to the instance you want - incompatible "
                "instances are greyed out.",
                size=12, color=TEXT_DIM,
            ),
            ft.Container(height=10),
            target_text,
            ft.Container(height=8),
            ft.Row([scan_btn, clear_btn], spacing=12),
            ft.Container(height=4),
            status_text,
            ft.Container(height=4),
            search_field,
            ft.Container(height=2),
            results_col,
        ],
        spacing=8, visible=False,
    )
    # Hooks so another surface (and the test harness) can drive a scan result
    # through the renderer without waiting on a real folder dialog. The pane's
    # own scan flow calls _render itself once scan_folder finishes.
    def _render_hook(result, status=None):
        state["result"] = result
        if result is not None:
            state["root"] = result.get("root") or state["root"]
        _render(result, status=status)

    pane.render_scan_result = _render_hook
    pane.import_item_ui = _import_one
    pane.open_picker_ui = _open_picker
    pane.picker_model_ui = _picker_model
    pane.remark_installed_ui = _remark
    pane._results_col = results_col
    pane._status_text = status_text
    pane._search_field = search_field
    return pane
