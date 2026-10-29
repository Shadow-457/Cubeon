"""Carry a redacted crash excerpt to the website, without a log-storage service.

The compressed report travels in a URL fragment (never sent to the web host).
The Doctor consumes and removes it before starting AI analysis. Browser transfer is
bounded; the original file stays on disk for a larger manual upload.
"""
from __future__ import annotations

import base64
import json
import os
import re
from urllib.parse import urlsplit, urlunsplit
import webbrowser
import zlib

SITE_URL = "https://www.ylet.online"
MAX_URL_CHARS = 7_500  # also fits browser wrappers using Windows' 8191-char cmd limit
MAX_REPORT_CHARS = 64_000


def redact_log(text: str) -> str:
    """Remove common credentials and personal locations, preserving errors."""
    text = str(text or "")
    text = re.sub(r"(?i)(authorization\s*[:=]\s*)(?:bearer\s+)?[^\s,;]+",
                  r"\1[redacted]", text)
    text = re.sub(
        r'''(?ix)((?:--)?(?:access[_-]?token|refresh[_-]?token|auth[_-]?token|
             api[_-]?key|client[_-]?secret|password|passwd|secret|--username)
             ["']?\s*(?:[:=]\s*|\s+))["']?[^\s,"';}]+["']?''',
        r"\1[redacted]", text)
    text = re.sub(r"(?i)\b(?:C:|[A-Z]:)[\\/]Users[\\/][^\\/\s\"']+",
                  r"C:\\Users\\[user]", text)
    text = re.sub(r"/(?:home|Users)/[^/\s\"']+", "/home/[user]", text)
    # Bounded email parts avoid quadratic scans over long exception lines.
    text = re.sub(r"[\w.+-]{1,64}@[\w.-]{1,253}\.[A-Za-z]{2,63}", "[email]", text)
    text = re.sub(r"(?i)(--server\s+)[^\s]+", r"\1[server]", text)
    return text


def doctor_url(log_text: str, *, reason: str = "", version_label: str = "",
               base_url: str | None = None) -> str:
    base = (base_url or os.environ.get("CUBEON_WEB_URL") or SITE_URL).strip()
    parts = urlsplit(base)
    local = parts.hostname in ("localhost", "127.0.0.1", "::1")
    if (parts.scheme != "https" and not (parts.scheme == "http" and local)) or not parts.netloc or parts.username:
        raise ValueError("Doctor needs an HTTPS website URL")
    url = urlunsplit((parts.scheme, parts.netloc, parts.path.rstrip('/') + '/doctor', '', ''))
    source = redact_log(log_text)
    excerpt = source[-MAX_REPORT_CHARS:]
    if len(source) > len(excerpt) and '\n' in excerpt:
        excerpt = excerpt.split('\n', 1)[1]
    # Include the error summary independently so truncating noisy output does
    # not lose the launcher's already-detected cause.
    while True:
        report = {
            'v': 1, 'log': excerpt, 'reason': redact_log(reason)[:1000],
            'version': redact_log(version_label)[:240],
            'original_chars': len(source), 'truncated': len(excerpt) < len(source),
        }
        packed = zlib.compress(json.dumps(report, ensure_ascii=False, separators=(',', ':')).encode('utf-8'), 9)
        fragment = base64.urlsafe_b64encode(packed).decode('ascii').rstrip('=')
        result = url + '#report=' + fragment
        if len(result) <= MAX_URL_CHARS:
            return result
        if len(excerpt) <= 100:
            raise ValueError("Doctor website URL is too long")
        excerpt = excerpt[-max(100, int(len(excerpt) * 0.7)):]


def open_doctor(log_text: str, *, reason: str = "", version_label: str = "") -> bool:
    """User-click handoff only: no network upload, no subprocess credentials."""
    try:
        return bool(webbrowser.open(doctor_url(log_text, reason=reason, version_label=version_label)))
    except Exception:
        return False
