#!/usr/bin/env python3
"""
Owner notifications (Phase 6) - launcher module, publisher CLI, Worker route.

    python3 tools/test_notify.py

Three layers, none of which touch the network or a real Cloudflare account:

  1. the launcher side (`cubeon/notify.py`): parsing an untrusted response,
     the seen-marker rule, the dialog, and the off-thread poll;
  2. the publisher CLI (`notify/`): payload/validation, token discovery, and
     the HTTP status mapping (401/501/200) against a fake transport;
  3. the Worker route, in `worker/test-notify.mjs` via node (skipped, not
     failed, when node is absent) - plus static checks that keep the pieces
     wired together.
"""
import io
import json
import os
import shutil
import subprocess
import sys
import urllib.error

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _ROOT)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

passed = 0
failed = 0


def check(label, cond, detail=""):
    global passed, failed
    if cond:
        passed += 1
        print(f"  ok   {label}")
    else:
        failed += 1
        print(f"  FAIL {label}" + (f"\n       {detail}" if detail else ""))


# Sandbox HOME before any cubeon import (config/paths resolve against it).
import _sandbox_home  # noqa: E402

_sandbox_home.isolate()

from cubeon import notify  # noqa: E402

print("\n1. an untrusted response is parsed defensively")

check("a well-formed entry comes through",
      notify.normalise({"headline": " Hi ", "content": " Body ", "ts": 5}) ==
      {"headline": "Hi", "content": "Body", "ts": 5.0, "url": None})
check("a non-dict is rejected", notify.normalise(["nope"]) is None)
check("a missing headline is rejected", notify.normalise({"content": "x", "ts": 1}) is None)
check("a blank headline is rejected", notify.normalise({"headline": "  ", "content": "x", "ts": 1}) is None)
check("a missing content is rejected", notify.normalise({"headline": "x", "ts": 1}) is None)
check("a non-numeric ts is rejected (it is the seen marker)",
      notify.normalise({"headline": "x", "content": "y", "ts": "soon"}) is None)
check("a bool ts is rejected", notify.normalise({"headline": "x", "content": "y", "ts": True}) is None)
check("an http url is kept",
      notify.normalise({"headline": "x", "content": "y", "ts": 1,
                        "url": "https://cubeon.run.place"})["url"] ==
      "https://cubeon.run.place")
check("a javascript: url is dropped",
      notify.normalise({"headline": "x", "content": "y", "ts": 1,
                        "url": "javascript:alert(1)"})["url"] is None)

print("\n2. the seen marker is the entry's ts")

check("a newer entry shows", notify.should_show({"ts": 10}, 5) is True)
check("the same entry does not show again", notify.should_show({"ts": 10}, 10) is False)
check("an older entry does not show", notify.should_show({"ts": 10}, 11) is False)
check("a first-ever entry shows (no marker yet)", notify.should_show({"ts": 1}, None) is True)
check("no entry never shows", notify.should_show(None, 0) is False)
check("a broken marker degrades to 'do not show'",
      notify.should_show({"ts": "x"}, 0) is False)

print("\n3. the dialog is the seasonal-greeting style (non-modal, dismissable)")

_dlg = notify.build_dialog({"headline": "Hello", "content": "World", "ts": 1})
_texts = []


def _collect(control):
    if hasattr(control, "value") and isinstance(getattr(control, "value"), str):
        _texts.append(control.value)
    for attr in ("content", "title", "controls", "actions"):
        child = getattr(control, attr, None)
        if isinstance(child, list):
            for c in child:
                _collect(c)
        elif child is not None:
            _collect(child)


_collect(_dlg)
check("the headline is in the dialog", "Hello" in _texts, str(_texts))
check("the content is in the dialog", "World" in _texts, str(_texts))
check("it is not modal (an announcement must never trap anyone)",
      not getattr(_dlg, "modal", False))

print("\n4. fetch_latest never raises and requires a 200 + JSON")


class _Resp:
    def __init__(self, body, status=200):
        self._body = body.encode() if isinstance(body, str) else body
        self.status = status

    def read(self, *a):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _opener(response):
    def _open(req, timeout=None):
        if isinstance(response, Exception):
            raise response
        return response
    return _open


