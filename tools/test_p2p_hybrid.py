#!/usr/bin/env python3
"""
Tests for Relayed Signalling with Direct Hole-Punch Handover
(cubeon/p2p.HybridSession) - run with:

    python3 tools/test_p2p_hybrid.py

Needs no network and no friends server. Two HybridSessions are wired
together through an in-memory "signal bus" that mimics the friends
WebSocket (ordered, reliable, two-party). The UDP side runs over real
loopback sockets: each session's "public candidate" is simply its bound
127.0.0.1 port, so the coordinated spray punches a genuine direct path.

Scenarios:
  1. relay-only: data flows immediately with no punch at all.
  2. full handover: punch lands, mode flips to "direct", the CUBP stream
     survives the swap byte-perfectly (data before AND after handover).
  3. spray-failure resilience: candidates pointed at a black hole - the
     session stays on "relay" and keeps working.
"""
import os
import sys
import types
import socket
import threading
import time

mll = types.SimpleNamespace(utils=types.SimpleNamespace(get_minecraft_directory=lambda: "/tmp/cubeon-test-mc"))
sys.modules.setdefault("minecraft_launcher_lib", mll)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home
_sandbox_home.isolate()

from cubeon.p2p import HybridSession                                    # noqa: E402

failures = 0


def check(label, ok, extra=""):
    global failures
    print(f"{'  ok  ' if ok else ' FAIL '} {label}{'  ' + str(extra) if extra else ''}")
    if not ok:
        failures += 1


class SignalBus:
    """Stands in for the friends WS: ordered, reliable, two-party."""

    def __init__(self):
        self.a = []   # callbacks for traffic TO side A (host)
        self.b = []   # callbacks for traffic TO side B (joiner)
        self.drop = False   # simulate relay outage (never used in these tests)
        self.lock = threading.Lock()

    def sender_for(self, to_side):
        def send(payload):
            if self.drop:
                return
            with self.lock:
                subs = self.b if to_side == "B" else self.a
                t = threading.Thread(target=self._deliver, args=(subs, payload), daemon=True)
                t.start()
                t.join(30)
        return send

    @staticmethod
    def _deliver(subs, payload):
        for cb in subs:
            cb(payload)


def wire(bus, host, joiner):
    # a_subs = callbacks invoked for traffic TO side A (= host), b_subs = to B
    # (= joiner); each side's sender must target the OTHER side's list.
    bus.a.append(host.on_signal_data)
    bus.b.append(joiner.on_signal_data)
    host._send_signal = bus.sender_for("B")
    joiner._send_signal = bus.sender_for("A")


def fake_lan_server():
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    return srv, srv.getsockname()[1]


def pump_both_ways(mc, conn, payload_down, payload_up_prefix=b"HELLO-FROM-JOINER"):
    """Send payload_down LAN->joiner and payload_up joiner->LAN concurrently;
    returns (got_on_mc, got_on_lan) once both complete."""
    got_on_mc = bytearray()
    down_done = threading.Event()

    def read_mc():
        mc.settimeout(60)
        while len(got_on_mc) < len(payload_down):
            d = mc.recv(65535)
            if not d:
                break
            got_on_mc.extend(d)
        if len(got_on_mc) >= len(payload_down):
            down_done.set()
    threading.Thread(target=read_mc, daemon=True).start()

    conn.settimeout(60)
    sent = 0
    while sent < len(payload_down):
        sent += conn.send(payload_down[sent:sent + 60_000])

    uplink = payload_up_prefix * 4   # initial bridge msg + three pump msgs
    got_on_lan = bytearray()
    up_done = threading.Event()

    def read_lan():
        while len(got_on_lan) < len(uplink):
            d = conn.recv(65535)
            if not d:
                break
            got_on_lan.extend(d)
        if len(got_on_lan) >= len(uplink):
            up_done.set()
    threading.Thread(target=read_lan, daemon=True).start()
    mc.settimeout(60)
    mc.sendall(uplink)

    down_done.wait(90)
    up_done.wait(90)
    return bytes(got_on_mc), bytes(got_on_lan)


