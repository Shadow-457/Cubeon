#!/usr/bin/env python3
"""
Tests for the punch-failure relay fallback (cubeon/p2p.RelaySession) - run with:

    python3 tools/test_p2p_relay.py

Needs no network and no friends server: two RelaySessions are wired together
through an in-memory "signal bus" that mimics the properties the real channel
guarantees (ordered, reliable delivery of opaque payloads between exactly two
room members). Fake LAN server on the host side, fake Minecraft client on the
joiner side, then bytes are pushed BOTH ways and verified byte-perfect.
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

from cubeon.p2p import RelaySession                                    # noqa: E402

failures = 0


def check(label, ok, extra=""):
    global failures
    print(f"{'  ok  ' if ok else ' FAIL '} {label}{'  ' + str(extra) if extra else ''}")
    if not ok:
        failures += 1


class SignalBus:
    """Stands in for the friends WS: ordered, reliable, two-party."""

    def __init__(self):
        self.a_subs = []   # callbacks for messages TO side A
        self.b_subs = []
        self.lock = threading.Lock()

    def sender_for(self, to_side):
        def send(payload):
            with self.lock:   # serialize like a single WS connection would
                subs = self.b_subs if to_side == "B" else self.a_subs
                # deliver asynchronously-ish but IN ORDER (a thread per frame
                # could reorder; a queue-preserving dispatch is what a WS gives)
                t = threading.Thread(target=self._deliver, args=(subs, payload), daemon=True)
                t.start()
                t.join(30)
        return send

    @staticmethod
    def _deliver(subs, payload):
        for cb in subs:
            cb(payload)


def main():
    bus = SignalBus()

    host = RelaySession(is_host=True, lan_port=None)
    joiner = RelaySession(is_host=False)

    bus.a_subs.append(lambda p: host.on_relay_chunk(p) if p.get("kind") == "p2p_relay_chunk" else None)
    bus.b_subs.append(lambda p: joiner.on_relay_chunk(p) if p.get("kind") == "p2p_relay_chunk" else None)
    # Each side's sender must deliver to the OTHER side's subscriber list
    host._send_signal = bus.sender_for("B")
    joiner._send_signal = bus.sender_for("A")

    # --- fake LAN server on the host -----------------------------------------
    srv = socket.socket()
    srv.bind(("127.0.0.1", 0))
    srv.listen(1)
    host.lan_port = srv.getsockname()[1]

    host.start()
    joiner.start()
    check("joiner relay port assigned", isinstance(joiner.local_relay_port, int))

    # NOTE: the host's bridge connects lazily on the FIRST INBOUND byte (same
    # as PunchSession), so Minecraft must attach and speak before accept()
    # can return - otherwise this deadlocks against itself.
    time.sleep(0.3)  # let the relay threads settle
    mc = socket.create_connection(("127.0.0.1", joiner.local_relay_port), timeout=10)
    check("minecraft attached to relay", joiner._tcp_ready.wait(5))
    # real MC speaks first: push the uplink handshake to bring the bridge up
    mc.sendall(b"HELLO-FROM-JOINER")
    conn, _ = srv.accept()
    check("host bridge established", host._tcp_ready.wait(10))

    # --- bidirectional transfer -------------------------------------------------
    to_joiner = bytes((i * 7 + 3) % 256 for i in range(300_000))   # ~5 chunks

    got_on_mc = bytearray()
    got_got = threading.Event()
    def read_mc():
        mc.settimeout(30)
        while len(got_on_mc) < len(to_joiner):
            d = mc.recv(65535)
            if not d:
                break
            got_on_mc.extend(d)
        if len(got_on_mc) >= len(to_joiner):
            got_got.set()
    threading.Thread(target=read_mc, daemon=True).start()

    conn.settimeout(30)
    sent_to_lan = 0
    while sent_to_lan < len(to_joiner):
        sent_to_lan += conn.send(to_joiner[sent_to_lan:sent_to_lan + 60_000])

    ok_down = got_got.wait(60)
    check("LAN -> joiner: all bytes delivered", ok_down and bytes(got_on_mc) == to_joiner,
          f"{len(got_on_mc)}/{len(to_joiner)}")
    check("no relay errors (downlink)", host.closed_reason is None and joiner.closed_reason is None,
          f"{host.closed_reason!r}/{joiner.closed_reason!r}")

    to_host = b"HELLO-FROM-JOINER" + bytes((i * 13 + 1) % 256 for i in range(150_000))

    got_on_lan = bytearray()
    up_done = threading.Event()
    def read_lan():
        while len(got_on_lan) < len(to_host):
            d = conn.recv(65535)
            if not d:
                break
            got_on_lan.extend(d)
        if len(got_on_lan) >= len(to_host):
            up_done.set()
    threading.Thread(target=read_lan, daemon=True).start()

    mc_sent = 0
    while mc_sent < len(to_host):
        mc_sent += mc.send(to_host[mc_sent:mc_sent + 60_000])
    ok_up = up_done.wait(60)
    expected_uplink = b"HELLO-FROM-JOINER" + to_host
    check("joiner -> LAN: all bytes delivered", ok_up and bytes(got_on_lan) == expected_uplink,
          f"{len(got_on_lan)}/{len(expected_uplink)}")

    # --- metrics contract (banner compatibility) -----------------------------
    m = joiner.metrics()
    check("metrics exposes banner fields",
          m.get("mode") == "relay" and m.get("rtt_ms", "x") is None
          and m.get("bytes_received", 0) >= len(to_joiner),
          str({k: m[k] for k in ("mode", "rtt_ms", "bytes_received")}))

    # --- close is clean and idempotent ---------------------------------------
    host.close()
    host.close()
    joiner.close()
    check("close idempotent, clean reason or none",
          host.closed_reason in (None, "Minecraft closed the connection"))

    print(f"\n{failures} CHECK(S) FAILED" if failures else "\nALL RELAY CHECKS PASSED")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
