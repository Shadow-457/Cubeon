"""
Cubeon - Modpacks tab UI.

Installing a modpack is a bigger, one-shot action than installing a single mod:
one click pulls a whole Minecraft version + mod loader + a fixed mod set + the
pack's config. So this tab is deliberately simpler than the Mods tab - no
per-version/loader picker, because the pack itself dictates those. You browse
Modrinth and CurseForge packs (or import a .mrpack / CurseForge .zip you already
have), hit Install, watch the progress, and the pack lands as a ready-to-play
version on the Play tab.

Because the pack dictates its own Minecraft version, browsing is NOT filtered
down to whatever is selected on the Play tab - a version-locked pack like
RLCraft (1.12.2 only) has to stay installable from any starting state.

Backed entirely by cubeon/modpacks.py via the launcher_core facade - see that
module for how CurseForge packs are converted into the one install pipeline.
"""

import os
import re
import subprocess
import threading

import flet as ft

from cubeon.theme import RADIUS, attach_hover, ACCENT_HI, ON_ACCENT  # blocky corner radius + hover helper/tokens
from cubeon import icons as _icons  # disk cache for Modrinth project art

import launcher_core as core
from cubeon import modpacks as modpacks_backend
from cubeon import thread_safe_ui  # control-level refresh() for per-file progress floods
from cubeon.paths import CUBEON_HOME


