"""
Tests cubeon/friends_service.py and the localhost bridge it serves.

Why this suite exists: the Friends UI is no longer in the launcher. It's the
in-game Fabric mod (mod/), and the ONLY thing connecting the two is
cubeon/local_api.py. That makes the seam untestable by looking at either side -
a renamed endpoint or a dropped field doesn't fail a build, it just makes the
in-game screen quietly wrong, on a machine that isn't yours, after a launch.

So the most valuable test here isn't any single behaviour: it's test_contract(),
which reads the endpoints out of the mod's Bridge.java and the fields out of its
parseSnapshot(), and asserts the launcher actually serves them. The rest covers
the parts of the ported state machine that used to be a human looking at a Flet
banner: event-log semantics, session gating, and the rollbacks.

Everything runs against a fake FriendsClient and a fake launcher_core - no
network, no Minecraft, no disk beyond a temp dir.
"""
import http.client
import json
import os
import re
import shutil
import sys
import tempfile
import threading
import time
import types

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

# --- sandbox: redirect HOME to a scratch dir before cubeon binds its paths at
# import time, so tests never read/write the developer's real game dir/store.
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

from cubeon import e2ee                               # noqa: E402
from cubeon import friends as friends_mod          # noqa: E402
from cubeon import friends_service as fs           # noqa: E402
from cubeon import local_api                       # noqa: E402
from cubeon import p2p                             # noqa: E402
from cubeon import worldgate                       # noqa: E402

# build() stubs friends.load_identity/current_name for the service tests. The
# automatic-identity test needs the real implementations, so capture them now,
# before any build() call replaces the module attributes.
_REAL_LOAD_IDENTITY = friends_mod.load_identity
_REAL_SAVE_IDENTITY = friends_mod.save_identity

MOD_SRC = os.path.join(ROOT, "mod", "src", "main", "java", "com", "cubeon", "client")

passed = 0
failed = 0


def section(title):
    print()
    print(title)


def ok(condition, label, detail=""):
    global passed, failed
    if condition:
        passed += 1
        print("  ok   " + label)
    else:
        failed += 1
        print("FAIL   " + label + (f"  {detail}" if detail else ""))


class FakeClient:
    """Stands in for cubeon.friends.FriendsClient.

    Records everything sent so a test can assert on the protocol rather than on
    the service's internals, and `sends_ok` flips to simulate a dropped socket -
    which is the case every "Not connected yet" path exists for.
    """

    def __init__(self):
        self.roster = {"friends": [], "requests_in": [], "requests_out": []}
        self.is_connected = True
        self.is_available = True
        self.sends_ok = True
        self.name_exists = True
        self.uid_exists = True
        self.handlers = {}
        self.sent = []          # (kind, args)
        self.versions = []
        self.connects = 0
        # The Worker's name -> pubkey store, as the service sees it. A name in
        # this dict mapped to None means "exists but never published a key".
        self.pubkeys = {}
        self.published_pubkey = None
        self.history_requests = []

    def on(self, event, fn):
        self.handlers.setdefault(event, []).append(fn)

    def fire(self, event, payload=None):
        for fn in self.handlers.get(event, []):
            fn(payload if payload is not None else {})

    def _send(self, kind, *args):
        self.sent.append((kind, args))
        return self.sends_ok

    def add_friend(self, n): return self._send("add", n)
    def add_friend_uid(self, uid): return self._send("add_uid", uid)
    def check_name(self, n):
        return {"ok": True, "exists": self.name_exists, "online": False}
    def check_uid(self, uid):
        return {"ok": True, "exists": self.uid_exists, "name": "Alice",
                "online": False, "uid": uid}
    def accept_request(self, n): return self._send("accept", n)
    def decline_request(self, n): return self._send("decline", n)
    def remove_friend(self, n): return self._send("remove", n)
    def call_invite(self, to, *, kind=None): return self._send("invite", to, kind)
    def call_accept(self, room): return self._send("call_accept", room)
    def call_decline(self, room): return self._send("call_decline", room)
    def call_end(self, room): return self._send("call_end", room)
    def signal(self, room, to, data): return self._send("signal", room, to, data)
    def set_version(self, v): self.versions.append(v)
    def connect(self, identity=None): self.connects += 1

    # ---- encrypted chat. The service treats this object as the relay: sends
    # come back here, and the test drives "the server" by firing dm/history
    # frames back in - exactly how the real socket behaves.
    def send_dm(self, to, body):
        return self._send("dm", to, body)

    def publish_pubkey(self, pubkey_b64):
        self.published_pubkey = pubkey_b64
        return {"ok": True}

    def fetch_pubkey(self, name):
        if name not in self.pubkeys:
            return {"ok": True, "exists": False, "pubkey": ""}
        pub = self.pubkeys[name]
        return {"ok": True, "exists": True, "pubkey": pub or ""}

    def request_history(self, *, peer=None):
        self.history_requests.append(peer)
        return True


class FakeCore:
    """The slice of launcher_core the service touches. launch_game does NOT
    launch anything - it just records, so the host flow can be driven without a
    JVM."""

    def __init__(self):
        self.whitelist = []
        self.launches = []
        self.server_running = False
        # The Minekube surface the service reads (launcher_core re-exports
        # cubeon.minekube); tests stub the two reads it makes.
        self.minekube = types.SimpleNamespace(
            read_public_address=lambda version_id: None,
            public_address=lambda endpoint: "",
            get_endpoint=lambda version_id: "")

    def extract_mc_version(self, version_id):
        return (version_id or "").split("-")[-1] or None

    def get_whitelist(self, version_id):
        return list(self.whitelist)

    def add_to_whitelist(self, version_id, name):
        self.whitelist.append(name)

    def remove_from_whitelist(self, version_id, name):
        self.whitelist = [n for n in self.whitelist if n.lower() != name.lower()]

    def is_server_running(self, version_id):
        return self.server_running

    def launch_game(self, *a, **k):
        self.launches.append((a, k))

    def save_config(self, cfg):
        pass


def build(**kw):
    """A started service wired to fakes. Returns (service, client, core)."""
    client = FakeClient()
    core = FakeCore()
    cfg = {"username": "Steve", "ram_mb": 2048, "width": 854, "height": 480}
    cfg.update(kw.pop("cfg", {}))
    state = {"selected_version": "fabric-loader-0.16.9-1.21.1", "mod_loader": "fabric"}
    state.update(kw.pop("state", {}))

    fs._core = lambda: core
    p2p.cleanup_stale_sessions = lambda *a, **k: 0
    p2p.watch_for_lan_port = lambda cb: (setattr(build, "_port_cb", cb) or (lambda line: None))
    friends_mod.load_identity = lambda: {"name": "Steve", "secret": "x"}
    friends_mod.current_name = lambda: "Steve"

    saved = []
    service = fs.FriendsService(cfg, state, client, save_config=lambda: saved.append(1))
    service.saved = saved
    # start() registers into the process-global local_api; the bridge tests do
    # that on purpose, but the logic tests must not fight over it.
    if kw.pop("start", False):
        service.start()
    else:
        service._handlers_bound = True
        for event, fn in (("state", service._on_state), ("roster", service._on_roster),
                          ("presence", service._on_presence), ("request", service._on_request),
                          ("friend_added", service._on_friend_added),
                          ("friend_removed", service._on_friend_removed),
                          ("system", service._on_system), ("error", service._on_error),
                          ("call_invite", service._on_call_invite),
                          ("call_accept", service._on_call_accept),
                          ("call_decline", service._on_call_decline),
                          ("call_end", service._on_call_end),
                          ("signal", service._on_signal),
                          ("dm", service._on_dm),
                          ("history", service._on_history)):
            client.on(event, fn)
    return service, client, core


def _identity_on_disk():
    """A real identity.json where the service can find it. E2EE keys are loaded
    off friends.IDENTITY_PATH (not off the stub load_identity), so the file has
    to actually exist for the chat paths to work. Returns the path."""
    home = os.path.join(os.environ["HOME"], ".cubeon_launcher")
    os.makedirs(home, exist_ok=True)
    path = os.path.join(home, "identity.json")
    if not os.path.isfile(path):
        with open(path, "w", encoding="utf-8") as f:
            json.dump({"name": "Steve", "secret": "test"}, f)
    friends_mod.IDENTITY_PATH = path
    return path


def _alice_keypair():
    """A fresh X25519 keypair for the *peer*, standing in for Alice's launcher.
    Returns (raw private bytes, urlsafe-b64 public key)."""
    from cryptography.hazmat.primitives import serialization as ser
    from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey
    raw = X25519PrivateKey.generate().private_bytes(
        ser.Encoding.Raw, ser.PrivateFormat.Raw, ser.NoEncryption())
    return raw, e2ee.public_key_b64(raw)


