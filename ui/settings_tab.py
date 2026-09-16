"""
The Settings tab, redesigned (2026-09-09).

Goals (user ask: "good looking, easy to manage, best user experience"):
- TWO PANES: a slim left rail of section links (Game versions, Memory,
  Display, Java, Privacy, Backups) and the active section's content on the
  right. Six topics in one endless scroll was the "hard to manage" part;
  one topic at a time with a visible rail is the fix.
- INSTANT SAVE: every control persists the moment you touch it. The old
  "Save settings" button saved width/height/java only after an explicit
  click - easy to forget, easy to lose. Now on_blur/on_change save.
- Consistent with the launcher's design language: section_label headings,
  transparent rows that lift on hover, no box-in-box-in-box. Each section
  is a flat list of setting ROWS (label + control), not stacked panels.

main.py still owns all logic/controls (the RAM slider and its color math,
legacy-version widgets, backup switches, FilePickers) - this module only
arranges them. `build_settings_tab()` takes the prebuilt controls and the
save callbacks, so nothing is duplicated or rewired.
"""
import flet as ft

from cubeon.theme import (
    RADIUS, attach_hover, text_tab, ROW_HOVER, ACCENT_TINT,
    TEXT_FAINT, CARD_BORDER, CARD_FILL, ACCENT_DIM, ACCENT_HI, ON_ACCENT,
)

# (key, icon, label) for the left rail. Order = display order.
SECTIONS = [
    ("versions", ft.Icons.HISTORY_ROUNDED, "Game versions"),
    ("memory", ft.Icons.MEMORY_ROUNDED, "Memory"),
    ("display", ft.Icons.MONITOR_ROUNDED, "Display"),
    ("java", ft.Icons.COFFEE_ROUNDED, "Java"),
    ("privacy", ft.Icons.PRIVACY_TIP_ROUNDED, "Privacy"),
    ("backups", ft.Icons.BACKUP_ROUNDED, "Backups"),
]


def _setting_row(title, subtitle, control, *, TEXT, TEXT_FAINT):
    """One setting: title (+ optional one-line why-it-matters) on the left,
    the control on the right. The whole app's 'one calm row' pattern."""
    return ft.Row(
        [
            ft.Column(
                [
                    ft.Text(title, size=13.5, color=TEXT, weight=ft.FontWeight.W_600),
                    *( [ft.Text(subtitle, size=11.5, color=TEXT_FAINT)]
                       if subtitle else [] ),
                ],
                spacing=2, expand=True,
            ),
            control,
        ],
        spacing=16, vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )


def _rail_item(key, icon, label, active, on_click, *, ACCENT, ACCENT_TINT,
               ROW_HOVER, TEXT, TEXT_DIM):
    return attach_hover(
        ft.Container(
            content=ft.Row(
                [
                    ft.Icon(icon, size=17,
                            color=ACCENT if active else TEXT_DIM),
                    ft.Text(label, size=13,
                            color=TEXT if active else TEXT_DIM,
                            weight=ft.FontWeight.W_600 if active else ft.FontWeight.W_500),
                ],
                spacing=10, tight=True,
            ),
            bgcolor=ACCENT_TINT if active else None,
            border_radius=RADIUS,
            padding=ft.padding.Padding.symmetric(horizontal=12, vertical=9),
            ink=False,
            on_click=on_click,
        ),
        ACCENT_TINT if active else None,
        ROW_HOVER,
    )


