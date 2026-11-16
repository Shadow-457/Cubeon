"""Retained, black frosted chrome without live backdrop filters."""
import flet as ft

from cubeon import thread_safe_ui, version_art


class ChromeBackdrop:
    def __init__(self, version, width, height):
        self.source = version_art.key_art_blurred_src(version)
        self.width, self.height = width, height
        self.images = []

    def panel(self, content, *, width=None, height=None, top=0):
        artwork = ft.Image(
            src=self.source, width=self.width, height=self.height,
            left=0, top=-top, fit=ft.BoxFit.COVER,
            gapless_playback=True, filter_quality=ft.FilterQuality.LOW,
        )
        self.images.append(artwork)
        return ft.Container(
            ft.Stack([
                artwork,
                ft.Container(left=0, top=0, right=0, bottom=0,
                             bgcolor=ft.Colors.with_opacity(.66, '#000000'),
                             ignore_interactions=True),
                ft.Container(content, left=0, top=0, right=0, bottom=0),
            ], fit=ft.StackFit.EXPAND),
            width=width, height=height,
            clip_behavior=ft.ClipBehavior.HARD_EDGE,
        )

    def set_version(self, version):
        source = version_art.key_art_blurred_src(version)
        if source == self.source:
            return
        with thread_safe_ui.TREE_LOCK:
            self.source = source
            for artwork in self.images:
                artwork.src = source
        for artwork in self.images:
            thread_safe_ui.refresh(artwork)

    def resize(self, width, height):
        if width < 160 or height < 160 or (width, height) == (self.width, self.height):
            return
        with thread_safe_ui.TREE_LOCK:
            self.width, self.height = width, height
            for artwork in self.images:
                artwork.width, artwork.height = width, height
        for artwork in self.images:
            thread_safe_ui.refresh(artwork)
