"""
Dialog + snackbar plumbing that works across the Flet versions this repo has
been developed against (0.86 desktop, and older wheels if anyone runs them).

Flet 0.86 REMOVED Page.open()/Page.close() and introduced Page.show_dialog()
/ Page.pop_dialog() (dialogs live in a managed stack, page._dialogs). The
launcher's old helpers fell back to a pre-0.28 branch (page.dialog + overlay
append) that 0.86 silently ignores - dialogs opened but never closed, and
snackbars never showed at all. One shared implementation, used by main.py
and every ui/ tab builder, so it can never drift again.
"""
import flet as ft


def open_dialog(page: ft.Page, dlg: ft.DialogControl) -> None:
    """Mount a dialog (AlertDialog / SnackBar / bottom sheet) on the page."""
    if hasattr(page, "show_dialog"):
        page.show_dialog(dlg)
    elif hasattr(page, "open"):
        page.open(dlg)
    else:
        # Pre-0.28 flet: no stack, just a property + overlay mount.
        dlg.open = True
        page.dialog = dlg
        if dlg not in page.overlay:
            page.overlay.append(dlg)
        page.update()


def close_dialog(page: ft.Page, dlg: ft.DialogControl) -> None:
    """Dismiss a specific dialog. pop_dialog() closes the TOP of the stack;
    when ours isn't top (a second dialog sits above it) flip its open flag
    directly - same visible effect without disturbing the stack order."""
    if hasattr(page, "pop_dialog"):
        stack = list(getattr(getattr(page, "_dialogs", None), "controls", [])
                     or [])
        if dlg in stack:
            if dlg is stack[-1]:
                page.pop_dialog()
            else:
                dlg.open = False
                try:
                    dlg.update()
                except Exception:
                    page.update()
            return
        # Not in the managed stack (opened via an older API): fall through.
    if hasattr(page, "close"):
        page.close(dlg)
    else:
        dlg.open = False
        page.update()


def show_snack(page: ft.Page, message: str, *, duration: int = 4000,
               action=None, action_label: str = None,
               bgcolor=None, text_color=None) -> None:
    """A toast. Best-effort: a missed toast must never break its caller.

    `action` (callable) renders as a labelled button next to the text.
    """
    try:
        content = ft.Text(message, size=13,
                          color=text_color if text_color is not None else None,
                          expand=action is not None)
        row_items = [content]
        if action is not None:
            row_items.append(ft.TextButton(
                action_label or "OK", on_click=lambda e: action(),
                style=ft.ButtonStyle(color=text_color)))
        snack = ft.SnackBar(ft.Row(row_items), duration=duration)
        if bgcolor is not None:
            snack.bgcolor = bgcolor
        open_dialog(page, snack)
    except Exception:
        pass
