"""Sidecar reads are cached by (path, mtime_ns, size) - and never serve stale data.

`list_mods()` read one `<jar>.cubeon.json` per installed jar on every repaint,
and the Play tab re-read one `_cubeon_instance.json` per instance row. Those are
tiny files but there are hundreds, and it was all on the UI thread: measured
301 file opens per 300-mod list refresh, now zero.

Locked-in behaviour:
  1. an unchanged sidecar is served from the cache (no second file open)
  2. editing the file invalidates it (mtime/size), so new content is seen
  3. `_write_meta` / `write_instance_meta` drop the entry, so even a same-size
     rewrite that lands in the same mtime tick is read fresh
  4. a deleted/again-corrupt sidecar reads as None, and stops being cached
  5. callers get copies - mutating the result cannot poison the cache
  6. the cache is bounded

Run: python tools/test_sidecar_cache.py
"""
import builtins
import json
import os
import sys
import tempfile

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home
_sandbox_home.isolate()

from cubeon import mods as M  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def count_opens(fn):
    """Run fn with open() counted; return how many real file opens it did."""
    opened = []
    real_open = builtins.open

    def counting(*a, **k):
        opened.append(a[0] if a else k.get("file"))
        return real_open(*a, **k)

    builtins.open = counting
    try:
        result = fn()
    finally:
        builtins.open = real_open
    return len(opened), result


root = tempfile.mkdtemp(prefix="cubeon-sidecar-cache-")
M.MINECRAFT_DIR = root
M._SIDECAR_CACHE.clear()
profile = os.path.join(root, "profile")
os.makedirs(profile, exist_ok=True)
jar = "sodium-fabric-0.9.2.jar"
sidecar = M._meta_path(profile, jar)
with open(sidecar, "w", encoding="utf-8") as fh:
    json.dump({"slug": "sodium", "project_id": "AANobbMI"}, fh)

# --- 1. a warm read does not touch the disk --------------------------------
first = M._read_meta(profile, jar)
opens, second = count_opens(lambda: M._read_meta(profile, jar))
check("the first read returns the sidecar", first == {"slug": "sodium",
                                                     "project_id": "AANobbMI"},
      str(first))
check("a repeated read is served from the cache", opens == 0,
      f"{opens} file open(s)")
check("the cached read has the same value", second == first, str(second))

# --- 2. editing the file invalidates it ------------------------------------
with open(sidecar, "w", encoding="utf-8") as fh:
    json.dump({"slug": "sodium-extra", "project_id": "AANobbMI"}, fh)
edited = M._read_meta(profile, jar)
check("an edited sidecar is re-read", (edited or {}).get("slug") == "sodium-extra",
      str(edited))

# --- 3. a same-size rewrite in the same mtime tick is still fresh ----------
# Only the writers in this module can guarantee this: they drop the entry.
OLD_SLUG, NEW_SLUG = "sodium-aaaaa", "sodium-bbbbb"   # same length on purpose
with open(sidecar, "w", encoding="utf-8") as fh:
    json.dump({"slug": OLD_SLUG}, fh)
check("the old slug is cached", (M._read_meta(profile, jar) or {}).get("slug") == OLD_SLUG)
before = os.stat(sidecar)
M._write_meta(profile, jar, NEW_SLUG)
check("the rewrite kept the same size (the hard case)",
      os.path.getsize(sidecar) == before.st_size,
      f"{before.st_size} -> {os.path.getsize(sidecar)}")
# Force the mtime BACK to the old value: without the explicit cache drop the key
# would match and the write would be invisible.
os.utime(sidecar, ns=(before.st_atime_ns, before.st_mtime_ns))
check("...and the cache key really is unchanged",
      os.stat(sidecar).st_mtime_ns == before.st_mtime_ns, "mtime moved")
reread = M._read_meta(profile, jar)
check("a write through _write_meta is never served stale",
      (reread or {}).get("slug") == NEW_SLUG, str(reread))

# --- 4. deletion and corruption -------------------------------------------
os.remove(sidecar)
check("a deleted sidecar reads as None", M._read_meta(profile, jar) is None,
      str(M._read_meta(profile, jar)))
with open(sidecar, "w", encoding="utf-8") as fh:
    fh.write("{not json")
check("a corrupt sidecar reads as None", M._read_meta(profile, jar) is None)
with open(sidecar, "w", encoding="utf-8") as fh:
    json.dump({"slug": "sodium"}, fh)
check("a repaired sidecar reads again",
      (M._read_meta(profile, jar) or {}).get("slug") == "sodium")

# --- 5. callers cannot poison the cache ------------------------------------
poisoned = M._read_meta(profile, jar)
poisoned["slug"] = "poisoned"
check("mutating the result does not poison the cache",
      (M._read_meta(profile, jar) or {}).get("slug") == "sodium",
      str(M._read_meta(profile, jar)))

# --- 6. instance sidecars use the same cache, same rules -------------------
version_id = "1.20.1-fabric"
folder = os.path.join(root, "versions", version_id)
os.makedirs(folder, exist_ok=True)
meta_path = os.path.join(folder, M.INSTANCE_META_FILENAME)
with open(meta_path, "w", encoding="utf-8") as fh:
    json.dump({"mc_version": "1.20.1", "loader": "fabric", "profile": "p1"}, fh)
check("read_instance_meta reads it",
      (M.read_instance_meta(version_id) or {}).get("profile") == "p1",
      str(M.read_instance_meta(version_id)))
opens, _ = count_opens(lambda: M.read_instance_meta(version_id))
check("read_instance_meta is cached too", opens == 0, f"{opens} file open(s)")
check("write_instance_meta reports success",
      M.write_instance_meta(version_id, {"profile": "p2"}) is True)
check("its write is visible immediately",
      (M.read_instance_meta(version_id) or {}).get("profile") == "p2",
      str(M.read_instance_meta(version_id)))
check("an unsafe id still reads as None",
      M.read_instance_meta("../escape") is None)
check("an unknown instance reads as None",
      M.read_instance_meta("no-such-instance") is None)

# --- 7. the cache is bounded ----------------------------------------------
M._SIDECAR_CACHE.clear()
for i in range(M._SIDECAR_CACHE_MAX + 40):
    M._SIDECAR_CACHE[f"/nonexistent/{i}.json"] = ((i, i), {"i": i})
M._read_meta(profile, jar)          # one real read, triggers the cap
check("the cache stays bounded", len(M._SIDECAR_CACHE) <= M._SIDECAR_CACHE_MAX,
      f"{len(M._SIDECAR_CACHE)} entries")
check("a read after the cap still works",
      (M._read_meta(profile, jar) or {}).get("slug") == "sodium")

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
