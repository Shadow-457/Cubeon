"""
P2P worlds - host a singleplayer world, a friend joins directly, no
dedicated server process and no relay. Decided scope, 2026-08-23 (see
docs/roadmap-adapted.md, Phase 2b (now under agents/docs/): STUN + UDP hole-punching only. No TURN,
no VPS - if the direct connection can't be established, this reports an
explicit error and stops. It does NOT fall back to the server.py + minekube.py
dedicated-server flow; that's a different feature with a different UX.

This module is entirely client-side. It needs no changes to the Cloudflare
Worker (worker/cubeon-friends.js) - it rides two pieces of the friends
protocol that already exist and are already generic, not voice-specific:

  - call_invite/call_accept/call_decline/call_end (friends.py) - the Worker's
    `calls` table and onCallInvite/onCallSignalControl handlers only ever
    look at `to` and `room`; nothing in the routing or SQL is audio-specific.
    Reused here as the P2P session's invite/accept/hang-up room lifecycle.
  - signal(room, to, data) - the Worker relays `data` completely opaque
    (onSignal never inspects it), so this module rides it for two different
    payload kinds distinguished by data["kind"]:
      "p2p_offer"   - {kind, lan_port, stun_candidate}   sent by the host
                       right after the invite is accepted, so the joiner
                       knows this room is a P2P world session (not a voice
                       call) and has what it needs to start hole-punching.
      "p2p_answer"  - {kind, stun_candidate}             sent by the joiner
                       in reply, completing the candidate exchange.
      "p2p_modlist" - {kind, mc_version, loader, mods: [{sha256, filename, size}]}
                       sent by the host alongside p2p_offer - the joiner's
                       full mod-diff input. Sent as its own signal rather
                       than folded into p2p_offer so a large mod list never
                       risks pushing that frame over a size limit.
      "p2p_modreq"  - {kind, sha256}                     joiner asking host
                       to send a mod it couldn't resolve locally.
      "p2p_modchunk"- {kind, sha256, seq, total, data_b64}
                                                          host streaming a
                       requested jar back over the same signalling channel,
                       base64 in chunks small enough for one WS frame.
    call_invite() itself only takes `to` (see friends.py's T_CALL_INVITE
    handler - it reads nothing else), so there's no room-purpose field on
    the invite frame itself; the "this is a P2P session, not a voice call"
    marker is the p2p_offer signal sent immediately after accept.

What DID carry over, as of 2026-08-25: RelaySession below carries the same
Minecraft TCP stream over the friends signalling channel (a WebSocket through
the free-tier Durable Object) as base64 chunks. No Worker changes - onSignal
already routes opaque payloads between room members, exactly like mod-sync
chunks already do.

RELAY-FIRST HANDOVER (added 2026-08-25, the current strategy)

HybridSession replaces "punch first, relay on failure" with Relayed
Signalling and Direct Hole-Punch Handover:

  1. SETUP PHASE (over relay): the CUBP reliable stream runs over the
     friends WebSocket from the moment the session starts - a guaranteed,
     ordered pipe NATs never block. The joiner can enter the world
     immediately.
  2. DIAGNOSTICS: while data flows, both peers run probe_nat() (multi-
     socket STUN probes -> symmetric-NAT detection + port-allocation
     delta) and swap the results over the relay inside p2p_offer /
     p2p_answer.
  3. COORDINATED SPRAY: the host arms rounds via p2p_punch_plan; both
     sides start spraying on a synchronized clock, blasting probes across
     each other's PREDICTED public port range (candidate + observed probe
     ports, widened by the measured delta) instead of one guessed port.
  4. HANDOVER: the first frame that parses AND authenticates arriving
     directly over UDP proves the path; each side sends p2p_direct_up,
     then flips the SAME CUBP stream (seq numbers continue seamlessly -
     duplicates across pipes are already handled by the rx buffer) to the
     UDP pipe and stops using the relay for data.

If the spray never lands (hard symmetric NAT / CGNAT), the session simply
stays on the relay - degraded ping, never a failure - and punching keeps
retrying in background rounds, so an upgrade can land mid-game.

SESSION LIFECYCLE

  1. Host: start_hosting() launches the game (launch.py's launch_game with
     log_cb watching for "Open to LAN on port <port>") and returns once the
     LAN port is known.
  2. Host: invite_friend(client, name) sends call_invite(name).
  3. Joiner: on call_invite, UI enables that host's Join button. Accepting
     calls call_accept(room), which is when the host's p2p_offer signal
     arrives with the LAN port and a STUN candidate.
  4. Both sides run HybridSession.begin() - the transport is up over the
      relay immediately, in parallel with mod sync (mod sync does not block
      the network path or vice versa - see roadmap Phase 2b). The
      coordinated punch + handover runs in the background; joining waits
      only for the relay path and mod sync.
   5. On success, the joiner points its Minecraft "Direct Connect" at
      127.0.0.1:<local_relay_port> - the session quietly forwards each
      packet to/from the host's LAN server over whichever pipe is active,
      upgrading from relay to direct mid-stream when the punch lands.
  6. On the joiner leaving, teardown() removes only this session's mod
     symlinks from the joiner's active profile (never touches the shared
     global cache) and stops the relay. A second join against the same
     host with the same mod set is link-only - nothing to refetch.
"""
import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import socket
import struct
import threading
import time
import atexit
import queue

from .paths import CUBEON_HOME, PROFILES_DIR
from . import global_mod_cache
from . import mods as mods_module

log = logging.getLogger(__name__)

# Public STUN servers - free, no account, no bandwidth cost to us (they only
# ever answer "what's your public address", they don't relay anything).
# Several, so one being down/rate-limiting doesn't fail hosting outright.
STUN_SERVERS = [
    ("stun.l.google.com", 19302),
    ("stun1.l.google.com", 19302),
    ("stun.cloudflare.com", 3478),
]

STUN_TIMEOUT_S = 3.0
PUNCH_ATTEMPT_S = 8.0          # how long both sides keep firing punch packets
PUNCH_INTERVAL_S = 0.25
CANDIDATE_WAIT_S = 15.0
TRANSPORT_IDLE_TIMEOUT_S = 30.0
TRANSPORT_PING_S = 5.0
MAX_UNACKED_FRAMES = 64
MAX_RETRANSMITS = 12
MAX_RX_BUFFER_FRAMES = 256        # bounded in-memory receive queue
METRICS_WINDOW_S = 10.0
MAX_PING_SAMPLES = 32

# ---------------------------------------------------------------------------
# Relayed-signalling handover strategy (HybridSession, added 2026-08-25).
#
# Instead of punching blind and falling back to relay only AFTER a failure,
# the session now starts ON the relay (the friends WebSocket - reliable,
# ordered, never blocked by NAT) so the joiner can get into the world
# immediately. While game data flows over that guaranteed pipe, both peers
# run a fast local NAT diagnostic (multi-socket STUN probes -> symmetric-NAT
# detection + port-allocation delta), swap the results over the relay, then
# execute a COORDINATED spray: synchronized start time (p2p_punch_plan),
# blasting probes across each other's predicted public port range instead
# of one guessed port. The moment an authenticated frame arrives directly
# from the peer's public endpoint, both sides hand the CUBP stream over to
# the UDP path and the relay stops carrying data.
# ---------------------------------------------------------------------------
HYBRID_TRANSPORT_TAG = "cubeon-hybrid-relay-first-v1"
NAT_PROBE_EXTRA_SOCKETS = 3     # plus the session socket => 4 sockets probed
SPRAY_LOW_OFFSET = -8           # spray window around predicted ports
SPRAY_HIGH_OFFSET = 24          # (32-wide span, covers typical +1..+5 deltas)
SPRAY_MAX_TARGETS = 48          # cap per burst; tiny payloads, still bounded
SPRAY_BURST_INTERVAL_S = 0.12
SPRAY_ROUND_S = 4.0             # how long one coordinated round sprays
PUNCH_RETRY_S = 15.0            # pause between rounds while still on relay
PLAN_DELAY_MS = 600             # responder starts spraying this long after
                                # receiving p2p_punch_plan; initiator adds a
                                # half-RTT fudge - the multi-second round
                                # makes sub-100 ms skew irrelevant.
HANDOVER_UDP_CONFIRM_S = 5.0    # after first direct frame, wait this long for
                                # the peer's p2p_direct_up before flipping on
                                # receipt-evidence alone (legacy-peer compat)
PUNCH_PAYLOAD = b"cubeon-p2p-punch"

LAN_OPEN_RE = re.compile(r"(?:Local game hosted on port|Open to LAN on port)\s+(\d+)|Started serving on .*:(\d+)", re.IGNORECASE)

# Where a joiner's session-only state lives, so teardown knows exactly what
# to remove and nothing else. Keyed by room so concurrent/sequential
# sessions with different friends never collide.
SESSIONS_DIR = os.path.join(CUBEON_HOME, "p2p_sessions")

# Relay fallback (see RelaySession): chunks ride the friends signalling
# channel, which is a WebSocket - i.e. already reliable and ordered - so
# chunks only need sequencing for sanity checks, never retransmission.
RELAY_CHUNK_BYTES = 48_000          # raw bytes per chunk (~64 KB base64'd)
RELAY_IDLE_TIMEOUT_S = 120.0        # no traffic for this long => peer is gone

MOD_CHUNK_BYTES = 48_000
MOD_SYNC_TIMEOUT_S = 120.0  # base64'd, stays comfortably under typical WS frame limits
ASSET_SYNC_TIMEOUT_S = 120.0
ASSET_CHUNK_BYTES = 48_000
ASSET_MAX_FILE_BYTES = 32 * 1024 * 1024
ASSET_MAX_TOTAL_BYTES = 128 * 1024 * 1024
ASSET_MAX_FILES = 1000
ASSET_MAX_MANIFEST_BYTES = 256 * 1024
ASSET_ALLOWED_CONFIG_EXTS = (".json", ".toml", ".cfg", ".properties", ".yml", ".yaml")


class P2PError(Exception):
    """Raised for any P2P-specific failure. The UI shows str(e) verbatim and
    stops - this module never falls back to the dedicated-server flow."""


class _PipeClosed(Exception):
    """Internal: the raw pipe under a transport loop died; stop the loop."""


