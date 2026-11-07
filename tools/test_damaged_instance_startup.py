"""Build the real launcher after a registered instance's metadata was deleted."""
import inspect
from pathlib import Path
import sys
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
import _fuzz_common as fz
import app_driver
from cubeon import config, mods, paths, storage, versions
from cubeon.atomicio import write_json


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
    raise AssertionError(f'Missing callback {name}')


def main():
    real_profile = mods.get_profile_dir
    stubs = fz.install_safe_stubs()
    mods.get_profile_dir = real_profile
    stubs.core.get_profile_dir = real_profile
    stubs.core.get_installed_versions = versions.get_installed_versions
    storage.initialize()
    damaged, healthy = 'fabric-loader-0.20.1-1.21.11', '1.20.1'
    runtime = Path(storage.runtime_dir())
    for vid in (damaged, healthy):
        folder = runtime / 'versions' / vid
        write_json(str(folder / (vid + '.json')), {'id': vid, 'type': 'release'})
        (folder / (vid + '.jar')).write_bytes(b'PK\x03\x04fixture')
        storage.folder_for(vid, create=True)
    broken_folder = storage.folder_for(damaged)
    metadata = broken_folder / 'instance.json'
    healthy_game = storage.game_dir(healthy)
    paths.set_active_game_dir(storage.game_dir(damaged))
    metadata.unlink()
    before = storage.registry_path().read_bytes()
    cfg = {**config.DEFAULT_CONFIG, 'last_version': damaged, 'username': 'tester',
           'onboarding_done': True, 'auto_organize_files': False}
    page = app_driver.DriverPage()
    with patch.object(stubs.core, 'load_config', return_value=cfg):
        stubs.app.run_sync(page)
    controls = fz.every_control(page)
    select = callback(controls, '_pick_version')
    play = callback(controls, 'on_play_click')
    scope = inspect.getclosurevars(play).nonlocals
    state = scope['state']
    assert state['selected_version'] == damaged
    assert state['installed_meta'][damaged]['incomplete']
    assert scope['version_issue_text'].visible
    assert 'Restore it before playing' in scope['version_issue_text'].value
    with patch.object(stubs.core, 'launch_game') as launch, patch.object(stubs.core, 'install_version') as install:
        assert play() is False
        assert not launch.called and not install.called
        select(healthy)
        assert state['selected_version'] == healthy
        assert not state['installed_meta'][healthy].get('incomplete')
        assert not scope['version_issue_text'].visible
        select(damaged)
        assert play() is False
        assert not launch.called and not install.called
    callback(controls, 'switch_tab')('settings')
    assert any(getattr(c, 'data', None) == 'replay-onboarding' for c in fz.every_control(page))
    assert not metadata.exists()
    assert storage.registry_path().read_bytes() == before
    assert storage.game_dir(healthy) == healthy_game
    assert not (Path(paths.MINECRAFT_DIR) / 'mods').exists()
    print('PASS: startup with deleted metadata, blocked Play, instance switching and Settings; no metadata recreation/shared fallback')


if __name__ == '__main__':
    main()
