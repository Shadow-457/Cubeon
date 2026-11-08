"""
Cubeon - Mods tab UI.
Lets the user browse/download mods from Modrinth and manage the mods already
installed for the currently selected Minecraft version + loader.

This module defines the UI for the 'Mods' tab in the launcher. It is built
the same way as skin_tab.py: a build_mods_tab() function that main.py calls
once at startup, which returns the tab's root control plus a couple of
functions main.py needs to call from elsewhere (e.g. when the version or
loader switcher changes on the Play tab, the mods list needs to be
re-filtered for the new version+loader profile).
"""

# Standard library imports
import re          # For turning mod names into comparable "slugs"
import logging
import threading   # For running network calls in the background without freezing the UI
import time        # Throttle for the automatic problem check
import weakref

# Flet imports - Flet is a UI framework for Python (like Flutter)
import flet as ft
from cubeon import i18n
from cubeon.mod_loaders import MOD_CAPABLE_LOADERS
from cubeon.content import content_mc_versions
from cubeon import cubeonfriends
from cubeon.mods import resolve_profile_dir

from cubeon.theme import (  # design system: corner radius, on-accent fg, hover states
    RADIUS, ON_ACCENT, ACCENT_HI, INFO, attach_hover,
    TEXT_FAINT, CARD_FILL, CARD_BORDER, ROW_HOVER, ACCENT_TINT,
    quiet_chip, pixel_divider, animated_switch,
)

# Our own launcher core module - contains all the actual mod file/network logic
import launcher_core as core

from cubeon import icons as _icons  # disk cache for Modrinth project art
from cubeon import eta as cubeon_eta  # measured "time left" for downloads
from cubeon import status_text  # keeps "<... at 0x...>" out of labels
from cubeon import thread_safe_ui  # TREE_LOCK for safe background-tree writes
from cubeon import dialogs  # open/close dialogs across Flet versions
from cubeon import instances as instance_info  # the selected instance's real loader
from ui.install_feedback import InstallRegistry, compact_status, progress_text
from ui.content_states import loading_rows, empty_state
from ui.content_tiles import tile_grid, tile_capacity, layout_tiles, style_tile, downloads_label, content_header, update_view_action
from cubeon.background_refresh import BackgroundRefresh
from cubeon.icon_loader import IconLoader


def batch_progress_text(value: float, total: float, eta: "str | None" = None) -> str:
    """The download label for one batch of files.

    A single click can install several files: a mod plus its required
    dependencies (Sodium -> Fabric API) are reported by the core as ONE batch
    counted in FILE UNITS - int(value) files are already done, so int(value)+1
    is the file being fetched now. Saying "file 2/3" is what stops a
    multi-file install from reading as a stuck 0-100 loop, and the percent is
    still of the WHOLE batch, so it never falls back to 0 between files.

    `eta` is the measured "~2m left" from cubeon/eta.py, appended when the
    estimate is worth showing (see that module for why it often is not).
    """
    files = int(total) if total else 1
    pct = int(value * 100 / total) if total else 0
    left = f" · {eta}" if eta else ""
    if files <= 1:
        return f"Downloading… {pct}%{left}"
    now = min(int(value) + 1, files)
    return f"Downloading… {pct}% (file {now}/{files}){left}"


def mod_compatibility_note(mod: dict, mc_version: str | None, loader: str | None) -> str:
    if loader not in MOD_CAPABLE_LOADERS:
        return "Choose a mod loader on the Play tab."
    versions = mod.get("game_versions")
    loaders = mod.get("loaders")
    if mc_version and versions is not None and mc_version not in versions:
        return f"No build for Minecraft {mc_version}. Open the mod to see supported versions."
    if loaders is not None and loader not in loaders:
        return f"No {loader.title()} build. Open the mod to see supported loaders."
    return ""


