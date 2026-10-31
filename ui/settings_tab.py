"""
The Settings tab, rewritten (2026-10-26).

What was wrong before: every setting carried a paragraph of explanation, rows
were a mix of checkboxes, switches, loose buttons and boxed panels, and the
account strip sat above everything and ate the height.

What it is now:
- ONE rail of sections on the left (Account, Game, Performance, Display,
  Seasonal, System, Doctor, Screenshots) and the active section on the right.
  Account is a section here, not a strip above the rail.
- ONE row pattern everywhere: a title, at most one short grey line, and the
  control on the right. Rows live in a group card and are separated by hairline
  dividers - no box-in-box, no loose checkboxes (every on/off is a switch).
- Copy is short. Anything that needs a paragraph is a tooltip, not a wall of
  text under the control.

main.py still owns all logic/controls (the RAM slider and its colour math,
legacy-version widgets, backup switches, FilePickers) - this module only
arranges them. `build_settings_tab()` keeps its old signature (plus optional
`account_pane`, `on_replay_onboarding` and `doctor_target`), so nothing is
rewired.
"""
import flet as ft
import threading
import unicodedata

from cubeon import i18n
from cubeon import motion
from cubeon import osnotify
from cubeon import thread_safe_ui
from cubeon.theme import (
    RADIUS, RADIUS_LG, attach_hover, ROW_HOVER, ACCENT_TINT, TEXT_FAINT,
)

# (key, icon, label). Order = display order. The keys are unchanged so deep
# links (the seasonal badge uses "seasonal") keep working; "account" is new.
SECTIONS = [
    ("account", ft.Icons.PERSON_ROUNDED, "Account"),
    ("versions", ft.Icons.SPORTS_ESPORTS_ROUNDED, "Game"),
    ("memory", ft.Icons.MEMORY_ROUNDED, "Performance"),
    ("display", ft.Icons.MONITOR_ROUNDED, "Display"),
    ("seasonal", ft.Icons.PARK_ROUNDED, "Seasonal"),
    ("system", ft.Icons.TUNE_ROUNDED, "System"),
    ("doctor", ft.Icons.MEDICAL_SERVICES_ROUNDED, "Doctor"),
    ("images", ft.Icons.PHOTO_LIBRARY_ROUNDED, "Screenshots"),
]

# The rail's motion: the section tint fades and its icon lifts one step.
# Deliberately the ONLY animation in this tab.
RAIL_ANIM = ft.Animation(150, ft.AnimationCurve.EASE_OUT_CUBIC)


def _apply_rail_state(item, active, *, ACCENT, ACCENT_TINT, TEXT, TEXT_DIM):
    """Paint one rail row for its active/inactive state, IN PLACE.

    Mutating (rather than rebuilding) is what lets the tint fade and the icon
    scale: `animate`/`animate_scale` only mean anything on a control the
    client already knows about.
    """
    item.bgcolor = ACCENT_TINT if active else None
    icon, label = item.content.controls[0], item.content.controls[1]
    icon.color = ACCENT if active else TEXT_DIM
    icon.scale = 1.0 if active else 0.94
    label.color = TEXT if active else TEXT_DIM
    label.weight = ft.FontWeight.W_600 if active else ft.FontWeight.W_500


def _rail_item(key, icon, label, active, on_click, *, ACCENT, ACCENT_TINT,
               ROW_HOVER, TEXT, TEXT_DIM):
    return attach_hover(
        ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, size=18,
                            color=ACCENT if active else TEXT_DIM,
                            scale=1.0 if active else 0.94,
                            animate_scale=RAIL_ANIM),
                    ft.Text(label, size=13.5,
                            color=TEXT if active else TEXT_DIM,
                            weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_500),
                ],
                spacing=12, tight=True,
            ),
            bgcolor=ACCENT_TINT if active else None,
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=14, vertical=11),
            ink=False,
            on_click=on_click,
            animate=RAIL_ANIM,
        ),
        ACCENT_TINT if active else None,
        ROW_HOVER,
    )


