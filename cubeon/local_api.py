"""
Local bridge between the Cubeon launcher and the in-game "Cubeon Friends" mod.

The mod (see the mod/ project) adds a Friends button to Minecraft's own game
menu - and since the launcher no longer has a Friends tab, that button is now
the only Friends UI there is. The mod can't reach the friends backend directly
(that lives in the launcher's process), so the launcher exposes this tiny HTTP
API on 127.0.0.1 and the mod talks to it. The bridge is deliberately thin: it
only EXPOSES what cubeon/friends_service.py already knows (the roster, the P2P
session state, a queue of notifications) and FORWARDS what the player clicks
straight into that service. No backend logic lives here.

Auth: the server binds to 127.0.0.1 with a random port and a random token
written to ~/.cubeon_launcher/local_api.json (0600). The mod reads the same
file. Requests without the token are refused - other local processes (other
users) can't drive your friends list.

Everything is fail-safe: if this server can't start (port blocked, firewall),
the game simply doesn't show the Friends button - the launcher is unaffected.
"""

import json
import os
import secrets
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlsplit

from .paths import CUBEON_HOME  # ~/.cubeon_launcher

_TOKEN_FILE = os.path.join(CUBEON_HOME, "local_api.json")

# Handlers cubeon/friends_service.py registers on startup. Everything that takes
# a name takes the raw string the player typed; the service validates it and
# returns the error text, because the wording belongs with the rules.
#   roster_provider()   -> {"you", "connected", "available", "friends": [...],
#                           "requests_in": [...], "requests_out": [...]}
#   status_provider()   -> {"state","peer","error","is_host","quality",
#                           "can_retry"} or {} when there is no session
#   events_provider(since) -> {"cursor": int, "events": [{seq,text,error}, ...]}
#   invite_handler(name)   -> host a P2P world for that friend
#   join_handler(name)     -> accept their invite and join
#   cancel_handler()       -> end the active session
#   retry_handler()        -> retry a failed session
#   add/accept/decline/remove_handler(name), whitelist_handler(name, on),
#   rename_handler(name)   -> all {"ok": bool, "error": str}
#   dm_handler(to, text)   -> {"ok": bool, "error": str}. POST /dm - send an
#                             E2EE-encrypted DM; encrypts, so it can block.
#   chat_provider(friend, after) -> {"friend","you","messages":[...]}. GET
#                             /chat transcript polling.
#   sync_provider(friend)  -> the profile-compare report. GET /sync?friend=
#   syncstart/syncdownload/syncclose_handler(name), askjoin_handler(name)
_providers = {
    "roster": None,
    "invite": None,
    "status": None,
    "events": None,
    "cancel": None,
    "retry": None,
    "join": None,
    "add": None,
    "accept": None,
    "decline": None,
    "remove": None,
    "whitelist": None,
    "rename": None,
    "dm": None,
    "chat": None,
    "sync": None,
    "syncstart": None,
    "syncdownload": None,
    "syncclose": None,
    "askjoin": None,
}

# POST routes that take a single {"name": ...} and return a result dict. Keeping
# them in one table means adding a friend-scoped action is a one-line change and
# they can't drift apart in their error handling.
_NAME_ROUTES = ("add", "accept", "decline", "remove", "rename", "join",
                "syncstart", "syncdownload", "syncclose", "askjoin")

# POST routes that take no arguments at all.
_BARE_ROUTES = ("cancel", "retry")
def set_invite_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str}. Hosts a P2P world for a friend."""
    _providers["invite"] = fn


def set_join_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str}. Joins a friend's P2P world."""
    _providers["join"] = fn


def set_status_provider(fn) -> None:
    _providers["status"] = fn


def set_events_provider(fn) -> None:
    """fn(since:int) -> {"cursor": int, "events": [...]}. since<0 means "first
    sync, skip the backlog" - a mod that just started shouldn't replay old news."""
    _providers["events"] = fn


def set_cancel_handler(fn) -> None:
    _providers["cancel"] = fn


def set_retry_handler(fn) -> None:
    _providers["retry"] = fn


def set_roster_provider(fn) -> None:
    _providers["roster"] = fn


def set_add_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str|None}. Sends a friend request."""
    _providers["add"] = fn


def set_accept_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str|None}. Accepts a request."""
    _providers["accept"] = fn


def set_decline_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str|None}. Declines a request."""
    _providers["decline"] = fn


def set_remove_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str|None}. Unfriends someone."""
    _providers["remove"] = fn


def set_whitelist_handler(fn) -> None:
    """fn(name, on) -> {"ok": bool, "error": str|None}. Adds or removes a friend
    from the installed server's whitelist."""
    _providers["whitelist"] = fn


