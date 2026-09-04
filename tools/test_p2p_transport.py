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

if __name__ == '__main__':
    main()
