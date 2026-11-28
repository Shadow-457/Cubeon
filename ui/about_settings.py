"""Brand, installed build information and project links for Settings."""
import platform
import threading
import webbrowser

import flet as ft

from cubeon import i18n, thread_safe_ui
from cubeon.theme import RADIUS_LG, ROW_HOVER, attach_hover, keyboard_target, hover_hint
from cubeon.updater import APP_VERSION

PROJECT_URL = "https://github.com/Shadow-457/Cubeon"


def build_about_section(*, SURFACE_HI, BORDER, ACCENT, TEXT, TEXT_DIM,
                        FONT_DISPLAY, FONT_MONO):
    feedback = ft.Text("", size=12, color=TEXT_DIM, visible=False,
                       font_family=FONT_MONO, selectable=True, data="about-link-feedback")

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
        artwork = ft.Stack([
            ft.Image(src="cube.svg" if key == "about-version" else "instance_icons/block-stone.svg",
                     width=40, height=44, right=0, top=0, exclude_from_semantics=True),
            ft.Image(src="instance_icons/block-stone.svg" if key == "about-version"
                     else "instance_icons/block-grass.svg", width=32, height=36,
                     left=4, bottom=0, exclude_from_semantics=True),
        ], width=78, height=58, right=0, bottom=-4, opacity=0.45)
        body = ft.Stack([ft.Column([
            ft.Row([ft.Icon(icon, size=16, color=ACCENT),
                    ft.Text(i18n.t(label), size=12, color=TEXT_DIM,
                            font_family=FONT_MONO)], spacing=8),
            ft.Text(value, size=20, color=TEXT, font_family=FONT_MONO,
                    max_lines=1, overflow=ft.TextOverflow.ELLIPSIS, data=key),
        ], spacing=10, left=0, right=84, top=0), artwork], height=56)
        return ft.Container(card(body), col={"xs": 12, "wide": 6})

    def project_link(key, label, subtitle, icon, url):
        button = card(ft.Row([
            ft.Icon(icon, size=21, color=ACCENT),
            ft.Column([
                ft.Text(i18n.t(label), size=14, color=TEXT, weight=ft.FontWeight.W_600,
                        font_family=FONT_MONO, max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
                ft.Text(i18n.t(subtitle), size=12, color=TEXT_DIM, font_family=FONT_MONO,
                        max_lines=1, overflow=ft.TextOverflow.ELLIPSIS),
            ], spacing=4, expand=True),
            ft.Icon(ft.Icons.OPEN_IN_NEW_ROUNDED, size=16, color=TEXT_DIM),
        ], spacing=16), padding=20)
        button.height = 76
        button.data = "about-link-" + key
        button.tooltip = hover_hint(url)
        button.on_click = lambda e: open_link(url)
        attach_hover(button, SURFACE_HI, ROW_HOVER)
        return ft.Container(keyboard_target(button, i18n.t(label)), col={"xs": 12, "wide": 6})

    def credit_link(key, label, url, width):
        button = ft.Container(ft.Row([
            ft.Text(label, size=12, color=TEXT_DIM, font_family=FONT_MONO),
            ft.Icon(ft.Icons.OPEN_IN_NEW_ROUNDED, size=12, color=TEXT_DIM),
        ], spacing=6), width=width, height=32, padding=8,
            border_radius=RADIUS_LG, data="about-link-" + key, tooltip=hover_hint(url),
            on_click=lambda e: open_link(url))
        attach_hover(button, None, ROW_HOVER)
        return keyboard_target(button, label)

    logo = ft.Image(src="cube.svg", width=52, height=52, fit=ft.BoxFit.CONTAIN,
                    semantics_label="Cubeon", data="about-logo")
    wordmark = ft.Text("Cubeon", size=32, color=TEXT, font_family=FONT_DISPLAY,
                       max_lines=1, data="about-wordmark")
    brand = ft.Row([logo, ft.Column([
        wordmark,
        ft.Text(i18n.t("Minecraft launcher"), size=13, color=ACCENT, font_family=FONT_MONO),
    ], spacing=6, expand=True)], spacing=20)
    hero_copy = ft.Column([
        brand,
        ft.Text(i18n.t("Your home for Minecraft instances, mods and Cubeon cosmetics."),
                size=14, color=TEXT_DIM, font_family=FONT_MONO, width=420),
    ], spacing=20, expand=True)

    # Static bundled artwork: the real Cubeon mark above Minecraft block icons.
    # Keep decorations out of the accessibility tree and off the compact layout.
    def block(src, size, left, top, opacity=1):
        return ft.Image(src=src, width=size * 0.88, height=size * 0.88,
                        left=left * 0.88, top=top * 0.88,
                        opacity=opacity, fit=ft.BoxFit.CONTAIN, exclude_from_semantics=True)

    hero_art = ft.Stack([
        block("instance_icons/block-grass.svg", 78, 125, 24),
        block("instance_icons/block-grass.svg", 78, 165, 45),
        block("instance_icons/block-grass.svg", 78, 87, 64),
        block("instance_icons/block-stone.svg", 78, 202, 65),
        block("instance_icons/block-stone.svg", 78, 128, 82),
        block("instance_icons/block-grass.svg", 78, 165, 85),
        block("instance_icons/block-stone.svg", 78, 128, 47),
        block("cube.svg", 55, 139, 0),
        block("instance_icons/block-stone.svg", 19, 20, 8, 0.4),
        block("cube.svg", 22, 292, 12),
        block("cube.svg", 12, 325, 78),
        *[ft.Container(width=3, height=3, left=x * 0.88, top=y * 0.88, bgcolor=ACCENT, opacity=0.4)
          for x, y in ((65, 2), (280, 1), (12, 100), (300, 126))],
    ], width=300, height=144, data="about-hero-art")
    hero = card(ft.Row([hero_copy, hero_art], spacing=24), padding=28)
    hero.data = "about-hero"

    def fit_hero(event):
        width = getattr(event, "width", None)
        if not width or width <= 0:
            return
        compact = width < 420
        desired = (width >= 700, 24 if compact else 32, 40 if compact else 52,
                   20 if compact else 28, 16 if compact else 20)
        with thread_safe_ui.TREE_LOCK:
            current = (hero_art.visible, wordmark.size, logo.width, hero.padding, brand.spacing)
            if current == desired:
                return
            hero_art.visible, wordmark.size, logo.width, hero.padding, brand.spacing = desired
            logo.height = logo.width
            thread_safe_ui.refresh(hero)

    hero.on_size_change = fit_hero

    return ft.Column([
        hero,
        ft.ResponsiveRow([
            build_info("Version", APP_VERSION, ft.Icons.ACCESS_TIME_ROUNDED, "about-version"),
            build_info("Platform", platform.system(), ft.Icons.COMPUTER_OUTLINED, "about-platform"),
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
                size=12, color=TEXT_DIM, font_family=FONT_MONO),
        ft.Row([
            credit_link("horizon", "Horizon Client", "https://github.com/horizon-rust/horizon", 142),
            credit_link("minekube", "Minekube Connect", "https://github.com/minekube/connect-java", 170),
        ], spacing=8, run_spacing=8, wrap=True),
        ft.Text(i18n.t("An independent project, not affiliated with Mojang or Microsoft."),
                size=11, color=TEXT_DIM, font_family=FONT_MONO),
    ], spacing=16, horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
       data="settings-about")
