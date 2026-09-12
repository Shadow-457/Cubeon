"""NEW-UI TEMPLATE - a redesign preview, NOT the real launcher UI.

Run with:  python main.py --new-ui

This is a standalone Flet app that mocks a different launcher layout:
top-bar navigation (instead of the sidebar rail), a wide cinematic
hero with the selected version's official banner artwork behind the
controls, a card grid for versions, and a cleaner two-column layout.

It reuses the real color templates (templates/color_*.py) so the
existing palette work still applies, but NOTHING here touches the
main UI code. If the design is approved, it gets ported into main.py
by hand.
"""
import os

import flet as ft

import importlib
from cubeon.color_templates import TEMPLATE_MODULES, _derive


# ---------------------------------------------------------------- helpers

def _version_art_or_none(version):
    """Disk-cache probe for the version's banner (never downloads)."""
    try:
        from cubeon.version_art import get_version_art
        path = get_version_art(version)
        # Only trust an existing file - a synchronous download inside a
        # preview window is not acceptable.
        if path and os.path.isfile(path):
            return path
    except Exception:
        pass
    return None


def _start_art_fetch(version, on_got):
    try:
        from cubeon.version_art import fetch_async
    except Exception:
        return
    fetch_async(version, on_got)


def get_template(name):
    class T: pass
    key = next((k for k in TEMPLATE_MODULES if k == name), "green")
    mod = importlib.import_module(TEMPLATE_MODULES[key])
    t = T()
    t.PALETTE = _derive(dict(mod.PALETTE))
    return t


# ---------------------------------------------------------------- app

NAV_ITEMS = [
    ("play", "Play", ft.Icons.PLAY_ARROW_ROUNDED),
    ("mods", "Mods", ft.Icons.EXTENSION_ROUNDED),
    ("modpacks", "Modpacks", ft.Icons.INVENTORY_2_ROUNDED),
    ("servers", "Servers", ft.Icons.DNS_ROUNDED),
    ("profile", "Profile", ft.Icons.PERSON_ROUNDED),
    ("settings", "Settings", ft.Icons.SETTINGS_ROUNDED),
]

VERSIONS = ["1.21.11", "1.21.4", "1.20.1", "1.19.2", "1.16.5", "1.12.2", "1.8.9"]
MODCARDS = [
    ("Sodium", "Rendering", "17.4M"),
    ("Iris Shaders", "Shaders", "14.1M"),
    ("Fabric API", "Library", "31.2M"),
    ("Lithium", "Performance", "8.9M"),
    ("AppleSkin", "HUD", "6.3M"),
    ("Xaero's Map", "Utility", "4.8M"),
]