def set_rename_handler(fn) -> None:
    """fn(name) -> {"ok": bool, "error": str|None, "message": str}. Re-claims
    this machine's Cubeon name (rename). Blocking HTTP claim - run off UI threads."""
    _providers["rename"] = fn


def set_dm_handler(fn) -> None:
    """fn(to, text) -> {"ok": bool, "error": str}. Encrypts and sends one DM.
    Encrypting and the relay round-trip can block, so it must run off UI
    threads (as _call already does for every POST)."""
    _providers["dm"] = fn


def set_chat_provider(fn) -> None:
    """fn(friend, after) -> {"friend","you","messages":[{seq,dir,name,text,ts}]}.
    after=-1 means "most recent page"; after>=0 means "seq > after" ascending."""
    _providers["chat"] = fn


def set_sync_provider(fn) -> None:
    """fn(friend) -> the profile-compare report:
    {"friend","state","error","encrypted","you"{version,loader,mods},"them"{...},
     "version_ok","loader_ok","missing":[{sha256,filename,size}],"extra":[...],
     "can_download","download_done","download_total","needs_relaunch",
     "lines":[...]}. state is idle|asking|ready|downloading|error. Polled, so it
    must not block."""
    _providers["sync"] = fn


def set_sync_start_handler(fn) -> None:
    """fn(name) -> {"ok","error"}. Opens the compare channel to a friend."""
    _providers["syncstart"] = fn


def set_sync_download_handler(fn) -> None:
    """fn(name) -> {"ok","error"}. Pulls the mods this machine is missing."""
    _providers["syncdownload"] = fn


def set_sync_close_handler(fn) -> None:
    """fn(name) -> {"ok","error"}. Drops the compare room."""
    _providers["syncclose"] = fn


def set_askjoin_handler(fn) -> None:
    """fn(name) -> {"ok","error"}. Asks a friend to open their world to us."""
    _providers["askjoin"] = fn