# ---------------------------------------------------------------------------
# 1. LAN-port detection - reuses launch.py's already-streamed log_cb, no
#    separate log-tailing needed.
# ---------------------------------------------------------------------------

def watch_for_lan_port(on_found) -> "callable":
    """Returns a log_cb suitable for launch_game(). Calls on_found(port) the
    first time a line announces the world is open to LAN, then becomes a
    no-op for the rest of the process's life (only the first port matters -
    re-opening to LAN mid-session isn't something Minecraft does without a
    fresh line anyway, and reacting twice would just double-invite)."""
    found = threading.Event()

    def _cb(line: str) -> None:
        if found.is_set():
            return
        m = LAN_OPEN_RE.search(line)
        if m:
            port = int(m.group(1) or m.group(2))
            found.set()
            on_found(port)

    return _cb


# ---------------------------------------------------------------------------
# 2. STUN - minimal client, just enough to learn our public ip:port for a
#    UDP socket we already have bound (RFC 5389 binding request/response,
#    no auth, no TURN attributes touched at all).
# ---------------------------------------------------------------------------

def _stun_binding_request() -> bytes:
    # Binding Request, length 0, magic cookie, random 96-bit transaction id.
    msg_type = b"\x00\x01"
    msg_len = b"\x00\x00"
    magic_cookie = b"\x21\x12\xa4\x42"
    txn_id = secrets.token_bytes(12)
    return msg_type + msg_len + magic_cookie + txn_id, txn_id


def _parse_xor_mapped_address(data: bytes, txn_id: bytes) -> "tuple[str, int] | None":
    if len(data) < 20 or data[4:8] != b"\x21\x12\xa4\x42" or data[8:20] != txn_id:
        return None
    magic = data[4:8]
    body = data[20:]
    i = 0
    while i + 4 <= len(body):
        attr_type = body[i:i + 2]
        attr_len = int.from_bytes(body[i + 2:i + 4], "big")
        value = body[i + 4:i + 4 + attr_len]
        # XOR-MAPPED-ADDRESS (0x0020) preferred; fall back to plain
        # MAPPED-ADDRESS (0x0001) for older servers that only send that.
        if attr_type == b"\x00\x20" and len(value) >= 8:
            port = int.from_bytes(value[2:4], "big") ^ int.from_bytes(magic[0:2], "big")
            ip_bytes = bytes(a ^ b for a, b in zip(value[4:8], magic))
            return ".".join(str(b) for b in ip_bytes), port
        if attr_type == b"\x00\x01" and len(value) >= 8:
            port = int.from_bytes(value[2:4], "big")
            ip_bytes = value[4:8]
            return ".".join(str(b) for b in ip_bytes), port
        i += 4 + attr_len + (attr_len % 4)  # attributes are padded to 4 bytes
    return None


def stun_get_public_endpoint(sock: socket.socket) -> "tuple[str, int]":
    """Uses an already-bound UDP socket (the same one that will do the
    hole-punch) to learn its public ip:port. Tries each server in turn;
    raises P2PError only if every one of them fails, since one dead STUN
    server is normal, not fatal."""
    last_error = None
    for host, port in STUN_SERVERS:
        try:
            request, txn_id = _stun_binding_request()
            sock.settimeout(STUN_TIMEOUT_S)
            sock.sendto(request, (host, port))
            data, _addr = sock.recvfrom(2048)
            result = _parse_xor_mapped_address(data, txn_id)
            if result:
                return result
        except OSError as e:
            last_error = e
            continue
    raise P2PError(
        "Couldn't reach any STUN server to find your public address. "
        "Check your internet connection and try again."
    ) from last_error


def _stun_query(sock: socket.socket, host: str, port: int) -> "tuple[str, int]":
    """One binding request to one specific STUN server. Unlike
    stun_get_public_endpoint this does NOT iterate servers - NAT-type
    detection needs the per-server mappings, not just 'a' mapping."""
    request, txn_id = _stun_binding_request()
    sock.settimeout(STUN_TIMEOUT_S)
    sock.sendto(request, (host, port))
    data, _addr = sock.recvfrom(2048)
    result = _parse_xor_mapped_address(data, txn_id)
    if not result:
        raise P2PError("STUN server returned an unusable response.")
    return result


