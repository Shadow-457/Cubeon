"""A failing provider must not look like "the launcher isn't running" (10.1).

`local_api._Handler.do_GET` called providers such as the friends roster
directly. If one raised, the request handler thread died before writing a
response, the socket closed with no body, and the in-game mod showed
"Cubeon launcher isn't running" although the launcher was up.

Locked-in behaviour:
  * GET /friends with a raising roster provider answers 500 + a JSON error;
  * GET /status with a raising status provider answers 500 + a JSON error;
  * the server survives both (a later normal request still answers);
  * unauthenticated requests still get 401 and never touch the provider.

Run: python tools/test_local_api_provider_error.py
"""
import http.client
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _sandbox_home

_sandbox_home.isolate()

from cubeon import local_api  # noqa: E402

passed = failed = 0


def check(label, condition, extra=""):
    global passed, failed
    passed += bool(condition)
    failed += not condition
    print(f"  {'ok' if condition else 'FAIL'} {label}"
          f"{(' - ' + extra) if extra and not condition else ''}")


def main():
    calls = {"roster": 0, "status": 0}

    def bad_roster():
        calls["roster"] += 1
        raise RuntimeError("roster backend blew up")

    def bad_status():
        calls["status"] += 1
        raise RuntimeError("status backend blew up")

    local_api.set_roster_provider(bad_roster)
    local_api.set_status_provider(bad_status)
    local_api.set_players_provider(lambda: {"players": []})

    if not local_api.start():
        print("  SKIP could not bind a local port in this environment")
        return 0
    server = local_api.start._server

    def get(route, token):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1],
                                          timeout=5)
        try:
            conn.request("GET", route, headers={"X-Cubeon-Token": token})
            response = conn.getresponse()
            body = response.read()
            return response.status, (json.loads(body) if body else None)
        finally:
            conn.close()

    try:
        # Unauthenticated: refused, provider untouched.
        code, _ = get("/friends", "wrong-token")
        check("a request without the token is still refused", code == 401, str(code))
        check("the provider was not called without a token",
              calls["roster"] == 0, str(calls["roster"]))

        # A raising roster provider: 500 with a real body, not a dead socket.
        code, body = get("/friends", server.token)
        check("GET /friends answers 500 when the provider raises", code == 500,
              str(code))
        check("the failure is described in the body",
              isinstance(body, dict) and "roster backend blew up"
              in str(body.get("error")), str(body))
        check("the roster provider really ran", calls["roster"] == 1,
              str(calls["roster"]))

        # Same for /status.
        code, body = get("/status", server.token)
        check("GET /status answers 500 when the provider raises", code == 500,
              str(code))
        check("the status failure is described in the body",
              isinstance(body, dict) and "status backend blew up"
              in str(body.get("error")), str(body))

        # The server is still alive and serving normal routes.
        code, body = get("/players", server.token)
        check("the server survives the failed requests", code == 200, str(code))
        check("a normal route still answers", body == {"players": []}, str(body))
    finally:
        local_api.stop()
        local_api.set_roster_provider(None)
        local_api.set_status_provider(None)
        local_api.set_players_provider(None)

    print()
    print(f"{passed} passed, {failed} failed")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
