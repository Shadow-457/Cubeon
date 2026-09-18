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
    _, txn = p2p._stun_binding_request()
    for length in (1, 2, 3, 5, 7):
        prefix = b"\x80\x22" + length.to_bytes(2, "big") + b"x" * length + b"\0" * (-length % 4)
        address = b"\x00\x01\x00\x08\x00\x01\x63\xdd\x7f\x00\x00\x01"
        body = prefix + address
        packet = b"\x01\x01" + len(body).to_bytes(2, "big") + b"\x21\x12\xa4\x42" + txn + body
        assert p2p._parse_xor_mapped_address(packet, txn) == ("127.0.0.1", 25565)
    for bad in ("../escape.jar", "sub/dir/mod.jar", "mod.exe"):
        try:
            p2p._mod_target("/tmp", bad)
            raise SystemExit(f"unsafe mod filename accepted: {bad}")
        except p2p.P2PError:
            pass
    try:
        p2p._asset_target("resourcepack", "packs/../evil.zip")
        raise SystemExit("asset traversal accepted")
    except p2p.P2PError:
        pass
    try:
        p2p._asset_target("config", "evil.exe")
        raise SystemExit("asset extension bypass accepted")
    except p2p.P2PError:
        pass
    item = {"size": 100}
    assert p2p._accept_chunk(item, 0, 2, "AAAA", p2p.MOD_MAX_FILE_BYTES, 64_000) is False
    assert p2p._accept_chunk(item, 1, 2, "BBBB", p2p.MOD_MAX_FILE_BYTES, 64_000) is True
    for seq, total in ((1, 3), (0, 200_000), (2, 2)):
        try:
            p2p._accept_chunk(item, seq, total, "AAAA", p2p.MOD_MAX_FILE_BYTES, 64_000)
            raise SystemExit("bad chunk indexing accepted")
        except p2p.P2PError:
            pass
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
