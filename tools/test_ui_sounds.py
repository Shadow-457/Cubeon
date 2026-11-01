"""Optional cues must stay silent by default and bound concurrent playback."""
import os
import sys
import wave
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from cubeon import ui_sounds as sound

assets = Path(__file__).resolve().parents[1] / 'assets'
cfg = {'ui_sounds': False}
sound.configure(cfg, str(assets))
with patch.object(sound.threading.Thread, 'start') as start:
    assert not sound.play('launch')
    start.assert_not_called()
    cfg['ui_sounds'] = True
    assert sound.play('launch')
    assert not sound.play('error'), 'a second worker escaped the concurrency limit'
    assert start.call_count == 1
sound._busy = False
with patch.object(sound.time, 'monotonic', return_value=sound._last + 0.1):
    assert not sound.play('error'), 'rapid events escaped the sound cooldown'
cfg['ui_sounds'] = False
assert not sound.play('error')
sound.configure(None, None)
for kind in ('launch', 'error'):
    with wave.open(str(assets / 'feedback' / (kind + '.wav'))) as wav:
        assert wav.getnframes() / wav.getframerate() <= 0.25
        assert wav.getnchannels() == 1 and wav.getsampwidth() == 2
print('PASS: default/off silence, one worker, cooldown, and short bundled cues')
