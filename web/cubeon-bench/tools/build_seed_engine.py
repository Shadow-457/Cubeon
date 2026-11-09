#!/usr/bin/env python3
"""Rebuild Bench's bundled MIT Cubiomes WebAssembly, without global SDK setup."""
import argparse
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PIN = 'e61f90580cbdd883214a8054670dacae655e59c0'


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cubiomes', type=Path, default=ROOT / 'tools/.work/cubiomes')
    parser.add_argument('--emcc', type=Path, default=ROOT / 'tools/.work/emsdk/upstream/emscripten/emcc')
    args = parser.parse_args()
    actual = subprocess.check_output(['git', '-C', str(args.cubiomes), 'rev-parse', 'HEAD'], text=True).strip()
    if actual != PIN:
        raise SystemExit(f'Use the reviewed Cubiomes revision {PIN}; found {actual}')
    sources = ['generator.c', 'layers.c', 'biomes.c', 'biomenoise.c', 'noise.c', 'finders.c', 'util.c']
    command = [str(args.emcc), '-O3', '-I', str(args.cubiomes), str(ROOT / 'tools/seed-engine.c')]
    command += [str(args.cubiomes / source) for source in sources]
    command += ['-lm', '-sMODULARIZE=1', '-sEXPORT_NAME=CubeonSeedEngine', '-sENVIRONMENT=worker,node', '-sALLOW_MEMORY_GROWTH=1',
                '-sFILESYSTEM=0', '-sEXPORTED_FUNCTIONS=["_cb_init","_cb_map","_cb_markers","_cb_count","_cb_biome_name","_cb_biome_color"]',
                '-sEXPORTED_RUNTIME_METHODS=["UTF8ToString","HEAP32"]', '-o', str(ROOT / 'vendor/cubiomes.js')]
    subprocess.run(command, cwd=ROOT, check=True)
    (ROOT / 'vendor/cubiomes.LICENSE').write_text((args.cubiomes / 'LICENSE').read_text())
    print('Built Cubeon seed engine from', PIN)


if __name__ == '__main__':
    main()
