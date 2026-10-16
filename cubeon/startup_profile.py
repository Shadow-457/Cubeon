"""Opt-in startup timing, so a slow cold start can be attributed instead of
guessed at.

Set ``CUBEON_STARTUP_PROFILE=1`` and every ``mark()`` is written to
``cubeon.log`` (and stderr, once logging is configured) with the milliseconds
elapsed since this module was first imported - which is early in main.py's own
import, so the first mark also covers most of the import cost::

    CUBEON_STARTUP_PROFILE=1 cubeon
    grep startup-profile ~/.cubeon_launcher/cubeon.log

Cost when disabled is one ``perf_counter()`` per mark and a skipped ``if`` - the
logging call is never reached. This is intentionally tiny: it exists to prove
where startup time goes (measured: the synchronous UI build, and the Mojang
feed fetch that used to run inside it) not to be a framework."""
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


def mark(name: str) -> None:
    """Record a startup milestone. No-op unless profiling is enabled."""
    if not _ENABLED:
        return
    _log.info("startup-profile %8.1f ms  %s", elapsed_ms(), name)