check("a 200 JSON entry is returned",
      notify.fetch_latest("https://x/notify", opener=_opener(
          _Resp(json.dumps({"headline": "a", "content": "b", "ts": 3}))))["headline"] == "a")
check("a 204 (nothing published) is None",
      notify.fetch_latest("https://x/notify", opener=_opener(_Resp("", 204))) is None)
check("an HTML error body is None",
      notify.fetch_latest("https://x/notify",
                          opener=_opener(_Resp("<html>nope</html>"))) is None)
check("a transport error is None, not an exception",
      notify.fetch_latest("https://x/notify",
                          opener=_opener(OSError("offline"))) is None)
check("an unusable entry is None",
      notify.fetch_latest("https://x/notify",
                          opener=_opener(_Resp(json.dumps({"headline": "x"})))) is None)

print("\n5. the poll runs off-thread and shows the entry exactly once")


class _FakePage:
    def __init__(self):
        self.overlay = []
        self.opened = []

    def run_task(self, handler):
        # flet's documented cross-thread hop. Faithfully mirror real Flet: call
        # the coroutine FUNCTION, then actually run it (a bare handler() would
        # only create a coroutine and silently do nothing).
        import asyncio

        result = handler()
        if asyncio.iscoroutine(result):
            asyncio.run(result)

    def open(self, control):
        self.opened.append(control)

    def launch_url(self, url):
        raise AssertionError("must not be called in this test")


class _InlineThread:
    """A thread that runs immediately, so the test needs no timing."""

    def __init__(self, target=None, name=None, daemon=None):
        self._target = target
        self.name = name

    def start(self):
        self._target()


_saved_dialogs = notify._dialogs


class _Dialogs:
    opened = []
    closed = []

    @staticmethod
    def open_dialog(page, dlg):
        _Dialogs.opened.append(dlg)
        page.open(dlg)

    @staticmethod
    def close_dialog(page, dlg):
        _Dialogs.closed.append(dlg)


notify._dialogs = _Dialogs
try:
    page = _FakePage()
    cfg = {}
    saved = []
    body = json.dumps({"headline": "Broadcast", "content": "It works", "ts": 42})
    notify.poll_async(page, cfg, save_config=lambda c: saved.append(dict(c)),
                      url="https://x/notify", thread_factory=_InlineThread,
                      opener=_opener(_Resp(body)))
    check("the dialog was opened", len(_Dialogs.opened) == 1,
          f"opened={len(_Dialogs.opened)}")
    check("the seen marker was recorded", cfg.get(notify.SEEN_KEY) == 42.0, str(cfg))
    check("the seen marker was persisted", saved and saved[-1].get(notify.SEEN_KEY) == 42.0)
    check("the polling thread is a daemon named cubeon-notify",
          _InlineThread(target=lambda: None, name="cubeon-notify").name == "cubeon-notify")

    # A second poll of the SAME entry must show nothing.
    _Dialogs.opened.clear()
    notify.poll_async(page, cfg, save_config=lambda c: None,
                      url="https://x/notify", thread_factory=_InlineThread,
                      opener=_opener(_Resp(body)))
    check("re-polling the same entry shows nothing", not _Dialogs.opened)

    # A newer entry shows again.
    newer = json.dumps({"headline": "Again", "content": "Newer", "ts": 43})
    notify.poll_async(page, cfg, save_config=lambda c: None,
                      url="https://x/notify", thread_factory=_InlineThread,
                      opener=_opener(_Resp(newer)))
    check("a newer entry shows again", len(_Dialogs.opened) == 1)
finally:
    notify._dialogs = _saved_dialogs

print("\n6. the publisher CLI validates before it sends")

import importlib.util  # noqa: E402

_spec = importlib.util.spec_from_file_location(
    "cubeon_notify_cli", os.path.join(_ROOT, "notify", "__main__.py"))
cli = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cli)


class _Args:
    headline = "Hello"
    content = "World"
    url = None


check("the payload carries headline + content",
      cli.build_payload(_Args()) == {"headline": "Hello", "content": "World"})
check("a valid payload passes validation", cli.validate(cli.build_payload(_Args())) is None)
check("an empty headline is rejected",
      cli.validate({"headline": "", "content": "x"}) is not None)