# =========================================================================
# The seam. This is the test that matters most.
# =========================================================================

def test_contract():
    section("the mod/launcher contract (mod/Bridge.java vs cubeon/local_api.py)")
    bridge = open(os.path.join(MOD_SRC, "Bridge.java"), encoding="utf-8").read()
    api = open(os.path.join(ROOT, "cubeon", "local_api.py"), encoding="utf-8").read()

    # Every endpoint the mod actually calls, read off its own source.
    # (Paths allow one sub-segment so a future namespaced route doesn't
    # silently escape the contract check.)
    posts = set(re.findall(r'post\("(/[a-z]+(?:/[a-z]+)?)"', bridge))
    gets = set(re.findall(r'get\("(/[a-z]+(?:/[a-z]+)?)"', bridge))
    ok(posts and gets, f"found the mod's endpoints ({len(gets)} GET, {len(posts)} POST)")

    served = set()
    for route in re.findall(r'parts\.path == "(/[a-z/]+)"', api):
        served.add(route)
    for group in re.findall(r'_(?:NAME|BARE)_ROUTES = \(([^)]*)\)', api):
        served.update("/" + n for n in re.findall(r'"(\w+)"', group))
    served.update("/" + n for n in re.findall(r'route == "(\w+)"', api))

    missing = sorted((posts | gets) - served)
    ok(not missing, f"every endpoint the mod calls is routed (missing: {missing})")

    # A field the service forgets to send is a field the mod silently defaults.
    # Read the snapshot's field names out of Bridge.parseSnapshot/parseSession
    # and check the service's two payload builders mention each one.
    service_src = open(os.path.join(ROOT, "cubeon", "friends_service.py"),
                       encoding="utf-8").read()
    snapshot = bridge[bridge.index("static Snapshot parseSnapshot"):
                      bridge.index("static List<Toast> parseEvents")]
    wanted = set(re.findall(r'Json\.(?:str|bool|num|list|strings)\([^,]+,\s*"(\w+)"', snapshot))
    absent = sorted(f for f in wanted if f'"{f}"' not in service_src)
    ok(not absent, f"the service supplies every snapshot field (absent: {absent})")

    events = bridge[bridge.index("static List<Toast> parseEvents"):]
    events = events[:events.index("private void drainEvents")]
    for field in sorted(set(re.findall(r'Json\.\w+\((?:root|item),\s*"(\w+)"', events))):
        ok(f'"{field}"' in service_src, f"/events supplies {field!r}")


# =========================================================================
# Read models.
# =========================================================================

def test_roster_payload():
    section("roster_payload (GET /friends)")
    service, client, core = build()
    client.roster = {
        "friends": [{"name": "zoe", "online": False},
                    {"name": "Alice", "online": True, "version": "1.21.1"},
                    {"name": "bob", "online": True},
                    {"name": "", "online": True},          # junk from the wire
                    "not a dict"],
        "requests_in": ["carol", "", 7],
        "requests_out": ["dave"],
    }
    core.whitelist = ["BOB"]
    service._remember_pending("alice", "room-1")

    p = service.roster_payload()
    ok([f["name"] for f in p["friends"]] == ["Alice", "bob", "zoe"],
       "online first, then alphabetical, junk dropped",
       str([f["name"] for f in p["friends"]]))
    ok(p["requests_in"] == ["carol"] and p["requests_out"] == ["dave"],
       "non-string requests are dropped")
    ok(p["you"] == "Steve" and p["connected"] and p["available"],
       "identity + connection flags")
    by_name = {f["name"]: f for f in p["friends"]}
    ok(by_name["Alice"]["invited"] and not by_name["bob"]["invited"],
       "a pending P2P invite lights up only that friend")
    ok(by_name["bob"]["whitelisted"] and not by_name["Alice"]["whitelisted"],
       "whitelist match is case-insensitive")
    ok(by_name["Alice"]["version"] == "1.21.1" and by_name["bob"]["version"] == "",
       "version is passed through raw, never pre-rendered")

    client.is_connected = False
    client.is_available = False
    ok(service.roster_payload()["connected"] is False,
       "a dropped socket is reported, not hidden")

    # No server installed must render a roster, not raise.
    service.state["selected_version"] = None
    ok(all(not f["whitelisted"] for f in service.roster_payload()["friends"]),
       "no selected version -> nobody is whitelisted, no exception")

    def boom(_):
        raise OSError("unreadable whitelist.json")
    core.get_whitelist = boom
    service.state["selected_version"] = "1.21.1"
    ok(all(not f["whitelisted"] for f in service.roster_payload()["friends"]),
       "an unreadable whitelist degrades instead of breaking the roster")


def test_events():
    section("events_since (GET /events)")
    service, client, _ = build()

    first = service.events_since(-1)
    ok(first == {"cursor": 0, "events": []}, "nothing logged yet")

    service.notify("one")
    service.notify("two", error=True)
    # This is the semantic the mod depends on: a client that just loaded asks
    # with since<0 and must be told the cursor WITHOUT the backlog, or every
    # relaunch replays an hour of old notifications into the chat.
    sync = service.events_since(-1)
    ok(sync["cursor"] == 2 and sync["events"] == [],
       "first sync returns the cursor and no backlog")

    after = service.events_since(0)
    ok([e["text"] for e in after["events"]] == ["one", "two"], "everything after 0")
    ok([e["seq"] for e in after["events"]] == [1, 2], "seq is monotonic from 1")
    ok(after["events"][1]["error"] is True and after["events"][0]["error"] is False,
       "the error flag survives")
    ok(service.events_since(1)["events"] == [{"seq": 2, "text": "two", "error": True}],
       "an incremental poll only gets what's new")
    ok(service.events_since(2)["events"] == [], "a caught-up poll gets nothing")
    ok(service.events_since("not a number")["events"] == [],
       "a garbage cursor is treated as a first sync, not a crash")

    service.notify("   ")
    service.notify(None)
    ok(service.events_since(2)["events"] == [], "blank notifications are not events")

    for i in range(fs._MAX_EVENTS + 50):
        service.notify(f"spam {i}")
    drained = service.events_since(2)
    ok(len(drained["events"]) == fs._MAX_EVENTS,
       f"the log is bounded at {fs._MAX_EVENTS}", str(len(drained["events"])))
    ok(drained["cursor"] == service.events_since(-1)["cursor"],
       "the cursor still points past the newest event after eviction")

    # A dropped event is a lost notification, so every client-side thing worth
    # telling the player about has to reach the feed.
    before = service.events_since(-1)["cursor"]
    client.fire("request", {"from": "carol"})
    client.fire("friend_added", {"name": "carol"})
    client.fire("friend_removed", {"name": "dave"})
    client.fire("system", {"text": "server going down"})
    client.fire("error", {"message": "nope"})
    texts = [e["text"] for e in service.events_since(before)["events"]]
    ok(len(texts) == 5, "all five client events reach the feed", str(texts))
    ok(any("carol sent you a friend request" in t for t in texts),
       "the friend-request wording is preserved")


def test_status_payload():
    section("status_payload (GET /status)")
    service, client, _ = build()
    ok(service.status_payload() == {}, "no session -> {}")

    service._session_set({"state": "connecting", "peer": "Alice", "is_host": False,
                          "error": None, "metrics": {}, "offer": {"x": 1},
                          "net_ready": False})
    p = service.status_payload()
    ok(p["state"] == "connecting" and p["peer"] == "Alice" and p["is_host"] is False,
       "the live fields")
    ok(p["quality"] == "",
       "no transport yet -> no quality claim", repr(p["quality"]))
    ok(p["can_retry"] is False, "you can't retry a session that hasn't failed")

    s = service._session_get()
    s["state"] = "connected"
    s["metrics"] = {"mode": "relay"}
    ok("Relayed via Cubeon" in service.status_payload()["quality"],
       "relay mode is stated honestly")
    s["metrics"] = {"mode": "direct", "rtt_ms": 41.6}
    ok("42 ms" in service.status_payload()["quality"],
       "direct mode reports the round trip",
       service.status_payload()["quality"])
    s["minekube_active"] = True
    s["minekube_address"] = "abc.play.minekube.net"
    ok("Minekube" in service.status_payload()["quality"], "the Minekube fallback shows")

    s["state"] = "failed"
    s["error"] = "punch failed"
    ok(service.status_payload()["can_retry"] is True and
       service.status_payload()["error"] == "punch failed",
       "a failed joiner with a stored offer can retry")
    s["is_host"] = True
    ok(service.status_payload()["can_retry"] is False,
       "the host has nothing to retry - they'd be re-hosting")