def build_modpacks_tab(page: ft.Page, cfg: dict, state: dict, *,
                        section_label, go_to_pack,
                        BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                        TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO):
    """
    Args:
        go_to_pack(meta): callback main.py provides - refresh the Play tab's
            version list, select this pack's launchable version, and switch to
            Play. Called both right after an install and when the user taps an
            already-installed pack.
    Returns:
        (modpacks_tab, refresh_installed_packs) - call refresh_installed_packs
        whenever the tab is opened so the 'Installed packs' list stays honest.
    """

    # One install at a time - the whole thing writes to a shared game dir, and
    # two packs installing at once would race each other's version/loader.
    busy = {"value": False}
    # Guards the one-time refresh of the 'Installed packs' list once an install
    # actually starts overwriting the target profile (see status_cb below). A
    # reinstall of an already-listed pack would otherwise keep showing its old
    # stale row - still Play-able - for the whole duration of the bar.
    installed_refresh_done = {"done": False}

    # --- Live install progress (hidden until an install starts) -------------
    install_status = ft.Text("", size=13, color=TEXT, font_family=FONT_MONO)
    install_bar = ft.ProgressBar(value=0, color=ACCENT, bgcolor=SURFACE_HI, border_radius=RADIUS)
    install_bar.data = 1  # holds the current phase's max (mirrors mods_tab pattern)
    install_card = ft.Container(
        content=ft.Column([install_status, install_bar], spacing=10),
        bgcolor=SURFACE, border=ft.border.Border.all(1, ACCENT_DIM), border_radius=RADIUS,
        padding=16, visible=False,
    )

    def status_cb(text):
        install_status.value = text
        install_status.color = TEXT
        # The core installer deletes the target profile's _modpack.json marker
        # the instant its rebuild starts (before downloading the MC version).
        # Refresh the list at that first destructive step so a pack being
        # reinstalled stops showing as "Installed" while the bar runs; it
        # reappears when _end_install_ok refreshes again on success.
        if (busy["value"] and not installed_refresh_done["done"]
                and (text.startswith("Installing Minecraft")
                     or text.startswith("Downloading mods"))):
            installed_refresh_done["done"] = True
            refresh_installed_packs()
        # Per-file flood: repaint just the status line + bar.
        thread_safe_ui.refresh(install_status)
        thread_safe_ui.refresh(install_bar)

    def progress_cb(val):
        mx = install_bar.data or 1
        install_bar.value = (val / mx) if mx else None
        thread_safe_ui.refresh(install_bar)

    def max_cb(val):
        install_bar.data = val or 1
        thread_safe_ui.refresh(install_bar)

    def _begin_install():
        busy["value"] = True
        installed_refresh_done["done"] = False
        install_card.visible = True
        install_bar.value = None  # indeterminate until the first real progress
        install_bar.data = 1
        install_status.value = "Starting..."
        install_status.color = TEXT
        page.update()

    def _end_install_ok(meta):
        busy["value"] = False
        install_status.value = f"Installed {meta.get('name', 'modpack')} ✓"
        install_status.color = ACCENT
        install_bar.value = 1
        page.update()
        refresh_installed_packs()
        _render_page()  # so its Install button flips to "Installed"
        # Hand off to the Play tab so the pack is immediately playable.
        try:
            go_to_pack(meta)
        except Exception:
            pass

    def _end_install_err(message):
        busy["value"] = False
        install_status.value = message
        install_status.color = DANGER
        install_bar.value = 0
        page.update()

    def run_install(*, url=None, file_path=None, cf_file=None):
        """cf_file: a get_modpack_file() result with source='curseforge' -
        installed through the CF->mrpack converter instead of the raw-mrpack
        path (a CurseForge zip isn't an .mrpack)."""
        if busy["value"]:
            return
        _begin_install()

        def worker():
            try:
                if cf_file is not None:
                    meta = core.install_modpack_from_cf(
                        cf_file["project_id"], cf_file["file_id"],
                        progress_cb=progress_cb, status_cb=status_cb, max_cb=max_cb)
                elif url is not None:
                    meta = core.install_modpack_from_url(
                        url, progress_cb=progress_cb, status_cb=status_cb, max_cb=max_cb)
                else:
                    meta = core.install_modpack_from_file(
                        file_path, progress_cb=progress_cb, status_cb=status_cb, max_cb=max_cb)
                _end_install_ok(meta)
            except core.ModpackError as me:
                _end_install_err(str(me))
            except Exception as ex:
                # mll surfaces its own exceptions (e.g. UnsupportedVersion)
                # with a version/build number in the message, which reads as
                # jargon since it's rarely the actual MC version the user
                # picked - it's usually the loader build the pack declared
                # for a version the launcher was never asked to install.
                # get_modpack_file() should already have refused an
                # incompatible pack before this point; if mll still raised,
                # say so plainly instead of showing the raw exception.
                type_name = type(ex).__name__
                if type_name in ("UnsupportedVersion", "VersionNotFound", "ExternalProgramError"):
                    _end_install_err(
                        "This modpack's Minecraft version or mod loader build "
                        "isn't supported by the installer. Try a different pack "
                        f"or a different published version of this one. ({ex})"[:220]
                    )
                else:  # network, disk, or anything else - keep the message visible
                    _end_install_err(f"Install failed: {type_name}: {ex}"[:200])

        threading.Thread(target=worker, daemon=True).start()

    # --- Install from a local .mrpack file ----------------------------------

    def handle_mrpack_files(files):
        if not files or busy["value"]:
            return
        run_install(file_path=files[0].path)

    def on_mrpack_picked(e):
        # Old-Flet path: pick_files() ran synchronously and the result
        # arrives here via on_result. Untyped rather than annotated as
        # ft.FilePickerResultEvent - missing on some pinned Flet builds
        # (e.g. 0.86.x), which would crash this def at import time.
        handle_mrpack_files(e.files)

    mrpack_picker = ft.FilePicker()
    mrpack_picker.on_result = on_mrpack_picked

    # Same version-spanning FilePicker registration dance used elsewhere in the
    # app (skin_tab.py, mods_tab.py): newer Flet self-registers Services, older
    # Flet needs the explicit overlay append.
    _registered = False
    _services_list = getattr(page, "_services", None)
    _already = (
        _services_list is not None
        and hasattr(_services_list, "_services")
        and mrpack_picker in _services_list._services
    )
    _register_fn = getattr(page, "register_service", None)
    if _already:
        _registered = True
    elif callable(_register_fn):
        try:
            _register_fn(mrpack_picker)
            _registered = True
        except Exception:
            _registered = False
    if not _registered:
        try:
            if mrpack_picker not in page.overlay:
                page.overlay.append(mrpack_picker)
        except Exception:
            pass

    def open_mrpack_picker(e):
        if busy["value"]:
            return
        core.run_file_picker(
            page, mrpack_picker,
            on_files=handle_mrpack_files,
            dialog_title="Choose a modpack (.mrpack or CurseForge .zip)",
            allow_multiple=False,
            allowed_extensions=["mrpack", "zip"],
        )

    # --- Create (author + export) a modpack ---------------------------------
    # The mirror of installing: pick one installed (version, loader) profile,
    # choose which of its mods to include, and write it back out as a .mrpack.
    # There's no cross-version FilePicker "save" helper in this app (only the
    # pick_files open flow), so exports land in CUBEON_HOME and we open that
    # folder for the user instead of prompting for a path.

    def _open_folder(path):
        """Reveal a folder in the OS file manager - same cross-platform
        approach as cubeon/mods.py's open_mods_folder()."""
        try:
            if os.name == "nt":
                os.startfile(path)
            elif os.uname().sysname == "Darwin":
                subprocess.Popen(["open", path])
            else:
                subprocess.Popen(["xdg-open", path])
        except Exception:
            pass

    def _pack_filename(name, version):
        """A safe .mrpack filename stem from the pack name + version."""
        stem = "".join(c if (c.isalnum() or c in "-_.") else "_"
                       for c in f"{name}-{version}").strip("_.")
        return (stem or "modpack") + ".mrpack"

    def open_create_dialog(e=None):
        if busy["value"]:
            return
        try:
            profiles = [p for p in core.list_profiles() if p.get("mod_count")]
        except Exception:
            profiles = []

        name_field = ft.TextField(
            label="Pack name", value="", border_color=BORDER, focused_border_color=ACCENT,
            color=TEXT, label_style=ft.TextStyle(color=TEXT_DIM),
            bgcolor=SURFACE_HI, border_radius=RADIUS, height=52,
        )
        version_field = ft.TextField(
            label="Version", value="1.0.0", border_color=BORDER, focused_border_color=ACCENT,
            color=TEXT, label_style=ft.TextStyle(color=TEXT_DIM),
            bgcolor=SURFACE_HI, border_radius=RADIUS, height=52,
        )
        desc_field = ft.TextField(
            label="Description (optional)", value="", multiline=True, min_lines=1, max_lines=3,
            border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
            label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI, border_radius=RADIUS,
        )
        profile_dd = ft.Dropdown(
            label="Version and loader", border_color=BORDER, focused_border_color=ACCENT,
            color=TEXT, label_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI,
            options=[
                ft.dropdown.Option(
                    key=p["key"],
                    text=f"{p.get('mc_version', '?')} · {(p.get('loader') or 'vanilla').title()}"
                         f" ({p.get('mod_count', 0)} mods)",
                )
                for p in profiles
            ],
        )
        mods_column = ft.Column(spacing=2, scroll=ft.ScrollMode.AUTO)
        mod_checks = []  # rebuilt whenever the selected profile changes
        create_status = ft.Text("", size=12, color=TEXT_DIM)

        def selected_profile():
            return next((p for p in profiles if p["key"] == profile_dd.value), None)

        def rebuild_mods(_=None):
            mod_checks.clear()
            mods_column.controls.clear()
            p = selected_profile()
            if not p:
                mods_column.controls.append(ft.Text("Pick a version and loader above.",
                                                    size=12, color=TEXT_DIM))
                page.update()
                return
            try:
                mods = core.list_mods(p["mc_version"], p["loader"])
            except Exception as ex:
                mods_column.controls.append(ft.Text(f"Couldn't read mods: {ex}", size=12, color=DANGER))
                page.update()
                return
            if not mods:
                mods_column.controls.append(ft.Text("This profile has no mods.", size=12, color=TEXT_DIM))
                page.update()
                return
            for m in mods:
                label = m["display_name"] + ("" if m["enabled"] else " (disabled)")
                cb = ft.Checkbox(label=label, value=True, active_color=ACCENT,
                                 label_style=ft.TextStyle(color=TEXT, size=13))
                cb.data = m["filename"]  # exact filename the backend expects
                mod_checks.append(cb)
                mods_column.controls.append(cb)
            page.update()

        profile_dd.on_change = rebuild_mods

        def close_dlg():
            # Same old/new-Flet compatibility fallback used across the app.
            if hasattr(page, "close"):
                page.close(dlg)
            else:
                dlg.open = False
                page.update()

        def do_create(e=None):
            if busy["value"]:
                return
            p = selected_profile()
            if not p:
                create_status.value = "Pick a version and loader first."
                create_status.color = DANGER
                page.update()
                return
            name = (name_field.value or "").strip()
            version = (version_field.value or "").strip()
            if not name:
                name_field.error_text = "Enter a pack name."
                page.update()
                return
            name_field.error_text = None
            if not version:
                version_field.error_text = "Enter a version."
                page.update()
                return
            version_field.error_text = None
            picked = [cb.data for cb in mod_checks if cb.value]

            busy["value"] = True
            create_status.value = "Exporting..."
            create_status.color = TEXT
            page.update()

            def cb_status(text):
                create_status.value = text
                create_status.color = TEXT
                page.update()

            def worker():
                try:
                    dest = os.path.join(CUBEON_HOME, _pack_filename(name, version))
                    out = modpacks_backend.export_mrpack(
                        name, version, p["mc_version"], p["loader"], picked, dest,
                        description=(desc_field.value or "").strip(),
                        summarize_cb=cb_status,
                    )
                    create_status.value = f"Saved to {out} ✓"
                    create_status.color = ACCENT
                    page.update()
                    _open_folder(CUBEON_HOME)  # reveal the .mrpack for the user
                except modpacks_backend.ModpackError as me:
                    create_status.value = str(me)
                    create_status.color = DANGER
                    page.update()
                except Exception as ex:
                    create_status.value = f"Export failed: {type(ex).__name__}: {ex}"[:200]
                    create_status.color = DANGER
                    page.update()
                finally:
                    busy["value"] = False

            threading.Thread(target=worker, daemon=True).start()

        # Preselect the first profile so its mods are shown immediately.
        if profiles:
            profile_dd.value = profiles[0]["key"]
            rebuild_mods()
        else:
            mods_column.controls.append(
                ft.Text("No installed mods to export yet. Add mods in the Mods tab first.",
                        size=12, color=TEXT_DIM))

        dlg = ft.AlertDialog(
            modal=True, bgcolor=SURFACE,
            title=ft.Text("Create modpack", color=TEXT, weight=ft.FontWeight.W_800),
            content=ft.Container(
                content=ft.Column(
                    [
                        name_field,
                        # expand ratios instead of intrinsic widths - the
                        # "Version and loader" text ("1.21.11 · Fabric (N mods)")
                        # is long enough to overflow the fixed-width dialog when
                        # the dropdown sizes to its content, which clipped it off
                        # the right edge. Constraining both to share the row width
                        # keeps them inside the dialog.
                        ft.Row(
                            [ft.Container(content=version_field, expand=2),
                             ft.Container(content=profile_dd, expand=3)],
                            spacing=10,
                        ),
                        desc_field,
                        ft.Text("Mods to include", size=12, color=TEXT_DIM),
                        ft.Container(content=mods_column, height=180),
                        create_status,
                    ],
                    spacing=12, tight=True,
                ),
                width=440,
            ),
            actions=[
                ft.TextButton("Cancel", on_click=lambda e: close_dlg()),
                ft.TextButton("Export .mrpack", on_click=do_create,
                              style=ft.ButtonStyle(color=ACCENT)),
            ],
        )
        if hasattr(page, "open"):
            page.open(dlg)
        else:
            dlg.open = True
            page.dialog = dlg
            if dlg not in page.overlay:
                page.overlay.append(dlg)
            page.update()

    # --- Browse Modrinth modpacks -------------------------------------------

    search_field = ft.TextField(
        hint_text="Search modpacks... e.g. better mc",
        border_color=BORDER, focused_border_color=ACCENT, color=TEXT,
        hint_style=ft.TextStyle(color=TEXT_DIM), bgcolor=SURFACE_HI,
        border_radius=RADIUS, height=48, prefix_icon=ft.Icons.SEARCH_ROUNDED,
        on_submit=lambda e: run_search(),  # Enter = search immediately
        on_change=lambda e: _schedule_live_search(),  # typing = debounced search
        expand=True,
    )

    results_view = ft.Column(spacing=8)
    browse_status = ft.Text("", size=12, color=TEXT_DIM)
    browse_title = ft.Text("Popular modpacks", size=12,
                           color=TEXT_DIM, font_family=FONT_MONO)
    browse_state = {"results": [], "page": 0}
    PAGE_SIZE = 5

    pager_label = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO)
    pager_prev = ft.Container(content=ft.Icon(ft.Icons.CHEVRON_LEFT_ROUNDED, size=18, color=TEXT),
                              padding=6, border_radius=RADIUS, ink=True)
    pager_next = ft.Container(content=ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=18, color=TEXT),
                              padding=6, border_radius=RADIUS, ink=True)
    pager_row = ft.Row([pager_prev, pager_label, pager_next],
                       alignment=ft.MainAxisAlignment.CENTER, spacing=4, visible=False)

    def render_results(results, empty_msg):
        browse_state["results"] = results or []
        browse_state["empty_msg"] = empty_msg
        browse_state["page"] = 0
        _render_page()

    def installed_pack_tokens() -> set:
        """Punctuation-free tokens of installed modpack *names*, so a Modrinth
        browse result that's already installed shows 'Installed' next to the
        name instead of another Install button. Installing a pack doesn't
        persist its Modrinth project id, so this matches by name - best-effort,
        the same way the resource-pack/shader tabs match on filename. A miss
        only leaves the Install button in place."""
        tokens = set()
        for p in core.list_installed_modpacks():
            token = re.sub(r"[^a-z0-9]+", "", (p.get("name") or "").lower())
            if token:
                tokens.add(token)
        return tokens

    def _render_page():
        results = browse_state["results"]
        total_pages = max(1, -(-len(results) // PAGE_SIZE))
        page_num = max(0, min(browse_state["page"], total_pages - 1))
        browse_state["page"] = page_num

        results_view.controls.clear()
        if not results:
            results_view.controls.append(
                ft.Text(browse_state.get("empty_msg", ""), size=13, color=TEXT_DIM))
        else:
            installed = installed_pack_tokens()
            start = page_num * PAGE_SIZE
            for pack in results[start:start + PAGE_SIZE]:
                title = re.sub(r"[^a-z0-9]+", "", (pack.get("title") or "").lower())
                slug = re.sub(r"[^a-z0-9]+", "", (pack.get("slug") or "").lower())
                is_installed = (bool(title) and title in installed) or \
                    (bool(slug) and slug in installed)
                results_view.controls.append(build_pack_row(pack, is_installed))

        browse_status.value = f"{len(results)} packs" if results else ""
        pager_label.value = f"Page {page_num + 1} of {total_pages}"
        pager_row.visible = len(results) > PAGE_SIZE
        pager_prev.disabled = page_num <= 0
        pager_next.disabled = page_num >= total_pages - 1
        page.update()

    def _prev(e=None):
        if browse_state["page"] > 0:
            browse_state["page"] -= 1
            _render_page()

    def _next(e=None):
        total_pages = max(1, -(-len(browse_state["results"]) // PAGE_SIZE))
        if browse_state["page"] < total_pages - 1:
            browse_state["page"] += 1
            _render_page()

    pager_prev.on_click = _prev
    pager_next.on_click = _next

    def load_popular():
        search_gen["v"] += 1
        gen = search_gen["v"]
        browse_title.value = "POPULAR MODPACKS"
        browse_status.value = "Loading..."
        results_view.controls.clear()
        # Loading state: repaint just the browse region.
        thread_safe_ui.refresh(results_view)
        thread_safe_ui.refresh(browse_status)
        thread_safe_ui.refresh(browse_title)
        wanted_mc = state.get("selected_mc_version")

        def worker():
            try:
                results = core.get_popular_modpacks(mc_version=wanted_mc)
            except Exception as ex:
                if gen != search_gen["v"]:
                    return
                browse_status.value = "Couldn't load the list - check your internet."
                thread_safe_ui.refresh(browse_status)
                return
            if gen != search_gen["v"]:
                return  # a newer search/popular-load took over while we fetched
            render_results(results, empty_msg="No modpacks found.")
            if not core.curseforge_enabled():
                # CurseForge classics (RLCraft, SkyFactory, ...) ARE included
                # now, keyless via cfwidget. The optional key unlocks full
                # search + faster installs - but that's detail for the hover,
                # not a sentence on the page.
                browse_status.value = "Includes CurseForge classics."
                browse_status.tooltip = (
                    "Popular CurseForge packs like RLCraft and SkyFactory are "
                    "included. Power users: adding a free CurseForge key to "
                    "config.json unlocks the full catalogue and faster installs.")
                thread_safe_ui.refresh(browse_status)

        threading.Thread(target=worker, daemon=True).start()

    # Search runs in TWO PHASES: Modrinth results render the moment their
    # (fast) request lands, then CurseForge hits are merged in when the
    # slower cfwidget probes finish - the user reads real results instead of
    # watching a spinner for the worst of the two providers. The generation
    # counter makes a slow older search unable to overwrite a newer one.
    search_gen = {"v": 0}
    _search_debounce = {"timer": None}

    def _schedule_live_search(e=None):
        """Debounced on_change: cancel any pending search, start a new one
        (same pattern as the Mods tab)."""
        pending = _search_debounce["timer"]
        if pending is not None:
            pending.cancel()
        _search_debounce["timer"] = threading.Timer(0.45, run_search)
        _search_debounce["timer"].daemon = True
        _search_debounce["timer"].start()

    def run_search():
        query = search_field.value.strip()
        if not query:
            load_popular()
            return
        search_gen["v"] += 1
        gen = search_gen["v"]
        browse_title.value = f'RESULTS FOR "{query.upper()}"'
        browse_status.value = "Searching..."
        results_view.controls.clear()
        page.update()
        wanted_mc = state.get("selected_mc_version")

        def mr_worker():
            try:
                results = core.search_modpacks_modrinth(query, mc_version=wanted_mc)
            except Exception as ex:
                if gen != search_gen["v"]:
                    return
                browse_status.value = "Search failed - check your internet."
                page.update()
                return
            if gen != search_gen["v"]:
                return
            render_results(results, empty_msg="No modpacks found for that search.")

        def cf_worker():
            try:
                cf = core.search_modpacks_curseforge(query, mc_version=wanted_mc)
            except Exception:
                return  # CF is optional; Modrinth results already rendered
            if gen != search_gen["v"] or not cf:
                return
            merged = core.merge_modpack_hits(
                browse_state.get("results") or [], cf, query)
            render_results(merged, empty_msg="No modpacks found for that search.")
            if any(h.get("source") == "curseforge" for h in merged):
                browse_status.value = f"{len(merged)} packs found."
                browse_status.tooltip = (
                    "Results mix Modrinth and CurseForge classics. Power "
                    "users: a free CurseForge key in config.json unlocks the "
                    "full CurseForge catalogue.")

        threading.Thread(target=mr_worker, daemon=True).start()
        threading.Thread(target=cf_worker, daemon=True).start()

    def build_pack_row(pack, is_installed=False):
        install_btn_text = ft.Text(
            "Installed" if is_installed else "Install",
            size=13, weight=ft.FontWeight.W_600,
            color=TEXT_DIM if is_installed else BG,
        )
        install_btn = ft.Container(
            content=ft.Row(
                [ft.Icon(ft.Icons.CHECK_ROUNDED if is_installed else ft.Icons.DOWNLOAD_ROUNDED,
                         color=TEXT_DIM if is_installed else BG, size=16),
                 install_btn_text],
                spacing=6, tight=True,
            ),
            bgcolor=None if is_installed else ACCENT,
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
            ink=not is_installed,
            disabled=is_installed,
        )

        def on_install(e):
            if busy["value"]:
                return
            install_btn.disabled = True
            install_btn_text.value = "Preparing..."
            page.update()

            def worker():
                try:
                    # Prefer a pack build matching the Minecraft version
                    # selected on the Play tab, so a pack that publishes for
                    # several versions installs the one the user is actually
                    # using (that's what keeps mll from being handed a
                    # version/loader combination nobody asked for - see
                    # get_modpack_file()'s docstring).
                    wanted_mc = state.get("selected_mc_version")
                    file_info = None
                    if wanted_mc:
                        file_info = core.get_modpack_file(pack["project_id"],
                                                          mc_version=wanted_mc)
                    if not file_info or not file_info.get("url"):
                        # ...but do not *require* a match. A modpack declares and
                        # installs its own Minecraft version + loader, so it need
                        # not agree with the Play tab at all. Refusing on mismatch
                        # made every version-locked classic uninstallable: RLCraft
                        # is 1.12.2-only, so unless the user happened to have
                        # 1.12.2 selected first, the only pack anyone actually
                        # asks for by name could never be installed.
                        file_info = core.get_modpack_file(pack["project_id"])
                    if not file_info or not file_info.get("url"):
                        _end_install_err(f"{pack['title']} has no installable version.")
                        install_btn.disabled = False
                        install_btn_text.value = "Install"
                        page.update()
                        return
                    if file_info.get("source") == "curseforge":
                        run_install(cf_file=file_info)
                    else:
                        run_install(url=file_info["url"])
                except Exception as ex:
                    _end_install_err(f"Couldn't start install: {ex}"[:200])
                finally:
                    install_btn.disabled = False
                    install_btn_text.value = "Install"
                    # No coalesced-progress flush needed: progress callbacks
                    # repaint their own controls directly.
                    page.update()

            threading.Thread(target=worker, daemon=True).start()

        if not is_installed:
            install_btn.on_click = on_install

        description = (pack.get("description") or "")
        if len(description) > 90:
            description = description[:87] + "..."

        # Cheap, advisory-only compatibility hint from the search hit's own
        # `versions` list (already returned by /search - no extra request).
        # This is NOT authoritative: Modrinth's search index can lag behind
        # what /project/<id>/version actually reports, which is exactly why
        # get_modpack_file() re-checks for real at install time regardless
        # of what's shown here. Phrased as information, not a warning: the
        # pack installs its own Minecraft version, so a mismatch with the
        # Play tab is normal and no longer blocks the install.
        wanted_mc = state.get("selected_mc_version")
        pack_versions = pack.get("versions") or []
        known_mismatch = bool(wanted_mc and pack_versions and wanted_mc not in pack_versions)
        meta_line = f"{pack.get('downloads', 0):,} downloads"
        if known_mismatch:
            meta_line += "  ·  installs its own Minecraft version"

        _icons.prefetch(pack.get("icon_url"))  # cache art for the next render
        icon = (
            ft.Image(src=_icons.src(pack.get("icon_url")),
                     width=48, height=48,
                     border_radius=RADIUS, fit=ft.BoxFit.COVER) if pack.get("icon_url") else
            ft.Container(width=48, height=48, bgcolor=SURFACE, border_radius=RADIUS,
                         content=ft.Icon(ft.Icons.INVENTORY_2_ROUNDED, color=TEXT_DIM, size=22),
                         alignment=ft.Alignment.CENTER)
        )
        return ft.Container(
            content=ft.Row(
                [
                    icon,
                    ft.Column(
                        [
                            ft.Text(pack["title"], size=14, color=TEXT, weight=ft.FontWeight.W_700),
                            ft.Text(description, size=11, color=TEXT_DIM),
                            ft.Text(meta_line, size=10,
                                    color=TEXT_DIM,
                                    font_family=FONT_MONO),
                        ],
                        spacing=2, expand=True,
                    ),
                    install_btn,
                ],
                spacing=12,
            ),
            bgcolor=SURFACE_HI, border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=14, vertical=10),
        )

    # --- Installed packs -----------------------------------------------------

    installed_view = ft.Column(spacing=8)
    installed_count = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO)
    delete_status = ft.Text("", size=12, color=TEXT_DIM)

    def _close_any_dialog(dlg):
        # Same old/new-Flet compatibility fallback used elsewhere in this file.
        if hasattr(page, "close"):
            page.close(dlg)
        else:
            dlg.open = False
            page.update()

    def _open_any_dialog(dlg):
        if hasattr(page, "open"):
            page.open(dlg)
        else:
            dlg.open = True
            page.dialog = dlg
            if dlg not in page.overlay:
                page.overlay.append(dlg)
            page.update()

    def _play_installed(m):
        """Installed-pack Play button. While another install is running the
        disk behind an already-listed pack may be mid-rewrite (its row is a
        moment away from being removed by the status_cb refresh), so launching
        would start a half-finished instance - refuse until the bar clears."""
        if busy["value"]:
            install_status.value = "Wait for the current install to finish before playing this pack."
            install_status.color = DANGER
            page.update()
            return
        go_to_pack(m)

    def build_installed_row(meta):
        loader = (meta.get("loader") or "vanilla").title()
        subtitle = f"{meta.get('mc_version', '?')} · {loader} · {meta.get('mod_count', 0)} mods"

        play_btn = attach_hover(ft.Container(
            content=ft.Row([ft.Icon(ft.Icons.PLAY_ARROW_ROUNDED, color=ON_ACCENT, size=16),
                            ft.Text("Play", size=13, weight=ft.FontWeight.W_700, color=ON_ACCENT)], spacing=4),
            bgcolor=ACCENT, border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=14, vertical=8), ink=True,
            on_click=lambda e, m=meta: _play_installed(m),
        ), ACCENT, ACCENT_HI)

        def do_delete(m):
            if busy["value"]:
                install_status.value = "Wait for the current install to finish before deleting packs."
                install_status.color = DANGER
                page.update()
                return
            version_id = m.get("version_id")
            name = m.get("name", "Modpack")

            def confirm(e=None):
                _close_any_dialog(dlg)
                # 1) Remove the installed Minecraft version this pack created,
                #    same call the Play tab's own "Delete instance" uses.
                deleted_version = False
                if version_id:
                    try:
                        core.delete_version(version_id)
                        deleted_version = True
                    except ValueError as ve:
                        # A missing/already-deleted version folder isn't
                        # fatal here - the tracking record still needs to
                        # go either way, which is exactly the stale-listing
                        # bug this button exists to let people fix by hand.
                        if "no longer exists" not in str(ve).lower():
                            delete_status.value = f"Couldn't delete {name}: {ve}"
                            delete_status.color = DANGER
                            page.update()
                            return
                # 2) Remove the modpack-tracking record so it stops being
                #    listed here, regardless of whether step 1 found a
                #    version folder to remove (covers the exact case this
                #    button was added for: a pack whose version was already
                #    deleted some other way and kept showing up anyway).
                try:
                    forgot = core.forget_modpack_for_version(version_id) if version_id else False
                except Exception:
                    forgot = False
                # 3) Keep config/state pointers consistent with the Play
                #    tab's own delete flow, in case this was the selected
                #    or last-launched version.
                if version_id:
                    labels = dict(cfg.get("version_labels") or {})
                    if labels.pop(version_id, None) is not None:
                        cfg["version_labels"] = labels
                    if cfg.get("last_version") == version_id:
                        cfg["last_version"] = None
                    if state.get("selected_version") == version_id:
                        state["selected_version"] = None
                    core.save_config(cfg)
                refresh_installed_packs()
                if deleted_version or forgot:
                    delete_status.value = f"Deleted {name}"
                    delete_status.color = ACCENT
                else:
                    delete_status.value = f"{name} had nothing left to delete."
                    delete_status.color = TEXT_DIM
                page.update()

            content_lines = [
                ft.Text(f"This permanently deletes '{name}' and its Minecraft "
                        "version from your versions folder.", size=13, color=TEXT),
            ]
            if not version_id:
                content_lines.append(
                    ft.Text("This pack has no linked version on disk - only its "
                            "tracking record will be removed.", size=12, color=TEXT_DIM))
            else:
                content_lines.append(
                    ft.Text("Your mods, skins, and worlds are not affected.",
                            size=12, color=TEXT_DIM))

            dlg = ft.AlertDialog(
                modal=True, bgcolor=SURFACE,
                title=ft.Text("Delete modpack?", color=TEXT, weight=ft.FontWeight.W_800),
                content=ft.Container(
                    content=ft.Column(content_lines, spacing=8, tight=True),
                    width=380,
                ),
                actions=[
                    ft.TextButton("Cancel", on_click=lambda e: _close_any_dialog(dlg)),
                    ft.TextButton("Delete", on_click=confirm, style=ft.ButtonStyle(color=DANGER)),
                ],
            )
            _open_any_dialog(dlg)

        delete_btn = ft.IconButton(
            ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color=DANGER, icon_size=20,
            tooltip="Delete this modpack",
            on_click=lambda e, m=meta: do_delete(m),
        )

        return ft.Container(
            content=ft.Row(
                [
                    ft.Container(width=44, height=44, bgcolor=SURFACE, border_radius=RADIUS,
                                 content=ft.Icon(ft.Icons.INVENTORY_2_ROUNDED, color=ACCENT, size=20),
                                 alignment=ft.Alignment.CENTER),
                    ft.Column(
                        [
                            ft.Text(meta.get("name", "Modpack"), size=14, color=TEXT, weight=ft.FontWeight.W_700),
                            ft.Text(subtitle, size=11, color=TEXT_DIM, font_family=FONT_MONO),
                        ],
                        spacing=2, expand=True,
                    ),
                    play_btn,
                    delete_btn,
                ],
                spacing=12,
            ),
            bgcolor=SURFACE_HI, border_radius=RADIUS,
            padding=ft.padding.Padding.only(left=10, right=10, top=8, bottom=8),
        )

    def refresh_installed_packs():
        try:
            packs = core.list_installed_modpacks()
        except Exception:
            packs = []
        installed_view.controls.clear()
        installed_count.value = f"{len(packs)} installed" if packs else ""
        if not packs:
            installed_view.controls.append(
                ft.Container(
                    content=ft.Column(
                        [
                            ft.Icon(ft.Icons.INVENTORY_2_OUTLINED, color=TEXT_DIM, size=28),
                            ft.Text("No modpacks installed yet", size=14, color=TEXT, weight=ft.FontWeight.W_600),
                            ft.Text("Install one above, or import a .mrpack file.", size=12, color=TEXT_DIM),
                        ],
                        horizontal_alignment=ft.CrossAxisAlignment.CENTER, spacing=4,
                    ),
                    padding=28, alignment=ft.Alignment.CENTER,
                )
            )
        else:
            for meta in packs:
                installed_view.controls.append(build_installed_row(meta))
        page.update()

    # --- Assemble ------------------------------------------------------------

    modpacks_tab = ft.Column(
        [
            ft.Row(
                [
                    ft.Column(
                        [
                            ft.Text("Modpacks", size=28, weight=ft.FontWeight.W_800, color=TEXT,
                                    font_family=FONT_DISPLAY),
                            ft.Text("Install a whole pack in one click - version, loader, mods and config together.",
                                    size=13, color=TEXT_DIM),
                        ],
                        spacing=2,
                    ),
                    ft.Container(expand=True),
                    attach_hover(ft.Container(
                        content=ft.Row(
                            [ft.Icon(ft.Icons.ADD_ROUNDED, color=ON_ACCENT, size=16),
                             ft.Text("Create modpack", color=ON_ACCENT, size=13, weight=ft.FontWeight.W_700)],
                            spacing=6,
                        ),
                        bgcolor=ACCENT, border_radius=RADIUS,
                        padding=ft.padding.Padding.symmetric(horizontal=14, vertical=10),
                        ink=True, on_click=open_create_dialog,
                    ), ACCENT, ACCENT_HI),
                    attach_hover(ft.Container(
                        content=ft.Row(
                            [ft.Icon(ft.Icons.UPLOAD_FILE_ROUNDED, color=TEXT, size=16),
                             ft.Text("Install from file", color=TEXT, size=13, weight=ft.FontWeight.W_600)],
                            spacing=6,
                        ),
                        border=ft.border.Border.all(1, BORDER), border_radius=RADIUS,
                        padding=ft.padding.Padding.symmetric(horizontal=14, vertical=10),
                        ink=True, on_click=open_mrpack_picker,
                    ), None, SURFACE_HI),
                ],
            ),
            ft.Container(height=14),
            install_card,
            ft.Container(height=6),
            ft.Row(
                [
                    search_field,
                    attach_hover(ft.Container(
                        content=ft.Text("Search", color=ON_ACCENT, weight=ft.FontWeight.W_700, size=13),
                        bgcolor=ACCENT, border_radius=RADIUS,
                        padding=ft.padding.Padding.symmetric(horizontal=18, vertical=13),
                        ink=True, on_click=lambda e: run_search(),
                    ), ACCENT, ACCENT_HI),
                ],
                spacing=10,
            ),
            ft.Container(height=10),
            ft.Row([browse_title, ft.Container(expand=True), browse_status],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            ft.Container(
                content=results_view,
                bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS, padding=16,
            ),
            pager_row,
            ft.Container(height=24),
            ft.Row([section_label("Installed packs"), ft.Container(expand=True), installed_count],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            delete_status,
            ft.Container(
                content=installed_view,
                bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER), border_radius=RADIUS, padding=16,
            ),
        ],
        spacing=8,
        scroll=ft.ScrollMode.AUTO,
    )

    return modpacks_tab, refresh_installed_packs, load_popular
