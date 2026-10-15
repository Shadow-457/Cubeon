"""How much longer? - a measured "time left" for the launcher's downloads.

Every download surface in the launcher is driven by the same two callbacks:
status_cb(text) names the file or phase, and progress_cb(value) reports the
current phase's count. The units differ per caller - minecraft_launcher_lib
counts FILES per phase, the mod installer counts files in the whole batch,
content downloads count bytes - and none of them carry a clock, so there is no
way to know how big what's left actually is. The only honest estimate is
measured: sample the fraction over time and extrapolate what remains at the
rate we have actually been going.

Three behaviours matter more than the arithmetic:

  * it stays SILENT until there is real movement (a couple of seconds and a
    percent or two). An ETA that appears instantly and then swings wildly is
    worse than no ETA at all - people trust the number and then feel cheated.
  * a BACKWARDS jump means a new phase started (libraries -> assets, or the
    next file of a batch), so the history is dropped rather than mixing two
    phases' rates into nonsense.
  * a STALLED download stops promising a time instead of counting down
    forever.

The clock is injectable, so tests need no sleeping.
"""
from __future__ import annotations

import time
from collections import deque

__all__ = ["EtaEstimator", "format_duration"]


def format_duration(seconds: float) -> str:
    """A short, human duration: '45s', '2m 10s', '1h 05m'."""
    total = int(seconds + 0.5)
    if total < 5:
        return "a few seconds"
    if total < 60:
        return f"{total}s"
    minutes, secs = divmod(total, 60)
    if minutes < 60:
        return f"{minutes}m {secs:02d}s" if secs else f"{minutes}m"
    hours, minutes = divmod(minutes, 60)
    return f"{hours}h {minutes:02d}m"


class EtaEstimator:
    """Feed it progress samples, ask it for "~2m 10s left"."""

    #: Seconds of real movement before a number is worth showing.
    MIN_SPAN = 2.0
    #: Fraction that must have moved before a number is worth showing.
    MIN_MOVED = 0.01
    #: Only this much of the tail feeds the rate, so the ETA reacts to the last
    #: half-minute rather than to the average since the download began.
    HISTORY = 30.0
    #: No sample for this long means the download stalled - stop promising.
    STALE = 15.0
    #: Beyond this the extrapolation is noise, not information.
    MAX_ETA = 6 * 3600.0

    def __init__(self, now=time.monotonic):
        self._now = now
        self._samples: "deque[tuple[float, float]]" = deque()
        self._last = 0.0

    def reset(self) -> None:
        """Forget everything - a new download (or phase) started."""
        self._samples.clear()
        self._last = 0.0

    def note(self, value, total) -> "str | None":
        """Record one progress sample; return the estimate, or None."""
        try:
            value = float(value or 0)
            total = float(total or 0)
        except (TypeError, ValueError):
            return None
        if total <= 0:
            return None
        frac = value / total
        frac = 0.0 if frac < 0.0 else (1.0 if frac > 1.0 else frac)
        now = self._now()
        if self._samples and frac + 0.005 < self._samples[-1][1]:
            # Backwards by any real amount: a different phase (libraries ->
            # assets, or the next file of a batch). Progress within a phase is
            # monotonic, so a drop is never just jitter - and mixing two
            # phases' rates produces nonsense.
            self._samples.clear()
        self._samples.append((now, frac))
        while len(self._samples) > 2 and now - self._samples[0][0] > self.HISTORY:
            self._samples.popleft()
        self._last = now
        return self.text(now)

    def text(self, now: "float | None" = None) -> "str | None":
        """The current estimate, without recording a sample."""
        if not self._samples:
            return None
        now = self._now() if now is None else now
        started, first = self._samples[0]
        last_t, last = self._samples[-1]
        if now - last_t > self.STALE:
            return None                       # stalled: say nothing
        span = last_t - started
        moved = last - first
        if span < self.MIN_SPAN or moved < self.MIN_MOVED or last >= 1.0:
            return None                       # no signal yet, or finished
        seconds = (1.0 - last) / (moved / span)
        if seconds > self.MAX_ETA:
            return None
        return "~" + format_duration(seconds) + " left"