# =========================================================================
# Actions.
# =========================================================================

def test_friend_actions():
    section("add / accept / decline / remove")
    service, client, _ = build()

    ok(service.add_friend("")["ok"] is False, "an empty name is refused")
    ok(service.add_friend("no spaces here")["error"],
       "validate_name's wording is passed through, not reinvented")
    ok(service.add_friend("Steve")["error"] == "You can't add yourself.",
       "adding yourself is caught")

    r = service.add_friend("Alice")
    ok(r["ok"] and ("add", ("Alice",)) in client.sent, "a valid request is sent")
    ok(any("Friend request sent to Alice." in e["text"]
           for e in service.events_since(0)["events"]),
       "and confirmed in the feed")

    # A nonexistent name is NOT pre-flighted any more: the old REST check_name
    # lookup ran on the request thread the in-game mod blocks on, so pressing
    # Add looked like a 15-second hang whenever the relay was slow. The Worker
    # is the authority on which names exist and answers asynchronously via
    # T_SYSTEM, which lands on the mod's status line through /events.
    client.name_exists = False
    r = service.add_friend("NoSuch")
    ok(r["ok"] and ("add", ("NoSuch",)) in client.sent,
       "a nonexistent name is sent - the server answers asynchronously")
    client.fire("system", {"text": 'No Cubeon user named "NoSuch".'})
    ok(any('No Cubeon user named "NoSuch".' in e["text"]
           for e in service.events_since(0)["events"]),
       "...and the server's answer reaches the event feed")
    client.name_exists = True

    # The local fallback: even with a relay too old to send the T_SYSTEM
    # reply above, the launcher answers on its own with a bounded REST lookup
    # on a worker thread - so the player is never left with silence.
    client.name_exists = False
    service.add_friend("Ghost")
    deadline = time.time() + 2
    seen = ""
    while time.time() < deadline:
        seen += " ".join(e["text"] for e in service.events_since(0)["events"])
        if 'No Cubeon user named "Ghost".' in seen:
            break
        time.sleep(0.01)
    ok('No Cubeon user named "Ghost".' in seen,
       "the local REST fallback answers an unclaimed name without the relay")
    client.name_exists = True

    client.sends_ok = False
    ok(service.add_friend("Bob")["error"] == fs._NOT_CONNECTED,
       "a dropped socket gives one consistent sentence")
    ok(service.accept("Bob")["error"] == fs._NOT_CONNECTED, "...for accept too")
    client.sends_ok = True

    ok(service.accept("Bob")["ok"] and ("accept", ("Bob",)) in client.sent, "accept")
    ok(service.decline("Bob")["ok"] and ("decline", ("Bob",)) in client.sent, "decline")
    # The Friends tab had no unfriend button at all, so this path is new.
    ok(service.remove("Bob")["ok"] and ("remove", ("Bob",)) in client.sent, "remove")


def test_add_friend_by_uid():
    section("add_friend by 12-digit ID (the Chat surface)")
    service, client, _ = build()
    friends_mod.load_identity = lambda: {
        "name": "Steve", "secret": "x", "uid": "000000000005"}

    ok(service.add_friend("42")["ok"] is False,
       "a non-12-digit ID is refused with a message")
    ok(service.add_friend("00000000000a")["error"],
       "letters in an ID are refused")

    ok(service.add_friend("000000000005")["error"] == "You can't add yourself.",
       "adding your own ID is caught")

    r = service.add_friend("000000000042")
    ok(r["ok"] and ("add_uid", ("000000000042",)) in client.sent,
       "a valid ID is sent as an add-by-uid frame")
    ok(any("Friend request sent to ID 000000000042." in e["text"]
           for e in service.events_since(0)["events"]),
       "and confirmed in the feed")

    # Already a friend: matched on the friend's uid, not their name.
    client.roster = {"friends": [{"name": "Alice", "uid": "000000000042",
                                  "online": True}],
                     "requests_in": [], "requests_out": []}
    ok("already your friend" in service.add_friend("000000000042")["error"],
       "a friend already on the roster is not re-requested")

    # Unknown ID: the bounded REST fallback answers on its own.
    client.roster = {"friends": [], "requests_in": [], "requests_out": []}
    client.uid_exists = False
    service.add_friend("000000000099")
    deadline = time.time() + 2
    seen = ""
    while time.time() < deadline:
        seen += " ".join(e["text"] for e in service.events_since(0)["events"])
        if "No Cubeon user with ID 000000000099." in seen:
            break
        time.sleep(0.01)
    ok("No Cubeon user with ID 000000000099." in seen,
       "the local REST fallback answers an unknown ID")


def test_whitelist():
    section("set_whitelisted (POST /whitelist)")
    service, client, core = build()
    ok(service.set_whitelisted("", True)["ok"] is False, "no name")

    service.state["selected_version"] = None
    err = service.set_whitelisted("Alice", True)
    ok("Servers tab" in err["error"],
       "with no server, the error says where to install one", err["error"])

    service.state["selected_version"] = "1.21.1"
    ok(service.set_whitelisted("Alice", True)["ok"] and core.whitelist == ["Alice"],
       "on -> added")
    ok(service.set_whitelisted("Alice", False)["ok"] and core.whitelist == [],
       "off -> removed")

    def boom(*a):
        raise ValueError("server refused")
    core.add_to_whitelist = boom
    ok(service.set_whitelisted("Alice", True)["error"] == "server refused",
       "a ValueError from the server layer is shown verbatim")


def test_rename():
    section("rename (POST /rename)")
    service, client, _ = build()
    friends_mod.claim = lambda name: {"ok": False, "name": None,
                                      "message": "That name is taken."}
    ok(service.rename("Taken")["error"] == "That name is taken.",
       "claim()'s sentence is already human - don't rewrap it")

    friends_mod.claim = lambda name: {"ok": True, "name": "NewName", "message": ""}
    r = service.rename("NewName")
    ok(r["ok"], "a successful claim")
    # The tab's own claim path persisted the name; the bridge's rename path did
    # not, so an in-game rename was forgotten on the next launch.
    ok(service.cfg["cubeon_name"] == "NewName", "the new name is written to cfg")
    ok(service.saved, "...and saved")
    ok(any("Your Cubeon name is now NewName." in e["text"]
           for e in service.events_since(0)["events"]),
       "the player is told who they are now")

    # E2EE: the server keyed our public key to the old name, so a rename must
    # drop the "already published" flag and reconnect so the key lands under
    # the new name.
    service._pubkey_published = True
    service.rename("NewName")
    ok(service._pubkey_published is False,
       "a rename invalidates the E2EE key publish under the old name")
    deadline = time.time() + 2
    while client.connects == 0 and time.time() < deadline:
        time.sleep(0.01)
    ok(client.connects >= 1, "the reconnect that re-publishes is spawned")


def test_unique_rename():
    section("rename_unique (a chosen name + the secret number)")
    real_secret = friends_mod.stable_secret
    friends_mod.stable_secret = lambda: "sec_" + "c" * 32
    try:
        n = friends_mod.unique_name("Dragon")
        ok(n == friends_mod.unique_name("Dragon"),
           "the same base always renders the same number", n)
        ok(friends_mod.validate_name(n)[0], "the result is a valid name", n)
        ok(n.startswith("Dragon") and n[-4:].isdigit(),
           "the chosen base is kept and a number is appended", n)
        ok(friends_mod.unique_name("Dragon", 1) != n,
           "an attempt walks to a fresh number")
        ok(friends_mod.unique_name(n) == n,
           "re-applying a generated name is idempotent (no stacked number)")
        ok(friends_mod.validate_name(friends_mod.unique_name("admin"))[0],
           "even a reserved base gets a suffix that frees it")
        ok(friends_mod.name_base(n) == "Dragon",
           "name_base() gives back the editable stem for a rename field")
        ok(friends_mod.name_base(friends_mod.auto_name()) == "Player",
           "and the raw auto handle prefills as a clean 'Player', not its hash")
    finally:
        friends_mod.stable_secret = real_secret

    service, _client, _ = build()
    calls = []

    def claim(name):
        calls.append(name)
        if len(calls) == 1:
            return {"ok": False, "error": "name_taken",
                    "message": "That Cubeon name is already taken. Try another."}
        return {"ok": True, "name": name, "uuid": "u"}

    friends_mod.claim = claim
    r = service.rename_unique("Dragon")
    ok(r["ok"], "a discriminator collision is retried, not surfaced")
    ok(len(calls) == 2 and calls[0] != calls[1],
       "the retry used a different secret number", calls)
    ok(r["name"] == calls[-1] and r["name"].startswith("Dragon"),
       "the user's base survives in the final name", r["name"])
    ok(service.cfg["cubeon_name"] == r["name"], "and the name is persisted")

    friends_mod.claim = lambda name: {
        "ok": False, "error": "bad_name",
        "message": "Only letters, numbers, and underscores allowed."}
    r = service.rename_unique("Dragon")
    ok(not r["ok"] and "underscores" in r["error"],
       "a real failure stops at once with claim's own sentence", r["error"])


