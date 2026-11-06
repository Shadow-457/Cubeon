"""Reversible renderer/effect settings for the opt-in FPS video sync.

Only existing, known config keys are managed. Missing fields keep the mod's
compiled defaults. Driver workarounds and the EntityCulling/ImmediatelyFast
rendering-compatibility switches are deliberately outside this preset.
"""
import json
from pathlib import Path
import re
import tempfile
import os
import threading

from .atomicio import write_json


_RENDERER = {
    "performance.chunk_builder_threads": 2,
    "performance.chunk_build_defer_mode": "ALWAYS",
    "performance.animate_only_visible_textures": True,
    "performance.use_entity_culling": True,
    "performance.use_fog_occlusion": True,
    "performance.use_block_face_culling": True,
    "quality.hidden_fluid_culling": True,
    "quality.improved_fluid_shaping": False,
}
SETTINGS = {
    "sodium-options.json": _RENDERER,
    "embeddium-options.json": _RENDERER,
    "rubidium-options.json": _RENDERER,
    "immediatelyfast.json": {
        "map_atlas_generation": True,
        "fast_text_lookup": True,
        "avoid_redundant_framebuffer_switching": True,
        "batch_animated_item_updates": True,
    },
    "cubeon-client-hud.json": {"cameraMotionBlur": False, "temporalMotionBlur": False},
    # Iris/Oculus test exactly "false". Case changes or trailing whitespace
    # can enable shaders. Keep raw property values for an exact restoration.
    "iris.properties": {"enableShaders": "false"},
    "oculus.properties": {"enableShaders": "false"},
}
BACKUP = ".cubeon-fps-mod-settings.json"
_LOCK = threading.RLock()
_SHADER = re.compile(r"^([ \t\f]*enableShaders(?:[ \t\f]*[:=][ \t\f]*|[ \t\f]+))([^\r\n]*)(\r\n|\n|\r)?$")


def _leaf(data, key):
    parts = key.split(".")
    for part in parts[:-1]:
        data = data.get(part) if isinstance(data, dict) else None
    return (data, parts[-1]) if isinstance(data, dict) and parts[-1] in data else None


def _read(path, rules):
    """Return current managed values and a writer preserving unrelated settings."""
    if path.suffix == ".properties":
        with path.open(encoding="utf-8", newline="") as source:
            original = source.read()
        lines = original.splitlines(keepends=True)
        for line in lines:
            stripped = line.lstrip()
            if not stripped or stripped.startswith(("#", "!")):
                continue
            key = re.split(r"[\s=:]", stripped, maxsplit=1)[0]
            body = line.rstrip("\r\n")
            if "\\" in key or (len(body) - len(body.rstrip("\\"))) % 2:
                raise ValueError("escaped keys or continued shader properties are unsupported")
        matches = [(i, _SHADER.fullmatch(line)) for i, line in enumerate(lines)]
        matches = [(i, match) for i, match in matches if match]
        # Java accepts duplicate/escaped/continued properties. Do not pretend a
        # partial parse knows the winning value of such a manually edited file.
        candidates = [line for line in lines if line.lstrip().startswith("enableShaders")]
        if len(matches) != 1 or len(candidates) != 1:
            raise ValueError("expected one plain enableShaders property")
        index, match = matches[0]
        current = {"enableShaders": match[2]}

        def write(values):
            updated = list(lines)
            updated[index] = match[1] + values["enableShaders"] + (match[3] or "")
            fd, name = tempfile.mkstemp(prefix=".cubeon-fps-", dir=path.parent)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="") as output:
                    output.write("".join(updated))
                    output.flush()
                    os.fsync(output.fileno())
                os.replace(name, path)
            finally:
                if os.path.exists(name):
                    os.unlink(name)
        return current, write

    data = json.loads(path.read_text(encoding="utf-8-sig"))
    if not isinstance(data, dict):
        raise ValueError("config must contain an object")
    current = {}
    for key, wanted in rules.items():
        leaf = _leaf(data, key)
        if leaf and type(leaf[0][leaf[1]]) is type(wanted):
            current[key] = leaf[0][leaf[1]]

    def write(values):
        for key, value in values.items():
            leaf = _leaf(data, key)
            if leaf:
                leaf[0][leaf[1]] = value
        write_json(str(path), data)
    return current, write


def _read_backup(path):
    try:
        saved = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return {"schema": 1, "files": {}}
    if not isinstance(saved, dict) or saved.get("schema") != 1 or not isinstance(saved.get("files"), dict):
        raise ValueError("invalid FPS mod settings backup")
    for filename, entry in saved["files"].items():
        if filename not in SETTINGS or not isinstance(entry, dict):
            raise ValueError("invalid FPS mod settings backup entry")
        if not isinstance(entry.get("before"), dict) or not isinstance(entry.get("applied"), dict):
            raise ValueError("invalid FPS mod settings backup values")
        if entry["before"].keys() != entry["applied"].keys():
            raise ValueError("incomplete FPS mod settings backup")
        for key, before in entry["before"].items():
            wanted = SETTINGS[filename].get(key)
            if wanted is None or type(before) is not type(wanted) or type(entry["applied"][key]) is not type(wanted):
                raise ValueError("unsupported FPS mod settings backup key")
    return saved


def sync_mod_settings(game_dir, *, enabled, sync_settings):
    """Enforce with sync ON; sync OFF stops enforcement; Boost OFF restores.

    Called before spawning the game, after performance-mod preparation. A failed
    backup prevents changes to that file. Failed config writes retain the backup
    for retry; one broken file never prevents restoring the remaining files.
    """
    report = {"changed": [], "errors": []}
    if enabled and not sync_settings:
        return report
    directory = Path(game_dir) / "config"
    marker = directory / BACKUP
    with _LOCK:
        try:
            saved = _read_backup(marker)
        except (OSError, ValueError) as error:
            report["errors"].append(f"Keeping mod settings: {error}")
            return report
        for filename, rules in SETTINGS.items():
            entry = saved["files"].get(filename)
            if not enabled and entry is None:
                continue
            path = directory / filename
            try:
                current, write = _read(path, rules)
                if enabled:
                    backup_changed = entry is None
                    entry = entry or {"before": {}, "applied": {}}
                    for key, value in current.items():
                        backup_changed |= key not in entry["before"] or entry["applied"].get(key) != rules[key]
                        entry["before"].setdefault(key, value)
                        entry["applied"][key] = rules[key]
                    if not entry["before"]:
                        continue
                    saved["files"][filename] = entry
                    # Journal the originals before any config write, including
                    # the first run when every setting already has its fast value.
                    if backup_changed:
                        write_json(str(marker), saved)
                    wanted = {key: rules[key] for key in current}
                else:
                    wanted = {key: before for key, before in entry["before"].items()
                              if key in current and current[key] == entry["applied"][key]}
                changed = {key: value for key, value in wanted.items() if current.get(key) != value}
                if changed:
                    write(changed)
                    report["changed"].append(filename)
                if not enabled:
                    saved["files"].pop(filename, None)
                    write_json(str(marker), saved)
            except FileNotFoundError:
                # A removed mod/config must never be recreated by restore.
                if path.exists():
                    report["errors"].append(f"{filename}: could not write settings or backup")
                elif not enabled and entry is not None:
                    saved["files"].pop(filename, None)
                    try:
                        write_json(str(marker), saved)
                    except OSError as error:
                        report["errors"].append(f"{filename}: {error}")
                continue
            except (OSError, ValueError) as error:
                report["errors"].append(f"{filename}: {error}")
    return report
