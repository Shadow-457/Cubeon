"""Server plugins use the same retained card catalogue as Mods."""
import re
import threading
import time

import flet as ft
import launcher_core as core
from cubeon import scrolling, storage, thread_safe_ui
from cubeon import icons
from cubeon.background_refresh import BackgroundRefresh
from cubeon.icon_loader import IconLoader
from cubeon.theme import RADIUS, TEXT_FAINT, CARD_FILL, CARD_BORDER, ROW_HOVER, ON_ACCENT, animated_switch
from ui.content_states import empty_state
from ui.content_tiles import tile_grid, layout_tiles, loading_tiles, style_tile, downloads_label, content_header, update_view_action, catalogue_views
from ui.detail_dialog import open_project_detail
from ui.image_memory import preview_image
from ui.install_feedback import InstallRegistry, InstallFeedback, compact_status, progress_text


def build_plugins_catalogue(page, active_version, *, section_label,
                            BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                            TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO):
    installed_plugins_list = tile_grid()
    plugin_results_list = tile_grid()
    installed_plugins_count = ft.Text('', size=12, color=TEXT_DIM, max_lines=1,
                                     overflow=ft.TextOverflow.ELLIPSIS)
    plugin_search_status = ft.Text('', size=12, color=TEXT_DIM, max_lines=1,
                                  overflow=ft.TextOverflow.ELLIPSIS)
    feedback_text = ft.Text('', size=11.5, color=TEXT_DIM, max_lines=1,
                            overflow=ft.TextOverflow.ELLIPSIS)
    plugin_market_title = ft.Text('Plugin picks', size=12, color=TEXT_DIM, font_family=FONT_MONO)
    plugins_active_view = {'value': 'browse'}
    snapshots, snapshot_at, match_sets = {}, {}, {}
    installed_rows, browse_rows, search_cache = {}, {}, {}
    installed_limit = {'value': 50}
    plugin_browse_state = {'results': [], 'page': 0, 'key': None, 'painted': None}
    generation = {'value': 0}
    search_timer = {'value': None}
    inflight = set()
    registry, artwork = InstallRegistry(), IconLoader()
    plugin_install_busy = {'value': False}

    def remember(cache, key, value, limit=200):
        cache[key] = value
        while len(cache) > limit:
            cache.pop(next(iter(cache)))

    def say(message):
        feedback_text.value = str(message)
        feedback_text.tooltip = str(message)
        thread_safe_ui.refresh(feedback_text)

    def _plugin_icon(hit):
        url = hit.get('icon_url')
        cached = icons.peek_src(url)
        image = preview_image(src=cached if icons.valid_source(cached) else 'icon_64.png',
                              width=44, height=44, fit=ft.BoxFit.COVER,
                              border_radius=RADIUS, gapless_playback=True, data=url)
        def ready(source):
            if image.data == url and icons.valid_source(source):
                image.src = source
                thread_safe_ui.refresh(image)
        if url and not icons.valid_source(cached):
            artwork.request(url, ready)
        return image

    def _plugin_installed_tokens():
        return match_sets.get(active_version['value'], set())

    def read_plugins(version):
        return version, core.list_plugins(version) if version else []

    def apply_plugins(snapshot):
        version, plugins = snapshot
        remember(snapshots, version, plugins, 12)
        snapshot_at[version] = time.monotonic()
        tokens = set()
        for plugin in plugins:
            for name in (plugin.get('slug'), plugin.get('project_id'), plugin.get('display_name')):
                if name:
                    tokens.add(name.lower())
                    tokens.add(re.sub(r'[^a-z0-9]+', '', name.lower()))
        match_sets[version] = tokens
        for retired in set(snapshot_at) - set(snapshots):
            snapshot_at.pop(retired, None)
            match_sets.pop(retired, None)
        if version == active_version['value']:
            render_installed()
            if plugin_browse_state['key'] and plugin_browse_state['key'][0] == version:
                _render_plugin_page()

    def failed_plugins(error):
        if active_version['value'] not in snapshots:
            installed_plugins_list.controls[:] = [empty_state(
                'Plugins unavailable', 'Reopen Plugins to retry.')]
            layout_tiles(installed_plugins_list, False)
            installed_plugins_count.value = "Couldn't read installed plugins"
            thread_safe_ui.refresh(installed_plugins_list)
            thread_safe_ui.refresh(installed_plugins_count)
        say(f"Couldn't read plugins: {error}")

    plugin_refresh = BackgroundRefresh(read_plugins, apply_plugins, name='plugins-refresh',
                                       failed=failed_plugins)

    def refresh_plugins_list(snapshot=None, *, force=False):
        with thread_safe_ui.TREE_LOCK:
            version = active_version['value']
            if snapshot is not None:
                plugin_refresh.invalidate()
                apply_plugins((version, snapshot.get('plugins', [])))
                return
            render_installed()
            if not version or (not force and version in snapshots and
                               time.monotonic() - snapshot_at.get(version, 0) < 15):
                return
        plugin_refresh.request(version)

    def _plugin_row(plugin):
        version = active_version['value']
        key = (version, plugin['filename'].removesuffix('.disabled'))
        cached = installed_rows.get(key)
        if cached:
            data, row, job = cached
            data.update(plugin)
            labels = row.content.controls[1].controls
            labels[0].value = plugin['display_name']
            labels[0].color = TEXT if plugin['enabled'] else TEXT_DIM
            if not job.busy:
                labels[1].value = 'Managed server integration' if plugin.get('protected') else (
                    'Enabled · Next server start' if plugin['enabled'] else 'Disabled · Next server start')
                if not plugin.get('protected'):
                    row.content.controls[2].value = plugin['enabled']
            return row
        data, job = dict(plugin), InstallFeedback()
        def action(remove=False, enabled=None):
            ft.context.disable_auto_update()
            with thread_safe_ui.TREE_LOCK:
                if version != active_version['value'] or data.get('protected') or job.busy:
                    return
                if not job.start(text='Removing…' if remove else 'Enabling…' if enabled else 'Disabling…'):
                    return
                switch = row.content.controls[2]
                before = data['enabled']
                for control in row.content.controls[2:]:
                    control.disabled = True
                row.content.controls[1].controls[1].value = job.text
                thread_safe_ui.refresh(row)
            def worker():
                error = None
                try:
                    with storage.update_operation():
                        if remove:
                            core.delete_plugin(version, data['filename'])
                        else:
                            core.toggle_plugin(version, data['filename'], enabled)
                    result = read_plugins(version)
                except Exception as ex:
                    error, result = ex, None
                with thread_safe_ui.TREE_LOCK:
                    job.finish(error=error)
                    for control in row.content.controls[2:]:
                        control.disabled = False
                    if error:
                        switch.value = before
                        row.content.controls[1].controls[1].value = 'Enabled' if before else 'Disabled'
                    if result is not None:
                        plugin_refresh.invalidate()
                        apply_plugins(result)
                    if version == active_version['value']:
                        say(error or f"{'Removed' if remove else 'Enabled' if enabled else 'Disabled'} {data['display_name']}.")
                        thread_safe_ui.refresh(row)
            try:
                threading.Thread(target=worker, daemon=True, name='plugin-action').start()
            except Exception as error:
                with thread_safe_ui.TREE_LOCK:
                    job.finish(error=error)
                    switch.value = before
                    for control in row.content.controls[2:]:
                        control.disabled = False
                    say(error)
                    thread_safe_ui.refresh(row)
        controls = [
            _plugin_icon(data),
            ft.Column([
                ft.Text(data['display_name'], size=13.5, color=TEXT if data['enabled'] else TEXT_DIM,
                        weight=ft.FontWeight.W_600, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text('Managed server integration' if data.get('protected') else
                        'Enabled · Next server start' if data['enabled'] else 'Disabled · Next server start',
                        size=11.5, color=TEXT_DIM, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=4, expand=True),
        ]
        if data.get('protected'):
            controls.append(ft.Icon(ft.Icons.LOCK_ROUNDED, size=18, color=TEXT_DIM, tooltip='Managed by Cubeon'))
        else:
            controls.extend([
                animated_switch(value=data['enabled'], active_color=ACCENT, scale=.85,
                                on_change=lambda e: action(enabled=bool(e.control.value)),
                                tooltip='Enable or disable on the next server start'),
                ft.IconButton(ft.Icons.DELETE_OUTLINE_ROUNDED, icon_size=18, icon_color=TEXT_FAINT,
                              tooltip='Remove', on_click=lambda e: action(remove=True)),
            ])
        row = style_tile(ft.Container(ft.Row(controls, vertical_alignment=ft.CrossAxisAlignment.CENTER)),
                         SURFACE, BORDER, ROW_HOVER)
        remember(installed_rows, key, (data, row, job))
        return row

    def render_installed():
        plugins = snapshots.get(active_version['value'])
        if plugins is None:
            installed_plugins_list.controls[:] = loading_tiles(installed_plugins_list)
            layout_tiles(installed_plugins_list)
            installed_plugins_count.value = 'Checking installed plugins…'
        else:
            query = installed_filter.value.strip().lower()
            filtered = [p for p in plugins if query in (p['display_name'] + ' ' + p['filename']).lower()]
            rows = [_plugin_row(p) for p in filtered[:installed_limit['value']]]
            if len(filtered) > len(rows):
                def more(e):
                    ft.context.disable_auto_update()
                    with thread_safe_ui.TREE_LOCK:
                        installed_limit['value'] += 50
                        render_installed()
                rows.append(ft.Container(ft.Text(f"Show more installed ({len(filtered) - len(rows)} more)",
                                                 size=12, color=ACCENT), padding=12, on_click=more))
            installed_plugins_list.controls[:] = rows or [empty_state(
                'No matching plugins' if query else 'No plugins installed yet',
                'Try another search.' if query else 'Browse plugins to add one.')]
            layout_tiles(installed_plugins_list, bool(rows))
            installed_plugins_count.value = f'{len(plugins)} installed'
        thread_safe_ui.refresh(installed_plugins_list)
        thread_safe_ui.refresh(installed_plugins_count)
        _build_plugins_view_segment()

    def _install_plugin_handler(hit, feedback=None, version=None):
        version = version or active_version['value']
        def handler(e=None):
            ft.context.disable_auto_update()
            if version != active_version['value']:
                return
            job = feedback or registry.project(('plugin', version), hit.get('project_id'), hit.get('slug'))
            with thread_safe_ui.TREE_LOCK:
                if plugin_install_busy['value']:
                    say('Finish the current plugin install first.')
                    return
                if not job.start():
                    return
                plugin_install_busy['value'] = True
            def worker():
                try:
                    file = core.get_plugin_download(hit.get('slug') or hit.get('project_id'),
                                                    mc_version=core.minecraft_version(version))
                    if not file:
                        raise RuntimeError('No build for this server version.')
                    with storage.update_operation():
                        core.download_plugin(version, file['url'], file['filename'], slug=hit.get('slug'),
                                             progress_cb=lambda done, total: job.status(progress_text(done, total)))
                    job.finish(file['filename'])
                    try:
                        snapshot = read_plugins(version)
                    except Exception as error:
                        with thread_safe_ui.TREE_LOCK:
                            if version == active_version['value']:
                                say(f"Installed, but couldn't refresh the list: {error}")
                        return
                    with thread_safe_ui.TREE_LOCK:
                        plugin_refresh.invalidate()
                        apply_plugins(snapshot)
                        if version == active_version['value']:
                            say(f"Installed {hit.get('title') or 'plugin'}.")
                except Exception as error:
                    job.finish(error=error)
                    with thread_safe_ui.TREE_LOCK:
                        if version == active_version['value']:
                            say(error)
                finally:
                    with thread_safe_ui.TREE_LOCK:
                        plugin_install_busy['value'] = False
            try:
                threading.Thread(target=worker, daemon=True, name='plugin-install').start()
            except Exception as error:
                with thread_safe_ui.TREE_LOCK:
                    plugin_install_busy['value'] = False
                    job.finish(error=error)
                    say(error)
        return handler

    def _plugin_result_row(hit, is_installed=False):
        version = active_version['value']
        key = (version, hit.get('project_id') or hit.get('slug') or hit['title'])
        cached = browse_rows.get(key)
        if cached and cached[0] == hit:
            cached[2](is_installed)
            return cached[1]
        job = registry.project(('plugin', version), hit.get('project_id'), hit.get('slug'))
        handler = _install_plugin_handler(hit, job, version)
        label = ft.Text('Installed' if is_installed else 'Install', size=12.5, weight=ft.FontWeight.W_700,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, expand=True)
        icon = ft.Icon(ft.Icons.DOWNLOAD_ROUNDED, size=15)
        button = ft.Container(ft.Row([icon, label], spacing=6), width=104, height=30,
                              padding=ft.padding.Padding.symmetric(horizontal=8), border_radius=RADIUS,
                              on_click=handler, alignment=ft.Alignment.CENTER)
        installed = {'value': is_installed, 'result': job.result_id}
        def paint(feedback):
            if installed['result'] != feedback.result_id:
                installed['result'] = feedback.result_id
                if feedback.result == 'success':
                    installed['value'] = True
            button.disabled = feedback.busy or installed['value']
            label.value = compact_status(feedback.text) if feedback.busy else (
                'Installed' if installed['value'] else 'Try again' if feedback.result == 'error' else 'Install')
            label.color = TEXT_DIM if feedback.busy or installed['value'] else ON_ACCENT
            icon.icon = ft.Icons.CHECK_ROUNDED if installed['value'] else ft.Icons.DOWNLOAD_ROUNDED
            icon.color = label.color
            button.bgcolor = SURFACE_HI if feedback.busy else None if installed['value'] else ACCENT
            button.tooltip = feedback.text if feedback.busy or feedback.result == 'error' else None
        def sync(value):
            installed['value'] = value
            paint(job)
        row = style_tile(ft.Container(ft.Row([
            _plugin_icon(hit), ft.Column([
                ft.Text(hit.get('title') or hit.get('slug'), size=13.5, color=TEXT, weight=ft.FontWeight.W_700,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(hit.get('author') or 'Community project', size=11.5, color=TEXT_DIM,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Row([ft.Icon(ft.Icons.DOWNLOAD_OUTLINED, size=12, color=TEXT_FAINT),
                        ft.Text(downloads_label(hit.get('downloads')), size=10.5, color=TEXT_FAINT)], spacing=4),
            ], spacing=4, expand=True), button,
        ], vertical_alignment=ft.CrossAxisAlignment.CENTER), tooltip=hit.get('description')),
            SURFACE, BORDER, ROW_HOVER)
        theme = dict(RADIUS=RADIUS, ACCENT=ACCENT, ACCENT_TINT=ft.Colors.with_opacity(.1, ACCENT),
                     CARD_FILL=CARD_FILL, CARD_BORDER=CARD_BORDER, TEXT=TEXT, TEXT_DIM=TEXT_DIM,
                     TEXT_FAINT=TEXT_FAINT, ON_ACCENT=ON_ACCENT, SURFACE=SURFACE, BG=BG,
                     DANGER=DANGER, FONT_DISPLAY=FONT_DISPLAY, FONT_MONO=FONT_MONO)
        def _open_plugin_detail(e=None):
            open_project_detail(
                page, ref=hit.get('project_id') or hit.get('slug'), theme=theme, title=hit.get('title') or 'Plugin',
                icon_url=hit.get('icon_url'), blurb=hit.get('description'), install_label='Install',
                on_install=handler, install_disabled=installed['value'], install_feedback=job,
                install_hint="Installs into this server's plugins folder.", loader=None)
        row.on_click = _open_plugin_detail
        job.watch(button, paint)
        remember(browse_rows, key, (dict(hit), row, sync))
        return row

    plugin_search_field = ft.TextField(hint_text='Search plugins on Modrinth…', expand=True, height=46,
        prefix_icon=ft.Icons.SEARCH_ROUNDED, bgcolor=CARD_FILL, border_color=CARD_BORDER,
        focused_border_color=ACCENT_DIM, color=TEXT, border_radius=RADIUS,
        content_padding=ft.padding.Padding.symmetric(horizontal=16, vertical=12),
        on_submit=lambda e: run_plugin_search())
    def filter_installed(e=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            render_installed()
    installed_filter = ft.TextField(hint_text='Search installed plugins…', height=46,
        prefix_icon=ft.Icons.SEARCH_ROUNDED, bgcolor=CARD_FILL, border_color=CARD_BORDER,
        focused_border_color=ACCENT_DIM, color=TEXT, border_radius=RADIUS,
        on_change=filter_installed)
    plugin_pager_label = ft.Text('', size=12, color=TEXT_DIM, text_align=ft.TextAlign.CENTER)
    plugin_pager_prev = ft.IconButton(ft.Icons.CHEVRON_LEFT_ROUNDED, icon_color=TEXT)
    plugin_pager_next = ft.IconButton(ft.Icons.CHEVRON_RIGHT_ROUNDED, icon_color=TEXT)
    retry = ft.TextButton('Retry', width=64, opacity=0, disabled=True, on_click=lambda e: run_plugin_search(force=True))
    plugin_pager_row = ft.Row([ft.Container(width=64), plugin_pager_prev,
        ft.Container(plugin_pager_label, width=140, alignment=ft.Alignment.CENTER), plugin_pager_next, retry],
        alignment=ft.MainAxisAlignment.CENTER, spacing=4, height=40)

    def _render_plugin_page():
        hits, page_num = plugin_browse_state['results'], plugin_browse_state['page']
        installed = _plugin_installed_tokens()
        rows = [_plugin_result_row(hit, any(
            value.lower() in installed or re.sub(r'[^a-z0-9]+', '', value.lower()) in installed
            for value in (hit.get('slug'), hit.get('project_id'), hit.get('title')) if value))
            for hit in hits[page_num * 24:(page_num + 1) * 24]]
        plugin_results_list.controls[:] = rows or [empty_state('No plugins found', 'Try another search.')]
        for row in rows:
            row.ignore_interactions = False
        layout_tiles(plugin_results_list, bool(rows))
        plugin_pager_label.value = f'Page {page_num + 1} of {max(1, -(-len(hits) // 24))}'
        plugin_pager_prev.disabled = page_num <= 0
        plugin_pager_next.disabled = (page_num + 1) * 24 >= len(hits)
        retry.opacity, retry.disabled = 0, True
        thread_safe_ui.refresh(plugin_results_list)
        thread_safe_ui.refresh(plugin_pager_row)
        painted = (plugin_browse_state['key'], page_num)
        if painted != plugin_browse_state['painted']:
            plugin_browse_state['painted'] = painted
            scrolling.to_top(page, plugin_results_list)

    def run_plugin_search(e=None, *, force=False):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            pending = search_timer['value']
            if pending is not None:
                pending.cancel()
                search_timer['value'] = None
            version = active_version['value']
            if not version:
                return
            key = (version, plugin_search_field.value.strip())
            generation['value'] += 1
            token = generation['value']
            plugin_browse_state['key'] = key
            if not force and key in search_cache:
                plugin_browse_state.update(results=search_cache[key], page=0)
                plugin_search_status.value = f'{len(search_cache[key])} results'
                thread_safe_ui.refresh(plugin_search_status)
                _render_plugin_page()
                return
            if key in inflight:
                return
            inflight.add(key)
            if not plugin_results_list.controls or plugin_results_list.controls[0].data == 'content-empty':
                plugin_results_list.controls[:] = loading_tiles(plugin_results_list)
                layout_tiles(plugin_results_list)
            for row in plugin_results_list.controls:
                row.ignore_interactions = True
            plugin_search_status.value = 'Loading…'
            plugin_pager_label.value = 'Loading…'
            plugin_pager_prev.disabled = plugin_pager_next.disabled = True
            retry.opacity, retry.disabled = 0, True
            thread_safe_ui.refresh(plugin_results_list)
            thread_safe_ui.refresh(plugin_search_status)
            thread_safe_ui.refresh(plugin_pager_row)
            def worker():
                try:
                    hits = (core.search_plugins(key[1], mc_version=core.minecraft_version(version))
                            if key[1] else core.get_recommended_plugins()) or []
                    error = None
                except Exception as ex:
                    hits, error = [], ex
                with thread_safe_ui.TREE_LOCK:
                    inflight.discard(key)
                    if not error:
                        remember(search_cache, key, hits[:100], 12)
                    if key != plugin_browse_state['key'] or key != (active_version['value'], plugin_search_field.value.strip()):
                        return
                    if error:
                        plugin_search_status.value = 'Search unavailable'
                        say(error)
                        for row in plugin_results_list.controls:
                            row.ignore_interactions = False
                        if all(row.data == 'content-loading' for row in plugin_results_list.controls):
                            plugin_results_list.controls[:] = [empty_state('Search unavailable', 'Check your connection and retry.')]
                            layout_tiles(plugin_results_list, False)
                        retry.opacity, retry.disabled = 1, False
                        plugin_pager_label.value = 'Couldn\'t load results'
                        thread_safe_ui.refresh(plugin_results_list)
                        thread_safe_ui.refresh(plugin_pager_row)
                    else:
                        plugin_browse_state.update(results=hits[:100], page=0)
                        plugin_search_status.value = f'{len(hits[:100])} results'
                        _render_plugin_page()
                    thread_safe_ui.refresh(plugin_search_status)
            try:
                threading.Thread(target=worker, daemon=True, name='plugin-search').start()
            except Exception as error:
                inflight.discard(key)
                retry.opacity, retry.disabled = 1, False
                say(error)
                thread_safe_ui.refresh(plugin_pager_row)

    def turn_page(delta):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            plugin_browse_state['page'] = max(0, min(
                plugin_browse_state['page'] + delta,
                max(0, -(-len(plugin_browse_state['results']) // 24) - 1)))
            _render_plugin_page()
    plugin_pager_prev.on_click = lambda e: turn_page(-1)
    plugin_pager_next.on_click = lambda e: turn_page(1)
    plugins_browse_pane = ft.Column([
        ft.Row([plugin_search_field]), ft.Row([ft.Container(plugin_market_title, expand=True),
            ft.Container(plugin_search_status, expand=True, alignment=ft.Alignment.CENTER_RIGHT)], height=36),
        plugin_results_list, plugin_pager_row], spacing=12, expand=True)
    plugins_installed_pane = ft.Column([
        ft.Row([ft.Container(installed_filter, expand=True)], height=46),
        ft.Row([ft.Container(section_label('Installed'), expand=True), installed_plugins_count], height=36),
        installed_plugins_list, ft.Container(height=40)], spacing=12, expand=True, visible=False)
    view_port, browse_host, installed_host, select_view = catalogue_views(
        page, plugins_browse_pane, plugins_installed_pane)
    plugins_view_segment_row = ft.Row()
    def _build_plugins_view_segment(n_plugs=None):
        count = len(snapshots.get(active_version['value'], [])) if n_plugs is None else n_plugs
        update_view_action(plugins_view_segment_row, plugins_active_view['value'], count,
                           _on_plugins_view_change, data='plugins-installed-toggle', color=TEXT_DIM)
    def _on_plugins_view_change(new_view):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if plugins_active_view['value'] == new_view:
                return
            plugins_active_view['value'] = new_view
            select_view(new_view)
            _build_plugins_view_segment()
            if new_view == 'installed':
                refresh_plugins_list()
    _build_plugins_view_segment()
    def schedule_search(e=None):
        ft.context.disable_auto_update()
        if search_timer['value']:
            search_timer['value'].cancel()
        def search():
            with thread_safe_ui.TREE_LOCK:
                run_plugin_search()
        timer = threading.Timer(.45, search)
        timer.daemon = True
        search_timer['value'] = timer
        timer.start()
    plugin_search_field.on_change = schedule_search
    subtitle = ft.Text('Find plugins, or manage what is installed for this server.', size=13, color=TEXT_DIM,
                       max_lines=1, overflow=ft.TextOverflow.ELLIPSIS)
    selector = ft.Container(ft.Row([ft.Icon(ft.Icons.EXTENSION_OUTLINED, size=16, color=TEXT),
        ft.Text('Plugins', size=12, color=TEXT, weight=ft.FontWeight.W_600)], spacing=8, tight=True),
        padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10), border_radius=6,
        bgcolor=SURFACE_HI, border=ft.border.Border.all(1, BORDER))
    body = ft.Column([content_header(subtitle, plugins_view_segment_row), ft.Container(height=16),
                      view_port, ft.Container(feedback_text, height=20)], spacing=0, expand=True)
    root = ft.Column([ft.Row([selector]), body], spacing=16, expand=True)
    return root, refresh_plugins_list, run_plugin_search, plugin_results_list