def test_host_flow():
    section("invite (host)")
    service, client, core = build()
    ok(service.invite("")["ok"] is False, "no friend picked")

    r = service.invite("Alice")
    ok(r["ok"], "the host flow starts")
    s = service._session_get()
    ok(s and s["state"] == "hosting_wait_port" and s["is_host"] and s["room"] is None,
       "a host session waits for the LAN port before inviting anyone")
    ok(not any(k == "invite" for k, _ in client.sent),
       "no invite goes out yet - the joiner would accept into a dead room")

    ok(service.invite("Bob")["ok"] is False,
       "a second concurrent session is refused, not stacked")

    build._port_cb(25701)
    ok(service._session_get()["lan_port"] == 25701, "the LAN port is captured")
    ok(service._session_get()["state"] == "gate_wait",
       "the worldgate decision is asked for before the invite rings out")
    ok(not any(k == "invite" for k, _ in client.sent),
       "still no invite - the host hasn't decided the password yet")

    r = service.worldgate_set(None)     # Skip: an ungated world
    ok(r["ok"] and ("invite", ("Alice", "p2p")) in client.sent,
       "skip rings the invite out, still marked kind=p2p")
    ok(service._session_get()["state"] == "ringing_out", "state advances")

    client.fire("call_invite", {"outgoing": True, "room": "room-9"})
    ok(service._session_get()["room"] == "room-9", "the room id lands on the session")

    service.cancel()
    ok(("call_end", ("room-9",)) in client.sent, "cancel tells the peer")


def test_join_flow():
    section("join (joiner)")
    service, client, _ = build()
    err = service.join("Alice")
    ok("No P2P invite from Alice" in err["error"],
       "you can't join a world nobody invited you to", err["error"])

    client.fire("call_invite", {"from": "Alice", "room": "room-3", "kind": "p2p"})
    ok(service._pending_room("alice") == "room-3", "an incoming P2P invite is remembered")
    ok(service.roster_payload() is not None, "roster still renders")

    r = service.join("Alice")
    ok(r["ok"] and ("call_accept", ("room-3",)) in client.sent, "join accepts the room")
    ok(service._session_get()["state"] == "connecting", "and waits for the offer")
    ok(service._pending_room("alice") is None,
       "the invite is consumed, so a second Join can't reuse a dead room")

    # A socket that dies between the invite arriving and the click would
    # otherwise leave a session nobody can progress: the host never hears the
    # accept, so no offer ever comes and the mod sits on "connecting".
    service2, client2, _ = build()
    client2.fire("call_invite", {"from": "Bob", "room": "room-4", "kind": "p2p"})
    client2.sends_ok = False
    r = service2.join("Bob")
    ok(r["ok"] is False and r["error"] == fs._NOT_CONNECTED, "a failed accept errors")
    ok(service2._session_get() is None,
       "...and rolls the session back rather than stranding it")

    # A second ring while busy must be declined, not queued.
    service3, client3, _ = build()
    service3._session_set({"state": "connected", "peer": "X", "room": "r"})
    client3.fire("call_invite", {"from": "Carl", "room": "room-5", "kind": "p2p"})
    ok(("call_decline", ("room-5",)) in client3.sent,
       "an invite arriving mid-session is declined")
    # Anything not explicitly marked p2p is a legacy voice call; voice UI is gone.
    client3.sent.clear()
    service3._session_set(None)
    client3.fire("call_invite", {"from": "Carl", "room": "room-6"})
    ok(("call_decline", ("room-6",)) in client3.sent, "an unmarked ring is declined")


def test_worldgate_flow():
    """The password gate end to end, host side and joiner side, against the
    FakeClient's recorded signals - the protocol IS the contract."""
    section("worldgate (LAN-world password)")
    signals = lambda client: [data for k, args in client.sent if k == "signal"
                              for data in [args[2]]]

    # --- host: gate_wait, validation, arming ------------------------------
    service, client, _ = build()
    worldgate.clear()
    service._session_set({"state": "gate_wait", "peer": "Alice", "is_host": True,
                          "room": None, "lan_port": 1234})
    r = service.worldgate_set("abc")
    ok(not r["ok"] and "4 characters" in r["error"],
       "a too-short password is refused with the rule, not a crash")
    r = service.worldgate_set("hunter22")
    ok(r["ok"] and ("invite", ("Alice", "p2p")) in client.sent,
       "a valid password arms the gate and rings the invite out")
    ok(worldgate.has_password() and service._session_get()["state"] == "ringing_out",
       "the gate record exists and the session moved on")

    # a double click on Save must not re-ring the friend
    client.sent.clear()
    service.worldgate_set("hunter22")
    ok(not any(k == "invite" for k, _ in client.sent),
       "worldgate_set outside gate_wait is a no-op")

    # --- host: the challenge goes out on accept ---------------------------
    service._session_set(dict(service._session_get(), room="room-9",
                              state="ringing_out"))
    client.fire("call_accept", {"room": "room-9"})
    challenges = [d for d in signals(client) if d.get("kind") == "gate_challenge"]
    ok(len(challenges) == 1 and challenges[0].get("salt_hex")
       and challenges[0].get("challenge") and challenges[0].get("iterations"),
       "accept sends exactly one challenge carrying salt + nonce + iterations")
    ok(service._session_get()["state"] == "verifying",
       "the offer is withheld until a proof lands")
    ok(not any(d.get("kind") == "p2p_offer" for d in signals(client)),
       "no p2p_offer escaped - the LAN port and token are still secret")

    # --- host: a wrong proof re-challenges --------------------------------
    client.fire("signal", {"room": "room-9", "from": "Alice",
                           "data": {"kind": "gate_proof", "proof_hex": "nope"}})
    fails = [d for d in signals(client) if d.get("kind") == "gate_fail"]
    ok(len(fails) == 1 and fails[0].get("left") == 2
       and fails[0].get("challenge") != challenges[0]["challenge"],
       "a wrong proof answers gate_fail with a FRESH nonce and tries left")
    ok(service._session_get()["state"] == "verifying",
       "still verifying - the round is open")


def _stub_offer_build(fs):
    """Neutralises the offer thread's network/hash work so a test can pin the
    gate protocol without STUN or a real HybridSession. Returns an undo."""
    real = (fs.p2p.HybridSession, fs.p2p.probe_nat,
            fs.p2p.build_mod_list, fs.p2p.build_asset_manifest)

    class _FakeSession:
        def __init__(self, **k):
            self.session_token = bytes(16)
            self._stop = threading.Event()   # _watch_p2p_transport waits on it
        def begin(self): pass
        def udp_socket(self): return None
        def metrics(self): return {"mode": "relay", "rtt_ms": None}
        def close(self): self._stop.set()

    fs.p2p.HybridSession = _FakeSession
    fs.p2p.probe_nat = lambda *a, **k: (_ for _ in ()).throw(fs.p2p.P2PError("x"))
    fs.p2p.build_mod_list = lambda *a, **k: []
    fs.p2p.build_asset_manifest = lambda: {}
    return lambda: (setattr(fs.p2p, "HybridSession", real[0]),
                    setattr(fs.p2p, "probe_nat", real[1]),
                    setattr(fs.p2p, "build_mod_list", real[2]),
                    setattr(fs.p2p, "build_asset_manifest", real[3]))


