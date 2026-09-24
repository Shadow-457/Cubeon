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
import time
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
print("\nuid validation (the 8-digit chat identity)")
# --------------------------------------------------------------------------
check("accepts an 8-digit string", friends.canonical_uid("00000001") == "00000001")
check("accepts an int and zero-pads", friends.canonical_uid(1) == "00000001")
check("rejects too few digits", friends.canonical_uid("42") is None)
check("rejects too many digits", friends.canonical_uid("1" * 13) is None)
check("rejects letters", friends.canonical_uid("0000000a") is None)
check("rejects None / bool", friends.canonical_uid(None) is None
      and friends.canonical_uid(True) is None)
check("format_uid pads an int", friends.format_uid(7) == "00000007")
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
print("\nminecraft username validation helper")
# --------------------------------------------------------------------------
check("accepts a normal username", friends.minecraft_username("Steve") == "Steve")
check("accepts digits + underscore", friends.minecraft_username("Xx_Pro_99xX") == "Xx_Pro_99xX")
check("preserves case", friends.minecraft_username("BlueFox") == "BlueFox")
check("accepts min length", friends.minecraft_username("abc") == "abc")
check("accepts max length", friends.minecraft_username("a" * 16) == "a" * 16)
check("rejects too short", friends.minecraft_username("ab") == "")
check("rejects too long", friends.minecraft_username("a" * 17) == "")
check("rejects spaces", friends.minecraft_username("blue fox") == "")
check("rejects punctuation", friends.minecraft_username("blue.fox") == "")
check("rejects empty", friends.minecraft_username("") == "")
check("rejects None", friends.minecraft_username(None) == "")
check("rejects non-string", friends.minecraft_username(42) == "")


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
                       "uid": "00000042"})


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
      saved_id and saved_id.get("uid") == "00000042"
      and friends.current_uid() == "00000042")

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
print("\nminecraft username metadata (T_METADATA)")
# --------------------------------------------------------------------------
client2 = friends.FriendsClient()
client2._identity = friends.load_identity()
sent_meta = []


class _FakeWS2:
    def send(self, data):
        sent_meta.append(json.loads(data))

    def close(self):
        pass


client2._ws = _FakeWS2()
client2._connected.set()

check("set_minecraft_username rejects invalid values",
      client2.set_minecraft_username("no!") is False
      and client2.set_minecraft_username(None) is False
      and client2.set_minecraft_username("ab") is False)
check("rejected values send nothing", sent_meta == [])

check("set_minecraft_username accepts a valid username",
      client2.set_minecraft_username("Steve") is True)
for _ in range(400):
    if not client2._metadata_sending:
        break
    time.sleep(0.005)
check("T_METADATA frame sent for a valid username",
      any(m.get("t") == friends.T_METADATA and m.get("minecraft_username") == "Steve"
          for m in sent_meta))

steve_meta_frames = len([m for m in sent_meta if m.get("t") == friends.T_METADATA])
check("unchanged username skips the write", client2.set_minecraft_username("Steve") is True)
check("no duplicate frame for unchanged username",
      len([m for m in sent_meta if m.get("t") == friends.T_METADATA]) == steve_meta_frames)

client2._ws = None
check("set_minecraft_username with no socket still remembers the value",
      client2.set_minecraft_username("Alex") is True)
client2._ws = _FakeWS2()
check("reconnect replay publishes the remembered username", client2._on_open(client2._ws) is None)
check("hello carries the remembered username",
      sent_meta[-1].get("t") == friends.T_HELLO
      and sent_meta[-1].get("minecraft_username") == "Alex")

# Identity never changes due to a username edit: the hello name is the handle.
check("username edits never touch the routing handle",
      sent_meta[-1].get("name") == "BlueFox")


# --------------------------------------------------------------------------
print("\nroster peer metadata caching (offline labels)")
# --------------------------------------------------------------------------
client3 = friends.FriendsClient()
client3._identity = friends.load_identity()
received_meta = []
client3.on("metadata", lambda m: received_meta.append(m))

