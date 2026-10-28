"""
The Settings tab, rewritten (2026-10-26).

What was wrong before: every setting carried a paragraph of explanation, rows
were a mix of checkboxes, switches, loose buttons and boxed panels, and the
account strip sat above everything and ate the height.

What it is now:
- ONE rail of sections on the left (Account, Game, Performance, Display,
  Seasonal, System, Screenshots) and the active section on the right.
  Account is a section here, not a strip above the rail.
- ONE row pattern everywhere: a title, at most one short grey line, and the
  control on the right. Rows live in a group card and are separated by hairline
  dividers - no box-in-box, no loose checkboxes (every on/off is a switch).
- Copy is short. Anything that needs a paragraph is a tooltip, not a wall of
  text under the control.

main.py still owns all logic/controls (the RAM slider and its colour math,
legacy-version widgets, backup switches, FilePickers) - this module only
arranges them. `build_settings_tab()` keeps its old signature (plus one
optional `account_pane`), so nothing is rewired.
"""
import flet as ft

from cubeon import i18n
from cubeon import motion
from cubeon import osnotify
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


def _java_defaults_panel(*, ram_slider, custom_jvm_field, BORDER, ACCENT,
                         ACCENT_TINT, TEXT, TEXT_DIM, TEXT_FAINT, FONT_MONO):
    """The read-only "these are Cubeon's default JVM flags" disclosure.

    Deliberately COLLAPSED and deliberately a readout: nobody needs twenty GC
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

    rows = ft.ListView(spacing=1, height=288, visible=False)
    chevron = ft.Icon(ft.Icons.CHEVRON_RIGHT_ROUNDED, size=18, color=TEXT_DIM)
    summary = ft.Text("", size=11.5, color=TEXT_FAINT)
    open_state = {"v": False}

    def _rebuild():
        """Re-read the live settings and repaint the list."""
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
                ram or None, custom_jvm_flags=user_flags)
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
                             *([ft.Text(i18n.t("Not added on this machine"),
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
        else:
            # The count leads, the translated phrase follows, so a language
            # that puts its noun first still reads correctly.
            summary.value = f"{applied} {i18n.t('flags added')}" + (
                f", {skipped} {i18n.t('not on this machine')}" if skipped else "")
        # Repaint only this panel: the rest of Settings is untouched.
        thread_safe_ui.refresh(rows)
        thread_safe_ui.refresh(summary)

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
            if callable(previous):
                previous(event)
            if open_state["v"]:
                with thread_safe_ui.TREE_LOCK:
                    _rebuild()

        control.on_change = changed

    return ft.Container(
        content=ft.Column([header, rows], spacing=0, tight=True),
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
                       account_pane=None, on_replay_onboarding=None):
    """Assembles the two-pane Settings tab from main.py's existing controls.

    `save_width_height_java` is main.py's save_settings() minus the button
    click - called on field blur so width/height/java persist instantly.

    `account_pane` (optional) is the prebuilt Account section; when it is
    None the Account entry is simply left out of the rail.

    `custom_chrome_cb` is the one that can legitimately be None: the custom
    window frame is Windows/Linux-only, so main.py passes None elsewhere and
    the row is left out entirely.
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
    performance_pane = pane(
        i18n.t("Performance"),
        block(i18n.t("Memory"), group([
            _body(ft.Column(
                [
                    ft.Row(
                        [
                            ft.Text(i18n.t("Allocated RAM"), size=14, color=TEXT,
                                    weight=ft.FontWeight.W_600, expand=True),
                            ram_label,
                        ],
                        vertical_alignment=ft.CrossAxisAlignment.CENTER,
                    ),
                    ram_slider,
                    ram_range_row,
                    ram_warning,
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
    # The language picker. Labels are shown in the language's OWN script
    # first ("العربية - Arabic") so the list is usable by someone who cannot
    # read English - that is the whole point of a language picker.
    #
    # The choice is SAVED, not applied: the chrome (nav rail, section labels,
    # every cached tab) reads i18n.t() at build time, and Arabic also has to
    # flip page.rtl. Applying half of that live would leave a mixed-language
    # window with a half-mirrored layout, which is worse than one clean
    # restart - so the row says "Restart to apply" like the other two here.
    language_dropdown = ft.Dropdown(
        value=i18n.current(),
        width=260,
        dense=True,
        text_size=13,
        bgcolor=ft.Colors.with_opacity(0.35, BG),
        border_color=BORDER,
        border_radius=RADIUS,
        options=[
            ft.dropdown.Option(
                key=code,
                text=(f"{native} — {english}" if code != "en" else english),
            )
            for code, native, english, _rtl in i18n.LANGUAGES
        ],
    )

    def _on_language_change(e=None):
        code = str(language_dropdown.value or "").strip().lower()
        if code not in i18n.SUPPORTED:
            from cubeon import thread_safe_ui
            language_dropdown.value = i18n.current()
            thread_safe_ui.refresh(language_dropdown)
            return
        previous = cfg.get(i18n.CONFIG_KEY)
        cfg[i18n.CONFIG_KEY] = code
        try:
            from cubeon import config as _config
            _config.save_config(cfg)
        except Exception:
            cfg[i18n.CONFIG_KEY] = previous
            language_dropdown.value = previous or i18n.current()
            from cubeon import thread_safe_ui
            thread_safe_ui.refresh(language_dropdown)
            set_status("Couldn't save the language")
            return
        rtl = i18n.is_rtl(code)
        set_status(f"Language set to {i18n.language_name(code, english=True)}"
                   + (" (right-to-left)" if rtl else "")
                   + " - restart Cubeon to apply")

    # on_select, NOT on_change: Flet 0.86's Dropdown fires on_select and
    # silently ignores on_change (the bug tools/test_seasonal.py guards - a
    # picker whose handler never runs looks fine in every headless test
    # because the test calls the handler itself).
    language_dropdown.on_select = _on_language_change

    launcher_rows = [
        row(i18n.t("Language"),
            "The launcher's own language. Restart to apply.",
            language_dropdown),
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
                     backup_status_text],
                    spacing=8,
                    vertical_alignment=ft.CrossAxisAlignment.CENTER),
                ft.Row([backup_now_btn, open_folder_btn, restore_btn],
                       spacing=12, wrap=True),
            ],
            spacing=10,
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
                "Stable gets finished releases. Beta also gets prereleases.",
                update_channel_chip),
        ])),
        minecraft_files_pane,
        block(i18n.t("Backups"), group(backup_rows)),
        ft.Row([cubeon_web_link, minekube_badge], spacing=16,
               vertical_alignment=ft.CrossAxisAlignment.CENTER),
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
