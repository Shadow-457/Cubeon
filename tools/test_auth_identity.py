"""The player identity must survive a transient auth_key.json read failure (11.1).

Report: any OSError while reading auth_key.json (Windows antivirus/sync lock, a
bad byte) was treated like "no identity" - a NEW public_uuid + secret_token
were minted and the file overwritten. The uuid keys per-server data, skins and
the friends identity, so that silently changed who the player is.

Locked-in behaviour:
  1. a transient read OSError is retried 3x, then the session identity is used
     WITHOUT writing the file
  2. a readable-but-broken file is copied to auth_key.json.corrupt-<time>
     before being repaired
  3. two threads on a first start get ONE identity
  4. a failed write is retried with the same identity on the next call
  5. legacy {uuid, secret} files still migrate without changing either value

Run: python tools/test_auth_identity.py
"""
import glob
import json
import os
import stat
import sys
import tempfile
import threading
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home
_sandbox_home.isolate()

from cubeon import config  # noqa: E402  (after the env isolation)

passed = failed = 0
_REAL_PATH = config.AUTH_KEY_PATH


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


class Sandbox:
    def __init__(self):
        self.root = tempfile.mkdtemp(prefix="cubeon-auth-test-")
        self.path = os.path.join(self.root, "auth_key.json")
        config.AUTH_KEY_PATH = self.path

    def write(self, data):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(data)

    def read(self):
        with open(self.path, encoding="utf-8") as fh:
            return json.load(fh)

    def backups(self):
        return sorted(glob.glob(self.path + ".corrupt-*"))

    def close(self):
        config.AUTH_KEY_PATH = _REAL_PATH
        import shutil
        shutil.rmtree(self.root, ignore_errors=True)


def valid(identity):
    return (isinstance(identity, dict)
            and bool(config._UUID_RE.match(identity.get("public_uuid") or ""))
            and str(identity.get("secret_token") or "").startswith("sec_")
            and len(identity["secret_token"]) >= 16)


print("a missing file is created once and reused")
s = Sandbox()
try:
    first = config.ensure_auth_key()
    second = config.ensure_auth_key()
    check("a fresh identity is valid", valid(first), f"identity={first!r}")
    check("the second call returns the same identity", first == second)
    check("the file holds that identity", s.read() == first)
    check("the file is 0600", stat.S_IMODE(os.stat(s.path).st_mode) == 0o600)
    check("no temp files are left behind",
          not [n for n in os.listdir(s.root) if n.endswith(".tmp")],
          f"dir={os.listdir(s.root)}")
finally:
    s.close()

print("\ntwo threads on a first start mint ONE identity")
s = Sandbox()
try:
    out = []
    barrier = threading.Barrier(2)

    def work():
        barrier.wait()
        out.append(config.ensure_auth_key())

    threads = [threading.Thread(target=work), threading.Thread(target=work)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    check("both threads agree", len(out) == 2 and out[0] == out[1],
          f"out={out}")
    check("the file matches too", s.read() == out[0])
finally:
    s.close()

print("\na readable-but-broken file is backed up, not silently destroyed")
s = Sandbox()
try:
    s.write("{not json at all")
    identity = config.ensure_auth_key()
    check("a usable identity is returned", valid(identity), f"got={identity!r}")
    check("the broken file was copied aside", len(s.backups()) == 1,
          f"backups={s.backups()}")
    check("the repaired file is valid", s.read() == identity)
finally:
    s.close()

print("\ncorruption later in the session keeps the known identity")
s = Sandbox()
try:
    known = config.ensure_auth_key()
    s.write("garbage")
    again = config.ensure_auth_key()
    check("the identity does not change", again == known,
          f"before={known!r} after={again!r}")
    check("the file was backed up", len(s.backups()) == 1,
          f"backups={s.backups()}")
    check("the file was rewritten from the known identity", s.read() == known)
finally:
    s.close()

print("\na partial file keeps its valid half")
s = Sandbox()
try:
    good_uuid = "11111111-1111-4111-8111-111111111111"
    s.write(json.dumps({"public_uuid": good_uuid, "secret_token": "short"}))
    identity = config.ensure_auth_key()
    check("the uuid is preserved", identity["public_uuid"] == good_uuid,
          f"got={identity!r}")
    check("the missing secret is minted", valid(identity))
    check("the file holds both halves", s.read() == identity)
finally:
    s.close()

print("\na transient read OSError retries and never overwrites")
s = Sandbox()
try:
    known = config.ensure_auth_key()
    before = open(s.path, "rb").read()
    with patch.object(config.json, "load",
                      side_effect=OSError("file is locked")):
        with patch.object(config.time, "sleep") as sleep:
            again = config.ensure_auth_key()
    check("the session identity is returned", again == known,
          f"before={known!r} after={again!r}")
    check("the file is untouched", open(s.path, "rb").read() == before)
    check("the read was retried three times", sleep.call_count == 2,
          f"sleeps={sleep.call_count}")
finally:
    s.close()

print("\nunreadable with no cache: a session identity, still no overwrite")
s = Sandbox()
try:
    s.write('{"public_uuid": "locked-out"}')
    before = open(s.path, "rb").read()
    with patch.object(config.json, "load",
                      side_effect=OSError("file is locked")):
        with patch.object(config.time, "sleep"):
            identity = config.ensure_auth_key()
    check("a usable session identity is returned", valid(identity),
          f"got={identity!r}")
    check("nothing was written over the unreadable file",
          open(s.path, "rb").read() == before)
finally:
    s.close()

print("\na failed write keeps the same identity and is retried")
s = Sandbox()
try:
    with patch.object(config.os, "replace", side_effect=OSError("disk full")):
        first = config.ensure_auth_key()
    check("the identity is returned anyway", valid(first), f"got={first!r}")
    check("no file was published", not os.path.exists(s.path))
    second = config.ensure_auth_key()
    check("the next call keeps that identity", second == first,
          f"first={first!r} second={second!r}")
    check("and now persists it", s.read() == first)
finally:
    s.close()

print("\nlegacy {uuid, secret} files migrate without changing values")
s = Sandbox()
try:
    legacy_uuid = "22222222-2222-4222-8222-222222222222"
    legacy_secret = "sec_" + "a" * 64
    s.write(json.dumps({"uuid": legacy_uuid, "secret": legacy_secret}))
    identity = config.ensure_auth_key()
    check("uuid survives", identity["public_uuid"] == legacy_uuid,
          f"got={identity!r}")
    check("secret survives", identity["secret_token"] == legacy_secret,
          f"got={identity!r}")
    check("the file uses the new keys",
          s.read() == {"public_uuid": legacy_uuid,
                       "secret_token": legacy_secret})
    check("no spurious corrupt backup", s.backups() == [],
          f"backups={s.backups()}")
finally:
    s.close()

print()
print(f"{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
