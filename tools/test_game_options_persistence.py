"""Real boost transitions: relaunches retain player settings and recover originals."""
import json
import os
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
sys.path[:0] = [str(Path(__file__).resolve().parent), str(Path(__file__).resolve().parents[1])]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import game_options as go, perf_mods

with tempfile.TemporaryDirectory() as directory:
    path = Path(directory) / 'options.txt'
    original = ('renderDistance:18\nsimulationDistance:10\ngraphicsPreset:"custom"\n'
                'particles:1\nao:true\nenableVsync:true\nmaxFps:144\nresourcePacks:["custom"]\n')
    path.write_text(original)
    assert go.sync_fps_boost(False, str(path))['changed'] == []
    assert path.read_text() == original
    first = go.sync_fps_boost(True, str(path))
    assert first['changed'] and 'renderDistance' not in first['changed']
    boosted = path.read_text()
    assert 'renderDistance:18' in boosted and 'simulationDistance:10' in boosted
    edited = boosted.replace('renderDistance:18', 'renderDistance:22').replace('particles:2', 'particles:0')
    path.write_text(edited)
    assert go.sync_fps_boost(True, str(path))['changed'] == []
    assert path.read_text() == edited
    restored = go.sync_fps_boost(False, str(path))
    assert 'graphicsPreset' in restored['changed'] and 'particles' not in restored['changed']
    after = path.read_text()
    assert 'graphicsPreset:"custom"' in after and 'renderDistance:22' in after and 'particles:0' in after
    assert 'enableVsync:true' in after and 'maxFps:144' in after and 'resourcePacks:["custom"]' in after
    assert go.sync_fps_boost(False, str(path))['changed'] == []
    assert go.sync_fps_boost(True, str(path))['changed']
    sibling = Path(directory) / 'sibling-options.txt'
    sibling.write_text(original)
    go.sync_fps_boost(False, str(sibling))
    assert sibling.read_text() == original
    marker = Path(str(path) + '.cubeon-boost.json')
    marker.write_text('{broken')
    before = path.read_bytes()
    assert 'backup is not readable' in go.sync_fps_boost(False, str(path))['detail']
    assert path.read_bytes() == before
    marker.unlink()
    with patch.object(go, 'write_json', side_effect=OSError('read-only backup')):
        assert not go.sync_fps_boost(True, str(path))['changed']
    assert path.read_bytes() == before
    assert not go.sync_fps_boost(True, str(Path(directory) / 'missing.txt'))['changed']
    sodium = Path(directory) / 'sodium-options.json'
    sodium.write_text(json.dumps({'performance': {'chunk_builder_threads': 1, 'use_fog_occlusion': False},
                                  'advanced': {'use_advanced_staging_buffers': False}}))
    sodium_before = sodium.read_bytes()
    assert not perf_mods.apply_max_fps_sodium(str(sodium), preserve_existing=True)['changed']
    assert sodium.read_bytes() == sodium_before
    sodium.unlink()
    assert perf_mods.apply_max_fps_sodium(str(sodium), preserve_existing=True)['changed'] == ['performance.chunk_builder_threads']
    assert json.loads(sodium.read_text()) == {'performance': {'chunk_builder_threads': 2}}
print('PASS: relaunch persistence, selective restore, instance isolation, backup failures, and Sodium workarounds')
