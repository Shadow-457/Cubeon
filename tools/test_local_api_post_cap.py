"""An oversized POST body is refused with 413, never truncated into `{}` (10.7).

`do_POST` read `min(Content-Length, 16384)` bytes and left the rest unread. The
truncated JSON failed to parse, became `{}`, and the action silently did
nothing. A negative Content-Length also reached `read(-5)`, which reads until
EOF - an unbounded body.

Locked-in behaviour:
  * Content-Length above `_MAX_BODY_BYTES` -> 413
    `{"ok": false, "error": "message too large"}` and the body is not read;
  * exactly the cap is still accepted;
  * a missing/invalid/negative Content-Length is treated as 0, never a
    blocking/EOF read;
  * a normal small JSON body is still parsed and dispatched.

Run: python tools/test_local_api_post_cap.py
"""
import json
import os
import sys
from types import SimpleNamespace

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import local_api  # noqa: E402

passed = failed = 0

TOKEN = "tok"


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


class Headers:
    def __init__(self, length):
        self.length = length

    def get(self, name, default=None):
        if name.lower() == "content-length":
            return self.length
        if name == "X-Cubeon-Token":
            return TOKEN
        return default


class Body:
    def __init__(self, data):
        self.data = data
        self.calls = []

    def read(self, n=-1):
        self.calls.append(n)
        if n is None or n < 0:
            return self.data
        return self.data[:n]


class FakeHandler:
    _authorized = local_api._Handler._authorized
    _call = local_api._Handler._call

    def __init__(self, length, data=b""):
        self.headers = Headers(length)
        self.rfile = Body(data)
        self.server = SimpleNamespace(token=TOKEN)
        self.path = "/invite"
        self.responses = []

    def _json(self, obj, code=200):
        self.responses.append((code, obj))


def post(length, data=b"", path="/invite"):
    handler = FakeHandler(length, data)
    handler.path = path
    local_api._Handler.do_POST(handler)
    return handler


def main():
    received = []
    saved_invite = local_api._providers.get("invite")
    local_api._providers["invite"] = lambda name: (received.append(name)
                                                   or {"ok": True, "error": ""})
    try:
        # --- 1. over the cap: 413 and no body read ------------------------
        handler = post(local_api._MAX_BODY_BYTES + 1, b'{"name": "Alex"}')
        check("an oversized body is refused with 413",
              handler.responses and handler.responses[-1][0] == 413,
              str(handler.responses))
        check("the error says the message is too large",
              handler.responses[-1][1].get("error") == "message too large",
              str(handler.responses[-1]))
        check("the oversized body is not read at all",
              handler.rfile.calls == [], str(handler.rfile.calls))
        check("no provider ran for an oversized body", not received,
              str(received))

        # --- 2. exactly the cap is accepted -------------------------------
        data = b'{"name": "Alex"}'
        received.clear()
        handler = post(local_api._MAX_BODY_BYTES, data)
        check("a body exactly at the cap is accepted",
              handler.responses and handler.responses[-1][0] == 200,
              str(handler.responses))
        check("it is read with the declared length",
              handler.rfile.calls == [local_api._MAX_BODY_BYTES],
              str(handler.rfile.calls))
        check("the body was parsed and dispatched",
              received == ["Alex"], str(received))

        # --- 3. missing / invalid / negative lengths ----------------------
        for label, length in (("missing", None), ("invalid", "not-a-number"),
                              ("negative", "-5")):
            received.clear()
            handler = post(length, b'{"name": "Alex"}')
            check(f"a {label} Content-Length never reads more than 0 bytes",
                  handler.rfile.calls == [0], str(handler.rfile.calls))
            check(f"a {label} Content-Length still answers",
                  handler.responses and handler.responses[-1][0] == 200,
                  str(handler.responses))
            check(f"a {label} Content-Length is not parsed as a body",
                  received == [""], str(received))

        # --- 4. a normal small body still works ---------------------------
        received.clear()
        data = json.dumps({"name": "Steve"}).encode()
        handler = post(len(data), data)
        check("a normal body parses and dispatches",
              received == ["Steve"]
              and handler.rfile.calls == [len(data)], str(received))

        # --- 5. unauthorized is still answered first ----------------------
        handler = FakeHandler(local_api._MAX_BODY_BYTES + 1)
        handler.server = SimpleNamespace(token="different")
        local_api._Handler.do_POST(handler)
        check("an unauthorized oversized request gets 401",
              handler.responses and handler.responses[-1][0] == 401,
              str(handler.responses))
        check("and its body is not read",
              handler.rfile.calls == [], str(handler.rfile.calls))
    finally:
        if saved_invite is None:
            local_api._providers.pop("invite", None)
        else:
            local_api._providers["invite"] = saved_invite

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
