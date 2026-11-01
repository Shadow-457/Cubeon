"""Exercise Play's real orchestration with held workers and simulated exits."""
import inspect
import os
from pathlib import Path
import sys
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__), os.path.dirname(os.path.dirname(__file__))]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common as fz
import app_driver
from cubeon import thread_safe_ui, version_art, versions, watchdog


def callback(controls, name):
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
    raise AssertionError(name)


stubs = fz.install_safe_stubs()
version_art.prefetch = lambda base, ready: ready(None)
installed = [{'id': '1.20.1', 'type': 'release'}, {'id': '1.21.11', 'type': 'release'}]
stubs.core.get_installed_versions = lambda: [dict(v) for v in installed]
page = app_driver.DriverPage()
stubs.app.run_sync(page)
controls = list(fz.every_control(page))
begin = callback(controls, '_begin_install_and_launch')
on_play = callback(controls, 'on_play_click')
delete = callback(controls, 'on_delete_instance')
scope = inspect.getclosurevars(begin).nonlocals
play_scope = inspect.getclosurevars(on_play).nonlocals
state = scope['state']
worker_scope = inspect.getclosurevars(scope['do_install_and_launch']).nonlocals
select = callback(controls, '_pick_version')
jobs = []
liveness_jobs = []
deny_liveness = False

# Renamed-instance art uses the recorded game version, reuses in-flight work,
# and cannot overwrite the artwork of a later selection.
renamed = Path(versions.version_folder('Survival 2.0'))
renamed.mkdir(parents=True)
(renamed / '_cubeon_instance.json').write_text('{"mc_version":"1.21.11"}')
refresh_banner = callback(controls, '_refresh_hero_banner')
banner = inspect.getclosurevars(refresh_banner).nonlocals['hero_art']
requests, lookups = [], []
with patch.object(version_art, 'src', side_effect=lambda base: lookups.append(base)), \
        patch.object(version_art, 'has_official', return_value=False), \
        patch.object(version_art, 'prefetch', side_effect=lambda base, ready: requests.append((base, ready))):
    refresh_banner('Survival 2.0')
    refresh_banner('Survival 2.0')
    assert lookups == ['1.21.11', '1.21.11'] and len(requests) == 1
    refresh_banner('1.20.1')
    requests[0][1]('stale-art')
    assert banner.source != 'stale-art'
    requests[1][1]('current-art')
    assert banner.source == 'current-art'


class HeldThread:
    def __init__(self, target, args=(), name=None, **kw):
        self.target, self.args, self.name = target, args, name
    def start(self):
        if self.name == 'running-liveness':
            liveness_jobs.append(self.target)
            if deny_liveness:
                raise RuntimeError('fixture: optional watcher thread unavailable')
        if self.name == 'delete-instance' or (inspect.isfunction(self.target) and
                'do_install_and_launch' in inspect.getclosurevars(self.target).nonlocals):
            jobs.append(lambda: self.target(*self.args))


def reset():
    state.update(installing_version=None, launching_version=None, running_version=None)
    state['mod_loader'] = 'vanilla'
    select('1.20.1', 'vanilla')
    play_scope['username_field'].value = 'AuditPilot'