def probe_nat(session_sock: socket.socket) -> dict:
    """Fast local NAT diagnostic for the relayed-handover strategy.

    Binds a few extra UDP sockets alongside the session's own and queries
    each against two different STUN servers. Comparing the mappings gives:

      * the session socket's public candidate (same as get_local_candidate);
      * whether the router is SYMMETRIC (same socket maps to different
        public ports for different destinations - single-port punching is
        hopeless there, spraying is the answer);
      * the port-allocation DELTA (how much the public port advances per new
        allocation) so the other side can predict where our NEXT sockets
        would land.

    The extra sockets are closed before returning - only the session
    socket's mapping persists, which is exactly the one we advertise.
    Raises P2PError only if the session socket itself can't reach any STUN
    server; extra-socket failures just shrink the diagnostic.
    """
    ip, port = stun_get_public_endpoint(session_sock)
    result = {
        "ip": ip,
        "port": port,
        "symmetric": False,
        "delta": None,
        "probes": [port],   # every observed public port for our side
    }
    extra = []
    try:
        allocations = []   # public ports in bind order => delta source
        for _ in range(NAT_PROBE_EXTRA_SOCKETS):
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.bind(("0.0.0.0", 0))
            extra.append(s)
        seen_ports = {port}
        symmetric_hit = False
        deltas = []
        prev = None
        for s in extra:
            mapped = []
            for host, sport in STUN_SERVERS[:2]:
                try:
                    _mip, mport = _stun_query(s, host, sport)
                    mapped.append(mport)
                except (OSError, P2PError):
                    continue
            if not mapped:
                continue
            if len(set(mapped)) > 1:
                # Same local socket, two different public ports depending on
                # destination - textbook symmetric NAT.
                symmetric_hit = True
            current = mapped[0]
            allocations.append(current)
            seen_ports.update(mapped)
            if prev is not None and current > prev:
                deltas.append(current - prev)
            prev = current
        result["symmetric"] = symmetric_hit
        if deltas:
            # Median positive delta - robust against one weird allocation.
            deltas.sort()
            result["delta"] = deltas[len(deltas) // 2]
        result["probes"] = sorted(seen_ports)
    finally:
        for s in extra:
            try:
                s.close()
            except OSError:
                pass
    return result


# ---------------------------------------------------------------------------
# 3. Hole-punch + relay.
# ---------------------------------------------------------------------------

class PunchSession:
    """One P2P world connection attempt.

    Minecraft Java's multiplayer transport is **TCP**, not UDP.  The earlier
    prototype punched a UDP path and then incorrectly forwarded Minecraft
    datagrams as UDP, which could never carry a real Java LAN world.  This
    implementation keeps the UDP NAT traversal, then runs a small reliable,
    ordered TCP-over-UDP stream over the punched path.  It is deliberately
    self-contained so Cubeon does not need a second native networking stack.

    The transport is not intended to replace TCP on the public internet.  It
    exists only for the already-punched two-peer session and provides:
      * ordered delivery with cumulative ACKs;
      * fragmentation/reassembly;
      * retransmission with a bounded send window;
      * a short session token on every frame, so random UDP traffic cannot
        reach the Minecraft LAN socket;
      * a local TCP socket on the joiner and a localhost TCP connection to
        Minecraft's LAN server on the host.
    """

    _MAGIC = b"CUBP"
    _VERSION = 2
    _HELLO = 1
    _DATA = 2
    _ACK = 3
    _FIN = 4
    _PING = 5
    _HEADER = struct.Struct("!4sBB16sIIH")
    _AUTH_TAG_BYTES = 16
    _MAX_PAYLOAD = 1000
    _RETX_S = 0.35
    _POLL_S = 0.05
    _CONNECT_TIMEOUT_S = 10.0

    def __init__(self, *, is_host: bool, lan_port: "int | None" = None,
                 session_token: "bytes | None" = None):
        self.is_host = is_host
        self.lan_port = lan_port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("0.0.0.0", 0))
        self.local_port = self._sock.getsockname()[1]
        self.public_endpoint = None
        self.peer_endpoint = None
        self._connected = threading.Event()
        self._transport_ready = threading.Event()
        self._stop = threading.Event()
        self._relay_thread = None
        self._local_listener = None
        self.local_relay_port = None
        self.session_token = session_token or secrets.token_bytes(16)
        if len(self.session_token) != 16:
            raise ValueError("P2P session token must be exactly 16 bytes")
        self._tx_seq = 1
        self._rx_next = 1
        self._unacked = {}
        self._rx_buffer = {}
        self._state_lock = threading.Lock()
        self._tcp_sock = None
        self._tcp_ready = threading.Event()
        self._transport_thread = None
        self._tcp_out_queue = bytearray()
        self._tcp_out_eof = False
        # Wakes _tcp_outbound_loop when there are TCP bytes to move (or a
        # stop) - the loop used to poll every 10ms around the clock.
        self._outbound_wake = threading.Condition(self._state_lock)
        self._tcp_in_queue = queue.Queue(maxsize=MAX_RX_BUFFER_FRAMES)
        self._last_peer_seen = time.monotonic()
        self._last_ping = 0.0
        self._pending_ping = None
        self._rtt_samples = []
        self._metrics_started = time.monotonic()
        self._frames_sent = 0
        self._frames_received = 0
        self._bytes_sent = 0
        self._bytes_received = 0
        self._retransmits = 0
        self._dropped_frames = 0
        self.closed_reason = None
        self._retransmit_count = {}

    def get_local_candidate(self) -> dict:
        ip, port = stun_get_public_endpoint(self._sock)
        self.public_endpoint = (ip, port)
        return {"ip": ip, "port": port}

    @property
    def udp_socket(self) -> socket.socket:
        """The underlying UDP socket - probe_nat() runs its diagnostics on
        this very socket so the advertised candidate IS the probed one."""
        return self._sock

    # ---- raw-pipe hooks -----------------------------------------------------
    # The transport loop below is pipe-agnostic: everything funnels through
    # these three hooks. The base class implements the classic punched-UDP
    # pipe; HybridSession overrides them to add the signalling-relay pipe and
    # the coordinated punch, without touching the reliable-stream machinery.

    def _poll_inbound(self) -> "tuple[bytes | None, object]":
        """One inbound poll. Returns (data, addr), or (None, None) for
        'nothing this tick'. Raises _PipeClosed when the pipe died and the
        transport loop must stop."""
        try:
            return self._sock.recvfrom(65535)
        except socket.timeout:
            return None, None
        except OSError:
            raise _PipeClosed()

    def _accept_raw(self, data: bytes, addr) -> bool:
        """Gate for raw datagrams before frame parsing. The base pipe only
        ever accepts the peer's exact endpoint."""
        return addr == self.peer_endpoint

    def _note_frame_source(self, addr) -> None:
        """Called with the source of every frame that parsed AND
        authenticated. Hook for handover logic; no-op on the base pipe."""

    def connect(self, peer_candidate: dict) -> None:
        self.peer_endpoint = (peer_candidate["ip"], int(peer_candidate["port"]))
        self._sock.settimeout(0.2)
        deadline = time.monotonic() + PUNCH_ATTEMPT_S
        last_sent = 0.0
        while time.monotonic() < deadline:
            now = time.monotonic()
            if now - last_sent >= PUNCH_INTERVAL_S:
                try:
                    self._sock.sendto(PUNCH_PAYLOAD, self.peer_endpoint)
                except OSError:
                    pass
                last_sent = now
            try:
                data, addr = self._sock.recvfrom(2048)
                if data == PUNCH_PAYLOAD:
                    self._sock.sendto(PUNCH_PAYLOAD, addr)
                    self._connected.set()
                    break
            except socket.timeout:
                continue
            except OSError:
                break

        if not self._connected.is_set():
            raise P2PError(
                "Couldn't connect directly to your friend - one or both of "
                "you may be behind a NAT this can't punch through. Cubeon "
                "doesn't run a relay server, so there's no fallback for "
                "this connection type."
            )

        self._start_transport()
        if not self._wait_transport_ready():
            raise P2PError("The direct path opened, but the P2P transport handshake timed out.")

    def _frame(self, kind: int, seq: int, ack: int, payload: bytes = b"") -> bytes:
        header = self._HEADER.pack(self._MAGIC, self._VERSION, kind,
                                   self.session_token, seq, ack, len(payload))
        # The session token is a room capability delivered over the authenticated
        # friends signalling channel. Use it as the HMAC key as well, so a packet
        # that is copied, modified, or injected on the UDP path is rejected before
        # it can touch the Minecraft TCP socket. The tag is intentionally truncated
        # to 128 bits to keep the per-frame overhead small.
        tag = hmac.new(self.session_token, header + payload, hashlib.sha256).digest()[:self._AUTH_TAG_BYTES]
        return header + payload + tag

    def _parse_frame(self, data: bytes):
        if len(data) < self._HEADER.size + self._AUTH_TAG_BYTES:
            return None
        header = data[:self._HEADER.size]
        magic, version, kind, token, seq, ack, size = self._HEADER.unpack(header)
        if magic != self._MAGIC or version != self._VERSION or not hmac.compare_digest(token, self.session_token):
            return None
        payload_end = self._HEADER.size + size
        if size > self._MAX_PAYLOAD or payload_end + self._AUTH_TAG_BYTES != len(data):
            return None
        payload = data[self._HEADER.size:payload_end]
        tag = data[payload_end:]
        expected = hmac.new(self.session_token, header + payload, hashlib.sha256).digest()[:self._AUTH_TAG_BYTES]
        if not hmac.compare_digest(tag, expected):
            return None
        return kind, seq, ack, payload

    def _send_raw(self, packet: bytes) -> None:
        if self.peer_endpoint:
            try:
                sent = self._sock.sendto(packet, self.peer_endpoint)
                self._frames_sent += 1
                self._bytes_sent += sent
            except OSError:
                self._dropped_frames += 1

    def metrics(self) -> dict:
        """A lightweight snapshot suitable for UI diagnostics."""
        samples = list(self._rtt_samples)
        return {
            "connected": self._transport_ready.is_set(),
            "peer": self.peer_endpoint,
            "rtt_ms": round(sum(samples) / len(samples) * 1000, 1) if samples else None,
            "rtt_samples": len(samples),
            "frames_sent": self._frames_sent,
            "frames_received": self._frames_received,
            "bytes_sent": self._bytes_sent,
            "bytes_received": self._bytes_received,
            "retransmits": self._retransmits,
            "dropped_frames": self._dropped_frames,
            "unacked": len(self._unacked),
            "last_peer_seen_s": round(max(0.0, time.monotonic() - self._last_peer_seen), 2),
            "closed_reason": self.closed_reason,
        }

    def _start_transport(self) -> None:
        if self._transport_thread and self._transport_thread.is_alive():
            return
        self._transport_thread = threading.Thread(
            target=self._transport_loop, name="cubeon-p2p-transport", daemon=True)
        self._transport_thread.start()
        if self.is_host:
            threading.Thread(target=self._tcp_delivery_loop,
                             name="cubeon-p2p-tcp-delivery", daemon=True).start()
            threading.Thread(target=self._tcp_outbound_loop,
                             name="cubeon-p2p-tcp-outbound", daemon=True).start()
            return
        # The joiner exposes a real TCP socket for Minecraft to connect to.
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(0.5)
        self._local_listener = listener
        self.local_relay_port = listener.getsockname()[1]
        threading.Thread(target=self._accept_joiner_client,
                         name="cubeon-p2p-local-listener", daemon=True).start()
        threading.Thread(target=self._tcp_delivery_loop,
                         name="cubeon-p2p-tcp-delivery", daemon=True).start()
        threading.Thread(target=self._tcp_outbound_loop,
                         name="cubeon-p2p-tcp-outbound", daemon=True).start()

    def _wait_transport_ready(self) -> bool:
        # The transport handshake is separate from the NAT punch. This avoids
        # declaring success when only the punch packet reached the peer.
        return self._transport_ready.wait(self._CONNECT_TIMEOUT_S)

    def _transport_loop(self) -> None:
        """Run the reliable UDP transport and TCP bridge.

        The first implementation could silently drop TCP bytes whenever the
        retransmission window was full because it read from the TCP socket
        before checking capacity. This version queues TCP bytes, bounds every
        receive/send buffer, retransmits with a retry ceiling, and keeps a
        lightweight heartbeat so dead peers do not leave Minecraft hanging
        forever.
        """
        self._sock.settimeout(self._POLL_S)
        last_retx = time.monotonic()
        self._last_peer_seen = time.monotonic()
        while not self._stop.is_set():
            now = time.monotonic()
            if not self._transport_ready.is_set() and now - self._last_ping >= 0.5:
                self._send_raw(self._frame(self._HELLO, 0, self._rx_next - 1))
                self._last_ping = now
            elif self._transport_ready.is_set() and now - self._last_ping >= TRANSPORT_PING_S:
                nonce = struct.pack("!Q", time.monotonic_ns())
                self._pending_ping = (nonce, now)
                self._send_raw(self._frame(self._PING, 0, self._rx_next - 1, nonce))
                self._last_ping = now

            if self._transport_ready.is_set() and now - self._last_peer_seen > TRANSPORT_IDLE_TIMEOUT_S:
                self._stop_with_reason("P2P peer timed out")
                break

            try:
                data, addr = self._poll_inbound()
            except _PipeClosed:
                break

            if data is not None and self._accept_raw(data, addr):
                frame = self._parse_frame(data)
                if frame:
                    self._frames_received += 1
                    self._bytes_received += len(data)
                    self._last_peer_seen = time.monotonic()
                    self._note_frame_source(addr)
                    kind, seq, ack, payload = frame
                    self._handle_frame(kind, seq, ack, payload)
                else:
                    self._dropped_frames += 1

            now = time.monotonic()
            if now - last_retx >= self._RETX_S:
                last_retx = now
                failed = False
                with self._state_lock:
                    for seq, (packet, sent_at) in list(self._unacked.items()):
                        if now - sent_at < self._RETX_S:
                            continue
                        count = self._retransmit_count.get(seq, 0) + 1
                        if count > MAX_RETRANSMITS:
                            failed = True
                            break
                        self._send_raw(packet)
                        self._unacked[seq] = (packet, now)
                        self._retransmit_count[seq] = count
                        self._retransmits += 1
                if failed:
                    self._stop_with_reason("P2P transport lost packets repeatedly")
                    break


    def _stop_with_reason(self, reason: str) -> None:
        self.closed_reason = reason
        self._stop.set()
        # Close local sockets immediately so Minecraft and waiting accept()
        # calls observe the failed session instead of hanging until the next
        # UI action. close() remains safe to call afterwards.
        for sock in (self._tcp_sock, self._local_listener):
            try:
                if sock:
                    sock.close()
            except OSError:
                pass

    def _handle_frame(self, kind: int, seq: int, ack: int, payload: bytes) -> None:
        with self._state_lock:
            freed = False
            for sent_seq in list(self._unacked):
                if sent_seq <= ack:
                    self._unacked.pop(sent_seq, None)
                    self._retransmit_count.pop(sent_seq, None)
                    freed = True
        if freed:
            self._wake_outbound()  # ACK freed send-window space: move more TCP bytes

        if kind == self._HELLO:
            self._send_raw(self._frame(self._ACK, 0, self._rx_next - 1))
            self._transport_ready.set()
            return
        if kind == self._PING:
            self._send_raw(self._frame(self._ACK, 0, self._rx_next - 1, payload[:8]))
            return
        if kind == self._ACK:
            if payload and self._pending_ping and payload == self._pending_ping[0]:
                sample = max(0.0, time.monotonic() - self._pending_ping[1])
                self._rtt_samples.append(sample)
                if len(self._rtt_samples) > MAX_PING_SAMPLES:
                    self._rtt_samples.pop(0)
                self._pending_ping = None
            if not self._transport_ready.is_set():
                self._transport_ready.set()
            return
        if kind == self._DATA:
            if seq < self._rx_next:
                self._send_raw(self._frame(self._ACK, 0, self._rx_next - 1))
                return
            with self._state_lock:
                if seq not in self._rx_buffer:
                    if len(self._rx_buffer) >= MAX_RX_BUFFER_FRAMES:
                        self._stop_with_reason("P2P receive buffer overflow")
                        return
                    self._rx_buffer[seq] = payload
            # Deliver BEFORE acknowledging: the ACK is cumulative
            # (rx_next - 1), so acking before the flush would not cover this
            # very frame and the sender would needlessly retransmit every
            # single DATA frame once. TCP delivery can block briefly on a
            # full local socket and must not prevent the sender from making
            # progress or cause avoidable retransmission storms.
            self._flush_received()
            self._send_raw(self._frame(self._ACK, 0, self._rx_next - 1))
            self._transport_ready.set()
            return
        if kind == self._FIN:
            self._send_raw(self._frame(self._ACK, 0, max(0, self._rx_next - 1)))
            self._stop_with_reason("Minecraft TCP connection closed")

    def _flush_received(self) -> None:
        while True:
            with self._state_lock:
                payload = self._rx_buffer.pop(self._rx_next, None)
                if payload is not None:
                    self._rx_next += 1
            if payload is None:
                return
            try:
                self._tcp_in_queue.put(payload, timeout=1.0)
            except queue.Full:
                self._stop_with_reason("P2P local TCP delivery queue overflow")
                return

    def _tcp_delivery_loop(self) -> None:
        # The joiner must not consume frames until Minecraft has attached to
        # the local relay - a byte dropped here would silently desync the TCP
        # stream (the host only sends once the joiner's client talks, but a
        # wait is cheap insurance against exactly that class of bug). The
        # host connects to its LAN server lazily below instead.
        if not self.is_host:
            while not self._tcp_ready.wait(0.2):
                if self._stop.is_set():
                    return
        while not self._stop.is_set():
            try:
                data = self._tcp_in_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if self.is_host and not self._tcp_sock:
                try:
                    sock = socket.create_connection(("127.0.0.1", int(self.lan_port)), timeout=5)
                    # Match the joiner's relay socket: Minecraft can pause
                    # reading while changing screens or saving, and a 50 ms
                    # send timeout turned every such pause into a dead session.
                    sock.settimeout(2.0)
                    self._tcp_sock = sock
                    self._tcp_ready.set()
                except OSError:
                    self._stop_with_reason("Could not connect to the Minecraft LAN socket")
                    return
            self._tcp_send(data)

    def _tcp_send(self, data: bytes) -> None:
        sock = self._tcp_sock
        if not sock:
            # Unreachable in normal flow (the delivery loop gates on
            # _tcp_ready / connects first), but if it ever happens the bytes
            # must NOT vanish silently - a missing chunk permanently desyncs
            # the TCP stream, so fail the session loudly instead.
            self._stop_with_reason("P2P local TCP socket disappeared mid-stream")
            return
        try:
            sock.sendall(data)
        except (OSError, socket.timeout):
            self._stop_with_reason("Minecraft TCP connection closed")

    def _tcp_outbound_loop(self) -> None:
        # Event-driven (2026-09-09): this used to poll every 10ms forever -
        # ~100 idle wakeups/second per P2P session. Now it sleeps on
        # _outbound_wake (nudged when an ACK frees send-window space or the
        # session stops) with a 0.2s timeout that bounds the window-full
        # backpressure case even if a nudge raced.
        while not self._stop.is_set():
            if not self._tcp_ready.wait(0.2):
                continue
            with self._outbound_wake:
                self._outbound_wake.wait(0.2)
            if self._stop.is_set():
                return
            self._drain_tcp_outbound()

    def _wake_outbound(self) -> None:
        with self._outbound_wake:
            self._outbound_wake.notify_all()

    def _drain_tcp_outbound(self) -> None:
        sock = self._tcp_sock
        if not sock or self._stop.is_set():
            return

        # Only read from TCP when there is room to turn the bytes into reliable
        # UDP frames. This prevents the old read-then-drop data-loss bug.
        with self._state_lock:
            window_full = len(self._unacked) >= MAX_UNACKED_FRAMES
        if not window_full and len(self._tcp_out_queue) < 256 * self._MAX_PAYLOAD:
            try:
                data = sock.recv(65535)
            except socket.timeout:
                data = None
            except OSError:
                self._stop_with_reason("Minecraft TCP connection closed unexpectedly")
                return
            if data == b'':
                self._tcp_out_eof = True
            elif data:
                self._tcp_out_queue.extend(data)

        while self._tcp_out_queue:
            with self._state_lock:
                if len(self._unacked) >= MAX_UNACKED_FRAMES:
                    break
                seq = self._tx_seq
                self._tx_seq += 1
            chunk = bytes(self._tcp_out_queue[:self._MAX_PAYLOAD])
            del self._tcp_out_queue[:len(chunk)]
            packet = self._frame(self._DATA, seq, self._rx_next - 1, chunk)
            with self._state_lock:
                self._unacked[seq] = (packet, time.monotonic())
                self._retransmit_count[seq] = 0
            self._send_raw(packet)

        if self._tcp_out_eof and not self._tcp_out_queue:
            self._send_raw(self._frame(self._FIN, 0, self._rx_next - 1))
            self._tcp_out_eof = False

    def _accept_joiner_client(self) -> None:
        listener = self._local_listener
        if not listener:
            return
        while not self._stop.is_set():
            try:
                conn, _ = listener.accept()
                self._tcp_sock = conn
                # Local Minecraft can momentarily stop reading while changing
                # screens/world state. Give sendall enough room before treating
                # it as a dead session.
                conn.settimeout(2.0)
                self._tcp_ready.set()
                return
            except socket.timeout:
                continue
            except OSError:
                return

    def reconnect(self, peer_candidate: dict) -> None:
        """Retry the direct path before Minecraft's TCP stream is established.

        A NAT mapping can disappear during the invite/sync phase. Reusing the
        same session token lets the caller retry without minting another room.
        Once a Minecraft TCP socket is attached, a seamless resume is not
        possible because Minecraft's own TCP stream is stateful; callers should
        close that session and create a fresh Minecraft connection instead.
        """
        if self._tcp_ready.is_set():
            raise P2PError("This P2P session already has a Minecraft connection and cannot resume in place.")
        self._stop.set()
        try:
            self._sock.close()
        except OSError:
            pass
        self._stop = threading.Event()
        self._connected.clear()
        self._transport_ready.clear()
        self._unacked.clear()
        self._rx_buffer.clear()
        self._retransmit_count.clear()
        self._tx_seq = 1
        self._rx_next = 1
        self.closed_reason = None
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("0.0.0.0", 0))
        self.local_port = self._sock.getsockname()[1]
        self.peer_endpoint = None
        self.public_endpoint = None
        self.connect(peer_candidate)


    def close(self) -> None:
        if not self._stop.is_set() and self.peer_endpoint:
            try:
                self._send_raw(self._frame(self._FIN, 0, max(0, self._rx_next - 1)))
            except Exception:
                pass
        self._stop.set()
        self._wake_outbound()  # unblock the outbound loop so it can exit
        for sock in (self._tcp_sock, self._local_listener, self._sock):
            try:
                if sock:
                    sock.close()
            except OSError:
                pass