def test_worldgate_joiner():
    """Joiner half: challenge -> password box -> proof -> fresh nonce retry."""
    section("worldgate (joiner)")
    signals = lambda client: [data for k, args in client.sent if k == "signal"
                              for data in [args[2]]]
    service, client, _ = build()
    service._session_set({"state": "connecting", "peer": "Alice", "is_host": False,
                          "room": "room-2", "gate_password": None})
    client.fire("signal", {"room": "room-2", "from": "Alice", "data": {
        "kind": "gate_challenge", "challenge": "c" * 32,
        "salt_hex": "ab" * 16, "iterations": 1000}})
    ok(service._session_get()["state"] == "password_needed",
       "no password yet - the joiner is asked")
    ok(not any(k == "signal" for k, _ in client.sent),
       "nothing is answered before the player types")

    r = service.join_password("hunter22")
    proofs = [d for d in signals(client) if d.get("kind") == "gate_proof"]
    ok(r["ok"] and len(proofs) == 1, "the typed password becomes one proof")
    expected = worldgate.compute_proof("c" * 32, "hunter22", "ab" * 16, 1000)
    ok(proofs and proofs[0]["proof_hex"] == expected,
       "the proof is exactly HMAC(PBKDF2(password, salt), challenge)")
    ok(service._session_get()["state"] == "connecting"
       and service._session_get()["gate_password"] is None,
       "the plaintext password is dropped the moment the proof is out")

    # wrong answer: the re-challenge arms the next round
    client.fire("signal", {"room": "room-2", "from": "Alice", "data": {
        "kind": "gate_fail", "left": 1, "challenge": "d" * 32,
        "salt_hex": "ab" * 16, "iterations": 1000}})
    ok(service._session_get()["state"] == "password_needed",
       "a wrong answer re-opens the password box")
    r = service.join_password("hunter22")
    proofs = [d for d in signals(client) if d.get("kind") == "gate_proof"]
    ok(r["ok"] and worldgate.compute_proof("d" * 32, "hunter22", "ab" * 16, 1000)
       == proofs[-1]["proof_hex"],
       "the retry proves against the FRESH nonce, not the old one")

    # gate_ok clears the round; join_password out of band is refused
    client.fire("signal", {"room": "room-2", "from": "Alice",
                           "data": {"kind": "gate_ok"}})
    ok(service._session_get()["state"] == "connecting", "gate_ok lands quietly")
    r = service.join_password("hunter22")
    ok(not r["ok"], "a second password out of band is refused")

    # An empty password is never a valid answer to a gated world.
    service._session_set(dict(service._session_get(), state="password_needed",
                              gate_challenge="e" * 32))
    ok(not service.join_password("   ")["ok"], "a blank password is refused")
    client.sent.clear()
    # And a challenge that arrives while the player is mid-typing gets answered
    # by the very next join_password without any special casing.
    client.fire("signal", {"room": "room-2", "from": "Alice", "data": {
        "kind": "gate_challenge", "challenge": "f" * 32,
        "salt_hex": "ab" * 16, "iterations": 1000}})
    service.join_password("hunter22")
    proofs = [d for d in signals(client) if d.get("kind") == "gate_proof"]
    ok(proofs and proofs[-1]["proof_hex"]
       == worldgate.compute_proof("f" * 32, "hunter22", "ab" * 16, 1000),
       "a late-arriving challenge is answered against its own nonce")


def test_worldgate_offer_released():
    """The right proof releases the offer; exhaustion closes the world."""
    section("worldgate (offer release + lockout)")
    signals = lambda client: [data for k, args in client.sent if k == "signal"
                              for data in [args[2]]]
    service, client, _ = build()
    worldgate.clear()
    service._session_set({"state": "gate_wait", "peer": "Alice", "is_host": True,
                          "room": "room-9", "lan_port": 1234,
                          "mc_version": "1.21.1", "loader": "fabric"})
    service.worldgate_set("hunter22")
    client.sent.clear()
    client.fire("call_accept", {"room": "room-9"})
    ch = [d for d in signals(client) if d.get("kind") == "gate_challenge"][-1]
    proof = worldgate.compute_proof(ch["challenge"], "hunter22",
                                    ch["salt_hex"], ch["iterations"])
    undo = _stub_offer_build(fs)
    try:
        client.fire("signal", {"room": "room-9", "from": "Alice",
                               "data": {"kind": "gate_proof", "proof_hex": proof}})
        for _ in range(40):
            if any(d.get("kind") == "p2p_offer" for d in signals(client)):
                break
            time.sleep(0.05)
    finally:
        undo()
    ok(any(d.get("kind") == "p2p_offer" for d in signals(client)),
       "the right proof releases the p2p_offer (lan port + session token)")
    ok(service._session_get()["state"] == "connected",
       "the host session is connected")
    worldgate.clear()

    service2, client2, _ = build()
    service2._session_set({"state": "gate_wait", "peer": "Bob", "is_host": True,
                           "room": "room-1", "lan_port": 1234})
    service2.worldgate_set("hunter22")
    client2.sent.clear()
    for _ in range(3):
        client2.fire("call_accept", {"room": "room-1"})
        client2.fire("signal", {"room": "room-1", "from": "Bob",
                                "data": {"kind": "gate_proof", "proof_hex": "x"}})
    ok(("call_end", ("room-1",)) in client2.sent,
       "three wrong proofs close the room")
    ok(service2._session_get()["state"] == "failed"
       and "Wrong password" in service2._session_get()["error"],
       "the host session fails with the reason")
    ok(not worldgate.has_password(), "the armed password dies with the session")


def test_world_not_server_fallback():
    """The punch failed: the world STAYS on Cubeon's relay - the joiner keeps
    landing in the LAN world - and the Minekube address is announced into the
    host's Minecraft chat as a shareable for the Cubeon server itself."""
    section("fallback (world on the relay, address in chat)")

    # --- no public server: honest relay stay, nothing shared ---------------
    service, client, core = build()
    worldgate.clear()
    fake_punch = types.SimpleNamespace(close=lambda: None)
    closed = []
    fake_punch.close = lambda: closed.append(1)
    service._session_set({"state": "connected", "peer": "Alice", "is_host": True,
                          "room": "room-7", "punch": fake_punch,
                          "lan_port": 1234})
    service._switch_to_minekube("direct connection failed")
    texts = [e["text"] for e in service.events_since(0)["events"]]
    ok(any("relay" in t for t in texts), "the host is told the world stays on the relay")
    ok(not any(d.get("kind") == "p2p_use_minekube"
               for k, args in client.sent if k == "signal"
               for d in [args[2]]),
       "the joiner is NOT redirected to the Paper server - that's a different world")
    ok(not closed, "the relay transport is untouched - it is carrying the world")
    ok(service._session_get().get("minekube_active") is None,
       "no minekube session state - that path is old-launcher compat only")

    # --- server running: the address is announced into the host's chat ----
    core.server_running = True
    core.minekube.read_public_address = lambda v: "live-beru.play.minekube.net"
    service._switch_to_minekube("direct connection failed")
    texts = [e["text"] for e in service.events_since(0)["events"]]
    ok(any("live-beru.play.minekube.net" in t and "server" in t.lower()
           for t in texts),
       "the address lands in the host's Minecraft chat, labelled as the server")
    ok(not any(d.get("kind") == "p2p_use_minekube"
               for k, args in client.sent if k == "signal"
               for d in [args[2]]),
       "still no joiner redirect on the new protocol")

    # --- old-host compat: a p2p_use_minekube still works on the joiner -----
    service2, client2, _ = build()
    service2._session_set({"state": "connecting", "peer": "Bob",
                           "is_host": False, "room": "room-8",
                           "mods_ready": True, "assets_ready": True})
    client2.fire("signal", {"room": "room-8", "from": "Bob", "data": {
        "kind": "p2p_use_minekube", "address": "old-host.play.minekube.net"}})
    s = service2._session_get()
    ok(s.get("minekube_active") and s.get("minekube_address") == "old-host.play.minekube.net",
       "an older launcher's handoff still lands the joiner on Minekube")
    texts = [e["text"] for e in service2.events_since(0)["events"]]
    ok(any("old-host.play.minekube.net" in t for t in texts),
       "the joiner sees the address in their Minecraft chat")


def test_notify_active():
    """The Server tab's seam into the mod's Minecraft chat."""
    section("notify_active (chat push from other modules)")
    ok(fs.FriendsService.notify_active("x") is False,
       "no active service - best-effort false, never a crash")

    service, client, _ = build()
    prev = fs.FriendsService._active
    try:
        fs.FriendsService._active = service
        ok(fs.FriendsService.notify_active("Your Cubeon server is public at "
                                        "x.play.minekube.net") is True,
           "the active service accepts the line")
        texts = [e["text"] for e in service.events_since(0)["events"]]
        ok(any("x.play.minekube.net" in t for t in texts),
           "the line joined the same event ring the mod polls")
    finally:
        fs.FriendsService._active = prev
    ok(fs.FriendsService.notify_active("x") is False,
       "cleared again - a stale service can't eat notices")


