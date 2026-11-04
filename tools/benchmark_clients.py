#!/usr/bin/env python3
"""Prepare a reversible comparison; launching requires --recording-ready.

Games must be launched with Play in their real launchers. No direct Java launch.
"""
from pathlib import Path
import argparse
import hashlib
import json
import os
import shutil
import statistics
import subprocess
import time
import zipfile
import signal
import sys
import tempfile
from datetime import datetime

REPO = Path(__file__).resolve().parents[1]
SOURCE = REPO / 'tools/benchmark_client_assets'
HOME = Path.home()
WORK = Path('/tmp/cubeon-fastclient-benchmark')
CUBEON = HOME / '.cubeon_minecraft/instances/fabric-loader-0.20.1-26.3'
FAST = HOME / '.fastclient/profiles/26.3-Fabric'
PROFILE = HOME / '.cubeon_launcher/mod_profiles/26.3-fabric'
JAVA = HOME / '.local/share/FastClient/runtimes/java-25/jdk-25.0.4.1+1/bin/java'
WORLD = 'Cubeon FastClient Benchmark'
JAR = 'client-comparison-only.jar'
MISSING = {'comparison_missing': True}


def write_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_name(path.name + '.comparison-tmp')
    temp.write_text(json.dumps(data, indent=2) + '\n')
    temp.replace(path)


def games():
    result = []
    for path in Path('/proc').iterdir():
        if not path.name.isdecimal():
            continue
        try:
            args = (path / 'cmdline').read_bytes().decode().split('\0')
            if '--gameDir' in args:
                result.append({'pid': int(path.name), 'directory': args[args.index('--gameDir') + 1]})
        except (OSError, UnicodeError, ValueError):
            pass
    return result


def no_games():
    found = games()
    if found:
        raise RuntimeError('Close Minecraft before setup/restore: ' + str(found))


def build():
    WORK.mkdir(mode=0o700, parents=True, exist_ok=True)
    classes = WORK / 'classes'
    classes.mkdir(exist_ok=True)
    libs = HOME / '.cubeon_minecraft/libraries'
    # Compiler-only classpath. Real launchers resolve their own exact runtime dependencies.
    cp = os.pathsep.join([str(HOME / '.cubeon_minecraft/versions/26.3/26.3.jar'),
                          *map(str, sorted(libs.rglob('*.jar')))])
    javac = HOME / '.gradle/jdks/eclipse_adoptium-25-amd64-linux.2/bin/javac'
    subprocess.run([str(javac), '--release', '17', '-proc:none', '-cp', cp,
                    '-d', str(classes), str(SOURCE / 'FrameProbe.java')], check=True)
    with zipfile.ZipFile(WORK / JAR, 'w', zipfile.ZIP_DEFLATED) as jar:
        for path in classes.rglob('*.class'):
            jar.write(path, path.relative_to(classes).as_posix())
        jar.writestr('fabric.mod.json', json.dumps({
            'schemaVersion': 1, 'id': 'client_comparison_only', 'version': '1.0.0',
            'name': 'Temporary client comparison', 'environment': 'client',
            'depends': {'minecraft': '26.3', 'fabricloader': '>=0.20.1'},
            'mixins': ['comparison.mixins.json']}))
        jar.writestr('comparison.mixins.json', json.dumps({
            'required': True, 'package': 'comparison', 'compatibilityLevel': 'JAVA_17',
            'client': ['FrameProbe'], 'injectors': {'defaultRequire': 1}}))
    print('Measurement mod compiled; no launcher or game started.')


def patch_json(path, values, journal):
    data = json.loads(path.read_text()) if path.exists() else {}
    original = {key: data.get(key, MISSING) for key in values}
    journal.append({'path': str(path), 'kind': 'json', 'original': original, 'applied': values})
    write_json(WORK / 'journal.json', journal)
    data.update(values)
    write_json(path, data)


def patch_options(path, values, journal):
    lines = path.read_text().splitlines()
    existing = dict(line.split(':', 1) for line in lines if ':' in line)
    journal.append({'path': str(path), 'kind': 'options',
                    'original': {key: existing.get(key, MISSING) for key in values}, 'applied': values})
    write_json(WORK / 'journal.json', journal)
    seen = set()
    output = []
    for line in lines:
        key = line.split(':', 1)[0]
        if key in values:
            if key not in seen:
                output.append(key + ':' + values[key])
            seen.add(key)
        else:
            output.append(line)
    output.extend(key + ':' + value for key, value in values.items() if key not in seen)
    path.write_text('\n'.join(output) + '\n')


