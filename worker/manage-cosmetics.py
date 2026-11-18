#!/usr/bin/env python3
"""Owner-only Neon cape publishing. Credentials never enter launcher builds."""
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
    return query(connection, """INSERT INTO cubeon_cosmetics
        (id, name, description, mime_type, file_bytes, byte_size, sha256, preview_png)
        VALUES ($1, $2, $3, $4, decode($5, 'base64'), $6, $7, decode($8, 'base64'))
        ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, description = EXCLUDED.description,
          mime_type = EXCLUDED.mime_type, file_bytes = EXCLUDED.file_bytes,
          byte_size = EXCLUDED.byte_size, sha256 = EXCLUDED.sha256,
          preview_png = EXCLUDED.preview_png, published = true, updated_at = now()
        RETURNING id, name, byte_size, sha256""", values)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--env-file", type=Path, default=ROOT / ".env")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("init", help="Create the cape table without changing existing data")
    commands.add_parser("sample", help="Publish exactly one sample using the existing Cubeon cape artwork")
    commands.add_parser("list", help="List owner-published catalog entries")
    upload = commands.add_parser("upload", help="Add a cape, or update the entry with the same id")
    upload.add_argument("file", type=Path)
    upload.add_argument("--id", required=True)
    upload.add_argument("--name", required=True)
    upload.add_argument("--description", default="")
    args = parser.parse_args()
    try:
        connection = connection_from_env(args.env_file)
        if args.command in ("init", "sample"):
            query(connection, (ROOT / "worker/cosmetics.sql").read_text())
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
            print(json.dumps(query(connection, "SELECT id, name, byte_size, sha256, published "
                "FROM cubeon_cosmetics ORDER BY updated_at DESC, id"), indent=2))
    except (ValueError, OSError) as error:
        # No traceback or raw provider messages containing connection details.
        parser.exit(1, f"{error}\n")


if __name__ == "__main__":
    main()
