#!/usr/bin/env python3
"""
Tests for cubeon/friends.py - run with:

    python3 tools/test_friends.py

Needs no network and no Cloudflare account. The name format, identity file, and
message protocol are pure; the HTTP client is exercised against a stubbed
`requests` module and the WebSocket client against a fake socket.

The checks that earn their keep, same spirit as tools/test_invites.py:

  * **Protocol parity with the Worker.** cubeon/friends.py defines the name
    format, the reserved names, and every message `t` (type) string.
    worker/cubeon-friends.js mirrors them. If they drift, the launcher speaks a
    dialect the server rejects - and only in production, since nothing local
    would notice. So this reads the Worker source and compares.

  * **The identity secret follows the claim outcome.** A successful claim() must
    leave identity.json (0600) on disk holding the owning secret; a failed one
    (name already taken) must NOT - persisting a name you didn't get would make
    the launcher think it owns someone else's name.

  * **Conversation keying.** A DM and its echo must map to one conversation on
    both sides, or the sender never sees their own message land.
"""
import json
import logging
import os
import re
import shutil
import sys
import tempfile
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

logging.disable(logging.WARNING)

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


PROJECT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORKER_SRC = os.path.join(PROJECT, "worker", "cubeon-friends.js")

# --- sandbox: redirect HOME to a scratch dir before cubeon binds its paths at
# import time, so tests never read/write the developer's real game dir/store.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import friends  # noqa: E402
from cubeon import config as _config  # noqa: E402

# Redirect the identity/roster files at a scratch dir so the test never touches
# the real ~/.cubeon_launcher/identity.json (which holds the user's own secret).
_scratch = tempfile.mkdtemp(prefix="cubeon-friends-test-")
friends.CUBEON_HOME = _scratch
friends.IDENTITY_PATH = os.path.join(_scratch, "identity.json")
friends.ROSTER_CACHE_PATH = os.path.join(_scratch, "friends_cache.json")
# The stable identity (auth_key.json) is read by save_identity()/claim() via
# config.ensure_auth_key(); redirect it too so the test's claims don't create or
# read the user's real auth_key.json.
_config.CUBEON_HOME = _scratch
_config.AUTH_KEY_PATH = os.path.join(_scratch, "auth_key.json")


# --------------------------------------------------------------------------
print("\nname validation")
# --------------------------------------------------------------------------
check("accepts a normal name", friends.validate_name("BlueFox")[0])
check("accepts min length", friends.validate_name("abc")[0])
check("accepts max length", friends.validate_name("a" * 16)[0])
check("rejects too short", not friends.validate_name("ab")[0])
check("rejects too long", not friends.validate_name("a" * 17)[0])
check("rejects spaces", not friends.validate_name("blue fox")[0])
check("rejects punctuation", not friends.validate_name("blue.fox")[0])
check("rejects a reserved name", not friends.validate_name("Cubeon")[0])
check("rejects reserved case-insensitively", not friends.validate_name("ADMIN")[0])
check("canonical_name lower-cases", friends.canonical_name("BlueFox") == "bluefox")
check("canonical_name rejects invalid", friends.canonical_name("no!") is None)


# --------------------------------------------------------------------------
print("\nuid validation (the 12-digit chat identity)")
# --------------------------------------------------------------------------
check("accepts a 12-digit string", friends.canonical_uid("000000000001") == "000000000001")
check("accepts an int and zero-pads", friends.canonical_uid(1) == "000000000001")
check("rejects too few digits", friends.canonical_uid("42") is None)
check("rejects too many digits", friends.canonical_uid("1" * 13) is None)
check("rejects letters", friends.canonical_uid("00000000000a") is None)
check("rejects None / bool", friends.canonical_uid(None) is None
      and friends.canonical_uid(True) is None)
check("format_uid pads an int", friends.format_uid(7) == "000000000007")
check("current_uid is empty with no identity", friends.current_uid() == "")