def build_settings_tab(page, cfg, *, section_label, pixel_divider,
                       set_status, save_width_height_java,
                       browse_online_row, legacy_btn, legacy_note,
                       client_mod_cb, ram_slider, ram_range_row, ram_label,
                       ram_warning, width_field, height_field,
                       java_path_field, detected_java, crash_reports_cb,
                       backup_enabled_switch, frequency_dropdown,
                       include_saves_switch, keep_last_field,
                       backup_status_text, backup_now_btn, open_folder_btn,
                       restore_btn, minekube_badge,
                       BG, SURFACE, SURFACE_HI, BORDER, ACCENT, ACCENT_DIM,
                       TEXT, TEXT_DIM, DANGER, FONT_DISPLAY, FONT_MONO):
    """Assembles the two-pane Settings tab from main.py's existing controls.

    `save_width_height_java` is main.py's save_settings() minus the button
    click - called on field blur so width/height/java persist instantly.
    """

    active_section = {"value": "versions"}

    # --- section panes ------------------------------------------------------
    versions_pane = ft.Column(
        [
            section_label("Game versions"),
            ft.Container(height=2),
            ft.Text(
                "Installed versions show up on the Play tab. Turn on legacy "
                "versions to also see old releases below 1.20.",
                size=12, color=TEXT_DIM,
            ),
            ft.Container(height=10),
            browse_online_row,
            ft.Row([legacy_btn], spacing=14),
            legacy_note,
            ft.Container(height=6),
            _setting_row(
                "Cubeon extras in-game",
                "Friends, skins and the in-game menu. Off launches a clean game.",
                client_mod_cb, TEXT=TEXT, TEXT_FAINT=TEXT_FAINT,
            ),
        ],
        spacing=8, visible=True,
    )

    memory_pane = ft.Column(
        [
            section_label("Memory"),
            ft.Container(height=2),
            ft.Text(
                "How much RAM Minecraft can use. Half your system RAM is "
                "usually plenty.",
                size=12, color=TEXT_DIM,
            ),
            ft.Container(height=10),
            ram_slider,
            ram_range_row,
            ram_label,
            ram_warning,
        ],
        spacing=8, visible=False,
    )

    display_pane = ft.Column(
        [
            section_label("Display"),
            ft.Container(height=2),
            ft.Text(
                "The game window size when Minecraft opens.",
                size=12, color=TEXT_DIM,
            ),
            ft.Container(height=10),
            ft.Row(
                [width_field, height_field], spacing=12,
            ),
        ],
        spacing=8, visible=False,
    )

    java_pane = ft.Column(
        [
            section_label("Java"),
            ft.Container(height=2),
            ft.Text(
                "Leave this blank unless you need a specific Java version.",
                size=12, color=TEXT_DIM,
            ),
            ft.Container(height=10),
            java_path_field,
            ft.Text(
                f"Found: {detected_java or 'detect automatically'}",
                size=11, color=TEXT_FAINT, font_family=FONT_MONO,
            ),
        ],
        spacing=8, visible=False,
    )

    privacy_pane = ft.Column(
        [
            section_label("Privacy"),
            ft.Container(height=2),
            ft.Text(
                "Crash reports help fix bugs and never include your password "
                "or messages.",
                size=12, color=TEXT_DIM,
            ),
            ft.Container(height=10),
            crash_reports_cb,
        ],
        spacing=8, visible=False,
    )

    backups_pane = ft.Column(
        [
            section_label("Backups"),
            ft.Container(height=2),
            ft.Text(
                "Saves your settings, mods, skins and worlds so nothing is "
                "lost if you reinstall.",
                size=12, color=TEXT_DIM,
            ),
            ft.Container(height=12),
            # --- Automatic backups: the grouped knob panel, kept as one
            # visual unit (it reads as a single feature).
            ft.Container(
                content=ft.Column(
                    [
                        _setting_row(
                            "Automatic backups",
                            "Runs while the launcher is open",
                            backup_enabled_switch, TEXT=TEXT, TEXT_FAINT=TEXT_FAINT,
                        ),
                        ft.Row([frequency_dropdown, keep_last_field], spacing=12),
                        _setting_row(
                            "Include world saves",
                            "Backs up your worlds too (much larger)",
                            include_saves_switch, TEXT=TEXT, TEXT_FAINT=TEXT_FAINT,
                        ),
                    ],
                    spacing=12,
                ),
                bgcolor=SURFACE_HI, border_radius=RADIUS, padding=14,
            ),
            ft.Container(height=10),
            ft.Row(
                [
                    ft.Icon(ft.Icons.HISTORY_ROUNDED, size=16, color=TEXT_FAINT),
                    backup_status_text,
                ],
                spacing=8, vertical_alignment=ft.CrossAxisAlignment.CENTER,
            ),
            ft.Container(height=4),
            ft.Row([backup_now_btn, open_folder_btn], spacing=12),
            restore_btn,
        ],
        spacing=8, visible=False,
    )

    panes = {
        "versions": versions_pane, "memory": memory_pane,
        "display": display_pane, "java": java_pane,
        "privacy": privacy_pane, "backups": backups_pane,
    }

    # --- left rail ------------------------------------------------------------
    rail = ft.Column(spacing=2)

    def _select_section(key):
        active_section["value"] = key
        for k, pane in panes.items():
            pane.visible = (k == key)
        _rebuild_rail()
        from cubeon import thread_safe_ui
        thread_safe_ui.refresh(rail)
        for pane in panes.values():
            thread_safe_ui.refresh(pane)

    def _rebuild_rail():
        rail.controls.clear()
        for key, icon, label in SECTIONS:
            rail.controls.append(
                _rail_item(key, icon, label,
                           active=(key == active_section["value"]),
                           on_click=lambda e, k=key: _select_section(k),
                           ACCENT=ACCENT, ACCENT_TINT=ACCENT_TINT,
                           ROW_HOVER=ROW_HOVER, TEXT=TEXT, TEXT_DIM=TEXT_DIM))

    _rebuild_rail()

    # --- root -----------------------------------------------------------------
    settings_tab = ft.Row(
        [
            # Slim left rail: section links, one per topic.
            ft.Container(
                content=ft.Column(
                    [
                        ft.Text("Settings", size=28, color=TEXT,
                                font_family=FONT_DISPLAY),
                        ft.Container(height=6),
                        rail,
                        ft.Container(expand=True),
                        minekube_badge,
                    ],
                    spacing=4,
                ),
                width=210, padding=ft.padding.Padding.only(right=18),
            ),
            # Vertical rule between rail and content.
            ft.Container(width=1, bgcolor=CARD_BORDER, expand=False),
            # Active section, one topic at a time.
            ft.Container(
                content=ft.Column(
                    [panes[k] for k, _, _ in SECTIONS],
                    spacing=8, expand=True,
                ),
                expand=True, padding=ft.padding.Padding.only(left=24),
            ),
        ],
        spacing=0,
        vertical_alignment=ft.CrossAxisAlignment.START,
        expand=True,
    )

    # Wrap in a scrollable host so narrow windows don't clip the rail.
    host = ft.Column([settings_tab], spacing=0, scroll=ft.ScrollMode.AUTO,
                     expand=True)

    # --- instant save on blur (width/height/java) ---------------------------
    # The old "Save settings" button is gone: leaving the field saves.
    def _save_on_blur(e=None):
        """Persist width/height/java_path.

        Guarded: this runs from on_blur AND on_submit, and it used to call
        save_width_height_java() bare. A rejected value (e.g. "abc" in the
        width field, which int() refuses) or an unwritable config file would
        raise straight out of the handler - Flet swallows handler exceptions,
        so the field simply looked dead: no save, no error, no feedback.
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
    # Enter in the field also saves (and feels instant). The previous submit
    # handler is preserved, but each half is isolated so a failure in one
    # can't stop the other (previously `(p and p(e), _save_on_blur(e))` would
    # abort the whole tuple eval if p(e) raised).
    for f in (width_field, height_field, java_path_field):
        prev = f.on_submit

        def _submit(e, p=prev):
            if p:
                try:
                    p(e)
                except Exception:
                    pass
            _save_on_blur(e)

        f.on_submit = _submit

    return host