# Sentinel "address" marking frames that arrived over the signalling relay
# rather than a real UDP endpoint - never equals a real (ip, port) tuple.
_RELAY_ADDR = ("@relay", 0)


class HybridSession(PunchSession):
    """Relayed Signalling with Direct Hole-Punch Handover.

    The SAME reliable CUBP stream as PunchSession (identical framing, seq/ACK,
    retransmission and HMAC - so seq numbering continues seamlessly across the
    swap), but with a swappable raw pipe underneath:

      PHASE 1 - SETUP (relay): frames ride the friends WebSocket from the
        first moment. The peer is reachable with certainty before any NAT
        work starts; the joiner can enter the world while punching is still
        running.
      PHASE 2 - DIAGNOSTICS + COORDINATED SPRAY: both sides run probe_nat(),
        exchange the results over the relay, then punch on a synchronized
        clock (p2p_punch_plan) across each other's predicted public port
        range instead of one guessed port.
      PHASE 3 - HANDOVER: the first frame that parses AND authenticates
        arriving straight over UDP proves the direct path works inbound.
        Each side announces p2p_direct_up over the relay; once a side has
        seen direct traffic AND the peer's announcement (or after a short
        confirmation window - which also covers a peer that punches but
        doesn't speak this protocol), it flips outgoing frames to the UDP
        pipe and stops using the relay for data.

    If the spray never lands (hard symmetric NAT / CGNAT), the session just
    stays on the relay forever - degraded ping, never a failure. Punching
    keeps retrying in rounds in the background, so an upgrade can still land
    minutes into the session.
    """

    def __init__(self, *, is_host: bool, lan_port: "int | None" = None,
                 session_token: "bytes | None" = None, send_signal=None):
        super().__init__(is_host=is_host, lan_port=lan_port,
                         session_token=session_token)
        self._send_signal = send_signal   # (payload dict) -> None, bound to room+peer
        self.nat_probe = None             # our probe_nat() result (set by caller)
        self.peer_nat_info = None         # peer's probe result (from offer/answer)
        self._initiator = bool(is_host)   # host arms coordinated rounds
        self._active_pipe = "relay"       # "relay" | "udp"
        self.mode = "relay"               # UI-facing: relay -> handover -> direct
        self._direct_rx = threading.Event()
        self._peer_direct_up = threading.Event()
        self._observed_peer_addr = None   # authenticated UDP source addr
        self._spray_start = None          # monotonic deadline for next round
        self._spray_cond = threading.Condition()
        self._punch_thread = None
        # UI-notification hooks: set once the first coordinated round ends
        # WITHOUT a direct connection (=> tell the user they're on relay),
        # and once an upgrade lands later (=> tell them ping improved).
        self.punch_failed_round = False
        self.upgraded_to_direct = False

    # ---- lifecycle ----------------------------------------------------------

    def begin(self) -> None:
        """Start the transport over the relay immediately. No peer endpoint
        is needed - that's the whole point of relay-first."""
        self._start_transport()

    def begin_punch(self, nat_probe: dict, peer_nat_info: dict) -> None:
        """Feed in both sides' diagnostics (already exchanged over the relay)
        and start the coordinated punch worker. Idempotent."""
        self.nat_probe = nat_probe or {}
        self.peer_nat_info = peer_nat_info or {}
        cand = self.peer_nat_info.get("candidate") or {}
        if cand.get("ip"):
            # Advertised candidate seeds the endpoint; the spray covers drift.
            self.peer_endpoint = (cand["ip"], int(cand["port"]))
        if self._punch_thread and self._punch_thread.is_alive():
            return
        self._punch_thread = threading.Thread(
            target=self._punch_worker, name="cubeon-p2p-coordinated-punch",
            daemon=True)
        self._punch_thread.start()

    def on_signal_data(self, data: dict) -> bool:
        """Entry point for P2P control signals and relay-carried CUBP frames,
        dispatched by the friends-tab signal handler. Returns True when the
        payload belonged to this session."""
        kind = data.get("kind")
        if kind == "p2p_relay_frame":
            try:
                raw = base64.b64decode(data.get("data_b64") or "")
            except (TypeError, ValueError):
                return True
            if raw:
                try:
                    self._relay_frames_in.put_nowait(raw)
                except queue.Full:
                    self._stop_with_reason("Relay receive buffer overflow")
            return True
        if kind == "p2p_direct_up":
            self._peer_direct_up.set()
            with self._spray_cond:
                self._spray_cond.notify_all()
            self._evaluate_handover()
            return True
        if kind == "p2p_punch_plan":
            delay_ms = data.get("delay_ms")
            try:
                delay = max(0.0, float(delay_ms)) / 1000.0
            except (TypeError, ValueError):
                return True
            with self._spray_cond:
                self._spray_start = time.monotonic() + delay
                self._spray_cond.notify_all()
            return True
        return False

    # ---- pipe overrides -----------------------------------------------------

    @property
    def _relay_frames_in(self) -> queue.Queue:
        # Lazily created so __init__ stays simple and reconnect()-style
        # resets can't orphan the queue.
        q = getattr(self, "_relay_q", None)
        if q is None:
            q = queue.Queue(maxsize=MAX_RX_BUFFER_FRAMES * 4)
            self._relay_q = q
        return q

    def _poll_inbound(self) -> "tuple[bytes | None, object]":
        """Relay frames first (they're ordered and already paid for), then
        the UDP socket. A dead UDP socket does NOT kill the session while
        the relay still works - that's the resilience this design buys."""
        try:
            return self._relay_frames_in.get_nowait(), _RELAY_ADDR
        except queue.Empty:
            pass
        try:
            return self._sock.recvfrom(65535)
        except socket.timeout:
            return None, None
        except OSError:
            return None, None

    def _accept_raw(self, data: bytes, addr) -> bool:
        if addr is _RELAY_ADDR:
            return True
        if data == PUNCH_PAYLOAD:
            # Bare coordinated-spray probe, not a CUBP frame. Echo it so the
            # peer knows their outbound path works, then IMMEDIATELY escalate
            # to an authenticated PING frame sent straight over UDP - this is
            # the spec's HANDSHAKE_ACK. Bare probes prove reachability but
            # prove nothing about identity (anyone can copy a packet); only
            # the HMAC proves the direct path carries OUR stream, and only
            # an authenticated frame flips the handover logic.
            try:
                self._sock.sendto(PUNCH_PAYLOAD, addr)
                self._sock.sendto(self._frame(self._PING, 0, max(0, self._rx_next - 1),
                                              struct.pack("!Q", time.monotonic_ns())),
                                  addr)
            except OSError:
                pass
            return False
        # Before handover, accept authenticated frames from ANY UDP source:
        # under symmetric NAT the peer's true public port may differ from its
        # advertised candidate, and only the HMAC proves a frame is ours.
        if not self._direct_rx.is_set():
            return True
        return addr == self._observed_peer_addr

    def _note_frame_source(self, addr) -> None:
        if addr is _RELAY_ADDR or addr is None:
            return
        first = not self._direct_rx.is_set()
        self._observed_peer_addr = addr
        self._direct_rx.set()
        if first:
            self._first_direct_at = time.monotonic()
            self.mode = "handover"
            # Tell the peer the direct path reached us (spec step 4: the ACK
            # goes straight back over the P2P pipe too - our next CUBP
            # frames/ACKs now flow via UDP since we accept them).
            self._send_control({"kind": "p2p_direct_up"})
        self._evaluate_handover()

    def _send_raw(self, packet: bytes) -> None:
        if self._active_pipe == "udp" and self.peer_endpoint:
            try:
                sent = self._sock.sendto(packet, self.peer_endpoint)
                self._frames_sent += 1
                self._bytes_sent += sent
            except OSError:
                self._dropped_frames += 1
            return
        if not self._send_signal:
            return
        try:
            self._send_signal({
                "kind": "p2p_relay_frame",
                "data_b64": base64.b64encode(packet).decode("ascii"),
            })
            self._frames_sent += 1
            self._bytes_sent += len(packet)
        except Exception:
            self._dropped_frames += 1

    # ---- handover -----------------------------------------------------------

    def _send_control(self, payload: dict) -> None:
        if not self._send_signal:
            return
        try:
            self._send_signal(payload)
        except Exception:
            pass

    def _evaluate_handover(self) -> None:
        if self._active_pipe == "udp" or not self._direct_rx.is_set():
            return
        # Flip once the peer confirmed - or, if they never will (an older
        # build that punches without this signalling), once we've been
        # receiving authenticated UDP traffic long enough that their outbound
        # path is demonstrably UDP-only anyway.
        confirmed = self._peer_direct_up.is_set()
        first_at = getattr(self, "_first_direct_at", None)
        timed_out = (first_at is not None and
                     time.monotonic() - first_at > HANDOVER_UDP_CONFIRM_S)
        if not confirmed and not timed_out:
            return
        if self._observed_peer_addr:
            self.peer_endpoint = self._observed_peer_addr
        self._active_pipe = "udp"
        was_relay = self.mode != "direct"
        self.mode = "direct"
        if was_relay:
            # Landed mid-session (possibly after minutes on relay).
            self.upgraded_to_direct = True

    # ---- coordinated punch --------------------------------------------------

    def _punch_worker(self) -> None:
        """Round-based coordinated spraying until the direct path is live or
        the session ends. The initiator (host) arms each round by sending
        p2p_punch_plan over the relay; the responder starts PLAN_DELAY_MS
        after receiving it, the initiator after the same delay plus a fudge -
        close enough that the multi-second spray windows overlap heavily."""
        round_no = 0
        while not self._stop.is_set() and not self._direct_rx.is_set():
            if self._initiator:
                start = self._arm_round(round_no)
                if self._stop.is_set():
                    return
                self._spray_round(start)
                round_no += 1
                if not self._direct_rx.is_set() and not self.punch_failed_round:
                    # First full coordinated round without a landing: fair to
                    # tell the user the session is riding the relay for now.
                    self.punch_failed_round = True
                if not self._stop.is_set() and not self._direct_rx.is_set():
                    time.sleep(PUNCH_RETRY_S)
            else:
                # Responder: purely plan-driven - the p2p_punch_plan signal
                # sets _spray_start and wakes us; no self-timed retries, so
                # we never drift out of sync with the initiator's rounds.
                with self._spray_cond:
                    while self._spray_start is None and not self._stop.is_set() \
                            and not self._direct_rx.is_set():
                        self._spray_cond.wait(2.0)
                    start = self._spray_start
                    self._spray_start = None
                if self._stop.is_set() or start is None:
                    continue
                self._spray_round(start)
                round_no += 1

    def _arm_round(self, round_no: int) -> "float | None":
        if not self._initiator:
            return None
        delay_s = PLAN_DELAY_MS / 1000.0
        self._send_control({"kind": "p2p_punch_plan", "round": round_no,
                            "delay_ms": PLAN_DELAY_MS})
        # Fudge: roughly half a relay RTT so both sprays overlap. The plan
        # travels one way (~RTT/2); starting slightly late errs toward more
        # overlap with the responder's window, which is what lands packets.
        return time.monotonic() + delay_s + 0.25

    def _spray_targets(self) -> "list[tuple[str, int]]":
        """Predicted public endpoints of the peer: its advertised candidate
        plus the observed probe-port range widened by the spray span, nudged
        further out by the peer's measured allocation delta."""
        info = self.peer_nat_info or {}
        cand = info.get("candidate") or {}
        ip = cand.get("ip")
        if not ip:
            return []
        ports = set()
        base_ports = []
        if cand.get("port"):
            base_ports.append(int(cand["port"]))
        for p in info.get("probes") or []:
            try:
                base_ports.append(int(p))
            except (TypeError, ValueError):
                continue
        delta = info.get("delta") or 0
        try:
            delta = int(delta)
        except (TypeError, ValueError):
            delta = 0
        for bp in base_ports:
            for off in range(SPRAY_LOW_OFFSET, SPRAY_HIGH_OFFSET + 1):
                ports.add(bp + off)
            if delta:
                ports.add(bp + delta)
                ports.add(bp + delta * 2)
        targets = [(ip, p) for p in sorted(ports) if 1024 <= p <= 65535]
        return targets[:SPRAY_MAX_TARGETS]

    def _spray_round(self, start: float) -> None:
        wait = start - time.monotonic()
        if wait > 0:
            with self._spray_cond:
                self._spray_cond.wait(min(wait, PUNCH_RETRY_S))
            if self._stop.is_set():
                return
        targets = self._spray_targets()
        if self.peer_endpoint:
            targets.append(self.peer_endpoint)
        end = time.monotonic() + SPRAY_ROUND_S
        while time.monotonic() < end and not self._stop.is_set() \
                and not self._direct_rx.is_set():
            for t in targets:
                try:
                    self._sock.sendto(PUNCH_PAYLOAD, t)
                except OSError:
                    return
            time.sleep(SPRAY_BURST_INTERVAL_S)

    # ---- reporting ----------------------------------------------------------

    def metrics(self) -> dict:
        m = super().metrics()
        m["mode"] = self.mode
        if self.nat_probe or self.peer_nat_info:
            m["nat"] = {
                "local_symmetric": bool((self.nat_probe or {}).get("symmetric")),
                "peer_symmetric": bool((self.peer_nat_info or {}).get("symmetric")),
            }
        return m