def tree_digest(root):
    h = hashlib.sha256()
    for file in sorted(root.rglob('*')):
        if file.is_file() and file.name != 'session.lock':
            h.update(file.relative_to(root).as_posix().encode())
            h.update(file.read_bytes())
    return h.hexdigest()


def prepare():
    no_games()
    if (WORK / 'journal.json').exists():
        raise RuntimeError('Setup already exists; inspect status or restore first.')
    if not (WORK / JAR).exists():
        raise RuntimeError('Run build first.')
    for instance in [CUBEON, FAST]:
        if (instance / 'saves' / WORLD).exists() or (instance / 'config/client-comparison.json').exists():
            raise RuntimeError('Refusing to overwrite an existing comparison fixture.')
    journal = []
    snapshot = WORK / 'world-snapshot'
    shutil.copytree(CUBEON / 'saves/New World', snapshot)
    (snapshot / 'session.lock').unlink(missing_ok=True)
    values = {
        'graphicsPreset': '"fast"', 'particles': '2', 'ao': 'false',
        'entityShadows': 'false', 'entityDistanceScaling': '0.75', 'biomeBlendRadius': '0',
        'syncChunkWrites': 'false', 'renderDistance': '6', 'simulationDistance': '5',
        'mipmapLevels': '2', 'renderClouds': '"fast"', 'enableVsync': 'false', 'maxFps': '260',
        'fullscreen': 'false', 'overrideWidth': '1280', 'overrideHeight': '720',
        'pauseOnLostFocus': 'false', 'inactivityFpsLimit': '"minimized"',
        'fov': '0.0', 'gamma': '0.5', 'guiScale': '3', 'resourcePacks': '[]',
        'tutorialStep': 'none', 'onboardAccessibility': 'false',
    }
    sodium = json.loads((CUBEON / 'config/sodium-options.json').read_text())
    sodium['performance']['chunk_builder_threads'] = 2
    mods = {}
    for label, instance, modfolder in [('cubeon', CUBEON, PROFILE), ('fastclient', FAST, FAST / 'mods')]:
        mods[label] = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                       for p in (instance / 'mods').glob('*.jar')}
        patch_options(instance / 'options.txt', values, journal)
        patch_json(instance / 'config/sodium-options.json', sodium, journal)
        config = instance / 'config/client-comparison.json'
        journal.append({'path': str(config), 'kind': 'created'})
        write_json(WORK / 'journal.json', journal)
        write_json(config, {'output': str(WORK), 'client': label})
        target = instance / 'saves' / WORLD
        journal.append({'path': str(target), 'kind': 'world'})
        write_json(WORK / 'journal.json', journal)
        shutil.copytree(snapshot, target)
        dest = modfolder / JAR
        if dest.exists():
            raise RuntimeError('Refusing to overwrite existing mod ' + str(dest))
        journal.append({'path': str(dest), 'kind': 'created'})
        write_json(WORK / 'journal.json', journal)
        shutil.copy2(WORK / JAR, dest)
        assert tree_digest(target) == tree_digest(snapshot)
    patch_json(HOME / '.cubeon_launcher/config.json',
               {'ram_mb': 4608, 'java_path': str(JAVA), 'width': 1280, 'height': 720}, journal)
    settings = HOME / '.local/share/FastClient/settings.json'
    patch_json(settings, {'gameFullscreen': False, 'gameWindowWidth': 1280,
                         'gameWindowHeight': 720, 'defaultMemory': 4608}, journal)
    profile_file = HOME / '.local/share/FastClient/profiles.json'
    profiles = json.loads(profile_file.read_text())
    for profile in profiles['profiles']:
        if profile['id'] == '26.3-Fabric':
            profile.update({'javaPath': str(JAVA), 'memory': 4608, 'defaultFullscreen': False})
    patch_json(profile_file, {'profiles': profiles['profiles']}, journal)
    iris = FAST / 'config/iris.properties'
    if iris.exists():
        # This properties file must be restored byte-for-byte, unless edited later.
        original = iris.read_text()
        lines = [line for line in original.splitlines() if not line.startswith('enableShaders=')]
        applied = '\n'.join(lines + ['enableShaders=false']) + '\n'
        journal.append({'path': str(iris), 'kind': 'text', 'original': original, 'applied': applied})
        write_json(WORK / 'journal.json', journal)
        iris.write_text(applied)
    report = {'minecraft': '26.3', 'fabric': '0.20.1', 'sodium': '0.9.2',
              'java': str(JAVA), 'max_heap_mb': 4608, 'video_options': values,
              'world_sha256': tree_digest(snapshot), 'mods': mods,
              'measurement': '3 x 30s warmup + 60s slow camera sweep; sequential clients',
              'launchers': {'cubeon': 'source checkout main.py', 'fastclient': 'provided AppImage'},
              'differences': 'Each client retains its installed mods and default JVM tuning.'}
    write_json(WORK / 'setup.json', report)
    print('Prepared both real-launcher profiles with identical copied worlds and settings. Nothing launched.')


