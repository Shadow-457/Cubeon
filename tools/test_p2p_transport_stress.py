import socket
import sys
import threading
import types
import time

sys.modules.setdefault("minecraft_launcher_lib", types.SimpleNamespace(
    utils=types.SimpleNamespace(get_minecraft_directory=lambda: "/tmp/cubeon-test-mc")
))

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()
from cubeon.p2p import PunchSession


def wait_recv(sock, size, timeout=10):
    sock.settimeout(0.25)
    out = bytearray()
    deadline = time.time() + timeout
    while len(out) < size and time.time() < deadline:
        try:
            chunk = sock.recv(min(65535, size - len(out)))
        except socket.timeout:
            continue
        if not chunk:
            break
        out.extend(chunk)
    return bytes(out)


def main():
    server_ready = threading.Event()
    port = {}
    received = bytearray()

    def server():
        s = socket.socket()
        s.bind(("127.0.0.1", 0)); s.listen(1)
        port["p"] = s.getsockname()[1]; server_ready.set()
        c, _ = s.accept(); c.settimeout(0.25)
        try:
            while len(received) < 180_000:
                try:
                    b = c.recv(65535)
                except socket.timeout:
                    continue
                if not b: break
                received.extend(b)
            c.sendall(bytes((i * 37) % 256 for i in range(120_000)))
        finally:
            c.close(); s.close()

    threading.Thread(target=server, daemon=True).start()
    assert server_ready.wait(2)
    token = b"0123456789abcdef"
    host = PunchSession(is_host=True, lan_port=port["p"], session_token=token)
    join = PunchSession(is_host=False, session_token=token)
    host.peer_endpoint = ("127.0.0.1", join.local_port)
    join.peer_endpoint = ("127.0.0.1", host.local_port)
    host._connected.set(); join._connected.set()
    host._start_transport(); join._start_transport()
    assert host._wait_transport_ready() and join._wait_transport_ready()

    c = socket.create_connection(("127.0.0.1", join.local_relay_port), timeout=2)
    payload = bytes((i * 13) % 256 for i in range(180_000))
    c.sendall(payload)
    got = wait_recv(c, 120_000, timeout=12)
    assert bytes(received) == payload, (len(received), len(payload))
    assert got == bytes((i * 37) % 256 for i in range(120_000)), len(got)
    c.close(); host.close(); join.close()
    print("p2p transport stress: PASS")


if __name__ == "__main__":
    main()
