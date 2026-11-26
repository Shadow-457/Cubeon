"""Opt-in startup timing, so a slow cold start can be attributed instead of
guessed at.

Set ``CUBEON_STARTUP_PROFILE=1`` and every ``mark()`` is written to
``cubeon.log`` (and stderr, once logging is configured) with the milliseconds
elapsed since this module was first imported - which is early in main.py's own
import, so the first mark also covers most of the import cost::

    CUBEON_STARTUP_PROFILE=1 cubeon
    grep startup-profile ~/.cubeon_launcher/cubeon.log

Marks return immediately when disabled. Play and Play setup report timings
relative to the start of their respective phases."""
import logging
import os
import time

# First-import stamp. Everything is reported relative to this, so the numbers
# include the module-import cost that precedes the first explicit mark.
_T0 = time.perf_counter()

_ENABLED = os.environ.get("CUBEON_STARTUP_PROFILE", "").strip().lower() \
    not in ("", "0", "false", "no", "off")

_log = logging.getLogger("cubeon.startup")


def enabled() -> bool:
    """True when CUBEON_STARTUP_PROFILE asks for marks."""
    return _ENABLED


def elapsed_ms() -> float:
    """Milliseconds since this module was first imported."""
    return (time.perf_counter() - _T0) * 1000.0


def mark(name: str, *, since: float = _T0) -> None:
    """Record a milestone relative to startup or the supplied perf_counter."""
    if not _ENABLED:
        return
    _log.info("startup-profile %8.1f ms  %s", (time.perf_counter() - since) * 1000, name)
