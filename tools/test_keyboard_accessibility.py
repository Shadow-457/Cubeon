"""Custom keyboard targets and overlay shortcuts must preserve action gates."""
import os
import sys
import asyncio
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__), os.path.dirname(os.path.dirname(__file__))]
import _sandbox_home
_sandbox_home.isolate()
import flet as ft
import _fuzz_common as fz
from cubeon import seasonal, theme

clicks = []
art = ft.Container(ft.Text('Play'), width=300, height=64,
                   tooltip='Launch Minecraft', on_click=lambda e: clicks.append(e.control))
host = theme.keyboard_target(art, 'Play')
target = host.controls[1]
target.on_click(SimpleNamespace(data=None))
assert clicks == [art], 'keyboard activation must keep the original event control'
art.disabled = True
target.on_click(SimpleNamespace(data=None))
assert clicks == [art], 'native button bypassed a disabled action'
assert host.controls[0] is art and host.width == 300 and host.height == 64
assert target.tooltip == art.tooltip, 'keyboard overlay swallowed the artwork tooltip'
assert target.content.content is not None, 'native Semantics requires a visible child'

stubs = fz.install_safe_stubs()
load = stubs.core.load_config
stubs.core.load_config = lambda: dict(load(), onboarded=True, season_seen=seasonal.current().slug)
page = fz.FakePage()
stubs.app.run_sync(page)
key = page.on_keyboard_event

def send(label, ctrl=False, shift=False):
    key(SimpleNamespace(key=label, ctrl=ctrl, shift=shift, alt=False, meta=False))

send('F1')
assert page.opened, 'shortcut help did not open'
help_dialog = page.opened[-1]
help_dialog.actions[0].on_click(None)
assert help_dialog not in page.opened, 'Close kept the shortcut dialog open'

modal = ft.AlertDialog(modal=True, content=ft.Text('Confirm'))
page.open(modal)
cell = dict(zip(key.__code__.co_freevars, key.__closure__))['_main_action_click']
original = cell.cell_contents
cell.cell_contents = lambda: clicks.append('launch')
try:
    send('Enter', ctrl=True)
    assert 'launch' not in clicks, 'global Play activated behind a dialog'
    send('Escape')
    assert modal not in page.opened, 'Escape failed to close the top dialog'
    send('Enter', ctrl=True)
    assert 'launch' in clicks, 'Play shortcut remained blocked after dismissal'
finally:
    cell.cell_contents = original

def closed_over(fn, name):
    return dict(zip(fn.__code__.co_freevars, fn.__closure__))[name].cell_contents


close_panel = closed_over(key, '_close_account_panel')
open_panel = closed_over(closed_over(key, 'switch_tab'), '_open_account_panel')
panel = closed_over(close_panel, 'account_panel')
scrim = closed_over(close_panel, 'account_scrim')
pending_fades, pending_retire = [], []
run_task = page.run_task
real_timer = stubs.app.threading.Timer


def hold_fade(handler, *args, **kwargs):
    if handler.__name__ == '_fade_account_in':
        pending_fades.append(handler)
        return None
    return run_task(handler, *args, **kwargs)


def hold_retire(delay, handler, *args, **kwargs):
    if handler.__name__ == '_retire_scrim':
        pending_retire.append(handler)
        return SimpleNamespace(start=lambda: None, daemon=False)
    return real_timer(delay, handler, *args, **kwargs)


with patch.object(page, 'run_task', side_effect=hold_fade), \
        patch.object(stubs.app.threading, 'Timer', side_effect=hold_retire):
    send(',', ctrl=True)
    assert panel.visible and pending_fades
    close_panel()
    asyncio.run(pending_fades.pop(0)())
    assert panel.opacity == 0, 'late entrance resurrected a dismissed popup'
    stale_retire = pending_retire.pop(0)
    # Reopening is still opacity 0 until its pending entrance paints.
    open_panel()
    stale_retire()
    assert panel.visible and scrim.visible, 'old close timer hid a reopened popup'
    asyncio.run(pending_fades.pop(0)())
    assert panel.opacity == 1
    close_panel()
    pending_retire.pop(0)()
    assert not panel.visible and not scrim.visible

print('PASS: native targets preserve action gates; modal shortcuts and popup fade races are safe')