def restore():
    no_games()
    journal = json.loads((WORK / 'journal.json').read_text())
    skipped = []
    for entry in reversed(journal):
        path = Path(entry['path'])
        if entry['kind'] == 'world':
            continue  # Keep the separately named recording world; never touch the user's New World.
        if entry['kind'] == 'created':
            path.unlink(missing_ok=True)
        elif entry['kind'] == 'text':
            if path.read_text() == entry['applied']:
                path.write_text(entry['original'])
            else:
                skipped.append(str(path))
        elif entry['kind'] == 'json':
            data = json.loads(path.read_text())
            for key, old in entry['original'].items():
                if data.get(key, MISSING) != entry['applied'][key]:
                    skipped.append(str(path) + ':' + key)
                elif old == MISSING:
                    data.pop(key, None)
                else:
                    data[key] = old
            write_json(path, data)
        elif entry['kind'] == 'options':
            lines = path.read_text().splitlines()
            output = []
            for line in lines:
                key, sep, value = line.partition(':')
                if key in entry['applied'] and value == entry['applied'][key]:
                    old = entry['original'][key]
                    if old != MISSING:
                        output.append(key + ':' + old)
                else:
                    output.append(line)
                    if key in entry['applied']:
                        skipped.append(str(path) + ':' + key)
            path.write_text('\n'.join(output) + '\n')
    # Cubeon's normal mod sync creates one additional staging link.
    staging = CUBEON / 'mods' / JAR
    if staging.is_symlink() and staging.resolve() == (PROFILE / JAR).resolve():
        staging.unlink()
    write_json(WORK / 'restore.json', {'preserved_later_edits': skipped})
    (WORK / 'restored').touch()
    print('Temporary measurement mods removed; settings restored, preserving later edits:', skipped)


def launch(client, ready, desktop_recovery=False):
    if not ready:
        raise RuntimeError('Wait for the user recording-ready signal; pass --recording-ready only then.')
    no_games()
    if not (WORK / 'setup.json').exists():
        raise RuntimeError('Prepare first.')
    env = os.environ.copy()
    for key in ['_JAVA_OPTIONS', 'JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', 'LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER']:
        env.pop(key, None)
    if desktop_recovery and client == 'cubeon':
        env['CUBEON_GPU_RESTARTS'] = '2'
    cmd = [str(REPO / '.venv-build/bin/python'), str(REPO / 'main.py')] if client == 'cubeon' else [str(HOME / 'Downloads/FastClient(1).AppImage')]
    with (WORK / (client + '-launcher.log')).open('w') as output:
        proc = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=output, stderr=subprocess.STDOUT, start_new_session=True)
    (WORK / (client + '-launcher.pid')).write_text(str(proc.pid))
    print('Started actual', client, 'launcher, pid', proc.pid, '; select the installed 26.3 profile and click Play.')


def results():
    output = []
    for file in sorted(WORK.glob('*-[123].csv')):
        validation = file.with_name(file.stem + '-validation.txt').read_text().strip()
        if validation != 'valid':
            output.append({'sample': file.stem, 'excluded': validation})
            continue
        ms = [int(line) / 1e6 for line in file.read_text().splitlines()[1:]]
        ordered = sorted(ms)
        tail_count = max(1, round(len(ms) * .01))
        output.append({'sample': file.stem, 'frames': len(ms), 'seconds': sum(ms) / 1000,
                       'average_fps': 1000 / statistics.mean(ms),
                       'one_percent_low_fps': 1000 / statistics.mean(ordered[-tail_count:]),
                       'p99_frame_ms': ordered[min(len(ms) - 1, int(len(ms) * .99))]})
    write_json(WORK / 'results.json', output)
    print(json.dumps(output, indent=2))


