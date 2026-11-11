"""Retained launcher Settings, with short rows and optional advanced controls.

Main supplies the shared controls and actions. Build each section once, keep
its scrolling independent, and preserve the established section deep links.
"""
import flet as ft
import unicodedata

from cubeon import i18n
from cubeon import motion
from cubeon import osnotify
from cubeon import thread_safe_ui, scrolling
from cubeon.theme import (
    RADIUS, RADIUS_LG, ROW_HOVER, ACCENT_TINT, TEXT_FAINT, keyboard_target,
)
from ui.about_settings import build_about_section

# Labels stay short; keys also serve existing links from the launcher.
SECTIONS = [
    ("account", ft.Icons.PERSON_ROUNDED, "Account"),
    ("versions", ft.Icons.SPORTS_ESPORTS_ROUNDED, "Game"),
    ("appearance", ft.Icons.PALETTE_ROUNDED, "Appearance"),
    ("notifications", ft.Icons.NOTIFICATIONS_OUTLINED, "Notifications"),
    ("import", ft.Icons.DOWNLOAD_ROUNDED, "Import"),
    ("about", ft.Icons.INFO_OUTLINE_ROUNDED, "About"),
]

# Selection changes the fill and text without moving the controls.
RAIL_ANIM = ft.Animation(150, ft.AnimationCurve.EASE_OUT_CUBIC)


def _apply_rail_state(item, active, *, ACCENT, ACCENT_TINT, TEXT, TEXT_DIM):
    """Keep the selection highlight correct after a pointer leaves the row."""
    item._settings_active = active
    item.bgcolor = (ACCENT_TINT if active else
                    ROW_HOVER if item._settings_hovered else None)
    icon, label = item.content.controls[0], item.content.controls[1]
    icon.color = ACCENT if active else TEXT_DIM
    label.color = TEXT if active else TEXT_DIM
    label.weight = ft.FontWeight.W_600 if active else ft.FontWeight.W_500


def _rail_item(key, icon, label, active, on_click, *, ACCENT, ACCENT_TINT,
               ROW_HOVER, TEXT, TEXT_DIM):
    item = ft.Container(
        content=ft.Row(
            [
                ft.Icon(icon, size=18, color=ACCENT if active else TEXT_DIM),
                ft.Text(label, size=13.5, expand=True, max_lines=2,
                        overflow=ft.TextOverflow.ELLIPSIS,
                        color=TEXT if active else TEXT_DIM,
                        weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_500),
            ],
            spacing=10, tight=True,
        ),
        bgcolor=ACCENT_TINT if active else None,
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=12, vertical=10),
        ink=False, on_click=on_click, animate=RAIL_ANIM,
        data="settings-section-" + key,
    )
    item._settings_active = active
    item._settings_hovered = False

    def hover_fill(hot):
        item._settings_hovered = hot
        item.bgcolor = (ACCENT_TINT if item._settings_active else
                        ROW_HOVER if hot else None)

    motion.polish(item, on_hover_fill=hover_fill)
    previous_hover = item.on_hover

    def hovered(event):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            previous_hover(event)

    item.on_hover = hovered
    return item


def _save_preference(cfg, key, value, *, set_status, error):
    """Persist one preference without leaving an unsaved live value behind."""
    from cubeon import config

    with thread_safe_ui.TREE_LOCK:
        existed, previous = key in cfg, cfg.get(key)
        cfg[key] = value
        try:
            config.save_config(cfg)
        except Exception:
            if existed:
                cfg[key] = previous
            else:
                cfg.pop(key, None)
            set_status(i18n.t(error))
            return False
        return True


