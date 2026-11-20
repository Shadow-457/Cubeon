"""Artwork-led setup with a validated player name and a guarded save."""
from __future__ import annotations

import threading

import flet as ft

from cubeon import thread_safe_ui
from cubeon.theme import ACCENT, BG, FONT_BODY, FONT_DISPLAY, ON_ACCENT, RADIUS, TEXT, TEXT_DIM

STEP_COUNT = 3
FADE_MS = 180
RETIRE_MS = 220


def _field_error(field, message):
    if hasattr(field, 'error'):
        field.error = message
    else:
        field.error_text = message


def _has_field_error(field) -> bool:
    return bool(getattr(field, 'error', None) or getattr(field, 'error_text', None))


def _title(text, size=40):
    return ft.Text(text, size=size, color='#F4F5EF', font_family=FONT_DISPLAY,
                   style=ft.TextStyle(height=1.3))


def _caption(text):
    return ft.Text(text, size=9, color=TEXT_DIM, font_family=FONT_BODY)


def build_onboarding(page, *, initial_name: str, friends_on: bool,
                     backdrop=None, validate_name, on_finish) -> ft.Container:
    """The caller mounts/reveals the overlay and owns saving the valid name.

    Both callbacks return (ok, error). Only a successful on_finish dismisses
    setup. The reference's Java Edition artwork stays fixed across steps.
    friends_on/backdrop remain accepted for existing startup/replay callers.
    """
    state = {'index': 0, 'busy': False, 'done': False}
    name_field = ft.TextField(
        value=(initial_name or '').strip(), label='Player name', hint_text='Steve',
        helper='3–16 letters, numbers, or underscores.',
        border_color=ft.Colors.with_opacity(.3, TEXT_DIM), focused_border_color=ACCENT,
        bgcolor=ft.Colors.with_opacity(.86, BG), color=TEXT,
        text_style=ft.TextStyle(size=13, font_family=FONT_BODY),
        label_style=ft.TextStyle(size=11, font_family=FONT_BODY),
        helper_style=ft.TextStyle(size=9, font_family=FONT_BODY),
        content_padding=ft.Padding(14, 16, 14, 16), border_radius=RADIUS,
        autocorrect=False, enable_suggestions=False,
        on_submit=lambda e: _next(), data='onboarding-name',
    )
    summary_name = ft.Text(name_field.value or 'Steve', size=14, color=TEXT,
                           font_family=FONT_BODY, max_lines=1,
                           overflow=ft.TextOverflow.ELLIPSIS)
    welcome = ft.Column([
        _caption('WELCOME'),
        _title('Welcome\nto Cubeon.'),
        ft.Text('Set your player name, then choose a Minecraft version.',
                size=11, color=TEXT_DIM, width=380, font_family=FONT_BODY),
    ], spacing=20, tight=True, alignment=ft.MainAxisAlignment.CENTER)
    player = ft.Column([
        _caption('PLAYER NAME'),
        _title('Your name\nin Minecraft.', 30),
        ft.Text('This is the name other players will see.', size=11, color=TEXT_DIM,
                font_family=FONT_BODY),
        name_field,
        ft.Text('You can change it later in Settings → Account.', size=10, color=TEXT_DIM,
                font_family=FONT_BODY),
    ], spacing=18, tight=True, alignment=ft.MainAxisAlignment.CENTER,
        horizontal_alignment=ft.CrossAxisAlignment.STRETCH)
    ready = ft.Column([
        _caption('START'),
        _title('Ready to play.', 32),
        ft.Text('Open New instance on the Play tab to choose a version.',
                size=11, color=TEXT_DIM, width=380, font_family=FONT_BODY),
        ft.Row([
            summary_name,
            ft.TextButton('Edit name', on_click=lambda e: _go(1),
                          style=ft.ButtonStyle(color=TEXT_DIM,
                                              text_style=ft.TextStyle(font_family=FONT_BODY, size=10))),
        ], spacing=14),
    ], spacing=22, tight=True, alignment=ft.MainAxisAlignment.CENTER)
    views = [welcome, player, ready]
    switcher = ft.AnimatedSwitcher(
        content=views[0], transition=ft.AnimatedSwitcherTransition.FADE,
        duration=FADE_MS, reverse_duration=FADE_MS,
        switch_in_curve=ft.AnimationCurve.EASE_OUT,
        switch_out_curve=ft.AnimationCurve.EASE_IN, data='onboarding-step',
    )
    numbers, labels, dots = [], [], []
    progress = []
    for i, title in enumerate(('Welcome', 'Player name', 'Start')):
        number = ft.Container(ft.Text(str(i + 1), size=9, color=TEXT_DIM, font_family=FONT_BODY),
                              width=24, height=24, border_radius=7,
                              alignment=ft.Alignment.CENTER,
                              bgcolor=ft.Colors.with_opacity(.55, BG))
        label = ft.Text(title, size=10, color=TEXT_DIM, font_family=FONT_BODY)
        numbers.append(number)
        labels.append(label)
        progress.append(ft.Row([number, label], spacing=8, tight=True))
        dots.append(ft.Container(width=6, height=6, border_radius=3,
                                 bgcolor=ft.Colors.with_opacity(.35, TEXT_DIM),
                                 animate=ft.Animation(FADE_MS)))
    skip_btn = ft.TextButton('Skip', data='onboarding-skip',
                             style=ft.ButtonStyle(color=TEXT_DIM, text_style=ft.TextStyle(font_family=FONT_BODY, size=10)))
    back_btn = ft.TextButton('Back', visible=False, data='onboarding-back',
                             style=ft.ButtonStyle(color=TEXT_DIM, text_style=ft.TextStyle(font_family=FONT_BODY, size=10)))
    next_btn = ft.FilledButton(
        'Continue', icon=ft.Icons.ARROW_FORWARD_ROUNDED, width=178, height=46,
        data='onboarding-next',
        style=ft.ButtonStyle(color=ON_ACCENT, bgcolor=ACCENT,
                             shape=ft.RoundedRectangleBorder(radius=RADIUS),
                             text_style=ft.TextStyle(size=11, font_family=FONT_BODY)),
    )
    footer = ft.Row([
        ft.Container(back_btn, width=178, alignment=ft.Alignment.BOTTOM_LEFT),
        ft.Container(ft.Row(dots, spacing=7, tight=True), expand=True,
                     alignment=ft.Alignment.BOTTOM_CENTER, padding=ft.Padding(0, 0, 0, 18)),
        next_btn,
    ], vertical_alignment=ft.CrossAxisAlignment.END)
    layout = ft.Container(
        left=0, top=0, right=0, bottom=0, padding=ft.Padding(40, 12, 40, 40),
        content=ft.Column([
            ft.Row([ft.Row(progress, spacing=20, tight=True),
                    ft.Container(expand=True), skip_btn],
                   vertical_alignment=ft.CrossAxisAlignment.CENTER),
            ft.Column([
                ft.Container(switcher, width=420, height=340,
                             alignment=ft.Alignment.CENTER_LEFT),
            ], expand=True, scroll=ft.ScrollMode.AUTO,
                alignment=ft.MainAxisAlignment.CENTER),
            footer,
        ], spacing=8, expand=True),
    )
    overlay = ft.Container(
        left=0, top=0, right=0, bottom=0, bgcolor=BG,
        visible=True, opacity=0, ink=False,
        on_click=lambda e: None,
        animate_opacity=ft.Animation(FADE_MS, ft.AnimationCurve.EASE_OUT),
        content=ft.Stack([
            ft.Container(left=0, top=0, right=0, bottom=0,
                         image=ft.DecorationImage(src='version-art/java-edition.webp',
                                                  fit=ft.BoxFit.COVER)),
            ft.Container(left=0, top=0, right=0, bottom=0,
                         gradient=ft.LinearGradient(
                             begin=ft.Alignment.CENTER_LEFT, end=ft.Alignment.CENTER_RIGHT,
                             colors=[ft.Colors.with_opacity(.86, BG),
                                     ft.Colors.with_opacity(.65, BG),
                                     ft.Colors.with_opacity(.10, BG),
                                     ft.Colors.with_opacity(.24, BG)],
                             stops=[0, .24, .62, 1])),
            layout,
        ], expand=True), data='onboarding',
    )

    def _sync():
        current = state['index']
        for i, (number, label, dot) in enumerate(zip(numbers, labels, dots)):
            active = i == current
            number.bgcolor = ACCENT if active else ft.Colors.with_opacity(.55, BG)
            number.content.color = ON_ACCENT if active else TEXT_DIM
            label.color = TEXT if active else TEXT_DIM
            dot.width = 24 if active else 6
            dot.bgcolor = ACCENT if active else ft.Colors.with_opacity(.35, TEXT_DIM)
            for control in (number, label, dot):
                thread_safe_ui.refresh(control)
        back_btn.visible = current > 0
        skip_btn.visible = current < STEP_COUNT - 1
        next_btn.content = 'Open launcher' if current == STEP_COUNT - 1 else 'Continue'
        for control in (back_btn, skip_btn, next_btn):
            thread_safe_ui.refresh(control)

    def _go(index):
        with thread_safe_ui.TREE_LOCK:
            if state['busy'] or state['done']:
                return
            state['index'] = max(0, min(index, STEP_COUNT - 1))
            summary_name.value = (name_field.value or '').strip() or 'Steve'
            switcher.content = views[state['index']]
            thread_safe_ui.refresh(switcher)
            _sync()
        if state['index'] == 1:
            try:
                page.run_task(name_field.focus)
            except Exception:
                pass

    def _name_changed(e=None):
        with thread_safe_ui.TREE_LOCK:
            if _has_field_error(name_field):
                _field_error(name_field, None)
                thread_safe_ui.refresh(name_field)
    name_field.on_change = _name_changed

    def _finish():
        with thread_safe_ui.TREE_LOCK:
            if state['busy'] or state['done']:
                return
            name = (name_field.value or '').strip()
        ok, err = validate_name(name)
        if not ok:
            _go(1)
            with thread_safe_ui.TREE_LOCK:
                _field_error(name_field, err or 'Please check your player name.')
                thread_safe_ui.refresh(name_field)
            return
        with thread_safe_ui.TREE_LOCK:
            if state['busy'] or state['done']:
                return
            state['busy'] = True
            next_btn.disabled = skip_btn.disabled = back_btn.disabled = True
            next_btn.content = 'Saving…'
            thread_safe_ui.refresh(next_btn)
        try:
            ok, err = on_finish(name)
        finally:
            with thread_safe_ui.TREE_LOCK:
                state['busy'] = False
                next_btn.disabled = skip_btn.disabled = back_btn.disabled = False
                _sync()
        if not ok:
            _go(1)
            with thread_safe_ui.TREE_LOCK:
                _field_error(name_field, err or "Couldn't save setup. Try again.")
                thread_safe_ui.refresh(name_field)
            return
        with thread_safe_ui.TREE_LOCK:
            state['done'] = True
            overlay.opacity = 0
            thread_safe_ui.refresh(overlay)
        def retire():
            with thread_safe_ui.TREE_LOCK:
                if state['done'] and overlay.opacity == 0:
                    overlay.visible = False
                    thread_safe_ui.refresh(overlay)
        timer = threading.Timer(RETIRE_MS / 1000, retire)
        timer.daemon = True
        timer.start()

    def _next(e=None):
        if state['busy'] or state['done']:
            return
        if state['index'] == 1:
            ok, err = validate_name((name_field.value or '').strip())
            if not ok:
                with thread_safe_ui.TREE_LOCK:
                    _field_error(name_field, err)
                    thread_safe_ui.refresh(name_field)
                return
        if state['index'] == STEP_COUNT - 1:
            _finish()
        else:
            _go(state['index'] + 1)

    def _skip(e=None):
        value = (name_field.value or '').strip()
        if not validate_name(value)[0]:
            value = (initial_name or '').strip()
            if not validate_name(value)[0]:
                value = 'Steve'
            with thread_safe_ui.TREE_LOCK:
                name_field.value = value
        _finish()

    next_btn.on_click = _next
    back_btn.on_click = lambda e: _go(state['index'] - 1)
    skip_btn.on_click = _skip
    _sync()
    return overlay
