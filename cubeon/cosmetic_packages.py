"""Validated, data-only store models using Cubeon's existing box/feather format."""
from __future__ import annotations

import base64
import copy
import hashlib
import io
import json
import math
from pathlib import Path
import re
import tempfile
import os
import threading

from PIL import Image
from .paths import CUBEON_HOME
from .atomicio import write_json

DIRECTORY = Path(CUBEON_HOME) / "cosmetics-store"
MIME = "application/vnd.cubeon.cosmetic+json"
KIND_SLOTS = {"pet": "shoulder", "wing": "back", "head": "head", "feet": "feet"}
MAX_BYTES = 2 * 1024 * 1024
_LOCK = threading.RLock()
_NAME = re.compile(r"[a-z0-9_-]+\.png")


def _vector(value, length, bound=256):
    if (not isinstance(value, list) or len(value) != length or
            any(type(n) not in (int, float) or not math.isfinite(n) or abs(n) > bound for n in value)):
        raise ValueError("Invalid model coordinates.")
    return value


def validate(package):
    """Reject scripts, paths, oversized meshes and invalid texture/UV data."""
    if not isinstance(package, dict) or package.get("schema") != 1 or package.get("kind") not in KIND_SLOTS:
        raise ValueError("Use a Cubeon pet, wing, headwear or footwear model package.")
    item, textures = package.get("item"), package.get("textures")
    if not isinstance(item, dict) or not isinstance(textures, dict) or not 1 <= len(textures) <= 4:
        raise ValueError("Model packages need an item and PNG textures.")
    decoded = {}
    for name, value in textures.items():
        if not _NAME.fullmatch(name) or not isinstance(value, str) or len(value) > MAX_BYTES * 2:
            raise ValueError("Model textures must be simple PNG filenames.")
        try:
            data = base64.b64decode(value, validate=True)
            with Image.open(io.BytesIO(data)) as image:
                if image.format != "PNG" or max(image.size) > 2048:
                    raise ValueError("Use PNG model textures up to 2048 pixels.")
                image.verify()
            decoded[name] = data
        except (OSError, ValueError) as error:
            raise ValueError("Invalid model PNG texture.") from error

    def model(entry, flat=False):
        slot = KIND_SLOTS[package["kind"]]
        if not isinstance(entry, dict) or entry.get("slot") != slot or entry.get("texture") not in decoded:
            raise ValueError("The model slot must match its cosmetic kind.")
        with Image.open(io.BytesIO(decoded[entry["texture"]])) as image:
            if (entry.get("tex_w"), entry.get("tex_h")) != image.size:
                raise ValueError("Model texture dimensions do not match its PNG.")
        glow = entry.get("emissive_texture")
        if glow is not None:
            if not isinstance(glow,str) or not _NAME.fullmatch(glow) or glow not in decoded:
                raise ValueError("Missing model glow texture.")
            with Image.open(io.BytesIO(decoded[glow])) as image:
                if image.size != (entry["tex_w"], entry["tex_h"]):
                    raise ValueError("Glow textures must use the model's atlas layout.")
        boxes = entry.get("boxes")
        if not isinstance(boxes, list) or not 1 <= len(boxes) <= 2048:
            raise ValueError("Models need 1–2048 boxes.")
        for box in boxes:
            if not isinstance(box, dict):
                raise ValueError("Invalid model box.")
            _vector(box.get("origin"), 3)
            size = _vector(box.get("size"), 3, 128)
            uv = _vector(box.get("uv"), 2, 2048)
            px = box.get("px")
            if min(size) <= 0 or min(uv) < 0 or type(px) is not int or not 1 <= px <= 16:
                raise ValueError("Invalid model size or UV scale.")
            if uv[0] + 2 * (size[0] + size[2]) * px > entry["tex_w"] or uv[1] + (size[1] + size[2]) * px > entry["tex_h"]:
                raise ValueError("Model UVs extend outside the texture.")
            if "pivot" in box:
                _vector(box["pivot"], 3)
            motion = box.get("motion", "")
            if motion not in ("", "none", "body", "head", "wing", "pack", "float", "aura",
                              "hover_body", "hover_head", "orbit", "orbit_wing_left", "orbit_wing_right", "left_leg", "right_leg"):
                raise ValueError("Unknown model animation group.")
            if (slot == "feet") != (motion in ("left_leg", "right_leg")):
                raise ValueError("Footwear boxes must identify their left or right leg.")
            if "faces" in box and (not isinstance(box["faces"], list) or not set(box["faces"]) <= {"front", "back", "left", "right", "top", "bottom"}):
                raise ValueError("Invalid box faces.")
        feathers = entry.get("feathers", [])
        if not isinstance(feathers, list) or len(feathers) > 16:
            raise ValueError("Wings allow up to sixteen feather guides.")
        for feather in feathers:
            _vector(feather.get("start"), 2)
            _vector(feather.get("end"), 2)
            for key, default, limit in (("width", 1, 128), ("curve", 0, 256), ("curl", 0, 8), ("tilt", 0, .5)):
                number = feather.get(key, default)
                if type(number) not in (int, float) or not math.isfinite(number) or abs(number) > limit or (key == "width" and number <= 0):
                    raise ValueError("Invalid feather guide.")
        if not flat and entry.get("flat") is not None:
            model(entry["flat"], True)
    model(item)
    return decoded


