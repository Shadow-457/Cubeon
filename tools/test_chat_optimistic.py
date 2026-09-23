"""Guard for the Chat tab's optimistic-send bookkeeping (ui/chat_tab.py).

The bug this locks down: one message could render as TWO bubbles. The send
path shows an optimistic "Sending…" bubble; if the relay's echo took longer
than the 12s sweep, that bubble turned red "Couldn't send" and the real line
was then appended as a second bubble for the same message. The same slow
confirmation also made chat feel laggy (a fixed 1.5s poll even while the user
sat staring at an open conversation).

Checks:
  - the relay echo replaces the optimistic bubble (no dupe) in the normal path,
  - a LATE echo replaces the red timeout bubble in place (the regression),
  - identical texts sent twice still show twice (dedupe must not eat them),
  - the poll cadence is adaptive and the pending queue is bounded.

Headless: no display, no network, no flet runtime. The tab's own poll thread
is suppressed so every step is synchronous.
"""
import os
import sys
import threading
import time
import types

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, REPO)
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _sandbox_home  # noqa: E402
_sandbox_home.isolate()

import flet as ft  # noqa: E402
from cubeon.theme import THEME, section_label  # noqa: E402
import ui.chat_tab as chat  # noqa: E402

_CHECKS = []


def check(label, ok, detail=""):
    _CHECKS.append(bool(ok))
    print(f"  {'ok ' if ok else 'FAIL'}  {label}" + (f"  ({detail})" if detail else ""))


class FakeWindow:
    def close(self):
        pass


class FakePage:
    def __init__(self):
        self.window = FakeWindow()
        self.overlay = []
        self.controls = []
        self.width = 1200
        self.update_calls = 0
        self.opened = []

    def update(self, *a):
        self.update_calls += 1

    def add(self, *a):
        self.controls.extend(a)

    def run_task(self, fn, *a, **k):
        try:
            res = fn(*a, **k)
            if hasattr(res, "close"):
                res.close()   # keep the fake synchronous; never await
        except Exception:
            pass


class FakeService:
    """FriendsService's chat surface with a scripted ring."""

    def __init__(self):
        self.ring = []
        self.next_seq = 0
        self.sent = []

    def roster_payload(self):
        return {"friends": [{"name": "alice", "minecraft_username": "Alice",
                             "online": True}],
                "requests_in": [], "requests_out": [],
                "requests_in_details": [], "requests_out_details": [],
                "connected": True, "available": True,
                "you_minecraft_username": "Steve"}

    def events_since(self, cursor):
        return {"events": [], "cursor": 0}

    def peer_metadata(self, name):
        return {"minecraft_username": "Alice"}

    def chat_payload(self, friend, after):
        msgs = ([m for m in self.ring if m["seq"] > after] if after >= 0
                else self.ring[-50:])
        return {"friend": friend, "you": "Steve",
                "messages": [dict(m) for m in msgs]}

    def mark_read(self, friend):
        return {}

    def send_chat(self, to, text):
        self.sent.append((to, text))
        return {"ok": True, "error": ""}

    def echo(self, text):
        """The relay's echo landing in the ring (what the next poll sees)."""
        self.ring.append({"seq": self.next_seq, "dir": "out", "name": "Steve",
                          "text": text, "ts": int(time.time() * 1000)})
        self.next_seq += 1


def walk(c):
    seen, out, stack = set(), [], [c]
    while stack:
        x = stack.pop()
        if x is None or id(x) in seen:
            continue
        seen.add(id(x))
        out.append(x)
        for attr in ("controls", "content"):
            v = getattr(x, attr, None)
            if isinstance(v, (list, tuple)):
                stack.extend([i for i in v if i is not None])
            elif v is not None:
                stack.append(v)
    return out


def texts(root, needle=None):
    """Every string a control carries (Text values and other .value fields)."""
    hits = []
    for c in walk(root):
        v = getattr(c, "value", None)
        if isinstance(v, str) and (needle is None or v == needle):
            hits.append(v)
    return hits