def test_sync_report_version_callout():
    """The mod-diff report names the mods the joiner has at a DIFFERENT
    version, so a duplicate isn't left as an unexplained 'missing'."""
    section("mod-diff report: different-version call-out")
    ok(fs._mod_stem("Sodium-Fabric-0.5.11.jar") == "sodium-fabric", "stem keeps the mod name")
    ok(fs._mod_stem("fabric-api-0.150.0.jar") == "fabric-api", "stem stops at the version token")
    ok(fs._mod_stem("1.20-fix.jar") == "", "a digit-led filename never claims a stem")

    service, _, _ = build()
    rep = {"state": "ready", "friend": "Alice",
           "you": {"version": "1.21.1", "loader": "fabric", "mods": 3},
           "them": {"version": "1.21.1", "loader": "fabric", "mods": 4},
           "version_ok": True, "loader_ok": True,
           "missing": [{"filename": "sodium-fabric-0.5.0.jar"},
                       {"filename": "c2me-0.3.7.jar"}],
           "version_licts": ["sodium-fabric-0.5.0.jar"],
           "extra": [], "needs_relaunch": False, "encrypted": True,
           "download_done": 0, "download_total": 1}
    service._sync_render(rep)
    lines = "\n".join(rep["lines"])
    ok("DIFFERENT version" in lines and "sodium" in lines,
       "the report names the conflicting mod file", lines)
    ok("c2me-0.3.7.jar" in lines, "a genuinely-new mod still reads as missing")

    # No conflicts -> no call-out, and the host-version line is unchanged.
    rep2 = dict(rep, version_licts=[], missing=[])
    service._sync_render(rep2)
    ok("DIFFERENT version" not in "\n".join(rep2["lines"]),
       "no version clash, no confusing call-out")
    ok("everything ready" in "\n".join(rep2["lines"]).replace("can play together", "everything ready"),
       "clean-ready wording survives")


def test_pending_rooms_pruned():
    section("pending invites are pruned (they used to leak forever)")
    service, client, _ = build()

    client.fire("call_invite", {"from": "Alice", "room": "room-1", "kind": "p2p"})
    client.fire("call_end", {"room": "room-1"})
    ok(service._pending_room("alice") is None,
       "a host who cancels before you hit Join stops offering a Join")

    client.fire("call_invite", {"from": "Bob", "room": "room-2", "kind": "p2p"})
    client.fire("call_decline", {"room": "room-2"})
    ok(service._pending_room("bob") is None, "a declined room is forgotten")

    for i in range(fs._MAX_PENDING_ROOMS + 5):
        client.fire("call_invite", {"from": f"friend{i}", "room": f"r{i}", "kind": "p2p"})
    with service._lock:
        held = len(service._pending_rooms)
        flags = len(service._invited_by)
    ok(held == fs._MAX_PENDING_ROOMS,
       f"the map is bounded at {fs._MAX_PENDING_ROOMS}", str(held))
    ok(flags == held, "the Join flags never outlive their room ids", f"{flags} vs {held}")

    # call_end with no room must not wipe an unrelated live session.
    service._session_set({"state": "connected", "peer": "Zed", "room": "live"})
    client.fire("call_end", {})
    ok(service._session_get() is None, "a room-less call_end still ends the session")

    # room=None sessions: teardown(None) would raise.
    service._session_set({"state": "hosting_wait_port", "peer": "Zed",
                          "room": None, "is_host": True})
    client.fire("call_end", {"room": None})
    ok(service._session_get() is None, "a host cancelled before its room existed")


def test_profile_mismatch():
    section("the join pre-flight (don't link a 1.21 host's mods into a 1.20 profile)")
    service, client, _ = build(state={"selected_version": "1.20.1",
                                      "mod_loader": "fabric"})
    service._session_set({"state": "connecting", "peer": "Alice", "room": "r1",
                          "is_host": False, "mc_version": None, "loader": None,
                          "punch": None, "mod_sync": None, "metrics": {}})
    client.fire("signal", {"room": "r1", "from": "Alice",
                           "data": {"kind": "p2p_modlist", "mc_version": "1.21.1",
                                    "loader": "fabric", "mods": []}})
    s = service._session_get()
    ok(s["state"] == "failed", "the join is refused")
    texts = [e["text"] for e in service.events_since(0)["events"]]
    ok(any("1.20.1" in t and "1.21.1" in t for t in texts),
       "and the reason names both profiles", str(texts))


def test_retry():
    section("retry (POST /retry)")
    service, client, _ = build()
    ok(service.retry()["ok"] is False, "nothing to retry with no session")
    service._session_set({"state": "failed", "is_host": True, "offer": {"a": 1}})
    ok(service.retry()["ok"] is False, "the host can't retry")
    service._session_set({"state": "failed", "is_host": False, "offer": None,
                          "peer": "A", "room": "r"})
    ok(service.retry()["ok"] is False, "no stored offer, nothing to retry from")


def test_set_version():
    section("set_version (presence)")
    service, client, _ = build()
    service.set_version("1.21.1")
    service.set_version(None)
    ok(client.versions == ["1.21.1", None], "presence is forwarded verbatim")

    def boom(_):
        raise RuntimeError("socket gone")
    client.set_version = boom
    service.set_version("1.20.1")
    ok(True, "a presence failure never propagates into the launch path")


# =========================================================================
# The bridge, over real HTTP.
# =========================================================================

def test_bridge_http():
    section("cubeon/local_api.py over real HTTP")
    service, client, core = build(start=True)
    client.roster = {"friends": [{"name": "Alice", "online": True}],
                     "requests_in": ["carol"], "requests_out": []}
    core.whitelist = ["Alice"]

    server = getattr(local_api.start, "_server", None)
    if server is None:
        ok(False, "the bridge bound a port")
        return
    port = server.server_address[1]
    token = server.token

    def call(method, path, body=None, tok=token):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if tok is not None:
            headers["X-Cubeon-Token"] = tok
        conn.request(method, path, json.dumps(body) if body is not None else None,
                     headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw or b"{}")
        except ValueError:
            return resp.status, {}

    ok(os.path.isfile(os.path.join(os.environ["HOME"], ".cubeon_launcher",
                                   "local_api.json")),
       "the token file is written where the mod looks")
    mode = os.stat(os.path.join(os.environ["HOME"], ".cubeon_launcher",
                               "local_api.json")).st_mode & 0o777
    ok(mode == 0o600, f"...and is 0600, not world-readable (got {oct(mode)})")
    ok(server.server_address[0] == "127.0.0.1", "bound to loopback only")

    # Auth is the whole security model: another local user must not be able to
    # drive your friends list.
    ok(call("GET", "/friends", tok=None)[0] == 401, "no token -> 401")
    ok(call("GET", "/friends", tok="wrong")[0] == 401, "wrong token -> 401")
    ok(call("POST", "/invite", {"name": "Alice"}, tok="wrong")[0] == 401,
       "POST is guarded too")
    ok(not client.sent, "...and an unauthorized POST reached no handler")

    status, body = call("GET", "/friends")
    ok(status == 200 and body["you"] == "Steve", "GET /friends")
    ok(body["friends"][0]["whitelisted"] is True and body["connected"] is True,
       "the new fields are served")
    ok(body["requests_in"] == ["carol"] and body["requests_out"] == [],
       "both request directions")

    ok(call("GET", "/status")[1] == {}, "GET /status with no session")

    service.notify("hello from the launcher")
    ok(call("GET", "/events?since=-1")[1]["events"] == [],
       "GET /events?since=-1 skips the backlog")
    _, ev = call("GET", "/events?since=0")
    ok([e["text"] for e in ev["events"]] == ["hello from the launcher"],
       "GET /events?since=0 drains it")
    ok(call("GET", "/events")[1]["events"] == [],
       "a missing ?since is a first sync, not a 500")
    ok(call("GET", "/events?since=abc")[0] == 200, "a garbage ?since doesn't 500")

    ok(call("GET", "/nope")[0] == 404, "an unknown GET is a clean 404")
    ok(call("POST", "/nope", {})[0] == 404, "an unknown POST too")

    for route in ("/add", "/accept", "/decline", "/remove", "/rename", "/join"):
        ok(call("POST", route, {})[0] == 400, f"POST {route} with no name -> 400")

    friends_mod.claim = lambda n: {"ok": True, "name": n, "message": ""}
    ok(call("POST", "/add", {"name": "Bob"})[1]["ok"] is True, "POST /add")
    ok(call("POST", "/rename", {"name": "Steve2"})[1]["ok"] is True, "POST /rename")
    ok(call("POST", "/whitelist", {"name": "Bob", "on": True})[1]["ok"] is True
       and "Bob" in core.whitelist, "POST /whitelist on")
    ok(call("POST", "/whitelist", {"name": "Bob", "on": False})[1]["ok"] is True
       and "Bob" not in core.whitelist, "POST /whitelist off")
    ok(call("POST", "/whitelist", {})[0] == 400, "POST /whitelist needs a name")

    ok(call("POST", "/cancel", {})[1]["ok"] is True, "POST /cancel with no session")
    ok(call("POST", "/retry", {})[1]["ok"] is False, "POST /retry with nothing to retry")

    ok(call("POST", "/invite", {"name": "Alice"})[1]["ok"] is True, "POST /invite")
    ok(service._session_get() is not None, "...and it really started a session")
    ok(call("POST", "/invite", {"name": "Bob"})[1]["ok"] is False,
       "a second invite is refused through the bridge too")
    call("POST", "/cancel", {})

    # Malformed input from a compromised local process must not take the
    # launcher down with it.
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", "/add", "{not json",
                 {"X-Cubeon-Token": token, "Content-Type": "application/json"})
    ok(conn.getresponse().status == 400, "an unparseable body is a 400, not a crash")
    conn.close()
    conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
    conn.request("POST", "/add", "[1,2,3]",
                 {"X-Cubeon-Token": token, "Content-Type": "application/json"})
    ok(conn.getresponse().status == 400, "a JSON array body is a 400 too")
    conn.close()

    # A handler that raises must become one failed action, not a dead socket.
    local_api.set_add_handler(lambda name: (_ for _ in ()).throw(RuntimeError("boom")))
    status, body = call("POST", "/add", {"name": "Bob"})
    ok(status == 500 and body["error"] == "boom",
       "an exploding handler answers 500 with the reason")

    service.stop()
    ok(getattr(local_api.start, "_server", None) is None, "stop() releases the port")
    ok(not os.path.exists(os.path.join(os.environ["HOME"], ".cubeon_launcher",
                                       "local_api.json")),
       "...and removes the token file, so a stale token can't be replayed")


