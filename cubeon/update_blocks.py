"""Content-defined package blocks shared by release tooling and the updater.

Boundaries follow a two-byte content anchor after 32 KiB, capped at 256 KiB.
Native bytes.find and SHA-256 keep indexing off Python's per-byte hot path.
Matching blocks can move within a package without needing to download them.
This format contains no paths or executable patch instructions.
"""
from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import re

ALGORITHM = "anchor-32k-256k-v1"
MIN_BLOCK = 32 * 1024
MAX_BLOCK = 256 * 1024
MAX_PACKAGE = 1024 * 1024 * 1024
MAX_MAP = 4 * 1024 * 1024
MAX_BLOCKS = MAX_PACKAGE // MIN_BLOCK + 1
ANCHOR = b"\x00\x00"
_HASH = re.compile(r"[0-9a-f]{64}\Z")


def identity(info):
    return info.st_dev, info.st_ino, info.st_size, info.st_mtime_ns, info.st_ctime_ns


@dataclass(frozen=True)
class Block:
    offset: int
    size: int
    sha256: str


def scan(stream, *, check=lambda: None):
    """Yield (Block, bytes) in order, with bounded memory and cancellation."""
    offset = 0
    pending = b""
    while True:
        check()
        pending += stream.read(MAX_BLOCK - len(pending))
        if not pending:
            return
        anchor = pending.find(ANCHOR, MIN_BLOCK)
        end = anchor + len(ANCHOR) if anchor >= 0 else len(pending)
        data = pending[:end]
        yield Block(offset, len(data), hashlib.sha256(data).hexdigest()), data
        offset += len(data)
        if offset > MAX_PACKAGE:
            raise ValueError("Package exceeds the block-map limit")
        pending = pending[end:]


def generate(path: Path) -> dict:
    info = path.stat()
    if not 0 < info.st_size <= MAX_PACKAGE:
        raise ValueError("Invalid package size")
    digest = hashlib.sha256()
    chunks = []
    with path.open("rb") as stream:
        for block, data in scan(stream):
            digest.update(data)
            chunks.append([block.size, block.sha256])
    if identity(info) != identity(path.stat()):
        raise ValueError("Package changed while creating its block map")
    result = {"schema_version": 1, "algorithm": ALGORITHM, "size": info.st_size,
              "sha256": digest.hexdigest(), "chunks": chunks}
    encoded = json.dumps(result, separators=(",", ":")).encode()
    if len(encoded) + 1 > MAX_MAP:
        raise ValueError("Block map exceeds its size limit")
    return result


def parse(body: bytes, size: int, sha256: str) -> list[Block]:
    """Validate against the independently verified GitHub package descriptor."""
    if len(body) > MAX_MAP:
        raise ValueError("Block map is too large")
    root = json.loads(body)
    if (not isinstance(root, dict) or type(root.get("schema_version")) is not int
            or root["schema_version"] != 1 or root.get("algorithm") != ALGORITHM
            or type(root.get("size")) is not int or root["size"] != size
            or type(size) is not int or not 0 < size <= MAX_PACKAGE
            or not isinstance(sha256, str) or not _HASH.fullmatch(sha256)
            or root.get("sha256") != sha256):
        raise ValueError("Block map does not describe this package")
    chunks = root.get("chunks")
    if not isinstance(chunks, list) or not 0 < len(chunks) <= MAX_BLOCKS:
        raise ValueError("Invalid block count")
    blocks = []
    offset = 0
    for index, chunk in enumerate(chunks):
        if (not isinstance(chunk, list) or len(chunk) != 2 or type(chunk[0]) is not int
                or not 0 < chunk[0] <= MAX_BLOCK or (index < len(chunks) - 1 and chunk[0] < MIN_BLOCK)
                or not isinstance(chunk[1], str) or not _HASH.fullmatch(chunk[1])):
            raise ValueError("Invalid package block")
        blocks.append(Block(offset, chunk[0], chunk[1]))
        offset += chunk[0]
        if offset > size:
            raise ValueError("Blocks exceed the package size")
    if offset != size:
        raise ValueError("Incomplete package block map")
    return blocks


def index(stream, *, check=lambda: None) -> dict[tuple[int, str], int]:
    return {(block.size, block.sha256): block.offset for block, _data in scan(stream, check=check)}


def ranges(blocks: list[Block], local: dict, *, maximum=8 * 1024 * 1024) -> list[tuple[int, int]]:
    """Coalesce adjacent missing blocks; endpoints are inclusive HTTP offsets."""
    missing = []
    for block in blocks:
        if (block.size, block.sha256) in local:
            continue
        end = block.offset + block.size - 1
        if missing and missing[-1][1] + 1 == block.offset and end - missing[-1][0] + 1 <= maximum:
            missing[-1] = missing[-1][0], end
        else:
            missing.append((block.offset, end))
    return missing
