"""Disconnected bridge clients must not trigger a warning or a second reply.

Run: python tools/test_local_api_disconnect.py
"""
import http.client
import io
import json
import os
import socket
import struct
import sys
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path[:0] = [os.path.dirname(__file__), ROOT]
import _sandbox_home

_sandbox_home.isolate()

from cubeon import local_api


class FailingWriter:
    def __init__(self, failure, fail_at):
        self.failure = failure
        self.fail_at = fail_at
        self.writes = []

    def write(self, data):
        self.writes.append(data)
        if len(self.writes) == self.fail_at:
            raise self.failure
        return len(data)


class Handler(local_api._Handler):
    """Exercise real header/body serialization without opening a socket."""
    def __init__(self, writer, method="GET", path="/cape", token="token"):
        self.wfile = writer
        self.rfile = io.BytesIO(b"{}")
        self.server = SimpleNamespace(token="token")
        self.command = method
        self.path = path
        self.requestline = f"{method} {path} HTTP/1.1"
        self.request_version = "HTTP/1.1"
        self.headers = {"X-Cubeon-Token": token, "Content-Length": "2"}
        self.close_connection = False
        self.codes = []

    def send_response(self, code, message=None):
        self.codes.append(code)
        super().send_response(code, message)


class DisconnectTests(unittest.TestCase):
    def setUp(self):
        self.providers = patch.dict(local_api._providers,
                                    {key: None for key in local_api._providers})
        self.providers.start()
        self.addCleanup(self.providers.stop)

    def test_response_disconnects_stop_after_one_attempt(self):
        # Both headers and body can fail, including on early/error responses.
        for failure in (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            for fail_at in (1, 2):
                for method, path, token, code in (
                        ("GET", "/cape", "token", 200),
                        ("GET", "/cape", "wrong", 401),
                        ("POST", "/cancel", "token", 200),
                        ("POST", "/cancel", "wrong", 401),
                        ("GET", "/missing", "token", 404)):
                    with self.subTest(failure=failure.__name__, fail_at=fail_at,
                                      method=method, code=code):
                        writer = FailingWriter(failure("client left"), fail_at)
                        handler = Handler(writer, method, path, token)
                        with patch.object(local_api, "log") as log:
                            getattr(handler, f"do_{method}")()
                        self.assertEqual(handler.codes, [code])
                        self.assertEqual(len(writer.writes), fail_at)
                        self.assertTrue(handler.close_connection)
                        log.warning.assert_not_called()

    def test_provider_failure_remains_a_logged_500(self):
        # Even a provider's own BrokenPipeError is a backend failure: only
        # socket writes belong to the quiet disconnect path.
        for failure in (RuntimeError, BrokenPipeError):
            with self.subTest(failure=failure.__name__):
                def bad_provider(game_dir):
                    raise failure("cape provider failed")

                local_api.set_cape_provider(bad_provider)
                handler = Handler(io.BytesIO())
                with patch.object(local_api, "log") as log:
                    handler.do_GET()
                self.assertEqual(handler.codes, [500])
                self.assertEqual(json.loads(handler.wfile.getvalue().split(b"\r\n\r\n")[1]),
                                 {"error": "cape provider failed"})
                log.warning.assert_called_once()

    def test_serialization_failure_still_answers_500(self):
        local_api.set_cape_provider(lambda game_dir: {"bad": object()})
        handler = Handler(io.BytesIO())
        with patch.object(local_api, "log") as log:
            handler.do_GET()
        self.assertEqual(handler.codes, [500])
        log.warning.assert_called_once()

    def test_unrelated_output_error_is_not_suppressed(self):
        handler = Handler(FailingWriter(OSError("unexpected write failure"), 1))
        with patch.object(local_api, "log") as log:
            handler.do_GET()
        self.assertEqual(handler.codes, [200, 500])
        log.warning.assert_called_once()

    def test_completed_post_is_not_repeated_after_disconnect(self):
        calls = []
        local_api.set_cancel_handler(lambda: calls.append("cancel") or {"ok": True})
        handler = Handler(FailingWriter(BrokenPipeError(), 2), "POST", "/cancel")
        handler.do_POST()
        self.assertEqual(calls, ["cancel"])
        self.assertEqual(handler.codes, [200])

    def test_real_client_disconnect_and_next_request(self):
        entered, release, finished = (threading.Event() for _ in range(3))
        codes = []

        def slow_cape(game_dir):
            entered.set()
            if not release.wait(5):
                raise RuntimeError("test did not release cape provider")
            return {"ok": True, "enabled": False}

        class TrackedHandler(local_api._Handler):
            def do_GET(self):
                try:
                    super().do_GET()
                finally:
                    if self.path == "/cape":
                        finished.set()

            def send_response(self, code, message=None):
                codes.append(code)
                super().send_response(code, message)

        local_api.set_cape_provider(slow_cape)
        with local_api._Server(("127.0.0.1", 0), TrackedHandler) as server:
            server.token = "token"
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            client = socket.create_connection(server.server_address, timeout=5)
            try:
                with patch.object(local_api, "log") as log, \
                        patch.object(server, "handle_error") as server_error:
                    client.sendall(b"GET /cape HTTP/1.0\r\nX-Cubeon-Token: token\r\n\r\n")
                    self.assertTrue(entered.wait(5))
                    # Send RST before allowing the response; no timing sleeps.
                    linger = struct.pack("HH" if os.name == "nt" else "ii", 1, 0)
                    client.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, linger)
                    client.close()
                    release.set()
                    self.assertTrue(finished.wait(5))
                    self.assertEqual(codes, [200])
                    log.debug.assert_called_once()
                    log.warning.assert_not_called()
                    server_error.assert_not_called()

                    conn = http.client.HTTPConnection(*server.server_address, timeout=5)
                    try:
                        conn.request("GET", "/status", headers={"X-Cubeon-Token": "token"})
                        reply = conn.getresponse()
                        self.assertEqual(reply.status, 200)
                        self.assertEqual(json.loads(reply.read()), {})
                    finally:
                        conn.close()
            finally:
                client.close()
                release.set()
                server.shutdown()
                worker.join(5)


if __name__ == "__main__":
    unittest.main(verbosity=2)