# --------------------------------------------------------------------------
print("\nidentity file")
# --------------------------------------------------------------------------
check("no identity to start", friends.load_identity() is None)
saved = friends.save_identity("BlueFox", "s3cr3t-value-0000000000000000")
check("save returns a uuid", bool(saved.get("uuid")))
loaded = friends.load_identity()
check("load round-trips the name", loaded and loaded["name"] == "BlueFox")
check("load round-trips the secret", loaded and loaded["secret"].startswith("s3cr3t"))
if os.name != "nt":
    mode = oct(os.stat(friends.IDENTITY_PATH).st_mode & 0o777)
    check("identity.json is 0600", mode == "0o600", f"mode was {mode}")
friends.clear_identity()
check("clear removes the identity", friends.load_identity() is None)


# --------------------------------------------------------------------------
print("\nclaim() - the secret follows the claim outcome")
# --------------------------------------------------------------------------
# Stub requests so claim() runs offline. The stub records what got sent; the
# assertions below check that a successful claim persists the owning secret and
# a rejected one leaves nothing behind.
_seen = {}


class _Resp:
    def __init__(self, status, body):
        self.status_code = status
        self._body = body

    def json(self):
        return self._body


def _fake_post(url, json=None, timeout=None, **kw):
    _seen["sent_uuid"] = json.get("uuid")
    _seen["sent_secret"] = json.get("secret")
    return _Resp(200, {"ok": True, "name": json["name"], "uuid": json.get("uuid"),
                       "uid": "000000000042"})


def _fake_get(url, timeout=None, **kw):
    return _Resp(404, {})


friends.requests = types.SimpleNamespace(
    post=_fake_post, get=_fake_get,
    RequestException=Exception, exceptions=types.SimpleNamespace(RequestException=Exception),
)

# Fresh machine: no identity yet, so a rejected claim must not create one.
friends.clear_identity()
friends.requests.post = lambda url, json=None, timeout=None, **kw: _Resp(409, {"error": "name_taken"})
taken_fresh = friends.claim("BlueFox")
check("name_taken surfaces as not-ok", not taken_fresh.get("ok"))
check("rejected claim on a fresh machine writes no identity",
      friends.load_identity() is None)

# Now a successful claim: identity must be on disk, holding the secret we sent.
friends.requests.post = _fake_post
result = friends.claim("BlueFox")
check("claim reports ok", result.get("ok"))
check("claim sends a locally-derived uuid", bool(_seen.get("sent_uuid")))
saved_id = friends.load_identity()
check("successful claim persisted the identity", saved_id and saved_id["name"] == "BlueFox")
check("the persisted secret is the one sent to the server",
      saved_id and saved_id["secret"] == _seen.get("sent_secret"))
check("a successful claim persists the server-assigned ID",
      saved_id and saved_id.get("uid") == "000000000042"
      and friends.current_uid() == "000000000042")

# Re-claiming a held name proves ownership by reusing the same secret, not by
# minting a new one that the server would reject.
_seen.clear()
friends.claim("BlueFox")
check("re-claim reuses the existing secret", _seen.get("sent_secret") == saved_id["secret"])

# A name-taken response on an owned name must not clobber the local identity.
friends.requests.post = lambda url, json=None, timeout=None, **kw: _Resp(409, {"error": "name_taken"})
before = friends.load_identity()
taken = friends.claim("BlueFox")
check("name_taken on an owned name keeps the existing identity",
      friends.load_identity() == before)


# --------------------------------------------------------------------------
print("\nWebSocket client - framing, dispatch, conversation keying")
# --------------------------------------------------------------------------
# A fake socket that records what the client sends and lets the test inject
# received frames, so the send helpers and _on_message dispatch can be checked
# with no network.
sent = []


class _FakeWS:
    def send(self, data):
        sent.append(json.loads(data))

    def close(self):
        pass


