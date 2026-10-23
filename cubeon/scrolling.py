"""Short client-side animations for app-driven scrolling, not wheel interception."""
import flet as ft

from cubeon import motion

SCROLL_MS = 180
SCROLL_CURVE = ft.AnimationCurve.EASE_OUT_CUBIC


def animation():
    return ft.Animation(SCROLL_MS if motion.transforms() else 0, SCROLL_CURVE)


def follow_end(page, control):
    scroll_animation = animation()
    return page.run_task(control.scroll_to, offset=-1,
                         duration=scroll_animation.duration, curve=scroll_animation.curve)