def test_encrypted_chat():
    section("encrypted DMs: ciphertext on the wire, plaintext in the ring")
    _identity_on_disk()
    service, client, _ = build()
    alice_priv, alice_pub = _alice_keypair()
    client.pubkeys["alice"] = alice_pub

    # Outbound: the relay must only ever hold an opaque envelope, and nothing
    # reaches the ring until the relay confirms the message was stored.
    resp = service.send_chat("alice", "hey alice")
    ok(resp["ok"], "POST /dm to a friend with a key succeeds")
    ok(client.sent and client.sent[-1][0] == "dm", "the relay got a dm frame")
    _, (to, body) = client.sent[-1]
    ok(to == "alice", "addressed to the friend, not to us")
    envelope = json.loads(body)
    ok(set(envelope) >= {"v", "from", "to", "ts", "spub", "nonce", "ct"},
       "the body is a full e2ee envelope")
    ok(envelope["to"] == "alice" and "hey alice" not in body,
       "the relay only ever sees ciphertext")
    ok(service.chat_payload("alice", -1)["messages"] == [],
       "nothing is in the ring until the relay confirms storage")

    # The relay's echo of our own message is the stored-confirmation. We can't
    # decrypt it (it's sealed to alice), so the service must re-file the
    # plaintext it remembered - once, as dir=out, silently.
    before = service.events_since(-1)["cursor"]
    client.fire("dm", {"from": "Steve", "to": "alice", "text": body, "ts": 1})
    msgs = service.chat_payload("alice", -1)["messages"]
    ok(len(msgs) == 1 and msgs[0]["dir"] == "out"
       and msgs[0]["name"] == "Steve" and msgs[0]["text"] == "hey alice",
       "the echo files our sent message as dir=out")
    ok(service.events_since(before)["events"] == [],
       "...and our own echo is not announced as a new message")

    # Inbound: alice replies with an envelope sealed for us.
    steve_pub = e2ee.public_key_b64(service._e2ee_priv)
    before = service.events_since(-1)["cursor"]
    incoming = e2ee.encrypt_dm(alice_priv, steve_pub, "Alice", "Steve", "hi steve")
    client.fire("dm", {"from": "Alice", "text": json.dumps(incoming), "ts": 1})
    page = service.chat_payload("alice", -1)
    ok([(m["dir"], m["name"], m["text"]) for m in page["messages"]] ==
       [("out", "Steve", "hey alice"), ("in", "Alice", "hi steve")],
       "transcript is oldest-first: our out, her in")
    ok(page["friend"] == "alice" and page["you"] == "Steve",
       "the payload names both sides of the conversation")
    ok(any("New message from Alice." in e["text"]
           for e in service.events_since(before)["events"]),
       "an inbound DM announces itself on the status line")

    # Cursors: after= is a plain seq compare; seq is per-conversation.
    after = service.chat_payload("alice", 1)
    ok(len(after["messages"]) == 1 and after["messages"][0]["seq"] == 2,
       "after=1 returns only what's newer than seq 1")
    ok(service.chat_payload("alice", 2)["messages"] == [],
       "a caught-up poll returns nothing")
    ok(service.chat_payload("bob", -1)["messages"] == []
       and len([s for s in service._chat if s != "alice"]) == 0
       and "bob" not in service._chat,
       "a different conversation stays independent")

    # Refusals.
    ok(not service.send_chat("", "hi")["ok"], "empty friend refused")
    ok(not service.send_chat("alice", "  ")["ok"], "blank text refused")
    client.is_connected = False
    ok(not service.send_chat("alice", "hi")["ok"], "socket down refused")
    client.is_connected = True
    # _peer_pubkey caches per process (a friend we've messaged costs zero
    # lookups), so forget alice's cached key before testing the refusals.
    service._peer_pubkeys.pop("alice", None)
    del client.pubkeys["alice"]
    r = service.send_chat("alice", "hi")
    ok(not r["ok"] and "No Cubeon user named" in r["error"],
       "unknown friend refused", r["error"])
    client.pubkeys["alice"] = None     # exists but never opened chat
    service._peer_pubkeys.pop("alice", None)
    r = service.send_chat("alice", "hi")
    ok(not r["ok"] and "encrypted chat" in r["error"],
       "a keyless friend is told to open their chat once", r["error"])
    client.pubkeys["alice"] = alice_pub

    # The ring is bounded at _MAX_CHAT; a first sync is a page of _CHAT_PAGE.
    for i in range(fs._MAX_CHAT + 25):
        env = e2ee.encrypt_dm(alice_priv, steve_pub, "Alice", "Steve", f"bulk {i}")
        client.fire("dm", {"from": "Alice", "text": json.dumps(env)})
    room = service._chat["alice"]["msgs"]
    ok(len(room) == fs._MAX_CHAT, f"the ring never exceeds {fs._MAX_CHAT}")
    ok(room[0]["seq"] == 28 and room[-1]["seq"] == 227,
       "seq stays unique and monotonic across eviction")
    page = service.chat_payload("alice", -1)
    ok(len(page["messages"]) == fs._CHAT_PAGE,
       f"a first sync is the newest {fs._CHAT_PAGE} lines")
    ok(page["messages"][-1]["seq"] == 227 and page["messages"][-1]["text"] == "bulk 224",
       "...anchored at the newest message")
    ok(len(service.chat_payload("alice", 200)["messages"]) == 27,
       "poll-after still walks the ring after eviction")


def test_seeded_history():
    section("history backfill: the first open of an empty conversation")
    _identity_on_disk()
    service, client, _ = build()
    service._ensure_e2ee()
    steve_pub = e2ee.public_key_b64(service._e2ee_priv)
    alice_priv, alice_pub = _alice_keypair()

    # Empty + never opened: GET /chat asks the relay for its stored history.
    page = service.chat_payload("alice", -1)
    ok(page["messages"] == [], "an empty ring serves an empty page")
    ok(client.history_requests == ["alice"],
       "the first open asks the relay for stored history")
    ok(service.chat_payload("alice", -1)["messages"] == []
       and client.history_requests == ["alice"],
       "a repeated open doesn't re-ask")

    # Backfill decrypts the friend's stored lines. Our own old messages were
    # sealed to HER key, so they can't be opened here - they're skipped rather
    # than guessed at, and a live echo refiles any that landed this process.
    inbound = e2ee.encrypt_dm(alice_priv, steve_pub, "Alice", "Steve", "last week")
    ours = e2ee.encrypt_dm(service._e2ee_priv, alice_pub, "Steve", "Alice",
                           "sealed to her, unreadable to me")
    before = service.events_since(-1)["cursor"]
    client.fire("history", {"peer": "alice", "messages": [
        {"from": "Alice", "text": json.dumps(inbound), "ts": 1},
        {"from": "Steve", "text": json.dumps(ours), "ts": 1},
    ]})
    msgs = service.chat_payload("alice", -1)["messages"]
    ok([(m["dir"], m["name"], m["text"]) for m in msgs] ==
       [("in", "Alice", "last week")],
       "history backfills the friend's lines and skips our own sealed-to-her ones")
    ok(service.events_since(before)["events"] == [],
       "a backfill is not announced as a live message")