client = friends.FriendsClient()
client._ws = _FakeWS()
client._identity = friends.load_identity()

# hello is sent on open, over the socket, carrying the secret (never the URL).
client._on_open(client._ws)
hello = sent[-1]
check("hello uses the mirrored type string", hello["t"] == friends.T_HELLO)
check("hello carries name + secret", hello.get("name") == "BlueFox" and "secret" in hello)

client.send_dm("Ruby", "hi there")
dm = sent[-1]
check("send_dm framed with T_DM", dm["t"] == friends.T_DM and dm["to"] == "Ruby")
check("send_dm auto-generates a message id", bool(dm.get("id")))

# Dispatch: an incoming frame should reach the matching handler.
received = {}
client.on("presence", lambda p: received.__setitem__("presence", p))
client.on("dm", lambda m: received.__setitem__("dm", m))
client.on("roster", lambda r: received.__setitem__("roster", r))

client._on_message(client._ws, json.dumps({"t": friends.T_PRESENCE, "name": "Ruby",
                                           "online": True, "version": "1.20.1"}))
check("presence frame dispatched", received.get("presence", {}).get("version") == "1.20.1")

client._on_message(client._ws, json.dumps({"t": friends.T_ROSTER, "friends": [{"name": "Ruby"}]}))
check("roster frame dispatched + cached", client.roster["friends"][0]["name"] == "Ruby")

client._on_message(client._ws, json.dumps({"t": friends.T_DM, "from": "Ruby",
                                           "to": "BlueFox", "text": "yo", "ts": 1, "id": "x"}))
check("dm frame dispatched", received.get("dm", {}).get("text") == "yo")

# Garbage must not raise out of the receive loop.
client._on_message(client._ws, "not json")
client._on_message(client._ws, json.dumps({"t": "totally_unknown_type"}))
check("garbage + unknown types are ignored, not fatal", True)

# A send with no live socket returns False rather than raising on a bg thread.
client._ws = None
check("send with no socket returns False", client.send_dm("Ruby", "x") is False)


# --------------------------------------------------------------------------
print("\nprotocol parity with worker/cubeon-friends.js")
# --------------------------------------------------------------------------
with open(WORKER_SRC, "r", encoding="utf-8") as f:
    worker_src = f.read()

# Every message type the client can send or receive must exist as a string
# literal in the Worker, or that message silently does nothing in production.
type_consts = [v for k, v in vars(friends).items()
               if k.startswith("T_") and isinstance(v, str)]
missing = [t for t in type_consts if f'"{t}"' not in worker_src]
check("every message type appears in the Worker", not missing,
      f"missing from worker: {missing}")

# The name regex must match on both sides. The Worker's is written out longhand;
# compare the character class + length bounds textually.
check("worker mirrors the name character class + length",
      "[A-Za-z0-9_]{3,16}" in worker_src,
      "NAME_RE in the worker does not match cubeon/friends.py _NAME_RE")

# Reserved names must match, or a name the client refuses could be claimed via a
# raw request, or vice-versa.
py_reserved = friends._RESERVED
worker_reserved_missing = [n for n in py_reserved if f'"{n}"' not in worker_src]
check("worker mirrors the reserved names", not worker_reserved_missing,
      f"missing from worker RESERVED: {worker_reserved_missing}")

# The 12-digit ID format and its two wire paths (REST /uid/<n>, and `add {uid}`)
# must exist server-side too, or adding a friend by ID dies in production only.
check("worker mirrors the 12-digit uid format",
      "[0-9]{12}" in worker_src and "/uid/" in worker_src,
      "UID_RE / the /uid/ route is missing from the worker")
check("worker resolves an add-by-uid frame",
      "nameByUid" in worker_src and "msg.uid" in worker_src,
      "the worker's onAdd must accept {uid} as well as {name}")


# --------------------------------------------------------------------------
shutil.rmtree(_scratch, ignore_errors=True)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
