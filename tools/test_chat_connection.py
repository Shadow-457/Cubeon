"""Chat startup/reconnect races, timeout budgets and encryption publication."""
import json
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__), os.path.dirname(os.path.dirname(__file__))]
import _sandbox_home
_sandbox_home.isolate()
from cubeon import friends, e2ee
from cubeon.friends_service import FriendsService


def check(label, value):
    assert value, label
    print("  ok  " + label)


identity = friends.ensure_identity()
real_timer = threading.Timer


class HeldSocket:
    instances = []

    def __init__(self, url, **callbacks):
        self.callbacks = callbacks
        self.entered = threading.Event()
        self.release = threading.Event()
        self.sent = []
        self.instances.append(self)

    def send(self, data):
        self.sent.append(json.loads(data))

    def close(self):
        pass  # simulate a slow close from the replaced loop

    def run_forever(self, **kwargs):
        self.callbacks["on_open"](self)
        self.entered.set()
        self.release.wait(3)
        self.callbacks["on_close"](self)


with patch.object(friends, "_FriendsSocket", HeldSocket), patch.object(threading.Timer, "start"):
    client = friends.FriendsClient()
    check("startup begins a chat loop", client.connect(identity))
    first = HeldSocket.instances[0] if HeldSocket.instances else None
    if first is None:
        client._thread.join(0.01)
        first = HeldSocket.instances[0]
    check("first loop reached its socket", first.entered.wait(2))
    first_thread, first_stop = client._thread, client._stop
    check("opening Chat while connecting reuses the loop",
          client.connect(dict(identity, uid="00000001")) and client._thread is first_thread)
    client.disconnect()
    client.connect(identity)
    second_thread = client._thread
    # wait for the replacement's hello before delivering stale callbacks
    for _ in range(200):
        if len(HeldSocket.instances) == 2:
            break
        threading.Event().wait(0.005)
    second = HeldSocket.instances[-1]
    check("replacement loop starts", second.entered.wait(2))
    client._on_message(second, json.dumps({"t": "hello_ok"}))
    first.callbacks["on_message"](first, json.dumps({"t": "hello_ok"}))
    first.callbacks["on_error"](first, RuntimeError("stale error"))
    first.release.set()
    first_thread.join(2)
    check("old loop stays stopped and cannot clear the replacement",
          first_stop.is_set() and not first_thread.is_alive()
          and client.is_connected and client._ws is second)
    client.disconnect()
    second.release.set()
    second_thread.join(2)
    check("disconnect ends the active loop", not second_thread.is_alive())


class Stop:
    def __init__(self, rounds=3):
        self.done, self.rounds, self.delays = False, rounds, []

    def is_set(self): return self.done
    def set(self): self.done = True
    def wait(self, seconds):
        self.delays.append(seconds)
        self.done = len(self.delays) >= self.rounds


class RejectedSocket(HeldSocket):
    auth_error = False

    def run_forever(self, **kwargs):
        self.callbacks["on_open"](self)
        if self.auth_error:
            self.callbacks["on_message"](self, json.dumps({
                "t": "error", "code": "rate_limited", "message": "Try again later."}))
        self.callbacks["on_close"](self)


with patch.object(friends, "_FriendsSocket", RejectedSocket), patch.object(threading.Timer, "start"):
    client = friends.FriendsClient()
    client._identity = identity
    client._stop = Stop()
    client._run_loop(client._stop)
    check("opening a socket without authenticating does not reset backoff",
          client._stop.delays == [1, 2, 5])
    RejectedSocket.auth_error = True
    client._stop = Stop(rounds=1)
    client._run_loop(client._stop)
    check("refused hello respects the hub's authentication budget",
          client._stop.delays == [friends._AUTH_RETRY_DELAY])

client = friends.FriendsClient()
client._identity = identity
client._ws = HeldSocket("test")
client._expire_connection(client._ws, client._stop)
client._on_message(client._ws, json.dumps({"t": "hello_ok"}))
check("an expired handshake cannot become connected from a late hello",
      not client.is_connected and "timed out" in client.connection_status["message"])
