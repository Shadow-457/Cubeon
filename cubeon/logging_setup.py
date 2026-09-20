"""
Central logging: one rotating file, plus last-resort hooks so NO failure is
ever completely silent.

Before this module, logging was imported in several cubeon/ modules but never
CONFIGURED anywhere - meaning every log.info/warning went to a default handler
nobody saw (or nowhere, in a windowed PyInstaller build), and an uncaught
exception in a background thread died with a console traceback the user never
sees. Now:

  - everything logs to ~/.cubeon_launcher/cubeon.log (5 MB x 3 rotating);
  - uncaught exceptions on the main thread AND worker threads are written
    there with full traceback before the process limps on or dies;
  - console still gets WARNING+ so running from a terminal stays informative.

setup_logging() is idempotent and safe to call from tests (CUBEON_GAME_DIR
doesn't move this file - the log belongs to the launcher, not the game dir).
"""
import logging
import logging.handlers
import os
import sys
import threading
import traceback

LOG_PATH = os.path.join(os.path.expanduser("~"), ".cubeon_launcher", "cubeon.log")
MAX_BYTES = 5 * 1024 * 1024
BACKUPS = 3
_configured = False


def _install_excepthooks() -> None:
    def _hook(kind, value, tb):
        logging.getLogger("cubeon.fatal").critical(
            "Uncaught exception", exc_info=(kind, value, tb))

    sys.excepthook = _hook

    def _thread_hook(args):
        logging.getLogger("cubeon.fatal").critical(
            "Uncaught exception in thread %s", args.thread.name if args.thread else "?",
            exc_info=(args.exc_type, args.exc_value, args.exc_traceback))

    if hasattr(threading, "excepthook"):
        threading.excepthook = _thread_hook


def setup_logging(verbose: bool = False) -> str:
    """Configure the root logger. Returns the log file path. Never raises:
    a read-only HOME must degrade to console-only logging, not kill startup."""
    global _configured
    if _configured:
        return LOG_PATH
    root = logging.getLogger()
    root.setLevel(logging.DEBUG if verbose else logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s %(levelname)-7s %(name)s: %(message)s", "%Y-%m-%d %H:%M:%S")
    console = logging.StreamHandler()
    console.setLevel(logging.DEBUG if verbose else logging.WARNING)
    console.setFormatter(fmt)
    root.addHandler(console)
    try:
        os.makedirs(os.path.dirname(LOG_PATH), exist_ok=True)
        fileh = logging.handlers.RotatingFileHandler(
            LOG_PATH, maxBytes=MAX_BYTES, backupCount=BACKUPS, encoding="utf-8")
        fileh.setFormatter(fmt)
        root.addHandler(fileh)
    except OSError as ex:
        root.warning("file logging unavailable (%s); console only", ex)
    logging.captureWarnings(True)
    _install_excepthooks()
    _configured = True
    return LOG_PATH


def diagnostics_text() -> str:
    """The tail of the log plus system basics - what a user pastes into a
    bug report. Kept deliberately small (last ~120 lines), and it must not
    throw: this runs when things are already broken."""
    import platform
    lines = [f"Cubeon diagnostics - {platform.platform()}",
             f"Python {sys.version.split()[0]}"]
    try:
        with open(LOG_PATH, "r", encoding="utf-8", errors="replace") as fh:
            lines += fh.readlines()[-120:]
    except OSError:
        lines.append("(no log file)")
    return "\n".join(lines)


def format_traceback(exc: BaseException) -> str:
    """Full traceback as a string - for the launcher's own error surfaces."""
    return "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