client3._on_message(client3._ws, json.dumps({
    "t": friends.T_ROSTER,
    "friends": [{"name": "Ruby", "uid": "00000002",
                 "minecraft_username": "RubyName", "online": True}],
    "requests_in": ["Player_99999999"],
    "requests_in_details": [{"name": "Player_99999999", "uid": "00000009",
                             "minecraft_username": "PendingGuy"}],
    "requests_out": [],
    "requests_out_details": [],
    "groups": [],
}))
meta = client3.roster.get("peer_metadata", {})
check("roster friend metadata cached by canonical handle",
      meta.get("ruby") == {"uid": "00000002", "minecraft_username": "RubyName"})
check("roster pending-request metadata cached",
      meta.get("player_99999999", {}).get("minecraft_username") == "PendingGuy")
check("rich request details retained on the roster",
      client3.roster.get("requests_in_details", [{}])[0].get("uid") == "00000009")
check("roster cached to disk with metadata",
      friends.load_cached_roster().get("peer_metadata", {}).get("ruby", {}).get("uid")
      == "00000002")

changed = []
client3.on("metadata", lambda m: changed.append(m))
client3._on_message(client3._ws, json.dumps({
    "t": friends.T_METADATA, "name": "Ruby", "uid": "00000002",
    "minecraft_username": "RenamedRuby"}))
check("metadata frame dispatched to handlers",
      changed and changed[-1].get("minecraft_username") == "RenamedRuby")
check("metadata frame merged into the cache before callbacks",
      client3.roster["peer_metadata"]["ruby"]["minecraft_username"] == "RenamedRuby")

# An unchanged metadata frame is a no-op repaint-wise (cache compare), but the
# event still fires - the server echoes it to every peer, dedupe is by value.
client3._on_message(client3._ws, json.dumps({
    "t": friends.T_METADATA, "name": "Ruby", "uid": "00000002",
    "minecraft_username": "RenamedRuby"}))
check("unchanged metadata frame leaves the cache identical",
      client3.roster["peer_metadata"]["ruby"]["minecraft_username"] == "RenamedRuby")

# Invalid payloads never poison the cache.
client3._on_message(client3._ws, json.dumps({"t": friends.T_METADATA, "name": "Ruby"}))
client3._on_message(client3._ws, json.dumps({"t": friends.T_METADATA, "minecraft_username": "x"}))
client3._on_message(client3._ws, "not json")
check("invalid/missing metadata frames cannot clear or corrupt the cache",
      client3.roster["peer_metadata"]["ruby"]["minecraft_username"] == "RenamedRuby"
      and client3.roster["peer_metadata"]["ruby"]["uid"] == "00000002")

client3._on_message(client3._ws, json.dumps({
    "t": friends.T_METADATA, "name": "Ruby", "uid": "00000002"}))
check("partial UID update preserves known username",
      client3.roster["peer_metadata"]["ruby"]["minecraft_username"] == "RenamedRuby")
client3._on_message(client3._ws, json.dumps({
    "t": friends.T_METADATA, "name": "Ruby", "minecraft_username": "NewestRuby"}))
check("partial username update preserves known UID",
      client3.roster["peer_metadata"]["ruby"] == {
          "uid": "00000002", "minecraft_username": "NewestRuby"})
presence_seen = []
client3.on("presence", lambda m: presence_seen.append(
    dict(next(f for f in client3.roster["friends"] if f["name"] == "Ruby"))))
client3._on_message(client3._ws, json.dumps({
    "t": friends.T_PRESENCE, "name": "ruby", "online": True,
    "version": "1.21.1", "status": "playing"}))
check("presence is merged before callbacks",
      presence_seen[-1]["online"] is True
      and presence_seen[-1]["version"] == "1.21.1")
client3._on_message(client3._ws, json.dumps({
    "t": friends.T_PRESENCE, "name": "Ruby", "online": False,
    "version": None, "status": None}))
check("offline presence clears playing fields explicitly",
      presence_seen[-1]["online"] is False
      and presence_seen[-1]["version"] is None
      and presence_seen[-1]["status"] is None)