def encode(package):
    validate(package)
    data = json.dumps(package, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()
    if len(data) > MAX_BYTES:
        raise ValueError("Model packages must be at most 2 MB.")
    return data


def read(payload):
    if len(payload) > MAX_BYTES:
        raise ValueError("Model package is too large.")
    try:
        package = json.loads(payload)
        validate(package)
        return package
    except (ValueError, TypeError, AttributeError, KeyError, RecursionError) as error:
        raise ValueError("Invalid Cubeon model package.") from error


def installed_items():
    result = []
    if DIRECTORY.is_dir():
        for manifest in sorted(DIRECTORY.glob("store_*/item.json")):
            try:
                item = json.loads(manifest.read_text())
                if item.get("id") != manifest.parent.name or not _NAME.fullmatch(item.get("texture", "")):
                    continue
                if item.get("flat") and (not _NAME.fullmatch(item["flat"].get("texture", "")) or
                        not (manifest.parent / item["flat"]["texture"]).is_file()):
                    continue
                if (manifest.parent / item["texture"]).is_file():
                    if any(model.get("emissive_texture") and
                           (not _NAME.fullmatch(model["emissive_texture"]) or
                            not (manifest.parent / model["emissive_texture"]).is_file())
                           for model in (item, item.get("flat")) if model):
                        continue
                    item["_store_directory"] = str(manifest.parent)
                    if item.get("flat"):
                        item["flat"]["_store_directory"] = str(manifest.parent)
                    result.append(item)
            except (OSError, ValueError, AttributeError):
                continue
    return result


def installed(item):
    return next((value for value in installed_items() if value.get("store_id") == item["id"] and
                 value.get("store_sha256") == item["sha256"]), None)


def install(payload, metadata):
    package = read(payload)
    if package["kind"] != metadata["kind"]:
        raise ValueError("The downloaded model kind changed.")
    if hashlib.sha256(payload).hexdigest() != metadata["sha256"]:
        raise ValueError("The downloaded model checksum changed.")
    with _LOCK:
        existing = installed(metadata)
        if existing:
            return existing
        # Versioned ids preserve equipped older revisions and cannot replace bundled art.
        item = copy.deepcopy(package["item"])
        item_id = "store_" + hashlib.sha256((metadata["id"] + metadata["sha256"]).encode()).hexdigest()[:32]
        item.update(id=item_id, name=metadata["name"], blurb=metadata["description"],
                    store_id=metadata["id"], store_sha256=metadata["sha256"])
        textures = validate(package)
        if item.get("flat"):
            item["flat"].update(id=item_id, name=metadata["name"])
        DIRECTORY.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".import-", dir=DIRECTORY) as temporary:
            stage = Path(temporary) / item_id
            stage.mkdir()
            for name, data in textures.items():
                (stage / name).write_bytes(data)
            write_json(str(stage / "item.json"), item)
            os.replace(stage, DIRECTORY / item_id)
        from . import cosmetics
        cosmetics.invalidate_cache()
        return installed(metadata)