with patch('main.threading.Thread', HeldThread), \
        patch.object(watchdog, 'stale_session', return_value=None), \
        patch.object(stubs.core, 'pack_install_for_instance', return_value=None):
    reset()
    with patch.object(stubs.core.jre, 'java_status') as java:
        assert on_play() is True
        java.assert_not_called()  # expensive preflight is off the click path
    assert len(jobs) == 1
    observed = {}
    def failed_setup(*args, **kwargs):
        observed.update(launching=state.get('launching_version'), running=state.get('running_version'))
        assert begin('1.21.11', 'AuditPilot') is False
        raise RuntimeError('fixture: setup failed before spawn')
    with patch.object(stubs.core, 'launch_game', failed_setup):
        jobs.pop()()
    assert observed == {'launching': '1.20.1', 'running': None}
    assert not state.get('launching_version') and not state.get('running_version')

    reset()
    exits = []
    def immediate_exit(*args, **kwargs):
        exits.append(kwargs['on_exit'])
        kwargs['on_exit'](3, ['fixture: early crash'], 'early')
        return SimpleNamespace(session_id='early')
    with patch.object(stubs.core, 'launch_game', immediate_exit):
        begin('1.20.1', 'AuditPilot')
        jobs.pop()()
    assert not state.get('running_version') and scope['progress_stage'].value != 'RUNNING'

    reset()
    def live_game(*args, **kwargs):
        exits.append(kwargs['on_exit'])
        return SimpleNamespace(session_id='live')
    with patch.object(stubs.core, 'launch_game', live_game), \
            patch.object(stubs.app._rpc, 'set_activity', side_effect=RuntimeError('Discord absent')):
        begin('1.20.1', 'AuditPilot')
        deny_liveness = True
        jobs.pop()()
        deny_liveness = False
    assert state['running_version'] == '1.20.1' and scope['progress_stage'].value == 'RUNNING'
    assert len(liveness_jobs) == 1
    previous_watch = worker_scope['_running_liveness']['stop']
    assert begin('1.21.11', 'AuditPilot') is False
    def failed_playtime_end(**kwargs):
        assert not thread_safe_ui.TREE_LOCK._is_owned(), 'playtime I/O held the UI lock'
        raise RuntimeError('playtime fixture unavailable')
    with patch.object(stubs.core, 'milestones_end_play_session', failed_playtime_end):
        exits[-1](0, [], 'live')
    assert not state.get('running_version')
    assert previous_watch.is_set(), 'exit must wake its liveness watcher immediately'

    reset()
    with patch.object(stubs.core.jre, 'java_status', return_value={'ok': False, 'required': 21, 'found': None}), \
            patch.object(stubs.core, 'launch_game') as spawn:
        begin('1.20.1', 'AuditPilot')
        jobs.pop()()
        spawn.assert_not_called()
    assert not state.get('installing_version') and page.opened
    page.close(page.opened[-1])

    # A healthy installed loader remains playable when its online catalogue is down.
    fabric = 'fabric-loader-0.19.5-1.20.1'
    installed.append({'id': fabric, 'type': 'release'})
    state.update(installing_version=None, launching_version=None, running_version=None)
    callback(controls, '_rescan_installed')()
    select(fabric)
    with patch.object(stubs.core, 'is_loader_supported', side_effect=RuntimeError('offline')) as support, \
            patch.object(stubs.core, 'launch_game', live_game):
        begin(fabric, 'AuditPilot')
        jobs.pop()()
        support.assert_not_called()
    assert state['running_version'] == fabric
    assert len(liveness_jobs) == 2, 'a rapid relaunch needs its own liveness watcher'
    new_watch = worker_scope['_running_liveness']['stop']
    assert new_watch is not previous_watch and not new_watch.is_set()
    # If the normal exit callback is lost, the new watcher still self-heals.
    with patch.object(new_watch, 'wait', return_value=False):
        liveness_jobs[-1]()
    assert not state.get('running_version')
    exits[-1](0, [], 'live')

    reset()
    with patch.object(stubs.core, 'dependents_of', return_value=['fabric-loader-0.19.5-1.20.1']), \
            patch.object(stubs.core, 'private_profile_for_deletion', return_value=None), \
            patch.object(stubs.core, 'delete_version') as erase:
        delete(vid='1.20.1')
        dialog = page.opened[-1]
        state['launching_version'] = 'fabric-loader-0.19.5-1.20.1'
        dialog.actions[-1].on_click(None)
        erase.assert_not_called()
        assert not jobs
        state['launching_version'] = None
        with patch.object(stubs.core, 'pack_install_for_instance', side_effect=RuntimeError('registry unreadable')):
            before = len(page.opened)
            delete(vid='1.20.1')
            assert len(page.opened) == before
    with patch.object(stubs.core, 'dependents_of', return_value=[]), \
            patch.object(stubs.core, 'private_profile_for_deletion', return_value=None):
        deleted = []
        def erase(version):
            assert not thread_safe_ui.TREE_LOCK._is_owned(), 'recursive deletion held the UI lock'
            deleted.append(version)
            installed[:] = [v for v in installed if v['id'] != version]
        with patch.object(stubs.core, 'delete_version', erase):
            delete(vid='1.20.1')
            dialog = page.opened[-1]
            dialog.actions[-1].on_click(None)
            assert not deleted and len(jobs) == 1
            assert begin('1.21.11', 'AuditPilot') is False
            jobs.pop()()
            assert set(deleted) == {'1.20.1', fabric}, 'base deletion must cascade its loader'
            assert not scope['_deleting_versions']

print('PASS: asynchronous Java, spawn/exit claims, relaunch liveness, renamed/stale art, safe background deletion')