check("presence changes persist to the roster cache",
      next(f for f in friends.load_cached_roster()["friends"]
           if f["name"] == "Ruby")["online"] is False)
friend_count = len(client3.roster["friends"])
client3._on_message(client3._ws, json.dumps({
    "t": friends.T_PRESENCE, "name": "UnknownPeer", "online": True}))
check("presence never creates a friendship",
      len(client3.roster["friends"]) == friend_count)

# Two accounts with identical usernames remain distinct accounts.
client3._on_message(client3._ws, json.dumps({
    "t": friends.T_ROSTER,
    "friends": [{"name": "Player_11111111", "uid": "00000001",
                 "minecraft_username": "Twin"},
                {"name": "Player_22222222", "uid": "00000002",
                 "minecraft_username": "Twin"}],
    "requests_in": [], "requests_in_details": [],
    "requests_out": [], "requests_out_details": [],
    "groups": [{"gid": "g_1", "name": "Room",
                "members": ["Player_11111111"],
                "member_details": [{"name": "Player_11111111",
                                    "uid": "00000001",
                                    "minecraft_username": "Twin"}]}],
}))
twin_meta = client3.roster["peer_metadata"]
check("duplicate usernames stay distinct accounts (handle-keyed cache)",
      twin_meta.get("player_11111111", {}).get("uid") == "00000001"
      and twin_meta.get("player_22222222", {}).get("uid") == "00000002"
      and twin_meta.get("player_11111111", {}).get("minecraft_username") == "Twin"
      and twin_meta.get("player_22222222", {}).get("minecraft_username") == "Twin")
check("group member_details feed the metadata cache",
      twin_meta.get("player_11111111", {}).get("minecraft_username") == "Twin")

# Legacy worker payloads (no metadata fields at all) keep working.
client3._on_message(client3._ws, json.dumps({
    "t": friends.T_ROSTER, "friends": [{"name": "OldWorker"}],
    "requests_in": [], "requests_out": [], "groups": []}))
check("older worker payload without metadata still caches",
      client3.roster["friends"][0]["name"] == "OldWorker"
      and "oldworker" not in client3.roster["peer_metadata"])


# --------------------------------------------------------------------------
print("\ndurable cancel: a declined request leaves the LOCAL roster too")
# --------------------------------------------------------------------------
# Until 2026-09-24 the deployed Worker kept a requester's outgoing row after
# their Cancel ("I cancelled it and it was still there after reopening").
# The Worker now deletes both directions, and on top of that a successful
# decline drops the name from the cached roster and persists it - so even a
# restart that paints from friends_cache.json before the first live roster
# cannot resurrect a cancelled request.
cancel_sent = []


class _FakeWSCancel:
    def send(self, data):
        cancel_sent.append(json.loads(data))

    def close(self):
        pass


cancel_client = friends.FriendsClient()
cancel_client._ws = _FakeWSCancel()
cancel_client.roster = {
    "friends": [],
    "requests_out": ["Ruby", "Dee"],
    "requests_in": ["Cara"],
    "requests_out_details": [{"name": "Ruby", "uid": "00000002"},
                             {"name": "Dee", "uid": "00000003"}],
    "requests_in_details": [{"name": "Cara", "uid": "00000004"}],
    "peer_metadata": {},
}
friends.save_cached_roster(cancel_client.roster)

check("decline_request sends the one DECLINE frame",
      cancel_client.decline_request("Ruby") is True
      and cancel_sent[-1] == {"t": friends.T_DECLINE, "name": "Ruby"})
check("a cancelled outgoing request leaves the live roster",
      cancel_client.roster["requests_out"] == ["Dee"]
      and [r["name"] for r in cancel_client.roster["requests_out_details"]]
      == ["Dee"])
check("the other direction's pending views are untouched",
      cancel_client.roster["requests_in"] == ["Cara"]
      and [r["name"] for r in cancel_client.roster["requests_in_details"]]
      == ["Cara"])
check("the removal is persisted for the next launch",
      friends.load_cached_roster().get("requests_out") == ["Dee"]
      and [r["name"] for r in friends.load_cached_roster()
           .get("requests_out_details", [])] == ["Dee"])