def windows(title=None):
    rows = subprocess.check_output(['wmctrl', '-lpG'], text=True).splitlines()
    output = []
    for row in rows:
        parts = row.split(None, 8)
        if len(parts) < 9:
            continue
        name = parts[8]
        if title and not (name == title or title == 'Minecraft' and name.startswith('Minecraft')):
            continue
        output.append({'id': parts[0], 'pid': int(parts[2]), 'x': int(parts[3]),
                       'y': int(parts[4]), 'width': int(parts[5]), 'height': int(parts[6]), 'title': name})
    return output


def key(window, combo):
    subprocess.run(['xdotool', 'windowactivate', '--sync', window['id']], check=True, timeout=5)
    subprocess.run(['xdotool', 'key', '--clearmodifiers', combo], check=True, timeout=5)


def capture(window, name):
    from PIL import ImageGrab
    subprocess.run(['xdotool', 'windowactivate', '--sync', window['id']], check=True, timeout=5)
    time.sleep(.3)
    ImageGrab.grab(bbox=(window['x'], window['y'], window['x'] + window['width'],
                        window['y'] + window['height'])).save(WORK / name)


def wait_until(check, timeout, description):
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        found = check()
        if found:
            return found
        time.sleep(.5)
    raise RuntimeError('Timed out: ' + description)


def stop_benchmark_games():
    """Close only games using this script's explicitly tagged fixture."""
    for game in games():
        config = Path(game['directory']) / 'config/client-comparison.json'
        if not config.exists() or json.loads(config.read_text()).get('output') != str(WORK):
            raise RuntimeError('Another Minecraft game is running. Close it first.')
        matches = [w for w in windows('Minecraft') if w['pid'] == game['pid']]
        if matches:
            subprocess.run(['wmctrl', '-ic', matches[0]['id']], check=True)
        else:
            os.kill(game['pid'], signal.SIGTERM)
        wait_until(lambda: all(g['pid'] != game['pid'] for g in games()), 25, 'benchmark game exit')


def stop_owned_launchers():
    for client in ['cubeon', 'fastclient']:
        path = WORK / (client + '-launcher.pid')
        if not path.exists():
            continue
        pid = int(path.read_text())
        proc = Path('/proc') / str(pid)
        if not proc.exists():
            continue
        args = (proc / 'cmdline').read_bytes().split(b'\0')
        expected = str(REPO / 'main.py').encode() if client == 'cubeon' else b'FastClient'
        if not any(expected in arg for arg in args):
            continue  # PID was reused.
        for window in windows('Cubeon' if client == 'cubeon' else 'FastClient'):
            subprocess.run(['wmctrl', '-ic', window['id']], check=True)
        try:
            wait_until(lambda: not proc.exists(), 6, client + ' launcher exit')
        except RuntimeError:
            os.kill(pid, signal.SIGTERM)


def automated_launch(client, appimage):
    no_games()
    env = os.environ.copy()
    for name in ['LIBGL_ALWAYS_SOFTWARE', 'GALLIUM_DRIVER', '_JAVA_OPTIONS', 'JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS']:
        env.pop(name, None)
    if client == 'cubeon':
        # Known-working launcher renderer on this Mesa installation. launch_game
        # strips these fallback variables before starting the hardware-rendered JVM.
        env['CUBEON_GPU_RESTARTS'] = '2'
        cmd = [str(REPO / '.venv-build/bin/python'), str(REPO / 'main.py')]
    else:
        cmd = [str(appimage), '--launch-profile', '26.3-Fabric']
    with (WORK / (client + '-launcher.log')).open('w') as log:
        process = subprocess.Popen(cmd, cwd=REPO, env=env, stdout=log, stderr=subprocess.STDOUT, start_new_session=True)
    (WORK / (client + '-launcher.pid')).write_text(str(process.pid))
    if client == 'cubeon':
        win = wait_until(lambda: windows('Cubeon') if (HOME / '.cubeon_launcher/ui_painted_ok').exists() else [],
                         75, 'Cubeon source window paint')[0]
        key(win, 'Escape')  # Dismiss the startup update notice.
        time.sleep(1.5)
        key(win, 'ctrl+Return')  # The real launcher's Play action.
    game = wait_until(lambda: [g for g in games() if g['directory'] == str(CUBEON if client == 'cubeon' else FAST)],
                      75, client + ' Minecraft process')
    return game[0]