def sync_game(cfg, game_dir):
    """Install selected model data and texture resources before Minecraft starts."""
    from . import cosmetics, game_options, packformat
    entries = [item for item in installed_items() if item["id"] in
               (cfg.get(f"active_{slot}_item") for slot in KIND_SLOTS.values())]
    if not entries:
        return
    game = Path(game_dir)
    pack = game / "resourcepacks" / "cubeon-store"
    textures = pack / "assets/cubeon-client/textures/cosmetics"
    textures.mkdir(parents=True, exist_ok=True)
    models = []
    for original in entries:
        item = copy.deepcopy(original)
        directory = Path(item.pop("_store_directory"))
        for model in (item, item.get("flat")):
            if model:
                model.pop("_store_directory", None)
                name = model["texture"]
                target = item["id"] + ("_flat.png" if model is not item else ".png")
                data = (directory / name).read_bytes()
                path = textures / target
                if not path.is_file() or path.read_bytes() != data:
                    fd, temporary = tempfile.mkstemp(prefix=".texture-", dir=textures)
                    try:
                        with os.fdopen(fd, "wb") as stream:
                            stream.write(data)
                            stream.flush()
                            os.fsync(stream.fileno())
                        os.replace(temporary, path)
                    finally:
                        if os.path.exists(temporary):
                            os.unlink(temporary)
                model["texture"] = target
                if model.get("emissive_texture"):
                    name = model["emissive_texture"]
                    target = item["id"] + ("_flat_glow.png" if model is not item else "_glow.png")
                    data = (directory / name).read_bytes()
                    path = textures / target
                    if not path.is_file() or path.read_bytes() != data:
                        fd, temporary = tempfile.mkstemp(prefix=".glow-", dir=textures)
                        try:
                            with os.fdopen(fd, "wb") as stream:
                                stream.write(data)
                                stream.flush()
                                os.fsync(stream.fileno())
                            os.replace(temporary, path)
                        finally:
                            if os.path.exists(temporary): os.unlink(temporary)
                    model["emissive_texture"] = target
        models.append(item)
    fmt = packformat.resource_format_for(cfg.get("last_version")) or 15
    write_json(str(pack / "pack.mcmeta"), {"pack": {"description": "Downloaded Cubeon cosmetics",
               "pack_format": fmt, "supported_formats": [fmt, fmt], "min_format": fmt, "max_format": fmt}})
    write_json(str(game / "config/cubeon-store.json"), {"items": models, "anchors": cosmetics.ANCHORS})
    options = game / "options.txt"
    packs = []
    if options.is_file():
        for line in options.read_text().splitlines():
            if line.startswith("resourcePacks:"):
                packs = json.loads(line.partition(":")[2])
    if not isinstance(packs, list) or any(not isinstance(value, str) for value in packs):
        raise ValueError("The instance resource pack selection is invalid.")
    if "file/cubeon-store" not in packs:
        packs.append("file/cubeon-store")
        game_options._set_options(str(options), {"resourcePacks": json.dumps(packs)}, "Cosmetics", allow_missing=True)
        if not options.is_file() or not any(line.startswith("resourcePacks:") and
                "file/cubeon-store" in json.loads(line.partition(":")[2]) for line in options.read_text().splitlines()):
            raise OSError("Could not enable the downloaded cosmetics resource pack.")
