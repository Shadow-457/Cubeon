"""Brand, installed build information and project links for Settings."""
import platform
import threading
import webbrowser

import flet as ft

from cubeon import i18n, thread_safe_ui
from cubeon.theme import RADIUS_LG, ROW_HOVER, attach_hover, keyboard_target
from cubeon.updater import APP_VERSION

PROJECT_URL = "https://github.com/Shadow-457/Cubeon"


def build_about_section(*, SURFACE_HI, BORDER, ACCENT, TEXT, TEXT_DIM,
                        FONT_DISPLAY, FONT_MONO):
    feedback = ft.Text("", size=12, color=TEXT_DIM, visible=False,
                       selectable=True, data="about-link-feedback")

    def show_link(url):
        with thread_safe_ui.TREE_LOCK:
            feedback.value = f"{i18n.t('Open this link in your browser:')} {url}"
            feedback.visible = True
            thread_safe_ui.refresh(feedback)

    def open_link(url):
        ft.context.disable_auto_update()

        def worker():
            try:
                if webbrowser.open(url):
                    return
            except Exception:
                pass
            show_link(url)

        try:
            threading.Thread(target=worker, name="cubeon-about-link", daemon=True).start()
        except Exception:
            show_link(url)

    def card(content, *, padding=20):
        return ft.Container(content, bgcolor=SURFACE_HI,
                            border=ft.Border.all(1, BORDER), border_radius=RADIUS_LG,
                            padding=padding)

    def build_info(label, value, icon, key):
        return ft.Container(card(ft.Column([
            ft.Row([ft.Icon(icon, size=16, color=ACCENT),
                    ft.Text(i18n.t(label), size=12, color=TEXT_DIM)], spacing=8),
            ft.Text(value, size=18, color=TEXT, font_family=FONT_MONO,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, data=key),
        ], spacing=12)), col={"xs": 12, "wide": 6})

    def project_link(key, label, subtitle, icon, url):
        button = card(ft.Row([
            ft.Icon(icon, size=21, color=ACCENT),
            ft.Column([
                ft.Text(i18n.t(label), size=14, color=TEXT, weight=ft.FontWeight.W_600,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(i18n.t(subtitle), size=11, color=TEXT_DIM,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=4, expand=True),
            ft.Icon(ft.Icons.OPEN_IN_NEW_ROUNDED, size=16, color=TEXT_DIM),
        ], spacing=12), padding=16)
        button.height = 78
        button.data = "about-link-" + key
        button.tooltip = url
        button.on_click = lambda e: open_link(url)
        attach_hover(button, SURFACE_HI, ROW_HOVER)
        return ft.Container(keyboard_target(button, i18n.t(label)), col={"xs": 12, "wide": 6})

    return ft.Column([
        card(ft.Column([
            ft.Row([
                ft.Image(src="cube.svg", width=56, height=56, fit=ft.BoxFit.CONTAIN),
                ft.Column([
                    ft.Text("Cubeon", size=28, color=TEXT, font_family=FONT_DISPLAY),
                    ft.Text(i18n.t("Minecraft launcher"), size=13, color=ACCENT),
                ], spacing=6, expand=True),
            ], spacing=20),
            ft.Text(i18n.t("Your home for Minecraft instances, mods and Cubeon cosmetics."),
                    size=13, color=TEXT_DIM),
        ], spacing=20), padding=24),
        ft.ResponsiveRow([
            build_info("Version", APP_VERSION, ft.Icons.NEW_RELEASES_OUTLINED, "about-version"),
            build_info("Platform", platform.system(), ft.Icons.COMPUTER_ROUNDED, "about-platform"),
        ], breakpoints={"xs": 0, "wide": 500}, spacing=12, run_spacing=12),
        ft.ResponsiveRow([
            project_link("website", "Website", "www.ylet.online", ft.Icons.PUBLIC_ROUNDED,
                         "https://www.ylet.online/"),
            project_link("source", "Source code", "Explore Cubeon on GitHub", ft.Icons.CODE_ROUNDED,
                         PROJECT_URL),
            project_link("releases", "Release notes", "See what's new", ft.Icons.HISTORY_ROUNDED,
                         PROJECT_URL + "/releases"),
            project_link("license", "License", "Read the project license", ft.Icons.DESCRIPTION_OUTLINED,
                         PROJECT_URL + "/blob/main/LICENSE"),
        ], breakpoints={"xs": 0, "wide": 500}, spacing=12, run_spacing=12),
        feedback,
        ft.Text(i18n.t("With thanks to the open source projects behind Cubeon."),
                size=12, color=TEXT_DIM),
        ft.Text(i18n.t("An independent project, not affiliated with Mojang or Microsoft."),
                size=11, color=TEXT_DIM),
    ], spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
       data="settings-about")