def build_mods_tab(page: ft.Page, cfg: dict, state: dict, version_dropdown: ft.Dropdown, *,
                    section_label,
                    BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                    TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO,
                    switch_loader=None, modpacks_content=None, on_modpacks_open=None,
                    on_client_mod_change=None):
    """
    Builds the Mods tab's root control (a Flet Column) and returns it along
    with a couple of functions main.py needs to call from other tabs.

    Args:
        page: The Flet page instance - needed to trigger page.update() from callbacks.
        cfg: The live launcher configuration; managed Client switches share
             its preference with Settings rather than toggling a staged JAR.
        state: The shared mutable state dict from main.py. This module reads
               state["selected_mc_version"] and state["mod_loader"] - it never
               sets them, since those belong to the Play tab's version/loader
               controls; it only reacts to them.
        version_dropdown: The Play tab's version Dropdown control, needed to
               figure out which Minecraft version to search Modrinth against.
        section_label: Shared helper from main.py to create small section headings.
        BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM, TEXT, TEXT_DIM,
        DANGER, FONT_DISPLAY, FONT_MONO: Shared design tokens from main.py.

    Returns:
        A tuple (mods_tab, refresh_mods_list, load_recommended_mods, refresh_browse_for_new_profile):
          - mods_tab: ft.Column, the tab's root control.
          - refresh_mods_list: call this whenever the selected version or
            loader changes elsewhere in the app, so the Mods tab stays honest
            about which profile it's showing.
          - load_recommended_mods: call this the first time the user opens
            the Mods tab, to populate the browse section.
          - refresh_browse_for_new_profile: call this whenever the selected
            version or loader changes elsewhere in the app, so the Browse
            section (recommendations/search results) doesn't keep showing
            mods for a version/loader you've since switched away from.
    """

    # --- UI elements for the Mods tab ---

    # List of installed mods (will be populated by refresh_mods_list)
    mods_list_view = tile_grid()
    installed_count_text = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO)
    installed_show_all = {"value": False}
    installed_limit = {"value": 25}
    installed_snapshots = {}
    artwork = IconLoader()
    local_install_busy = {'value': False}
    picker_target = {'value': None}
    installed_rows = {}
    installed_collisions = set()
    browse_rows = {}
    install_registry = InstallRegistry()

    def _row_key(identity):
        return (_ct(), state.get("selected_mc_version"), state.get("mod_loader"),
                version_dropdown.value, identity)

    def _remember_row(cache, key, entry):
        cache[key] = entry
        if len(cache) > 200:
            cache.pop(next(iter(cache)))

    # Row-action feedback line (under the Installed header): toggle/remove
    # failures used to raise out of the click handler, which Flet swallows -
    # the switch/delete just looked dead. Surface the reason instead.
    installed_status = ft.Text("", size=11.5, color=TEXT_DIM,
                               font_family=FONT_MONO, visible=False)

    def _set_installed_status(t):
        with thread_safe_ui.TREE_LOCK:
            installed_status.value = t
            installed_status.visible = True
            thread_safe_ui.refresh(installed_status)

    # --- Installed-mod icons -------------------------------------------------
    # Installed jars only record their Modrinth *slug* in a sidecar file - the
    # icon the browse row showed isn't stored anywhere. So the installed list
    # renders instantly with a placeholder, then one bulk slug->icon lookup
    # (core.get_mod_icons, session-cached) patches real art in the moment it
    # lands. Manually-dropped jars have no slug and keep the placeholder.
    installed_icon_urls = {}   # slug -> icon URL (or None once resolved-and-missing)
    pending_icon_holders = {}  # slug -> [placeholder Containers awaiting art]
    icon_inflight = set()

    def _art_image(url, width=44, height=44, radius=RADIUS):
        cached_source = _icons.peek_src(url)
        image = ft.Image(
            src=cached_source if _icons.valid_source(cached_source) else 'icon_64.png',
            width=width, height=height, border_radius=radius,
            fit=ft.BoxFit.COVER, gapless_playback=True,
            data=url,
            error_content=ft.Image(src='icon_64.png', width=width, height=height, fit=ft.BoxFit.CONTAIN),
        )
        def ready(source):
            if image.data == url and image.src != source and _icons.valid_source(source):
                image.src = source
                thread_safe_ui.refresh(image)
        if url and not _icons.peek_src(url):
            artwork.request(url, ready)
        return image

    def _icon_image(url):
        return _art_image(url)

    def _make_installed_icon(m):
        """Embedded pack art, stored project art or a Cubeon logo fallback."""
        slug = m.get("slug")
        holder = ft.Container(
            width=44, height=44, bgcolor=CARD_FILL, border_radius=RADIUS,
            alignment=ft.Alignment.CENTER,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
        )
        url = m.get('icon_url') or (installed_icon_urls.get(slug) if slug else None)
        if _icons.valid_source(m.get('icon_source')):
            holder.content = ft.Image(src=m['icon_source'], width=44, height=44, fit=ft.BoxFit.COVER,
                                      border_radius=RADIUS, gapless_playback=True,
                                      error_content=ft.Image(src='icon_64.png', width=44, height=44))
        elif url:
            holder.content = _icon_image(url)
        else:
            holder.content = _art_image(None)
            if slug and slug not in installed_icon_urls:
                pending_icon_holders.setdefault(slug, []).append(weakref.ref(holder))
        return holder

    def _fetch_missing_icons():
        """Fires the bulk icon lookup for any placeholders rendered this pass
        and swaps the art in as each URL arrives. Runs off the UI thread;
        core.get_mod_icons memoises, so repeated refreshes don't re-fetch."""
        with thread_safe_ui.TREE_LOCK:
            slugs = [s for s in pending_icon_holders
                     if s not in installed_icon_urls and s not in icon_inflight]
            icon_inflight.update(slugs)
        if not slugs:
            return

        def worker():
            try:
                got = core.get_mod_icons(slugs)
            except Exception:
                with thread_safe_ui.TREE_LOCK:
                    icon_inflight.difference_update(slugs)
                return
            # Mutate the tree under the shared lock (see thread_safe_ui.py):
            # Flet's diff walks the control tree on the loop thread, and this
            # worker's holder swaps must never land mid-walk.
            with thread_safe_ui.TREE_LOCK:
                for s in slugs:
                    url = got.get(s)
                    installed_icon_urls[s] = url
                    holders = pending_icon_holders.pop(s, [])
                    if not url:
                        continue
                    for holder_ref in holders:
                        holder = holder_ref()
                        if holder is not None:
                            holder.content = _icon_image(url)
                icon_inflight.difference_update(slugs)
            # Control-level repaint scoped to the list region only: a
            # full-tree update from a worker thread is the redundant-diff
            # anti-pattern (the worker already mutated the tree under
            # TREE_LOCK above).
            thread_safe_ui.refresh(mods_list_view)

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception:
            with thread_safe_ui.TREE_LOCK:
                icon_inflight.difference_update(slugs)
            logging.getLogger(__name__).warning('icon lookup could not start', exc_info=True)

    # --- Category filters: collapsed behind a "..." button ------------------
    # A wrapped strip of a dozen chips ate a lot of vertical space above the
    # content, so they now live behind one small overflow button and only
    # unfold on demand. The button tints green while a non-All filter is
    # applied, so an active filter is never silently hidden.
    filters_open = {"value": False}

    def on_filters_toggle(e=None):
        filters_open["value"] = not filters_open["value"]
        category_chips_container.visible = filters_open["value"]
        filters_button.style = ft.ButtonStyle(color=TEXT_DIM)
        thread_safe_ui.refresh(category_chips_container)
        thread_safe_ui.refresh(filters_button)

    filters_button = ft.TextButton(i18n.t('Filters'), icon=ft.Icons.TUNE_ROUNDED,
                                  on_click=on_filters_toggle, data='mods-filters',
                                  style=ft.ButtonStyle(color=TEXT_DIM))

    # Filter field to search installed mods by name
    # Typing used to rebuild every row per keystroke (~120 ms with 300 mods
    # installed), which stutters while typing. Restart a short timer on each
    # keystroke and re-filter once it settles - the same debounce the browse
    # search box uses. Enter filters immediately.
    _filter_debounce = {"timer": None}

    def _run_mods_filter():
        """The debounce fires on a background thread; the rebuild mutates the
        tree, so take the shared lock (see cubeon/thread_safe_ui.py)."""
        try:
            with thread_safe_ui.TREE_LOCK:
                _render_installed_snapshot(_cached_installed())
        except Exception:
            pass

    def _schedule_mods_filter(e=None):
        pending = _filter_debounce["timer"]
        if pending is not None:
            pending.cancel()
        _filter_debounce["timer"] = threading.Timer(0.15, _run_mods_filter)
        _filter_debounce["timer"].daemon = True
        _filter_debounce["timer"].start()

    def _filter_now(e=None):
        pending = _filter_debounce["timer"]
        if pending is not None:
            pending.cancel()
        _run_mods_filter()

    installed_filter_field = ft.TextField(
        hint_text="Search installed mods...",
        border_color=CARD_BORDER,
        focused_border_color=ACCENT_DIM,
        color=TEXT,
        hint_style=ft.TextStyle(color=TEXT_DIM),
        text_style=ft.TextStyle(size=13),
        bgcolor=SURFACE_HI,
        border_radius=RADIUS,
        height=40,
        content_padding=ft.padding.Padding.symmetric(horizontal=12, vertical=12),
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        on_change=_schedule_mods_filter,  # Debounced - see above
        on_submit=_filter_now,            # Enter = filter immediately
    )

    def installed_slugs() -> set:
        """
        Returns a set of identifiers for installed mods. Includes each mod's
        canonical Modrinth slug (recorded in its sidecar meta when downloaded
        from Modrinth), its opaque Modrinth project id (the ONLY identifier a
        modpack manifest leaves behind - pack-installed mods have no slug, so
        without this every pack mod re-read as "not installed" in browse),
        plus a punctuation-free token of its display name, so a
        browse result reads as "already installed" whether it was pulled from
        Modrinth (exact slug match), installed by a modpack (project-id
        match), or dropped in as a local .jar (name-token
        match). Slug-only matching used to miss mods whose Modrinth slug
        differs from the hyphenated display name (e.g. "Mod Menu" -> slug
        "modmenu"), which re-showed the Download button on already-installed
        mods.
        """
        names = set()
        for m in _cached_installed('mod'):
            inst_slug = (m.get("slug") or "").lower()
            if inst_slug:
                names.add(inst_slug)
            inst_pid = (m.get("project_id") or "").strip()
            if inst_pid:
                names.add(inst_pid.lower())
            token = re.sub(r"[^a-z0-9]+", "", (m.get("display_name") or "").lower())
            if token:
                names.add(token)
            # The filename stem ("sodium-extra-fabric-0.8.7+mc26.1.1" ->
            # "sodium-extra"). CurseForge packs leave NO sidecar - their CDN
            # URLs carry no Modrinth id - so the stem is the only handle on
            # those jars, and it happens to equal Modrinth's compacted slug
            # for every pack mod checked. The raw display-name token above
            # ("sodiumextrafabric087mc2611") never matches anything.
            stem = re.sub(r"[^a-z0-9]+", "", (m.get("stem") or "").lower())
            if stem:
                names.add(stem)
                # Modrinth slugs often carry a loader word the jar's stem has
                # already had peeled ("c2me-fabric" jar -> stem "c2me", but the
                # project's slug is "c2me-fabric"), so register those variants
                # too. Loader-only suffixes, never anything that could collide
                # with a different mod's name.
                for sfx in ("fabric", "forge", "neoforge", "quilt"):
                    names.add(stem + sfx)
        return names

    def content_installed_tokens() -> set:
        """Cached per-instance filenames and recorded project identities.

        Filename tokens also recognize content installed without a sidecar.
        Disabled entries remain installed and can be re-enabled in Installed.
        """
        tokens = set()
        for it in _cached_installed():
            tokens.add(re.sub(r"[^a-z0-9]+", "", it["display_name"].lower()))
            for identity in (it.get('slug'), it.get('title')):
                if identity:
                    tokens.add(re.sub(r"[^a-z0-9]+", "", identity.lower()))
        return tokens

    def shader_requirement_installed() -> bool:
        """True once Iris or OptiFine is present in the current profile - the
        only two things that can actually load a shader pack. Sodium alone
        can't (it needs Iris), so it doesn't count. The Shaders segment's
        'install Iris' notice is only useful before this point, so it retires
        itself instead of nagging someone who already did it."""
        try:
            mods = _cached_installed('mod')
        except Exception:
            return False
        for m in mods:
            if not m.get('enabled'):
                continue
            name = re.sub(r"[^a-z0-9]+", "", (m.get("display_name") or "").lower())
            stem = str(m.get('stem') or m.get('slug') or '').lower()
            if stem in ('iris', 'optifine', 'oculus') or name.startswith(('iris', 'optifine', 'oculus')):
                return True
        return False

    def _installed_target(kind=None):
        return (kind or _ct(), state.get('selected_mc_version'),
                state.get('mod_loader'), version_dropdown.value)

    def _cached_installed(kind=None):
        return installed_snapshots.get(_installed_target(kind), [])

    def _is_client_mod(m):
        name = str(m.get('filename') or '').lower()
        return (name.startswith(('cubeon-client', 'cubeon-friends'))
                or m.get('slug') in ('cubeon-client', 'cubeon-friends'))

    def _installed_display_count():
        items = _cached_installed()
        backups = max(0, sum(_is_client_mod(m) for m in items) - 1) if _is_mod() else 0
        return len(items) - backups

    def _change_client_enabled(enabled):
        with thread_safe_ui.TREE_LOCK:
            changed = False
            try:
                if on_client_mod_change is not None:
                    if on_client_mod_change(enabled) is False:
                        raise RuntimeError('Could not save Cubeon Client settings')
                else:
                    existed, previous = 'client_mod_enabled' in cfg, cfg.get('client_mod_enabled', True)
                    cfg['client_mod_enabled'] = bool(enabled)
                    try:
                        core.save_config(cfg)
                    except Exception:
                        if existed:
                            cfg['client_mod_enabled'] = previous
                        else:
                            cfg.pop('client_mod_enabled', None)
                        raise
            except Exception as error:
                _set_installed_status(f"Could not save Cubeon Client settings: {error}")
            else:
                changed = True
                _set_installed_status(f"Cubeon Client {'enabled' if enabled else 'disabled'}. "
                                      'Applies to all instances on the next launch.')
            _render_installed_snapshot(_cached_installed())
            return changed

    def _client_browse_entry():
        # A local catalogue entry shares the normal Browse grid. Never alter
        # provider pages/offsets or offer a client for an unsupported profile.
        if (not _is_mod() or browse_state['page'] != 0
                or state.get('mod_loader') not in ('fabric', 'quilt', 'forge')
                or cubeonfriends.client_support_status(
                    state.get('selected_mc_version'), state.get('mod_loader')) is None
                or active_category['value'] not in ('', 'utility', 'social')):
            return None
        if any(word not in 'cubeon client cosmetics friends chat hud' for word in _browse_query().lower().split()):
            return None
        return dict(slug='cubeon-client', title='Cubeon Client', author='Cubeon',
                    description='Cosmetics, friends, chat and HUD controls.', builtin_client=True)

    def _install_client(target, feedback):
        with thread_safe_ui.TREE_LOCK:
            if (target != _installed_target('mod') or not _is_mod() or not _can_install('mod') or feedback.busy
                    or target[2] not in ('fabric', 'quilt', 'forge')
                    or cubeonfriends.client_support_status(target[1], target[2]) is None):
                return
            if not cfg.get('client_mod_enabled', True) and not _change_client_enabled(True):
                feedback.finish(error=installed_status.value)
                return
            if not feedback.start(text='Installing Cubeon Client...'):
                return

        def worker():
            try:
                profile = resolve_profile_dir(target[1], target[2], target[3])
                if not cubeonfriends.ensure_installed(target[1], target[2], profile):
                    raise RuntimeError('The matching Cubeon Client file is unavailable. Update the launcher and retry.')
                feedback.finish(note='Cubeon Client installed. Available on the next game launch.')
                _refresh_after_install(target)
            except Exception as error:
                feedback.finish(error=f"Couldn't install Cubeon Client: {error}")

        try:
            threading.Thread(target=worker, daemon=True, name='cubeon-client-install').start()
        except Exception as error:
            feedback.finish(error=f"Couldn't start Cubeon Client installation: {error}")

    def _mod_status(m):
        if _is_client_mod(m):
            return f"{'Enabled' if m['enabled'] else 'Disabled'} · Next launch · All instances"
        return f"{m['size_kb']:,.0f} KB  ·  {'Enabled' if m['enabled'] else 'Disabled'}"

    def _read_installed_snapshot(target):
        kind, mc, loader, version = target
        mods = core.list_mods(mc, loader, version_id=version) if kind in ('mod', 'shader') else None
        items = mods if kind == 'mod' else core.list_content(kind, mc, loader=loader, version_id=version)
        return target, items, mods

    def _apply_installed_snapshot(snapshot):
        target, items, mods = snapshot
        installed_snapshots[target] = items
        if mods is not None:
            installed_snapshots[('mod', *target[1:])] = mods
        while len(installed_snapshots) > 12:
            installed_snapshots.pop(next(iter(installed_snapshots)))
        if target == _installed_target():
            _render_installed_snapshot(items)
            _render_browse_page()

    def _installed_failed(error):
        _set_installed_status(f"Couldn't read installed content: {error}")
        mods_list_view.controls[:] = [empty_state('Couldn\'t read installed content',
                                                 'Try refreshing this instance.'),
                                     quiet_chip('Retry', on_click=lambda e: refresh_mods_list(background=True))]
        thread_safe_ui.refresh(mods_list_view)

    installed_refresh = BackgroundRefresh(_read_installed_snapshot, _apply_installed_snapshot,
                                         name='mods-refresh', failed=_installed_failed)

    def refresh_mods_list(*, background=False):
        target = _installed_target()
        if background:
            # Cached rows can paint immediately; filesystem/archive reads stay
            # on the worker even when this callback holds the UI tree lock.
            with thread_safe_ui.TREE_LOCK:
                _render_installed_snapshot(_cached_installed(), loading=target not in installed_snapshots)
            try:
                installed_refresh.request(target)
            except Exception as error:
                _set_installed_status(f"Couldn't refresh installed content: {error}")
            return
        installed_refresh.invalidate()
        snapshot = _read_installed_snapshot(target)
        with thread_safe_ui.TREE_LOCK:
            _apply_installed_snapshot(snapshot)

    def _refresh_after_install(target):
        # The installation has already succeeded. A repaint failure must not
        # turn that result into a failed download or encourage a second one.
        try:
            snapshot = _read_installed_snapshot(target)
            with thread_safe_ui.TREE_LOCK:
                if target == _installed_target():
                    installed_refresh.invalidate()
                    _apply_installed_snapshot(snapshot)
        except Exception:
            logging.getLogger(__name__).warning('post-install refresh failed', exc_info=True)

    def _render_installed_snapshot(all_mods, *, loading=False):
        """
        Reloads the installed list for whatever content type is active and
        updates the UI. Mods come from the per-(version, loader) profile;
        resource packs / shaders come from their per-instance content profile.
        Applies the filter from the installed_filter_field.
        """
        # Client availability is a persisted preference, applied at launch.
        # Keep disk snapshots intact for Doctor and dependency checks.
        if _is_mod():
            clients = [m for m in all_mods if _is_client_mod(m)]
            client = next((m for m in clients if m.get('enabled')), clients[0] if clients else None)
            displayed, client_added = [], False
            for m in all_mods:
                if _is_client_mod(m):
                    # A launch can reinstall the current JAR beside an older
                    # .jar.disabled backup. They share one managed preference,
                    # so expose one switch while preserving every disk entry.
                    if not client_added:
                        displayed.append(dict(client, display_name='Cubeon Client',
                                              enabled=bool(cfg.get('client_mod_enabled', True)), protected=True))
                        client_added = True
                else:
                    displayed.append(m)
            all_mods = displayed
        client_preference_switch.value = bool(cfg.get('client_mod_enabled', True))
        client_preference_row.visible = (_is_mod() and bool(state.get('selected_mc_version'))
                                         and state.get('mod_loader') in core.MOD_CAPABLE_LOADERS
                                         and not any(_is_client_mod(m) for m in all_mods))
        thread_safe_ui.refresh(client_preference_row)
        names = [m.get('filename', '').removesuffix('.disabled') for m in all_mods]
        from collections import Counter
        installed_collisions.clear()
        installed_collisions.update(name for name, count in Counter(names).items() if count > 1)
        local_install_btn.disabled = local_install_busy['value'] or picker_target['value'] is not None or not _can_install()
        local_install_btn.tooltip = None if _can_install() else "Choose a mod loader on the Play tab first."
        _apply_type_labels()
        if _is_mod():
            vanilla_mods_notice.visible = (state["mod_loader"] == "vanilla")
            shader_notice.visible = False
        else:
            vanilla_mods_notice.visible = False
            shader_notice.visible = (_ct() == "shader"
                                     and not shader_requirement_installed())
            if shader_notice.visible:
                _sync_shader_notice()
            # Version info is what lets each installed row say whether the game
            # will actually accept it (see cubeon/packformat.py). The list is
            # this instance's profile: packs follow the version+loader now,
            # exactly like mods do.
        query = installed_filter_field.value.strip().lower()
        mods = [m for m in all_mods if query in m["display_name"].lower()] if query else all_mods

        rows = []
        installed_count_text.value = 'Checking installed content...' if loading else (
            f"{len(all_mods)} installed" if not query else f"{len(mods)} of {len(all_mods)} shown"
        )

        # If nothing installed, show a placeholder worded for the active type.
        if loading:
            rows.append(loading_rows(fill=BORDER))
        elif not all_mods:
            if _is_mod():
                empty_icon = ft.Icons.EXTENSION_OFF_ROUNDED
                empty_title = "No mods installed yet"
                empty_hint = "Find a mod with search, or use Import mods."
            else:
                empty_icon = ft.Icons.IMAGE_NOT_SUPPORTED_OUTLINED
                empty_title = f"No {core.CONTENT_TYPES[_ct()]['label_plural'].lower()} installed yet"
                empty_hint = "Find content with search, or import files you already have."
            rows.append(empty_state(empty_title, empty_hint, icon=empty_icon,
                                    action_label="Find content", on_action=lambda e: on_view_change("browse")))
        elif not mods:
            # Filter returned no results
            rows.append(
                empty_state("No matching installed content", "Try another filter.")
            )
        else:
            # Build a row for each mod
            capacity = tile_capacity(mods_list_view)
            limit = max(capacity, installed_limit['value']) if query or installed_show_all['value'] else capacity
            visible_mods = mods[:limit]
            for m in visible_mods:
                rows.append(build_installed_row(m))
            if len(mods) > len(visible_mods):
                hidden = len(mods) - len(visible_mods)
                def more(e):
                    installed_limit['value'] = len(visible_mods) + 25
                    installed_show_all['value'] = True
                    _render_installed_snapshot(_cached_installed())
                rows.append(
                    attach_hover(ft.Container(
                        content=ft.Text(
                            f"Show more installed ({hidden} more)",
                            size=12, color=ACCENT, weight=ft.FontWeight.W_700,
                        ),
                        padding=ft.padding.Padding.symmetric(vertical=8, horizontal=12),
                        border_radius=RADIUS,
                        ink=False,
                        on_click=more,
                    ), None, SURFACE_HI)
                )
            if installed_show_all['value'] and not query:
                rows.append(quiet_chip('Show fewer', on_click=lambda e: (
                    installed_show_all.update(value=False), installed_limit.update(value=25),
                    _render_installed_snapshot(_cached_installed()))))
        mods_list_view.controls[:] = rows
        layout_tiles(mods_list_view, bool(mods) and not loading)
        _fetch_missing_icons()
        # Rebuilt the list: repaint just the list region + count, not the
        # full tree (this fires per keystroke of the installed filter).
        thread_safe_ui.refresh(mods_list_view)
        thread_safe_ui.refresh(installed_count_text)
        thread_safe_ui.refresh(installed_filter_field)
        thread_safe_ui.refresh(local_install_btn)
        thread_safe_ui.refresh(vanilla_mods_notice)
        thread_safe_ui.refresh(shader_notice)
        # Keep the "Installed (N)" tab label in step with reality.
        _build_view_segment()

    # Checks stay in the tab: no approval or result windows during automatic
    # scans. An explicit Check & repair click authorizes reversible changes;
    # a passive check never disables or replaces an existing mod.
    repair_status = ft.Text("", size=11.5, color=TEXT_DIM,
                            font_family=FONT_MONO, visible=False)
    repair_details = ft.Text("", size=12, color=TEXT_DIM, visible=False,
                             data="mods-repair-details", selectable=True)
    repair_lock = threading.Lock()
    AUTO_CHECK_SECONDS = 15 * 60
    auto_check_state = {"last": {}}

    def _set_repair_status(text, detail=None):
        with thread_safe_ui.TREE_LOCK:
            repair_status.value = i18n.t(text)
            repair_status.visible = bool(text)
            repair_status.tooltip = detail
            repair_details.value = detail or ""
            repair_details.visible = bool(detail)
            thread_safe_ui.refresh(repair_status)
            thread_safe_ui.refresh(repair_details)

    def _repair_sections():
        return ["mods"] if _is_mod() else ["shaders" if _ct() == "shader" else "resourcepacks"]

    def _start_repair(mc, loader, version_id, sections, *, explicit=False):
        if (state.get("running_version") or state.get("installing_version")
                or state.get("launching_version") or state.get("fixing_mods")):
            if explicit:
                _set_repair_status("Close the game and finish installs before repairing")
            return False
        if not repair_lock.acquire(blocking=False):
            return False
        with thread_safe_ui.TREE_LOCK:
            if explicit:
                state["fixing_mods"] = version_id
            check_repair_btn.disabled = True
            thread_safe_ui.refresh(check_repair_btn)
        if explicit:
            _set_repair_status("Checking…")

        def worker():
            try:
                report = core.run_doctor(
                    mc, loader, auto_fix=True, check_online=explicit,
                    approve_cb=(lambda change: True) if explicit else None,
                    version_id=version_id, include=sections)
                fixed = len((report or {}).get("fixed") or [])
                unresolved = (report or {}).get("unfixed") or []
                # Mod names are a separate report field; detail alone used to
                # leave users with "requires X" and no mod to find in Installed.
                # Explicit repairs also show exactly what changed, inline - and
                # `format_problem` keeps the ERROR attached to every fixed row,
                # so "disabled it" never arrives without "duplicate copies".
                from cubeon.doctor import format_problem
                problems = unresolved + (list((report or {}).get("fixed") or []) if explicit else [])
                detail = "\n".join(format_problem(p) for p in problems[:10])
                if len(problems) > 10:
                    detail += f"\n{len(problems) - 10} more results; check the marked Installed rows."
                if version_dropdown.value == version_id and _repair_sections() == sections:
                    if fixed:
                        refresh_mods_list()
                    if unresolved:
                        _set_repair_status(f"Fixed {fixed}; {len(unresolved)} need attention", detail)
                    elif fixed:
                        _set_repair_status(f"Fixed {fixed} problem{'s' if fixed != 1 else ''}", detail)
                    else:
                        _set_repair_status("No problems found")
            except Exception as error:
                logging.getLogger(__name__).warning("background content check failed", exc_info=True)
                if explicit:
                    _set_repair_status(f"Could not complete this check: {error}")
            finally:
                with thread_safe_ui.TREE_LOCK:
                    if explicit and state.get("fixing_mods") == version_id:
                        state["fixing_mods"] = None
                    check_repair_btn.disabled = False
                    thread_safe_ui.refresh(check_repair_btn)
                repair_lock.release()

        try:
            threading.Thread(target=worker, daemon=True, name="cubeon-content-check").start()
        except Exception:
            if explicit and state.get("fixing_mods") == version_id:
                state["fixing_mods"] = None
            check_repair_btn.disabled = False
            thread_safe_ui.refresh(check_repair_btn)
            repair_lock.release()
            raise
        return True

    def run_mod_repair(e=None):
        mc = state.get("selected_mc_version")
        loader = state.get("mod_loader") or "vanilla"
        version_id = version_dropdown.value
        if not mc or not version_id:
            _set_repair_status("Pick an instance first")
            return
        if _is_mod() and loader == "vanilla":
            _set_repair_status("Vanilla runs resource packs, not mods")
            return
        _start_repair(mc, loader, version_id, _repair_sections(), explicit=True)

    check_repair_btn = attach_hover(ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.BUILD_ROUNDED, color=TEXT_DIM, size=14),
             ft.Text(i18n.t("Check & repair"), color=TEXT_DIM, size=12,
                     weight=ft.FontWeight.W_600)], spacing=4, tight=True),
        border=ft.border.Border.all(1, CARD_BORDER), border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=12, vertical=4),
        tooltip="Repair missing dependencies and conflicts in the background. "
                "Changed mods are kept as disabled backups.",
        ink=False, on_click=run_mod_repair, data="mods-check-repair",
    ), "transparent", ROW_HOVER)

    def auto_check(force=False):
        mc = state.get("selected_mc_version")
        loader = state.get("mod_loader") or "vanilla"
        version_id = version_dropdown.value
        if not mc or not version_id:
            return
        key = (version_id, loader, _ct())
        last = auto_check_state["last"].get(key)
        if not force and last and time.monotonic() - last < AUTO_CHECK_SECONDS:
            return
        if _start_repair(mc, loader, version_id, _repair_sections()):
            auto_check_state["last"][key] = time.monotonic()

    def _compat_lines(m):
        """The one-line compatibility verdict for an installed pack/shader.

        Silence means "the game will load it" - a positive line on every row
        would just add noise. A pack the game would show as Incompatible is the
        whole reason this exists, so that one is called out in red with the
        full explanation in a tooltip (and Check & repair fixes supported issues)."""
        compat = m.get("compat")
        if not compat or compat.get("ok") is True:
            return []
        detail = (compat.get("reason") or "").strip()
        if compat.get("ok") is False:
            return [ft.Text(
                "Incompatible - use Check & repair",
                size=10.5, color=DANGER,
                tooltip=detail or "The game would show this as incompatible.")]
        return [ft.Text(
            "Can't check the format for this version", size=10.5,
            color=TEXT_FAINT, tooltip=detail)]

    row_actions = set()

    def _run_row_action(target, row, action, success):
        # Folder removal and post-action archive scans must not stall Flet.
        key = (target, id(row))
        with thread_safe_ui.TREE_LOCK:
            if key in row_actions:
                return
            row_actions.add(key)
            row.disabled = True
            thread_safe_ui.refresh(row)

        def worker():
            try:
                action()
                message = success
            except Exception as error:
                message = str(error)
            try:
                snapshot = _read_installed_snapshot(target)
            except Exception as error:
                snapshot = None
                message += f" Couldn't refresh the list: {error}"
            with thread_safe_ui.TREE_LOCK:
                row_actions.discard(key)
                row.disabled = False
                if target == _installed_target():
                    if snapshot is not None:
                        installed_refresh.invalidate()
                        _apply_installed_snapshot(snapshot)
                    _set_installed_status(message)
                    thread_safe_ui.refresh(row)

        try:
            threading.Thread(target=worker, daemon=True, name='mods-row-action').start()
        except Exception as error:
            with thread_safe_ui.TREE_LOCK:
                row_actions.discard(key)
                row.disabled = False
                _set_installed_status(f"Couldn't start this action: {error}")
                thread_safe_ui.refresh(row)

    def build_installed_row(m):
        """
        Installed items expose per-instance availability and removal.

        Deliberately NOT a boxed card: rows are transparent and lift only on
        hover, so the list reads as one calm surface instead of a stack of
        rectangles inside the enclosing rectangle.
        """
        row_target = _installed_target()
        identity = m.get('filename') or m.get('id') or m['display_name']
        key = _row_key(identity if identity.removesuffix('.disabled') in installed_collisions
                       else identity.removesuffix('.disabled'))
        cached = installed_rows.get(key)
        if cached:
            metadata, row = cached
            if _is_mod() and bool(metadata.get("protected")) == bool(m.get("protected")):
                metadata.clear()
                metadata.update(m)
                labels = row.content.controls[1].controls
                labels[0].value = m["display_name"]
                labels[0].color = TEXT if m["enabled"] else TEXT_DIM
                labels[1].value = _mod_status(m)
                if not m.get("protected") or _is_client_mod(m):
                    row.content.controls[2].value = m["enabled"]
                row.on_click = (
                    (lambda event, metadata=metadata: open_mod_detail(metadata))
                    if not m.get("protected") and (m.get("project_id") or m.get("slug")) else None
                )
                return row
            if metadata == m:
                return row
            if not _is_mod() and {k: v for k, v in metadata.items() if k not in ('enabled', 'filename')} == {
                    k: v for k, v in m.items() if k not in ('enabled', 'filename')}:
                metadata.clear()
                metadata.update(m)
                labels = row.content.controls[1].controls
                labels[0].color = TEXT if m.get('enabled', True) else TEXT_DIM
                labels[1].value = f"{m['size_kb']:,.0f} KB · {'Enabled' if m.get('enabled', True) else 'Disabled'}"
                row.content.controls[2].value = m.get('enabled', True)
                row.content.controls[2].tooltip = ('Disable for this instance on next launch' if m.get('enabled', True)
                                                   else 'Enable for this instance on next launch')
                return row
        m = dict(m)
        if not _is_mod():
            def on_toggle_content(e):
                if row_target != _installed_target():
                    return
                def action():
                    core.toggle_content(row_target[0], m['filename'], row_target[1], row_target[2],
                                        version_id=row_target[3])
                _run_row_action(row_target, row, action,
                                f"{'Disabled' if m.get('enabled', True) else 'Enabled'} '{m['display_name']}'.")

            def on_delete_content(e):
                if row_target != _installed_target():
                    _set_installed_status('This row belongs to another instance. Refresh the list.')
                    return
                def action():
                    core.delete_content(row_target[0], m["filename"], row_target[1],
                                        version_id=row_target[3], loader=row_target[2])
                _run_row_action(row_target, row, action, f"Removed '{m['display_name']}'.")

            row_icon = _make_installed_icon(m)
            row = style_tile(
                ft.Container(
                    content=ft.Row(
                        [
                            row_icon,
                            ft.Column(
                                [
                                    ft.Text(m["display_name"], size=13.5,
                                            color=TEXT if m.get('enabled', True) else TEXT_DIM,
                                            weight=ft.FontWeight.W_600, max_lines=1,
                                            overflow=ft.TextOverflow.ELLIPSIS, tooltip=m['display_name']),
                                    ft.Text(f"{m['size_kb']:,.0f} KB · {'Enabled' if m.get('enabled', True) else 'Disabled'}", size=10.5,
                                            color=TEXT_DIM, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                    *_compat_lines(m),
                                ],
                                spacing=4, expand=True,
                            ),
                            animated_switch(value=m.get('enabled', True), active_color=ACCENT,
                                            on_change=on_toggle_content, scale=0.85,
                                            tooltip='Disable for this instance on next launch' if m.get('enabled', True)
                                            else 'Enable for this instance on next launch'),
                            ft.IconButton(ft.Icons.CLOSE_ROUNDED, icon_color=TEXT_FAINT,
                                          icon_size=17, tooltip=i18n.t("Remove"),
                                          on_click=on_delete_content),
                        ],
                        spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    border_radius=RADIUS,
                    padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
                ),
                SURFACE, BORDER, ROW_HOVER,
            )
            _remember_row(installed_rows, key, (m, row))
            return row

        def on_toggle(e):
            if row_target != _installed_target():
                return
            if _is_client_mod(m):
                _change_client_enabled(not m['enabled'])
                return
            if m.get("protected"):
                return  # Cubeon-managed mod - core would refuse anyway
            def action():
                core.toggle_mod(row_target[1], row_target[2], m["filename"],
                                version_id=row_target[3])
            _run_row_action(row_target, row, action,
                            f"{'Disabled' if m['enabled'] else 'Enabled'} '{m['display_name']}'.")

        def on_delete(e):
            if row_target != _installed_target():
                return
            if m.get("protected"):
                return  # Cubeon-managed mod - core would refuse anyway
            def action():
                core.delete_mod(row_target[1], row_target[2], m["filename"],
                                version_id=row_target[3])
            _run_row_action(row_target, row, action, f"Removed '{m['display_name']}'.")

        row = style_tile(
            ft.Container(
                content=ft.Row(
                    [
                        # Enabled mods read brighter; disabled ones dim. State is
                        # typography, not a colored bar. The icon is the mod's
                        # real Modrinth art once its slug resolves (placeholder
                        # until then - manually-dropped jars have no slug).
                        _make_installed_icon(m),
                        ft.Column(
                            [
                                ft.Text(m["display_name"], size=13.5,
                                        color=TEXT if m["enabled"] else TEXT_DIM,
                                        weight=ft.FontWeight.W_600, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text(
                                    _mod_status(m),
                                    size=11.5, color=TEXT_DIM, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS,
                                ),
                            ],
                            spacing=4, expand=True,
                        ),
                        # Client uses its persisted global preference. Other
                        # managed mods retain their lock and deletion guard.
                        *(
                            [animated_switch(value=m['enabled'], active_color=ACCENT,
                                             on_change=on_toggle, scale=0.85,
                                             tooltip='Enable or disable Cubeon Client for all instances on the next launch')]
                            if _is_client_mod(m) else
                            [ft.Container(
                                content=ft.Row([
                                    ft.Icon(ft.Icons.LOCK_ROUNDED, size=14, color=TEXT_DIM),
                                    ft.Text(i18n.t("System"), size=11, color=TEXT_DIM, font_family=FONT_MONO),
                                ], spacing=4, tight=True),
                                padding=ft.padding.Padding.symmetric(horizontal=8, vertical=4),
                            )]
                            if m.get("protected") else [
                                # Toggle switch
                                animated_switch(value=m["enabled"], active_color=ACCENT, on_change=on_toggle, scale=0.85),
                                # Delete button
                                ft.IconButton(ft.Icons.DELETE_OUTLINE_ROUNDED, icon_color=TEXT_FAINT,
                                              icon_size=18, tooltip=i18n.t("Remove"), on_click=on_delete),
                            ]
                        ),
                    ],
                    spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
            ),
            SURFACE, BORDER, ROW_HOVER,
        )
        # Clicking the row (not the switch/delete) opens the full mod menu.
        # Protected/system files have no store identity to look up.
        if not m.get("protected") and (m.get("project_id") or m.get("slug")):
            row.on_click = lambda e, mm=m: open_mod_detail(mm)
        _remember_row(installed_rows, key, (m, row))
        return row

    def open_folder_click(e):
        """Opens the folder for the active content type in the system file explorer."""
        if _is_mod():
            core.open_mods_folder(state["selected_mc_version"], state["mod_loader"],
                                  version_id=version_dropdown.value)
        else:
            core.open_content_folder(_ct(), state["selected_mc_version"],
                                     version_id=version_dropdown.value,
                                     loader=loader_for_content())

    # --- Install from file: lets the user pick a .jar already on their
    # disk and drop it straight into the current profile's mods folder,
    # without needing to find/search it on Modrinth first. ---

    # Hidden while empty - a visible-but-blank Text still occupies a full line,
    # which is what opened a dead band between the segment tabs and search.
    local_install_status = ft.Text("", size=12, color=TEXT_DIM, visible=False)
    local_install_label = ft.Text(i18n.t('Import mods'), color=TEXT_DIM, size=12, weight=ft.FontWeight.W_600)

    def handle_local_mod_files(files):
        if not files:
            picker_target['value'] = None
            local_install_btn.disabled = not _can_install()
            thread_safe_ui.refresh(local_install_btn)
            return
        if local_install_busy['value']:
            return
        target = picker_target['value'] or _installed_target()
        picker_target['value'] = None
        if target != _installed_target():
            local_install_status.value = 'The selected instance changed. Choose the file again.'
            local_install_status.visible = True
            local_install_btn.disabled = not _can_install()
            thread_safe_ui.refresh(local_install_status)
            thread_safe_ui.refresh(local_install_btn)
            return
        if not _can_install():
            local_install_status.value = "Choose a compatible mod loader on the Play tab first. Texture packs work in vanilla."
            local_install_status.visible = True
            local_install_btn.disabled = True
            thread_safe_ui.refresh(local_install_status)
            thread_safe_ui.refresh(local_install_btn)
            return
        local_install_busy['value'] = True
        local_install_status.value = "Checking selected mods…" if target[0] == 'mod' else "Installing selected files…"
        local_install_status.visible = True
        thread_safe_ui.refresh(local_install_status)
        # Park the trigger so a double-pick can't run two installs into the
        # same profile; the worker below restores it.
        local_install_btn.disabled = True
        thread_safe_ui.refresh(local_install_btn)

        if target[0] == 'mod':
            def release_import():
                with thread_safe_ui.TREE_LOCK:
                    local_install_busy['value'] = False
                    local_install_btn.disabled = not _can_install()
                    thread_safe_ui.refresh(local_install_btn)

            def imported(results):
                _refresh_after_install(target)
                with thread_safe_ui.TREE_LOCK:
                    if target == _installed_target():
                        count = sum(result['status'] == 'imported' for result in results)
                        failed = sum(result['status'] == 'failed' for result in results)
                        local_install_status.value = f'{count} mods imported' + (f' · {failed} failed' if failed else '')
                        thread_safe_ui.refresh(local_install_status)

            def review_worker():
                try:
                    from cubeon import local_mods
                    from ui.local_mod_import import LocalModImport
                    review = local_mods.review_files([getattr(file, 'path', None) for file in files],
                                                    target[1], target[2], version_id=target[3])
                    with thread_safe_ui.TREE_LOCK:
                        if target != _installed_target():
                            release_import()
                            return
                        local_install_status.value = ''
                        local_install_status.visible = False
                        thread_safe_ui.refresh(local_install_status)
                        LocalModImport(page, review,
                                       instance_label=(cfg.get('version_labels') or {}).get(target[3]) or target[3],
                                       finished=imported, closed=release_import).open()
                except Exception as error:
                    with thread_safe_ui.TREE_LOCK:
                        if target == _installed_target():
                            local_install_status.value = f"Couldn't check the selected files: {error}"
                            thread_safe_ui.refresh(local_install_status)
                    release_import()
            try:
                threading.Thread(target=review_worker, daemon=True, name='cubeon-local-mod-install').start()
            except Exception as error:
                local_install_status.value = f"Couldn't start importing: {error}"
                thread_safe_ui.refresh(local_install_status)
                release_import()
            return

        # The install is real disk work (global-store copy/link, sidecar meta;
        # for packs a full copy + pack.mcmeta verify/fix) and run_mod_repair
        # even does network checks - none of it belongs on the UI thread
        # (same treatment the cosmetics uploads got).
        def worker():
            message = None
            try:
                imported_count, failures = 0, []
                for picked in files:
                    try:
                        core.install_local_content(target[0], picked.path, target[1], target[3], target[2])
                        imported_count += 1
                    except Exception as error:
                        failures.append(f'{picked.name}: {error}')
                message = f'Imported {imported_count} file(s).'
                if failures:
                    message += '\n' + '\n'.join(failures)
                _refresh_after_install(target)
                # Phase 7: a local OS toast so a slow install can finish while
                # the launcher is behind another window. Best-effort by
                # construction (see cubeon/osnotify.py) - and it never names a
                # kind with no Settings switch (content_kind maps shaders onto
                # the texture-pack one).
                try:
                    from cubeon import osnotify
                    osnotify.install_finished(osnotify.content_kind(target[0]),
                                              f'{imported_count} file(s)')
                except Exception:
                    pass
            except ValueError as ve:
                message = str(ve)
            except Exception as ex:
                message = f"Install failed: {ex}"
            finally:
                with thread_safe_ui.TREE_LOCK:
                    if target == _installed_target():
                        local_install_status.value = message
                        local_install_status.visible = True
                        thread_safe_ui.refresh(local_install_status)
                    local_install_busy['value'] = False
                    local_install_btn.disabled = not _can_install()
                    thread_safe_ui.refresh(local_install_btn)

        try:
            threading.Thread(target=worker, daemon=True, name="cubeon-local-mod-install").start()
        except Exception as error:
            local_install_busy['value'] = False
            local_install_status.value = f"Couldn't start installation: {error}"
            local_install_btn.disabled = not _can_install()
            thread_safe_ui.refresh(local_install_status)
            thread_safe_ui.refresh(local_install_btn)

    def on_local_mod_picked(e):
        # Old-Flet path: pick_files() ran synchronously and the result
        # arrives here via on_result. Untyped rather than annotated as
        # ft.FilePickerResultEvent - that class is missing on some pinned
        # Flet builds (e.g. 0.86.x) and a hard annotation crashes this
        # function's definition at import time on those builds.
        handle_local_mod_files(e.files)

    local_mod_file_picker = ft.FilePicker()
    local_mod_file_picker.on_result = on_local_mod_picked

    # Same version-spanning registration dance used for the profile
    # picture / skin FilePickers in main.py and skin_tab.py - newer Flet
    # self-registers Services, older Flet needs the explicit overlay append.
    _lmf_registered = False
    _lmf_services_list = getattr(page, "_services", None)
    _lmf_already_registered = (
        _lmf_services_list is not None
        and hasattr(_lmf_services_list, "_services")
        and local_mod_file_picker in _lmf_services_list._services
    )
    _lmf_register_fn = getattr(page, "register_service", None)
    if _lmf_already_registered:
        _lmf_registered = True
    elif callable(_lmf_register_fn):
        try:
            _lmf_register_fn(local_mod_file_picker)
            _lmf_registered = True
        except Exception:
            _lmf_registered = False
    if not _lmf_registered:
        try:
            if local_mod_file_picker not in page.overlay:
                page.overlay.append(local_mod_file_picker)
        except Exception:
            pass

    def open_local_mod_picker(e):
        if local_install_busy['value'] or picker_target['value'] is not None:
            return
        if not _can_install():
            local_install_status.value = "Mods and shaders need a compatible mod loader. Choose one on the Play tab."
            local_install_status.visible = True
            thread_safe_ui.refresh(local_install_status)
            return
        if _is_mod():
            # Vanilla can't load mods: refuse here instead of letting the
            # install land in a profile the game never reads. (install_local_
            # mod enforces the same rule at the core layer as a backstop.)
            if state["mod_loader"] == "vanilla":
                local_install_status.value = (
                    "Vanilla can't load mods - switch the loader on the "
                    "Play tab first.")
                local_install_status.visible = True
                thread_safe_ui.refresh(local_install_status)
                return
            exts, title = ["jar"], "Choose mod JARs to import"
        else:
            exts, title = ["zip"], f"Choose a {_type_label()} .zip"
        picker_target['value'] = _installed_target()
        local_install_btn.disabled = True
        thread_safe_ui.refresh(local_install_btn)
        def picker_failed(error):
            with thread_safe_ui.TREE_LOCK:
                picker_target['value'] = None
                local_install_btn.disabled = not _can_install()
                local_install_status.value = f"Couldn't open the file chooser: {error}"
                local_install_status.visible = True
                thread_safe_ui.refresh(local_install_status)
                thread_safe_ui.refresh(local_install_btn)
        try:
            core.run_file_picker(
                page, local_mod_file_picker,
                on_files=handle_local_mod_files, on_error=picker_failed,
                dialog_title=title, allow_multiple=True,
                file_type=ft.FilePickerFileType.CUSTOM, allowed_extensions=exts,
            )
        except Exception as error:
            picker_failed(error)

    # --- Browse / download section (Modrinth integration) ---

    # Search happens LIVE as you type: a short debounce timer restarts on
    # every keystroke and only the last one actually fires, so typing
    # "sodium" costs one request instead of six. That's what lets the big
    # green "Search" button disappear - there was nothing left for it to do.
    mod_search_field = ft.TextField(
        hint_text="Search mods... e.g. sodium, iris, jei",
        border_color=CARD_BORDER,
        focused_border_color=ACCENT_DIM,
        color=TEXT,
        hint_style=ft.TextStyle(color=TEXT_FAINT),
        text_style=ft.TextStyle(size=13.5),
        bgcolor=CARD_FILL,
        border_radius=RADIUS,
        height=46,
        content_padding=ft.padding.Padding.symmetric(horizontal=16, vertical=12),
        prefix_icon=ft.Icons.SEARCH_ROUNDED,
        on_submit=lambda e: run_mod_search(),  # Enter = search immediately
        expand=True,
    )
    _search_debounce = {"timer": None}

    def _schedule_live_search(e=None):
        """Debounced on_change: cancel any pending search, start a new one."""
        pending = _search_debounce["timer"]
        if pending is not None:
            pending.cancel()
        _search_debounce["timer"] = threading.Timer(0.45, run_mod_search_safe)
        _search_debounce["timer"].daemon = True
        _search_debounce["timer"].start()

    def _cancel_search_timer():
        pending = _search_debounce['timer']
        if pending is not None:
            pending.cancel()
            _search_debounce['timer'] = None

    def run_mod_search_safe():
        with thread_safe_ui.TREE_LOCK:
            run_mod_search()

    mod_search_field.on_change = _schedule_live_search

    browse_results_view = tile_grid()
    browse_status_text = ft.Text("", size=12, color=TEXT_DIM)
    # Each page fills the available grid. Modrinth permits up to 100 hits
    # per request. Pages are fetched ON DEMAND (see _load_browse_page):
    # opening the tab loads page 1 only, and each pager click fetches just the
    # page it needs instead of pulling all 10 pages up front (which made the
    # tab slow and heavy). Each fetched page is stashed in browse_state["pages"]
    # so going back to a page already seen is instant and never re-fetches.
    BROWSE_PAGE_SIZE = 24  # Stable offsets; viewport changes only lay out tiles.
    MAX_BROWSE_PAGES = -(-100 // BROWSE_PAGE_SIZE)
    browse_state = {
        "results": [],          # items on the page currently rendered
        "page": 0,
        "empty_msg": "",
        "pages": {},            # page_num -> [items] already fetched
        "total_pages": MAX_BROWSE_PAGES,
        "token": None,          # (generation, key) these pages belong to
        "paged": True,          # later pages fetch on demand
    }
    browse_pager_label = ft.Text("", size=12, color=TEXT_DIM, font_family=FONT_MONO)
    browse_pager_prev = ft.Container(
        content=ft.Icon(ft.Icons.CHEVRON_LEFT_ROUNDED, size=18, color=TEXT),
        padding=8, border_radius=RADIUS, ink=False,
    )
    browse_pager_next = ft.Container(
        content=ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=18, color=TEXT),
        padding=8, border_radius=RADIUS, ink=False,
    )
    browse_pager_row = ft.Row(
        [browse_pager_prev, browse_pager_label, browse_pager_next],
        alignment=ft.MainAxisAlignment.CENTER, spacing=4, visible=False,
    )
    browse_title_text = ft.Text("Popular", size=12,
                                 color=TEXT_DIM, font_family=FONT_MONO)
    search_scope = {"compatible": True}
    browse_scope_text = ft.Text("", size=11.5, color=TEXT_DIM)
    compatible_only = ft.Checkbox(
        label="Compatible only", value=True,
        active_color=ACCENT,
        label_style=ft.TextStyle(color=TEXT_DIM, size=11.5),
        on_change=lambda event: _change_search_scope(bool(event.control.value)),
    )

    # Currently selected category filter ("" = All). Kept as mutable state
    # so both the chip row and the search/recommend functions can read it.
    active_category = {"value": ""}

    # Which kind of content this tab is currently showing. The same browse +
    # installed UI is reused for all three by routing its data calls through
    # the _is_mod() branches below - mods go through the per-profile
    # cubeon/mods.py path (version+loader keyed, synced at launch), while
    # resource packs and shaders go through cubeon/content.py, which installs
    # straight into the shared, version-agnostic .minecraft/resourcepacks and
    # shaderpacks folders the game reads directly (no profiles, no toggle, no
    # sync step - see cubeon/content.py for why they genuinely differ).
    active_content = {"type": "mod"}  # "mod" | "resourcepack" | "shader"
    CONTENT_TABS = [("mod", "Mods"), ("resourcepack", "Resource Packs"), ("shader", "Shaders")]

    def _ct() -> str:
        return active_content["type"]

    def _is_mod() -> bool:
        return active_content["type"] == "mod"

    def _instance_mod_capable():
        """Does the SELECTED INSTANCE really have a mod loader?

        ``state["mod_loader"]`` is the switcher's choice, not on-disk truth: it
        can read "fabric" because another instance on the same Minecraft
        version has Fabric, or because the user armed Play to install one.
        Trusting it let a plain Vanilla folder accept mods and shaders (the
        2026-10-25 report). An installed instance therefore has to prove it
        with its own descriptor; a not-yet-installed version still follows the
        switcher, and a pending loader install counts as the intent to become
        modded.
        """
        vid = version_dropdown.value
        if not vid:
            return False
        pending = state.get("pending_loader_install") or {}
        if (pending.get("version_id") == vid
                and pending.get("loader") in MOD_CAPABLE_LOADERS):
            return True
        if vid in (state.get("installed") or set()):
            try:
                meta = (state.get("installed_meta") or {}).get(vid) or {}
                info = instance_info.describe(
                    vid, meta, (cfg.get("version_labels") or {}).get(vid),
                    with_mods=False, play_store={})
                return info.get("loader") in MOD_CAPABLE_LOADERS
            except Exception:
                return False
        # Not installed yet: the switcher is the only loader information.
        return state.get("mod_loader") in MOD_CAPABLE_LOADERS

    def _can_install(content_type=None):
        kind = content_type or _ct()
        if kind == "resourcepack":
            # Texture packs work in plain Vanilla - always allowed.
            return True
        return (_instance_mod_capable()
                and state.get("mod_loader") in MOD_CAPABLE_LOADERS)

    def loader_for_content() -> str | None:
        """The loader half of the profile key a pack is stored under.

        Content has no loader of its own, but the profile that OWNS it does: a
        Vanilla instance gets its own set of packs instead of sharing the
        modded instance's (which matters because a shader is only usable where
        Iris/OptiFine is actually installed)."""
        return state.get("mod_loader")

    def _type_label() -> str:
        """Singular human label for the active non-mod type, e.g. 'resource pack'."""
        return core.CONTENT_TYPES[_ct()]["label"].lower()

    def build_category_chips():
        """Optional categories occupy one scrolling strip, without a dropdown."""
        def select_category(key):
            active_category['value'] = key
            build_category_chips()
            run_mod_search() if mod_search_field.value.strip() else load_recommended_mods()

        choices = core.MOD_CATEGORIES if _is_mod() else core.category_choices(_ct())
        category_chips_container.content = ft.Column([
            compatible_only,
            ft.Row([ft.TextButton(i18n.t(label), on_click=lambda e, k=key: select_category(k),
                                 style=ft.ButtonStyle(color=TEXT if key == active_category['value'] else TEXT_DIM,
                                                      bgcolor=SURFACE_HI if key == active_category['value'] else None))
                    for key, label in choices], spacing=4, scroll=ft.ScrollMode.AUTO),
        ], spacing=4)
        filters_button.content = i18n.t('Filters') + (' · on' if active_category['value'] or not search_scope['compatible'] else '')
        filters_button.style = ft.ButtonStyle(color=TEXT_DIM)
        thread_safe_ui.refresh(category_chips_container)
        thread_safe_ui.refresh(filters_button)

    category_chips_container = ft.Container(content=ft.Row())
    category_chips_container.visible = False  # shown by the labeled Filters action

    def _apply_type_labels():
        installed_filter_field.hint_text = ('Search installed mods...' if _is_mod()
                                            else 'Search installed resource packs...' if _ct() == 'resourcepack'
                                            else 'Search installed shaders...')
        """Refreshes the header/search/notice text to match the active type.
        Kept in one place so every type-dependent label switches together."""
        header_title.value = dict(CONTENT_TABS)[_ct()]
        if _is_mod():
            header_subtitle.value = "Choose a mod loader on Play to install mods." if not _can_install() else ''
            mod_search_field.hint_text = "Search mods or paste a Modrinth link..."
        elif _ct() == "resourcepack":
            header_subtitle.value = "Texture packs work in vanilla and modded Minecraft."
            mod_search_field.hint_text = "Search resource packs... e.g. faithful, stay true"
        else:
            header_subtitle.value = "Download shaders - they need Iris, Oculus, or OptiFine to run."
            mod_search_field.hint_text = "Search shaders... e.g. complementary, BSL, sildurs"
        compatible_only.visible = _is_mod()
        local_install_label.value = i18n.t('Import mods' if _is_mod() else 'Import packs' if _ct() == 'resourcepack' else 'Import shaders')
        _refresh_browse_scope()

    def on_content_type_change(new_type):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if selected_content['value'] == new_type:
                return
            _cancel_search_timer()
            pending = _filter_debounce['timer']
            if pending is not None:
                pending.cancel()
            type_preferences[_ct()] = (mod_search_field.value, active_category['value'],
                                       installed_filter_field.value, active_view['value'],
                                       installed_limit['value'], filters_open['value'])
            selected_content['value'] = new_type
            for kind, button in content_buttons.items():
                button.style = selector_style(kind == new_type)
                thread_safe_ui.refresh(button)
            mods_body.visible = new_type != 'modpack'
            if modpacks_content is not None:
                modpacks_content.visible = new_type == 'modpack'
                thread_safe_ui.refresh(modpacks_content)
            if new_type == 'modpack':
                thread_safe_ui.refresh(mods_body)
                if on_modpacks_open:
                    on_modpacks_open()
                return
            active_content['type'] = new_type
            query, category, installed_query, view, limit, filters = type_preferences.get(
                new_type, ('', '', '', 'browse', 25, False))
            mod_search_field.value = query
            active_category['value'] = category
            installed_filter_field.value = installed_query
            installed_limit['value'] = limit
            installed_show_all['value'] = False
            filters_open['value'] = filters
            category_chips_container.visible = filters
            active_view['value'] = view
            browse_pane.visible = view == 'browse'
            installed_pane.visible = view == 'installed'
            build_category_chips()
            _apply_type_labels()
            _build_view_segment()
            # Never display the previous type's cards while the new type loads.
            browse_results_view.controls.clear()
            if _installed_target() in installed_snapshots:
                _render_installed_snapshot(_cached_installed())
            else:
                refresh_mods_list(background=True)
            run_mod_search()
            thread_safe_ui.refresh(mods_body)

    def current_mc_version_for_search() -> str | None:
        """
        Extracts the Minecraft version number (e.g., "1.20.4") from the selected version ID.
        This is used to find mods compatible with the current game version.
        """
        v = version_dropdown.value
        if not v:
            return None
        return state.get('selected_mc_version') or core.extract_mc_version(v)

    def browse_loader() -> str:
        """The loader to filter Modrinth results by. Vanilla can't load mods
        at all, so default that case to Fabric (the most commonly supported
        loader) rather than sending an invalid facet."""
        loader = state.get("mod_loader") or "vanilla"
        return loader if loader != "vanilla" else "fabric"

    def _change_search_scope(compatible):
        search_scope["compatible"] = compatible
        compatible_only.value = compatible
        build_category_chips()
        run_mod_search() if mod_search_field.value.strip() else load_recommended_mods()

    def _search_all_modrinth(event=None):
        active_category["value"] = ""
        build_category_chips()
        _change_search_scope(False)

    def _refresh_browse_scope():
        if _is_mod() and not search_scope["compatible"]:
            label = "All Minecraft versions · all loaders"
        else:
            version = current_mc_version_for_search() or "all versions"
            label = f"Minecraft {version}"
            if _is_mod():
                label = f"{browse_loader().title()} · {label}"
        category = active_category["value"]
        if category:
            choices = core.MOD_CATEGORIES if _is_mod() else core.category_choices(_ct())
            label += f" · {dict(choices).get(category, category)}"
        browse_scope_text.value = label
        header_subtitle.value = label
        thread_safe_ui.refresh(header_subtitle)

    browse_generation = {"value": 0}
    browse_inflight = set()
    browse_sessions = {}
    type_preferences = {}

    def _browse_key():
        return (mod_search_field.value.strip(), state.get("selected_mc_version"),
                version_dropdown.value, state.get("mod_loader"), _ct(),
                active_category["value"], search_scope["compatible"], BROWSE_PAGE_SIZE)

    def _begin_browse():
        _cancel_search_timer()
        _refresh_browse_scope()
        key = _browse_key()
        cached = browse_sessions.get(key)
        if cached is not None:
            return cached['token']
        browse_generation["value"] += 1
        return browse_generation["value"], key

    def _browse_current(token):
        return token == browse_state['token'] and token[1] == _browse_key()

    def _retry_search(event=None):
        browse_sessions.pop(_browse_key(), None)
        run_mod_search_safe()

    # --- Lazy page fetching -------------------------------------------------
    # A browse never pulls more than ONE page of results off the network. The
    # old code asked Modrinth for 100 hits (20 pages) up front and sliced them
    # locally, which made opening the tab slow and heavy. Now each pager click
    # fetches just its own offset; already-seen pages are cached in
    # browse_state["pages"] so stepping back is instant.
    def _browse_query() -> str:
        return mod_search_field.value.strip()

    def _browse_is_paged() -> bool:
        """Every catalogue, including popular Mods, fetches one page at a time."""
        return True

    def _browse_fetch(page_num: int, key=None):
        """One page of results for the CURRENT browse key. Runs on a worker
        thread. May return fewer than BROWSE_PAGE_SIZE hits, which the caller
        treats as the last page."""
        query, mc_version, version, loader, content_type, cat, compatible, page_size = key or _browse_key()
        loader = loader if loader and loader != 'vanilla' else 'fabric'
        if content_type == "mod" and not compatible:
            mc_version, loader = None, None
        offset = page_num * page_size
        if content_type == "mod":
            if query:
                return core.search_mods(
                    query, mc_version=mc_version, loader=loader,
                    categories=[cat] if cat else None,
                    limit=page_size, offset=offset)
            return core.get_recommended_mods(
                mc_version=mc_version, loader=loader, category=cat or None,
                limit=page_size, offset=offset)
        if query:
            return core.search_content(
                content_type, query, mc_version=mc_version,
                categories=[cat] if cat else None,
                limit=page_size, offset=offset)
        return core.get_recommended_content(
            content_type, mc_version=mc_version, category=cat or None,
            limit=page_size, offset=offset)

    def _load_browse_page(page_num: int, token, error_prefix: str):
        """Fetches page `page_num` for `token` and renders it when it still
        belongs to the current browse. An already-cached page just re-renders."""
        if page_num in browse_state["pages"]:
            _render_browse_page()
            return
        request = (token, page_num)
        if request in browse_inflight:
            return
        browse_inflight.add(request)
        browse_status_text.value = "Loading..."
        thread_safe_ui.refresh(browse_status_text)

        def worker():
            try:
                items = _browse_fetch(page_num, token[1])
            except Exception as ex:
                logging.getLogger(__name__).warning("%s: %s", error_prefix, ex, exc_info=True)
                with thread_safe_ui.TREE_LOCK:
                    browse_inflight.discard(request)
                    if not _browse_current(token):
                        return
                    browse_sessions.pop(token[1], None)
                    browse_status_text.value = "Search unavailable"
                    client_entry = _client_browse_entry()
                    browse_results_view.disabled = False
                    if client_entry:
                        # Bundled client recovery remains available offline, in
                        # the same compact grid as successful provider results.
                        browse_results_view.controls[:] = [
                            build_browse_row(client_entry, any(_is_client_mod(m) for m in _cached_installed('mod'))),
                            ft.Container(ft.Column([
                                ft.Text('Modrinth unavailable', size=12, color=TEXT_DIM),
                                ft.TextButton('Retry', on_click=_retry_search),
                            ], spacing=4), padding=12),
                        ]
                    else:
                        browse_results_view.controls[:] = [
                            empty_state("Search unavailable", "Check your connection, then try again.",
                                        icon=ft.Icons.WIFI_OFF_ROUNDED),
                            quiet_chip('Retry', on_click=_retry_search),
                        ]
                    layout_tiles(browse_results_view, bool(client_entry))
                thread_safe_ui.refresh(browse_status_text)
                thread_safe_ui.refresh(browse_results_view)
                return
            with thread_safe_ui.TREE_LOCK:
                browse_inflight.discard(request)
                session = browse_sessions.get(token[1])
                if session is None or session['token'] != token:
                    return
                items = items or []
                if session['paged']:
                    items = items[:BROWSE_PAGE_SIZE]
                session["pages"][page_num] = items
                if len(items) < BROWSE_PAGE_SIZE:
                    session["total_pages"] = min(session["total_pages"], page_num + 1)
                if _browse_current(token):
                    _render_browse_page()

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as error:
            browse_inflight.discard(request)
            browse_results_view.disabled = False
            browse_status_text.value = f"Couldn't start search: {error}"
            thread_safe_ui.refresh(browse_results_view)
            thread_safe_ui.refresh(browse_status_text)

    def render_browse_results(empty_msg):
        """
        Resets the browse to page 1 for the current key and starts its fetch.
        Later pages load only when the pager asks for them.
        """
        nonlocal browse_state
        token = browse_state['token']
        key = token[1]
        cached = browse_sessions.get(key)
        if cached is None:
            cached = dict(empty_msg=empty_msg, page=0, pages={}, results=[],
                          paged=_browse_is_paged(), total_pages=MAX_BROWSE_PAGES,
                          token=token)
            browse_sessions[key] = cached
            while len(browse_sessions) > 12:
                browse_sessions.pop(next(iter(browse_sessions)))
        browse_state = cached
        _render_browse_page()

    def load_recommended_mods():
        """
        Fetches the first page of items for the current version+category and
        displays them in the browse section. All types use popular results
        (or the top results in a category), one page at a time.
        """
        with thread_safe_ui.TREE_LOCK:
            nonlocal browse_state
            token = _begin_browse()
            browse_state = dict(browse_state, token=token)
            content_type = _ct()
            cat = active_category["value"]
            if content_type == "mod":
                cat_label = dict(core.MOD_CATEGORIES).get(cat, "")
                default_title = "POPULAR"
            else:
                cat_label = dict(core.category_choices(_ct())).get(cat, "")
                default_title = "POPULAR"
            browse_title_text.value = f"TOP {cat_label.upper()}" if cat else default_title
            render_browse_results(empty_msg="Nothing found for this version/category.")

    def run_mod_search():
        """
        Initiates a search on Modrinth based on the query entered in mod_search_field,
        scoped to the current version, active content type, and selected category.
        If the query is empty, it loads recommendations instead.
        """
        with thread_safe_ui.TREE_LOCK:
            query = mod_search_field.value.strip()
            if not query:
                load_recommended_mods()
                return
            nonlocal browse_state
            token = _begin_browse()
            browse_state = dict(browse_state, token=token)
            browse_title_text.value = f'RESULTS FOR "{query.upper()}"'
            # Live search repaints only the browse region (title/results), not the
            # whole mounted tree - this fires per debounced keystroke.
            thread_safe_ui.refresh(browse_title_text)
            render_browse_results(empty_msg="Nothing found for that search.")

    def _show_browse_loading():
        """The placeholder shown while a page that isn't cached yet is being
        fetched - it keeps the pager out of the way so a stale page number
        can't be clicked while the real one is in flight."""
        if (not browse_results_view.controls or isinstance(browse_results_view.controls[0], (ft.Text, ft.Row))
                or getattr(browse_results_view.controls[0], "data", None) == "content-empty"):
            client_entry = _client_browse_entry()
            if client_entry:
                browse_results_view.controls[:] = [
                    ft.Container(ft.Text('Loading…', size=12, color=TEXT_DIM),
                                 alignment=ft.Alignment.CENTER, data='content-loading'),
                    build_browse_row(client_entry, any(_is_client_mod(m) for m in _cached_installed('mod'))),
                ]
            else:
                browse_results_view.controls[:] = [loading_rows(fill=BORDER)]
            layout_tiles(browse_results_view, bool(client_entry))
        browse_results_view.disabled = getattr(browse_results_view.controls[0], 'data', None) != 'content-loading'
        browse_pager_row.visible = False
        # Scoped: a full page.update() here re-synced every mounted tab right
        # after switch_tab had already painted the shell - that double diff is
        # part of the "click Mods and everything lags at once" report.
        thread_safe_ui.refresh(browse_results_view)
        thread_safe_ui.refresh(browse_pager_row)

    def _render_browse_page():
        """Renders the current page from the cache, fetching it if this is the
        first visit. Whatever isn't cached stays un-fetched until asked for."""
        if browse_state["token"] is None:
            # No browse has been started yet (e.g. a re-render triggered by an
            # install/delete before the tab's first load) - nothing to show.
            return
        page_num = browse_state["page"]
        token = browse_state["token"]

        if not browse_state["paged"]:
            # Legacy non-paged sessions slice their cached results locally.
            all_items = browse_state["pages"].get(0)
            if all_items is None:
                _show_browse_loading()
                _load_browse_page(0, token, "Couldn't load recommendations")
                return
            total_pages = max(1, -(-len(all_items) // BROWSE_PAGE_SIZE))
            page_num = max(0, min(page_num, total_pages - 1))
            browse_state["page"] = page_num
            browse_state["total_pages"] = total_pages
            results = all_items[page_num * BROWSE_PAGE_SIZE:
                                (page_num + 1) * BROWSE_PAGE_SIZE]
        else:
            results = browse_state["pages"].get(page_num)
            if results is None:
                _show_browse_loading()
                _load_browse_page(page_num, token, "Search failed")
                return
            total_pages = max(1, browse_state["total_pages"])

        browse_state["results"] = results

        client_entry = _client_browse_entry()
        displayed_results = ([client_entry] if client_entry else []) + [
            item for item in results if not client_entry or item.get('slug') != 'cubeon-client']
        rows = []
        if not displayed_results:
            rows.append(
                empty_state(browse_state.get("empty_msg") or "No results",
                            "Try a different search or adjust the filters."))
            if _is_mod() and _browse_query() and (search_scope["compatible"] or active_category["value"]):
                rows.append(quiet_chip("Search all Modrinth", on_click=_search_all_modrinth))
        else:
            # Snapshot the mode once: a background recommend/search worker can
            # finish and call this right after the user flipped the content-type
            # segment, so re-checking _is_mod() per row could read one mode in
            # setup and the other in the loop (crashing on the unset variable).
            is_mod_now = _is_mod()
            already = installed_slugs() if is_mod_now else set()
            tokens = set() if is_mod_now else content_installed_tokens()
            for mod in displayed_results:
                if is_mod_now:
                    slug = (mod.get("slug") or "").lower()
                    compact = re.sub(r"[^a-z0-9]+", "", slug)
                    # Modrinth's opaque project id: a modpack install leaves
                    # exactly this and no slug, so it's often the only match
                    # for a pack-installed mod.
                    pid = (mod.get("project_id") or "").strip().lower()
                    is_installed = (any(_is_client_mod(item) for item in _cached_installed('mod'))
                                    if mod.get('builtin_client') else
                                    slug in already or (bool(compact) and compact in already)
                                    or (bool(pid) and pid in already))
                else:
                    # Resource packs / shaders store no Modrinth slug (they're
                    # just .zips in a shared folder), so match the project's
                    # slug OR title as a compacted token against installed
                    # filenames. Best-effort; a miss only shows "Download".
                    slug = re.sub(r"[^a-z0-9]+", "", (mod.get("slug") or "").lower())
                    title = re.sub(r"[^a-z0-9]+", "", (mod.get("title") or "").lower())
                    is_installed = (bool(slug) and any(slug in t for t in tokens)) or \
                        (bool(title) and any(title in t for t in tokens))
                rows.append(build_browse_row(mod, is_installed))

        browse_results_view.controls[:] = rows
        layout_tiles(browse_results_view, bool(displayed_results))
        browse_results_view.disabled = False

        matched_query = results[0].get("search_query", _browse_query()) if results else ""
        browse_status_text.value = (
            "No filtered matches · showing other versions, loaders or categories"
            if any(item.get('search_broadened') for item in results)
            else f'Related matches for "{matched_query}"' if matched_query and matched_query != _browse_query()
            else f"{len(displayed_results)} result(s)" if displayed_results else "")
        browse_pager_label.value = f"Page {page_num + 1} of {total_pages}"
        browse_pager_row.visible = total_pages > 1
        browse_pager_prev.disabled = page_num <= 0
        browse_pager_next.disabled = page_num >= total_pages - 1
        # Results often land moments after the tab switch, while the user is
        # already moving. Repaint only the browse region instead of diffing
        # the whole page in that moment.
        thread_safe_ui.refresh(browse_results_view)
        thread_safe_ui.refresh(browse_status_text)
        thread_safe_ui.refresh(browse_pager_label)
        thread_safe_ui.refresh(browse_pager_row)
        thread_safe_ui.refresh(browse_pager_prev)
        thread_safe_ui.refresh(browse_pager_next)

    # --- Mod detail menu ----------------------------------------------------
    # Clicking a mod (browse or installed) opens this: cover art, the full
    # description, the numbers, and every released version with a one-click
    # install. A list row only has room for a name and a line of text; this is
    # where "what is this, and which version do I want?" gets answered.

    def _detail_loading_row():
        return ft.Row(
            [ft.ProgressRing(width=16, height=16, stroke_width=2, color=ACCENT),
             ft.Text("Loading details...", size=13, color=TEXT_DIM)],
            spacing=12, alignment=ft.MainAxisAlignment.CENTER,
        )

    def _detail_badge(text, tone="dim"):
        """A tiny metadata pill. Quiet by default; green only for the one
        version that matches the profile the user is browsing."""
        accent = tone == "accent"
        return ft.Container(
            content=ft.Text(text, size=10.5,
                            color=ACCENT if accent else TEXT_FAINT,
                            weight=ft.FontWeight.W_600,
                            font_family=FONT_MONO),
            bgcolor=ACCENT_TINT if accent else CARD_FILL,
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=8, vertical=4),
            border=None if accent else ft.border.Border.all(1, CARD_BORDER),
        )

    def open_mod_detail(mod, content_type=None):
        """Open the full menu for one mod, keyed by its Modrinth id or slug.
        Manually dropped-in files have neither, so there is nothing to look
        up - those rows simply don't open a menu."""
        ref = (mod.get("project_id") or mod.get("slug") or "").strip()
        if not ref:
            return

        content_type = content_type or _ct()
        detail_mc = state["selected_mc_version"]
        detail_version = version_dropdown.value
        detail_search_mc = current_mc_version_for_search()
        detail_loader = state.get("mod_loader")
        feedback = install_registry.project(
            (content_type, detail_mc, detail_loader, detail_version), ref, mod.get("slug"))
        title = mod.get("title") or mod.get("display_name") or "Mod"
        icon_url = mod.get("icon_url")
        blurb = (mod.get("description") or "").strip()

        _body_h = 560
        try:
            _wh = getattr(page, "height", None)
            if not _wh and getattr(page, "window", None) is not None:
                _wh = page.window.height
            if _wh:
                _body_h = max(360, min(640, int(_wh) - 210))
        except Exception:
            _body_h = 560

        detail_body = ft.Column(
            [_detail_loading_row()],
            spacing=16, width=680, height=_body_h,
            scroll=ft.ScrollMode.AUTO,
        )

        def _close(e=None):
            dialogs.close_dialog(page, dlg)

        def _hero(url, *, width, height, radius=RADIUS):
            return _art_image(url, width, height, radius)

        dlg = ft.AlertDialog(
            modal=False, bgcolor=SURFACE,
            content=ft.Container(
                width=720,
                content=ft.Column(
                    [
                        ft.Row(
                            [
                                (_hero(icon_url, width=64, height=64)
                                 if icon_url else
                                 ft.Container(width=64, height=64, bgcolor=CARD_FILL,
                                              border_radius=RADIUS,
                                              content=ft.Icon(
                                                  ft.Icons.EXTENSION_OUTLINED,
                                                  color=TEXT_FAINT, size=26),
                                              alignment=ft.Alignment.CENTER)),
                                ft.Column(
                                    [
                                        ft.Text(title, size=20, color=TEXT,
                                                weight=ft.FontWeight.W_800,
                                                max_lines=2),
                                        ft.Text(blurb or " ", size=12.5,
                                                color=TEXT_DIM, max_lines=2)
                                        if blurb else ft.Container(height=0),
                                    ],
                                    spacing=4, expand=True,
                                ),
                                ft.IconButton(ft.Icons.CLOSE_ROUNDED,
                                              icon_color=TEXT_DIM, icon_size=20,
                                              tooltip=i18n.t("Close"), on_click=_close),
                            ],
                            spacing=16,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER,
                        ),
                        pixel_divider(),
                        detail_body,
                    ],
                    spacing=16, tight=True,
                ),
            ),
        )

        dialogs.open_dialog(page, dlg)

        installed_now = {}
        try:
            items = _cached_installed(content_type)
            for m in items:
                if m.get("filename"):
                    installed_now[m["filename"]] = m
        except Exception:
            installed_now = {}

        # --- Shared install plumbing ---------------------------------------
        # One path for the top "Install latest" button and every row in the
        # version list, so their states can never drift apart.
        def _human_count(n):
            try:
                n = int(n)
            except (TypeError, ValueError):
                return str(n)
            if n >= 1_000_000:
                return f"{n / 1_000_000:.1f}M".replace(".0M", "M")
            if n >= 1_000:
                return f"{n / 1_000:.1f}K".replace(".0K", "K")
            return str(n)

        def _plain_preview(md):
            """A short, readable teaser from the Markdown body: images, links
            and markup stripped, whitespace collapsed."""
            t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md or "")
            t = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", t)
            t = re.sub(r"<[^>]+>", " ", t)
            t = re.sub(r"[#>*_`~|]+", " ", t)
            return re.sub(r"\s+", " ", t).strip()

        def _run_install(v, details, *, on_status, on_done, on_error):
            # Progress on whatever control shows status: whole-percent only, so
            # page.update() isn't flooded on fast links. The core reports the
            # mod + its required dependencies as ONE batch counted in FILE UNITS,
            # so the label says "file 2/3" and the percent is of the whole batch
            # - a single file no longer restarts the bar at 0 (see
            # batch_progress_text).
            _pct = {"v": -1}
            _eta = cubeon_eta.EtaEstimator()

            def _install_progress(done, total):
                pct = min(100, int(done * 100 / total)) if total else -1
                if pct != _pct["v"]:
                    _pct["v"] = pct
                    on_status(progress_text(done, total, batch=True,
                                            eta=_eta.note(done, total)))

            def worker():
                try:
                    result = {"failed": []}
                    if content_type == "mod":
                        result = core.install_mod_with_dependencies(
                            v["url"], v["filename"],
                            mc_version=detail_mc, loader=detail_loader,
                            version_id=detail_version,
                            slug=details.get("slug"), project_id=details.get("project_id"),
                            hashes=v.get("hashes"),
                            status_cb=on_status, progress_cb=_install_progress,
                        )
                    else:
                        core.download_content(
                            content_type, v["url"], v["filename"],
                            mc_version=detail_mc, version_id=detail_version,
                            loader=detail_loader, hashes=v.get("hashes"),
                            icon_url=details.get("icon_url"),
                            slug=details.get("slug"),
                            title=details.get("title"),
                            progress_cb=lambda done, total: on_status(progress_text(done, total)))
                    if result.get("failed"):
                        _refresh_after_install((content_type, detail_mc, detail_loader, detail_version))
                        on_error(RuntimeError("Installed, but dependencies failed: "
                                              + ", ".join(result["failed"])))
                        return
                    # Automatic repair: an install is exactly when a stale
                    # duplicate or a missing dependency tends to appear.
                    fixed = 0
                    try:
                        report = (core.mod_doctor(
                            detail_mc, detail_loader,
                            auto_fix=True, status_cb=on_status, approve_cb=None,
                            version_id=detail_version)
                            if content_type == "mod" else {})
                        fixed = len(report.get("fixed") or [])
                    except Exception:
                        fixed = 0
                    _refresh_after_install((content_type, detail_mc, detail_loader, detail_version))
                    with thread_safe_ui.TREE_LOCK:
                        installed_now[v["filename"]] = {"filename": v["filename"]}
                        on_done(fixed)
                except Exception as ex:
                    on_error(ex)
            try:
                threading.Thread(target=worker, daemon=True).start()
            except Exception as error:
                on_error(error)

        quick_state = {"repaints": []}

        def _install_button(v, details, *, label="Install", big=False):
            """An Install button that owns its busy / done / error states."""
            done = {"v": bool(installed_now.get(v.get("filename")))}
            blocked = (not detail_mc or not detail_loader or not detail_version
                       or not v.get('url') or not v.get('filename')
                       or (content_type != "resourcepack" and detail_loader not in MOD_CAPABLE_LOADERS)
                       or v.get('compatible') is False)
            blocked_note = ('This release has no downloadable file.' if not v.get('url') or not v.get('filename') else
                            "This build doesn't match this instance's Minecraft version or loader."
                            if v.get('compatible') is False else
                            'Choose a compatible mod loader on the Play tab first.')
            fg = ON_ACCENT if big else ACCENT
            text = ft.Text(label, size=13 if big else 12,
                           weight=ft.FontWeight.W_700,
                           color=TEXT_FAINT if done["v"] else fg)
            icon = ft.Icon(ft.Icons.CHECK_ROUNDED if done["v"]
                           else ft.Icons.DOWNLOAD_ROUNDED,
                           color=TEXT_FAINT if done["v"] else fg,
                           size=16 if big else 15)
            btn = ft.Container(
                content=ft.Row([icon, text], spacing=8, tight=True),
                bgcolor=ACCENT_TINT if done["v"]
                else (ACCENT if big else ACCENT_TINT),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(
                    horizontal=16 if big else 12, vertical=12 if big else 8),
                ink=False, disabled=done["v"] or blocked,
                tooltip=blocked_note if blocked else None,
            )

            seen = {"result": feedback.result_id}
            def paint(job):
                if seen["result"] != job.result_id:
                    seen["result"] = job.result_id
                    if job.result == "success" and job.filename:
                        installed_now[job.filename] = {"filename": job.filename}
                done["v"] = bool(installed_now.get(v.get("filename")))
                btn.disabled = job.busy or done["v"] or blocked
                text.value = compact_status(job.text) if job.busy else (
                    i18n.t("Installed") if done["v"] else "Try again" if job.result == "error" else label)
                text.color = TEXT_DIM if job.busy else TEXT_FAINT if done["v"] else DANGER if job.result == "error" else fg
                icon.icon = ft.Icons.CHECK_ROUNDED if done["v"] and not job.busy else ft.Icons.DOWNLOAD_ROUNDED
                icon.color = text.color
                btn.bgcolor = ROW_HOVER if job.busy else ACCENT_TINT if done["v"] or not big else ACCENT
                btn.tooltip = job.text if job.busy or job.result == "error" else (
                    blocked_note if blocked else None)

            def on_click(e):
                if done["v"] or blocked or not feedback.start(v.get("filename"), "Installing..."):
                    return

                def finished(fixed):
                    feedback.finish(v.get("filename"))
                    for _repaint in quick_state.get("repaints", []):
                        try:
                            _repaint()
                        except Exception:
                            pass
                    if fixed:
                        dialogs.show_snack(page, f"Installed. Fixed {fixed} problem(s).",
                                           bgcolor=SURFACE_HI, text_color=TEXT)

                def failed(ex):
                    feedback.finish(v.get("filename"), error=f"Install failed: {ex}")
                    dialogs.show_snack(page, f"Install failed: {ex}",
                                       bgcolor=SURFACE_HI, text_color=TEXT)

                _run_install(v, details, on_status=feedback.status,
                             on_done=finished, on_error=failed)

            btn.on_click = on_click
            feedback.watch(btn, paint)
            return btn

        def _gallery_strip(gallery):
            """All screenshots, hero first, in a sideways-scrolling strip -
            one image made the menu feel like it was hiding the rest."""
            tiles = []
            for g in gallery[:8]:
                tiles.append(ft.Container(
                    content=_art_image(g['url'], 300, 170),
                    border_radius=RADIUS,
                    clip_behavior=ft.ClipBehavior.ANTI_ALIAS,
                    border=ft.border.Border.all(1, CARD_BORDER),
                ))
            return ft.Row(tiles, spacing=12, scroll=ft.ScrollMode.AUTO)

        def _meta_line(details):
            """Only what a player decides on: how popular it is, what loader it
            runs on, and which Minecraft versions it covers."""
            pills = []
            if details.get("downloads"):
                pills.append(_detail_badge(
                    _human_count(details["downloads"]) + " downloads"))
            loaders = details.get("loaders") or []
            if loaders:
                pills.append(_detail_badge(
                    " / ".join(x.title() for x in loaders[:3])))
            gvs = details.get("game_versions") or []
            if gvs:
                shown = ", ".join(gvs[:3]) + ("…" if len(gvs) > 3 else "")
                pills.append(_detail_badge("Minecraft " + shown))
            return ft.Row(pills, spacing=8, run_spacing=8, wrap=True) if pills else None

        def _quick_action(details, versions):
            """The one thing most people came to do, at the top: get the newest
            build that matches their game, or see they already have it - no
            scanning a long list required."""
            compat = [v for v in versions if v.get("compatible") and v.get("url")]
            compat.sort(key=lambda v: v.get("date_published") or "", reverse=True)
            holder = ft.Container()

            def _paint():
                if not compat:
                    holder.content = ft.Row(
                        [ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, size=16,
                                 color=TEXT_DIM),
                         ft.Text("No build for your Minecraft version yet.",
                                 size=12.5, color=TEXT_DIM)],
                        spacing=8)
                else:
                    best = compat[0]
                    vnum = str(best.get("version_number")
                               or best.get("name") or "").split("+", 1)[0]
                    if installed_now.get(best.get("filename")):
                        holder.content = ft.Row(
                            [ft.Icon(ft.Icons.CHECK_CIRCLE_ROUNDED, size=20,
                                     color=ACCENT),
                             ft.Column(
                                 [ft.Text("You're up to date", size=13,
                                          color=ACCENT,
                                          weight=ft.FontWeight.W_700),
                                  ft.Text(f"{vnum} is installed", size=11.5,
                                          color=TEXT_DIM)],
                                 spacing=4, expand=True)],
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER)
                    else:
                        holder.content = ft.Row(
                            [ft.Column(
                                [ft.Text("Latest for your setup", size=11,
                                         color=ft.Colors.with_opacity(0.7, TEXT), font_family=FONT_MONO),
                                 ft.Text(vnum, size=16, color=TEXT,
                                         weight=ft.FontWeight.W_800,
                                         font_family=FONT_DISPLAY)],
                                spacing=4, expand=True),
                             _install_button(best, details,
                                             label="Install latest", big=True)],
                            spacing=12,
                            vertical_alignment=ft.CrossAxisAlignment.CENTER)
                try:
                    thread_safe_ui.refresh(holder)
                except Exception:
                    pass

            quick_state["repaints"].append(_paint)
            _paint()
            holder.bgcolor = CARD_FILL
            holder.border = ft.border.Border.all(1, CARD_BORDER)
            holder.border_radius = RADIUS
            holder.padding = ft.padding.Padding.symmetric(horizontal=16, vertical=12)
            return holder

        def _description_block(body):
            """The README is useful but enormous; show a three-line teaser with
            a 'Read more' toggle instead of burying the versions below a wall
            of text."""
            preview = _plain_preview(body)
            if not preview:
                return None
            full = {"ctrl": None, "shown": False}
            holder = ft.Column(spacing=8)
            toggle_text = ft.Text("Read more", size=12, color=ACCENT,
                                  weight=ft.FontWeight.W_700)
            toggle = ft.Container(
                content=toggle_text, ink=False,
                padding=ft.padding.Padding.symmetric(vertical=4))
            text_ctrl = ft.Text(
                preview + ("…" if len(body) > len(preview) else ""),
                size=12.5, color=TEXT_DIM)

            def _toggle(e=None):
                if full["shown"]:
                    holder.controls = [text_ctrl, toggle]
                    toggle_text.value = "Read more"
                    full["shown"] = False
                else:
                    if full["ctrl"] is None:
                        full["ctrl"] = ft.Markdown(
                            body, selectable=True,
                            extension_set=ft.MarkdownExtensionSet.GITHUB_WEB,
                            shrink_wrap=True)
                    holder.controls = [full["ctrl"], toggle]
                    toggle_text.value = "Show less"
                    full["shown"] = True
                thread_safe_ui.refresh(holder)

            toggle.on_click = _toggle
            holder.controls = [text_ctrl, toggle]
            return ft.Column(
                [ft.Text("About this mod", size=15, color=TEXT,
                         weight=ft.FontWeight.W_700, font_family=FONT_DISPLAY),
                 holder],
                spacing=8)

        def _versions_section(details, versions):
            """Compatible builds first, and only a handful of them - a mod like
            Sodium has hundreds of releases across every Minecraft version."""
            compat = [v for v in versions if v.get("compatible")]
            compat.sort(key=lambda v: v.get("date_published") or "", reverse=True)
            others = [v for v in versions if not v.get("compatible")]
            others.sort(key=lambda v: v.get("date_published") or "", reverse=True)
            version_limit = {'value': 8}
            list_holder = ft.Column(spacing=4)
            more_text = ft.Text("", size=12, color=ACCENT,
                                weight=ft.FontWeight.W_700)
            more = ft.Container(content=more_text, visible=False, ink=False,
                                padding=ft.padding.Padding.symmetric(vertical=8))

            def _paint():
                rows = []
                if not versions:
                    rows.append(ft.Text("No versions are available for this mod.",
                                        size=12.5, color=TEXT_DIM))
                else:
                    ordered = compat + others
                    for v in ordered[:version_limit['value']]:
                        rows.append(_build_version_row(v, details))
                    hidden = max(0, len(ordered) - version_limit['value'])
                    if not hidden and version_limit['value'] > 8:
                        more.visible = True
                        more_text.value = "Show fewer versions"
                    elif hidden > 0:
                        more.visible = True
                        more_text.value = f"Show more versions ({hidden} more)"
                    else:
                        more.visible = False
                list_holder.controls = rows
                try:
                    thread_safe_ui.refresh(list_holder)
                    thread_safe_ui.refresh(more)
                except Exception:
                    pass

            def _toggle(e=None):
                version_limit['value'] = (version_limit['value'] + 25
                                          if version_limit['value'] < len(versions) else 8)
                _paint()

            more.on_click = _toggle
            _paint()
            quick_state["repaints"].append(_paint)
            return ft.Column(
                [ft.Text(i18n.t("Versions"), size=15, color=TEXT,
                         weight=ft.FontWeight.W_700, font_family=FONT_DISPLAY),
                 list_holder, more],
                spacing=8)

        def _render_details(details, versions):
            controls = []
            gallery = [g for g in (details.get("gallery") or []) if g.get("url")]
            if gallery:
                controls.append(_gallery_strip(gallery))
            meta = _meta_line(details)
            if meta is not None:
                controls.append(meta)
            controls.append(_quick_action(details, versions))
            desc = _description_block(details.get("body") or "")
            if desc is not None:
                controls.append(pixel_divider())
                controls.append(desc)
            controls.append(pixel_divider())
            controls.append(_versions_section(details, versions))

            detail_body.controls.clear()
            detail_body.controls.extend(controls)
            thread_safe_ui.refresh(detail_body)

        def _build_version_row(v, details):
            vnum = str(v.get("version_number") or v.get("name")
                       or "version").split("+", 1)[0]
            already = installed_now.get(v.get("filename"))

            tags = list(v.get("loaders") or [])
            gv = v.get("game_versions") or []
            tag_text = " · ".join([x.title() for x in tags] + [", ".join(gv[:3])])
            if len(gv) > 3:
                tag_text += "…"

            return ft.Container(
                content=ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Row(
                                    [ft.Text(vnum, size=13.5, color=TEXT,
                                             weight=ft.FontWeight.W_700),
                                     *([_detail_badge("match", "accent")]
                                       if v.get("compatible")
                                       else [_detail_badge("other version")])],
                                    spacing=8,
                                    vertical_alignment=ft.CrossAxisAlignment.CENTER,
                                ),
                                ft.Text(
                                    (v.get("version_type") or "release").title()
                                    + (f"  ·  {tag_text}" if tag_text else ""),
                                    size=11, color=TEXT_FAINT,
                                    font_family=FONT_MONO, max_lines=2),
                            ],
                            spacing=4, expand=True,
                        ),
                        _install_button(
                            v, details,
                            label="Installed" if already else "Install"),
                    ],
                    spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                bgcolor=CARD_FILL if already else None,
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=8, vertical=8),
            )

        def worker():
            details, versions, err = None, [], None
            try:
                details = core.get_mod_details(ref) or {}
            except Exception as ex:
                err = ex
            if details is None:
                details = {}
            try:
                versions = core.get_mod_versions(
                    ref, mc_version=detail_search_mc,
                    loader=detail_loader if content_type == "mod" else None)
                if content_type != "mod":
                    candidates = content_mc_versions(detail_search_mc)
                    versions = [dict(v, compatible=(not candidates or any(
                        candidate in (v.get("game_versions") or []) for candidate in candidates)))
                        for v in versions]
            except Exception:
                versions = []
            try:
                _target, items, _mods = _read_installed_snapshot(
                    (content_type, detail_mc, detail_loader, detail_version))
                with thread_safe_ui.TREE_LOCK:
                    installed_now.clear()
                    installed_now.update((m['filename'].removesuffix('.disabled'), m)
                                         for m in items if m.get('filename'))
            except Exception:
                logging.getLogger(__name__).debug('detail installed scan failed', exc_info=True)
            if not details and not versions:
                def _failed():
                    detail_body.controls.clear()
                    detail_body.controls.append(ft.Text(
                        "Couldn't load this mod's details. Check your "
                        "connection and try again.", size=13, color=TEXT_DIM))
                    thread_safe_ui.refresh(detail_body)
                with thread_safe_ui.TREE_LOCK:
                    _failed()
                return
            with thread_safe_ui.TREE_LOCK:
                _render_details(details, versions)

        try:
            threading.Thread(target=worker, daemon=True).start()
        except Exception as error:
            with thread_safe_ui.TREE_LOCK:
                detail_body.controls[:] = [empty_state('Couldn\'t load details', str(error))]
                thread_safe_ui.refresh(detail_body)

    def _browse_page_prev(e=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if browse_state["page"] > 0:
                browse_state["page"] -= 1
                _render_browse_page()

    def _browse_page_next(e=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            total_pages = max(1, browse_state["total_pages"])
            if browse_state["page"] < total_pages - 1:
                browse_state["page"] += 1
                _render_browse_page()

    browse_pager_prev.on_click = _browse_page_prev
    browse_pager_next.on_click = _browse_page_next

    def build_browse_row(mod, is_installed=False):
        """
        Creates a row for a mod in the browse results.

        Reads like a store listing, not a database record: the mod's NAME is
        the dominant element (15px, bold), its description sits underneath at
        readable size, and download count is tiny metadata. The whole row is
        transparent until hovered - no enclosing slab - and the download
        action is a restrained green wash instead of a solid block, so five
        rows don't stack five loud buttons.
        """
        builtin = bool(mod.get('builtin_client'))
        row_content_type = _ct()
        if mod.get('slug') and mod.get('icon_url'):
            installed_icon_urls[mod['slug']] = mod['icon_url']
        row_target = _installed_target(row_content_type)
        compatibility_note = (mod_compatibility_note(
            mod, current_mc_version_for_search(), state.get("mod_loader"))
            if row_content_type == "mod" else "")
        key = _row_key(mod.get("project_id") or mod.get("slug") or mod["title"])
        feedback = install_registry.project(key[:4], mod.get("project_id") or mod.get("slug") or mod.get("title"), mod.get("slug"))
        cached = browse_rows.get(key)
        if cached and cached[0] == mod:
            cached[2](is_installed)
            return cached[1]
        available = not is_installed and not compatibility_note and _can_install(row_content_type)
        # The download button's text and icon change based on installed status
        download_btn_text = ft.Text(
            i18n.t("Installed") if is_installed else "Unavailable" if compatibility_note else "Install",
            size=12.5, weight=ft.FontWeight.W_700,
            color=ON_ACCENT if available else TEXT_DIM,
        )
        download_btn = ft.Container(
            content=ft.Row(
                [
                    ft.Icon(ft.Icons.CHECK_ROUNDED if is_installed else ft.Icons.DOWNLOAD_ROUNDED,
                            color=ON_ACCENT if available else TEXT_DIM, size=15),
                    download_btn_text,
                ],
                spacing=8, tight=True,
            ),
            bgcolor=ACCENT if available else None,
            width=104 if builtin else 84, height=30, alignment=ft.Alignment.CENTER,
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
            ink=False,
            disabled=is_installed or bool(compatibility_note) or not _can_install(row_content_type),
            tooltip=compatibility_note or ("Choose a compatible mod loader on the Play tab first." if not _can_install(row_content_type) else None),
        )

        def on_download(e):
            """
            Handles the download of a mod. It finds the appropriate file (compatible with
            current Minecraft version and loader), then downloads it and refreshes the installed list.
            """
            if builtin:
                _install_client(row_target, feedback)
                return
            content_type = row_content_type
            if row_target != _installed_target(row_content_type):
                return
            if not _can_install(content_type) or (content_type == "mod" and mod_compatibility_note(
                    mod, current_mc_version_for_search(), state.get("mod_loader"))):
                return
            selected_mc = state["selected_mc_version"]
            selected_version = version_dropdown.value
            search_mc_version = current_mc_version_for_search()
            selected_loader = state.get("mod_loader")
            if row_state["installed"] or not feedback.start():
                return

            def worker():
                try:
                    # Search against the numeric MC version (Modrinth wants
                    # "1.20.4", not a loader-qualified id). For mods, STORE the
                    # download under state["selected_mc_version"] + loader - the
                    # exact keys list_mods()/sync_mods_to_game() use - so the
                    # mod ends up in the profile the game reads. Resource packs
                    # and shaders also use the captured instance's profile.
                    if content_type == "mod":
                        file_info = core.get_mod_download(mod["project_id"], mc_version=search_mc_version, loader=selected_loader)
                    else:
                        file_info = core.get_content_download(content_type, mod["project_id"], mc_version=search_mc_version)
                    if not file_info:
                        feedback.finish(error="No matching file for this version and loader.")
                        return

                    feedback.status("Downloading...")
                    # Progress on the button itself (bugs-and-flaws follow-up: a
                    # static "Downloading..." gave no way to tell a 2 MB shader
                    # from a 400 MB mod). Coalesced to whole percent so
                    # page.update() isn't flooded. The two callers below report
                    # in DIFFERENT units, so each gets its own label: the mod
                    # path counts the whole install (the mod + its required
                    # dependencies) in FILE UNITS, the resourcepack/shader path
                    # counts bytes.
                    _pct = {"v": -1}

                    def _reporter(label_fn):
                        _eta = cubeon_eta.EtaEstimator()

                        def _report(done, total):
                            pct = min(100, int(done * 100 / total)) if total else done // 65536
                            if pct == _pct["v"]:
                                return
                            _pct["v"] = pct
                            feedback.status(label_fn(done, total, _eta.note(done, total)))
                        return _report

                    def _bytes_label(done, total, eta=None):
                        return progress_text(done, total, eta=eta)

                    _progress = _reporter(_bytes_label)
                    _batch_progress = _reporter(lambda d, t, eta: progress_text(d, t, batch=True, eta=eta))
                    # Keep dependency/repair details in the success tooltip;
                    # the compact action label stays readable.
                    deps_note = ""
                    # Any compatibility repair the install needed, so the user
                    # is told why a pack they just installed was touched.
                    fix_note = {"text": ""}

                    def _note_fix(rep):
                        fix_note["text"] = rep.get("reason") or ""

                    if content_type == "mod":
                        # mc_version/loader must be passed explicitly - without
                        # them this silently lands in the wrong profile folder
                        # (get_profile_dir(None, None) => "unknown-vanilla") and
                        # the game never finds it at launch. See cubeon/mods.py.
                        #
                        # install_mod_with_dependencies also pulls in every
                        # REQUIRED Modrinth dependency the profile doesn't have
                        # yet (Fabric API is the classic one), so a fresh click
                        # actually results in a mod that loads in-game.
                        def _dep_status(t):
                            feedback.status(t)
                        result = core.install_mod_with_dependencies(
                            file_info["url"], file_info["filename"],
                            mc_version=selected_mc, loader=selected_loader,
                            version_id=selected_version,
                            slug=mod.get("slug"), project_id=mod.get("project_id"),
                            hashes=file_info.get("hashes"),
                            status_cb=_dep_status, progress_cb=_batch_progress,
                        )
                        deps_note = f" +{len(result['installed']) - 1} deps" \
                            if len(result["installed"]) > 1 else ""
                        if result["failed"]:
                            feedback.finish(file_info["filename"], error="Installed, but dependencies failed: " + ", ".join(result["failed"]))
                            _refresh_after_install((content_type, selected_mc, selected_loader, selected_version))
                            return
                    else:
                        # hashes = Modrinth's per-file sha512/sha1; passing them
                        # makes the install reject a corrupt/truncated transfer
                        # instead of dropping bad bytes into resourcepacks/.
                        # mc_version/version_id/fix_cb: the core then checks the
                        # pack's own pack.mcmeta against every installed version
                        # and widens its range if the game would show it as
                        # Incompatible (an author's Modrinth version list is not
                        # what the game reads).
                        core.download_content(
                            content_type, file_info["url"], file_info["filename"],
                            progress_cb=_progress,
                            hashes=file_info.get("hashes"),
                            mc_version=selected_mc,
                            version_id=selected_version,
                            loader=selected_loader,
                            icon_url=mod.get("icon_url"),
                            slug=mod.get("slug"),
                            title=mod.get("title"),
                            fix_cb=_note_fix)

                    feedback.finish(file_info["filename"], note=fix_note["text"] or (
                        "Installed" + deps_note if deps_note else None))
                    _refresh_after_install((content_type, selected_mc, selected_loader, selected_version))
                    # Automatic repair: catch a duplicate/missing dependency
                    # introduced by this install before it can crash a launch.
                    if (content_type == "mod" and selected_mc == state["selected_mc_version"]
                            and selected_loader == browse_loader()
                            and selected_version == version_dropdown.value):
                        run_mod_repair()
                except Exception as ex:
                    # Say WHY in one line - "Failed" alone left the user with
                    # no idea whether to retry, free up disk, or pick another
                    # file. net.DownloadError messages are already human-sized.
                    reason = (str(ex).strip().splitlines() or [""])[0] \
                        or type(ex).__name__
                    feedback.finish(error=f"Failed - {status_text.human(reason)}")

            try:
                threading.Thread(target=worker, daemon=True).start()
            except Exception as error:
                feedback.finish(error=f"Couldn't start installation: {error}")

        if not is_installed:
            download_btn.on_click = on_download

        description = (mod.get("description") or "").strip()
        installed_badge = ft.Container(
            ft.Row([ft.Icon(ft.Icons.CHECK_ROUNDED, size=11, color=ACCENT),
                    ft.Text(i18n.t('Installed'), size=9, color=ACCENT)], spacing=3, tight=True),
            bgcolor=ACCENT_TINT, border_radius=4,
            padding=ft.padding.Padding.symmetric(horizontal=5, vertical=2), visible=is_installed,
        )

        # Cache this row's art for the next render (no-op if already cached).

        # Match the compact catalogue tile used for every content kind.
        row = style_tile(
            ft.Container(
                content=ft.Row(
                    [
                        # Mod icon (or placeholder if none) - disk-cached art
                        (ft.Image(src="icon_64.png", width=44, height=44, fit=ft.BoxFit.CONTAIN)
                         if builtin else _art_image(mod.get("icon_url"), 44, 44)),
                        # Title leads; description and metadata support it.
                        ft.Column(
                            [
                                ft.Row([ft.Text(mod["title"], size=13.5, color=TEXT,
                                                weight=ft.FontWeight.W_700, max_lines=1,
                                                overflow=ft.TextOverflow.ELLIPSIS, expand=True, expand_loose=True),
                                        installed_badge], spacing=6),
                                ft.Text(mod.get('author') or mod.get('author_name') or 'Community project',
                                        size=11.5, color=TEXT_DIM, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                                ft.Text("Bundled with Cubeon", size=10.5, color=TEXT_FAINT) if builtin else
                                ft.Row([ft.Icon(ft.Icons.DOWNLOAD_OUTLINED, size=12, color=TEXT_FAINT),
                                        ft.Text(downloads_label(mod.get('downloads')), size=10.5, color=TEXT_FAINT)], spacing=4),
                            ],
                            spacing=4, expand=True,
                        ),
                        download_btn,
                    ],
                    spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER,
                ),
                border_radius=RADIUS,
                padding=ft.padding.Padding.symmetric(horizontal=12, vertical=14),
                tooltip=compatibility_note or description or f"{mod.get('downloads', 0):,} downloads · Open details",
            ),
            SURFACE, BORDER, ROW_HOVER,
        )
        row.on_click = None if builtin else lambda e: open_mod_detail(mod, row_content_type)
        if builtin:
            row.data = 'cubeon-client-browse'
            download_btn.data = 'cubeon-client-install'

        row_state = {"installed": is_installed, "result": feedback.result_id}
        def paint(job):
            if row_state["result"] != job.result_id:
                row_state["result"] = job.result_id
                if job.result == "success":
                    row_state["installed"] = True
            installed = row_state["installed"]
            installed_badge.visible = installed and not job.busy
            download_btn.visible = builtin or not installed or job.busy
            icon = download_btn.content.controls[0]
            icon.icon = ft.Icons.CHECK_ROUNDED if installed and not job.busy else ft.Icons.DOWNLOAD_ROUNDED
            download_btn_text.value = compact_status(job.text) if job.busy else (
                "Try again" if builtin and job.result == "error" else
                "Reinstall" if builtin and installed else i18n.t("Installed") if installed else "Try again" if job.result == "error"
                else "Unavailable" if compatibility_note else "Install")
            can_install = (builtin or not installed) and not compatibility_note and _can_install(row_content_type)
            download_btn_text.color = (TEXT_DIM if job.busy or not can_install else
                                       DANGER if job.result == 'error' else ON_ACCENT)
            icon.color = download_btn_text.color
            download_btn.bgcolor = SURFACE_HI if job.busy else ACCENT if can_install and job.result != 'error' else None
            download_btn.disabled = job.busy or (installed and not builtin) or bool(compatibility_note) or not _can_install(row_content_type)
            download_btn.tooltip = job.text if job.busy or job.result == "error" else (
                job.note if installed else compatibility_note or None)
            download_btn.on_click = None if installed and not builtin and not job.busy else on_download

        def sync_action(installed):
            row_state["installed"] = installed
            paint(feedback)

        feedback.watch(download_btn, paint)
        feedback.watch(row, paint)

        _remember_row(browse_rows, key, (dict(mod), row, sync_action))
        return row

    # Warning shown when Vanilla is selected - mods never load without a mod
    # loader, so it's better to say that plainly than let the tab look
    # "installed" for nothing.
    vanilla_mods_notice = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, color=TEXT_DIM, size=14),
                ft.Text(
                    "Mods need Fabric, Quilt, Forge, or NeoForge. Choose a loader on Play.",
                    size=12, color=TEXT_DIM,
                ),
            ],
            spacing=8,
        ),
        visible=(state["mod_loader"] == "vanilla"),
        padding=ft.padding.Padding.symmetric(vertical=8),
    )

    # Shown on the Shaders segment: a shader .zip only does anything if Iris
    # (Fabric) or OptiFine is installed to read it, so say so plainly rather
    # than let a downloaded shader look like it should "just work".
    shader_notice_text = ft.Text("", size=12.5, color=TEXT_DIM, expand=True)
    shader_setup_label = ft.Text("Set up shaders", size=12.5, color=ACCENT,
                                 weight=ft.FontWeight.W_700)
    shader_setup_btn = ft.Container(
        content=ft.Row([ft.Icon(ft.Icons.AUTO_AWESOME_ROUNDED, size=15, color=ACCENT),
                        shader_setup_label], spacing=8, tight=True),
        bgcolor=ACCENT_TINT, border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=16, vertical=8),
        ink=False,
        on_click=lambda e: _setup_shaders(),
    )
    shader_notice = ft.Container(
        content=ft.Row(
            [
                ft.Icon(ft.Icons.INFO_OUTLINE_ROUNDED, color=TEXT_DIM, size=14),
                shader_notice_text,
                shader_setup_btn,
            ],
            spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        visible=False,
        padding=ft.padding.Padding.symmetric(vertical=8),
    )

    def _sync_shader_notice():
        """Describe shader support without promising an instance conversion."""
        loader = state.get('mod_loader')
        shader_setup_btn.disabled = setup_busy['v'] or not _can_install('shader')
        if loader in ("fabric", "quilt", 'neoforge'):
            shader_notice_text.value = ("Shaders need Iris (with Sodium) to run. "
                                        "Install the compatible build for this instance.")
            shader_setup_label.value = "Install Iris"
        elif loader == 'forge':
            shader_notice_text.value = 'Shaders need Oculus and its dependencies. Availability depends on your Minecraft version.'
            shader_setup_label.value = 'Install Oculus'
        else:
            shader_notice_text.value = 'Shaders need a mod loader. Create or choose a Fabric instance on Play first.'
            shader_setup_label.value = "Set up shaders"

    setup_busy = {"v": False}

    def _setup_shaders():
        """Install Iris or Oculus and required dependencies for this loader.

        Resolve compatible builds without changing the selected instance.
        """
        if setup_busy["v"]:
            return
        target = _installed_target()

        def say(text, bad=False):
            with thread_safe_ui.TREE_LOCK:
                if target != _installed_target():
                    return
                local_install_status.value = text
                local_install_status.color = DANGER if bad else TEXT_DIM
                local_install_status.visible = True
                thread_safe_ui.refresh(local_install_status)

        if not state.get("selected_mc_version") or not version_dropdown.value:
            say("Pick a Minecraft version on the Play tab first.", bad=True)
            return
        if not _can_install('shader'):
            say('Choose a mod-loader instance on Play first.', bad=True)
            return
        setup_busy["v"] = True
        shader_setup_btn.disabled = True
        shader_setup_label.value = "Setting up..."
        thread_safe_ui.refresh(shader_setup_btn)

        def worker():
            try:
                loader, mc, version_id, search_mc = setup_target
                project = 'oculus' if loader == 'forge' else 'iris'
                label = project.title()
                say(f"Finding {label}...")
                info = core.get_mod_download(project, mc_version=search_mc, loader=loader)
                if not info:
                    say(f"{label} has no build for Minecraft {search_mc} with {loader.title()}. Choose another compatible instance.", bad=True)
                    return
                result = core.install_mod_with_dependencies(
                    info["url"], info["filename"],
                    mc_version=mc, loader=loader, version_id=version_id,
                    slug=project, project_id=info.get("project_id") or project,
                    hashes=info.get("hashes"),
                    status_cb=lambda t: say(status_text.human(t)),
                    progress_cb=lambda done, total: say(
                        f"Installing {label} and dependencies... {int(done * 100 / total)}%") if total else None,
                )
                _refresh_after_install(target)
                if result.get("failed"):
                    say("Installed, but these failed: " + ", ".join(result["failed"]), bad=True)
                else:
                    say(f"{label} is installed. Add a shader pack, press Play, then select it in the game's shader settings.")
            except Exception as ex:
                say(f"Couldn't set up shaders: {ex}", bad=True)
            finally:
                with thread_safe_ui.TREE_LOCK:
                    setup_busy["v"] = False
                    _sync_shader_notice()
                    thread_safe_ui.refresh(shader_notice)

        setup_target = (state.get('mod_loader'), state['selected_mc_version'],
                        version_dropdown.value, current_mc_version_for_search())
        try:
            threading.Thread(target=worker, daemon=True, name="ux-shader-setup").start()
        except Exception as error:
            setup_busy['v'] = False
            shader_setup_btn.disabled = False
            say(f"Couldn't start shader setup: {error}", bad=True)
            _sync_shader_notice()

    # Tracks the (version, loader) profile the browse section currently
    # reflects, so we only re-fetch recommendations/search when it's
    # actually stale, not on every unrelated refresh_mods_list() call.
    browse_profile = {"key": None}

    # --- Browse / Installed view tabs ---------------------------------------
    # One thing on screen at a time: the browse surface (search + results)
    # or the installed list. Switching is instant and free - both panes stay
    # mounted, only their visibility flips, so nothing is rebuilt or
    # re-fetched on toggle.
    active_view = {"value": "browse"}  # "browse" | "installed"

    browse_pane = ft.Column(
        [
            ft.Row([mod_search_field, filters_button], spacing=8),
            category_chips_container,
            ft.Row([browse_title_text, ft.Container(expand=True), browse_status_text],
                   alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            browse_results_view,
            browse_pager_row,
        ],
        spacing=12,
        visible=True,
        expand=True,
    )

    # Keep opt-in available after an OFF launch removes the managed client
    # JAR, or before the first launch has installed it.
    client_preference_switch = animated_switch(
        value=bool(cfg.get('client_mod_enabled', True)), active_color=ACCENT, scale=0.85,
        on_change=lambda e: _change_client_enabled(bool(client_preference_switch.value)),
        tooltip='Enable or disable Cubeon Client for all instances on the next launch',
    )
    client_preference_switch.data = 'installed-cubeon-client-enabled'
    client_preference_row = ft.Row([
        ft.Column([ft.Text('Cubeon Client', color=TEXT, size=13.5, weight=ft.FontWeight.W_600),
                   ft.Text('Applies to all instances on the next launch.', color=TEXT_DIM, size=11.5)],
                  spacing=4, expand=True),
        client_preference_switch,
    ], visible=False, vertical_alignment=ft.CrossAxisAlignment.CENTER)

    installed_pane = ft.Column(
        [
            # One header row: title on the left, then the repair action, the
            # automatic-check status line and the count grouped on the right.
            # The row uses an expanding spacer, so it must not set wrap=True
            # (Flutter's wrapped layout cannot host flex children).
            ft.Row(
                [section_label(i18n.t("Installed")), ft.Container(expand=True),
                 check_repair_btn, repair_status, installed_count_text],
                spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER),
            repair_details,
            installed_status,
            client_preference_row,
            installed_filter_field,
            mods_list_view,
        ],
        spacing=12,
        visible=False,
        expand=True,
    )

    view_segment_row = ft.Row(spacing=8)

    def _build_view_segment():
        update_view_action(view_segment_row, active_view['value'], _installed_display_count(),
                           on_view_change, data='mods-installed-toggle', color=TEXT_DIM)

    def on_view_change(new_view):
        if active_view["value"] == new_view:
            return
        active_view["value"] = new_view
        browse_pane.visible = (new_view == "browse")
        installed_pane.visible = (new_view == "installed")
        browse_scope_text.visible = (new_view == "browse")
        compatible_only.visible = _is_mod()
        thread_safe_ui.refresh(browse_scope_text)
        thread_safe_ui.refresh(compatible_only)
        _build_view_segment()
        if new_view == "installed":
            refresh_mods_list(background=True)
            auto_check()
        thread_safe_ui.refresh(browse_pane)
        thread_safe_ui.refresh(installed_pane)

    def refresh_browse_for_new_profile():
        """
        Called whenever the selected version or loader changes elsewhere in
        the app (Play tab dropdown, loader switcher). The Installed list is
        already kept in sync via refresh_mods_list(), but the Browse section
        was only ever loaded once on first tab open - meaning if you changed
        version/loader afterward, it kept showing mods for the OLD profile,
        which could be the wrong version or not even support the new loader.
        This re-fetches so Browse always matches what's actually selected.
        """
        key = (state.get("selected_mc_version"), state.get("mod_loader"), version_dropdown.value)
        if key == browse_profile["key"]:
            return  # nothing actually changed for browse purposes
        browse_profile["key"] = key
        # Only bother re-fetching if the tab has been opened at least once -
        # otherwise this fires on startup before the user ever sees Mods.
        if state.get("mods_recommendations_loaded"):
            query = mod_search_field.value.strip()
            if query:
                run_mod_search()
            else:
                load_recommended_mods()

    build_category_chips()
    _build_view_segment()

    # Header title/subtitle are refs so _apply_type_labels() can retarget them
    # when the content-type segment switches (Mods -> Resource Packs -> Shaders).
    header_title = ft.Text(i18n.t("Mods"), size=26, weight=ft.FontWeight.W_700, color=TEXT,
                            font_family=FONT_DISPLAY)
    header_subtitle = ft.Text("Download mods, or manage what's already installed.",
                              size=13, color=TEXT_DIM)
    _apply_type_labels()  # sync the refs now that they exist
    selected_content = {'value': 'mod'}

    def selector_style(selected):
        return ft.ButtonStyle(
            color=TEXT if selected else TEXT_DIM, bgcolor=SURFACE_HI if selected else None,
            shape=ft.RoundedRectangleBorder(radius=6),
            side=ft.BorderSide(1, BORDER if selected else 'transparent'),
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
        )

    kinds = [('mod', 'Mods', ft.Icons.VIEW_IN_AR_OUTLINED)]
    if modpacks_content is not None:
        kinds.append(('modpack', 'Modpacks', ft.Icons.INVENTORY_2_OUTLINED))
    kinds.extend([('resourcepack', 'Resource Packs', ft.Icons.IMAGE_OUTLINED),
                  ('shader', 'Shaders', ft.Icons.AUTO_AWESOME_OUTLINED)])
    content_buttons = {
        kind: ft.TextButton(
            content=ft.Row([ft.Icon(icon, size=16), ft.Text(i18n.t(label), size=12,
                                                          weight=ft.FontWeight.W_600)], spacing=8, tight=True),
            style=selector_style(kind == 'mod'), on_click=lambda e, t=kind: on_content_type_change(t),
            data='content-' + kind,
        ) for kind, label, icon in kinds
    }
    content_selector = ft.Row(list(content_buttons.values()), spacing=8, scroll=ft.ScrollMode.AUTO)

    # Now assemble the Mods tab.
    #
    # Layout rhythm: section -> comfortable gap -> section. The old build
    # wrapped the results AND the installed list in bordered filled panels -
    # boxes around rows that were themselves boxes. Both wrappers are gone:
    # lists float directly on the surface, sections are separated by a single
    # Header action: "Install from file" (ghost button). Named so the local-
    # install worker can park it while an install runs (double-pick guard).
    local_install_btn = attach_hover(ft.Container(
        content=ft.Row(
            [ft.Icon(ft.Icons.UPLOAD_FILE_ROUNDED, color=TEXT_DIM, size=14),
             local_install_label],
            spacing=4, tight=True,
        ),
        border=ft.border.Border.all(1, CARD_BORDER),
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=12, vertical=4),
        tooltip="Install from a file on your computer",
        ink=False, on_click=open_local_mod_picker,
    ), "transparent", ROW_HOVER)

    # hairline divider, and spacing snaps to one consistent scale instead of
    # alternating huge gaps with dense slabs.
    mods_body = ft.Column(
        [
            # Header: just the title + one-line description.
            content_header(header_subtitle, view_segment_row, local_install_btn),
            ft.Container(height=16),
            # Contextual notices disappear without leaving another toolbar.
            ft.Column(
                [
                    local_install_status,
                    vanilla_mods_notice,
                    shader_notice,
                ],
                spacing=8,
            ),
            browse_pane,
            installed_pane,
        ],
        spacing=0,
        expand=True,
    )

    if modpacks_content is not None:
        modpacks_content.visible = False
    mods_tab = ft.Column([content_selector, mods_body,
                          *([modpacks_content] if modpacks_content is not None else [])],
                         spacing=16, expand=True)
    mods_tab.select_content_type = on_content_type_change
    def refresh_client_preference():
        with thread_safe_ui.TREE_LOCK:
            _render_installed_snapshot(_cached_installed(), loading=_installed_target() not in installed_snapshots)
    mods_tab.refresh_client_preference = refresh_client_preference

    mods_list_view.on_capacity_change = lambda capacity: _render_installed_snapshot(_cached_installed())

    def open_hook():
        if selected_content['value'] == 'modpack':
            if on_modpacks_open:
                on_modpacks_open()
            return
        run_mod_search()
        auto_check()

    return mods_tab, refresh_mods_list, open_hook, refresh_browse_for_new_profile