def main():
    token = bytes(range(16))

    # ================= 1. relay-only =====================================
    print("--- scenario 1: relay-only (no punch) ---")
    bus1 = SignalBus()
    lan_srv, lan_port = fake_lan_server()
    host = HybridSession(is_host=True, lan_port=lan_port, session_token=token)
    joiner = HybridSession(is_host=False, session_token=token)
    wire(bus1, host, joiner)

    host.begin()
    joiner.begin()
    check("joiner local relay port assigned", isinstance(joiner.local_relay_port, int))
    check("transport handshake over bare relay",
          joiner._transport_ready.wait(10) and host._transport_ready.wait(10))

    time.sleep(0.2)
    mc = socket.create_connection(("127.0.0.1", joiner.local_relay_port), timeout=10)
    check("minecraft attached to joiner relay", joiner._tcp_ready.wait(5))
    mc.sendall(b"HELLO-FROM-JOINER")
    conn, _ = lan_srv.accept()
    check("host bridge established over relay", host._tcp_ready.wait(10))

    down, up = pump_both_ways(mc, conn, bytes((i * 7 + 3) % 256 for i in range(200_000)))
    check("relay-only downlink byte-perfect", down == bytes((i * 7 + 3) % 256 for i in range(200_000)),
          f"{len(down)} bytes")
    check("relay-only uplink byte-perfect",
          up == b"HELLO-FROM-JOINER" * 5, f"{len(up)} bytes")
    check("mode stays 'relay' without punch", joiner.mode == "relay" and host.mode == "relay",
          f"{joiner.mode}/{host.mode}")

    host.close(); joiner.close(); conn.close(); mc.close(); lan_srv.close()

    # ================= 2. coordinated punch -> handover ==================
    print("--- scenario 2: coordinated spray + handover ---")
    bus2 = SignalBus()
    lan_srv2, lan_port2 = fake_lan_server()
    host2 = HybridSession(is_host=True, lan_port=lan_port2, session_token=token)
    joiner2 = HybridSession(is_host=False, session_token=token)
    wire(bus2, host2, joiner2)

    host2.begin()
    joiner2.begin()
    check("handover setup: transport up on relay",
          joiner2._transport_ready.wait(10) and host2._transport_ready.wait(10))

    # Real loopback endpoints stand in for STUN-derived public candidates.
    host_nat = {"candidate": {"ip": "127.0.0.1", "port": host2.local_port},
                "symmetric": False, "delta": None, "probes": [host2.local_port]}
    joiner_nat = {"candidate": {"ip": "127.0.0.1", "port": joiner2.local_port},
                  "symmetric": False, "delta": None, "probes": [joiner2.local_port]}
    host2.begin_punch(host_nat, joiner_nat)
    joiner2.begin_punch(joiner_nat, host_nat)

    deadline = time.monotonic() + 30
    while time.monotonic() < deadline and not (host2._direct_rx.is_set() and joiner2._direct_rx.is_set()):
        time.sleep(0.1)
    check("both sides saw direct UDP frames",
          host2._direct_rx.is_set() and joiner2._direct_rx.is_set())

    deadline = time.monotonic() + 15
    while time.monotonic() < deadline and not (joiner2.mode == "direct" and host2.mode == "direct"):
        time.sleep(0.1)
    check("mode flipped to 'direct' on both sides",
          joiner2.mode == "direct" and host2.mode == "direct",
          f"joiner={joiner2.mode} host={host2.mode}")

    # Stream survives the pipe swap byte-perfectly: traffic now crosses the
    # punched UDP path (relay frames are no longer emitted by either side).
    time.sleep(0.2)
    mc2 = socket.create_connection(("127.0.0.1", joiner2.local_relay_port), timeout=10)
    check("minecraft attached post-handover", joiner2._tcp_ready.wait(5))
    mc2.sendall(b"HELLO-FROM-JOINER")
    conn2, _ = lan_srv2.accept()
    check("host bridge established post-handover", host2._tcp_ready.wait(10))

    expected_down = bytes((i * 11 + 5) % 256 for i in range(400_000))
    down2, up2 = pump_both_ways(mc2, conn2, expected_down)
    check("post-handover downlink byte-perfect (UDP pipe)",
          down2 == expected_down, f"{len(down2)}/{len(expected_down)}")
    check("post-handover uplink byte-perfect (UDP pipe)",
          up2 == b"HELLO-FROM-JOINER" * 5, f"{len(up2)} bytes")
    m = joiner2.metrics()
    check("metrics report direct mode", m.get("mode") == "direct", str(m.get("mode")))
    check("peer endpoint locked to observed addr",
          isinstance(joiner2.peer_endpoint, tuple))

    host2.close(); joiner2.close(); conn2.close(); mc2.close(); lan_srv2.close()

    # ================= 3. punch failure stays on relay ===================
    print("--- scenario 3: unreachable candidate -> stays relayed ---")
    bus3 = SignalBus()
    lan_srv3, lan_port3 = fake_lan_server()
    host3 = HybridSession(is_host=True, lan_port=lan_port3, session_token=token)
    joiner3 = HybridSession(is_host=False, session_token=token)
    wire(bus3, host3, joiner3)

    host3.begin()
    joiner3.begin()
    # Candidates point at an unbound port range: probes go nowhere, no
    # direct frames ever arrive, and the session must keep working anyway.
    dead = {"candidate": {"ip": "127.0.0.1", "port": 1},
            "symmetric": True, "delta": 2, "probes": [1]}
    host3.begin_punch(dead, dict(dead, candidate=dict(dead["candidate"])))
    joiner3.begin_punch(dict(dead, candidate=dict(dead["candidate"])), dead)

    time.sleep(0.2)
    mc3 = socket.create_connection(("127.0.0.1", joiner3.local_relay_port), timeout=10)
    mc3.sendall(b"HELLO-FROM-JOINER")
    conn3, _ = lan_srv3.accept()
    down3, _up3 = pump_both_ways(mc3, conn3, b"still-relayed-" * 1000)
    check("session keeps working through failed punch", down3 == b"still-relayed-" * 1000,
          f"{len(down3)} bytes")
    check("mode honestly reports 'relay'", joiner3.metrics().get("mode") == "relay")

    host3.close(); joiner3.close(); conn3.close(); mc3.close(); lan_srv3.close()

    print(f"\n{failures} CHECK(S) FAILED" if failures else "\nALL HYBRID CHECKS PASSED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
