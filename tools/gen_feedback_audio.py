"""Generate Cubeon's quiet, short local UI cues using only the standard library."""
import math
from pathlib import Path
import struct
import wave

folder = Path(__file__).resolve().parents[1] / 'assets' / 'feedback'
folder.mkdir(exist_ok=True)
rate = 22050
for name, notes in {'launch': (523.25, 659.25), 'error': (392.0, 329.63)}.items():
    frames = bytearray()
    for freq in notes:
        length = int(rate * 0.10)
        for i in range(length):
            envelope = math.sin(math.pi * i / length) ** 2
            sample = 0.045 * envelope * math.sin(2 * math.pi * freq * i / rate)
            frames.extend(struct.pack('<h', int(sample * 32767)))
    with wave.open(str(folder / (name + '.wav')), 'wb') as out:
        out.setparams((1, 2, rate, 0, 'NONE', 'not compressed'))
        out.writeframes(frames)
