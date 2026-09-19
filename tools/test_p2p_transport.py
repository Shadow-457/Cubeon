import socket
import sys
import types
mll = types.SimpleNamespace(utils=types.SimpleNamespace(get_minecraft_directory=lambda: "/tmp/cubeon-test-mc"))
sys.modules.setdefault("minecraft_launcher_lib", mll)
import threading
import time
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()
from cubeon.p2p import PunchSession


def fin_drain_check():
    """A peer FIN must never truncate bytes already queued for local delivery.

    Deterministic repro of the 2026-09-18 stress flake (a 120000-byte
    transfer cut at 118535): the FIN branch closed the local TCP socket
    immediately, so everything still sitting in _tcp_in_queue vanished and
    Minecraft saw a half-delivered stream. The FIN is delivered here BEFORE
    the delivery loop runs, so the old code fails this every time instead of
    one run in five.
    """
    token = b"0123456789abcdef"
    s = PunchSession(is_host=True, lan_port=1, session_token=token)
    local, peer = socket.socketpair()
    s._tcp_sock = local
    payloads = [b"A" * 1024, b"B" * 777]
    for p in payloads:
        s._tcp_in_queue.put(p)

    s._handle_frame(s._FIN, 0, 0, b"")     # peer's FIN, both payloads queued
    assert not s._stop.is_set(), \
        "FIN tore the session down while bytes were still queued for delivery"

    # The socket must still be open and untouched: the drain owns it now.
    peer.settimeout(0.3)
    try:
        early = peer.recv(4096)
        raise AssertionError(f"unexpected bytes before the drain: {early[:16]!r}")
    except socket.timeout:
        pass

    threading.Thread(target=s._tcp_delivery_loop, daemon=True).start()
    peer.settimeout(5)
    got = b""
    want = b"".join(payloads)
    while len(got) < len(want):
        chunk = peer.recv(4096)
        if not chunk:
            break
        got += chunk
    assert got == want, (len(got), len(want))
    assert peer.recv(4096) == b"", "the local side must still see a clean EOF"
    deadline = time.time() + 2
    while time.time() < deadline and not s._stop.is_set():
        time.sleep(0.02)
    assert s.closed_reason == "Minecraft TCP connection closed", s.closed_reason
    s.close(); peer.close()


def main():
    received = []
    server_ready = threading.Event()
    server_port = {}

    def server():
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.bind(('127.0.0.1', 0))
        s.listen(1)
        server_port['p'] = s.getsockname()[1]
        server_ready.set()
        conn, _ = s.accept()
        data = conn.recv(4096)
        received.append(data)
        conn.sendall(b'world:' + data)
        conn.close(); s.close()

    threading.Thread(target=server, daemon=True).start()
    assert server_ready.wait(2)
    token = b'0123456789abcdef'
    host = PunchSession(is_host=True, lan_port=server_port['p'], session_token=token)
    join = PunchSession(is_host=False, session_token=token)
    host.peer_endpoint = ('127.0.0.1', join.local_port)
    join.peer_endpoint = ('127.0.0.1', host.local_port)
    host._connected.set(); join._connected.set()
    host._start_transport(); join._start_transport()
    assert host._wait_transport_ready()
    assert join._wait_transport_ready()
    c = socket.create_connection(('127.0.0.1', join.local_relay_port), timeout=2)
    c.sendall(b'hello')
    deadline = time.time() + 5
    got = b''
    while time.time() < deadline and not got:
        try:
            got = c.recv(4096)
        except socket.timeout:
            pass
    assert received == [b'hello'], received
    assert got == b'world:hello', got
    c.close(); host.close(); join.close()
    print('p2p transport loopback: PASS')
    fin_drain_check()
    print('p2p transport fin-drain: PASS')

if __name__ == '__main__':
    main()