class _ShiftedTime:
    """A `time` shim running 60s ahead, so the 12s pending sweep fires
    deterministically instead of the test sleeping for it."""

    def __init__(self, real, offset):
        self._real = real
        self._offset = offset

    def __getattr__(self, k):
        return getattr(self._real, k)

    def monotonic(self):
        return self._real.monotonic() + self._offset


def main():
    print("chat optimistic-send bookkeeping")

    svc = FakeService()
    page = FakePage()
    real_start = threading.Thread.start
    threading.Thread.start = lambda self: None  # no background poller
    try:
        root, refresh = chat.build_chat_tab(
            page, {"username": "Steve"}, {"selected_version": "1.21.1"},
            svc, section_label=section_label,
            **{k: v for k, v in THEME.items()})
    finally:
        threading.Thread.start = real_start
    page.controls.append(root)
    refresh()

    # open the conversation: the innermost clickable row mentioning Alice
    row = None
    for c in walk(root):
        if callable(getattr(c, "on_click", None)) and "alice" in " ".join(
                texts(c)).lower():
            row = c if row is None or len(walk(c)) < len(walk(row)) else row
    check("the roster row for a friend is clickable", row is not None)
    row.on_click(types.SimpleNamespace(control=row))
    refresh()

    composer = [c for c in walk(root) if isinstance(c, ft.TextField)][0]
    send = None
    for c in walk(root):
        inner = getattr(c, "content", None)
        if (isinstance(inner, ft.Icon)
                and getattr(inner, "icon", None) == ft.Icons.SEND_ROUNDED):
            send = c
    check("the send button is wired", send is not None)

    def send_text(text):
        composer.value = text
        send.on_click(types.SimpleNamespace(control=send))
        time.sleep(0.25)   # let the send worker release tick_lock
        refresh()

    # --- normal path: echo replaces the optimistic bubble -----------------
    send_text("hello")
    check("the optimistic bubble shows immediately",
          texts(root, "hello") == ["hello"], str(texts(root, "hello")))
    svc.echo("hello")
    refresh()
    check("the echo replaces it - exactly one bubble",
          texts(root, "hello") == ["hello"], str(texts(root, "hello")))
    check("no red bubble for a confirmed send",
          not [t for t in texts(root) if "Could" in t])

    # --- late echo: the red timeout bubble is replaced in place ----------
    send_text("late one")
    real_time = chat.time
    chat.time = _ShiftedTime(real_time, 60.0)
    try:
        refresh()   # the sweep fires: 60s on, the 12s deadline is long past
        check("an unconfirmed bubble goes red after the timeout",
              bool([t for t in texts(root) if "Could" in t]),
              str([t for t in texts(root) if "Could" in t]))
        svc.echo("late one")
        refresh()   # the real line arrives late
    finally:
        chat.time = real_time
    check("a LATE echo replaces the red bubble, never duplicates it",
          texts(root, "late one") == ["late one"],
          f"{texts(root, 'late one')} (2 = the dupe bug)")

    # --- identical texts are still two messages --------------------------
    send_text("gg")
    send_text("gg")
    svc.echo("gg")
    svc.echo("gg")
    refresh()
    check("two identical sends still show two bubbles",
          texts(root, "gg") == ["gg", "gg"], str(texts(root, "gg")))

    # --- cadence + bounded queue ----------------------------------------
    check("idle cadence stays the relaxed 1.5s",
          chat._POLL_SECONDS >= 1.0, str(chat._POLL_SECONDS))
    check("an open conversation polls at half a second",
          chat._POLL_ACTIVE_SECONDS <= 0.5, str(chat._POLL_ACTIVE_SECONDS))
    check("a fresh send polls fast for a short window",
          chat._POLL_FAST_SECONDS < chat._POLL_ACTIVE_SECONDS
          and chat._CONFIRM_WINDOW_S <= 3.0,
          f"{chat._POLL_FAST_SECONDS}s / window {chat._CONFIRM_WINDOW_S}s")
    check("the pending queue is bounded",
          isinstance(chat._MAX_PENDING, int) and 0 < chat._MAX_PENDING <= 128,
          str(chat._MAX_PENDING))

    print()
    total, failed = len(_CHECKS), _CHECKS.count(False)
    print(f"{total - failed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())