class RelaySession:
    """Punch-free fallback for peers that can't hole-punch (CGNAT, symmetric
    NAT): carries the same Minecraft TCP stream over the friends signalling
    channel instead of a punched UDP path.

    WHY THIS IS SOUND: the signalling channel is a WebSocket - i.e. TCP -
    through the friends Durable Object. That gives ordered, reliable delivery
    for free, so unlike PunchSession this class needs no framing protocol,
    ACKs or retransmission: it just chunks local TCP bytes into base64
    signals ("p2p_relay_chunk") and reassembles them on the other side.
    Authentication is inherited from the signalling layer (both room members
    are authenticated friends; the Worker routes only between them), so no
    session token is needed here.

    The interface deliberately mirrors PunchSession where the UI consumes it:
    `local_relay_port`, `closed_reason`, `metrics()`, `close()` and `_stop`
    mean exactly the same thing, so friends_service's join flow, watchdog and
    status payload work unchanged whichever session class ended up in
    the session dict's "punch" slot.

    TRADE-OFFS vs PunchSession (why this is only a fallback):
      * latency: traffic bounces through Cloudflare (~2x the ping to the
        friends server) instead of direct;
      * throughput: bounded by WebSocket message rate rather than raw UDP.
    Direct is always attempted first; this runs only after the punch fails.
    """

    def __init__(self, *, is_host: bool, lan_port: "int | None" = None, send_signal=None):
        self.is_host = is_host
        self.lan_port = lan_port
        self._send_signal = send_signal  # (payload dict) -> None, bound to (room, peer)
        self._stop = threading.Event()
        self.closed_reason = None
        self.local_relay_port = None     # joiner side: the port Minecraft connects to
        self._tcp_sock = None
        self._tcp_ready = threading.Event()
        self._local_listener = None
        self._in_queue = queue.Queue(maxsize=MAX_RX_BUFFER_FRAMES)
        self._seq_out = 0
        self._last_traffic = time.monotonic()
        self._started = time.monotonic()
        self._bytes_in = 0
        self._bytes_out = 0

    # ---- lifecycle ----------------------------------------------------------

    def start(self) -> None:
        """Bind the local endpoint and start pumping. Joiner: opens the TCP
        relay listener Minecraft will connect to. Host: nothing to bind - the
        bridge into the LAN server connects lazily on first inbound byte,
        exactly like PunchSession's host path."""
        if self.is_host:
            threading.Thread(target=self._delivery_loop,
                             name="cubeon-p2p-relay-delivery", daemon=True).start()
            threading.Thread(target=self._outbound_loop,
                             name="cubeon-p2p-relay-outbound", daemon=True).start()
            threading.Thread(target=self._idle_watchdog,
                             name="cubeon-p2p-relay-idle", daemon=True).start()
            return
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen(1)
        listener.settimeout(0.5)
        self._local_listener = listener
        self.local_relay_port = listener.getsockname()[1]
        threading.Thread(target=self._accept_local_client,
                         name="cubeon-p2p-relay-listener", daemon=True).start()
        threading.Thread(target=self._delivery_loop,
                         name="cubeon-p2p-relay-delivery", daemon=True).start()
        threading.Thread(target=self._outbound_loop,
                         name="cubeon-p2p-relay-outbound", daemon=True).start()
        threading.Thread(target=self._idle_watchdog,
                         name="cubeon-p2p-relay-idle", daemon=True).start()

    def close(self) -> None:
        self._stop.set()
        for sock in (self._tcp_sock, self._local_listener):
            try:
                if sock:
                    sock.close()
            except OSError:
                pass

    def metrics(self) -> dict:
        return {
            "connected": True,   # banner shows quality text via rtt_ms/mode
            "mode": "relay",
            "rtt_ms": None,      # honest: we don't measure RTT over the WS path
            "peer": None,
            "frames_sent": None,
            "frames_received": None,
            "bytes_sent": self._bytes_out,
            "bytes_received": self._bytes_in,
            "retransmits": 0,    # WS is reliable; there is nothing to resend
            "dropped_frames": 0,
            "unacked": 0,
            "last_peer_seen_s": round(time.monotonic() - self._last_traffic, 2),
            "closed_reason": self.closed_reason,
        }

    # ---- data path ----------------------------------------------------------

    def on_relay_chunk(self, data: dict) -> None:
        """Feed one incoming p2p_relay_chunk signal here (called from
        friends_service's signal dispatcher)."""
        if self._stop.is_set():
            return
        try:
            seq = int(data.get("seq"))
            payload = base64.b64decode(data.get("data_b64") or "")
        except (TypeError, ValueError):
            return
        self._last_traffic = time.monotonic()
        try:
            self._in_queue.put((seq, payload), timeout=1.0)
        except queue.Full:
            self._stop_with_reason("Relay receive buffer overflow")

    def _delivery_loop(self) -> None:
        # Same gate as PunchSession: never consume inbound bytes before the
        # local Minecraft socket exists - a silent drop would desync the
        # stream. The host connects to its LAN server lazily below instead.
        if not self.is_host:
            while not self._tcp_ready.wait(0.2):
                if self._stop.is_set():
                    return
        while not self._stop.is_set():
            try:
                _, payload = self._in_queue.get(timeout=0.2)
            except queue.Empty:
                continue
            if self.is_host and not self._tcp_sock:
                try:
                    sock = socket.create_connection(("127.0.0.1", int(self.lan_port)), timeout=5)
                    # Same reasoning as PunchSession: Minecraft pauses reading
                    # during saves/screen changes; 50 ms timeouts killed sessions.
                    sock.settimeout(2.0)
                    self._tcp_sock = sock
                    self._tcp_ready.set()
                except OSError:
                    self._stop_with_reason("Could not connect to the Minecraft LAN socket")
                    return
            self._tcp_send(payload)

    def _tcp_send(self, data: bytes) -> None:
        sock = self._tcp_sock
        if not sock:
            self._stop_with_reason("Relay local TCP socket disappeared mid-stream")
            return
        try:
            sock.sendall(data)
            self._bytes_in += len(data)
        except (OSError, socket.timeout):
            self._stop_with_reason("Minecraft TCP connection closed")

    def _outbound_loop(self) -> None:
        # Wait until the local side exists: host bridges lazily, joiner waits
        # for Minecraft. Reading earlier would silently lose nothing (the
        # socket isn't there yet), but waiting keeps ordering trivially safe.
        if not self.is_host:
            while not self._tcp_ready.wait(0.2):
                if self._stop.is_set():
                    return
        while not self._stop.is_set():
            sock = self._tcp_sock
            if not sock:
                time.sleep(0.05)
                continue
            try:
                data = sock.recv(64 * 1024)
            except socket.timeout:
                continue
            except OSError:
                if not self._stop.is_set():
                    self._stop_with_reason("Minecraft TCP connection closed unexpectedly")
                return
            if data == b"":
                # Local peer hung up cleanly - tell the other side by closing
                # our end of the relay too.
                self._stop_with_reason("Minecraft closed the connection")
                return
            self._send_chunks(data)

    def _send_chunks(self, data: bytes) -> None:
        if not self._send_signal:
            return
        b64 = base64.b64encode(data).decode("ascii")
        total = (len(b64) + RELAY_CHUNK_BYTES - 1) // RELAY_CHUNK_BYTES
        try:
            for i in range(total):
                if self._stop.is_set():
                    return
                self._seq_out += 1
                # A blocking send IS the backpressure: websocket-client blocks
                # when its buffers fill, which throttles us to the peer's pace
                # without an explicit credit/ACK scheme.
                self._send_signal({
                    "kind": "p2p_relay_chunk",
                    "seq": self._seq_out,
                    "total": total,
                    "data_b64": b64[i * RELAY_CHUNK_BYTES:(i + 1) * RELAY_CHUNK_BYTES],
                })
                self._bytes_out += len(data) // total
        except Exception as e:
            self._stop_with_reason(f"Relay transport failed: {e.__class__.__name__}")

    def _accept_local_client(self) -> None:
        listener = self._local_listener
        if not listener:
            return
        while not self._stop.is_set():
            try:
                conn, _ = listener.accept()
                conn.settimeout(2.0)
                self._tcp_sock = conn
                self._tcp_ready.set()
                return
            except socket.timeout:
                continue
            except OSError:
                return

    def _idle_watchdog(self) -> None:
        """Fail loudly when the relay goes quiet - a dead WebSocket would
        otherwise leave Minecraft staring at a frozen loading screen."""
        while not self._stop.wait(5.0):
            now = time.monotonic()
            # Only arm once real traffic has flowed; the handshake gap before
            # Minecraft speaks can legitimately take a while (mod sync runs
            # in parallel and launch happens after).
            if (self._bytes_in or self._bytes_out) and \
                    now - self._last_traffic > RELAY_IDLE_TIMEOUT_S:
                self._stop_with_reason("Relay connection timed out")
                return

    def _stop_with_reason(self, reason: str) -> None:
        self.closed_reason = reason
        self._stop.set()
        for sock in (self._tcp_sock, self._local_listener):
            try:
                if sock:
                    sock.close()
            except OSError:
                pass


