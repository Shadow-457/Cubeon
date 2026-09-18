import http.client
import json
import os
import runpy
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
sys.path.insert(0, os.path.join(ROOT, "tools"))

import _sandbox_home

_sandbox_home.isolate()


def main():
    fixtures = runpy.run_path(os.path.join(ROOT, "tools", "test_friends_service.py"),
                             run_name="bridge_gate_fixtures")
    service, _, _ = fixtures["build"]()
    api = fixtures["local_api"]
    received = []

    def receive(kind, value):
        received.append((kind, value))
        return {"ok": True, "error": ""}

    service.worldgate_set = lambda value: receive("host", value)
    service.join_password = lambda value: receive("join", value)
    service.start()
    server = api.start._server
    passed = 0

    def post(route, payload, token):
        conn = http.client.HTTPConnection("127.0.0.1", server.server_address[1], timeout=5)
        try:
            conn.request("POST", route, json.dumps(payload),
                         {"Content-Type": "application/json", "X-Cubeon-Token": token})
            response = conn.getresponse()
            return response.status, json.loads(response.read())
        finally:
            conn.close()

    try:
        for route in ("/worldgate", "/joinpassword"):
            assert post(route, {"password": "test-password"}, "wrong")[0] == 401
            assert not received
            passed += 1
        for route, payload, expected in (
                ("/worldgate", {"password": "test-password"}, ("host", "test-password")),
                ("/worldgate", {"skip": True}, ("host", None)),
                ("/joinpassword", {"password": "test-password"}, ("join", "test-password"))):
            code, result = post(route, payload, server.token)
            assert code == 200 and result["ok"]
            assert received[-1] == expected
            passed += 1
    finally:
        service.stop()
    print(f"{passed} passed, 0 failed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