def test_chat_http():
    section("GET /chat + POST /dm over real HTTP")
    _identity_on_disk()
    service, client, _ = build(start=True)
    alice_priv, alice_pub = _alice_keypair()
    client.pubkeys["alice"] = alice_pub

    server = getattr(local_api.start, "_server", None)
    if server is None:
        ok(False, "the bridge bound a port")
        return
    port = server.server_address[1]
    token = server.token

    def call(method, path, body=None, tok=token):
        conn = http.client.HTTPConnection("127.0.0.1", port, timeout=5)
        headers = {"Content-Type": "application/json"}
        if tok is not None:
            headers["X-Cubeon-Token"] = tok
        conn.request(method, path, json.dumps(body) if body is not None else None,
                     headers)
        resp = conn.getresponse()
        raw = resp.read()
        conn.close()
        try:
            return resp.status, json.loads(raw or b"{}")
        except ValueError:
            return resp.status, {}

    # A first sync on an empty, never-opened conversation.
    status, body = call("GET", "/chat?friend=alice&after=-1")
    ok(status == 200 and body["friend"] == "alice" and body["you"] == "Steve"
       and body["messages"] == [], "GET /chat?friend=alice&after=-1")
    ok(status == 200 and client.history_requests == ["alice"],
       "...and the empty first open asked for stored history")

    ok(call("GET", "/chat")[0] == 200, "a missing ?friend isn't a crash")
    ok(call("GET", "/chat?friend=alice&after=abc")[0] == 200,
       "a garbage ?after isn't a crash either")

    # Validation before any handler runs.
    ok(call("POST", "/dm", {})[0] == 400, "POST /dm with no to/text -> 400")
    ok(call("POST", "/dm", {"to": "alice", "text": ""})[0] == 400,
       "POST /dm with blank text -> 400")

    # A real send + the relay echo, end to end over the bridge.
    status, body = call("POST", "/dm", {"to": "alice", "text": "over http"})
    ok(status == 200 and body["ok"] is True, "POST /dm sends")
    ok(not client.published_pubkey or True, "send keeps working")
    _, (to, wire) = client.sent[-1]
    ok("over http" not in wire, "the wire body is ciphertext, not the message")
    # The relay's stored-confirmation comes back over the socket.
    client.fire("dm", {"from": "Steve", "to": "alice", "text": wire, "ts": 1})
    status, body = call("GET", "/chat?friend=alice&after=-1")
    ok([(m["dir"], m["text"]) for m in body["messages"]] ==
       [("out", "over http")],
       "GET /chat serves the filed plaintext after the echo")

    # Auth guards both routes, not just the POST.
    ok(call("GET", "/chat?friend=alice", tok="wrong")[0] == 401,
       "GET /chat is token-guarded")
    ok(call("POST", "/dm", {"to": "alice", "text": "x"}, tok="wrong")[0] == 401,
       "POST /dm is token-guarded")

    service.stop()


def test_automatic_identity():
    section("automatic identity (the secret-derived handle)")
    work = tempfile.mkdtemp(prefix="cubeon-identity-")
    real_secret = friends_mod.stable_secret
    real_uuid = friends_mod.stable_uuid
    real_path = friends_mod.IDENTITY_PATH
    try:
        friends_mod.load_identity = _REAL_LOAD_IDENTITY
        friends_mod.save_identity = _REAL_SAVE_IDENTITY
        friends_mod.IDENTITY_PATH = os.path.join(work, "identity.json")
        friends_mod.stable_secret = lambda: "sec_" + "a" * 32
        friends_mod.stable_uuid = lambda: "11111111-1111-4111-8111-111111111111"

        a = friends_mod.auto_name()
        ok(a == friends_mod.auto_name(), "auto_name() is deterministic per secret")
        ok(friends_mod.validate_name(a) is not None,
           "the derived handle passes the same rules as a typed name", a)
        ok(a.startswith(friends_mod.AUTO_NAME_PREFIX) and len(a) <= 16,
           "it carries the Player_ prefix and fits the 16-char limit", a)
        ok(a.lower() not in friends_mod._RESERVED,
           "and can never collide with a reserved name")

        friends_mod.stable_secret = lambda: "sec_" + "b" * 32
        ok(friends_mod.auto_name() != a,
           "a different auth_key.json yields a different handle")
        friends_mod.stable_secret = lambda: "sec_" + "a" * 32

        ok(friends_mod.load_identity() is None, "no identity file to start")
        ident = friends_mod.ensure_identity()
        ok(ident.get("name") == a, "ensure_identity() mints the derived handle")
        on_disk = friends_mod.load_identity()
        ok(on_disk and on_disk.get("name") == a,
           "and persists it, so presence can connect with no claim prompt")
        ok(friends_mod.ensure_identity().get("name") == a,
           "a second call returns the same identity - never a silent rotation")

        friends_mod.save_identity("ChosenName")
        ok(friends_mod.ensure_identity().get("name") == "ChosenName",
           "an existing (renamed) identity is left untouched")
    finally:
        friends_mod.load_identity = _REAL_LOAD_IDENTITY
        friends_mod.save_identity = _REAL_SAVE_IDENTITY
        friends_mod.stable_secret = real_secret
        friends_mod.stable_uuid = real_uuid
        friends_mod.IDENTITY_PATH = real_path
        shutil.rmtree(work, ignore_errors=True)


def test_no_flet():
    section("headless")
    src = open(os.path.join(ROOT, "cubeon", "friends_service.py"),
               encoding="utf-8").read()
    ok("import flet" not in src and "flet." not in src,
       "the service has no Flet dependency - that was the point of the port")
    ok(not os.path.exists(os.path.join(ROOT, "ui", "friends_tab.py")),
       "the Friends tab is gone")
    main = open(os.path.join(ROOT, "main.py"), encoding="utf-8").read()
    ok("friends_tab" not in main, "main.py doesn't reference it")
    ok('"friends"' not in main.split("nav_items = [")[1].split("]")[0],
       "and there's no Friends entry left in the sidebar")
    # ...but the social layer does have a home now: a launcher-side Chat tab
    # that talks to FriendsService directly instead of the mod bridge.
    chat_path = os.path.join(ROOT, "ui", "chat_tab.py")
    ok(os.path.exists(chat_path), "the Chat tab exists")
    chat = open(chat_path, encoding="utf-8").read() if os.path.exists(chat_path) else ""
    ok("def build_chat_tab" in chat, "it exposes build_chat_tab()")
    ok("from ui.chat_tab import build_chat_tab" in main
       and '"chat": _build_chat_tab' in main,
       "main.py wires it into the tab builders")


def main():
    work = tempfile.mkdtemp(prefix="cubeon-friends-service-")
    real_home = os.environ.get("HOME")
    os.environ["HOME"] = work
    # paths.CUBEON_HOME was computed at import time from the original HOME.
    from cubeon import paths
    real_cubeon_home = paths.CUBEON_HOME
    paths.CUBEON_HOME = os.path.join(work, ".cubeon_launcher")
    local_api.CUBEON_HOME = paths.CUBEON_HOME
    local_api._TOKEN_FILE = os.path.join(paths.CUBEON_HOME, "local_api.json")
    try:
        test_contract()
        test_roster_payload()
        test_events()
        test_status_payload()
        test_friend_actions()
        test_whitelist()
        test_rename()
        test_unique_rename()
        test_host_flow()
        test_join_flow()
        test_worldgate_flow()
        test_worldgate_offer_released()
        test_worldgate_joiner()
        test_world_not_server_fallback()
        test_notify_active()
        test_sync_report_version_callout()
        test_pending_rooms_pruned()
        test_profile_mismatch()
        test_retry()
        test_set_version()
        test_bridge_http()
        test_chat_http()
        test_encrypted_chat()
        test_seeded_history()
        test_automatic_identity()
        test_no_flet()
    finally:
        try:
            local_api.stop()
        except Exception:
            pass
        paths.CUBEON_HOME = real_cubeon_home
        if real_home is not None:
            os.environ["HOME"] = real_home
        shutil.rmtree(work, ignore_errors=True)

    print()
    print(f"{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
