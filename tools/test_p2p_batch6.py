import os
import socket
import sys
import tempfile
import time
import types

sys.modules.setdefault("minecraft_launcher_lib", types.SimpleNamespace(
    utils=types.SimpleNamespace(get_minecraft_directory=lambda: "/tmp/cubeon-test-mc")
))

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()
from cubeon import p2p


def main():
    token = b"0123456789abcdef"
    a = p2p.PunchSession(is_host=False, session_token=token)
    b = p2p.PunchSession(is_host=False, session_token=token)
    try:
        frame = a._frame(a._DATA, 1, 0, b"hello")
        assert b._parse_frame(frame)[3] == b"hello"
        tampered = bytearray(frame)
        tampered[-1] ^= 0x01
        assert b._parse_frame(bytes(tampered)) is None
        wrong = p2p.PunchSession(is_host=False, session_token=b"fedcba9876543210")
        try:
            assert wrong._parse_frame(frame) is None
        finally:
            wrong.close()

        with tempfile.TemporaryDirectory() as td:
            f = os.path.join(td, "mod.jar")
            with open(f, "wb") as out:
                out.write(b"one")
            first = p2p.hash_file(f)
            second = p2p.hash_file(f)
            assert first == second
            with open(f, "wb") as out:
                out.write(b"two")
            os.utime(f, None)
            third = p2p.hash_file(f)
            assert third != first

        # Loopback transport metrics should expose a bounded diagnostic shape.
        host = p2p.PunchSession(is_host=False, session_token=token)
        peer = p2p.PunchSession(is_host=False, session_token=token)
        host.peer_endpoint = ("127.0.0.1", peer.local_port)
        peer.peer_endpoint = ("127.0.0.1", host.local_port)
        host._connected.set(); peer._connected.set()
        host._start_transport(); peer._start_transport()
        assert host._wait_transport_ready() and peer._wait_transport_ready()
        host._send_raw(host._frame(host._PING, 0, 0, b"12345678"))
        time.sleep(0.15)
        metrics = host.metrics()
        assert "rtt_ms" in metrics and "retransmits" in metrics and "bytes_sent" in metrics
        host.close(); peer.close()
        print("p2p batch6 security/cache/metrics: PASS")
    finally:
        a.close(); b.close()


if __name__ == "__main__":
    main()