client._ws = HeldSocket("test")
client._connection_error = ""
client._on_error(client._ws, SimpleNamespace(status_code=407))
client._on_close(client._ws)
check("proxy refusal produces an actionable connection message",
      "proxy" in client.connection_status["message"])


class CoreSocket:
    def __init__(self, **kwargs):
        self.timeouts, self.connect_options, self.closed = [], {}, False

    def settimeout(self, seconds): self.timeouts.append(seconds)
    def connect(self, url, **kwargs): self.connect_options = kwargs
    def abort(self): pass
    def close(self, **kwargs): self.closed = True


with patch.object(friends.websocket, "WebSocket", CoreSocket):
    opened = []
    socket = friends._FriendsSocket("wss://chat.test/ws", on_open=lambda ws: (opened.append(ws), ws.close()),
                                    on_message=lambda *args: None, on_error=lambda *args: None,
                                    on_close=lambda *args: None)
    socket.run_forever(ping_interval=25, ping_timeout=10, http_proxy_timeout=10)
    check("TLS/upgrade has its own finite timeout and always closes",
          socket._socket.connect_options["timeout"] == 10 and socket._socket.closed)

class HeartbeatSocket(CoreSocket):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.pings = 0
    def ping(self): self.pings += 1
    def recv_data_frame(self, **kwargs):
        fake_clock[0] += self.timeouts[-1]
        raise friends.websocket.WebSocketTimeoutException("idle")

fake_clock, heartbeat_errors = [0.0], []
with (patch.object(friends.websocket, "WebSocket", HeartbeatSocket),
      patch.object(friends.time, "monotonic", side_effect=lambda: fake_clock[0])):
    socket = friends._FriendsSocket("wss://chat.test/ws", on_open=lambda ws: None,
                                    on_message=lambda *args: None,
                                    on_error=lambda ws, error: heartbeat_errors.append(error),
                                    on_close=lambda ws: None)
    socket.run_forever(ping_interval=25, ping_timeout=10, http_proxy_timeout=10)
    check("idle socket sends a protocol ping and drops an unanswered pong",
          socket._socket.pings == 1 and len(heartbeat_errors) == 1
          and fake_clock[0] == 35 and socket._socket.closed)

client = friends.FriendsClient()
client._identity = identity
client._ws = HeldSocket("test")
observed_connected = []
with patch.object(friends, "remember_uid",
                  side_effect=lambda uid: (observed_connected.append(client.is_connected) or False)):
    client._on_message(client._ws, json.dumps({"t": "hello_ok", "uid": "00000001"}))
check("UID persistence finishes before chat callers see a connected session",
      observed_connected == [False] and client.is_connected)

published = threading.Event()
fake_client = SimpleNamespace(is_connected=True, roster={}, is_available=True,
                              set_minecraft_username=lambda value: True,
                              publish_pubkey=lambda key: (published.set() or {"ok": True}))
service = FriendsService({"username": "Steve"}, {}, fake_client)
service._on_state({"connected": True})
check("first successful hello publishes a key without the user sending first", published.wait(2))
with ThreadPoolExecutor(max_workers=8) as pool:
    keys = list(pool.map(lambda _: service._ensure_e2ee(), range(8)))
check("concurrent chat callers share one persisted encryption key",
      all(key == keys[0] for key in keys)
      and e2ee.load_or_create_key(friends.IDENTITY_PATH) == keys[0][0])
with patch.object(e2ee, "write_json", side_effect=OSError("disk full")):
    try:
        e2ee._write_identity(friends.IDENTITY_PATH, identity)
    except OSError:
        check("key persistence failure is reported instead of publishing an ephemeral key", True)
    else:
        raise AssertionError("key persistence failure was swallowed")
with (patch("builtins.open", side_effect=PermissionError("identity unreadable")),
      patch.object(e2ee, "write_json") as writer):
    try:
        e2ee.load_or_create_key(friends.IDENTITY_PATH)
    except PermissionError:
        check("unreadable identity is never overwritten with a key-only file", not writer.called)
    else:
        raise AssertionError("unreadable identity was overwritten")
print("Chat connection checks passed")