def verify_effective(client):
    path = WORK / (client + '-effective-options.txt')
    data = dict(line.split(': ', 1) for line in path.read_text().splitlines() if ': ' in line)
    expected = {'renderDistance': '6', 'simulationDistance': '5', 'particles': 'MINIMAL',
                'biomeBlendRadius': '0', 'enableVsync': 'false', 'maxFps': '260',
                'mipmapLevels': '2', 'renderClouds': 'FAST', 'ao': 'false',
                'entityShadows': 'false', 'graphicsPreset': 'FAST', 'fov': '70'}
    errors = [f'{k}: {data.get(k)} != {v}' for k, v in expected.items() if data.get(k) != v]
    if errors:
        raise RuntimeError('Effective settings mismatch: ' + '; '.join(errors))
    instance = CUBEON if client == 'cubeon' else FAST
    sodium = json.loads((instance / 'config/sodium-options.json').read_text())
    if sodium['performance']['chunk_builder_threads'] != 2:
        raise RuntimeError('Sodium chunk threads are not 2')


def run_client(client, args):
    for file in WORK.glob(client + '-*'):
        if file.is_file() and file.suffix in ['.csv', '.txt']:
            file.unlink()
    config = (CUBEON if client == 'cubeon' else FAST) / 'config/client-comparison.json'
    write_json(config, {'output': str(WORK), 'client': client, 'auto': True,
                        'runs': args.runs, 'warmup': args.warmup, 'duration': args.duration})
    print(f'{client}: launching, showing settings, then {args.runs} samples.', flush=True)
    game = automated_launch(client, args.fastclient)
    status_file = WORK / (client + '-status.txt')
    began = time.monotonic()
    previous = ''
    captured = False
    deadline = began + args.runs * (args.warmup + args.duration) + 150
    last_progress = 0
    while time.monotonic() < deadline:
        if not any(g['pid'] == game['pid'] for g in games()):
            raise RuntimeError(client + ' exited before completing the benchmark')
        status = status_file.read_text().strip() if status_file.exists() else 'starting game'
        if status != previous:
            print(client + ': ' + status, flush=True)
            previous = status
        if 'showing matched video settings' in status and not captured:
            verify_effective(client)
            matches = [w for w in windows('Minecraft') if w['pid'] == game['pid']]
            if matches:
                capture(matches[0], client + '-settings.png')
                captured = True
        if status.startswith('INVALID'):
            raise RuntimeError(client + ': ' + status)
        if status.startswith('complete;'):
            if not captured:
                raise RuntimeError('Settings were not verified/captured')
            for run in range(1, args.runs + 1):
                valid = (WORK / f'{client}-{run}-validation.txt').read_text().strip()
                if valid != 'valid':
                    raise RuntimeError(f'{client} sample {run} invalid: {valid}')
            runtime = (WORK / (client + '-runtime.txt')).read_text()
            if 'Framebuffer 1280x720' not in runtime or 'Max heap 4831838208' not in runtime:
                raise RuntimeError('Runtime resolution or heap mismatch: ' + runtime)
            mods = {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                    for p in (Path(game['directory']) / 'mods').glob('*.jar')}
            write_json(WORK / (client + '-loaded-mods.json'), mods)
            stop_benchmark_games()
            stop_owned_launchers()
            return
        if time.monotonic() - last_progress > 20:
            print(f'{client}: elapsed {time.monotonic() - began:.0f}s', flush=True)
            last_progress = time.monotonic()
        time.sleep(.5)
    raise RuntimeError(client + ' benchmark timed out')


