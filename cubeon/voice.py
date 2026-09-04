"""
Voice - the audio half of a call. Optional, and deliberately isolated.

The call *system* (ringing, accept/decline, hang-up, "in call with X") lives in
friends_service.py + the Durable Object and works with no extra dependencies. This
module is only the microphone→speaker audio, which needs a native audio library
the base launcher doesn't bundle - keeping it optional means the download stays
small and an install without it still rings, connects, and chats, just without
sound (the UI says so rather than pretending).

WHY SERVER-RELAYED PCM AND NOT WEBRTC

Peer-to-peer WebRTC would be lighter on the server but needs a TURN server to
punch through most home/mobile NATs, and TURN is the one piece that isn't free.
Cubeon has no budget for that (see the infra notes), so audio rides the same
Durable Object that already relays call signalling: each side sends small PCM
frames as `signal` messages and plays back what it receives. Higher latency than
P2P and heavier on the DO, but it works behind any NAT with zero extra infra -
the right trade for "a few friends on a call", which is the whole use case.

Frames are 16 kHz mono int16 in ~40 ms chunks, base64 in the signal payload.
That's ~32 KB/s raw per direction - fine for a small call, and the DO only stays
"awake" (and thus billable) while a call is actually up.

EVERYTHING HERE IS BEST-EFFORT

Audio devices are the most machine-specific thing a desktop app touches. Every
entry point is wrapped so that a missing library, a busy microphone, or an odd
default device downgrades the call to signalling-only instead of throwing on a
background thread. `is_available()` gates the whole module; if it's False the UI
never calls the rest.
"""
import base64
import logging
import threading

log = logging.getLogger(__name__)

# Audio format - kept low so relayed frames stay small. Opus would compress far
# better but adds another native dependency; raw PCM at 16 kHz is intelligible
# for voice and needs only sounddevice + numpy.
SAMPLE_RATE = 16000
CHANNELS = 1
BLOCK_MS = 40
BLOCK_FRAMES = SAMPLE_RATE * BLOCK_MS // 1000

try:
    import numpy as np
    import sounddevice as sd
    _HAVE_AUDIO = True
except Exception:  # pragma: no cover - depends on the host having the add-on
    np = None
    sd = None
    _HAVE_AUDIO = False


def is_available() -> bool:
    """True only if the audio add-on is importable. The Friends tab checks this
    before offering real audio, and falls back to a signalling-only call with a
    one-line explanation when it's False."""
    return _HAVE_AUDIO


# A single active session at a time - Cubeon supports one call at once, so a
# module global is simpler than threading a handle through the UI and keeps
# on_signal() (which is dispatched from the socket thread) able to find it.
_session = None
_lock = threading.Lock()


class _Session:
    """One live call's audio: capture the mic, relay it, play what comes back."""

    def __init__(self, room, peer, client, on_status):
        self.room = room
        self.peer = peer            # canonical/display name to relay frames to
        self.client = client
        self.on_status = on_status or (lambda s: None)
        self._in = None
        self._out = None
        self._play_lock = threading.Lock()
        self._playing = bytearray()
        self._alive = False

    def start(self):
        # Output stream drains a rolling buffer that on_signal() fills; input
        # stream ships each captured block to the peer. Both are opened inside
        # the try so a device error can't leave one half running.
        self._out = sd.RawOutputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16",
            blocksize=BLOCK_FRAMES, callback=self._on_playback,
        )
        self._in = sd.RawInputStream(
            samplerate=SAMPLE_RATE, channels=CHANNELS, dtype="int16",
            blocksize=BLOCK_FRAMES, callback=self._on_capture,
        )
        self._out.start()
        self._in.start()
        self._alive = True
        self.on_status("audio")

    def _on_capture(self, indata, frames, time_info, status):
        if not self._alive:
            return
        try:
            payload = base64.b64encode(bytes(indata)).decode("ascii")
            self.client.signal(self.room, self.peer, {"audio": payload})
        except Exception:
            # A single dropped frame is inaudible; never raise out of the
            # PortAudio callback (that kills the stream).
            pass

    def _on_playback(self, outdata, frames, time_info, status):
        need = len(outdata)
        with self._play_lock:
            have = self._playing[:need]
            del self._playing[:need]
        if len(have) < need:
            have = bytes(have) + b"\x00" * (need - len(have))  # underrun -> silence
        outdata[:] = have

    def feed(self, b64_audio):
        if not self._alive:
            return
        try:
            pcm = base64.b64decode(b64_audio)
        except Exception:
            return
        with self._play_lock:
            self._playing.extend(pcm)
            # Bound the buffer so a burst can't build unbounded latency.
            max_buffered = SAMPLE_RATE * 2 * 1  # ~1s of int16 mono
            if len(self._playing) > max_buffered:
                del self._playing[:len(self._playing) - max_buffered]

    def stop(self):
        self._alive = False
        for stream in (self._in, self._out):
            try:
                if stream is not None:
                    stream.stop()
                    stream.close()
            except Exception:
                pass
        self._in = self._out = None


def start(room, peer, client, on_status=None) -> bool:
    """Begin capturing/playing audio for a call. Returns True if audio actually
    started; False (never raises) if the add-on is missing or a device failed,
    in which case the call simply stays signalling-only."""
    global _session
    if not _HAVE_AUDIO:
        return False
    with _lock:
        if _session is not None:
            return True  # already in a call
        try:
            _session = _Session(room, peer, client, on_status)
            _session.start()
            return True
        except Exception as ex:
            log.warning("voice: audio unavailable (%s)", ex.__class__.__name__)
            _session = None
            return False


def stop() -> None:
    """End the current call's audio, if any. Safe to call when nothing's running."""
    global _session
    with _lock:
        if _session is not None:
            _session.stop()
            _session = None


def on_signal(payload: dict) -> None:
    """Handle a relayed `signal` frame. Only audio payloads matter here; anything
    else (future WebRTC negotiation, etc.) is ignored so it can share the channel."""
    sess = _session
    if sess is None or not isinstance(payload, dict):
        return
    data = payload.get("data")
    if isinstance(data, dict) and "audio" in data:
        sess.feed(data["audio"])
