#!/usr/bin/env python3
"""Publish local cosmetic collections to Neon. Credentials stay owner-only."""
from __future__ import annotations

import argparse
import base64
import hashlib
import io
import json
import os
from pathlib import Path
import re
import sys
import copy
import shutil
import tempfile
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
MAX_BYTES = 2 * 1024 * 1024


def connection_from_env(path):
    connection = os.environ.get("NEON_DATABASE_URL", "").strip()
    if not connection and path.is_file():
        for line in path.read_text().splitlines():
            key, separator, value = line.partition("=")
            if separator and key.strip() == "NEON_DATABASE_URL":
                connection = value.strip().strip("\"'")
    parsed = urlsplit(connection)
    if (parsed.scheme not in ("postgres", "postgresql") or not parsed.username or
            not parsed.password or not parsed.path.strip("/") or
            not re.fullmatch(r"ep-[a-z0-9-]+\.[a-z0-9.-]+\.neon\.tech", parsed.hostname or "")):
        raise ValueError("Set NEON_DATABASE_URL in the ignored .env file or environment.")
    return connection


def query(connection, sql, params=()):
    import requests
    host = urlsplit(connection).hostname.replace("-pooler.", ".")
    try:
        response = requests.post("https://" + host + "/sql",
            headers={"Neon-Connection-String": connection,
                     "Neon-Raw-Text-Output": "true", "Neon-Array-Mode": "false"},
            json={"query": sql, "params": list(params)}, timeout=30,
            allow_redirects=False)
        with response:
            if response.status_code != 200:
                raise ValueError(f"Neon query failed (HTTP {response.status_code}).")
            if len(response.content) > 100000:
                raise ValueError("Unexpectedly large Neon response.")
            result = response.json()
    except requests.RequestException:
        raise ValueError("Could not reach Neon. Check the connection and network.") from None
    if not isinstance(result.get("rows"), list):
        raise ValueError("Unexpected Neon response.")
    return result["rows"]


def initialize(connection):
    creation, migration = (ROOT / "worker/cosmetics.sql").read_text().split("-- Idempotent", 1)
    query(connection, creation)
    query(connection, "-- Idempotent" + migration)


def prepare_cape(path, item_id, name, description):
    from PIL import Image
    from cubeon import capes
    if not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", item_id):
        raise ValueError("Use a 3–64 character lowercase id with letters, digits, underscores or hyphens.")
    if not 1 <= len(name.strip()) <= 80 or len(description) > 400:
        raise ValueError("Names need 1–80 characters; descriptions allow up to 400.")
    if not 0 < path.stat().st_size <= MAX_BYTES:
        raise ValueError("Store cape files must be at most 2 MB.")
    data = path.read_bytes()
    with Image.open(io.BytesIO(data)) as source:
        mime = {"PNG": "image/png", "GIF": "image/gif"}.get(source.format)
    if not mime:
        raise ValueError("Publish a PNG or animated GIF cape.")
    # Same validation, normalized layout and animation bounds as launcher import.
    frames, _, _ = capes._decode_cape(str(path))
    sheet = frames[0]
    scale = sheet.width // 64
    preview = sheet.crop((scale, scale, 11 * scale, 17 * scale)).resize(
        (80, 128), Image.Resampling.NEAREST)
    buf = io.BytesIO()
    preview.save(buf, "PNG", optimize=True)
    if len(buf.getvalue()) > 24576:
        raise ValueError("Cape preview is too complex; simplify the artwork.")
    return [item_id, name.strip(), description, mime,
            base64.b64encode(data).decode("ascii"), len(data), hashlib.sha256(data).hexdigest(),
            base64.b64encode(buf.getvalue()).decode("ascii")]


def publish(connection, values):
    from cubeon.cosmetic_retirement import STORE_IDS
    if values[0] in STORE_IDS:
        raise ValueError("This cosmetic has been retired; remove it from the upload folder.")
    # Cape upload callers retain their original eight-value contract.
    if len(values) == 8:
        values = [*values, "cape"]
    return query(connection, """INSERT INTO cubeon_cosmetics
        (id, name, description, mime_type, file_bytes, byte_size, sha256, preview_png, kind)
        VALUES ($1, $2, $3, $4, decode($5, 'base64'), $6, $7, decode($8, 'base64'), $9)
        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description,
          kind = EXCLUDED.kind,
          mime_type = EXCLUDED.mime_type, file_bytes = EXCLUDED.file_bytes,
          byte_size = EXCLUDED.byte_size, sha256 = EXCLUDED.sha256,
          preview_png = EXCLUDED.preview_png, published = true, updated_at = now()
        WHERE (cubeon_cosmetics.name, cubeon_cosmetics.description, cubeon_cosmetics.kind,
               cubeon_cosmetics.sha256, cubeon_cosmetics.preview_png, cubeon_cosmetics.published)
          IS DISTINCT FROM (EXCLUDED.name, EXCLUDED.description, EXCLUDED.kind,
                            EXCLUDED.sha256, EXCLUDED.preview_png, true)
        RETURNING id, name, byte_size, sha256""", values)