check("a non-http url is rejected",
      cli.validate({"headline": "a", "content": "b", "url": "ftp://x"}) is not None)
check("an https url is accepted",
      cli.validate({"headline": "a", "content": "b", "url": "https://x"}) is None)
check("--dry-run writes nothing and needs no token",
      cli.main(["--dry-run", "--headline", "H", "--content", "C"]) == 0)

_prev_env = os.environ.pop("CUBEON_NOTIFY_TOKEN", None)
try:
    check("no token anywhere -> None (and the CLI refuses)",
          cli.find_token() is None)
    os.environ["CUBEON_NOTIFY_TOKEN"] = "env-token"
    check("$CUBEON_NOTIFY_TOKEN is used", cli.find_token() == "env-token")
    check("--token wins over the environment", cli.find_token("explicit") == "explicit")
    os.environ.pop("CUBEON_NOTIFY_TOKEN", None)
    _token_path = os.path.join(_ROOT, ".notify_token")
    _had = os.path.exists(_token_path)
    try:
        with open(_token_path, "w", encoding="utf-8") as _fh:
            _fh.write("file-token\n")
        check("the .notify_token file is a fallback", cli.find_token() == "file-token")
    finally:
        if _had:
            pass
        else:
            try:
                os.remove(_token_path)
            except OSError:
                pass
finally:
    if _prev_env is not None:
        os.environ["CUBEON_NOTIFY_TOKEN"] = _prev_env

# Status mapping against a fake transport: the CLI must say something useful.
_status, _body = cli.send("https://x/notify", "t", {"headline": "a", "content": "b"},
                          opener=_opener(_Resp('{"ok":true,"ts":7}')))
check("a 200 round-trips the body", _status == 200 and '"ts":7' in _body)


def _http_error(code, text):
    def _open(req, timeout=None):
        raise urllib.error.HTTPError(req.full_url, code, text, {}, io.BytesIO(text.encode()))
    return _open


check("a 401 surfaces as 401",
      cli.send("https://x/notify", "t", {}, opener=_http_error(401, "unauthorized"))[0] == 401)
check("a 501 (no KV binding) surfaces as 501",
      cli.send("https://x/notify", "t", {}, opener=_http_error(501, "misconfigured"))[0] == 501)

print("\n7. the Worker route and the wiring")

_worker = open(os.path.join(_ROOT, "worker", "cubeon-downloads.js"), encoding="utf-8").read()
check("the Worker routes /notify", 'url.pathname === "/notify"' in _worker)
check("an unauthenticated POST is 401 before storage",
      'return new Response("unauthorized", { status: 401 })' in _worker
      and "NOTIFY_TOKEN" in _worker)
check("the Worker validates before storing",
      "headline and content are required" in _worker
      and "NOTIFY_MAX" in _worker)
_toml = open(os.path.join(_ROOT, "worker", "wrangler-downloads.toml"), encoding="utf-8").read()
check("the deploy config documents the KV binding + NOTIFY_TOKEN",
      "CUBEON_NOTIFY" in _toml and "NOTIFY_TOKEN" in _toml)
_main_src = open(os.path.join(_ROOT, "main.py"), encoding="utf-8").read()
check("main() polls for a notification after the seasonal greeting",
      "cubeon_notify.poll_async(" in _main_src
      and _main_src.find("SEASONAL GREETING") < _main_src.find("cubeon_notify.poll_async("),
      "the announcement must be wired into startup")
check("the poll is wrapped so a missed announcement cannot break startup",
      "pass  # a missed announcement must not break startup" in _main_src)
check(".notify_token is gitignored",
      ".notify_token" in open(os.path.join(_ROOT, ".gitignore"), encoding="utf-8").read())

print("\n8. the Worker suite (node)")

if shutil.which("node"):
    _proc = subprocess.run(["node", os.path.join("worker", "test-notify.mjs")],
                           cwd=_ROOT, capture_output=True, text=True)
    check("node worker/test-notify.mjs passes", _proc.returncode == 0,
          (_proc.stdout + _proc.stderr)[-400:])
else:
    print("  skip node not installed - worker/test-notify.mjs not run")

print(f"\n{passed} passed, {failed} failed")
if failed:
    print("Notify test: FAIL")
    sys.exit(1)
print("Notify test: PASS")
