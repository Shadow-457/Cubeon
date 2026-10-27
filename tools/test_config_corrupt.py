"""A broken config.json must not silently wipe every setting (11.2).

Before this fix load_config() fell back to defaults on JSONDecodeError/OSError,
and the next save_config() then replaced the user's real file (version labels,
last version, RAM, Java path, ...). OSError was the worst case: the file was
often still perfectly good, just briefly locked.

Locked-in behaviour:
  1. a readable-but-broken file is copied to config.json.corrupt-<time> first
     (at most three kept) and a warning is logged
  2. a transient read OSError is retried, then the last good config from this
     session is used - the file is NOT overwritten
  3. a missing file is still a clean first start (defaults, no backup)
  4. save_config() updates the in-memory last-good copy

Run: python tools/test_config_corrupt.py
"""
import glob
import json
import logging
import os
import shutil
import sys
import tempfile
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home
_sandbox_home.isolate()

from cubeon import config  # noqa: E402  (after the env isolation)

passed = failed = 0
_REAL_PATH = config.CONFIG_PATH


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


class Sandbox:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="cubeon-config-test-")
        self.path = os.path.join(self.root, "config.json")
        config.CONFIG_PATH = self.path
        config._LAST_GOOD_CONFIG = None

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(data)

    def read(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def backups(self):
        return sorted(glob.glob(self.path + ".corrupt-*"))

    def close(self):
        config.CONFIG_PATH = _REAL_PATH
        config._LAST_GOOD_CONFIG = None
        shutil.rmtree(self.root, ignore_errors=True)


class Capture(logging.Handler):
    def __init__(self):
        super().__init__()
        self.records = []

    def emit(self, record):
        self.records.append(record)


def capture_warnings():
    handler = Capture()
    logger = logging.getLogger("cubeon.config")
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    return handler, logger


print("a valid config is returned untouched")
s = Sandbox()
try:
    s.write(json.dumps({"username": "KeepMe", "ram_mb": 1234}))
    cfg = config.load_config()
    check("the user's values are loaded",
          cfg.get("username") == "KeepMe" and cfg.get("ram_mb") == 1234)
    check("no corrupt backup is made", s.backups() == [],
          f"backups={s.backups()}")
finally:
    s.close()

print("\nbroken JSON is backed up and warns instead of vanishing")
s = Sandbox()
try:
    s.write('{"username": "KeepMe", broken')
    handler, logger = capture_warnings()
    try:
        cfg = config.load_config()
    finally:
        logger.removeHandler(handler)
    check("the broken value is not used", cfg.get("username") != "KeepMe")
    check("a corrupt backup exists", len(s.backups()) == 1,
          f"backups={s.backups()}")
    check("the warning names the backup",
          any("corrupt" in r.getMessage() for r in handler.records),
          f"logs={[r.getMessage() for r in handler.records]}")
    check("the broken file itself is left for inspection",
          "broken" in open(s.path, encoding="utf-8").read())
finally:
    s.close()

print("\nvalid JSON that is not an object is treated the same way")
s = Sandbox()
try:
    s.write("[1, 2, 3]")
    cfg = config.load_config()
    check("a dict is returned", isinstance(cfg, dict))
    check("a corrupt backup exists", len(s.backups()) == 1,
          f"backups={s.backups()}")
finally:
    s.close()

print("\nat most three corrupt copies are kept")
s = Sandbox()
try:
    for _ in range(5):
        s.write("{broken")
        config.load_config()
    check("exactly three backups remain", len(s.backups()) == 3,
          f"backups={s.backups()}")
finally:
    s.close()

print("\na transient read OSError keeps the last good settings")
s = Sandbox()
try:
    s.write(json.dumps({"username": "LockedOut", "ram_mb": 3456}))
    first = config.load_config()
    before = open(s.path, "rb").read()
    with patch.object(config.json, "load",
                      side_effect=OSError("file is locked")):
        with patch.object(config.time, "sleep") as sleep:
            second = config.load_config()
    check("the last good config is returned",
          second.get("username") == "LockedOut"
          and second.get("ram_mb") == 3456,
          f"got={second!r}")
    check("it is the same dict content", second == first)
    check("the file is untouched", open(s.path, "rb").read() == before)
    check("the read was retried three times", sleep.call_count == 2,
          f"sleeps={sleep.call_count}")
finally:
    s.close()

print("\nunreadable with no last-good copy: defaults, file untouched")
s = Sandbox()
try:
    s.write(json.dumps({"username": "StillThere"}))
    before = open(s.path, "rb").read()
    with patch.object(config.json, "load",
                      side_effect=OSError("file is locked")):
        with patch.object(config.time, "sleep"):
            cfg = config.load_config()
    check("defaults are returned", cfg.get("username") != "StillThere")
    check("the file is untouched", open(s.path, "rb").read() == before)
    check("no corrupt backup (nothing was readable to copy)", s.backups() == [],
          f"backups={s.backups()}")
finally:
    s.close()

print("\na missing file is still a clean first start")
s = Sandbox()
try:
    cfg = config.load_config()
    check("defaults are returned", isinstance(cfg, dict))
    check("no backup", s.backups() == [], f"backups={s.backups()}")
finally:
    s.close()

print("\nsave_config updates the last-good copy")
s = Sandbox()
try:
    config.save_config({"username": "Saved", "ram_mb": 2048})
    with patch.object(config.json, "load",
                      side_effect=OSError("file is locked")):
        with patch.object(config.time, "sleep"):
            cfg = config.load_config()
    check("the saved settings are the fallback",
          cfg.get("username") == "Saved" and cfg.get("ram_mb") == 2048,
          f"got={cfg!r}")
finally:
    s.close()

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