def setup(folder):
    """Create the ignored owner workspace without overwriting artwork."""
    for name in ("capes", "pets", "wings", "head", "feet", "auras", "examples"):
        (folder / name).mkdir(parents=True, exist_ok=True)
    sample = folder / "capes/cubeon-cape-sample.png"
    if not sample.exists():
        shutil.copyfile(ROOT / "assets/capes/cubeon_cape.png", sample)
    metadata = sample.with_suffix(".json")
    if not metadata.exists():
        metadata.write_text(json.dumps({"id": "cubeon-cape-sample", "name": "Cubeon Cape Sample",
            "description": "A free sample cape featuring Cubeon's original cube artwork."}, indent=2) + "\n")
    for kind, template in (("pet", "shoulder_ember_fox"), ("wing", "back_ember_wings_small")):
        path = folder / "examples" / (kind + ".json")
        if not path.exists():
            path.write_text(json.dumps({"id": "my-" + kind, "name": "My " + kind.title(),
                "description": "My original cosmetic.", "based_on": template}, indent=2) + "\n")
    print(f"Cosmetics folder ready: {folder}")


def _metadata(path):
    if path.stat().st_size > MAX_BYTES:
        raise ValueError(f"Metadata is too large: {path.name}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise ValueError(f"Use a JSON object in {path.name}.")
    return value


def prepare_model(path, kind):
    from cubeon import cosmetics, cosmetic_packages
    value = _metadata(path)
    item_id = value.get("id", path.stem.lower().replace("_", "-"))
    name = value.get("name", path.stem.replace("-", " ").replace("_", " ").title())
    description = value.get("description", "")
    if not isinstance(item_id, str) or not re.fullmatch(r"[a-z][a-z0-9_-]{2,63}", item_id):
        raise ValueError(f"Invalid cosmetic id in {path.name}.")
    if not isinstance(name, str) or not 1 <= len(name.strip()) <= 80 or not isinstance(description, str) or len(description) > 400:
        raise ValueError(f"Invalid name or description in {path.name}.")
    template = cosmetics.get(value.get("based_on"))
    item = copy.deepcopy(value.get("model", template))
    if not isinstance(item, dict):
        raise ValueError(f"{path.name} needs model geometry or a valid based_on id.")
    item.update(id=item_id, name=name.strip(), blurb=description)
    textures = {}
    for model, key in ((item, "texture"), (item.get("flat"), "flat_texture")):
        if not model:
            continue
        if model.get("emissive_texture"):
            glow_key = "emissive_texture" if model is item else "flat_emissive_texture"
            bundled_glow = template is not None and 'model' not in value and glow_key not in value
            if bundled_glow:
                source = Path(cosmetics.texture_path(model)).parent / model['emissive_texture']
            else:
                filename = Path(value.get(glow_key, model["emissive_texture"]))
                if filename.is_absolute() or ".." in filename.parts:
                    raise ValueError("Glow texture paths must stay inside their cosmetic folder.")
                source = path.parent / filename
            if (not bundled_glow and not source.resolve().is_relative_to(path.parent.resolve())) or not source.is_file() or source.stat().st_size > MAX_BYTES:
                raise ValueError("Missing or invalid glow texture.")
            model["emissive_texture"] = "glow.png" if model is item else "flat_glow.png"
            textures[model["emissive_texture"]] = base64.b64encode(source.read_bytes()).decode()
        if model is not item:
            model.update(id=item_id, name=name.strip())
        if key in value:
            filename = Path(value[key])
            if filename.is_absolute() or ".." in filename.parts:
                raise ValueError("Texture paths must stay inside their cosmetic folder.")
            source = path.parent / filename
        elif template:
            source = Path(cosmetics.texture_path(model))
        else:
            source = path.parent / model["texture"]
        if (key in value or not template) and not source.resolve().is_relative_to(path.parent.resolve()):
            raise ValueError("Texture paths must stay inside their cosmetic folder.")
        if not source.is_file() or source.stat().st_size > MAX_BYTES:
            raise ValueError(f"Missing or oversized texture in {path.name}.")
        model.pop("_store_directory", None)
        model["texture"] = "texture.png" if model is item else "flat.png"
        textures[model["texture"]] = base64.b64encode(source.read_bytes()).decode()
    package = {"schema": 1, "kind": kind, "item": item, "textures": textures}
    payload = cosmetic_packages.encode(package)
    # Reuse the launcher's actual 3D thumbnail renderer for owner previews.
    with tempfile.TemporaryDirectory() as temporary:
        for filename, data in cosmetic_packages.validate(package).items():
            (Path(temporary) / filename).write_bytes(data)
        preview = cosmetics.render_thumbnail(item, temporary, size=(80, 128), simplify=True)
    buffer = io.BytesIO()
    preview.save(buffer, "PNG", optimize=True)
    if len(buffer.getvalue()) > 24576:
        raise ValueError("The model preview is too complex.")
    return [item_id, name.strip(), description, cosmetic_packages.MIME,
            base64.b64encode(payload).decode(), len(payload), hashlib.sha256(payload).hexdigest(),
            base64.b64encode(buffer.getvalue()).decode(), kind]


def prepare_folder(folder):
    if not folder.is_dir():
        raise ValueError("Run publish-cosmetics.sh setup to create the local cosmetics folder.")
    prepared = []
    for path in sorted((folder / "capes").rglob("*")):
        if not path.is_file() or path.suffix.lower() not in (".png", ".gif"):
            continue
        value = _metadata(path.with_suffix(".json")) if path.with_suffix(".json").is_file() else {}
        prepared.append(prepare_cape(path, value.get("id", path.stem.lower().replace("_", "-")),
            value.get("name", path.stem.replace("-", " ").replace("_", " ").title()), value.get("description", "")))
    for directory, kind in (("pets", "pet"), ("wings", "wing"), ("head", "head"), ("feet", "feet"), ("auras", "aura")):
        for path in sorted((folder / directory).rglob("*.json")):
            prepared.append(prepare_model(path, kind))
    ids = [value[0] for value in prepared]
    from cubeon.cosmetic_retirement import STORE_IDS
    if set(ids) & STORE_IDS:
        raise ValueError("Retired cosmetics must be removed from the upload folder before sync.")
    if len(ids) != len(set(ids)):
        raise ValueError("Two local cosmetics have the same id. Give each entry a unique id.")
    return prepared


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create the cape table without changing existing data")
    commands.add_parser("sample", help="Publish exactly one sample using the existing Cubeon cape artwork")
    commands.add_parser("list", help="List owner-published catalog entries")
    for command in ("setup", "sync"):
        sub = commands.add_parser(command, help="Create local folders" if command == "setup" else "Publish all local cosmetics; skip unchanged entries")
        sub.add_argument("--folder", type=Path, default=ROOT / "cosmetics")
        if command == "sync":
            sub.add_argument("--dry-run", action="store_true", help="Validate everything without credentials or uploads")
    upload = commands.add_parser("upload", help="Add a cape, or update the entry with the same id")
    upload.add_argument("file", type=Path)
    upload.add_argument("--id", required=True)
    upload.add_argument("--name", required=True)
    upload.add_argument("--description", default="")
    args = parser.parse_args()
    try:
        if args.command == "setup":
            setup(args.folder)
            return
        if args.command == "sync":
            values = prepare_folder(args.folder)
            if args.dry_run:
                for value in values:
                    print(f"Valid: {value[0]} ({value[8] if len(value) == 9 else 'cape'}, {value[5]} bytes)")
                print(f"Validated {len(values)} cosmetics. No uploads.")
                return
            connection = connection_from_env(args.env_file)
            initialize(connection)
            changed = 0
            for value in values:
                result = publish(connection, value)
                changed += bool(result)
                print(f"{'Published' if result else 'Unchanged'}: {value[0]}")
            print(f"{changed} published; {len(values) - changed} unchanged. Store updates within 60 seconds.")
            return
        connection = connection_from_env(args.env_file)
        if args.command in ("init", "sample"):
            initialize(connection)
        if args.command == "init":
            print("Neon cape catalog is ready.")
        elif args.command == "sample":
            result = publish(connection, prepare_cape(ROOT / "assets/capes/cubeon_cape.png",
                "cubeon-cape-sample", "Cubeon Cape Sample",
                "A free sample cape featuring Cubeon's original cube artwork."))
            print(json.dumps(result, indent=2))
        elif args.command == "upload":
            print(json.dumps(publish(connection,
                prepare_cape(args.file, args.id, args.name, args.description)), indent=2))
        else:
            print(json.dumps(query(connection, "SELECT id, kind, name, byte_size, sha256, published "
                "FROM cubeon_cosmetics ORDER BY updated_at DESC, id"), indent=2))
    except (ValueError, OSError, TypeError, KeyError) as error:
        # No traceback or raw provider messages containing connection details.
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
