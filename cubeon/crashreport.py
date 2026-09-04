"""
Opt-in crash reporting: when the user says yes, an uncaught exception's
diagnostics are POSTed once to a Cubeon endpoint so field failures aren't
invisible. Defaults are strict:

  - OFF unless cfg["crash_reports"] is True (never on by default);
  - NOWHERE to send unless an endpoint is configured (env
    CUBEON_CRASH_ENDPOINT or cfg["crash_endpoint"]);
  - the POST runs on a daemon thread with a 5s timeout and can never raise,
    crash, or block shutdown - a failed report is a log line, not a problem;
  - the payload is diagnostics_text() only (app log tail + platform string).
    No usernames, no file contents, no friends data.
"""
import json
import logging
import os
import threading

import requests

log = logging.getLogger(__name__)


def endpoint(cfg: dict | None = None) -> str | None:
    """Where reports go, or None when disabled - either by the opt-out or
    by having no destination configured."""
    if cfg is not None and not cfg.get("crash_reports", False):
        return None
    ep = os.environ.get("CUBEON_CRASH_ENDPOINT")
    if ep:
        return ep
    if cfg is not None:
        return cfg.get("crash_endpoint") or None
    return None


def report(cfg: dict | None, text: str) -> None:
    """Fire-and-forget a crash report. Safe to call from the excepthook."""
    ep = endpoint(cfg)
    if not ep:
        return
    payload = json.dumps({"app": "cubeon", "diagnostics": text[-8000:]}).encode()

    def _send():
        try:
            requests.post(ep, data=payload,
                          headers={"Content-Type": "application/json"},
                          timeout=5)
        except Exception as ex:  # noqa: BLE001 - reporting must never crash
            log.info("crash report not delivered: %s", ex.__class__.__name__)

    threading.Thread(target=_send, name="cubeon-crash-report",
                     daemon=True).start()