def _write_token(port: int, token: str) -> None:
    os.makedirs(CUBEON_HOME, exist_ok=True)
    tmp = _TOKEN_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"port": port, "token": token}, f)
    os.replace(tmp, _TOKEN_FILE)
    try:
        os.chmod(_TOKEN_FILE, 0o600)
    except OSError:
        pass


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence the default stderr spam
        pass

    def _json(self, obj, code=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        return self.headers.get("X-Cubeon-Token") == self.server.token

    def do_GET(self):
        if not self._authorized():
            self._json({"error": "unauthorized"}, 401)
            return
        # /events carries a query string, so route on the path alone.
        parts = urlsplit(self.path)
        if parts.path == "/friends":
            fn = _providers["roster"]
            roster = fn() if fn else {}
            friends = [f for f in (roster.get("friends") or [])
                       if isinstance(f, dict) and f.get("name")]
            requests_in = [r for r in (roster.get("requests_in") or [])
                           if isinstance(r, str) and r]
            requests_out = [r for r in (roster.get("requests_out") or [])
                            if isinstance(r, str) and r]
            # connected/available default to True when the provider doesn't say,
            # matching the mod's own defaults: an older launcher that omits them
            # should read as "working", not as "signed out".
            self._json({"friends": friends,
                        "requests_in": requests_in,
                        "requests_out": requests_out,
                        "connected": bool(roster.get("connected", True)),
                        "available": bool(roster.get("available", True)),
                        "you": roster.get("you") or ""})
        elif parts.path == "/status":
            fn = _providers["status"]
            self._json(fn() if fn else {})
        elif parts.path == "/events":
            fn = _providers["events"]
            if not fn:
                self._json({"cursor": 0, "events": []})
                return
            # A missing or unparseable ?since= means "first sync": the provider
            # reads a negative cursor as "give me no backlog".
            try:
                since = int(parse_qs(parts.query).get("since", ["-1"])[0])
            except (TypeError, ValueError):
                since = -1
            try:
                self._json(fn(since))
            except Exception as ex:
                self._json({"cursor": since, "events": [], "error": str(ex)}, 500)
        elif parts.path == "/chat":
            fn = _providers["chat"]
            if not fn:
                self._json({"friend": "", "you": "", "messages": []})
                return
            query = parse_qs(parts.query)
            friend = str(query.get("friend", [""])[0] or "").strip()
            # Missing/unparseable ?after= means "first sync": the provider
            # reads -1 as "give me the most recent page" and seeds history.
            try:
                after = int(query.get("after", ["-1"])[0])
            except (TypeError, ValueError):
                after = -1
            try:
                self._json(fn(friend, after))
            except Exception as ex:
                self._json({"friend": friend, "you": "", "messages": [],
                            "error": str(ex)}, 500)
        elif parts.path == "/sync":
            fn = _providers["sync"]
            friend = str(parse_qs(parts.query).get("friend", [""])[0] or "").strip()
            if not fn:
                # An older launcher with a newer mod: say "idle" rather than 404
                # so the mod's poll loop treats it as "nothing open", not as a
                # dead bridge.
                self._json({"friend": friend, "state": "idle", "error": "",
                            "lines": [], "missing": [], "extra": []})
                return
            try:
                self._json(fn(friend))
            except Exception as ex:
                self._json({"friend": friend, "state": "error", "error": str(ex),
                            "lines": [str(ex)], "missing": [], "extra": []}, 500)
        else:
            self._json({"error": "not found"}, 404)

    def do_POST(self):
        if not self._authorized():
            self._json({"error": "unauthorized"}, 401)
            return
        try:
            # Generous cap: DM bodies carry a base64 E2EE envelope, which runs
            # ~1.4x the plaintext length. Still bounded, so a misbehaving mod
            # can't make the launcher buffer an unbounded request.
            length = min(int(self.headers.get("Content-Length") or 0), 16384)
            body = json.loads(self.rfile.read(length) or b"{}")
        except (ValueError, json.JSONDecodeError):
            body = {}
        if not isinstance(body, dict):
            body = {}
        route = urlsplit(self.path).path.lstrip("/")

        if route == "invite":
            # Kept separate from the table below: invite takes the name the
            # player picked from their own roster, so an empty one is the
            # service's error to word, not a 400.
            name = str(body.get("name") or "").strip()
            fn = _providers["invite"]
            if not fn:
                self._json({"ok": False, "error": "no invite handler"}, 503)
                return
            self._call(lambda: fn(name))
        elif route in _NAME_ROUTES:
            name = str(body.get("name") or "").strip()
            if not name:
                self._json({"ok": False, "error": "missing name"}, 400)
                return
            fn = _providers[route]
            if not fn:
                self._json({"ok": False, "error": "no handler"}, 503)
                return
            self._call(lambda: fn(name))
        elif route == "whitelist":
            name = str(body.get("name") or "").strip()
            if not name:
                self._json({"ok": False, "error": "missing name"}, 400)
                return
            fn = _providers["whitelist"]
            if not fn:
                self._json({"ok": False, "error": "no handler"}, 503)
                return
            on = bool(body.get("on"))
            self._call(lambda: fn(name, on))
        elif route == "dm":
            to = str(body.get("to") or "").strip()
            text = str(body.get("text") or "").strip()
            if not to or not text:
                self._json({"ok": False, "error": "missing to or text"}, 400)
                return
            fn = _providers["dm"]
            if not fn:
                self._json({"ok": False, "error": "no handler"}, 503)
                return
            self._call(lambda: fn(to, text))
        elif route in _BARE_ROUTES:
            fn = _providers[route]
            if not fn:
                # Nothing to cancel is not a failure; nothing to retry is.
                self._json({"ok": route == "cancel",
                            "error": "" if route == "cancel" else "no handler"})
                return
            self._call(fn)
        else:
            self._json({"error": "not found"}, 404)

    def _call(self, thunk):
        """Run a handler and answer with its result dict.

        Handlers are trusted to be quick - they hand slow work to a worker
        thread - but never to be exception-free: an unhandled one here would
        otherwise close the socket with no body and the mod would report
        "launcher not responding" for what is really one failed action.
        """
        try:
            result = thunk()
        except Exception as ex:
            self._json({"ok": False, "error": str(ex)}, 500)
            return
        if isinstance(result, dict):
            self._json(result)
        else:
            self._json({"ok": bool(result) or result is None, "error": ""})


class _Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True


def start() -> bool:
    """Starts the bridge on a random 127.0.0.1 port and writes the token file
    the mod reads. Returns True if it's up (or already up)."""
    if getattr(start, "_server", None) is not None:
        return True
    try:
        server = _Server(("127.0.0.1", 0), _Handler)
        token = secrets.token_urlsafe(24)
        server.token = token
        thread = threading.Thread(target=server.serve_forever, daemon=True,
                                  name="cubeon-local-api")
        thread.start()
        _write_token(server.server_address[1], token)
        start._server = server
        return True
    except Exception:
        return False


def stop() -> None:
    server = getattr(start, "_server", None)
    if server is not None:
        try:
            server.shutdown()
        except Exception:
            pass
        start._server = None
        try:
            os.remove(_TOKEN_FILE)
        except OSError:
            pass
