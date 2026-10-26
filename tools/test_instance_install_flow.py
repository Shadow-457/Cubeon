"""Offline regressions for install ownership, selection and cancellation."""
import inspect
import os
import sys
from unittest.mock import patch
sys.path[:0] = [os.path.dirname(__file__), os.path.dirname(os.path.dirname(__file__))]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common as fz
import app_driver
from cubeon import thread_safe_ui

passed = failed = 0

def check(label, condition):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}")


def function_from_controls(controls, name):
    seen = set()
    def visit(fn):
        if not inspect.isfunction(fn) or id(fn) in seen:
            return None
        seen.add(id(fn))
        if fn.__name__ == name:
            return fn
        for value in inspect.getclosurevars(fn).nonlocals.values():
            found = visit(value)
            if found:
                return found
    for control in controls:
        found = visit(getattr(control, 'on_click', None))
        if found:
            return found
    raise AssertionError(f"Missing callback {name}")

stubs = fz.install_safe_stubs()
installed = [{'id': '1.20.1', 'type': 'release'}]
stubs.core.get_installed_versions = lambda: list(installed)
page = app_driver.DriverPage()
stubs.app.run_sync(page)
controls = list(fz.every_control(page))
begin = function_from_controls(controls, '_begin_install_and_launch')
scope = inspect.getclosurevars(begin).nonlocals
worker = inspect.getclosurevars(scope['do_install_and_launch']).nonlocals
state = scope['state']
jobs = []

class DeferredThread:
    def __init__(self, target, args=(), **kwargs):
        self.target = target
        self.run = lambda: target(*args)
    def start(self):
        # Snackbars and loader-support notices also start short workers.
        # Only defer the install worker; those UI helpers own no install slot.
        target = self.target
        if inspect.isfunction(target) and 'do_install_and_launch' in inspect.getclosurevars(target).nonlocals:
            jobs.append(self.run)

# A selection has no authority to write/download game files.
select = function_from_controls(controls, '_pick_version')
with patch.object(stubs.core, 'install_version') as install:
    select('1.21.11', 'fabric')
    check('selecting an online version downloads nothing', install.call_count == 0)

with patch('main.threading.Thread', DeferredThread):
    begin('1.21.11', 'tester')
    begin('1.20.1', 'tester')
    check('the shared card refuses a second simultaneous install', len(jobs) == 1)
    scope['_cancel_event']('1.21.11').set()
    jobs.pop(0)()
check('an immediate cancel survives until the worker starts',
      scope['progress_stage'].value == 'CANCELLED' and state['installing_version'] is None)
check('cancel returns a usable main button',
      not scope['progress_bar'].visible and not scope['progress_spinner'].visible)

# The loader choice belongs to the attempt, even if selection changes while
# the worker is waiting to run. Stop in the fake loader, before any spawn.
loader_calls = []
def install_base(version, progress, status, maximum, **kwargs):
    maximum(10)
    progress(5)
    installed.append({'id': version, 'type': 'release'})

def cancelled_loader(loader, mc, progress, status, maximum, **kwargs):
    loader_calls.append((loader, mc))
    kwargs['cancel_event'].set()
    raise RuntimeError('fixture: cancelled during loader download')

with patch.object(stubs.core, 'install_version', install_base), \
     patch.object(stubs.core, 'install_mod_loader', cancelled_loader), \
     patch.object(stubs.core, 'is_loader_supported', return_value=True), \
     patch.object(stubs.core, 'delete_version') as delete, \
     patch('main.threading.Thread', DeferredThread):
    state['mod_loader'] = 'fabric'
    begin('1.21.11', 'tester')
    state['mod_loader'] = 'forge'
    jobs.pop(0)()
    check('changing selection cannot change the loader being installed',
          loader_calls == [('fabric', '1.21.11')])
    check('loader cancellation keeps the verified base version',
          '1.21.11' in state['installed'] and delete.call_count == 0)
    check('loader cancellation releases the install claim',
          state['installing_version'] is None and scope['progress_stage'].value == 'CANCELLED')

scope['progress_bar'].visible = True
scope['set_bar'](None)
scope['set_bar'](0)
check('a new phase can leave an indeterminate bar at real zero', scope['progress_bar'].value == 0)
scope['set_bar'](.5, instant=True)
scope['set_bar'](None)
check('a new unmeasured phase hides the previous percentage',
      scope['progress_bar'].value is None and not worker['progress_percent'].visible)

# Reopening the welcome tour never needs a config reset.
replay = next(c for c in fz.every_control(page) if getattr(c, 'content', None) == 'Open tour')
before = len(page.overlay)
replay.on_click(None)
check('Settings can reopen onboarding', len(page.overlay) >= before and page.overlay[-1].opacity == 1)
print(f'\n{passed} passed, {failed} failed')
sys.exit(1 if failed else 0)