def cleanup_stale_sessions(max_age_s: int = 24 * 60 * 60) -> int:
    """Remove abandoned P2P session state left by a crash or forced exit.

    Only session metadata older than ``max_age_s`` is considered. Cleanup is
    deliberately conservative: it restores renamed local mods through the
    same guarded teardown() path and never deletes global cache content.
    """
    if not os.path.isdir(SESSIONS_DIR):
        return 0
    removed = 0
    cutoff = time.time() - max_age_s
    for name in os.listdir(SESSIONS_DIR):
        if not name.endswith('.json'):
            continue
        path = os.path.join(SESSIONS_DIR, name)
        try:
            if os.path.getmtime(path) >= cutoff:
                continue
            room = name[:-5]
            teardown(room)
            removed += 1
        except OSError:
            continue
    return removed


# A launcher crash must not leave session-only files around indefinitely.
# This runs only at process exit and is intentionally best-effort.
atexit.register(lambda: cleanup_stale_sessions(max_age_s=0))


# ---------------------------------------------------------------------------
# 4. Mod sync - runs in parallel with the network path (roadmap Phase 2b
#    decision: neither blocks the other; joining waits for both).
#
#    Resolution order per missing mod, cheapest/most-correct first:
#      1. Already in the global cache under a hash we recognise -> just link.
#      2. Not in the cache -> ask the host directly over signal() (p2p_modreq
#         / p2p_modchunk) and cache what comes back, so a second joiner (or
#         this same friend next time) never re-asks.
#    There is deliberately no step 2.5 "try Modrinth by hash" - this
#    codebase's Modrinth integration (mods.py/modpacks.py) only ever
#    resolves forward, by project id/slug, never backward from a bare
#    sha256, and Modrinth's own hash-lookup endpoint isn't wired up
#    anywhere here. Adding that would be a real, separate feature, not
#    something to fake in this module - so "not in cache" here really does
#    mean "ask the peer", not silently upgrade to a Modrinth search this
#    codebase can't actually do yet.
# ---------------------------------------------------------------------------

