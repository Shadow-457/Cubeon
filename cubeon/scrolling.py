"""Short client-side animations for app-driven scrolling, not wheel interception."""
import flet as ft
import re

from cubeon import motion

SCROLL_MS = 180
SCROLL_CURVE = ft.AnimationCurve.EASE_OUT_CUBIC


def animation():
    return ft.Animation(SCROLL_MS if motion.transforms() else 0, SCROLL_CURVE)


def _scroll(page, control, offset):
    scroll_animation = animation()

    async def scroll():
        # Cached tabs can be hidden or detached between scheduling and execution.
        ancestor = control
        while ancestor is not page:
            if ancestor is None or getattr(ancestor, "visible", True) is False:
                return
            ancestor = ancestor.parent
        try:
            await control.scroll_to(offset=offset, duration=scroll_animation.duration,
                                    curve=scroll_animation.curve)
        except RuntimeError as error:
            message = str(error)
            # A disappearing viewport can lose its native method listener. Own
            # that task's completion so Flet doesn't re-raise the timeout later.
            if message == "Session closed" or message == (
                    f"{type(control).__qualname__}({control._i}) "
                    "Control must be added to the page first"):
                return
            if re.fullmatch(
                    r"TimeoutException after [\d:.]+: Timeout waiting for invoke "
                    r"method listener for " + re.escape(f"{type(control).__qualname__}({control._i}).scroll_to"),
                    message):
                return
            raise

    return page.run_task(scroll)


def follow_end(page, control):
    return _scroll(page, control, -1)


def to_top(page, control):
    """Reset changed search/page results with one native animated command."""
    return _scroll(page, control, 0)


def to_offset(page, control, offset):
    """Reveal a retained navigation item with the same bounded native scroll."""
    return _scroll(page, control, max(0, offset))