def _row(title, subtitle, control, *, TEXT, TEXT_DIM):
    """Keep switches beside their label; wide actions stack in narrow forms."""
    labels = ft.Column([
        ft.Text(i18n.t(title), size=14, color=TEXT, weight=ft.FontWeight.W_600),
        *([ft.Text(i18n.t(subtitle), size=12, color=TEXT_DIM)] if subtitle else []),
    ], spacing=4, expand=True)
    if isinstance(control, (ft.Switch, ft.Checkbox)):
        content = ft.Row([labels, control], spacing=16,
                         vertical_alignment=ft.CrossAxisAlignment.CENTER)
    else:
        if isinstance(control, ft.Dropdown):
            control.expand = True
            control = ft.Row([control], spacing=0)
        elif isinstance(control, ft.TextField):
            control = ft.Column([control], spacing=0,
                                horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        content = ft.ResponsiveRow([
            ft.Container(labels, col={"xs": 12, "wide": 7}),
            ft.Container(control, col={"xs": 12, "wide": 5}, alignment=ft.Alignment.CENTER_RIGHT),
        ], breakpoints={"xs": 0, "wide": 500}, spacing=16, run_spacing=10,
            vertical_alignment=ft.CrossAxisAlignment.CENTER)
    return ft.Container(
        content=content,
        padding=ft.padding.Padding.symmetric(horizontal=16, vertical=12),
    )


def _body(control, *, pad_v=14):
    """A full-width cell inside a group (fields, sliders - things that are not
    a title/control pair)."""
    if isinstance(control, ft.Column):
        control.horizontal_alignment = ft.CrossAxisAlignment.STRETCH
    return ft.Container(
        content=control,
        padding=ft.padding.Padding.symmetric(horizontal=16, vertical=pad_v),
    )


def _language_picker(cfg, *, on_restart, set_status, BG, BORDER, ACCENT,
                     TEXT, TEXT_DIM):
    """Save a language from a searchable inline list; apply it on restart."""
    from cubeon import config

    def font(code):
        if i18n.is_rtl(code):
            return "Noto Arabic"
        return {"hi":"Noto Devanagari", "bn":"Noto Bengali", "zh-cn":"Cubeon Language CJK",
                "ja":"Cubeon Language CJK", "ko":"Cubeon Language CJK"}.get(code, "Inter")

    ui_font = font(i18n.current())

    def selected():
        code = cfg.get(i18n.CONFIG_KEY)
        return code if code in i18n.SUPPORTED else i18n.current()

    native_text = ft.Text(size=14, color=TEXT, weight=ft.FontWeight.W_600)
    english_text = ft.Text(size=11.5, color=TEXT_DIM, rtl=False, font_family="Inter")
    chevron = ft.Icon(ft.Icons.EXPAND_MORE_ROUNDED, size=20, color=TEXT_DIM)
    search = ft.TextField(
        label=i18n.t("Search"), hint_text="English, العربية, es…",
        prefix_icon=ft.Icons.SEARCH_ROUNDED, text_size=13, color=TEXT,
        border_color=BORDER, focused_border_color=ACCENT, border_radius=RADIUS,
        bgcolor=BG, data="language-search",
        text_style=ft.TextStyle(font_family=ui_font, font_family_fallback=[
            "Inter", "Noto Arabic", "Noto Devanagari", "Noto Bengali", "Cubeon Language CJK"]),
        label_style=ft.TextStyle(font_family=ui_font, color=TEXT_DIM),
    )
    choices = ft.ListView(height=252, spacing=4, data="language-options")
    no_results = ft.Text(i18n.t("No languages found"), color=TEXT_DIM,
                         size=12, visible=False, font_family=ui_font)
    dropdown = ft.Container(
        content=ft.Column([search, choices, no_results], spacing=12,
                          horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
        visible=False, padding=12, border=ft.border.Border.all(1, BORDER),
        border_radius=RADIUS, bgcolor=BG,
    )
    def restart_click(e=None):
        with thread_safe_ui.TREE_LOCK:
            on_restart(e)

    restart = ft.FilledButton(
        i18n.t("Restart"), icon=ft.Icons.RESTART_ALT_ROUNDED,
        on_click=restart_click, data="language-restart",
        style=ft.ButtonStyle(color=BG, bgcolor=ACCENT,
                             text_style=ft.TextStyle(font_family=ui_font),
                             shape=ft.RoundedRectangleBorder(radius=RADIUS)),
    )
    notice = ft.Column([
        ft.Text(i18n.t("Restart to apply"), size=12, color=TEXT_DIM, font_family=ui_font), restart,
    ], spacing=8, visible=False, data="language-restart-notice")

    def sync():
        code = selected()
        native_text.value = i18n.language_name(code)
        native_text.rtl = i18n.is_rtl(code)
        native_text.font_family = font(code)
        english_text.value = i18n.language_name(code, english=True)
        english_text.visible = english_text.value != native_text.value
        notice.visible = code != i18n.current()

    def choose(code):
        with thread_safe_ui.TREE_LOCK:
            previous = cfg.get(i18n.CONFIG_KEY)
            had_key = i18n.CONFIG_KEY in cfg
            cfg[i18n.CONFIG_KEY] = code
            try:
                config.save_config(cfg)
            except Exception:
                if had_key:
                    cfg[i18n.CONFIG_KEY] = previous
                else:
                    cfg.pop(i18n.CONFIG_KEY, None)
                set_status(i18n.t("Couldn't save the language"))
                return
            dropdown.visible = False
            chevron.icon = ft.Icons.EXPAND_MORE_ROUNDED
            sync()
            thread_safe_ui.refresh(panel)
        set_status(i18n.t("Restart to apply") if notice.visible else native_text.value)

    def normalized(value):
        return ''.join(c for c in unicodedata.normalize('NFKD', value.casefold())
                       if not unicodedata.combining(c))

    def filter_choices(e=None):
        with thread_safe_ui.TREE_LOCK:
            query = normalized(search.value or '').strip()
            rows = []
            for code, native, english, rtl in i18n.LANGUAGES:
                if query not in normalized(' '.join((code, native, english))):
                    continue
                labels = [ft.Text(native, size=14, color=TEXT, rtl=rtl, font_family=font(code))]
                if native != english:
                    labels.append(ft.Text(english, size=11.5, color=TEXT_DIM, rtl=False, font_family="Inter"))
                rows.append(ft.TextButton(
                    content=ft.Row([
                        ft.Column(labels, spacing=4, expand=True),
                        ft.Icon(ft.Icons.CHECK_ROUNDED, size=18, color=ACCENT,
                                visible=code == selected()),
                    ], spacing=12),
                    style=ft.ButtonStyle(
                        padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
                        bgcolor=ACCENT_TINT if code == selected() else None,
                        overlay_color=ROW_HOVER,
                        shape=ft.RoundedRectangleBorder(radius=RADIUS)),
                    on_click=lambda e, code=code: choose(code),
                    data="language-option-" + code,
                ))
            choices.controls = rows
            choices.visible = bool(rows)
            no_results.visible = not rows
            thread_safe_ui.refresh(dropdown)

    def toggle(e=None):
        with thread_safe_ui.TREE_LOCK:
            dropdown.visible = not dropdown.visible
            chevron.icon = (ft.Icons.EXPAND_LESS_ROUNDED if dropdown.visible
                            else ft.Icons.EXPAND_MORE_ROUNDED)
            if dropdown.visible:
                search.value = ''
                filter_choices()
            thread_safe_ui.refresh(panel)

    search.on_change = filter_choices
    selector = ft.TextButton(
        content=ft.Row([
            ft.Icon(ft.Icons.LANGUAGE_ROUNDED, size=20, color=ACCENT),
            ft.Column([native_text, english_text], spacing=4, expand=True), chevron,
        ], spacing=12),
        on_click=toggle, data="language-picker-toggle",
        style=ft.ButtonStyle(
            padding=12, bgcolor=ft.Colors.with_opacity(.35, BG),
            overlay_color=ROW_HOVER,
            side=ft.BorderSide(1, BORDER),
            shape=ft.RoundedRectangleBorder(radius=RADIUS)),
    )
    panel = ft.Column([
        ft.Text(i18n.t("Language"), size=14, color=TEXT, weight=ft.FontWeight.W_600, font_family=ui_font),
        selector, dropdown, notice,
    ], spacing=12, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        data="language-picker")
    sync()
    return panel


def _java_defaults_panel(*, ram_slider, custom_jvm_field, BORDER, ACCENT,
                         ACCENT_TINT, TEXT, TEXT_DIM, TEXT_FAINT, FONT_MONO,
                         cfg=None, set_status=None, memory_status=None):
    """Default JVM flags, with a saved opt-out and shared launch readout.

    The flag list is COLLAPSED, while the opt-out stays visible: nobody needs twenty GC
    flags in their face, but "what is Cubeon actually passing to Java?" is a
    fair question the moment a mod misbehaves or a friend suggests a flag.

    The rows come from `launch.default_jvm_flags_report()`, which assembles
    them from the same functions `build_launch_command` uses - so this panel
    cannot drift from what actually launches. That is why it takes
    `ram_slider` and `custom_jvm_field` rather than a static list: the answer
    genuinely depends on the RAM you allocated, your core count and whether
    you chose your own garbage collector.
    """
    from cubeon import launch
    from cubeon import thread_safe_ui
    from cubeon import config

    settings = cfg if cfg is not None else {}
    enabled_key = "default_jvm_flags_enabled"
    enabled = ft.Switch(value=settings.get(enabled_key, True), active_color=ACCENT,
                        data="default-jvm-flags-enabled")

    rows = ft.ListView(spacing=4, height=288, visible=False)
    chevron = ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=18, color=TEXT_DIM)
    summary = ft.Text("", size=11.5, color=TEXT_FAINT, width=120, max_lines=2,
                      overflow=ft.TextOverflow.ELLIPSIS)
    open_state = {"v": False}
    # Advanced Java choices affect launch precedence, not pointer interaction.
    ram_slider.disabled = False

    def _sync_memory():
        if memory_status is not None:
            report = launch.memory_limit_report(
                int(ram_slider.value or 0),
                custom_jvm_flags=custom_jvm_field.value or "",
                default_jvm_flags_enabled=bool(enabled.value))
            if report["source"] == "custom":
                memory_status.value = i18n.t(
                    "Custom Java limit: {flag}. This overrides the RAM slider.").format(
                        flag=report["flag"])
            elif report["source"] == "slider":
                memory_status.value = i18n.t(
                    "Maximum: {mb} MB ({gb} GB). Applies on the next launch.").format(
                        mb=int(report["ram_mb"]), gb=f'{report["ram_mb"] / 1024:g}')
            else:
                memory_status.value = i18n.t(
                    "Saved RAM applies when default Java flags are on. Otherwise the profile or Java chooses the memory limit.")
            thread_safe_ui.refresh(memory_status)

    def _rebuild():
        """Re-read the live settings and repaint the list."""
        _sync_memory()
        try:
            ram = int(getattr(ram_slider, "value", 0) or 0)
        except (TypeError, ValueError):
            ram = 0
        try:
            user_flags = getattr(custom_jvm_field, "value", "") or ""
        except Exception:
            user_flags = ""
        try:
            report = launch.default_jvm_flags_report(
                ram or None, custom_jvm_flags=user_flags,
                default_jvm_flags_enabled=bool(enabled.value))
        except Exception:
            report = []
        rows.controls.clear()
        for entry in report:
            flag = str(entry.get("flag") or "")
            note = str(entry.get("note") or "")
            source = entry.get("source") or "always"
            dropped = source == "dropped"
            # One row: the flag in mono on the left, its reason on the right.
            # No wrap=True here - the note expands, and Flutter's wrapped
            # layout cannot host a flex child.
            rows.controls.append(ft.Container(
                content=ft.Row(
                    [
                        ft.Text(flag, size=11.5, font_family=FONT_MONO,
                                color=(TEXT_FAINT if dropped else ACCENT),
                                expand=True, selectable=True, rtl=False),
                        ft.Column(
                            [ft.Text(note, size=11, color=TEXT_DIM),
                             *([ft.Text(i18n.t("Disabled in Settings") if not enabled.value
                                        else i18n.t("Not added on this machine"),
                                        size=10, color=TEXT_FAINT)]
                               if dropped else [])],
                            spacing=4, expand=2, tight=True),
                    ],
                    spacing=12, vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                padding=ft.padding.Padding.symmetric(horizontal=16, vertical=4),
            ))
        applied = sum(1 for e in report
                      if (e.get("source") or "always") != "dropped")
        skipped = len(report) - applied
        if not report:
            summary.value = i18n.t("Unavailable right now")
        elif not enabled.value:
            summary.value = i18n.t("Default flags disabled")
        else:
            # The count leads, the translated phrase follows, so a language
            # that puts its noun first still reads correctly.
            summary.value = f"{applied} {i18n.t('flags added')}" + (
                f", {skipped} {i18n.t('not on this machine')}" if skipped else "")
        summary.tooltip = summary.value
        # Repaint only this panel: the rest of Settings is untouched.
        thread_safe_ui.refresh(rows)
        thread_safe_ui.refresh(summary)

    def _save_enabled(event=None):
        with thread_safe_ui.TREE_LOCK:
            previous = settings.get(enabled_key, True)
            existed = enabled_key in settings
            settings[enabled_key] = bool(enabled.value)
            try:
                config.save_config(settings)
            except Exception:
                if existed:
                    settings[enabled_key] = previous
                else:
                    settings.pop(enabled_key, None)
                enabled.value = previous
                if set_status:
                    set_status(i18n.t("Could not save Java settings"))
            else:
                if set_status:
                    set_status(i18n.t("Java settings saved. Applies on the next launch."))
            _rebuild()
            thread_safe_ui.refresh(enabled)

    enabled.on_change = _save_enabled
    toggle_row = ft.Container(
        content=ft.Row([
            ft.Column([
                ft.Text(i18n.t("Use Cubeon's default Java flags"), size=13, color=TEXT),
                ft.Text(i18n.t("Off lets your custom flags, game profile or Java choose the memory limit."),
                        size=11.5, color=TEXT_DIM),
            ], spacing=4, expand=True), enabled,
        ], spacing=12),
        padding=ft.padding.Padding.symmetric(horizontal=16, vertical=12))

    def _toggle(e=None):
        with thread_safe_ui.TREE_LOCK:
            open_state["v"] = not open_state["v"]
            rows.visible = open_state["v"]
            chevron.icon = (ft.Icons.EXPAND_MORE_ROUNDED if open_state["v"]
                            else ft.Icons.CHEVRON_RIGHT_ROUNDED)
            if open_state["v"]:
                _rebuild()   # pick up a RAM change made since it was last opened
            thread_safe_ui.refresh(rows)
            thread_safe_ui.refresh(chevron)

    header = ft.TextButton(
        content=ft.Row(
            [chevron,
             ft.Text(i18n.t("Cubeon's default flags"), size=13, color=TEXT,
                     weight=ft.FontWeight.W_600, expand=True),
             summary],
            spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        style=ft.ButtonStyle(
            padding=ft.padding.Padding.symmetric(horizontal=16, vertical=12),
            overlay_color=ROW_HOVER,
            shape=ft.RoundedRectangleBorder(radius=RADIUS)),
        on_click=_toggle,
        tooltip="The JVM options Cubeon passes to Java on every launch, "
                "and why each one is there",
    )

    for control in (ram_slider, custom_jvm_field):
        previous = control.on_change

        def changed(event, previous=previous, is_ram=control is ram_slider):
            if is_ram:
                ft.context.disable_auto_update()
            with thread_safe_ui.TREE_LOCK:
                if callable(previous):
                    previous(event)
                if open_state["v"] and not is_ram:
                    _rebuild()
                else:
                    _sync_memory()

        control.on_change = changed

    # Expanded JVM details rebuild on release, never for every drag tick.
    for event_name in ("on_change_end", "on_blur"):
        previous = getattr(ram_slider, event_name)

        def finished(event, previous=previous):
            ft.context.disable_auto_update()
            with thread_safe_ui.TREE_LOCK:
                if callable(previous):
                    previous(event)
                if open_state["v"]:
                    _rebuild()
                else:
                    _sync_memory()

        setattr(ram_slider, event_name, finished)

    _sync_memory()
    return ft.Container(
        content=ft.Column([toggle_row, header, rows], spacing=0, tight=True,
                          horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
    )


def _group(rows, *, SURFACE_HI, BORDER):
    """A card of rows separated by hairlines."""
    items = []
    for i, row in enumerate(rows):
        if i:
            items.append(ft.Divider(
                height=1, thickness=1,
                color=ft.Colors.with_opacity(0.55, BORDER)))
        items.append(row)
    return ft.Container(
        content=ft.Column(items, spacing=0),
        bgcolor=SURFACE_HI, border_radius=RADIUS_LG,
    )


def build_settings_tab(page, cfg, *, section_label, pixel_divider,
                       set_status, save_width_height_java,
                       browse_online_row, legacy_btn, legacy_note,
                       client_mod_cb, csl_cb, glass_cb, tidy_btn, ram_slider, ram_range_row, ram_label,
                       custom_chrome_cb,
                       ram_warning, width_field, height_field,
                       java_path_field, custom_jvm_field, detected_java,
                       import_pane,
                       backup_enabled_switch, frequency_dropdown,
                       include_saves_switch, keep_last_field,
                       backup_status_text, backup_now_btn, open_folder_btn,
                       minecraft_files_pane,
                       restore_btn, minekube_badge, cubeon_web_link,
                       seasonal_switch, season_dropdown, seasonal_status_icon,
                       seasonal_status_text, seasonal_source_text,
                       seasonal_restart_btn, seasonal_restart_note,
                       season_pin_note,
                       season_pet_switch, season_overlay_switch,
                       BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                       TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO,
                       on_open_screenshots=None,
                       account_pane=None, on_replay_onboarding=None,
                       on_motion_change=None, detected_java_label=None):
    """Assemble Settings from the existing controls and callbacks.

    `save_width_height_java` is main.py's save_settings() minus the button
    click - called on field blur so width/height/java persist instantly.

    `account_pane` (optional) is the prebuilt profile card. Account also owns
    backups and the launcher actions, so its entry exists without that card.

    `custom_chrome_cb` is the one that can legitimately be None: the custom
    window frame is Windows/Linux-only, so main.py passes None elsewhere and
    the row is left out entirely.

    """

    # Labels are translated at build time; the KEYS are not - deep links (the
    # seasonal badge uses "seasonal") key off them. A language change lands on
    # the next start, like the rest of the chrome.
    sections = [(key, icon, i18n.t(label)) for key, icon, label in SECTIONS]
    active_section = {"value": sections[0][0]}

    if detected_java_label is None:
        detected_java_label = ft.Text(
            f"{i18n.t('Found')}: {detected_java}" if detected_java else i18n.t("Detected automatically"),
            size=11.5, color=TEXT_FAINT, font_family=FONT_MONO,
            rtl=False, max_lines=2, overflow=ft.TextOverflow.ELLIPSIS,
            tooltip=detected_java,
        )

    def row(title, subtitle, control):
        if isinstance(control, ft.Container) and callable(control.on_click):
            control = keyboard_target(control, i18n.t(title))
        return _row(title, subtitle, control, TEXT=TEXT, TEXT_DIM=TEXT_DIM)

    def group(rows):
        return _group(rows, SURFACE_HI=SURFACE_HI, BORDER=BORDER)

    def block(label, content):
        """A small caps label over a group."""
        return ft.Column([section_label(i18n.t(label)), content], spacing=8)

    def heading(title):
        return ft.Text(i18n.t(title), size=22, color=TEXT, font_family=FONT_DISPLAY)

    def pane(title, *children):
        return ft.Column(
            [heading(title), *children], spacing=16, visible=False,
            expand=True, scroll=ft.ScrollMode.AUTO,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )

    disclosures = []

    def advanced(label, content, *, data):
        duration = motion.BASE_MS if motion.transforms() else 0
        tile = ft.ExpansionTile(
            title=ft.Text(i18n.t(label), size=13, color=TEXT,
                          weight=ft.FontWeight.W_600),
            controls=[content], maintain_state=True, dense=True,
            expanded_cross_axis_alignment=ft.CrossAxisAlignment.STRETCH,
            tile_padding=ft.padding.Padding.symmetric(horizontal=16, vertical=8),
            controls_padding=0, icon_color=TEXT_DIM, collapsed_icon_color=TEXT_DIM,
            bgcolor=SURFACE_HI, collapsed_bgcolor=SURFACE_HI,
            shape=ft.RoundedRectangleBorder(radius=RADIUS_LG),
            collapsed_shape=ft.RoundedRectangleBorder(radius=RADIUS_LG),
            animation_style=ft.AnimationStyle(duration=duration, reverse_duration=duration),
            data=data,
        )
        disclosures.append(tile)
        return tile

    def compact(btn):
        """Shrink a full-width button to a row-sized one."""
        try:
            btn.padding = ft.padding.Padding.symmetric(horizontal=16, vertical=8)
            if isinstance(btn.content, ft.Text):
                btn.content.size = 13
        except Exception:
            pass
        return btn

    # --- switches that own their own config key ------------------------------
    # Built here, like before: each reads and writes exactly one config key.
    auto_cleanup_switch = ft.Switch(
        value=bool(cfg.get("auto_delete_incomplete", True)),
        active_color=ACCENT, scale=0.85, data="install-cleanup-enabled",
    )

    def _on_auto_cleanup_change(_e, sw=auto_cleanup_switch):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            previous = bool(cfg.get("auto_delete_incomplete", True))
            if _save_preference(cfg, "auto_delete_incomplete", bool(sw.value),
                                set_status=set_status,
                                error="Couldn't save the install-cleanup setting"):
                set_status(i18n.t("Unfinished installs will be removed on the next start")
                           if cfg["auto_delete_incomplete"] else
                           i18n.t("Unfinished installs will be kept"))
            else:
                sw.value = previous
            thread_safe_ui.refresh(sw)

    auto_cleanup_switch.on_change = _on_auto_cleanup_change

    motion_switch = ft.Switch(
        value=motion.transforms(), active_color=ACCENT, scale=0.85,
        data="settings-motion-enabled",
        tooltip=i18n.t("Hover lifts and list motion. Off leaves fades only."),
    )

    def _on_motion_change(_e, sw=motion_switch):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            previous_level = motion.level()
            existed, previous = "motion_level" in cfg, cfg.get("motion_level")
            level = motion.set_level("full" if sw.value else "reduced")
            cfg["motion_level"] = level
            try:
                from cubeon import config as _config
                _config.save_config(cfg)
            except Exception:
                if existed:
                    cfg["motion_level"] = previous
                else:
                    cfg.pop("motion_level", None)
                motion.set_level(previous_level)
                set_status(i18n.t("Couldn't save the motion setting"))
            else:
                if on_motion_change is not None:
                    on_motion_change()
                set_status(i18n.t("Full motion") if sw.value else
                           i18n.t("Motion reduced - fades only, nothing moves on its own"))
            sw.value = motion.transforms()
            duration = motion.BASE_MS if motion.transforms() else 0
            for tile in disclosures:
                tile.animation_style = ft.AnimationStyle(duration=duration, reverse_duration=duration)
                thread_safe_ui.refresh(tile)
            thread_safe_ui.refresh(sw)

    motion_switch.on_change = _on_motion_change

    # ======================================================================
    # ACCOUNT
    # ======================================================================
    account_section = pane("Account", *([account_pane] if account_pane is not None else []))

    # ======================================================================
    # GAME
    # ======================================================================
    compact(tidy_btn)
    minecraft_files_pane.visible = True
    for field in (width_field, height_field):
        field.width = None
        field.expand = True
    game_window = block("Game window", group([
        _body(ft.Row([width_field, ft.Text("×", color=TEXT_DIM), height_field],
                     spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER)),
    ]))
    versions_pane = pane(
        i18n.t("Game"),
        game_window,
        block("In game", group([
            row("Cubeon Client", "Menu, HUD and Cubeon features", client_mod_cb),
            row("CustomSkinLoader (CSL)", "Skin and cape loading", csl_cb),
        ])),
        ft.Text(i18n.t("Applies on the next launch."), size=11.5, color=TEXT_DIM),
        advanced("Maintenance", group([
            row("Delete unfinished installs",
                "Clean up incomplete downloads at startup",
                auto_cleanup_switch),
            row("Tidy up files",
                "Clear temporary files and merge stray assets",
                tidy_btn),
            _body(minecraft_files_pane),
        ]), data="settings-maintenance"),
    )
    import_pane.visible = True

    # ======================================================================
    # PERFORMANCE (inside Game)
    # ======================================================================
    memory_status = ft.Text("", size=11.5, color=TEXT_DIM,
                            data="memory-limit-status")
    ram_label.tooltip = i18n.t(
        "In Minecraft's F3 screen, check the maximum after the slash on the Mem line. "
        "Allocated shows the memory Java has reserved so far and can be lower.")
    if len(ram_range_row.controls) >= 3:
        minimum, recommendation, maximum = ram_range_row.controls[:3]
        recommendation.expand = False
        recommendation.text_align = ft.TextAlign.CENTER
        ram_range_row.controls[:] = [ft.Column([
            ft.Row([minimum, maximum], alignment=ft.MainAxisAlignment.SPACE_BETWEEN),
            recommendation,
        ], spacing=6, expand=True, horizontal_alignment=ft.CrossAxisAlignment.STRETCH)]
    ram_warning.max_lines = 2
    ram_warning.overflow = ft.TextOverflow.ELLIPSIS
    versions_pane.controls.extend([
        block(i18n.t("Memory"), group([
            _body(ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(i18n.t("Maximum RAM"), size=14, color=TEXT,
                                    weight=ft.FontWeight.W_600, expand=True),
                            ram_label,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ram_slider,
                    ram_range_row,
                    ft.Container(ram_warning, height=40),
                    memory_status,
                ],
                spacing=8,
            )),
        ])),
        advanced("Advanced Java settings", group([
            _body(ft.Column(
                [
                    java_path_field,
                    detected_java_label,
                    custom_jvm_field,
                    ft.Text(i18n.t("Leave blank to use automatic Java and default flags."),
                            size=11.5, color=TEXT_FAINT),
                    ft.Container(height=8),
                    # "Which flags does Cubeon apply by default?" - collapsed,
                    # and built from launch.py so it cannot go stale.
                    _java_defaults_panel(
                        ram_slider=ram_slider,
                        custom_jvm_field=custom_jvm_field,
                        cfg=cfg, set_status=set_status, memory_status=memory_status,
                        BORDER=BORDER, ACCENT=ACCENT, ACCENT_TINT=ACCENT_TINT,
                        TEXT=TEXT, TEXT_DIM=TEXT_DIM, TEXT_FAINT=TEXT_FAINT,
                        FONT_MONO=FONT_MONO),
                ],
                spacing=8,
            )),
        ]), data="settings-java-advanced"),
    ])

    # ======================================================================
    # APPEARANCE
    # ======================================================================
    language_picker = _language_picker(
        cfg, on_restart=seasonal_restart_btn.on_click, set_status=set_status,
        BG=BG, BORDER=BORDER, ACCENT=ACCENT, TEXT=TEXT, TEXT_DIM=TEXT_DIM,
    )

    launcher_rows = [
        _body(language_picker),
        row(i18n.t("Glass background"),
            "Restart to apply",
            glass_cb),
    ]
    if custom_chrome_cb is not None:
        launcher_rows.append(row(
            i18n.t("Custom title bar"),
            "Restart to apply",
            custom_chrome_cb))
    launcher_rows.append(row(
        "Animations",
        "Off reduces movement",
        motion_switch))

    # Theme and launcher appearance share one retained section.
    seasonal_status_text.expand = True
    seasonal_restart_note.expand = True
    season_dropdown.width = None
    appearance_pane = pane(
        "Appearance", group(launcher_rows),
        block("Theme", group([
            row("Seasonal look",
                "Use colours for the current season",
                seasonal_switch),
            _body(ft.Column(
                [
                    ft.Row([seasonal_status_icon, seasonal_status_text],
                           spacing=8,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                    seasonal_source_text,
                ],
                spacing=4,
            ), pad_v=10),
            row("Season", "Auto follows your timezone", season_dropdown),
            _body(ft.Column(
                [
                    season_pin_note,
                    ft.ResponsiveRow([
                        ft.Container(keyboard_target(seasonal_restart_btn, i18n.t("Restart")),
                                     col={"xs": 12, "wide": 4}),
                        ft.Container(seasonal_restart_note, col={"xs": 12, "wide": 8}),
                    ], breakpoints={"xs": 0, "wide": 500}, spacing=12, run_spacing=8,
                        vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ],
                spacing=8,
            ), pad_v=10),
        ])),
        block(i18n.t("Extras"), group([
            row("Play scenery", "Trees and seasonal effects on Play",
                season_overlay_switch),
            row("Seasonal buddy", "A companion around the launcher",
                season_pet_switch),
        ])),
    )

    # ======================================================================
    # NOTIFICATIONS
    # ======================================================================
    def _notify_switch(key):
        sw = ft.Switch(value=bool(cfg.get(key, True)), active_color=ACCENT,
                       scale=0.85, data=key)

        def _on_change(_e, k=key, s=sw):
            ft.context.disable_auto_update()
            with thread_safe_ui.TREE_LOCK:
                previous = bool(cfg.get(k, True))
                if not _save_preference(cfg, k, bool(s.value), set_status=set_status,
                                        error="Couldn't save the notification setting"):
                    s.value = previous
                thread_safe_ui.refresh(s)

        sw.on_change = _on_change
        return sw

    def _send_test_notification(_e=None):
        """force=True on purpose: the point of the button is to check whether
        this desktop actually shows them."""
        shown = osnotify.notify(
            "mod", "Cubeon notifications are on",
            "This is what an install-finished alert looks like.",
            cfg=cfg, force=True)
        if shown:
            set_status("Test notification sent")
        elif not osnotify.available():
            set_status("This system has no desktop notifier installed")
        else:
            set_status("Couldn't show a test notification")

    notify_backend = osnotify.backend_name()

    notify_test_btn = ft.TextButton(i18n.t("Send test"),
                                   on_click=_send_test_notification)

    notification_rows = [
        row(i18n.t(label), sub, _notify_switch(key))
        for kind, key, label, sub in osnotify.KINDS
    ]
    sound_switch = ft.Switch(value=bool(cfg.get("ui_sounds", False)), active_color=ACCENT,
                             scale=0.85, data="settings-sound-enabled")

    def _sound_changed(e):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            previous = bool(cfg.get("ui_sounds", False))
            saved = _save_preference(cfg, "ui_sounds", bool(sound_switch.value),
                                     set_status=set_status,
                                     error="Couldn't save the sound setting")
            if not saved:
                sound_switch.value = previous
            thread_safe_ui.refresh(sound_switch)
            play_cue = saved and sound_switch.value
        if play_cue:
            from cubeon import ui_sounds
            ui_sounds.play("launch")

    sound_switch.on_change = _sound_changed
    notification_rows.append(row(
        "Sound feedback", "Quiet launch and error sounds", sound_switch))
    notification_rows.append(row(
        "Test notification",
        (f"Using {notify_backend}" if notify_backend
         else "No desktop notifier found"),
        notify_test_btn))
    notifications_pane = pane("Notifications", group(notification_rows))

    # ======================================================================
    # BACKUPS (inside Account)
    # ======================================================================

    frequency_dropdown.expand = True
    keep_last_field.width = None
    backup_now_btn.expand = open_folder_btn.expand = False
    backup_rows = [
        row("Automatic backups", "Runs while Cubeon is open",
            backup_enabled_switch),
        advanced("Backup schedule",
                 _body(ft.ResponsiveRow([
                     ft.Container(ft.Row([frequency_dropdown], spacing=0), col={"xs": 12, "wide": 7}),
                     ft.Container(ft.Column([keep_last_field], spacing=0,
                                  horizontal_alignment=ft.CrossAxisAlignment.STRETCH), col={"xs": 12, "wide": 5}),
                 ], breakpoints={"xs": 0, "wide": 420}, spacing=12, run_spacing=12), pad_v=12),
                 data="settings-backup-schedule"),
        row("Include world saves", "Much larger backups", include_saves_switch),
        _body(ft.Column(
            [
                ft.Row(
                    [ft.Icon(ft.Icons.HISTORY_ROUNDED, size=16,
                             color=TEXT_FAINT),
                     ft.Container(content=backup_status_text, expand=True)],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.ResponsiveRow([
                    ft.Container(keyboard_target(backup_now_btn, i18n.t("Back up now")), col={"xs": 12, "wide": 6}),
                    ft.Container(keyboard_target(open_folder_btn, i18n.t("Open backups folder")), col={"xs": 12, "wide": 6}),
                ], breakpoints={"xs": 0, "wide": 500}, spacing=12, run_spacing=12),
                keyboard_target(restore_btn, i18n.t("Restore from a backup zip")),
            ],
            spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ), pad_v=12),
    ]

    account_section.controls.append(block("Backups", group(backup_rows)))
    imports_pane = pane("Import", import_pane)
    import_pane.controls[0].visible = False  # The section already supplies its heading.

    # ======================================================================
    # LAUNCHER
    # ======================================================================
    account_section.controls.extend([block("Launcher", group([
        *([row("Replay onboarding", "Open the welcome tour",
               ft.TextButton(i18n.t("Open tour"), data="replay-onboarding",
                             on_click=lambda e: on_replay_onboarding()))]
          if on_replay_onboarding else []),
    ])), ft.Row([keyboard_target(cubeon_web_link, "Cubeon Web"), minekube_badge], spacing=16,
               vertical_alignment=ft.CrossAxisAlignment.CENTER)])

    about_pane = pane("About", build_about_section(
        SURFACE_HI=SURFACE_HI, BORDER=BORDER, ACCENT=ACCENT,
        TEXT=TEXT, TEXT_DIM=TEXT_DIM, FONT_DISPLAY=FONT_DISPLAY, FONT_MONO=FONT_MONO,
    ))

    panes = {'account': account_section, 'versions': versions_pane,
             'appearance': appearance_pane,
             'notifications': notifications_pane, 'import': imports_pane, 'about': about_pane}
    aliases = {'display': 'appearance', 'theme': 'appearance', 'seasonal': 'appearance',
               'backups': 'account', 'storage': 'account',
               'launcher': 'account', 'system': 'account',
               'game': 'versions', 'performance': 'versions', 'memory': 'versions',
               'files': 'versions'}
    for key, p in panes.items():
        p.visible = (key == active_section["value"])
        p.data = 'settings-pane-' + key

    # --- section rail ---------------------------------------------------------
    rail = ft.Column(spacing=4, tight=True,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    rail_items = {}   # key -> the row Container, built once (see _rebuild_rail)

    def _select_section(key):
        ft.context.disable_auto_update()
        if key in {'images', 'screenshots'}:
            if callable(on_open_screenshots):
                on_open_screenshots()
            return
        with thread_safe_ui.TREE_LOCK:
            key = aliases.get(key, key)
            if key not in panes:
                return
            if key != active_section["value"]:
                active_section["value"] = key
                for k, p in panes.items():
                    p.visible = (k == key)
                _rebuild_rail()
                thread_safe_ui.refresh(compact_rail if layout["compact"] else rail)
                thread_safe_ui.refresh(pane_host)
            reveal_selection()

    def _rebuild_rail():
        # Retain the controls and their keyboard targets across selections.
        if not rail_items:
            for key, icon, label in sections:
                item = _rail_item(
                    key, icon, label,
                    active=(key == active_section["value"]),
                    on_click=lambda e, k=key: _select_section(k),
                    ACCENT=ACCENT, ACCENT_TINT=ACCENT_TINT,
                    ROW_HOVER=ROW_HOVER, TEXT=TEXT, TEXT_DIM=TEXT_DIM)
                rail_items[key] = item
                from cubeon.theme import keyboard_target
                rail.controls.append(keyboard_target(item, i18n.t(label)))
        for key, item in rail_items.items():
            _apply_rail_state(item, key == active_section["value"],
                              ACCENT=ACCENT, ACCENT_TINT=ACCENT_TINT,
                              TEXT=TEXT, TEXT_DIM=TEXT_DIM)

    _rebuild_rail()

    # Each retained section owns a viewport, so switching never inherits
    # another section's scroll offset or clips the full-height gallery.
    pane_host = ft.Container(
        content=ft.Stack(
            [panes[k] for k, _, _ in sections],
            expand=True, fit=ft.StackFit.EXPAND,
        ),
        expand=True,
        padding=ft.padding.Padding.only(right=8),
    )

    rail_host = ft.Container(content=ft.Column([rail], scroll=ft.ScrollMode.AUTO,
                                              expand=True), width=168)
    divider = ft.Container(width=1, bgcolor=BORDER)
    settings_tab = ft.Row(
        [
            rail_host,
            divider,
            pane_host,
        ],
        spacing=16,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        expand=True,
    )

    # Mounted once in the launcher's retained Settings tab.
    compact_rail = ft.Row(spacing=6, scroll=ft.ScrollMode.AUTO,
                          data="settings-compact-navigation")
    compact_host = ft.Container(compact_rail, height=54, visible=False)
    rail_targets = tuple(rail.controls)
    layout = {"compact": False}
    host = ft.Column([compact_host, settings_tab], spacing=12, expand=True,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
                     data="settings-layout")

    def reveal_selection():
        if layout["compact"]:
            try:
                mounted_page = compact_rail.page
            except RuntimeError:
                return
            index = next(index for index, (key, _, _) in enumerate(sections)
                         if key == active_section["value"])
            scrolling.to_offset(mounted_page, compact_rail, index * 150)

    def layout_changed(event):
        ft.context.disable_auto_update()
        compact_mode = float(event.width or 1000) < 760
        with thread_safe_ui.TREE_LOCK:
            if compact_mode == layout["compact"]:
                return
            layout["compact"] = compact_mode
            # Move the same keyboard targets. No field or section is rebuilt
            # when a resized window changes the navigation's orientation.
            rail.controls[:] = [] if compact_mode else rail_targets
            compact_rail.controls[:] = rail_targets if compact_mode else []
            for item in rail_items.values():
                item.width = 144 if compact_mode else None
                item.height = 48 if compact_mode else None
            compact_host.visible = compact_mode
            rail_host.visible = divider.visible = not compact_mode
            settings_tab.spacing = 0 if compact_mode else 16
            pane_host.padding = 0 if compact_mode else ft.Padding(0, 0, 8, 0)
            thread_safe_ui.refresh(host)
            reveal_selection()
    host.on_size_change = layout_changed
    host.size_change_interval = 100

    # --- instant save on blur (width/height/java) ---------------------------
    fields = (('width', width_field), ('height', height_field),
              ('java_path', java_path_field), ('custom_jvm_flags', custom_jvm_field))

    def field_values():
        return tuple(str(field.value or '').strip() for _, field in fields)

    saved_fields = {'values': field_values(), 'failed': False}

    def _save_on_blur(e=None):
        """Save once per edit; keep failed edits retryable and the live config intact."""
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            if field_values() == saved_fields['values'] and not saved_fields['failed']:
                return True
            previous = {key: (key in cfg, cfg.get(key)) for key, _ in fields}
            try:
                if save_width_height_java() is False:
                    raise RuntimeError(i18n.t("Couldn't save settings"))
            except Exception as ex:
                for key, (existed, value) in previous.items():
                    if existed:
                        cfg[key] = value
                    else:
                        cfg.pop(key, None)
                saved_fields['failed'] = True
                for index, (_key, field) in enumerate(fields):
                    if field_values()[index] != saved_fields['values'][index]:
                        field.error = i18n.t("Couldn't save this change. Try again.")
                        thread_safe_ui.refresh(field)
                set_status(f"{i18n.t('Could not save settings')}: {ex}")
                return False
            for _, field in fields:
                if field.error:
                    field.error = None
                    thread_safe_ui.refresh(field)
            saved_fields.update(values=field_values(), failed=False)
            set_status(i18n.t("Settings saved"))
            return True

    for _, field in fields:
        for event_name in ('on_blur', 'on_submit'):
            previous = getattr(field, event_name)

            def saved(event, previous=previous):
                with thread_safe_ui.TREE_LOCK:
                    error = None
                    try:
                        if callable(previous):
                            previous(event)
                    except Exception as ex:
                        error = ex
                    if _save_on_blur(event) and error is not None:
                        set_status(f"{i18n.t('Settings saved')}. {error}")

            setattr(field, event_name, saved)

    # Exposed so another surface can deep-link a section (the seasonal badge
    # uses it; a notification or a milestone card would too).
    host.select_section = _select_section

    return host
