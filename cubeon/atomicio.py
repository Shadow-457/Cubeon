"""
Atomic JSON writes.

Invariant used across Cubeon's persisted state (config.json, skins.json,
skin_net.json, auth_key.json, invites.json, ...): a crash mid-write must
never leave a truncated/corrupt file behind. load_* readers here mostly
fall back to defaults on JSONDecodeError, which would silently wipe the
user's settings/skins - so every writer goes through a temp file +
os.replace(), which is atomic on POSIX and Windows. Write to a unique
temp file in the SAME directory (os.replace is only atomic on one
filesystem), fsync it, then rename over the target.
"""
import json
import os
import tempfile


def write_json(path: str, data, indent: int | None = 2) -> None:
    """Atomically write `data` as JSON to `path`. Raises OSError on failure
    (the previous file is left intact); callers that must never raise can
    catch OSError around this."""
    directory = os.path.dirname(path) or "."
    os.makedirs(directory, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=".atomic-", suffix=".tmp", dir=directory)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=indent)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