_HASH_CACHE = {}
_HASH_CACHE_LOCK = threading.Lock()

def hash_file(path: str) -> str:
    """SHA-256 with a process-local stat cache.

    P2P manifests are often rebuilt twice during one join (host offer and
    serving requests, or a retry). Re-hashing unchanged jars/configs wastes
    CPU and disk IO. The cache is invalidated by size + mtime_ns and never
    bypasses hashing when either changes.
    """
    absolute = os.path.abspath(path)
    try:
        st = os.stat(absolute)
    except OSError:
        raise
    key = (st.st_size, st.st_mtime_ns)
    with _HASH_CACHE_LOCK:
        cached = _HASH_CACHE.get(absolute)
        if cached and cached[:2] == key:
            return cached[2]
    h = hashlib.sha256()
    with open(absolute, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    digest = h.hexdigest()
    with _HASH_CACHE_LOCK:
        _HASH_CACHE[absolute] = (st.st_size, st.st_mtime_ns, digest)
    return digest


def build_mod_list(mc_version: str, loader: str) -> "list[dict]":
    """Host side: the {sha256, filename, size} list to send in a
    p2p_modlist signal, built from this machine's own active profile - the
    same folder sync_mods_to_game() reads from, so what's listed here is
    exactly what the host is actually running."""
    profile_dir = mods_module.get_profile_dir(mc_version, loader)
    out = []
    for entry in mods_module.list_mods(mc_version, loader):
        if not entry["enabled"]:
            continue  # a disabled mod isn't loaded, so the joiner doesn't need it
        full = os.path.join(profile_dir, entry["filename"])
        try:
            out.append({
                "sha256": hash_file(full),
                "filename": entry["filename"],
                "size": os.path.getsize(full),
            })
        except OSError:
            continue  # file vanished between listing and hashing - skip rather than crash the whole list
    return out


def local_mod_hashes(mc_version: str, loader: str) -> "list[dict]":
    """Joiner side: this machine's own enabled mods for the same
    (mc_version, loader) profile, in the same shape build_mod_list()
    produces, so diff_missing_mods() can compare them directly."""
    return build_mod_list(mc_version, loader)


def resolve_missing_mod_from_cache(sha256_hex: str, dest_dir: str, filename: str) -> "str | None":
    """Step 1 of the resolution order: if the global cache already has a
    jar under this exact sha256 (from an earlier Modrinth install, another
    profile, or a previous P2P session with anyone), link it straight into
    the joiner's profile and skip asking the host entirely. Returns the
    linked path, or None on an actual cache miss - never raises, since a
    miss here just means "fall through to asking the peer", not an error."""
    cached_path = global_mod_cache.cache_path_if_present(sha256_hex)
    if not cached_path:
        return None
    dest_path = os.path.join(dest_dir, filename)
    global_mod_cache.link_into_place(cached_path, dest_path)
    return dest_path


class ModSyncSession:
    """Orchestrates one joiner's mod sync against one host's mod list, over
    a live signal() channel. Owned by the caller (friends_service.py), which
    feeds it incoming p2p_modlist/p2p_modchunk signals and reads
    is_complete()/error to know when to let the join through.

    Host side doesn't need an instance of this - responding to p2p_modreq
    is just read_chunks_for_mod() + a handful of signal() sends, handled
    directly by the caller (see friends_service.py's _on_signal p2p_modreq
    branch), since the host has no diffing to do.
    """

    def __init__(self, *, mc_version: str, loader: str, send_signal):
        self.mc_version = mc_version
        self.loader = loader
        self.profile_dir = mods_module.get_profile_dir(mc_version, loader)
        self._send_signal = send_signal  # (data: dict) -> None, already bound to (room, host_name)
        self.pending: "dict[str, dict]" = {}   # sha256 -> {filename, chunks: [str,...], total}
        self.linked_paths: "list[str]" = []
        self.disabled_paths: "list[dict]" = []  # extra local mods temporarily disabled for this session
        self.newly_linked_from_cache: "list[str]" = []  # already-cached mods, no peer round-trip needed
        self.awaiting_peer: "set[str]" = set()
        self.error: "str | None" = None
        self._done = threading.Event()
        self._started_at = None
        self._last_progress = time.monotonic()

    def is_complete(self) -> bool:
        return self._done.is_set()

    def start(self, host_mod_list: "list[dict]") -> None:
        """Call once, as soon as the p2p_modlist signal arrives. Links
        every already-cached mod immediately (no network round trip) and
        sends one p2p_modreq per genuine miss."""
        try:
            self._started_at = time.monotonic()
            self._last_progress = self._started_at
            threading.Thread(target=self._timeout_watchdog,
                             name="cubeon-p2p-mod-sync-timeout", daemon=True).start()
            local = local_mod_hashes(self.mc_version, self.loader)
            host_hashes = {(entry.get("sha256") or "").lower() for entry in host_mod_list}
            # Disable enabled local mods that the host is not running. Leaving
            # extra client-only jars active can make a loader reject the
            # connection or crash after join. We rename them to .disabled for
            # the session and restore the exact original names on teardown.
            for entry in local:
                sha = (entry.get("sha256") or "").lower()
                if not sha or sha in host_hashes:
                    continue
                original = os.path.join(self.profile_dir, entry["filename"])
                if not os.path.isfile(original) or entry["filename"].endswith(".disabled"):
                    continue
                disabled = original + ".disabled"
                if os.path.exists(disabled):
                    continue
                os.rename(original, disabled)
                self.disabled_paths.append({"original": original, "disabled": disabled})

            missing = diff_missing_mods(local, host_mod_list)
            if not missing:
                self._done.set()
                return

            still_missing = []
            for entry in missing:
                linked = resolve_missing_mod_from_cache(
                    entry["sha256"], self.profile_dir, entry["filename"])
                if linked:
                    self.linked_paths.append(linked)
                    self.newly_linked_from_cache.append(linked)
                else:
                    still_missing.append(entry)

            if not still_missing:
                self._done.set()
                return

            for entry in still_missing:
                sha = entry["sha256"].lower()
                self.pending[sha] = {"filename": entry["filename"], "chunks": [], "total": None}
                self.awaiting_peer.add(sha)
                self._send_signal({"kind": "p2p_modreq", "sha256": sha})
        except Exception as e:
            self.error = f"Couldn't start mod sync: {e}"
            self._done.set()

    def _timeout_watchdog(self) -> None:
        """Fail a mod sync that has stopped receiving data.

        WebSocket delivery is asynchronous, so an unanswered p2p_modreq used
        to leave the Join button stuck in "syncing" forever. A bounded timeout
        turns that into an actionable session error while preserving partial
        cache work for the next attempt.
        """
        while not self._done.wait(1.0):
            if self._started_at is None:
                continue
            now = time.monotonic()
            if now - self._last_progress >= MOD_SYNC_TIMEOUT_S:
                self.error = (
                    "Mod synchronization timed out while waiting for your friend. "
                    "Check both launchers are online and try again."
                )
                self._done.set()
                return

    def on_modchunk(self, data: dict) -> None:
        """Feed each incoming p2p_modchunk signal here. Reassembles and
        links a mod into the profile once every chunk for it has arrived;
        marks the whole session done once nothing's left outstanding."""
        sha = (data.get("sha256") or "").lower()
        entry = self.pending.get(sha)
        if not entry:
            return  # a chunk for a mod we didn't ask for, or already finished - ignore
        self._last_progress = time.monotonic()
        seq = data.get("seq")
        total = data.get("total")
        chunk = data.get("data_b64", "")
        if seq is None or total is None:
            return
        entry["total"] = total
        # Chunks can arrive out of order over a lossy UDP-backed session;
        # pad the list so seq always lands at the right index regardless of
        # arrival order.
        while len(entry["chunks"]) < total:
            entry["chunks"].append(None)
        if 0 <= seq < total:
            entry["chunks"][seq] = chunk

        if all(c is not None for c in entry["chunks"]):
            try:
                dest = fetch_missing_mod_via_peer(
                    sha, entry["chunks"], self.profile_dir, entry["filename"])
                # Stored once under its real (human) name in the global mods
                # store and linked into the profile, so list_mods()/
                # sync_mods_to_game() (which key off filename, not hash) see
                # it correctly and future joins reuse it with no re-fetch.
                self.linked_paths.append(dest)
            except Exception as e:
                self.error = f"Couldn't fetch {entry['filename']} from your friend: {e}"
                self._done.set()
                return
            self.pending.pop(sha, None)
            self.awaiting_peer.discard(sha)
            if not self.awaiting_peer:
                self._done.set()

def diff_missing_mods(local_hashes: "list[dict]", host_hashes: "list[dict]") -> "list[dict]":
    """local_hashes/host_hashes: [{"sha256": ..., "filename": ...}, ...].
    Returns the subset of host_hashes not present locally."""
    local_set = {h["sha256"].lower() for h in local_hashes if h.get("sha256")}
    return [h for h in host_hashes if h.get("sha256", "").lower() not in local_set]


def fetch_missing_mod_via_peer(sha256_hex: str, chunks: "list[str]", dest_dir: str,
                               filename: "str | None" = None) -> str:
    """Reassembles base64 chunks sent by the host over p2p_modchunk signals
    into the jar, checks the reassembled bytes actually hash to the
    sha256 we requested (a peer could be on a different build of the
    "same" mod, or the transfer could have dropped/reordered a chunk), and
    only then stores it through the normal global mods store path
    (get_or_fetch's fetch_fn just writes the bytes we already have instead
    of downloading) so it's stored under the real sha256 under its human
    filename for every future install, P2P or not. Returns the path it was
    linked to in dest_dir. Raises P2PError on a hash mismatch rather than
    silently storing (and then loading) a jar that isn't what was asked
    for."""
    raw = base64.b64decode("".join(chunks))
    actual = hashlib.sha256(raw).hexdigest()
    if actual.lower() != sha256_hex.lower():
        raise P2PError(
            f"Received mod data didn't match the expected file (hash "
            f"mismatch) - not installing it."
        )

    filename = os.path.basename((filename or f"{sha256_hex}.jar").replace("\\", "/"))
    dest_path = os.path.join(dest_dir, filename)

    def _fetch_fn(tmp_path: str) -> None:
        with open(tmp_path, "wb") as f:
            f.write(raw)

    global_mod_cache.get_or_fetch(dest_path, _fetch_fn,
                                  hashes={"sha256": sha256_hex}, human_name=filename)
    return dest_path


def read_chunks_for_mod(jar_path: str) -> "list[str]":
    """Host side: split a cached jar into base64 chunks small enough for
    individual signal() frames."""
    with open(jar_path, "rb") as f:
        raw = f.read()
    b64 = base64.b64encode(raw).decode("ascii")
    return [b64[i:i + MOD_CHUNK_BYTES] for i in range(0, len(b64), MOD_CHUNK_BYTES)]


# ---------------------------------------------------------------------------
# 5. Shared-session assets: resourcepacks + allowlisted loader configs.
# ---------------------------------------------------------------------------

ASSET_ROOTS = {
    "resourcepack": ("resourcepacks", ".zip"),
    "config": ("config", ASSET_ALLOWED_CONFIG_EXTS),
}


def _asset_root(kind: str) -> str:
    from .paths import MINECRAFT_DIR
    try:
        rel, _ = ASSET_ROOTS[kind]
    except KeyError:
        raise P2PError(f"Unsupported P2P asset kind: {kind}") from None
    return os.path.join(MINECRAFT_DIR, rel)


def _safe_asset_relpath(rel: str) -> str:
    rel = str(rel or "").replace("\\", "/")
    if not rel or rel.startswith("/") or ".." in rel.split("/"):
        raise P2PError("P2P asset path is unsafe")
    return rel


def _iter_asset_files(kind: str) -> list[tuple[str, str, int]]:
    root = _asset_root(kind)
    _, exts = ASSET_ROOTS[kind]
    os.makedirs(root, exist_ok=True)
    out, total = [], 0
    for base, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in (".git", "__pycache__")]
        for name in files:
            full = os.path.join(base, name)
            if not os.path.isfile(full) or os.path.islink(full):
                continue
            allowed = name.lower().endswith(exts) if isinstance(exts, str) else name.lower().endswith(tuple(exts))
            if not allowed:
                continue
            size = os.path.getsize(full)
            if size > ASSET_MAX_FILE_BYTES:
                continue
            total += size
            if total > ASSET_MAX_TOTAL_BYTES:
                raise P2PError("P2P asset set is too large (128 MB limit)")
            rel = os.path.relpath(full, root).replace(os.sep, "/")
            out.append((rel, full, size))
    return out


