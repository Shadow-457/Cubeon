"""A retained hue/saturation wheel and launcher preview for Appearance."""
import colorsys
import math
import re

import flet as ft

from cubeon import config, i18n, thread_safe_ui
from cubeon.color_templates import CUSTOM_PALETTE_KEY, custom_palette, normalize_custom_palette
from cubeon.theme import FONT_BODY, RADIUS, RADIUS_LG, THEME
from templates.color_green import PALETTE


def seed_color(hue, saturation, value):
    rgb = colorsys.hsv_to_rgb(hue % 1, max(0, min(1, saturation)), max(0, min(1, value)))
    return '#' + ''.join(f'{round(channel * 255):02X}' for channel in rgb)


def wheel_position(x, y, size, previous_hue=0):
    """Match the clockwise native sweep and clamp drags to the wheel edge."""
    dx, dy = x - size / 2, y - size / 2
    distance = math.hypot(dx, dy)
    hue = math.atan2(dy, dx) / math.tau % 1 if distance > .001 else previous_hue
    return hue, min(1, distance / (size / 2))


class ColorStudio:
    """Keep the existing appearance integration and saved palette recipe."""

    def __init__(self, page, cfg, *, on_restart, set_status, assets_dir=None, version=None):
        self.page, self.cfg = page, cfg
        self.on_restart, self.set_status = on_restart, set_status
        self.recipe = normalize_custom_palette(cfg.get(CUSTOM_PALETTE_KEY))
        self.saved = self.recipe.copy() if self.recipe else None
        seed = (self.recipe or {}).get('seed', PALETTE['ACCENT'])
        self.hsv = colorsys.rgb_to_hsv(*(int(seed[i:i+2], 16) / 255 for i in (1, 3, 5)))
        self.size = 224.
        self.message = ft.Text(i18n.t('Choose a color. Save and restart to apply it.'),
                               size=11.5, color=THEME['TEXT_DIM'], data='color-studio-status')
        self.marker = ft.Container(width=20, height=20, border_radius=10,
            border=ft.border.Border.all(3, '#FFFFFF'),
            shadow=ft.BoxShadow(blur_radius=5, color='#99000000'),
            ignore_interactions=True, data='color-wheel-marker')
        self.shade = ft.Container(bgcolor='#000000', opacity=0,
                                 left=0, top=0, right=0, bottom=0, ignore_interactions=True)
        self.field = ft.Container(ft.GestureDetector(
            ft.Stack([
                ft.Container(gradient=ft.SweepGradient(colors=[
                    '#FF0000', '#FFFF00', '#00FF00', '#00FFFF', '#0000FF', '#FF00FF', '#FF0000']),
                    left=0, top=0, right=0, bottom=0),
                ft.Container(gradient=ft.RadialGradient(colors=['#FFFFFF', '#00FFFFFF'], radius=.5),
                    left=0, top=0, right=0, bottom=0, ignore_interactions=True),
                self.shade, self.marker,
            ], fit=ft.StackFit.EXPAND),
            on_tap_down=self._point, on_pan_start=self._point, on_pan_update=self._point,
            drag_interval=32, mouse_cursor=ft.MouseCursor.PRECISE, data='color-wheel'),
            width=self.size, height=self.size, border_radius=self.size / 2,
            clip_behavior=ft.ClipBehavior.ANTI_ALIAS)
        self.wheel_slot = ft.Container(self.field, height=self.size,
            alignment=ft.Alignment.CENTER, on_size_change=self._resized, size_change_interval=100)
        self.sample_label = ft.Text(size=11, font_family=FONT_BODY, rtl=False)
        self.preview_title = ft.Text('Cubeon', size=13, weight=ft.FontWeight.W_600)
        self.preview_hint = ft.Text(i18n.t('Ready to play'), size=11)
        self.preview_game_text = ft.Text('Minecraft', size=24, weight=ft.FontWeight.W_700)
        self.preview_play_text = ft.Text('PLAY', size=14, weight=ft.FontWeight.W_700)
        self.preview_play = ft.Container(ft.Stack([
            ft.Image(src='pixel_button_frame.svg', fit=ft.BoxFit.FILL,
                     left=0, top=0, right=0, bottom=0, exclude_from_semantics=True),
            ft.Container(self.preview_play_text, alignment=ft.Alignment.CENTER,
                         left=0, top=0, right=0, bottom=0),
        ], fit=ft.StackFit.EXPAND), height=40,
                                         border_radius=RADIUS, alignment=ft.Alignment.CENTER)
        self.preview_chip_text = ft.Text(i18n.t('Survival'), size=10)
        self.preview_chip = ft.Container(self.preview_chip_text, border_radius=6,
                                         padding=ft.padding.Padding.symmetric(horizontal=8, vertical=4))
        self.preview_card = ft.Container(
            ft.Column([ft.Row([self.preview_chip, ft.Container(expand=True),
                               ft.Icon(ft.Icons.SPORTS_ESPORTS_ROUNDED, size=20)], spacing=8),
                       self.preview_game_text,
                       self.preview_hint, ft.Container(height=4), self.preview_play], spacing=10),
            padding=18, border_radius=RADIUS_LG)
        self.preview_icons = [ft.Icon(glyph, size=18) for glyph in (
            ft.Icons.PLAY_ARROW_ROUNDED, ft.Icons.EXTENSION_ROUNDED, ft.Icons.PALETTE_ROUNDED)]
        self.preview_rail = ft.Container(
            ft.Column([ft.Image(src='cube.svg', width=22, height=22),
                       ft.Container(height=12),
                       *self.preview_icons],
                      spacing=14, horizontal_alignment=ft.CrossAxisAlignment.CENTER),
            width=48, padding=12, border_radius=RADIUS)
        self.preview = ft.Container(
            ft.Column([ft.Row([self.preview_title, ft.Container(expand=True),
                               ft.Text(i18n.t('LIVE PREVIEW'), size=9, color=THEME['TEXT_DIM'])]),
                       ft.Row([self.preview_rail, ft.Container(self.preview_card, expand=True)],
                              spacing=12, vertical_alignment=ft.CrossAxisAlignment.START),
                       self.sample_label], spacing=12),
            height=254, padding=16, border_radius=RADIUS_LG, data='color-studio-preview')
        self.brightness = ft.Slider(value=self.hsv[2] * 100, min=0, max=100, divisions=100,
            label='{value}%', on_change=self._brightness, data='color-wheel-brightness')
        self.hex_field = ft.TextField(label=i18n.t('Color'), prefix=ft.Text('#'), value=seed[1:],
            width=132, height=48, dense=True, max_length=6, counter='',
            on_submit=self._hex_changed, on_blur=self._hex_changed, data='color-wheel-hex')
        self.save = ft.FilledButton(i18n.t('Save color'), on_click=self._save, data='color-studio-save')
        self.restart = ft.TextButton(i18n.t('Restart to apply'), on_click=on_restart,
                                    visible=False, data='color-studio-restart')
        self.restore = ft.TextButton(i18n.t('Original green'), on_click=self._restore,
                                    data='color-studio-original')
        selector = ft.Column([self.wheel_slot,
            ft.Row([ft.Text(i18n.t('Brightness'), size=12, color=THEME['TEXT_DIM']),
                    ft.Container(self.brightness, expand=True)], spacing=8),
            ft.Container(self.hex_field, alignment=ft.Alignment.CENTER)], spacing=10)
        self.control = ft.Container(ft.Column([
            ft.Text(i18n.t('Launcher color'), size=18, color=THEME['TEXT'], weight=ft.FontWeight.W_600),
            ft.ResponsiveRow([ft.Container(selector, col={'xs': 12, 'wide': 6}),
                              ft.Container(self.preview, col={'xs': 12, 'wide': 6})],
                             breakpoints={'xs': 0, 'wide': 600}, spacing=20, run_spacing=16),
            ft.Row([self.save, self.restore, self.restart], wrap=True, spacing=8), self.message,
        ], spacing=14), padding=16, border_radius=RADIUS_LG,
            bgcolor=THEME['SURFACE_HI'], data='color-studio')
        self._paint(repaint=False)

    def _move_marker(self):
        hue, saturation, _ = self.hsv
        radius = self.size / 2
        # Keep the complete marker inside the circular clipping boundary.
        reach = max(0, radius - 11) * saturation
        self.marker.left = radius + reach * math.cos(hue * math.tau) - 10
        self.marker.top = radius + reach * math.sin(hue * math.tau) - 10

    def _paint(self, *, repaint=True):
        palette = custom_palette(self.recipe) if self.recipe else PALETTE
        self.preview.bgcolor = palette['BG']
        self.preview.border = ft.border.Border.all(1, palette['BORDER_HI'])
        self.preview_rail.bgcolor = palette['SURFACE_HI']
        for index, icon in enumerate(self.preview_icons):
            icon.color = palette['ACCENT'] if index == 0 else palette['TEXT_DIM']
        self.preview_card.bgcolor = palette['SURFACE']
        self.preview_card.border = ft.border.Border.all(1, palette['BORDER'])
        self.preview_title.color = palette['TEXT']
        self.preview_game_text.color = palette['TEXT']
        self.preview_hint.color = palette['TEXT_DIM']
        self.preview_play.bgcolor = palette['ACCENT']
        self.preview_play_text.color = palette['ON_ACCENT']
        self.preview_chip.bgcolor = palette['ACCENT_DEEP']
        self.preview_chip_text.color = palette['ACCENT']
        self.sample_label.value = (f"{i18n.t('Accent')} {palette['ACCENT']}"
                                   if self.recipe else i18n.t('Original Cubeon green'))
        self.sample_label.color = palette['TEXT_DIM']
        self.marker.bgcolor = seed_color(*self.hsv)
        self.brightness.active_color = palette['ACCENT']
        self.shade.opacity = 1 - self.hsv[2]
        self.hex_field.value = seed_color(*self.hsv)[1:]
        self.brightness.value = self.hsv[2] * 100
        self.save.disabled = self.recipe == self.saved
        self._move_marker()
        if repaint:
            for control in (self.preview, self.marker, self.shade, self.brightness, self.hex_field, self.save):
                thread_safe_ui.refresh(control)

    def _changed(self):
        previous = self.recipe or {}
        self.recipe = normalize_custom_palette(dict(seed=seed_color(*self.hsv),
            depth=previous.get('depth', .5), vividness=previous.get('vividness', .5)))
        self.hex_field.error = None
        self.restart.visible = False
        self.message.value = i18n.t('Preview only. Save color when you are ready.')
        self._paint()
        thread_safe_ui.refresh(self.message)
        thread_safe_ui.refresh(self.restart)

    def _point(self, event):
        ft.context.disable_auto_update()
        position = event.local_position
        if not all(math.isfinite(value) for value in (position.x, position.y)):
            return
        with thread_safe_ui.TREE_LOCK:
            hue, saturation = wheel_position(position.x, position.y, self.size, self.hsv[0])
            self.hsv = hue, saturation, self.hsv[2]
            self._changed()

    def _brightness(self, event):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            self.hsv = self.hsv[0], self.hsv[1], self.brightness.value / 100
            self._changed()

    def _hex_changed(self, event=None):
        ft.context.disable_auto_update()
        value = str(self.hex_field.value or '').strip().removeprefix('#')
        with thread_safe_ui.TREE_LOCK:
            if not re.fullmatch(r'[0-9a-fA-F]{6}', value):
                self.hex_field.error = i18n.t('Use six hex digits.')
                thread_safe_ui.refresh(self.hex_field)
                return False
            if '#' + value.upper() != seed_color(*self.hsv):
                self.hsv = colorsys.rgb_to_hsv(*(int(value[i:i+2], 16) / 255 for i in (0, 2, 4)))
                self._changed()
            else:
                self.hex_field.error = None
                thread_safe_ui.refresh(self.hex_field)
            return True

    def _resized(self, event):
        ft.context.disable_auto_update()
        if not event.width or not math.isfinite(event.width):
            return
        with thread_safe_ui.TREE_LOCK:
            size = min(224., max(100., event.width))
            if abs(size - self.size) < 1:
                return
            self.size = size
            self.field.width = self.field.height = self.wheel_slot.height = size
            self.field.border_radius = size / 2
            self._move_marker()
            thread_safe_ui.refresh(self.wheel_slot)

    def _restore(self, event=None):
        ft.context.disable_auto_update()
        with thread_safe_ui.TREE_LOCK:
            self.recipe = None
            seed = PALETTE['ACCENT']
            self.hsv = colorsys.rgb_to_hsv(*(int(seed[i:i+2], 16) / 255 for i in (1, 3, 5)))
            self.restart.visible = False
            self.message.value = i18n.t('Original green is ready to save.' if self.saved else 'Original Cubeon green')
            self._paint()
            thread_safe_ui.refresh(self.message)
            thread_safe_ui.refresh(self.restart)

    def _save(self, event=None):
        ft.context.disable_auto_update()
        if not self._hex_changed():
            return
        with thread_safe_ui.TREE_LOCK:
            existed, previous = CUSTOM_PALETTE_KEY in self.cfg, self.cfg.get(CUSTOM_PALETTE_KEY)
            self.cfg[CUSTOM_PALETTE_KEY] = self.recipe.copy() if self.recipe else None
            try:
                config.save_config(self.cfg)
            except Exception:
                if existed:
                    self.cfg[CUSTOM_PALETTE_KEY] = previous
                else:
                    self.cfg.pop(CUSTOM_PALETTE_KEY, None)
                self.message.value = i18n.t("Couldn't save your look. Try again.")
            else:
                self.saved = self.recipe.copy() if self.recipe else None
                self.restart.visible = True
                self.message.value = i18n.t('Look saved. Restart the launcher to apply it.')
                self.set_status(self.message.value)
            self._paint()
            thread_safe_ui.refresh(self.message)
            thread_safe_ui.refresh(self.restart)
