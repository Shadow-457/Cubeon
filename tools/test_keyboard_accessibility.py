"""Custom keyboard targets, dialogs and Settings preserve action gates."""
import os
import sys
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


switch_tab = closed_over(key, 'switch_tab')
active = closed_over(switch_tab, 'active_tab')
views = closed_over(switch_tab, '_tab_views')
send(',', ctrl=True)
assert active['value'] == 'settings', 'Settings shortcut must navigate to its tab'
assert views['settings'].visible and not views['play'].visible
assert not any(getattr(control, 'visible', False) for control in page.overlay
               if getattr(control, 'content', None) is not None
               and getattr(control.content, 'shadow', None)), 'Settings opened a floating card'
cell.cell_contents = lambda: clicks.append('settings-launch')
try:
    send('Enter', ctrl=True)
    assert 'settings-launch' not in clicks, 'Play shortcut activated while editing Settings'
finally:
    cell.cell_contents = original
settings = closed_over(switch_tab, 'tabs')['settings']
select = closed_over(settings.select_section, '_select_section') if '_select_section' in settings.select_section.__code__.co_freevars else settings.select_section
panes = closed_over(select, 'panes')
assert {'notifications', 'storage', 'seasonal', 'doctor', 'images', 'system'} <= set(panes)
for section in panes:
    settings.select_section(section)
    assert [name for name, pane in panes.items() if pane.visible] == [section]
switch_tab('chat')
assert not views['settings'].visible, 'Settings stayed on top of Chat'
state = closed_over(switch_tab, 'state')
state['chat_composing'] = True
send('!', shift=True)
assert active['value'] == 'chat', 'Typing ! in Chat activated the Shift+1 navigation shortcut'
state['chat_composing'] = False
print('PASS: keyboard targets and modal gates; Settings tab and separate sections')
