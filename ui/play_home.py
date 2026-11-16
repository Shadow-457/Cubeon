"""Artwork-led Play screen with retained header and compact launch footer."""
import flet as ft

from cubeon import thread_safe_ui
from cubeon.theme import FONT_BODY, TEXT_DIM


class PlayHome:
    def __init__(self, page, *, hero, title, action, version, account, actions,
                 fps, progress):
        self.page = page
        self.title = title
        self.action = action
        self.hero_content = hero
        self.actions = actions
        self._geometry = None
        self.version = self._field("VERSION", version)
        self.account = self._field("USERNAME", account)
        self.fields = ft.Row([self.version, self.account], spacing=16)
        self.action_row = ft.Row(
            [self.fields, action], spacing=16,
            vertical_alignment=ft.CrossAxisAlignment.END,
        )
        self.fps = fps
        self.progress_slot = ft.Container(progress, height=94)
        self.footer = ft.Column(
            [self.action_row, fps, self.progress_slot], spacing=12,
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.hero_area = ft.Container(expand=True, data="play-art-space")
        self.header_row = ft.Row(
            [ft.Container(hero, expand=True), actions], spacing=20,
            vertical_alignment=ft.CrossAxisAlignment.START,
        )
        self.header = ft.Column([self.header_row], spacing=12,
                                horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
        self.body = ft.Column(
            [self.header, self.hero_area, self.footer], spacing=16,
            expand=True, data="play-body",
            horizontal_alignment=ft.CrossAxisAlignment.STRETCH,
        )
        self.host = ft.Container(self.body, padding=24)
        self.root = ft.Stack([
            # A broad bottom scrim leaves the central artwork clear.
            ft.Container(left=0, top=0, right=0, bottom=0,
                         gradient=ft.LinearGradient(
                             begin=ft.Alignment.TOP_CENTER,
                             end=ft.Alignment.BOTTOM_CENTER,
                             colors=["#000A0D0B", "#100A0D0B", "#600A0D0B",
                                     "#D90A0D0B", "#F20A0D0B"],
                             stops=[0, .35, .60, .85, 1]),
                         ignore_interactions=True),
            ft.Container(left=0, top=0, right=0, height=180,
                         gradient=ft.LinearGradient(
                             begin=ft.Alignment.TOP_CENTER,
                             end=ft.Alignment.BOTTOM_CENTER,
                             colors=["#66000000", "#00000000"]),
                         ignore_interactions=True),
            ft.Container(self.host, left=0, top=0, right=0, bottom=0),
        ], expand=True, fit=ft.StackFit.EXPAND,
            on_size_change=lambda e: self.fit(e.width, e.height), size_change_interval=100)

    @staticmethod
    def _field(label, control):
        return ft.Container(
            ft.Column([
                ft.Text(label, size=10, color=TEXT_DIM, font_family=FONT_BODY,
                        weight=ft.FontWeight.W_600),
                control,
            ], spacing=8, horizontal_alignment=ft.CrossAxisAlignment.STRETCH),
            expand=True,
        )

    def fit(self, width, height, repaint=True):
        ft.context.disable_auto_update()
        # Hidden native windows can report the 1x1 bootstrap viewport.
        if width < 160 or height < 160:
            return
        geometry = (round(width), round(height))
        if geometry == self._geometry:
            return
        with thread_safe_ui.TREE_LOCK:
            self._geometry = geometry
            compact = width < 900 or height < 560
            narrow = width < 520
            padding = 16 if compact else 24
            available = max(1, width - padding * 2)
            self.host.padding = padding
            self.title.size = 26 if narrow else 36 if compact else 44
            self.hero_area.expand = None if compact else True
            self.hero_area.height = 32 if compact else None
            self.body.scroll = ft.ScrollMode.AUTO if compact else None
            header = [self.hero_content, self.actions] if narrow else [self.header_row]
            if self.header.controls != header:
                self.header.controls = header
            self.version.expand = self.account.expand = not narrow
            self.fields.expand = not compact
            if narrow:
                launch = [self.version, self.account, self.action]
            elif compact:
                launch = [self.fields, self.action]
            else:
                launch = [self.action_row]
            footer = [*launch, self.fps, self.progress_slot]
            if self.footer.controls != footer:
                self.footer.controls = footer
            # Keyboard targets copy artwork dimensions at construction.
            # Resize the wrapper and original button together.
            button_width = min(300, available)
            self.action.width = self.action.content.width = button_width
            self.action.content.controls[0].width = button_width
        if repaint:
            thread_safe_ui.refresh(self.host)