def build_app(page: ft.Page, palette_name: str = "green"):
    t = get_template(palette_name)
    P = t.PALETTE
    BG, SURFACE, SURFACE_HI = P["BG"], P["SURFACE"], P["SURFACE_HI"]
    TEXT, TEXT_DIM, TEXT_FAINT = P["TEXT"], P["TEXT_DIM"], P["TEXT_FAINT"]
    ACCENT, ACCENT_HI, ON_ACCENT = P["ACCENT"], P["ACCENT_HI"], P["ON_ACCENT"]
    BORDER, BORDER_HI = P["BORDER"], P["BORDER_HI"]
    R = 14
    R_LG = 18
    FONT_DISPLAY = "Minecraftia"

    page.title = "Cubeon - new UI preview"
    page.bgcolor = BG
    page.padding = 0
    page.window.width = 1120
    page.window.height = 720

    state = {"tab": "play", "version": VERSIONS[0], "art": None}

    def hero_section() -> ft.Control:
        art = state.get("art")
        art_fill = ft.Container(
            content=ft.Image(
                src=art, fit=ft.BoxFit.COVER, width=10000, height=10000
            ) if art else ft.Container(bgcolor=SURFACE_HI),
            expand=True,
            border_radius=R_LG,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )
        return ft.Container(
            content=ft.Stack(
                [
                    art_fill,
                    # dark scrim so white text reads on any banner
                    ft.Container(
                        bgcolor=ft.Colors.with_opacity(0.55, "#000000"),
                        expand=True,
                    ),
                    ft.Container(
                        content=ft.Column(
                            [
                                ft.Text("CUBEON", size=13, color=ACCENT_HI,
                                        weight=ft.FontWeight.W_700,
                                        style=ft.TextStyle(letter_spacing=1.2)),
                                ft.Text(f"Minecraft {state['version']}", size=32,
                                        color="#FFFFFF", font_family=FONT_DISPLAY),
                                ft.Text("Offline launcher - any version, any loader.",
                                        size=13, color=ft.Colors.with_opacity(0.85, "#FFFFFF")),
                            ],
                            spacing=6,
                        ),
                        left=24, right=24, top=24, bottom=24,
                    ),
                ],
                expand=True,
            ),
            height=180,
            border_radius=R_LG,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

    hero = hero_section()

    def _apply_art(path):
        if path and os.path.isfile(path):
            state["art"] = path
            try:
                page.run_task(lambda: _repaint_hero())
            except Exception:
                _repaint_hero()

    def _repaint_hero():
        try:
            new_hero = hero_section()
            hero.content = new_hero.content
            hero.height = new_hero.height
            thread_safe_refresh(page, hero)
        except Exception:
            pass

    _start_art_fetch(state["version"], _apply_art)

    def version_card(vid: str) -> ft.Control:
        selected = state["version"] == vid

        def pick(e):
            state["version"] = vid
            state["art"] = None
            _start_art_fetch(vid, _apply_art)
            _rebuild()

        return ft.Container(
            content=ft.Column(
                [
                    ft.Text(vid, size=15, weight=ft.FontWeight.W_600,
                            color=TEXT if selected else TEXT_DIM),
                    ft.Text("Release", size=11, color=TEXT_FAINT),
                ],
                spacing=2, horizontal_alignment=ft.CrossAxisAlignment.START,
            ),
            padding=ft.padding.Padding(14),
            bgcolor=SURFACE_HI if selected else SURFACE,
            border=ft.border.Border.all(
                2 if selected else 1, ACCENT if selected else BORDER),
            border_radius=R,
            on_click=pick,
            ink=True,
        )

    def play_tab() -> ft.Control:
        return ft.Column(
            [
                hero,
                ft.Container(height=16),
                ft.Row(
                    [
                        ft.Text("JUMP BACK IN", size=12, color=TEXT_FAINT,
                                weight=ft.FontWeight.W_700),
                    ],
                ),
                ft.Container(height=8),
                ft.Row(
                    [version_card(v) for v in VERSIONS[:4]],
                    spacing=10, wrap=True, run_spacing=10,
                ),
                ft.Row(
                    [version_card(v) for v in VERSIONS[4:]],
                    spacing=10, wrap=True, run_spacing=10,
                ),
                ft.Container(height=18),
                ft.Row(
                    [
                        ft.Column(
                            [
                                ft.Text("USERNAME", size=11, color=TEXT_FAINT,
                                        weight=ft.FontWeight.W_700),
                                ft.Container(height=4),
                                ft.TextField(
                                    value="Player", height=46, bgcolor=SURFACE_HI,
                                    border_color=BORDER, focused_border_color=ACCENT,
                                    color=TEXT, border_radius=R,
                                    content_padding=ft.padding.Padding.symmetric(
                                        horizontal=12, vertical=10),
                                ),
                            ],
                            expand=True,
                        ),
                        ft.Container(width=12),
                        ft.Column(
                            [
                                ft.Text("LOADER", size=11, color=TEXT_FAINT,
                                        weight=ft.FontWeight.W_700),
                                ft.Container(height=4),
                                ft.Row(
                                    [
                                        ft.Container(
                                            content=ft.Text(x, size=12,
                                                            color=ACCENT_HI if x == "Vanilla"
                                                            else TEXT_DIM),
                                            padding=ft.padding.Padding.symmetric(
                                                horizontal=14, vertical=10),
                                            bgcolor=SURFACE_HI,
                                            border=ft.border.Border.all(
                                                1, ACCENT if x == "Vanilla" else BORDER),
                                            border_radius=999,
                                        )
                                        for x in ("Vanilla", "Fabric", "Quilt",
                                                  "Forge", "NeoForge")
                                    ],
                                    spacing=8, wrap=True, run_spacing=8,
                                ),
                            ],
                            expand=True,
                        ),
                    ],
                    vertical_alignment=ft.CrossAxisAlignment.END,
                ),
                ft.Container(height=18),
                ft.Container(
                    content=ft.Row(
                        [
                            ft.Icon(ft.Icons.PLAY_ARROW_ROUNDED, color=ON_ACCENT, size=22),
                            ft.Text("PLAY", size=15, color=ON_ACCENT,
                                    weight=ft.FontWeight.W_700),
                        ],
                        alignment=ft.MainAxisAlignment.CENTER,
                        spacing=8,
                    ),
                    height=52,
                    bgcolor=ACCENT,
                    border_radius=R,
                    on_click=lambda e: None,
                    ink=True,
                ),
            ],
            spacing=0,
            scroll=ft.ScrollMode.AUTO,
            expand=True,
        )

    def mods_tab() -> ft.Control:
        return ft.Column(
            [
                ft.Text("Popular mods", size=20, color=TEXT, font_family=FONT_DISPLAY),
                ft.Container(height=4),
                ft.Text("Fabric ecosystem - one click install", size=12, color=TEXT_DIM),
                ft.Container(height=14),
                ft.Row(
                    [
                        ft.Container(
                            content=ft.Row(
                                [
                                    ft.Container(
                                        width=44, height=44, bgcolor=SURFACE_HI,
                                        border_radius=R,
                                        content=ft.Icon(
                                            ft.Icons.EXTENSION_ROUNDED,
                                            color=TEXT_FAINT, size=22),
                                    ),
                                    ft.Column(
                                        [
                                            ft.Text(name, size=14, color=TEXT,
                                                    weight=ft.FontWeight.W_600),
                                            ft.Text(f"{cat} - {dl} downloads",
                                                    size=11, color=TEXT_FAINT),
                                        ],
                                        spacing=2,
                                    ),
                                    ft.Container(expand=True),
                                    ft.Container(
                                        content=ft.Text("Add", size=12, color=ACCENT_HI,
                                                        weight=ft.FontWeight.W_600),
                                        border=ft.border.Border.all(1, BORDER_HI),
                                        border_radius=999,
                                        padding=ft.padding.Padding.symmetric(
                                            horizontal=12, vertical=6),
                                    ),
                                ],
                                spacing=12,
                                vertical_alignment=ft.CrossAxisAlignment.CENTER,
                            ),
                            bgcolor=SURFACE, border=ft.border.Border.all(1, BORDER),
                            border_radius=R, padding=ft.padding.Padding(12),
                            expand=True,
                        )
                        for name, cat, dl in MODCARDS
                    ],
                    wrap=True, run_spacing=10,
                ),
            ],
            scroll=ft.ScrollMode.AUTO,
            expand=True,
            spacing=0,
        )

    def stub_tab(title: str, subtitle: str) -> ft.Control:
        return ft.Column(
            [
                ft.Text(title, size=20, color=TEXT, font_family=FONT_DISPLAY),
                ft.Container(height=4),
                ft.Text(subtitle, size=12, color=TEXT_DIM),
            ],
            spacing=0, expand=True,
        )

    TAB_BUILDERS = {
        "play": play_tab,
        "mods": mods_tab,
        "modpacks": lambda: stub_tab("Modpacks", "Browse and install modpacks."),
        "servers": lambda: stub_tab("Servers", "Host a Paper server for friends."),
        "profile": lambda: stub_tab("Profile", "Skins, capes and your name."),
        "settings": lambda: stub_tab("Settings", "Java, RAM, backups."),
    }

    def _rebuild():
        content_host.content = ft.Container(
            content=TAB_BUILDERS[state["tab"]](),
            padding=ft.padding.Padding.only(left=28, right=28, top=20, bottom=24),
            expand=True,
        )
        for key, btn in nav_buttons.items():
            _style_nav(btn, key == state["tab"])
        page.update()

    nav_buttons: dict[str, ft.Container] = {}

    def _style_nav(btn: ft.Container, active: bool):
        btn.bgcolor = SURFACE_HI if active else None
        for c in btn.content.controls:
            c.color = ACCENT if active else TEXT_DIM

    def nav_button(key: str, label: str, icon: str) -> ft.Control:
        txt = ft.Text(label, size=13, color=TEXT_DIM, weight=ft.FontWeight.W_600)
        ic = ft.Icon(icon, size=18, color=TEXT_DIM)
        btn = ft.Container(
            content=ft.Row([ic, txt], spacing=10),
            padding=ft.padding.Padding.symmetric(horizontal=14, vertical=10),
            border_radius=R,
            on_click=lambda e, k=key: (state.__setitem__("tab", k), _rebuild()),
            ink=True,
        )
        nav_buttons[key] = btn
        return btn

    brand = ft.Row(
        [
            ft.Image(src="cube.svg", width=26, height=26, fit=ft.BoxFit.CONTAIN),
            ft.Text("Cubeon", size=16, color=TEXT, font_family=FONT_DISPLAY),
        ],
        spacing=10,
    )

    # TOP BAR layout - the core difference from the real UI's sidebar rail
    topbar = ft.Container(
        content=ft.Row(
            [brand] + [nav_button(*item) for item in NAV_ITEMS],
            spacing=6,
            vertical_alignment=ft.CrossAxisAlignment.CENTER,
        ),
        padding=ft.padding.Padding.only(left=20, right=20, top=12, bottom=12),
    )

    content_host = ft.Container(expand=True)

    page.add(
        ft.Container(
            content=ft.Column(
                [topbar, ft.Divider(height=1, color=BORDER), content_host],
                spacing=0, expand=True,
            ),
            expand=True,
        )
    )

    _rebuild()
    return page


def thread_safe_refresh(page, ctrl):
    try:
        from cubeon import thread_safe_ui
        thread_safe_ui.refresh(ctrl)
    except Exception:
        try:
            ctrl.update()
        except Exception:
            pass


def run(palette_name: str = "green"):
    import flet as ft
    ft.run(lambda page: build_app(page, palette_name),
           assets_dir=os.path.join(os.path.dirname(os.path.abspath(__file__)), "..",
                                   "assets"))