def summary(output):
    data = json.loads((WORK / 'results.json').read_text())
    text = ['# Minecraft 26.3 client benchmark', '',
            '| Client | Average FPS | 1% low FPS | p99 frame time |',
            '|---|---:|---:|---:|']
    means = {}
    for client in ['cubeon', 'fastclient']:
        rows = [r for r in data if r['sample'].startswith(client) and 'excluded' not in r]
        if not rows:
            continue
        means[client] = statistics.mean(r['average_fps'] for r in rows)
        text.append(f"| {client} | {means[client]:.1f} | {statistics.mean(r['one_percent_low_fps'] for r in rows):.1f} | {statistics.mean(r['p99_frame_ms'] for r in rows):.2f} ms |")
    if len(means) == 2:
        delta = (means['cubeon'] / means['fastclient'] - 1) * 100
        text.extend(['', f'Cubeon average FPS relative to FastClient: {delta:+.1f}%.'])
    text.extend(['', 'Same world snapshot, 1280×720, distances 6/5, Fast graphics, VSync off,',
                 'unlimited FPS, two Sodium chunk threads, Java 25 and 4608 MiB maximum heap.',
                 'Each client retains its installed mods and default JVM tuning.',
                 'Results describe this scene and machine; launcher startup time is excluded.',
                 'Settings screenshots, runtime evidence and raw frame timings are included.'])
    output.mkdir(parents=True, exist_ok=True)
    for file in WORK.iterdir():
        if file.is_file() and (file.suffix in ['.csv', '.png'] or file.name in ['setup.json', 'results.json', 'restore.json']
                               or file.name.endswith(('-runtime.txt', '-effective-options.txt', '-validation.txt', '-loaded-mods.json'))):
            shutil.copy2(file, output / file.name)
    (output / 'README.md').write_text('\n'.join(text) + '\n')
    print('\n'.join(text), flush=True)
    print('\nResults: ' + str(output), flush=True)


def automatic(args):
    global WORK
    for tool in ['wmctrl', 'xdotool']:
        if not shutil.which(tool):
            raise RuntimeError('Install ' + tool + ' first')
    if os.environ.get('XDG_SESSION_TYPE') != 'x11':
        raise RuntimeError('This desktop automation requires an X11 session.')
    if not args.fastclient.is_file():
        raise RuntimeError('FastClient AppImage not found: ' + str(args.fastclient))
    if (WORK / 'journal.json').exists() and not (WORK / 'restored').exists():
        stop_benchmark_games()  # Only this script's existing interrupted test.
        stop_owned_launchers()
    else:
        no_games()
        WORK = Path(tempfile.mkdtemp(prefix='cubeon-fastclient-benchmark-'))
    try:
        build()
        if not (WORK / 'journal.json').exists():
            prepare()
        for instance, folder in [(CUBEON, PROFILE), (FAST, FAST / 'mods')]:
            shutil.copy2(WORK / JAR, folder / JAR)
        for client in ['cubeon', 'fastclient']:
            # A fresh identical scene for each client; only this script's copy is replaced.
            target = (CUBEON if client == 'cubeon' else FAST) / 'saves' / WORLD
            if tree_digest(target) != tree_digest(WORK / 'world-snapshot'):
                shutil.rmtree(target)
                shutil.copytree(WORK / 'world-snapshot', target)
            run_client(client, args)
        results()
    finally:
        stop_benchmark_games()
        stop_owned_launchers()
        if (WORK / 'journal.json').exists():
            restore()
    summary(args.output)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Automatically benchmark real Cubeon source and FastClient launchers.')
    parser.add_argument('--fastclient', type=Path, default=HOME / 'Downloads/FastClient(1).AppImage')
    parser.add_argument('--runs', type=int, default=2)
    parser.add_argument('--warmup', type=float, default=15)
    parser.add_argument('--duration', type=float, default=30)
    parser.add_argument('--output', type=Path, default=REPO / 'archive/benchmarks/client-comparison' / datetime.now().strftime('%Y%m%d-%H%M%S'))
    parser.add_argument('--check', action='store_true', help='Compile/check prerequisites without launching.')
    args = parser.parse_args()
    if not 1 <= args.runs <= 3 or args.warmup < 5 or args.duration < 10:
        parser.error('Use 1–3 runs, warmup >=5 seconds and duration >=10 seconds.')
    try:
        if args.check:
            build()
            print('Ready. Actual-launcher quick run takes about 3 minutes plus startup.')
        else:
            automatic(args)
    except KeyboardInterrupt:
        print('Benchmark cancelled; temporary settings restored.', file=sys.stderr)
        sys.exit(130)
    except Exception as error:
        print('Benchmark failed: ' + str(error), file=sys.stderr)
        print('Diagnostic files: ' + str(WORK), file=sys.stderr)
        sys.exit(1)


