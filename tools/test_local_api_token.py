"""Only the launcher that owns the token file removes it (10.5).

`local_api.stop()` deleted `local_api.json` unconditionally. With two launcher
windows (or a fast restart) closing the first removed the second's token, so
its in-game mod lost the connection until a restart. `_authorized` also compared
the bearer token with `==`, which leaks prefix timing.

Locked-in behaviour:
  * `stop()` removes the token file only when its `"token"` equals this
    server's token; another launcher's file is left byte-intact;
  * the header is compared with `hmac.compare_digest` (spied on here), accepts
    the exact token, refuses a wrong/missing/non-ASCII one, and never raises.

Run: python tools/test_local_api_token.py
"""
import json
import os
import sys
import tempfile
from unittest.mock import patch

sys.path[:0] = [os.path.dirname(__file__),
                os.path.dirname(os.path.dirname(os.path.abspath(__file__)))]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import local_api  # noqa: E402

passed = failed = 0

TOKEN = "the-real-token"


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


class Headers:
    def __init__(self, value):
        self.value = value

    def get(self, name, default=None):
        if name == "X-Cubeon-Token":
            return self.value
        return default


class FakeServer:
    def __init__(self, token):
        self.token = token
        self.shut_down = False

    def shutdown(self):
        self.shut_down = True


def make_handler(header_value, token=TOKEN):
    handler = local_api._Handler.__new__(local_api._Handler)
    handler.headers = Headers(header_value)
    handler.server = FakeServer(token)
    return handler


def write_token_file(path, token):
    with open(path, "w", encoding="utf-8") as fh:
        json.dump({"port": 1234, "token": token}, fh)


def main():
    scratch = tempfile.mkdtemp(prefix="cubeon-localapi-")
    token_file = os.path.join(scratch, "local_api.json")
    local_api._TOKEN_FILE = token_file
    real_server = getattr(local_api.start, "_server", None)
    try:
        # --- 1. constant-time authorization -------------------------------
        handler = make_handler(TOKEN)
        spy_calls = []
        real_compare = local_api.hmac.compare_digest

        def spy(a, b):
            spy_calls.append((a, b))
            return real_compare(a, b)

        with patch.object(local_api.hmac, "compare_digest", spy):
            check("the exact token is authorized", handler._authorized())
        check("the header is compared in constant time",
              bool(spy_calls), "hmac.compare_digest was never called")

        check("a wrong token is refused",
              not make_handler("wrong")._authorized())
        check("a missing token is refused",
              not make_handler(None)._authorized())
        check("a non-ASCII token header is refused without raising",
              not make_handler("tökén")._authorized())

        # --- 2. stop() only removes its own token file --------------------
        local_api.start._server = FakeServer(TOKEN)
        write_token_file(token_file, "another-launcher-token")
        with open(token_file, "rb") as fh:
            foreign_before = fh.read()
        local_api.stop()
        check("stop() shut its server down",
              local_api.start._server is None)
        check("another launcher's token file is left alone",
              os.path.isfile(token_file), token_file)
        foreign_after = None
        if os.path.isfile(token_file):
            with open(token_file, "rb") as fh:
                foreign_after = fh.read()
        check("the foreign token file is byte-identical",
              foreign_after == foreign_before, repr(foreign_after))

        local_api.start._server = FakeServer(TOKEN)
        write_token_file(token_file, TOKEN)
        local_api.stop()
        check("its own token file is removed", not os.path.exists(token_file))

        local_api.start._server = FakeServer(TOKEN)
        ex = None
        try:
            local_api.stop()
        except Exception as e:  # noqa: BLE001 - the assertion is the point
            ex = e
        check("a missing token file does not raise", ex is None, repr(ex))

        local_api.start._server = FakeServer(TOKEN)
        with open(token_file, "wb") as fh:
            fh.write(b"{not json")
        ex = None
        try:
            local_api.stop()
        except Exception as e:  # noqa: BLE001
            ex = e
        check("a corrupt token file does not raise", ex is None, repr(ex))
        check("a corrupt token file is not deleted either",
              os.path.isfile(token_file), token_file)
    finally:
        local_api.start._server = real_server

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
