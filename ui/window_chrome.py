"""The custom window frame's WIDGETS (Windows-only; policy in cubeon/winchrome.py).

main.py decides WHEN the custom frame is used (`winchrome.custom_chrome_enabled`);
this module builds WHAT it is made of:

  * `build_window_controls` - the min / maximize / close cluster that replaces
    the OS title-bar buttons the frameless window drops.
  * `set_maximized_glyph`   - swap maximize <-> restore after a maximize event.
  * `build_resize_edges`    - the eight invisible hot-zones over the window's
    border, each wired to `Window.start_resizing`.

WHY THE RESIZE EDGES ARE OURS
`window_manager`'s `setAsFrameless` rebuilds the native window style, so the OS
resize border can be gone once the frame is dropped - and `resizable = True` is
a no-op on the flet side when it is already the default (the Prop descriptor
never sends an unchanged value, see flet's `value_types.Prop.__set__`). The hot
zones make resizing work either way instead of depending on what the plugin's
Windows implementation kept.

Kept here, not in main.py, for the same reason every other tab builder is: this
is reachable code that the headless smoke test can actually BUILD and inspect
(see tools/test_ui_smoke.py), whereas anything inline in main()'s window-chrome
branch would only ever run on real Windows.
"""
import flet as ft

from cubeon import winchrome

__all__ = [
    "build_window_controls",
    "set_maximized_glyph",
    "build_resize_edges",
    "set_resize_edges_visible",
]

# Map winchrome's plain value strings ("topLeft") back onto the enum flet's
# Window.start_resizing expects. Built once; an unknown value is skipped rather
# than raising, so a future edit to RESIZE_EDGES can never kill startup.
_RESIZE_BY_VALUE = {e.value: e for e in ft.WindowResizeEdge}

# Icons for the maximize button's two states. CROP_SQUARE is the empty box
# (maximize); FILTER_NONE is the offset double box (restore down) - Flutter's
# nearest equivalents of the Windows glyphs.
_GLYPH_MAXIMIZE = ft.Icons.CROP_SQUARE
_GLYPH_RESTORE = ft.Icons.FILTER_NONE


def _title_bar_button(icon, tooltip, on_click, *, hover_bg, hover_fg,
                      TEXT_DIM):
    """One square title-bar button on the Cubeon palette.

    Deliberately square and flush: these live in the window's top-right corner,
    where the app's rounded-radius system would look clipped. The hover wash is
    the only affordance - a title-bar button should be discoverable, not loud.
    """
    return ft.IconButton(
        icon=icon,
        icon_size=15,
        icon_color=TEXT_DIM,
        tooltip=tooltip,
        on_click=on_click,
        alignment=ft.Alignment.CENTER,
        # Material gives an IconButton a 48x48 minimum; a title-bar button is
        # shorter than that, and without clearing the floor `height` is ignored.
        size_constraints=ft.BoxConstraints(min_width=0, min_height=0),
        height=30,
        style=ft.ButtonStyle(
            shape=ft.RoundedRectangleBorder(radius=0),
            padding=ft.padding.Padding.symmetric(horizontal=12),
            bgcolor={ft.ControlState.HOVERED: hover_bg},
            color={ft.ControlState.HOVERED: hover_fg},
            # The theme's green overlay would tint the red close wash.
            overlay_color=ft.Colors.TRANSPARENT,
        ),
    )


def build_window_controls(*, on_minimize, on_maximize, on_close,
                          TEXT_DIM, TEXT, SURFACE_HI, DANGER, ON_DANGER):
    """Build the title-bar button cluster.

    Returns a dict: ``{"row", "minimize", "maximize", "close"}``. The row is
    what main.py mounts at the right edge of the top bar; the named buttons are
    kept so the window-event handler can flip the maximize glyph in place
    (rebuilding the row would re-send the whole top bar on every maximize).

    Handlers must be CHEAP: they run on flet's event loop, and a hang there
    freezes `ft.run()` itself (the "launcher alive with no window" bug).
    Minimize/close in particular must only schedule work - `Window.close()` is
    a coroutine on this build.
    """
    minimize = _title_bar_button(
        ft.Icons.REMOVE, "Minimize", on_minimize,
        hover_bg=SURFACE_HI, hover_fg=TEXT, TEXT_DIM=TEXT_DIM)
    maximize = _title_bar_button(
        _GLYPH_MAXIMIZE, "Maximize", on_maximize,
        hover_bg=SURFACE_HI, hover_fg=TEXT, TEXT_DIM=TEXT_DIM)
    close = _title_bar_button(
        ft.Icons.CLOSE, "Close", on_close,
        hover_bg=DANGER, hover_fg=ON_DANGER, TEXT_DIM=TEXT_DIM)
    row = ft.Row(
        [minimize, maximize, close],
        spacing=0,
        vertical_alignment=ft.CrossAxisAlignment.CENTER,
    )
    return {"row": row, "minimize": minimize, "maximize": maximize,
            "close": close}


def set_maximized_glyph(controls, maximized):
    """Point the maximize button at the state the window is now in.

    Never raises: a missing/odd control just means nothing to restyle, and this
    runs off a native window event.
    """
    try:
        btn = controls.get("maximize")
    except Exception:
        return controls
    if btn is None:
        return controls
    btn.icon = _GLYPH_RESTORE if maximized else _GLYPH_MAXIMIZE
    btn.tooltip = "Restore" if maximized else "Maximize"
    return controls


def build_resize_edges(on_resize):
    """The eight invisible resize hot-zones, in winchrome.RESIZE_EDGES order.

    ``on_resize(edge)`` receives an `ft.WindowResizeEdge`. The caller schedules
    `Window.start_resizing` with it - the native resize loop takes the mouse
    over from there, which is what makes a frameless window still feel native.
    """
    edges = []
    for spec in winchrome.RESIZE_EDGES:
        edge = _RESIZE_BY_VALUE.get(spec.get("edge"))
        if edge is None:
            continue  # unknown edge name: skip rather than break the frame
        cursor = getattr(ft.MouseCursor, spec.get("cursor", ""),
                         ft.MouseCursor.BASIC)
        pos = {k: spec[k] for k in ("left", "top", "right", "bottom",
                                    "width", "height") if k in spec}
        edges.append(ft.GestureDetector(
            mouse_cursor=cursor,
            on_pan_start=(lambda e, edge=edge: on_resize(edge)),
            **pos,
        ))
    return edges


def set_resize_edges_visible(edges, visible):
    """Show/hide the hot-zones. A maximized window cannot be resized, and a
    stale handle there would swallow clicks meant for the UI underneath."""
    for e in edges or ():
        try:
            e.visible = bool(visible)
        except Exception:
            pass  # a decoration must never break the frame it decorates
    return edges
