"""Bounded BSDIFF40 decoding. Patch generation is build-only, not a runtime dependency."""
import bz2
import os
import time
from pathlib import Path

CHUNK = 64 * 1024
MAX_ACTIVE_SECONDS = 15 * 60
MAX_OUTPUT = 1024 * 1024 * 1024


class PatchError(ValueError):
    pass


def _number(data):
    if len(data) != 8:
        raise PatchError("Truncated patch number.")
    value = int.from_bytes(data, "little")
    return -(value & ((1 << 63) - 1)) if value >> 63 else value


class _Section:
    def __init__(self, path, start, length, checkpoint):
        self.file = Path(path).open("rb")
        self.file.seek(start)
        self.remaining = length
        self.decoder = bz2.BZ2Decompressor()
        self.checkpoint = checkpoint

    def read(self, count):
        result = bytearray()
        while len(result) < count:
            self.checkpoint()
            if self.decoder.eof:
                raise PatchError("Truncated patch section.")
            data = b""
            if self.decoder.needs_input:
                if not self.remaining:
                    raise PatchError("Unterminated patch section.")
                data = self.file.read(min(CHUNK, self.remaining))
                if not data:
                    raise PatchError("Truncated patch section.")
                self.remaining -= len(data)
            try:
                result.extend(self.decoder.decompress(data, max_length=count - len(result)))
            except (OSError, EOFError) as error:
                raise PatchError("Invalid patch compression.") from error
        return result

    def finish(self):
        # Consume only the stream terminator; extra decoded output is invalid.
        while not self.decoder.eof:
            self.checkpoint()
            data = b""
            if self.decoder.needs_input:
                if not self.remaining:
                    raise PatchError("Unterminated patch section.")
                data = self.file.read(min(CHUNK, self.remaining))
                self.remaining -= len(data)
                if not data:
                    raise PatchError("Truncated patch section.")
            try:
                if self.decoder.decompress(data, max_length=1):
                    raise PatchError("Excess patch output.")
            except OSError as error:
                raise PatchError("Invalid patch compression.") from error
        if self.remaining or self.decoder.unused_data:
            raise PatchError("Trailing patch data.")

    def close(self):
        self.file.close()


def apply_patch(base, patch, output, size, *, checkpoint=lambda: None):
    """Write a new file exclusively; never modify the base or installed program."""
    if type(size) is not int or not 0 <= size <= MAX_OUTPUT:
        raise PatchError("Invalid patch output limit.")
    # Waiting for gameplay to end is excluded from the reconstruction budget.
    last_checkpoint = time.monotonic()
    active = 0.0
    def bounded_checkpoint():
        nonlocal last_checkpoint, active
        active += time.monotonic() - last_checkpoint
        checkpoint()
        last_checkpoint = time.monotonic()
        if active > MAX_ACTIVE_SECONDS:
            raise PatchError("Patch reconstruction timed out.")
    patch = Path(patch)
    with patch.open("rb") as source:
        header = source.read(32)
    if len(header) != 32 or header[:8] != b"BSDIFF40":
        raise PatchError("Unsupported patch format.")
    control_len, diff_len, new_size = (_number(header[n:n + 8]) for n in (8, 16, 24))
    extra_len = patch.stat().st_size - 32 - control_len - diff_len
    if min(control_len, diff_len, extra_len) < 0 or new_size != size or size < 0:
        raise PatchError("Invalid patch section or output size.")
    sections = []
    try:
        for offset, length in ((32, control_len), (32 + control_len, diff_len),
                               (32 + control_len + diff_len, extra_len)):
            sections.append(_Section(patch, offset, length, bounded_checkpoint))
        control, diff, extra = sections
        with Path(base).open("rb") as old, Path(output).open("xb") as new:
            old_size = os.fstat(old.fileno()).st_size
            old_pos = new_pos = operations = idle_controls = 0
            while new_pos < size:
                bounded_checkpoint()
                operations += 1
                if operations > min(size + 1024, 1000000):
                    raise PatchError("Patch has too many controls.")
                x, y, z = (_number(control.read(8)) for _ in range(3))
                if x < 0 or y < 0 or x + y > size - new_pos:
                    raise PatchError("Patch writes outside the output.")
                idle_controls = idle_controls + 1 if x + y == 0 else 0
                if idle_controls > 1024:
                    raise PatchError("Patch makes no output progress.")
                remaining = x
                while remaining:
                    count = min(CHUNK, remaining)
                    data = diff.read(count)
                    first = max(0, old_pos)
                    last = min(old_size, old_pos + count)
                    if last > first:
                        old.seek(first)
                        previous = old.read(last - first)
                        if len(previous) != last - first:
                            raise PatchError("Base changed during reconstruction.")
                        start = first - old_pos
                        for n, value in enumerate(previous, start):
                            data[n] = (data[n] + value) & 255
                    new.write(data)
                    old_pos += count
                    new_pos += count
                    remaining -= count
                remaining = y
                while remaining:
                    count = min(CHUNK, remaining)
                    new.write(extra.read(count))
                    new_pos += count
                    remaining -= count
                old_pos += z
            for section in sections:
                section.finish()
            new.flush()
            os.fsync(new.fileno())
    finally:
        for section in sections:
            section.close()