def build_asset_manifest() -> list[dict]:
    manifest = []
    for kind in ASSET_ROOTS:
        for rel, full, size in _iter_asset_files(kind):
            manifest.append({"kind": kind, "path": rel, "size": size, "sha256": hash_file(full)})
    manifest.sort(key=lambda x: (x["kind"], x["path"]))
    if len(manifest) > ASSET_MAX_FILES:
        raise P2PError("P2P asset set contains too many files (1000 limit)")
    if len(json.dumps(manifest, separators=(",", ":"), ensure_ascii=False).encode("utf-8")) > ASSET_MAX_MANIFEST_BYTES:
        raise P2PError("P2P asset manifest is too large")
    return manifest


def _asset_target(kind: str, rel: str) -> str:
    rel = _safe_asset_relpath(rel)
    root = os.path.abspath(_asset_root(kind))
    target = os.path.abspath(os.path.join(root, *rel.split("/")))
    if os.path.commonpath([root, target]) != root:
        raise P2PError("P2P asset path escaped its root")
    return target


def read_chunks_for_asset(path: str) -> list[str]:
    with open(path, "rb") as f:
        raw = f.read(ASSET_MAX_FILE_BYTES + 1)
    if len(raw) > ASSET_MAX_FILE_BYTES:
        raise P2PError("P2P asset exceeds the per-file size limit")
    b64 = base64.b64encode(raw).decode("ascii")
    return [b64[i:i + ASSET_CHUNK_BYTES] for i in range(0, len(b64), ASSET_CHUNK_BYTES)] or [""]


class AssetSyncSession:
    def __init__(self, *, send_signal):
        self._send_signal = send_signal
        self.pending, self.added_paths, self.backups = {}, [], []
        self.error = None
        self._done = threading.Event()
        self._last_progress = time.monotonic()

    def is_complete(self) -> bool:
        return self._done.is_set()

    def start(self, host_manifest: list[dict]) -> None:
        try:
            threading.Thread(target=self._watchdog, name="cubeon-p2p-asset-timeout", daemon=True).start()
            local = {(e["kind"], e["path"]): e for e in build_asset_manifest()}
            for entry in host_manifest:
                kind, rel = entry.get("kind"), _safe_asset_relpath(entry.get("path"))
                sha, size = str(entry.get("sha256") or "").lower(), int(entry.get("size") or 0)
                if kind not in ASSET_ROOTS or len(sha) != 64 or size < 0 or size > ASSET_MAX_FILE_BYTES:
                    raise P2PError("Host sent an invalid P2P asset manifest")
                local_entry = local.get((kind, rel))
                if local_entry and local_entry.get("sha256", "").lower() == sha:
                    continue
                target = _asset_target(kind, rel)
                if os.path.isfile(target):
                    backup = target + ".cubeon-p2p-backup"
                    if os.path.exists(backup):
                        os.remove(backup)
                    os.replace(target, backup)
                    self.backups.append({"original": target, "backup": backup})
                os.makedirs(os.path.dirname(target), exist_ok=True)
                self.pending[(kind, rel)] = {"sha256": sha, "size": size, "chunks": [], "total": None}
                self._send_signal({"kind": "p2p_assetreq", "asset_kind": kind, "path": rel, "sha256": sha})
            if not self.pending:
                self._done.set()
        except Exception as e:
            self.error = f"Couldn't start resource/config sync: {e}"
            self._done.set()

    def _watchdog(self):
        while not self._done.wait(1.0):
            if time.monotonic() - self._last_progress >= ASSET_SYNC_TIMEOUT_S:
                self.error = "Resource/config synchronization timed out while waiting for your friend."
                self._done.set()
                return

    def on_chunk(self, data: dict):
        try:
            kind, rel = data.get("asset_kind"), _safe_asset_relpath(data.get("path"))
            item = self.pending.get((kind, rel))
            if not item:
                return
            seq, total = int(data.get("seq")), int(data.get("total"))
            chunk = data.get("data_b64", "")
            if total <= 0 or total > 100000 or seq < 0 or seq >= total or not isinstance(chunk, str):
                raise P2PError("Invalid P2P asset chunk")
            self._last_progress = time.monotonic()
            while len(item["chunks"]) < total:
                item["chunks"].append(None)
            item["total"], item["chunks"][seq] = total, chunk
            if not all(x is not None for x in item["chunks"]):
                return
            raw = base64.b64decode("".join(item["chunks"]), validate=True)
            if len(raw) != item["size"] or hashlib.sha256(raw).hexdigest().lower() != item["sha256"]:
                raise P2PError(f"Received {rel} failed its SHA-256 verification")
            target = _asset_target(kind, rel)
            tmp = target + ".cubeon-p2p.tmp"
            with open(tmp, "wb") as f:
                f.write(raw)
            os.replace(tmp, target)
            self.added_paths.append(target)
            self.pending.pop((kind, rel), None)
            if not self.pending:
                self._done.set()
        except Exception as e:
            self.error = str(e)
            self._done.set()


# ---------------------------------------------------------------------------
# 6. Session bookkeeping - what teardown() needs to know to clean up only
#    this session's links and nothing shared.
# ---------------------------------------------------------------------------

def _session_state_path(room: str) -> str:
    os.makedirs(SESSIONS_DIR, exist_ok=True)
    return os.path.join(SESSIONS_DIR, f"{room}.json")


def record_session_links(room: str, mc_version: str, loader: str, linked_paths: "list[str]",
                          disabled_paths: "list[dict] | None" = None,
                          asset_paths: "list[str] | None" = None,
                          asset_backups: "list[dict] | None" = None) -> None:
    """Record session-only mod changes. Peer-linked files are removed on
    leave; extra local mods temporarily renamed to .disabled are restored.
    The global cache and the user's pre-existing files are never deleted."""
    state = {"mc_version": mc_version, "loader": loader,
             "linked_paths": linked_paths, "disabled_paths": disabled_paths or [],
             "asset_paths": asset_paths or [], "asset_backups": asset_backups or []}
    with open(_session_state_path(room), "w", encoding="utf-8") as f:
        json.dump(state, f)


def teardown(room: str) -> None:
    """Joiner leaving: remove this session's mod symlinks from the active
    profile only. The global mods store (one physical human-named copy per
    jar) is untouched - those bytes are shared and content-addressed, so
    the next join (this friend or any other) that needs the same mod links
    straight from the store with no re-fetch."""
    path = _session_state_path(room)
    try:
        with open(path, "r", encoding="utf-8") as f:
            state = json.load(f)
    except (OSError, ValueError):
        return  # nothing recorded for this room - already torn down, or never joined

    for linked_path in state.get("linked_paths", []):
        try:
            if os.path.islink(linked_path) or os.path.exists(linked_path):
                os.remove(linked_path)
        except OSError:
            pass

    for asset_path in state.get("asset_paths", []):
        try:
            if os.path.isfile(asset_path) or os.path.islink(asset_path):
                os.remove(asset_path)
        except OSError:
            pass

    for item in state.get("asset_backups", []):
        original, backup = item.get("original"), item.get("backup")
        if not original or not backup:
            continue
        try:
            if os.path.exists(backup) and not os.path.exists(original):
                os.makedirs(os.path.dirname(original), exist_ok=True)
                os.replace(backup, original)
        except OSError:
            pass

    for item in state.get("disabled_paths", []):
        original = item.get("original")
        disabled = item.get("disabled")
        if not original or not disabled:
            continue
        try:
            # Restore only if the original path is free. This avoids replacing
            # a file created by the user while the P2P session was active.
            if os.path.exists(disabled) and not os.path.exists(original):
                os.rename(disabled, original)
        except OSError:
            pass

    try:
        os.remove(path)
    except OSError:
        pass