# Declining a name the roster never listed must not rewrite the cache.
_before = open(friends.ROSTER_CACHE_PATH, "rb").read()
cancel_client.decline_request("Nobody")
check("declining an unknown name leaves the cache alone",
      open(friends.ROSTER_CACHE_PATH, "rb").read() == _before)

# A frame that never left the socket must not touch the roster either.
cancel_client._ws = None
check("a decline with no socket reports failure",
      cancel_client.decline_request("Ruby") is False)
check("a failed decline keeps the roster intact",
      cancel_client.roster["requests_out"] == ["Dee"])


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

# The 8-digit ID format and its two wire paths (REST /uid/<n>, and `add {uid}`)
# must exist server-side too, or adding a friend by ID dies in production only.
check("worker mirrors the 8-digit uid format",
      "[0-9]{8}" in worker_src and "/uid/" in worker_src,
      "UID_RE / the /uid/ route is missing from the worker")
check("worker resolves an add-by-uid frame",
      "nameByUid" in worker_src and "msg.uid" in worker_src,
      "the worker's onAdd must accept {uid} as well as {name}")

# Username metadata parity: the T_METADATA frame must be handled server-side,
# persisted as a nullable column with no uniqueness constraint, replayed on
# hello, and fan-out to friends AND pending-request counterparts.
check("worker handles the T_METADATA frame",
      "METADATA" in worker_src and "onMetadata" in worker_src,
      "worker must handle the metadata frame")
check("worker persists minecraft_username as a nullable no-unique column",
      "minecraft_username TEXT" in worker_src,
      "worker must carry a nullable minecraft_username column")
check("worker skips unchanged metadata writes",
      "row.minecraft_username === username" in worker_src,
      "worker must compare before writing metadata")
check("worker notifies friends and pending counterparts of metadata changes",
      "broadcastMetadata" in worker_src and "FROM requests WHERE requester=? OR target=?" in worker_src,
      "metadata fan-out must include pending-request counterparts")
check("worker validates metadata with the username charset",
      "function minecraftUsername" in worker_src,
      "worker must validate minecraft_username")
check("worker enriches identity-bearing events with uid + username",
      "identityOf" in worker_src and "enrichIdentity" in worker_src,
      "worker must attach uid/minecraft_username to identity events")
check("worker keeps existing routing handles immutable",
      "UPDATE names SET minecraft_username=?" in worker_src,
      "metadata update must write only the username column")

# A refused DM must TELL the sender why (the UI renders optimistically and
# only confirms delivery on the echo - a silent drop looks like being ignored).
dm_error_codes = ["dm_bad_recipient", "dm_empty", "dm_not_friends"]
dm_missing = [c for c in dm_error_codes if c not in worker_src]
check("worker's onDm refuses with an error frame, not silence",
      all(c in worker_src for c in dm_error_codes) and "T.ERROR" in worker_src,
      f"missing DM refusal codes in worker: {dm_missing}")

# One DECLINE frame serves BOTH directions now: the receiver declining an
# incoming request, and the requester CANCELING their outgoing one (the Chat
# tab's Cancel button). The DELETE must cover both orderings or the cancel
# silently removes nothing on the server and the pending row comes back.
check("worker's decline removes the request in both directions",
      "(requester=? AND target=?) OR (requester=? AND target=?)"
      in worker_src,
      "onDecline must DELETE (other,me) OR (me,other) - a one-directional "
      "DELETE makes cancelling an outgoing request impossible")
check("client exposes a cancel path for outgoing requests",
      "Cancel" in open(os.path.join(PROJECT, "ui", "chat_tab.py"),
                       encoding="utf-8").read()
      and "service.decline" in open(os.path.join(PROJECT, "ui", "chat_tab.py"),
                                    encoding="utf-8").read(),
      "the outgoing row needs a Cancel affordance wired to service.decline")


# --------------------------------------------------------------------------
shutil.rmtree(_scratch, ignore_errors=True)
print(f"\n{passed} passed, {failed} failed")
sys.exit(1 if failed else 0)