def _row(title, subtitle, control, *, TEXT, TEXT_DIM):
    """One setting: title (+ at most one short grey line) on the left, the
    control on the right. The only row pattern in the whole tab."""
    return ft.Container(
        content=ft.Row(
            [
                ft.Column(
                    [
                        ft.Text(i18n.t(title), size=14, color=TEXT,
                                weight=ft.FontWeight.W_600),
                        *([ft.Text(i18n.t(subtitle), size=12, color=TEXT_DIM)]
                          if subtitle else []),
                    ],
                    spacing=2, expand=True,
                ),
                control,
            ],
            spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.Padding.symmetric(horizontal=18, vertical=13),
    )


def _body(control, *, pad_v=14):
    """A full-width cell inside a group (fields, sliders - things that are not
    a title/control pair)."""
    return ft.Container(
        content=control,
        padding=ft.padding.Padding.symmetric(horizontal=18, vertical=pad_v),
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
    choices = ft.ListView(height=252, spacing=3, data="language-options")
    no_results = ft.Text(i18n.t("No languages found"), color=TEXT_DIM,
                         size=12, visible=False, font_family=ui_font)
    dropdown = ft.Container(
        content=ft.Column([search, choices, no_results], spacing=10,
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
            chevron.name = ft.Icons.EXPAND_MORE_ROUNDED
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
                rows.append(ft.Container(
                    content=ft.Row([
                        ft.Column(labels, spacing=2, expand=True),
                        ft.Icon(ft.Icons.CHECK_ROUNDED, size=18, color=ACCENT,
                                visible=code == selected()),
                    ], spacing=10),
                    padding=ft.padding.Padding.symmetric(horizontal=10, vertical=9),
                    bgcolor=ACCENT_TINT if code == selected() else None,
                    border_radius=RADIUS, ink=False,
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
            chevron.name = ft.Icons.EXPAND_LESS_ROUNDED if dropdown.visible else ft.Icons.EXPAND_MORE_ROUNDED
            if dropdown.visible:
                search.value = ''
                filter_choices()
            thread_safe_ui.refresh(panel)

    search.on_change = filter_choices
    selector = ft.Container(
        content=ft.Row([
            ft.Icon(ft.Icons.LANGUAGE_ROUNDED, size=20, color=ACCENT),
            ft.Column([native_text, english_text], spacing=2, expand=True), chevron,
        ], spacing=12),
        on_click=toggle, data="language-picker-toggle",
        padding=12, bgcolor=ft.Colors.with_opacity(.35, BG),
        border=ft.border.Border.all(1, BORDER), border_radius=RADIUS, ink=False,
    )
    panel = ft.Column([
        ft.Text(i18n.t("Language"), size=14, color=TEXT, weight=ft.FontWeight.W_600, font_family=ui_font),
        selector, dropdown, notice,
    ], spacing=12, data="language-picker")
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

    rows = ft.ListView(spacing=1, height=288, visible=False)
    chevron = ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=18, color=TEXT_DIM)
    summary = ft.Text("", size=11.5, color=TEXT_FAINT)
    open_state = {"v": False}

    def _sync_memory():
        ram_slider.disabled = not bool(enabled.value)
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
                    "Cubeon's default Java flags are off. The profile or Java chooses the memory limit.")
            thread_safe_ui.refresh(memory_status)
        thread_safe_ui.refresh(ram_slider)

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
                                width=232, selectable=True, rtl=False),
                        ft.Column(
                            [ft.Text(note, size=11, color=TEXT_DIM),
                             *([ft.Text(i18n.t("Disabled in Settings") if not enabled.value
                                        else i18n.t("Not added on this machine"),
                                        size=10, color=TEXT_FAINT)]
                               if dropped else [])],
                            spacing=1, expand=True, tight=True),
                    ],
                    spacing=12, vertical_alignment=ft.CrossAxisAlignment.START,
                ),
                padding=ft.padding.Padding.symmetric(horizontal=18, vertical=5),
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
                ft.Text(i18n.t("Turn off to use only your custom flags. The RAM slider then stops setting the Java heap."),
                        size=11.5, color=TEXT_DIM),
            ], spacing=3, expand=True), enabled,
        ], spacing=12),
        padding=ft.padding.Padding.symmetric(horizontal=18, vertical=12))

    def _toggle(e=None):
        with thread_safe_ui.TREE_LOCK:
            open_state["v"] = not open_state["v"]
            rows.visible = open_state["v"]
            chevron.name = (ft.Icons.EXPAND_MORE_ROUNDED if open_state["v"]
                            else ft.Icons.CHEVRON_RIGHT_ROUNDED)
            if open_state["v"]:
                _rebuild()   # pick up a RAM change made since it was last opened
            thread_safe_ui.refresh(rows)
            thread_safe_ui.refresh(chevron)

    header = attach_hover(
        ft.Container(
            content=ft.Row(
                [chevron,
                 ft.Text(i18n.t("Cubeon's default flags"), size=13, color=TEXT,
                         weight=ft.FontWeight.W_600),
                 ft.Container(expand=True),
                 summary],
                spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            padding=ft.padding.Padding.symmetric(horizontal=18, vertical=12),
            ink=False, on_click=_toggle,
            tooltip="The JVM options Cubeon passes to Java on every launch, "
                    "and why each one is there",
        ),
        None, ROW_HOVER,
    )

    for control in (ram_slider, custom_jvm_field):
        previous = control.on_change

        def changed(event, previous=previous):
            with thread_safe_ui.TREE_LOCK:
                if callable(previous):
                    previous(event)
                if open_state["v"]:
                    _rebuild()
                else:
                    _sync_memory()

        control.on_change = changed

    _sync_memory()
    return ft.Container(
        content=ft.Column([toggle_row, header, rows], spacing=0, tight=True),
        bgcolor=ft.Colors.with_opacity(0.35, ACCENT_TINT),
        border=ft.border.Border.all(1, BORDER),
        border_radius=RADIUS,
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
                       client_mod_cb, glass_cb, tidy_btn, ram_slider, ram_range_row, ram_label,
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
                       season_pet_switch, season_ambience_switch,
                       BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                       TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO,
                       screenshot_gallery=None, refresh_screenshot_gallery=None,
                       account_pane=None, on_replay_onboarding=None,
                       doctor_target=None, on_check_updates=None):
    """Assembles the two-pane Settings tab from main.py's existing controls.

    `save_width_height_java` is main.py's save_settings() minus the button
    click - called on field blur so width/height/java persist instantly.

    `account_pane` (optional) is the prebuilt Account section; when it is
    None the Account entry is simply left out of the rail.

    `custom_chrome_cb` is the one that can legitimately be None: the custom
    window frame is Windows/Linux-only, so main.py passes None elsewhere and
    the row is left out entirely.

    `doctor_target` (optional) returns (mc_version, loader, version_id) for the
    instance to check; when it is None the Doctor pane says so instead of
    guessing. The full check runs on a worker thread and renders every result
    inline - the error stays attached to the fix that followed it.
    """

    # Labels are translated at build time; the KEYS are not - deep links (the
    # seasonal badge uses "seasonal") key off them. A language change lands on
    # the next start, like the rest of the chrome.
    sections = [(key, icon, i18n.t(label)) for key, icon, label in SECTIONS
                if key != "account" or account_pane is not None]
    active_section = {"value": sections[0][0]}

    def row(title, subtitle, control):
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
            [heading(title), ft.Container(height=2), *children],
            spacing=18, visible=False,
        )

    def compact(btn):
        """Shrink a full-width button to a row-sized one."""
        try:
            btn.padding = ft.padding.Padding.symmetric(horizontal=18, vertical=9)
            if isinstance(btn.content, ft.Text):
                btn.content.size = 13
        except Exception:
            pass
        return btn

    # --- switches that own their own config key ------------------------------
    # Built here, like before: each reads and writes exactly one config key.
    auto_cleanup_switch = ft.Switch(
        value=bool(cfg.get("auto_delete_incomplete", True)),
        active_color=ACCENT, scale=0.85,
    )

    def _on_auto_cleanup_change(_e, sw=auto_cleanup_switch):
        """Persist now, like every other control in this tab."""
        cfg["auto_delete_incomplete"] = bool(sw.value)
        try:
            from cubeon import config as _config
            _config.save_config(cfg)
        except Exception:
            set_status("Couldn't save the install-cleanup setting")
            return
        set_status("Unfinished installs will be removed on the next start"
                   if sw.value else
                   "Unfinished installs will be kept")

    auto_cleanup_switch.on_change = _on_auto_cleanup_change

    motion_switch = ft.Switch(
        value=motion.transforms(), active_color=ACCENT, scale=0.85,
    )

    def _on_motion_change(_e, sw=motion_switch):
        """Apply now, persist now. The level is consulted when an event fires,
        so it takes effect on rows already on screen - no restart."""
        level = motion.set_level("full" if sw.value else "reduced")
        sw.value = motion.transforms()      # the truth, not the click
        cfg["motion_level"] = level
        try:
            from cubeon import config as _config
            _config.save_config(cfg)
        except Exception:
            set_status("Couldn't save the motion setting")
            return
        set_status("Full motion" if sw.value else
                   "Motion reduced - fades only, nothing moves on its own")

    motion_switch.on_change = _on_motion_change

    # ======================================================================
    # ACCOUNT
    # ======================================================================
    account_section = None
    if account_pane is not None:
        account_section = pane(i18n.t("Account"), account_pane)

    # ======================================================================
    # GAME
    # ======================================================================
    compact(tidy_btn)
    versions_pane = pane(
        i18n.t("Game"),
        block(i18n.t("Versions"), ft.Column(
            [
                group([
                    row("Show snapshots",
                        "Include snapshot builds in the version list",
                        browse_online_row),
                    row("Legacy versions",
                        "Releases below 1.20",
                        legacy_btn),
                ]),
                # Shown only while legacy is on (main.py toggles it).
                legacy_note,
            ],
            spacing=8,
        )),
        block("In game", group([
            row("Cubeon extras",
                "Friends, skins and the in-game menu. Off launches a clean game.",
                client_mod_cb),
        ])),
        block(i18n.t("Maintenance"), group([
            row("Delete unfinished installs",
                "Removes half-downloaded versions at startup",
                auto_cleanup_switch),
            row("Tidy up files",
                "Merges stray assets, clears temp files. Worlds are never touched.",
                tidy_btn),
        ])),
        import_pane,
    )
    import_pane.visible = True

    # ======================================================================
    # PERFORMANCE
    # ======================================================================
    memory_status = ft.Text("", size=11.5, color=TEXT_DIM,
                            data="memory-limit-status")
    performance_pane = pane(
        i18n.t("Performance"),
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
                    ram_warning,
                    memory_status,
                    ft.Text(i18n.t("In Minecraft's F3 screen, check the maximum after the slash on the Mem line. "
                                   "Allocated shows the memory Java has reserved so far and can be lower."),
                            size=11.5, color=TEXT_FAINT),
                ],
                spacing=6,
            )),
        ])),
        block(i18n.t("Java"), group([
            _body(ft.Column(
                [
                    java_path_field,
                    ft.Text(f"Found: {detected_java or 'detected automatically'}",
                            size=11.5, color=TEXT_FAINT, font_family=FONT_MONO),
                    ft.Container(height=4),
                    custom_jvm_field,
                    ft.Text(i18n.t("Extra flags go after Cubeon's defaults. "
                            "Leave both fields blank unless you need them."),
                            size=11.5, color=TEXT_FAINT),
                    ft.Container(height=6),
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
                spacing=6,
            )),
        ])),
    )

    # ======================================================================
    # DISPLAY
    # ======================================================================
    language_picker = _language_picker(
        cfg, on_restart=seasonal_restart_btn.on_click, set_status=set_status,
        BG=BG, BORDER=BORDER, ACCENT=ACCENT, TEXT=TEXT, TEXT_DIM=TEXT_DIM,
    )

    launcher_rows = [
        _body(language_picker),
        row(i18n.t("Glass background"),
            "Translucent window. Restart to apply.",
            glass_cb),
    ]
    if custom_chrome_cb is not None:
        launcher_rows.append(row(
            i18n.t("Custom title bar"),
            "Cubeon's own window frame. Restart to apply.",
            custom_chrome_cb))
    launcher_rows.append(row(
        "Animations",
        "Hover lifts and list motion. Off leaves fades only.",
        motion_switch))

    display_pane = pane(
        i18n.t("Display"),
        block(i18n.t("Game window"), group([
            row("Window size", "Resolution Minecraft opens at",
                ft.Row([width_field, ft.Text("x", color=TEXT_DIM),
                        height_field], spacing=10,
                       vertical_alignment=ft.CrossAxisAlignment.CENTER)),
        ])),
        block(i18n.t("Launcher"), group(launcher_rows)),
    )

    # ======================================================================
    # SEASONAL
    # ======================================================================
    seasonal_pane = pane(
        i18n.t("Seasonal"),
        block(i18n.t("Look"), group([
            row("Seasonal look",
                "Colours that follow the season in your timezone",
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
                    ft.Row([seasonal_restart_btn, seasonal_restart_note],
                           spacing=12,
                           vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ],
                spacing=8,
            ), pad_v=10),
        ])),
        block(i18n.t("Extras"), group([
            row("Seasonal buddy", "A little companion on the sidebar",
                season_pet_switch),
            row("Weather effects", "Leaves, snow or petals drifting across the top",
                season_ambience_switch),
        ])),
    )

    # ======================================================================
    # SYSTEM
    # ======================================================================
    def _save_notify_setting(_e=None):
        try:
            from cubeon import config as _config
            _config.save_config(cfg)
        except Exception:
            set_status("Couldn't save the notification setting")

    def _notify_switch(key):
        sw = ft.Switch(value=bool(cfg.get(key, True)), active_color=ACCENT,
                       scale=0.85)

        def _on_change(_e, k=key, s=sw):
            cfg[k] = bool(s.value)
            _save_notify_setting()

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

    # STABLE reads GitHub's /releases/latest (never a prerelease); BETA also
    # sees prereleases. Two states, one click - a cycling chip, not a dropdown.
    update_channel_chip = ft.Container(
        data="update-channel",
        content=ft.Row(
            [
                ft.Icon(ft.Icons.VERIFIED_ROUNDED, size=15, color=ACCENT),
                ft.Text("STABLE", size=12, weight=ft.FontWeight.W_700,
                        color=ACCENT),
            ],
            spacing=6, tight=True,
        ),
        bgcolor=ACCENT_TINT, border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=12, vertical=7),
        ink=False,
        on_click=lambda e: _cycle_update_channel(),
    )

    def _paint_update_channel():
        beta = str(cfg.get("update_channel") or "stable").lower() == "beta"
        chip_row = update_channel_chip.content
        chip_row.controls[0].icon = (ft.Icons.SCIENCE_ROUNDED if beta
                                     else ft.Icons.VERIFIED_ROUNDED)
        chip_row.controls[1].value = "BETA" if beta else "STABLE"
        try:
            update_channel_chip.update()
        except Exception:
            pass

    def _cycle_update_channel():
        beta = str(cfg.get("update_channel") or "stable").lower() == "beta"
        cfg["update_channel"] = "stable" if beta else "beta"
        try:
            from cubeon import config as _config
            _config.save_config(cfg)
        except Exception:
            set_status("Couldn't save the update channel")
        _paint_update_channel()
        set_status("Update channel: beta - prereleases will be offered too"
                   if cfg["update_channel"] == "beta" else
                   "Update channel: stable")

    _paint_update_channel()

    notify_test_btn = ft.Container(
        content=ft.Text("Send test", color=TEXT, weight=ft.FontWeight.W_600,
                        size=13),
        bgcolor=ft.Colors.with_opacity(0.6, BG),
        border=ft.border.Border.all(1, BORDER),
        border_radius=RADIUS,
        padding=ft.padding.Padding.symmetric(horizontal=18, vertical=9),
        alignment=ft.Alignment.CENTER, ink=False,
        on_click=_send_test_notification,
    )

    notification_rows = [
        row(i18n.t(label), sub, _notify_switch(key))
        for kind, key, label, sub in osnotify.KINDS
    ]
    notification_rows.append(row(
        "Test notification",
        (f"Using {notify_backend}" if notify_backend
         else "No desktop notifier found - these switches will do nothing"),
        notify_test_btn))

    backup_rows = [
        row("Automatic backups", "Runs while Cubeon is open",
            backup_enabled_switch),
        _body(ft.Row([frequency_dropdown, keep_last_field], spacing=12), pad_v=12),
        row("Include world saves", "Much larger backups", include_saves_switch),
        _body(ft.Column(
            [
                ft.Row(
                    [ft.Icon(ft.Icons.HISTORY_ROUNDED, size=16,
                             color=TEXT_FAINT),
                     ft.Container(content=backup_status_text, expand=True)],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER),
                # Expanded buttons need a bounded, unwrapped Row. Flutter's
                # Wrap cannot lay out flex children and paints an error panel.
                ft.Row([backup_now_btn, open_folder_btn], spacing=12),
                restore_btn,
            ],
            spacing=10,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        ), pad_v=12),
    ]

    minecraft_files_pane.visible = True
    system_pane = pane(
        i18n.t("System"),
        block("Welcome tour", group([
            row("Replay onboarding", "See Cubeon's introduction again.",
                ft.TextButton("Open tour", on_click=lambda e: on_replay_onboarding()))
        ])) if on_replay_onboarding else ft.Container(visible=False),
        block(i18n.t("Notifications"), group(notification_rows)),
        block(i18n.t("Updates"), group([
            row("Update channel",
                "Stable is the default. Beta also offers prereleases on the next launch.",
                update_channel_chip),
            _body(ft.Text("A newer version shows Skip and Update when Cubeon starts. "
                          "Update downloads, installs and reopens Cubeon automatically.", size=12,
                          color=TEXT_DIM), pad_v=12),
            *([row("Launcher updates", "Check again after reconnecting to the internet.",
                   ft.TextButton("Check for updates", data="check-launcher-updates",
                                 on_click=lambda e: on_check_updates()))]
              if on_check_updates else []),
        ])),
        minecraft_files_pane,
        block(i18n.t("Backups"), group(backup_rows)),
        ft.Row([cubeon_web_link, minekube_badge], spacing=16,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
    )

    # ======================================================================
    # DOCTOR
    # ======================================================================
    doctor_status = ft.Text("", size=12.5, color=TEXT_DIM, visible=False,
                            selectable=True)
    doctor_spinner = ft.ProgressRing(width=14, height=14, stroke_width=2,
                                     color=ACCENT, visible=False)
    doctor_summary = ft.Text("", size=12, color=TEXT_DIM, visible=False,
                             selectable=True, data="settings-doctor-summary")
    doctor_entries = ft.ListView(spacing=8, padding=0, height=340)
    doctor_entries_host = ft.Container(
        content=doctor_entries, visible=False,
        border=ft.border.Border.all(1, BORDER), border_radius=RADIUS,
        bgcolor=BG, padding=ft.padding.Padding.symmetric(horizontal=14,
                                                          vertical=12),
    )
    doctor_cancel = threading.Event()
    doctor_lock = threading.Lock()

    def _doctor_actions(enabled=True):
        with thread_safe_ui.TREE_LOCK:
            doctor_run_btn.disabled = not enabled
            doctor_stop_btn.visible = not enabled
            doctor_spinner.visible = not enabled
            thread_safe_ui.refresh(doctor_run_btn)
            thread_safe_ui.refresh(doctor_stop_btn)
            thread_safe_ui.refresh(doctor_spinner)

    def _doctor_set_status(text=""):
        with thread_safe_ui.TREE_LOCK:
            doctor_status.value = i18n.t(text) if text else ""
            doctor_status.visible = bool(text)
            thread_safe_ui.refresh(doctor_status)

    def _doctor_clear_results():
        with thread_safe_ui.TREE_LOCK:
            doctor_entries.controls.clear()
            doctor_entries_host.visible = False
            doctor_summary.value = ""
            doctor_summary.visible = False
            thread_safe_ui.refresh(doctor_entries)
            thread_safe_ui.refresh(doctor_entries_host)
            thread_safe_ui.refresh(doctor_summary)

    def _doctor_render(report):
        """Show EVERY result inline: the error, then what the doctor did."""
        from cubeon.doctor import format_problem

        rows = []
        fixed = list(report.get("fixed") or [])
        unfixed = list(report.get("unfixed") or [])
        for entry in fixed + unfixed:
            if entry.get("fixed"):
                icon = ft.Icons.CHECK_CIRCLE_ROUNDED
                color = ACCENT
            elif entry.get("kind") == "section-failed":
                icon = ft.Icons.ERROR_OUTLINE_ROUNDED
                color = DANGER
            else:
                icon = ft.Icons.WARNING_AMBER_ROUNDED
                color = TEXT_DIM
            rows.append(ft.Row(
                [
                    ft.Icon(icon, size=15, color=color),
                    ft.Text(format_problem(entry), size=12.5,
                            color=TEXT if entry.get("fixed") else TEXT_DIM,
                            selectable=True, expand=True),
                ],
                spacing=8, vertical_alignment=ft.CrossAxisAlignment.START,
            ))
        with thread_safe_ui.TREE_LOCK:
            doctor_entries.controls[:] = rows
            doctor_entries_host.visible = bool(rows)
            summary = report.get("summary") or ""
            failed = [name for name, info in (report.get("sections") or {}).items()
                      if isinstance(info, dict) and info.get("error")]
            if report.get("cancelled"):
                summary = (summary or "Check stopped early.") + " Stopped."
            if failed:
                summary += (" Check(s) that could not run: "
                            + ", ".join(sorted(failed)) + ".")
            doctor_summary.value = summary
            doctor_summary.visible = bool(summary)
            thread_safe_ui.refresh(doctor_entries)
            thread_safe_ui.refresh(doctor_entries_host)
            thread_safe_ui.refresh(doctor_summary)

    def _doctor_target():
        try:
            return doctor_target() if callable(doctor_target) else None
        except Exception:
            return None

    def _doctor_done(report):
        try:
            _doctor_render(report)
            _doctor_set_status("")
        finally:
            doctor_lock.release()
            _doctor_actions(True)

    def run_full_doctor(e=None):
        if not doctor_lock.acquire(blocking=False):
            return
        target = _doctor_target()
        mc, loader, version_id = (target if target else (None, None, None))
        if not mc or not version_id:
            doctor_lock.release()
            _doctor_set_status("Pick a Minecraft version on the Play tab first")
            return
        if not callable(doctor_target):
            doctor_lock.release()
            _doctor_set_status("The Doctor isn't available in this build")
            return
        from cubeon.doctor_ui import start_doctor_worker

        doctor_cancel.clear()
        _doctor_clear_results()
        _doctor_set_status("")
        _doctor_actions(False)
        _doctor_set_status(f"Checking {version_id}…")
        started = start_doctor_worker(
            mc_version=mc, loader=loader or "vanilla", version_id=version_id,
            include=None, check_online=True, cancel_event=doctor_cancel,
            status_cb=_doctor_set_status, on_done=_doctor_done,
            approve_all=True)
        if started is None:
            doctor_lock.release()
            _doctor_actions(True)
            _doctor_set_status("Couldn't start the check - see the log")

    def stop_full_doctor(e=None):
        doctor_cancel.set()
        _doctor_set_status("Stopping after the current step…")

    def _doctor_button(label, icon, on_click, *, primary=False):
        return attach_hover(ft.Container(
            content=ft.Row(
                [ft.Icon(icon, size=15, color=ACCENT if primary else TEXT_DIM),
                 ft.Text(i18n.t(label), size=12.5,
                         color=TEXT if primary else TEXT_DIM,
                         weight=ft.FontWeight.W_600)],
                spacing=6, tight=True),
            bgcolor=ACCENT_TINT if primary else None,
            border=ft.border.Border.all(1, ACCENT if primary else BORDER),
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=8),
            ink=False, on_click=on_click,
        ), ACCENT_TINT if primary else "transparent", ROW_HOVER)

    doctor_run_btn = _doctor_button("Run full check", ft.Icons.MEDICAL_SERVICES_ROUNDED,
                                    run_full_doctor, primary=True)
    doctor_stop_btn = _doctor_button("Stop", ft.Icons.STOP_CIRCLE_OUTLINED,
                                     stop_full_doctor)
    doctor_stop_btn.visible = False
    if not callable(doctor_target):
        doctor_run_btn.disabled = True

    doctor_pane = pane(
        i18n.t("Doctor"),
        ft.Text(
            "Checks launch settings, mods, resource packs, shaders, modpacks "
            "and server plugins for the selected instance. Problems are fixed "
            "when it is safe to do so; anything disabled is kept on disk so it "
            "can be turned back on in Mods → Installed.",
            size=12.5, color=TEXT_DIM),
        ft.Row(
            [doctor_run_btn, doctor_stop_btn, doctor_spinner],
            spacing=12, vertical_alignment=ft.CrossAxisAlignment.CENTER),
        doctor_status,
        doctor_summary,
        doctor_entries_host,
        ft.Text(
            "Clicking Run full check is your approval for the fixes it finds, "
            "including installing a missing required library. Nothing is "
            "changed by just opening this page.",
            size=11.5, color=TEXT_FAINT),
    )

    # ======================================================================
    # SCREENSHOTS
    # ======================================================================
    if screenshot_gallery is None:
        from ui.screenshot_gallery import build_screenshot_gallery_tab
        screenshot_gallery, refresh_screenshot_gallery = build_screenshot_gallery_tab(page)

    images_pane = ft.Container(content=screenshot_gallery, height=620)

    panes = {
        "versions": versions_pane,
        "memory": performance_pane,
        "display": display_pane,
        "seasonal": seasonal_pane,
        "system": system_pane,
        "doctor": doctor_pane,
        "images": images_pane,
    }
    if account_section is not None:
        panes["account"] = account_section
    for key, p in panes.items():
        p.visible = (key == active_section["value"])

    # --- section rail ---------------------------------------------------------
    rail = ft.Column(spacing=2, tight=True,
                     horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    rail_items = {}   # key -> the row Container, built once (see _rebuild_rail)

    def _select_section(key):
        if key not in panes:
            return
        active_section["value"] = key
        if key == "images" and callable(refresh_screenshot_gallery):
            refresh_screenshot_gallery()
        for k, p in panes.items():
            p.visible = (k == key)
        _rebuild_rail()
        from cubeon import thread_safe_ui
        thread_safe_ui.refresh(rail)
        for p in panes.values():
            thread_safe_ui.refresh(p)
        # No fade on the pane itself: a dip-to-0-opacity-then-settle stuttered
        # (it needs two flushes ~20ms apart that each re-sync the whole host).

    def _rebuild_rail():
        # Built ONCE, then mutated, so the tint can fade and the icon can lift.
        if not rail_items:
            for key, icon, label in sections:
                item = _rail_item(
                    key, icon, label,
                    active=(key == active_section["value"]),
                    on_click=lambda e, k=key: _select_section(k),
                    ACCENT=ACCENT, ACCENT_TINT=ACCENT_TINT,
                    ROW_HOVER=ROW_HOVER, TEXT=TEXT, TEXT_DIM=TEXT_DIM)
                rail_items[key] = item
                rail.controls.append(item)
        for key, item in rail_items.items():
            _apply_rail_state(item, key == active_section["value"],
                              ACCENT=ACCENT, ACCENT_TINT=ACCENT_TINT,
                              TEXT=TEXT, TEXT_DIM=TEXT_DIM)

    _rebuild_rail()

    # Only the CONTENT pane scrolls; the rail stays put beside it.
    pane_host = ft.Container(
        content=ft.Column(
            [panes[k] for k, _, _ in sections],
            spacing=8, expand=True, scroll=ft.ScrollMode.AUTO,
        ),
        expand=True,
        padding=ft.padding.Padding.only(right=6),
    )

    rail_host = ft.Container(content=rail, width=184)
    settings_tab = ft.Row(
        [
            rail_host,
            ft.Container(width=1, bgcolor=BORDER),
            pane_host,
        ],
        spacing=22,
        vertical_alignment=ft.CrossAxisAlignment.STRETCH,
        expand=True,
    )

    # The popup already bounds the height; the content pane owns the scroll.
    host = ft.Column([settings_tab], spacing=0, expand=True)

    # --- instant save on blur (width/height/java) ---------------------------
    def _save_on_blur(e=None):
        """Persist width/height/java_path/custom flags.

        Guarded: this runs from on_blur AND on_submit. A rejected value or an
        unwritable config file would otherwise raise straight out of the
        handler - Flet swallows handler exceptions, so the field would look
        dead with no feedback.
        """
        try:
            save_width_height_java()
        except Exception as ex:
            set_status(f"Couldn't save settings: {ex}")
            return
        set_status("Settings saved")

    width_field.on_blur = _save_on_blur
    height_field.on_blur = _save_on_blur
    java_path_field.on_blur = _save_on_blur
    custom_jvm_field.on_blur = _save_on_blur
    # Enter also saves. The previous submit handler is preserved, but each
    # half is isolated so a failure in one can't stop the other.
    for f in (width_field, height_field, java_path_field, custom_jvm_field):
        prev = f.on_submit

        def _submit(e, p=prev):
            if p:
                try:
                    p(e)
                except Exception:
                    pass
            _save_on_blur(e)

        f.on_submit = _submit

    # Exposed so another surface can deep-link a section (the seasonal badge
    # uses it; a notification or a milestone card would too).
    host.select_section = _select_section

    return host
